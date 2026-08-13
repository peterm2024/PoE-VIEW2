"""Tests für die Zonenwechsel-Beobachtung (Peter, 2026-08-01: "Erst nach
Zonenwechsel gibt es einen Refresh"). ``ZoneWatcher.check_now()`` wird
direkt aufgerufen statt auf ein echtes, zeitlich unvorhersehbares
Datei-Ereignis zu warten — deterministisch und schnell, wie der Rest der
Suite (kein echter Timer/Wait)."""

from poe_view.services.zone_watcher import ZoneWatcher, resolve_client_log_path

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
