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


# --- Nur echte Gems (2026-08-16) --------------------------------------- #

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


def _auf_dunklem_grund(strip):
    """Palette auf einen dunklen Grund setzen: Offscreen laeuft sonst mit
    heller Palette, und die Trennung neben dem Rahmen waere weiss."""
    from PySide6.QtGui import QColor

    pal = strip.palette()
    pal.setColor(pal.ColorRole.Window, QColor("#2b2b2b"))
    strip.setPalette(pal)
    return strip


def _gezeichnet(*gems: dict):
    """Den echten Streifen zeichnen und das Bild zurueckgeben.

    ``render()``/``grab()`` des echten Widgets, nie ein Nachbau: Ein
    nachgebauter Streifen hatte am 2026-08-16 einen Unterschied
    vorgetaeuscht, den es im Programm gar nicht gab."""
    from poe_view.ui.gem_progress import BAR_HEIGHT, GemProgressBar

    strip = _auf_dunklem_grund(GemProgressBar())
    strip.set_gems(gem_progress_of([_item_with(*gems)]))
    strip.resize(20, BAR_HEIGHT)
    return strip.grab().toImage()


def _spalte(bild, x: int = 2) -> list[str]:
    """Eine senkrechte Pixelspalte durch die Mitte eines Balkens."""
    from PySide6.QtGui import QColor

    return [QColor(bild.pixel(x, y)).name() for y in range(bild.height())]


# --- Hoehe = Stufe, Linie = Erfahrung (2026-08-16) --------------------- #

def test_die_balkenhoehe_folgt_der_stufe_und_nicht_dem_fortschritt(qapp) -> None:
    """Peter, 2026-08-16: "Die aktuelle Stufe des Gems ist wichtiger als
    die aktuelle Erfahrung." Vorher fuellte der Fortschritt den Balken,
    jetzt die Stufe — bei Stufe 10 von 20 also die halbe Hoehe, ganz
    gleich, wie weit die naechste Stufe ist.

    Der Test setzt beide Werte bewusst weit auseinander (Stufe 10,
    Fortschritt 90 %): Wuerde noch der Fortschritt zaehlen, waere der
    Balken zu neun Zehnteln hell."""
    from poe_view.ui.gem_progress import gem_colour

    spalte = _spalte(_gezeichnet(_gem("Halb", "10", "D", progress=0.9)))
    hell = gem_colour("D")

    assert spalte[59] == hell           # unten gefuellt
    assert spalte[31] == hell           # bis knapp ueber die Mitte
    assert spalte[28] != hell           # darueber nicht mehr


def test_die_stufe_deckelt_bei_zwanzig_damit_korrupte_gems_nicht_ueberlaufen(qapp) -> None:
    """"21 (Max)" ist eine gueltige Stufe (23 Stueck in Peters Bestand).
    Ungedeckelt kaeme 21/20 heraus und der gefuellte Teil waere hoeher
    als der Balken."""
    from poe_view.ui.gem_progress import GemProgress

    assert GemProgress("x", "S", 1.0, "21 (Max)", True, False).level_fill == 1.0
    assert GemProgress("x", "S", 0.0, "10", False, False).level_fill == 0.5


def test_eine_unlesbare_stufe_gilt_als_null_statt_als_geraten(qapp) -> None:
    """Liefert GGG etwas, das keine Zahl ist, bleibt der Balken leer —
    dieselbe Regel wie beim Fortschritt ohne Beleg."""
    from poe_view.ui.gem_progress import GemProgress

    assert GemProgress("x", "S", 0.0, "?", False, False).level_number == 0


def test_die_erfahrung_steht_als_gelbe_linie_ueber_der_ganzen_hoehe(qapp) -> None:
    """Peter: "eine 1px Linie am jeweiligen Gem in Intensiv-Gelb fuer die
    aktuelle Erfahrung" — und zwar ueber die ganze Balkenhoehe, nicht
    innerhalb der Stufe. Innerhalb waere der Spielraum ein Zwanzigstel,
    bei 60 px also 3 px; die Linie wuerde sich praktisch nicht bewegen.

    Geprueft wird genau das: Zwei Gems gleicher Stufe, verschiedener
    Erfahrung, muessen ihre Linie weit auseinander haben."""
    from poe_view.ui.theme import GEM_XP_LINE

    gelb = GEM_XP_LINE
    frueh = _spalte(_gezeichnet(_gem("Frueh", "10", "D", progress=0.25))).index(gelb)
    spaet = _spalte(_gezeichnet(_gem("Spaet", "10", "D", progress=0.75))).index(gelb)

    assert spaet == 15 and frueh == 45          # 75 % bzw. 25 % von 60 px
    assert frueh - spaet == 30                  # halbe Balkenhoehe Abstand


def test_die_linie_bleibt_an_beiden_enden_im_balken(qapp) -> None:
    """Bei 0 % laege sie rechnerisch eine Zeile UNTER dem Balken, bei
    100 % genau auf der Oberkante. Beide Male soll man sie sehen."""
    from poe_view.ui.theme import GEM_XP_LINE

    leer = _spalte(_gezeichnet(_gem("Frisch", "10", "D", progress=0.0)))
    voll = _spalte(_gezeichnet(_gem("Gleich", "10", "D", progress=0.999)))

    assert leer[59] == GEM_XP_LINE
    assert voll[0] == GEM_XP_LINE


def test_ein_fertiges_gem_ist_ein_voller_balken_in_der_satten_farbe(qapp) -> None:
    """Peter: "Fertig gelevelte Gems werden einfach als intensiver 5px
    Balken dargestellt." Das loest zugleich, woran der gelbe Rahmen vom
    selben Tag gescheitert war: Auf 5 px Breite traegt eine Farbflaeche,
    keine Kontur (gemessen 1,13:1 gegen Gruen, 1,01:1 gegen Grau)."""
    from poe_view.ui.theme import GEM_COLORS_DONE

    spalte = _spalte(_gezeichnet(_gem("Fertig", "20 (Max)", "I")))

    assert set(spalte) == {GEM_COLORS_DONE["I"]}    # von oben bis unten


def test_ein_fertiges_gem_bekommt_keine_erfahrungslinie(qapp) -> None:
    """Es hat kein Erfahrungsfeld mehr — eine Linie waere eine erfundene
    Angabe. Deckt zugleich ab, dass der ``continue``-Zweig nicht
    versehentlich weiterzeichnet."""
    from poe_view.ui.theme import GEM_XP_LINE

    assert GEM_XP_LINE not in _spalte(_gezeichnet(_gem("Fertig", "20 (Max)", "I")))


def test_fertig_und_stufe_zwanzig_sind_klar_zu_unterscheiden(qapp) -> None:
    """Der Fall, an dem die ganze Markierung haengt: Ein Gem auf Stufe 20
    OHNE "(Max)" wartet auf einen Klick und ist voll — es darf nicht
    aussehen wie ein fertiges. Satte Farbe gegen gedaempfte Farbe plus
    goldene Kappe."""
    fertig = _spalte(_gezeichnet(_gem("Fertig", "20 (Max)", "D")))
    wartet = _spalte(_gezeichnet(_gem("Wartet", "20", "D", progress=1.0)))

    assert fertig[30] != wartet[30]


def test_die_goldene_kappe_bleibt_dem_wartenden_gem_erhalten(qapp) -> None:
    """Peter, 2026-08-16: "Das mit der goldenen Kappe bei levelbaren Gems
    behalten wir bei.\""""
    from poe_view.ui.theme import DASH_WARN

    spalte = _spalte(_gezeichnet(_gem("Wartet", "20", "D", progress=1.0)))

    assert spalte[0] == DASH_WARN and spalte[2] == DASH_WARN
    assert spalte[59] != DASH_WARN


def test_die_satten_farben_folgen_denselben_attributen(qapp) -> None:
    """Vier Farben, nicht eine: Ein einheitliches Rot fuer alles Fertige
    wuerde bei 227 von 448 Gems die Attribut-Zuordnung wegwerfen. Gelbe
    Gems, die es seit kurzem gibt, fallen wie alles Unbekannte auf Weiss
    (Peter: "die nehmen wir vorerst zu den weissen Gems dazu")."""
    from poe_view.ui.gem_progress import gem_colour_done
    from poe_view.ui.theme import GEM_COLOR_DONE_OTHER, GEM_COLORS_DONE

    assert gem_colour_done("S") == GEM_COLORS_DONE["S"]
    assert gem_colour_done("D") == GEM_COLORS_DONE["D"]
    assert gem_colour_done("I") == GEM_COLORS_DONE["I"]
    assert gem_colour_done("G") == GEM_COLOR_DONE_OTHER
    assert gem_colour_done("") == GEM_COLOR_DONE_OTHER
    assert len(set(GEM_COLORS_DONE.values()) | {GEM_COLOR_DONE_OTHER}) == 4


def test_ein_leerer_balken_bleibt_sichtbar(qapp) -> None:
    """Peters Bildschirmfoto vom 2026-08-16: Gems mit wenig Fortschritt
    sahen aus wie LUECKEN im Streifen. Gemessen hatte der dunkle Teil
    1,02-1,21:1 gegen den Hintergrund, war also unsichtbar; jetzt sind
    es 1,44-2,29:1.

    Geprueft wird, dass sich der dunkle Teil ueberhaupt vom Hintergrund
    unterscheidet — nicht ein bestimmter Farbwert."""
    from PySide6.QtGui import QColor
    from poe_view.ui.gem_progress import GemProgressBar

    strip = _auf_dunklem_grund(GemProgressBar())
    strip.set_gems(gem_progress_of([_item_with(
        _gem("Kaum gelevelt", "3", "D", progress=0.03))]))
    strip.resize(20, 60)
    bild = strip.grab().toImage()

    oben = QColor(bild.pixel(2, 5))          # der leere Teil
    assert oben.name() != "#2b2b2b", "leerer Balken verschwindet im Hintergrund"
    unten = QColor(bild.pixel(2, 59))        # der gefuellte Teil
    assert unten.name() != oben.name()       # und beide sind unterscheidbar
