"""Tests für die Charakter-Paperdoll (ToDo.md: "Doppelklick auf einen Char
'beleuchtet' diesen"). Reine Anzeige bereits geladener Items — kein
Netzzugriff, kein Worker nötig."""

from PySide6.QtGui import QFont, QFontMetrics

from poe_view.api.models import Character, Item
from poe_view.ui.paperdoll import (_DOLL_SLOTS, _NAME_LINES, PaperdollDialog,
                                   _fit_name, _SlotButton)


def _char() -> Character:
    return Character.model_validate({"name": "Testolus", "class": "Witch", "level": 90})


def _item(slot: str, name: str = "Something", **kwargs) -> Item:
    return Item.model_validate({"typeLine": name, "baseType": name, "inventoryId": slot, **kwargs})


def _slot_buttons(dialog: PaperdollDialog) -> list[_SlotButton]:
    return dialog.findChildren(_SlotButton)


def _label(button: _SlotButton) -> str:
    """Beschriftung ohne den Zeilenumbruch, den der Platz je nach
    Schriftbreite einfuegt. Wo genau umbrochen wird, haengt an der
    Schrift — offscreen ist die Ersatzschrift mehr als doppelt so breit
    wie eine echte Windows-Schrift, ein Test darauf pruefte also die
    Testumgebung statt den Code (das Umbrechen selbst hat unten eigene,
    schriftunabhaengige Tests)."""
    return " ".join(button.text().split())


def _labels(dialog: PaperdollDialog) -> set[str]:
    return {_label(b) for b in _slot_buttons(dialog)}


def test_equipped_items_land_in_their_named_slot(qapp) -> None:
    helm = _item("Helm", "Lion Pelt")
    dialog = PaperdollDialog(_char(), [helm], pixmap_for=lambda item: None)
    assert "Lion Pelt" in _labels(dialog)


def test_the_grid_matches_the_arrangement_in_the_game(qapp) -> None:
    """Peter schickte am 2026-08-07 einen Screenshot seines laufenden
    Spiels, weil die Anordnung hier nach meiner Erinnerung gebaut war —
    und an zwei Stellen falsch: Die Ringe flankieren die RUESTUNG (nicht
    den Guertel), und das Amulett sitzt RECHTS NEBEN DEM HELM (nicht
    zwischen den Waffen).

    Geprueft werden Lagebeziehungen, keine festen Koordinaten: Wo genau
    das Raster anfaengt, ist Geschmack — was neben was liegt, nicht."""
    zeile = {slot: r for r, _c, slot, _label in _DOLL_SLOTS}
    spalte = {slot: c for _r, c, slot, _label in _DOLL_SLOTS}

    # Helm und Amulett teilen sich die oberste Zeile, Amulett rechts
    assert zeile["Helm"] == zeile["Amulet"]
    assert spalte["Amulet"] > spalte["Helm"]

    # Ringe links und rechts der Ruestung, auf ihrer Hoehe
    assert zeile["Ring"] == zeile["BodyArmour"] == zeile["Ring2"]
    assert spalte["Ring"] < spalte["BodyArmour"] < spalte["Ring2"]

    # Waffe ganz aussen links, Zweithand ganz aussen rechts
    assert spalte["Weapon"] == min(spalte.values())
    assert spalte["Offhand"] == max(spalte.values())

    # Handschuhe, Guertel, Stiefel auf einer Hoehe, unter der Ruestung
    assert zeile["Gloves"] == zeile["Belt"] == zeile["Boots"]
    assert zeile["Belt"] > zeile["BodyArmour"]
    assert spalte["Gloves"] < spalte["Belt"] < spalte["Boots"]

    # Der Helm liegt ueber allem anderen
    assert zeile["Helm"] == min(zeile.values())


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
    names_in_order = [_label(b) for b in _slot_buttons(dialog)
                     if _label(b).startswith("Flask ")]
    assert names_in_order == ["Flask A", "Flask B", "Flask C"]


def test_weapon_swap_and_trinket_slots_only_appear_when_present(qapp) -> None:
    dialog_without = PaperdollDialog(_char(), [], pixmap_for=lambda item: None)
    assert len(_slot_buttons(dialog_without)) == len(_DOLL_SLOTS)  # nur die zehn Kern-Slots

    dialog_with = PaperdollDialog(_char(), [_item("Weapon2", "Swap Weapon"),
                                            _item("Trinket", "Ancient Sliver")],
                                  pixmap_for=lambda item: None)
    labels = _labels(dialog_with)
    assert "Swap Weapon" in labels
    assert "Ancient Sliver" in labels
    assert len(_slot_buttons(dialog_with)) == len(_DOLL_SLOTS) + 2


def test_passive_jewels_are_slots_like_everything_else(qapp) -> None:
    """Bis 2026-08-06 standen sie als reine Textliste in einem Rollbereich
    darunter — die einzigen Items im Fenster, die auf einen Klick nicht
    reagierten, und die Liste schnitt regelmaessig mitten in einer Zeile
    ab. Der alte Test schrieb genau das fest; er beschrieb den Zustand,
    nicht eine Anforderung."""
    jewels = [_item("PassiveJewels", "Ruby"), _item("PassiveJewels", "Opal")]
    dialog = PaperdollDialog(_char(), jewels, pixmap_for=lambda item: None)

    assert {"Ruby", "Opal"} <= _labels(dialog)

    button = next(b for b in _slot_buttons(dialog) if _label(b) == "Opal")
    button.click()
    assert "Opal" in dialog.detail._name.text()


def test_no_passive_jewels_section_without_any_jewels(qapp) -> None:
    from PySide6.QtWidgets import QGroupBox

    dialog = PaperdollDialog(_char(), [], pixmap_for=lambda item: None)
    assert not any("Jewels" in box.title() for box in dialog.findChildren(QGroupBox))


def test_clicking_a_slot_shows_it_in_the_embedded_item_detail(qapp) -> None:
    helm = _item("Helm", "Lion Pelt")
    dialog = PaperdollDialog(_char(), [helm], pixmap_for=lambda item: None)
    button = next(b for b in _slot_buttons(dialog) if _label(b) == "Lion Pelt")

    button.click()

    assert "Lion Pelt" in dialog.detail._name.text()


def test_clicking_an_empty_slot_does_nothing(qapp) -> None:
    dialog = PaperdollDialog(_char(), [], pixmap_for=lambda item: None)
    before = dialog.detail._name.text()
    for button in _slot_buttons(dialog):
        button.click()  # deaktiviert, Qt liefert ohnehin kein clicked-Signal
    assert dialog.detail._name.text() == before


# --- Lesbarkeit der Beschriftungen (2026-08-06) ---
#
# An Peters echten Charakteren gemessen wurden vorher 87 von 171
# Ausruestungsteilen abgeschnitten — die Haelfte. Vier Flaschen lasen sich
# allesamt als "Flagell..." und waren nicht auseinanderzuhalten.

def test_a_name_that_fits_is_left_on_one_line(qapp) -> None:
    """Breite absichtlich riesig gewaehlt: So haengt der Test nicht an der
    Schrift der Testumgebung (offscreen laeuft mit einer Ersatzschrift,
    die mehr als doppelt so breit ist wie eine echte Windows-Schrift)."""
    metrics = QFontMetrics(QFont())
    assert _fit_name("Quicksilver Flask", metrics, 10_000) == "Quicksilver Flask"


def test_a_long_name_is_broken_at_a_word_boundary(qapp) -> None:
    metrics = QFontMetrics(QFont())
    breit = metrics.horizontalAdvance("Quicksilver ")
    assert _fit_name("Quicksilver Flask", metrics, breit) == "Quicksilver\nFlask"


def test_the_name_never_grows_beyond_the_allowed_lines(qapp) -> None:
    """Sonst waere der Platz kein Platz mehr, sondern ein Textblock."""
    metrics = QFontMetrics(QFont())
    gequetscht = _fit_name("Flagellant's Quicksilver Flask of the Kaleidoscope",
                          metrics, 20)
    assert gequetscht.count("\n") + 1 <= _NAME_LINES


def test_the_slot_itself_wraps_and_does_not_overflow(qapp) -> None:
    """Gegenstueck zu den drei Tests oben: Die pruefen _fit_name, dieser
    prueft, dass der Platz sie ueberhaupt benutzt.

    Acht Woerter passen in KEINER Schrift in eine Zeile von rund 94 px —
    damit haengt der Test nicht an der Testumgebung."""
    langer = _item("Helm", "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta")
    dialog = PaperdollDialog(_char(), [langer], pixmap_for=lambda item: None)
    button = next(b for b in _slot_buttons(dialog) if "Alpha" in b.text())

    assert "\n" in button.text()
    assert button.text().count("\n") + 1 <= _NAME_LINES


def test_the_slot_shows_the_base_type_not_a_rolled_fantasy_name(qapp) -> None:
    """Ein Rare heisst "Vortex Bane" und ist ein "Gutting Knife" — nur das
    zweite sagt etwas. Und die Affix-Kette eines Magic-Items passt hier
    ohnehin nie hin. Der vollstaendige Name bleibt im Tooltip.

    Kurze Namen, damit der Test nicht an der Schriftbreite haengt: Ein
    einzelnes langes Wort laesst sich nicht umbrechen und wird gekuerzt,
    und wo diese Grenze liegt, entscheidet die Schrift."""
    rare = Item.model_validate({"name": "Bane", "typeLine": "Knife",
                                "baseType": "Knife", "frameType": 2,
                                "inventoryId": "Weapon"})
    dialog = PaperdollDialog(_char(), [rare], pixmap_for=lambda item: None)
    button = next(b for b in _slot_buttons(dialog) if _label(b) == "Knife")
    assert button.toolTip() == "Bane"


def test_a_unique_keeps_its_own_name(qapp) -> None:
    unique = Item.model_validate({"name": "Gull", "typeLine": "Mask",
                                  "baseType": "Mask", "frameType": 3,
                                  "inventoryId": "Helm"})
    dialog = PaperdollDialog(_char(), [unique], pixmap_for=lambda item: None)
    assert "Gull" in _labels(dialog)


def test_slots_are_coloured_by_rarity_like_the_item_table(qapp) -> None:
    """Sonst sieht man der Puppe nicht an, welches Teil das Unique ist."""
    from poe_view.ui.theme import RARITY_COLORS

    unique = Item.model_validate({"name": "Gull", "baseType": "Mask",
                                  "frameType": 3, "inventoryId": "Helm"})
    dialog = PaperdollDialog(_char(), [unique], pixmap_for=lambda item: None)

    belegt = next(b for b in _slot_buttons(dialog) if _label(b) == "Gull")
    leer = next(b for b in _slot_buttons(dialog) if _label(b).startswith("("))
    assert RARITY_COLORS[3] in belegt.styleSheet()
    assert leer.styleSheet() == ""  # leere Plaetze bleiben unbunt


def test_the_paperdoll_is_written_in_english_like_the_rest_of_the_ui(qapp) -> None:
    """Oberflaeche englisch, Kommentare und Projektdoku deutsch (bewusste
    Trennung). Neben dem Settings-Dialog war die Paperdoll die zweite
    Stelle, an der die Grenze verrutscht war — samtliche Slot-Namen,
    "Ausruestung", "Flasche" und "Jewels im Passiv-Baum" standen deutsch
    im Fenster."""
    from PySide6.QtWidgets import QAbstractButton, QGroupBox, QLabel

    char = Character(name="WitchOfPeter", league="Standard", classId=0,
                     ascendancyClass=0, **{"class": "Chieftain"}, level=90,
                     experience=0)
    dialog = PaperdollDialog(char, [
        _item("Flask", "Divine Life Flask"),
        _item("PassiveJewels", "The Red Nightmare"),
        _item("Weapon2", "Swap Bow"),
    ], lambda item: None)

    texts = []
    for kind in (QGroupBox, QLabel, QAbstractButton):
        texts += [w.title() if kind is QGroupBox else w.text()
                  for w in dialog.findChildren(kind)]
    joined = " ".join(t for t in texts if t)

    for umlaut in "äöüß":
        assert umlaut not in joined, f"deutscher Text in der Paperdoll: {umlaut!r}"
    for german in ("Flasche", "Passiv-Baum", "Waffe", "Tausch"):
        assert german not in joined, f"deutscher Text in der Paperdoll: {german!r}"

    # Und die Beschriftungen sind wirklich da — sonst prueft der Test nichts.
    assert "Equipment" in joined
    assert "Jewels in the passive tree" in joined
    assert "(Body Armour)" in joined  # Platzhalter eines leeren Slots

    dialog.deleteLater()
