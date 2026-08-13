"""Persistenter Preis-Cache mit TTL (docs/ARCHITEKTUR.md §4.14).

Ein voller poe.ninja-Abruf kostet ~30 Requests und ~1 MB — das lohnt sich
nicht bei jedem App-Start neu, zumal sich Preise nicht minütlich ändern.
Eine JSON-Datei pro Liga-Cache-Datei (wie ``data_cache.py``), keine
Datenbank: der Datenumfang (ein paar tausend Preis-Einträge) rechtfertigt
keine.
"""

from __future__ import annotations

import json
import logging
import time

from poe_view import config
from poe_view.api.ninja import PriceIndex
from poe_view.services import atomic_json

log = logging.getLogger(__name__)

_CACHE_FILE = config.APP_DATA_DIR / "price-cache.json"

# Preise bewegen sich über Stunden, nicht Minuten — 6h hält die Anzeige
# aktuell genug, ohne bei jedem Start unnötig ~1 MB nachzuladen.
TTL_SECONDS = 6 * 3600

# Kürzere TTL für ein Ergebnis ohne eine einzige echte Preiszeile
# (``PriceIndex.is_empty``) — entweder ein transienter Abruf-Fehler oder
# dauerhaft eine Liga, die poe.ninja nicht führt (FALLSTRICKE #49). Die
# volle 6h-TTL hätte einen echten transienten Fehler unnötig lange
# festgehalten (real beobachtet: "Standard" bekam einmal eine leere
# Antwort und blieb dadurch 6h ohne jeden Preis, obwohl poe.ninja Sekunden
# später wieder normal antwortete). Immer noch spürbar länger als ein
# einzelner Liga-Wechsel, damit eine dauerhaft leere Liga nicht bei jedem
# Wechsel erneut ~30 Requests gegen poe.ninja auslöst.
EMPTY_TTL_SECONDS = 3600

# Hochzählen, sobald sich die BERECHNUNG der Preise ändert — Einträge mit
# einer anderen Nummer gelten als abgelaufen, egal wie frisch sie sind.
# Anlass war die Korrektur des 1:1-Bodens der poe.ninja-receive-Seite
# (2026-08-05, §api/ninja.currency_chaos_value): Ohne diese Nummer hätte
# der Cache bis zu sechs Stunden weiter die alten, um Faktor 246 zu hohen
# Werte ausgeliefert — die Behebung wäre unsichtbar geblieben und hätte
# wie ein fehlgeschlagener Fix ausgesehen. Die TTL allein deckt das nicht
# ab: Sie misst das Alter der DATEN, nicht das der Rechenvorschrift.
#
# 3 (2026-08-13): Dieselbe Rechenvorschrift noch einmal korrigiert —
# poe.ninja führt die pay-Seite inzwischen teils in der umgekehrten
# Einheit, wodurch der Boden bei Scroll of Wisdom wieder durchschlug
# (921 Stück = 4,9 div in Peters Tabelle). Ohne diese Nummer hätte sein
# Cache die 1,0 c weiter ausgeliefert.
CACHE_VERSION = 3


def _index_to_payload(index: PriceIndex) -> dict:
    return {
        "simple": index._simple,
        "gems": {name: [list(variant) for variant in variants]
                for name, variants in index._gems.items()},
        "links": {name: {("base" if bucket is None else str(bucket)): chaos
                         for bucket, chaos in buckets.items()}
                 for name, buckets in index._links.items()},
    }


def _payload_to_index(payload: dict) -> PriceIndex:
    index = PriceIndex()
    index._simple.update(payload.get("simple", {}))
    index._gems = {
        name: [tuple(variant) for variant in variants]
        for name, variants in payload.get("gems", {}).items()
    }
    index._links = {
        name: {(None if bucket == "base" else int(bucket)): chaos
               for bucket, chaos in buckets.items()}
        for name, buckets in payload.get("links", {}).items()
    }
    return index


def save(league: str, index: PriceIndex) -> None:
    """Schreibt EINEN Liga-Eintrag; andere Ligen im Cache bleiben erhalten."""
    all_leagues = _read_raw()
    all_leagues[league] = {"version": CACHE_VERSION, "fetched_at": time.time(),
                           "empty": index.is_empty,
                           "prices": _index_to_payload(index)}
    try:
        config.ensure_dirs()
        # Wie beim Daten-Cache vollständig oder gar nicht (§atomic_json).
        # Kleiner als der Daten-Cache und damit weniger gefährdet, aber
        # dieselbe Bauart — eine halb geschriebene Datei kostet hier alle
        # Preise ALLER Ligen auf einmal, nicht nur die zuletzt geholte.
        atomic_json.write_json(_CACHE_FILE, all_leagues)
    except OSError:
        log.exception("Preis-Cache: Schreiben fehlgeschlagen")


def load(league: str, ttl_seconds: float | None = None) -> PriceIndex | None:
    """None, wenn nichts gecacht ist ODER der Eintrag älter als die TTL —
    beide Fälle bedeuten für den Aufrufer dasselbe: neu abrufen.

    Ohne explizite ``ttl_seconds`` entscheidet der beim Speichern
    vermerkte ``empty``-Zustand über die TTL (§EMPTY_TTL_SECONDS) — ein
    Ergebnis ganz ohne Preiszeile verdient kein 6h-Vertrauen.

    Ein Eintrag aus einer älteren Rechenvorschrift (§CACHE_VERSION) gilt
    ebenfalls als abgelaufen. Er wird nur ignoriert, nicht gelöscht: Der
    nächste Abruf derselben Liga überschreibt ihn ohnehin, und ein Cache,
    der von sich aus Daten wegwirft, ist in diesem Projekt schon zweimal
    teuer geworden."""
    entry = _read_raw().get(league)
    if entry is None:
        return None
    if entry.get("version") != CACHE_VERSION:
        return None
    if ttl_seconds is None:
        ttl_seconds = EMPTY_TTL_SECONDS if entry.get("empty") else TTL_SECONDS
    age = time.time() - entry.get("fetched_at", 0)
    if age > ttl_seconds:
        return None
    try:
        return _payload_to_index(entry["prices"])
    except (KeyError, TypeError, ValueError):
        log.exception("Preis-Cache: Eintrag für %s beschädigt — ignoriere ihn", league)
        return None


def _read_raw() -> dict:
    if not _CACHE_FILE.is_file():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("Preis-Cache: Lesen fehlgeschlagen — ignoriere Cache-Datei")
        return {}
