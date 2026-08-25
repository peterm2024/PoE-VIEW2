"""Tests der Balkenspalte vor den Mod-Zeilen (§4.52.2).

Der Kern fast aller Faelle hier ist derselbe: **Die Spalte ist immer
gleich breit.** Sie ist der Grund, warum es ueberhaupt eine gezeichnete
Spalte gibt statt eines Balkens aus Zeichen — 23,6 % der Mod-Zeilen haben
nichts zum Vergleichen und brauchen trotzdem exakt dieselbe Luecke.
"""

from poe_view.api.models import Item
from poe_view.services.mod_collection import (LEGACY_LEAGUE,
                                              MIN_LEAGUE_OBSERVATIONS,
                                              ModCollection)
from poe_view.ui import mod_bar


def _zellen(html: str) -> int:
    """Wie viele Zellen belegt diese Spalte? Gezaehlt wird das geschuetzte
    Leerzeichen, egal ob gefaerbt oder nicht."""
    return html.count(mod_bar.CELL)


def _ring(**kwargs) -> Item:
    return Item.model_validate({"typeLine": "Gold Ring", "frameType": 2,
                                "league": "Standard", **kwargs})


def _sammlung(werte, *, rarity: int = 2, league: str = LEGACY_LEAGUE,
              zeile: str = "+{} to maximum Life") -> ModCollection:
    sammlung = ModCollection()
    for wert in werte:
        sammlung.observe("explicitMods", zeile.format(wert),
                         rarity=rarity, league=league)
    sammlung.clear_new()
    return sammlung


# ------------------------------ Fuellstand ----------------------------- #

def test_the_bar_is_empty_at_the_bottom_and_full_at_the_top() -> None:
    assert mod_bar.fill_cells(0.0) == 0
    assert mod_bar.fill_cells(1.0) == mod_bar.BAR_CELLS


def test_a_near_best_roll_is_not_shown_as_the_best() -> None:
    """Die eine Aussage, die der Balken hart trifft, ist "der beste Roll,
    den diese Sammlung kennt". Ohne die Klemmung saehe 0,97 genauso aus —
    und dann traefe er sie nicht mehr."""
    assert mod_bar.fill_cells(0.97) == mod_bar.BAR_CELLS - 1
    assert mod_bar.fill_cells(0.999) == mod_bar.BAR_CELLS - 1


def test_a_barely_better_than_worst_roll_is_not_shown_as_the_worst() -> None:
    """Dieselbe Klemmung am unteren Rand: Ein leerer Balken heisst "der
    schlechteste, den ich kenne", nicht "fast der schlechteste"."""
    assert mod_bar.fill_cells(0.01) == 1
    assert mod_bar.fill_cells(0.02) == 1


def test_the_middle_is_the_middle() -> None:
    assert mod_bar.fill_cells(0.5) == mod_bar.BAR_CELLS // 2


# ------------------------- Immer gleiche Breite ------------------------ #

def test_every_column_has_the_same_number_of_cells() -> None:
    """Der Grund fuer die ganze Bauweise. Eine Spalte, die je nach Inhalt
    schmaler wird, verschoebe den Textanfang von Zeile zu Zeile."""
    breiten = {_zellen(mod_bar.bar_html(anteil))
               for anteil in (0.0, 0.1, 0.5, 0.9, 1.0)}
    breiten.add(_zellen(mod_bar.blank_html()))

    assert breiten == {mod_bar.BAR_CELLS + 2}, breiten


def test_the_first_find_keeps_the_column_width_too() -> None:
    """Das Zeichen ist breiter als eine Zelle, deshalb weniger
    Auffuellung. Gemessen ueber 8 bis 14 pt trifft es die Spaltenbreite
    auf +-1 px — hier wird die Regel geprueft, nicht die Pixel: Zeichen
    plus Auffuellung plus Abstand."""
    assert mod_bar.NEW_MARK in mod_bar.new_html()
    assert _zellen(mod_bar.new_html()) == len(mod_bar.NEW_PAD) + 2


def test_an_empty_column_carries_no_colour() -> None:
    """Kein Vergleich heisst kein Balken — und schon gar kein leerer, der
    sich als "schlechtester Roll" lesen liesse."""
    assert "background-color" not in mod_bar.blank_html()


# ----------------------------- Farbe/Grundlage ------------------------- #

def test_the_two_pots_get_different_colours() -> None:
    """Die Grundlage gehoert zur Aussage: gegen den eigenen Topf gemessen
    oder gegen den gemischten Altbestand."""
    assert mod_bar.COLOR_FILL in mod_bar.bar_html(0.5, own_pot=True)
    assert mod_bar.COLOR_FILL_LEGACY in mod_bar.bar_html(0.5, own_pot=False)
    assert mod_bar.COLOR_FILL != mod_bar.COLOR_FILL_LEGACY


def test_a_full_bar_has_no_track_left() -> None:
    voll = mod_bar.bar_html(1.0)
    assert mod_bar.COLOR_TRACK not in voll
    assert _zellen(voll) == mod_bar.BAR_CELLS + 2


def test_an_empty_bar_is_all_track() -> None:
    leer = mod_bar.bar_html(0.0)
    assert mod_bar.COLOR_TRACK in leer
    assert mod_bar.COLOR_FILL not in leer


# ------------------------------ mark_for ------------------------------- #

def test_a_line_the_collection_does_not_know_gets_a_gap() -> None:
    spalte = mod_bar.mark_for(ModCollection(), _ring())
    assert spalte("explicitMods", "+96 to maximum Life") == mod_bar.blank_html()


def test_a_first_sighting_gets_the_find_mark() -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=2)

    spalte = mod_bar.mark_for(sammlung, _ring())
    assert spalte("explicitMods", "+96 to maximum Life") == mod_bar.new_html()


def test_a_thin_span_gets_no_bar() -> None:
    """Unter ``MIN_BAR_OBSERVATIONS`` Sichtungen bleibt die Spalte leer —
    zwei Rolls sehen als Skala aus wie zweihundert."""
    duenn = _sammlung(range(41, 41 + mod_bar.MIN_BAR_OBSERVATIONS - 1))
    dicht = _sammlung(range(41, 41 + mod_bar.MIN_BAR_OBSERVATIONS))

    assert (mod_bar.mark_for(duenn, _ring())("explicitMods", "+41 to maximum Life")
            == mod_bar.blank_html())
    assert (mod_bar.mark_for(dicht, _ring())("explicitMods", "+41 to maximum Life")
            != mod_bar.blank_html())


def test_a_mod_without_numbers_gets_no_bar() -> None:
    """"Has 1 Socket" hat eine Zahl, "Corrupted" keine. Ohne Zahl gibt es
    nichts zu vergleichen."""
    sammlung = ModCollection()
    for _ in range(20):
        sammlung.observe("explicitMods", "Cannot be Frozen", rarity=2)
    sammlung.clear_new()

    spalte = mod_bar.mark_for(sammlung, _ring())
    assert spalte("explicitMods", "Cannot be Frozen") == mod_bar.blank_html()


def test_the_bar_falls_back_to_the_old_stock_and_says_so() -> None:
    """Ein Item aus einer temporaeren Liga, in der die Zeile noch zu
    selten vorkam: verglichen wird gegen den Altbestand, und der Balken
    zeigt es im Farbton."""
    sammlung = _sammlung(range(41, 97))          # nur Altbestand

    spalte = mod_bar.mark_for(sammlung, _ring(league="Allflame"))
    assert spalte("explicitMods", "+96 to maximum Life") == mod_bar.bar_html(
        1.0, own_pot=False)


def test_enough_sightings_in_the_league_win_the_full_colour() -> None:
    genug = max(MIN_LEAGUE_OBSERVATIONS, mod_bar.MIN_BAR_OBSERVATIONS)
    sammlung = _sammlung(range(41, 97))
    for wert in range(60, 60 + genug):
        sammlung.observe("explicitMods", f"+{wert} to maximum Life",
                         rarity=2, league="Allflame")
    sammlung.clear_new()

    spalte = mod_bar.mark_for(sammlung, _ring(league="Allflame"))
    assert spalte("explicitMods", f"+{60 + genug - 1} to maximum Life") == (
        mod_bar.bar_html(1.0, own_pot=True))


def test_the_column_never_carries_the_mod_text() -> None:
    """Die Spalte wird ausschliesslich aus eigenen Konstanten gebaut. Kaeme
    Text von GGGs Server hinein, ginge er als HTML ungeprueft durch — die
    Marke wird beim Zusammensetzen bewusst NICHT escaped
    (``item_detail.Line``)."""
    boese = "+96 to <b>maximum</b> Life"
    sammlung = ModCollection()
    for wert in range(41, 97):
        sammlung.observe("explicitMods", f"+{wert} to <b>maximum</b> Life", rarity=2)
    sammlung.clear_new()

    spalte = mod_bar.mark_for(sammlung, _ring())(("explicitMods"), boese)
    assert "<b>" not in spalte
    assert "maximum" not in spalte


# ------------------- Der Balken muss bei SEINER Zeile stehen ----------- #

def _block_of(html: str, text: str):
    """Der Textblock, in dem ``text`` steht — samt der Frage, ob in
    demselben Block etwas Gefaerbtes liegt."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextDocument

    doc = QTextDocument()
    doc.setHtml(html)
    block = doc.begin()
    while block.isValid():
        if text in block.text():
            gefaerbt = False
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                # Gegen das Enum vergleichen, nicht gegen 0: PySide6-Enums
                # sind keine ints, und ``!= 0`` waere immer wahr.
                if (fragment.isValid()
                        and fragment.charFormat().background().style()
                        != Qt.BrushStyle.NoBrush):
                    gefaerbt = True
                it += 1
            return block.text(), gefaerbt
        block = block.next()
    return None, False


def test_the_bar_lands_in_the_same_block_as_its_mod_line(qapp) -> None:
    """Qt schneidet fuehrenden Leerraum am Blockanfang weg, und ein
    gefaerbtes ``<span>`` aus lauter geschuetzten Leerzeichen ist genau
    das. Die erste Mod-Zeile nach einer Trennlinie bekam ihren Balken
    dadurch in den Block DAVOR — der Balken eine Zeile zu hoch, der Text
    daneben nicht eingerueckt (FALLSTRICKE #77).

    Geprueft am geparsten Dokument statt an Pixeln: Die Frage ist, in
    welchem BLOCK die Faerbung landet, und die haengt nicht an der
    Schrift."""
    from poe_view.ui.item_detail import Line, _blocks_to_html

    html = _blocks_to_html([[Line("iLvl 60")],
                            [Line("30% increased Global Critical Strike Chance",
                                  mod_bar.bar_html(0.5))]])

    davor, davor_gefaerbt = _block_of(html, "iLvl 60")
    eigener, eigener_gefaerbt = _block_of(html, "30% increased Global")

    assert eigener is not None
    assert eigener_gefaerbt, "der Balken gehoert in den Block seiner Mod-Zeile"
    assert not davor_gefaerbt, "und nicht in den davor"


def test_every_column_starts_with_the_zero_width_guard() -> None:
    """Die Regel, die den Fall oben verhindert — an einer Stelle, an der
    sie beim Umbauen auffaellt."""
    for spalte in (mod_bar.bar_html(0.5), mod_bar.bar_html(1.0),
                   mod_bar.new_html(), mod_bar.blank_html()):
        assert spalte.startswith(mod_bar.BLOCK_START)

