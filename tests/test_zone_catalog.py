"""Tests für den Zonen-Katalog (``services/zone_catalog.py``).

Die Kennungen in diesen Tests sind echte aus Peters Client.txt — das ist
der Punkt: Die Einteilung wurde an 381 vorkommenden Gebieten ausgezählt,
nicht an erdachten Mustern.
"""

from datetime import datetime, timedelta

import json

import pytest

from poe_view.services import zone_catalog as zk
from poe_view.services.league_log import UNKNOWN
from poe_view.services.zone_watcher import ZoneStay


def stay(area_id: str, name: str = "Zone", level: int = 68,
         minute: int = 0, seed: str = "", minutes: int = 5) -> ZoneStay:
    return ZoneStay(entered=datetime(2026, 9, 26, 12, minute),
                    left=datetime(2026, 9, 26, 12, minute) + timedelta(minutes=minutes),
                    name=name, area_id=area_id, instance="1", level=level,
                    seed=seed)


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


def _eintritt(zeit: str, level: int, area: str, name: str,
              seed: str = "1") -> list[str]:
    return [
        f"2026/09/26 {zeit} 123 abc [DEBUG Client 1] Client-Safe Instance ID = 1",
        f'2026/09/26 {zeit} 123 abc [DEBUG Client 1] Generating level {level} '
        f'area "{area}" with seed {seed}',
        f"2026/09/26 {zeit} 123 abc [INFO Client 1] : You have entered {name}.",
    ]


def test_refresh_reads_the_log_saves_and_survives_a_truncated_log(tmp_path) -> None:
    """Der eigentliche Zweck des Katalogs: PoE kürzt die Client.txt
    irgendwann, der Katalog behält trotzdem, was einmal gesehen wurde."""
    # Jedes Log endet mit einer Rückkehr ins Hideout: Der jeweils letzte
    # Aufenthalt läuft noch und wird erst gezählt, wenn er vorbei ist
    # (§refresh_from_log).
    pfad = _log(tmp_path, [*_eintritt("12:00:00", 68, "MapWorldsCells", "Cells"),
                           *_eintritt("12:10:00", 60, "HideoutSlum", "Hideout"),
                           *_eintritt("12:20:00", 77, "MapWorldsAtoll", "Atoll"),
                           *_eintritt("12:25:00", 60, "HideoutSlum", "Hideout")])

    records = zk.refresh_from_log(pfad, "TestAccount#1234")
    assert set(records) == {"MapWorldsCells", "HideoutSlum", "MapWorldsAtoll"}
    assert zk.catalog_path("TestAccount#1234").exists()

    gekuerzt = _log(tmp_path, [*_eintritt("12:30:00", 81, "MapWorldsPit", "Pit"),
                               *_eintritt("12:40:00", 60, "HideoutSlum", "Hideout")])
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


# --- Zahlen je Gebietslevel (VERSION 4, Peter 2026-09-27) --------------- #

def test_visits_are_counted_under_their_own_level() -> None:
    """Der Befund, der diese Ebene noetig gemacht hat: Peters Karten sind
    nummerierte Items ("Map (Tier 4)") mit dem Text "Travel to a Map of
    this tier or lower" — der Gebietslevel kommt vom Item, nicht von der
    Zone. Bazaar lief dreimal auf 71 und dreimal auf 72."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsBazaar", "Bazaar", 71, m)
                             for m in (0, 10, 20)]
                   + [stay("MapWorldsBazaar", "Bazaar", 72, m)
                      for m in (30, 40)])

    zahlen = records["MapWorldsBazaar"].stats(UNKNOWN)
    assert {lv: w.visits for lv, w in zahlen.by_level.items()} == {71: 3, 72: 2}
    assert zahlen.visits == 5                     # die Summe bleibt richtig
    assert zahlen.levels == {71, 72}


def test_deaths_and_seconds_stay_with_their_level() -> None:
    """Gepoolt waere nicht mehr zu sehen, auf welcher Stufe gestorben
    wurde — genau das war Peters Anlass."""
    records: dict[str, zk.ZoneRecord] = {}
    tod = datetime(2026, 9, 26, 12, 2)
    zk.merge_stays(records, [stay("MapWorldsBazaar", "Bazaar", 71, 0),
                             stay("MapWorldsBazaar", "Bazaar", 72, 30)],
                   deaths=[tod])

    zahlen = records["MapWorldsBazaar"].stats(UNKNOWN)
    assert zahlen.by_level[71].deaths == 1
    assert zahlen.by_level[72].deaths == 0
    assert zahlen.deaths == 1
    assert zahlen.by_level[71].average_seconds == 300      # 5 Minuten


def test_a_stay_without_a_level_is_not_lost() -> None:
    """Die Zeile "Generating level N area" ist ein DEBUG-Eintrag; fehlt
    sie, gibt es trotzdem einen Besuch zu zaehlen. Er landet unter
    ``NO_LEVEL`` und bleibt aus jeder Level-Anzeige heraus."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsBazaar", "Bazaar", 0, 0)])

    zahlen = records["MapWorldsBazaar"].stats(UNKNOWN)
    assert zahlen.by_level[zk.NO_LEVEL].visits == 1
    assert zahlen.visits == 1
    assert zahlen.levels == set()                 # kein erfundener Level


def test_the_per_level_numbers_survive_a_save_and_load(tmp_path) -> None:
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsBazaar", "Bazaar", 71, 0),
                             stay("MapWorldsBazaar", "Bazaar", 72, 30),
                             stay("MapWorldsBazaar", "Bazaar", 72, 40)])
    pfad = tmp_path / "zonen.json"
    zk.save(pfad, records)

    zurueck = zk.load(pfad)
    zahlen = zurueck["MapWorldsBazaar"].stats(UNKNOWN)
    assert {lv: w.visits for lv, w in zahlen.by_level.items()} == {71: 1, 72: 2}
    assert zahlen.by_level[72].last_seen == "2026-09-26T12:40:00"


def test_a_catalogue_of_another_version_is_discarded_even_if_it_parses(
        tmp_path) -> None:
    """VERSION 3 fuehrte nur eine Summe je Liga; wie sie sich auf die
    Stufen verteilt, steht dort nicht. Statt sie zu erfinden, faengt der
    Katalog leer an — ``refresh_from_log`` liest die Client.txt dann von
    vorn und weiss es genau.

    Geprueft wird das mit einem Rumpf, der sich SEHR WOHL lesen liesse.
    Die erste Fassung dieses Tests nahm eine echte v3-Datei, und die ist
    unter v4-Regeln ohnehin unlesbar ( "levels" ist dort eine Liste,
    hier ein Objekt) — sie wurde also auch ohne Versionspruefung
    verworfen, und der Test bestand aus dem falschen Grund. Aufgefallen
    ist das erst in der Gegenprobe."""
    gueltiger_rumpf = ('"zones": [{"area_id": "MapWorldsBazaar", "name": '
                       '"Bazaar", "category": "Map", "leagues": {"X": '
                       '{"levels": {"71": {"visits": 6}}}}}]')
    passend = tmp_path / "passend.json"
    passend.write_text('{"version": %d, %s}' % (zk.VERSION, gueltiger_rumpf),
                       encoding="utf-8")
    assert zk.load(passend)["MapWorldsBazaar"].stats("X").visits == 6

    fremd = tmp_path / "fremd.json"
    fremd.write_text('{"version": 3, %s}' % gueltiger_rumpf, encoding="utf-8")
    assert zk.load(fremd) == {}


def test_the_tier_column_spans_what_actually_occurred() -> None:
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsBazaar", "Bazaar", 71, 0),
                             stay("MapWorldsBazaar", "Bazaar", 72, 30)])
    eintrag = records["MapWorldsBazaar"]

    assert eintrag.tier_text(UNKNOWN) == "4–5"
    assert eintrag.tier(UNKNOWN) == 4              # Sortierung: die niedrigste
    zk.merge_stays(records, [stay("1_5_3b", "The Ruined Square", 44, 0)])
    assert records["1_5_3b"].tier_text(UNKNOWN) == ""      # Story hat keine


# --- Karten statt Eintritte (VERSION 5, Peter 2026-10-01) --------------- #
# "wird hier jeder Besuch gezählt (auch Händlerbesuche) oder die gesamte
# Map?" — an seinem Log 1.130 Eintritte für 359 Karten.

def test_returning_to_the_same_map_is_one_visit_but_several_entries() -> None:
    """Map, Händler, zurück, Händler, zurück: eine Karte, drei Eintritte.
    Die Zeit addiert sich, der Schnitt gilt je Karte."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsPort", "Port", 70, m, seed="711400918")
                             for m in (0, 10, 20)])
    zahlen = records["MapWorldsPort"].stats(None)
    assert zahlen.visits == 1
    assert zahlen.entries == 3
    assert zahlen.seconds == 15 * 60
    assert zahlen.average_seconds == 15 * 60


def test_a_new_seed_is_a_new_map() -> None:
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsPort", "Port", 70, 0, seed="111"),
                             stay("MapWorldsPort", "Port", 70, 10, seed="111"),
                             stay("MapWorldsPort", "Port", 70, 20, seed="222")])
    zahlen = records["MapWorldsPort"].stats(None)
    assert (zahlen.visits, zahlen.entries) == (2, 3)
    assert zahlen.average_seconds == 15 * 60 / 2


@pytest.mark.parametrize("seed", ["1", ""])
def test_fixed_or_missing_seeds_count_every_entry(seed) -> None:
    """Hideout und Städte stehen immer auf Seed 1 — jede Rückkehr ist
    ein eigener Aufenthalt. Ohne Seed bleibt es beim alten Zählen."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("HideoutSlum", "Hideout", 60, m, seed=seed)
                             for m in (0, 10, 20)])
    zahlen = records["HideoutSlum"].stats(None)
    assert (zahlen.visits, zahlen.entries) == (3, 3)


def test_a_map_counts_as_timed_once_even_if_only_a_later_entry_was_measurable() -> None:
    """Der erste Eintritt ist zu lang (Feierabend in der offenen Instanz,
    §_MAX_DWELL_S), der zweite gemessen: eine Karte mit Dauer, nicht
    null und nicht zwei."""
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsPort", "Port", 70, 0, seed="9", minutes=120),
                             stay("MapWorldsPort", "Port", 70, 10, seed="9", minutes=4),
                             stay("MapWorldsPort", "Port", 70, 20, seed="9", minutes=6)])
    zahlen = records["MapWorldsPort"].stats(None)
    assert zahlen.timed_visits == 1
    assert zahlen.average_seconds == 10 * 60


def test_entries_are_summed_across_leagues() -> None:
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsPort", "Port", 70, 0, seed="5"),
                             stay("MapWorldsPort", "Port", 70, 10, seed="5")],
                   league_of=lambda zeit: "A")
    zk.merge_stays(records, [stay("MapWorldsPort", "Port", 70, 30, seed="6")],
                   league_of=lambda zeit: "B")
    gesamt = records["MapWorldsPort"].stats(None)
    assert (gesamt.visits, gesamt.entries) == (2, 3)


def test_a_map_spanning_two_refreshes_is_counted_once(tmp_path) -> None:
    """Der Katalog arbeitet die Client.txt in Stücken ein. Läuft dieselbe
    Karte über die Grenze, muss er sich ihren Seed gemerkt haben —
    sonst zählte jedes Öffnen der Tabelle mitten im Lauf eine Karte
    mehr."""
    zeilen = [*_eintritt("12:00:00", 70, "MapWorldsPort", "Port", "4242"),
              *_eintritt("12:05:00", 60, "HideoutSlum", "Hideout")]
    pfad = _log(tmp_path, zeilen)
    zk.refresh_from_log(pfad, "TestAccount#1234")
    zeilen += [*_eintritt("12:07:00", 70, "MapWorldsPort", "Port", "4242"),
               *_eintritt("12:12:00", 60, "HideoutSlum", "Hideout")]
    pfad = _log(tmp_path, zeilen)
    records = zk.refresh_from_log(pfad, "TestAccount#1234")
    zahlen = records["MapWorldsPort"].stats(None)
    assert (zahlen.visits, zahlen.entries) == (1, 2)
    assert zahlen.average_seconds == 10 * 60


def test_the_running_stay_is_counted_only_once_it_ended_with_its_time(tmp_path) -> None:
    """Der Fehler, der dabei auffiel: Wer die Tabelle mitten in einer
    Map öffnete, bekam sie mit 0 Sekunden eingetragen — und weil sie
    danach vor der Grenze lag, nie korrigiert."""
    zeilen = [*_eintritt("12:00:00", 60, "HideoutSlum", "Hideout"),
              *_eintritt("12:01:00", 70, "MapWorldsPort", "Port", "77")]
    pfad = _log(tmp_path, zeilen)
    mitten = zk.refresh_from_log(pfad, "TestAccount#1234")
    assert "MapWorldsPort" not in mitten
    zeilen += _eintritt("12:09:00", 60, "HideoutSlum", "Hideout")
    pfad = _log(tmp_path, zeilen)
    danach = zk.refresh_from_log(pfad, "TestAccount#1234")
    zahlen = danach["MapWorldsPort"].stats(None)
    assert zahlen.visits == 1
    assert zahlen.seconds == 8 * 60


def test_seed_memory_survives_save_and_load(tmp_path) -> None:
    records: dict[str, zk.ZoneRecord] = {}
    zk.merge_stays(records, [stay("MapWorldsPort", "Port", 70, 0, seed="31"),
                             stay("MapWorldsPort", "Port", 70, 10, seed="31")])
    pfad = tmp_path / "katalog.json"
    zk.save(pfad, records)
    geladen = zk.load(pfad)
    stufe = geladen["MapWorldsPort"].leagues[UNKNOWN].by_level[70]
    assert (stufe.visits, stufe.entries) == (1, 2)
    assert stufe.last_seed == "31" and stufe.last_seed_timed
    zk.merge_stays(geladen, [stay("MapWorldsPort", "Port", 70, 20, seed="31")])
    assert geladen["MapWorldsPort"].stats(None).visits == 1


def test_a_version_4_catalog_is_rebuilt_instead_of_reinterpreted(tmp_path) -> None:
    """Version-4-Zahlen zählen Eintritte als Besuche; als Karten gelesen
    wären sie dreimal zu hoch. Verworfen und neu aufgebaut."""
    pfad = tmp_path / "alt.json"
    pfad.write_text(json.dumps({"version": 4, "zones": [
        {"area_id": "MapWorldsPort", "name": "Port", "category": "Map",
         "leagues": {"A": {"levels": {"70": {"visits": 72}}}}}]}),
        encoding="utf-8")
    assert zk.load(pfad) == {}



# --- Monster je Karte aus /kills (§attribute_kills) --------------------- #
# Peter, 2026-10-03: "Wir können jetzt für die Zones auch eine
# Monsters-Spalte einführen."

from poe_view.services.zone_watcher import KillReading  # noqa: E402


def _zeit(minute: int, sekunde: int = 0) -> datetime:
    return datetime(2026, 9, 26, 12, minute, sekunde)


def _ablesung(minute: int, total: int, sekunde: int = 0, session: int = 1) -> KillReading:
    return KillReading(_zeit(minute, sekunde), total, session)


def _karte(area_id: str, von: int, bis: int, seed: str, level: int = 77,
           von_s: int = 0, bis_s: int = 0) -> ZoneStay:
    return ZoneStay(entered=_zeit(von, von_s), left=_zeit(bis, bis_s), name=area_id,
                    area_id=area_id, instance="1", level=level, seed=seed)


def _hideout(von: int, bis: int, von_s: int = 0, bis_s: int = 0) -> ZoneStay:
    return ZoneStay(entered=_zeit(von, von_s), left=_zeit(bis, bis_s), name="Hideout",
                    area_id="HideoutSlum", instance="1", level=60, seed="1")


def _katalog(stays) -> dict:
    records: dict = {}
    zk.merge_stays(records, stays)
    return records


def test_two_readings_in_the_same_map_count_for_that_map() -> None:
    """Peters 01:04 und 01:19 in der Haunted Mansion — beide Ablesungen in
    derselben Karte. Die erste Fassung (über die eigene Mitschrift)
    ordnete das keiner Zone zu."""
    stays = [_karte("MapWorldsAtoll", 0, 20, "222")]
    records = _katalog(stays)
    zk.attribute_kills(records, stays, [_ablesung(1, 1000), _ablesung(16, 1600)])
    stufe = records["MapWorldsAtoll"].stats(UNKNOWN).by_level[77]
    assert stufe.kills == 600
    assert stufe.kill_seconds == 15 * 60
    assert stufe.kills_per_minute == 40


def test_the_reminder_routine_counts_the_previous_map_and_drops_the_first_seconds() -> None:
    """Ablesung ein paar Sekunden nach dem Betreten jeder neuen Karte: Der
    Abschnitt enthält die ganze vorige Karte samt Hideout-Gängen und zehn
    Sekunden der neuen — die fallen weg, statt ihn zu verwerfen."""
    stays = [_karte("MapWorldsAtoll", 0, 6, "222"), _hideout(6, 7),
             _karte("MapWorldsAtoll", 7, 10, "222"), _hideout(10, 11),
             _karte("MapWorldsCells", 11, 20, "333", level=68)]
    records = _katalog(stays)
    zk.attribute_kills(records, stays, [_ablesung(0, 1000, sekunde=10),
                                        _ablesung(11, 1700, sekunde=10)])
    atoll = records["MapWorldsAtoll"].stats(UNKNOWN).by_level[77]
    assert atoll.kills == 700
    assert atoll.kill_seconds == 9 * 60 - 10      # 6 + 3 Minuten, ab der Ablesung
    assert records["MapWorldsCells"].stats(UNKNOWN).by_level[68].kills == 0


def test_two_maps_between_readings_cannot_be_split_and_count_for_neither() -> None:
    stays = [_karte("MapWorldsAtoll", 0, 6, "222"), _hideout(6, 7),
             _karte("MapWorldsCells", 7, 12, "333", level=68)]
    records = _katalog(stays)
    zk.attribute_kills(records, stays, [_ablesung(0, 0), _ablesung(13, 900)])
    assert records["MapWorldsAtoll"].stats(UNKNOWN).kills == 0
    assert records["MapWorldsCells"].stats(UNKNOWN).kills == 0


def test_the_same_map_twice_with_another_seed_is_two_maps() -> None:
    stays = [_karte("MapWorldsAtoll", 0, 6, "222"), _hideout(6, 7),
             _karte("MapWorldsAtoll", 7, 12, "999")]
    records = _katalog(stays)
    zk.attribute_kills(records, stays, [_ablesung(0, 0), _ablesung(13, 900)])
    assert records["MapWorldsAtoll"].stats(UNKNOWN).kills == 0


def test_readings_across_a_login_are_never_compared() -> None:
    """Dazwischen kann ein anderer Charakter spielen — sein Zähler hat mit
    dem vorigen nichts zu tun."""
    stays = [_karte("MapWorldsAtoll", 0, 20, "222")]
    records = _katalog(stays)
    zk.attribute_kills(records, stays, [_ablesung(1, 1000, session=1),
                                        _ablesung(16, 1600, session=2)])
    assert records["MapWorldsAtoll"].stats(UNKNOWN).kills == 0


def test_a_falling_counter_is_skipped() -> None:
    stays = [_karte("MapWorldsAtoll", 0, 20, "222")]
    records = _katalog(stays)
    zk.attribute_kills(records, stays, [_ablesung(1, 5000), _ablesung(16, 1600)])
    assert records["MapWorldsAtoll"].stats(UNKNOWN).kill_seconds == 0


def test_a_break_in_the_map_keeps_the_pace_out() -> None:
    """Underground Sea in Peters Log: 11 Kills/min über 2,8 Stunden — eine
    Pause, kein Spiel. Dieselbe Grenze wie für die Durchschnittszeit."""
    stays = [ZoneStay(entered=datetime(2026, 9, 26, 10, 0), left=datetime(2026, 9, 26, 12, 0),
                      name="Sea", area_id="MapWorldsUndergroundSea", instance="1",
                      level=73, seed="5")]
    records = _katalog(stays)
    zk.attribute_kills(records, stays, [
        KillReading(datetime(2026, 9, 26, 10, 1), 0, 1),
        KillReading(datetime(2026, 9, 26, 11, 59), 1800, 1)])
    assert records["MapWorldsUndergroundSea"].stats(UNKNOWN).kills == 0


def test_already_counted_readings_are_not_counted_again() -> None:
    stays = [_karte("MapWorldsAtoll", 0, 20, "222")]
    records = _katalog(stays)
    ablesungen = [_ablesung(1, 1000), _ablesung(16, 1600)]
    bis = zk.attribute_kills(records, stays, ablesungen)
    assert bis == "2026-09-26T12:16:00"
    zk.attribute_kills(records, stays, ablesungen, since=bis)
    assert records["MapWorldsAtoll"].stats(UNKNOWN).kills == 600


def test_monsters_per_visit_is_the_pace_times_the_average_time() -> None:
    stufe = zk.LevelStats(seconds=1200, timed_visits=2, kills=300, kill_seconds=300)
    assert stufe.kills_per_minute == 60
    assert stufe.monsters_per_visit == 600


def test_kills_survive_saving_and_loading(tmp_path) -> None:
    stays = [_karte("MapWorldsAtoll", 0, 20, "222")]
    records = _katalog(stays)
    zk.attribute_kills(records, stays, [_ablesung(1, 1000), _ablesung(16, 1600)])
    pfad = tmp_path / "katalog.json"
    zk.save(pfad, records, "2026-09-26T12:16:00")
    wieder = zk.load(pfad)
    stufe = wieder["MapWorldsAtoll"].stats(UNKNOWN).by_level[77]
    assert (stufe.kills, stufe.kill_seconds) == (600, 900)
    assert zk._load_kills_until(pfad) == "2026-09-26T12:16:00"


def _kills_zeile(zeit: str, total: str) -> str:
    return f"2026/09/26 {zeit} 123 abc [INFO Client 1] : You have killed {total} monsters."


def test_refresh_counts_kills_once_even_when_called_again(tmp_path) -> None:
    pfad = _log(tmp_path, [*_eintritt("12:00:00", 77, "MapWorldsAtoll", "Atoll", seed="222"),
                           _kills_zeile("12:00:20", "1.000"),
                           _kills_zeile("12:09:20", "1.540"),
                           *_eintritt("12:10:00", 60, "HideoutSlum", "Hideout")])
    zk.refresh_from_log(pfad, "TestAccount#1234")
    records = zk.refresh_from_log(pfad, "TestAccount#1234")
    stufe = records["MapWorldsAtoll"].stats(UNKNOWN).by_level[77]
    assert stufe.kills == 540
    assert stufe.kill_seconds == 9 * 60


def test_kills_add_up_over_all_leagues() -> None:
    eintrag = zk.ZoneRecord("MapWorldsAtoll", "Atoll", zk.MAP, leagues={
        "Mirage": zk.LeagueStats(by_level={70: zk.LevelStats(kills=100, kill_seconds=60)}),
        "Allflame": zk.LeagueStats(by_level={70: zk.LevelStats(kills=200, kill_seconds=120)})})
    gesamt = eintrag.stats(None)
    assert (gesamt.kills, gesamt.kill_seconds) == (300, 180)
