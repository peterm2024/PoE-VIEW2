"""CSV-Mitschrift der Sockel-Gem-Erfahrung über die Zeit (Peter,
2026-08-10: "Ich werde demnächst eine Runde spielen, da können wir mal
die XP/h pro Gem messen. Die genauen Werte bzw. der Verlauf würde mich
interessieren." — Grundlage für die in ARCHITEKTUR.md §4.34 zurückgestellte
Gem-XP/h-Anzeige, direkt aus der §4.33-Diagnose entstanden).

Reine Beobachtung für die kommende Spielrunde, kein Ersatz für einen
richtigen Zeitreihen-Speicher (der bräuchte ein Format, das sich schnell
nach einem einzelnen Gem filtern lässt — für eine Handvoll Spielstunden
tut es eine CSV, die man in jede Tabellenkalkulation ziehen kann, genauso
gut und ist in einer Zeile erklärt).

**Zwei Fälle, die Peter ausdrücklich unterschieden haben wollte, bevor
gemessen wird — beide real in Peters eigenem Cache gefunden, keine
Vermutung:**

- Ein Gem OHNE `nextLevelRequirements`-Feld levelt normal weiter, sobald
  genug Erfahrung da ist.
- Ein Gem MIT `nextLevelRequirements` und `progress == 1.0`
  (Erfahrung für die aktuelle Stufe bereits voll) hängt fest, weil eine
  Voraussetzung für die nächste Stufe fehlt — meist ein Attribut (z. B.
  Peters "Blood Rage": braucht 50 Dex für die nächste Stufe, hat nur 41)
  oder ein zu niedriges Charakterlevel. `capped_by_requirement` markiert
  genau das.

Ob PoE zusätzlich einen eigenen Schalter "EP-Zuwachs deaktivieren" kennt
(Peters zweite Vermutung), ließ sich weder in Peters echtem Cache noch in
der öffentlichen Doku bestätigen — deshalb hier NICHT geraten, sondern
einfach ALLE Rohfelder mitgeschrieben. Bleibt die Erfahrung eines Gems
über die Spielrunde hinweg flach, ohne dass `capped_by_requirement`
gesetzt ist, ist das der Kandidat dafür; die CSV reicht, um das im
Nachhinein zu unterscheiden, ohne dass vorher schon geraten werden musste,
wonach zu suchen ist.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from poe_view import config
from poe_view.api.models import Item

FIELDNAMES = [
    "timestamp", "character", "slot", "gem_id", "gem", "support",
    "level", "quality", "experience", "experience_max", "progress",
    "capped_by_requirement", "next_level_requirements",
]

# Fast voll gilt als voll — Fließkomma-Werte aus der API landen nicht
# immer exakt auf 1.0 (real bei Peter beobachtet: 1 als int, aber die
# Toleranz kostet nichts und schützt gegen einen künftigen 0.999-Fall).
_FULL_PROGRESS = 0.999


def log_path() -> Path:
    """Funktion statt Konstante — dieselbe Falle wie bei
    ``cache_backup.directory()``: ``config.LOG_DIR`` bei Modul-Importzeit
    einzufrieren, würde Tests, die den Pfad patchen, ins echte
    Datenverzeichnis schreiben lassen (genau das ist hier schon einmal
    passiert, sechs Fremddateien in Peters echtem Ordner)."""
    return config.LOG_DIR / "gem-xp-log.csv"


def _property_value(gem: dict, list_key: str, name: str) -> str | None:
    for prop in gem.get(list_key) or []:
        if prop.get("name") == name:
            values = prop.get("values") or []
            if values:
                return values[0][0]
    return None


def _experience(gem: dict) -> tuple[int | None, int | None, float | None]:
    for prop in gem.get("additionalProperties") or []:
        if prop.get("name") != "Experience":
            continue
        progress = prop.get("progress")
        values = prop.get("values") or []
        if not values:
            return None, None, progress
        current_str, _, max_str = str(values[0][0]).partition("/")
        try:
            return int(current_str), int(max_str), progress
        except ValueError:
            return None, None, progress
    return None, None, None


def _format_requirements(entries: list[dict] | None) -> str:
    if not entries:
        return ""
    parts = []
    for entry in entries:
        values = entry.get("values") or []
        if values:
            parts.append(f"{entry.get('name')} {values[0][0]}")
    return "; ".join(parts)


def _gem_rows(character: str, timestamp: str, item: Item) -> list[dict]:
    """Eine Zeile je Sockel-Gem in ``item``. ``socketedItems`` ist ein
    über ``extra=\"allow\"`` mitgeführtes Rohfeld (siehe ARCHITEKTUR.md
    §4.33) — rohe Dicts, keine eigenen Pydantic-Modelle, deshalb hier
    direkt über GGGs Schlüssel statt über typisierte Attribute."""
    rows = []
    for gem in getattr(item, "socketedItems", None) or []:
        if not isinstance(gem, dict):
            continue
        experience, experience_max, progress = _experience(gem)
        next_requirements = gem.get("nextLevelRequirements")
        capped = bool(next_requirements) and progress is not None and progress >= _FULL_PROGRESS
        rows.append({
            "timestamp": timestamp,
            "character": character,
            "slot": item.inventoryId,
            "gem_id": gem.get("id", ""),
            "gem": gem.get("typeLine") or gem.get("baseType") or "",
            "support": gem.get("support", False),
            "level": _property_value(gem, "properties", "Level"),
            "quality": _property_value(gem, "properties", "Quality"),
            "experience": experience,
            "experience_max": experience_max,
            "progress": progress,
            "capped_by_requirement": capped,
            "next_level_requirements": _format_requirements(next_requirements),
        })
    return rows


def append(character: str, items: list[Item]) -> None:
    """Ein Messpunkt: eine Zeile pro Sockel-Gem über alle Items von
    ``character`` (Ausrüstung UND Rucksack — Letzterer hat schlicht nie
    ``socketedItems``, kein Sonderfall nötig). Läuft für JEDEN
    Charakter-Abruf mit, auch im stillen Hintergrund-Refresh
    (``_on_character_items``) — mehr Messpunkte für den von Peter
    gewünschten Verlauf, unabhängig davon, welcher Charakter gerade
    angezeigt wird. Ohne Sockel-Gems (z. B. ein frisch erstellter
    Charakter) wird nichts geschrieben, auch keine leere Zeile."""
    timestamp = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for item in items:
        rows.extend(_gem_rows(character, timestamp, item))
    if not rows:
        return
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)
