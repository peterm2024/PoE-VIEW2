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

**Was der Balken NICHT ist.** Kein Tier, kein Prozentsatz der echten
Wertespanne. Er zeigt die Lage innerhalb dessen, was durch Peters Hände
ging (``services/mod_collection.py``). Ein voller Balken heißt "der beste
Roll dieser Zeile, den diese Sammlung kennt" — das ist genau die Aussage,
die vorher der Stern ★ trug.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QColor

from poe_view.api.models import Item
from poe_view.services import mod_collection
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
             item: Item) -> Callable[[str, str], str]:
    """Die Spalten-Funktion für DIESES Item.

    Als Abschluss über das Item statt als Funktion mit fünf Argumenten:
    Der Vergleich braucht Rarität UND Liga, und beide gehören zum Item,
    nicht zur einzelnen Zeile. Ein Rare gegen die festen Werte eines
    Uniques zu messen ergäbe eine Zahl, die nichts bedeutet — und ein Roll
    aus der laufenden Liga gegen einen Altbestand, in dem Items aus
    mehreren Jahren liegen, eine, die etwas anderes bedeutet, als sie zu
    sagen scheint (§4.52)."""
    liga, rarity = mod_collection.item_buckets(item)

    def spalte(kind: str, line: str) -> str:
        if collection.is_new(kind, line):
            return new_html()
        eintrag = collection.get(kind, line)
        if eintrag is None:
            return blank_html()
        wert, grundlage, sichtungen = eintrag.rating_detail(line, rarity, liga)
        if wert is None or sichtungen < MIN_BAR_OBSERVATIONS:
            return blank_html()
        return bar_html(wert, own_pot=grundlage == liga)

    return spalte
