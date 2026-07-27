"""Hauptfenster: verdrahtet Worker-Signale mit den Widgets (Mockup: docs/ui-mockup.html).

Alle Slots hier laufen im Main-Thread (Qt queued connections aus dem Worker).
Die UI löst API-Arbeit ausschließlich über ``worker.submit(Job)`` aus.

"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QProgressDialog, QSizePolicy,
                               QSplitter, QTableView, QToolBar, QVBoxLayout,
                               QWidget, QWidgetAction)

from poe_view import __version__, config
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
    # Hintergrund-Auto-Refresh: nie jünger als 1 Tag anfassen
    # (dafür reicht der manuelle Refresh völlig). Pro Tick können jetzt BIS
    # ZU ZWEI Jobs rausgehen (das gerade angezeigte Fach + der normale
    # Sweep-Kandidat) — Intervall verdoppelt, damit die Gesamt-Anfragerate
    # ans Rate-Limit gegenüber vorher gleich bleibt und wir nicht in dessen
    # Sperre (Timeout) laufen.
    AUTO_REFRESH_INTERVAL_MS = 40_000
    AUTO_REFRESH_MIN_AGE = timedelta(days=1)
    # Nur eine kleine Notreserve für manuelle Klicks halten, kein hartes
    # 50/50-Splitting mehr (Peter: "sollte doch eigentlich permanent
    # laufen — Manual-Refresh kann ich ja auch jederzeit machen"). Alle
    # Jobs — auto wie manuell — laufen ohnehin durch dieselbe FIFO-Queue
    # und werden vom Rate-Limiter gleich gedrosselt; die Reserve verhindert
    # nur, dass ein manueller Klick ausgerechnet den letzten freien Request
    # vor einer 429-Sperre wegschnappt.
    AUTO_REFRESH_MIN_HEADROOM = 0.1

    # Stash-Modus bevorzugt gefüllte Fächer (Items > 0) vor leeren — leere
    # sind uninteressant und sollen den Takt nicht mit unnötigen Requests
    # blockieren. Damit ein einmal als leer bekanntes Fach aber nicht für
    # immer unbeachtet bleibt, hängt sich nach jeder vollständigen Runde
    # durch alle AKTUELL gefüllten Fächer automatisch ein einziger
    # zusätzlicher Check für das nächste noch leere Fach an
    # (§_pick_stash_mode_candidate) — reihum nach Fächerreihenfolge, nicht
    # nach Alter, damit ein im Spiel nach vorne verschobenes Fach auch hier
    # schneller wieder drankommt. Bewusst kein fester Anteil (z. B. "jeder
    # 10. Pick"): die Häufigkeit soll sich automatisch an die Truhengröße
    # anpassen (bei 5 gefüllten Fächern alle 5 Picks eins, bei 80 gefüllten
    # alle 80). Keine Sonderbehandlung mehr für bestimmte Positionen
    # (z. B. "immer die vordersten 10") — das soll später über eine
    # Favoriten-Markierung gelöst werden, nicht über einen festen Index.

    # Typ-Filter-Checkboxen: die vier PoE-Rarities, dazu
    # Gem/Currency/Divination Card, und "Sonstige" (OTHER_TYPE) für den
    # Rest (Quest, Prophecy, Relic, Unbekanntes).
    TYPE_FILTER_ENTRIES = (
        (0, "Normal"), (1, "Magic"), (2, "Rare"), (3, "Unique"),
        (4, "Gem"), (5, "Currency"), (6, "Div Card"),
        (OTHER_TYPE, "Other"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PoE-VIEW2 v{__version__}")
        self.resize(1100, 700)

        self._account_name: str = ""
        self._stash_trees: dict[str, list[StashTab]] = {}      # Liga → Baumstruktur
        self._items: dict[str, dict[str, list[Item]]] = {}     # Liga → {stash_id: Items}
        self._last_loaded: dict[str, dict[str, str]] = {}      # Liga → {stash_id: ISO-Zeitstempel}
        self._leaf_stashes: list[StashTab] = []                # abgeflacht, nur aktuelle Liga
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
        # Startwert True: der bestehende `_current_league`-Guard blockiert den
        # Auto-Refresh ohnehin, bis eine Liga aktiv ist (was einen
        # erfolgreichen Login voraussetzt) — dieses Flag greift nur für den
        # Fall, dass der Token MITTEN in der Session abläuft (`login_required`
        # setzt es dann auf False, `logged_in` wieder auf True).
        self._logged_in = True
        self._auto_refresh_counts: dict[str, int] = {}  # Liga → auto-aktualisierte Tabs (Session)
        self._auto_refresh_counted: dict[str, set[str | int]] = {}  # Liga → Truhenplätze (§_count_silent_refresh)
        # Refresh-Modus: "auto" (Standard) | "single" | "stash" — siehe
        # _drive_refresh_mode. Nicht persistiert, startet nach jedem
        # Neustart bewusst wieder bei "auto" (keine Überraschung durch
        # volles Tempo direkt nach dem Programmstart).
        self._refresh_mode = "auto"
        self._refresh_mode_pending = False  # schon ein eigener Job in der Queue?
        self._refresh_mode_next_due = 0.0  # time.monotonic()-Zeitpunkt des nächsten Takts
        # Policy-Name des ZULETZT VOM MODUS SELBST gesehenen Requests — nicht
        # der globale rate_limiter._last_policy, der von JEDEM Request (auch
        # einem dazwischengefunkten Klick auf einen anderen Endpunkt)
        # überschrieben werden kann (§steady_pace_interval_s).
        self._refresh_mode_policy: str | None = None
        self._stash_mode_round_picks = 0  # normale Picks seit dem letzten Coverage-Pick
        self._stash_mode_coverage_cursor = 0  # Rundlauf-Index durch die leeren Fächer, §_pick_stash_mode_candidate
        self._stash_mode_list_refresh_due = False  # nächster Tick lädt die Fach-LISTE neu, §_drive_refresh_mode
        # Angeklicktes Fach, das im Stash-Modus als nächstes drankommen soll
        # (§_prioritise_selection_in_refresh_mode) — vordrängeln statt sofort feuern.
        self._refresh_mode_priority_id: str | None = None
        self._raw_data_viewer: RawDataViewer | None = None
        self._offline = False  # GGG nicht erreichbar (Wartung am Patchday)
        self._live_leagues: set[str] | None = None  # letzte /account/leagues-Antwort; None = noch unbekannt
        self._restore_cached_data()

        self.worker = ApiWorker()
        # BootstrapJob muss als ERSTER Job in der Queue landen — vor jedem
        # Job, den `_build_ui()` (z. B. über `_populate_cached_leagues()` →
        # `_on_league_changed`) synchron mit-auslöst. Sonst würde ein
        # ungeloggter FetchStashListJob vor dem Bootstrap laufen, mit einem
        # HTTP-Client ohne gesetzten Token — GGG antwortet mit 401, unser
        # AuthError-Handler löscht daraufhin den (eigentlich gültigen!)
        # gespeicherten Token, und Bootstrap findet ihn dann schon gelöscht
        # vor. Real beobachtet: Rückfrage "warum wird mein Token
        # zwischendurch invalid, sollte doch Stunden gültig sein" — der Token
        # war nie wirklich abgelaufen, wir haben ihn uns selbst zerstört
        # (FALLSTRICKE #30). `submit()` ist eine reine Queue-Operation und
        # funktioniert bereits vor `worker.start()`.
        self.worker.submit(BootstrapJob())
        self._build_ui()
        self._connect_worker()
        self.worker.start()

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(self.AUTO_REFRESH_INTERVAL_MS)
        self._auto_refresh_timer.timeout.connect(self._maybe_auto_refresh)
        self._auto_refresh_timer.start()

        # Sekündliches Ticken der Countdown-Anzeige — unabhängig vom
        # Auto-Refresh-Timer selbst, der nur alle AUTO_REFRESH_INTERVAL_MS
        # feuert. Peter: "ca. 5 Minuten gewartet ohne dass irgendwas
        # passiert ist" — ohne sichtbaren Countdown ist von außen nicht zu
        # unterscheiden, ob der Timer noch läuft oder der nächste Tick aus
        # gutem Grund (Rate-Limit, Token abgelaufen, …) nichts tut.
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._update_auto_refresh_countdown)
        self._countdown_timer.start()
        self._update_auto_refresh_countdown()

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
        # Ältere Caches liegen noch flach vor (Ordner-Inhalte auf oberster
        # Ebene, teils zusätzlich im Ordner) — beim Laden einmal aufräumen,
        # sonst zeigt der Baum bis zum nächsten Listen-Refresh die alte,
        # falsche Reihenfolge samt Dubletten (§_nest_folder_members).
        self._stash_trees = {league: self._nest_folder_members(tree)
                             for league, tree in cached.stash_trees.items()}
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
        # Toolbar an, mit dem sie sich komplett ausblenden lässt — ohne Menü-
        # leiste gäbe es dann keinen Weg mehr zurück (Login, Refresh, Liga-
        # Wahl, Suche — alles verschwunden). aus Versehen
        # passiert. Deaktiviert.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._login_action = QAction("🔑 Log in", self)
        self._login_action.triggered.connect(lambda: self.worker.submit(LoginJob()))
        toolbar.addAction(self._login_action)

        self._refresh_action = QAction("⟳ Refresh", self)
        self._refresh_action.triggered.connect(self._refresh)
        toolbar.addAction(self._refresh_action)

        toolbar.addWidget(QLabel(" Mode: "))
        self._refresh_mode_combo = QComboBox()
        self._refresh_mode_combo.addItems(["Auto", "Single", "Stash"])
        self._refresh_mode_combo.setToolTip(
            "Auto: keeps the open tab/character live, sweeps the rest of the "
            "stash in the background (default, reserves budget for manual clicks).\n"
            "Single: refreshes just the currently selected tab or character "
            "on a steady clock, as tight as the rate limit allows.\n"
            "Stash: cycles through the whole stash on that same steady clock, "
            "non-empty tabs first. For an immediate one-off pass, use "
            "\"Load All Tabs\" instead.")
        self._refresh_mode_combo.currentTextChanged.connect(self._on_refresh_mode_changed)
        toolbar.addWidget(self._refresh_mode_combo)

        self._load_all_action = QAction("⇊ Load All Tabs", self)
        self._load_all_action.setToolTip(
            "Load items from all stash tabs of the current league one by one "
            "(can take a while depending on tab count and rate limit)")
        self._load_all_action.triggered.connect(self._load_all_items)
        toolbar.addAction(self._load_all_action)

        self._export_action = QAction("💾 Export CSV", self)
        self._export_action.setToolTip("Save the currently visible (filtered) items as CSV")
        self._export_action.triggered.connect(self._export_csv)
        toolbar.addAction(self._export_action)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" League: "))
        self._league_combo = QComboBox()
        self._league_combo.setMinimumWidth(160)
        self._league_combo.currentTextChanged.connect(self._on_league_changed)
        toolbar.addWidget(self._league_combo)

        toolbar.addWidget(QLabel("  Type: "))
        # 8 Checkboxen statt Namen (Namen wären zu lang) —
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
        self._filter_edit.setPlaceholderText("🔍 Search all tabs of the league — * for everything")
        self._filter_edit.setFixedWidth(260)
        self._filter_edit.setClearButtonEnabled(True)  # eingebautes "x" zum Leeren
        toolbar.addWidget(self._filter_edit)

        # Linke Seite: Charakterliste (flach) oben, Stash-Baum unten — je mit
        # eigener Überschrift statt eines gemeinsamen Wrapper-Baums (spart
        # eine Ebene).
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        char_label = QLabel("Characters")
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
        for name in ("Req.Lvl", "Str", "Dex", "Int"):  # schmale Zahlenspalten
            self.table.setColumnWidth(COLUMNS.index(name), 58)
        self.table.setColumnWidth(MODS_COL, 320)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        # Spalten per Rechtsklick auf den Header an-/abwählbar;
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

        self._status_msg = QLabel("Starting…")
        self.statusBar().addWidget(self._status_msg, stretch=1)
        # Range (0, 0) macht aus der QProgressBar einen "busy"-Indikator mit
        # eingebauter Lauf-Animation (kein eigener QTimer/keine Assets nötig).
        self._busy_indicator = QProgressBar()
        self._busy_indicator.setRange(0, 0)
        self._busy_indicator.setFixedSize(90, 14)
        self._busy_indicator.setTextVisible(False)
        self._busy_indicator.hide()
        self.statusBar().addWidget(self._busy_indicator)
        # Permanentes Offline-Banner (GGG-Wartung am
        # Patchday/Liga-Start) — separat vom transienten _status_msg, damit
        # es nicht von der nächsten "Lade …"-Meldung überschrieben wird.
        self._offline_label = QLabel("")
        self._offline_label.setStyleSheet("color: #d9a441; font-weight: 600;")
        self.statusBar().addPermanentWidget(self._offline_label)
        # Sichtbarer Nachweis, dass der Hintergrund-Auto-Refresh arbeitet
        # ("Bist du dir sicher, dass das funktioniert?").
        self._auto_refresh_label = QLabel("")
        self.statusBar().addPermanentWidget(self._auto_refresh_label)
        # Countdown bis zum nächsten Auto-Refresh-Tick, bzw. der Grund, warum
        # gerade keiner stattfindet (§ _auto_refresh_blocked_reason).
        self._auto_refresh_countdown_label = QLabel("")
        self._auto_refresh_countdown_label.setStyleSheet("color: #8a8478;")
        self.statusBar().addPermanentWidget(self._auto_refresh_countdown_label)
        self.statusBar().addPermanentWidget(QLabel(config.DISCLAIMER))

        # Liga-Dropdown SOFORT aus dem Cache befüllen — unabhängig vom
        # Netzwerk nutzbar (GGG-Wartung am Patchday). Muss
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
        """Hat der Nutzer dort tatsächlich einen Spielstand (Charaktere oder
        bereits geladene Items)? Grundlage der Dropdown-Sortierung — GGG legt
        pro Account automatisch leere Hardcore-/Ruthless-Varianten an, auch
        wenn der Nutzer dort nie gespielt hat ("Hardcore
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
    # ("als Offline-Liga anhängen", nicht nur positionell
    # trennen). Text bewusst so gewählt, dass er nie mit einem echten
    # Liga-Namen kollidiert.
    _ARCHIVED_HEADER = "── Ended leagues (cache only, no online access) ──"

    def _rebuild_league_combo(self, live_leagues: list[str] | None) -> None:
        """Baut das Liga-Dropdown neu auf: aktuell gültige
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
        # nicht suchen — sonst würde findText("") zufällig etwas mit leerem
        # Text treffen).
        idx = self._league_combo.findText(previous) if previous else -1
        self._league_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._league_combo.blockSignals(False)
        if self._league_combo.count():
            self._on_league_changed(self._league_combo.currentText())
        self._update_tree_offline_display()  # auch wenn _on_league_changed oben früh returnt

    def _current_league_is_archived(self) -> bool:
        """True, wenn die aktuelle Liga zwar im Cache existiert, aber nicht
        mehr in der letzten Live-Antwort von /account/leagues auftaucht,
        etwa weil eine temporäre Liga beendet wurde. Auf deren Inhalte gibt
        es dann keinen Online-Zugriff mehr.

        ``None`` bedeutet, dass noch nie eine Live-Antwort eintraf, und gilt
        nicht als archiviert. Sonst würde ein Offline-Start (§4.12)
        fälschlich jede gecachte Liga als beendet markieren."""
        return self._live_leagues is not None and self._current_league not in self._live_leagues

    def _update_tree_offline_display(self) -> None:
        """Baum zeigt 📴 statt ⟳, wenn entweder GGG global nicht erreichbar
        ist (§4.12) oder die aktuell angezeigte Liga archiviert ist (Liga
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

    # --- Spalten-Sichtbarkeit der Item-Tabelle --------- #

    # "Type" ist standardmäßig aus: die Rarity steckt bereits in der
    # Namensfarbe. Die Tab-Spalte wird automatisch verwaltet (aus bei
    # Einzelfach, an bei Aggregat) und ist deshalb nicht im Menü.
    DEFAULT_HIDDEN_COLUMNS = frozenset({"Type"})

    def _settings(self) -> QSettings:
        """INI-Datei statt Registry, konsistent zum Datei-Cache-Ansatz."""
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
        # ("z. B. 20% Quality oder iLvl <45"). Übernahme
        # mit Enter; aktive Filter tragen 🔍 im Spalten-Header.
        if clicked_col > ICON_COL:
            title = menu.addAction(f"Filter \"{COLUMNS[clicked_col]}\" (Enter applies):")
            title.setEnabled(False)
            edit = QLineEdit(self.proxy.column_filter(clicked_col))
            edit.setPlaceholderText("e.g. >=20, <45, =text, substring")
            edit.returnPressed.connect(
                lambda c=clicked_col, e=edit, m=menu: (
                    self._apply_column_filter(c, e.text()), m.close()))
            field = QWidgetAction(menu)
            field.setDefaultWidget(edit)
            menu.addAction(field)
            if self.proxy.filtered_columns():
                clear_action = menu.addAction("✕ Clear All Column Filters")
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
            f"Column filter [{active}]: {shown} of {total} items visible"
            if active else f"Column filter removed — {total} items")

    def _clear_column_filters(self) -> None:
        self.proxy.clear_column_filters()
        self._status_msg.setText(
            f"All column filters cleared — {self.table_model.rowCount()} items")

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
        self._logged_in = True
        self._login_action.setText(f"⚷ {account_name}")
        self._login_action.setEnabled(False)
        self.worker.submit(FetchLeaguesJob())
        self.worker.submit(FetchCharactersJob())

    def _on_login_required(self, reason: str) -> None:
        """Auch vom Token-Ablauf MITTEN in der Session erreicht (nicht nur
        beim Start) — ``AuthError`` kann aus jedem Job kommen, auch einem
        stillen Auto-Refresh-Tick. ``_logged_in = False`` stoppt in diesem
        Fall den Auto-Refresh (§4.8), sonst würde er alle 40s mit demselben,
        bereits als ungültig bekannten Token weiter gegen die API laufen —
        real beobachtet: mehrere Minuten lang HTTP 401 im Log, alle exakt
        AUTO_REFRESH_INTERVAL_MS auseinander, bis der Nutzer den Login-Button
        von Hand bemerkt (Rückfrage "Automatik hat nicht hingehauen").
        """
        self._logged_in = False
        self._login_action.setEnabled(True)
        self._login_action.setText("🔑 Log in")
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
            # Versuch, der ohnehin nur scheitern kann.
            self._status_msg.setText(
                f"{league}: league ended — showing the last known state "
                "(no more online access).")
        else:
            # … und trotzdem im Hintergrund bestätigen/aktualisieren (wie bisher).
            self.worker.submit(FetchStashListJob(league))
        # Stash-Modus soll sofort auf die neue Liga umsteigen statt den
        # Rest-Takt der vorherigen Liga abzuwarten.
        self._refresh_mode_pending = False
        self._refresh_mode_next_due = 0.0
        self._refresh_mode_policy = None
        self._stash_mode_round_picks = 0
        self._stash_mode_coverage_cursor = 0
        self._stash_mode_list_refresh_due = False
        self._refresh_mode_priority_id = None  # Fach-IDs gelten nur innerhalb einer Liga
        self._drive_refresh_mode()

    def _on_characters(self, characters: list[Character]) -> None:
        """/character liefert ligenübergreifend; gefiltert wird lokal übers Dropdown.

        Kein eigener Liga-Level in der Liste (spart eine Ebene) — das
        Liga-Dropdown steuert Charaktere und Stash-Tabs gemeinsam, ein
        Wechsel zwischen Ligen ist bei Items/Stash ohnehin nicht möglich.
        """
        self._all_characters = characters
        self._apply_character_league_filter()
        self._persist_cache()

    def _apply_character_league_filter(self) -> None:
        filtered = [c for c in self._all_characters if c.league == self._current_league]
        self.character_list.set_characters(filtered)

    def _activate_stash_tree(self, stashes: list[StashTab]) -> None:
        """Baum rendern + abgeflachte Liste aktualisieren — für Live- und
        Cache-Daten. Setzt voraus, dass ``stashes`` bereits unter der
        aktuellen Liga in ``_stash_trees`` hängt: ``_tab_positions()`` für
        die Pos.-Spalte liest von dort."""
        self._leaf_stashes = self._flatten_stashes(stashes)
        last_loaded = self._last_loaded.get(self._current_league, {})
        item_counts = self._item_counts_for_current_league()
        self.tree.set_stashes(stashes, last_loaded=last_loaded, item_counts=item_counts,
                              positions=self._tab_positions())
        self._update_auto_refresh_label()

    def _item_counts_for_current_league(self) -> dict[str, int]:
        """stash_id → tatsächlich geladene Item-Anzahl — überschreibt im Baum
        den bloßen API-Hinweis (metadata.items bei Map-/Unique-Kindern)."""
        return {sid: len(items)
                for sid, items in self._items.get(self._current_league, {}).items()}

    def _on_stash_list(self, stashes: list[StashTab], silent: bool) -> None:
        """``silent=True`` kommt vom periodischen Listen-Refresh des
        Stash-Modus (§_drive_refresh_mode) — deckt Umsortierungen/neue/
        entfernte Fächer auf, die ein reiner Item-Sweep nie bemerken würde,
        ohne den laufenden Sweep selbst zu unterbrechen."""
        # Erst die flache Liste in die echte Ordner-Struktur bringen, dann
        # mergen: so füllen sich die Ordner aus der Liste selbst und der Merge
        # kümmert sich nur noch um Spezial-Tab-Kinder (§_nest_folder_members).
        stashes = self._nest_folder_members(stashes)
        # Die Liga-LISTE der API kennt die Kinder von Spezial-Tabs (MapStash,
        # UniqueStash) nicht — ohne Merge gingen bereits entdeckte Unter-Tabs
        # bei jedem Listen-Refresh/Liga-Wechsel wieder verloren.
        old = self._stash_trees.get(self._current_league)
        if old:
            self._merge_known_children(stashes, old)
        self._stash_trees[self._current_league] = stashes
        self._activate_stash_tree(stashes)
        if self._search_all_active:
            self._enter_search_all()  # Suchansicht auf die frische Liste umstellen
        self._persist_cache()
        if silent:
            # Policy-Name JETZT festhalten, siehe Kommentar in
            # _count_silent_refresh.
            self._refresh_mode_policy = self.worker.rate_limiter.last_policy
            self._note_refresh_mode_job_done()

    @staticmethod
    def _nest_folder_members(stashes: list[StashTab]) -> list[StashTab]:
        """Ordner-Inhalte aus der flachen API-Liste unter ihren Ordner hängen.

        GGG liefert die Fächer FLACH: ein Fach, das im Spiel in einem Ordner
        liegt, kommt als ganz normaler Listeneintrag mit ``folder`` = ID des
        Ordners. Dessen ``index`` setzt die Zählung des Ordners fort und
        überschneidet sich mit der anderer Ordner — als Truhen-Position ist er
        ohnehin unbrauchbar (FALLSTRICKE #21). Ohne diese Umformung landen die
        Ordner-Inhalte auf der obersten Ebene und schieben sich zwischen die
        echten Fächer; die Baum-Reihenfolge weicht dadurch von der im Spiel ab
        und die Ordner bleiben leer (FALLSTRICKE #38).

        Ein Mitglied, das der Ordner bereits kennt (aus einem früheren Abruf
        grafted), wird ersetzt statt ein zweites Mal eingehängt — sonst stünde
        dasselbe Fach zweimal im Baum. Bereits entdeckte Unter-Tabs des
        alten Eintrags bleiben dabei erhalten.

        Zeigt ``folder`` auf eine unbekannte ID, bleibt das Fach oben stehen:
        besser an der falschen Stelle sichtbar als gar nicht.
        """
        folders = {s.id: s for s in stashes if s.is_folder}
        if not folders:
            return list(stashes)
        top: list[StashTab] = []
        for stash in stashes:
            parent = folders.get(stash.folder) if stash.folder else None
            if parent is None or parent is stash:
                top.append(stash)
                continue
            for i, known in enumerate(parent.children):
                if known.id == stash.id:
                    if not stash.children and known.children:
                        stash.children = known.children
                    parent.children[i] = stash
                    break
            else:
                parent.children.append(stash)
        return top

    @staticmethod
    def _merge_known_children(new_stashes: list[StashTab],
                              old_stashes: list[StashTab]) -> None:
        """Überträgt in früheren Abrufen entdeckte Spezial-Tab-Kinder in die
        frisch geladene Stash-Liste (in-place).

        Läuft nach ``_nest_folder_members``, die Ordner also bereits aus der
        Liste selbst gefüllt. Ein LEERER Ordner ist damit echt leer und darf
        seine alten Mitglieder nicht zurückbekommen — sonst tauchten im Spiel
        gelöschte oder herausgezogene Fächer wieder auf."""
        old_by_id: dict[str, StashTab] = {}

        def index(stashes: list[StashTab]) -> None:
            for stash in stashes:
                old_by_id[stash.id] = stash
                index(stash.children)

        def graft(stashes: list[StashTab]) -> None:
            for stash in stashes:
                if stash.children:
                    graft(stash.children)  # Ordner: Kinder kommen aus der Liste selbst
                elif not stash.is_folder:
                    old = old_by_id.get(stash.id)
                    if old is not None and old.children:
                        stash.children = old.children

        index(old_stashes)
        graft(new_stashes)

    @staticmethod
    def _flatten_stashes(stashes: list[StashTab]) -> list[StashTab]:
        """Rekursiv alle Nicht-Container-Tabs einsammeln (Reihenfolge wie im Baum).

        Container = Ordner oder Spezial-Tabs mit bereits entdeckten Kindern
        (MapStash/UniqueStash) — bei denen sind die KINDER die ladbaren
        Einheiten. Ein Spezial-Tab vor seiner Entdeckung hat keine children
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
                # der Tab-Spalte.
                self._show_special_parent_aggregate(stash, name)
                return
            # Spezial-Tab ohne bekannte Kinder: immer fetchen, den Item-Cache
            # bewusst ignorieren — ein alter "0 Items"-Eintrag (von vor dem
            # Spezial-Tab-Feature) wäre sonst ein permanenter Cache-Treffer,
            # und die Kinder-Entdeckung fände nie statt. Ausnahme ist eine
            # archivierte Liga, dort gibt es nichts mehr zu entdecken.
            if self._archived_league_guard(
                    f"{name}: league ended — sub-tabs no longer available."):
                return
            self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name))
            return
        league_items = self._items.get(self._current_league, {})
        if stash_id in league_items:
            # Speicher-/Datei-Cache: kein erneuter API-Call (Doku §5)
            self._show_items(stash_id, league_items[stash_id], name)
            # … im Stash-Modus zusätzlich als nächstes Ziel vormerken, damit
            # das angeklickte Fach als Erstes an die Reihe kommt.
            self._prioritise_selection_in_refresh_mode(stash_id)
            return
        if self._archived_league_guard(
                f"{name}: never loaded — league ended, no longer available."):
            return
        self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name,
                                              parent_id=self._parent_id_of(stash_id)))

    def _on_stash_refresh(self, stash_id: str, name: str) -> None:
        """Klick auf den Refresh-Button eines Tabs — bewusst AM Cache vorbei."""
        self._showing_aggregate = False
        if self._archived_league_guard(f"{name}: league ended — refresh no longer possible."):
            return
        self.worker.submit(FetchStashItemsJob(self._current_league, stash_id, name,
                                              parent_id=self._parent_id_of(stash_id)))

    def _count_silent_refresh(self, league: str, stash_id: str) -> None:
        """Zählt einen Tab für "X von Y Stash-Tabs aktualisiert" genau
        einmal pro Session — unabhängig davon, ob er (auch aus einer
        früheren Session/dem Datei-Cache) schon vorher geladen war.

        Ein reiner ``already_loaded``-Check anhand von ``_last_loaded``
        wäre hier falsch: Wer eine Liga schon einmal komplett heruntergeladen
        hat, hat für JEDEN Tab ``already_loaded=True``, sobald der Cache
        beim Start geladen ist — der Zähler bliebe dann für immer bei 0
        stehen, obwohl der Sweep im Hintergrund längst reihum die ältesten
        Tabs auffrischt (real beobachtet: "0 von 94" dauerhaft, obwohl der
        Zeitstempel im Baum sich sichtbar aktualisiert). Das eigene
        Session-Set verhindert stattdessen nur das ursprüngliche Problem
        (FALLSTRICKE #27): das wiederholte Live-Halten des GERADE
        angezeigten Fachs bei jedem Tick soll nicht mehrfach zählen.

        Gezählt wird der echte Truhenplatz (`_tab_positions()`), nicht die
        rohe `stash_id` — sonst zählt jede einzelne Map-/Unique-Sektion als
        eigener "Tab" und "Y" wäre die aufgeblähte Zahl ladbarer Einheiten
        statt der tatsächlichen Fächer-Anzahl (real beobachtet: "939" statt
        391 echter Fächer in Standard, FALLSTRICKE #36 — derselbe
        Zähl-Fehler wie bei der Positions-Spalte, nur an anderer Stelle)."""
        slot = self._tab_positions(league).get(stash_id, stash_id)
        counted = self._auto_refresh_counted.setdefault(league, set())
        if slot not in counted:
            counted.add(slot)
            self._auto_refresh_counts[league] = len(counted)
        # Policy-Name JETZT festhalten, nicht erst in _drive_refresh_mode
        # auslesen — sonst könnte ein dazwischengefunkter anderer Request
        # (z. B. der normale Refresh-Button) den globalen Stand vorher
        # schon wieder überschrieben haben.
        self._refresh_mode_policy = self.worker.rate_limiter.last_policy
        self._note_refresh_mode_job_done()

    def _note_refresh_mode_job_done(self) -> None:
        """Ein eigener Job des Single-/Stash-Modus ist durch (Erfolg wie
        Fehler): Kette freigeben und den nächsten Takt AB JETZT zählen.
        Im "auto"-Modus ein No-Op, da ``_drive_refresh_mode`` dort nichts tut.

        Der Takt läuft bewusst ab dem ENDE eines Requests, nicht ab seinem
        Absenden. Wartet der Rate-Limiter mitten im Job minutenlang
        (``check_and_wait``), wäre eine beim Absenden gesetzte Fälligkeit
        längst abgelaufen — der nächste Pick feuerte dann sofort hinterher.
        Genau das hat sich real hochgeschaukelt: 300s-Sperre → Doppel-Request
        beim Wiederanlauf → dadurch erneut 29 Treffer im Fenster → wieder
        Sperre, endlos (FALLSTRICKE #34)."""
        self._refresh_mode_pending = False
        self._refresh_mode_next_due = time.monotonic() + \
            self.worker.rate_limiter.steady_pace_interval_s(self._refresh_mode_policy)
        self._drive_refresh_mode()

    def _on_stash_items(self, league: str, stash_id: str, name: str,
                        items: list[Item], silent: bool) -> None:
        """``league`` kommt aus dem Signal (nicht ``self._current_league``!) —
        sonst würde ein spät eintreffender Hintergrund-Job die Daten der
        MOMENTAN aktiven Liga verfälschen, falls der Nutzer zwischenzeitlich
        die Liga gewechselt hat."""
        self._last_loaded.setdefault(league, {})[stash_id] = datetime.now(timezone.utc).isoformat()
        self._items.setdefault(league, {})[stash_id] = items
        if silent:
            self._count_silent_refresh(league, stash_id)
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
        # offen ist (Regression, das Live-Halten des
        # aktuellen Fachs aktualisierte bisher nur den Cache/Baum, nicht
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
            # Erst NACH dem Anhängen der Kinder neu abflachen — die neu
            # entdeckten Unter-Fächer sind ab jetzt die ladbaren Einheiten
            # (Sweep, Bulk-Load). Die Pos.-Spalte hängt nicht hieran,
            # sondern direkt am Baum (§_tab_positions).
            self._leaf_stashes = self._flatten_stashes(tree)
        if silent:
            self._count_silent_refresh(league, stash_id)
        self._persist_cache()
        if league != self._current_league:
            return
        league_loaded = self._last_loaded.get(league, {})
        item_counts = self._item_counts_for_current_league()
        self.tree.set_children(stash_id, children, last_loaded=league_loaded,
                               item_counts=item_counts, expand=not silent,
                               positions=self._tab_positions())
        # Gesamtsumme über die Kinder (bekannte API-Hinweise + evtl. schon
        # geladene) auch am Eltern-Knoten zeigen.
        counts = [item_counts.get(c.id, c.metadata.get("items")) for c in children]
        total = sum(c or 0 for c in counts) if any(c is not None for c in counts) else None
        self.tree.mark_loaded(stash_id, league_loaded[stash_id], count=total)
        self._update_auto_refresh_label()
        if not silent:
            self._status_msg.setText(
                f"{name}: special tab with {len(children)} sub-tabs — "
                "click a sub-tab to load its items")
            self._update_raw_viewer(stash_id, name)

    def _stamp_category(self, league: str, stash_id: str, items: list[Item]) -> str | None:
        """Namenlose Unique-Stash-Fächer nach dem ersten Item-Load taufen
        ("über die Kategorie gehen, z. B. Two Handed Axe,
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

    def _tab_positions(self, league: str | None = None) -> dict[str, int]:
        """1-basierte Position jedes Fachs in der Reihenfolge, in der die
        API sie für die angegebene (oder sonst die aktuelle) Liga
        zurückliefert. Grundlage der Position-Spalte in der Item-Tabelle
        (§4.11), der Pos.-Spalte im Stash-Baum (§4.7.1) und des
        Auto-Refresh-Zählers (§_count_silent_refresh, §_update_auto_refresh_label).

        Explizite ``league`` nötig, wenn der Aufrufer für eine ANDERE als
        die gerade aktive Liga rechnet (z. B. ein spät eintreffender
        Hintergrund-Job nach einem Liga-Wechsel) — sonst würde
        ``self._current_league`` stillschweigend die falsche Truhe befragen.

        ``StashTab.index`` ist dafür ungeeignet: Fächer wandern beim
        Liga-Ende nach Standard und behalten ihren ursprünglichen Index aus
        der alten Liga, sodass dort mehrere Fächer denselben Wert tragen
        (FALLSTRICKE #21). Die Reihenfolge der API-Antwort entspricht
        dagegen der tatsächlichen Position in der Truhen-Leiste.

        Gezählt wird, was in der Truhen-Leiste einen Platz belegt — NICHT
        ``_leaf_stashes``, das die ladbaren EINHEITEN beschreibt und damit
        eine andere Frage beantwortet. Der Unterschied betrifft die
        Spezial-Tabs: ein Map-/Unique-Stash ist EIN Fach in der Leiste,
        seine Sektionen liegen innerhalb dieses einen Platzes. In
        ``_leaf_stashes`` ist es umgekehrt (der Eltern-Tab fällt raus,
        die Kinder sind die ladbaren Einheiten) — direkt daraus
        nummeriert, bekamen Map-/Unique-Tabs gar keine Position, während
        ihre Sektionen je eine eigene verbrauchten und alle folgenden
        Fächer verschoben (real: ein einzelner Map-Stash belegte die
        Positionen 28–38). Die Sektionen erben deshalb hier die Nummer
        ihres Eltern-Tabs, damit auch Items aus ihnen den richtigen
        Truhenplatz anzeigen. Ordner belegen wie bisher keinen eigenen
        Platz, sondern nur die Fächer darin.
        """
        positions: dict[str, int] = {}
        counter = 0

        def walk(nodes: list[StashTab]) -> None:
            nonlocal counter
            for stash in nodes:
                if stash.is_folder:
                    walk(stash.children)
                    continue
                counter += 1
                positions[stash.id] = counter
                for child in self._flatten_stashes(stash.children):
                    positions[child.id] = counter

        walk(self._stash_trees.get(league or self._current_league) or [])
        return positions

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
        den Fach-Namen ("Map (Tier 1)")."""
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
            f"{name}: {len(items)} items from {loaded} of {len(stash.children)} "
            "loaded sub-tabs")
        self._update_raw_viewer(stash.id, name)

    # --- Alle Tabs laden (Bulk) ----------------------------------------- #

    def _load_all_items(self) -> None:
        if self._bulk_dialog is not None:
            return  # läuft schon
        if not self._leaf_stashes:
            QMessageBox.information(
                self, "Load All Tabs",
                "No stash tabs loaded — please select a league first.")
            return
        if self._current_league_is_archived():
            # Liga beendet — keiner der nicht gecachten Tabs ist noch
            # abrufbar, "Alle Tabs laden" kann nur den Cache zusammenfassen.
            self._show_aggregate()
            self._status_msg.setText(
                "League ended — showing the last known state of all loaded tabs.")
            return
        league_items = self._items.get(self._current_league, {})
        # Spezial-Tabs ohne entdeckte Kinder immer mitnehmen: ein evtl.
        # vorhandener Item-Cache-Eintrag ist bei ihnen bedeutungslos (§4.10).
        to_fetch = [s for s in self._leaf_stashes
                    if s.id not in league_items or s.type in self.SPECIAL_TAB_TYPES]
        # Älteste bzw. nie geladene Fächer zuerst — bricht der Nutzer über
        # "Abbrechen" vorzeitig ab, sind es die dringendsten, die schon
        # durch sind, nicht die per Zufall der Truhen-Reihenfolge nach
        # vorne gerutschten.
        league_loaded = self._last_loaded.get(self._current_league, {})
        to_fetch.sort(key=lambda s: (self._NEVER_LOADED if s.id not in league_loaded
                                     else datetime.fromisoformat(league_loaded[s.id])))
        if not to_fetch:
            self._show_aggregate()  # schon alles im Cache
            return

        # Anzeige zählt echte Truhenplätze, nicht die rohen Abrufe: eine
        # Map-/Unique-Sektion braucht zwar einen eigenen Request, teilt sich
        # aber den Platz ihres Eltern-Tabs (FALLSTRICKE #36 — sonst z. B.
        # "58/561" statt "58/391").
        positions = self._tab_positions()
        real_total = len({positions.get(s.id, s.id) for s in to_fetch})

        self._bulk_dialog = QProgressDialog(
            "Loading stash tabs…", "Cancel", 0, real_total, self)
        self._bulk_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._bulk_dialog.setMinimumDuration(0)
        self._bulk_dialog.canceled.connect(self.worker.cancel_bulk)
        self.worker.submit(FetchAllItemsJob(self._current_league, to_fetch, positions))

    def _on_bulk_progress(self, done: int, total: int, name: str) -> None:
        if self._bulk_dialog is not None:
            self._bulk_dialog.setLabelText(f"Loading stash tab {done}/{total}: {name}")
            self._bulk_dialog.setValue(done)

    def _on_bulk_finished(self, success: int, total: int) -> None:
        if self._bulk_dialog is not None:
            self._bulk_dialog.close()
            self._bulk_dialog = None
        self._status_msg.setText(f"All tabs loaded: {success}/{total} successful.")
        self._show_aggregate()

    def _show_aggregate(self) -> None:
        """Items aller bereits geladenen Tabs und Charaktere dieser Liga
        zusammen anzeigen (lokal filter-/exportierbar), siehe `_league_wide_items`."""
        self._showing_aggregate = True
        self._search_all_active = False
        self._current_tab_name = "All Tabs"
        self._current_stash_id = None  # Rückkehr aus der Suche landet wieder hier
        self._current_character_name = None
        items, sources, tab_indices, stash_ids = self._league_wide_items()
        self.table.setColumnHidden(TAB_COL, False)  # Aggregat: Herkunft zeigen
        self.table_model.set_items(items, sources, tab_indices, stash_ids,
                                   request_icons=False)  # lazy
        self._status_msg.setText(f"All Tabs: {len(items)} items total")

    def _league_wide_items(self) -> tuple[list[Item], list[str], list[int | None], list[str | None]]:
        """Alle gecachten Items der aktuellen Liga, je Item ergänzt um
        Herkunfts-Fachname, Tab-Position und Tab-ID.

        Die Tab-Position stammt aus ``_tab_positions`` (1-basierter Platz in
        ``_leaf_stashes``, nicht ``stash.index``) und unterscheidet
        gleichnamige Fächer. Die Tab-ID dient der Baum-Hervorhebung bei
        Zeilenauswahl.

        Zusätzlich enthalten sind Ausrüstung und Inventar aller Charaktere
        derselben Liga, sofern bereits geladen (§4.13). Als Herkunft steht
        dort "Charaktername: Slot" statt eines Fach-Namens; Position und
        Tab-ID bleiben ``None``, da kein Truhenfach beteiligt ist."""
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
        for char in self._all_characters:
            if char.league != self._current_league:
                continue
            cached = self._character_items.get(char.name)
            if not cached:
                continue
            items.extend(cached)
            sources.extend(f"{char.name}: {item.inventoryId or '?'}" for item in cached)
            tab_indices.extend([None] * len(cached))
            stash_ids.extend([None] * len(cached))
        return items, sources, tab_indices, stash_ids

    # --- Fächerübergreifende Suche --------------------- #

    def _on_filter_text_changed(self, text: str) -> None:
        """Tippen sucht liga-weit über alle bereits geladenen Fächer; Leeren
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
            f"Searching {loaded} loaded tabs/characters ({len(items)} items) — "
            "clear the field to return to the tab view")

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
            QMessageBox.information(self, "CSV Export", "No items loaded to export.")
            return
        default_path = str(config.downloads_dir() / self._default_export_filename())
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Items as CSV", default_path, "CSV files (*.csv)")
        if not path:
            return
        count = export_items(path, rows)
        self._status_msg.setText(f"Exported {count} items to {path}.")

    def _default_export_filename(self) -> str:
        """Dateiname-Vorschlag: Liga + (aktiver Filtertext, sonst Tab-/Aggregat-Name).

        Die Liga gehört immer mit rein — Items sind nie liga-übergreifend
        gültig, das soll auch am Dateinamen erkennbar sein.
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
            # Keine Sonderbehandlung nötig: der Single-Modus zielt ohnehin
            # immer auf die aktuelle Auswahl (§_pick_single_target), der
            # neue Charakter ist also beim nächsten regulären Takt dran.
            return
        self._status_msg.setText(f"Loading equipment: {char.name}…")
        self.worker.submit(FetchCharacterItemsJob(char.name))

    def _on_character_refresh(self, char: Character) -> None:
        """Rechtsklick → "Aktualisieren" — bewusst AM Cache vorbei, analog
        `_on_stash_refresh`. Schaltet die Ansicht (wie beim Stash-Refresh
        auch) auf diesen Charakter um, sobald das Ergebnis eintrifft."""
        self._current_character_name = char.name
        self._status_msg.setText(f"Loading equipment: {char.name}…")
        self.worker.submit(FetchCharacterItemsJob(char.name))

    def _on_character_items(self, name: str, items: list[Item], silent: bool) -> None:
        """``name`` kommt aus dem Signal, nicht aus der Auswahl — sonst könnte
        ein spät eintreffender Job Daten eines inzwischen abgewählten
        Charakters in die aktuelle Ansicht einsickern lassen (analog
        `_on_stash_items`)."""
        self._character_items[name] = items
        self._character_items_loaded[name] = datetime.now(timezone.utc).isoformat()
        self._persist_cache()
        if silent:
            # Policy-Name jetzt festhalten, siehe Kommentar in
            # _count_silent_refresh.
            self._refresh_mode_policy = self.worker.rate_limiter.last_policy
            self._note_refresh_mode_job_done()
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
        self._status_msg.setText(f"{name}: {len(items)} items (equipment + inventory)")

    def _on_icon(self, url: str, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.table_model.set_icon(url, pixmap)

    def _on_row_selected(self, current, _previous) -> None:
        source_idx = self.proxy.mapToSource(current)
        item = self.table_model.item_at(source_idx.row())
        if item:
            self.detail.show_item(item, self.table_model.pixmap_for(item))
        # Herkunfts-Fach im Baum hervorheben (v. a. bei "*"
        # bzw. Aggregat-Ansichten mit mehreren Quell-Tabs) — highlight_stash
        # nutzt bewusst setCurrentItem statt eines Klick-Signals, damit die
        # aktuelle Such-/Aggregat-Ansicht in der Item-Tabelle nicht verändert
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
        self._status_msg.setText(f"Error: {message}")
        log.error("%s", message)
        # Ein gescheiterter Job überspringt den Erfolgs-Signal-Pfad, über
        # den die Single-/Stash-Modus-Kette sich sonst selbst weitertreibt
        # (§_drive_refresh_mode) — ohne diesen Reset könnte ein einzelner
        # Fehler (z. B. ein transienter Netzwerk-Hänger) die Kette für den
        # Rest der Session stillschweigend stoppen. Im "auto"-Modus ein No-Op.
        # Der Takt wird dabei mitgezählt wie bei Erfolg: ein Fehlschlag darf
        # keinen Sofort-Retry auslösen, der das Rate-Limit-Budget verheizt.
        if self._refresh_mode != "auto":
            self._note_refresh_mode_job_done()

    def _on_offline_changed(self, offline: bool) -> None:
        """GGG nicht erreichbar (Wartung/kein Netz, §4.12) — permanentes
        Banner statt einer Fehlermeldung, die die nächste Statuszeile
        wegwischt, und Markierung im Baum, dass Fächer aus dem Cache kommen."""
        self._offline = offline
        self._update_tree_offline_display()
        self._offline_label.setText(
            "📴 Offline — GGG unreachable, showing cached data"
            if offline else "")

    def _refresh(self) -> None:
        """Stash-Liste + Charaktere neu laden; Item-Daten bleiben unangetastet
        (dafür gibt es die gezielten Refresh-Buttons je Tab im Baum). Für
        eine archivierte (beendete) Liga macht ein Stash-Listen-Refresh
        keinen Sinn — /character bleibt aber liga-unabhängig sinnvoll."""
        if self._current_league and not self._current_league_is_archived():
            self.worker.submit(FetchStashListJob(self._current_league))
        self.worker.submit(FetchCharactersJob())

    # --- Rohdaten-Mini-Viewer (Rechtsklick im Baum) ----- #

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

    # --- Hintergrund-Auto-Refresh ---------------------- #

    def _auto_refresh_blocked_reason(self) -> str | None:
        """Grund, warum der nächste Tick nichts täte, oder ``None``, wenn er
        normal laufen würde. Von ``_maybe_auto_refresh`` als Guard genutzt
        und von ``_update_auto_refresh_countdown`` für die Statuszeile —
        eine Quelle für beides, damit Countdown-Text und tatsächliches
        Verhalten nie auseinanderlaufen."""
        if not self._current_league:
            return "no league selected"
        if self._worker_busy or self._bulk_dialog is not None:
            return "busy"
        if not self._logged_in:
            # Token abgelaufen/ungültig (AuthError, z. B. mitten in der
            # Session) — ohne diese Bremse würde jeder Tick erneut mit dem
            # bereits als ungültig bekannten Token gegen die API laufen und
            # scheitern, real beobachtet über mehrere Minuten alle 40s in
            # Folge (siehe _on_login_required). Manuelle Klicks dürfen es
            # trotzdem versuchen — die zeigen ihr Ergebnis sofort sichtbar.
            return "not logged in"
        if self._current_league_is_archived():
            return "league ended"  # jeder Versuch würde nur scheitern (oder Cache überschreiben)
        if self.worker.rate_limiter.headroom_fraction() < self.AUTO_REFRESH_MIN_HEADROOM:
            return "rate limit budget reserved for manual requests"
        return None

    def _update_auto_refresh_countdown(self) -> None:
        """Sekündlich aktualisierte Anzeige neben dem Auto-Refresh-Zähler:
        Countdown bis zum nächsten Tick, oder der Grund, warum der nächste
        Tick nichts tun wird. ``remainingTime()`` fragt den echten
        Timer-Zustand ab statt eine eigene Restzeit mitzuführen — bleibt so
        auch nach einem Neustart der App/des Timers automatisch korrekt.

        Aktualisiert nebenbei auch das Rate-Limit-Dashboard aus einem reinen
        Snapshot (kein echter Request) — sonst friert die Anzeige während
        einer Auto-Refresh-Pause ein, weil ohne Request auch kein neuer
        Header mehr reinkommt, der sie sonst antreiben würde (Rückfrage
        "Policy-Statusleiste aktualisiert sich während der Pause nicht")."""
        self.dashboard.update_state(*self.worker.rate_limiter.snapshot())
        self.tree.refresh_age_colors()
        # Sicherheitsnetz für Single/Stash: falls die Job-Kette (§_drive_
        # refresh_mode) je stockt — etwa weil ein Fehler den erwarteten
        # Erfolgs-Signal-Pfad übersprungen hat —, stößt der ohnehin
        # laufende Sekunden-Timer sie spätestens hier wieder an.
        self._drive_refresh_mode()
        if not self._current_league:
            self._auto_refresh_countdown_label.setText("")
            return
        if self._refresh_mode != "auto":
            seconds = max(0, round(self._refresh_mode_next_due - time.monotonic()))
            self._auto_refresh_countdown_label.setText(
                f"Refresh mode: {self._refresh_mode_combo.currentText()} — "
                f"next update in {seconds}s")
            return
        reason = self._auto_refresh_blocked_reason()
        if reason is not None:
            self._auto_refresh_countdown_label.setText(f"Auto-refresh paused ({reason})")
            return
        seconds = max(0, self._auto_refresh_timer.remainingTime() // 1000)
        self._auto_refresh_countdown_label.setText(f"Next auto-refresh in {seconds}s")

    def _on_refresh_mode_changed(self, mode: str) -> None:
        self._refresh_mode = mode.lower()
        self._refresh_mode_pending = False
        self._refresh_mode_next_due = 0.0  # sofort beim Umschalten aktualisieren, nicht erst nach einem Takt
        self._refresh_mode_policy = None
        self._refresh_mode_priority_id = None
        self._drive_refresh_mode()

    def _prioritise_selection_in_refresh_mode(self, stash_id: str) -> None:
        """Ein bewusst angeklicktes Fach kommt im Stash-Modus als NÄCHSTES
        dran — es drängelt sich in der Abarbeitungsliste nach vorn, löst
        aber keinen eigenen Request aus.

        Früher übersprang ein Klick den laufenden Takt und feuerte sofort
        (``_kick_refresh_mode_after_selection``). Das war ein Extra-Request
        neben dem gleichmäßigen Takt und hat real mit dazu beigetragen, das
        300s-Fenster auf die Auslöseschwelle zu treiben (FALLSTRICKE #34).
        Der konservative Weg kostet bis zu einen Takt Wartezeit (~11s bei
        30/300s), hält die Anfragerate dafür aber unter allen Umständen
        konstant — egal wie oft und schnell geklickt wird.

        Nur für Cache-Treffer gedacht: bei einem Cache-Miss ist über den
        normalen Auswahl-Pfad ohnehin schon ein (nicht-stiller) Fetch
        unterwegs, eine Vormerkung wäre ein doppelter Request.
        """
        if self._refresh_mode == "stash":
            self._refresh_mode_priority_id = stash_id

    def _pick_single_target(self) -> tuple[str, str, str | None] | None:
        """Aktuell gewählte Zeile für den Single-Modus — Fach oder Charakter,
        gegenseitig exklusiv wie überall sonst (``_current_stash_id`` /
        ``_current_character_name``). Wird bei jedem Kettenglied neu
        ausgewertet, folgt also automatisch, wenn der Nutzer währenddessen
        eine andere Zeile auswählt."""
        if self._current_stash_id is not None:
            return ("stash", self._current_stash_id, self._parent_id_of(self._current_stash_id))
        if self._current_character_name is not None:
            return ("character", self._current_character_name, None)
        return None

    def _pick_stash_mode_candidate(self) -> StashTab | None:
        """Nächster Kandidat für den Stash-Modus: das am längsten nicht
        aktualisierte GEFÜLLTE Fach (Items > 0) — leere Fächer sind
        uninteressant und sollen den Takt nicht mit unnötigen Requests
        blockieren. Läuft, weil der jeweils frisch geladene Kandidat danach
        "jung" ist und erst wieder drankommt, wenn alle anderen gefüllten
        einmal durch waren, quasi endlos rundenweise durch die gefüllten
        Fächer.

        Sobald eine solche Runde vollständig war (`_stash_mode_round_picks`
        erreicht die Anzahl der aktuell gefüllten Fächer), passiert ZWEIERLEI:
        ein zusätzlicher Pick für das nächste noch leere Fach hängt sich an
        (sofern eins existiert), UND `_stash_mode_list_refresh_due` wird für
        den NÄCHSTEN Tick gesetzt — `_drive_refresh_mode` löst daraus einen
        stillen `FetchStashListJob` aus, der Umsortierungen/neue/entfernte
        Fächer aufdeckt, die ein reiner Item-Sweep nie bemerken würde. Danach
        beginnt die Zählung neu. Bewusst kein fester Anteil (z. B. "jeder 10.
        Pick") für beides — die Häufigkeit soll sich automatisch an die
        Truhengröße anpassen. Der Rundlauf durch die leeren Fächer
        (`_stash_mode_coverage_cursor`) folgt der FÄCHERREIHENFOLGE, nicht
        dem Alter: verschiebt der Nutzer im Spiel ein Fach weiter nach
        vorne, rückt es in `_leaf_stashes` ebenso weiter nach vorne und ist
        dadurch beim Rundlauf schneller wieder dran."""
        if not self._leaf_stashes:
            return None
        # Ein bewusst angeklicktes Fach drängelt sich einmalig nach vorn,
        # ohne einen Extra-Request auszulösen (§_prioritise_selection_in_refresh_mode).
        # Zählt als normaler Pick der laufenden Runde, damit die
        # Leer-Fach-Abdeckung dadurch nicht ins Stocken gerät.
        if self._refresh_mode_priority_id is not None:
            priority_id, self._refresh_mode_priority_id = self._refresh_mode_priority_id, None
            for stash in self._leaf_stashes:
                if stash.id == priority_id:
                    self._stash_mode_round_picks += 1
                    return stash
        item_counts = self._item_counts_for_current_league()
        non_empty = [s for s in self._leaf_stashes if item_counts.get(s.id)]
        empty = [s for s in self._leaf_stashes if not item_counts.get(s.id)]

        if non_empty and self._stash_mode_round_picks >= len(non_empty):
            self._stash_mode_round_picks = 0
            self._stash_mode_list_refresh_due = True
            if empty:
                candidate = empty[self._stash_mode_coverage_cursor % len(empty)]
                self._stash_mode_coverage_cursor += 1
                return candidate
            # Keine leeren Fächer (alles bekannt gefüllt) -> normaler Pick unten.

        league_loaded = self._last_loaded.get(self._current_league, {})

        def sort_key(stash: StashTab) -> tuple[bool, datetime]:
            is_empty = not item_counts.get(stash.id)
            iso = league_loaded.get(stash.id)
            age = self._NEVER_LOADED if iso is None else datetime.fromisoformat(iso)
            return (is_empty, age)

        self._stash_mode_round_picks += 1
        return min(self._leaf_stashes, key=sort_key)

    def _drive_refresh_mode(self) -> None:
        """Hält Single-/Stash-Modus am Laufen: ein GLEICHMÄSSIGER Takt,
        kein Burst — der Rate-Limit-Gesamtdurchsatz wäre bei beidem
        identisch, aber ein Burst-dann-Warten sähe minutenlang aus wie
        "nichts passiert" (genau das Problem, das wir für Auto schon
        gefixt haben). Für einen einmaligen Sofort-Burst gibt es bereits
        "Load All Tabs".

        Takt kommt aus ``steady_pace_interval_s(self._refresh_mode_policy)``
        — live aus den tatsächlich bekannten Rate-Limit-Regeln berechnet
        (Peters Beobachtung: bei "30 Treffer/300s" wären das rund 10s), mit
        einem konservativen Default, solange noch keine Regel bekannt ist.
        ``_refresh_mode_policy`` ist bewusst der beim EIGENEN letzten Job
        gemerkte Policy-Name, nicht der globale ``rate_limiter._last_policy``
        — sonst hätte ein dazwischengefunkter Request an einen ANDEREN
        Endpunkt (z. B. der normale "Refresh"-Button, der die Charakter-
        LISTE lädt statt eines einzelnen Charakters) kurzzeitig dessen
        Policy eingemischt und den Takt verfälscht (real beobachtet: 35s
        statt der erwarteten ~10s). Ausgelöst wird dieser Timer-artige Takt
        vom 1-Sekunden-Tick in ``_update_auto_refresh_countdown`` — kein
        eigener QTimer nötig. Die Fälligkeit des nächsten Takts setzt nicht
        diese Methode, sondern ``_note_refresh_mode_job_done`` beim Eintreffen
        der Antwort — siehe dort, warum das nicht schon beim Absenden passieren
        darf.

        Anders als Auto (§_auto_refresh_blocked_reason) wird KEIN
        Rate-Limit-Budget für manuelle Klicks reserviert — das ist hier
        gewollt, der Nutzer hat den Modus bewusst gewählt, um den vollen
        Pool für genau dieses Ziel einzusetzen."""
        if self._refresh_mode == "auto":
            return
        if (self._refresh_mode_pending or not self._logged_in
                or not self._current_league or self._current_league_is_archived()):
            return
        if self._bulk_dialog is not None:
            # "Load All Tabs" taktet sich selbst durch die ganze Truhe
            # (§ApiWorker._fetch_all_items). Liefe der Modus daneben weiter,
            # verdoppelte sich die Anfragerate und beide zusammen liefen
            # prompt in die 300s-Sperre, die jeder für sich vermeidet.
            return
        now = time.monotonic()
        if now < self._refresh_mode_next_due:
            return
        if self._refresh_mode == "single":
            target = self._pick_single_target()
            if target is None:
                return
            kind, ident, parent_id = target
            self._refresh_mode_pending = True
            if kind == "stash":
                self.worker.submit(FetchStashItemsJob(
                    self._current_league, ident, self._current_tab_name,
                    parent_id=parent_id, silent=True))
            else:
                self.worker.submit(FetchCharacterItemsJob(ident, silent=True))
        elif self._refresh_mode == "stash":
            if self._stash_mode_list_refresh_due:
                # Eine Runde durch die gefüllten Fächer ist durch (§_pick_
                # stash_mode_candidate) — jetzt einmalig die Fach-LISTE
                # auffrischen statt eines weiteren Items-Picks, sonst würden
                # Umsortierungen/neue/entfernte Fächer im Spiel nie sichtbar.
                self._stash_mode_list_refresh_due = False
                self._refresh_mode_pending = True
                self.worker.submit(FetchStashListJob(self._current_league, silent=True))
                return
            candidate = self._pick_stash_mode_candidate()
            if candidate is None:
                return
            self._refresh_mode_pending = True
            self.worker.submit(FetchStashItemsJob(
                self._current_league, candidate.id, candidate.display_name,
                parent_id=candidate.parent, silent=True))

    def _maybe_auto_refresh(self) -> None:
        """Läuft per QTimer und lädt höchstens zwei Dinge neu:

        1. Das gerade angezeigte Fach oder den gerade angezeigten
           Charakter, unabhängig vom Alter der Daten, damit die offene
           Ansicht aktuell bleibt. Beide schließen sich gegenseitig aus,
           siehe ``_current_stash_id`` und ``_current_character_name``.
        2. Den normalen Sweep-Kandidaten, der nach und nach den Rest der
           Truhe füllt.

        Beides nur, wenn genug Rate-Limit-Budget für manuelle Abfragen
        übrig bleibt (§4.8). Da pro Tick bis zu zwei Jobs entstehen, ist
        ``AUTO_REFRESH_INTERVAL_MS`` doppelt so groß wie zu der Zeit, als
        nur ein Job je Tick abging.

        Charaktere haben keinen eigenen Sweep. Anders als bei mehreren
        hundert Stash-Tabs ist die Charakterliste klein genug, dass ein
        automatischer Durchlauf keinen Mehrwert brächte; nicht angezeigte
        Charaktere bleiben bis zum nächsten Klick oder einem manuellen
        Refresh per Rechtsklick unverändert.

        Läuft nur im Modus "auto" — Single/Stash treiben sich über
        ``_drive_refresh_mode`` selbst an, ausgelöst durch Job-Abschlüsse
        statt durch diesen 40s-Takt (§_drive_refresh_mode)."""
        if self._refresh_mode != "auto":
            return
        if self._auto_refresh_blocked_reason() is not None:
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
        """Zähler rechts in der Statusleiste: „Auto-refresh: X of Y stash tabs updated“.

        "Y" ist die Zahl echter Truhenplätze (eindeutige Werte aus
        ``_tab_positions()``), NICHT ``len(self._leaf_stashes)`` — das zählt
        jede Map-/Unique-Sektion einzeln und blähte "Y" real auf 939 statt
        391 tatsächlicher Fächer auf (FALLSTRICKE #36). ``_count_silent_
        refresh`` zählt "X" in derselben Einheit, sonst passt der Bruch nicht."""
        total = len(set(self._tab_positions().values()))
        if not total:
            self._auto_refresh_label.setText("")
            return
        count = self._auto_refresh_counts.get(self._current_league, 0)
        self._auto_refresh_label.setText(
            f"Auto-refresh: {count} of {total} stash tabs updated")

    # Noch nie geladene Tabs zählen als "unendlich alt" — sie kommen vor
    # jedem tatsächlich datierten Tab dran (siehe _pick_auto_refresh_candidate).
    _NEVER_LOADED = datetime.min.replace(tzinfo=timezone.utc)

    def _pick_auto_refresh_candidate(self) -> StashTab | None:
        """Ältester Tab der aktuellen Liga — inkl. noch nie geladener Tabs (⬇).

        Noch nie geladene Tabs gelten als "unendlich alt" und werden immer
        als Kandidat betrachtet (die 1-Tag-Schonfrist gilt nur für bereits
        bekannte Daten — es gibt nichts zu schonen, wenn noch gar keine
        Daten da sind). So füllt sich der Stash über die Zeit von selbst,
        ohne dass 391 Tabs einzeln angeklickt werden müssen.
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
