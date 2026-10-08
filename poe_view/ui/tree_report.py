"""Der Passiv-Baum als Bericht: einmal gegliedert, zweimal ausgegeben
(§4.60.3).

Peter, 2026-10-05: "Kannst du beim Baum noch ein bisschen mehr Farbe und
Symbole ins Spiel bringen? Und eine Summary oben mit den Insgesamtwerten,
z.B. 120% increased Damage, +95 max. Life..."

Farbe kann Markdown nicht. Deshalb baut dieses Modul den Bericht als
Liste von ``Block`` und gibt ihn auf zwei Wegen aus: als Markdown für den
Charakterbogen und "Copy as text" (Symbole ja, Farben nein — ein Chat
oder Forum zeigt sie ohnehin nicht), als HTML für das Fenster.

Die Farben sind gerechnet, je eine Reihe für dunklen und hellen Grund,
gegen den echten Grund des Textfelds (``Base``: #2d2d2d dunkel, #ffffff
hell): dunkel 5,6–8,1:1, hell 4,9–6,5:1 — alle über 4,5:1 für Text.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from poe_view.services import passive_tree
from poe_view.services.passive_tree import (DEFENCE, JEWEL, KEYSTONE, MASTERY, MINIONS,
                                            NOTABLE, OFFENCE, OTHER, START, UTILITY, Tree)

# Symbol je Thema und je Abschnitt — im Markdown wie im HTML.
SYMBOL = {DEFENCE: "🛡", MINIONS: "💀", OFFENCE: "⚔", UTILITY: "✦", OTHER: "•",
          "ascendancy": "👑", "keystone": "🔑", "mastery": "✪", "jewel": "💎",
          "totals": "📊", "gain": "▲", "loss": "▼", "refund": "↩", "allocate": "＋",
          "reach": "🧭"}

_DUNKEL = {DEFENCE: "#7cc86a", MINIONS: "#c39bea", OFFENCE: "#f08a6e", UTILITY: "#6cb6f0",
           OTHER: "#b0b0b0", "ascendancy": "#e6c35c", "keystone": "#e6c35c",
           "gain": "#7cc86a", "loss": "#f08a6e"}
_HELL = {DEFENCE: "#2e7d32", MINIONS: "#7b3fb5", OFFENCE: "#c0392b", UTILITY: "#1565c0",
         OTHER: "#5f5f5f", "ascendancy": "#8a6d00", "keystone": "#8a6d00",
         "gain": "#2e7d32", "loss": "#c0392b"}


def colour(key: str, dark: bool) -> str | None:
    return (_DUNKEL if dark else _HELL).get(key)


@dataclass
class Line:
    """Eine Listenzeile: fetter Name (darf leer sein), Text, und ein
    Schlüssel für die Farbe des Namens (Thema, "gain", …)."""
    name: str
    text: str = ""
    key: str = ""


@dataclass
class Block:
    title: str
    level: int = 3
    key: str = ""               # Farbe und Symbol der Überschrift
    paragraphs: list[str] = field(default_factory=list)
    items: list[Line] = field(default_factory=list)
    # Im Fenster: Zeilen in so vielen Spalten (die Summen, sonst eine
    # Textwand); im Markdown immer eine Zeile je Eintrag.
    columns: int = 1


def _stats(stats) -> str:
    return "; ".join(stats) or "—"


# --- Bausteine ------------------------------------------------------------ #

def _by_theme(nodes):
    gruppen: dict[str, list] = {}
    for n in nodes:
        gruppen.setdefault(passive_tree.theme(n), []).append(n)
    return [(t, sorted(gruppen[t], key=lambda n: n.name))
            for t in passive_tree.THEMES if t in gruppen]


def _counts(gruppen) -> str:
    return ", ".join(f"{len(g)} {t}" for t, g in gruppen)


# Was zuerst stehen soll: Peters Beispiel "120% increased Damage, +95 max.
# Life" — die Werte, nach denen man den Baum beurteilt. Alles Übrige folgt
# alphabetisch nach dem ersten Wort.
_ZUERST = [re.compile(m, re.I) for m in (
    # Minion-Zeilen stehen nur unter Minions — ihre Muster zuerst, sonst
    # zöge "Golems have 30% increased Maximum Life" vor "Minions deal".
    r"^minions deal", r"^minions have .*maximum life", r"maximum number",
    r"maximum life", r"energy shield", r"all elemental resistances",
    r"(fire|cold|lightning) resistance", r"chaos resistance", r"armour|evasion",
    r"block", r"regenerate|recoup|leech",
    r"increased damage", r"attack speed|cast speed", r"critical")]


def _rang(zeile: str) -> int:
    return next((i for i, m in enumerate(_ZUERST) if m.search(zeile)), len(_ZUERST))


def totals_blocks(tree: Tree, passives: dict) -> list[Block]:
    """Die Gesamtwerte aller vergebenen Knoten — kleine, Notables,
    Keystones, Aszendenz, gewählte Masteries — nach Wortlaut
    zusammengezählt, je Thema ein Block, die wichtigsten Werte vorn.
    Jewels zählen nicht mit: deren Werte stehen im Jewel-Abschnitt, und ein
    Jewel mit "Radius" änderte die Knoten selbst — das rechnet nur das
    Spiel."""
    summen = passive_tree.summed_stats(passive_tree.all_stats(tree, passives))
    bloecke = []
    for thema in passive_tree.THEMES:
        teil = [z for z in summen if passive_tree.line_theme(z) == thema]
        if teil:
            teil = sorted(teil, key=_rang)          # stabil: innen bleibt das Alphabet
            bloecke.append(Block(f"{thema} ({len(teil)})", level=4, key=thema, columns=3,
                                 items=[Line("", z) for z in teil]))
    return bloecke


def tree_blocks(entry: dict | None, tree: Tree | None, *, character_class: str,
                jewels: list[tuple[str, list[str]]] = (),
                include_reach: bool = True) -> list[Block]:
    kopf = Block("Passive tree", level=2)
    if not entry:
        kopf.paragraphs.append("*Not known yet — it arrives with the next refresh of this "
                               "character.*")
        return [kopf]
    passives = entry.get("passives") or {}
    have = passive_tree.allocated(passives)
    if tree is None:
        kopf.paragraphs.append(f"*{len(have)} nodes allocated. GGG's tree data has not been "
                               "downloaded yet, so their names and values are missing — try "
                               "again in a minute.*")
        return [kopf]

    knoten = [tree.nodes[h] for h in sorted(have) if h in tree.nodes]
    unbekannt = len(have) - len(knoten)
    aszendenz = [n for n in knoten if n.ascendancy and n.kind != START]
    normal = [n for n in knoten if not n.ascendancy and n.kind != START]
    kleine = [n for n in normal if n.kind not in (NOTABLE, KEYSTONE, JEWEL, MASTERY)]
    cluster = len(passives.get("hashes_ex") or ())
    level = entry.get("level") or 0

    zeile = (f"{'Ruthless' if tree.ruthless else 'Standard'} tree · "
             f"{len(normal)} points allocated · {len(aszendenz)} ascendancy points")
    if cluster:
        zeile += f" · {cluster} cluster jewel nodes"
    kopf.paragraphs.append(zeile)
    if level:
        kopf.paragraphs.append(f"Level {level} gives {level - 1} points from levels, plus "
                               "quest rewards (the API does not report those).")
    extras = []
    if passives.get("bandit_choice"):
        extras.append(f"Bandit: {passives['bandit_choice']}")
    if passives.get("pantheon_major"):
        extras.append(f"Pantheon: {passives['pantheon_major']}"
                      + (f" / {passives['pantheon_minor']}" if passives.get("pantheon_minor")
                         else ""))
    if extras:
        kopf.paragraphs.append(" · ".join(extras))
    if unbekannt:
        kopf.paragraphs.append(f"*{unbekannt} allocated nodes are missing from GGG's tree data "
                               "(the download may be older than the last patch).*")
    bloecke = [kopf]

    summen = totals_blocks(tree, passives)
    if summen:
        bloecke.append(Block(f"Totals (all {len(knoten)} allocated nodes)", key="totals"))
        bloecke += summen

    if aszendenz:
        bloecke.append(Block(f"Ascendancy ({character_class})", key="ascendancy",
                             items=[Line(n.name, _stats(n.stats), "ascendancy")
                                    for n in sorted(aszendenz, key=lambda n: n.name)]))
    keystones = [n for n in normal if n.kind == KEYSTONE]
    if keystones:
        bloecke.append(Block("Keystones", key="keystone",
                             items=[Line(n.name, _stats(n.stats), "keystone")
                                    for n in sorted(keystones, key=lambda n: n.name)]))
    notables = [n for n in normal if n.kind == NOTABLE]
    if notables:
        gruppen = _by_theme(notables)
        bloecke.append(Block(f"Notables ({len(notables)}): {_counts(gruppen)}"))
        for thema, gruppe in gruppen:
            bloecke.append(Block(f"{thema} ({len(gruppe)})", level=4, key=thema,
                                 items=[Line(n.name, _stats(n.stats), thema) for n in gruppe]))

    wahl = passive_tree.mastery_choices(passives)
    masteries = []
    for knoten_id, effekt in sorted(wahl.items()):
        mastery = tree.nodes.get(knoten_id)
        if mastery is not None and mastery.kind == MASTERY:
            werte = mastery.effects.get(effekt, ())
            masteries.append(Line(mastery.name, _stats(werte),
                                  passive_tree.theme(passive_tree.Node(0, "", MASTERY, werte))))
    if masteries:
        bloecke.append(Block("Masteries", key="mastery",
                             items=sorted(masteries, key=lambda i: i.name)))

    sockel = [n for n in normal if n.kind == JEWEL]
    if sockel or jewels:
        block = Block(f"Jewels ({len(sockel)} sockets allocated)", key="jewel",
                      items=[Line(name, _stats(mods)) for name, mods in jewels])
        if not jewels:
            block.paragraphs.append("*No jewels socketed.*")
        bloecke.append(block)
    if kleine:
        bloecke[0].paragraphs.append(f"{len(kleine)} small passives — their values are in the "
                                     "totals.")

    if include_reach:
        bloecke += reach_blocks(tree, have, character_class)
    return bloecke


def reach_groups(tree: Tree, have: set[int], character_class: str):
    """(Titel, Farbschlüssel, [Reach, …]): Keystones, Jewel-Sockel, dann
    die Notables nach Thema; innen nach Punkten (§4.60.2)."""
    alle = passive_tree.within_reach(tree, have, class_name=character_class)
    gruppen = [("Keystones", "keystone", [r for r in alle if r.node.kind == KEYSTONE]),
               ("Jewel sockets", "jewel", [r for r in alle if r.node.kind == JEWEL])]
    notables = [r for r in alle if r.node.kind == NOTABLE]
    for thema in passive_tree.THEMES:
        gruppen.append((thema, thema,
                        [r for r in notables if passive_tree.theme(r.node) == thema]))
    return [(titel, key, sorted(liste, key=lambda r: (r.cost, r.node.name)))
            for titel, key, liste in gruppen if liste]


def reach_text(r) -> str:
    punkte = "point" if r.cost == 1 else "points"
    weg = f" via {', '.join(n.name for n in r.via)}" if r.via else ""
    werte = _stats(r.node.stats) if r.node.stats else (
        "empty socket" if r.node.kind == JEWEL else "—")
    return f"· {r.cost} {punkte}{weg} — {werte}"


def reach_blocks(tree: Tree, have: set[int], character_class: str) -> list[Block]:
    gruppen = reach_groups(tree, have, character_class)
    kopf = Block(f"Within reach (up to {passive_tree.REACH_POINTS} more points): "
                 + (", ".join(f"{len(g)} {t}" for t, _k, g in gruppen) or "nothing"),
                 key="reach")
    if not gruppen:
        kopf.paragraphs.append("*Nothing notable within reach.*")
        return [kopf]
    return [kopf] + [Block(f"{titel} ({len(g)})", level=4, key=key,
                           items=[Line(r.node.name, reach_text(r), key) for r in g])
                     for titel, key, g in gruppen]


_ERSTE_ZAHL = re.compile(r"(?<!\w)([+-])\d")


def is_gain(line: str) -> bool:
    """Gewinn nach dem Vorzeichen der ersten Zahl — es steht vorn ("+5% to
    X") oder an der Stelle der Zahl ("Regenerate +1% ...")."""
    if line.startswith("gained: "):
        return True
    treffer = _ERSTE_ZAHL.search(line)
    return treffer is not None and treffer.group(1) == "+"


def used_points(tree: Tree, passives: dict) -> tuple[int, int, int]:
    """(Punkte gesamt, davon in Cluster-Jewels, Aszendenz-Punkte). Knoten
    in Cluster-Jewels kosten im Spiel einen Punkt wie jeder andere."""
    cluster = len((passives or {}).get("hashes_ex") or ())
    aszendenz = sum(1 for h in passive_tree.allocated(passives)
                    if h in tree.nodes and tree.nodes[h].ascendancy
                    and tree.nodes[h].kind != START)
    return passive_tree.main_points(tree, passives) + cluster, cluster, aszendenz


def points_text(tree: Tree, passives: dict, compare_to: dict | None = None, *,
                level: int | None = None, bandit: str | None = None) -> str:
    """"Points used: 101 (3 in cluster jewels) · max 113 at level 90 ·
    ascendancy 8", beim Vergleich mit dem aktuellen Baum dahinter, wo er
    abweicht; ohne Level kein Höchstwert."""
    gesamt, cluster, aszendenz = used_points(tree, passives)
    text = f"Points used: {gesamt}"
    if cluster:
        text += f" ({cluster} in cluster jewels)"
    vorher = used_points(tree, compare_to) if compare_to is not None else None
    if vorher and vorher[0] != gesamt:
        text += f", current tree {vorher[0]}"
    if level:
        text += f" · max {passive_tree.max_points(level, bandit)} at level {level}"
    text += f" · ascendancy {aszendenz}"
    if vorher and vorher[2] != aszendenz:
        text += f", current tree {vorher[2]}"
    return text


def gold_text(umbau, level: int | None) -> str:
    """" · about 11,256 gold at level 81" — leer ohne Level (§4.60.7)."""
    gold = umbau.gold(level) if level else None
    if gold is None or not (umbau.points or umbau.ascendancy_points):
        return ""
    return f" · about {gold:,} gold at level {level}"


def respec_blocks(tree: Tree, current: dict, target: dict, *, title: str,
                  level: int | None = None) -> list[Block]:
    """Der Umbau als Arbeitsliste für den Baum im Spiel (§4.60.1); mit
    ``level`` samt Goldpreis (§4.60.7)."""
    umbau = passive_tree.compare(tree, current, target)
    kopf = Block(title, level=2)
    if not (umbau.refund or umbau.allocate or umbau.masteries):
        kopf.paragraphs.append("*Same tree — nothing to change.*")
        return [kopf]
    kopf.paragraphs.append(
        f"{umbau.points} {'point' if umbau.points == 1 else 'points'} to refund in the main tree"
        + (" (plus ascendancy changes)" if any(n.ascendancy for n in
                                               umbau.refund + umbau.allocate) else "")
        + gold_text(umbau, level)
        # Was ein Mastery-Wechsel kostet, steht in keiner belegten Quelle.
        + (" (mastery changes not priced)" if umbau.masteries and gold_text(umbau, level)
           else ""))
    bloecke = [kopf]

    def knoten(n) -> Line:
        art = {KEYSTONE: "keystone", NOTABLE: "notable", JEWEL: "jewel socket"}.get(n.kind, "")
        zusatz = f" ({'ascendancy ' if n.ascendancy else ''}{art})" if art or n.ascendancy else ""
        # "(notable) — Werte"; ohne Art nur die Werte — sonst stünde der
        # Gedankenstrich doppelt da ("Life — — 5% ...", im Test gesehen).
        # Ohne Themenfarbe: Grün und Rot stehen hier für Gewinn und
        # Verlust — ein roter Angriffs-Knoten unter "Allocate" las sich
        # wie ein Verlust (nativ gesehen).
        return Line(n.name, f"{zusatz.strip()} — {_stats(n.stats)}" if zusatz else _stats(n.stats))

    gewinne = sorted((z for z in umbau.stats if is_gain(z)), key=_rang)
    verluste = sorted((z for z in umbau.stats if not is_gain(z)), key=_rang)
    if gewinne:
        bloecke.append(Block(f"Gains ({len(gewinne)})", key="gain",
                             items=[Line("", z, "gain") for z in gewinne]))
    if verluste:
        bloecke.append(Block(f"Losses ({len(verluste)})", key="loss",
                             items=[Line("", z, "loss") for z in verluste]))
    if umbau.refund:
        bloecke.append(Block(f"Refund ({len(umbau.refund)})", key="refund",
                             items=[knoten(n) for n in umbau.refund]))
    if umbau.allocate:
        bloecke.append(Block(f"Allocate ({len(umbau.allocate)})", key="allocate",
                             items=[knoten(n) for n in umbau.allocate]))
    if umbau.masteries:
        bloecke.append(Block("Change mastery", key="mastery",
                             items=[Line(m.name, f"{_stats(alt)} → {_stats(neu)}")
                                    for m, alt, neu in umbau.masteries]))
    return bloecke


# --- Ausgabe -------------------------------------------------------------- #

def _heading(block: Block) -> str:
    symbol = SYMBOL.get(block.key, "")
    return f"{symbol} {block.title}" if symbol else block.title


def to_markdown(bloecke: list[Block]) -> list[str]:
    zeilen: list[str] = []
    for b in bloecke:
        zeilen += [f"{'#' * b.level} {_heading(b)}", ""]
        for absatz in b.paragraphs:
            zeilen += [absatz, ""]
        for item in b.items:
            if item.name and item.text.startswith(("·", "(")):
                zeilen.append(f"- **{item.name}** {item.text}")
            elif item.name:
                zeilen.append(f"- **{item.name}** — {item.text}" if item.text
                              else f"- **{item.name}**")
            else:
                zeilen.append(f"- {item.text}")
        if b.items:
            zeilen.append("")
    return zeilen


def _md_inline(text: str) -> str:
    """Das bisschen Markdown in den Absätzen (*kursiv*) als HTML."""
    text = html.escape(text)
    return re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)


def to_html(bloecke: list[Block], *, dark: bool) -> str:
    groesse = {2: "130%", 3: "112%", 4: "100%"}
    teile = []
    for b in bloecke:
        farbe = colour(b.key, dark)
        stil = f"color:{farbe};" if farbe else ""
        teile.append(f"<p style='margin:10px 0 3px 0; font-weight:600; "
                     f"font-size:{groesse.get(b.level, '100%')}; {stil}'>"
                     f"{html.escape(_heading(b))}</p>")
        for absatz in b.paragraphs:
            teile.append(f"<p style='margin:1px 0;'>{_md_inline(absatz)}</p>")
        if b.items and b.columns > 1:
            # Spaltenweise füllen: von oben nach unten, dann nach rechts —
            # so bleiben die vorn sortierten Werte in der ersten Spalte oben.
            hoehe = -(-len(b.items) // b.columns)
            teile.append("<table cellspacing='0' cellpadding='1' width='100%' "
                         "style='margin-left:14px;'>")
            for zeile in range(hoehe):
                zellen = []
                for spalte in range(b.columns):
                    i = spalte * hoehe + zeile
                    text = html.escape(b.items[i].text) if i < len(b.items) else ""
                    zellen.append(f"<td width='{100 // b.columns}%' "
                                  f"style='padding:1px 12px 1px 0;'>{text}</td>")
                teile.append("<tr>" + "".join(zellen) + "</tr>")
            teile.append("</table>")
        elif b.items:
            teile.append("<table cellspacing='0' cellpadding='1' style='margin-left:14px;'>")
            for item in b.items:
                farbe = colour(item.key, dark)
                name_stil = f" style='color:{farbe};'" if farbe else ""
                text = html.escape(item.text)
                if item.name:
                    trenner = " " if item.text.startswith(("·", "(")) else " — "
                    inhalt = (f"<b{name_stil}>{html.escape(item.name)}</b>"
                              + (trenner + text if item.text else ""))
                else:
                    inhalt = f"<span{name_stil}>{text}</span>"
                teile.append(f"<tr><td style='padding:1px 0;'>{inhalt}</td></tr>")
            teile.append("</table>")
    return "<html><body>" + "\n".join(teile) + "</body></html>"
