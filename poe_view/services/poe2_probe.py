"""Rohdaten-Abzug der PoE2-Endpunkte (docs/ARCHITEKTUR.md §4.43).

GGGs Referenz beschreibt einen ``realm``-Query-Parameter, der die Spiele
unterscheidet — kein eigener Pfad, kein eigener OAuth-Scope. Gelesen am
2026-08-15 (https://www.pathofexile.com/developer/docs/reference):

- ``/account/leagues``  — ``realm`` erlaubt ``pc``, ``xbox``, ``sony``, ``poe2``
- ``/character``        — ``realm`` erlaubt ``xbox``, ``sony``, ``poe2``
- ``/stash/...``        — ``realm`` erlaubt nur ``xbox`` oder ``sony``

**Gemessen am 2026-08-15 stimmt das nicht.** Mit Peters Token liefern
alle vier Varianten (ohne Realm, ``poe2``, ``xbox``, ein frei erfundener
Wert) bytegleiche Antworten — gleiche Prüfsumme, 50 PoE1-Charaktere,
Feld ``realm`` überall ``pc``. GGG lehnt den Wert also nicht ab, sondern
wertet den Parameter gar nicht aus.

Deshalb fragt der Abzug nicht nur nach ``poe2``, sondern immer auch ohne
Realm und mit einem absichtlich ungültigen Wert. Erst der Vergleich der
drei Antworten trennt "PoE2 ist leer" von "der Parameter wirkt nicht" —
ohne die Kontrollabrufe sähe ein Abzug voller PoE1-Daten wie eine
erfolgreiche PoE2-Abfrage aus.

Dieses Modul stellt die Aufbereitung: Der Abruf liegt im ApiWorker
(``_poe2_probe``), die Anzeige im RawDataViewer. Hier steht, was
Qt-frei und ohne Netz prüfbar ist.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from poe_view import __version__, config

REALM = "poe2"

# Ein Wert, den es bei GGG nicht gibt und auch nie geben wird. Antwortet
# er wie ein gueltiger, wertet der Endpunkt den Parameter nicht aus.
INVALID_REALM = "zznotarealm"

# Rollen der einzelnen Abrufe. Der Vergleich haengt an diesen Marken und
# nicht am Beschriftungstext — der ist fuer Menschen da.
PLAIN = "plain"        # derselbe Endpunkt ohne Realm (Kontrolle)
POE2 = "poe2"          # die eigentliche Frage
INVALID = "invalid"    # erfundener Realm (Kontrolle)
LEAGUES = "leagues"
DETAIL = "detail"


@dataclass
class ProbeCall:
    """Ergebnis genau eines Abrufs.

    Fehlschläge werden mitgeführt statt geworfen: Ob ein Endpunkt für
    PoE2 überhaupt antwortet, ist die eigentliche Frage dieses Abzugs —
    ein 403 oder 400 ist hier ein Messergebnis, kein Abbruchgrund.
    """

    label: str
    ok: bool
    data: object = None
    error: str = ""
    digest: str = ""
    role: str = ""


@dataclass
class Probe:
    calls: list[ProbeCall] = field(default_factory=list)
    fetched_at: float = 0.0


def digest_of(data: object) -> str:
    """Prüfsumme über die Antwort, unabhängig von der Schlüsselreihenfolge.

    Zwei Antworten zu vergleichen ist der ganze Trick dieses Abzugs; ein
    Hash macht das im Text nachvollziehbar, ohne zwei riesige JSON-Blöcke
    nebeneinanderlegen zu müssen."""
    roh = json.dumps(data, sort_keys=True, ensure_ascii=False,
                     default=str).encode("utf-8")
    return hashlib.sha256(roh).hexdigest()


def _by_role(calls: list[ProbeCall], role: str) -> ProbeCall | None:
    for call in calls:
        if call.role == role:
            return call
    return None


def realm_had_effect(calls: list[ProbeCall]) -> bool:
    """Hat ``realm=poe2`` die Antwort überhaupt verändert?

    Fehlt eine der beiden Antworten, gilt das als "verändert" — dann ist
    der Unterschied ein Fehlschlag auf einer Seite, und den will man
    sehen statt wegzuoptimieren."""
    plain = _by_role(calls, PLAIN)
    poe2 = _by_role(calls, POE2)
    if plain is None or poe2 is None:
        return True
    if not (plain.ok and poe2.ok):
        return True
    return plain.digest != poe2.digest


def verdict(calls: list[ProbeCall]) -> list[str]:
    """Die Antwort auf Peters Frage in Klartext, vor den Rohdaten."""
    plain = _by_role(calls, PLAIN)
    poe2 = _by_role(calls, POE2)
    invalid = _by_role(calls, INVALID)
    if plain is None or poe2 is None:
        return ["No comparison was made."]
    if not plain.ok or not poe2.ok:
        return ["The two character requests did not both succeed — compare "
                "them by hand below."]

    zeilen = [f"  {'without realm':<22} sha256 {plain.digest[:16]}",
              f"  {'realm=' + REALM:<22} sha256 {poe2.digest[:16]}"]
    if invalid is not None and invalid.ok:
        zeilen.append(
            f"  {'realm=' + INVALID_REALM:<22} sha256 {invalid.digest[:16]}")

    if plain.digest != poe2.digest:
        return ["The realm parameter changed the answer — the PoE2 data "
                "below is real.", ""] + zeilen

    kopf = ["The realm parameter had no effect: asking for PoE2 returned "
            "exactly the same",
            "bytes as asking for nothing. Everything below is Path of "
            "Exile 1 data.", ""]
    if invalid is not None and invalid.ok and invalid.digest == plain.digest:
        schluss = ["",
                   "An invented realm returns those same bytes too, so GGG "
                   "is not rejecting the",
                   "value — it ignores the parameter. This endpoint cannot "
                   "answer the PoE2",
                   "question at all, whether or not the account has PoE2 "
                   "characters."]
    else:
        schluss = ["",
                   "The invalid-realm control did not come back, so it is "
                   "open whether GGG",
                   "ignores the parameter or the account simply has no PoE2 "
                   "data."]
    return kopf + zeilen + schluss


def character_names(calls: list[ProbeCall]) -> list[str]:
    """Charakternamen aus der PoE2-Antwort, soweit eine zurückkam.

    Bewusst über die Antwortstruktur statt über das ``Character``-Modell:
    Das Modell ist an PoE1 gemessen, und ob PoE2 dieselben Felder liefert,
    ist gerade die offene Frage."""
    call = _by_role(calls, POE2)
    if call is None or not call.ok or not isinstance(call.data, dict):
        return []
    characters = call.data.get("characters")
    if not isinstance(characters, list):
        return []
    return [c["name"] for c in characters
            if isinstance(c, dict) and c.get("name")]


def report_path() -> Path:
    """Ablageort des Abzugs, bei jedem Aufruf neu aus ``config`` gebildet.

    Als Funktion und nicht als Modul-Konstante: Eine beim Import
    eingefrorene, aus ``config.APP_DATA_DIR`` abgeleitete Konstante wäre
    vom Testschutz in ``tests/conftest.py`` nicht mehr erreichbar und
    schriebe in den echten Profilordner (dieselbe Falle wie bei
    ``cache_backup`` und ``LOG_DIR``)."""
    return config.APP_DATA_DIR / "poe2-probe.txt"


def save_report(text: str) -> Path:
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def build_report(probe: Probe) -> str:
    """Der vollständige Abzug als Text — dasselbe, was das Fenster zeigt
    und was in der Datei landet. Eine Quelle, damit beide nicht
    auseinanderlaufen."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(probe.fetched_at))
    lines = [
        f"PoE-VIEW2 {__version__} — raw PoE2 API probe",
        f"Fetched: {stamp} (local time)",
        "",
        "This dump contains your account name and your character names.",
        "Look before you share it.",
        "",
        "-" * 72,
        "VERDICT",
        "-" * 72,
    ]
    lines.extend(verdict(probe.calls))
    lines.append("")
    # Bytegleiche Antworten nur EINMAL ausschreiben. Der gemessene Fall
    # liefert dreimal dieselbe 50-Charakter-Liste; dreimal abgedruckt
    # verdeckt sie das Wenige, was sich tatsächlich unterscheidet — und
    # das Unterscheiden ist der Zweck dieses Abzugs.
    gesehen: dict[str, str] = {}
    for call in probe.calls:
        lines.append("=" * 72)
        lines.append(call.label)
        lines.append("=" * 72)
        if not call.ok:
            lines.append(f"FAILED — {call.error}")
        elif call.digest in gesehen:
            lines.append(f"sha256 {call.digest}")
            lines.append(f"Byte-identical to \"{gesehen[call.digest]}\" — "
                         "not repeated here.")
        else:
            if call.digest:
                gesehen[call.digest] = call.label
                lines.append(f"sha256 {call.digest}")
            lines.append(json.dumps(call.data, indent=2, ensure_ascii=False,
                                    default=str))
        lines.append("")
    lines.append("=" * 72)
    lines.append(
        "Not asked for: the stash endpoints. GGG's reference lists only "
        "xbox and sony\nas realm values there, so PoE2 stash tabs are not "
        "reachable through the API\nat all — see docs/ARCHITEKTUR.md §4.43."
    )
    return "\n".join(lines)
