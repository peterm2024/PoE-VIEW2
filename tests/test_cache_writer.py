"""Tests fuer den Hintergrund-Schreiber des Daten-Caches (Peter,
2026-08-12: "Gibt es eine Moeglichkeit, die kurzzeitigen Freezes beim
Updaten der Faecher zu umgehen? Evtl. in den Hintergrund auslagern" —
ARCHITEKTUR.md §4.37)."""

import threading
import time

from poe_view.api.models import Character, Item
from poe_view.services import data_cache
from poe_view.services.cache_writer import CacheWriter


def _daten(account: str = "PeterM", *item_namen: str) -> data_cache.CachedData:
    data = data_cache.CachedData()
    data.account_name = account
    data.characters = [Character.model_validate({"name": "WitchOfPeter", "league": "Standard"})]
    data.items_by_league = {"Standard": {"tab-1": [
        Item.model_validate({"id": f"item-{n}", "typeLine": n}) for n in item_namen]}}
    return data


def test_a_snapshot_writes_the_same_file_as_the_synchronous_save(tmp_path) -> None:
    """Die Aufteilung in einen billigen und einen teuren Teil darf am
    ERGEBNIS nichts aendern — sonst waere aus einer Beschleunigung ein
    Datenformat-Wechsel geworden."""
    data = _daten("PeterM", "Chaos Orb", "Divine Orb")
    alt = tmp_path / "alt.json"
    neu = tmp_path / "neu.json"

    data_cache.save(data, alt)
    data_cache.Snapshot(data, neu).write()

    assert neu.read_text(encoding="utf-8") == alt.read_text(encoding="utf-8")
    wieder = data_cache.load(neu)
    assert wieder is not None
    assert [i.typeLine for i in wieder.items_by_league["Standard"]["tab-1"]] == [
        "Chaos Orb", "Divine Orb"]


def test_a_snapshot_is_detached_from_later_changes(tmp_path) -> None:
    """Der Kern der Sache: Zwischen dem Aufnehmen des Snapshots und dem
    Schreiben laeuft die Anwendung weiter und tauscht Item-Listen aus.
    Was der Schreiber in der Hand haelt, muss der Stand von damals sein —
    sonst schriebe er einen halb alten, halb neuen Mischzustand."""
    data = _daten("PeterM", "Chaos Orb")
    ziel = tmp_path / "cache.json"
    snapshot = data_cache.Snapshot(data, ziel)

    # Genau die Aenderungen, die im Betrieb vorkommen: eine Item-Liste
    # wird als Ganzes ersetzt, eine Liga kommt dazu, der Kontoname wechselt.
    data.items_by_league["Standard"]["tab-1"] = [
        Item.model_validate({"id": "spaeter", "typeLine": "Mirror of Kalandra"})]
    data.items_by_league["Hardcore"] = {"tab-9": []}
    data.account_name = "JemandAnders"

    snapshot.write()

    wieder = data_cache.load(ziel)
    assert wieder is not None
    assert wieder.account_name == "PeterM"
    assert "Hardcore" not in wieder.items_by_league
    assert [i.typeLine for i in wieder.items_by_league["Standard"]["tab-1"]] == ["Chaos Orb"]


def test_the_writer_does_not_block_the_caller(tmp_path) -> None:
    """Der ganze Zweck: ``request()`` kehrt sofort zurueck. Gemessen an
    Peters echtem Bestand dauerte ein Speichervorgang 1,4 s, und der lief
    bei JEDEM eintreffenden Fach im GUI-Thread."""
    langsam = threading.Event()
    fertig = threading.Event()

    class LangsamerSnapshot:
        path = tmp_path / "egal.json"

        def write(self):
            langsam.wait(5)
            fertig.set()

    writer = CacheWriter()
    t0 = time.monotonic()
    writer.request(LangsamerSnapshot())
    dauer = time.monotonic() - t0

    assert dauer < 0.5, "request() hat auf den Schreibvorgang gewartet"
    langsam.set()
    assert writer.flush() and fertig.is_set()


def test_requests_during_a_write_collapse_into_the_newest(tmp_path) -> None:
    """Zusammenfassen statt takten: Waehrend geschrieben wird, ersetzt
    jede neue Anforderung die wartende. Bei "Load All Tabs" mit mehreren
    hundert Abschnitten faellt der Berg damit von selbst zusammen — und
    zwar auf den JEWEILS AKTUELLSTEN Stand, ein aelterer wuerde ohnehin
    nur ueberschrieben."""
    laeuft = threading.Event()
    weiter = threading.Event()
    geschrieben: list[str] = []

    class Snapshot:
        path = tmp_path / "egal.json"

        def __init__(self, name: str, blockiert: bool = False):
            self.name = name
            self.blockiert = blockiert

        def write(self):
            geschrieben.append(self.name)
            if self.blockiert:
                laeuft.set()
                weiter.wait(5)

    writer = CacheWriter()
    writer.request(Snapshot("erster", blockiert=True))
    assert laeuft.wait(5), "der erste Schreibvorgang kam nicht in Gang"
    for name in ("zweiter", "dritter", "vierter"):
        writer.request(Snapshot(name))
    weiter.set()

    assert writer.flush()
    assert geschrieben == ["erster", "vierter"]


def test_flush_reports_a_timeout_instead_of_claiming_success(tmp_path) -> None:
    """Beim Beenden muss der Aufrufer erfahren, dass der letzte Stand
    NICHT auf der Platte liegt — ein stillschweigendes "fertig" waere
    hier das Schlimmste, denn danach stirbt der Daemon-Thread mit dem
    Prozess."""
    haengt = threading.Event()

    class HaengenderSnapshot:
        path = tmp_path / "egal.json"

        def write(self):
            haengt.wait(5)

    writer = CacheWriter()
    writer.request(HaengenderSnapshot())

    assert writer.flush(timeout_s=0.2) is False

    haengt.set()
    assert writer.flush()


def test_a_failing_write_does_not_kill_the_writer(tmp_path, caplog) -> None:
    """Ein Fehler beim Schreiben darf nicht dazu fuehren, dass ab da
    still gar nichts mehr gespeichert wird, waehrend die Anwendung
    munter weiterlaeuft. ``Snapshot.write`` faengt OSError selbst ab;
    dieser Test sichert die Stufe darueber gegen alles Uebrige — und
    besteht darauf, dass es im Log steht."""
    import logging

    ziel = tmp_path / "cache.json"
    writer = CacheWriter()

    class KaputterSnapshot:
        path = ziel

        def write(self):
            raise RuntimeError("etwas Unerwartetes")

    with caplog.at_level(logging.ERROR, logger="poe_view.services.cache_writer"):
        writer.request(KaputterSnapshot())
        assert writer.flush()

    assert any("fehlgeschlagen" in m for m in caplog.messages)

    writer.request(data_cache.Snapshot(_daten("PeterM", "Chaos Orb"), ziel))
    assert writer.flush()
    assert data_cache.load(ziel) is not None


def test_flush_without_anything_pending_returns_immediately() -> None:
    writer = CacheWriter()
    t0 = time.monotonic()
    assert writer.flush() is True
    assert time.monotonic() - t0 < 0.5
