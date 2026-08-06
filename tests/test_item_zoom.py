"""Tests für die vergrößerte Item-Ansicht (ToDo.md: "Doppelklick auf ein
Item 'beleuchtet' dies"). Reine Anzeige eines übergebenen Items — kein
Netzzugriff, kein Worker nötig."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from poe_view.api.models import Item
from poe_view.ui.item_zoom import ItemZoomDialog
from poe_view.ui.theme import MARKUP_COLORS


def _item(**kwargs) -> Item:
    return Item.model_validate(kwargs)


def _all_label_text(dialog: ItemZoomDialog) -> str:
    return " ".join(label.text() for label in dialog.findChildren(QLabel))


def test_window_title_and_heading_use_the_display_name(qapp) -> None:
    item = _item(name="Tabula Rasa", typeLine="Simple Robe", baseType="Simple Robe", frameType=3)
    dialog = ItemZoomDialog(item, None)
    assert dialog.windowTitle() == "Tabula Rasa"
    assert "Tabula Rasa" in dialog._name.text()


def test_shows_all_mods_without_the_compact_panels_truncation() -> None:
    """ItemDetail (das kompakte Panel) kürzt auf 12 Zeilen — die
    vergrößerte Ansicht ist der ganze Punkt, warum es dieses Fenster gibt,
    darf also nicht genauso abschneiden."""
    item = _item(typeLine="Vaal Regalia", baseType="Vaal Regalia", frameType=2,
                implicitMods=["implicit 1"],
                explicitMods=[f"explicit mod {i}" for i in range(20)])
    text = ItemZoomDialog._build_text(item)
    for i in range(20):
        assert f"explicit mod {i}" in text


def test_includes_the_item_class_line() -> None:
    item = _item(typeLine="Ruby Ring", baseType="Ruby Ring", frameType=0)
    assert "Class: Ring" in ItemZoomDialog._build_text(item)


def test_includes_sockets_when_present() -> None:
    item = _item(typeLine="Vaal Regalia", baseType="Vaal Regalia", frameType=2,
                sockets=[{"group": 0, "attr": "I", "sColour": "B"}] * 3)
    assert "Sockets: B-B-B" in ItemZoomDialog._build_text(item)


def test_no_sockets_line_when_item_has_none() -> None:
    item = _item(typeLine="Chaos Orb", baseType="Chaos Orb", frameType=5)
    assert "Sockets:" not in ItemZoomDialog._build_text(item)


def test_marks_corrupted_and_unidentified_items_in_the_heading(qapp) -> None:
    item = _item(typeLine="Vaal Regalia", baseType="Vaal Regalia", frameType=2,
                corrupted=True, identified=False)
    dialog = ItemZoomDialog(item, None)
    assert "Corrupted" in dialog._name.text()
    assert "Unidentified" in dialog._name.text()


# --- Pergament-Rahmen für Divination Cards (Peter, 2026-07-31, Wiki-Referenz) ---

def test_divination_cards_get_the_decorative_card_frame(qapp) -> None:
    from PySide6.QtWidgets import QFrame

    item = _item(typeLine="The Doctor", baseType="The Doctor", frameType=6)
    dialog = ItemZoomDialog(item, None)
    assert dialog.findChild(QFrame, "cardFrame") is not None


def test_other_items_do_not_get_the_card_frame(qapp) -> None:
    from PySide6.QtWidgets import QFrame

    item = _item(typeLine="Vaal Regalia", baseType="Vaal Regalia", frameType=2)
    dialog = ItemZoomDialog(item, None)
    assert dialog.findChild(QFrame, "cardFrame") is None


# --- Fester Vergrößerungsfaktor statt Fensterbreite (Peter, 2026-07-31: ---
# --- "das ging schief... einfach fest auf 300% vergrößern", danach ---
# --- "300% ist zu groß, bitte auf 200% reduzieren") ---

def _pixmap(width: int, height: int):
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(width, height)
    pixmap.fill()
    return pixmap


def test_icon_is_scaled_to_exactly_200_percent_of_the_original() -> None:
    item = _item(typeLine="The Doctor", baseType="The Doctor", frameType=6)
    dialog = ItemZoomDialog(item, _pixmap(64, 64))
    assert dialog._icon.pixmap().width() == 64 * 2
    assert dialog._icon.pixmap().height() == 64 * 2


def test_icon_scaling_keeps_the_aspect_ratio_of_a_landscape_image() -> None:
    """Div-Card-Artwork ist querformatig (~237x170) — 200% davon darf
    nicht verzerren."""
    item = _item(typeLine="The Doctor", baseType="The Doctor", frameType=6)
    dialog = ItemZoomDialog(item, _pixmap(237, 170))
    assert dialog._icon.pixmap().width() == 237 * 2
    assert dialog._icon.pixmap().height() == 170 * 2


def test_icon_does_not_change_size_when_the_dialog_is_resized(qapp) -> None:
    """Fester Faktor, nicht mehr an die Fensterbreite gekoppelt."""
    item = _item(typeLine="The Doctor", baseType="The Doctor", frameType=6)
    dialog = ItemZoomDialog(item, _pixmap(64, 64))
    dialog.show()
    qapp.processEvents()

    dialog.resize(900, 900)
    qapp.processEvents()

    assert dialog._icon.pixmap().width() == 64 * 2
    dialog.close()


# --- Spruchtext: bei Karten der eigentliche Inhalt, bei Uniques die ---
# --- Hintergrundgeschichte (2026-08-06) ---

def test_the_flavour_text_is_shown_for_a_divination_card(qapp) -> None:
    """Ein Kartenrahmen ohne den Spruchtext bleibt stumm — er ist das,
    was eine Divination Card ausmacht."""
    item = _item(typeLine="Loyalty", baseType="Loyalty", frameType=6,
                flavourText=["Bound by fate,\r", "inseparable by choice."])
    dialog = ItemZoomDialog(item, None)
    assert dialog._flavour.text() == "Bound by fate,\ninseparable by choice."
    assert dialog._flavour.isVisibleTo(dialog)


def test_the_flavour_text_is_shown_for_uniques_too(qapp) -> None:
    """Nicht nur Karten haben einen: In Peters Cache tragen ihn 9176
    Uniques gegenueber 976 Karten."""
    item = _item(name="Tabula Rasa", typeLine="Simple Robe", baseType="Simple Robe",
                frameType=3, flavourText=["<size:31>{Wisdom is not a purchase.}"])
    dialog = ItemZoomDialog(item, None)
    assert dialog._flavour.text() == "Wisdom is not a purchase."


def test_no_empty_flavour_line_for_items_without_one(qapp) -> None:
    """Sonst klaffte unter jedem Rare eine leere Kursivzeile."""
    item = _item(typeLine="Vaal Regalia", baseType="Vaal Regalia", frameType=2)
    dialog = ItemZoomDialog(item, None)
    assert not dialog._flavour.isVisibleTo(dialog)


def test_the_mod_text_carries_no_ggg_markup(qapp) -> None:
    """Gegenprobe zur Filterung an der Stelle, an der sie sichtbar wird:
    Im Fenster stand woertlich "<currencyitem>{...}"."""
    item = _item(typeLine="Loyalty", baseType="Loyalty", frameType=6,
                explicitMods=["<currencyitem>{3x Orb of Fusing}"])
    text = ItemZoomDialog._build_text(item)
    assert "3x Orb of Fusing" in text
    assert "<" not in text and "{" not in text


# --- Satz-Fortschritt einer Divination Card (Peters Vorschlag, 2026-08-06) ---
#
# "Am Anfang der Zeile die Anzahl voller Stacks (bei 0 ausgeblendet) und
# dahinter dann die Zahl der vorhandenen Karten in gefuellten Rechtecken
# und anschliessend die fehlenden in leeren Rechtecken."

def _card_with_stack(held: int, per_set: int) -> Item:
    return _item(typeLine="The Doctor", baseType="The Doctor", frameType=6,
                stackSize=held, maxStackSize=per_set,
                properties=[{"name": "Stack Size",
                             "values": [[f"{held}/{per_set}", 0]]}])


def _boxes(item: Item) -> str:
    """Nur die Rechteck-Zeile, Leerzeichen entfernt — die schmalen
    Trennzeichen interessieren hier nicht."""
    for line in ItemZoomDialog._text_lines(item):
        text = "".join(part for _tag, part in line)
        if "▮" in text or "▯" in text:
            return "".join(text.split())
    return ""


def test_a_partial_set_shows_held_and_missing_cards(qapp) -> None:
    assert _boxes(_card_with_stack(4, 8)) == "▮▮▮▮▯▯▯▯"
    assert _boxes(_card_with_stack(2, 5)) == "▮▮▯▯▯"


def test_complete_sets_are_counted_not_drawn(qapp) -> None:
    """467 Karten sind 116 volle Saetze (real, "The Carrion Crow"). Als
    Rechtecke waere das eine Wand ohne Aussage — die Zahl steht davor, ein
    einzelnes gruenes Rechteck sagt, wovon sie spricht."""
    assert _boxes(_card_with_stack(7, 5)) == "1▮+▮▮▯▯▯"
    assert _boxes(_card_with_stack(467, 4)).startswith("116▮+")


def test_a_set_that_comes_out_even_does_not_look_empty(qapp) -> None:
    """15/5 sind drei fertige Saetze und ein noch leerer vierter. Ohne das
    gruene Rechteck davor stand dort ``3× ▯▯▯▯▯`` — eine Reihe leerer
    Kaestchen, die auf den ersten Blick wie "du hast nichts" aussieht."""
    assert _boxes(_card_with_stack(15, 5)) == "3▮+▯▯▯▯▯"


def test_the_count_is_hidden_without_a_complete_set(qapp) -> None:
    """Peters Vorgabe — und der haeufigste Fall: 495 von 976 Karten haben
    keinen vollen Satz."""
    assert not _boxes(_card_with_stack(3, 5)).startswith("0")
    assert _boxes(_card_with_stack(3, 5)) == "▮▮▮▯▯"


def test_only_divination_cards_get_rectangles(qapp) -> None:
    """Peter, 2026-08-06: "die Rechtecke meine ich nur bei den Divination
    Cards". Bei Waehrung ist maxStackSize keine Satzgroesse, sondern
    Lagerkapazitaet — real bis 50000, das waeren 50000 Rechtecke."""
    currency = _item(typeLine="Chaos Orb", frameType=5, stackSize=1200,
                    maxStackSize=5000,
                    properties=[{"name": "Stack Size", "values": [["1200/5000", 0]]}])
    assert _boxes(currency) == ""
    assert "Stack Size: 1200/5000" in ItemZoomDialog._build_text(currency)


def test_a_set_of_one_shows_only_the_count_and_a_green_box(qapp) -> None:
    """16 Karten haben Satzgroesse 1 — jede ist fuer sich ein voller Satz,
    einen angefangenen gibt es nicht."""
    assert _boxes(_card_with_stack(16, 1)) == "16▮"


def test_cards_of_set_size_one_get_a_line_although_ggg_sends_no_property(qapp) -> None:
    """Peter fand es an "Society's Remorse": Dort stand ueberhaupt nichts,
    weder die Stueckzahl noch die Satzgroesse. Ursache ist kein Sonderfall
    unserer Logik, sondern ein Loch in den Daten — real geprueft: ALLE 16
    Karten mit Satzgroesse 1 liefern ``properties: []``, alle 960 uebrigen
    eine Stack-Size-Property. Deshalb haengt die Zeile nicht mehr am
    Durchlauf durch die Properties.

    Und "gar nichts" ist von einem Fehler nicht zu unterscheiden."""
    remorse = _item(typeLine="Society's Remorse", baseType="Society's Remorse",
                   frameType=6, stackSize=16, maxStackSize=1, properties=[])
    assert _boxes(remorse) == "16▮"
    assert "16" in ItemZoomDialog._build_text(remorse)


def test_a_card_without_a_set_size_keeps_the_plain_number(qapp) -> None:
    card = _item(typeLine="The Doctor", frameType=6, stackSize=3,
                properties=[{"name": "Stack Size", "values": [["3/8", 0]]}])
    assert _boxes(card) == ""
    assert "Stack Size: 3/8" in ItemZoomDialog._build_text(card)


def test_complete_sets_are_green_and_partial_progress_is_not(qapp) -> None:
    """Gruen heisst an dieser Stelle immer und nur "vollstaendig"."""
    from poe_view.ui.theme import STACK_COLORS

    even = ItemZoomDialog._build_html(_card_with_stack(15, 5))
    partial = ItemZoomDialog._build_html(_card_with_stack(3, 5))
    assert STACK_COLORS["stack-complete"] in even
    assert STACK_COLORS["stack-complete"] not in partial


def test_held_and_missing_are_told_apart_by_colour(qapp) -> None:
    from poe_view.ui.theme import STACK_COLORS

    html_text = ItemZoomDialog._build_html(_card_with_stack(4, 8))
    assert STACK_COLORS["stack-full"] in html_text
    assert STACK_COLORS["stack-empty"] in html_text


def test_the_exact_numbers_survive_in_the_tooltip(qapp) -> None:
    """Die Rechtecke ersetzen den Zahlentext — 467 Karten und 116 Saetze
    lassen sich aber nicht abzaehlen. Die Auskunft darf aus der Zeile
    verschwinden, nicht aus dem Fenster."""
    dialog = ItemZoomDialog(_card_with_stack(467, 4), None)
    tip = dialog._text.toolTip()
    assert "467" in tip and "4 per set" in tip and "116 complete" in tip

    remorse = _item(typeLine="Society's Remorse", frameType=6,
                   stackSize=16, maxStackSize=1, properties=[])
    assert "16 cards" in ItemZoomDialog(remorse, None)._text.toolTip()


def test_no_stack_tooltip_on_items_without_the_bar(qapp) -> None:
    assert ItemZoomDialog(_item(typeLine="Vaal Regalia", frameType=2), None) \
        ._text.toolTip() == ""


def test_the_rectangles_are_separated_so_they_can_be_counted(qapp) -> None:
    """Aneinandergesetzt verschmelzen sie zu einem Balken — und abzaehlen,
    worum es hier gerade geht, kann man ihn dann nicht mehr."""
    line = next(text for text in
               ("".join(part for _t, part in ln)
                for ln in ItemZoomDialog._text_lines(_card_with_stack(2, 5)))
               if "▮" in text)
    assert "▮▮" not in line and "▯▯" not in line
    assert not line.endswith(" ")  # hinter dem letzten trennt nichts mehr


# --- Farbe, Zentrierung, Schrift (Peter, 2026-08-06) ---

def test_the_reward_is_shown_in_the_colour_ggg_assigned_it(qapp) -> None:
    """Die Farbe kommt aus GGGs eigenem Markup, nicht aus einer eigenen
    Zuordnung nach Schlagworten: Aus dem Text "Doomfletch" allein ist
    nicht ableitbar, dass es ein Unique ist."""
    from poe_view.ui.theme import RARITY_COLORS

    currency = _item(typeLine="Loyalty", baseType="Loyalty", frameType=6,
                    explicitMods=["<currencyitem>{3x Orb of Fusing}"])
    unique = _item(typeLine="The Dark Mage", baseType="The Dark Mage", frameType=6,
                  explicitMods=["<uniqueitem>{Doomfletch}"])

    assert RARITY_COLORS[5] in ItemZoomDialog._build_html(currency)
    assert RARITY_COLORS[3] in ItemZoomDialog._build_html(unique)


def test_two_colours_within_one_mod_line(qapp) -> None:
    """"Level 21 Vaal Summon Skeletons" gruen, "Corrupted" rot — beides
    steht in EINEM Mod-Eintrag, durch einen Zeilenumbruch getrennt."""
    item = _item(typeLine="Gift of the Gemling Queen", frameType=6,
                explicitMods=["<gemitem>{Level 21 Vaal Summon Skeletons}\r\n"
                             "<corrupted>{Corrupted}"])
    html_text = ItemZoomDialog._build_html(item)
    assert MARKUP_COLORS["gemitem"] in html_text
    assert MARKUP_COLORS["corrupted"] in html_text
    # und der Umbruch bleibt ein Umbruch, keine zusammengezogene Zeile
    assert "Level 21 Vaal Summon Skeletons\nCorrupted" in ItemZoomDialog._build_text(item)


def test_our_own_labels_stay_uncoloured(qapp) -> None:
    """Farbig ist nur, was GGG selbst eingefaerbt hat. "Class: Ring" und
    "Sockets: …" sind unsere Beschriftungen — wuerden sie mitgefaerbt,
    saehe das Fenster wie ein Farbkasten aus, und die Belohnung ginge in
    der Buntheit unter."""
    item = _item(typeLine="Ruby Ring", baseType="Ruby Ring", frameType=0)
    assert "color:" not in ItemZoomDialog._build_html(item)


def test_an_unknown_markup_tag_gets_no_invented_colour(qapp) -> None:
    """Eine geratene Farbe waere schlechter als gar keine — der Text
    bleibt aber vollstaendig lesbar."""
    item = _item(typeLine="Something New", frameType=6,
                explicitMods=["<brandnewtag>{Mystery Reward}"])
    html_text = ItemZoomDialog._build_html(item)
    assert "Mystery Reward" in html_text
    assert "color:" not in html_text


def test_html_special_characters_in_a_mod_are_escaped(qapp) -> None:
    """Der Textblock ist Rich Text — ein "&" oder "<" aus den Daten darf
    nicht als Auszeichnung gedeutet werden."""
    item = _item(typeLine="Weird", frameType=2, explicitMods=["Bows & <Wands>"])
    html_text = ItemZoomDialog._build_html(item)
    assert "&amp;" in html_text and "&lt;Wands&gt;" in html_text


def test_everything_is_centred(qapp) -> None:
    """Peter, 2026-08-06: "Generell saemtliche Texte dort mittig
    platzieren"."""
    item = _item(name="Tabula Rasa", typeLine="Simple Robe", frameType=3,
                flavourText=["Wisdom is not a purchase."])
    dialog = ItemZoomDialog(item, None)
    assert dialog._name.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert dialog._flavour.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert "align='center'" in ItemZoomDialog._build_html(item)


def test_the_flavour_text_uses_a_larger_italic_serif(qapp) -> None:
    """Er ist Prosa, kein Datenfeld — und hebt sich dadurch ab, ohne laut
    zu werden."""
    item = _item(typeLine="Loyalty", frameType=6, flavourText=["Bound by fate."])
    dialog = ItemZoomDialog(item, None)
    font = dialog._flavour.font()
    assert font.italic()
    assert font.pointSizeF() > dialog._text.font().pointSizeF()
    assert font.families()[0] == "Georgia"


def test_the_card_ornament_is_not_an_emoji_glyph(qapp) -> None:
    """Windows zeichnet ❦ (U+2766) und ❧ (U+2767) aus einer
    Farb-Emoji-Schrift — als buntes Bildchen statt in der Rahmenfarbe,
    auch mit Variantenselektor. Der Teiler darf keins davon enthalten."""
    from poe_view.ui import item_zoom

    assert "❦" not in item_zoom._CARD_ORNAMENT
    assert "❧" not in item_zoom._CARD_ORNAMENT


def test_the_ornament_only_appears_when_there_is_a_flavour_text(qapp) -> None:
    """Er trennt Artwork und Spruchtext. Ohne Spruchtext traennte er
    nichts und haenge nur als Zierrat unter dem Bild."""
    from poe_view.ui import item_zoom

    with_flavour = _item(typeLine="Loyalty", frameType=6,
                        flavourText=["Bound by fate."])
    without = _item(typeLine="Humility", frameType=6, flavourText=[" "])

    assert item_zoom._CARD_ORNAMENT in _all_label_text(ItemZoomDialog(with_flavour, None))
    assert item_zoom._CARD_ORNAMENT not in _all_label_text(ItemZoomDialog(without, None))


def test_the_flavour_text_sits_between_picture_and_attributes(qapp) -> None:
    """Peter, 2026-08-06. Bei einer Karte gehoert er MIT IN den Rahmen —
    er ist Teil der Karte, nicht eine Bemerkung darunter."""
    from PySide6.QtWidgets import QFrame

    card = _item(typeLine="Loyalty", frameType=6, flavourText=["Bound by fate."])
    dialog = ItemZoomDialog(card, None)
    frame = dialog.findChild(QFrame, "cardFrame")
    assert dialog._flavour in frame.findChildren(QLabel)

    other = _item(typeLine="Vaal Regalia", frameType=2, flavourText=["Ein Spruch."])
    dialog2 = ItemZoomDialog(other, None)
    outer = dialog2.layout()
    positions = {outer.itemAt(i).widget(): i for i in range(outer.count())}
    assert positions[dialog2._icon] < positions[dialog2._flavour]


def test_cards_open_taller_so_reward_and_flavour_are_not_hidden(qapp) -> None:
    """Ueber dem Text steht bei Karten der Rahmen mit dem Artwork (rund
    350 px). In der Hoehe der uebrigen Items lagen Belohnung und
    Spruchtext hinter einem Rollbalken."""
    card = _item(typeLine="Loyalty", baseType="Loyalty", frameType=6)
    other = _item(typeLine="Vaal Regalia", baseType="Vaal Regalia", frameType=2)
    assert ItemZoomDialog(card, None).height() > ItemZoomDialog(other, None).height()
