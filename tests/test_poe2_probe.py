"""PoE2-Rohdaten-Abzug: Aufbereitung, Ablage und der Abruf im Worker."""

from __future__ import annotations

import pytest

from poe_view import config
from poe_view.api.client import ApiError, AuthError
from poe_view.services import poe2_probe
from poe_view.services.api_worker import ApiWorker, Poe2ProbeJob
from poe_view.services.poe2_probe import Probe, ProbeCall


def _probe(*calls: ProbeCall) -> Probe:
    return Probe(calls=list(calls), fetched_at=1_755_000_000.0)


# --------------------------- character_names ---------------------------- #

def test_character_names_liest_die_namen_aus_der_liste():
    calls = [ProbeCall("leagues", True, {"leagues": [{"id": "Standard"}]}),
             ProbeCall("chars", True, {"characters": [{"name": "A"}, {"name": "B"}]})]
    assert poe2_probe.character_names(calls) == ["A", "B"]


def test_character_names_ohne_treffer_leer():
    assert poe2_probe.character_names([]) == []
    assert poe2_probe.character_names(
        [ProbeCall("chars", False, error="ApiError: HTTP 403")]) == []


def test_character_names_uebergeht_leere_und_kaputte_eintraege():
    """GGG darf liefern, was es will — ein Eintrag ohne Namen oder ein
    String statt eines Objekts soll den Abzug nicht sprengen."""
    calls = [ProbeCall("chars", True,
                       {"characters": [{"name": "A"}, {}, "kaputt", {"name": ""}]})]
    assert poe2_probe.character_names(calls) == ["A"]


def test_character_names_ignoriert_antwort_ohne_characters_liste():
    calls = [ProbeCall("x", True, {"characters": "nicht-liste"}),
             ProbeCall("y", True, {"characters": [{"name": "Echt"}]})]
    assert poe2_probe.character_names(calls) == ["Echt"]


# ---------------------------- build_report ------------------------------ #

def test_report_enthaelt_erfolg_und_fehlschlag():
    text = poe2_probe.build_report(_probe(
        ProbeCall("GET /account/leagues?realm=poe2", True, {"leagues": []}),
        ProbeCall("GET /character?realm=poe2", False,
                  error="ApiError: HTTP 403 for /character?realm=poe2")))
    assert "GET /account/leagues?realm=poe2" in text
    assert '"leagues": []' in text
    assert "FAILED — ApiError: HTTP 403 for /character?realm=poe2" in text


def test_report_warnt_vor_den_namen_im_text():
    """Der Abzug enthält Konto- und Charakternamen und wird
    erfahrungsgemäß weitergereicht — der Hinweis muss drinstehen."""
    text = poe2_probe.build_report(_probe())
    assert "account name" in text
    assert "character names" in text


def test_report_nennt_die_fehlenden_stash_endpunkte():
    """Ohne diese Zeile liest sich ein Abzug ohne Truhenfächer wie ein
    Fehler unseres Programms statt wie eine Grenze der API."""
    text = poe2_probe.build_report(_probe())
    assert "stash endpoints" in text


def test_report_zeigt_zeitpunkt_und_version():
    text = poe2_probe.build_report(_probe())
    assert "Fetched: " in text
    assert "raw PoE2 API probe" in text


def test_report_bricht_nicht_an_nicht_serialisierbaren_daten():
    """``default=str`` statt eines Absturzes: Ein unerwarteter Typ in
    GGGs Antwort soll den Abzug nicht verhindern."""
    text = poe2_probe.build_report(_probe(
        ProbeCall("x", True, {"wert": {1, 2}})))
    assert "wert" in text


# ------------------------------ Ablage ---------------------------------- #

def test_report_path_folgt_dem_gepatchten_app_data_dir(tmp_path, monkeypatch):
    """Der Pfad wird bei jedem Aufruf neu gebildet — sonst schriebe der
    Abzug am Testschutz vorbei in Peters echten Profilordner."""
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path / "woanders")
    assert poe2_probe.report_path().parent == tmp_path / "woanders"


def test_save_report_legt_das_verzeichnis_an(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path / "neu")
    path = poe2_probe.save_report("Inhalt")
    assert path.read_text(encoding="utf-8") == "Inhalt"


def test_save_report_ueberschreibt_den_vorigen_abzug(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path)
    poe2_probe.save_report("alt")
    path = poe2_probe.save_report("neu")
    assert path.read_text(encoding="utf-8") == "neu"


# --------------------------- Abruf im Worker ---------------------------- #

class _FakeClient:
    """Ersetzt den echten Client; zählt mit, was abgefragt wurde."""

    def __init__(self, characters=None, fail=()):
        self._characters = characters if characters is not None else []
        self._fail = fail
        self.calls: list[tuple] = []

    def get_leagues_raw(self, realm=None):
        self.calls.append(("leagues", realm))
        if "leagues" in self._fail:
            raise ApiError(400, "HTTP 400 for /account/leagues?realm=poe2: nope")
        return {"leagues": [{"id": "Standard"}]}

    def get_characters_raw(self, realm=None):
        self.calls.append(("characters", realm))
        if "characters" in self._fail:
            raise ApiError(403, "HTTP 403 for /character?realm=poe2: nope")
        return {"characters": [{"name": n} for n in self._characters]}

    def get_character_raw(self, name, realm=None):
        self.calls.append(("character", name, realm))
        if "character" in self._fail:
            raise AuthError("Not authorized")
        return {"character": {"name": name, "level": 42}}


@pytest.fixture
def worker():
    w = ApiWorker()
    echter_client = w.client  # die Tests hängen einen Fake ein
    yield w
    echter_client.close()
    w._ninja_http.close()


def test_probe_fragt_beide_listen_mit_realm_poe2(worker):
    worker.client = _FakeClient()
    probe = worker._poe2_probe()
    assert worker.client.calls == [("leagues", "poe2"), ("characters", "poe2")]
    assert [c.ok for c in probe.calls] == [True, True]


def test_probe_holt_nur_den_ersten_charakter(worker):
    """Ein Charakter beantwortet die strukturelle Frage genauso wie zehn;
    jeder weitere kostete nur Rate-Limit-Kontingent."""
    worker.client = _FakeClient(characters=["Eins", "Zwei", "Drei"])
    probe = worker._poe2_probe()
    assert ("character", "Eins", "poe2") in worker.client.calls
    assert ("character", "Zwei", "poe2") not in worker.client.calls
    assert len(probe.calls) == 3


def test_probe_haelt_fehlschlaege_fest_statt_abzubrechen(worker):
    """Ein 403 auf die Charakterliste ist das Messergebnis — die Ligen
    davor müssen trotzdem im Abzug stehen."""
    worker.client = _FakeClient(fail=("characters",))
    probe = worker._poe2_probe()
    assert [c.ok for c in probe.calls] == [True, False]
    assert "HTTP 403" in probe.calls[1].error
    assert poe2_probe.character_names(probe.calls) == []


def test_probe_laeuft_weiter_wenn_die_ligen_scheitern(worker):
    worker.client = _FakeClient(characters=["Eins"], fail=("leagues",))
    probe = worker._poe2_probe()
    assert probe.calls[0].ok is False
    assert probe.calls[1].ok is True
    assert len(probe.calls) == 3


def test_probe_reicht_autherror_weiter(worker):
    """Ein totes Token soll wie überall sonst den Login anstoßen statt
    still als Textzeile im Abzug zu verschwinden."""
    worker.client = _FakeClient(characters=["Eins"], fail=("character",))
    with pytest.raises(AuthError):
        worker._poe2_probe()


def test_probe_setzt_einen_zeitstempel(worker):
    worker.client = _FakeClient()
    assert worker._poe2_probe().fetched_at > 0


def test_probe_job_braucht_ein_token(worker):
    """Ohne Token verwirft der Worker den Job, statt einen sicheren 401
    zu kassieren (dieselbe Regel wie für alle Daten-Jobs)."""
    assert worker._skip_unauthenticated(Poe2ProbeJob()) is True


def test_probe_job_wird_im_read_only_modus_verworfen(worker):
    """Der Abzug läuft über das Rate-Limit-Budget des Kontos — eine
    zweite Instanz darf es nicht mitverbrauchen."""
    worker.client.set_token("tok")
    worker.read_only = True
    assert worker._skip_read_only(Poe2ProbeJob()) is True
