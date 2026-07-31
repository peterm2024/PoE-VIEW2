"""Tests für die Charakter-Paperdoll (ToDo.md: "Doppelklick auf einen Char
'beleuchtet' diesen"). Reine Anzeige bereits geladener Items — kein
Netzzugriff, kein Worker nötig."""

from poe_view.api.models import Character, Item
from poe_view.ui.paperdoll import _DOLL_SLOTS, PaperdollDialog, _SlotButton


def _char() -> Character:
    return Character.model_validate({"name": "Testolus", "class": "Witch", "level": 90})


def _item(slot: str, name: str = "Something", **kwargs) -> Item:
    return Item.model_validate({"typeLine": name, "baseType": name, "inventoryId": slot, **kwargs})


def _slot_buttons(dialog: PaperdollDialog) -> list[_SlotButton]:
    return dialog.findChildren(_SlotButton)


def test_equipped_items_land_in_their_named_slot(qapp) -> None:
    helm = _item("Helm", "Lion Pelt")
    dialog = PaperdollDialog(_char(), [helm], pixmap_for=lambda item: None)
    labels = {b.text() for b in _slot_buttons(dialog)}
    assert "Lion Pelt" in labels


def test_empty_slots_show_a_disabled_placeholder(qapp) -> None:
    dialog = PaperdollDialog(_char(), [], pixmap_for=lambda item: None)
    buttons = _slot_buttons(dialog)
    assert buttons  # die zehn Ausrüstungs-Slots existieren immer
    assert all(not b.isEnabled() for b in buttons)
    assert all(b.text().startswith("(") for b in buttons)


def test_flasks_are_ordered_by_their_x_coordinate(qapp) -> None:
    flasks = [
        _item("Flask", "Flask C", x=2),
        _item("Flask", "Flask A", x=0),
        _item("Flask", "Flask B", x=1),
    ]
    dialog = PaperdollDialog(_char(), flasks, pixmap_for=lambda item: None)
    names_in_order = [b.text() for b in _slot_buttons(dialog) if b.text().startswith("Flask ")]
    assert names_in_order == ["Flask A", "Flask B", "Flask C"]


def test_weapon_swap_and_trinket_slots_only_appear_when_present(qapp) -> None:
    dialog_without = PaperdollDialog(_char(), [], pixmap_for=lambda item: None)
    assert len(_slot_buttons(dialog_without)) == len(_DOLL_SLOTS)  # nur die zehn Kern-Slots

    dialog_with = PaperdollDialog(_char(), [_item("Weapon2", "Swap Weapon"),
                                            _item("Trinket", "Ancient Sliver")],
                                  pixmap_for=lambda item: None)
    labels = {b.text() for b in _slot_buttons(dialog_with)}
    assert "Swap Weapon" in labels
    assert "Ancient Sliver" in labels
    assert len(_slot_buttons(dialog_with)) == len(_DOLL_SLOTS) + 2


def test_passive_jewels_are_listed_but_not_shown_as_slot_buttons(qapp) -> None:
    from PySide6.QtWidgets import QLabel

    jewels = [_item("PassiveJewels", "The Red Nightmare"), _item("PassiveJewels", "Brood Glimmer")]
    dialog = PaperdollDialog(_char(), jewels, pixmap_for=lambda item: None)
    assert not any(b.text() in ("The Red Nightmare", "Brood Glimmer")
                  for b in _slot_buttons(dialog))
    labels_text = "\n".join(l.text() for l in dialog.findChildren(QLabel))
    assert "The Red Nightmare" in labels_text
    assert "Brood Glimmer" in labels_text


def test_no_passive_jewels_section_without_any_jewels(qapp) -> None:
    from PySide6.QtWidgets import QGroupBox

    dialog = PaperdollDialog(_char(), [], pixmap_for=lambda item: None)
    assert not any("Jewels" in box.title() for box in dialog.findChildren(QGroupBox))


def test_clicking_a_slot_shows_it_in_the_embedded_item_detail(qapp) -> None:
    helm = _item("Helm", "Lion Pelt")
    dialog = PaperdollDialog(_char(), [helm], pixmap_for=lambda item: None)
    button = next(b for b in _slot_buttons(dialog) if b.text() == "Lion Pelt")

    button.click()

    assert "Lion Pelt" in dialog.detail._name.text()


def test_clicking_an_empty_slot_does_nothing(qapp) -> None:
    dialog = PaperdollDialog(_char(), [], pixmap_for=lambda item: None)
    before = dialog.detail._name.text()
    for button in _slot_buttons(dialog):
        button.click()  # deaktiviert, Qt liefert ohnehin kein clicked-Signal
    assert dialog.detail._name.text() == before
