"""Tests für die Liga-Zuordnung (``services/league_log.py``).

Die Zeilenformate sind die echten aus Peters Client.txt; die Zahlen in
den Docstrings stammen aus der Messung über seine 5,5 Monate Log.
"""

from datetime import datetime, timedelta

from poe_view.services import league_log
from poe_view.services.league_log import UNKNOWN, Mark

LEVELUP = ("2026/09/26 12:00:00 1 abc [INFO Client 1] : "
           "WitchOfPeter (Occultist) is now level 83")
TOD = ("2026/09/26 18:00:00 1 abc [INFO Client 1] : "
       "PeterM has been slain.")
ZONE = ("2026/09/26 12:30:00 1 abc [INFO Client 1] : "
        "You have entered Chateau.")


def _log(tmp_path, *zeilen: str):
    pfad = tmp_path / "Client.txt"
    pfad.write_text("\n".join(zeilen), encoding="utf-8")
    return pfad


def test_both_line_types_name_the_character(tmp_path) -> None:
    """Aufstiege und Tode sind die einzigen Zeilen, die den Charakter
    nennen — 256 und 226 Stück in Peters Log."""
    marken = league_log.marks_from_log(_log(tmp_path, LEVELUP, ZONE, TOD))

    assert [(m.at.hour, m.character) for m in marken] == [
        (12, "WitchOfPeter"), (18, "PeterM")]


def test_an_unreadable_log_yields_no_marks(tmp_path) -> None:
    assert league_log.marks_from_log(tmp_path / "gibtsnicht.txt") == []


def test_the_nearest_mark_within_the_window_wins() -> None:
    marken = [Mark(datetime(2026, 9, 26, 12), "WitchOfPeter"),
              Mark(datetime(2026, 9, 26, 18), "PeterM")]

    assert league_log.character_at(datetime(2026, 9, 26, 13), marken) == "WitchOfPeter"
    assert league_log.character_at(datetime(2026, 9, 26, 17), marken) == "PeterM"


def test_a_mark_too_far_away_does_not_count() -> None:
    """Sechs Stunden decken 92 % der Zonen-Eintritte ab und sind
    trotzdem enger als ein Schlaf. Was darüber liegt, wäre geraten."""
    marken = [Mark(datetime(2026, 9, 26, 12), "WitchOfPeter")]

    assert league_log.character_at(datetime(2026, 9, 26, 17, 59), marken)
    assert not league_log.character_at(datetime(2026, 9, 26, 18, 1), marken)
    assert not league_log.character_at(datetime(2026, 9, 25, 12), marken)


def test_the_league_comes_from_the_character() -> None:
    marken = [Mark(datetime(2026, 9, 26, 12), "WitchOfPeter")]
    ligen = {"WitchOfPeter": "Allflame"}

    assert league_log.league_at(datetime(2026, 9, 26, 13), marken, ligen) == "Allflame"


def test_an_unmatched_time_is_unknown() -> None:
    """"Weiß ich nicht" ist eine Aussage, die man sehen soll — deshalb
    ein eigener Wert und kein leerer String."""
    assert league_log.league_at(datetime(2026, 9, 26), [], {}) == UNKNOWN
    marken = [Mark(datetime(2026, 9, 26, 12), "Fremder")]
    assert league_log.league_at(datetime(2026, 9, 26, 12), marken,
                                {"WitchOfPeter": "Allflame"}) == UNKNOWN


def test_times_before_the_running_season_are_marked_as_earlier() -> None:
    """Beim Season-Ende wandern die Charaktere in die permanente Liga.
    Ihr heutiger Name sagt dann nicht mehr, in welcher SEASON sie
    spielten — wohl aber, in welcher SPIELART, und genau darauf zielte
    Peters Frage ("Diese kommen aber in SSF Ruthless nicht vor"). Der
    Zusatz hält die alten Zahlen trotzdem getrennt: Sonst mischten sich
    zwei Atlanten in einer Zeile."""
    marken = [Mark(datetime(2026, 5, 1, 12), "PeterM"),
              Mark(datetime(2026, 9, 1, 12), "WitchOfPeter")]
    ligen = {"PeterM": "SSF Ruthless", "WitchOfPeter": "SSF R Allflame"}
    grenze = datetime(2026, 7, 24, 22)

    assert league_log.league_at(datetime(2026, 5, 1, 13), marken, ligen,
                                grenze) == "SSF Ruthless (earlier)"
    assert league_log.league_at(datetime(2026, 9, 1, 13), marken, ligen,
                                grenze) == "SSF R Allflame"


def test_without_a_season_boundary_every_name_is_taken_as_is() -> None:
    """Der Zustand vor dem ersten Liga-Abruf: Wir wissen nicht, wann die
    laufende Season begann, also gibt es auch kein "davor"."""
    marken = [Mark(datetime(2026, 5, 1, 12), "PeterM")]
    assert league_log.league_at(datetime(2026, 5, 1, 13), marken,
                                {"PeterM": "SSF Ruthless"}) == "SSF Ruthless"


# --- Das live mitgeschriebene Protokoll --------------------------------- #

def test_recording_keeps_one_mark_per_character_and_quarter_hour(tmp_path) -> None:
    """Ein Spielabend bringt sonst hunderte Zeilen, die alle dasselbe
    sagen. Das Suchfenster ist sechs Stunden breit — eine Marke je
    Viertelstunde reicht bei Weitem."""
    pfad = tmp_path / "sessions.json"
    for minute in (0, 3, 7, 14, 15, 31):
        league_log.record_seen("WitchOfPeter",
                               datetime(2026, 9, 26, 12, minute), pfad)

    marken = league_log.load_sessions(pfad)
    assert [m.at.minute for m in marken] == [0, 15, 30]
    assert {m.character for m in marken} == {"WitchOfPeter"}


def test_two_characters_in_the_same_quarter_hour_both_count(tmp_path) -> None:
    pfad = tmp_path / "sessions.json"
    league_log.record_seen("WitchOfPeter", datetime(2026, 9, 26, 12, 1), pfad)
    league_log.record_seen("PeterM", datetime(2026, 9, 26, 12, 2), pfad)

    assert {m.character for m in league_log.load_sessions(pfad)} == {
        "WitchOfPeter", "PeterM"}


def test_the_log_is_capped_so_it_cannot_grow_without_end(tmp_path) -> None:
    pfad = tmp_path / "sessions.json"
    start = datetime(2026, 9, 26, 12)
    for i in range(6):
        league_log.record_seen("WitchOfPeter", start + timedelta(minutes=15 * i),
                               pfad, max_marks=3)

    marken = league_log.load_sessions(pfad)
    assert len(marken) == 3
    assert marken[-1].at == start + timedelta(minutes=75)   # die jüngsten bleiben


def test_a_broken_session_file_yields_no_marks(tmp_path) -> None:
    pfad = tmp_path / "sessions.json"
    pfad.write_text("kein json", encoding="utf-8")
    assert league_log.load_sessions(pfad) == []


def test_the_session_path_follows_the_patched_app_data_dir() -> None:
    """Sonst schriebe ein Testlauf in Peters echten
    ``%LOCALAPPDATA%\\PoE-VIEW2`` (CLAUDE.md, "Tests")."""
    from poe_view import config
    assert league_log.sessions_path().parent == config.APP_DATA_DIR
