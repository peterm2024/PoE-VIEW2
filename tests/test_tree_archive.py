"""Ältere Passiv-Bäume bleiben ansehbar (§4.60.15).

Peter, 2026-11-08, vor Covens of Umbra: "Ich würde gerne die alten Trees
als 'Read-Only' behalten, falls das geht. Dann kann man nachschauen, wie
man mal geskillt hatte."
"""

from __future__ import annotations

import copy
import json
from datetime import datetime

import httpx
import pytest

from poe_view.api.models import Character
from poe_view.services import passive_tree as pt
from poe_view.services import tree_history as th
from tests.test_passive_tree import _ROH, _fenster, _knoten, _real_fetch


def _alt_und_neu():
    alt = copy.deepcopy(_ROH)
    neu = copy.deepcopy(_ROH)
    neu["nodes"]["12"]["name"] = "Iron Heart Reworked"
    neu["nodes"]["11"]["out"].append("60")
    neu["nodes"]["60"] = _knoten("New in Covens", (), isNotable=True, stats=["+1 to Level"])
    return alt, neu


def _commits(*eintraege):
    return [{"commit": {"message": f"{text}\n\nmore", "committer": {"date": datum}}}
            for text, datum in eintraege]


@pytest.fixture
def zwei(monkeypatch):
    """Erst der Allflame-Baum ("3.29.1"), dann der neue ("3.30.0 preview")
    — beide über den echten Download. Gibt (alt_id, neu_id)."""
    monkeypatch.setattr(pt, "fetch", _real_fetch)
    alt, neu = _alt_und_neu()
    stand = {"baum": alt, "commits": _commits(("3.29.1", "2026-07-31T10:00:00Z"))}

    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=stand["commits"])
        return httpx.Response(200, content=json.dumps(stand["baum"]))

    assert pt.fetch(httpx.Client(transport=httpx.MockTransport(handler)))
    alt_id = pt.current_id()
    stand.update(baum=neu, commits=_commits(("3.30.0 preview", "2026-11-10T10:00:00Z"),
                                            ("3.29.1", "2026-07-31T10:00:00Z")))
    assert pt.fetch(httpx.Client(transport=httpx.MockTransport(handler)))
    return alt_id, pt.current_id(), handler


# --- Archiv ----------------------------------------------------------------- #

def test_a_new_tree_moves_the_old_one_to_the_archive(zwei) -> None:
    alt_id, neu_id, handler = zwei
    assert alt_id and neu_id and alt_id != neu_id
    assert pt.archived_ids() == [alt_id]
    assert (pt.tree_label(alt_id), pt.tree_label(neu_id)) == ("3.29.1", "3.30.0 preview")
    assert pt.load(True, alt_id).nodes[12].name == "Iron Heart"
    assert pt.load(True).nodes[12].name == "Iron Heart Reworked"
    assert pt.load(False, neu_id) is pt.load(False)
    assert pt.oldest_id() == alt_id
    # Derselbe Baum noch einmal: nichts Neues im Archiv, der Name bleibt.
    assert pt.fetch(httpx.Client(transport=httpx.MockTransport(handler)))
    assert pt.archived_ids() == [alt_id] and pt.tree_label(neu_id) == "3.30.0 preview"
    assert pt.load(True, "000000000000") is None                  # unbekannt


def test_a_tree_from_before_this_version_gets_an_id_and_its_name(monkeypatch) -> None:
    """Peters Bestand hat ein Manifest ohne Kennung und Namen — der Name
    kommt aus dem Commit, der zum damaligen Download im Export stand."""
    monkeypatch.setattr(pt, "fetch", _real_fetch)
    alt, neu = _alt_und_neu()
    pt.tree_dir().mkdir(parents=True)
    for name in ("data.json", "ruthless.json"):
        (pt.tree_dir() / name).write_text(json.dumps(alt), encoding="utf-8")
    damals = datetime(2026, 10, 5, 3, 0).timestamp()
    (pt.tree_dir() / "manifest.json").write_text(json.dumps({"version": 1, "fetched_at": damals}))
    alt_id = pt.current_id()
    assert alt_id and json.loads((pt.tree_dir() / "manifest.json").read_text())["id"] == alt_id

    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=_commits(("3.30.0 preview", "2026-11-10T10:00:00Z"),
                                                     ("3.29.1", "2026-07-31T10:00:00Z")))
        return httpx.Response(200, content=json.dumps(neu))

    assert pt.fetch(httpx.Client(transport=httpx.MockTransport(handler)))
    assert pt.archived_ids() == [alt_id] and pt.tree_label(alt_id) == "3.29.1"


def test_without_github_the_name_is_the_download_date(monkeypatch) -> None:
    monkeypatch.setattr(pt, "fetch", _real_fetch)
    alt, neu = _alt_und_neu()
    pt.tree_dir().mkdir(parents=True)
    for name in ("data.json", "ruthless.json"):
        (pt.tree_dir() / name).write_text(json.dumps(alt), encoding="utf-8")
    damals = datetime(2026, 10, 5, 3, 0).timestamp()
    (pt.tree_dir() / "manifest.json").write_text(json.dumps({"version": 1, "fetched_at": damals}))
    alt_id = pt.current_id()

    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(403)
        return httpx.Response(200, content=json.dumps(neu))

    assert pt.fetch(httpx.Client(transport=httpx.MockTransport(handler)))
    assert pt.tree_label(alt_id) == "tree of 2026-10-05"


def test_entries_belong_to_their_tree_old_ones_to_the_oldest(zwei) -> None:
    alt_id, neu_id, _ = zwei
    assert pt.entry_tree_id({}) == alt_id                         # vor den Kennungen
    assert pt.entry_tree_id({"tree": neu_id}) == neu_id
    zeichen: dict = {}
    th.record(zeichen, "WitchOfPeter", {"hashes": [10]}, level=2, ruthless=True, tree=neu_id)
    th.save_config(zeichen, "WitchOfPeter", "A", {"hashes": [10]}, level=2, ruthless=True,
                   source="pob", tree=neu_id)
    assert th.current(zeichen, "WitchOfPeter")["tree"] == neu_id
    assert th.history(zeichen, "WitchOfPeter")[0]["tree"] == neu_id
    assert th.configs(zeichen, "WitchOfPeter")["A"]["tree"] == neu_id


def test_unknown_nodes_mean_a_newer_tree() -> None:
    baum = pt.parse_tree(_ROH, ruthless=True)
    assert pt.unknown_nodes(baum, {"hashes": [10, 11], "hashes_ex": [5000]}) == set()
    assert pt.unknown_nodes(baum, {"hashes": [10, 60]}) == {60}


# --- Baum-Fenster ------------------------------------------------------------- #

def _fenster_zwei(qapp, zwei):
    """Verlauf und aktueller Baum ohne Kennung (entstanden vor ihr, also
    auf dem Allflame-Baum); "Covens" auf dem neuen, "Allflame build" ohne
    Kennung."""
    alt_id, neu_id, _ = zwei
    dialog, zeichen, gespeichert = _fenster(qapp, pt.load(True))
    th.save_config(zeichen, "WitchOfPeter", "Covens", {"hashes": [10, 11, 60]}, level=30,
                   ruthless=True, source="pob", tree=neu_id)
    th.save_config(zeichen, "WitchOfPeter", "Allflame build", {"hashes": [10, 11, 12]},
                   level=30, ruthless=True, source="pob")
    dialog.refresh()
    return dialog, zeichen, gespeichert


def test_an_old_entry_is_shown_on_its_own_tree_and_cannot_be_edited(qapp, zwei) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG, HISTORY
    dialog, zeichen, gespeichert = _fenster_zwei(qapp, zwei)
    dialog.refresh((HISTORY, 1))
    assert dialog._tree.nodes[12].name == "Iron Heart"            # der alte Baum
    assert "Read-only: made on the 3.29.1 tree" in dialog.hint.text()
    assert "click: allocate" not in dialog.graph_legend.text()
    assert dialog.list.currentItem().text().endswith(" · 3.29.1")
    dialog.graph.node_clicked.emit(13, False)
    assert dialog._draft is None and dialog._click_hint(13) is None
    assert not dialog.planner_button.isEnabled() and not dialog.act_link.isEnabled()
    # "Set order" klickt auf einem alten Stand nichts in den Plan.
    th.set_leveling(zeichen, "WitchOfPeter", "Covens")
    dialog.order_button.setChecked(True)
    dialog.graph.node_clicked.emit(11, False)
    assert th.leveling(zeichen, "WitchOfPeter")["priority"] == []
    dialog.order_button.setChecked(False)
    th.clear_leveling(zeichen, "WitchOfPeter")
    # Zwei Stände desselben alten Baums vergleichen sich weiter, einer auf
    # dem neuen nicht mit dem alten davor.
    assert dialog._base((HISTORY, 1))[1] == "the tree before"
    th.record(zeichen, "WitchOfPeter", {"hashes": [10, 11, 60]}, level=31, ruthless=True,
              tree=zwei[1])
    dialog.refresh((HISTORY, 2))
    assert dialog._base((HISTORY, 2)) is None
    # Auch eine von Hand gewählte Basis aus dem anderen Baum gilt nicht.
    dialog._compare_key = lambda: (HISTORY, 0)
    assert dialog._base((CONFIG, "Covens")) is None
    assert dialog._base((HISTORY, 1))[1] != "the tree before"           # gleicher Baum: ja
    del dialog._compare_key
    # Eine alte Konfiguration: kein Vergleich mit dem heutigen Baum, kein Plan.
    dialog.refresh((CONFIG, "Allflame build"))
    assert dialog._base((CONFIG, "Allflame build")) is None
    assert "Level towards this" not in [a.text() for a in dialog._context_actions(
        (CONFIG, "Allflame build")) if a is not None]
    dialog._menu_keys = [(CONFIG, "Allflame build")]
    dialog._use_as_plan()
    dialog._menu_keys = None
    assert th.leveling(zeichen, "WitchOfPeter") is None and gespeichert == []
    # Duplizieren behält den alten Baum.
    dialog._ask_name = lambda *a: "Allflame copy"
    dialog._duplicate()
    assert th.configs(zeichen, "WitchOfPeter")["Allflame copy"]["tree"] == zwei[0]
    dialog.close()


def test_entries_of_the_current_tree_stay_editable(qapp, zwei) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT
    dialog, zeichen, _ = _fenster_zwei(qapp, zwei)
    dialog.refresh((CONFIG, "Covens"))
    assert dialog._tree.nodes[12].name == "Iron Heart Reworked"
    assert "Read-only" not in dialog.hint.text()
    assert "click: allocate" in dialog.graph_legend.text()
    assert not dialog.list.currentItem().text().endswith("3.29.1")
    assert dialog._base((CONFIG, "Covens"))[1] == "current tree"
    assert "Level towards this" in [a.text() for a in dialog._context_actions(
        (CONFIG, "Covens")) if a is not None]
    dialog.refresh((CURRENT, None))                               # immer der heutige Baum
    assert dialog._tree.nodes[12].name == "Iron Heart Reworked"
    dialog.graph.node_clicked.emit(13, False)
    assert dialog._draft is not None
    dialog._draft = None
    dialog.close()


def test_a_plan_towards_an_old_configuration_does_not_run(qapp, zwei) -> None:
    from poe_view.ui import leveling_view
    _, zeichen, _ = _fenster_zwei(qapp, zwei)
    th.set_leveling(zeichen, "WitchOfPeter", "Allflame build")
    assert leveling_view.build_plan(zeichen, "WitchOfPeter") is None
    th.set_leveling(zeichen, "WitchOfPeter", "Covens")
    assert leveling_view.build_plan(zeichen, "WitchOfPeter") is not None


def test_the_window_takes_a_new_tree(qapp, zwei) -> None:
    from poe_view.ui.passive_tree_dialog import CURRENT
    alt_id, _, _ = zwei
    dialog, _, _ = _fenster(qapp, pt.load(True, alt_id))
    dialog.refresh((CURRENT, None))
    assert dialog._tree.nodes[12].name == "Iron Heart"
    dialog.set_live_tree(pt.load(True))
    assert dialog._tree.nodes[12].name == "Iron Heart Reworked"
    assert dialog._selected() == (CURRENT, None)
    dialog.close()


# --- Hauptfenster -------------------------------------------------------------- #

def test_unknown_nodes_fetch_the_new_tree_once(qapp, monkeypatch) -> None:
    from poe_view.services.api_worker import FetchPassiveTreeJob
    from poe_view.ui.main_window import MainWindow
    baum = pt.parse_tree(_ROH, ruthless=True)
    monkeypatch.setattr("poe_view.services.passive_tree.load", lambda ruthless, tree_id=None: baum)
    monkeypatch.setattr("poe_view.services.passive_tree.current_id", lambda: "abc123")
    win = MainWindow()
    win._all_characters = [Character.model_validate(
        {"name": "WitchOfPeter", "class": "Juggernaut", "level": 30, "league": "Standard"})]
    baeume: dict = {}
    monkeypatch.setattr(win, "_trees", lambda: baeume)
    monkeypatch.setattr(win, "_save_trees", lambda: None)
    auftraege = []
    monkeypatch.setattr(win.worker, "submit", auftraege.append)
    try:
        win._on_character_tree("WitchOfPeter", {"hashes": [10, 11]}, True)
        assert auftraege == []                                    # alles bekannt
        assert th.current(baeume, "WitchOfPeter")["tree"] == "abc123"
        win._on_character_tree("WitchOfPeter", {"hashes": [10, 11, 60]}, True)
        win._on_character_tree("WitchOfPeter", {"hashes": [10, 11, 60, 61]}, True)
        assert [type(a) for a in auftraege] == [FetchPassiveTreeJob]     # einmal je Sitzung
        # Kommt ein neuer Baum, nimmt ihn ein offenes Baum-Fenster.
        win._on_character_tree_requested(win._all_characters[0])
        neu = []
        monkeypatch.setattr(win._tree_dialog, "set_live_tree", neu.append)
        win._on_passive_tree_updated(False)
        assert neu == []
        win._on_passive_tree_updated(True)
        assert neu == [baum] and "new passive tree" in win._status_msg.text()
    finally:
        from PySide6.QtWidgets import QApplication
        for w in (getattr(win, "_tree_dialog", None), win):
            if w is not None:
                w.close()
                w.deleteLater()
        QApplication.processEvents()
