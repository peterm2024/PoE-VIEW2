"""Charakterbogen zum Ausdrucken/Exportieren, im Stile alter Pen&Paper-
RPGs (Peter, 2026-08-21: "eine Hommage, mit den ganzen Eigenschaften und
Items und verwendeten Gems und Levels").

**Keine berechneten Werte.** Peter hatte zunächst an das Spiel-eigene
Charakterblatt gedacht (Leben/Mana/Energieschild, Attribute, DPS) — GGGs
API liefert das nicht. Nachgemessen am kompletten Cache eines Charakters:
Weder die Charakterliste noch der Item-Endpunkt tragen irgendwo ein Feld
namens `life`, `mana`, `strength` o. ä.; nur Item- und Gem-Rohdaten.
Diese Werte entstehen im Spielclient aus dem VOLLEN Passivbaum plus allen
Item-Mods — dieselbe Rechnung, die Path of Building nachbaut. Sie hier
nachzubilden wäre ein eigenes Projekt, kein Feature nebenbei. Der Bogen
zeigt deshalb Ausrüstung und Gems — die homage kommt über die FORM
(Gliederung nach Körperslot wie ein Papierbogen), nicht über erfundene
Zahlen.

Reine Textfunktion ohne Qt-Abhängigkeit — wie ``external_tools.py``,
dessen ``item_export_text`` denselben Rohdaten entnimmt, was ein Item
ausmacht. ``DOLL_SLOTS``/``SWAP_SLOTS``/``TRINKET_SLOT`` kommen aus
``paperdoll.py``, damit Slot-Reihenfolge und -Beschriftung nicht ein
zweites Mal gepflegt werden.
"""

from __future__ import annotations

from collections.abc import Sequence

from poe_view.api.models import (ENCHANT_MOD_FIELD, FRAME_TYPE_NAMES, Character,
                                 Item, all_extra_mod_lines, extra_mod_lines)
from poe_view.ui.gem_progress import gem_progress_of
from poe_view.ui.paperdoll import DOLL_SLOTS, SWAP_SLOTS, TRINKET_SLOT

# Nur diese drei Farbkürzel stehen für ein Attribut (§theme.GEM_COLORS);
# alles andere (leer, "G") bleibt ohne Tag statt mit einer bedeutungslosen
# Platzhalter-Angabe.
_ATTRIBUTE_TAGS = {"S": "Str", "D": "Dex", "I": "Int"}


def _item_mod_lines(item: Item) -> list[str]:
    """Implizite, explizite und alle Zusatz-Mods (Verzauberung, Fraktur, …)
    in einer Liste — dieselben Quellen wie ``item_export_text``, aber ohne
    dessen PoB-Abschnittstrennung: Ein Papierbogen muss nicht zwischen
    "implizit" und "explizit" unterscheiden."""
    lines = list(extra_mod_lines(item, ENCHANT_MOD_FIELD))
    lines += list(item.implicit_mods)
    lines += list(item.explicit_mods)
    lines += [m for m in all_extra_mod_lines(item) if m not in lines]
    return lines


def _item_label(item: Item) -> str:
    """Anzeigename, plus Basistyp in Klammern, wenn er eigenständig
    etwas aussagt — bei Rare/Unique/Magic trägt ``baseType`` die
    bereinigte Fassung, bei allem anderen ist er ohnehin identisch
    (siehe ``Item.lookup_name``, dieselbe Unterscheidung)."""
    label = item.display_name
    if item.baseType and item.baseType != label:
        label = f"{label} ({item.baseType})"
    return label


def _equipment_row(slot_label: str, item: Item | None) -> str:
    if item is None:
        return f"| {slot_label} | — | — | — |"
    rarity = FRAME_TYPE_NAMES.get(item.frameType, "")
    mods = "<br>".join(_item_mod_lines(item)) or "—"
    return f"| {slot_label} | {_item_label(item)} | {rarity} | {mods} |"


def _gem_section(slot_label: str, item: Item | None) -> list[str]:
    # ``gem_progress_of`` kommt mit ``item=None`` (kein Slot belegt)
    # bereits von sich aus klar — ``getattr(None, ...)`` liefert dort den
    # Vorgabewert statt zu werfen, siehe ``gem_progress.py``.
    gems = gem_progress_of([item])
    if not gems:
        return []
    lines = [f"### {slot_label} — {_item_label(item)}", ""]
    for gem in gems:
        tag = _ATTRIBUTE_TAGS.get(gem.colour, "")
        praefix = f"[{tag}] " if tag else ""
        lines.append(f"- {praefix}{gem.tooltip}")
    lines.append("")
    return lines


def build_character_sheet(character: Character, items: Sequence[Item], *,
                          level: int | None = None,
                          experience: int | None = None) -> str:
    """Der komplette Bogen als Markdown-Text.

    ``level``/``experience`` überschreiben ``character.level`` mit dem
    live beobachteten Stand (``_XpWatch``), wenn vorhanden — dieselbe
    Zahl, die das Leveling-Feld zeigt. Ohne Angabe fällt die Anzeige auf
    ``character.level`` zurück und lässt die Erfahrung ganz weg, statt
    eine unbekannte Zahl zu behaupten."""
    by_slot: dict[str, Item] = {}
    flasks: list[Item] = []
    for item in items:
        if item.inventoryId == "Flask":
            flasks.append(item)
        elif item.inventoryId:
            by_slot.setdefault(item.inventoryId, item)

    kopf = [f"# {character.name}", ""]
    unterzeile = f"{character.class_} — Level {level if level is not None else character.level}"
    if character.league:
        unterzeile += f" — {character.league}"
    kopf.append(unterzeile)
    if experience is not None:
        kopf.append(f"XP total: {experience:,}".replace(",", " "))
    kopf.append("")

    ausruestung = ["## Equipment", "", "| Slot | Item | Rarity | Mods |",
                  "|---|---|---|---|"]
    # Die zehn Kernplätze stehen immer da, auch leer — die Silhouette
    # eines Papierbogens bleibt vollständig. Tausch-Set und Trinket
    # dagegen nur, wenn der Charakter tatsächlich etwas darin trägt
    # (dieselbe Regel wie in der Paperdoll, §SWAP_SLOTS/TRINKET_SLOT):
    # nicht jeder Charakter hat ein Zweitwaffen-Set oder ein Ritual-
    # Trinket, und eine immer leere Zeile wäre nur Ballast.
    slot_reihenfolge: list[tuple[str, str]] = [
        (slot_id, label) for _r, _c, slot_id, label in DOLL_SLOTS]
    slot_reihenfolge += [(slot_id, label) for slot_id, label in SWAP_SLOTS
                        if slot_id in by_slot]
    if TRINKET_SLOT[0] in by_slot:
        slot_reihenfolge.append(TRINKET_SLOT)
    for slot_id, label in slot_reihenfolge:
        ausruestung.append(_equipment_row(label, by_slot.get(slot_id)))
    ausruestung.append("")

    if flasks:
        ausruestung.append("### Flasks")
        ausruestung.append("")
        for flask in sorted(flasks, key=lambda i: i.x or 0):
            ausruestung.append(f"1. {_item_label(flask)}")
        ausruestung.append("")

    gems = ["## Gems", ""]
    hatte_gems = False
    for slot_id, label in slot_reihenfolge:
        item = by_slot.get(slot_id)
        # ``gem_progress_of`` kommt mit ``item=None`` klar (kein Slot
        # belegt) und liefert dann schlicht keine Gems — ein eigener
        # Leerlauf-Zweig hier wäre ununterscheidbar von diesem Fall.
        abschnitt = _gem_section(label, item)
        if abschnitt:
            hatte_gems = True
            gems += abschnitt
    if not hatte_gems:
        gems.append("*No socketed gems.*")
        gems.append("")

    return "\n".join(kopf + ausruestung + gems).rstrip() + "\n"
