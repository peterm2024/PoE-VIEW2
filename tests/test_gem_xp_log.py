"""Tests für die CSV-Mitschrift der Sockel-Gem-Erfahrung (Peter,
2026-08-10: "Ich werde demnächst eine Runde spielen, da können wir mal
die XP/h pro Gem messen ... Bitte bau doch mal ein Log ein, evtl als
csv, dass das mitschreibt").
"""

import csv

import pytest

from poe_view.api.models import Item
from poe_view.services import gem_xp_log


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """Den LOG-Ordner umbiegen, nicht die Datei direkt — der einzige Weg,
    der etwas beweist: Eine Konstante, beim Import ausgerechnet, hätte
    diesen Umweg ignoriert und in Peters echten Ordner geschrieben. Genau
    das ist ``cache_backup`` schon einmal passiert (sechs Fremdkörper in
    seinem echten ``backups``-Verzeichnis), siehe ``gem_xp_log.log_path``."""
    monkeypatch.setattr(gem_xp_log.config, "LOG_DIR", tmp_path)
    return tmp_path


def test_the_log_path_follows_the_configured_log_folder(log_dir) -> None:
    """Gegenstück zur Fixture: Wird der Log-Ordner umgebogen, muss die
    Datei mitwandern — sonst schreibt jeder Test in echte Nutzerdaten."""
    assert gem_xp_log.log_path().parent == log_dir


_LEVELING_GEM = {
    "id": "gem-a", "typeLine": "Fire Trap", "support": False,
    "properties": [{"name": "Level", "values": [["19", 0]]},
                   {"name": "Quality", "values": [["+19%", 1]]}],
    "additionalProperties": [
        {"name": "Experience", "values": [["66921722/212046017", 0]], "progress": 0.32},
    ],
}

_CAPPED_GEM = {
    "id": "gem-b", "typeLine": "Blood Rage", "support": False,
    "properties": [{"name": "Level", "values": [["1", 0]]}],
    "additionalProperties": [
        {"name": "Experience", "values": [["49725/49725", 0]], "progress": 1},
    ],
    "nextLevelRequirements": [
        {"name": "Level", "values": [["20", 0]]},
        {"name": "Dex", "values": [["50", 0]]},
    ],
}


def _helm(*gems: dict) -> Item:
    return Item.model_validate({"id": "helm-1", "typeLine": "Rat's Nest",
                                "inventoryId": "Helm", "socketedItems": list(gems)})


def test_append_writes_a_header_and_one_row_per_gem(log_dir) -> None:
    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM, _CAPPED_GEM)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert {r["gem"] for r in rows} == {"Fire Trap", "Blood Rage"}
    assert all(r["character"] == "WitchOfPeter" and r["slot"] == "Helm" for r in rows)


def test_a_normally_leveling_gem_is_not_marked_as_capped(log_dir) -> None:
    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert row["level"] == "19"
    assert row["quality"] == "+19%"
    assert row["experience"] == "66921722"
    assert row["experience_max"] == "212046017"
    assert row["progress"] == "0.32"
    assert row["capped_by_requirement"] == "False"
    assert row["next_level_requirements"] == ""


def test_a_gem_stuck_on_a_missing_requirement_is_marked_as_capped(log_dir) -> None:
    """Peters zweiter Fall: ein Gem, das nicht weiterleveln KANN, weil
    ein Attribut (hier Dex) nicht hoch genug ist — real in Peters eigenem
    Cache gefunden (Blood Rage, ARCHITEKTUR.md §4.34), keine Vermutung."""
    gem_xp_log.append("WitchOfPeter", [_helm(_CAPPED_GEM)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert row["progress"] == "1"
    assert row["capped_by_requirement"] == "True"
    assert row["next_level_requirements"] == "Level 20; Dex 50"


def test_second_append_does_not_repeat_the_header(log_dir) -> None:
    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])
    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    lines = gem_xp_log.log_path().read_text(encoding="utf-8").splitlines()

    assert lines[0].startswith("timestamp,")
    assert sum(1 for line in lines if line.startswith("timestamp,")) == 1
    assert len(lines) == 3  # Header + zwei Messpunkte


def test_items_without_socketed_gems_write_nothing(log_dir) -> None:
    """Ein Ring, ein Amulett, der Rucksack — nichts davon hat Sockel. Kein
    leeres Log statt gar keinem, sonst müsste man beim Auswerten zwischen
    "kein Gem" und "kein Messpunkt" unterscheiden."""
    ring = Item.model_validate({"id": "r1", "typeLine": "Agony Gyre", "inventoryId": "Ring"})
    gem_xp_log.append("WitchOfPeter", [ring])

    assert not gem_xp_log.log_path().exists()


def test_the_character_column_distinguishes_multiple_characters(log_dir) -> None:
    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])
    gem_xp_log.append("AnotherChar", [_helm(_CAPPED_GEM)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert [r["character"] for r in rows] == ["WitchOfPeter", "AnotherChar"]
