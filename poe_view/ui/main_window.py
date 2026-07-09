"""Hauptfenster: verdrahtet Worker-Signale mit den Widgets (Mockup: docs/ui-mockup.html).

Alle Slots hier laufen im Main-Thread (Qt queued connections aus dem Worker).
Die UI löst API-Arbeit ausschließlich über ``worker.submit(Job)`` aus.

LabVIEW-Äquivalent: das Main-VI mit Event-Struktur (User Events + UI-Events).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QProgressDialog,
                               QSizePolicy, QSplitter, QTableView, QToolBar,
                               QVBoxLayout, QWidget)

from poe_view import config
from poe_view.api.models import Character, Item, StashTab
from poe_view.services.api_worker import (ApiWorker, BootstrapJob,
                                          FetchAllItemsJob,
                                          FetchCharactersJob, FetchIconJob,
                                          FetchLeaguesJob, FetchStashItemsJob,
                                          FetchStashListJob, LoginJob,
                                          LogoutJob)
from poe_view.services.csv_export import export_items, sanitize_filename
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
        self._leaf_stashes: list[StashTab] = []  # abgeflacht, ohne Ordner
        self._all_characters: list[Character] = []  # ligenübergreifend, ungefiltert
        self._current_league: str = ""
        self._current_tab_name: str = ""
        self._bulk_dialog: QProgressDialog | None = None
        self._showing_aggregate = False

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

        self._load_all_action = QAction("⇊ Alle Tabs laden", self)
        self._load_all_action.setToolTip(
            "Items aller Stash-Tabs der aktuellen Liga nacheinander laden "
            "(kann je nach Tab-Anzahl und Rate-Limit länger dauern)")
        self._load_all_action.triggered.connect(self._load_all_items)
        toolbar.addAction(self._load_all_action)

        self._export_action = QAction("💾 CSV exportieren", self)
        self._export_action.setToolTip("Aktuell angezeigte (gefilterte) Items als CSV speichern")
        self._export_action.triggered.connect(self._export_csv)
        toolbar.addAction(self._export_action)

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
        self.table.setColumnWidth(1, 110)
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
        w.bulk_progress.connect(self._on_bulk_progress)
        w.bulk_finished.connect(self._on_bulk_finished)

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
        self._leaf_stashes = []
        self.worker.submit(FetchStashListJob(league))
        self._apply_character_league_filter()

    def _on_characters(self, characters: list[Character]) -> None:
        """/character liefert ligenübergreifend; gefiltert wird lokal übers Dropdown.

        Kein eigener Liga-Level im Baum (spart eine Ebene) — das Liga-Dropdown
        steuert Charaktere UND Stash-Tabs gemeinsam, ein Wechsel zwischen
        Ligen ist bei Items/Stash ohnehin nicht möglich.
        """
        self._all_characters = characters
        self._apply_character_league_filter()

    def _apply_character_league_filter(self) -> None:
        filtered = [c for c in self._all_characters if c.league == self._current_league]
        self.tree.set_characters(filtered)

    def _on_stash_list(self, stashes: list[StashTab]) -> None:
        self.tree.set_stashes(stashes)
        self._leaf_stashes = self._flatten_stashes(stashes)

    @staticmethod
    def _flatten_stashes(stashes: list[StashTab]) -> list[StashTab]:
        """Rekursiv alle Nicht-Ordner-Tabs einsammeln (Reihenfolge wie im Baum)."""
        flat: list[StashTab] = []
        for stash in stashes:
            if stash.is_folder:
                flat.extend(MainWindow._flatten_stashes(stash.children))
            else:
                flat.append(stash)
        return flat

    def _on_stash_selected(self, stash_id: str, name: str) -> None:
        self._showing_aggregate = False
        if stash_id in self._items_cache:
            # Speicher-Cache: kein erneuter API-Call (Intention, siehe Doku §5)
            self._show_items(self._items_cache[stash_id], name)
            return
        self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name))

    def _on_stash_items(self, stash_id: str, name: str, items: list[Item]) -> None:
        self._items_cache[stash_id] = items
        if not self._showing_aggregate:
            self._show_items(items, name)

    def _show_items(self, items: list[Item], name: str) -> None:
        self._current_tab_name = name
        self.table_model.set_items(items, [name] * len(items))
        self._status_msg.setText(f"{name}: {len(items)} Items")

    # --- Alle Tabs laden (Bulk) ----------------------------------------- #

    def _load_all_items(self) -> None:
        if self._bulk_dialog is not None:
            return  # läuft schon
        if not self._leaf_stashes:
            QMessageBox.information(
                self, "Alle Tabs laden",
                "Keine Stash-Tabs geladen — bitte zuerst eine Liga wählen.")
            return
        to_fetch = [s for s in self._leaf_stashes if s.id not in self._items_cache]
        if not to_fetch:
            self._show_aggregate()  # schon alles im Cache
            return

        self._bulk_dialog = QProgressDialog(
            "Lade Stash-Tabs …", "Abbrechen", 0, len(to_fetch), self)
        self._bulk_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._bulk_dialog.setMinimumDuration(0)
        self._bulk_dialog.canceled.connect(self.worker.cancel_bulk)
        self.worker.submit(FetchAllItemsJob(self._current_league, to_fetch))

    def _on_bulk_progress(self, done: int, total: int, name: str) -> None:
        if self._bulk_dialog is not None:
            self._bulk_dialog.setLabelText(f"Lade Stash-Tab {done}/{total}: {name}")
            self._bulk_dialog.setValue(done)

    def _on_bulk_finished(self, success: int, total: int) -> None:
        if self._bulk_dialog is not None:
            self._bulk_dialog.close()
            self._bulk_dialog = None
        self._status_msg.setText(f"Alle Tabs geladen: {success}/{total} erfolgreich.")
        self._show_aggregate()

    def _show_aggregate(self) -> None:
        """Items aller bereits geladenen Tabs zusammen anzeigen (lokal filter-/exportierbar)."""
        self._showing_aggregate = True
        self._current_tab_name = f"alle-tabs-{self._current_league}"
        items: list[Item] = []
        sources: list[str] = []
        for stash in self._leaf_stashes:
            cached = self._items_cache.get(stash.id)
            if cached is None:
                continue
            items.extend(cached)
            sources.extend([stash.name] * len(cached))
        self.table_model.set_items(items, sources)
        self._status_msg.setText(f"Alle Tabs: {len(items)} Items gesamt")

    # --- CSV-Export ------------------------------------------------------ #

    def _export_csv(self) -> None:
        rows = self._visible_rows()
        if not rows:
            QMessageBox.information(self, "CSV-Export", "Keine Items zum Exportieren geladen.")
            return
        default_path = str(config.downloads_dir() / self._default_export_filename())
        path, _ = QFileDialog.getSaveFileName(
            self, "Items als CSV exportieren", default_path, "CSV-Dateien (*.csv)")
        if not path:
            return
        count = export_items(path, rows)
        self._status_msg.setText(f"{count} Items nach {path} exportiert.")

    def _default_export_filename(self) -> str:
        """Dateiname-Vorschlag: aktiver Filtertext, sonst der Tab-/Aggregat-Name."""
        filter_text = self._filter_edit.text().strip()
        base = sanitize_filename(filter_text) if filter_text \
            else sanitize_filename(self._current_tab_name)
        return f"poe-view2-{base}.csv"

    def _visible_rows(self) -> list[tuple[str, Item]]:
        """(Tab-Name, Item)-Paare für die AKTUELL sichtbaren (gefilterten) Zeilen."""
        rows: list[tuple[str, Item]] = []
        for row in range(self.proxy.rowCount()):
            source_idx = self.proxy.mapToSource(self.proxy.index(row, 0))
            item = self.table_model.item_at(source_idx.row())
            if item is not None:
                rows.append((self.table_model.source_at(source_idx.row()), item))
        return rows

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
        if not self.worker.wait(3000):
            log.warning("ApiWorker reagierte nicht innerhalb von 3s auf stop() — erzwinge Beendigung.")
            self.worker.terminate()
            self.worker.wait(1000)
        event.accept()


def show_config_hint(parent=None) -> None:
    QMessageBox.warning(
        parent, "Konfiguration fehlt",
        "Bitte .env.example nach .env kopieren und POE_CONTACT_EMAIL eintragen.\n"
        "Die GGG-API verlangt eine Kontaktadresse im User-Agent.")
