"""Hauptfenster: verdrahtet Worker-Signale mit den Widgets (Mockup: docs/ui-mockup.html).

Alle Slots hier laufen im Main-Thread (Qt queued connections aus dem Worker).
Die UI löst API-Arbeit ausschließlich über ``worker.submit(Job)`` aus.

LabVIEW-Äquivalent: das Main-VI mit Event-Struktur (User Events + UI-Events).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QProgressBar,
                               QProgressDialog, QSizePolicy, QSplitter,
                               QTableView, QToolBar, QVBoxLayout, QWidget)

from poe_view import config
from poe_view.api.models import Character, Item, StashTab
from poe_view.services import data_cache
from poe_view.services.api_worker import (ApiWorker, BootstrapJob,
                                          FetchAllItemsJob,
                                          FetchCharactersJob, FetchIconJob,
                                          FetchLeaguesJob, FetchStashItemsJob,
                                          FetchStashListJob, LoginJob,
                                          LogoutJob)
from poe_view.services.csv_export import export_items, sanitize_filename
from poe_view.ui.character_list import CharacterList
from poe_view.ui.item_detail import ItemDetail
from poe_view.ui.item_table import ItemFilterProxy, ItemTableModel
from poe_view.ui.rate_limit_dashboard import RateLimitDashboard
from poe_view.ui.stash_tree import StashTree

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    # Hintergrund-Auto-Refresh (Nutzer-Feedback): nie jünger als 1 Tag anfassen
    # (dafür reicht der manuelle Refresh völlig), und dem Nutzer immer mind.
    # die Hälfte des Rate-Limit-Budgets für manuelle Klicks übrig lassen.
    AUTO_REFRESH_INTERVAL_MS = 20_000
    AUTO_REFRESH_MIN_AGE = timedelta(days=1)
    AUTO_REFRESH_MIN_HEADROOM = 0.5

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PoE-VIEW2")
        self.resize(1100, 700)

        self._account_name: str = ""
        self._stash_trees: dict[str, list[StashTab]] = {}      # Liga → Baumstruktur
        self._items: dict[str, dict[str, list[Item]]] = {}     # Liga → {stash_id: Items}
        self._last_loaded: dict[str, dict[str, str]] = {}      # Liga → {stash_id: ISO-Zeitstempel}
        self._leaf_stashes: list[StashTab] = []                # abgeflacht, NUR aktuelle Liga
        self._all_characters: list[Character] = []             # ligenübergreifend, ungefiltert
        self._current_league: str = ""
        self._current_tab_name: str = ""
        self._bulk_dialog: QProgressDialog | None = None
        self._showing_aggregate = False
        self._worker_busy = False
        self._auto_refresh_counts: dict[str, int] = {}  # Liga → auto-aktualisierte Tabs (Session)
        self._restore_cached_data()

        self.worker = ApiWorker()
        self._build_ui()
        self._connect_worker()
        self.worker.start()
        self.worker.submit(BootstrapJob())

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(self.AUTO_REFRESH_INTERVAL_MS)
        self._auto_refresh_timer.timeout.connect(self._maybe_auto_refresh)
        self._auto_refresh_timer.start()

        if not config.is_configured():
            self._status_msg.setText(
                "⚠ POE_CONTACT_EMAIL fehlt in der .env — bitte .env.example kopieren und ausfüllen.")

    # ------------------------------------------------------------------ #

    def _restore_cached_data(self) -> None:
        """Lädt den letzten Daten-Cache (überlebt einen Neustart) — rein in-memory.

        Das Rendern übernimmt der normale Ablauf, sobald eine Liga aktiv
        wird (_on_league_changed → _activate_stash_tree), genau wie bei
        frisch von der API geladenen Daten.
        """
        cached = data_cache.load()
        if cached is None:
            return
        self._all_characters = cached.characters
        self._stash_trees = cached.stash_trees
        self._items = cached.items_by_league
        self._last_loaded = cached.last_loaded
        log.info("Daten-Cache geladen: %d Charaktere, %d Liga(en)",
                 len(cached.characters), len(cached.stash_trees))

    def _persist_cache(self) -> None:
        data = data_cache.CachedData()
        data.account_name = self._account_name
        data.characters = self._all_characters
        data.stash_trees = self._stash_trees
        data.items_by_league = self._items
        data.last_loaded = self._last_loaded
        data_cache.save(data)

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

        # Linke Seite: Charakterliste (flach) oben, Stash-Baum unten — je mit
        # eigener Überschrift statt eines gemeinsamen Wrapper-Baums (spart
        # eine Ebene, Nutzer-Feedback).
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        char_label = QLabel("Charaktere")
        char_label.setStyleSheet("font-weight: 600; padding: 2px 4px;")
        self.character_list = CharacterList()
        self.character_list.character_selected.connect(self._on_character_selected)
        self.character_list.setMaximumHeight(220)

        stash_label = QLabel("Stash")
        stash_label.setStyleSheet("font-weight: 600; padding: 2px 4px;")
        self.tree = StashTree()
        self.tree.stash_selected.connect(self._on_stash_selected)
        self.tree.stash_refresh_requested.connect(self._on_stash_refresh)

        left_layout.addWidget(char_label)
        left_layout.addWidget(self.character_list)
        left_layout.addWidget(stash_label)
        left_layout.addWidget(self.tree, stretch=1)

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
        splitter.addWidget(left_panel)
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
        # Range (0, 0) macht aus der QProgressBar einen "busy"-Indikator mit
        # eingebauter Lauf-Animation (kein eigener QTimer/keine Assets nötig).
        self._busy_indicator = QProgressBar()
        self._busy_indicator.setRange(0, 0)
        self._busy_indicator.setFixedSize(90, 14)
        self._busy_indicator.setTextVisible(False)
        self._busy_indicator.hide()
        self.statusBar().addWidget(self._busy_indicator)
        # Sichtbarer Nachweis, dass der Hintergrund-Auto-Refresh arbeitet
        # (Nutzer-Feedback: "Bist du dir sicher, dass das funktioniert?").
        self._auto_refresh_label = QLabel("")
        self.statusBar().addPermanentWidget(self._auto_refresh_label)
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
        w.status.connect(self._on_status)
        w.busy_changed.connect(self._on_busy_changed)
        w.job_error.connect(self._on_error)
        w.bulk_progress.connect(self._on_bulk_progress)
        w.bulk_finished.connect(self._on_bulk_finished)

    # --- Worker-Slots (Main-Thread) ------------------------------------ #

    def _on_logged_in(self, account_name: str) -> None:
        self._account_name = account_name
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
        self._showing_aggregate = False
        self._apply_character_league_filter()
        cached_tree = self._stash_trees.get(league)
        if cached_tree is not None:
            # Sofort anzeigen (aus dieser Session oder vom letzten Programmstart) …
            self._activate_stash_tree(cached_tree)
        else:
            self.tree.set_stashes([])
            self._leaf_stashes = []
        # … und trotzdem im Hintergrund bestätigen/aktualisieren (wie bisher).
        self.worker.submit(FetchStashListJob(league))

    def _on_characters(self, characters: list[Character]) -> None:
        """/character liefert ligenübergreifend; gefiltert wird lokal übers Dropdown.

        Kein eigener Liga-Level in der Liste (spart eine Ebene) — das
        Liga-Dropdown steuert Charaktere UND Stash-Tabs gemeinsam, ein
        Wechsel zwischen Ligen ist bei Items/Stash ohnehin nicht möglich.
        """
        self._all_characters = characters
        self._apply_character_league_filter()
        self._persist_cache()

    def _apply_character_league_filter(self) -> None:
        filtered = [c for c in self._all_characters if c.league == self._current_league]
        self.character_list.set_characters(filtered)

    def _activate_stash_tree(self, stashes: list[StashTab]) -> None:
        """Baum rendern + abgeflachte Liste aktualisieren — für Live- UND Cache-Daten."""
        last_loaded = self._last_loaded.get(self._current_league, {})
        self.tree.set_stashes(stashes, last_loaded=last_loaded)
        self._leaf_stashes = self._flatten_stashes(stashes)
        self._update_auto_refresh_label()

    def _on_stash_list(self, stashes: list[StashTab]) -> None:
        self._stash_trees[self._current_league] = stashes
        self._activate_stash_tree(stashes)
        self._persist_cache()

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
        league_items = self._items.get(self._current_league, {})
        if stash_id in league_items:
            # Speicher-/Datei-Cache: kein erneuter API-Call (Doku §5)
            self._show_items(league_items[stash_id], name)
            return
        self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name))

    def _on_stash_refresh(self, stash_id: str, name: str) -> None:
        """Klick auf den Refresh-Button eines Tabs — bewusst AM Cache vorbei."""
        self._showing_aggregate = False
        self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name))

    def _on_stash_items(self, league: str, stash_id: str, name: str,
                        items: list[Item], silent: bool) -> None:
        """``league`` kommt aus dem Signal (nicht ``self._current_league``!) —
        sonst würde ein spät eintreffender Hintergrund-Job die Daten der
        MOMENTAN aktiven Liga verfälschen, falls der Nutzer zwischenzeitlich
        die Liga gewechselt hat."""
        self._last_loaded.setdefault(league, {})[stash_id] = datetime.now(timezone.utc).isoformat()
        self._items.setdefault(league, {})[stash_id] = items
        if silent:
            self._auto_refresh_counts[league] = self._auto_refresh_counts.get(league, 0) + 1
        self._persist_cache()
        if league != self._current_league:
            return
        self.tree.mark_loaded(stash_id, self._last_loaded[league][stash_id])
        if silent:
            self._update_auto_refresh_label()
        elif not self._showing_aggregate:
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
        league_items = self._items.get(self._current_league, {})
        to_fetch = [s for s in self._leaf_stashes if s.id not in league_items]
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
        self._current_tab_name = "Alle Tabs"
        league_items = self._items.get(self._current_league, {})
        items: list[Item] = []
        sources: list[str] = []
        for stash in self._leaf_stashes:
            cached = league_items.get(stash.id)
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
        """Dateiname-Vorschlag: Liga + (aktiver Filtertext, sonst Tab-/Aggregat-Name).

        Die Liga gehört immer mit rein — Items sind nie liga-übergreifend
        gültig, das soll auch am Dateinamen erkennbar sein (Nutzer-Feedback).
        """
        filter_text = self._filter_edit.text().strip()
        base = sanitize_filename(filter_text) if filter_text \
            else sanitize_filename(self._current_tab_name)
        parts = [p for p in (sanitize_filename(self._current_league, ""), base) if p]
        return f"poe-view2-{'-'.join(parts)}.csv"

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

    def _on_status(self, text: str) -> None:
        """Reiner Verlaufstext — Busy-Zustand kommt separat über busy_changed
        (siehe FALLSTRICKE_UND_WORKAROUNDS.md #8)."""
        self._status_msg.setText(text)

    def _on_busy_changed(self, busy: bool) -> None:
        self._busy_indicator.setVisible(busy)
        self._worker_busy = busy

    def _on_error(self, message: str) -> None:
        self._status_msg.setText(f"Fehler: {message}")
        log.error("%s", message)

    def _refresh(self) -> None:
        """Stash-Liste + Charaktere neu laden; Item-Daten bleiben unangetastet
        (dafür gibt es die gezielten Refresh-Buttons je Tab im Baum)."""
        if self._current_league:
            self.worker.submit(FetchStashListJob(self._current_league))
        self.worker.submit(FetchCharactersJob())

    # --- Hintergrund-Auto-Refresh (Nutzer-Feedback) ---------------------- #

    def _maybe_auto_refresh(self) -> None:
        """Läuft alle paar Sekunden per QTimer; lädt höchstens EINEN Tab neu,
        und nur, wenn genug Rate-Limit-Budget für manuelle Klicks übrig
        bleibt (Doku §4.8)."""
        if not self._current_league or self._worker_busy or self._bulk_dialog is not None:
            return
        if self.worker.rate_limiter.headroom_fraction() < self.AUTO_REFRESH_MIN_HEADROOM:
            return
        candidate = self._pick_auto_refresh_candidate()
        if candidate is not None:
            self.worker.submit(FetchStashItemsJob(
                self._current_league, candidate.id, candidate.name, silent=True))

    def _update_auto_refresh_label(self) -> None:
        """Zähler rechts in der Statusleiste: „Auto-Refresh: X von Y Stash-Tabs aktualisiert“."""
        total = len(self._leaf_stashes)
        if not total:
            self._auto_refresh_label.setText("")
            return
        count = self._auto_refresh_counts.get(self._current_league, 0)
        self._auto_refresh_label.setText(
            f"Auto-Refresh: {count} von {total} Stash-Tabs aktualisiert")

    # Noch nie geladene Tabs zählen als "unendlich alt" — sie kommen vor
    # jedem tatsächlich datierten Tab dran (siehe _pick_auto_refresh_candidate).
    _NEVER_LOADED = datetime.min.replace(tzinfo=timezone.utc)

    def _pick_auto_refresh_candidate(self) -> StashTab | None:
        """Ältester Tab der aktuellen Liga — inkl. noch nie geladener Tabs (⬇).

        Noch nie geladene Tabs gelten als "unendlich alt" und werden IMMER
        als Kandidat betrachtet (die 1-Tag-Schonfrist gilt nur für bereits
        bekannte Daten — es gibt nichts zu schonen, wenn noch gar keine
        Daten da sind). So füllt sich der Stash über die Zeit von selbst,
        ohne dass 391 Tabs einzeln angeklickt werden müssen (Nutzer-Feedback).
        Tabs, deren Name "Remove-only" enthält, werden nachrangig behandelt
        — nur falls es sonst keinen anderen Kandidaten gibt, kommen sie doch dran.
        """
        league_loaded = self._last_loaded.get(self._current_league, {})
        now = datetime.now(timezone.utc)
        candidates: list[tuple[datetime, StashTab]] = []
        for stash in self._leaf_stashes:
            iso = league_loaded.get(stash.id)
            if iso is None:
                candidates.append((self._NEVER_LOADED, stash))
                continue
            loaded_at = datetime.fromisoformat(iso)
            if now - loaded_at >= self.AUTO_REFRESH_MIN_AGE:
                candidates.append((loaded_at, stash))
        if not candidates:
            return None
        preferred = [pair for pair in candidates if "remove-only" not in pair[1].name.lower()]
        pool = preferred or candidates
        return min(pool, key=lambda pair: pair[0])[1]  # älteste (bzw. nie geladene) zuerst

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
