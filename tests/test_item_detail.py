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
