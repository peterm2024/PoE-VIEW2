"""Persistenter Datei-Cache: Charaktere/Stash/Items überleben einen Neustart.

Eine JSON-Datei statt einer Datenbank: Der Datenumfang von einigen
hundert Items und einigen Dutzend Charakteren rechtfertigt keine.
Struktur und Items werden getrennt gehalten (``stash_trees`` und
``items_by_league``), weil die Stash-Liste der API grundsätzlich keine
Items enthält; diese kommen ausschließlich vom Einzel-Tab-Endpunkt.

Eine Cache-Datei JE KONTO (``path_for``), nicht mehr eine einzige
gemeinsame (Peter, 2026-08-02: "Wenn ich den Account wechsle, habe ich
dann meine eigenen Daten?"). Vorher wurde ``account_name`` zwar
gespeichert, aber nirgends verglichen — nach einem Kontowechsel blieben
Stash-Baum, Items und Charaktere des alten Kontos stehen und mischten
sich mit denen des neuen. ``save``/``load`` bleiben absichtlich auf den
ALTEN, kontounabhängigen ``_CACHE_FILE``-Pfad voreingestellt (kein
Pflicht-Parameter) — bestehende Aufrufer/Tests funktionieren dadurch
unverändert weiter; ``MainWindow`` übergibt seit der Konto-Trennung
immer explizit ``path_for(account_name)``. Die alte gemeinsame Datei
wird dadurch nie gelöscht, nur nicht mehr beschrieben (Migration siehe
``MainWindow._restore_cached_data``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from poe_view import config
from poe_view.services import atomic_json
from poe_view.api.models import Character, Item, StashTab
from poe_view.services.csv_export import sanitize_filename

log = logging.getLogger(__name__)

_CACHE_FILE = config.APP_DATA_DIR / "data-cache.json"


def path_for(account_name: str) -> Path:
    """Cache-Datei-Pfad für EIN Konto."""
    safe = sanitize_filename(account_name, fallback="account")
    return config.APP_DATA_DIR / f"data-cache-{safe}.json"


class CachedData:
    """Alles, was über einen Neustart hinweg erhalten bleiben soll."""

    def __init__(self) -> None:
        self.account_name: str = ""
        self.characters: list[Character] = []
        self.stash_trees: dict[str, list[StashTab]] = {}         # Liga → Baumstruktur
        self.items_by_league: dict[str, dict[str, list[Item]]] = {}  # Liga → {stash_id: Items}
        self.last_loaded: dict[str, dict[str, str]] = {}         # Liga → {stash_id: ISO-Zeitstempel}
        self.character_items: dict[str, list[Item]] = {}         # Charaktername → Ausrüstung+Inventar
        self.character_items_loaded: dict[str, str] = {}         # Charaktername → ISO-Zeitstempel


def save(data: CachedData, path: Path | None = None) -> None:
    """Schreibt einen vollständigen Snapshot; Fehler werden nur geloggt (kein Crash).

    ``path`` fehlt → ``_CACHE_FILE`` (siehe Modul-Docstring, Konto-Trennung)."""
    path = path if path is not None else _CACHE_FILE
    payload = {
        "account_name": data.account_name,
        "characters": [c.model_dump(mode="json") for c in data.characters],
        "stash_trees": {
            league: [s.model_dump(mode="json") for s in tree]
            for league, tree in data.stash_trees.items()
        },
        "items_by_league": {
            league: {sid: [i.model_dump(mode="json") for i in items]
                     for sid, items in stashes.items()}
            for league, stashes in data.items_by_league.items()
        },
        "last_loaded": data.last_loaded,
        "character_items": {
            name: [i.model_dump(mode="json") for i in items]
            for name, items in data.character_items.items()
        },
        "character_items_loaded": data.character_items_loaded,
    }
    try:
        config.ensure_dirs()
        # Nicht direkt in die Zieldatei: siehe atomic_json — bei 52 MB
        # dauert das lange genug, dass ein Absturz oder eine zweite
        # Instanz eine abgeschnittene Datei hinterlassen könnte.
        atomic_json.write_json(path, payload)
    except OSError:
        log.exception("Daten-Cache: Schreiben fehlgeschlagen")


def load(path: Path | None = None) -> CachedData | None:
    """None bei fehlender/kaputter Datei (z. B. allererster Start) — kein Fehler.

    ``path`` fehlt → ``_CACHE_FILE`` (siehe Modul-Docstring, Konto-Trennung)."""
    path = path if path is not None else _CACHE_FILE
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        data = CachedData()
        data.account_name = payload.get("account_name", "")
        data.characters = [Character.model_validate(c) for c in payload["characters"]]
        data.stash_trees = {
            league: [StashTab.model_validate(s) for s in tree]
            for league, tree in payload["stash_trees"].items()
        }
        data.items_by_league = {
            league: {sid: [Item.model_validate(i) for i in items]
                     for sid, items in stashes.items()}
            for league, stashes in payload["items_by_league"].items()
        }
        data.last_loaded = payload.get("last_loaded", {})
        # .get() mit Default: Cache-Dateien von vor diesem Feature kennen
        # diese Schlüssel noch nicht — sollen aber weiter ladbar bleiben.
        data.character_items = {
            name: [Item.model_validate(i) for i in items]
            for name, items in payload.get("character_items", {}).items()
        }
        data.character_items_loaded = payload.get("character_items_loaded", {})
        _backfill_last_loaded(data, path)
        return data
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.exception("Daten-Cache: Lesen fehlgeschlagen — ignoriere Cache-Datei")
        return None


def _backfill_last_loaded(data: CachedData, path: Path) -> None:
    """Migration für Cache-Dateien von vor dem last_loaded-Feature (FALLSTRICKE #12).

    Tabs, deren Items im Cache liegen, aber keinen Zeitstempel haben, bekommen
    die mtime der Cache-Datei — die Daten sind höchstens so alt wie deren
    letzter Schreibvorgang. Ohne Backfill blieben solche Tabs für immer als
    "nie geladen" (⬇) markiert und für den Auto-Refresh unsichtbar.
    """
    mtime_iso = datetime.fromtimestamp(path.stat().st_mtime,
                                       tz=timezone.utc).isoformat()
    for league, stashes in data.items_by_league.items():
        league_loaded = data.last_loaded.setdefault(league, {})
        for stash_id in stashes:
            league_loaded.setdefault(stash_id, mtime_iso)
