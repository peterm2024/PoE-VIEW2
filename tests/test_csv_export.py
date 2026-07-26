"""Tests für den CSV-Export — laut Nutzer der wichtigste Punkt des Features."""

import csv

from poe_view.api.models import Item
from poe_view.services.csv_export import export_items, sanitize_filename

GEM = Item.model_validate({
    "typeLine": "Awakened Multistrike Support", "frameType": 4, "corrupted": True,
    "properties": [{"name": "Level", "values": [["5 (Max)", 0]]},
                   {"name": "Quality", "values": [["+20%", 1]]}],
})


def test_export_writes_semicolon_csv_with_bom(tmp_path) -> None:
    path = tmp_path / "export.csv"
    count = export_items(str(path), [("Gems", GEM)])
    assert count == 1

    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8-BOM, wichtig für Excel/de-DE

    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert rows[0]["Tab"] == "Gems"
    assert rows[0]["Name"] == "Awakened Multistrike Support"
    assert rows[0]["Level"] == "5"
    assert rows[0]["Quality"] == "+20%"
    assert rows[0]["Corrupted"] == "yes"


def test_export_empty_list_writes_header_only(tmp_path) -> None:
    path = tmp_path / "empty.csv"
    count = export_items(str(path), [])
    assert count == 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert rows == []


def test_sanitize_filename_strips_invalid_windows_chars() -> None:
    assert sanitize_filename("a:b") == "a_b"
    assert sanitize_filename("a<b>c") == "a_b_c"


def test_sanitize_filename_collapses_whitespace_to_dash() -> None:
    assert sanitize_filename("Chaos   Orb") == "Chaos-Orb"


def test_sanitize_filename_empty_uses_fallback() -> None:
    assert sanitize_filename("   ", fallback="items") == "items"


def test_sanitize_filename_truncates_long_input() -> None:
    assert len(sanitize_filename("x" * 200)) == 60
