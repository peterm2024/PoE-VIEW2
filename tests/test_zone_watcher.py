"""Tests für die Zonenwechsel-Beobachtung (Peter, 2026-08-01: "Erst nach
Zonenwechsel gibt es einen Refresh"). ``ZoneWatcher.check_now()`` wird
direkt aufgerufen statt auf ein echtes, zeitlich unvorhersehbares
Datei-Ereignis zu warten — deterministisch und schnell, wie der Rest der
Suite (kein echter Timer/Wait)."""

from datetime import datetime

from poe_view.services.zone_watcher import (ZoneWatcher, is_rest_area,
                                            resolve_client_log_path, zone_stays)

_ZONE_LINE = ('2026/08/01 21:44:37 15181671 cffb0658 [INFO Client 18604] '
             ': You have entered The Coast.\n')
_OTHER_LINE = '2026/08/01 21:44:38 15181672 54ee9dc3 [INFO Client 18604] [WINDOW] Lost focus\n'


def _write(path, text) -> None:
    path.write_text(text, encoding="utf-8")


# --- resolve_client_log_path: Datei ODER nur der Installationsordner --- #

def test_resolve_accepts_the_log_file_directly(tmp_path) -> None:
    log = tmp_path / "Client.txt"
    log.write_text("", encoding="utf-8")
    assert resolve_client_log_path(str(log)) == log


def test_resolve_accepts_the_install_folder_with_a_logs_subfolder(tmp_path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log = logs_dir / "Client.txt"
    log.write_text("", encoding="utf-8")
    assert resolve_client_log_path(str(tmp_path)) == log


def test_resolve_accepts_the_logs_folder_itself(tmp_path) -> None:
    log = tmp_path / "Client.txt"
    log.write_text("", encoding="utf-8")
    assert resolve_client_log_path(str(tmp_path)) == log


def test_resolve_returns_none_for_an_empty_or_missing_path(tmp_path) -> None:
    assert resolve_client_log_path("") is None
    assert resolve_client_log_path("   ") is None
    assert resolve_client_log_path(str(tmp_path / "does_not_exist")) is None


# --- ZoneWatcher: liest nur NEU angehängte Zeilen ---------------------- #

def test_ignores_content_written_before_construction(tmp_path, qapp) -> None:
    log = tmp_path / "Client.txt"
    _write(log, _ZONE_LINE)
    watcher = ZoneWatcher(log)

    seen = []
    watcher.zone_changed.connect(seen.append)
    watcher.check_now()
    assert seen == []


def test_emits_the_zone_name_for_a_newly_appended_line(tmp_path, qapp) -> None:
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)

    seen = []
    watcher.zone_changed.connect(seen.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_ZONE_LINE)
    watcher.check_now()
    assert seen == ["The Coast"]


def test_does_not_emit_for_unrelated_log_lines(tmp_path, qapp) -> None:
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)

    seen = []
    watcher.zone_changed.connect(seen.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_OTHER_LINE)
    watcher.check_now()
    assert seen == []


def test_emits_once_per_zone_line_in_a_single_batch(tmp_path, qapp) -> None:
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)

    seen = []
    watcher.zone_changed.connect(seen.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_OTHER_LINE)
        f.write(_ZONE_LINE)
        f.write(_ZONE_LINE.replace("The Coast", "Backstreet Hideout"))
    watcher.check_now()
    assert seen == ["The Coast", "Backstreet Hideout"]


def test_a_second_check_without_new_content_emits_nothing(tmp_path, qapp) -> None:
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)
    with log.open("a", encoding="utf-8") as f:
        f.write(_ZONE_LINE)
    watcher.check_now()

    seen = []
    watcher.zone_changed.connect(seen.append)
    watcher.check_now()
    assert seen == []


# --- Poll-Timer als verlässliche Grundlage (FALLSTRICKE #61) ----------- #

def test_the_poll_timer_runs_and_detects_an_append_without_any_watcher_event(
        tmp_path, qapp) -> None:
    """Peter, 2026-08-03: "Ich habe gerade die Zone gewechselt und das LOG
    hat es nicht mitbekommen." Ursache: Qts ``fileChanged`` feuert für PoEs
    Client.txt nicht (FALLSTRICKE #61). Der Poll-Timer trägt die Erkennung
    seitdem allein — hier bewusst OHNE jedes Datei-Ereignis geprüft, nur
    über den Timer-Slot."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)
    assert watcher._poll_timer.isActive()

    seen = []
    watcher.zone_changed.connect(seen.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_ZONE_LINE)
    watcher._poll_timer.timeout.emit()  # das, was der laufende Timer tut

    assert seen == ["The Coast"]


def test_a_truncated_or_replaced_file_is_watched_from_the_start_again(tmp_path, qapp) -> None:
    """Peter startet PoE gelegentlich neu — dann kann Client.txt kleiner
    sein als der zuletzt gemerkte Stand. Statt daran hängen zu bleiben,
    fängt die Beobachtung wieder bei 0 an."""
    log = tmp_path / "Client.txt"
    _write(log, _ZONE_LINE * 5)  # simuliert einen "alten", langen Stand
    watcher = ZoneWatcher(log)

    _write(log, _ZONE_LINE.replace("The Coast", "Backstreet Hideout"))  # neue, kürzere Datei
    seen = []
    watcher.zone_changed.connect(seen.append)
    watcher.check_now()
    assert seen == ["Backstreet Hideout"]


# --- Inventar-Ereignisse: Haendler-Verkauf und Identifizieren --- #
#
# Die Zeilenformate stammen 1:1 aus Peters echter Client.txt (dort
# nachgezaehlt: "Trade accepted." 1028x, "N Items identified" 821x,
# "1 Item identified" 78x, "Trade cancelled." 60x).

_TRADE_LINE = ('2026/08/10 21:06:27 15181673 cffb0658 [INFO Client 18604] '
               ': Trade accepted.\n')
_IDENTIFY_LINE = ('2026/08/10 21:06:08 15181674 cffb0658 [INFO Client 18604] '
                  ': 2 Items identified\n')
_IDENTIFY_ONE_LINE = ('2026/08/10 21:06:09 15181675 cffb0658 [INFO Client 18604] '
                      ': 1 Item identified\n')
_TRADE_CANCELLED_LINE = ('2026/08/10 21:06:30 15181676 cffb0658 [INFO Client 18604] '
                         ': Trade cancelled.\n')


def test_a_completed_trade_is_reported_as_an_inventory_event(tmp_path, qapp) -> None:
    """Peter, 2026-08-10: "Die Interaktion mit einem Haendler, Verkaufen,
    Identifizieren, ... triggert auch das Senden der neuesten Items von
    GGG-Seite." — "Trade accepted." deckt Verkauf an NPC UND Spielerhandel
    ab; fuer den Refresh macht die Unterscheidung keinen Unterschied."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)

    seen = []
    watcher.inventory_event.connect(seen.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_TRADE_LINE)
    watcher.check_now()
    assert seen == ["Trade accepted"]


def test_identifying_items_is_reported_in_both_singular_and_plural(tmp_path, qapp) -> None:
    """Beide Schreibweisen kommen in Peters Log real vor — eine davon zu
    uebersehen hiesse, jeden Einzel-Identify stillschweigend zu verpassen."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)

    seen = []
    watcher.inventory_event.connect(seen.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_IDENTIFY_LINE)
        f.write(_IDENTIFY_ONE_LINE)
    watcher.check_now()
    assert seen == ["2 Items identified", "1 Item identified"]


def test_a_cancelled_trade_is_not_an_inventory_event(tmp_path, qapp) -> None:
    """Gegenprobe: Bei "Trade cancelled." aendert sich nichts — ein Abruf
    darauf waere reine Rate-Limit-Verschwendung."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)

    seen = []
    watcher.inventory_event.connect(seen.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_TRADE_CANCELLED_LINE)
        f.write(_OTHER_LINE)
    watcher.check_now()
    assert seen == []


def test_zone_changes_and_inventory_events_stay_on_separate_signals(tmp_path, qapp) -> None:
    """Getrennte Signale, weil der Zonenwechsel zusaetzlich die
    Zonen-Anzeige und die Messungen aus §_PublishWatch fuettert — ein
    Haendler-Verkauf hat dort nichts verloren, obwohl beide denselben
    Refresh ausloesen."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)

    zones, events = [], []
    watcher.zone_changed.connect(zones.append)
    watcher.inventory_event.connect(events.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_ZONE_LINE)
        f.write(_TRADE_LINE)
    watcher.check_now()

    assert zones == ["The Coast"]
    assert events == ["Trade accepted"]


# --- Instanz-Kennung (Peter, 2026-08-13) ------------------------------- #
#
# Echte Zeilen aus Peters Client.txt, gekuerzt. Die Kennung steht IMMER
# vor dem zugehoerigen "You have entered".

_INSTANCE_BLOCK = (
    '2026/08/13 17:23:10 11298781 11869d8b [DEBUG Client 21356] '
    'Client-Safe Instance ID = 2308728564\n'
    '2026/08/13 17:23:10 11298781 1186a8a3 [DEBUG Client 21356] '
    'Generating level 80 area "MapWorldsBrambleValley" with seed 711400918\n'
    '2026/08/13 17:23:11 11299000 cffb065b [INFO Client 21356] '
    ': You have entered Bramble Valley.\n')


def test_the_instance_id_is_picked_up_with_the_zone(qapp, tmp_path) -> None:
    """Ohne sie liesse sich "zurueck in dieselbe Map" nicht von "naechste
    Map gleichen Namens" unterscheiden — am Zonennamen allein ist das
    NICHT zu erkennen, und die Gruppierung im XP-Graphen haengt daran."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)
    zonen = []
    watcher.zone_changed.connect(zonen.append)

    _write(log, _INSTANCE_BLOCK)
    watcher.check_now()

    assert zonen == ["Bramble Valley"]
    assert watcher.last_instance_id == "2308728564"


def test_returning_to_the_same_map_keeps_the_same_instance_id(qapp, tmp_path) -> None:
    """Peters echter Ablauf vom 2026-08-13: Map, kurz ins Hideout Items
    verkaufen, zurueck in DIESELBE Map. Beide Male 2308728564."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)
    gesehen = []
    watcher.zone_changed.connect(lambda zone: gesehen.append((zone, watcher.last_instance_id)))

    hideout = ('2026/08/13 17:29:12 1 x [DEBUG Client 1] '
               'Client-Safe Instance ID = 3117141110\n'
               '2026/08/13 17:29:13 1 x [INFO Client 1] '
               ': You have entered Backstreet Hideout.\n')
    _write(log, _INSTANCE_BLOCK + hideout + _INSTANCE_BLOCK)
    watcher.check_now()

    assert gesehen == [("Bramble Valley", "2308728564"),
                       ("Backstreet Hideout", "3117141110"),
                       ("Bramble Valley", "2308728564")]


def test_without_the_debug_line_the_id_stays_empty(qapp, tmp_path) -> None:
    """Es ist eine DEBUG-Zeile. Fehlt sie, bleibt die Kennung leer und
    alles verhaelt sich wie zuvor — jeder Aufenthalt zaehlt fuer sich.
    Lieber nicht gruppieren als falsch gruppieren."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)
    zonen = []
    watcher.zone_changed.connect(zonen.append)

    _write(log, _ZONE_LINE)
    watcher.check_now()

    assert zonen == ["The Coast"]
    assert watcher.last_instance_id == ""


# --- Tode: "has been slain" je Charakter, rollierendes Fenster --------- #

_DEATH_LINE_A = ('2026/09/13 19:25:16 28758625 cffb065b [INFO Client 19976] '
                 ': WitchOfPeter has been slain.\n')
_DEATH_LINE_B = ('2026/09/13 20:48:14 33736781 cffb065b [INFO Client 19976] '
                 ': Demo Ranger has been slain.\n')
_DEATH_YESTERDAY = ('2026/09/12 23:59:59 11111111 cffb065b [INFO Client 19976] '
                    ': WitchOfPeter has been slain.\n')
_DEATH_TOO_OLD = ('2026/09/10 12:00:00 22222222 cffb065b [INFO Client 19976] '
                  ': WitchOfPeter has been slain.\n')


def test_deaths_since_counts_only_the_window_per_character(tmp_path) -> None:
    """Anlass (2026-09-13): Aus den XP-Deltas sind Tode nicht ablesbar —
    ein Tod in einem 11,5-Minuten-Fenster verschwand im Netto (+1,9 Mio.).
    Die Client.txt ist die verlässliche Quelle für den Zähler. Das
    Fenster ist ROLLIEREND (Peter: kein Reset um Mitternacht) — die
    Zeile von 23:59 des Vortags zählt hier mit, die ältere nicht."""
    from datetime import datetime
    from poe_view.services.zone_watcher import deaths_since
    log = tmp_path / "Client.txt"
    _write(log, _DEATH_TOO_OLD + _DEATH_YESTERDAY + _DEATH_LINE_A
           + _DEATH_LINE_B + _ZONE_LINE)

    tode = deaths_since(log, datetime(2026, 9, 12, 21, 0, 0))

    assert set(tode) == {"WitchOfPeter", "Demo Ranger"}
    assert tode["WitchOfPeter"] == [datetime(2026, 9, 12, 23, 59, 59),
                                    datetime(2026, 9, 13, 19, 25, 16)]
    assert tode["Demo Ranger"] == [datetime(2026, 9, 13, 20, 48, 14)]


def test_deaths_since_returns_empty_for_a_missing_file(tmp_path) -> None:
    from datetime import datetime
    from poe_view.services.zone_watcher import deaths_since
    assert deaths_since(tmp_path / "fehlt.txt", datetime(2026, 9, 13)) == {}


def test_a_newly_appended_death_line_is_emitted_with_its_time(tmp_path, qapp) -> None:
    from datetime import datetime
    log = tmp_path / "Client.txt"
    _write(log, _OTHER_LINE)
    watcher = ZoneWatcher(log)
    seen = []
    watcher.death_seen.connect(lambda name, at: seen.append((name, at)))

    with log.open("a", encoding="utf-8") as f:
        f.write(_DEATH_LINE_A)
    watcher.check_now()

    assert seen == [("WitchOfPeter", datetime(2026, 9, 13, 19, 25, 16))]


def test_a_death_line_is_no_zone_or_inventory_event(tmp_path, qapp) -> None:
    log = tmp_path / "Client.txt"
    _write(log, _OTHER_LINE)
    watcher = ZoneWatcher(log)
    zonen, inventar = [], []
    watcher.zone_changed.connect(zonen.append)
    watcher.inventory_event.connect(inventar.append)

    with log.open("a", encoding="utf-8") as f:
        f.write(_DEATH_LINE_A)
    watcher.check_now()

    assert zonen == [] and inventar == []


# --- Gebiets-Kennung: Kampfzone oder Ruhezone? ------------------------- #

def _stay_lines(stamp: str, area: str, instance: str, name: str) -> str:
    """Der Dreisatz, mit dem PoE jeden Zonenwechsel protokolliert."""
    return (f'{stamp} 1 11869d8b [DEBUG Client 1] '
            f'Client-Safe Instance ID = {instance}\n'
            f'{stamp} 1 1186a8a3 [DEBUG Client 1] '
            f'Generating level 70 area "{area}" with seed 1\n'
            f'{stamp} 1 cffb065b [INFO Client 1] : You have entered {name}.\n')


def test_rest_areas_are_recognised_by_their_area_id() -> None:
    """Ausgezaehlt an Peters echter Client.txt (2026-09-22): Hideouts,
    Staedte (auch die Endgame-Stadt), die Hubs und die Labyrinth-Vorhalle
    bringen keine Erfahrung."""
    for kennung in ("HideoutSlum", "HideoutTemplarLab", "1_1_town", "2_8_town",
                    "2_11_endgame_town", "HeistHub", "DeepwaterHub", "MavenHub",
                    "Menagerie_Hub", "Labyrinth_Airlock", "KalguuranSettlersLeague"):
        assert is_rest_area(kennung), kennung


def test_fighting_areas_are_not_rest_areas() -> None:
    """Und ausdruecklich NICHT pauschal alles mit "Labyrinth": Die
    Labyrinth-Gebiete selbst sind Kampfzonen, nur die Vorhalle nicht."""
    for kennung in ("MapWorldsCage", "Delve_Main", "3_Labyrinth_boss_2",
                    "EndGame_Labyrinth_OH_straight", "1_3_17_1", "MapSideArea4_1"):
        assert not is_rest_area(kennung), kennung


def test_an_unknown_area_id_counts_as_a_fighting_area() -> None:
    """Ohne Kennung bleibt es beim Verhalten von vorher: Der Aufenthalt
    zaehlt. Eine uebersehene Kampfzone verfaelscht die Rate staerker als
    eine mitgezaehlte Ruhepause."""
    assert not is_rest_area("")
    assert not is_rest_area("   ")


# --- zone_stays: Verweildauern aus der Client.txt ---------------------- #

_STAY_LOG = (
    _stay_lines("2026/09/22 22:20:37", "HideoutSlum", "111", "Backstreet Hideout")
    + _stay_lines("2026/09/22 22:21:23", "MapWorldsCage", "222", "Cage")
    + _stay_lines("2026/09/22 22:29:17", "HideoutSlum", "333", "Backstreet Hideout")
    + _stay_lines("2026/09/22 22:29:53", "MapWorldsCage", "222", "Cage")
    + _stay_lines("2026/09/22 22:31:03", "HideoutSlum", "444", "Backstreet Hideout"))


def test_zone_stays_returns_each_visit_with_its_duration(tmp_path) -> None:
    """Peters echter Ablauf vom 2026-09-22, Sekunde fuer Sekunde: 474 s
    in der Map, 36 s Hideout, nochmal 70 s in DERSELBEN Instanz."""
    log = tmp_path / "Client.txt"
    _write(log, _STAY_LOG)

    stays = zone_stays(log, datetime(2026, 9, 22, 22, 0))

    assert [(s.name, s.seconds, s.resting) for s in stays] == [
        ("Backstreet Hideout", 46.0, True),
        ("Cage", 474.0, False),
        ("Backstreet Hideout", 36.0, True),
        ("Cage", 70.0, False),
        ("Backstreet Hideout", 0.0, True)]     # noch drin
    assert stays[-1].left is None
    assert [s.instance for s in stays if not s.resting] == ["222", "222"]


def test_zone_stays_keeps_a_visit_that_started_before_the_window(tmp_path) -> None:
    """Sonst fiele genau die Map heraus, die beim Start des Fensters
    schon lief — der Aufrufer schneidet sie selbst zu."""
    log = tmp_path / "Client.txt"
    _write(log, _STAY_LOG)

    stays = zone_stays(log, datetime(2026, 9, 22, 22, 25))

    assert [s.name for s in stays] == ["Cage", "Backstreet Hideout", "Cage",
                                       "Backstreet Hideout"]
    assert stays[0].entered == datetime(2026, 9, 22, 22, 21, 23)


def test_zone_stays_does_not_inherit_the_area_id_of_the_previous_zone(tmp_path) -> None:
    """Fehlt die DEBUG-Zeile, ist die Kennung UNBEKANNT — nicht die der
    Zone davor. Sonst gaelte ein Aufenthalt nach einem Hideout-Besuch
    stillschweigend als Ruhezone und fiele aus der Rechnung."""
    log = tmp_path / "Client.txt"
    _write(log, _stay_lines("2026/09/22 22:20:37", "HideoutSlum", "111", "Backstreet Hideout")
           + '2026/09/22 22:21:23 1 cffb065b [INFO Client 1] : You have entered Cage.\n'
           + _stay_lines("2026/09/22 22:29:17", "HideoutSlum", "333", "Backstreet Hideout"))

    stays = zone_stays(log, datetime(2026, 9, 22, 22, 0))

    assert [(s.name, s.area_id, s.resting) for s in stays] == [
        ("Backstreet Hideout", "HideoutSlum", True),
        ("Cage", "", False),
        ("Backstreet Hideout", "HideoutSlum", True)]


def test_zone_stays_returns_empty_for_a_missing_file(tmp_path) -> None:
    assert zone_stays(tmp_path / "nope.txt", datetime(2026, 9, 22)) == []


def test_the_watcher_picks_up_the_area_id_with_the_zone(tmp_path, qapp) -> None:
    """Live dieselbe Kennung wie im Rueckblick — sonst rechnete der
    laufende Betrieb mit anderen Zonen als der Start."""
    log = tmp_path / "Client.txt"
    _write(log, "")
    watcher = ZoneWatcher(log)
    gesehen = []
    watcher.zone_changed.connect(lambda zone: gesehen.append((zone, watcher.last_area_id)))

    _write(log, _stay_lines("2026/09/22 22:21:23", "MapWorldsCage", "222", "Cage"))
    watcher.check_now()

    assert gesehen == [("Cage", "MapWorldsCage")]


# --- Der Gebietslevel aus derselben Zeile (§4.56) ---------------------- #

def _level_lines(stamp: str, area: str, level: int, name: str) -> str:
    return (f'{stamp} 1 11869d8b [DEBUG Client 1] '
            f'Client-Safe Instance ID = 1\n'
            f'{stamp} 1 1186a8a3 [DEBUG Client 1] '
            f'Generating level {level} area "{area}" with seed 1\n'
            f'{stamp} 1 cffb065b [INFO Client 1] : You have entered {name}.\n')


def test_zone_stays_carries_the_area_level(tmp_path) -> None:
    """Die Zahl stand immer schon in der Zeile — sie wurde nur
    weggeworfen. Peters Log am 26.09.: Chateau auf 68, davor Atoll auf
    77."""
    log = tmp_path / "Client.txt"
    log.write_text(_level_lines("2026/09/26 13:00:00", "MapWorldsAtoll", 77, "Atoll")
                   + _level_lines("2026/09/26 13:10:00", "MapWorldsChateau", 68,
                                  "Chateau"),
                   encoding="utf-8")

    stays = zone_stays(log, datetime(2026, 9, 26))

    assert [(s.area_id, s.level) for s in stays] == [
        ("MapWorldsAtoll", 77), ("MapWorldsChateau", 68)]


def test_a_stay_without_a_generating_line_has_level_zero(tmp_path) -> None:
    """Ein Log ohne DEBUG-Zeilen (anderer Log-Umfang) darf den Level der
    Zone davor NICHT erben — 0 heisst "unbekannt", und die Anzeige sagt
    dann nichts."""
    log = tmp_path / "Client.txt"
    log.write_text(
        _level_lines("2026/09/26 13:00:00", "MapWorldsAtoll", 77, "Atoll")
        + "2026/09/26 13:10:00 1 cffb065b [INFO Client 1] : You have entered Cage.\n",
        encoding="utf-8")

    stays = zone_stays(log, datetime(2026, 9, 26))

    assert [(s.name, s.level) for s in stays] == [("Atoll", 77), ("Cage", 0)]


def test_the_watcher_remembers_the_level_of_the_zone_just_entered(tmp_path) -> None:
    """``last_area_level`` neben ``last_area_id``: Die Zeile steht immer
    VOR dem "You have entered", der Wert ist beim Emittieren also schon
    gesetzt (dieselbe Begruendung wie bei der Instanz-Kennung)."""
    log = tmp_path / "Client.txt"
    log.write_text("", encoding="utf-8")
    watcher = ZoneWatcher(log)
    gesehen = []
    watcher.zone_changed.connect(
        lambda name: gesehen.append((name, watcher.last_area_level)))

    log.write_text(_level_lines("2026/09/26 13:00:00", "MapWorldsChateau", 68,
                                "Chateau"), encoding="utf-8")
    watcher.check_now()

    assert gesehen == [("Chateau", 68)]
    assert watcher.last_area_id == "MapWorldsChateau"


# --- Die Minen-Basis (Peters Bildschirmfoto, 2026-09-27) --------------- #

def test_the_mine_base_is_a_rest_area_but_the_nodes_are_not() -> None:
    """Die Basis teilt sich die Kennung ``Delve_Main`` mit dem ganzen
    Bergwerk — am Namen allein ist sie nicht zu erkennen. Peters
    Bildschirmfoto nennt beide Zahlen nebeneinander: "Azurite Mine ·
    Monster Level: 34 · Delve Depth: 0". Dort stehen Niko, der
    Voltaxic-Generator, eine Truhe und der einzige Wegpunkt des
    Bergwerks; gestorben ist dort in 44 Besuchen nie jemand."""
    assert is_rest_area("Delve_Main", 34)
    assert not is_rest_area("Delve_Main", 72)
    assert not is_rest_area("Delve_Main", 47)


def test_without_a_level_the_mine_counts_as_a_combat_zone() -> None:
    """Fehlt die DEBUG-Zeile mit dem Level, gilt die alte Regel: lieber
    eine Ruhepause mitzaehlen als eine Kampfzone uebersehen."""
    assert not is_rest_area("Delve_Main")


def test_the_level_does_not_leak_into_other_zones() -> None:
    """Ein Hideout bleibt eine Ruhezone, egal welche Stufe daneben
    steht, und eine Karte auf Stufe 34 bleibt eine Kampfzone."""
    assert is_rest_area("HideoutSlum", 34)
    assert is_rest_area("HideoutSlum", 72)
    assert not is_rest_area("MapWorldsBazaar", 34)


def test_zone_stays_carries_the_seed_and_does_not_inherit_it(tmp_path) -> None:
    """Der Seed erkennt dieselbe Karte über mehrere Eintritte
    (§_AREA_LINE). Ein Eintritt ohne Generierungszeile erbt ihn nicht —
    sonst hielte der Katalog eine fremde Zone für dieselbe Karte."""
    log = tmp_path / "Client.txt"
    log.write_text(
        "2026/09/26 13:00:00 1 1186a8a3 [DEBUG Client 1] "
        'Generating level 70 area "MapWorldsPort" with seed 711400918\n'
        "2026/09/26 13:00:01 1 cffb065b [INFO Client 1] : You have entered Port.\n"
        "2026/09/26 13:10:00 1 cffb065b [INFO Client 1] : You have entered Cage.\n",
        encoding="utf-8")

    stays = zone_stays(log, datetime(2026, 9, 26))

    assert [s.seed for s in stays] == ["711400918", ""]


# --- /kills (§kills_log) ------------------------------------------------ #

_KILLS_LINE = ('2026/10/02 21:32:08 36346140 cffb065b [INFO Client 21176] '
               ': You have killed 131.404 monsters.\n')


def test_a_kills_reading_is_emitted_with_its_count_and_time(tmp_path, qapp) -> None:
    log = tmp_path / "Client.txt"
    _write(log, _OTHER_LINE)
    watcher = ZoneWatcher(log)
    gesehen, zonen = [], []
    watcher.kills_reported.connect(lambda n, at: gesehen.append((n, at)))
    watcher.zone_changed.connect(zonen.append)

    with log.open("a", encoding="utf-8") as f:
        f.write(_KILLS_LINE)
    watcher.check_now()

    assert gesehen == [(131404, datetime(2026, 10, 2, 21, 32, 8))]
    assert zonen == []


def test_the_watcher_keeps_the_seed_of_the_last_area(tmp_path, qapp) -> None:
    log = tmp_path / "Client.txt"
    _write(log, _OTHER_LINE)
    watcher = ZoneWatcher(log)
    with log.open("a", encoding="utf-8") as f:
        f.write('2026/10/02 21:30:00 1 c [DEBUG Client 1] Generating level 61 area '
                '"2_9_1" with seed 2711539918\n')
    watcher.check_now()
    assert watcher.last_area_seed == "2711539918"



def test_kill_readings_come_with_the_login_they_belong_to(tmp_path) -> None:
    from poe_view.services.zone_watcher import kill_readings
    log = tmp_path / "Client.txt"
    _write(log, "".join([
        "2026/10/02 20:00:00 1 c [INFO Client 7] Async connecting to fra.login.pathofexile.com:20488\n",
        _KILLS_LINE,
        "2026/10/02 21:40:00 1 c [INFO Client 7] : You have killed 131.950 monsters.\n",
        "2026/10/02 22:00:00 1 c [INFO Client 8] Async connecting to fra.login.pathofexile.com:20488\n",
        "2026/10/02 22:05:00 1 c [INFO Client 8] : You have killed 12 monsters.\n",
    ]))
    gelesen = kill_readings(log)
    assert [(r.total, r.session) for r in gelesen] == [(131404, 1), (131950, 1), (12, 2)]
    assert gelesen[0].at == datetime(2026, 10, 2, 21, 32, 8)


def test_kill_readings_of_a_missing_file_are_empty(tmp_path) -> None:
    from poe_view.services.zone_watcher import kill_readings
    assert kill_readings(tmp_path / "fehlt.txt") == []


_LEVEL_LINE = ('2026/10/08 18:31:07 33736781 cffb065b [INFO Client 19976] '
               ': WitchOfPeter (Chieftain) is now level 32\n')


def test_a_level_up_is_emitted_for_the_leveling_plan(tmp_path, qapp) -> None:
    """§4.60.14: Der Plan zählt live weiter — der Aufstieg kommt aus der
    Client.txt, die API kennt ihn erst beim nächsten Abruf."""
    log = tmp_path / "Client.txt"
    _write(log, _OTHER_LINE)
    watcher = ZoneWatcher(log)
    stufen, tode, zonen = [], [], []
    watcher.level_up.connect(lambda name, level: stufen.append((name, level)))
    watcher.death_seen.connect(lambda *a: tode.append(a))
    watcher.zone_changed.connect(zonen.append)
    with log.open("a", encoding="utf-8") as f:
        f.write(_LEVEL_LINE)
        f.write(_LEVEL_LINE.replace("WitchOfPeter (Chieftain)", "PeterM (Necromancer)")
                .replace("level 32", "level 100"))
    watcher.check_now()
    assert stufen == [("WitchOfPeter", 32), ("PeterM", 100)]
    assert tode == [] and zonen == []
