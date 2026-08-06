"""Tests fuer die zeitgestempelten Cache-Sicherungen (Peter, 2026-08-06:
"ein Backup mit Timestamp, das erst nach 24h geloescht werden darf …
ab 24h werden die alten Backups geloescht").

Anlass war ein realer Schaden am selben Abend, siehe FALLSTRICKE #66 —
eine Aenderung am Datenmodell schrieb sich beim naechsten Speichern in die
Cache-Datei durch. Wiederherstellbar nur durch einen vollen Neuabruf.
"""

import gzip
import json
from datetime import datetime, timedelta

import pytest

from poe_view.services import cache_backup


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Den DATENORDNER umbiegen, nicht das Sicherungsverzeichnis.

    Das ist der Weg, den auch die uebrigen Tests gehen — und der einzige,
    der etwas beweist: Eine Konstante ``BACKUP_DIR``, beim Import
    ausgerechnet, haette diesen Umweg ignoriert und in den echten Ordner
    des Nutzers geschrieben. Genau das ist am 2026-08-06 passiert (sechs
    Fremdkoerper in Peters ``backups``-Verzeichnis aus Testlaeufen),
    siehe ``cache_backup.directory``."""
    monkeypatch.setattr(cache_backup.config, "APP_DATA_DIR", tmp_path)
    return tmp_path


def test_the_backup_folder_follows_the_configured_data_folder(cache_dir) -> None:
    """Gegenstueck zur Fixture: Wird der Datenordner umgebogen, muss die
    Sicherung mitwandern — sonst schreibt jeder Test in echte
    Nutzerdaten."""
    assert cache_backup.directory().parent == cache_dir


@pytest.fixture
def source(cache_dir):
    path = cache_dir / "data-cache-Someone#1234.json"
    path.write_text(json.dumps({"account_name": "Someone#1234", "items": [1, 2, 3]}),
                    encoding="utf-8")
    return path


def _touch(source, when: datetime) -> None:
    """mtime der Quelle setzen — die Unveraendert-Pruefung haengt daran."""
    import os

    stamp = when.timestamp()
    os.utime(source, (stamp, stamp))


def _fake_backup(name: str, when: datetime) -> None:
    cache_backup.directory().mkdir(parents=True, exist_ok=True)
    stamp = when.strftime(cache_backup._STAMP_FORMAT)
    (cache_backup.directory() / f"{name}.{stamp}.json.gz").write_bytes(b"alt")


# --- Anlegen ---

def test_the_backup_contains_exactly_the_cache_content(source) -> None:
    """Eine Sicherung, die etwas anderes enthaelt als das Original, ist
    keine."""
    backup = cache_backup.create(source)

    assert backup is not None
    with gzip.open(backup, "rt", encoding="utf-8") as packed:
        assert json.load(packed) == json.loads(source.read_text(encoding="utf-8"))


def test_the_name_carries_the_cache_name_and_a_timestamp(source) -> None:
    backup = cache_backup.create(source, now=datetime(2026, 8, 6, 21, 25, 11))
    assert backup.name == "data-cache-Someone#1234.20260806-212511.json.gz"


def test_nothing_to_back_up_without_a_cache_file(cache_dir) -> None:
    assert cache_backup.create(cache_dir / "gibtsnicht.json") is None


def test_an_unchanged_cache_is_not_backed_up_twice(source) -> None:
    """Sonst legte jeder Neustart eine weitere identische Kopie an — wer
    dreimal hintereinander startet, ohne dazwischen etwas abzurufen,
    verdraengte damit aeltere, tatsaechlich verschiedene Staende."""
    _touch(source, datetime(2026, 8, 6, 20, 0))
    first = cache_backup.create(source, now=datetime(2026, 8, 6, 21, 0))
    second = cache_backup.create(source, now=datetime(2026, 8, 6, 22, 0))

    assert first is not None
    assert second is None
    assert len(cache_backup.backups_for(source)) == 1


def test_a_changed_cache_is_backed_up_again(source) -> None:
    _touch(source, datetime(2026, 8, 6, 20, 0))
    cache_backup.create(source, now=datetime(2026, 8, 6, 21, 0))

    source.write_text('{"neu": true}', encoding="utf-8")
    _touch(source, datetime(2026, 8, 6, 23, 0))

    assert cache_backup.create(source, now=datetime(2026, 8, 7, 0, 0)) is not None
    assert len(cache_backup.backups_for(source)) == 2


def test_backups_of_other_accounts_are_not_mixed_in(source, cache_dir) -> None:
    """Eine Cache-Datei je Konto — die Sicherungen duerfen sich nicht
    gegenseitig verdraengen oder loeschen."""
    _fake_backup("data-cache-Andere#9999", datetime(2026, 8, 6, 21, 0))
    cache_backup.create(source, now=datetime(2026, 8, 6, 21, 30))

    mine = cache_backup.backups_for(source)
    assert len(mine) == 1
    assert "Someone" in mine[0].name


# --- Aufraeumen ---

def test_backups_older_than_a_day_are_removed(source) -> None:
    now = datetime(2026, 8, 7, 12, 0)
    _fake_backup(source.stem, now - timedelta(hours=30))
    _fake_backup(source.stem, now - timedelta(hours=25))
    _fake_backup(source.stem, now - timedelta(hours=5))
    _fake_backup(source.stem, now - timedelta(minutes=10))

    assert cache_backup.prune(source, now=now) == 2
    assert len(cache_backup.backups_for(source)) == 2


def test_a_backup_exactly_at_the_limit_survives(source) -> None:
    """"erst nach 24h geloescht werden darf" — bei genau 24 Stunden also
    noch nicht."""
    now = datetime(2026, 8, 7, 12, 0)
    _fake_backup(source.stem, now - timedelta(hours=24))
    _fake_backup(source.stem, now)

    assert cache_backup.prune(source, now=now) == 0


def test_the_newest_backup_is_never_deleted(source) -> None:
    """Sonst staende man nach zwei Wochen Pause ganz ohne Sicherung da —
    also genau dann, wenn man am wenigsten weiss, was der letzte gute
    Stand war."""
    now = datetime(2026, 8, 20, 12, 0)
    _fake_backup(source.stem, now - timedelta(days=14))
    _fake_backup(source.stem, now - timedelta(days=13))

    assert cache_backup.prune(source, now=now) == 1
    assert len(cache_backup.backups_for(source)) == 1


def test_foreign_files_in_the_backup_folder_are_left_alone(source) -> None:
    """Was wir nicht als eigene Sicherung erkennen, wird nie geloescht —
    der Ordner steht dem Nutzer offen, und ein Aufraeumer, der fremde
    Dateien mitnimmt, ist genau die Sorte Ueberraschung, gegen die dieses
    Modul gebaut wurde."""
    cache_backup.directory().mkdir(parents=True, exist_ok=True)
    eigene = cache_backup.directory() / "meine-handkopie.json.gz"
    eigene.write_bytes(b"wichtig")
    _fake_backup(source.stem, datetime(2020, 1, 1))
    _fake_backup(source.stem, datetime(2020, 1, 2))

    cache_backup.prune(source, now=datetime(2026, 8, 7, 12, 0))

    assert eigene.exists()


def test_a_flood_of_backups_is_capped(source) -> None:
    """Rueckfallgrenze fuer den Fall, den die Altersregel nicht abdeckt:
    Wer im Minutentakt neu startet und dazwischen abruft, erzeugt binnen
    eines Tages beliebig viele Sicherungen."""
    now = datetime(2026, 8, 7, 12, 0)
    for minute in range(cache_backup.MAX_COUNT + 10):
        _fake_backup(source.stem, now - timedelta(minutes=minute))

    cache_backup.prune(source, now=now)

    assert len(cache_backup.backups_for(source)) == cache_backup.MAX_COUNT


def test_the_cap_keeps_the_newest_not_the_oldest(source) -> None:
    now = datetime(2026, 8, 7, 12, 0)
    for minute in range(cache_backup.MAX_COUNT + 5):
        _fake_backup(source.stem, now - timedelta(minutes=minute))

    cache_backup.prune(source, now=now)

    survivors = cache_backup.backups_for(source)
    assert cache_backup._stamp_of(survivors[0]) == now
    assert all(cache_backup._stamp_of(path) > now - timedelta(minutes=cache_backup.MAX_COUNT)
               for path in survivors)


# --- Zusammenspiel ---

def test_run_creates_before_it_prunes(source) -> None:
    """Braeche das Anlegen ab, waeren sonst die alten Sicherungen schon
    weg und die neue noch nicht da."""
    now = datetime(2026, 8, 7, 12, 0)
    _fake_backup(source.stem, now - timedelta(hours=30))
    _touch(source, now - timedelta(minutes=1))

    created = cache_backup.run(source, now=now)

    assert created is not None and created.exists()
    assert len(cache_backup.backups_for(source)) == 1  # die alte ist weg


def test_run_survives_a_missing_cache_file(cache_dir) -> None:
    """Erster Start ueberhaupt — kein Cache, kein Backup, kein Fehler."""
    assert cache_backup.run(cache_dir / "gibtsnicht.json") is None


def test_an_unreadable_backup_folder_does_not_raise(source, monkeypatch) -> None:
    """Ein misslungenes Backup darf den Programmstart nicht verhindern."""
    def boom(*_args, **_kwargs):
        raise OSError("kein Platz")

    monkeypatch.setattr(cache_backup.Path, "mkdir", boom)
    assert cache_backup.run(source) is None
