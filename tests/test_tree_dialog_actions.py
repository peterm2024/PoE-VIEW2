"""Rechtsklick-Menü und Tastenkürzel im Baum-Fenster (§4.60.10)."""

from __future__ import annotations

import base64
import zlib

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from poe_view.services import passive_tree as pt
from poe_view.services import tree_history as th
from tests.test_passive_tree import _ROH, _eintraege, _fenster


@pytest.fixture
def baum() -> pt.Tree:
    return pt.parse_tree(_ROH, ruthless=True)


@pytest.fixture(autouse=True)
def keine_offenen_meldungen(monkeypatch) -> None:
    """Offscreen wartete eine echte Meldung ewig (FALLSTRICKE #99)."""
    from poe_view.ui import passive_tree_dialog as modul

    def unerwartet(*a, **k):
        raise AssertionError(f"unerwartete Meldung: {a[1:3]}")
    for art in ("warning", "question", "information", "critical"):
        monkeypatch.setattr(modul.QMessageBox, art, staticmethod(unerwartet))
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(unerwartet))
    # Ein echtes Menü wartet offscreen genauso (ein echter Rechtsklick
    # öffnet es — so hing der Lauf beim ersten Versuch).
    monkeypatch.setattr(modul.PassiveTreeDialog, "_exec_menu",
                        lambda self, m, *a: unerwartet(None, "QMenu", m))


def _offen(qapp, baum):
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    dialog.show()
    dialog.activateWindow()
    qapp.processEvents()
    return dialog, zeichen, gespeichert


def _texte(aktionen) -> list[str]:
    return ["—" if a is None else a.text() for a in aktionen]


def test_the_shortcuts_and_where_they_apply(qapp, baum) -> None:
    """Fenster-weit nur, was nie mit einem Feld oder dem Bild kollidiert;
    Entf, F2, Strg+C, Strg+V nur in der Liste."""
    dialog, _z, _g = _fenster(qapp, baum)
    erwartet = {"act_save": ("Ctrl+S", False), "act_save_as": ("Ctrl+Shift+S", False),
                "act_undo": ("Ctrl+Z", False), "act_import": ("Ctrl+I", False),
                "act_paste": ("Ctrl+V", True), "act_rename": ("F2", True),
                "act_delete": ("Del", True), "act_duplicate": ("Ctrl+D", False),
                "act_planner": ("Ctrl+O", False), "act_link": ("Ctrl+L", False),
                "act_text": ("Ctrl+C", True), "act_find": ("Ctrl+F", False)}
    for name, (kuerzel, nur_liste) in erwartet.items():
        a = getattr(dialog, name)
        assert a.shortcut().toString() == kuerzel, name
        assert (a.shortcutContext() == Qt.ShortcutContext.WidgetShortcut) == nur_liste, name
        assert (a in dialog.list.actions()) == nur_liste, name
    # Die Knöpfe nennen ihr Kürzel.
    assert dialog.rename_button.toolTip() == "F2"
    assert dialog.link_button.toolTip() == "Ctrl+L"
    dialog.close()


def test_the_menu_fits_the_entry(qapp, baum) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT, DRAFT, HISTORY
    dialog, zeichen, _ = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Fire", {"hashes": [10, 11, 14, 15]}, level=30,
                   ruthless=True, source="link")
    dialog.refresh((CONFIG, "Fire"))
    teile = ["—", "Open in planner", "Copy link", "Copy as text", "—", "Import…"]
    assert _texte(dialog._context_actions((CONFIG, "Fire"))) == [
        "Show tree", "Rename…", "Duplicate…", "Move to group…", "Use as leveling plan",
        "Delete"] + teile
    # Bei einem anderen als dem gezeigten Eintrag: "Compare with this" (§4.60.11).
    assert _texte(dialog._context_actions((CURRENT, None))) == [
        "Show tree", "Save as configuration…", "Compare with this"] + teile
    assert _texte(dialog._context_actions((HISTORY, 0))) == [
        "Show tree", "Save as configuration…", "Compare with this"] + teile
    assert _texte(dialog._context_actions(None)) == ["Import…"]
    dialog.graph.node_clicked.emit(13, False)                     # Entwurf aus "Fire"
    assert _texte(dialog._context_actions((DRAFT, None))) == [
        "Save to “Fire”", "Save as…", "Undo", "Discard changes"] + teile
    dialog._draft = None
    dialog.close()


def test_the_list_shortcuts_fire_only_in_the_list(qapp, baum, monkeypatch) -> None:
    """Echte Tastendrücke: F2 und Entf in der Liste — im Suchfeld löscht
    Entf Text, keine Konfiguration."""
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, _ = _offen(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Fire", {"hashes": [10, 11]}, level=30,
                   ruthless=True, source="link")
    dialog.refresh((CONFIG, "Fire"))
    monkeypatch.setattr(dialog, "_ask_name", lambda *a: "Hot")
    dialog.list.setFocus()
    QTest.keyClick(dialog.list, Qt.Key.Key_F2)
    assert set(th.configs(zeichen, "WitchOfPeter")) == {"Hot"}
    from poe_view.ui import passive_tree_dialog as modul
    gefragt = []
    monkeypatch.setattr(modul.QMessageBox, "question", staticmethod(
        lambda *a, **k: gefragt.append(a[2]) or modul.QMessageBox.StandardButton.Yes))
    dialog.tabs.setCurrentIndex(3)
    dialog.graph_search.setText("abc")
    dialog.graph_search.setFocus()
    dialog.graph_search.setCursorPosition(0)
    QTest.keyClick(dialog.graph_search, Qt.Key.Key_Delete)
    assert dialog.graph_search.text() == "bc" and gefragt == []    # Text, nicht Konfiguration
    dialog.list.setFocus()
    QTest.keyClick(dialog.list, Qt.Key.Key_Delete)
    assert gefragt == ["Delete “Hot”?"] and th.configs(zeichen, "WitchOfPeter") == {}
    dialog.close()


def test_ctrl_c_copies_the_entry_in_the_list_and_the_node_in_the_tree(qapp, baum) -> None:
    dialog, _z, _g = _offen(qapp, baum)
    dialog.list.setFocus()
    QTest.keyClick(dialog.list, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == dialog.markdown_for(dialog._selected())
    dialog.tabs.setCurrentIndex(3)
    dialog.graph.setFocus()
    dialog.graph.hovered = 12
    QTest.keyClick(dialog.graph, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == "Iron Heart (ID 12)"
    dialog.close()


def test_window_shortcuts_save_undo_and_find(qapp, baum, monkeypatch) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, _ = _offen(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Fire", {"hashes": [10, 11]}, level=30,
                   ruthless=True, source="link")
    dialog.refresh((CONFIG, "Fire"))
    dialog.graph.node_clicked.emit(12, False)
    dialog.graph.node_clicked.emit(13, False)
    assert dialog.act_undo.isEnabled()
    QTest.keyClick(dialog.list, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert pt.allocated(dialog._draft) == {10, 11, 12}
    # Strg+S: der Entwurf aus "Fire" geht ohne Frage nach "Fire" zurück.
    QTest.keyClick(dialog.list, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert dialog._draft is None
    assert pt.allocated(th.configs(zeichen, "WitchOfPeter")["Fire"]["passives"]) == {10, 11, 12}
    assert not dialog.act_undo.isEnabled()
    # Strg+F: ins Suchfeld über dem Bild; im Reiter "Within reach" in dessen Filter.
    QTest.keyClick(dialog.list, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert dialog.tabs.currentIndex() == 3 and dialog.graph_search.hasFocus()
    dialog.tabs.setCurrentIndex(2)
    QTest.keyClick(dialog.list, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert dialog.reach_filter.hasFocus()
    # Strg+1: Respec ist bei "Fire" sichtbar; Strg+2 Overview.
    QTest.keyClick(dialog.list, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert dialog.tabs.currentIndex() == 1
    dialog.close()


def test_duplicate_a_configuration_or_a_history_entry(qapp, baum, monkeypatch) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG, HISTORY
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Fire", {"hashes": [10, 11, 14]}, level=30,
                   ruthless=True, source="link")
    dialog.refresh((CONFIG, "Fire"))
    vorschlaege = []
    monkeypatch.setattr(dialog, "_ask_name", lambda titel, v="": vorschlaege.append(v) or v)
    dialog.act_duplicate.trigger()
    dialog.refresh((HISTORY, 0))
    dialog.act_duplicate.trigger()
    assert vorschlaege == ["Fire (copy)", "Level 29 tree"]
    konfigs = th.configs(zeichen, "WitchOfPeter")
    assert pt.allocated(konfigs["Fire (copy)"]["passives"]) == {10, 11, 14}
    assert pt.allocated(konfigs["Level 29 tree"]["passives"]) == {10, 11}
    assert konfigs["Level 29 tree"]["source"] == "copy" and konfigs["Level 29 tree"]["level"] == 29
    assert dialog._selected() == (CONFIG, "Level 29 tree") and gespeichert == [1, 1]
    dialog.close()


def test_double_click_or_enter_shows_the_tree(qapp, baum) -> None:
    dialog, _z, _g = _fenster(qapp, baum)
    dialog.tabs.setCurrentIndex(1)
    dialog.list.itemActivated.emit(dialog.list.currentItem())
    assert dialog.tabs.currentIndex() == 3
    dialog.close()


def _pob(baum, *titel_und_knoten) -> str:
    specs = "".join(f'<Spec title="{t}"><URL>{pt.encode_url(baum, {"hashes": k}, "Juggernaut")}'
                    f"</URL></Spec>" for t, k in titel_und_knoten)
    xml = f"<PathOfBuilding><Tree activeSpec='1'>{specs}</Tree></PathOfBuilding>"
    return base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()


def test_the_clipboard_fills_the_import(qapp, baum, monkeypatch) -> None:
    """Was nach Baum, Build oder pobb.in aussieht, steht schon im Feld;
    Strg+V in der Liste importiert es ohne Nachfrage nach dem Text."""
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, _ = _offen(qapp, baum)
    QGuiApplication.clipboard().setText("just some words")
    assert dialog._clipboard_import_text() == ""
    for text in ("https://pobb.in/abc", "https://www.pathofexile.com/passive-skill-tree/AAAABgEA",
                 _pob(baum, ("A", [10]))):
        QGuiApplication.clipboard().setText(text)
        assert dialog._clipboard_import_text() == text
    vorschlaege = []
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(
        lambda *a, **k: vorschlaege.append(k.get("text")) or ("", False)))
    QGuiApplication.clipboard().setText("https://pobb.in/abc")
    dialog.act_import.trigger()
    assert vorschlaege == ["https://pobb.in/abc"]
    # Strg+V in der Liste: Build mit einem Baum → nur noch der Name.
    QGuiApplication.clipboard().setText(_pob(baum, ("Endgame", [10, 11, 12])))
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(
        lambda *a, **k: vorschlaege.append(k.get("text")) or ("Endgame", True)))
    dialog.list.setFocus()
    QTest.keyClick(dialog.list, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert vorschlaege[-1] == "Endgame"                           # nur die Namensfrage
    assert "Endgame" in th.configs(zeichen, "WitchOfPeter")
    assert "Endgame" in _eintraege(dialog)
    dialog.close()


def _drei(qapp, baum):
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, gespeichert = _offen(qapp, baum)
    for name, knoten in (("A", [10]), ("B", [10, 11]), ("C", [10, 11, 12])):
        th.save_config(zeichen, "WitchOfPeter", name, {"hashes": knoten}, level=30,
                       ruthless=True, source="link")
    dialog.refresh((CONFIG, "A"))
    return dialog, zeichen, gespeichert


def _item(dialog, key):
    from PySide6.QtCore import Qt as _Qt
    return next(dialog.list.item(i) for i in range(dialog.list.count())
                if dialog.list.item(i).data(_Qt.ItemDataRole.UserRole) == key)


def _menue_waehlt(monkeypatch, aktion_name, dialog, gesehen=None):
    """Das Menü "öffnen": die genannte Aktion auslösen, als hätte man sie
    im offenen Menü angeklickt."""
    def ausfuehren(menue, *a):
        if gesehen is not None:
            gesehen.append([x.text() for x in menue.actions() if not x.isSeparator()])
        getattr(dialog, aktion_name).trigger()
    monkeypatch.setattr(dialog, "_exec_menu", ausfuehren)


def test_a_right_click_does_not_change_the_selection(qapp, baum, monkeypatch) -> None:
    """Peter, 2026-10-08: "Wenn ich auf eine Config rechtsklicke wird diese
    automatisch ausgewählt - Bug?" — jetzt nicht mehr: das Bild bleibt."""
    from poe_view.ui.passive_tree_dialog import CONFIG
    from poe_view.ui import passive_tree_dialog as modul
    dialog, _z, _g = _drei(qapp, baum)
    punkt = dialog.list.visualItemRect(_item(dialog, (CONFIG, "C"))).center()
    geoeffnet = []
    monkeypatch.setattr(dialog, "_exec_menu", lambda m, *a: geoeffnet.append(
        [x.text() for x in m.actions() if not x.isSeparator()][:2]))
    QTest.mouseClick(dialog.list.viewport(), Qt.MouseButton.RightButton, pos=punkt)
    # Das Kontextmenü-Ereignis kommt offscreen nicht von selbst mit.
    from PySide6.QtGui import QContextMenuEvent
    QApplication.sendEvent(dialog.list.viewport(),
                           QContextMenuEvent(QContextMenuEvent.Reason.Mouse, punkt,
                                             dialog.list.viewport().mapToGlobal(punkt)))
    assert geoeffnet == [["Show tree", "Rename…"]]               # das Menü kam
    assert dialog._selected() == (CONFIG, "A") and dialog._selected_keys() == [(CONFIG, "A")]
    QTest.mouseClick(dialog.list.viewport(), Qt.MouseButton.LeftButton, pos=punkt)
    assert dialog._selected() == (CONFIG, "C")                   # links wählt weiter aus
    dialog.close()


def test_the_menu_acts_on_the_entry_under_the_mouse(qapp, baum, monkeypatch) -> None:
    """Umbenennen, Link kopieren, löschen von "C", während "A" gezeigt wird —
    die Auswahl bleibt bei "A"."""
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, _ = _drei(qapp, baum)
    punkt = dialog.list.visualItemRect(_item(dialog, (CONFIG, "C"))).center()
    gesehen = []
    monkeypatch.setattr(dialog, "_ask_name", lambda *a: "C2")
    _menue_waehlt(monkeypatch, "act_rename", dialog, gesehen)
    dialog._list_menu(punkt)
    assert gesehen[0][:6] == ["Show tree", "Rename…", "Duplicate…", "Move to group…",
                              "Use as leveling plan", "Delete"]
    assert set(th.configs(zeichen, "WitchOfPeter")) == {"A", "B", "C2"}
    assert dialog._selected() == (CONFIG, "A")
    punkt = dialog.list.visualItemRect(_item(dialog, (CONFIG, "C2"))).center()
    _menue_waehlt(monkeypatch, "act_link", dialog)
    dialog._list_menu(punkt)
    assert QGuiApplication.clipboard().text() == dialog.link_for((CONFIG, "C2"))
    assert dialog.link_for((CONFIG, "C2")) != dialog.link_for((CONFIG, "A"))
    # Während das Menü offen ist, ist "C2" getönt, danach nicht mehr.
    toene = []
    monkeypatch.setattr(dialog, "_exec_menu", lambda m, *a: toene.append(
        _item(dialog, (CONFIG, "C2")).background().style()))
    dialog._list_menu(punkt)
    assert toene == [Qt.BrushStyle.SolidPattern]
    assert _item(dialog, (CONFIG, "C2")).background().style() == Qt.BrushStyle.NoBrush
    # "Show tree" wählt aus und zeigt das Bild.
    dialog.tabs.setCurrentIndex(1)
    _menue_waehlt(monkeypatch, "act_show", dialog)
    dialog._list_menu(punkt)
    assert dialog._selected() == (CONFIG, "C2") and dialog.tabs.currentIndex() == 3
    # Ohne Menü wirken die Kürzel wieder auf die Auswahl.
    assert dialog._menu_keys is None and dialog._target() == (CONFIG, "C2")
    dialog.close()


def test_several_configurations_are_deleted_at_once(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT
    dialog, zeichen, gespeichert = _drei(qapp, baum)
    _item(dialog, (CONFIG, "B")).setSelected(True)
    _item(dialog, (CURRENT, None)).setSelected(True)             # bleibt, wird nicht gelöscht
    assert set(dialog._selected_keys()) == {(CONFIG, "A"), (CONFIG, "B"), (CURRENT, None)}
    fragen = []
    monkeypatch.setattr(modul.QMessageBox, "question", staticmethod(
        lambda *a, **k: fragen.append((a[1], a[2])) or modul.QMessageBox.StandardButton.Yes))
    # Rechtsklick auf einen Eintrag der Auswahl: gilt für alle gewählten.
    punkt = dialog.list.visualItemRect(_item(dialog, (CONFIG, "B"))).center()
    _menue_waehlt(monkeypatch, "act_delete", dialog)
    dialog._list_menu(punkt)
    assert fragen == [("Delete configurations", "Delete these 2 configurations?\n\nB\nA")]
    assert set(th.configs(zeichen, "WitchOfPeter")) == {"C"}
    assert dialog._selected() == (CURRENT, None) and gespeichert == [1]
    # Rechtsklick außerhalb der Auswahl: nur dieser eine.
    th.save_config(zeichen, "WitchOfPeter", "D", {"hashes": [10]}, level=30, ruthless=True,
                   source="link")
    dialog.refresh((CONFIG, "C"))
    _item(dialog, (CURRENT, None)).setSelected(True)
    fragen.clear()
    dialog._list_menu(dialog.list.visualItemRect(_item(dialog, (CONFIG, "D"))).center())
    assert fragen == [("Delete configuration", "Delete “D”?")]
    assert set(th.configs(zeichen, "WitchOfPeter")) == {"C"} and dialog._selected() == (CONFIG, "C")
    dialog.close()


def test_compare_two_configurations(qapp, baum, monkeypatch) -> None:
    """Idee 2 (Peter, 2026-10-08: "so machen wir das"): "Lvl 61-80" gegen
    "Lvl 41-60" statt gegen den aktuellen Baum — Respec, Gold, Bild, Punkte."""
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT, HISTORY
    dialog, zeichen, _ = _fenster(qapp, baum)
    # Wogegen das Bild vergleicht (der Testbaum hat keine Lage, also keine
    # gezeichneten Knoten — deshalb ein Spion statt der Zustände).
    verglichen = []
    original = dialog.graph.show_tree
    monkeypatch.setattr(dialog.graph, "show_tree", lambda p, k, compare_to=None, **kw: (
        verglichen.append(pt.allocated(compare_to) if compare_to is not None else None),
        original(p, k, compare_to=compare_to, **kw)))
    th.save_config(zeichen, "WitchOfPeter", "Lvl 41-60", {"hashes": [10, 11, 12, 13]},
                   level=30, ruthless=True, source="pob")
    th.save_config(zeichen, "WitchOfPeter", "Lvl 61-80", {"hashes": [10, 11, 12, 14, 15]},
                   level=30, ruthless=True, source="pob")
    dialog.refresh((CONFIG, "Lvl 61-80"))
    box = dialog.compare_box
    assert [box.itemText(i) for i in range(box.count())][:4] == [
        "Automatic (current tree / the tree before)", "Current tree", "Lvl 41-60", "Lvl 61-80"]
    assert dialog._compare_keys[4:] == [(HISTORY, 1), (HISTORY, 0)]
    # Automatisch: gegen den aktuellen Baum (10, 11, 12).
    assert "Respec: current tree → Lvl 61-80" in dialog.respec_text.toPlainText()
    # Gegen "Lvl 41-60": 13 fällt weg, 14 und 15 kommen dazu.
    box.setCurrentIndex(dialog._compare_index((CONFIG, "Lvl 41-60")))
    respec = dialog.respec_text.toPlainText()
    assert "Respec: Lvl 41-60 → Lvl 61-80" in respec
    assert "1 point to refund in the main tree · about" in respec and "at level 30" in respec
    assert "Refund (1)" in respec and "Allocate (2)" in respec
    assert verglichen[-1] == {10, 11, 12, 13} and dialog.graph.comparing
    assert dialog.graph_points.text().startswith("Points used: 5, Lvl 41-60 4 · max")
    # Der Vergleichs-Eintrag selbst: dann automatisch (gegen den aktuellen Baum).
    dialog.refresh((CONFIG, "Lvl 41-60"))
    assert "Respec: current tree → Lvl 41-60" in dialog.respec_text.toPlainText()
    assert verglichen[-1] == {10, 11, 12}
    # Auch der aktuelle Baum lässt sich gegen eine Konfiguration zeigen.
    dialog.refresh((CURRENT, None))
    assert "Respec: Lvl 41-60 → current tree" in dialog.respec_text.toPlainText()
    assert dialog.tabs.isTabVisible(0)
    # Gibt es den Vergleichs-Eintrag nicht mehr, gilt wieder "Automatic".
    th.delete_config(zeichen, "WitchOfPeter", "Lvl 41-60")
    dialog.refresh((CONFIG, "Lvl 61-80"))
    assert dialog._compare_key() is None and box.currentIndex() == 0
    assert "Respec: current tree → Lvl 61-80" in dialog.respec_text.toPlainText()
    dialog.close()


def test_history_compares_with_the_tree_before_or_the_chosen_one(qapp, baum) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG, HISTORY
    dialog, zeichen, _ = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Far", {"hashes": [10, 11, 12, 14, 15]},
                   level=30, ruthless=True, source="link")
    dialog.refresh((HISTORY, 1))
    assert "Changes from the tree before" in dialog.respec_text.toPlainText()
    assert "gold" not in dialog.respec_text.toPlainText()          # schon geschehen
    assert ", " not in dialog.graph_points.text().split(" · ")[0]  # kein "the tree before 2"
    dialog.compare_box.setCurrentIndex(dialog._compare_index((CONFIG, "Far")))
    assert "Respec: Far → tree of 2026-10-04 19:00" in dialog.respec_text.toPlainText()
    assert dialog.graph_points.text().startswith("Points used: 3, Far 5")
    dialog.close()


def test_compare_with_this_from_the_menu(qapp, baum, monkeypatch) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, _ = _drei(qapp, baum)
    punkt = dialog.list.visualItemRect(_item(dialog, (CONFIG, "C"))).center()
    gesehen = []
    _menue_waehlt(monkeypatch, "act_compare", dialog, gesehen)
    dialog._list_menu(punkt)
    assert "Compare with this" in gesehen[0]
    assert dialog._compare_key() == (CONFIG, "C") and dialog._selected() == (CONFIG, "A")
    assert "Respec: C → A" in dialog.respec_text.toPlainText()
    # Beim gezeigten Eintrag selbst steht es nicht im Menü.
    assert "Compare with this" not in _texte(dialog._context_actions((CONFIG, "A")))
    dialog.close()


def test_configurations_are_sorted_by_their_numbers() -> None:
    """Pohx' Bäume standen alphabetisch durcheinander ("Lvl 100" vor
    "Lvl 31-40"); jetzt nach Zahlen, Groß/klein egal."""
    from poe_view.ui.passive_tree_dialog import config_order
    namen = ["Lvl 100 Cogwork Ring {10}", "Lvl 31-40 {2}", "lvl 01-30 {1}", "Boss",
             "Lvl 95+ Small Cluster {8}", "Lvl 100 25% Effect {9}", "Lvl 90 Block {6}", "boss 2"]
    assert sorted(namen, key=config_order) == [
        "Boss", "boss 2", "lvl 01-30 {1}", "Lvl 31-40 {2}", "Lvl 90 Block {6}",
        "Lvl 95+ Small Cluster {8}", "Lvl 100 25% Effect {9}", "Lvl 100 Cogwork Ring {10}"]


def test_respec_lines_without_stats_or_kind_read_cleanly() -> None:
    """Nativ gesehen: "Basic Jewel Socket (jewel socket) — —" und
    "(ascendancy )"."""
    from poe_view.ui import tree_report
    roh = {"classes": [{"name": "Marauder", "ascendancies": [{"name": "Juggernaut"}]}],
           "nodes": {
               "1": {"name": "MARAUDER", "out": ["10"], "in": [], "classStartIndex": 0},
               "10": {"name": "Basic Jewel Socket", "out": ["11"], "in": [], "isJewelSocket": True},
               "11": {"name": "Unrelenting", "out": [], "in": [], "ascendancyName": "Juggernaut",
                      "stats": ["+1 to Armour"]}}}
    b = pt.parse_tree(roh, False)
    bloecke = tree_report.respec_blocks(b, {"hashes": []}, {"hashes": [10, 11]}, title="T")
    zeilen = {z.name: z.text for blk in bloecke for z in blk.items}
    assert zeilen["Basic Jewel Socket"] == "(jewel socket)"
    assert zeilen["Unrelenting"] == "(ascendancy) — +1 to Armour"


def test_groups_keep_their_configurations_together(qapp, baum, monkeypatch) -> None:
    """Idee 3: importierte Bäume unter einer aufklappbaren Überschrift statt
    alphabetisch zwischen den eigenen."""
    from poe_view.ui import passive_tree_dialog as modul
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, gespeichert = _offen(qapp, baum)
    for name, gruppe in (("Boss", ""), ("Lvl 01-30", "Pohx RF"), ("Lvl 100", "Pohx RF"),
                         ("Lvl 31-40", "Pohx RF"), ("Arc", "Other")):
        th.save_config(zeichen, "WitchOfPeter", name, {"hashes": [10]}, level=30, ruthless=True,
                       source="pob", group=gruppe)
    dialog.refresh((CONFIG, "Boss"))
    eintraege = _eintraege(dialog)
    start = eintraege.index("Configurations")
    assert eintraege[start:start + 8] == ["Configurations", "Boss", "▾ Other (1)", "Arc",
                                          "▾ Pohx RF (3)", "Lvl 01-30", "Lvl 31-40", "Lvl 100"]
    # Ein Klick auf die Überschrift klappt zu — und wählt nichts aus.
    kopf = next(dialog.list.item(i) for i in range(dialog.list.count())
                if dialog.list.item(i).data(modul.GROUP_ROLE) == "Pohx RF")
    QTest.mouseClick(dialog.list.viewport(), Qt.MouseButton.LeftButton,
                     pos=dialog.list.visualItemRect(kopf).center())
    assert "▸ Pohx RF (3)" in _eintraege(dialog) and "Lvl 100" not in _eintraege(dialog)
    assert dialog._selected() == (CONFIG, "Boss")
    # Wird eine Konfiguration der Gruppe gewählt, klappt sie wieder auf.
    dialog.refresh((CONFIG, "Lvl 100"))
    assert "Lvl 100" in _eintraege(dialog) and dialog._selected() == (CONFIG, "Lvl 100")
    # "Save to X" und Überschreiben behalten die Gruppe.
    th.save_config(zeichen, "WitchOfPeter", "Lvl 100", {"hashes": [10, 11]}, level=30,
                   ruthless=True, source="edited")
    assert th.group_of(zeichen, "WitchOfPeter", "Lvl 100") == "Pohx RF"
    dialog.close()


def test_move_rename_ungroup_and_delete_a_group(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT
    dialog, zeichen, gespeichert = _drei(qapp, baum)
    # Zwei gewählte Konfigurationen in eine neue Gruppe.
    _item(dialog, (CONFIG, "B")).setSelected(True)
    angeboten = []
    monkeypatch.setattr(modul.QInputDialog, "getItem", staticmethod(
        lambda *a, **k: angeboten.append(a[3]) or ("Pohx", True)))
    dialog.act_move_group.trigger()
    assert angeboten == [[""]]                                    # noch keine Gruppen
    assert th.group_of(zeichen, "WitchOfPeter", "A") == "Pohx"
    assert th.group_of(zeichen, "WitchOfPeter", "B") == "Pohx"
    assert th.group_of(zeichen, "WitchOfPeter", "C") == ""
    assert gespeichert == [1]

    def kopf_punkt(gruppe):
        kopf = next(dialog.list.item(i) for i in range(dialog.list.count())
                    if dialog.list.item(i).data(modul.GROUP_ROLE) == gruppe)
        return dialog.list.visualItemRect(kopf).center()
    # Rechtsklick auf die Überschrift: Gruppen-Menü.
    gesehen = []
    monkeypatch.setattr(dialog, "_ask_name", lambda *a: "Pohx RF")
    _menue_waehlt(monkeypatch, "act_rename_group", dialog, gesehen)
    dialog._list_menu(kopf_punkt("Pohx"))
    assert gesehen[0] == ["Rename group…", "Ungroup", "Use as leveling plan",
                          "Delete group and its 2 configurations…"]
    assert tree_groups(zeichen) == ["Pohx RF"]
    _menue_waehlt(monkeypatch, "act_ungroup", dialog)
    dialog._list_menu(kopf_punkt("Pohx RF"))
    assert tree_groups(zeichen) == [] and set(th.configs(zeichen, "WitchOfPeter")) == {"A", "B", "C"}
    # Gruppe samt Konfigurationen löschen — nach einer Frage.
    th.set_group(zeichen, "WitchOfPeter", ["B", "C"], "Old")
    dialog.refresh((CONFIG, "B"))
    fragen = []
    monkeypatch.setattr(modul.QMessageBox, "question", staticmethod(
        lambda *a, **k: fragen.append(a[2]) or modul.QMessageBox.StandardButton.Yes))
    _menue_waehlt(monkeypatch, "act_delete_group", dialog)
    dialog._list_menu(kopf_punkt("Old"))
    assert fragen == ["Delete the group “Old” and its 2 configurations?"]
    assert set(th.configs(zeichen, "WitchOfPeter")) == {"A"}
    assert dialog._selected() == (CURRENT, None)                  # B war gewählt
    dialog.close()


def tree_groups(zeichen) -> list[str]:
    return th.groups(zeichen, "WitchOfPeter")


def test_a_multi_tree_import_lands_in_a_group(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, _ = _fenster(qapp, baum)
    code = _pob(baum, ("Lvl 01-30", [10, 11]), ("Lvl 31-40", [10, 11, 12]))
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(lambda *a, **k: (code, True)))
    felder = []

    def zeigen(fenster):
        feld = fenster.findChild(modul.QLineEdit, "group")
        felder.append(feld.text())
        feld.setText("Pohx RF")
        return modul.QDialog.DialogCode.Accepted
    monkeypatch.setattr(modul.QDialog, "exec", zeigen)
    dialog._import_link()
    assert felder == ["Juggernaut build"]                        # Vorschlag
    assert {th.group_of(zeichen, "WitchOfPeter", n) for n in ("Lvl 01-30", "Lvl 31-40")} == {
        "Pohx RF"}
    # Mit pobb.in-Adresse steht sie im Vorschlag.
    assert dialog._suggest_group(pob_trees(baum), "https://pobb.in/KMJMGblyFcI7") == (
        "Juggernaut (pobb.in/KMJMGblyFcI7)")
    dialog.close()


def pob_trees(baum):
    from poe_view.services import pob_import as pi
    return pi.decode_code(_pob(baum, ("A", [10]), ("B", [10, 11])))


def test_arrow_keys_skip_group_headers(qapp, baum) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, _ = _offen(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Boss", {"hashes": [10]}, level=30, ruthless=True,
                   source="link")
    th.save_config(zeichen, "WitchOfPeter", "Lvl 01-30", {"hashes": [10]}, level=30,
                   ruthless=True, source="pob", group="Pohx")
    dialog.refresh((CONFIG, "Boss"))
    dialog.list.setFocus()
    QTest.keyClick(dialog.list, Qt.Key.Key_Down)
    assert dialog._selected() == (CONFIG, "Lvl 01-30")            # über "▾ Pohx (1)" hinweg
    dialog.close()


def test_notes_are_saved_per_configuration(qapp, baum, monkeypatch) -> None:
    """Idee 4: Notizen je Konfiguration — speichern sich selbst (nach einer
    Pause beim Tippen, beim Wechsel, beim Schließen)."""
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT
    dialog, zeichen, gespeichert = _drei(qapp, baum)
    assert dialog.tabs.tabText(4) == "Notes" and not dialog.notes_edit.isReadOnly()
    dialog.notes_edit.setPlainText("Sirus: wear the fire res ring")
    assert dialog.tabs.tabText(4) == "Notes •"
    assert th.configs(zeichen, "WitchOfPeter")["A"].get("notes") is None   # noch nicht
    assert dialog._notes_timer.isActive()
    dialog._notes_timer.timeout.emit()                            # Pause beim Tippen
    assert th.configs(zeichen, "WitchOfPeter")["A"]["notes"] == "Sirus: wear the fire res ring"
    assert gespeichert == [1]
    assert _item(dialog, (CONFIG, "A")).toolTip() == "Sirus: wear the fire res ring"
    # Wechsel sichert sofort, ohne auf die Pause zu warten.
    dialog.notes_edit.setPlainText("Sirus: wear the ring, flask!")
    dialog.refresh((CONFIG, "B"))
    assert th.configs(zeichen, "WitchOfPeter")["A"]["notes"] == "Sirus: wear the ring, flask!"
    assert dialog.notes_edit.toPlainText() == "" and dialog.tabs.tabText(4) == "Notes"
    # Aktueller Baum: keine Notizen, nur lesen.
    dialog.refresh((CURRENT, None))
    assert dialog.notes_edit.isReadOnly() and "belong to configurations" in (
        dialog.notes_edit.placeholderText())
    dialog.notes_edit.setPlainText("x")                           # nichts gespeichert
    dialog._commit_notes()
    assert "notes" not in th.configs(zeichen, "WitchOfPeter")["B"]
    # Schließen sichert, was noch in der Pause hängt.
    dialog.refresh((CONFIG, "C"))
    dialog.notes_edit.setPlainText("for Maven")
    dialog.close()
    assert th.configs(zeichen, "WitchOfPeter")["C"]["notes"] == "for Maven"
    # Leeren nimmt das Feld heraus.
    assert th.set_notes(zeichen, "WitchOfPeter", "C", "  ") is True
    assert "notes" not in th.configs(zeichen, "WitchOfPeter")["C"]


def test_notes_survive_save_to_and_duplicate(qapp, baum, monkeypatch) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, _ = _drei(qapp, baum)
    th.set_notes(zeichen, "WitchOfPeter", "A", "keep me")
    dialog.refresh((CONFIG, "A"))
    dialog.graph.node_clicked.emit(12, False)                     # Entwurf aus "A"
    dialog.act_save.trigger()                                     # Save to "A"
    assert th.configs(zeichen, "WitchOfPeter")["A"]["notes"] == "keep me"
    monkeypatch.setattr(dialog, "_ask_name", lambda titel, v="": v)
    dialog.act_duplicate.trigger()
    assert th.configs(zeichen, "WitchOfPeter")["A (copy)"]["notes"] == "keep me"
    dialog.close()


def test_build_notes_come_with_the_import(qapp, baum, monkeypatch) -> None:
    """Pohx' Notizen (20.000 Zeichen, mit PoB-Farbcodes) kommen mit — ohne
    die Codes, mit Zeilen und Regex-Zeilen wie sie sind."""
    from poe_view.services import pob_import as pi
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, _ = _fenster(qapp, baum)
    specs = "".join(f'<Spec title="{t}"><URL>{pt.encode_url(baum, {"hashes": k}, "Juggernaut")}'
                    f"</URL></Spec>" for t, k in (("A", [10]), ("B", [10, 11])))
    notizen = "\n\t\t^2Visit Pohx.net^7\nRegex --> ^fire t|male\n\n^xE05030RED^7 end\n\t"
    xml = (f"<PathOfBuilding><Notes>{notizen}</Notes><Tree activeSpec='1'>{specs}</Tree>"
           "</PathOfBuilding>")
    code = base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()
    assert pi.decode_code(code)[0].notes == "Visit Pohx.net\nRegex --> ^fire t|male\n\nRED end"
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(lambda *a, **k: (code, True)))
    monkeypatch.setattr(dialog, "_choose_trees", lambda b: b)
    dialog._import_link()
    konfigs = th.configs(zeichen, "WitchOfPeter")
    assert konfigs["A"]["notes"] == konfigs["B"]["notes"] == (
        "Visit Pohx.net\nRegex --> ^fire t|male\n\nRED end")
    dialog.close()


def test_a_reimport_over_the_shown_configuration_keeps_its_new_notes(qapp, baum,
                                                                      monkeypatch) -> None:
    """Das Feld schreibt nur Getipptes zurück — sonst überschriebe es die
    Notizen, die ein Import gerade in die gezeigte Konfiguration legte."""
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, gespeichert = _drei(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "A", {"hashes": [10]}, level=30, ruthless=True,
                   source="pob", notes="new notes from the build")
    dialog.refresh((CONFIG, "B"))
    assert th.configs(zeichen, "WitchOfPeter")["A"]["notes"] == "new notes from the build"
    assert gespeichert == []
    dialog.close()


# --- Leveling-Plan (§4.60.14) ---------------------------------------------- #

def _plan_fenster(qapp, baum):
    """Aktueller Baum 10, 11, 12 (Level 30); Gruppe "Build" mit zwei
    Abschnitten: "S1" = 10, 11, 12, 20, 21 und "S2" = … 13, 14, 15."""
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "S2", {"hashes": [10, 11, 12, 13, 14, 15]},
                   level=30, ruthless=True, source="pob", group="Build")
    th.save_config(zeichen, "WitchOfPeter", "S1", {"hashes": [10, 11, 12, 20, 21]},
                   level=30, ruthless=True, source="pob", group="Build")
    dialog.refresh()
    return dialog, zeichen, gespeichert


def test_a_group_becomes_the_leveling_plan(qapp, baum, monkeypatch) -> None:
    """Peter, 2026-10-08: "Leveling-Mode … zeigt dann den zu vergebenden
    Skill-Punkt im Tree an." Rechtsklick auf die Gruppe → Plan."""
    from poe_view.ui import passive_tree_dialog as modul
    from poe_view.ui.passive_tree_dialog import CONFIG, CURRENT
    dialog, zeichen, gespeichert = _plan_fenster(qapp, baum)
    dialog.refresh((CONFIG, "S2"))
    dialog._menu_group = "Build"
    dialog.act_plan.trigger()
    dialog._menu_group = None
    assert th.leveling(zeichen, "WitchOfPeter") == {"stages": ["S1", "S2"], "priority": [],
                                                    "title": "Build"}
    assert dialog._selected() == (CURRENT, None) and dialog.tabs.currentIndex() == 3
    assert dialog.plan_bar.isVisibleTo(dialog) and gespeichert == [1]
    text = dialog.plan_label.text()
    assert text.startswith("Leveling “Build” · stage 1/2 “S1” · next: Life (towards Basic Jewel")
    assert "then Basic Jewel Socket, Iron Will" in text
    assert dialog.graph.markers == {20: "1", 21: "2", 13: "3", 14: "4", 15: "5"}
    assert dialog.graph.marker_now == 20 and dialog.graph.marker_refund == set()
    # Andere Einträge: kein Plan im Bild, nur der Hinweis.
    dialog.refresh((CONFIG, "S1"))
    assert dialog.graph.markers == {} and "select “Current tree”" in dialog.plan_label.text()
    # Stoppen.
    dialog.refresh((CURRENT, None))
    dialog.plan_stop_button.click()
    assert th.leveling(zeichen, "WitchOfPeter") is None
    assert not dialog.plan_bar.isVisibleTo(dialog) and dialog.graph.markers == {}
    dialog.close()


def test_points_spent_since_the_last_update_are_ticked(qapp, baum) -> None:
    """Zwischen zwei Abrufen zählt der Plan live weiter: zwei Aufstiege seit
    dem letzten Abruf → der erste Punkt ist vermutlich vergeben (✓)."""
    dialog, zeichen, _ = _plan_fenster(qapp, baum)
    th.set_leveling(zeichen, "WitchOfPeter", ["S1", "S2"], title="Build")
    dialog.refresh()
    dialog.set_levels(30, 32)
    assert dialog.graph.markers == {20: "✓", 21: "1", 13: "2", 14: "3", 15: "4"}
    assert dialog.graph.marker_now == 21
    assert "next: Basic Jewel Socket" in dialog.plan_label.text()
    assert "1 point assumed spent since the last update" in dialog.plan_label.text()
    dialog.close()


def test_the_order_is_set_by_clicking(qapp, baum, monkeypatch) -> None:
    """"Set order": Klicks stellen die Reihenfolge um und bauen keinen
    Entwurf; Knoten außerhalb des Plans sagen das."""
    from poe_view.ui.passive_tree_dialog import _GESPERRT_PLAN
    dialog, zeichen, gespeichert = _plan_fenster(qapp, baum)
    th.set_leveling(zeichen, "WitchOfPeter", ["S1", "S2"], title="Build")
    dialog.refresh()
    dialog.order_button.setChecked(True)
    assert dialog._click_hint(21) == "Click: take this as #1 in the leveling order"
    assert dialog._click_info(31) == (_GESPERRT_PLAN, False)
    dialog.graph.node_clicked.emit(15, False)                    # erst Far Away
    assert th.leveling(zeichen, "WitchOfPeter")["priority"] == [15]
    assert dialog._draft is None
    assert dialog._click_hint(15) == "Click: remove from the leveling order (#1)"
    # S1 ist noch offen (20, 21) — der Vorrang gilt im Abschnitt, in dem 15 liegt.
    assert dialog.graph.markers == {20: "1", 21: "2", 14: "3", 15: "4", 13: "5"}
    assert "click notables in the order you want them" in dialog.plan_label.text()
    dialog.graph.node_clicked.emit(15, False)                    # wieder heraus
    assert th.leveling(zeichen, "WitchOfPeter")["priority"] == []
    dialog.graph.node_clicked.emit(31, False)                    # nicht im Plan: nichts
    assert th.leveling(zeichen, "WitchOfPeter")["priority"] == []
    dialog.order_button.setChecked(False)
    dialog.graph.node_clicked.emit(13, False)                    # wieder normal: Entwurf
    assert dialog._draft is not None
    dialog._draft = None
    dialog.close()


def test_selected_configurations_and_a_renamed_stage_stay_in_the_plan(qapp, baum,
                                                                      monkeypatch) -> None:
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, _ = _plan_fenster(qapp, baum)
    dialog.refresh((CONFIG, "S2"))
    _item(dialog, (CONFIG, "S1")).setSelected(True)
    dialog.act_plan.trigger()
    assert th.leveling(zeichen, "WitchOfPeter")["stages"] == ["S1", "S2"]
    assert th.rename_config(zeichen, "WitchOfPeter", "S1", "Act 1-5")
    assert th.leveling(zeichen, "WitchOfPeter")["stages"] == ["Act 1-5", "S2"]
    # Eine gelöschte Konfiguration fällt aus dem Plan; fehlen alle, gibt es keinen.
    th.delete_config(zeichen, "WitchOfPeter", "Act 1-5")
    assert [s.name for s in dialog._plan().stages] == ["S2"]
    th.delete_config(zeichen, "WitchOfPeter", "S2")
    assert dialog._plan() is None
    dialog.close()


def test_plan_markers_are_drawn_and_the_current_step_stands_out(qapp) -> None:
    """Gemalt am Baum mit Lage: violetter Ring je Schritt, der jetzt dran
    ist doppelt so kräftig; was zurückzunehmen ist, gestrichelt."""
    from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsSimpleTextItem
    from poe_view.ui.tree_graph import _FARBEN, TreeGraph
    from tests.test_passive_tree import _aszendenz_baum
    g = TreeGraph()
    g.set_tree(_aszendenz_baum())
    g.show_tree({"hashes": [103]}, "Witch")
    g.set_markers({300: "1", 106: "2"}, now=300, refund=[102])
    ringe = [i for i in g._marker_items if isinstance(i, QGraphicsEllipseItem)]
    texte = sorted(i.text() for i in g._marker_items if isinstance(i, QGraphicsSimpleTextItem))
    assert texte == ["1", "2"]
    breiten = {round(r.rect().center().y()): (r.pen().widthF(), r.pen().style(), r.pen().color().name())
               for r in ringe}
    lage300 = round(g._lage(300).y)
    assert breiten[lage300] == (4.0, Qt.PenStyle.SolidLine, _FARBEN[True]["plan"])
    assert sorted(b[0] for b in breiten.values()) == [2.0, 2.0, 4.0]
    assert sum(1 for b in breiten.values() if b[1] == Qt.PenStyle.DashLine) == 1
    g.set_markers({})
    assert g._marker_items == []
    g.close()
