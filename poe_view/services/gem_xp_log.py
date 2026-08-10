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

**Was die Messung ergeben hat (eine Spielstunde, 231 Messpunkte,
2026-08-10 — die Spalten unten sind danach benannt, nicht vorher
geraten):**

Ein Gem kennt drei Zustände, alle drei sind hier ablesbar:

- **levelt normal** — kein `nextLevelRequirements`-Feld, der
  Erfahrungsbalken läuft.
- **wartet auf Level-Up** — `nextLevelRequirements` vorhanden UND
  `progress == 1.0`. Gems steigen in PoE nicht von selbst auf; solange
  nicht geklickt wird, ist die Erfahrung eingefroren. Genau so hält Peter
  Gems absichtlich auf Stufe 1 (Blood Rage, Frostblink, Lifetap: voller
  Balken, nie geklickt). `waiting_for_levelup` markiert das.
- **pausiert** — das Gem ist ausgesockelt und taucht überhaupt nicht auf.
  Es verpasst dabei jeden Erfahrungsschub, der in die Zeit fällt (in der
  Messung an "Summon Skitterbots" nachgewiesen: zehn Minuten draußen,
  danach fehlten ihm exakt die 1.066.352 XP des einen Schubs in diesem
  Fenster).

Peters ursprünglich vermuteter vierter Fall — ein Gem kann nicht leveln,
weil ein Attribut fehlt — sieht in den Rohdaten IDENTISCH aus wie "wartet
auf Level-Up": Das `nextLevelRequirements`-Feld nennt schlicht die
Anforderungen der nächsten Stufe, unabhängig davon, ob sie erfüllt sind.
Auseinanderhalten lässt sich beides nur, indem man diese Anforderung
gegen die Attribute des Charakters hält — die GGGs Charakter-Endpunkt
nicht liefert. Dafür `_attribute_floor()`: Was der Charakter TRÄGT, muss
er auch erfüllen, das ergibt eine sichere Untergrenze (bei Peter Str≥151,
Dex≥108, Int≥131).

`requirement_met` sagt deshalb nur `True` oder gar nichts — eine
Untergrenze kann "erfüllt" beweisen, "nicht erfüllt" aber grundsätzlich
nicht. Peters echte Attribute liegen weit über dem, was seine Ausrüstung
verlangt (Passivbaum, Juwelen); "liegt über der Untergrenze, also
blockiert" wäre ein Fehlschluss gewesen und hätte reihenweise Gems
fälschlich als festhängend gemeldet. Für die offenen Fälle steht die
Untergrenze selbst in der Spalte `attribute_floor`, sodass sich beim
Auswerten gegen den tatsächlichen Attributwert rechnen lässt — den kennt
nur der Charakterbogen im Spiel.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from poe_view import config
from poe_view.api.models import Item, req_attribute, req_level

log = logging.getLogger(__name__)

FIELDNAMES = [
    "timestamp", "character", "slot", "gem_id", "gem", "support",
    "level", "quality", "experience", "experience_max", "progress",
    "waiting_for_levelup", "requirement_met", "next_level_requirements",
    "attribute_floor",
]

# Fast voll gilt als voll — Fließkomma-Werte aus der API landen nicht
# immer exakt auf 1.0 (real bei Peter beobachtet: 1 als int, aber die
# Toleranz kostet nichts und schützt gegen einen künftigen 0.999-Fall).
_FULL_PROGRESS = 0.999

# Slots, deren Anforderungen der Charakter zwingend erfüllt, weil er die
# Sachen am Körper trägt. Bewusst eine EIGENE, knapp gehaltene Liste statt
# ``paperdoll.EQUIPPED_SLOTS``: Ein Import aus dem UI-Paket zöge Qt-Widgets
# in einen reinen Service, und die beiden Listen haben gegenläufige
# Ansprüche — die dort muss VOLLSTÄNDIG sein (sonst fehlt ein Feld auf der
# Puppe), diese hier muss SICHER sein. Eine Untergrenze wird durch einen
# fehlenden Slot nur schwächer, durch einen falschen dagegen falsch.
# Die Wechselwaffen-Plätze ("Weapon2"/"Offhand2") bleiben deshalb außen
# vor: ob PoE deren Anforderungen genauso hart erzwingt wie bei der
# geführten Waffe, ist nicht nachgeprüft.
_WORN_SLOTS = frozenset({
    "Weapon", "Offhand", "Helm", "BodyArmour", "Gloves", "Boots",
    "Belt", "Amulet", "Ring", "Ring2", "Flask",
})

# Anforderungen, für die sich aus der getragenen Ausrüstung eine
# Untergrenze ableiten lässt. Alles andere (z. B. Heists "Level N in Any
# Job") bleibt unentschieden statt geraten.
_BOUNDED_REQUIREMENTS = ("Level", "Str", "Dex", "Int")


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


def _as_int(text: str | None) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _attribute_floor(items: list[Item]) -> dict[str, int]:
    """Untergrenzen für Charakterlevel und Attribute, abgeleitet aus dem,
    was der Charakter TRÄGT: Jedes angelegte Item erzwingt seine eigenen
    Anforderungen, also liegt der Charakter mindestens beim höchsten davon.
    Kein zusätzlicher Request und keine Schätzung — und für die einzige
    Frage, die hier ansteht ("ist diese Gem-Anforderung erfüllt?"), reicht
    eine Untergrenze aus.

    Nutzt ``models.req_level``/``req_attribute`` statt eigener Parserei —
    die kennen bereits die Langformen ("Dexterity") und den Heist-Sonderfall
    "Level 2 in Any Job", der sonst als Charakterlevel durchginge."""
    floor: dict[str, int] = {}
    for item in items:
        if item.inventoryId not in _WORN_SLOTS:
            continue
        for name in _BOUNDED_REQUIREMENTS:
            raw = req_level(item) if name == "Level" else req_attribute(item, name)
            value = _as_int(raw)
            if value is not None:
                floor[name] = max(floor.get(name, 0), value)
    return floor


def _requirement_met(entries: list[dict] | None, floor: dict[str, int]) -> str:
    """``"True"``, wenn ALLE Anforderungen der nächsten Gem-Stufe
    nachweislich erfüllt sind — dann wartet das Gem nur auf einen Klick.
    Sonst leer.

    **Bewusst nur diese eine Richtung.** Eine Untergrenze kann "erfüllt"
    beweisen (die Anforderung liegt unter etwas, das der Charakter
    ohnehin schon trägt), "nicht erfüllt" dagegen NICHT: Über der
    Untergrenze zu liegen heißt bloß, dass die getragene Ausrüstung
    nichts darüber aussagt. Peters echte Werte liegen weit über dem, was
    seine Ausrüstung verlangt (Passivbaum, Juwelen) — ein "übersteigt die
    Untergrenze, also blockiert" hätte reihenweise Gems fälschlich als
    festhängend gemeldet. Die erste Fassung dieser Funktion tat genau
    das; die Spalte hieß entsprechend ``requirement_unmet`` und war ein
    Fehlschluss.

    Für die Fälle, die offen bleiben, steht die Untergrenze selbst mit in
    der Zeile (``attribute_floor``) — damit lässt sich beim Auswerten
    gegen den tatsächlichen Attributwert rechnen, den nur der Charakter-
    bogen im Spiel kennt."""
    if not entries:
        return ""
    for entry in entries:
        name = entry.get("name")
        values = entry.get("values") or []
        needed = _as_int(values[0][0]) if values else None
        if needed is None or name not in floor or needed > floor[name]:
            return ""
    return "True"


def _format_floor(floor: dict[str, int]) -> str:
    return "; ".join(f"{name} {floor[name]}"
                     for name in _BOUNDED_REQUIREMENTS if name in floor)


def _format_requirements(entries: list[dict] | None) -> str:
    if not entries:
        return ""
    parts = []
    for entry in entries:
        values = entry.get("values") or []
        if values:
            parts.append(f"{entry.get('name')} {values[0][0]}")
    return "; ".join(parts)


def _gem_rows(character: str, timestamp: str, item: Item,
              floor: dict[str, int]) -> list[dict]:
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
        waiting = (bool(next_requirements) and progress is not None
                   and progress >= _FULL_PROGRESS)
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
            "waiting_for_levelup": waiting,
            "requirement_met": _requirement_met(next_requirements, floor) if waiting else "",
            "next_level_requirements": _format_requirements(next_requirements),
            "attribute_floor": _format_floor(floor) if waiting else "",
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
    floor = _attribute_floor(items)
    rows: list[dict] = []
    for item in items:
        rows.extend(_gem_rows(character, timestamp, item, floor))
    if not rows:
        return
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _retire_foreign_header(path)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def _retire_foreign_header(path: Path) -> None:
    """Legt eine vorhandene Mitschrift mit ANDEREN Spalten beiseite, statt
    Zeilen hineinzuschreiben, die nicht zu ihrem Kopf passen.

    Konkreter Anlass: Peters erste Messstunde liegt in einer Datei mit der
    alten Spalte ``capped_by_requirement``. Würde einfach weiter angehängt,
    stünden ab da Werte unter falschen Überschriften — die Datei wäre
    stillschweigend unbrauchbar, und zwar rückwirkend auch für den Teil,
    der vorher gestimmt hat. Der alte Stand bleibt darum unter seinem
    Zeitstempel erhalten, die neue Datei fängt mit passendem Kopf an."""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), None)
    except OSError:
        return
    if header == FIELDNAMES:
        return
    retired = path.with_name(
        f"{path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    path.rename(retired)
    log.info("Gem-XP-Mitschrift hatte andere Spalten und wurde beiseitegelegt: %s",
             retired.name)
