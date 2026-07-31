"""Tests für die vergrößerte Item-Ansicht (ToDo.md: "Doppelklick auf ein
Item 'beleuchtet' dies"). Reine Anzeige eines übergebenen Items — kein
Netzzugriff, kein Worker nötig."""

from poe_view.api.models import Item
from poe_view.ui.item_zoom import ItemZoomDialog


def _item(**kwargs) -> Item:
    return Item.model_validate(kwargs)


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
