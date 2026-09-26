"""Tests für die Zonen-Tabelle (``ui/zone_table.py``) samt CSV-Export."""

import csv

from PySide6.QtCore import Qt

from poe_view.services.zone_catalog import MAP, REST, STORY, ZoneRecord
from poe_view.ui.zone_table import (NUMERIC_SORT_ROLE, ZoneFilterProxy,
                                    ZoneTableModel, export_zones)

_LEVEL_COL = 2
_NAME_COL = 1


def record(area_id: str, name: str, category: str, levels: set[int],
           visits: int = 1, last_seen: str = "2026-09-26T12:00:00") -> ZoneRecord:
    return ZoneRecord(area_id=area_id, name=name, category=category,
                      levels=set(levels), visits=visits, last_seen=last_seen)


def beispiel() -> list[ZoneRecord]:
    return [
        record("MapWorldsAtoll", "Atoll", MAP, {70, 77}, visits=48),
        record("MapWorldsCells", "Cells", MAP, {68}, visits=3),
        record("2_9_1", "The Blood Aqueduct", STORY, {61}, visits=37),
        record("HideoutSlum", "Backstreet Hideout", REST, {60}, visits=908),
    ]


def test_a_range_of_levels_sorts_by_the_highest_one(qapp) -> None:
    """"70–77" ist als Text sinnlos sortierbar — die Spalte muss nach
    Zahl gehen, sonst steht "68" hinter "61" aber vor "70–77"."""
    model = ZoneTableModel(beispiel())
    idx = model.index(0, _LEVEL_COL)          # Atoll
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "70–77"
    assert model.data(idx, NUMERIC_SORT_ROLE) == 77


def test_the_level_tooltip_lists_every_level_seen(qapp) -> None:
    """Die Zelle zeigt die Spanne (bei Delve wären es 34 Werte), der
    Tooltip die Einzelwerte — genau das, was man bei einer Spanne fragt."""
    model = ZoneTableModel(beispiel())
    tooltip = model.data(model.index(0, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert tooltip == "Levels seen: 70, 77"


def test_the_tooltip_adds_what_the_character_would_still_get(qapp) -> None:
    model = ZoneTableModel(beispiel(), character_level=96)
    tooltip = model.data(model.index(1, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert "character level 96" in tooltip
    assert "yields" in tooltip


def test_without_a_character_the_tooltip_says_nothing_about_experience(qapp) -> None:
    model = ZoneTableModel(beispiel())
    tooltip = model.data(model.index(1, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert "yields" not in tooltip


def test_the_group_filter_narrows_to_one_category(qapp) -> None:
    model = ZoneTableModel(beispiel())
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_group(MAP)

    assert proxy.rowCount() == 2
    proxy.set_group("")
    assert proxy.rowCount() == 4


def test_search_matches_name_id_group_and_level(qapp) -> None:
    model = ZoneTableModel(beispiel())
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    for begriff, treffer in (("atoll", 1), ("mapworlds", 2), ("rest", 1),
                             ("61", 1), ("blood aqueduct", 1)):
        proxy.setFilterFixedString(begriff)
        assert proxy.rowCount() == treffer, begriff


def test_search_and_group_filter_combine(qapp) -> None:
    model = ZoneTableModel(beispiel())
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_group(MAP)
    proxy.setFilterFixedString("cells")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, _NAME_COL),
                      Qt.ItemDataRole.DisplayRole) == "Cells"


def test_the_csv_writes_the_levels_individually(tmp_path) -> None:
    """In der Anzeige steht "70–77", in der Datei stehen die Zahlen — eine
    Tabellenkalkulation soll damit rechnen können, und "70–77" ist dort
    Text."""
    ziel = tmp_path / "zones.csv"
    export_zones(str(ziel), beispiel())

    with open(ziel, encoding="utf-8-sig", newline="") as datei:
        zeilen = list(csv.reader(datei, delimiter=";"))

    assert zeilen[0][:3] == ["Group", "Zone", "Area id"]
    atoll = next(z for z in zeilen if z[1] == "Atoll")
    assert atoll[3] == "70" and atoll[4] == "77"
    assert atoll[5] == "70 77"
    assert atoll[6] == "48"


def test_the_csv_carries_a_bom_so_excel_opens_it_directly(tmp_path) -> None:
    """Dieselbe Regel wie beim Item-Export: ohne BOM zerlegt Excel unter
    deutscher Locale die Umlaute."""
    ziel = tmp_path / "zones.csv"
    export_zones(str(ziel), beispiel())
    assert ziel.read_bytes().startswith(b"\xef\xbb\xbf")


def test_sorting_by_group_puts_story_first_and_orders_by_level(qapp) -> None:
    """Peter hat "unterteilt nach Story, Map und Special-Maps" bestellt.
    Alphabetisch stünde da "Map, Rest, Special, Story" — richtig sortiert
    und trotzdem verkehrt herum."""
    model = ZoneTableModel(beispiel())
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.sort(0, Qt.SortOrder.AscendingOrder)   # Group-Spalte

    namen = [proxy.data(proxy.index(zeile, _NAME_COL), Qt.ItemDataRole.DisplayRole)
             for zeile in range(proxy.rowCount())]
    assert namen == ["The Blood Aqueduct",       # Story
                     "Cells", "Atoll",           # Map, nach Level (68, 77)
                     "Backstreet Hideout"]       # Rest
