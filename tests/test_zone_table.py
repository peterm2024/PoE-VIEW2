"""Tests für die Zonen-Tabelle (``ui/zone_table.py``) samt CSV-Export.

Die Season-Trennung ist hier kein Beiwerk: Derselbe Kartenname trägt in
jeder Season einen anderen Monsterlevel (an Peters Log gemessen, siehe
``services/season_log``), und eine Tabelle, die das zusammenwirft, zeigt
Spannen, die es nie gab.
"""

import csv

from PySide6.QtCore import Qt

from poe_view.services.league_log import UNKNOWN
from poe_view.services.zone_catalog import (MAP, REST, SIDE_AREA, STORY,
                                            LeagueStats, LevelStats,
                                            ZoneRecord)
from poe_view.ui.zone_table import (NUMERIC_SORT_ROLE, ZoneFilterProxy,
                                    ZoneTreeModel, _dauer_text,
                                    _league_choices, export_zones)

_NAME_COL = 1
_TIER_COL = 2
_LEVEL_COL = 3
_VISITS_COL = 4
_ENTRIES_COL = 5
_DEATHS_COL = 6
_TIME_COL = 7
_ID_COL = 9

ALLFLAME = "Allflame"
MIRAGE = "SSF Ruthless (earlier)"


def record(area_id: str, name: str, category: str,
           seasons: dict[str, tuple[set[int], int, str]]) -> ZoneRecord:
    """Kurzform für Tests, die nur Gesamtzahlen prüfen: Die Besuche
    landen auf der NIEDRIGSTEN genannten Stufe, die übrigen Stufen
    bleiben als gesehen stehen, ohne eigene Zahlen. Wer die Aufteilung
    selbst prüft, nimmt ``record_by_level``."""
    def zahlen(levels: set[int], visits: int, zuletzt: str) -> LeagueStats:
        stufen = sorted(levels)
        nach_level = {lv: LevelStats() for lv in stufen}
        if stufen:
            nach_level[stufen[0]] = LevelStats(visits=visits, last_seen=zuletzt)
        return LeagueStats(by_level=nach_level)

    return ZoneRecord(
        area_id=area_id, name=name, category=category,
        leagues={season: zahlen(*werte) for season, werte in seasons.items()})


def record_by_level(area_id: str, name: str, category: str,
                    leagues: dict[str, dict[int, LevelStats]]) -> ZoneRecord:
    """Ein Gebiet mit ausdrücklichen Zahlen je Gebietslevel — die Form,
    in der der Baum seine Kindzeilen zieht."""
    return ZoneRecord(
        area_id=area_id, name=name, category=category,
        leagues={liga: LeagueStats(by_level=dict(stufen))
                 for liga, stufen in leagues.items()})


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
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    assert model.data(model.index(0, _LEVEL_COL),
                      Qt.ItemDataRole.DisplayRole) == "77"

    model.set_league(MIRAGE)
    assert model.data(model.index(0, _LEVEL_COL),
                      Qt.ItemDataRole.DisplayRole) == "70"


def test_all_leagues_together_show_the_whole_range(qapp) -> None:
    """Wer ausdrücklich alle Ligen wählt, bekommt die Spanne — und im
    Tooltip, aus welcher Liga welcher Level stammt."""
    model = ZoneTreeModel(beispiel(), league=None)
    idx = model.index(0, _LEVEL_COL)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "70–77"
    tooltip = model.data(idx, Qt.ItemDataRole.ToolTipRole)
    assert "Allflame: 77" in tooltip
    assert f"{MIRAGE}: 70" in tooltip


def test_visits_and_last_seen_follow_the_season(qapp) -> None:
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    assert model.data(model.index(0, _VISITS_COL),
                      Qt.ItemDataRole.DisplayRole) == "36"
    model.set_league(MIRAGE)
    assert model.data(model.index(0, _VISITS_COL),
                      Qt.ItemDataRole.DisplayRole) == "12"
    model.set_league(None)
    assert model.data(model.index(0, _VISITS_COL),
                      Qt.ItemDataRole.DisplayRole) == "48"


def test_a_zone_not_played_in_that_season_disappears(qapp) -> None:
    """Sonst stünde eine leere Level-Spalte da und sähe aus wie ein
    Fehler. Cells gab es in Mirage nicht (jedenfalls nicht betreten)."""
    model = ZoneTreeModel(beispiel(), league=MIRAGE)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    namen = [proxy.data(proxy.index(z, _NAME_COL), Qt.ItemDataRole.DisplayRole)
             for z in range(proxy.rowCount())]
    assert set(namen) == {"Atoll", "The Blood Aqueduct"}


def test_the_season_choices_are_newest_first_with_earlier_last() -> None:
    """Die Namen selbst tragen keine Ordnung ("Allflame" vor "Mirage"?)
    — sortiert wird nach dem jüngsten Besuch."""
    zonen = beispiel() + [record("MapWorldsPit", "Pit", MAP,
                                 {UNKNOWN: ({80}, 2, "2026-03-01T10:00:00")})]
    assert _league_choices(zonen) == [ALLFLAME, MIRAGE, UNKNOWN]


def test_season_choices_only_list_what_the_catalogue_holds() -> None:
    """Eine Season, in der dieses Konto nie gespielt hat, waere ein
    Eintrag, der immer auf eine leere Tabelle fuehrt."""
    assert _league_choices([beispiel()[1]]) == [ALLFLAME]


# --- Sortierung, Suche, Tooltip ---------------------------------------- #

def test_a_range_of_levels_sorts_by_the_highest_one(qapp) -> None:
    """"70–77" ist als Text sinnlos sortierbar — die Spalte muss nach
    Zahl gehen, sonst steht "68" hinter "61" aber vor "70–77"."""
    model = ZoneTreeModel(beispiel(), league=None)
    idx = model.index(0, _LEVEL_COL)
    assert model.data(idx, NUMERIC_SORT_ROLE) == 77


def test_the_level_tooltip_lists_every_level_seen(qapp) -> None:
    """Die Zelle zeigt die Spanne (bei Delve wären es 34 Werte), der
    Tooltip die Einzelwerte — genau das, was man bei einer Spanne fragt."""
    model = ZoneTreeModel(beispiel(), league=None)
    tooltip = model.data(model.index(0, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert tooltip.startswith("Levels seen: 70, 77")


def test_the_tooltip_adds_what_the_character_would_still_get(qapp) -> None:
    model = ZoneTreeModel(beispiel(), character_level=96, league=ALLFLAME)
    tooltip = model.data(model.index(1, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert "character level 96" in tooltip
    assert "yields" in tooltip


def test_without_a_character_the_tooltip_says_nothing_about_experience(qapp) -> None:
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    tooltip = model.data(model.index(1, _LEVEL_COL), Qt.ItemDataRole.ToolTipRole)
    assert "yields" not in tooltip


def test_the_group_filter_narrows_to_one_category(qapp) -> None:
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_group(MAP)

    assert proxy.rowCount() == 2
    proxy.set_group("")
    assert proxy.rowCount() == 4


def test_search_matches_name_id_group_and_level(qapp) -> None:
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    for begriff, treffer in (("atoll", 1), ("mapworlds", 2), ("rest", 1),
                             ("61", 1), ("blood aqueduct", 1)):
        proxy.setFilterFixedString(begriff)
        assert proxy.rowCount() == treffer, begriff


def test_search_and_group_filter_combine(qapp) -> None:
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
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
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
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
    model = ZoneTreeModel(zonen, league=MIRAGE)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)
    proxy.sort(0, Qt.SortOrder.AscendingOrder)

    def namen():
        return [proxy.data(proxy.index(z, _NAME_COL), Qt.ItemDataRole.DisplayRole)
                for z in range(proxy.rowCount())]

    assert namen() == ["Atoll", "Pit"]           # 70 vor 75
    model.set_league(ALLFLAME)
    proxy.sort(0, Qt.SortOrder.AscendingOrder)
    assert namen() == ["Pit", "Atoll"]           # 72 vor 77


# --- CSV ---------------------------------------------------------------- #

def test_the_csv_writes_one_row_per_level(tmp_path) -> None:
    """Dieselbe Aufloesung, die der Baum aufgeklappt zeigt. Die
    Zusammenfassung liesse sich daraus jederzeit bilden, umgekehrt nicht:
    Aus "Bazaar, 6 Besuche, 71–72" ist nicht mehr herauszuholen, wieviele
    davon auf welcher Stufe lagen."""
    zonen = [record_by_level("MapWorldsBazaar", "Bazaar", MAP, {ALLFLAME: {
        71: LevelStats(visits=3, deaths=1, seconds=750, timed_visits=3,
                       last_seen="2026-09-15T22:59:13", entries=7),
        72: LevelStats(visits=3, deaths=0, seconds=738, timed_visits=3,
                       last_seen="2026-09-27T11:40:11", entries=5),
    }})]
    ziel = tmp_path / "zones.csv"
    export_zones(str(ziel), zonen, ALLFLAME)

    with open(ziel, encoding="utf-8-sig", newline="") as datei:
        zeilen = list(csv.reader(datei, delimiter=";"))

    assert zeilen[0][:6] == ["League", "Group", "Zone", "Area id", "Tier",
                             "Monster level"]
    bazaar = [z for z in zeilen if z[2] == "Bazaar"]
    assert len(bazaar) == 2
    assert zeilen[0][6:9] == ["Visits", "Entries", "Deaths"]
    assert [(z[4], z[5], z[6], z[7], z[8]) for z in bazaar] == [
        ("4", "71", "3", "7", "1"), ("5", "72", "3", "5", "0")]


def test_the_csv_gives_every_league_its_own_row(tmp_path) -> None:
    """Ueber alle Ligen hinweg eine Zeile je Liga: Eine Zeile
    "Atoll 70–77" gaebe einen Wert wieder, den es nie gab."""
    ziel = tmp_path / "zones.csv"
    export_zones(str(ziel), beispiel(), None)

    with open(ziel, encoding="utf-8-sig", newline="") as datei:
        zeilen = [z for z in csv.reader(datei, delimiter=";") if z[2] == "Atoll"]

    assert [(z[0], z[5]) for z in zeilen] == [(ALLFLAME, "77"), (MIRAGE, "70")]


def test_the_csv_carries_a_bom_so_excel_opens_it_directly(tmp_path) -> None:
    """Dieselbe Regel wie beim Item-Export: ohne BOM zerlegt Excel unter
    deutscher Locale die Umlaute."""
    ziel = tmp_path / "zones.csv"
    export_zones(str(ziel), beispiel(), ALLFLAME)
    assert ziel.read_bytes().startswith(b"\xef\xbb\xbf")


# --- Tier, Tode, Dauer --------------------------------------------------- #

def test_the_tier_column_shows_the_range_that_actually_occurred(qapp) -> None:
    """Urspruenglich stand hier nur die niedrigste Stufe (Peter: "Hier
    zaehlt natuerlich nur die niedrigmoeglichste Tier der Map") — unter
    der Annahme, eine Karte HABE eine feste Stufe. Die Messung an seiner
    Truhe hat das widerlegt: Die Karten sind nummerierte Items ("Map
    (Tier 4)") mit dem Text "Travel to a Map of this tier or lower", der
    Gebietslevel kommt also vom Item. Eine einzelne Zahl waere die
    Antwort auf eine Frage, die so nicht mehr steht.

    Atoll ueber alle Ligen: Tier 3 (Level 70, frueher) bis Tier 10
    (Level 77, heute). In Allflame allein bleibt es die 10."""
    model = ZoneTreeModel(beispiel(), league=None)
    assert model.data(model.index(0, _TIER_COL),
                      Qt.ItemDataRole.DisplayRole) == "3–10"
    model.set_league(ALLFLAME)
    assert model.data(model.index(0, _TIER_COL),
                      Qt.ItemDataRole.DisplayRole) == "10"      # 77 - 67
    # Sortiert wird weiter nach der niedrigsten Stufe — eine Spanne
    # laesst sich nicht vergleichen.
    model.set_league(None)
    assert model.data(model.index(0, _TIER_COL), NUMERIC_SORT_ROLE) == 3


def test_zones_without_a_tier_leave_the_column_empty(qapp) -> None:
    """Story-Gebiete und Hideouts tragen einen Level, aber keine Tier."""
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    assert model.data(model.index(2, _TIER_COL),     # The Blood Aqueduct
                      Qt.ItemDataRole.DisplayRole) == ""
    # ... und sortieren nach unten statt vor Tier 1.
    assert model.data(model.index(2, _TIER_COL), NUMERIC_SORT_ROLE) == -1


def test_deaths_and_average_time_show_per_league(qapp) -> None:
    zonen = [record("MapWorldsAtoll", "Atoll", MAP,
                    {ALLFLAME: ({77}, 4, "2026-09-20T10:00:00")})]
    stufe = zonen[0].leagues[ALLFLAME].at(77)
    stufe.deaths = 3
    stufe.seconds = 4 * 430
    stufe.timed_visits = 4
    model = ZoneTreeModel(zonen, league=ALLFLAME)

    assert model.data(model.index(0, _DEATHS_COL),
                      Qt.ItemDataRole.DisplayRole) == "3"
    assert model.data(model.index(0, _TIME_COL),
                      Qt.ItemDataRole.DisplayRole) == "7:10"


def test_a_zone_without_deaths_leaves_the_column_empty(qapp) -> None:
    """Eine 0 in jeder zweiten Zeile ist Rauschen; leer liest sich als
    "nichts passiert"."""
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    assert model.data(model.index(0, _DEATHS_COL),
                      Qt.ItemDataRole.DisplayRole) == ""


def test_the_duration_text_switches_to_minutes() -> None:
    assert _dauer_text(0) == ""
    assert _dauer_text(42) == "42 s"
    assert _dauer_text(60) == "1:00"
    assert _dauer_text(430) == "7:10"


def test_side_areas_are_their_own_group_in_the_filter(qapp) -> None:
    """Peters eigentlicher Punkt: In SSF Ruthless gibt es keine
    Vaal-Side-Areas — sie duerfen die Karten-Liste nicht verwaessern."""
    zonen = beispiel() + [record("MapSideArea4_2", "Ancient Catacomb",
                                 SIDE_AREA, {ALLFLAME: ({81}, 1,
                                                        "2026-08-13T18:43:09")})]
    model = ZoneTreeModel(zonen, league=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_group(MAP)
    namen = [proxy.data(proxy.index(z, _NAME_COL), Qt.ItemDataRole.DisplayRole)
             for z in range(proxy.rowCount())]
    assert "Ancient Catacomb" not in namen

    proxy.set_group(SIDE_AREA)
    assert proxy.rowCount() == 1


def test_an_endless_stay_does_not_drag_the_average_up() -> None:
    """Die Client.txt schreibt beim Beenden nichts — der letzte
    Aufenthalt endet erst beim naechsten Start. In Peters Log steht so
    ein Eintrag mit 19,6 Stunden; ueber einer Stunde liegen 7 von 1.108
    Map-Aufenthalten (0,6 %). Sie zaehlen als Besuch, aber nicht im
    Schnitt."""
    from datetime import datetime

    from poe_view.services import zone_catalog as zk
    from poe_view.services.zone_watcher import ZoneStay

    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [
        ZoneStay(entered=datetime(2026, 9, 26, 12, 0),
                 left=datetime(2026, 9, 26, 12, 8), name="Atoll",
                 area_id="MapWorldsAtoll", instance="1", level=77),
        ZoneStay(entered=datetime(2026, 9, 26, 20, 0),
                 left=datetime(2026, 9, 27, 15, 0), name="Atoll",
                 area_id="MapWorldsAtoll", instance="2", level=77),
    ])

    zahlen = records["MapWorldsAtoll"].stats(None)
    assert zahlen.visits == 2                 # beide Besuche zaehlen
    assert zahlen.timed_visits == 1           # nur einer hat eine Dauer
    assert zahlen.average_seconds == 480      # 8 min, nicht 9,5 Stunden


# --- Der Baum: eine Kindzeile je Gebietslevel (Peter, 2026-09-27) ------- #

def _bazaar() -> ZoneRecord:
    """Peters echter Fall: dieselbe Zone auf zwei Stufen, weil der
    Gebietslevel vom Karten-Item kommt ("Travel to a Map of this tier or
    lower")."""
    return record_by_level("MapWorldsBazaar", "Bazaar", MAP, {ALLFLAME: {
        71: LevelStats(visits=3, deaths=1, seconds=750, timed_visits=3,
                       last_seen="2026-09-15T22:59:13"),
        72: LevelStats(visits=3, deaths=0, seconds=738, timed_visits=3,
                       last_seen="2026-09-27T11:40:11"),
    }})


def test_a_zone_with_one_level_has_no_children(qapp) -> None:
    """Eine einzelne Kindzeile wiederholte bloss ihre Elternzeile — und
    ein Aufklapp-Pfeil, hinter dem nichts Neues steht, ist eine
    Enttaeuschung."""
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    assert model.rowCount(model.index(0, 0)) == 0


def test_a_zone_with_two_levels_splits_into_two_children(qapp) -> None:
    model = ZoneTreeModel([_bazaar()], league=ALLFLAME)
    eltern = model.index(0, 0)

    assert model.rowCount(eltern) == 2
    assert [model.data(model.index(z, _LEVEL_COL, eltern),
                       Qt.ItemDataRole.DisplayRole) for z in range(2)] == ["71", "72"]


def test_a_child_shows_the_numbers_of_its_own_level(qapp) -> None:
    """Der eigentliche Zweck: Gepoolt sagt "6 Besuche, 1 Tod" nichts
    darueber, auf welcher Stufe gestorben wurde."""
    model = ZoneTreeModel([_bazaar()], league=ALLFLAME)
    eltern = model.index(0, 0)

    def zelle(zeile, spalte):
        return model.data(model.index(zeile, spalte, eltern),
                          Qt.ItemDataRole.DisplayRole)

    assert (zelle(0, _VISITS_COL), zelle(0, _DEATHS_COL)) == ("3", "1")
    assert (zelle(1, _VISITS_COL), zelle(1, _DEATHS_COL)) == ("3", "")
    assert zelle(0, _TIME_COL) == "4:10"        # 750 s / 3
    # Die Elternzeile bleibt die Zusammenfassung.
    assert model.data(model.index(0, _VISITS_COL), Qt.ItemDataRole.DisplayRole) == "6"
    assert model.data(model.index(0, _DEATHS_COL), Qt.ItemDataRole.DisplayRole) == "1"


def test_a_child_carries_its_own_tier_not_the_zones(qapp) -> None:
    model = ZoneTreeModel([_bazaar()], league=ALLFLAME)
    eltern = model.index(0, 0)

    assert model.data(model.index(0, _TIER_COL, eltern),
                      Qt.ItemDataRole.DisplayRole) == "4"       # 71 - 67
    assert model.data(model.index(1, _TIER_COL, eltern),
                      Qt.ItemDataRole.DisplayRole) == "5"       # 72 - 67
    assert model.data(model.index(0, _TIER_COL),
                      Qt.ItemDataRole.DisplayRole) == "4–5"


def test_children_leave_name_group_and_id_empty(qapp) -> None:
    """Sie stuenden wortgleich in der Zeile darueber, und die Einrueckung
    sagt bereits, wozu die Zeile gehoert."""
    model = ZoneTreeModel([_bazaar()], league=ALLFLAME)
    kind = model.index(0, 0, model.index(0, 0))

    for spalte in (0, _NAME_COL, _ID_COL):
        assert model.data(model.index(kind.row(), spalte, model.index(0, 0)),
                          Qt.ItemDataRole.DisplayRole) == ""


def test_a_story_zone_has_no_tier_on_its_children_either(qapp) -> None:
    zonen = [record_by_level("2_9_1", "The Blood Aqueduct", STORY, {ALLFLAME: {
        60: LevelStats(visits=1, last_seen="2026-09-01T10:00:00"),
        61: LevelStats(visits=2, last_seen="2026-09-02T10:00:00"),
    }})]
    model = ZoneTreeModel(zonen, league=ALLFLAME)
    eltern = model.index(0, 0)

    assert model.data(model.index(0, _TIER_COL, eltern),
                      Qt.ItemDataRole.DisplayRole) == ""
    assert model.data(eltern.siblingAtColumn(_TIER_COL),
                      Qt.ItemDataRole.DisplayRole) == ""


def test_switching_the_league_changes_the_children(qapp) -> None:
    """Die Stufen sind eine Eigenschaft der Liga, nicht der Zone: In der
    einen Liga lief Bazaar auf zwei Stufen, in der anderen auf einer."""
    zone = record_by_level("MapWorldsBazaar", "Bazaar", MAP, {
        ALLFLAME: {71: LevelStats(visits=3, last_seen="2026-09-15T22:59:13"),
                   72: LevelStats(visits=3, last_seen="2026-09-27T11:40:11")},
        MIRAGE: {71: LevelStats(visits=1, last_seen="2026-07-01T10:00:00")}})
    model = ZoneTreeModel([zone], league=ALLFLAME)
    assert model.rowCount(model.index(0, 0)) == 2

    model.set_league(MIRAGE)
    assert model.rowCount(model.index(0, 0)) == 0


def test_children_follow_their_zone_through_the_filter(qapp) -> None:
    """Eine Stufe fuer sich zu filtern hiesse, eine Zone zu zeigen, deren
    Zahlen nicht mehr zu ihren Kindern passen."""
    model = ZoneTreeModel(beispiel() + [_bazaar()], league=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)

    proxy.setFilterFixedString("bazaar")
    assert proxy.rowCount() == 1
    assert proxy.rowCount(proxy.index(0, 0)) == 2

    proxy.setFilterFixedString("cells")          # Bazaar faellt samt Kindern weg
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, _NAME_COL),
                      Qt.ItemDataRole.DisplayRole) == "Cells"


def test_children_sort_by_level_under_the_group_column(qapp) -> None:
    """In der Gruppen-Spalte stehen Kinder alle leer — ohne eigene Regel
    waere ihre Reihenfolge dem Zufall ueberlassen."""
    model = ZoneTreeModel([_bazaar()], league=ALLFLAME)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)
    proxy.sort(0, Qt.SortOrder.DescendingOrder)

    eltern = proxy.index(0, 0)
    assert [proxy.data(proxy.index(z, _LEVEL_COL, eltern),
                       Qt.ItemDataRole.DisplayRole)
            for z in range(proxy.rowCount(eltern))] == ["72", "71"]


# --- Excel-artiger Spaltenfilter (Peter, 2026-09-27) ------------------- #

def _proxy_mit(zonen, liga=ALLFLAME):
    model = ZoneTreeModel(zonen, league=liga)
    proxy = ZoneFilterProxy()
    proxy.setSourceModel(model)
    return model, proxy


def test_a_column_filter_narrows_to_matching_rows(qapp) -> None:
    model, proxy = _proxy_mit(beispiel())
    vorher = proxy.rowCount()

    proxy.set_column_filter(_NAME_COL, "atoll")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, _NAME_COL),
                      Qt.ItemDataRole.DisplayRole) == "Atoll"
    proxy.set_column_filter(_NAME_COL, "")
    assert proxy.rowCount() == vorher


def test_comparison_expressions_work_on_numbers(qapp) -> None:
    """Dieselben Mini-Ausdruecke wie in der Item-Liste: ">=20", "<45"."""
    model, proxy = _proxy_mit(beispiel())

    proxy.set_column_filter(_LEVEL_COL, ">=70")
    namen = {proxy.data(proxy.index(z, _NAME_COL), Qt.ItemDataRole.DisplayRole)
             for z in range(proxy.rowCount())}
    assert namen == {"Atoll"}            # 77; Cells 68, Aqueduct 61, Hideout 60

    proxy.set_column_filter(_LEVEL_COL, "<62")
    namen = {proxy.data(proxy.index(z, _NAME_COL), Qt.ItemDataRole.DisplayRole)
             for z in range(proxy.rowCount())}
    assert namen == {"The Blood Aqueduct", "Backstreet Hideout"}


def test_two_column_filters_combine(qapp) -> None:
    model, proxy = _proxy_mit(beispiel())

    proxy.set_column_filter(0, MAP)
    proxy.set_column_filter(_LEVEL_COL, "<70")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, _NAME_COL),
                      Qt.ItemDataRole.DisplayRole) == "Cells"


def test_clearing_the_column_filters_empties_them_all(qapp) -> None:
    model, proxy = _proxy_mit(beispiel())
    proxy.set_column_filter(_NAME_COL, "atoll")
    proxy.set_column_filter(_LEVEL_COL, ">60")
    assert proxy.filtered_columns() == {_NAME_COL, _LEVEL_COL}

    proxy.clear_column_filters()

    assert proxy.filtered_columns() == set()
    assert proxy.rowCount() == 4


def test_children_stay_with_a_parent_that_passes_the_column_filter(qapp) -> None:
    """Der Filter arbeitet auf Gebieten, nicht auf Stufen — sonst zeigte
    die Elternzeile Zahlen, die nicht mehr zu ihren Kindern passen."""
    model, proxy = _proxy_mit(beispiel() + [_bazaar()])

    proxy.set_column_filter(_NAME_COL, "bazaar")

    assert proxy.rowCount() == 1
    assert proxy.rowCount(proxy.index(0, 0)) == 2


def test_the_suggestions_only_list_values_of_the_shown_league(qapp) -> None:
    """Ein Vorschlag, der auf nichts passt, ist schlimmer als keiner."""
    model = ZoneTreeModel(beispiel(), league=ALLFLAME)
    assert model.distinct_values(_NAME_COL) == [
        "Atoll", "Backstreet Hideout", "Cells", "The Blood Aqueduct"]

    model.set_league(MIRAGE)
    assert model.distinct_values(_NAME_COL) == ["Atoll", "The Blood Aqueduct"]
    # Und die Level-Spalte zeigt die Werte DIESER Liga (Atoll 70, nicht 77).
    assert "70" in model.distinct_values(_LEVEL_COL)
    assert "77" not in model.distinct_values(_LEVEL_COL)


def test_typing_into_the_header_field_filters_the_table(qapp) -> None:
    """Peter, 2026-10-01: "wenn man die Filter direkt in eine Zeile
    eintragen könnte" — die Felder sitzen im Spaltenkopf
    (§column_filter.FilterHeader)."""
    from poe_view.ui.zone_table import ZoneTableDialog

    dialog = ZoneTableDialog(beispiel(), league=ALLFLAME)
    try:
        feld = dialog._filter_header.filter_edit(_NAME_COL)
        assert feld.completer() is not None
        assert "Atoll" in feld._suggestions

        feld.setText("atoll")
        assert dialog._proxy.rowCount() == 1
        assert "1 of 4 zones" in dialog._count_label.text()

        dialog._clear_column_filters()
        assert feld.text() == ""
        assert dialog._proxy.rowCount() == 4
    finally:
        dialog.deleteLater()


def test_a_filter_set_from_outside_shows_up_in_its_field(qapp) -> None:
    """Das Feld ist die eine Stelle, die den Filter zeigt — auch wenn er
    nicht dort eingetippt wurde."""
    from poe_view.ui.zone_table import ZoneTableDialog

    dialog = ZoneTableDialog(beispiel(), league=ALLFLAME)
    try:
        dialog.apply_column_filter(_LEVEL_COL, "<70")
        assert dialog._filter_header.filter_text(_LEVEL_COL) == "<70"
        assert dialog._proxy.column_filter(_LEVEL_COL) == "<70"
    finally:
        dialog.deleteLater()


# --- Aktualisieren (Peter, 2026-10-01: "einen aktualisieren Button ...
# oder eine automatische aktualisierung") ----------------------------- #

def _dialog_mit(records, reload=None, league=ALLFLAME):
    from poe_view.ui.zone_table import ZoneTableDialog
    return ZoneTableDialog(records, league=league, reload=reload)


def _mehr_besuche(records, area_id, extra):
    """Dieselben Zonen, bei einer davon ``extra`` Besuche mehr — so sieht
    ein frischer Stand nach einem Zonenwechsel aus."""
    neu = []
    for r in records:
        ligen = {}
        for name, werte in r.leagues.items():
            ligen[name] = LeagueStats(by_level={
                lv: LevelStats(visits=w.visits + (extra if r.area_id == area_id else 0),
                               entries=w.entries, deaths=w.deaths,
                               seconds=w.seconds, timed_visits=w.timed_visits,
                               last_seen=w.last_seen)
                for lv, w in werte.by_level.items()})
        neu.append(ZoneRecord(r.area_id, r.name, r.category, ligen))
    return neu


def test_the_refresh_button_only_exists_with_something_to_reload(qapp) -> None:
    ohne = _dialog_mit(beispiel())
    mit = _dialog_mit(beispiel(), reload=lambda: beispiel())
    try:
        assert ohne._refresh_button.isHidden()
        assert not mit._refresh_button.isHidden()
    finally:
        ohne.deleteLater()
        mit.deleteLater()


def test_refresh_shows_the_new_numbers(qapp) -> None:
    stand = {"records": beispiel()}
    dialog = _dialog_mit(stand["records"], reload=lambda: stand["records"])
    try:
        stand["records"] = _mehr_besuche(beispiel(), "MapWorldsCells", 5)
        dialog._refresh_button.click()
        zeile = next(z for z in range(dialog._proxy.rowCount())
                     if dialog._proxy.index(z, _NAME_COL).data() == "Cells")
        vorher = next(r for r in beispiel() if r.area_id == "MapWorldsCells")
        assert dialog._proxy.index(zeile, _VISITS_COL).data() == str(
            vorher.stats(ALLFLAME).visits + 5)
    finally:
        dialog.deleteLater()


def test_refresh_keeps_filters_league_and_expanded_zones(qapp) -> None:
    """Sonst risse jeder Zonenwechsel die Tabelle an den Anfang zurück —
    die automatische Aktualisierung wäre eine Störung statt einer Hilfe."""
    zonen = beispiel() + [_bazaar()]
    dialog = _dialog_mit(zonen, reload=lambda: _mehr_besuche(zonen, "MapWorldsBazaar", 1))
    try:
        dialog._group_combo.setCurrentIndex(dialog._group_combo.findData(MAP))
        dialog._filter_header.filter_edit(_NAME_COL).setText("baz")
        assert dialog._proxy.rowCount() == 1
        bazaar = dialog._proxy.index(0, 0)
        dialog._view.expand(bazaar)
        dialog._view.setCurrentIndex(bazaar)

        dialog.refresh()

        assert dialog._model.league() == ALLFLAME
        assert dialog._league_combo.currentData() == ALLFLAME
        assert dialog._group_combo.currentData() == MAP
        assert dialog._filter_header.filter_text(_NAME_COL) == "baz"
        assert dialog._proxy.rowCount() == 1
        assert dialog._view.isExpanded(dialog._proxy.index(0, 0))
        assert dialog._view.currentIndex().row() == 0
    finally:
        dialog.deleteLater()


def test_a_reload_that_returns_nothing_leaves_the_table_alone(qapp) -> None:
    """Zonen-Beobachter inzwischen aus: lieber den alten Stand zeigen als
    eine leere Tabelle."""
    dialog = _dialog_mit(beispiel(), reload=lambda: None)
    try:
        dialog.refresh()
        assert dialog._proxy.rowCount() == 4
    finally:
        dialog.deleteLater()


def test_switching_the_league_resorts_and_recounts(qapp) -> None:
    """Regression: Bis 2026-10-01 rief der Liga-Wechsel
    ``horizontalHeader()`` — das gibt es an einem QTreeView nicht. Die
    Zahlen wechselten, Sortierung und Zähler blieben stehen."""
    dialog = _dialog_mit(beispiel())
    try:
        assert "4 zones" in dialog._count_label.text()
        dialog._league_combo.setCurrentIndex(dialog._league_combo.findData(MIRAGE))
        assert dialog._model.league() == MIRAGE
        assert "2 zones" in dialog._count_label.text()
        assert "77" not in dialog._filter_header.filter_edit(_LEVEL_COL)._suggestions
    finally:
        dialog.deleteLater()


def test_the_entries_column_shows_every_entry(qapp) -> None:
    zonen = [record_by_level("MapWorldsPort", "Port", MAP, {ALLFLAME: {
        70: LevelStats(visits=19, entries=72, seconds=19 * 600, timed_visits=19,
                       last_seen="2026-09-30T20:00:00")}})]
    model = ZoneTreeModel(zonen, league=ALLFLAME)
    assert model.data(model.index(0, _VISITS_COL), Qt.ItemDataRole.DisplayRole) == "19"
    assert model.data(model.index(0, _ENTRIES_COL), Qt.ItemDataRole.DisplayRole) == "72"
    assert model.data(model.index(0, _ENTRIES_COL), NUMERIC_SORT_ROLE) == 72
    assert "entries" in model.headerData(_ENTRIES_COL, Qt.Orientation.Horizontal,
                                         Qt.ItemDataRole.ToolTipRole).lower()


# --- Der Filterkopf (§column_filter.FilterHeader) ----------------------- #

def test_the_filter_fields_sit_under_their_columns(qapp) -> None:
    dialog = _dialog_mit(beispiel())
    try:
        dialog.resize(1000, 400)
        dialog.show()
        qapp.processEvents()
        kopf = dialog._filter_header
        assert kopf.height() >= kopf.label_height() + kopf.filter_edit(0).sizeHint().height()
        for spalte in (0, _NAME_COL, _VISITS_COL, _ID_COL):
            feld = kopf.filter_edit(spalte)
            assert feld.isVisible()
            assert feld.y() >= kopf.label_height()
            assert abs(feld.x() - kopf.sectionViewportPosition(spalte)) <= 1
            assert abs(feld.width() - kopf.sectionSize(spalte)) <= 2
    finally:
        dialog.deleteLater()


def test_a_click_in_the_field_row_does_not_sort(qapp) -> None:
    """Der Klick gehört dem Feld, auch im freien Pixel zwischen zwei
    Feldern — sonst sortierte die Tabelle beim Danebenklicken um."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    dialog = _dialog_mit(beispiel())
    try:
        dialog.resize(1000, 400)
        dialog.show()
        qapp.processEvents()
        kopf = dialog._filter_header
        vorher = (kopf.sortIndicatorSection(), kopf.sortIndicatorOrder())
        # Mitten in der Spalte, weit weg vom Rand (dort zöge der Kopf die
        # Spaltenbreite, statt zu sortieren — ein Klick dort bewiese
        # nichts). QTest liefert den Klick an den Kopf selbst, nicht an
        # das Feld darüber: genau der Fall eines Klicks, den kein Feld
        # abfängt.
        mitte = (kopf.sectionViewportPosition(_VISITS_COL)
                 + kopf.sectionSize(_VISITS_COL) // 2)
        QTest.mouseClick(kopf.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(mitte, kopf.label_height() + 3))
        assert (kopf.sortIndicatorSection(), kopf.sortIndicatorOrder()) == vorher
        QTest.mouseClick(kopf.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(mitte, kopf.label_height() // 2))
        assert kopf.sortIndicatorSection() == _VISITS_COL
    finally:
        dialog.deleteLater()


def test_typing_a_filter_does_not_move_the_columns(qapp) -> None:
    """Passten sich die Breiten dem gefilterten Inhalt an, rutschte das
    Feld, in das man gerade tippt, unter dem Cursor weg."""
    dialog = _dialog_mit(beispiel())
    try:
        dialog.resize(1000, 400)
        dialog.show()
        qapp.processEvents()
        kopf = dialog._filter_header
        vorher = [kopf.sectionSize(c) for c in range(kopf.count())]
        kopf.filter_edit(_NAME_COL).setText("cells")
        qapp.processEvents()
        assert dialog._proxy.rowCount() == 1
        assert [kopf.sectionSize(c) for c in range(kopf.count())] == vorher
    finally:
        dialog.deleteLater()
