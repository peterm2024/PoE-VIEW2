"""Tests für den CSV-Export — laut Nutzer der wichtigste Punkt des Features."""

import csv
import json

from poe_view.api.models import Item
from poe_view.api.ninja import PriceIndex
from poe_view.services.csv_export import (FIELDNAMES, RAW_JSON_FIELD, export_items,
                                          sanitize_filename)

GEM = Item.model_validate({
    "typeLine": "Awakened Multistrike Support", "frameType": 4, "corrupted": True,
    "properties": [{"name": "Level", "values": [["5 (Max)", 0]]},
                   {"name": "Quality", "values": [["+20%", 1]]}],
})

# Rare mit allem, was ein Item an Listen und Zusatzfeldern mitbringen kann —
# genau die Felder, die vor 0.4.0 im Export fehlten.
FULL_RARE = Item.model_validate({
    "id": "abc123",
    "name": "Doom Grip",
    "typeLine": "Titan Gauntlets",
    "baseType": "Titan Gauntlets",
    "frameType": 2,
    "ilvl": 84,
    "x": 3, "y": 5,
    "identified": False,
    "corrupted": True,
    "duplicated": True,
    "fractured": True,
    "influences": {"shaper": True, "elder": False, "crusader": True},
    "note": "~price 5 divine",
    "properties": [{"name": "Armour", "values": [["450", 0]]}],
    "requirements": [{"name": "Level", "values": [["68", 0]]},
                     {"name": "Str", "values": [["98", 0]]},
                     {"name": "Dex", "values": [["45", 0]]}],
    "implicitMods": ["+12 to maximum Life"],
    "explicitMods": ["+78 to maximum Life", "+34% to Fire Resistance"],
    "craftedMods": ["+18% to Cold Resistance"],
    "enchantMods": ["Word of Fury"],
    "fracturedMods": ["+29% to Chaos Resistance"],
    "sockets": [{"group": 0, "sColour": "R"}, {"group": 0, "sColour": "R"},
                {"group": 0, "sColour": "G"}, {"group": 1, "sColour": "B"}],
})


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


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


def test_export_covers_every_item_facet(tmp_path) -> None:
    """Peter, 2026-08-02: "Im CSV hätte ich gerne alle Eigenschaften eines
    Items." Prüft je Feldgruppe einen Vertreter — Grunddaten, Position,
    Anforderungen, Sockets/Links, Merkmale, Einflüsse, alle Mod-Arten,
    Properties und die Preisnotiz."""
    path = tmp_path / "full.csv"
    export_items(str(path), [("Rares", FULL_RARE)])
    row = read_rows(path)[0]

    assert row["Name"] == "Doom Grip"
    assert row["Category"] == "Gloves"
    assert row["ItemLevel"] == "84"
    assert (row["X"], row["Y"]) == ("3", "5")
    assert (row["ReqLevel"], row["ReqStr"], row["ReqDex"]) == ("68", "98", "45")
    assert row["Sockets"] == "R-R-G B"
    assert row["Links"] == "3"
    assert row["Identified"] == "no"
    assert row["Corrupted"] == "yes"
    assert row["Mirrored"] == "yes"        # GGG nennt das Feld "duplicated"
    assert row["Fractured"] == "yes"
    assert row["Synthesised"] == ""        # nicht gesetzt → leer, nicht "no"
    assert row["Influences"] == "crusader | shaper"   # elder ist false
    assert row["Properties"] == "Armour: 450"
    assert row["ImplicitMods"] == "+12 to maximum Life"
    assert row["ExplicitMods"] == "+78 to maximum Life | +34% to Fire Resistance"
    assert row["CraftedMods"] == "+18% to Cold Resistance"
    assert row["EnchantMods"] == "Word of Fury"
    assert row["FracturedMods"] == "+29% to Chaos Resistance"
    assert row["Note"] == "~price 5 divine"
    assert row["ItemId"] == "abc123"


def test_export_value_is_a_plain_number_times_stack(tmp_path) -> None:
    """ValueChaos bewusst ohne Einheit und ohne Divine-Umrechnung: in einer
    Tabellenkalkulation ist eine einheitliche Zahl weiterverarbeitbar."""
    index = PriceIndex()
    index._simple.update({"Divine Orb": 200.0, "Vaal Orb": 0.7})
    stack = Item.model_validate({"typeLine": "Vaal Orb", "frameType": 5, "stackSize": 10})
    divines = Item.model_validate({"typeLine": "Divine Orb", "frameType": 5, "stackSize": 3})

    path = tmp_path / "value.csv"
    export_items(str(path), [("$", stack), ("$", divines)], price_index=index)
    rows = read_rows(path)
    assert rows[0]["ValueChaos"] == "7.00"     # 0.7 × 10
    assert rows[1]["ValueChaos"] == "600.00"   # 200 × 3, NICHT "3.0div"


def test_export_without_price_index_leaves_value_empty(tmp_path) -> None:
    """Liga ohne poe.ninja-Daten (z. B. SSF): leer statt 0 — ein unbekannter
    Preis ist etwas anderes als ein wertloses Item."""
    path = tmp_path / "noprice.csv"
    export_items(str(path), [("Rares", FULL_RARE)])
    assert read_rows(path)[0]["ValueChaos"] == ""


def test_raw_json_column_is_opt_in_and_complete(tmp_path) -> None:
    """Die Roh-Spalte ist die Antwort auf "wirklich alles", aber nicht die
    Voreinstellung (Dateigröße, siehe csv_export-Docstring)."""
    plain, raw = tmp_path / "plain.csv", tmp_path / "raw.csv"
    export_items(str(plain), [("Rares", FULL_RARE)])
    export_items(str(raw), [("Rares", FULL_RARE)], raw_json=True)

    assert RAW_JSON_FIELD not in read_rows(plain)[0]
    payload = json.loads(read_rows(raw)[0][RAW_JSON_FIELD])
    # Auch ein Feld, das KEINE eigene Spalte hat, ist darin enthalten.
    assert payload["influences"] == {"shaper": True, "elder": False, "crusader": True}
    assert payload["name"] == "Doom Grip"


def test_export_header_order_is_stable(tmp_path) -> None:
    """Der Spaltensatz ist fest, nicht aus den Daten abgeleitet — sonst
    verschöbe sich die Tabelle je nachdem, welche Items gerade exportiert
    werden, und Excel-Vorlagen brächen bei jedem Export."""
    path = tmp_path / "header.csv"
    export_items(str(path), [("Gems", GEM)])
    with open(path, encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f, delimiter=";"))
    assert header == FIELDNAMES


def test_sanitize_filename_strips_invalid_windows_chars() -> None:
    assert sanitize_filename("a:b") == "a_b"
    assert sanitize_filename("a<b>c") == "a_b_c"


def test_sanitize_filename_collapses_whitespace_to_dash() -> None:
    assert sanitize_filename("Chaos   Orb") == "Chaos-Orb"


def test_sanitize_filename_empty_uses_fallback() -> None:
    assert sanitize_filename("   ", fallback="items") == "items"


def test_sanitize_filename_truncates_long_input() -> None:
    assert len(sanitize_filename("x" * 200)) == 60
