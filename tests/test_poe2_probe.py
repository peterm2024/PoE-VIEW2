"""PoE2-Rohdaten-Abzug: Aufbereitung, Kontrollvergleich, Ablage und Abruf.

Der Kern dieser Tests ist der Vergleich, nicht der Abruf. Der erste
Abzug (2026-08-15) zeigte PoE1-Daten unter einer PoE2-Ueberschrift, und
nur Peters Blick darauf hat es aufgedeckt — ein Abzug ohne Kontrollen
kann "PoE2 ist leer" nicht von "der Parameter wirkt nicht" trennen.
"""

from __future__ import annotations

import pytest

from poe_view import config
from poe_view.api.client import ApiError, AuthError
from poe_view.services import poe2_probe
from poe_view.services.api_worker import ApiWorker, Poe2ProbeJob
from poe_view.services.poe2_probe import (DETAIL, INVALID, LEAGUES, PLAIN,
                                          POE2, Probe, ProbeCall)


def _call(role: str, data, ok: bool = True) -> ProbeCall:
    return ProbeCall(label=role, ok=ok, data=data, role=role,
                     digest=poe2_probe.digest_of(data) if ok else "")


def _probe(*calls: ProbeCall) -> Probe:
    return Probe(calls=list(calls), fetched_at=1_755_000_000.0)


# ------------------------------ digest_of -------------------------------- #

def test_digest_ignoriert_die_schluesselreihenfolge():
    """Sonst haenge der ganze Vergleich daran, in welcher Reihenfolge GGG
    die Felder serialisiert."""
    assert (poe2_probe.digest_of({"a": 1, "b": 2})
            == poe2_probe.digest_of({"b": 2, "a": 1}))


def test_digest_trennt_verschiedene_antworten():
    assert poe2_probe.digest_of({"a": 1}) != poe2_probe.digest_of({"a": 2})


def test_digest_bricht_nicht_an_nicht_serialisierbaren_daten():
    assert poe2_probe.digest_of({"wert": {1, 2}})


# --------------------------- realm_had_effect ---------------------------- #

def test_gleiche_antwort_heisst_keine_wirkung():
    calls = [_call(PLAIN, {"characters": []}), _call(POE2, {"characters": []})]
    assert poe2_probe.realm_had_effect(calls) is False


def test_andere_antwort_heisst_wirkung():
    calls = [_call(PLAIN, {"characters": []}),
             _call(POE2, {"characters": [{"name": "Neu"}]})]
    assert poe2_probe.realm_had_effect(calls) is True


def test_fehlender_kontrollabruf_gilt_als_wirkung():
    """Im Zweifel den Unterschied zeigen statt ihn wegzuoptimieren."""
    assert poe2_probe.realm_had_effect([_call(POE2, {"x": 1})]) is True


def test_fehlgeschlagener_abruf_gilt_als_wirkung():
    calls = [_call(PLAIN, {"characters": []}),
             ProbeCall("poe2", False, role=POE2, error="ApiError: HTTP 403")]
    assert poe2_probe.realm_had_effect(calls) is True


# ------------------------------- verdict --------------------------------- #

def test_verdict_nennt_den_parameter_wirkungslos():
    """Der gemessene Fall vom 2026-08-15: alle drei Antworten bytegleich."""
    gleich = {"characters": [{"name": "PoE1Held", "realm": "pc"}]}
    text = "\n".join(poe2_probe.verdict(
        [_call(PLAIN, gleich), _call(POE2, gleich), _call(INVALID, gleich)]))
    assert "had no effect" in text
    assert "Path of Exile 1 data" in text
    assert "ignores the parameter" in text


def test_verdict_meldet_eine_echte_wirkung():
    text = "\n".join(poe2_probe.verdict(
        [_call(PLAIN, {"characters": []}),
         _call(POE2, {"characters": [{"name": "EchtPoE2"}]})]))
    assert "changed the answer" in text
    assert "had no effect" not in text


def test_verdict_ohne_kontrolle_bleibt_vorsichtig():
    """Fehlt der erfundene Realm, ist offen, ob GGG ignoriert oder das
    Konto einfach keine PoE2-Daten hat — das muss dastehen."""
    gleich = {"characters": []}
    text = "\n".join(poe2_probe.verdict([_call(PLAIN, gleich), _call(POE2, gleich)]))
    assert "open whether" in text
    # Die sichere Aussage ("GGG lehnt den Wert nicht ab") darf hier NICHT
    # stehen — ohne den erfundenen Realm ist sie nicht belegt.
    assert "not rejecting the" not in text


def test_verdict_zeigt_die_pruefsummen():
    gleich = {"characters": []}
    text = "\n".join(poe2_probe.verdict([_call(PLAIN, gleich), _call(POE2, gleich)]))
    assert poe2_probe.digest_of(gleich)[:16] in text


def test_verdict_bei_fehlschlag_verweist_auf_die_rohdaten():
    calls = [_call(PLAIN, {"x": 1}),
             ProbeCall("poe2", False, role=POE2, error="ApiError: HTTP 403")]
    assert "by hand" in "\n".join(poe2_probe.verdict(calls))


# --------------------------- character_names ----------------------------- #

def test_character_names_liest_nur_die_poe2_antwort():
    """Der Kontrollabruf ohne Realm enthaelt dieselben Felder — wer ihn
    mitliest, holt am Ende einen PoE1-Charakter im Detail."""
    calls = [_call(PLAIN, {"characters": [{"name": "AusKontrolle"}]}),
             _call(POE2, {"characters": [{"name": "AusPoE2"}]})]
    assert poe2_probe.character_names(calls) == ["AusPoE2"]


def test_character_names_ohne_treffer_leer():
    assert poe2_probe.character_names([]) == []
    assert poe2_probe.character_names(
        [ProbeCall("chars", False, role=POE2, error="ApiError")]) == []


def test_character_names_uebergeht_leere_und_kaputte_eintraege():
    calls = [_call(POE2, {"characters": [{"name": "A"}, {}, "kaputt", {"name": ""}]})]
    assert poe2_probe.character_names(calls) == ["A"]


def test_character_names_ignoriert_antwort_ohne_liste():
    assert poe2_probe.character_names([_call(POE2, {"characters": "nix"})]) == []


# ---------------------------- build_report ------------------------------- #

def test_report_stellt_das_urteil_vor_die_rohdaten():
    gleich = {"characters": []}
    text = poe2_probe.build_report(_probe(
        _call(PLAIN, gleich), _call(POE2, gleich), _call(INVALID, gleich)))
    assert text.index("VERDICT") < text.index("GET" if "GET" in text else "plain")
    assert "had no effect" in text


def test_report_enthaelt_erfolg_und_fehlschlag():
    text = poe2_probe.build_report(_probe(
        ProbeCall("GET /account/leagues?realm=poe2", True, {"leagues": []},
                  role=LEAGUES, digest="abc"),
        ProbeCall("GET /character?realm=poe2", False, role=POE2,
                  error="ApiError: HTTP 403 for /character?realm=poe2")))
    assert '"leagues": []' in text
    assert "FAILED — ApiError: HTTP 403 for /character?realm=poe2" in text


def test_report_warnt_vor_den_namen_im_text():
    text = poe2_probe.build_report(_probe())
    assert "account name" in text
    assert "character names" in text


def test_report_nennt_die_fehlenden_stash_endpunkte():
    """Ohne diese Zeile liest sich ein Abzug ohne Faecher wie ein Fehler
    des Programms statt wie eine Grenze der API."""
    assert "stash endpoints" in poe2_probe.build_report(_probe())


def test_report_zeigt_zeitpunkt_und_version():
    text = poe2_probe.build_report(_probe())
    assert "Fetched: " in text
    assert "raw PoE2 API probe" in text


# ------------------------------- Ablage ---------------------------------- #

def test_report_path_folgt_dem_gepatchten_app_data_dir(tmp_path, monkeypatch):
    """Der Pfad wird bei jedem Aufruf neu gebildet — sonst schriebe der
    Abzug am Testschutz vorbei in Peters echten Profilordner."""
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path / "woanders")
    assert poe2_probe.report_path().parent == tmp_path / "woanders"


def test_save_report_legt_das_verzeichnis_an(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path / "neu")
    assert poe2_probe.save_report("Inhalt").read_text(encoding="utf-8") == "Inhalt"


def test_save_report_ueberschreibt_den_vorigen_abzug(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DATA_DIR", tmp_path)
    poe2_probe.save_report("alt")
    assert poe2_probe.save_report("neu").read_text(encoding="utf-8") == "neu"


# --------------------------- Abruf im Worker ----------------------------- #

class _FakeClient:
    """Ersetzt den echten Client; zaehlt mit, was abgefragt wurde.

    ``poe2_characters`` = None bedeutet: GGG antwortet auf jeden Realm
    gleich (der real gemessene Fall)."""

    def __init__(self, poe2_characters=None, fail=()):
        self._poe2 = poe2_characters
        self._fail = fail
        self.calls: list[tuple] = []

    def get_leagues_raw(self, realm=None):
        self.calls.append(("leagues", realm))
        if "leagues" in self._fail:
            raise ApiError(400, "HTTP 400 for /account/leagues?realm=poe2")
        return {"leagues": [{"id": "Standard", "realm": "pc"}]}

    def get_characters_raw(self, realm=None):
        self.calls.append(("characters", realm))
        if "characters" in self._fail:
            raise ApiError(403, "HTTP 403 for /character?realm=poe2")
        if realm == poe2_probe.REALM and self._poe2 is not None:
            return {"characters": [{"name": n} for n in self._poe2]}
        return {"characters": [{"name": "PoE1Held", "realm": "pc"}]}

    def get_character_raw(self, name, realm=None):
        self.calls.append(("character", name, realm))
        if "character" in self._fail:
            raise AuthError("Not authorized")
        return {"character": {"name": name, "level": 42}}


@pytest.fixture
def worker():
    w = ApiWorker()
    echter_client = w.client  # die Tests haengen einen Fake ein
    yield w
    echter_client.close()
    w._ninja_http.close()


def test_probe_fragt_mit_kontrollen_ab(worker):
    """Ohne Realm, mit poe2, mit einem erfundenen Wert — in dieser
    Reihenfolge, plus die Ligen."""
    worker.client = _FakeClient()
    worker._poe2_probe()
    assert worker.client.calls == [
        ("characters", None),
        ("characters", "poe2"),
        ("characters", poe2_probe.INVALID_REALM),
        ("leagues", "poe2"),
    ]


def test_probe_erkennt_den_wirkungslosen_parameter(worker):
    """Der real gemessene Fall (2026-08-15): GGG antwortet auf jeden
    Realm bytegleich."""
    worker.client = _FakeClient()
    probe = worker._poe2_probe()
    assert poe2_probe.realm_had_effect(probe.calls) is False
    assert "had no effect" in poe2_probe.build_report(probe)


def test_probe_holt_kein_detail_wenn_der_realm_nichts_aendert(worker):
    """Es waere ein PoE1-Charakter im PoE2-Abzug — ein Abruf fuer eine
    Antwort, die in die Irre fuehrt."""
    worker.client = _FakeClient()
    probe = worker._poe2_probe()
    assert not any(c[0] == "character" for c in worker.client.calls)
    assert not any(c.role == DETAIL for c in probe.calls)


def test_probe_holt_das_detail_wenn_der_realm_wirkt(worker):
    """Faengt GGG irgendwann an, den Parameter auszuwerten, ist genau das
    der interessante Teil — und er muss dann von selbst kommen."""
    worker.client = _FakeClient(poe2_characters=["EchtPoE2", "Zweiter"])
    probe = worker._poe2_probe()
    assert ("character", "EchtPoE2", "poe2") in worker.client.calls
    assert ("character", "Zweiter", "poe2") not in worker.client.calls
    assert any(c.role == DETAIL for c in probe.calls)


def test_probe_haelt_fehlschlaege_fest_statt_abzubrechen(worker):
    worker.client = _FakeClient(fail=("characters",))
    probe = worker._poe2_probe()
    assert [c.ok for c in probe.calls] == [False, False, False, True]
    assert "HTTP 403" in probe.calls[1].error


def test_probe_laeuft_weiter_wenn_die_ligen_scheitern(worker):
    worker.client = _FakeClient(fail=("leagues",))
    probe = worker._poe2_probe()
    assert [c.ok for c in probe.calls] == [True, True, True, False]


def test_probe_reicht_autherror_weiter(worker):
    """Ein totes Token soll wie ueberall sonst den Login anstossen statt
    still als Textzeile im Abzug zu verschwinden."""
    worker.client = _FakeClient(poe2_characters=["Eins"], fail=("character",))
    with pytest.raises(AuthError):
        worker._poe2_probe()


def test_probe_legt_zu_jedem_erfolg_eine_pruefsumme_ab(worker):
    worker.client = _FakeClient()
    assert all(c.digest for c in worker._poe2_probe().calls)


def test_probe_setzt_einen_zeitstempel(worker):
    worker.client = _FakeClient()
    assert worker._poe2_probe().fetched_at > 0


def test_probe_job_braucht_ein_token(worker):
    """Ohne Token verwirft der Worker den Job, statt einen sicheren 401
    zu kassieren (dieselbe Regel wie fuer alle Daten-Jobs)."""
    assert worker._skip_unauthenticated(Poe2ProbeJob()) is True


def test_probe_job_wird_im_read_only_modus_verworfen(worker):
    """Der Abzug laeuft ueber das Rate-Limit-Budget des Kontos — eine
    zweite Instanz darf es nicht mitverbrauchen."""
    worker.client.set_token("tok")
    worker.read_only = True
    assert worker._skip_read_only(Poe2ProbeJob()) is True


def test_report_druckt_bytegleiche_antworten_nur_einmal():
    """Der gemessene Fall liefert dreimal dieselbe 50-Charakter-Liste.
    Dreimal abgedruckt verdeckt sie das Wenige, was sich unterscheidet."""
    gleich = {"characters": [{"name": "PoE1Held"}]}
    text = poe2_probe.build_report(_probe(
        ProbeCall("GET /character", True, gleich, role=PLAIN,
                  digest=poe2_probe.digest_of(gleich)),
        ProbeCall("GET /character?realm=poe2", True, gleich, role=POE2,
                  digest=poe2_probe.digest_of(gleich))))

    assert text.count('"PoE1Held"') == 1
    assert 'Byte-identical to "GET /character"' in text


def test_report_druckt_unterschiedliche_antworten_beide_aus():
    a = {"characters": [{"name": "Eins"}]}
    b = {"characters": [{"name": "Zwei"}]}
    text = poe2_probe.build_report(_probe(_call(PLAIN, a), _call(POE2, b)))

    assert '"Eins"' in text and '"Zwei"' in text
    assert "Byte-identical" not in text


def test_verdict_haelt_die_pruefsummen_in_einer_spalte():
    """Der erfundene Realm ist laenger als "poe2" — ohne feste Breite
    verrutscht die Spalte genau dort, wo man vergleichen soll."""
    gleich = {"characters": []}
    zeilen = [z for z in poe2_probe.verdict(
        [_call(PLAIN, gleich), _call(POE2, gleich), _call(INVALID, gleich)])
        if "sha256" in z]

    assert len(zeilen) == 3
    assert len({z.index("sha256") for z in zeilen}) == 1
