"""Tests für die Zonen-Tabelle (``ui/zone_table.py``) samt CSV-Export.

Die Season-Trennung ist hier kein Beiwerk: Derselbe Kartenname trägt in
jeder Season einen anderen Monsterlevel (an Peters Log gemessen, siehe
``services/season_log``), und eine Tabelle, die das zusammenwirft, zeigt
Spannen, die es nie gab.
"""

import csv

from PySide6.QtCore import Qt

from poe_view.services.season_log import EARLIER
from poe_view.services.zone_catalog import (MAP, REST, STORY, SeasonStats,
                                            ZoneRecord)
from poe_view.ui.zone_table import (NUMERIC_SORT_ROLE, ZoneFilterProxy,
                                    ZoneTableModel, _season_choices,
                                    export_zones)

_LEVEL_COL = 2
_VISITS_COL = 3
_NAME_COL = 1

ALLFLAME = "Allflame"
MIRAGE = "Mirage"


def record(area_id: str, name: str, category: str,
           seasons: dict[str, tuple[set[int], int, str]]) -> ZoneRecord:
    return ZoneRecord(
        area_id=area_id, name=name, category=category,
        seasons={season: SeasonStats(levels=set(levels), visits=visits,
                                     last_seen=zuletzt)
                 for season, (levels, visits, zuletzt) in seasons.items()})


def beispiel() -> list[ZoneRecord]:
    """Vier Zonen, wie sie in Peters Katalog stehen — Atoll mit dem
    echten Season-Sprung von 70 auf 77."""
    return [
        record("MapWorldsAtoll", "Atoll", MAP,
               {MIRAGE: ({70}, 12, "2026-07-01T10:00:00"),
                ALLFLAME: ({77}, 36, "2026-09-20T10:00:00")}),
        record("MapWorldsCells", "Cells", MAP,
               {ALLFLAME: ({68}, 3, "2026-09-26T10:11:17")}),
        record("2_9_1", "The Blood Aqueduct", STORY,
               {MIRAGE: ({61}, 20, "2026-07-02T10:00:00"),
                ALLFLAME: ({61}, 17, "2026-09-01T10:00:00")}),
        record("HideoutSlum", "Backstreet Hideout", REST,
               {ALLFLAME: ({60}, 908, "2026-09-26T13:48:20")}),
    ]


# --- Season-Trennung --------------------------------------------------- #

def test_the_level_column_shows_only_the_selected_seasons_level(qapp) -> None:
    """Der eigentliche Punkt: Atoll stand in Mirage auf 70 und steht in
    Allflame auf 77. Ohne Trennung stünde da "70–77" — eine Spanne, die
    es nie gab."""
    model = ZoneTableModel(beispiel(), season=ALLFLAME)
    assert model.data(model.index(0, _LEVEL_COL),
                      Qt.ItemDataRole.DisplayRole) == "77"

    model.set_season(MIRAGE)
    assert model.data(model.index(0, _LEVEL_COL),
                      Qt.ItemDataRole.DisplayRole) == "70"


def test_all_seasons_together_show_the_whole_range(qapp) -> None:
    """Wer ausdrücklich alle Seasons wählt, bekommt die Spanne — und im
    Tooltip, aus welcher Season welcher Level stammt."""
    model = ZoneTableModel(beispiel(), season=None)
    idx = model.index(0, _LEVEL_COL)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "70–77"
    tooltip = model.data(idx, Qt.ItemDataRole.ToolTipRole)
    assert "Allflame: 77" in tooltip
    assert "Mirage: 70" in tooltip


def test_visits_and_last_seen_follow_the_season(qapp) -> None:
    model = ZoneTableModel(beispiel(), season=ALLFLAME)
    assert model.data(model.index(0, _VISITS_COL),
                      Qt.ItemDataRole.DisplayRole) == "36"
    model.set_season(MIRAGE)
    assert model.data(model.index(0, _VISITS_COL),
                      Qt.ItemDataRole.DisplayRole) == "12"
    model.set_season(None)
    assert model.data(model.index(0, _VISITS_COL),
                      Qt.ItemDataRole.DisplayRole) == "48"


def test_a_zone_not_played_in_that_season_disappears(qapp) -> None:
    """Sonst stünde eine leere Level-Spalte da und sähe aus wie ein
    Fehler. Cells gab es in Mirage nicht (jedenfalls nicht betreten)."""
    model = ZoneTableModel(beispiel(), season=MIRAGE)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    namen = [proxy.data(proxy.index(z, _NAME_COL), Qt.ItemDataRole.DisplayRole)
             for z in range(proxy.rowCount())]
    assert set(namen) == {"Atoll", "The Blood Aqueduct"}


def test_the_season_choices_are_newest_first_with_earlier_last() -> None:
    """Die Namen selbst tragen keine Ordnung ("Allflame" vor "Mirage"?)
    — sortiert wird nach dem jüngsten Besuch."""
    zonen = beispiel() + [record("MapWorldsPit", "Pit", MAP,
                                 {EARLIER: ({80}, 2, "2026-03-01T10:00:00")})]
    assert _season_choices(zonen) == [ALLFLAME, MIRAGE, EARLIER]


def test_season_choices_only_list_what_the_catalogue_holds() -> None:
    """Eine Season, in der dieses Konto nie gespielt hat, waere ein
    Eintrag, der immer auf eine leere Tabelle fuehrt."""
    assert _season_choices([beispiel()[1]]) == [ALLFLAME]


# --- Sortierung, Suche, Tooltip ---------------------------------------- #

def test_a_range_of_levels_sorts_by_the_highest_one(qapp) -> None:
    """"70–77" ist als Text sinnlos sortierbar — die Spalte muss nach
    Zahl gehen, sonst steht "68" hinter "61" aber vor "70–77"."""
    model = ZoneTableModel(beispiel(), season=None)
    idx = model.index(0, _LEVEL_COL)
    assert model.data(idx, NUMERIC_SORT_ROLE) == 77


def test_the_level_tooltip_lists_every_level_seen(qapp) -> None:
    """Die Zelle zeigt die Spanne (bei Delve wären es 34 Werte), der
    Tooltip die Einzelwerte — genau das, was man bei einer Spanne fragt."""
    model = ZoneTableModel(beispiel(), season=None)
    tooltip = model.data(model.index(0, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert tooltip.startswith("Levels seen: 70, 77")


def test_the_tooltip_adds_what_the_character_would_still_get(qapp) -> None:
    model = ZoneTableModel(beispiel(), character_level=96, season=ALLFLAME)
    tooltip = model.data(model.index(1, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert "character level 96" in tooltip
    assert "yields" in tooltip


def test_without_a_character_the_tooltip_says_nothing_about_experience(qapp) -> None:
    model = ZoneTableModel(beispiel(), season=ALLFLAME)
    tooltip = model.data(model.index(1, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert "yields" not in tooltip


def test_the_group_filter_narrows_to_one_category(qapp) -> None:
    model = ZoneTableModel(beispiel(), season=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_group(MAP)

    assert proxy.rowCount() == 2
    proxy.set_group("")
    assert proxy.rowCount() == 4


def test_search_matches_name_id_group_and_level(qapp) -> None:
    model = ZoneTableModel(beispiel(), season=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    for begriff, treffer in (("atoll", 1), ("mapworlds", 2), ("rest", 1),
                             ("61", 1), ("blood aqueduct", 1)):
        proxy.setFilterFixedString(begriff)
        assert proxy.rowCount() == treffer, begriff


def test_search_and_group_filter_combine(qapp) -> None:
    model = ZoneTableModel(beispiel(), season=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_group(MAP)
    proxy.setFilterFixedString("cells")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, _NAME_COL),
                      Qt.ItemDataRole.DisplayRole) == "Cells"


def test_sorting_by_group_puts_story_first_and_orders_by_level(qapp) -> None:
    """Peter hat "unterteilt nach Story, Map und Special-Maps" bestellt.
    Alphabetisch stünde da "Map, Rest, Special, Story" — richtig sortiert
    und trotzdem verkehrt herum."""
    model = ZoneTableModel(beispiel(), season=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.sort(0, Qt.SortOrder.AscendingOrder)   # Group-Spalte

    namen = [proxy.data(proxy.index(zeile, _NAME_COL), Qt.ItemDataRole.DisplayRole)
             for zeile in range(proxy.rowCount())]
    assert namen == ["The Blood Aqueduct",       # Story
                     "Cells", "Atoll",           # Map, nach Level (68, 77)
                     "Backstreet Hideout"]       # Rest


def test_sorting_follows_the_season(qapp) -> None:
    """In Mirage stand Atoll auf 70, in Allflame auf 77 — die Reihenfolge
    innerhalb der Gruppe haengt also an der gewaehlten Season."""
    zonen = [record("MapWorldsAtoll", "Atoll", MAP,
                    {MIRAGE: ({70}, 1, "2026-07-01T10:00:00"),
                     ALLFLAME: ({77}, 1, "2026-09-01T10:00:00")}),
             record("MapWorldsPit", "Pit", MAP,
                    {MIRAGE: ({75}, 1, "2026-07-01T10:00:00"),
                     ALLFLAME: ({72}, 1, "2026-09-01T10:00:00")})]
    model = ZoneTableModel(zonen, season=MIRAGE)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)
    proxy.sort(0, Qt.SortOrder.AscendingOrder)

    def namen():
        return [proxy.data(proxy.index(z, _NAME_COL), Qt.ItemDataRole.DisplayRole)
                for z in range(proxy.rowCount())]

    assert namen() == ["Atoll", "Pit"]           # 70 vor 75
    model.set_season(ALLFLAME)
    proxy.sort(0, Qt.SortOrder.AscendingOrder)
    assert namen() == ["Pit", "Atoll"]           # 72 vor 77


# --- CSV ---------------------------------------------------------------- #

def test_the_csv_writes_the_levels_individually(tmp_path) -> None:
    """In der Anzeige steht "70–77", in der Datei stehen die Zahlen — eine
    Tabellenkalkulation soll damit rechnen können, und "70–77" ist dort
    Text."""
    ziel = tmp_path / "zones.csv"
    export_zones(str(ziel), beispiel(), ALLFLAME)

    with open(ziel, encoding="utf-8-sig", newline="") as datei:
        zeilen = list(csv.reader(datei, delimiter=";"))

    assert zeilen[0][:4] == ["Season", "Group", "Zone", "Area id"]
    atoll = next(z for z in zeilen if z[2] == "Atoll")
    assert atoll[0] == ALLFLAME
    assert atoll[4] == "77" and atoll[5] == "77"
    assert atoll[7] == "36"


def test_the_csv_gives_every_season_its_own_row(tmp_path) -> None:
    """Ueber alle Seasons hinweg eine Zeile je Season: Eine Zeile
    "Atoll 70–77" gaebe einen Wert wieder, den es nie gab."""
    ziel = tmp_path / "zones.csv"
    export_zones(str(ziel), beispiel(), None)

    with open(ziel, encoding="utf-8-sig", newline="") as datei:
        zeilen = [z for z in csv.reader(datei, delimiter=";") if z[2] == "Atoll"]

    assert [(z[0], z[6]) for z in zeilen] == [(ALLFLAME, "77"), (MIRAGE, "70")]


def test_the_csv_carries_a_bom_so_excel_opens_it_directly(tmp_path) -> None:
    """Dieselbe Regel wie beim Item-Export: ohne BOM zerlegt Excel unter
    deutscher Locale die Umlaute."""
    ziel = tmp_path / "zones.csv"
    export_zones(str(ziel), beispiel(), ALLFLAME)
    assert ziel.read_bytes().startswith(b"\xef\xbb\xbf")
