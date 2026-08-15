"""XP-Verlauf über einen Programmstart hinweg (§4.44).

Der Kern ist die Umrechnung zwischen der laufzeitinternen ``monotonic``-
Uhr und der Wanduhr. Sie ist die einzige Stelle, an der ein Fehler nicht
auffiele: Ein falscher Nullpunkt zeichnet Balken an die falsche Stelle
im Graphen, ohne dass irgendetwas abstürzt.
"""

from __future__ import annotations

from typing import NamedTuple

import pytest

from poe_view import config
from poe_view.services import xp_history

SPAN = 3 * 3600


class P(NamedTuple):
    """Genügt dem Protokoll des Moduls; der echte XpPoint hängt an Qt."""

    at: float
    seconds: float
    rate: float
    instance: str = ""


def _hin_und_zurueck(punkte, *, mono_save=1000.0, wall_save=50_000.0,
                     mono_load=42.0, wall_load=None, span=SPAN):
    """Speichern und in einer neuen 'Sitzung' wieder laden."""
    if wall_load is None:
        wall_load = wall_save
    payload = xp_history.to_payload({"Held": punkte},
                                    now_mono=mono_save, now_wall=wall_save)
    return xp_history.from_payload(payload, now_mono=mono_load,
                                   now_wall=wall_load, span_s=span)


# --------------------------- Umrechnung ---------------------------------- #

def test_das_alter_eines_punktes_ueberlebt_den_neustart():
    """600 Sekunden alt bleibt 600 Sekunden alt, egal wo die
    monotone Uhr nach dem Neustart steht."""
    zurueck = _hin_und_zurueck([P(at=400.0, seconds=300.0, rate=1e8)],
                               mono_save=1000.0, mono_load=42.0)
    assert zurueck["Held"][0]["at"] == pytest.approx(42.0 - 600.0)


def test_die_zeit_zwischen_speichern_und_laden_zaehlt_mit():
    """Zwei Stunden Programmpause muessen den Punkt zwei Stunden aelter
    machen — sonst wandert er im Graphen nach rechts."""
    zurueck = _hin_und_zurueck([P(at=1000.0, seconds=60.0, rate=1e8)],
                               mono_save=1000.0, wall_save=50_000.0,
                               mono_load=0.0, wall_load=50_000.0 + 7200)
    assert zurueck["Held"][0]["at"] == pytest.approx(-7200.0)


def test_dauer_rate_und_instanz_bleiben_unveraendert():
    zurueck = _hin_und_zurueck([P(at=990.0, seconds=305.5, rate=1.23e8,
                                  instance="4711")])
    punkt = zurueck["Held"][0]
    assert punkt["seconds"] == pytest.approx(305.5)
    assert punkt["rate"] == pytest.approx(1.23e8)
    assert punkt["instance"] == "4711"


# ------------------------------ Kürzen ------------------------------------ #

def test_punkte_ausserhalb_des_graph_fensters_fallen_weg():
    """Was der Graph ohnehin nicht zeigt, muss gar nicht erst zurueck —
    sonst waechst die Datei ueber Wochen mit Unsichtbarem."""
    zurueck = _hin_und_zurueck([P(at=1000.0 - SPAN - 1, seconds=60.0, rate=1e8),
                                P(at=1000.0 - 60, seconds=60.0, rate=2e8)])
    assert [p["rate"] for p in zurueck["Held"]] == [2e8]


def test_ein_ganz_alter_stand_ergibt_gar_nichts():
    """Nach ein paar Tagen Pause ist der Verlauf leer statt falsch."""
    zurueck = _hin_und_zurueck([P(at=1000.0, seconds=60.0, rate=1e8)],
                               wall_save=50_000.0, wall_load=50_000.0 + 4 * SPAN)
    assert zurueck == {}


def test_punkte_aus_der_zukunft_werden_verworfen():
    """Gestellte Uhr oder eine Datei von einem anderen Rechner: Ein
    Balken, der noch nicht passiert ist, gehoert nicht in den Graphen."""
    zurueck = _hin_und_zurueck([P(at=1000.0, seconds=60.0, rate=1e8)],
                               wall_save=50_000.0, wall_load=50_000.0 - 3600)
    assert zurueck == {}


def test_eine_kleine_uhrabweichung_wird_geduldet():
    """Sekundenbruchteile zwischen den beiden Uhrabfragen duerfen den
    juengsten Punkt nicht kosten."""
    zurueck = _hin_und_zurueck([P(at=1000.0, seconds=60.0, rate=1e8)],
                               wall_save=50_000.0, wall_load=50_000.0 - 2)
    assert len(zurueck["Held"]) == 1


def test_die_reihenfolge_ist_nach_dem_laden_zeitlich():
    payload = xp_history.to_payload(
        {"Held": [P(at=990.0, seconds=60.0, rate=2e8),
                  P(at=900.0, seconds=60.0, rate=1e8)]},
        now_mono=1000.0, now_wall=50_000.0)
    zurueck = xp_history.from_payload(payload, now_mono=0.0,
                                      now_wall=50_000.0, span_s=SPAN)
    assert [p["rate"] for p in zurueck["Held"]] == [1e8, 2e8]


# --------------------------- Mehrere Charaktere --------------------------- #

def test_jeder_charakter_behaelt_seinen_eigenen_verlauf():
    payload = xp_history.to_payload(
        {"Eins": [P(at=990.0, seconds=60.0, rate=1e8)],
         "Zwei": [P(at=980.0, seconds=60.0, rate=2e8)]},
        now_mono=1000.0, now_wall=50_000.0)
    zurueck = xp_history.from_payload(payload, now_mono=0.0,
                                      now_wall=50_000.0, span_s=SPAN)
    assert sorted(zurueck) == ["Eins", "Zwei"]
    assert zurueck["Eins"][0]["rate"] == 1e8


def test_charaktere_ohne_punkte_landen_nicht_in_der_datei():
    payload = xp_history.to_payload({"Leer": []}, now_mono=1.0, now_wall=1.0)
    assert payload["characters"] == {}


# ------------------------------ Robustheit -------------------------------- #

def test_ein_alter_dateiaufbau_wird_verworfen():
    """Aendert sich das Format, ist ein alter Stand kein Verlust — aber
    falsch gedeutet waere er einer."""
    payload = xp_history.to_payload({"Held": [P(at=1.0, seconds=1.0, rate=1.0)]},
                                    now_mono=1.0, now_wall=1.0)
    payload["version"] = xp_history.VERSION + 1
    assert xp_history.from_payload(payload, now_mono=1.0, now_wall=1.0,
                                   span_s=SPAN) == {}


@pytest.mark.parametrize("payload", [
    {}, {"version": xp_history.VERSION}, "kein Objekt",
    {"version": xp_history.VERSION, "characters": "keine Zuordnung"},
])
def test_kaputte_nutzlast_ergibt_leeren_verlauf(payload):
    assert xp_history.from_payload(payload, now_mono=1.0, now_wall=1.0,
                                   span_s=SPAN) == {}


@pytest.mark.parametrize("zeile", [
    "kein Objekt", {}, {"at": "keine Zahl", "seconds": 1, "rate": 1},
    {"at": 1.0, "rate": 1.0}, {"at": None, "seconds": 1.0, "rate": 1.0},
])
def test_eine_kaputte_zeile_kostet_nicht_den_ganzen_verlauf(zeile):
    payload = {"version": xp_history.VERSION,
               "characters": {"Held": [zeile, {"at": 100.0, "seconds": 60.0,
                                               "rate": 5e8}]}}
    zurueck = xp_history.from_payload(payload, now_mono=0.0, now_wall=100.0,
                                      span_s=SPAN)
    assert [p["rate"] for p in zurueck["Held"]] == [5e8]


def test_fehlende_instanz_wird_zum_leeren_text():
    payload = {"version": xp_history.VERSION,
               "characters": {"Held": [{"at": 100.0, "seconds": 60.0,
                                        "rate": 1e8, "instance": 99}]}}
    zurueck = xp_history.from_payload(payload, now_mono=0.0, now_wall=100.0,
                                      span_s=SPAN)
    assert zurueck["Held"][0]["instance"] == ""


# -------------------------------- Datei ----------------------------------- #

def test_der_pfad_folgt_dem_gepatchten_app_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path / "woanders")
    assert xp_history.path_for("Konto#1234").parent == tmp_path / "woanders"


def test_der_pfad_trennt_die_konten(tmp_path, monkeypatch):
    """Wie beim Daten-Cache: Zwei Konten duerfen sich keinen Verlauf
    teilen."""
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path)
    assert xp_history.path_for("Eins#1") != xp_history.path_for("Zwei#2")


def test_der_pfad_entschaerft_ungueltige_zeichen(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path)
    assert "/" not in xp_history.path_for("a/b:c").name


def test_speichern_und_laden_ueber_die_datei(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path / "neu")
    pfad = xp_history.path_for("Konto#1")

    xp_history.save({"Held": [P(at=990.0, seconds=60.0, rate=7e8, instance="a")]},
                    pfad, now_mono=1000.0, now_wall=50_000.0)
    zurueck = xp_history.load(pfad, now_mono=0.0, now_wall=50_000.0, span_s=SPAN)

    assert zurueck["Held"][0]["rate"] == 7e8
    assert zurueck["Held"][0]["at"] == pytest.approx(-10.0)


def test_eine_fehlende_datei_ist_kein_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path)
    assert xp_history.load(tmp_path / "gibtsnicht.json", now_mono=0.0,
                           now_wall=0.0, span_s=SPAN) == {}


def test_eine_kaputte_datei_ist_kein_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path)
    pfad = tmp_path / "kaputt.json"
    pfad.write_text("{das ist kein JSON", encoding="utf-8")
    assert xp_history.load(pfad, now_mono=0.0, now_wall=0.0, span_s=SPAN) == {}


def test_speichern_legt_das_verzeichnis_an(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path / "tief" / "drin")
    pfad = xp_history.path_for("Konto#1")
    xp_history.save({"Held": [P(at=1.0, seconds=1.0, rate=1.0)]}, pfad,
                    now_mono=1.0, now_wall=1.0)
    assert pfad.exists()
