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

# RePoEs Bezeichnung -> unsere item_category() (nur eingetragen, wo sie
# abweichen; sonst identisch). Die Waffen heißen bei RePoE "One Hand
# Sword", bei uns "One Handed Sword". "AbyssJewel" fällt bei uns mit
# "Jewel" zusammen: `item_category()` entscheidet über die
# baseType-Endung, und ein "Searching Eye Jewel" endet auf "Jewel" wie
# jedes andere. Die Leitern beider Jewel-Arten landen dadurch in einem
# Topf — dieselbe Annäherung wie bei den Rüstungstypen, siehe §4.53.
_CLASS_RENAME = {
    "One Hand Sword": "One Handed Sword", "Two Hand Sword": "Two Handed Sword",
    "Thrusting One Hand Sword": "Thrusting One Handed Sword",
    "One Hand Axe": "One Handed Axe", "Two Hand Axe": "Two Handed Axe",
    "One Hand Mace": "One Handed Mace", "Two Hand Mace": "Two Handed Mace",
    "AbyssJewel": "Jewel",
}

# Unsere Kategorien, auf denen Jewel-Mods leben. Getrennt von der
# übrigen Ausrüstung, weil RePoE sie über die DOMAIN trennt und nicht
# über Tags: Ein Jewel-Mod wie `DexterityJewel` trägt
# `[{not_dex: 300}, {default: 500}]` — auf ein Amulett (Tags
# `{amulet, default}`) passt `default`, der Mod wäre also für JEDE
# Kategorie zugelassen und schob sich vor die echten Amulett-Sprossen.
# Genau eine Sprosse zu viel gegenüber Peters CraftOfExile-Screenshot.
JEWEL_CATEGORIES = frozenset({"Jewel"})

# Domains, deren Mods ausschließlich auf Jewels erscheinen. "misc" sind
# die gewöhnlichen Jewels (nicht "item", was lange unbemerkt blieb),
# "abyss_jewel" die aus den Abyss-Fassungen.
_JEWEL_DOMAINS = frozenset({"misc", "abyss_jewel"})


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
    """Kann ein Mod mit diesen `spawn_weights` auf einer Basis mit genau
    diesen Tags auftreten?

    **Die Reihenfolge der Liste entscheidet, nicht die der Tags.** Das
    Spiel geht `spawn_weights` von oben nach unten durch und nimmt den
    ERSTEN Eintrag, dessen Tag die Basis trägt; `default` steht deshalb
    immer am Ende und fängt alles Übrige. Der erste Entwurf hatte
    stattdessen über die Tags der Basis iteriert und in einer
    Gewichts-Tabelle nachgeschlagen — dieselbe Menge, andere Reihenfolge,
    und weil `tags` ein `frozenset` ist, war die Reihenfolge zwischen
    zwei Prozessen sogar verschieden (Pythons Hash-Randomisierung). Ein
    Mod wie `Dexterity1` (`[{amulet: 1000}, {default: 0}]`) fiel damit
    mal durch und mal nicht: An Peters CraftOfExile-Screenshot gemessen
    fehlten acht von neun Amulett-Sprossen (§4.53)."""
    for eintrag in spawn_weights:
        if eintrag["tag"] == "default" or eintrag["tag"] in tags:
            return eintrag["weight"] > 0
    return False


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


def _bases_by_category(base_items: dict) -> dict[str, set[frozenset[str]]]:
    """Je Kategorie die Tag-Mengen ihrer ausgelieferten Basen — EINE
    Menge je Basis, nicht eine Vereinigung über alle.

    Die Vereinigung wäre falsch, obwohl sie naheliegt: Sie mischt die
    Tags verschiedener Basen zu einer Basis, die es nicht gibt, und die
    Reihenfolge-Regel in `_eligible` liefert für dieses Phantom eine
    andere Antwort als für jede echte Basis. Ein Mod gilt für die
    Kategorie, wenn er auf IRGENDEINER ihrer Basen erscheinen kann —
    das ist die Frage, die zum gröberen Kategorie-Begriff von
    `item_category()` passt.

    Dedupliziert, weil viele Basen dieselben Tags tragen (866 Mengen
    statt gut 2000 Basen)."""
    basen: dict[str, set[frozenset[str]]] = {}
    for base in base_items.values():
        cls = base.get("item_class")
        if base.get("release_state") != "released" or not cls:
            continue
        category = _CLASS_RENAME.get(cls, cls)
        basen.setdefault(category, set()).add(frozenset(base.get("tags") or []))
    return basen


def build() -> Knowledge | None:
    """Baut die Leitern aus dem gecachten RePoE-Stand. ``None``, wenn
    (noch) nichts gecacht ist — der Aufrufer entscheidet dann, ob er
    zuerst ``fetch()`` versucht."""
    raw = _load_raw()
    if raw is None:
        return None
    mods, translations, base_items = raw
    by_id = {t["ids"][0]: t for t in translations if len(t.get("ids") or []) == 1}
    bases_by_category = _bases_by_category(base_items)
    equipment = set(bases_by_category) - JEWEL_CATEGORIES

    ladders: dict[tuple[str, str], list[TierStep]] = {}
    for mod in mods.values():
        categories = (JEWEL_CATEGORIES if mod.get("domain") in _JEWEL_DOMAINS
                      else equipment if mod.get("domain") == "item" else None)
        if not categories:
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
        for category in categories:
            if not any(_eligible(spawn_weights, tags)
                      for tags in bases_by_category[category]):
                continue
            if identity is None:
                identity = render_identity(by_id, stat["id"], stat["min"])
                if identity is None:
                    break
            ladders.setdefault((identity, category), []).append(
                TierStep(required_level, stat["min"], stat["max"]))

    return Knowledge({schluessel: _tidy(steps)
                     for schluessel, steps in ladders.items()})


def _tidy(steps: list[TierStep]) -> list[TierStep]:
    """Sprossen nach Freischalt-Level ordnen und wertgleiche
    zusammenfassen.

    Zwei Sprossen mit derselben Spanne sind für den Betrachter dieselbe
    Stufe, auch wenn RePoE sie getrennt führt: Bei Jewels stehen der
    gewöhnliche und der Abyss-Mod nebeneinander (beide `12–16`), und die
    Leiter zeigte sonst zwei Stufen, die sich um nichts unterscheiden.
    Behalten wird die früheste — das Freischalt-Level ist eine Aussage
    darüber, ab wann die Spanne erreichbar ist."""
    beste: dict[tuple[float, float], TierStep] = {}
    for step in sorted(steps, key=lambda s: s.required_level):
        beste.setdefault((step.low, step.high), step)
    return sorted(beste.values(), key=lambda s: s.required_level)


_cached: Knowledge | None = None


def get(rebuild: bool = False) -> Knowledge | None:
    """Im-Speicher-Singleton — das Bauen liest und verarbeitet ~30 MB
    JSON, das lohnt sich nicht bei jeder Abfrage neu."""
    global _cached
    if rebuild or _cached is None:
        _cached = build()
    return _cached
