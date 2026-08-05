"""Tests für das vollständige-oder-gar-nicht-Schreiben der Cache-Dateien
(Peter, 2026-08-04: "Hab gerade gesehen, dass ich mehrere Instanzen von
PoE-VIEW gleichzeitig offen hatte. Konsequenzen?").

Der springende Punkt ist nicht, dass Schreiben funktioniert — das tat es
vorher auch. Geprüft wird der Fall, in dem es MISSLINGT: Dann muss die
bisherige Datei unangetastet auf ihrem letzten gültigen Stand bleiben.
"""

import json

import pytest

from poe_view.services import atomic_json, data_cache, price_cache
from poe_view.api.ninja import PriceIndex


def test_write_json_replaces_the_file_completely(tmp_path) -> None:
    path = tmp_path / "cache.json"
    atomic_json.write_json(path, {"a": 1})
    atomic_json.write_json(path, {"b": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"b": 2}


def test_a_failed_write_leaves_the_previous_file_intact(tmp_path, monkeypatch) -> None:
    """Der eigentliche Zweck: Absturz, Stromausfall oder eine zweite
    Instanz mitten im Schreibvorgang dürfen keine abgeschnittene Datei
    hinterlassen. Vorher wurde direkt in die Zieldatei geschrieben — dort
    stand danach ein Fragment."""
    path = tmp_path / "cache.json"
    atomic_json.write_json(path, {"wertvoll": "bleibt"})

    def boom(self, *args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(OSError):
        atomic_json.write_json(path, {"neu": "geht schief"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"wertvoll": "bleibt"}


def test_a_failed_write_leaves_no_leftover_temp_file(tmp_path, monkeypatch) -> None:
    """Sonst sammelten sich neben einer 52-MB-Datei beliebig viele
    52-MB-Leichen an."""
    path = tmp_path / "cache.json"

    def boom(self, *args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(OSError):
        atomic_json.write_json(path, {"neu": "geht schief"})

    assert list(tmp_path.iterdir()) == []


def test_two_writers_do_not_share_a_temp_file(tmp_path, monkeypatch) -> None:
    """Die Nebendatei trägt die Prozess-ID: Zwei gleichzeitig laufende
    Instanzen schreiben nicht in dieselbe Zwischendatei, sonst wäre das
    Problem nur verschoben."""
    seen = []
    real = atomic_json.Path.write_text

    def spy(self, *args, **kwargs):
        seen.append(self.name)
        return real(self, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.write_text", spy)
    monkeypatch.setattr(atomic_json.os, "getpid", lambda: 4711)
    atomic_json.write_json(tmp_path / "cache.json", {"a": 1})

    assert seen == ["cache.json.4711.tmp"]


def test_the_data_cache_writes_through_the_atomic_path(tmp_path, monkeypatch) -> None:
    """Verdrahtung statt nur Baustein: Die Funktion nützt nichts, wenn
    der Daten-Cache weiter direkt schreibt."""
    calls = []
    monkeypatch.setattr(atomic_json, "write_json",
                        lambda path, payload: calls.append(path))

    data_cache.save(data_cache.CachedData(), tmp_path / "data.json")

    assert calls == [tmp_path / "data.json"]


def test_the_price_cache_writes_through_the_atomic_path(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(price_cache, "_CACHE_FILE", tmp_path / "prices.json")
    monkeypatch.setattr(atomic_json, "write_json",
                        lambda path, payload: calls.append(path))

    price_cache.save("Standard", PriceIndex())

    assert calls == [tmp_path / "prices.json"]
