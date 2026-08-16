"""Tests fuer das Leveling-Panel rechts neben dem Item-Detail (Peter,
2026-08-12: "Ich haette den rechten (freien) Bereich hier gerne fuer
unsere Leveling-Infos (XP/h-Graph) benutzt") — ARCHITEKTUR.md §4.39."""

from poe_view.api.models import Item
from poe_view.ui.leveling_panel import LevelingPanel
from poe_view.ui.main_window import MainWindow


def test_the_panel_shows_level_experience_and_rate(qapp) -> None:
    panel = LevelingPanel()
    panel.show_character("WitchOfPeter", level=90, experience=1935625585,
                         rate_text="119.2M XP/h", age_note=" (3m ago)")

    assert "WitchOfPeter" in panel._title.text()
    body = panel._body.text()
    assert "Level 90" in body
    assert "119.2M XP/h" in body
    assert "(3m ago)" in body


def test_a_missing_rate_says_why_instead_of_staying_blank(qapp) -> None:
    """GGG veroeffentlicht Erfahrung erst beim Verlassen einer Zone. Ein
    leeres Feld saehe nach einem Fehler aus, obwohl alles in Ordnung
    ist — genau diese Verwechslung hat beim Bau der Rate schon einmal
    Zeit gekostet."""
    panel = LevelingPanel()
    panel.show_character("WitchOfPeter", level=90, experience=1, rate_text=None,
                         age_note="")

    assert "zone change" in panel._body.text()


def test_switching_to_a_stash_tab_clears_the_leveling_panel(qapp, monkeypatch) -> None:
    """Die Anzeige gehoert zu EINEM Charakter. Bliebe sie neben einem
    Truhenfach stehen, behauptete sie einen Zusammenhang, den es nicht
    gibt."""
    win = MainWindow()
    win._current_character_name = "WitchOfPeter"
    win._on_character_items("WitchOfPeter", [
        Item.model_validate({"id": "ring-1", "typeLine": "Amethyst Ring",
                             "inventoryId": "Ring"})], False)
    assert "WitchOfPeter" in win.leveling._title.text()

    win._show_items("tab-1", [], "Currency")

    assert win.leveling._title.text() == "Leveling"
    assert "No character selected" in win.leveling._body.text()

    win.worker.stop()
    win.worker.wait(5000)


def test_without_a_character_the_graph_axis_disappears_too(qapp) -> None:
    """Eine leere Achse neben "No character selected" behauptet, es gaebe
    hier einen Verlauf zu sehen. Bei einem Charakter OHNE Abschnitte ist
    die leere Achse dagegen die richtige Aussage — deshalb nur beim
    Leeren ausblenden."""
    panel = LevelingPanel()
    panel.show_character("WitchOfPeter", level=90, experience=1, rate_text=None,
                         age_note="")
    panel.show()
    assert not panel._graph.isHidden()

    panel.clear()

    assert panel._graph.isHidden()


# --- Anordnung nach Peters Skizze vom 2026-08-16 ------------------------ #

def _panel_mit_inhalt(qapp, gem_anzahl: int = 12, favoriten: int = 2):
    from poe_view.api.models import Item
    from poe_view.ui.favourites import FavouriteRow
    from poe_view.ui.gem_progress import gem_progress_of

    gems = gem_progress_of([Item.model_validate({"typeLine": "Vaal Regalia",
        "socketedItems": [
            {"typeLine": f"Gem {i}", "colour": "S", "frameType": 4,
             "properties": [{"name": "Level", "values": [["19", 0]]}],
             "additionalProperties": [{"name": "Experience",
                                       "values": [["1/2", 0]],
                                       "progress": 0.5}]}
            for i in range(gem_anzahl)]})])
    panel = LevelingPanel()
    panel.resize(578, 320)
    panel.show_character("WitchOfPeter", level=91, experience=2_151_302_311,
                         rate_text="114.7M XP/h", age_note="", gems=gems)
    panel.set_favourites([FavouriteRow(f"Crystallised Lifeforce {i}", 5017 + i)
                          for i in range(favoriten)])
    panel.show()
    qapp.processEvents()
    return panel


def test_die_favoriten_stehen_neben_dem_textblock(qapp) -> None:
    """Peters Vorgabe: Tabelle nach rechts, nicht darunter."""
    panel = _panel_mit_inhalt(qapp)

    assert panel.favourites.x() > panel._body.x() + panel._body.width() - 1
    assert panel.favourites.y() <= panel._body.y()

    panel.close()


def test_die_favoriten_fuellen_die_hoehe_des_textblocks(qapp) -> None:
    """"Die volle uns verbliebene Hoehe" — die Tabelle reicht mindestens
    so weit hinunter wie Titel und Zahlen daneben."""
    panel = _panel_mit_inhalt(qapp)

    unterkante_text = panel._body.y() + panel._body.height()
    assert panel.favourites.y() + panel.favourites.height() >= unterkante_text

    panel.close()


def test_die_gem_balken_bleiben_unter_dem_textblock(qapp) -> None:
    """Peter: "Die Gem-Balken lassen wir dort wo sie sind." Sie stehen
    also weiterhin in eigener Zeile ueber dem Graphen, nicht rechts."""
    panel = _panel_mit_inhalt(qapp)

    assert panel._gems.x() == panel._body.x()
    assert panel._gems.y() > panel._body.y()
    assert panel._gems.y() < panel._graph.y()
    assert panel._gems.width() > 0

    panel.close()


def test_der_graph_bekommt_den_rest(qapp) -> None:
    """Der Graph steht ganz unten und behaelt den groessten Anteil —
    sonst haette die Umsortierung ihn gekostet."""
    panel = _panel_mit_inhalt(qapp)

    assert panel._graph.y() > panel._gems.y()
    assert panel._graph.height() > panel.favourites.height()

    panel.close()


def test_die_favoriten_reichen_bis_neben_die_gem_balken(qapp) -> None:
    """Peter, 2026-08-16: "Koennen wir den Platz neben den Gem-Balken
    nicht auch noch fuer die Fav-Tabelle nutzen?" Die Tabelle steht also
    nicht nur neben dem Textblock, sondern reicht bis ans untere Ende des
    Balkenstreifens."""
    panel = _panel_mit_inhalt(qapp)

    unterkante_balken = panel._gems.y() + panel._gems.height()
    assert panel.favourites.y() + panel.favourites.height() >= unterkante_balken
    assert panel.favourites.x() > panel._gems.x() + panel._gems.width() - 1

    panel.close()


def test_die_graph_hoehe_haengt_nicht_an_der_zahl_der_gems(qapp) -> None:
    """Ohne Mindestbreite fuer den Textblock zog die Tabelle bei WENIGEN
    Gems so viel Breite an sich, dass die Zahlenzeile umbrach — und jede
    zusaetzliche Textzeile ging direkt vom Graphen ab. Gemessen waren das
    126 statt 154 px, also ausgerechnet beim schmaleren Balkenstreifen
    der kleinere Graph.

    Ein Charakter kann hoechstens 38 Sockel-Gems tragen; beide Enden der
    Spanne muessen dieselbe Graph-Hoehe ergeben."""
    wenige = _panel_mit_inhalt(qapp, gem_anzahl=12)
    viele = _panel_mit_inhalt(qapp, gem_anzahl=38)

    assert wenige._graph.height() == viele._graph.height()
    assert wenige._body.width() == viele._body.width()

    wenige.close()
    viele.close()


def test_auch_38_gems_lassen_der_tabelle_platz(qapp) -> None:
    """38 ist das Maximum: 6 Ruestung + 6 Waffe + 6 Zweitwaffe + 4 Helm
    + 4 Handschuhe + 4 Stiefel + 3 + 3 Schildhand + je 1 Abyss-Sockel in
    Ring und Guertel (an Peters Cache nachgezaehlt, sein Hoechstwert
    liegt bei 33)."""
    panel = _panel_mit_inhalt(qapp, gem_anzahl=38)

    assert panel._gems.width() > 0
    assert panel.favourites.width() >= panel.favourites.minimumSizeHint().width()
    assert panel.favourites.isVisible()

    panel.close()


def test_ohne_gems_bleibt_die_tabelle_neben_dem_text(qapp) -> None:
    """Ein Charakter ohne Sockel-Gems: Der Streifen verschwindet, die
    Tabelle rueckt mit nach oben statt ins Leere zu greifen."""
    panel = _panel_mit_inhalt(qapp, gem_anzahl=0)

    assert panel._gems.isHidden()
    assert panel.favourites.isVisible()
    assert panel.favourites.y() <= panel._body.y()

    panel.close()
