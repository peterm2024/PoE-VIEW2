"""Hauptfenster: verdrahtet Worker-Signale mit den Widgets (Mockup: docs/ui-mockup.html).

Alle Slots hier laufen im Main-Thread (Qt queued connections aus dem Worker).
Die UI löst API-Arbeit ausschließlich über ``worker.submit(Job)`` aus.

LabVIEW-Äquivalent: das Main-VI mit Event-Struktur (User Events + UI-Events).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QComboBox, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QSizePolicy, QSplitter,
                               QTableView, QToolBar, QVBoxLayout, QWidget)

from poe_view import config
from poe_view.api.models import Character, Item, StashTab
from poe_view.services.api_worker import (ApiWorker, BootstrapJob,
                                          FetchCharactersJob, FetchIconJob,
                                          FetchLeaguesJob, FetchStashItemsJob,
                                          FetchStashListJob, LoginJob,
                                          LogoutJob)
from poe_view.ui.item_detail import ItemDetail
from poe_view.ui.item_table import ItemFilterProxy, ItemTableModel
from poe_view.ui.rate_limit_dashboard import RateLimitDashboard
from poe_view.ui.stash_tree import StashTree

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PoE-VIEW2")
        self.resize(1100, 700)

        self._items_cache: dict[str, list[Item]] = {}  # stash_id → Items
        self._current_league: str = ""

        self.worker = ApiWorker()
        self._build_ui()
        self._connect_worker()
        self.worker.start()
        self.worker.submit(BootstrapJob())

        if not config.is_configured():
            self._status_msg.setText(
                "⚠ POE_CONTACT_EMAIL fehlt in der .env — bitte .env.example kopieren und ausfüllen.")

    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._login_action = QAction("🔑 Login", self)
        self._login_action.triggered.connect(lambda: self.worker.submit(LoginJob()))
        toolbar.addAction(self._login_action)

        self._refresh_action = QAction("⟳ Aktualisieren", self)
        self._refresh_action.triggered.connect(self._refresh)
        toolbar.addAction(self._refresh_action)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Liga: "))
        self._league_combo = QComboBox()
        self._league_combo.setMinimumWidth(160)
        self._league_combo.currentTextChanged.connect(self._on_league_changed)
        toolbar.addWidget(self._league_combo)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("🔍 Item-Filter (lokal, ohne API-Call)")
        self._filter_edit.setFixedWidth(260)
        toolbar.addWidget(self._filter_edit)

        # Linke Seite: Baum
        self.tree = StashTree()
        self.tree.stash_selected.connect(self._on_stash_selected)
        self.tree.character_selected.connect(self._on_character_selected)

        # Rechte Seite: Tabelle + Detail
        self.table_model = ItemTableModel(
            icon_requester=lambda url: self.worker.submit(FetchIconJob(url)))
        self.proxy = ItemFilterProxy()
        self.proxy.setSourceModel(self.table_model)
        self._filter_edit.textChanged.connect(self.proxy.setFilterFixedString)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 36)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_selected)

        self.detail = ItemDetail()
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.table, stretch=1)
        right_layout.addWidget(self.detail)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 840])

        self.dashboard = RateLimitDashboard()
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self.dashboard)
        self.setCentralWidget(central)

        self._status_msg = QLabel("Starte …")
        self.statusBar().addWidget(self._status_msg, stretch=1)
        self.statusBar().addPermanentWidget(QLabel(config.DISCLAIMER))

    def _connect_worker(self) -> None:
        w = self.worker
        w.logged_in.connect(self._on_logged_in)
        w.login_required.connect(self._on_login_required)
        w.leagues_loaded.connect(self._on_leagues)
        w.characters_loaded.connect(self._on_characters)
        w.stash_list_loaded.connect(self._on_stash_list)
        w.stash_items_loaded.connect(self._on_stash_items)
        w.icon_loaded.connect(self._on_icon)
        w.rate_limit_changed.connect(self.dashboard.update_state)
        w.status.connect(self._status_msg.setText)
        w.job_error.connect(self._on_error)

    # --- Worker-Slots (Main-Thread) ------------------------------------ #

    def _on_logged_in(self, account_name: str) -> None:
        self._login_action.setText(f"⚷ {account_name}")
        self._login_action.setEnabled(False)
        self.worker.submit(FetchLeaguesJob())
        self.worker.submit(FetchCharactersJob())

    def _on_login_required(self, reason: str) -> None:
        self._login_action.setEnabled(True)
        self._login_action.setText("🔑 Login")
        self._status_msg.setText(reason)

    def _on_leagues(self, leagues: list[str]) -> None:
        self._league_combo.blockSignals(True)
        self._league_combo.clear()
        self._league_combo.addItems(leagues)
        self._league_combo.blockSignals(False)
        if leagues:
            self._on_league_changed(self._league_combo.currentText())

    def _on_league_changed(self, league: str) -> None:
        if not league or league == self._current_league:
            return
        self._current_league = league
        self._items_cache.clear()
        self.worker.submit(FetchStashListJob(league))

    def _on_characters(self, characters: list[Character]) -> None:
        self.tree.set_characters(characters)

    def _on_stash_list(self, stashes: list[StashTab]) -> None:
        self.tree.set_stashes(stashes)

    def _on_stash_selected(self, stash_id: str, name: str) -> None:
        if stash_id in self._items_cache:
            # Speicher-Cache: kein erneuter API-Call (Intention, siehe Doku §5)
            self._show_items(self._items_cache[stash_id], name)
            return
        self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name))

    def _on_stash_items(self, stash_id: str, name: str, items: list[Item]) -> None:
        self._items_cache[stash_id] = items
        self._show_items(items, name)

    def _show_items(self, items: list[Item], name: str) -> None:
        self.table_model.set_items(items)
        self._status_msg.setText(f"{name}: {len(items)} Items")

    def _on_character_selected(self, char: Character) -> None:
        self._status_msg.setText(
            f"{char.name} — {char.class_} {char.level} ({char.league}). "
            "Charakter-Equipment-Ansicht folgt in einer späteren Version.")

    def _on_icon(self, url: str, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.table_model.set_icon(url, pixmap)

    def _on_row_selected(self, current, _previous) -> None:
        source_idx = self.proxy.mapToSource(current)
        item = self.table_model.item_at(source_idx.row())
        if item:
            self.detail.show_item(item, self.table_model.pixmap_for(item))

    def _on_error(self, message: str) -> None:
        self._status_msg.setText(f"Fehler: {message}")
        log.error("%s", message)

    def _refresh(self) -> None:
        self._items_cache.clear()
        if self._current_league:
            self.worker.submit(FetchStashListJob(self._current_league))
        self.worker.submit(FetchCharactersJob())

    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:  # noqa: N802
        self.worker.stop()
        self.worker.wait(3000)
        event.accept()


def show_config_hint(parent=None) -> None:
    QMessageBox.warning(
        parent, "Konfiguration fehlt",
        "Bitte .env.example nach .env kopieren und POE_CONTACT_EMAIL eintragen.\n"
        "Die GGG-API verlangt eine Kontaktadresse im User-Agent.")
