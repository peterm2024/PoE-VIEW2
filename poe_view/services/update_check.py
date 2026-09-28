"""Gibt es ein neueres Release auf GitHub? (§4.57)

Anlass (Peter, 2026-09-28): "Haben wir eigentlich eine
Aktualisierungsbenachrichtigung bei neuen Versionen?" — nein, und die
Download-Zahlen zeigen, was das heißt: Wer einmal v0.12.0 geladen hat,
erfährt von v0.17.0 nur, wenn er zufällig im Forum oder auf GitHub
vorbeischaut.

**Nur ein Hinweis, kein Auto-Update.** Das Programm lädt nichts herunter
und ersetzt nichts; es zeigt in der Statusleiste einen Link auf die
Release-Seite, geklickt wird selbst. Das passt zu "It only reads", und
eine unsignierte .exe, die sich selbst austauscht, wäre genau das, was
ein vorsichtiger Nutzer einem Fremdwerkzeug nicht zutrauen sollte.

**Einmal pro Start, das Ergebnis sechs Stunden vorgehalten.** GitHub
erlaubt ohne Anmeldung 60 Anfragen pro Stunde und IP; wer das Programm
oft neu startet, soll davon nicht mehr als eine verbrauchen. Ein
gescheiterter Abruf wird NICHT vorgehalten — ohne Netz oder bei einem
GitHub-Aussetzer erscheint einfach nichts, und der nächste Start fragt
erneut.

**Nur in der .exe** (die Entscheidung trifft der Aufrufer über
``config.RUNNING_AS_EXE``): Wer aus dem Quellcode startet, hat Git.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from poe_view import __version__, config
from poe_view.services import atomic_json

log = logging.getLogger(__name__)

LATEST_URL = "https://api.github.com/repos/peterm2024/PoE-VIEW2/releases/latest"

TTL_SECONDS = 6 * 3600

# Kurz, weil der Abruf im EINEN Worker-Thread läuft (§4.5): Solange er
# wartet, wartet auch jeder GGG-Abruf dahinter. GitHub antwortet
# gewöhnlich in unter einer Sekunde; wer zehn braucht, ist gestört, und
# dann ist "kein Hinweis" die richtige Antwort.
TIMEOUT_SECONDS = 10.0

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _cache_path() -> Path:
    """Als Funktion statt Modul-Konstante — die Test-Fixture biegt
    ``config.APP_DATA_DIR`` erst nach dem Import um (FALLSTRICKE, dieselbe
    Falle wie bei ``cache_backup.BACKUP_DIR``)."""
    return config.APP_DATA_DIR / "update-check.json"


@dataclass(frozen=True)
class Release:
    version: str   # so, wie GitHub den Tag führt, z. B. "v0.18.0"
    url: str       # die Release-Seite, nicht die .exe


def parse_version(text: str) -> tuple[int, int, int] | None:
    """``"v0.17.0"``, ``"0.17.0"`` und ``"0.17.0+dev"`` → ``(0, 17, 0)``.

    Der Zusatz nach der dritten Zahl fällt weg: Zwischen zwei Releases
    trägt das Programm ``X.Y.Z+dev`` (RELEASING §4), und das ist NICHT
    älter als ``X.Y.Z`` — sonst meldete jeder Entwicklerstand das Release,
    aus dem er gerade entstanden ist."""
    treffer = _VERSION.match(text.strip())
    if treffer is None:
        return None
    return int(treffer[1]), int(treffer[2]), int(treffer[3])


def is_newer(latest: str, current: str) -> bool:
    neu, jetzt = parse_version(latest), parse_version(current)
    # Eine unlesbare Nummer auf einer der beiden Seiten ist kein Grund zu
    # melden — lieber ein verpasster Hinweis als ein falscher.
    return neu is not None and jetzt is not None and neu > jetzt


def _load_cached(now: float) -> Release | None:
    try:
        daten = json.loads(_cache_path().read_text(encoding="utf-8"))
        if now - float(daten["checked_at"]) > TTL_SECONDS:
            return None
        return Release(str(daten["version"]), str(daten["url"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _fetch(http: httpx.Client) -> Release | None:
    try:
        antwort = http.get(LATEST_URL, timeout=TIMEOUT_SECONDS,
                           headers={"Accept": "application/vnd.github+json"})
        antwort.raise_for_status()
        daten = antwort.json()
        return Release(str(daten["tag_name"]), str(daten["html_url"]))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as fehler:
        log.info("Update-Pruefung: kein Ergebnis (%s)", fehler)
        return None


def latest_release(http: httpx.Client, now: float | None = None) -> Release | None:
    """Das neueste veröffentlichte Release — aus dem Vorrat, solange der
    jünger als ``TTL_SECONDS`` ist, sonst von GitHub. ``/releases/latest``
    lässt Entwürfe und Vorab-Releases von sich aus weg."""
    now = time.time() if now is None else now
    vorrat = _load_cached(now)
    if vorrat is not None:
        return vorrat
    release = _fetch(http)
    if release is not None:
        try:
            _cache_path().parent.mkdir(parents=True, exist_ok=True)
            atomic_json.write_json(_cache_path(), {
                "checked_at": now, "version": release.version, "url": release.url})
        except OSError as fehler:
            log.info("Update-Pruefung: Vorrat nicht geschrieben (%s)", fehler)
    return release


def check(http: httpx.Client, current: str = __version__,
          now: float | None = None) -> Release | None:
    """Das neuere Release, oder ``None``, wenn es keins gibt oder die Frage
    sich nicht beantworten ließ."""
    release = latest_release(http, now)
    if release is None or not is_newer(release.version, current):
        return None
    log.info("Update-Pruefung: %s verfuegbar (laufend %s)", release.version, current)
    return release
