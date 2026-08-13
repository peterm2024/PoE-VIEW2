"""Tests fuer den XP/h-Verlauf im Leveling-Feld (Peter, 2026-08-13: "Wir
zeichnen einen Graph ueber die letzten 3 Stunden ... Die berechnete XP/h
des letzten Abschnitts schreiben wir einfach in den Graph") —
ARCHITEKTUR.md §4.40.

Geprueft wird die Geometrie, nicht das Bild: ``graph_layout`` rechnet
ohne Qt, ein Fehler darin waere in einer Zeichenroutine sonst nur mit
dem Auge zu finden.
"""

import pytest

from poe_view.ui.xp_graph import (GRAPH_SPAN_S, XpGraph, XpPoint, axis_label,
                                  combined_rate, graph_layout,
                                  group_by_instance, visible_points)

WIDTH = 300.0
HEIGHT = 100.0


def _point(minuten_her: float, dauer_s: float, rate: float) -> XpPoint:
    """Ein Abschnitt, der vor ``minuten_her`` Minuten geendet hat. Die
    Uhr steht dabei fest auf 0 — ``now`` ist in allen Tests 0.0, alles
    Aeltere damit negativ."""
    return XpPoint(at=-minuten_her * 60.0, seconds=dauer_s, rate=rate)


def test_a_fresh_section_sits_at_the_right_edge() -> None:
    """Der Graph endet beim Jetzt. Eine Map, die gerade abgeschlossen
    wurde, gehoert also ganz rechts hin — dort schaut man zuerst."""
    layout = graph_layout([_point(0, 600, 120_000_000)], 0.0, WIDTH, HEIGHT)

    x, y, w, h, rate = layout.bars[0]
    assert x + w == pytest.approx(WIDTH)
    assert w == pytest.approx(600 / GRAPH_SPAN_S * WIDTH)   # zehn Minuten von drei Stunden
    assert h == pytest.approx(HEIGHT)                       # einziger Wert = Spitze
    assert rate == 120_000_000


def test_the_bar_width_is_the_time_the_section_took() -> None:
    """Peters Begruendung fuer das Zeitfenster: "Die meisten Gamer
    schliessen eine Map innerhalb von 5 Minuten ab." Genau dieser
    Unterschied soll sichtbar sein — eine lange Map ist ein breiterer
    Balken, nicht nur ein weiterer Punkt."""
    lang, kurz = graph_layout(
        [_point(20, 900, 50_000_000), _point(2, 120, 50_000_000)],
        0.0, WIDTH, HEIGHT).bars

    assert lang[2] == pytest.approx(kurz[2] * 7.5)          # 15 min gegen 2 min


def test_gaps_stay_empty_instead_of_being_connected() -> None:
    """Wo nichts gezeichnet ist, wurde keine Erfahrung gemacht — Pause,
    Stadt, Truhe sortieren. Eine durchgezogene Linie muesste dort etwas
    behaupten; die beiden Balken duerfen sich deshalb nicht beruehren."""
    frueh, spaet = graph_layout(
        [_point(120, 300, 40_000_000), _point(5, 300, 40_000_000)],
        0.0, WIDTH, HEIGHT).bars

    assert frueh[0] + frueh[2] < spaet[0]


def test_sections_older_than_the_window_drop_out() -> None:
    layout = graph_layout([_point(240, 600, 90_000_000), _point(10, 600, 30_000_000)],
                          0.0, WIDTH, HEIGHT)

    assert len(layout.bars) == 1
    assert layout.peak == 30_000_000        # der Vier-Stunden-Balken skaliert nicht mehr mit
    assert visible_points([_point(240, 600, 1.0)], 0.0) == []


def test_a_deadly_section_hangs_below_the_zero_line() -> None:
    """Ab Akt 5 kostet der Tod Erfahrung. Ein Abschnitt mit Verlust darf
    nicht wie ein magerer Gewinn aussehen (dieselbe Entscheidung wie bei
    ``_format_xp_rate``, das das Vorzeichen ebenfalls stehen laesst)."""
    layout = graph_layout([_point(30, 600, 100.0), _point(5, 600, -50.0)],
                          0.0, WIDTH, HEIGHT)
    gewinn, verlust = layout.bars

    assert layout.zero_y == pytest.approx(HEIGHT * 100 / 150)
    assert gewinn[1] + gewinn[3] == pytest.approx(layout.zero_y)   # endet auf der Null-Linie
    assert verlust[1] == pytest.approx(layout.zero_y)              # beginnt dort und faellt


def test_a_very_short_section_stays_visible() -> None:
    """Zwei Sekunden von drei Stunden sind ein Fuenfzigstel Pixel. Ohne
    Mindestbreite waere so ein Abschnitt unsichtbar — und ausgerechnet
    die kurzen Abschnitte tragen die hoechsten Raten."""
    x, _y, w, h, _rate = graph_layout([_point(0, 2, 900_000_000)],
                                      0.0, WIDTH, HEIGHT).bars[0]

    assert w >= 2.0
    assert x >= 0.0


def test_an_empty_history_draws_an_empty_axis() -> None:
    layout = graph_layout([], 0.0, WIDTH, HEIGHT)

    assert layout.bars == []
    assert layout.zero_y == HEIGHT          # Null-Linie unten, kein Balken darueber


def test_axis_label_is_coarser_than_the_number_next_to_it() -> None:
    """An der Achse steht die Groessenordnung, die genaue Zahl steht als
    Text im selben Feld ("119.2M XP/h"). Zweimal dieselbe Zahl
    verschieden genau nebeneinander liest sich wie ein Widerspruch."""
    assert axis_label(119_200_000) == "119M"
    assert axis_label(2_500_000_000) == "2.5B"
    assert axis_label(340_000) == "340K"
    assert axis_label(-1_000_000) == "-1M"


def test_the_widget_survives_a_paint_with_and_without_data(qapp) -> None:
    """Kein Bildvergleich, nur die Zusicherung, dass beide Faelle
    ueberhaupt durchlaufen — ein leerer Graph ist der Normalfall beim
    Start."""
    graph = XpGraph()
    graph.resize(300, 120)

    graph.clear()
    graph.render(graph.grab())

    graph.set_points([_point(20, 600, 12_000_000), _point(1, 300, -400_000)], 0.0)
    graph.render(graph.grab())

    assert len(graph._points) == 2


# --- Eine Map mit Unterbrechung (Peter, 2026-08-13) -------------------- #
#
# Sein echter Ablauf, Zahlen aus dem Log: 17:23:13 rein, 17:29:15 raus
# (+14.643.224 in 362 s = 145,6 Mio./h), 56 s im Hideout verkauft,
# 17:30:11 zurueck, 17:32:03 raus (+686.080 in 112 s = 22,1 Mio./h).
# Beide Male dieselbe Instanz 2308728564.

_MAP = "2308728564"
_VERKAUFSPAUSE = [
    XpPoint(at=-170.0, seconds=362.0, rate=145_600_000.0, instance=_MAP),
    XpPoint(at=0.0, seconds=112.0, rate=22_100_000.0, instance=_MAP),
]


def test_two_visits_to_one_map_form_a_group() -> None:
    assert [len(g) for g in group_by_instance(_VERKAUFSPAUSE)] == [2]


def test_two_maps_of_the_same_name_are_not_grouped() -> None:
    """Der Grund, warum es die Instanz-Kennung braucht: Zwei Maps
    gleichen Namens hintereinander sind zwei Maps. Am Zonennamen waeren
    sie nicht zu unterscheiden."""
    zwei = [XpPoint(at=-600.0, seconds=300.0, rate=1.0, instance="aaa"),
            XpPoint(at=0.0, seconds=300.0, rate=1.0, instance="bbb")]

    assert [len(g) for g in group_by_instance(zwei)] == [1, 1]


def test_without_an_instance_id_nothing_is_grouped() -> None:
    """Ohne die DEBUG-Zeile in der Client.txt steht jeder Aufenthalt fuer
    sich — lieber nicht gruppieren als falsch gruppieren."""
    ohne = [XpPoint(at=-600.0, seconds=300.0, rate=1.0),
            XpPoint(at=0.0, seconds=300.0, rate=1.0)]

    assert [len(g) for g in group_by_instance(ohne)] == [1, 1]


def test_the_combined_rate_weighs_by_time_not_by_section() -> None:
    """Ein Mittel UEBER die beiden Raten waere (145,6 + 22,1) / 2 = 83,9
    Mio./h — falsch, weil der erste Abschnitt dreimal so lang war. Richtig
    ist die Summe der Erfahrung durch die Summe der GESPIELTEN Zeit."""
    assert combined_rate(_VERKAUFSPAUSE) == pytest.approx(116_400_000, rel=0.001)
    assert combined_rate(_VERKAUFSPAUSE) != pytest.approx(83_850_000, rel=0.01)


def test_the_group_area_spans_the_break_and_sits_at_the_common_rate() -> None:
    """Peter: "Zusammenfassen will ich die beiden Balken nicht, weil hier
    sieht man wirklich schoen wann man raus und wieder rein ist und was
    das gekostet hat." Also bleiben die Balken einzeln, und die Flaeche
    dahinter spannt sich UEBER die Pause — genau die macht sie sichtbar."""
    layout = graph_layout(_VERKAUFSPAUSE, 0.0, WIDTH, HEIGHT)
    (gx, gy, gw, gh), = layout.groups
    erster, zweiter = layout.bars

    assert gx == pytest.approx(erster[0])              # beginnt am ersten Aufenthalt
    assert gx + gw == pytest.approx(zweiter[0] + zweiter[2])   # endet am zweiten
    assert gw > erster[2] + zweiter[2]                 # die Pause liegt dazwischen
    # Hoehe = gemeinsame Rate, also zwischen den beiden Balken.
    assert zweiter[3] < gh < erster[3]
    assert len(layout.bars) == 2                       # die Balken bleiben getrennt


def test_a_single_section_gets_no_area_behind_it() -> None:
    """Ein Rechteck deckungsgleich hinter einem einzelnen Balken waere
    reine Verdopplung."""
    layout = graph_layout([_VERKAUFSPAUSE[0]], 0.0, WIDTH, HEIGHT)

    assert layout.groups == []


def test_the_dashed_line_is_the_rate_over_everything_visible() -> None:
    """Sie steht ruhig, waehrend die einzelnen Abschnitte springen — und
    beantwortet damit, was ein einzelner Balken nicht kann: liege ich
    ueber oder unter meinem Schnitt?"""
    layout = graph_layout(_VERKAUFSPAUSE, 0.0, WIDTH, HEIGHT)

    assert layout.average == pytest.approx(combined_rate(_VERKAUFSPAUSE))
    assert layout.average_y is not None
    # Zwischen den beiden Balken, wie die Rate selbst.
    assert layout.bars[0][1] < layout.average_y < layout.bars[1][1]
