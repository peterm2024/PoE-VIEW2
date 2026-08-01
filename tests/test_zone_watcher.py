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
