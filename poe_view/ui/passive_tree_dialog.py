"""Das Fenster "Passive Tree": aktueller Baum, Verlauf und benannte
Konfigurationen eines Charakters (§4.60.1).

Peter, 2026-10-04: "Wir müssen uns auch eine Möglichkeit überlegen für
den Baum verschiedene Konfigurationen zur Verfügung zu stellen. Das
wechseln der Knoten kostet zwar Gold, aber ist oft die einzige
Möglichkeit bestimmte Bosse zu legen, gerade wenn man beschränkte
Ausrüstung hat."

Links die Liste (aktuell, Verlauf, Konfigurationen), rechts der Text zum
Gewählten — bei einer Konfiguration die Respec-Liste gegenüber dem
aktuellen Baum, beim Verlauf die Änderung gegenüber dem Eintrag davor.
Eine Konfiguration entsteht aus dem aktuellen Baum, aus einem
Planer-/PoB-Link oder aus einem PoB-Build (Code, pobb.in, §4.60.9); "Open in planner" zeigt jeden Baum grafisch im
offiziellen Planer, ohne dass PoE-VIEW2 selbst einen Baum zeichnet.

Das Fenster ändert nur die übergebenen Daten und ruft danach
``on_change`` — Speichern bleibt Sache des Hauptfensters.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (QAction, QBrush, QColor, QCursor, QDesktopServices,
                           QGuiApplication, QKeySequence, QPalette)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView,
                               QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSplitter, QTabWidget, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from poe_view.services import passive_tree, pob_import, tree_history
from poe_view.services.passive_tree import Tree, TreeLinkError
from poe_view.ui import tree_report
from poe_view.ui.tree_graph import TreeGraph

CURRENT, HISTORY, CONFIG = "current", "history", "config"


def config_order(name: str) -> list:
    """Sortierung der Konfigurationen nach Zahlen, nicht nach Zeichen:
    "Lvl 31-40" vor "Lvl 100" (Pohx' Bäume standen alphabetisch
    durcheinander, nativ gesehen)."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.lower())
            for t in re.split(r"(\d+)", name)]


class _EntryList(QListWidget):
    """Die Liste links. Ein Rechtsklick wählt nicht aus (§4.60.10; Peter,
    2026-10-08: "Wenn ich auf eine Config rechtsklicke wird diese
    automatisch ausgewählt" — sonst wechselte das Bild rechts mit); das
    Menü wirkt auf den Eintrag unter der Maus."""

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)
# Der Entwurf aus Klicks im Bild (§4.60.6) — nur im Fenster, bis er als
# Konfiguration gespeichert wird.
DRAFT = "draft"
_GESPERRT_WEG = "Not reachable from your tree"
_GESPERRT_MASTERY = "Needs a notable of this group first"
# Die Aszendenzen werden gezeigt, aber (noch) nicht geplant (§4.60.8).
_GESPERRT_ASZENDENZ = "Ascendancy: shown only, plan it in the official planner"


class PassiveTreeDialog(QDialog):
    def __init__(self, name: str, class_name: str, characters: dict, tree: Tree | None,
                 on_change: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Passive tree — {name}")
        # Ein QDialog hat unter Windows nur "Schließen"; für den Baum will
        # man den ganzen Bildschirm (Peter, 2026-10-05: "bitte aktiviere
        # auch den Maximieren-Knopf für das Fenster").
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self._name = name
        self._class = class_name
        self._characters = characters
        self._tree = tree
        self._on_change = on_change
        self._draft: dict | None = None          # passives des Entwurfs
        self._draft_from: tuple | None = None    # woraus er entstand
        self._undo: list[dict] = []
        self._status = ""                        # Meldung zum letzten Klick
        self._menu_keys: list | None = None      # Ziel des offenen Menüs (§4.60.10)

        self.list = _EntryList()
        # Mehrere Konfigurationen auf einmal löschen (Strg-/Umschalt-Klick),
        # etwa die zehn eines importierten Builds; gezeigt wird die aktuelle.
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        # Rechtsklick-Menü und Doppelklick/Enter → Bild (§4.60.10).
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        self.list.itemActivated.connect(lambda *_: self._show_tree_tab())
        # Rechts drei Reiter (§4.60.2, Peter: "Wir müssen unbedingt den Tree
        # übersichtlicher hinbekommen"): der Umbau (nur bei Konfiguration
        # und Verlauf), der Baum nach Themen, und die Reichweite als
        # aufklappbare Tabelle mit Suchfeld statt einer Liste von 100 Zeilen.
        self.respec_text = QTextBrowser()
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        self.reach_filter = QLineEdit()
        self.reach_filter.setPlaceholderText("Filter, e.g. fire res, life, minion…")
        self.reach_filter.setClearButtonEnabled(True)
        self.reach_filter.textChanged.connect(self._apply_reach_filter)
        self.reach = QTreeWidget()
        self.reach.setHeaderLabels(["Node", "Points", "Stats", "Via"])
        self.reach.setRootIsDecorated(True)
        self.reach.setUniformRowHeights(True)
        kopf = self.reach.header()
        kopf.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        kopf.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        kopf.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        kopf.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        kopf.setStretchLastSection(False)
        reichweite = QWidget()
        r_aufbau = QVBoxLayout(reichweite)
        r_aufbau.setContentsMargins(0, 0, 0, 0)
        r_aufbau.addWidget(self.reach_filter)
        r_aufbau.addWidget(self.reach, 1)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.respec_text, "Respec")
        self.tabs.addTab(self.text, "Overview")
        self.tabs.addTab(reichweite, "Within reach")
        # Der Baum als Bild (§4.60.4).
        self.graph = TreeGraph()
        self.graph_reach = QCheckBox("Within reach")
        self.graph_reach.setChecked(True)
        self.graph_reach.toggled.connect(lambda *_: self._fill_graph(self._selected(), fit=False))
        self.graph_search = QLineEdit()
        self.graph_search.setPlaceholderText("Find nodes, e.g. fire res, or a node ID…")
        self.graph_search.setClearButtonEnabled(True)
        self.graph_search.textChanged.connect(lambda t: self.graph.highlight(t, center=True))
        self.graph.node_clicked.connect(self._on_node_clicked)
        self.graph.click_hint = self._click_info
        self.graph_legend = QLabel()
        self.graph_legend.setWordWrap(True)
        self.graph_points = QLabel()        # verbrauchte Punkte des Gezeigten
        leiste = QHBoxLayout()
        leiste.addWidget(self.graph_search, 1)
        leiste.addWidget(self.graph_reach)
        bild = QWidget()
        b_aufbau = QVBoxLayout(bild)
        b_aufbau.setContentsMargins(0, 0, 0, 0)
        b_aufbau.addLayout(leiste)
        # Eigene Zeile: neben dem Suchfeld drückte der lange Text es auf
        # 168 px zusammen (nativ gemessen).
        b_aufbau.addWidget(self.graph_points)
        b_aufbau.addWidget(self.graph, 1)
        b_aufbau.addWidget(self.graph_legend)
        self.tabs.addTab(bild, "Tree")
        # Eingepasst wird nur beim ersten Zeigen; danach bleibt der
        # Ausschnitt, auch beim Wechsel in der Liste (§4.60.6).
        self._graph_fitted = False
        # Einpassen erst, wenn das Bild sichtbar ist — ein verdeckter Reiter
        # hat keine Größe, und fitInView zoomte dann ins Leere (nativ gesehen).
        self._graph_fit_pending = False
        self.tabs.currentChanged.connect(self._fit_graph_if_pending)

        # Wogegen verglichen wird (§4.60.11): automatisch wie bisher, oder
        # ein beliebiger anderer Eintrag.
        self.compare_box = QComboBox()
        self.compare_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.compare_box.currentIndexChanged.connect(lambda *_: self._show_selected())
        rechts = QWidget()
        rechts_aufbau = QVBoxLayout(rechts)
        rechts_aufbau.setContentsMargins(0, 0, 0, 0)
        vergleich_zeile = QHBoxLayout()
        vergleich_zeile.addStretch(1)
        vergleich_zeile.addWidget(QLabel("Compare with:"))
        vergleich_zeile.addWidget(self.compare_box)
        rechts_aufbau.addLayout(vergleich_zeile)
        rechts_aufbau.addWidget(self.tabs, 1)
        teiler = QSplitter()
        teiler.addWidget(self.list)
        teiler.addWidget(rechts)
        teiler.setStretchFactor(1, 3)

        self.save_button = QPushButton("Save current as…")
        self.import_button = QPushButton("Import…")
        self.rename_button = QPushButton("Rename…")
        self.delete_button = QPushButton("Delete")
        self.planner_button = QPushButton("Open in planner")
        self.link_button = QPushButton("Copy link")
        self.copy_button = QPushButton("Copy as text")
        self.undo_button = QPushButton("Undo")
        self.overwrite_button = QPushButton("Save")
        self.discard_button = QPushButton("Discard changes")
        self.undo_button.clicked.connect(self._undo_edit)
        self.overwrite_button.clicked.connect(self._save_draft_over)
        self.discard_button.clicked.connect(lambda: self._discard_draft(ask=True))
        self.save_button.clicked.connect(self._save_current)
        self.import_button.clicked.connect(self._import_link)
        self.rename_button.clicked.connect(self._rename)
        self.delete_button.clicked.connect(self._delete)
        self.planner_button.clicked.connect(self._open_planner)
        self.link_button.clicked.connect(self._copy_link)
        self.copy_button.clicked.connect(self._copy_text)
        knoepfe = QHBoxLayout()
        for knopf in (self.save_button, self.overwrite_button, self.undo_button,
                      self.discard_button, self.import_button, self.rename_button,
                      self.delete_button):
            knoepfe.addWidget(knopf)
        knoepfe.addStretch(1)
        for knopf in (self.planner_button, self.link_button, self.copy_button):
            knoepfe.addWidget(knopf)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        aufbau = QVBoxLayout(self)
        aufbau.addWidget(teiler, 1)
        aufbau.addWidget(self.hint)
        aufbau.addLayout(knoepfe)
        self._build_actions()
        self.resize(1000, 700)
        self.refresh()

    # --- Menü und Tastenkürzel (§4.60.10) ------------------------------- #

    def _build_actions(self) -> None:
        """Peter, 2026-10-08: "Folgende QoL wären für die Configurations
        noch gut: Rechtsklick-Menüs und Shortcuts." Jede Handlung einmal als
        QAction — im Menü steht ihr Kürzel daneben, die Knöpfe nennen es im
        Tooltip. Die Handler prüfen selbst, ob sie gerade passen.

        Fenster-weit: was nie mit einem Eingabefeld oder dem Bild kollidiert.
        Nur in der Liste: Entf, F2, Strg+C, Strg+V — im Suchfeld löschen,
        kopieren und einfügen sie Text, im Bild kopiert Strg+C den Knoten."""
        def aktion(text, kuerzel, handler, nur_liste=False, knopf=None) -> QAction:
            a = QAction(text, self)
            a.setShortcut(QKeySequence(kuerzel))
            a.triggered.connect(lambda *_: handler())
            ziel = self.list if nur_liste else self
            a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut if nur_liste
                                 else Qt.ShortcutContext.WindowShortcut)
            ziel.addAction(a)
            if knopf is not None:
                knopf.setToolTip(a.shortcut().toString(QKeySequence.SequenceFormat.NativeText))
            return a

        def mit_baum(handler):
            return lambda: handler() if self._tree is not None else None

        self.act_save = aktion("Save", "Ctrl+S", self._save_quick, knopf=self.overwrite_button)
        self.act_save_as = aktion("Save as…", "Ctrl+Shift+S", self._save_current,
                                  knopf=self.save_button)
        self.act_undo = aktion("Undo", "Ctrl+Z", self._undo_edit, knopf=self.undo_button)
        self.act_discard = aktion("Discard changes", "", lambda: self._discard_draft(ask=True))
        self.act_import = aktion("Import…", "Ctrl+I", mit_baum(self._import_link),
                                 knopf=self.import_button)
        self.act_paste = aktion("Import from clipboard", "Ctrl+V",
                                mit_baum(lambda: self._import_link(from_clipboard=True)),
                                nur_liste=True)
        self.act_rename = aktion("Rename…", "F2", self._rename, nur_liste=True,
                                 knopf=self.rename_button)
        self.act_delete = aktion("Delete", "Del", self._delete, nur_liste=True,
                                 knopf=self.delete_button)
        self.act_duplicate = aktion("Duplicate…", "Ctrl+D", self._duplicate)
        self.act_planner = aktion("Open in planner", "Ctrl+O", self._open_planner,
                                  knopf=self.planner_button)
        self.act_link = aktion("Copy link", "Ctrl+L", self._copy_link, knopf=self.link_button)
        self.act_text = aktion("Copy as text", "Ctrl+C", self._copy_text, nur_liste=True,
                               knopf=self.copy_button)
        self.act_show = aktion("Show tree", "", self._show_target)
        self.act_compare = aktion("Compare with this", "", self._compare_with_target)
        self.act_find = aktion("Find", "Ctrl+F", self._focus_search)
        for nummer in range(4):
            aktion(f"Tab {nummer + 1}", f"Ctrl+{nummer + 1}",
                   lambda n=nummer: self._show_tab(n))

    def _targets(self) -> list:
        """Worauf eine Handlung wirkt: im Menü der Eintrag unter der Maus
        (oder die Auswahl, wenn er dazugehört), sonst die Auswahl — die
        aktuelle zuerst."""
        if self._menu_keys is not None:
            return list(self._menu_keys)
        aktuell = self._selected()
        weitere = [k for k in self._selected_keys() if k != aktuell]
        return ([aktuell] if aktuell else []) + weitere

    def _target(self):
        ziele = self._targets()
        return ziele[0] if ziele else None

    def _selected_keys(self) -> list:
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()
                if i.data(Qt.ItemDataRole.UserRole)]

    def _after(self, key, ziel=None) -> None:
        """Nach einer Handlung neu aufbauen — die Auswahl bleibt, außer die
        Handlung galt ihr selbst (dann ``ziel``, etwa der neue Name)."""
        gewaehlt = self._selected()
        self.refresh(ziel if key == gewaehlt or gewaehlt is None else gewaehlt)

    def _context_actions(self, key) -> list[QAction | None]:
        """Was das Menü zu ``key`` zeigt (``None`` = Trennstrich)."""
        art = key[0] if key else None
        haupt: list[QAction | None] = []
        if art == DRAFT:
            herkunft = self._draft_from or (None, None)
            if herkunft[0] == CONFIG:
                self.act_save.setText(f"Save to “{herkunft[1]}”")
                haupt.append(self.act_save)
            haupt += [self.act_save_as, self.act_undo, self.act_discard]
        elif art == CONFIG:
            haupt += [self.act_show, self.act_rename, self.act_duplicate, self.act_delete]
        elif art in (CURRENT, HISTORY):
            haupt += [self.act_show, self.act_duplicate]
        self.act_duplicate.setText("Duplicate…" if art == CONFIG else "Save as configuration…")
        if key and key != self._selected() and self._entry(key) is not None:
            haupt.append(self.act_compare)                 # §4.60.11
        if self._entry(key) is not None:
            haupt += [None, self.act_planner, self.act_link, self.act_text]
        return haupt + ([None] if haupt else []) + [self.act_import]

    def _list_menu(self, punkt) -> None:
        """Das Menü zum Eintrag unter der Maus, ohne ihn auszuwählen. Gehört
        er zu einer Mehrfachauswahl, gilt es für alle (Löschen)."""
        item = self.list.itemAt(punkt)
        key = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        auswahl = self._selected_keys()
        self._menu_keys = ([key] + [k for k in auswahl if k != key] if key in auswahl
                           else [key] if key else [])
        hervor = None
        if item is not None and key and not item.isSelected():
            # Solange das Menü offen ist, zeigt eine Tönung, worauf es wirkt.
            hervor = item
            item.setBackground(QBrush(self.palette().color(QPalette.ColorRole.Mid)))
        menue = QMenu(self)
        for a in self._context_actions(key):
            menue.addSeparator() if a is None else menue.addAction(a)
        try:
            self._exec_menu(menue, self.list.viewport().mapToGlobal(punkt))
        finally:
            self._menu_keys = None
            # Über den Schlüssel, nicht das Item: Löschen, Umbenennen usw.
            # bauen die Liste neu, das alte Item gibt es dann nicht mehr.
            for i in range(self.list.count()):
                if hervor is not None and self.list.item(i).data(Qt.ItemDataRole.UserRole) == key:
                    self.list.item(i).setBackground(QBrush())

    def _exec_menu(self, menue: QMenu, punkt):
        """Ein Menü öffnen. Eigene Methode, damit Tests sie ersetzen können:
        ``QMenu.exec`` lässt sich bei PySide6 an der Klasse nicht ersetzen
        (die statische Überladung gleichen Namens geht vor), ein echtes
        Menü wartet offscreen ewig (FALLSTRICKE #99)."""
        return menue.exec(punkt)

    def _save_quick(self) -> None:
        """Strg+S: einen Entwurf aus einer Konfiguration dorthin zurück,
        sonst wie "Save as…"."""
        if self._draft is not None and self._draft_from and self._draft_from[0] == CONFIG:
            self._save_draft_over()
        else:
            self._save_current()

    def _duplicate(self) -> None:
        """Den gewählten Eintrag als (neue) Konfiguration — Kopie einer
        Konfiguration oder ein Stand aus dem Verlauf."""
        key = self._target()
        eintrag = self._entry(key)
        if eintrag is None or key[0] == DRAFT:
            return
        if key[0] == CURRENT:
            self._save_current()
            return
        vorschlag = f"{key[1]} (copy)" if key[0] == CONFIG else \
            f"Level {eintrag.get('level') or '?'} tree"
        name = self._ask_name("Save as configuration", vorschlag)
        if not name or not self._confirm_overwrite(name):
            return
        aktuell = tree_history.current(self._characters, self._name) or {}
        tree_history.save_config(self._characters, self._name, name,
                                 dict(eintrag.get("passives") or {}),
                                 level=eintrag.get("level") or aktuell.get("level") or 0,
                                 ruthless=bool(eintrag.get("ruthless", aktuell.get("ruthless"))),
                                 source="copy")
        self._on_change()
        self._after(key, (CONFIG, name))

    def _show_target(self) -> None:
        """"Show tree": den Eintrag auswählen und das Bild zeigen."""
        key = self._target()
        if key:
            self.refresh(key)
        self._show_tree_tab()

    def _show_tab(self, nummer: int) -> None:
        if self.tabs.isTabVisible(nummer):
            self.tabs.setCurrentIndex(nummer)

    def _show_tree_tab(self) -> None:
        self.tabs.setCurrentIndex(3)

    def _focus_search(self) -> None:
        """Strg+F: im Reiter "Within reach" dessen Filter, sonst das
        Suchfeld über dem Bild."""
        if self.tabs.currentIndex() == 2:
            feld = self.reach_filter
        else:
            self._show_tree_tab()
            feld = self.graph_search
        feld.setFocus(Qt.FocusReason.ShortcutFocusReason)
        feld.selectAll()

    @staticmethod
    def _clipboard_import_text() -> str:
        """Was in der Zwischenablage nach Baum, Build oder pobb.in aussieht —
        als Vorschlag im Import-Feld; sonst nichts."""
        text = (QGuiApplication.clipboard().text() or "").strip()
        if not text or len(text) > 2_000_000:
            return ""
        if pob_import.remote_url(text) or "passive-skill-tree/" in text:
            return text
        roh = "".join(text.split())
        if len(roh) >= 40 and all(c.isalnum() or c in "-_=" for c in roh):
            return text                                 # Code (Base64)
        return ""

    # --- Liste ---------------------------------------------------------- #

    def refresh(self, select: tuple[str, object] | None = None) -> None:
        """Liste neu aufbauen; ``select`` = (Art, Schlüssel) danach wählen."""
        alt = select or self._selected()
        self.list.blockSignals(True)
        self.list.clear()
        aktuell = tree_history.current(self._characters, self._name)
        if self._draft is not None:
            self._add("✎ Unsaved changes", (DRAFT, None), bold=True)
        if aktuell:
            self._add("Current tree", (CURRENT, None), bold=True)
        konfigs = tree_history.configs(self._characters, self._name)
        if konfigs:
            self._header("Configurations")
            for name in sorted(konfigs, key=config_order):
                self._add(f"  {name}", (CONFIG, name))
        verlauf = tree_history.history(self._characters, self._name)
        if verlauf:
            self._header("History")
            for index in range(len(verlauf) - 1, -1, -1):
                eintrag = verlauf[index]
                self._add(f"  {self._history_caption(verlauf, index)}", (HISTORY, index))
        self.list.blockSignals(False)
        self._fill_compare_box(aktuell, konfigs, verlauf)
        # Überschriften tragen keinen Schlüssel — ohne ``alt`` darf die
        # Suche nicht auf ihnen landen.
        ziel = next((self.list.item(i) for i in range(self.list.count())
                     if alt and self.list.item(i).data(Qt.ItemDataRole.UserRole) == alt), None)
        if ziel is None:
            ziel = next((self.list.item(i) for i in range(self.list.count())
                         if self.list.item(i).data(Qt.ItemDataRole.UserRole)), None)
        if ziel is not None:
            self.list.setCurrentItem(ziel)
        self._show_selected()

    def _fill_compare_box(self, aktuell, konfigs, verlauf) -> None:
        """"Automatic", der aktuelle Baum, die Konfigurationen, der Verlauf —
        die Wahl bleibt, solange es den Eintrag gibt."""
        alt = self._compare_key()
        # Die Schlüssel stehen in einer eigenen Liste: ``findData`` vergleicht
        # Python-Objekte im QVariant über ihre Identität — ein gleiches,
        # aber neu gebautes Tupel fand es nicht (-1; gemessen).
        eintraege = [("Automatic (current tree / the tree before)", None)]
        if aktuell:
            eintraege.append(("Current tree", (CURRENT, None)))
        eintraege += [(name, (CONFIG, name)) for name in sorted(konfigs or {}, key=config_order)]
        eintraege += [(self._history_caption(verlauf, index), (HISTORY, index))
                      for index in range(len(verlauf or ()) - 1, -1, -1)]
        self._compare_keys = [k for _t, k in eintraege]
        self.compare_box.blockSignals(True)
        self.compare_box.clear()
        self.compare_box.addItems([t for t, _k in eintraege])
        self.compare_box.setCurrentIndex(self._compare_index(alt))
        self.compare_box.blockSignals(False)

    def _compare_key(self):
        i = self.compare_box.currentIndex()
        keys = getattr(self, "_compare_keys", [])
        return keys[i] if 0 <= i < len(keys) else None

    def _compare_index(self, key) -> int:
        keys = getattr(self, "_compare_keys", [])
        return keys.index(key) if key in keys else 0

    def _label(self, key) -> str:
        art, schluessel = key
        if art == CURRENT:
            return "current tree"
        if art == DRAFT:
            return "unsaved changes"
        if art == CONFIG:
            return schluessel
        eintrag = self._entry(key) or {}
        return f"tree of {str(eintrag.get('at', '')).replace('T', ' ')[:16]}"

    def _base(self, key) -> tuple[dict, str, bool] | None:
        """Wogegen ``key`` verglichen wird: (passives, Bezeichnung, ob der
        Umbau jetzt ansteht — dann mit Goldpreis). Automatisch:
        Konfiguration und Entwurf gegen den aktuellen Baum, Verlauf gegen
        den Eintrag davor (§4.60.11)."""
        gewaehlt = self._compare_key()
        if gewaehlt and gewaehlt != key and self._entry(gewaehlt) is not None:
            return (self._entry(gewaehlt).get("passives") or {}, self._label(gewaehlt), True)
        art = key[0] if key else None
        if art in (CONFIG, DRAFT):
            aktuell = tree_history.current(self._characters, self._name)
            if aktuell:
                return aktuell.get("passives") or {}, "current tree", True
        if art == HISTORY and key[1] > 0:
            davor = tree_history.history(self._characters, self._name)[key[1] - 1]
            return davor.get("passives") or {}, "the tree before", False
        return None

    def _compare_with_target(self) -> None:
        """Menü "Compare with this": den Eintrag unter der Maus als Basis."""
        key = self._target()
        if key and self._compare_index(key):
            self.compare_box.setCurrentIndex(self._compare_index(key))

    def _add(self, text: str, key: tuple, bold: bool = False) -> None:
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, key)
        if bold:
            schrift = item.font()
            schrift.setBold(True)
            item.setFont(schrift)
        self.list.addItem(item)

    def _header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        schrift = item.font()
        schrift.setBold(True)
        item.setFont(schrift)
        self.list.addItem(item)

    def _history_caption(self, verlauf: list[dict], index: int) -> str:
        eintrag = verlauf[index]
        zeit = str(eintrag.get("at", "")).replace("T", " ")[:16]
        kopf = f"{zeit} · Level {eintrag.get('level') or '?'}"
        if index == 0:
            return f"{kopf} · first seen"
        jetzt = passive_tree.allocated(eintrag.get("passives") or {})
        vorher = passive_tree.allocated(verlauf[index - 1].get("passives") or {})
        return f"{kopf} · +{len(jetzt - vorher)} / −{len(vorher - jetzt)}"

    def _selected(self) -> tuple[str, object] | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _entry(self, key) -> dict | None:
        if not key:
            return None
        art, schluessel = key
        if art == DRAFT:
            if self._draft is None:
                return None
            basis = dict(tree_history.current(self._characters, self._name) or {})
            basis["passives"] = self._draft
            return basis
        if art == CURRENT:
            return tree_history.current(self._characters, self._name)
        if art == CONFIG:
            return tree_history.configs(self._characters, self._name).get(schluessel)
        verlauf = tree_history.history(self._characters, self._name)
        return verlauf[schluessel] if 0 <= schluessel < len(verlauf) else None

    # --- Anzeige -------------------------------------------------------- #

    def _respec_blocks(self, key) -> list:
        """Der Umbau zum Gewählten — von dem aus, wogegen verglichen wird
        (``_base``); ohne Vergleich nichts."""
        eintrag = self._entry(key)
        basis = self._base(key) if eintrag is not None and self._tree is not None else None
        if basis is None:
            return []
        passives, bezeichnung, jetzt = basis
        aktuell = tree_history.current(self._characters, self._name) or {}
        if bezeichnung == "the tree before":
            titel = "Changes from the tree before"
        else:
            titel = f"Respec: {bezeichnung} → {self._label(key)}"
        return tree_report.respec_blocks(
            self._tree, passives, eintrag.get("passives") or {}, title=titel,
            level=aktuell.get("level") if jetzt else None)   # umgebaut wird auf dem heutigen Level

    def _tree_blocks(self, key, include_reach: bool) -> list:
        bloecke = tree_report.tree_blocks(self._entry(key), self._tree,
                                          character_class=self._class,
                                          include_reach=include_reach)
        if key and key[0] == CONFIG:
            bloecke[0].title = f"Configuration: {key[1]}"
        elif key and key[0] == DRAFT:
            bloecke[0].title = "Unsaved changes"
        return bloecke

    def markdown_for(self, key) -> str:
        """Alles als Markdown — das, was "Copy as text" kopiert."""
        eintrag = self._entry(key)
        if eintrag is None:
            return ("*No tree recorded for this character yet. It arrives with the "
                    "next refresh of the character.*")
        if self._tree is None:
            return ("*GGG's tree data has not been downloaded yet — try again in a "
                    "minute.*")
        return "\n".join(tree_report.to_markdown(
            self._respec_blocks(key) + self._tree_blocks(key, include_reach=True)))

    def _dark(self) -> bool:
        return self.text.palette().color(QPalette.ColorRole.Base).lightnessF() < 0.5

    def _fill_reach(self, key) -> None:
        self.reach.clear()
        eintrag = self._entry(key)
        if eintrag is None or self._tree is None:
            return
        have = passive_tree.allocated(eintrag.get("passives") or {})
        for titel, farbe_key, gruppe in tree_report.reach_groups(self._tree, have, self._class):
            symbol = tree_report.SYMBOL.get(farbe_key, "")
            kopf = QTreeWidgetItem([f"{symbol} {titel} ({len(gruppe)})"])
            kopf.setData(0, Qt.ItemDataRole.UserRole, f"{symbol} {titel}")
            schrift = kopf.font(0)
            schrift.setBold(True)
            kopf.setFont(0, schrift)
            farbe = tree_report.colour(farbe_key, self._dark())
            if farbe:
                kopf.setForeground(0, QBrush(QColor(farbe)))
            for r in gruppe:
                werte = ("; ".join(r.node.stats) if r.node.stats
                         else "empty socket" if r.node.kind == passive_tree.JEWEL else "—")
                zeile = QTreeWidgetItem([r.node.name, str(r.cost), werte,
                                         ", ".join(n.name for n in r.via)])
                if farbe:
                    zeile.setForeground(0, QBrush(QColor(farbe)))
                zeile.setToolTip(2, "\n".join(r.node.stats) or werte)
                zeile.setToolTip(3, " → ".join(n.name for n in r.via))
                zeile.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                kopf.addChild(zeile)
            self.reach.addTopLevelItem(kopf)
        self.reach.expandAll()
        self._apply_reach_filter(self.reach_filter.text())

    def _fill_graph(self, key, *, fit: bool) -> None:
        """Bild zum Gewählten: bei Konfiguration und Verlauf als Umbau
        (grün nehmen, rot zurücknehmen), sonst mit Reichweite."""
        self.graph.set_tree(self._tree)
        eintrag = self._entry(key)
        if eintrag is None or self._tree is None:
            self.graph_legend.setText("")
            self.graph_points.setText("")
            return
        basis = self._base(key)
        vergleich = basis[0] if basis else None
        self.graph.show_tree(eintrag.get("passives") or {}, self._class,
                             compare_to=vergleich, show_reach=self.graph_reach.isChecked(),
                             dark=self._dark())
        self.graph.highlight(self.graph_search.text())
        # Level und Bandit: beim Verlauf die des Eintrags, sonst die des
        # Charakters heute — gebaut wird auf dem heutigen Level.
        quelle = (eintrag if key[0] == HISTORY
                  else tree_history.current(self._characters, self._name) or eintrag)
        # Der Eintrag davor (Verlauf, automatisch) steht nicht dabei.
        nennen = basis is not None and basis[1] != "the tree before"
        self.graph_points.setText(tree_report.points_text(
            self._tree, eintrag.get("passives") or {}, vergleich if nennen else None,
            level=quelle.get("level"),
            bandit=(quelle.get("passives") or {}).get("bandit_choice"),
            base_label=basis[1] if nennen else "current tree"))
        self.graph_reach.setEnabled(vergleich is None)
        self.graph_legend.setText(
            ("Green: allocate · red: refund · white: unchanged · " if vergleich is not None
             else "Filled: allocated (colour = theme) · ring: within reach · ")
            + "hollow: not allocated · yellow ring: search match · wheel: zoom · drag: move · "
            "click: allocate · right-click: refund\n"
            + "Background: red Strength · green Dexterity · blue Intelligence · "
            "striped: hybrid classes")
        if fit:
            self._graph_fitted = True
            self._graph_fit_pending = True
            self._fit_graph_if_pending()

    def _fit_graph_if_pending(self, *_args) -> None:
        if self._graph_fit_pending and self.graph.isVisible():
            self._graph_fit_pending = False
            self.graph.fit_allocated()

    def _apply_reach_filter(self, text: str) -> None:
        """Jedes Wort muss in Name oder Werten vorkommen ("fire res" findet
        "+8% to Fire Resistance"); leere Gruppen verschwinden."""
        woerter = text.lower().split()
        for i in range(self.reach.topLevelItemCount()):
            gruppe = self.reach.topLevelItem(i)
            sichtbar = 0
            for j in range(gruppe.childCount()):
                kind = gruppe.child(j)
                heuhaufen = f"{kind.text(0)} {kind.toolTip(2)}".lower()
                treffer = all(w in heuhaufen for w in woerter)
                kind.setHidden(not treffer)
                sichtbar += treffer
            gruppe.setHidden(sichtbar == 0)
            titel = gruppe.data(0, Qt.ItemDataRole.UserRole)
            anzahl = gruppe.childCount()
            gruppe.setText(0, f"{titel} ({sichtbar} of {anzahl})" if woerter
                           else f"{titel} ({anzahl})")

    def _show_selected(self) -> None:
        key = self._selected()
        dunkel = self._dark()
        umbau = self._respec_blocks(key)
        self.respec_text.setHtml(tree_report.to_html(umbau, dark=dunkel) if umbau else "")
        # Mit Umbau zeigt der Reiter "Respec" — er ist bei einer
        # Konfiguration das, worum es geht; ohne Umbau verschwindet er.
        self.tabs.setTabVisible(0, bool(umbau))
        # Der gewählte Reiter bleibt, auch beim Wechsel der Auswahl (Peter,
        # 2026-10-08: "statt auf dem Tree zu bleiben"); nur ein Respec-Reiter,
        # der verschwindet, gibt an "Overview" ab (§4.60.6).
        if not umbau and self.tabs.currentIndex() == 0:
            self.tabs.setCurrentIndex(1)
        if self._entry(key) is None or self._tree is None:
            self.text.setMarkdown(self.markdown_for(key))
        else:
            self.text.setHtml(tree_report.to_html(self._tree_blocks(key, include_reach=False),
                                                  dark=dunkel))
        self._fill_reach(key)
        self._fill_graph(key, fit=not self._graph_fitted)
        ist_konfig = bool(key) and key[0] == CONFIG
        self.rename_button.setEnabled(ist_konfig)
        self.delete_button.setEnabled(ist_konfig)
        hat_baum = self._entry(key) is not None and self._tree is not None
        self.planner_button.setEnabled(hat_baum)
        self.link_button.setEnabled(hat_baum)
        self.copy_button.setEnabled(self._entry(key) is not None)
        ist_entwurf = bool(key) and key[0] == DRAFT
        self.save_button.setText("Save as…" if ist_entwurf else "Save current as…")
        self.save_button.setEnabled(
            tree_history.current(self._characters, self._name) is not None)
        herkunft = self._draft_from if ist_entwurf else None
        self.overwrite_button.setVisible(bool(herkunft) and herkunft[0] == CONFIG)
        if herkunft and herkunft[0] == CONFIG:
            self.overwrite_button.setText(f"Save to “{herkunft[1]}”")
        self.undo_button.setVisible(ist_entwurf)
        self.undo_button.setEnabled(bool(self._undo))
        # Die Aktionen (Menü, Kürzel) wie die Knöpfe (§4.60.10).
        self.act_undo.setEnabled(bool(self._undo))
        self.act_import.setEnabled(self._tree is not None)
        self.act_paste.setEnabled(self._tree is not None)
        self.discard_button.setVisible(ist_entwurf)
        self.import_button.setEnabled(self._tree is not None)
        teile = ["Ruthless tree"] if self._tree is not None and self._tree.ruthless else []
        if ist_entwurf and self._tree is not None:
            aktuell = tree_history.current(self._characters, self._name) or {}
            vorher = aktuell.get("passives") or {}
            umbau = passive_tree.compare(self._tree, vorher, self._draft)
            umbau_punkte = umbau.points
            teile.append(
                f"Unsaved changes: {passive_tree.main_points(self._tree, self._draft)} points "
                f"(current tree {passive_tree.main_points(self._tree, vorher)}) · "
                f"respec: {umbau_punkte} {'point' if umbau_punkte == 1 else 'points'} "
                "to refund" + tree_report.gold_text(umbau, aktuell.get("level")))
        if self._status:
            teile.append(self._status)
        self.hint.setText(" · ".join(teile))

    # --- Handlungen ----------------------------------------------------- #

    def _ask_name(self, title: str, vorschlag: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, "Name:", text=vorschlag)
        name = name.strip()
        return name if ok and name else None

    def _confirm_overwrite(self, name: str) -> bool:
        if name not in tree_history.configs(self._characters, self._name):
            return True
        return QMessageBox.question(
            self, "Overwrite configuration",
            f"A configuration named “{name}” exists. Replace it?") == QMessageBox.StandardButton.Yes

    # --- Bearbeiten im Bild (§4.60.6) ------------------------------------ #

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _editing_base(self) -> dict | None:
        """Woraus ein Klick baut: der Entwurf, sonst das Gewählte."""
        key = self._selected()
        if key and key[0] == DRAFT:
            return self._draft
        eintrag = self._entry(key)
        return None if eintrag is None else (eintrag.get("passives") or {})

    def _click_hint(self, node: int) -> str | None:
        basis = self._editing_base()
        if basis is None or self._tree is None or node not in self._tree.nodes:
            return None
        n = self._tree.nodes[node]
        if n.ascendancy:
            return None if n.kind == passive_tree.START else _GESPERRT_ASZENDENZ
        have = passive_tree.allocated(basis)
        if n.kind == passive_tree.MASTERY:
            if node in have:
                return "Click: change effect · right-click: refund"
            return ("Click: choose an effect" if passive_tree.mastery_allowed(
                self._tree, have, node) else _GESPERRT_MASTERY)
        if n.kind == passive_tree.START:
            return None
        if node in have:
            weg = passive_tree.cut_off(self._tree, have, node, self._class)
            return f"Right-click: refund ({len(weg)} {'point' if len(weg) == 1 else 'points'})"
        weg = passive_tree.path_to(self._tree, have, node, self._class)
        if weg is None:
            return _GESPERRT_WEG
        return f"Click: allocate ({len(weg)} {'point' if len(weg) == 1 else 'points'})"

    def _click_info(self, node: int) -> tuple[str, bool] | None:
        """Für das Bild: Zusatzzeile und ob ein Klick etwas tut (Zeiger
        "Hand" oder "verboten")."""
        text = self._click_hint(node)
        return None if text is None else (
            text, text not in (_GESPERRT_WEG, _GESPERRT_MASTERY, _GESPERRT_ASZENDENZ))

    def _choose_effect(self, node: int, have_choice: dict[int, int]) -> int | None:
        """Menü mit den Effekten der Mastery; schon anderswo gewählte sind
        gesperrt (jeder Effekt nur einmal je Baum)."""
        m = self._tree.nodes[node]
        menue = QMenu(self)
        anderswo = {e for k, e in have_choice.items() if k != node}
        aktionen = {}
        for effekt, werte in m.effects.items():
            a = menue.addAction(" / ".join(werte) or str(effekt))
            a.setCheckable(True)
            a.setChecked(have_choice.get(node) == effekt)
            a.setEnabled(effekt not in anderswo)
            aktionen[a] = effekt
        gewaehlt = self._exec_menu(menue, QCursor.pos())
        return aktionen.get(gewaehlt)

    def _on_node_clicked(self, node: int, right: bool) -> None:
        if self._tree is None or node not in self._tree.nodes or self._tree.nodes[node].ascendancy:
            return                                  # Aszendenz: nur gezeigt (§4.60.8)
        key = self._selected()
        basis = self._editing_base()
        if basis is None:
            return
        n = self._tree.nodes[node]
        if n.kind == passive_tree.MASTERY:
            if right:
                neu = passive_tree.edit_mastery(self._tree, basis, node, None)
            elif not passive_tree.mastery_allowed(self._tree, passive_tree.allocated(basis), node):
                self._set_status(f"{n.name}: needs a notable of this group first")
                return
            else:
                effekt = self._choose_effect(node, passive_tree.mastery_choices(basis))
                if effekt is None:
                    return
                neu = passive_tree.edit_mastery(self._tree, basis, node, effekt)
        elif right:
            neu = passive_tree.edit_refund(self._tree, basis, node, self._class)
        else:
            neu = passive_tree.edit_allocate(self._tree, basis, node, self._class)
            if neu is None:
                self._set_status(f"{n.name}: not reachable from your tree")
                return
        if neu is None or (passive_tree.allocated(neu) == passive_tree.allocated(basis)
                           and passive_tree.mastery_choices(neu)
                           == passive_tree.mastery_choices(basis)):
            return
        if key and key[0] != DRAFT:
            # Ein neuer Entwurf aus dem Gewählten — ein alter ginge verloren.
            if self._draft is not None and not self._ask(
                    "Unsaved changes", "Discard the unsaved changes and start again from "
                    "this tree?"):
                return
            self._draft_from = key
            self._undo = []
        # Auch der erste Klick ist rücknehmbar: dann zurück zum Ausgangsbaum.
        self._undo.append(basis)
        self._draft = neu
        self._status = ""
        self.refresh((DRAFT, None))

    def _set_status(self, text: str) -> None:
        self._status = text
        self._show_selected()

    def _undo_edit(self) -> None:
        if not self._undo:
            return
        vorher = self._undo.pop()
        if not self._undo:
            # Der erste Schritt ist zurückgenommen: kein Entwurf mehr, wieder
            # das Gewählte von vorher — ohne Rückfrage, verloren geht nichts.
            zurueck = self._draft_from or (CURRENT, None)
            self._draft, self._draft_from, self._status = None, None, ""
            self.refresh(zurueck)
            return
        self._draft = vorher
        self._status = ""
        self.refresh((DRAFT, None))

    def _discard_draft(self, ask: bool) -> bool:
        if self._draft is None:
            return True
        if ask and not self._ask("Discard changes", "Discard the unsaved changes?"):
            return False
        zurueck = self._draft_from or (CURRENT, None)
        self._draft, self._draft_from, self._undo, self._status = None, None, [], ""
        self.refresh(zurueck)
        return True

    def _store_draft(self, name: str) -> None:
        aktuell = tree_history.current(self._characters, self._name) or {}
        tree_history.save_config(self._characters, self._name, name, dict(self._draft),
                                 level=aktuell.get("level") or 0,
                                 ruthless=self._tree.ruthless if self._tree else False,
                                 source="edited")
        self._draft, self._draft_from, self._undo, self._status = None, None, [], ""
        self._on_change()
        self.refresh((CONFIG, name))

    def _save_draft_over(self) -> None:
        if self._draft is not None and self._draft_from and self._draft_from[0] == CONFIG:
            self._store_draft(self._draft_from[1])

    def reject(self) -> None:
        # Schließen (Esc, ×) fragt, wenn ein Entwurf verloren ginge.
        if self._draft is not None and not self._ask(
                "Unsaved changes", "Close and discard the unsaved changes?"):
            return
        super().reject()

    def _save_current(self) -> None:
        key = self._target()
        if key and key[0] == DRAFT and self._draft is not None:
            herkunft = self._draft_from or (None, None)
            name = self._ask_name("Save changes as", herkunft[1] if herkunft[0] == CONFIG else "")
            if name and self._confirm_overwrite(name):
                self._store_draft(name)
            return
        aktuell = tree_history.current(self._characters, self._name)
        name = self._ask_name("Save current tree as") if aktuell else None
        if not name or not self._confirm_overwrite(name):
            return
        tree_history.save_config(self._characters, self._name, name,
                                 dict(aktuell.get("passives") or {}),
                                 level=aktuell.get("level") or 0,
                                 ruthless=bool(aktuell.get("ruthless")), source="current")
        self._on_change()
        self.refresh((CONFIG, name))

    def _import_link(self, from_clipboard: bool = False) -> None:
        """Planer-Link, PoB-Code oder pobb.in-/pastebin-Link (§4.60.9;
        Peter, 2026-10-08: "Evtl. sollten wir die pobb.in Unterstützung
        hinzufügen") — ein Build bringt oft mehrere Bäume mit. Was in der
        Zwischenablage danach aussieht, steht schon im Feld (§4.60.10);
        Strg+V in der Liste importiert es ohne Nachfrage."""
        vorschlag = self._clipboard_import_text()
        if from_clipboard and vorschlag:
            text, ok = vorschlag, True
        else:
            text, ok = QInputDialog.getText(
                self, "Import tree",
                "Paste a passive tree link (official planner or Path of Building),\n"
                "a Path of Building code, or a pobb.in / pastebin link:", text=vorschlag)
        if not ok or not text.strip():
            return
        try:
            baeume = self._read_trees(text)
        except (TreeLinkError, pob_import.PobImportError) as exc:
            QMessageBox.warning(self, "Import tree", f"Nothing to import ({exc}).")
            return
        if len(baeume) > 1:
            baeume = self._choose_trees(baeume)
            if not baeume:
                return
        eigene = self._tree.class_ids.get(self._class, (None, None))[0]
        fremd = sorted({passive_tree.class_name_of(self._tree, b.link.class_index,
                                                   b.link.ascendancy_index) or "different class"
                        for b in baeume if eigene is not None and b.link.class_index != eigene})
        if fremd and QMessageBox.question(
                self, "Import tree",
                f"{'This tree is' if len(baeume) == 1 else 'These trees are'} for a "
                f"{' / '.join(fremd)}, not a {self._class}. Import anyway?"
        ) != QMessageBox.StandardButton.Yes:
            return
        if len(baeume) == 1:
            name = self._ask_name("Name the configuration", baeume[0].title)
            if not name or not self._confirm_overwrite(name):
                return
            namen = [name]
        else:
            namen = self._unique_titles(baeume)
            vorhanden = [n for n in namen if n in tree_history.configs(self._characters,
                                                                       self._name)]
            if vorhanden and not self._ask(
                    "Overwrite configurations",
                    f"{len(vorhanden)} of these names exist already "
                    f"(“{vorhanden[0]}”{', …' if len(vorhanden) > 1 else ''}). Replace them?"):
                return
        aktuell = tree_history.current(self._characters, self._name) or {}
        for name, baum in zip(namen, baeume):
            tree_history.save_config(self._characters, self._name, name, baum.link.passives,
                                     level=aktuell.get("level") or 0,
                                     ruthless=self._tree.ruthless,
                                     source="link" if not baum.title else "pob")
        self._on_change()
        self.refresh((CONFIG, namen[0]))

    def _read_trees(self, text: str) -> list[pob_import.BuildTree]:
        """Erst die Links mit eigener Adresse (pobb.in/pastebin, Abruf mit
        Sanduhr), dann ein Baum-Link, zuletzt ein PoB-Code."""
        if pob_import.remote_url(text):
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                return pob_import.read(text)
            finally:
                QGuiApplication.restoreOverrideCursor()
        try:
            return [pob_import.BuildTree("", passive_tree.decode_url(text))]
        except TreeLinkError:
            return pob_import.decode_code(text)

    @staticmethod
    def _unique_titles(baeume: list[pob_import.BuildTree]) -> list[str]:
        namen: list[str] = []
        for baum in baeume:
            name, n = baum.title, 2
            while name in namen:
                name, n = f"{baum.title} ({n})", n + 1
            namen.append(name)
        return namen

    def _choose_trees(self, baeume: list[pob_import.BuildTree]) -> list[pob_import.BuildTree]:
        """Welche Bäume des Builds? Vorgewählt sind alle mit Punkten — ein
        "Info"-Baum mit nur dem Start (Pohx: "CHECK POB NOTES") nicht."""
        fenster = QDialog(self)
        fenster.setWindowTitle("Import trees from build")
        liste = QListWidget()
        for baum in baeume:
            punkte = tree_report.used_points(self._tree, baum.link.passives)[0]   # wie "Points used"
            klasse = passive_tree.class_name_of(self._tree, baum.link.class_index,
                                                baum.link.ascendancy_index) or "?"
            item = QListWidgetItem(f"{baum.title} — {klasse}, {punkte} points"
                                   + (" (active in Path of Building)" if baum.active else ""))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if punkte else Qt.CheckState.Unchecked)
            liste.addItem(item)
        knoepfe = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        knoepfe.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        knoepfe.accepted.connect(fenster.accept)
        knoepfe.rejected.connect(fenster.reject)
        aufbau = QVBoxLayout(fenster)
        aufbau.addWidget(QLabel(f"This build has {len(baeume)} trees. Each one you tick "
                                "becomes a configuration named after it."))
        aufbau.addWidget(liste)
        aufbau.addWidget(knoepfe)
        # Hoch genug für alle Bäume (Pohx: zehn — mit fester Höhe war der
        # letzte abgeschnitten, nativ gesehen), höchstens 720 px.
        fenster.resize(600, min(720, liste.sizeHintForRow(0) * len(baeume) + 110))
        if fenster.exec() != QDialog.DialogCode.Accepted:
            return []
        return [b for i, b in enumerate(baeume)
                if liste.item(i).checkState() == Qt.CheckState.Checked]

    def _rename(self) -> None:
        key = self._target()
        if not key or key[0] != CONFIG:
            return
        neu = self._ask_name("Rename configuration", key[1])
        if not neu or neu == key[1]:
            return
        if not tree_history.rename_config(self._characters, self._name, key[1], neu):
            QMessageBox.warning(self, "Rename configuration",
                                f"A configuration named “{neu}” exists already.")
            return
        self._on_change()
        self._after(key, (CONFIG, neu))

    def _delete(self) -> None:
        """Löschen — bei einer Mehrfachauswahl alle gewählten
        Konfigurationen auf einmal (Verlauf und aktueller Baum bleiben)."""
        namen = [k[1] for k in self._targets() if k and k[0] == CONFIG]
        if not namen:
            return
        frage = (f"Delete “{namen[0]}”?" if len(namen) == 1
                 else f"Delete these {len(namen)} configurations?\n\n" + "\n".join(namen))
        title = "Delete configuration" if len(namen) == 1 else "Delete configurations"
        if QMessageBox.question(self, title, frage) != QMessageBox.StandardButton.Yes:
            return
        gewaehlt = self._selected()
        for name in namen:
            tree_history.delete_config(self._characters, self._name, name)
        self._on_change()
        self.refresh((CURRENT, None) if gewaehlt in [(CONFIG, n) for n in namen] else gewaehlt)

    def link_for(self, key) -> str | None:
        eintrag = self._entry(key)
        if eintrag is None or self._tree is None:
            return None
        return passive_tree.encode_url(self._tree, eintrag.get("passives") or {}, self._class)

    def _open_planner(self) -> None:
        link = self.link_for(self._target())
        if link:
            QDesktopServices.openUrl(QUrl(link))

    def _copy_link(self) -> None:
        link = self.link_for(self._target())
        if link:
            QGuiApplication.clipboard().setText(link)

    def _copy_text(self) -> None:
        QGuiApplication.clipboard().setText(self.markdown_for(self._target()))
