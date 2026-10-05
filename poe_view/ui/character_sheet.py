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
from poe_view.services.passive_tree import Tree
from poe_view.ui import tree_report
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


def _gem_line(gem) -> str:
    tag = _ATTRIBUTE_TAGS.get(gem.colour, "")
    return f"{f'[{tag}] ' if tag else ''}{gem.tooltip()}"


def _link_groups(item: Item, gems) -> list[list] | None:
    """Die Gems nach Link-Gruppe ihres Sockels, in Sockel-Reihenfolge —
    oder ``None``, wenn sich nicht jedes Gem einem Sockel zuordnen lässt
    (ältere Daten ohne ``socket``, fehlende Gem-Kennung). Dann bleibt es
    bei der flachen Liste statt einer halb richtigen Gruppierung."""
    sockel = {str(g.get("id") or ""): g.get("socket")
              for g in getattr(item, "socketedItems", None) or [] if isinstance(g, dict)}
    if not item.sockets or "" in sockel:
        return None
    gruppen: dict[int, list] = {}
    for gem in gems:
        index = sockel.get(gem.gem_id)
        if not isinstance(index, int) or not 0 <= index < len(item.sockets):
            return None
        gruppen.setdefault(item.sockets[index].group, []).append(gem)
    return [gruppen[g] for g in sorted(gruppen)]


def _gem_section(slot_label: str, item: Item | None) -> list[str]:
    # ``gem_progress_of`` kommt mit ``item=None`` (kein Slot belegt)
    # bereits von sich aus klar — ``getattr(None, ...)`` liefert dort den
    # Vorgabewert statt zu werfen, siehe ``gem_progress.py``.
    gems = gem_progress_of([item])
    if not gems:
        return []
    lines = [f"### {slot_label} — {_item_label(item)}", ""]
    gruppen = _link_groups(item, gems)
    if gruppen is None:
        lines += [f"- {_gem_line(gem)}" for gem in gems]
    else:
        # Nach Link-Gruppen (Peter, 2026-10-05, zur Einschätzung: welche
        # Gems unterstützen einander wirklich?). "Sockets" in der
        # Schreibweise des Spiels: R-G-B verlinkt, Leerzeichen trennt.
        lines += [f"Sockets: {item.socket_string}", ""]
        for gruppe in gruppen:
            if len(gruppe) == 1:
                lines.append(f"- Alone: {_gem_line(gruppe[0])}")
                continue
            lines.append(f"- Linked ({len(gruppe)}): " + " + ".join(g.name for g in gruppe))
            lines += [f"  - {_gem_line(g)}" for g in gruppe]
    lines.append("")
    return lines


def _stats_text(stats) -> str:
    return "; ".join(stats) or "—"


def tree_section(entry: dict | None, tree: Tree | None, *, character_class: str,
                 jewels: Sequence[Item] = (), include_reach: bool = True) -> list[str]:
    """Der Passiv-Baum als Markdown-Abschnitt (§4.60). Gegliedert wird in
    ``tree_report`` (§4.60.3), das auch das farbige Fenster speist; hier
    nur die Jewels als Text und die Markdown-Ausgabe."""
    return tree_report.to_markdown(tree_report.tree_blocks(
        entry, tree, character_class=character_class,
        jewels=[(_item_label(j), _item_mod_lines(j)) for j in jewels],
        include_reach=include_reach))


def reach_section(tree: Tree, have: set[int], character_class: str) -> list[str]:
    return tree_report.to_markdown(tree_report.reach_blocks(tree, have, character_class))


def build_character_sheet(character: Character, items: Sequence[Item], *,
                          level: int | None = None,
                          experience: int | None = None,
                          tree_entry: dict | None = None,
                          tree: Tree | None = None) -> str:
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

    baum = tree_section(tree_entry, tree, character_class=character.class_,
                        jewels=[i for i in items if i.inventoryId == "PassiveJewels"])
    return "\n".join(kopf + ausruestung + gems + baum).rstrip() + "\n"


def respec_section(tree: Tree, current: dict, target: dict, *, title: str) -> list[str]:
    """Der Umbau als Markdown (§4.60.1, gegliedert in ``tree_report``)."""
    return tree_report.to_markdown(tree_report.respec_blocks(tree, current, target, title=title))
