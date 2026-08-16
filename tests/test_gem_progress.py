"""Tests fuer die Gem-Fortschrittsbalken ueber dem XP-Graphen (Peter,
2026-08-13: "Dadurch sollte man gut erkennen können ob ein Gem fertig auf
Stufe 20 gelevelt ist") — ARCHITEKTUR.md §4.42.

Die Zustaende sind an Peters echtem Bestand abgezaehlt: 449 Sockel-Gems
ueber 16 Charaktere, davon 226 fertig, 65 mit vollem Balken und 157 am
Leveln. Die Rohform der Gem-Eintraege hier ist die von GGG.
"""

from poe_view.api.models import Item
from poe_view.ui.gem_progress import (GemProgressBar, gem_colour,
                                      gem_progress_of)
from poe_view.ui.theme import GEM_COLORS, GEM_COLOR_OTHER


def _item_with(*gems: dict) -> Item:
    return Item.model_validate({"typeLine": "Vaal Regalia", "socketedItems": list(gems)})


def _gem(name: str, level: str, colour: str = "S",
         progress: float | None = None) -> dict:
    # ``frameType`` 4 ist GGGs Kennzeichen fuer ein Gem — ohne das ist
    # es ein Jewel und gehoert nicht in den Streifen.
    gem: dict = {"typeLine": name, "colour": colour, "frameType": 4,
                 "properties": [{"name": "Level", "values": [[level, 0]]}]}
    if progress is not None:
        gem["additionalProperties"] = [
            {"name": "Experience", "values": [["1/2", 0]], "progress": progress}]
    return gem


def test_a_maxed_gem_is_recognised_from_the_level_text() -> None:
    """Die schwierigste Frage beantwortet GGG selbst: Die Stufe steht im
    Klartext als "20 (Max)". Ohne das muesste man Gem-Art und Hoechststufe
    kennen — ein Awakened-Gem ist bei 5 fertig, ein korrumpiertes kann bei
    21 stehen. In Peters Bestand fehlt genau diesen 226 Gems zugleich das
    Erfahrungsfeld."""
    fertig, = gem_progress_of([_item_with(_gem("Righteous Fire", "20 (Max)", "I"))])

    assert fertig.maxed is True
    assert fertig.ready is False
    assert fertig.progress == 1.0


def test_awakened_and_corrupted_gems_are_maxed_at_their_own_levels() -> None:
    """Nicht jedes Gem ist bei 20 fertig — in Peters Bestand stehen
    6 Gems bei "5 (Max)" und 23 bei "21 (Max)". Am Zahlenwert allein
    waere das nicht zu erkennen."""
    gems = gem_progress_of([_item_with(
        _gem("Awakened Burning Damage Support", "5 (Max)", "S"),
        _gem("Lifetap Support", "21 (Max)", "S"))])

    assert [g.maxed for g in gems] == [True, True]


def test_a_full_bar_below_max_means_it_waits_for_a_click() -> None:
    """Gems steigen in PoE nicht von selbst auf (poe-verhalten.md §4).
    Ein voller Balken unterhalb der Hoechststufe ist damit
    Charakterstaerke, die nur auf einen Mausklick wartet — 65 Stueck in
    Peters Bestand. Ohne eigene Markierung saehe das aus wie "fertig"."""
    wartend, = gem_progress_of([_item_with(_gem("Blood Rage", "16", "D", progress=1.0))])

    assert wartend.ready is True
    assert wartend.maxed is False
    assert "ready to level up" in wartend.tooltip


def test_a_levelling_gem_carries_its_progress() -> None:
    gem, = gem_progress_of([_item_with(_gem("Fire Trap", "17", "D", progress=0.93))])

    assert gem.progress == 0.93
    assert (gem.ready, gem.maxed) == (False, False)
    assert "93% to next" in gem.tooltip


def test_a_gem_without_any_evidence_stays_empty_instead_of_full() -> None:
    """Weder "(Max)" noch ein Erfahrungsfeld: Dann wissen wir nichts. Ein
    voller Balken hiesse "fertig" und waere eine Behauptung ohne
    Grundlage.

    In Peters Bestand tritt der Fall seit dem Jewel-Filter nicht mehr auf
    (448 Gems, keiner ohne Beleg) — der fruehere Einzelfall WAR das
    Abyss-Jewel im Guertel. Die Regel bleibt trotzdem: GGG darf jederzeit
    ein Gem ohne diese Felder liefern."""
    unklar, = gem_progress_of([_item_with(
        {"typeLine": "Seltsames Gem", "colour": "S", "frameType": 4})])

    assert unklar.progress == 0.0
    assert (unklar.ready, unklar.maxed) == (False, False)


def test_the_colours_follow_gggs_attribute_letters() -> None:
    """S/D/I sind Staerke/Geschick/Intelligenz. In Peters Bestand kommen
    zusaetzlich 3 Gems mit "G" und eines ganz ohne Farbe vor — die
    duerfen nicht in einer der drei Attributfarben landen."""
    assert gem_colour("S") == GEM_COLORS["S"]
    assert gem_colour("D") == GEM_COLORS["D"]
    assert gem_colour("I") == GEM_COLORS["I"]
    assert gem_colour("G") == GEM_COLOR_OTHER
    assert gem_colour("") == GEM_COLOR_OTHER


def test_the_order_follows_the_items_and_their_sockets() -> None:
    """Dieselbe Reihenfolge wie in der Paperdoll — sonst laesst sich ein
    Balken nicht ohne Suchen zuordnen."""
    gems = gem_progress_of([
        _item_with(_gem("Erstes", "1", "S", progress=0.1),
                   _gem("Zweites", "2", "D", progress=0.2)),
        _item_with(_gem("Drittes", "3", "I", progress=0.3))])

    assert [g.name for g in gems] == ["Erstes", "Zweites", "Drittes"]


def test_items_without_sockets_contribute_nothing() -> None:
    assert gem_progress_of([Item.model_validate({"typeLine": "Amethyst Ring"})]) == []


def test_the_strip_hides_itself_when_there_are_no_gems(qapp) -> None:
    """Ein Charakter ohne Sockel-Gems soll keinen leeren Streifen
    zeigen — der Platz gehoert dann dem Graphen."""
    strip = GemProgressBar()
    strip.set_gems(gem_progress_of([_item_with(_gem("Fire Trap", "17", "D", progress=0.5))]))
    assert not strip.isHidden()

    strip.clear()

    assert strip.isHidden()


def test_the_strip_paints_all_three_states(qapp) -> None:
    """Kein Bildvergleich, nur die Zusicherung, dass jeder Zustand die
    Zeichenroutine durchlaeuft."""
    strip = GemProgressBar()
    strip.resize(200, 60)
    strip.set_gems(gem_progress_of([_item_with(
        _gem("Fertig", "20 (Max)", "I"),
        _gem("Wartet", "16", "D", progress=1.0),
        _gem("Laeuft", "12", "S", progress=0.4))]))

    strip.render(strip.grab())

    assert len(strip._gems) == 3


# --- Breite neben der Favoriten-Tabelle (2026-08-16) -------------------- #

def _n_gems(anzahl: int):
    """``anzahl`` Sockel-Gems, ueber denselben Weg wie im Betrieb."""
    return gem_progress_of([_item_with(
        *[_gem(f"Gem {i}", "17", "D", progress=0.5) for i in range(anzahl)])])


def _zwoelf_gems():
    return _n_gems(12)


def test_die_balken_melden_ihre_breite_an(qapp) -> None:
    """Solange die Balken allein in einer Zeile standen, brauchten sie
    keinen Breitenwunsch. Seit die Favoriten-Tabelle daneben sitzt, schon:
    Ohne ihn fiel das Widget auf 0 px zusammen."""
    from poe_view.ui.gem_progress import GemProgressBar

    bar = GemProgressBar()
    bar.set_gems(_zwoelf_gems())

    assert bar.sizeHint().width() == 12 * 7 - 2
    assert bar.minimumSizeHint().width() == bar.sizeHint().width()


def test_die_breite_waechst_mit_der_zahl_der_gems(qapp) -> None:
    from poe_view.ui.gem_progress import GemProgressBar

    bar = GemProgressBar()
    bar.set_gems(_n_gems(1))
    schmal = bar.sizeHint().width()
    bar.set_gems(_n_gems(20))

    assert bar.sizeHint().width() > schmal


def test_ohne_gems_wird_keine_breite_verlangt(qapp) -> None:
    from poe_view.ui.gem_progress import GemProgressBar

    bar = GemProgressBar()
    bar.set_gems([])

    assert bar.sizeHint().width() == 0


def test_die_balken_ueberleben_die_tabelle_daneben(qapp) -> None:
    """Der eigentliche Regressionstest: Peters Bildschirmfotos vom
    2026-08-16 zeigten das Leveling-Feld ohne jeden Gem-Balken, weil die
    Favoriten-Tabelle im selben Streifen allen Platz bekam."""
    from poe_view.ui.favourites import FavouriteRow
    from poe_view.ui.gem_progress import GemProgressBar
    from poe_view.ui.leveling_panel import LevelingPanel

    panel = LevelingPanel()
    panel._gems.set_gems(_zwoelf_gems())
    panel.resize(560, 320)
    panel.show()
    qapp.processEvents()
    allein = panel._gems.width()

    panel.set_favourites([FavouriteRow("Primal Crystallised Lifeforce", 5017),
                          FavouriteRow("Vivid Crystallised Lifeforce", 5562)])
    qapp.processEvents()

    assert allein > 0
    assert panel._gems.width() == allein
    panel.close()


# --- Nur echte Gems, und der Rahmen fuer fertige (2026-08-16) ---------- #

def test_ein_abyss_jewel_im_guertel_ist_kein_gem() -> None:
    """Peter, 2026-08-16: "Belt gibts glaube ich nicht fuer Gems, nur
    fuer Jewels." In seinem Bestand steckte genau ein solches Jewel und
    bekam einen eigenen, ewig leeren Balken — es war jenes vermeintliche
    "Gem, dessen Stufe die API nicht mitliefert"."""
    guertel = Item.model_validate({"typeLine": "Leather Belt", "socketedItems": [
        {"typeLine": "Discharging Hypnotic Eye Jewel of Abuse", "frameType": 1,
         "abyssJewel": True}]})

    assert gem_progress_of([guertel]) == []


def test_gems_neben_einem_jewel_bleiben_erhalten() -> None:
    """Der Filter darf nicht die ganze Liste verwerfen."""
    ring = Item.model_validate({"typeLine": "Unset Ring", "socketedItems": [
        {"typeLine": "Hypnotic Eye Jewel", "frameType": 2},
        {"typeLine": "Summon Skitterbots", "frameType": 4, "colour": "I",
         "properties": [{"name": "Level", "values": [["19", 0]]}]}]})

    gems = gem_progress_of([ring])

    assert [g.name for g in gems] == ["Summon Skitterbots"]


def test_ein_fertiges_gem_bekommt_einen_rahmen(qapp) -> None:
    """Peter: "so dass man deutlich erkennt, dass der Gem ausgelevelt
    ist." Ein voller Balken allein sieht aus wie ein Gem, das gerade die
    naechste Stufe erreicht hat.

    Geprueft wird die Farbe der Randpixel, nicht ein Bildvergleich."""
    from PySide6.QtGui import QColor
    from poe_view.ui.gem_progress import GemProgressBar
    from poe_view.ui.theme import DASH_WARN

    strip = GemProgressBar()
    strip.set_gems(gem_progress_of([_item_with(_gem("Fertig", "20 (Max)", "I"))]))
    strip.resize(20, 60)
    bild = strip.grab().toImage()

    assert QColor(bild.pixel(0, 30)).name() == QColor(DASH_WARN).name()
    assert QColor(bild.pixel(2, 30)).name() != QColor(DASH_WARN).name()


def test_ein_levelndes_gem_bekommt_keinen_rahmen(qapp) -> None:
    from PySide6.QtGui import QColor
    from poe_view.ui.gem_progress import GemProgressBar
    from poe_view.ui.theme import DASH_WARN

    strip = GemProgressBar()
    strip.set_gems(gem_progress_of([_item_with(
        _gem("Laeuft noch", "17", "I", progress=0.3))]))
    strip.resize(20, 60)
    bild = strip.grab().toImage()

    assert QColor(bild.pixel(0, 30)).name() != QColor(DASH_WARN).name()
