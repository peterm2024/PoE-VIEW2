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


def test_a_normally_leveling_gem_is_not_marked_as_waiting(log_dir) -> None:
    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert row["level"] == "19"
    assert row["quality"] == "+19%"
    assert row["experience"] == "66921722"
    assert row["experience_max"] == "212046017"
    assert row["progress"] == "0.32"
    assert row["waiting_for_levelup"] == "False"
    assert row["requirement_met"] == ""
    assert row["next_level_requirements"] == ""


def test_a_gem_with_a_full_bar_is_marked_as_waiting_for_a_levelup(log_dir) -> None:
    """Gems steigen in PoE nicht von selbst auf: Voller Balken plus
    ``nextLevelRequirements`` heisst "wartet auf den Klick". Genau so haelt
    Peter Blood Rage, Frostblink und Lifetap absichtlich auf Stufe 1 (in
    seiner Messstunde nachgewiesen, ARCHITEKTUR.md §4.35)."""
    gem_xp_log.append("WitchOfPeter", [_helm(_CAPPED_GEM)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert row["progress"] == "1"
    assert row["waiting_for_levelup"] == "True"
    assert row["next_level_requirements"] == "Level 20; Dex 50"


def _boots(**requirements: int) -> Item:
    return Item.model_validate({
        "id": "boots-1", "typeLine": "Soldier Boots", "inventoryId": "Boots",
        "requirements": [{"name": n, "values": [[str(v), 0]]}
                         for n, v in requirements.items()]})


def test_a_met_requirement_proves_the_gem_waits_voluntarily(log_dir) -> None:
    """Der Abgleich, der Peters zwei Faelle trennt: Traegt der Charakter
    Ausruestung, die 108 Dex verlangt, dann sind die 50 Dex der naechsten
    Gem-Stufe zwingend erfuellt — das Gem wartet also freiwillig. Genau
    dieser Fall lag bei allen vier wartenden Gems seiner Messstunde vor."""
    gem_xp_log.append("WitchOfPeter", [_helm(_CAPPED_GEM), _boots(Level=69, Dex=108)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["gem"] == "Blood Rage")

    assert row["waiting_for_levelup"] == "True"
    assert row["requirement_met"] == "True"
    assert row["attribute_floor"] == "Level 69; Dex 108"


def test_a_requirement_above_the_floor_stays_undecided_rather_than_blocked(log_dir) -> None:
    """Der Fehlschluss, den die erste Fassung machte: Ueber der
    Untergrenze zu liegen beweist NICHT, dass die Anforderung unerfuellt
    ist — es heisst nur, dass die getragene Ausruestung nichts darueber
    aussagt. Peters echte Attribute liegen weit ueber dem, was seine
    Ausruestung verlangt (Passivbaum, Juwelen); "ueber der Untergrenze,
    also blockiert" haette reihenweise Gems falsch gemeldet. Statt einer
    Behauptung steht die Untergrenze selbst in der Zeile."""
    gem_xp_log.append("WitchOfPeter", [_helm(_CAPPED_GEM), _boots(Level=69, Dex=30)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["gem"] == "Blood Rage")

    assert row["waiting_for_levelup"] == "True"
    assert row["requirement_met"] == ""
    assert row["next_level_requirements"] == "Level 20; Dex 50"
    assert row["attribute_floor"] == "Level 69; Dex 30"


def test_an_unknown_attribute_leaves_the_verdict_open(log_dir) -> None:
    """Ohne ein einziges getragenes Teil mit Dex-Anforderung laesst sich
    ueber die geforderte Dex gar nichts sagen — auch dann keine
    Behauptung."""
    gem_xp_log.append("WitchOfPeter", [_helm(_CAPPED_GEM), _boots(Level=69)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["gem"] == "Blood Rage")

    assert row["waiting_for_levelup"] == "True"
    assert row["requirement_met"] == ""
    assert row["attribute_floor"] == "Level 69"


def test_only_worn_items_count_towards_the_attribute_floor(log_dir) -> None:
    """Ein Item im Rucksack beweist gar nichts — der Charakter kann es
    aufgehoben haben, ohne seine Anforderungen zu erfuellen. Zaehlte es
    mit, wuerde aus einem moeglicherweise blockierten Gem faelschlich ein
    nachweislich freiwillig wartendes."""
    in_backpack = Item.model_validate({
        "id": "bag-1", "typeLine": "Soldier Boots", "inventoryId": "MainInventory",
        "requirements": [{"name": "Dex", "values": [["108", 0]]}]})

    gem_xp_log.append("WitchOfPeter", [_helm(_CAPPED_GEM), in_backpack])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert row["requirement_met"] == ""
    assert row["attribute_floor"] == ""


def test_an_older_log_with_different_columns_is_set_aside(log_dir) -> None:
    """Peters erste Messstunde liegt in einer Datei mit der alten Spalte
    ``capped_by_requirement``. Wuerde einfach weiter angehaengt, stuenden
    ab da Werte unter falschen Ueberschriften — die Datei waere
    stillschweigend unbrauchbar, rueckwirkend auch fuer den Teil, der
    vorher gestimmt hat."""
    old = gem_xp_log.log_path()
    old.write_text("timestamp,character,capped_by_requirement\nalt,alt,True\n",
                   encoding="utf-8")

    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    with gem_xp_log.log_path().open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1 and rows[0]["gem"] == "Fire Trap"

    retired = [p for p in log_dir.iterdir() if p.name.startswith("gem-xp-log-")]
    assert len(retired) == 1
    assert "capped_by_requirement" in retired[0].read_text(encoding="utf-8")


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


# --- Nur beim Entwickeln, nicht im ausgelieferten Programm --------------- #
#
# Peter, 2026-08-10: "Den Gem-Log lassen wir nicht in der Release drin, das
# ist dort unnuetz." Die Mitschrift ist ein Messwerkzeug, kein Feature --
# rund 1,8 MB pro Spielstunde, die nur jemand auswertet, der die Fragen
# dahinter kennt.

def test_the_log_stays_silent_in_a_packaged_release(log_dir, monkeypatch) -> None:
    monkeypatch.setattr(gem_xp_log.config, "RUNNING_AS_EXE", True)

    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    assert not gem_xp_log.log_path().exists()


def test_the_log_runs_by_itself_when_started_from_source(log_dir, monkeypatch) -> None:
    """Die Kehrseite, und der Grund fuer die Kopplung an die
    Auslieferungsform statt an eine Einstellung: Beim Weiterentwickeln ist
    die Mitschrift ohne Zutun da, und niemand muss daran denken, sie vor
    einem Release abzuschalten."""
    monkeypatch.setattr(gem_xp_log.config, "RUNNING_AS_EXE", False)

    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    assert gem_xp_log.log_path().exists()


def test_the_environment_variable_switches_the_log_on_in_a_release(
        log_dir, monkeypatch) -> None:
    """Wofuer der Schalter da ist: eine fertig gebaute .exe vor dem Release
    noch einmal mit Mitschrift durchspielen, ohne dafuer aus dem Quellcode
    starten zu muessen."""
    monkeypatch.setattr(gem_xp_log.config, "RUNNING_AS_EXE", True)
    monkeypatch.setenv("POEVIEW_GEM_XP_LOG", "1")

    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    assert gem_xp_log.log_path().exists()


def test_the_environment_variable_also_switches_it_off(log_dir, monkeypatch) -> None:
    """Gegenprobe in die andere Richtung — sonst waere der Schalter nur ein
    Ein-Schalter und man muesste zum Abschalten den Quellcode verlassen."""
    monkeypatch.setattr(gem_xp_log.config, "RUNNING_AS_EXE", False)
    monkeypatch.setenv("POEVIEW_GEM_XP_LOG", "0")

    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    assert not gem_xp_log.log_path().exists()


def test_a_disabled_log_does_not_touch_an_existing_file(log_dir, monkeypatch) -> None:
    """Abgeschaltet heisst wirklich nichts anfassen: Auch das Beiseitelegen
    einer aelteren Mitschrift mit anderen Spalten darf dann nicht laufen,
    sonst benennt ein ausgeliefertes Programm ungefragt Dateien um."""
    monkeypatch.setattr(gem_xp_log.config, "RUNNING_AS_EXE", True)
    vorhanden = gem_xp_log.log_path()
    vorhanden.write_text("timestamp,character,capped_by_requirement\n", encoding="utf-8")

    gem_xp_log.append("WitchOfPeter", [_helm(_LEVELING_GEM)])

    assert vorhanden.read_text(encoding="utf-8").startswith("timestamp,character,capped")
    assert list(log_dir.iterdir()) == [vorhanden]
