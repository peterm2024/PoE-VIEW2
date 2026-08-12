"""Tests für das Item-Detail-Panel: Tag-Zeile (Unidentified/Corrupted)
und die Anforderungs-Zeile (iLvl/Req.Lvl/Str/Dex/Int)."""

from poe_view.api.models import Item
from poe_view.ui.item_detail import ItemDetail


def _item(**kwargs) -> Item:
    return Item.model_validate({"typeLine": "Sun Plate", "frameType": 2, **kwargs})


def test_identified_item_shows_no_tag(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(identified=True), None)
    assert "[" not in detail._name.text()


def test_unidentified_item_is_tagged(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(identified=False), None)
    assert "[Unidentified]" in detail._name.text()


def test_corrupted_item_is_tagged(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(corrupted=True), None)
    assert "[Corrupted]" in detail._name.text()


def test_unidentified_and_corrupted_both_shown(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(identified=False, corrupted=True), None)
    assert "[Unidentified, Corrupted]" in detail._name.text()


def test_requirement_line_shows_ilvl_and_req_level(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(ilvl=82, requirements=[{"name": "Level", "values": [["68", 0]]}]), None)
    assert "iLvl 82" in detail._props.text()
    assert "Req. Lvl 68" in detail._props.text()


def test_requirement_line_shows_attribute_requirements(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(requirements=[
        {"name": "Str", "values": [["155", 0]]},
        {"name": "Dex", "values": [["50", 0]]},
    ]), None)
    props = detail._props.text()
    assert "Req. Str 155" in props
    assert "Req. Dex 50" in props
    assert "Req. Int" not in props


def test_requirement_line_absent_when_nothing_known(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(), None)
    lines = detail._props.text().split("\n")
    assert not any("iLvl" in line or "Req." in line for line in lines)


# --- Gliederung in Bloecke (Peter, 2026-08-12: "etwas uebersichtlicher") --- #

def _blocks(item: Item) -> list[list[str]]:
    from poe_view.ui.item_detail import _item_blocks
    return [b for b in _item_blocks(item) if b]


def test_the_implicit_mod_is_its_own_block() -> None:
    """Der Kern der Ueberarbeitung. Vorher lief alles als flache Liste
    untereinander, und WELCHER Mod der implizite ist, war ueberhaupt
    nicht zu erkennen — im Spiel trennt ihn eine Linie ab."""
    blocks = _blocks(Item.model_validate({
        "typeLine": "Opal Sceptre", "name": "Soul Bane", "frameType": 2,
        "implicitMods": ["40% increased Elemental Damage"],
        "explicitMods": ["69% increased Fire Damage", "+109 to maximum Mana"],
    }))

    assert ["40% increased Elemental Damage"] in blocks
    assert ["69% increased Fire Damage", "+109 to maximum Mana"] in blocks


def test_properties_requirements_and_mods_are_separate_blocks() -> None:
    blocks = _blocks(Item.model_validate({
        "typeLine": "Opal Sceptre", "name": "Soul Bane", "frameType": 2, "ilvl": 70,
        "properties": [{"name": "Quality", "values": [["+20%", 1]]}],
        "requirements": [{"name": "Level", "values": [["68", 0]]}],
        "explicitMods": ["+109 to maximum Mana"],
    }))

    assert blocks == [
        ["Rare · Opal Sceptre"],
        ["Quality: +20%"],
        ["iLvl 70 · Req. Lvl 68"],
        ["+109 to maximum Mana"],
    ]


def test_enchantments_and_utility_mods_are_shown_at_all() -> None:
    """Dieselbe Luecke wie im Item-Textexport: Das Panel kannte nur
    explicitMods und implicitMods. Ein verzauberter Helm und jede
    Utility-Flasche zeigten ihren eigentlichen Inhalt gar nicht."""
    blocks = _blocks(Item.model_validate({
        "typeLine": "Granite Flask", "frameType": 1,
        "enchantMods": ["Adds 4 Passive Skills"],
        "implicitMods": ["10% increased Frenzy Charge Duration"],
        "utilityMods": ["+1500 to Armour"],
    }))

    # Verzauberung ueber dem impliziten Mod, Flaschen-Effekt bei den
    # expliziten — dieselbe Aufteilung wie im Textexport.
    assert blocks[-3:] == [
        ["Adds 4 Passive Skills"],
        ["10% increased Frenzy Charge Duration"],
        ["+1500 to Armour"],
    ]


def test_truncation_says_that_it_truncated(qapp) -> None:
    """Der eigentliche Mangel der alten Fassung war nicht die Grenze,
    sondern dass sie STILL zuschlug: Peters "Pain Crusher" lag mit exakt
    zwoelf Zeilen auf der Kante, ein Mod mehr waere wortlos verschwunden."""
    detail = ItemDetail()
    detail.show_item(Item.model_validate({
        "typeLine": "Sun Plate", "frameType": 2,
        "explicitMods": [f"Mod {n}" for n in range(40)]}), None)

    text = detail._props.text()
    assert "more" in text and "double-click" in text


def test_nothing_is_cut_off_silently_below_the_limit(qapp) -> None:
    """Gegenprobe: Solange es passt, taucht der Hinweis nicht auf."""
    detail = ItemDetail()
    detail.show_item(Item.model_validate({
        "typeLine": "Sun Plate", "frameType": 2,
        "explicitMods": ["+43 to Armour", "+27 to maximum Life"]}), None)

    assert "more" not in detail._props.text()


def test_mod_text_is_escaped_for_the_rich_text_label(qapp) -> None:
    """Das Panel rendert seit der Gliederung HTML (fuer die Trennlinien).
    Ein Mod-Text mit spitzen Klammern darf dadurch nicht als Markup
    gedeutet werden und verschwinden."""
    detail = ItemDetail()
    detail.show_item(Item.model_validate({
        "typeLine": "Sun Plate", "frameType": 2,
        "explicitMods": ["Deals <b>50</b> Damage"]}), None)

    assert "&lt;b&gt;" in detail._props.text()


def test_the_panel_height_does_not_change_with_the_item(qapp) -> None:
    """Peter, 2026-08-13: "Koennen wir den XP-Bereich unten
    ausrichten/fixieren? Dann wackelt das beim Item-Wechsel nicht so
    rum." Ein Ring mit zwei Mods und ein Unique mit acht liessen das
    Panel sonst bei jedem Klick springen — und mit ihm das Leveling-Feld
    daneben und den unteren Rand der Tabelle darueber."""
    detail = ItemDetail()
    hoehen = set()
    for mods in ([], ["+43 to Armour"], [f"Mod {n}" for n in range(30)]):
        detail.show_item(Item.model_validate({
            "typeLine": "Sun Plate", "frameType": 2, "explicitMods": mods}), None)
        hoehen.add(detail.height())

    assert len(hoehen) == 1


def test_the_panel_is_at_least_as_tall_as_its_own_icon(qapp) -> None:
    """Gegenprobe zur festen Hoehe: Ein Currency-Item ohne Mods darf das
    Panel nicht kleiner machen als das Bild, das darin steht."""
    assert ItemDetail().height() >= 64


def test_the_preferred_width_fits_a_typical_mod_line(qapp) -> None:
    """Grundlage der Splitter-Position (Peter: "anhand der Zeilenbreite
    berechnen"). Gemessen an 201.426 echten Mod-Zeilen passen 95 % in 68
    Zeichen; die Breite muss also mindestens so viel Text plus Icon
    fassen."""
    detail = ItemDetail()
    metrics = detail._props.fontMetrics()

    assert detail.preferred_width() >= metrics.averageCharWidth() * 68 + 64
