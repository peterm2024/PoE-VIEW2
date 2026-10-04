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
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSplitter,
                               QTextBrowser, QVBoxLayout, QWidget)

from poe_view.services import passive_tree, tree_history
from poe_view.services.passive_tree import Tree, TreeLinkError
from poe_view.ui.character_sheet import respec_section, tree_section

CURRENT, HISTORY, CONFIG = "current", "history", "config"


class PassiveTreeDialog(QDialog):
    def __init__(self, name: str, class_name: str, characters: dict, tree: Tree | None,
                 on_change: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Passive tree — {name}")
        self._name = name
        self._class = class_name
        self._characters = characters
        self._tree = tree
        self._on_change = on_change

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)

        teiler = QSplitter()
        teiler.addWidget(self.list)
        teiler.addWidget(self.text)
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

    def markdown_for(self, key) -> str:
        """Der Text rechts — auch das, was "Copy as text" kopiert."""
        eintrag = self._entry(key)
        if eintrag is None:
            return ("*No tree recorded for this character yet. It arrives with the "
                    "next refresh of the character.*")
        if self._tree is None:
            return ("*GGG's tree data has not been downloaded yet — try again in a "
                    "minute.*")
        art, schluessel = key
        zeilen: list[str] = []
        aktuell = tree_history.current(self._characters, self._name)
        if art == CONFIG and aktuell:
            zeilen += respec_section(self._tree, aktuell.get("passives") or {},
                                     eintrag.get("passives") or {},
                                     title=f"Respec: current tree → {schluessel}")
        elif art == HISTORY and schluessel > 0:
            verlauf = tree_history.history(self._characters, self._name)
            zeilen += respec_section(self._tree, verlauf[schluessel - 1].get("passives") or {},
                                     eintrag.get("passives") or {},
                                     title="Changes from the tree before")
        abschnitt = tree_section(eintrag, self._tree, character_class=self._class)
        if art == CONFIG:
            abschnitt[0] = f"## Configuration: {schluessel}"
        return "\n".join(zeilen + abschnitt)

    def _show_selected(self) -> None:
        key = self._selected()
        self.text.setMarkdown(self.markdown_for(key))
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
