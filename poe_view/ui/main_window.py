"""Hauptfenster: verdrahtet Worker-Signale mit den Widgets (Mockup: docs/ui-mockup.html).

Alle Slots hier laufen im Main-Thread (Qt queued connections aus dem Worker).
Die UI löst API-Arbeit ausschließlich über ``worker.submit(Job)`` aus.

LabVIEW-Äquivalent: das Main-VI mit Event-Struktur (User Events + UI-Events).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QProgressDialog, QSizePolicy,
                               QSplitter, QTableView, QToolBar, QVBoxLayout,
                               QWidget, QWidgetAction)

from poe_view import config
from poe_view.api.models import Character, Item, StashTab, dominant_category
from poe_view.services import data_cache
from poe_view.services.api_worker import (ApiWorker, BootstrapJob,
                                          FetchAllItemsJob,
                                          FetchCharacterItemsJob,
                                          FetchCharactersJob, FetchIconJob,
                                          FetchLeaguesJob, FetchStashItemsJob,
                                          FetchStashListJob, LoginJob,
                                          LogoutJob)
from poe_view.services.csv_export import export_items, sanitize_filename
from poe_view.ui.character_list import CharacterList
from poe_view.ui.item_detail import ItemDetail
from poe_view.ui.item_table import (COLUMNS, ICON_COL, MODS_COL,
                                    POSITION_COL, TAB_COL, ItemFilterProxy,
                                    ItemTableModel)
from poe_view.ui.rate_limit_dashboard import RateLimitDashboard
from poe_view.ui.raw_data_viewer import RawDataViewer
from poe_view.ui.stash_tree import StashTree
from poe_view.ui.theme import OTHER_TYPE, RARITY_COLORS, TYPE_FILTER_COLOR

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    # Hintergrund-Auto-Refresh (Nutzer-Feedback): nie jünger als 1 Tag anfassen
    # (dafür reicht der manuelle Refresh völlig), und dem Nutzer immer mind.
    # die Hälfte des Rate-Limit-Budgets für manuelle Klicks übrig lassen.
    # Pro Tick können jetzt BIS ZU ZWEI Jobs rausgehen (das gerade angezeigte
    # Fach + der normale Sweep-Kandidat, Nutzer-Feedback) — Intervall verdoppelt,
    # damit die Gesamt-Anfragerate ans Rate-Limit gegenüber vorher gleich bleibt
    # und wir nicht in dessen Sperre (Timeout) laufen.
    AUTO_REFRESH_INTERVAL_MS = 40_000
    AUTO_REFRESH_MIN_AGE = timedelta(days=1)
    AUTO_REFRESH_MIN_HEADROOM = 0.5

    # Typ-Filter-Checkboxen (Nutzer-Feedback): die vier PoE-Rarities, dazu
    # Gem/Currency/Divination Card, und "Sonstige" (OTHER_TYPE) für den
    # Rest (Quest, Prophecy, Relic, Unbekanntes).
    TYPE_FILTER_ENTRIES = (
        (0, "Normal"), (1, "Magic"), (2, "Rare"), (3, "Unique"),
        (4, "Gem"), (5, "Currency"), (6, "Div Card"),
        (OTHER_TYPE, "Sonstige"),
    )

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
        self._search_all_active = False        # Suchfeld → liga-weite Ansicht aktiv
        self._current_stash_id: str | None = None  # zuletzt gewähltes Fach (Rückkehrziel)
        self._character_items: dict[str, list[Item]] = {}       # Charaktername → Ausrüstung+Inventar
        self._character_items_loaded: dict[str, str] = {}       # Charaktername → ISO-Zeitstempel
        self._current_character_name: str | None = None         # gerade angezeigter Charakter
        self._worker_busy = False
        self._auto_refresh_counts: dict[str, int] = {}  # Liga → auto-aktualisierte Tabs (Session)
        self._raw_data_viewer: RawDataViewer | None = None
        self._offline = False  # GGG nicht erreichbar (Nutzer-Feedback: Wartung am Patchday)
        self._live_leagues: set[str] | None = None  # letzte /account/leagues-Antwort; None = noch unbekannt
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
        self._character_items = cached.character_items
        self._character_items_loaded = cached.character_items_loaded
        log.info("Daten-Cache geladen: %d Charaktere, %d Liga(en)",
                 len(cached.characters), len(cached.stash_trees))

    def _persist_cache(self) -> None:
        data = data_cache.CachedData()
        data.account_name = self._account_name
        data.characters = self._all_characters
        data.stash_trees = self._stash_trees
        data.items_by_league = self._items
        data.last_loaded = self._last_loaded
        data.character_items = self._character_items
        data.character_items_loaded = self._character_items_loaded
        data_cache.save(data)

    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # QMainWindow bietet per Default ein Rechtsklick-Kontextmenü über der
        # Toolbar an, mit dem sie sich komplett ausblenden lässt — OHNE Menü-
        # leiste gäbe es dann keinen Weg mehr zurück (Login, Refresh, Liga-
        # Wahl, Suche — alles verschwunden). Nutzer-Feedback: aus Versehen
        # passiert. Deaktiviert.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
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

        toolbar.addWidget(QLabel("  Typ: "))
        # 8 Checkboxen statt Namen (Nutzer-Feedback: Namen wären zu lang) —
        # die Farbe des Käschchens IST das Label, Tooltip trägt den Namen.
        # Die letzte ("Sonstige", Pink) fängt alles ohne eigene Kategorie
        # auf: Quest, Prophecy, Relic, unbekannte frameTypes (§4.11).
        self._type_checks: dict[int, QCheckBox] = {}
        for type_key, name in self.TYPE_FILTER_ENTRIES:
            box = QCheckBox()
            box.setChecked(True)
            box.setToolTip(name)
            colour = RARITY_COLORS.get(type_key, TYPE_FILTER_COLOR)
            box.setStyleSheet(
                f"QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 3px; "
                f"border: 2px solid {colour}; }} "
                f"QCheckBox::indicator:checked {{ background-color: {colour}; }}")
            box.toggled.connect(lambda checked, tk=type_key: self._on_type_toggled(tk, checked))
            self._type_checks[type_key] = box
            toolbar.addWidget(box)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("🔍 Suche über alle Fächer der Liga — * für alles")
        self._filter_edit.setFixedWidth(260)
        self._filter_edit.setClearButtonEnabled(True)  # eingebautes "x" zum Leeren
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
        self.character_list.character_refresh_requested.connect(self._on_character_refresh)
        self.character_list.setMaximumHeight(220)

        stash_label = QLabel("Stash")
        stash_label.setStyleSheet("font-weight: 600; padding: 2px 4px;")
        self.tree = StashTree()
        self.tree.stash_selected.connect(self._on_stash_selected)
        self.tree.stash_refresh_requested.connect(self._on_stash_refresh)
        self.tree.raw_data_requested.connect(self._on_raw_data_requested)

        left_layout.addWidget(char_label)
        left_layout.addWidget(self.character_list)
        left_layout.addWidget(stash_label)
        left_layout.addWidget(self.tree, stretch=1)

        # Rechte Seite: Tabelle + Detail
        self.table_model = ItemTableModel(
            icon_requester=lambda url: self.worker.submit(FetchIconJob(url)))
        self.proxy = ItemFilterProxy()
        self.proxy.setSourceModel(self.table_model)
        self._filter_edit.textChanged.connect(self._on_filter_text_changed)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(POSITION_COL, 100)
        for name in ("Anf.Lvl", "Str", "Dex", "Int"):  # schmale Zahlenspalten
            self.table.setColumnWidth(COLUMNS.index(name), 58)
        self.table.setColumnWidth(MODS_COL, 320)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        # Spalten per Rechtsklick auf den Header an-/abwählbar (Nutzer-Feedback);
        # die Wahl überlebt den Neustart (ui-settings.ini im APP_DATA_DIR).
        table_header = self.table.horizontalHeader()
        table_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table_header.customContextMenuRequested.connect(self._on_table_header_menu)
        self._apply_hidden_columns(self._load_hidden_columns())

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
        # Permanentes Offline-Banner (Nutzer-Feedback: GGG-Wartung am
        # Patchday/Liga-Start) — separat vom transienten _status_msg, damit
        # es nicht von der nächsten "Lade …"-Meldung überschrieben wird.
        self._offline_label = QLabel("")
        self._offline_label.setStyleSheet("color: #d9a441; font-weight: 600;")
        self.statusBar().addPermanentWidget(self._offline_label)
        # Sichtbarer Nachweis, dass der Hintergrund-Auto-Refresh arbeitet
        # (Nutzer-Feedback: "Bist du dir sicher, dass das funktioniert?").
        self._auto_refresh_label = QLabel("")
        self.statusBar().addPermanentWidget(self._auto_refresh_label)
        self.statusBar().addPermanentWidget(QLabel(config.DISCLAIMER))

        # Liga-Dropdown SOFORT aus dem Cache befüllen — unabhängig vom
        # Netzwerk nutzbar (Nutzer-Feedback: GGG-Wartung am Patchday). Muss
        # als letztes hier stehen: braucht Tree/League-Combo bereits gebaut.
        self._populate_cached_leagues()

    def _populate_cached_leagues(self) -> None:
        """Zeigt gecachte Ligen im Dropdown, bevor überhaupt ein Netzwerk-Call
        stattgefunden hat — die spätere LIVE-Liste (``_on_leagues``) ersetzt
        das vollständig, sobald sie eintrifft. Ohne das wäre die App bei
        GGG-Wartung beim Start komplett leer, obwohl der Cache längst alles
        Nötige hätte."""
        self._rebuild_league_combo(None)

    def _league_has_content(self, league: str) -> bool:
        """Hat der Nutzer dort tatsächlich einen Spielstand (Charaktere ODER
        bereits geladene Items)? Grundlage der Dropdown-Sortierung — GGG legt
        pro Account automatisch leere Hardcore-/Ruthless-Varianten an, auch
        wenn der Nutzer dort nie gespielt hat (Nutzer-Feedback: "Hardcore
        zuerst, obwohl ich noch keinen Hardcore-Spielstand habe")."""
        if any(c.league == league for c in self._all_characters):
            return True
        return any(self._items.get(league, {}).values())

    def _sort_by_content(self, leagues: list[str]) -> list[str]:
        """Ligen mit Spielstand zuerst — stabil, die restliche Reihenfolge
        (Cache: alphabetisch; live: API-Reihenfolge) bleibt sonst erhalten."""
        return sorted(leagues, key=lambda league: not self._league_has_content(league))

    # Nicht-auswählbare "Überschrift" statt eines blanken Trennstrichs —
    # macht sichtbar explizit, WARUM die unteren Einträge getrennt sind
    # (Nutzer-Feedback: "als Offline-Liga anhängen", nicht nur positionell
    # trennen). Text bewusst so gewählt, dass er nie mit einem echten
    # Liga-Namen kollidiert.
    _ARCHIVED_HEADER = "── Beendete Ligen (nur Cache, kein Online-Zugriff) ──"

    def _rebuild_league_combo(self, live_leagues: list[str] | None) -> None:
        """Baut das Liga-Dropdown neu auf (Nutzer-Feedback): aktuell gültige
        Ligen oben (nach Spielstand sortiert, §_sort_by_content), abgelaufene
        — nur noch im Cache vorhandene — Ligen darunter, per nicht wählbarer
        Überschrift abgetrennt. ``live_leagues=None`` heißt "wissen wir noch
        nicht" (Start vor der ersten API-Antwort, §4.12): dann gilt der
        gesamte Cache als "oben", ohne Abtrennung, da wir noch nicht
        unterscheiden können, was inzwischen abgelaufen ist."""
        previous = self._league_combo.currentText()
        if live_leagues is None:
            top, bottom = sorted(self._stash_trees), []
        else:
            live_set = set(live_leagues)
            top = list(live_leagues)
            bottom = sorted(league for league in self._stash_trees if league not in live_set)
        top = self._sort_by_content(top)

        self._league_combo.blockSignals(True)
        self._league_combo.clear()
        self._league_combo.addItems(top)
        if top and bottom:
            self._league_combo.addItem(self._ARCHIVED_HEADER)
            header_item = self._league_combo.model().item(self._league_combo.count() - 1)
            header_item.setEnabled(False)  # nur Überschrift, nicht anwählbar
        self._league_combo.addItems(bottom)
        # Auswahl möglichst über den Rebuild hinweg erhalten (leeres previous
        # NICHT suchen — sonst würde findText("") zufällig etwas mit leerem
        # Text treffen).
        idx = self._league_combo.findText(previous) if previous else -1
        self._league_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._league_combo.blockSignals(False)
        if self._league_combo.count():
            self._on_league_changed(self._league_combo.currentText())
        self._update_tree_offline_display()  # auch wenn _on_league_changed oben früh returnt

    def _current_league_is_archived(self) -> bool:
        """True, wenn die aktuelle Liga zwar im Cache existiert, aber nicht
        mehr in der letzten Live-Antwort von /account/leagues auftaucht —
        z. B. weil eine temporäre Liga beendet wurde (Nutzer-Feedback:
        Liga-Start, "keinen Online-Zugriff mehr auf den alten Liga-Content").
        ``None`` (noch nie eine Live-Antwort erhalten) gilt NICHT als
        archiviert — sonst würde ein Offline-Start (§4.12) fälschlich jede
        gecachte Liga als tot markieren."""
        return self._live_leagues is not None and self._current_league not in self._live_leagues

    def _update_tree_offline_display(self) -> None:
        """Baum zeigt 📴 statt ⟳, wenn entweder GGG global nicht erreichbar
        ist (§4.12) ODER die aktuell angezeigte Liga archiviert ist (Liga
        beendet, kein Online-Zugriff mehr) — für den Nutzer bedeutet beides
        dasselbe: "das hier ist garantiert nur Cache"."""
        self.tree.set_offline(self._offline or self._current_league_is_archived())

    def _archived_league_guard(self, message: str) -> bool:
        """True (+ zeigt ``message``), wenn für die aktuelle Liga kein
        Online-Zugriff mehr besteht — verhindert nutzlose Netzwerk-Versuche
        für beendete Ligen. Bewusst PRÄVENTIV statt "versuchen und Fehler
        behandeln": unklar, ob GGG dafür einen Fehler liefert oder still
        eine leere Antwort (die den Cache überschreiben würde) — beides
        wird durch den Verzicht auf den Versuch gleichermaßen vermieden."""
        if self._current_league_is_archived():
            self._status_msg.setText(message)
            return True
        return False

    def _on_type_toggled(self, type_key: int, visible: bool) -> None:
        self.proxy.set_type_visible(type_key, visible)

    # --- Spalten-Sichtbarkeit der Item-Tabelle (Nutzer-Feedback) --------- #

    # "Typ" ist standardmäßig aus: die Rarity steckt bereits in der
    # Namensfarbe. Die Tab-Spalte wird automatisch verwaltet (aus bei
    # Einzelfach, an bei Aggregat) und ist deshalb NICHT im Menü.
    DEFAULT_HIDDEN_COLUMNS = frozenset({"Typ"})

    def _settings(self) -> QSettings:
        """INI-Datei statt Registry — konsistent zum Datei-Cache-Ansatz und
        1:1 nach LabVIEW portierbar (Config-File)."""
        return QSettings(str(config.APP_DATA_DIR / "ui-settings.ini"),
                         QSettings.Format.IniFormat)

    def _load_hidden_columns(self) -> set[str]:
        stored = self._settings().value("item_table/hidden_columns")
        if stored is None:
            return set(self.DEFAULT_HIDDEN_COLUMNS)
        return {name for name in str(stored).split(";") if name}

    def _apply_hidden_columns(self, hidden: set[str]) -> None:
        for i, name in enumerate(COLUMNS):
            if i == TAB_COL:
                continue  # automatisch verwaltet (Einzelfach vs. Aggregat)
            self.table.setColumnHidden(i, name in hidden)

    def _toggle_column(self, name: str) -> None:
        hidden = self._load_hidden_columns()
        hidden.symmetric_difference_update({name})
        self._apply_hidden_columns(hidden)
        self._settings().setValue("item_table/hidden_columns", ";".join(sorted(hidden)))

    def _on_table_header_menu(self, pos) -> None:
        header = self.table.horizontalHeader()
        clicked_col = header.logicalIndexAt(pos)
        menu = QMenu(self.table)
        # Excel-artiger Spalten-Filter für die angeklickte Spalte
        # (Nutzer-Feedback: "z. B. 20% Quality oder iLvl <45"). Übernahme
        # mit Enter; aktive Filter tragen 🔍 im Spalten-Header.
        if clicked_col > ICON_COL:
            title = menu.addAction(f"Filter „{COLUMNS[clicked_col]}“ (Enter übernimmt):")
            title.setEnabled(False)
            edit = QLineEdit(self.proxy.column_filter(clicked_col))
            edit.setPlaceholderText("z. B. >=20, <45, =Text, Teilstring")
            edit.returnPressed.connect(
                lambda c=clicked_col, e=edit, m=menu: (
                    self._apply_column_filter(c, e.text()), m.close()))
            field = QWidgetAction(menu)
            field.setDefaultWidget(edit)
            menu.addAction(field)
            if self.proxy.filtered_columns():
                clear_action = menu.addAction("✕ Alle Spalten-Filter löschen")
                clear_action.triggered.connect(self._clear_column_filters)
            menu.addSeparator()
        hidden = self._load_hidden_columns()
        for i, name in enumerate(COLUMNS):
            if i == TAB_COL:
                continue
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name not in hidden)
            action.triggered.connect(lambda _=False, n=name: self._toggle_column(n))
        menu.exec(header.mapToGlobal(pos))

    def _apply_column_filter(self, col: int, expr: str) -> None:
        self.proxy.set_column_filter(col, expr)
        shown, total = self.proxy.rowCount(), self.table_model.rowCount()
        active = ", ".join(f"{COLUMNS[c]} {self.proxy.column_filter(c)}"
                           for c in sorted(self.proxy.filtered_columns()))
        self._status_msg.setText(
            f"Spalten-Filter [{active}]: {shown} von {total} Items sichtbar"
            if active else f"Spalten-Filter entfernt — {total} Items")

    def _clear_column_filters(self) -> None:
        self.proxy.clear_column_filters()
        self._status_msg.setText(
            f"Alle Spalten-Filter gelöscht — {self.table_model.rowCount()} Items")

    def _connect_worker(self) -> None:
        w = self.worker
        w.logged_in.connect(self._on_logged_in)
        w.login_required.connect(self._on_login_required)
        w.leagues_loaded.connect(self._on_leagues)
        w.characters_loaded.connect(self._on_characters)
        w.stash_list_loaded.connect(self._on_stash_list)
        w.stash_items_loaded.connect(self._on_stash_items)
        w.stash_children_loaded.connect(self._on_stash_children)
        w.character_items_loaded.connect(self._on_character_items)
        w.icon_loaded.connect(self._on_icon)
        w.rate_limit_changed.connect(self.dashboard.update_state)
        w.status.connect(self._on_status)
        w.busy_changed.connect(self._on_busy_changed)
        w.job_error.connect(self._on_error)
        w.bulk_progress.connect(self._on_bulk_progress)
        w.bulk_finished.connect(self._on_bulk_finished)
        w.offline_changed.connect(self._on_offline_changed)

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
        self._live_leagues = set(leagues)
        self._rebuild_league_combo(leagues)

    def _on_league_changed(self, league: str) -> None:
        if not league or league == self._current_league or league == self._ARCHIVED_HEADER:
            return  # Header-Zeile ist nicht anwählbar, aber sicherheitshalber abgefangen
        self._current_league = league
        self._showing_aggregate = False
        self._current_stash_id = None  # Fach-IDs gelten nur innerhalb einer Liga
        self._current_character_name = None
        self._apply_character_league_filter()
        cached_tree = self._stash_trees.get(league)
        if cached_tree is not None:
            # Sofort anzeigen (aus dieser Session oder vom letzten Programmstart) …
            self._activate_stash_tree(cached_tree)
        else:
            self.tree.set_stashes([])
            self._leaf_stashes = []
        if self._search_all_active:
            self._enter_search_all()  # laufende Suche auf die neue Liga umziehen
        self._update_tree_offline_display()
        if self._current_league_is_archived():
            # Liga beendet (nicht mehr in /account/leagues) — kein Netzwerk-
            # Versuch, der ohnehin nur scheitern kann (Nutzer-Feedback).
            self._status_msg.setText(
                f"{league}: Liga beendet — zeige den zuletzt bekannten Stand "
                "(kein Online-Zugriff mehr).")
        else:
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
        item_counts = self._item_counts_for_current_league()
        self.tree.set_stashes(stashes, last_loaded=last_loaded, item_counts=item_counts)
        self._leaf_stashes = self._flatten_stashes(stashes)
        self._update_auto_refresh_label()

    def _item_counts_for_current_league(self) -> dict[str, int]:
        """stash_id → tatsächlich geladene Item-Anzahl — überschreibt im Baum
        den bloßen API-Hinweis (metadata.items bei Map-/Unique-Kindern)."""
        return {sid: len(items)
                for sid, items in self._items.get(self._current_league, {}).items()}

    def _on_stash_list(self, stashes: list[StashTab]) -> None:
        # Die Liga-LISTE der API kennt die Kinder von Spezial-Tabs (MapStash,
        # UniqueStash) NICHT — ohne Merge gingen bereits entdeckte Unter-Tabs
        # bei jedem Listen-Refresh/Liga-Wechsel wieder verloren.
        old = self._stash_trees.get(self._current_league)
        if old:
            self._merge_known_children(stashes, old)
        self._stash_trees[self._current_league] = stashes
        self._activate_stash_tree(stashes)
        if self._search_all_active:
            self._enter_search_all()  # Suchansicht auf die frische Liste umstellen
        self._persist_cache()

    @staticmethod
    def _merge_known_children(new_stashes: list[StashTab],
                              old_stashes: list[StashTab]) -> None:
        """Überträgt in früheren Abrufen entdeckte Spezial-Tab-Kinder in die
        frisch geladene Stash-Liste (in-place)."""
        old_by_id: dict[str, StashTab] = {}

        def index(stashes: list[StashTab]) -> None:
            for stash in stashes:
                old_by_id[stash.id] = stash
                index(stash.children)

        def graft(stashes: list[StashTab]) -> None:
            for stash in stashes:
                if stash.children:
                    graft(stash.children)  # Ordner: Kinder kommen aus der Liste selbst
                else:
                    old = old_by_id.get(stash.id)
                    if old is not None and old.children:
                        stash.children = old.children

        index(old_stashes)
        graft(new_stashes)

    @staticmethod
    def _flatten_stashes(stashes: list[StashTab]) -> list[StashTab]:
        """Rekursiv alle Nicht-Container-Tabs einsammeln (Reihenfolge wie im Baum).

        Container = Ordner ODER Spezial-Tabs mit bereits entdeckten Kindern
        (MapStash/UniqueStash) — bei denen sind die KINDER die ladbaren
        Einheiten. Ein Spezial-Tab VOR seiner Entdeckung hat keine children
        und zählt als Leaf — sein erster Abruf liefert dann die Kinder.
        """
        flat: list[StashTab] = []
        for stash in stashes:
            if stash.is_folder or stash.children:
                flat.extend(MainWindow._flatten_stashes(stash.children))
            else:
                flat.append(stash)
        return flat

    @staticmethod
    def _find_stash(stashes: list[StashTab], stash_id: str) -> StashTab | None:
        for stash in stashes:
            if stash.id == stash_id:
                return stash
            found = MainWindow._find_stash(stash.children, stash_id)
            if found is not None:
                return found
        return None

    # Tab-Typen, die am Einzel-Endpunkt children statt items liefern (§4.10)
    SPECIAL_TAB_TYPES = frozenset({"MapStash", "UniqueStash"})

    def _parent_id_of(self, stash_id: str) -> str | None:
        """Substash-Eltern-ID (nur bei Kindern von Spezial-Tabs, sonst None)."""
        stash = self._find_stash(self._stash_trees.get(self._current_league, []), stash_id)
        return stash.parent if stash is not None else None

    def _on_stash_selected(self, stash_id: str, name: str) -> None:
        self._showing_aggregate = False
        self._search_all_active = False  # Baum-Klick beendet die liga-weite Suchansicht
        stash = self._find_stash(self._stash_trees.get(self._current_league, []), stash_id)
        if stash is not None and stash.type in self.SPECIAL_TAB_TYPES and stash.parent is None:
            if stash.children:
                # Struktur bekannt: alle bereits geladenen Unter-Fächer
                # aggregiert anzeigen — mit Fach-Namen ("Map (Tier 1)") in
                # der Tab-Spalte (Nutzer-Feedback).
                self._show_special_parent_aggregate(stash, name)
                return
            # Spezial-Tab ohne bekannte Kinder: IMMER fetchen, den Item-Cache
            # bewusst ignorieren — ein alter "0 Items"-Eintrag (von vor dem
            # Spezial-Tab-Feature) wäre sonst ein permanenter Cache-Treffer,
            # und die Kinder-Entdeckung fände nie statt (Nutzer-Befund:
            # "musste erst manuell aktualisieren"). Außer die Liga ist
            # archiviert — dann gibt es nichts mehr zu entdecken.
            if self._archived_league_guard(
                    f"{name}: Liga beendet — Unter-Fächer nicht mehr abrufbar."):
                return
            self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name))
            return
        league_items = self._items.get(self._current_league, {})
        if stash_id in league_items:
            # Speicher-/Datei-Cache: kein erneuter API-Call (Doku §5)
            self._show_items(stash_id, league_items[stash_id], name)
            return
        if self._archived_league_guard(
                f"{name}: nie geladen — Liga beendet, jetzt nicht mehr abrufbar."):
            return
        self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name,
                                              parent_id=self._parent_id_of(stash_id)))

    def _on_stash_refresh(self, stash_id: str, name: str) -> None:
        """Klick auf den Refresh-Button eines Tabs — bewusst AM Cache vorbei."""
        self._showing_aggregate = False
        if self._archived_league_guard(f"{name}: Liga beendet — kein Refresh mehr möglich."):
            return
        self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name,
                                              parent_id=self._parent_id_of(stash_id)))

    def _on_stash_items(self, league: str, stash_id: str, name: str,
                        items: list[Item], silent: bool) -> None:
        """``league`` kommt aus dem Signal (nicht ``self._current_league``!) —
        sonst würde ein spät eintreffender Hintergrund-Job die Daten der
        MOMENTAN aktiven Liga verfälschen, falls der Nutzer zwischenzeitlich
        die Liga gewechselt hat."""
        already_loaded = stash_id in self._last_loaded.get(league, {})
        self._last_loaded.setdefault(league, {})[stash_id] = datetime.now(timezone.utc).isoformat()
        self._items.setdefault(league, {})[stash_id] = items
        if silent and not already_loaded:
            # Nur NEU geladene Fächer zählen für "X von Y Stash-Tabs" — sonst
            # würde das wiederholte Live-Halten des gerade angezeigten Fachs
            # (jeder Auto-Refresh-Tick) den Zähler weit über Y treiben.
            self._auto_refresh_counts[league] = self._auto_refresh_counts.get(league, 0) + 1
        relabelled = self._stamp_category(league, stash_id, items)
        self._persist_cache()
        if league != self._current_league:
            return
        self.tree.mark_loaded(stash_id, self._last_loaded[league][stash_id], count=len(items))
        if relabelled is not None:
            self.tree.update_label(stash_id, relabelled)
        if silent:
            self._update_auto_refresh_label()
        # Bei einem STILLEN Refresh die sichtbare Tabelle nur dann live
        # aktualisieren, wenn genau DIESES Fach gerade als Einzelansicht
        # offen ist (Regression, Nutzer-Feedback: das Live-Halten des
        # aktuellen Fachs aktualisierte bisher nur den Cache/Baum, NICHT
        # die Tabelle — "lebt" war es also gar nicht). Bei einem
        # Sweep-Kandidaten (ein ANDERES Fach) oder während einer Aggregat-/
        # Such-Ansicht bleibt die Tabelle unangetastet, sonst würde ein
        # Hintergrund-Job die aktuelle Ansicht des Nutzers wegreißen.
        if not self._showing_aggregate and (not silent or stash_id == self._current_stash_id):
            self._show_items(stash_id, items, name)

    def _on_stash_children(self, league: str, stash_id: str, name: str,
                           children: list[StashTab], silent: bool) -> None:
        """Ein Spezial-Tab (MapStash/UniqueStash) hat statt Items Unter-Tabs
        geliefert — in Baumstruktur und Anzeige einhängen. Deren Items werden
        wie bei normalen Tabs erst per Klick (oder Auto-Refresh) geladen."""
        already_loaded = stash_id in self._last_loaded.get(league, {})
        self._last_loaded.setdefault(league, {})[stash_id] = datetime.now(timezone.utc).isoformat()
        # Ein evtl. vorhandener alter Item-Eintrag des Eltern-Tabs ist Müll
        # (Spezial-Tabs haben nie eigene Items) — raus damit, sonst wäre der
        # nächste Klick wieder ein irreführender "0 Items"-Cache-Treffer.
        self._items.get(league, {}).pop(stash_id, None)
        tree = self._stash_trees.get(league)
        if tree is not None:
            tab = self._find_stash(tree, stash_id)
            if tab is not None:
                tab.children = children
        if silent and not already_loaded:  # siehe _on_stash_items: nicht über Y hinauszählen
            self._auto_refresh_counts[league] = self._auto_refresh_counts.get(league, 0) + 1
        self._persist_cache()
        if league != self._current_league:
            return
        league_loaded = self._last_loaded.get(league, {})
        item_counts = self._item_counts_for_current_league()
        self.tree.set_children(stash_id, children, last_loaded=league_loaded,
                               item_counts=item_counts, expand=not silent)
        # Gesamtsumme über die Kinder (bekannte API-Hinweise + evtl. schon
        # geladene) auch am Eltern-Knoten zeigen.
        counts = [item_counts.get(c.id, c.metadata.get("items")) for c in children]
        total = sum(c or 0 for c in counts) if any(c is not None for c in counts) else None
        self.tree.mark_loaded(stash_id, league_loaded[stash_id], count=total)
        if tree is not None:
            self._leaf_stashes = self._flatten_stashes(tree)
        self._update_auto_refresh_label()
        if not silent:
            self._status_msg.setText(
                f"{name}: Spezial-Tab mit {len(children)} Unter-Tabs — "
                "Items je Unter-Tab per Klick laden")
            self._update_raw_viewer(stash_id, name)

    def _stamp_category(self, league: str, stash_id: str, items: list[Item]) -> str | None:
        """Namenlose Unique-Stash-Fächer nach dem ersten Item-Load taufen
        (Nutzer-Feedback: "über die Kategorie gehen, z. B. Two Handed Axe,
        Ring, Flask"). Die Kategorie wandert als synthetischer Schlüssel
        ``poeview_category`` in die Tab-Metadaten — landet damit im
        Datei-Cache und überlebt den Neustart. Rückgabe: neuer Anzeigename,
        falls sich einer ergeben hat, sonst None."""
        tab = self._find_stash(self._stash_trees.get(league, []), stash_id)
        if tab is None or tab.parent is None:
            return None  # nur Kinder von Spezial-Tabs sind namenlos
        if tab.name.strip() or tab.metadata.get("map"):
            return None  # hat bereits einen brauchbaren Namen (Map-Fächer etc.)
        category = dominant_category(items)
        if not category or tab.metadata.get("poeview_category") == category:
            return None
        tab.metadata["poeview_category"] = category
        return tab.display_name

    def _tab_positions(self) -> dict[str, int]:
        """1-basierte Position jedes Fachs in der Reihenfolge, in der die API
        sie für die AKTUELLE Liga zurückliefert (`_leaf_stashes`) — Basis der
        Position-Spalte (§4.11). NICHT ``StashTab.index`` nehmen: Fächer
        wandern beim Liga-Ende nach Standard und behalten dabei ihren
        ursprünglichen Index aus der (jetzt toten) alten Liga — mehrere
        Fächer in Standard tragen so denselben Index (Nutzer-Feedback,
        FALLSTRICKE #21). Die JSON-Reihenfolge selbst ist dagegen die
        tatsächliche, aktuelle Position in der Truhen-Leiste."""
        return {stash.id: position for position, stash in enumerate(self._leaf_stashes, start=1)}

    def _show_items(self, stash_id: str, items: list[Item], name: str) -> None:
        self._current_tab_name = name
        self._current_stash_id = stash_id  # Rückkehrziel nach liga-weiter Suche
        self._current_character_name = None
        tab_index = self._tab_positions().get(stash_id)
        self.table.setColumnHidden(TAB_COL, True)  # redundant bei Einzelfach
        self.table_model.set_items(items, [name] * len(items), [tab_index] * len(items),
                                   [stash_id] * len(items))
        self._status_msg.setText(f"{name}: {len(items)} Items")
        self._update_raw_viewer(stash_id, name)

    def _show_special_parent_aggregate(self, stash: StashTab, name: str) -> None:
        """Klick auf einen Spezial-Tab-Elternknoten (Map/Unique): Items ALLER
        bereits geladenen Unter-Fächer zusammen anzeigen; die Tab-Spalte trägt
        den Fach-Namen ("Map (Tier 1)", Nutzer-Feedback)."""
        self._showing_aggregate = True
        self._current_tab_name = name
        self._current_stash_id = stash.id  # Rückkehrziel nach liga-weiter Suche
        self._current_character_name = None
        league_items = self._items.get(self._current_league, {})
        positions = self._tab_positions()
        items: list[Item] = []
        sources: list[str] = []
        tab_indices: list[int | None] = []
        stash_ids: list[str | None] = []
        loaded = 0
        for child in stash.children:
            cached = league_items.get(child.id)
            if cached is None:
                continue
            loaded += 1
            items.extend(cached)
            sources.extend([child.display_name] * len(cached))
            tab_indices.extend([positions.get(child.id)] * len(cached))
            stash_ids.extend([child.id] * len(cached))
        self.table.setColumnHidden(TAB_COL, False)  # hier trägt sie die Info
        self.table_model.set_items(items, sources, tab_indices, stash_ids,
                                   request_icons=False)  # lazy
        self._status_msg.setText(
            f"{name}: {len(items)} Items aus {loaded} von {len(stash.children)} "
            "geladenen Unter-Fächern")
        self._update_raw_viewer(stash.id, name)

    # --- Alle Tabs laden (Bulk) ----------------------------------------- #

    def _load_all_items(self) -> None:
        if self._bulk_dialog is not None:
            return  # läuft schon
        if not self._leaf_stashes:
            QMessageBox.information(
                self, "Alle Tabs laden",
                "Keine Stash-Tabs geladen — bitte zuerst eine Liga wählen.")
            return
        if self._current_league_is_archived():
            # Liga beendet — keiner der nicht gecachten Tabs ist noch
            # abrufbar, "Alle Tabs laden" kann nur den Cache zusammenfassen.
            self._show_aggregate()
            self._status_msg.setText(
                "Liga beendet — zeige den zuletzt bekannten Stand aller geladenen Fächer.")
            return
        league_items = self._items.get(self._current_league, {})
        # Spezial-Tabs ohne entdeckte Kinder immer mitnehmen: ein evtl.
        # vorhandener Item-Cache-Eintrag ist bei ihnen bedeutungslos (§4.10).
        to_fetch = [s for s in self._leaf_stashes
                    if s.id not in league_items or s.type in self.SPECIAL_TAB_TYPES]
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
        self._search_all_active = False
        self._current_tab_name = "Alle Tabs"
        self._current_stash_id = None  # Rückkehr aus der Suche landet wieder hier
        self._current_character_name = None
        items, sources, tab_indices, stash_ids = self._league_wide_items()
        self.table.setColumnHidden(TAB_COL, False)  # Aggregat: Herkunft zeigen
        self.table_model.set_items(items, sources, tab_indices, stash_ids,
                                   request_icons=False)  # lazy
        self._status_msg.setText(f"Alle Tabs: {len(items)} Items gesamt")

    def _league_wide_items(self) -> tuple[list[Item], list[str], list[int | None], list[str | None]]:
        """Alle gecachten Items der aktuellen Liga + Herkunfts-Fachname,
        Tab-Position (Positions-Spalte, unterscheidet gleichnamige Fächer —
        1-basierter Platz in ``_leaf_stashes``, NICHT ``stash.index``,
        §_tab_positions) und Tab-ID (Baum-Hervorhebung bei Zeilenauswahl,
        Nutzer-Feedback) je Item."""
        league_items = self._items.get(self._current_league, {})
        items: list[Item] = []
        sources: list[str] = []
        tab_indices: list[int | None] = []
        stash_ids: list[str | None] = []
        for position, stash in enumerate(self._leaf_stashes, start=1):
            cached = league_items.get(stash.id)
            if cached is None:
                continue
            items.extend(cached)
            sources.extend([stash.display_name] * len(cached))
            tab_indices.extend([position] * len(cached))
            stash_ids.extend([stash.id] * len(cached))
        return items, sources, tab_indices, stash_ids

    # --- Fächerübergreifende Suche (Nutzer-Feedback) --------------------- #

    def _on_filter_text_changed(self, text: str) -> None:
        """Tippen sucht liga-weit über ALLE bereits geladenen Fächer; Leeren
        des Felds kehrt zur vorher gewählten Ansicht zurück. Eingrenzen auf
        ein Fach geht weiterhin: Baum-Klick oder Spalten-Filter auf "Tab"."""
        if text and not self._search_all_active:
            self._enter_search_all()
        elif not text and self._search_all_active:
            self._leave_search_all()
        self.proxy.setFilterFixedString(text)

    def _enter_search_all(self) -> None:
        self._search_all_active = True
        self._showing_aggregate = True  # späte Einzel-Ergebnisse nicht reinfunken lassen
        self._current_character_name = None
        items, sources, tab_indices, stash_ids = self._league_wide_items()
        self.table.setColumnHidden(TAB_COL, False)  # Herkunft ist Teil der Antwort
        # request_icons=False: sonst würde die Suche zigtausend Icon-Jobs in
        # die Worker-Queue schieben — Icons kommen lazy für sichtbare Zeilen.
        self.table_model.set_items(items, sources, tab_indices, stash_ids, request_icons=False)
        loaded = len({s for s in sources})
        self._status_msg.setText(
            f"Suche über {loaded} geladene Fächer ({len(items)} Items) — "
            "Feld leeren führt zurück zur Fach-Ansicht")

    def _leave_search_all(self) -> None:
        self._search_all_active = False
        if self._current_stash_id is not None:
            self._on_stash_selected(self._current_stash_id, self._current_tab_name)
        elif self._leaf_stashes:
            self._show_aggregate()
        else:
            self.table_model.set_items([])

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
        """Zeigt Ausrüstung + Inventar des Charakters in der Item-Tabelle —
        wie bei Stash-Fächern: Cache-Treffer zeigen sofort an, sonst wird
        einmalig nachgeladen (kein automatisches Neuladen bei jedem Klick,
        Doku §4.4/§5)."""
        self._current_character_name = char.name
        cached = self._character_items.get(char.name)
        if cached is not None:
            self._show_character_items(char.name, cached)
            return
        self._status_msg.setText(f"Lade Ausrüstung: {char.name} …")
        self.worker.submit(FetchCharacterItemsJob(char.name))

    def _on_character_refresh(self, char: Character) -> None:
        """Rechtsklick → "Aktualisieren" — bewusst AM Cache vorbei, analog
        `_on_stash_refresh`. Schaltet die Ansicht (wie beim Stash-Refresh
        auch) auf diesen Charakter um, sobald das Ergebnis eintrifft."""
        self._current_character_name = char.name
        self._status_msg.setText(f"Lade Ausrüstung: {char.name} …")
        self.worker.submit(FetchCharacterItemsJob(char.name))

    def _on_character_items(self, name: str, items: list[Item]) -> None:
        """``name`` kommt aus dem Signal, nicht aus der Auswahl — sonst könnte
        ein spät eintreffender Job Daten eines inzwischen abgewählten
        Charakters in die aktuelle Ansicht einsickern lassen (analog
        `_on_stash_items`)."""
        self._character_items[name] = items
        self._character_items_loaded[name] = datetime.now(timezone.utc).isoformat()
        self._persist_cache()
        if name != self._current_character_name:
            return
        self._show_character_items(name, items)

    def _show_character_items(self, name: str, items: list[Item]) -> None:
        """Slot (``inventoryId``, z. B. "Weapon"/"BodyArmour"/"MainInventory")
        übernimmt die Rolle der Tab-Spalte — analog zu den Aggregat-Ansichten
        der Stash-Tabs. Kein Truhenfach beteiligt: Position-Spalte zeigt nur
        die Item-Koordinate (falls vorhanden), Baum-Hervorhebung entfällt."""
        self._showing_aggregate = False
        self._search_all_active = False
        self._current_stash_id = None
        self.table.setColumnHidden(TAB_COL, False)
        sources = [item.inventoryId or "?" for item in items]
        self.table_model.set_items(items, sources, [None] * len(items), [None] * len(items))
        self._status_msg.setText(f"{name}: {len(items)} Items (Ausrüstung + Inventar)")

    def _on_icon(self, url: str, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.table_model.set_icon(url, pixmap)

    def _on_row_selected(self, current, _previous) -> None:
        source_idx = self.proxy.mapToSource(current)
        item = self.table_model.item_at(source_idx.row())
        if item:
            self.detail.show_item(item, self.table_model.pixmap_for(item))
        # Herkunfts-Fach im Baum hervorheben (Nutzer-Feedback, v. a. bei "*"
        # bzw. Aggregat-Ansichten mit mehreren Quell-Tabs) — highlight_stash
        # nutzt bewusst setCurrentItem statt eines Klick-Signals, damit die
        # aktuelle Such-/Aggregat-Ansicht in der Item-Tabelle NICHT verändert
        # wird (kein stash_selected-Signal, siehe StashTree.highlight_stash).
        stash_id = self.table_model.stash_id_at(source_idx.row())
        if stash_id is not None:
            self.tree.highlight_stash(stash_id)

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

    def _on_offline_changed(self, offline: bool) -> None:
        """GGG nicht erreichbar (Wartung/kein Netz, §4.12) — permanentes
        Banner statt einer Fehlermeldung, die die nächste Statuszeile
        wegwischt, UND Markierung im Baum, dass Fächer aus dem Cache kommen."""
        self._offline = offline
        self._update_tree_offline_display()
        self._offline_label.setText(
            "📴 Offline — GGG nicht erreichbar, zeige zwischengespeicherte Daten"
            if offline else "")

    def _refresh(self) -> None:
        """Stash-Liste + Charaktere neu laden; Item-Daten bleiben unangetastet
        (dafür gibt es die gezielten Refresh-Buttons je Tab im Baum). Für
        eine archivierte (beendete) Liga macht ein Stash-Listen-Refresh
        keinen Sinn — /character bleibt aber liga-unabhängig sinnvoll."""
        if self._current_league and not self._current_league_is_archived():
            self.worker.submit(FetchStashListJob(self._current_league))
        self.worker.submit(FetchCharactersJob())

    # --- Rohdaten-Mini-Viewer (Rechtsklick im Baum, Nutzer-Feedback) ----- #

    def _on_raw_data_requested(self, stash_id: str, name: str) -> None:
        if self._raw_data_viewer is None:
            self._raw_data_viewer = RawDataViewer(self)
        self._raw_data_viewer.show()
        self._raw_data_viewer.raise_()
        self._raw_data_viewer.activateWindow()
        # Lädt bei Bedarf nach (wie ein normaler Linksklick) — _show_items
        # aktualisiert den jetzt sichtbaren Viewer im selben Zug.
        self._on_stash_selected(stash_id, name)

    def _update_raw_viewer(self, stash_id: str, name: str) -> None:
        """Hält den (falls geöffneten) Mini-Viewer beim Tab-Wechsel synchron."""
        if self._raw_data_viewer is None or not self._raw_data_viewer.isVisible():
            return
        payload = self._build_raw_stash_payload(stash_id)
        if payload is not None:
            self._raw_data_viewer.show_payload(stash_id, name, payload)

    def _build_raw_stash_payload(self, stash_id: str) -> dict | None:
        """Setzt Tab-Metadaten (aus der Stash-Liste) und Items (aus dem Item-Cache)
        wieder zu einem vollständigen Objekt zusammen. Dank ``extra="allow"`` in
        den pydantic-Modellen (api/models.py) verlustfrei identisch zu dem, was
        die API tatsächlich liefert — kein separater Rohtext-Cache nötig.
        Bei Spezial-Tabs (MapStash, …) sind die children Teil der Rohdaten."""
        tab = self._find_stash(self._stash_trees.get(self._current_league, []), stash_id)
        if tab is None:
            return None
        items = self._items.get(self._current_league, {}).get(stash_id, [])
        payload = tab.model_dump(mode="json")
        payload["items"] = [item.model_dump(mode="json") for item in items]
        return self._strip_synthetic_keys(payload)

    @staticmethod
    def _strip_synthetic_keys(obj):
        """Von uns gestempelte "poeview_*"-Schlüssel aus den Rohdaten entfernen —
        der Viewer verspricht, zu zeigen, was die API WIRKLICH liefert."""
        if isinstance(obj, dict):
            return {k: MainWindow._strip_synthetic_keys(v)
                    for k, v in obj.items() if not k.startswith("poeview_")}
        if isinstance(obj, list):
            return [MainWindow._strip_synthetic_keys(x) for x in obj]
        return obj

    # --- Hintergrund-Auto-Refresh (Nutzer-Feedback) ---------------------- #

    def _maybe_auto_refresh(self) -> None:
        """Läuft alle paar Sekunden per QTimer; lädt höchstens ZWEI Dinge neu —
        das gerade angezeigte Fach ODER der gerade angezeigte Charakter
        (immer, unabhängig vom Alter, damit die aktuelle Ansicht "lebt",
        Nutzer-Feedback — beide schließen sich gegenseitig aus, siehe
        `_current_stash_id`/`_current_character_name`) UND der normale
        Sweep-Kandidat (füllt nach und nach den Rest der Truhe) — und nur,
        wenn genug Rate-Limit-Budget für manuelle Klicks übrig bleibt
        (Doku §4.8). Deshalb ist ``AUTO_REFRESH_INTERVAL_MS`` doppelt so groß
        wie früher, als pro Tick nur ein Job rausging. Charaktere haben
        KEINEN eigenen Sweep — anders als bei 391 Stash-Tabs ist die
        Charakterliste klein genug, dass "irgendwann von selbst" keinen
        Mehrwert hätte; nicht angezeigte Charaktere bleiben bis zum
        nächsten Klick oder manuellen Refresh (Rechtsklick) unverändert."""
        if not self._current_league or self._worker_busy or self._bulk_dialog is not None:
            return
        if self._current_league_is_archived():
            return  # Liga beendet — jeder Versuch würde nur scheitern (oder Cache überschreiben)
        if self.worker.rate_limiter.headroom_fraction() < self.AUTO_REFRESH_MIN_HEADROOM:
            return
        current_id = self._current_stash_id
        if current_id is not None:
            self.worker.submit(FetchStashItemsJob(
                self._current_league, current_id, self._current_tab_name,
                parent_id=self._parent_id_of(current_id), silent=True))
        elif self._current_character_name is not None:
            self.worker.submit(FetchCharacterItemsJob(self._current_character_name, silent=True))
        candidate = self._pick_auto_refresh_candidate()
        if candidate is not None and candidate.id != current_id:
            self.worker.submit(FetchStashItemsJob(
                self._current_league, candidate.id, candidate.display_name,
                parent_id=candidate.parent, silent=True))

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
        if self._raw_data_viewer is not None:
            self._raw_data_viewer.close()
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
