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
Eine Konfiguration entsteht aus dem aktuellen Baum oder aus einem
Planer-/PoB-Link; "Open in planner" zeigt jeden Baum grafisch im
offiziellen Planer, ohne dass PoE-VIEW2 selbst einen Baum zeichnet.

Das Fenster ändert nur die übergebenen Daten und ruft danach
``on_change`` — Speichern bleibt Sache des Hauptfensters.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QGuiApplication, QPalette
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSplitter, QTabWidget, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from poe_view.services import passive_tree, tree_history
from poe_view.services.passive_tree import Tree, TreeLinkError
from poe_view.ui import tree_report
from poe_view.ui.tree_graph import TreeGraph

CURRENT, HISTORY, CONFIG = "current", "history", "config"


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

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
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
        self.graph_search.setPlaceholderText("Find nodes, e.g. fire res…")
        self.graph_search.setClearButtonEnabled(True)
        self.graph_search.textChanged.connect(self.graph.highlight)
        self.graph_legend = QLabel()
        self.graph_legend.setWordWrap(True)
        leiste = QHBoxLayout()
        leiste.addWidget(self.graph_search, 1)
        leiste.addWidget(self.graph_reach)
        bild = QWidget()
        b_aufbau = QVBoxLayout(bild)
        b_aufbau.setContentsMargins(0, 0, 0, 0)
        b_aufbau.addLayout(leiste)
        b_aufbau.addWidget(self.graph, 1)
        b_aufbau.addWidget(self.graph_legend)
        self.tabs.addTab(bild, "Tree")
        self._graph_key = None
        # Einpassen erst, wenn das Bild sichtbar ist — ein verdeckter Reiter
        # hat keine Größe, und fitInView zoomte dann ins Leere (nativ gesehen).
        self._graph_fit_pending = False
        self.tabs.currentChanged.connect(self._fit_graph_if_pending)

        teiler = QSplitter()
        teiler.addWidget(self.list)
        teiler.addWidget(self.tabs)
        teiler.setStretchFactor(1, 3)

        self.save_button = QPushButton("Save current as…")
        self.import_button = QPushButton("Import link…")
        self.rename_button = QPushButton("Rename…")
        self.delete_button = QPushButton("Delete")
        self.planner_button = QPushButton("Open in planner")
        self.link_button = QPushButton("Copy link")
        self.copy_button = QPushButton("Copy as text")
        self.save_button.clicked.connect(self._save_current)
        self.import_button.clicked.connect(self._import_link)
        self.rename_button.clicked.connect(self._rename)
        self.delete_button.clicked.connect(self._delete)
        self.planner_button.clicked.connect(self._open_planner)
        self.link_button.clicked.connect(self._copy_link)
        self.copy_button.clicked.connect(self._copy_text)
        knoepfe = QHBoxLayout()
        for knopf in (self.save_button, self.import_button, self.rename_button,
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
        self.resize(1000, 700)
        self.refresh()

    # --- Liste ---------------------------------------------------------- #

    def refresh(self, select: tuple[str, object] | None = None) -> None:
        """Liste neu aufbauen; ``select`` = (Art, Schlüssel) danach wählen."""
        alt = select or self._selected()
        self.list.blockSignals(True)
        self.list.clear()
        aktuell = tree_history.current(self._characters, self._name)
        if aktuell:
            self._add("Current tree", (CURRENT, None), bold=True)
        konfigs = tree_history.configs(self._characters, self._name)
        if konfigs:
            self._header("Configurations")
            for name in sorted(konfigs, key=str.lower):
                self._add(f"  {name}", (CONFIG, name))
        verlauf = tree_history.history(self._characters, self._name)
        if verlauf:
            self._header("History")
            for index in range(len(verlauf) - 1, -1, -1):
                eintrag = verlauf[index]
                self._add(f"  {self._history_caption(verlauf, index)}", (HISTORY, index))
        self.list.blockSignals(False)
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
        if art == CURRENT:
            return tree_history.current(self._characters, self._name)
        if art == CONFIG:
            return tree_history.configs(self._characters, self._name).get(schluessel)
        verlauf = tree_history.history(self._characters, self._name)
        return verlauf[schluessel] if 0 <= schluessel < len(verlauf) else None

    # --- Anzeige -------------------------------------------------------- #

    def _respec_blocks(self, key) -> list:
        """Der Umbau zum Gewählten: bei einer Konfiguration vom aktuellen
        Baum aus, beim Verlauf vom Eintrag davor; sonst nichts."""
        eintrag = self._entry(key)
        if eintrag is None or self._tree is None or not key:
            return []
        art, schluessel = key
        aktuell = tree_history.current(self._characters, self._name)
        if art == CONFIG and aktuell:
            return tree_report.respec_blocks(
                self._tree, aktuell.get("passives") or {}, eintrag.get("passives") or {},
                title=f"Respec: current tree → {schluessel}")
        if art == HISTORY and schluessel > 0:
            verlauf = tree_history.history(self._characters, self._name)
            return tree_report.respec_blocks(
                self._tree, verlauf[schluessel - 1].get("passives") or {},
                eintrag.get("passives") or {}, title="Changes from the tree before")
        return []

    def _tree_blocks(self, key, include_reach: bool) -> list:
        bloecke = tree_report.tree_blocks(self._entry(key), self._tree,
                                          character_class=self._class,
                                          include_reach=include_reach)
        if key and key[0] == CONFIG:
            bloecke[0].title = f"Configuration: {key[1]}"
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
            return
        vergleich = None
        if key[0] == CONFIG:
            aktuell = tree_history.current(self._characters, self._name)
            vergleich = (aktuell or {}).get("passives")
        elif key[0] == HISTORY and key[1] > 0:
            vergleich = tree_history.history(self._characters, self._name)[key[1] - 1].get(
                "passives")
        self.graph.show_tree(eintrag.get("passives") or {}, self._class,
                             compare_to=vergleich, show_reach=self.graph_reach.isChecked(),
                             dark=self._dark())
        self.graph.highlight(self.graph_search.text())
        self.graph_reach.setEnabled(vergleich is None)
        self.graph_legend.setText(
            ("Green: allocate · red: refund · white: unchanged · " if vergleich is not None
             else "Filled: allocated (colour = theme) · ring: within reach · ")
            + "hollow: not allocated · yellow ring: search match · wheel: zoom · drag: move")
        if fit:
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
        if umbau:
            self.tabs.setCurrentIndex(0)
        elif self.tabs.currentIndex() == 0:
            self.tabs.setCurrentIndex(1)
        if self._entry(key) is None or self._tree is None:
            self.text.setMarkdown(self.markdown_for(key))
        else:
            self.text.setHtml(tree_report.to_html(self._tree_blocks(key, include_reach=False),
                                                  dark=dunkel))
        self._fill_reach(key)
        self._fill_graph(key, fit=key != self._graph_key)
        self._graph_key = key
        ist_konfig = bool(key) and key[0] == CONFIG
        self.rename_button.setEnabled(ist_konfig)
        self.delete_button.setEnabled(ist_konfig)
        hat_baum = self._entry(key) is not None and self._tree is not None
        self.planner_button.setEnabled(hat_baum)
        self.link_button.setEnabled(hat_baum)
        self.copy_button.setEnabled(self._entry(key) is not None)
        self.save_button.setEnabled(
            tree_history.current(self._characters, self._name) is not None)
        self.import_button.setEnabled(self._tree is not None)
        self.hint.setText("Ruthless tree" if self._tree is not None and self._tree.ruthless
                          else "")

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

    def _save_current(self) -> None:
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

    def _import_link(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Import tree link",
            "Paste a passive tree link (official planner or Path of Building):")
        if not ok or not text.strip():
            return
        try:
            link = passive_tree.decode_url(text)
        except TreeLinkError as exc:
            QMessageBox.warning(self, "Import tree link", f"That is not a tree link ({exc}).")
            return
        klasse = passive_tree.class_name_of(self._tree, link.class_index, link.ascendancy_index)
        eigene = self._tree.class_ids.get(self._class, (None, None))[0]
        if eigene is not None and link.class_index != eigene:
            if QMessageBox.question(
                    self, "Import tree link",
                    f"This tree is for a {klasse or 'different class'}, not a {self._class}. "
                    "Import it anyway?") != QMessageBox.StandardButton.Yes:
                return
        name = self._ask_name("Name the configuration")
        if not name or not self._confirm_overwrite(name):
            return
        aktuell = tree_history.current(self._characters, self._name) or {}
        tree_history.save_config(self._characters, self._name, name, link.passives,
                                 level=aktuell.get("level") or 0,
                                 ruthless=self._tree.ruthless, source="link")
        self._on_change()
        self.refresh((CONFIG, name))

    def _rename(self) -> None:
        key = self._selected()
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
        self.refresh((CONFIG, neu))

    def _delete(self) -> None:
        key = self._selected()
        if not key or key[0] != CONFIG:
            return
        if QMessageBox.question(self, "Delete configuration",
                                f"Delete “{key[1]}”?") != QMessageBox.StandardButton.Yes:
            return
        tree_history.delete_config(self._characters, self._name, key[1])
        self._on_change()
        self.refresh((CURRENT, None))

    def link_for(self, key) -> str | None:
        eintrag = self._entry(key)
        if eintrag is None or self._tree is None:
            return None
        return passive_tree.encode_url(self._tree, eintrag.get("passives") or {}, self._class)

    def _open_planner(self) -> None:
        link = self.link_for(self._selected())
        if link:
            QDesktopServices.openUrl(QUrl(link))

    def _copy_link(self) -> None:
        link = self.link_for(self._selected())
        if link:
            QGuiApplication.clipboard().setText(link)

    def _copy_text(self) -> None:
        QGuiApplication.clipboard().setText(self.markdown_for(self._selected()))
