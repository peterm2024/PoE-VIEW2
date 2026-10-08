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
        "Show tree", "Rename…", "Duplicate…", "Delete"] + teile
    assert _texte(dialog._context_actions((CURRENT, None))) == [
        "Show tree", "Save as configuration…"] + teile
    assert _texte(dialog._context_actions((HISTORY, 0))) == [
        "Show tree", "Save as configuration…"] + teile
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
    assert gesehen[0][:4] == ["Show tree", "Rename…", "Duplicate…", "Delete"]
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
