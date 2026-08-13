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
    gem: dict = {"typeLine": name, "colour": colour,
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
    Grundlage — betrifft genau ein Gem von 449."""
    unklar, = gem_progress_of([_item_with(
        {"typeLine": "Seltsames Gem", "colour": "S"})])

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
