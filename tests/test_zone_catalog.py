"""Tests für den Zonen-Katalog (``services/zone_catalog.py``).

Die Kennungen in diesen Tests sind echte aus Peters Client.txt — das ist
der Punkt: Die Einteilung wurde an 381 vorkommenden Gebieten ausgezählt,
nicht an erdachten Mustern.
"""

from datetime import datetime

import pytest

from poe_view.services import zone_catalog as zk
from poe_view.services.league_log import UNKNOWN
from poe_view.services.zone_watcher import ZoneStay


def stay(area_id: str, name: str = "Zone", level: int = 68,
         minute: int = 0) -> ZoneStay:
    return ZoneStay(entered=datetime(2026, 9, 26, 12, minute),
                    left=datetime(2026, 9, 26, 12, minute + 5),
                    name=name, area_id=area_id, instance="1", level=level)


@pytest.mark.parametrize("area_id,gruppe", [
    ("1_2_5", zk.STORY),
    ("1_SideArea5_3_2", zk.STORY),
    ("2_7_2b", zk.STORY),
    ("MapWorldsChateau", zk.MAP),
    ("Delve_Main", zk.DELVE),
    ("MapSideArea4_2", zk.SIDE_AREA),
    ("MapSideAreaIceForest", zk.SIDE_AREA),
    ("3_Labyrinth_boss_2", zk.LABYRINTH),
    ("EndGame_Labyrinth_trials_spikes", zk.LABYRINTH),
    ("SanctumCellar", zk.SPECIAL),
    ("AbyssLeagueBoss2", zk.SPECIAL),
    ("HideoutSlum", zk.REST),
    ("2_8_town", zk.REST),
    ("HeistHub", zk.REST),
    ("KalguuranSettlersLeague", zk.REST),
])
def test_categories_match_the_area_ids_seen_in_the_real_log(area_id, gruppe) -> None:
    assert zk.categorise(area_id) == gruppe


def test_the_labyrinth_wins_over_the_story_pattern() -> None:
    """``1_Labyrinth_OH_branch`` sieht aus wie Akt 1, ist aber
    Endspiel-Inhalt — mit 82 Kennungen die drittgrößte Gruppe in Peters
    Log. Die Reihenfolge der Prüfungen in ``categorise`` ist die
    Aussage."""
    assert zk.categorise("1_Labyrinth_OH_branch") == zk.LABYRINTH
    assert zk.categorise("1_4_3_3") == zk.STORY


def test_a_side_area_is_not_a_map() -> None:
    """Peter, 2026-09-26: "MapSideArea sind keine eigenen Maps, das sind
    meistens Vaal-Side-Areas." Unter ``Map`` verfälschten sie die
    Karten-Liste mit neun Einträgen, die keine Karte sind."""
    assert zk.categorise("MapSideAreaIceValley") == zk.SIDE_AREA
    assert zk.categorise("MapWorldsAtoll") == zk.MAP


def test_the_map_tier_comes_from_the_lowest_level_seen() -> None:
    """Peter: "Hier zählt natürlich nur die niedrigmöglichste Tier der
    Map." Tier 1 ist Level 68, Tier 16 ist 83."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsAtoll", "Atoll", 77),
                             stay("MapWorldsAtoll", "Atoll", 70, minute=10)])
    assert records["MapWorldsAtoll"].tier() == 3           # 70 - 67

    zk.merge_stays(records, [stay("2_9_1", "The Blood Aqueduct", 61)])
    assert records["2_9_1"].tier() is None                 # keine Karte

    # Der Fall, der die Gegenprobe zunaechst durchgelassen hat: ein
    # Gebiet, dessen Level MITTEN im Tier-Bereich liegt, das aber keine
    # Karte ist. Peters Labyrinth steht auf 68 — ohne die
    # Kategorie-Pruefung stuende dort "T1".
    zk.merge_stays(records, [stay("3_Labyrinth_boss_2", "Aspirant's Trial", 68)])
    assert records["3_Labyrinth_boss_2"].category == zk.LABYRINTH
    assert records["3_Labyrinth_boss_2"].tier() is None
    assert zk.map_tier_from_level(68) == 1                 # der Level allein schon


def test_levels_outside_the_tier_range_have_no_tier() -> None:
    """Story-Gebiete, Delve-Tiefen und Hideouts tragen einen Level, aber
    keine Tier — eine ausgerechnete wäre erfunden."""
    assert zk.map_tier_from_level(68) == 1
    assert zk.map_tier_from_level(83) == 16
    assert zk.map_tier_from_level(84) == 17
    assert zk.map_tier_from_level(85) is None
    assert zk.map_tier_from_level(60) is None
    assert zk.map_tier_from_level(0) is None


def test_an_unknown_id_becomes_special_rather_than_disappearing() -> None:
    """Eine neue Liga bringt neue Kennungen. Sie sollen in der Tabelle
    auftauchen, nicht stillschweigend fehlen."""
    assert zk.categorise("SomeNewLeagueMechanic2027") == zk.SPECIAL
    assert zk.categorise("") == zk.SPECIAL


def test_a_zone_collects_every_level_it_was_ever_seen_with() -> None:
    """Innerhalb EINER Season sammelt ein Gebiet trotzdem mehrere Level:
    ``Delve_Main`` wandert mit der Tiefe. Ohne Season-Historie landet
    alles unter ``UNKNOWN``."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("Delve_Main", "Azurite Mine", 70),
                             stay("Delve_Main", "Azurite Mine", 77, minute=10)])

    eintrag = records["Delve_Main"]
    assert eintrag.stats(UNKNOWN).levels == {70, 77}
    assert eintrag.level_text() == "70–77"
    assert eintrag.max_level() == 77
    assert eintrag.stats(None).visits == 2


def test_the_same_zone_in_two_leagues_stays_apart() -> None:
    """Der Grund fuer die Liga-Trennung (Peter, 2026-09-26): Der Atlas
    baut sich mit jeder Season um, Atoll stand vorher auf 70 und in
    Allflame auf 77. Zusammengeworfen ergaebe das die Spanne "70–77",
    die es nie gab. Und Peters zweiter Punkt liegt darunter: Die Ligen
    EINER Season unterscheiden sich im Inhalt."""
    def liga_von(zeit):
        return "SSF Ruthless (earlier)" if zeit < datetime(2026, 7, 24)             else "SSF R Allflame"

    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [
        ZoneStay(entered=datetime(2026, 7, 1, 12, 0),
                 left=datetime(2026, 7, 1, 12, 5), name="Atoll",
                 area_id="MapWorldsAtoll", instance="1", level=70),
        ZoneStay(entered=datetime(2026, 9, 1, 12, 0),
                 left=datetime(2026, 9, 1, 12, 5), name="Atoll",
                 area_id="MapWorldsAtoll", instance="2", level=77),
    ], liga_von)

    eintrag = records["MapWorldsAtoll"]
    assert eintrag.level_text("SSF Ruthless (earlier)") == "70"
    assert eintrag.level_text("SSF R Allflame") == "77"
    assert eintrag.level_text(None) == "70–77"
    assert eintrag.tier("SSF R Allflame") == 10          # 77 - 67
    assert eintrag.seen_in("SSF R Allflame")
    assert not eintrag.seen_in("Allflame")


def test_a_stay_without_a_league_lands_in_unknown() -> None:
    """Ohne zuordenbaren Charakter wissen wir die Liga nicht.
    ``UNKNOWN`` ist ehrlicher als ein geratener Name — und als Auswahl
    in der Tabelle sichtbar."""
    records: dict[str, zk.ZoneRecord] = {}

    zk.merge_stays(records, [
        ZoneStay(entered=datetime(2026, 5, 1, 12, 0),
                 left=datetime(2026, 5, 1, 12, 5), name="Atoll",
                 area_id="MapWorldsAtoll", instance="1", level=70)],
        lambda zeit: "")

    assert set(records["MapWorldsAtoll"].leagues) == {UNKNOWN}


def test_deaths_and_dwell_time_land_in_the_right_zone() -> None:
    """Peter, 2026-09-26: "Wir koennten hier auch die Tode in eine Spalte
    nehmen und auch die durchschnittliche Dauer der Zone." Die Tode
    stehen mit Zeitstempel in derselben Client.txt; zugeordnet wird, in
    welchen Aufenthalt sie fallen."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [
        ZoneStay(entered=datetime(2026, 9, 26, 12, 0),
                 left=datetime(2026, 9, 26, 12, 10), name="Atoll",
                 area_id="MapWorldsAtoll", instance="1", level=77),
        ZoneStay(entered=datetime(2026, 9, 26, 12, 10),
                 left=datetime(2026, 9, 26, 12, 12), name="Hideout",
                 area_id="HideoutSlum", instance="2", level=60),
        ZoneStay(entered=datetime(2026, 9, 26, 12, 12),
                 left=datetime(2026, 9, 26, 12, 32), name="Atoll",
                 area_id="MapWorldsAtoll", instance="3", level=77),
    ], None, [datetime(2026, 9, 26, 12, 5),      # im ersten Atoll
              datetime(2026, 9, 26, 12, 20),     # im zweiten Atoll
              datetime(2026, 9, 26, 12, 25)])    # auch dort

    atoll = records["MapWorldsAtoll"].stats(None)
    assert atoll.deaths == 3
    assert atoll.visits == 2
    assert atoll.seconds == 600 + 1200
    assert atoll.average_seconds == 900          # 15 min im Schnitt
    assert records["HideoutSlum"].stats(None).deaths == 0


def test_a_running_stay_gets_no_deaths_and_no_time() -> None:
    """Der letzte Aufenthalt der Datei laeuft noch: Er ist nach oben
    offen, ein Tod danach gehoerte zur naechsten Zone, und eine Dauer
    von 0 s duerfte den Schnitt nicht druecken."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [
        ZoneStay(entered=datetime(2026, 9, 26, 12, 0), left=None, name="Atoll",
                 area_id="MapWorldsAtoll", instance="1", level=77)],
        None, [datetime(2026, 9, 26, 12, 5)])

    zahlen = records["MapWorldsAtoll"].stats(None)
    assert zahlen.deaths == 0
    assert zahlen.seconds == 0
    assert zahlen.average_seconds == 0


def test_a_single_level_is_shown_without_a_range() -> None:
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsCells", "Cells", 68)])
    assert records["MapWorldsCells"].level_text() == "68"


def test_a_stay_without_an_area_id_is_skipped() -> None:
    """Ohne Kennung (Log ohne DEBUG-Zeilen) ließe sich weder die Gruppe
    bestimmen noch die Zone beim nächsten Mal wiedererkennen."""
    records: dict[str, zk.ZoneRecord] = {}
    assert zk.merge_stays(records, [stay("", "Somewhere")]) == 0
    assert records == {}


def test_the_newest_display_name_wins() -> None:
    """Hideouts lassen sich umbenennen, die Sprache lässt sich
    umstellen. Die Kennung bleibt, der Name folgt."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("HideoutSlum", "Backstreet Hideout", 60),
                             stay("HideoutSlum", "Mein Versteck", 60, minute=10)])
    assert records["HideoutSlum"].name == "Mein Versteck"


def test_a_saved_catalog_comes_back_unchanged(tmp_path) -> None:
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsAtoll", "Atoll", 70),
                             stay("MapWorldsAtoll", "Atoll", 77, minute=10),
                             stay("2_8_town", "The Sarn Encampment", 60)])
    pfad = tmp_path / "zones.json"
    zk.save(pfad, records)

    zurueck = zk.load(pfad)
    assert set(zurueck) == {"MapWorldsAtoll", "2_8_town"}
    assert zurueck["MapWorldsAtoll"].stats(UNKNOWN).levels == {70, 77}
    assert zurueck["MapWorldsAtoll"].stats(None).visits == 2
    assert zurueck["2_8_town"].category == zk.REST


def test_a_broken_file_yields_an_empty_catalog_instead_of_an_exception(tmp_path) -> None:
    """Der Katalog lässt sich aus der Client.txt jederzeit neu aufbauen —
    ein Programm, das deswegen nicht mehr startet, wäre der größere
    Verlust."""
    pfad = tmp_path / "zones.json"
    pfad.write_text("{kein json", encoding="utf-8")
    assert zk.load(pfad) == {}
    pfad.write_text('{"version": 99, "zones": []}', encoding="utf-8")
    assert zk.load(pfad) == {}


def test_the_catalog_path_follows_the_patched_app_data_dir(tmp_path) -> None:
    """Sonst schriebe ein Testlauf in Peters echten
    ``%LOCALAPPDATA%\\PoE-VIEW2`` (CLAUDE.md, "Tests")."""
    from poe_view import config
    assert zk.catalog_path("Gandol#4338").parent == config.APP_DATA_DIR
    assert zk.catalog_path("Gandol#4338").name == "zone-catalog-Gandol#4338.json"
    assert zk.catalog_path("a/b\\c").name == "zone-catalog-a_b_c.json"


def _log(tmp_path, zeilen: list[str]):
    pfad = tmp_path / "Client.txt"
    pfad.write_text("\n".join(zeilen), encoding="utf-8")
    return pfad


def _eintritt(zeit: str, level: int, area: str, name: str) -> list[str]:
    return [
        f"2026/09/26 {zeit} 123 abc [DEBUG Client 1] Client-Safe Instance ID = 1",
        f'2026/09/26 {zeit} 123 abc [DEBUG Client 1] Generating level {level} '
        f'area "{area}" with seed 1',
        f"2026/09/26 {zeit} 123 abc [INFO Client 1] : You have entered {name}.",
    ]


def test_refresh_reads_the_log_saves_and_survives_a_truncated_log(tmp_path) -> None:
    """Der eigentliche Zweck des Katalogs: PoE kürzt die Client.txt
    irgendwann, der Katalog behält trotzdem, was einmal gesehen wurde."""
    pfad = _log(tmp_path, [*_eintritt("12:00:00", 68, "MapWorldsCells", "Cells"),
                           *_eintritt("12:10:00", 60, "HideoutSlum", "Hideout"),
                           *_eintritt("12:20:00", 77, "MapWorldsAtoll", "Atoll")])

    records = zk.refresh_from_log(pfad, "TestAccount#1234")
    assert set(records) == {"MapWorldsCells", "HideoutSlum", "MapWorldsAtoll"}
    assert zk.catalog_path("TestAccount#1234").exists()

    gekuerzt = _log(tmp_path, _eintritt("12:30:00", 81, "MapWorldsPit", "Pit"))
    danach = zk.refresh_from_log(gekuerzt, "TestAccount#1234")
    assert set(danach) == {"MapWorldsCells", "HideoutSlum", "MapWorldsAtoll",
                           "MapWorldsPit"}


def test_a_second_run_over_the_same_log_does_not_count_visits_twice(tmp_path) -> None:
    """Der Katalog wird bei jedem Öffnen der Tabelle aufgefrischt. Ohne
    Grenze stünde nach dem dritten Blick die dreifache Besuchszahl da."""
    pfad = _log(tmp_path, [*_eintritt("12:00:00", 68, "MapWorldsCells", "Cells"),
                           *_eintritt("12:10:00", 68, "MapWorldsCells", "Cells"),
                           *_eintritt("12:20:00", 60, "HideoutSlum", "Hideout")])

    zuerst = zk.refresh_from_log(pfad, "TestAccount#1234")
    nochmal = zk.refresh_from_log(pfad, "TestAccount#1234")

    assert zuerst["MapWorldsCells"].stats(None).visits == 2
    assert nochmal["MapWorldsCells"].stats(None).visits == 2
