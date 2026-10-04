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

import re
from collections.abc import Sequence

from poe_view.api.models import (ENCHANT_MOD_FIELD, FRAME_TYPE_NAMES, Character,
                                 Item, all_extra_mod_lines, extra_mod_lines)
from poe_view.services import passive_tree
from poe_view.services.passive_tree import (JEWEL, KEYSTONE, MASTERY, NOTABLE, SMALL,
                                            START, Tree)
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
        lines.append(f"- {praefix}{gem.tooltip()}")
    lines.append("")
    return lines


def _stats_text(stats) -> str:
    return "; ".join(stats) or "—"


def tree_section(entry: dict | None, tree: Tree | None, *, character_class: str,
                 jewels: Sequence[Item] = ()) -> list[str]:
    """Der Passiv-Baum als Markdown-Abschnitt (§4.60).

    Peter, 2026-10-04: "eine Export-Funktion ... um z.B. eine Einschätzung
    von dir zur Skillpunktvergabe holen zu können." Geschrieben für einen
    Leser, der den Baum NICHT vor sich hat: jeder Knoten mit seinen Werten,
    die kleinen Knoten zusammengezählt, und was mit wenigen Punkten
    erreichbar wäre."""
    zeilen = ["## Passive tree", ""]
    if not entry:
        zeilen += ["*Not known yet — it arrives with the next refresh of this character.*", ""]
        return zeilen
    passives = entry.get("passives") or {}
    have = passive_tree.allocated(passives)
    if tree is None:
        zeilen += [f"*{len(have)} nodes allocated. GGG's tree data has not been downloaded "
                   "yet, so their names and values are missing — try again in a minute.*", ""]
        return zeilen

    knoten = [tree.nodes[h] for h in sorted(have) if h in tree.nodes]
    unbekannt = len(have) - len(knoten)
    aszendenz = [n for n in knoten if n.ascendancy and n.kind != START]
    normal = [n for n in knoten if not n.ascendancy and n.kind != START]
    cluster = len(passives.get("hashes_ex") or ())
    level = entry.get("level") or 0

    kopf = (f"{'Ruthless' if tree.ruthless else 'Standard'} tree · "
            f"{len(normal)} points allocated · {len(aszendenz)} ascendancy points")
    if cluster:
        kopf += f" · {cluster} cluster jewel nodes"
    # Jede Kopfzeile ein eigener Absatz — Markdown zieht aufeinanderfolgende
    # Zeilen sonst zu einer zusammen (nativ gesehen im Baum-Fenster).
    zeilen += [kopf, ""]
    if level:
        zeilen += [f"Level {level} gives {level - 1} points from levels, plus quest "
                   "rewards (the API does not report those).", ""]
    extras = []
    if passives.get("bandit_choice"):
        extras.append(f"Bandit: {passives['bandit_choice']}")
    if passives.get("pantheon_major"):
        extras.append(f"Pantheon: {passives['pantheon_major']}"
                      + (f" / {passives['pantheon_minor']}" if passives.get("pantheon_minor") else ""))
    if extras:
        zeilen += [" · ".join(extras), ""]
    if unbekannt:
        zeilen += [f"*{unbekannt} allocated nodes are missing from GGG's tree data "
                   "(the download may be older than the last patch).*", ""]

    def liste(titel: str, gruppe) -> None:
        if not gruppe:
            return
        zeilen.extend([f"### {titel}", ""])
        zeilen.extend(f"- **{n.name}** — {_stats_text(n.stats)}"
                      for n in sorted(gruppe, key=lambda n: n.name))
        zeilen.append("")

    liste(f"Ascendancy ({character_class})", aszendenz)
    liste("Keystones", [n for n in normal if n.kind == KEYSTONE])
    notables = [n for n in normal if n.kind == NOTABLE]
    liste(f"Notables ({len(notables)})", notables)

    wahl = passive_tree.mastery_choices(passives)
    masteries = []
    for knoten_id, effekt in sorted(wahl.items()):
        mastery = tree.nodes.get(knoten_id)
        if mastery is None or mastery.kind != MASTERY:
            continue
        masteries.append(f"- **{mastery.name}** — "
                         f"{_stats_text(mastery.effects.get(effekt, ()))}")
    if masteries:
        zeilen += ["### Masteries", ""] + sorted(masteries) + [""]

    sockel = [n for n in normal if n.kind == JEWEL]
    if sockel or jewels:
        zeilen += [f"### Jewels ({len(sockel)} sockets allocated)", ""]
        zeilen += [f"- **{_item_label(j)}** — {_stats_text(_item_mod_lines(j))}"
                   for j in jewels]
        if not jewels:
            zeilen.append("*No jewels socketed.*")
        zeilen.append("")

    kleine = [n for n in normal if n.kind == SMALL]
    if kleine:
        zeilen += [f"### Small passives ({len(kleine)}), summed", ""]
        zeilen += [f"- {z}" for z in
                   passive_tree.summed_stats([z for n in kleine for z in n.stats])]
        zeilen.append("")

    reichweite = passive_tree.within_reach(tree, have, class_name=character_class)
    zeilen += [f"### Within reach (up to {passive_tree.REACH_POINTS} more points)", ""]
    if not reichweite:
        zeilen.append("*Nothing notable within reach.*")
    for r in reichweite:
        art = {KEYSTONE: "keystone", JEWEL: "jewel socket"}.get(r.node.kind, "notable")
        weg = f"; via {', '.join(n.name for n in r.via)}" if r.via else ""
        werte = _stats_text(r.node.stats) if r.node.stats else (
            "empty socket" if r.node.kind == JEWEL else "—")
        punkte = "point" if r.cost == 1 else "points"
        zeilen.append(f"- **{r.node.name}** ({art}, {r.cost} {punkte}{weg}) — {werte}")
    zeilen.append("")
    return zeilen


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
    """Der Umbau als Markdown: was zurücknehmen, was nehmen, welche Mastery
    anders, was sich an Werten ändert (§4.60.1). Geschrieben als
    Arbeitsliste für den Baum im Spiel."""
    umbau = passive_tree.compare(tree, current, target)
    zeilen = [f"## {title}", ""]
    if not (umbau.refund or umbau.allocate or umbau.masteries):
        return zeilen + ["*Same tree — nothing to change.*", ""]
    zeilen.append(f"{umbau.points} points to refund in the main tree"
                  + (" (plus ascendancy changes)" if any(n.ascendancy for n in
                                                          umbau.refund + umbau.allocate) else ""))
    zeilen.append("")
    # Gewinn oder Verlust nach dem Vorzeichen der ersten Zahl — es steht
    # vorn ("+5% to X") oder an der Stelle der Zahl ("Regenerate +1% ...").
    gewinne = [z for z in umbau.stats if z.startswith("gained: ")
               or (m := re.search(r"(?<!\w)([+-])\d", z)) is not None and m.group(1) == "+"]
    verluste = [z for z in umbau.stats if z not in gewinne]

    def knoten_zeile(n) -> str:
        art = {KEYSTONE: "keystone", NOTABLE: "notable", JEWEL: "jewel socket"}.get(n.kind, "")
        zusatz = f" ({'ascendancy ' if n.ascendancy else ''}{art})" if art or n.ascendancy else ""
        return f"- **{n.name}**{zusatz} — {_stats_text(n.stats)}"

    if umbau.refund:
        zeilen += [f"### Refund ({len(umbau.refund)})", ""] + [knoten_zeile(n) for n in umbau.refund] + [""]
    if umbau.allocate:
        zeilen += [f"### Allocate ({len(umbau.allocate)})", ""] + [knoten_zeile(n) for n in umbau.allocate] + [""]
    if umbau.masteries:
        zeilen += ["### Change mastery", ""]
        zeilen += [f"- **{m.name}**: {_stats_text(alt)} → {_stats_text(neu)}"
                   for m, alt, neu in umbau.masteries]
        zeilen.append("")
    if gewinne:
        zeilen += ["### Gains", ""] + [f"- {z}" for z in gewinne] + [""]
    if verluste:
        zeilen += ["### Losses", ""] + [f"- {z}" for z in verluste] + [""]
    return zeilen
