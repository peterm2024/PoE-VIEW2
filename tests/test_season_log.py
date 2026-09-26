"""Tests für die Season-Historie (``services/season_log.py``).

Die Antwortstruktur in diesen Tests ist die echte von
``/account/leagues`` (live abgefragt am 2026-09-26): 16 Ligen, davon acht
mit ``category.current``, ``startAt`` in UTC, ``endAt`` überall ``null``.
"""

from datetime import datetime, timezone

from poe_view.services import season_log
from poe_view.services.season_log import EARLIER, Season


def antwort(*ligen: dict) -> dict:
    return {"leagues": list(ligen)}


def liga(liga_id: str, kategorie: str, start: str | None = None,
         current: bool = False) -> dict:
    eintrag = {"id": liga_id, "realm": "pc", "endAt": None,
               "category": {"id": kategorie}}
    if current:
        eintrag["category"]["current"] = True
    if start:
        eintrag["startAt"] = start
    return eintrag


STANDARD = liga("Standard", "Standard", "2013-01-23T21:00:00Z")
ALLFLAME = liga("Allflame", "Allflame", "2026-07-24T20:00:00Z", current=True)
SSF_ALLFLAME = liga("SSF R Allflame", "Allflame", "2026-07-24T20:00:00Z",
                    current=True)


def test_the_current_season_comes_from_the_category_not_the_league() -> None:
    """Allflame, HC Allflame und SSF R Allflame sind DIESELBE Season mit
    demselben Atlas — maßgeblich ist ``category.id``.

    Geprüft wird an einer Antwort, in der die ERSTE laufende Liga anders
    heißt als ihre Kategorie: Stünde hier ``eintrag["id"]`` statt
    ``category["id"]``, hieße die Season "HC SSF Allflame", und der
    Zonen-Katalog bekäme für jede Liga-Variante einen eigenen Topf.
    (Die Gegenprobe hat genau das zunächst durchgelassen — in der
    echten Antwort steht "Allflame" zufällig vorn, dort sind beide
    Namen gleich.)"""
    hc_zuerst = liga("HC SSF Allflame", "Allflame", "2026-07-24T20:00:00Z",
                     current=True)
    season = season_log.current_season(antwort(STANDARD, hc_zuerst, ALLFLAME))
    assert season is not None
    assert season.id == "Allflame"

    # Und mit der echten Reihenfolge derselbe Name.
    assert season_log.current_season(
        antwort(STANDARD, ALLFLAME, SSF_ALLFLAME)).id == "Allflame"


def test_the_start_is_converted_to_local_time() -> None:
    """Die Client.txt schreibt lokale Zeitstempel, verglichen wird gegen
    die. ``startAt`` kommt dagegen in UTC."""
    season = season_log.current_season(antwort(ALLFLAME))
    erwartet = (datetime(2026, 7, 24, 20, tzinfo=timezone.utc)
                .astimezone().replace(tzinfo=None))
    assert season.start == erwartet
    assert season.start.tzinfo is None


def test_a_permanent_league_is_not_a_season() -> None:
    """Standard läuft seit 2013 und ist nie "current" — sonst stünde die
    ganze Historie unter "Standard"."""
    assert season_log.current_season(antwort(STANDARD)) is None


def test_a_current_league_without_a_start_is_ignored() -> None:
    """Ruthless trägt in der echten Antwort ``startAt: null``. Ohne
    Startzeitpunkt lässt sich nichts einsortieren, und ein erfundener
    wäre schlimmer als keiner."""
    ohne = liga("Ruthless", "Ruthless", None, current=True)
    assert season_log.current_season(antwort(ohne)) is None


def test_recording_keeps_what_is_already_known(tmp_path) -> None:
    """Der Start einer Season steht fest. Ein späterer Abruf darf ihn
    nicht verschieben — sonst wanderte mit jedem Programmstart die
    Grenze, an der die Zonen einsortiert werden."""
    pfad = tmp_path / "seasons.json"
    season_log.save([Season("Allflame", datetime(2026, 7, 24, 22))], pfad)

    verschoben = liga("Allflame", "Allflame", "2026-08-01T20:00:00Z", current=True)
    bekannt = season_log.record_current(antwort(verschoben), pfad)

    assert [s.start for s in bekannt] == [datetime(2026, 7, 24, 22)]


def test_recording_adds_a_new_season_to_the_history(tmp_path) -> None:
    """So — und nur so — wächst die Historie: Die API vergisst beendete
    Ligen, jede neue Season muss beim Laufen festgehalten werden."""
    pfad = tmp_path / "seasons.json"
    season_log.save([Season("Mirage", datetime(2026, 4, 1))], pfad)

    bekannt = season_log.record_current(antwort(ALLFLAME), pfad)

    assert [s.id for s in bekannt] == ["Mirage", "Allflame"]
    assert [s.id for s in season_log.load(pfad)] == ["Mirage", "Allflame"]


def test_an_empty_or_broken_file_yields_no_seasons(tmp_path) -> None:
    pfad = tmp_path / "seasons.json"
    assert season_log.load(pfad) == []
    pfad.write_text("kein json", encoding="utf-8")
    assert season_log.load(pfad) == []
    pfad.write_text('{"version": 99, "seasons": []}', encoding="utf-8")
    assert season_log.load(pfad) == []


def test_season_at_picks_the_season_that_was_running() -> None:
    seasons = [Season("Mirage", datetime(2026, 4, 1)),
               Season("Allflame", datetime(2026, 7, 24, 22))]

    assert season_log.season_at(datetime(2026, 5, 1), seasons) == "Mirage"
    assert season_log.season_at(datetime(2026, 9, 1), seasons) == "Allflame"
    assert season_log.season_at(datetime(2026, 7, 24, 22), seasons) == "Allflame"
    assert season_log.season_at(datetime(2026, 7, 24, 21, 59), seasons) == "Mirage"


def test_everything_before_the_oldest_known_season_is_earlier() -> None:
    """Peters Client.txt reicht bis April zurück, die API kennt nur
    Allflame ab dem 24.07. Alles davor heißt ``EARLIER`` — nicht
    "Mirage", denn das wäre geraten."""
    seasons = [Season("Allflame", datetime(2026, 7, 24, 22))]
    assert season_log.season_at(datetime(2026, 5, 1), seasons) == EARLIER
    assert season_log.season_at(datetime(2026, 5, 1), []) == EARLIER


def test_the_newest_season_is_the_preselection() -> None:
    """Wer die Zonen-Tabelle öffnet, meint den Atlas, den er gerade
    spielt."""
    seasons = [Season("Mirage", datetime(2026, 4, 1)),
               Season("Allflame", datetime(2026, 7, 24, 22))]
    assert season_log.newest(seasons) == "Allflame"
    assert season_log.newest([]) == EARLIER


def test_the_path_follows_the_patched_app_data_dir() -> None:
    """Sonst schriebe ein Testlauf in Peters echten
    ``%LOCALAPPDATA%\\PoE-VIEW2`` (CLAUDE.md, "Tests")."""
    from poe_view import config
    assert season_log.seasons_path().parent == config.APP_DATA_DIR
