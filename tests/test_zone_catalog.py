"""Tests für den Zonen-Katalog (``services/zone_catalog.py``).

Die Kennungen in diesen Tests sind echte aus Peters Client.txt — das ist
der Punkt: Die Einteilung wurde an 381 vorkommenden Gebieten ausgezählt,
nicht an erdachten Mustern.
"""

from datetime import datetime

import pytest

from poe_view.services import zone_catalog as zk
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
    ("MapSideArea4_2", zk.MAP),
    ("Delve_Main", zk.SPECIAL),
    ("3_Labyrinth_boss_2", zk.SPECIAL),
    ("EndGame_Labyrinth_trials_spikes", zk.SPECIAL),
    ("SanctumCellar", zk.SPECIAL),
    ("AbyssLeagueBoss2", zk.SPECIAL),
    ("HideoutSlum", zk.REST),
    ("2_8_town", zk.REST),
    ("HeistHub", zk.REST),
    ("KalguuranSettlersLeague", zk.REST),
])
def test_categories_match_the_area_ids_seen_in_the_real_log(area_id, gruppe) -> None:
    assert zk.categorise(area_id) == gruppe


def test_the_labyrinth_is_special_although_its_id_starts_like_a_story_area() -> None:
    """``1_Labyrinth_OH_branch`` sieht aus wie Akt 1, ist aber
    Endspiel-Inhalt. Die Ausnahme steht in ``_STORY_RE`` und ist der
    einzige Grund, warum die Regel nicht einfach "Zahl am Anfang" heißt."""
    assert zk.categorise("1_Labyrinth_OH_branch") == zk.SPECIAL
    assert zk.categorise("1_4_3_3") == zk.STORY


def test_an_unknown_id_becomes_special_rather_than_disappearing() -> None:
    """Eine neue Liga bringt neue Kennungen. Sie sollen in der Tabelle
    auftauchen, nicht stillschweigend fehlen."""
    assert zk.categorise("SomeNewLeagueMechanic2027") == zk.SPECIAL
    assert zk.categorise("") == zk.SPECIAL


def test_a_zone_collects_every_level_it_was_ever_seen_with() -> None:
    """Bei Karten hängt der Level an der eingelegten Karte, bei Delve an
    der Tiefe — eine einzelne Zahl wäre dort falsch. Peters
    ``MapWorldsAtoll`` stand auf 70 und auf 77."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsAtoll", "Atoll", 70),
                             stay("MapWorldsAtoll", "Atoll", 77, minute=10)])

    eintrag = records["MapWorldsAtoll"]
    assert eintrag.levels == {70, 77}
    assert eintrag.level_text == "70–77"
    assert eintrag.max_level == 77
    assert eintrag.visits == 2


def test_a_single_level_is_shown_without_a_range() -> None:
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsCells", "Cells", 68)])
    assert records["MapWorldsCells"].level_text == "68"


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
    assert zurueck["MapWorldsAtoll"].levels == {70, 77}
    assert zurueck["MapWorldsAtoll"].visits == 2
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

    assert zuerst["MapWorldsCells"].visits == 2
    assert nochmal["MapWorldsCells"].visits == 2
