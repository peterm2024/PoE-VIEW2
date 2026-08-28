"""Die Balkenspalte vor den Mod-Zeilen: wo liegt dieser Roll in dem, was
die Sammlung bisher gesehen hat?

Peter, 2026-08-24: "Können wir hinter die Mods eine Progressbar machen,
die anzeigt, wo der Mod im Vergleich zu anderen liegt?" — und kurz
darauf, nachdem die Zeichen-Variante an ihren Grenzen sichtbar wurde:
"Oder wir nehmen keine Balkenzeichen sondern definieren hier eine extra
Spalte mit einem Rechteck und das wird prozentual gefüllt."

Der zweite Vorschlag ist der bessere, und zwar aus einem Grund, der sich
erst beim Messen zeigte: **Ein Balken aus Zeichen bekommt keine leeren
Zeilen hin.** 23,6 % aller Mod-Zeilen in Peters Bestand haben nichts zum
Vergleichen (nur ein einziger Wert je gesehen), und die brauchen eine
Lücke von exakt der Balkenbreite, sonst rutscht ihr Text nach links und
die Spalte franst aus. Kein Leerzeichen der Schrift hält dafür ein festes
Verhältnis zu den Blockzeichen — gemessen über 8 bis 14 pt schwankt es
zwischen 2,25 und 3,0 Blockbreiten. Ein *gezeichnetes* Rechteck aus
geschützten Leerzeichen mit Hintergrundfarbe hat das Problem nicht: Die
Spalte besteht IMMER aus derselben Zahl Zellen, gefärbt wird nur, was
gefüllt ist.

Gemessen im echten Windows-Qt (nicht offscreen, §FALLSTRICKE #55):
Die Spalte ist bei 9 pt 42 px breit, unabhängig vom Füllstand, und der
Text beginnt in jeder Zeile bei 48 px — auch in den Zeilen ohne Balken.

**Zwei Maßstäbe, und die Zeile sagt, welcher gilt.** Kennt die
Mod-Datenbank (§4.53) die echte Leiter der Zeile, misst der Balken gegen
DIE: voll heißt "der beste Roll, den das Spiel kennt", und hinter der
Zeile steht das Tier-Etikett (``tail_for``: ``T3``, in den Metallen des
Albums). Ohne Leiter — oder für einen Wert neben ihr — zeigt er wie
zuvor die Lage innerhalb dessen, was durch Peters Hände ging
(``services/mod_collection.py``): voll heißt dann "der beste Roll, den
diese Sammlung kennt", die Aussage, die vorher der Stern ★ trug. Das
Etikett ist der Unterschied — eine Zeile ohne Etikett hat keine Leiter.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QColor

from poe_view.api.models import Item, item_category
from poe_view.services import mod_collection
from poe_view.services.mod_collection import mod_identity, mod_values, tierable
from poe_view.services.mod_knowledge import tier_number
from poe_view.ui.theme import DASH_OK, DASH_WARN, blend

# Zellen der Spalte. Jede Zelle ist ein geschütztes Leerzeichen mit
# Hintergrundfarbe — 14 davon sind bei 9 pt 42 px, also gut ein Zehntel
# der Panelbreite, und geben eine Auflösung von rund 7 %. Mehr Zellen
# heißt feiner UND breiter; die Breite geht dem Text verloren (siehe
# ``item_detail._MAX_UNITS``: mit dieser Spalte deckt das Panel 93,0 %
# der Items ohne Abschneiden ab statt 94,2 %).
BAR_CELLS = 14

# Geschütztes Leerzeichen: Gewöhnliche fallen in HTML zusammen, damit
# gäbe es weder Spalte noch Lücke.
# (Als Escape geschrieben und nicht als Zeichen: Ein geschütztes
# Leerzeichen im Quelltext ist von einem gewöhnlichen nicht zu
# unterscheiden, und ein gewöhnliches würde die Spalte auflösen.)
CELL = "\u00a0"

# Abstand zwischen Spalte und Text.
GAP = CELL * 2

# Nullbreiten-Zwischenraum vor jeder Spalte, damit Qt sie am Blockanfang
# nicht wegschneidet — Begründung bei ``_column``.
BLOCK_START = "\u200b"

# Der Erstfund behält sein Zeichen statt einen Balken zu bekommen: Er hat
# ja nichts zum Vergleichen (eine erste Sichtung ergibt immer eine Spanne
# aus einem einzigen Wert). Ein goldener VOLLbalken war die naheliegende
# Alternative und wurde verworfen — er liest sich als "Maximum", und das
# ist beim Erstfund gerade die falsche Aussage.
NEW_MARK = "✦"

# Auffüllung hinter dem Erstfund-Zeichen, damit der Text auf derselben
# Höhe beginnt wie in den Balkenzeilen. Gemessen über 8 bis 14 pt: Das
# Zeichen plus zehn Zellen trifft die Spaltenbreite auf ±1 px genau.
NEW_PAD = CELL * 10

# Der Grund, gegen den hier gerechnet wird: **#2d2d2d, gemessen aus einem
# gegriffenen Panel** — nicht #1e1e1e, was ``QPalette.Window`` meldet. Der
# Rahmen des Detail-Panels (``QFrame.StyledPanel``) malt eine andere Rolle
# als die, die die Palette für das Fenster nennt. Die erste Fassung dieser
# Datei rechnete gegen die Palettenfarbe, und die Spur war im echten
# Panel mit ΔE 4,2 praktisch unsichtbar (siehe FALLSTRICKE #76).
PANEL_BG = "#2d2d2d"

# Der leere Teil der Spur. Leise, aber sichtbar: WCAG-Kontrast 1,55,
# CIEDE2000 9,5 gegen ``PANEL_BG``. Ohne sichtbare Spur wäre nicht zu
# erkennen, wie lang der Balken hätte werden können — ein halb gefüllter
# sähe aus wie ein kurzer.
COLOR_TRACK = "#4a4a4a"

# Die Füllung, in zwei Tönen — sie sagen, WORAUF der Vergleich steht.
# Voller Ton: gegen den eigenen Topf des Items gemessen. Gedämpft: Die
# eigene Liga hatte zu wenige Sichtungen, verglichen wurde gegen den
# Altbestand, in dem Items aus mehreren Jahren liegen (dieselbe
# Unterscheidung, die vorher ★ und ☆ trugen). Gerechnet gegen
# ``PANEL_BG``: CIEDE2000 zwischen den beiden Tönen 10,3 —
# unterscheidbar, ohne zu schreien; Kontrast 5,17 bzw. 3,58 gegen den
# Grund und ΔE 41,5 bzw. 30,9 gegen die Spur, der Balken bleibt also in
# beiden Tönen als Balken lesbar.
COLOR_FILL = DASH_OK
COLOR_FILL_LEGACY = blend(QColor(DASH_OK), QColor(PANEL_BG), 0.25).name()

# Gold für den Erstfund. Kontrast 6,3 gegen den Grund, ΔE 26,9 zur
# Füllung — als Fund erkennbar, ohne mit einem Balken verwechselt zu
# werden.
COLOR_NEW = DASH_WARN

# So viele Sichtungen braucht eine Spanne, bevor daraus ein Balken wird.
# Eigene Zahl, nicht ``mod_collection.MIN_LEAGUE_OBSERVATIONS``, auch
# wenn beide bei 5 stehen: Jene entscheidet, welcher TOPF den Vergleich
# trägt, diese, ob ein Vergleich überhaupt gezeigt wird. Kostet in Peters
# Bestand 0,8 % der Zeilen — und nimmt die heraus, bei denen zwei oder
# drei Rolls wie eine Skala aussähen.
MIN_BAR_OBSERVATIONS = 5

# Die T-Nummern hinter der Mod-Zeile (Stufe 3 der Mod-Datenbank,
# §4.53.4), in denselben Metallen wie im Album: T1 Gold, T2 Silber, T3
# Bronze, ab T4 schlichtes Grau — drei Metalle versteht jeder sofort,
# zehn Farbstufen niemand. Gerechnet gegen ``PANEL_BG`` (Skript im
# Scratchpad, 2026-08-28): Gold 8,0, Silber 8,6, Bronze 5,6, Grau 5,3.
# EINE Tabelle für Album und Item-Detail — ``mod_album`` liest sie hier.
TIER_COLORS = {1: "#e8c15a", 2: "#c8ccd4", 3: "#d09a6a"}
TIER_COLOR_REST = "#a8a8a8"

# Abstand zwischen Mod-Text und Etikett — geschützt, damit Qt ihn nicht
# an einem Umbruch verschluckt.
TIER_GAP = CELL * 2


def ladder_rating(ladder: list, value: float) -> float | None:
    """Wo liegt der Wert in der ECHTEN Spanne der Leiter — 0 ist die
    unterste Sprosse unten, 1 die oberste oben (der beste mögliche Roll).
    ``None`` für Werte neben der Leiter (gecraftet, Essenz, beeinflusst)
    und für eine entartete Leiter ohne Breite."""
    lo = min(step.low for step in ladder)
    hi = max(step.high for step in ladder)
    if hi <= lo or not lo <= value <= hi:
        return None
    return (value - lo) / (hi - lo)


def ladder_tiers(ladder: list, value: float, ilvl: int) -> list[str]:
    """Die T-Nummern, in die der Wert fällt — meist eine, bei
    überlappenden Sprossen mehrere (2 % der Sichtungen in Peters
    Bestand). Das Item-Level siebt Sprossen aus, die das Item noch gar
    nicht rollen kann; bleibt danach nichts übrig, gilt die ungesiebte
    Liste — die Leiter kann Lücken haben, das Item ist trotzdem echt."""
    treffer = [i for i, step in enumerate(ladder) if step.low <= value <= step.high]
    moeglich = [i for i in treffer if ladder[i].required_level <= ilvl]
    return sorted((tier_number(ladder, i) for i in (moeglich or treffer)),
                  key=lambda t: int(t[1:]))


def tier_label_html(tiers: list[str]) -> str:
    """``T3`` bzw. ``T2/T3`` als gefärbtes Etikett hinter der Zeile — in
    der Farbe des BESTEN Tiers. Leer ohne Tiers."""
    if not tiers:
        return ""
    farbe = TIER_COLORS.get(int(tiers[0][1:]), TIER_COLOR_REST)
    return f'{TIER_GAP}<span style="color:{farbe}">{"/".join(tiers)}</span>'


def _ladder_lookup(item: Item, knowledge) -> Callable[[str, str], list]:
    """Die Leiter zu einer Mod-Zeile DIESES Items — oder ``[]``.

    Dieselben Bedingungen wie beim Kontenbuch (§mod_collection.tierable):
    gerollte Affixe unkorrumpierter Magic-/Rare-Items mit bekanntem
    Item-Level, nur Explicit/Implicit, nur Zeilen mit genau einer Zahl."""
    ilvl = int(getattr(item, "ilvl", 0) or 0)
    _liga, rarity = mod_collection.item_buckets(item)
    kategorie = item_category(item) or ""
    aktiv = (knowledge is not None and kategorie
             and tierable(rarity, ilvl))

    def leiter(kind: str, line: str) -> list:
        if not aktiv or kind not in ("explicitMods", "implicitMods"):
            return []
        if len(mod_values(line)) != 1:
            return []
        return knowledge.ladder(mod_identity(line), kategorie)

    return leiter


def tail_for(item: Item, knowledge) -> Callable[[str, str], str]:
    """Die Etikett-Funktion für DIESES Item: ``(kind, line) -> HTML``,
    das HINTER die Mod-Zeile kommt (Peters Wahl, 2026-08-29: "hinter
    der Mod-Zeile"). Leer, wo keine Leiter bekannt ist oder der Wert
    neben ihr liegt — dort steht dann auch keine Behauptung."""
    leiter = _ladder_lookup(item, knowledge)
    ilvl = int(getattr(item, "ilvl", 0) or 0)

    def etikett(kind: str, line: str) -> str:
        ladder = leiter(kind, line)
        if not ladder:
            return ""
        return tier_label_html(ladder_tiers(ladder, mod_values(line)[0], ilvl))

    return etikett


def fill_cells(value: float, cells: int = BAR_CELLS) -> int:
    """Wie viele Zellen sind gefüllt?

    Die beiden Ränder sind reserviert: **ganz voll nur bei genau 1.0,
    ganz leer nur bei genau 0.0.** Ohne diese Klemmung sähe ein Roll bei
    0,97 aus wie der beste je gesehene — und genau diese Aussage ist die
    einzige, die der Balken hart trifft."""
    voll = round(value * cells)
    if voll >= cells and value < 1.0:
        voll = cells - 1
    if voll <= 0 and value > 0.0:
        voll = 1
    return max(0, min(cells, voll))


def _span(colour: str, zellen: int) -> str:
    return f'<span style="background-color:{colour}">{CELL * zellen}</span>'


def _column(inhalt: str) -> str:
    """Eine fertige Spalte — mit dem Nullbreiten-Zwischenraum davor.

    **Der ist nicht kosmetisch.** Qt schneidet am Anfang eines Blocks
    führenden Leerraum weg, und ein gefärbtes ``<span>``, das nur aus
    geschützten Leerzeichen besteht, ist für diese Regel genau das: Die
    erste Mod-Zeile nach einer Trennlinie bekam ihren Balken dadurch in
    den Block DAVOR gemalt — der Balken stand eine Zeile zu hoch, der
    Text daneben gar nicht eingerückt (FALLSTRICKE #77). Ein Zeichen
    ohne Breite davor macht den Leerraum zu Inhalt in der Mitte eines
    Blocks, und Qt lässt ihn stehen. Gemessen von 8 bis 14 pt: Breite
    0,00 px, in jeder Größe."""
    return BLOCK_START + inhalt


def bar_html(value: float, *, own_pot: bool = True,
             cells: int = BAR_CELLS) -> str:
    """Die Spalte für einen bewerteten Mod."""
    voll = fill_cells(value, cells)
    farbe = COLOR_FILL if own_pot else COLOR_FILL_LEGACY
    teile = []
    if voll:
        teile.append(_span(farbe, voll))
    if voll < cells:
        teile.append(_span(COLOR_TRACK, cells - voll))
    return _column("".join(teile) + GAP)


def new_html() -> str:
    """Die Spalte für einen Erstfund."""
    return _column(f'<span style="color:{COLOR_NEW}">{NEW_MARK}</span>'
                   f'{NEW_PAD}{GAP}')


def blank_html(cells: int = BAR_CELLS) -> str:
    """Die Spalte für alles ohne Vergleich — unsichtbar, aber genau so
    breit wie ein Balken. Das ist der ganze Grund für die gezeichnete
    Spalte (siehe Modulkopf)."""
    return _column(CELL * cells + GAP)


def mark_for(collection: mod_collection.ModCollection,
             item: Item, knowledge=None) -> Callable[[str, str], str]:
    """Die Spalten-Funktion für DIESES Item.

    Als Abschluss über das Item statt als Funktion mit fünf Argumenten:
    Der Vergleich braucht Rarität UND Liga, und beide gehören zum Item,
    nicht zur einzelnen Zeile. Ein Rare gegen die festen Werte eines
    Uniques zu messen ergäbe eine Zahl, die nichts bedeutet — und ein Roll
    aus der laufenden Liga gegen einen Altbestand, in dem Items aus
    mehreren Jahren liegen, eine, die etwas anderes bedeutet, als sie zu
    sagen scheint (§4.52).

    **Mit Mod-Wissen misst der Balken gegen die ECHTE Leiter** (§4.53.4):
    voll heißt dann "der beste Roll, den das Spiel kennt", nicht mehr
    "der beste, den diese Sammlung kennt" — und die Zeile trägt dann
    auch ihr T-Etikett (``tail_for``), das den Maßstab sichtbar macht.
    Der Erstfund behält sein ✦; wo keine Leiter bekannt ist oder der
    Wert neben ihr liegt, bleibt es beim Sichtungs-Vergleich."""
    liga, rarity = mod_collection.item_buckets(item)
    leiter = _ladder_lookup(item, knowledge)

    def spalte(kind: str, line: str) -> str:
        if collection.is_new(kind, line):
            return new_html()
        ladder = leiter(kind, line)
        if ladder:
            wert = ladder_rating(ladder, mod_values(line)[0])
            if wert is not None:
                return bar_html(wert, own_pot=True)
        eintrag = collection.get(kind, line)
        if eintrag is None:
            return blank_html()
        wert, grundlage, sichtungen = eintrag.rating_detail(line, rarity, liga)
        if wert is None or sichtungen < MIN_BAR_OBSERVATIONS:
            return blank_html()
        return bar_html(wert, own_pot=grundlage == liga)

    return spalte
