"""Echte Tier-Leitern aus RePoE — das Fundament der Mod-Datenbank (§4.53).

Anlass: Peter beim Betrachten der aus dem Item-Level GESCHÄTZTEN
Prozent-Bänder (`mod_tiers.py`): "was sehe ich hier und was bringt mir
das? [...] Ich bin mir nicht sicher, ob wir hier was Sinnvolles machen
oder einem Gespenst hinterherjagen." Eine echte Machbarkeitsmessung
(read-only gegen Peters Bestand, nichts davon gespeichert) ergab: kein
Gespenst — 63,3 % seiner 109.888 tier-fähigen Sichtungen haben bereits
eine belegte Ground-Truth-Leiter, sobald man Item-Basis-Tags statt
Slot-Namen verwendet und Jewels (`domain: "misc"`, nicht `"item"`) nicht
vergisst. Dieses Modul ist die Umsetzung dieser Messung als Dauerbetrieb.

**Quelle:** `repoe-fork/repoe` (GitHub-Org, aktiv gepflegt), Exporte unter
https://repoe-fork.github.io/ als `mods.min.json`,
`stat_translations.min.json`, `base_items.min.json`.

**Lizenz-Falle, deshalb Laufzeit-Download statt Repo-Bündelung:** RePoEs
CODE ist MIT, die generierten DATEN gehören laut dessen eigenem
`LICENSE.md` GGG. Die Dateien dürfen deshalb nicht ins öffentliche
PoE-VIEW2-Repo — genau wie beim poe.ninja-Preis-Cache (`price_cache.py`)
lädt die App sie zur Laufzeit und hält sie lokal vor, statt sie
mitzuliefern.

**Warum die exakte Umrechnung der `index_handlers` (negate,
divide_by_X, milliseconds_to_seconds, ...) hier fehlt:**
`mod_collection.mod_identity()` ersetzt JEDE Ziffernfolge durch `#` —
für die Identität reicht deshalb ein plausibel-numerischer gerenderter
Text, die tatsächliche Umrechnung würde nur die ANGEZEIGTE Größe
betreffen, nie das Identitäts-Matching. Das war Teil der Messung, nicht
nur eine Abkürzung hier.

**Warum Kategorien über Tag-Vereinigung statt über einzelne Basen:**
`mod_collection` schlüsselt das Kontenbuch nach `item_category()`
("Boots", "Ring", ...) — gröber als RePoEs Tags ("dex_boots", ...). Eine
Leiter muss in genau diesem Namensraum liegen, um mit dem Kontenbuch
vergleichbar zu sein. Die Vereinigung ALLER Tags ausgelieferter Basen
je Kategorie ist eine Annäherung (kann vereinzelt einen Mod fälschlich
als für eine ganze Kategorie eligible ansehen, der nur eine
Rüstungsvariante trifft) — dieselbe Annäherung, mit der die 63,3-%-Zahl
gemessen wurde.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from poe_view import config
from poe_view.services.mod_collection import mod_identity

log = logging.getLogger(__name__)

_BASE_URL = "https://repoe-fork.github.io"
_FILES = ("mods.min.json", "stat_translations.min.json", "base_items.min.json")

_DIR_NAME = "mod-knowledge"


def _cache_dir() -> Path:
    """Als Funktion statt Modul-Konstante — wie `cache_backup.directory()`.
    Eine bei Modul-Import eingefrorene Konstante hätte `config.APP_DATA_DIR`
    NICHT mehr gesehen, sobald Tests es umbiegen (dieselbe wiederkehrende
    Falle wie einst bei `cache_backup.BACKUP_DIR`/`config.LOG_DIR`)."""
    return config.APP_DATA_DIR / _DIR_NAME


# RePoE ändert sich mit Spiel-Patches, nicht mit Sitzungen — eine Woche
# hält den ~30-MB-Download selten, ohne nach einem Liga-Patch wochenlang
# veraltete Mod-Listen zu zeigen.
TTL_SECONDS = 7 * 24 * 3600

# Hochzählen, sobald sich das GESPEICHERTE FORMAT ändert (nicht die
# heruntergeladenen Rohdaten selbst) — wie bei price_cache.CACHE_VERSION.
CACHE_VERSION = 1

# Waffen-Item-Klassen: RePoEs Bezeichnung -> unsere item_category()
# (nur eingetragen, wo sie abweichen; sonst identisch).
_CLASS_RENAME = {
    "One Hand Sword": "One Handed Sword", "Two Hand Sword": "Two Handed Sword",
    "Thrusting One Hand Sword": "Thrusting One Handed Sword",
    "One Hand Axe": "One Handed Axe", "Two Hand Axe": "Two Handed Axe",
    "One Hand Mace": "One Handed Mace", "Two Hand Mace": "Two Handed Mace",
}


# --- Download/Cache (Muster: services/price_cache.py) ------------------- #

def _manifest_path() -> Path:
    return _cache_dir() / "manifest.json"


def is_fresh() -> bool:
    """Liegt ein vollständiger, nicht abgelaufener Download vor?"""
    manifest = _read_manifest()
    if manifest is None or manifest.get("version") != CACHE_VERSION:
        return False
    if not all((_cache_dir() / name).is_file() for name in _FILES):
        return False
    age = time.time() - manifest.get("fetched_at", 0)
    return age <= TTL_SECONDS


def _read_manifest() -> dict | None:
    path = _manifest_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def fetch(http: httpx.Client | None = None) -> bool:
    """Lädt alle drei RePoE-Dateien neu. Best-effort wie beim
    Preis-Cache: Ein Netzwerkfehler darf die App nicht zum Absturz
    bringen, nur den bisherigen Cache unverändert lassen. Schreibt erst
    dann, wenn alle drei Dateien vollständig da sind — ein Teil-Download
    (z. B. Abbruch nach `mods.min.json`) darf keinen inkonsistenten
    Stand hinterlassen, in dem eine Datei neuer ist als die anderen."""
    owns_client = http is None
    client = http or httpx.Client(
        timeout=60.0, headers={"User-Agent": config.user_agent()}, follow_redirects=True)
    try:
        payloads: dict[str, bytes] = {}
        for name in _FILES:
            resp = client.get(f"{_BASE_URL}/{name}")
            if resp.status_code != 200:
                log.warning("Mod-Wissen: Download von %s fehlgeschlagen (Status %s)",
                            name, resp.status_code)
                return False
            payloads[name] = resp.content

        cache_dir = _cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        for name, data in payloads.items():
            tmp = cache_dir / f"{name}.tmp"
            tmp.write_bytes(data)
            tmp.replace(cache_dir / name)
        _manifest_path().write_text(
            json.dumps({"version": CACHE_VERSION, "fetched_at": time.time()}), encoding="utf-8")
        return True
    except (httpx.HTTPError, OSError):
        log.exception("Mod-Wissen: Download fehlgeschlagen")
        return False
    finally:
        if owns_client:
            client.close()


def ensure_fresh(http: httpx.Client | None = None) -> bool:
    """Lädt nur nach, wenn der Cache fehlt oder abgelaufen ist."""
    return True if is_fresh() else fetch(http)


def _load_raw() -> tuple[dict, list, dict] | None:
    cache_dir = _cache_dir()
    try:
        mods = json.loads((cache_dir / "mods.min.json").read_text(encoding="utf-8"))
        translations = json.loads(
            (cache_dir / "stat_translations.min.json").read_text(encoding="utf-8"))
        base_items = json.loads((cache_dir / "base_items.min.json").read_text(encoding="utf-8"))
        return mods, translations, base_items
    except (OSError, json.JSONDecodeError):
        return None


# --- Übersetzung stat_id+Wert -> Mod-Identität --------------------------- #

def render_identity(by_id: dict, stat_id: str, value: float) -> str | None:
    """Rendert einen stat_id+Wert wie das Spiel es als Mod-Zeile zeigen
    würde, und liefert dessen Identität (siehe Modul-Docstring, warum
    die grobe Formatierung hier reicht). ``None``, wenn die
    Übersetzungstabelle diese stat_id nicht führt oder das Format
    fehlerhaft ist."""
    entry = by_id.get(stat_id)
    if entry is None:
        return None
    varianten = entry.get("English") or []
    if not varianten:
        return None
    treffer = None
    for v in varianten:
        cond = (v.get("condition") or [{}])[0] or {}
        lo, hi = cond.get("min"), cond.get("max")
        if (lo is None or value >= lo) and (hi is None or value <= hi):
            treffer = v
            break
    v = treffer or varianten[0]
    fmt = (v.get("format") or ["#"])[0]
    text = f"+{value:g}" if fmt == "+#" and value >= 0 else f"{value:g}"
    try:
        rendered = v["string"].format(text)
    except (IndexError, KeyError):
        return None
    return mod_identity(rendered)


def _eligible(spawn_weights: list[dict], tags: frozenset) -> bool:
    """Kann ein Mod mit diesen `spawn_weights` auf einer Basis mit
    diesen Tags auftreten? RePoE prüft die Tags der Basis der Reihe
    nach gegen die Gewichtstabelle des Mods und nimmt den ersten
    Treffer; ohne Tag-Treffer entscheidet `default`."""
    gewichte = {w["tag"]: w["weight"] for w in spawn_weights}
    for tag in tags:
        if tag in gewichte:
            return gewichte[tag] > 0
    return gewichte.get("default", 0) > 0


# --- Tier-Leitern --------------------------------------------------------- #

@dataclass(frozen=True)
class TierStep:
    """Eine Sprosse der echten Leiter: ab `required_level` erreichbar,
    mit Wertspanne `low`..`high`."""

    required_level: int
    low: float
    high: float


class Knowledge:
    """Ladders je (Mod-Identität, Item-Kategorie) — schreibgeschützt
    nach dem Bau, damit sie sich wie das Kontenbuch nur lesend
    verwenden lässt."""

    def __init__(self, ladders: dict[tuple[str, str], list[TierStep]]) -> None:
        self._ladders = ladders

    def ladder(self, identity: str, category: str) -> list[TierStep]:
        return self._ladders.get((identity, category), [])

    def has(self, identity: str, category: str) -> bool:
        return (identity, category) in self._ladders

    def __len__(self) -> int:
        return len(self._ladders)


def _tags_by_category(base_items: dict) -> dict[str, set[str]]:
    tags: dict[str, set[str]] = {}
    for base in base_items.values():
        cls = base.get("item_class")
        if base.get("release_state") != "released" or not cls:
            continue
        category = _CLASS_RENAME.get(cls, cls)
        tags.setdefault(category, set()).update(base.get("tags") or [])
    return tags


def build() -> Knowledge | None:
    """Baut die Leitern aus dem gecachten RePoE-Stand. ``None``, wenn
    (noch) nichts gecacht ist — der Aufrufer entscheidet dann, ob er
    zuerst ``fetch()`` versucht."""
    raw = _load_raw()
    if raw is None:
        return None
    mods, translations, base_items = raw
    by_id = {t["ids"][0]: t for t in translations if len(t.get("ids") or []) == 1}
    tags_by_category = _tags_by_category(base_items)

    ladders: dict[tuple[str, str], list[TierStep]] = {}
    for mod in mods.values():
        if mod.get("domain") not in ("item", "misc"):
            continue
        if mod.get("generation_type") not in ("prefix", "suffix"):
            continue
        if mod.get("is_essence_only"):
            continue
        stats = mod.get("stats") or []
        if len(stats) != 1:
            continue
        stat = stats[0]
        spawn_weights = mod.get("spawn_weights") or []
        required_level = mod.get("required_level", 0)

        identity: str | None = None
        for category, tags in tags_by_category.items():
            if not _eligible(spawn_weights, frozenset(tags)):
                continue
            if identity is None:
                identity = render_identity(by_id, stat["id"], stat["min"])
                if identity is None:
                    break
            ladders.setdefault((identity, category), []).append(
                TierStep(required_level, stat["min"], stat["max"]))

    for steps in ladders.values():
        steps.sort(key=lambda s: s.required_level)
    return Knowledge(ladders)


_cached: Knowledge | None = None


def get(rebuild: bool = False) -> Knowledge | None:
    """Im-Speicher-Singleton — das Bauen liest und verarbeitet ~30 MB
    JSON, das lohnt sich nicht bei jeder Abfrage neu."""
    global _cached
    if rebuild or _cached is None:
        _cached = build()
    return _cached
