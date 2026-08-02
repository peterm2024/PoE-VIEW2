"""Hauptfenster: verdrahtet Worker-Signale mit den Widgets (Mockup: docs/ui-mockup.html).

Alle Slots hier laufen im Main-Thread (Qt queued connections aus dem Worker).
Die UI löst API-Arbeit ausschließlich über ``worker.submit(Job)`` aus.

"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QMouseEvent, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QCompleter,
                               QDialog, QFileDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QProgressDialog, QSizePolicy, QSplitter,
                               QTableView, QToolBar, QToolButton, QVBoxLayout,
                               QWidget, QWidgetAction)

from poe_view import __version__, config
from poe_view.api.models import (Character, Item, StashTab,
                                 dominant_category, is_ggg_suffix)
from poe_view.api.ninja import PriceIndex
from poe_view.services import data_cache, icon_cache, price_cache
from poe_view.services.zone_watcher import ZoneWatcher, resolve_client_log_path
from poe_view.services.api_worker import (ApiWorker, BootstrapJob,
                                          BulkProgress, FetchAllItemsJob,
                                          FetchCharacterItemsJob,
                                          FetchCharactersJob, FetchIconJob,
                                          FetchLeaguesJob, FetchPricesJob,
                                          FetchStashItemsJob,
                                          FetchStashListJob, LoginJob,
                                          LogoutJob)
from poe_view.services.csv_export import export_items, sanitize_filename
from poe_view.ui import external_tools
from poe_view.ui.character_list import CharacterList
from poe_view.ui.item_detail import ItemDetail
from poe_view.ui.item_table import (COLUMNS, CONFIGURABLE_COLUMNS, ICON_COL,
                                    MODS_COL, POSITION_COL, TAB_COL,
                                    VALUE_COL, ItemFilterProxy, ItemTableModel,
                                    compile_search, format_chaos_value,
                                    matches_search)
from poe_view.ui.item_history import (BASE_COL as HISTORY_BASE_COL,
                                      CHARACTER_COL as HISTORY_CHARACTER_COL,
                                      EVENT_COL as HISTORY_EVENT_COL,
                                      ICON_COL as HISTORY_ICON_COL,
                                      NAME_COL as HISTORY_NAME_COL,
                                      STACK_COL as HISTORY_STACK_COL,
                                      TIME_COL as HISTORY_TIME_COL,
                                      VALUE_COL as HISTORY_VALUE_COL,
                                      HistoryEntry, ItemHistoryModel)
from poe_view.ui.item_zoom import ItemZoomDialog
from poe_view.ui.paperdoll import PaperdollDialog
from poe_view.ui.settings_dialog import SettingsDialog
from poe_view.ui.rate_limit_dashboard import RateLimitDashboard
from poe_view.ui.raw_data_viewer import RawDataViewer
from poe_view.ui.stash_tree import StashTree
from poe_view.ui.theme import OTHER_TYPE, RARITY_COLORS, TYPE_FILTER_COLOR

log = logging.getLogger(__name__)


class _TypeFilterCheckBox(QCheckBox):
    """Checkbox für einen Item-Typ-Filter mit Zusatzgesten (Peter,
    2026-07-28): ein normaler Klick isoliert diesen Typ (alle anderen aus)
    — der weitaus häufigere Wunsch als "nur diesen einen abwählen". Wer
    gezielt einen weiteren Typ zur aktuellen Ansicht hinzufügen oder wieder
    herausnehmen will, hält dafür Strg — das ist das native
    Einzel-Umschalten von QCheckBox, hier nur nicht mehr der Normalfall.
    Strg+Umschalt+Klick sowie Doppelklick setzen wieder alle Typen an
    (zwei Wege zum selben Ziel, beide leicht zu finden). Ohne die eigene
    mouseDoubleClickEvent-Behandlung würde Qt einen Doppelklick als zwei
    normale Klicks werten — der Haken wäre danach unverändert (zweimal
    umgeschaltet) statt zurückgesetzt."""

    solo_requested = Signal()
    reset_requested = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.ControlModifier:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self.reset_requested.emit()
                    event.accept()
                    return
                super().mousePressEvent(event)  # normales Einzel-Umschalten
                return
            self.solo_requested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


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

    # Pause zwischen letztem Tastendruck im Suchfeld und dem tatsächlichen
    # Zeilen-Filter — siehe Kommentar bei self._search_debounce.
    SEARCH_DEBOUNCE_MS = 350

    # Ab dieser Item-Anzahl im Liga-Aggregat schaltet die Suche von "live"
    # auf "on demand" um (§_enter_search_all, FALLSTRICKE #40): das
    # komplette ungefilterte Aggregat als Qt-Modell aufzubauen kostet ab
    # hier spürbar (gemessen ~8s bei 200.000 Items) — Peter hat mit 19704
    # Items noch deutlich Luft darunter.
    LIVE_SEARCH_ITEM_LIMIT = 50_000

    # Refresh-Modi, die sich selbst im Takt weitertreiben
    # (§_drive_refresh_mode). "auto" läuft stattdessen am 40s-Timer,
    # "pause" gar nicht — für beide ist _drive_refresh_mode ein No-Op.
    STEPPING_REFRESH_MODES = ("single", "stash")

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PoE-VIEW2 v{__version__}")
        self.resize(1200, 700)
        # Liga/Typ-Filter/Suche sitzen seit 2026-08-01 in einer eigenen
        # zweiten Toolbar-Zeile (siehe _build_ui). Unter ~740px (real am
        # Fenster gemessen, siehe FALLSTRICKE #55) klappt genau diese
        # Zeile zusammen und versteckt das Suchfeld hinter "…". 800x600
        # (Peter, 2026-08-01: "pragmatisch auf die bekannte Größe") liegt
        # mit Puffer darüber — bewusst kein exaktes Mindestmaß, ein
        # gängiger Standard-Wert für Mindestfenstergrößen.
        self.setMinimumSize(800, 600)

        # Konto-Trennung (Peter, 2026-08-02: "Wenn ich den Account wechsle,
        # habe ich dann meine eigenen Daten?"): `_account_name` ist doppelt
        # belegt — Anzeigename UND Schlüssel, unter dem `_persist_cache`
        # sichert (`data_cache.path_for`). "" bedeutet "kein Konto aktiv",
        # sowohl direkt nach dem Start als auch nach einem Logout.
        self._account_name: str = ""
        self._stash_trees: dict[str, list[StashTab]] = {}      # Liga → Baumstruktur
        self._items: dict[str, dict[str, list[Item]]] = {}     # Liga → {stash_id: Items}
        self._last_loaded: dict[str, dict[str, str]] = {}      # Liga → {stash_id: ISO-Zeitstempel}
        self._leaf_stashes: list[StashTab] = []                # abgeflacht, nur aktuelle Liga
        self._all_characters: list[Character] = []             # ligenübergreifend, ungefiltert
        self._current_league: str = ""
        self._current_tab_name: str = ""
        self._bulk_dialog: QProgressDialog | None = None
        self._bulk_progress: BulkProgress | None = None  # letzter Tick, für den Sekunden-Countdown
        self._bulk_next_fetch_at = 0.0   # time.monotonic()-Zeitpunkt des nächsten Bulk-Abrufs
        # Rest der aktuellen Rate-Limit-Zwangspause, gespeist vom
        # Sekunden-Countdown des RateLimitManagers (§_on_rate_limit_changed).
        # 0 = keine Sperre aktiv.
        self._rate_limit_wait_until = 0.0
        self._showing_aggregate = False
        self._search_all_active = False        # Suchfeld → liga-weite Ansicht aktiv
        # Zwischengespeichertes, UNGEFILTERTES Aggregat für die "on demand"-
        # Suche (§_enter_search_all/_run_large_search) — None = normaler
        # Live-Modus. Nur gesetzt, solange eine Suche über ein Aggregat
        # oberhalb LIVE_SEARCH_ITEM_LIMIT aktiv ist.
        self._large_search_items: tuple[list[Item], list[str],
                                        list[int | None], list[str | None]] | None = None
        self._current_stash_id: str | None = None  # zuletzt gewähltes Fach (Rückkehrziel)
        # Mehrfachauswahl im Stash-Baum (Peter, 2026-08-02): Liste der
        # ausgewählten Blatt-Fach-IDs, solange diese Ansicht aktiv ist, sonst
        # None. BEWUSST getrennt von `_current_stash_id`/`_current_tab_name`
        # — die bleiben bei einer Mehrfachauswahl unverändert (zeigen weiter
        # auf das zuletzt EINZELN angeklickte Fach), damit die Refresh-Modi
        # "Single"/"Stash" und der Zonenwechsel-Trigger unbeeinflusst davon
        # weiterlaufen (ToDo.md). Siehe `_show_stash_selection`.
        self._current_stash_selection: list[str] | None = None
        self._character_items: dict[str, list[Item]] = {}       # Charaktername → Ausrüstung+Inventar
        self._character_items_loaded: dict[str, str] = {}       # Charaktername → ISO-Zeitstempel
        self._current_character_name: str | None = None         # gerade angezeigter Charakter
        # Doppelklick auf einen Char ohne Cache-Treffer: die Paperdoll öffnet
        # sich erst, sobald FetchCharacterItemsJob (vom vorangehenden
        # Einzelklick ausgelöst, siehe _on_character_selected) fertig ist.
        self._paperdoll_pending_char: str | None = None
        # Divination-Card-Artwork, das noch über FetchIconJob unterwegs ist
        # (URL, Ziel-ItemZoomDialog) — siehe _request_card_art/_on_icon.
        self._pending_card_art: tuple[str, ItemZoomDialog] | None = None
        self._worker_busy = False
        self._price_indexes: dict[str, PriceIndex] = {}  # Liga → PriceIndex (Cache-Hit oder Worker-Ergebnis)
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
        self._zone_watcher: ZoneWatcher | None = None
        # Charakter-Item-Verlauf (Peter, 2026-08-02): letzte 120 Items, die
        # neu im Inventar aufgetaucht oder daraus verschwunden sind — über
        # ALLE Charaktere hinweg, unabhängig davon, welcher gerade angezeigt
        # wird (appendleft: Zeile 0 = jüngstes Ereignis, siehe item_history.py).
        self._item_history: deque[HistoryEntry] = deque(maxlen=120)
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
        self._apply_zone_watcher_config(*self._load_zone_watcher_config())

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

    # Settings-Schlüssel: welches Konto war zuletzt aktiv (siehe
    # _restore_cached_data/_on_logged_in) — persistiert in ui-settings.ini,
    # NICHT im Daten-Cache selbst, weil er schon vor dem allerersten
    # Cache-Zugriff gebraucht wird (kalter Start kennt den Account-Namen
    # sonst erst nach dem asynchronen /profile-Aufruf, siehe unten).
    _ACCOUNT_SETTING_KEY = "account/last_active"

    def _restore_cached_data(self) -> None:
        """Lädt den letzten Daten-Cache (überlebt einen Neustart) — rein in-memory.

        Das Rendern übernimmt der normale Ablauf, sobald eine Liga aktiv
        wird (_on_league_changed → _activate_stash_tree), genau wie bei
        frisch von der API geladenen Daten.

        Konto-Trennung (Peter, 2026-08-02): welches Konto geladen wird,
        muss VOR dem Bootstrap/Login feststehen, sonst gäbe es beim Start
        keine Offline-Ansicht (die läuft komplett ohne Netzwerk, ein
        Warten auf den account-liefernden /profile-Aufruf würde sie
        kaputt machen). Die letzte bekannte Kontokennung kommt deshalb aus
        `ui-settings.ini`, nicht aus einem API-Aufruf.

        Fehlt der Hinweis (erster Start nach dieser Funktion, oder ganz
        neue Installation) ODER existiert die kontospezifische Datei noch
        NICHT (real beobachtet, Peter 2026-08-02: eine kurze erste Sitzung
        schrieb den Hinweis bereits über `_on_logged_in`, ohne dass
        `_persist_cache()` je gelaufen wäre — jeder weitere Start versuchte
        danach nur noch die fehlende Datei und gab auf, obwohl die alte,
        52 MB große `data-cache.json` unverändert daneben lag), fällt das
        auf den alten, kontounabhängigen Pfad zurück. Übernommen wird er
        aber NUR, wenn sein eigener gespeicherter `account_name` zum
        Hinweis passt (oder gar kein Hinweis existiert) — sonst würde ein
        ECHTER Kontowechsel, dessen neue Datei aus einer kurzen Sitzung
        noch fehlt, fälschlich wieder die Daten des VORHERIGEN Kontos
        zeigen. Migration ohne Kopier-/Löschcode: der nächste
        `_persist_cache()`-Aufruf schreibt bereits in die neue,
        kontospezifische Datei; die alte bleibt unverändert liegen.
        """
        hint = str(self._settings().value(self._ACCOUNT_SETTING_KEY, ""))
        cached = data_cache.load(data_cache.path_for(hint)) if hint else None
        if cached is None:
            legacy = data_cache.load()
            if legacy is not None and (not hint or legacy.account_name == hint):
                cached = legacy
        if cached is None:
            return
        self._account_name = hint or cached.account_name
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
        """Kein aktives Konto (frisch ausgeloggt) → nichts zu sichern, UND
        insbesondere keine leere Datei über einen bestehenden Kontostand
        schreiben (könnte sonst passieren, wenn ein noch laufender Job kurz
        nach einem Logout sein Ergebnis liefert, siehe _on_logout_clicked)."""
        if not self._account_name:
            return
        data = data_cache.CachedData()
        data.account_name = self._account_name
        data.characters = self._all_characters
        data.stash_trees = self._stash_trees
        data.items_by_league = self._items
        data.last_loaded = self._last_loaded
        data.character_items = self._character_items
        data.character_items_loaded = self._character_items_loaded
        data_cache.save(data, data_cache.path_for(self._account_name))

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
        # Liga/Typ-Filter/Suche in eine eigene zweite Zeile (Peter,
        # 2026-08-01: die erste Zeile wurde bei schmalerem Fenster am
        # rechten Rand abgeschnitten, Suche/Filter dadurch unsichtbar).
        # addToolBarBreak() erzwingt den Zeilenumbruch vor der nächsten
        # addToolBar()-Toolbar.
        self.addToolBarBreak()
        filter_toolbar = QToolBar()
        filter_toolbar.setMovable(False)
        self.addToolBar(filter_toolbar)

        # Ein QToolButton statt einer schlichten QAction (Peter, 2026-08-02:
        # "Wer sich mit einem ANDEREN GGG-Konto anmelden will, muss den
        # Eintrag ... von Hand löschen ... Sackgasse") — nach dem Login
        # bekommt derselbe Button ein Menü mit "Log out" statt einfach nur
        # deaktiviert zu werden. Ausgeloggt bleibt das Verhalten identisch
        # zur alten QAction: ein Klick startet direkt den Login (kein Menü
        # im Weg), da `_account_menu` erst in `_on_logged_in` angehängt
        # wird. `InstantPopup` sorgt dafür, dass ein Klick mit Menü das
        # Menü öffnet statt `clicked` auszulösen — ein einziger Button und
        # ein einziger Klick-Handler genügen für beide Zustände.
        self._login_button = QToolButton()
        self._login_button.setText("🔑 Log in")
        self._login_button.setAutoRaise(True)
        self._login_button.clicked.connect(lambda: self.worker.submit(LoginJob()))
        toolbar.addWidget(self._login_button)
        self._account_menu = QMenu(self._login_button)
        self._account_menu.addAction("🚪 Log out").triggered.connect(self._on_logout_clicked)

        self._refresh_action = QAction("⟳ Refresh", self)
        self._refresh_action.triggered.connect(self._refresh)
        toolbar.addAction(self._refresh_action)

        toolbar.addWidget(QLabel(" Mode: "))
        self._refresh_mode_combo = QComboBox()
        self._refresh_mode_combo.addItems(["Auto", "Single", "Stash", "Pause"])
        self._refresh_mode_combo.setToolTip(
            "Auto: keeps the open tab/character live, sweeps the rest of the "
            "stash in the background (default, reserves budget for manual clicks).\n"
            "Single: refreshes just the currently selected tab or character "
            "on a steady clock, as tight as the rate limit allows.\n"
            "Stash: cycles through the whole stash on that same steady clock, "
            "non-empty tabs first. For an immediate one-off pass, use "
            "\"Load All Tabs\" instead.\n"
            "Pause: no background requests at all — clicks and \"Load All "
            "Tabs\" still work and get the full rate limit budget.")
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

        self._settings_action = QAction("⚙ Settings", self)
        self._settings_action.setToolTip("Configure the item right-click menu")
        self._settings_action.triggered.connect(self._open_settings_dialog)
        toolbar.addAction(self._settings_action)

        filter_toolbar.addWidget(QLabel(" League: "))
        self._league_combo = QComboBox()
        self._league_combo.setMinimumWidth(160)
        self._league_combo.currentTextChanged.connect(self._on_league_changed)
        filter_toolbar.addWidget(self._league_combo)

        filter_toolbar.addWidget(QLabel("  Type: "))
        # 8 Checkboxen statt Namen (Namen wären zu lang) —
        # die Farbe des Käschchens IST das Label, Tooltip trägt den Namen.
        # Die letzte ("Sonstige", Pink) fängt alles ohne eigene Kategorie
        # auf: Quest, Prophecy, Relic, unbekannte frameTypes (§4.11).
        self._type_checks: dict[int, QCheckBox] = {}
        for type_key, name in self.TYPE_FILTER_ENTRIES:
            box = _TypeFilterCheckBox()
            box.setChecked(True)
            box.setToolTip(f"{name}\n"
                          f"click: show only this type\n"
                          f"Ctrl+click: add/remove this type\n"
                          f"Ctrl+Shift+click or double-click: show all types")
            colour = RARITY_COLORS.get(type_key, TYPE_FILTER_COLOR)
            box.setStyleSheet(
                f"QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 3px; "
                f"border: 2px solid {colour}; }} "
                f"QCheckBox::indicator:checked {{ background-color: {colour}; }}")
            box.toggled.connect(lambda checked, tk=type_key: self._on_type_toggled(tk, checked))
            box.solo_requested.connect(lambda tk=type_key: self._solo_type_filter(tk))
            box.reset_requested.connect(self._reset_type_filters)
            self._type_checks[type_key] = box
            filter_toolbar.addWidget(box)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        filter_toolbar.addWidget(spacer)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("🔍 Search all tabs of the league — * for everything")
        self._filter_edit.setFixedWidth(260)
        self._filter_edit.setClearButtonEnabled(True)  # eingebautes "x" zum Leeren
        filter_toolbar.addWidget(self._filter_edit)
        # Regex-Umschalter, standardmäßig AN: entspricht PoEs eigener
        # Truhensuche, sodass auf poe.re zusammengeklickte Muster
        # ("r-r-g|r-g-r|g-r-r", "-\w-.-") unverändert funktionieren. Wer
        # nur nach einem Namen sucht, merkt davon nichts — ein reiner Text
        # ist auch als Regex ein Teilstring-Treffer.
        self._regex_toggle = QCheckBox(".*")
        self._regex_toggle.setToolTip(
            "Regular expressions\n"
            "on: search text is a regex — poe.re socket patterns work here\n"
            "off: plain text search")
        self._regex_toggle.setChecked(self._load_regex_enabled())
        self._regex_search_enabled = self._regex_toggle.isChecked()
        self._regex_toggle.toggled.connect(self._on_regex_toggled)
        filter_toolbar.addWidget(self._regex_toggle)

        self._update_online_controls_enabled()

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
        self.character_list.character_paperdoll_requested.connect(
            self._on_character_paperdoll_requested)
        self.character_list.export_visible_requested.connect(self._export_csv)
        self.character_list.setMaximumHeight(220)

        stash_label = QLabel("Stash")
        stash_label.setStyleSheet("font-weight: 600; padding: 2px 4px;")
        self.tree = StashTree()
        self.tree.stash_selected.connect(self._on_stash_selected)
        self.tree.selection_changed.connect(self._show_stash_selection)
        self.tree.export_visible_requested.connect(self._export_csv)
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
        # Erst hier möglich: der Umschalter entsteht schon in der Toolbar
        # (oben), der Proxy aber erst jetzt.
        self.proxy.set_regex_enabled(self._regex_search_enabled)
        # Dämpfer für den eigentlichen Zeilen-Filter (SEARCH_DEBOUNCE_MS):
        # bei liga-weiten Aggregaten mit zehntausenden Items kostet
        # invalidateFilter() spürbar Zeit — bei jedem Tastendruck sofort
        # angewendet, ruckelte das merklich (Peter, 2026-07-28: "All Tabs
        # liefert mir 19704 Items"). Das Umschalten in/aus dem Aggregat
        # (_enter_search_all/_leave_search_all) bleibt dagegen sofort, da es
        # ohnehin nur EINMAL pro Such-Session läuft, nicht pro Tastendruck.
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(self.SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._apply_debounced_search_filter)
        self._filter_edit.textChanged.connect(self._on_filter_text_changed)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        # Voreinstellung statt roher API-Reihenfolge: aufsteigend nach Wert,
        # damit unbekannte/geringe Preise ("wahrscheinlich Schrott", siehe
        # VALUE_COL-Abblendung) von selbst oben gruppiert sind (ToDo.md:
        # "Schrott-Items finden"). Nur der Startzustand — ein Klick auf
        # einen anderen Header überschreibt ihn wie jede normale
        # Sortierung, Qt merkt sich das eigenständig.
        self.table.sortByColumn(VALUE_COL, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(POSITION_COL, 100)
        for name in ("Req.Lvl", "Str", "Dex", "Int"):  # schmale Zahlenspalten
            self.table.setColumnWidth(COLUMNS.index(name), 58)
        self.table.setColumnWidth(MODS_COL, 320)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        # Rechtsklick auf eine Zeile: die selbst konfigurierten
        # Nachschlagewerke zum markierten Item (§external_tools.py).
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_row_menu)
        # Doppelklick auf eine Zeile: vergrößerte Item-Ansicht (ToDo.md:
        # "Doppelklick auf ein Item 'beleuchtet' dies", Peter 2026-07-31).
        self.table.doubleClicked.connect(self._on_table_row_double_clicked)
        # Spalten per Rechtsklick auf den Header an-/abwählbar;
        # die Wahl überlebt den Neustart (ui-settings.ini im APP_DATA_DIR).
        table_header = self.table.horizontalHeader()
        table_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table_header.customContextMenuRequested.connect(self._on_table_header_menu)
        self._apply_column_config(self._load_column_config())

        # Charakter-Item-Verlauf (Peter, 2026-08-02): eigenes, schlankes
        # Spaltenformat statt der Item-Tabelle (§item_history.py) — deshalb
        # eigener Header, anders als ursprünglich angedacht ("Header ist
        # der gleiche wie oben, deshalb nicht angezeigt" galt nur für die
        # zunächst erwogene Wiederverwendung des Item-Tabellen-Formats).
        self.history_model = ItemHistoryModel(
            icon_requester=lambda url: self.worker.submit(FetchIconJob(url)))
        self.history_table = QTableView()
        self.history_table.setModel(self.history_model)
        self.history_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.history_table.verticalHeader().hide()
        # Spaltenbreiten wie bei der Item-Tabelle von Hand: die Qt-Vorgabe
        # (überall 100px) verschenkt Platz an Icon/Event und schneidet
        # dafür lange Item-Namen ab ("Awakened Deadly Ailments Support").
        for col, width in ((HISTORY_ICON_COL, 36), (HISTORY_TIME_COL, 70),
                           (HISTORY_CHARACTER_COL, 130), (HISTORY_EVENT_COL, 50),
                           (HISTORY_NAME_COL, 220), (HISTORY_BASE_COL, 160),
                           (HISTORY_STACK_COL, 60), (HISTORY_VALUE_COL, 90)):
            self.history_table.setColumnWidth(col, width)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self._on_history_row_menu)
        self.history_table.doubleClicked.connect(self._on_history_row_double_clicked)

        self.detail = ItemDetail()
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        # Vertikaler Splitter statt fixer Höhe: standardmäßig auf eine
        # Zeile kollabiert (nur das jüngste Verlaufs-Ereignis sichtbar),
        # per Ziehen am Griff beliebig aufziehbar (Peter: "kann aufgezogen
        # werden") — QSplitter bringt das ohne eigene Resize-Logik mit.
        table_splitter = QSplitter(Qt.Orientation.Vertical)
        table_splitter.addWidget(self.table)
        table_splitter.addWidget(self.history_table)
        table_splitter.setStretchFactor(0, 1)
        table_splitter.setStretchFactor(1, 0)
        one_row_height = (self.history_table.horizontalHeader().sizeHint().height()
                          + self.history_table.verticalHeader().defaultSectionSize()
                          + 2 * self.history_table.frameWidth())
        table_splitter.setSizes([1000, one_row_height])
        right_layout.addWidget(table_splitter, stretch=1)
        right_layout.addWidget(self.detail)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        # 340px, nicht mehr 260: die Pos.-Spalte (§_tab_positions) kam später
        # dazu und braucht neben Name/#/Status zusätzlichen Platz, sonst
        # schneidet der Baum ohne manuelles Nachziehen etwas ab (Peter,
        # 2026-07-28). Fensterbreite um denselben Betrag erhöht, damit die
        # Item-Tabelle rechts nicht kleiner wird als vorher.
        splitter.setSizes([340, 840])

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
        # Summe der Stack-Größen über die gerade sichtbaren (gefilterten)
        # Items — die häufigste Alltagsfrage ("wie viel Chaos hab ich"),
        # bisher musste man die Stack-Spalte selbst zusammenzählen oder nach
        # CSV exportieren (Peter, 2026-07-28).
        #
        # NUR an modelReset gehängt (ein einziges Signal pro set_items()-
        # Aufruf, unabhängig von der Zeilenzahl) — NICHT an layoutChanged/
        # rowsInserted/rowsRemoved (FALLSTRICKE #39, zweiter Teil): sobald
        # eine QTableView am Proxy hängt, feuert QSortFilterProxyModel bei
        # einer Textsuche über ein liga-weites Aggregat pro ZUSAMMENHÄNGENDEM
        # Block verborgener/wieder sichtbarer Zeilen ein eigenes rowsRemoved/
        # rowsInserted — bei über die ganze Liste verstreuten Treffern
        # (z. B. "Currency 7" bei 19704 Items) waren das ~395 Aufrufe. Jeder
        # rief _update_stack_sum() mit einer erneuten O(sichtbare Zeilen)-
        # Schleife auf — zusammen O(n²), gemessen 9,5 SEKUNDEN für einen
        # einzigen Tastendruck. Stattdessen wird _update_summaries() (ruft
        # _update_stack_sum() + _update_value_sum()) jetzt an jeder Stelle,
        # die den Filter ändert, GENAU EINMAL explizit aufgerufen
        # (_apply_debounced_search_filter, _on_type_toggled,
        # _apply_column_filter, _clear_column_filters).
        self._stack_sum_label = QLabel("")
        self.statusBar().addPermanentWidget(self._stack_sum_label)
        # Gesamtwert der sichtbaren Items (poe.ninja, §ARCHITEKTUR.md §4.14)
        # — dieselbe Update-Disziplin wie die Stack-Summe: nur explizite
        # Aufrufe, nie an rowsInserted/rowsRemoved (FALLSTRICKE #39).
        self._value_sum_label = QLabel("")
        self.statusBar().addPermanentWidget(self._value_sum_label)
        self.proxy.modelReset.connect(self._update_summaries)
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
        self._update_summaries()

    def _solo_type_filter(self, type_key: int) -> None:
        """Normaler Klick auf ein Typ-Symbol: nur diesen Typ zeigen, alle
        anderen aus — der weitaus häufigere Fall als "nur diesen einen
        abwählen", das native Einzel-Umschalten bleibt über Strg+Klick
        erreichbar."""
        for tk, box in self._type_checks.items():
            box.setChecked(tk == type_key)

    def _reset_type_filters(self) -> None:
        """Strg+Umschalt+Klick oder Doppelklick auf ein Typ-Symbol: wieder
        alle Typen zeigen."""
        for box in self._type_checks.values():
            box.setChecked(True)

    def _update_stack_sum(self, *_args) -> None:
        """Summe der Stack-Größe über die aktuell sichtbaren (gefilterten)
        Zeilen — nur Items MIT Stack-Größe zählen mit; ein Item ohne
        Stack-Angabe (Ausrüstung) ist kein "Stack von 1".

        Zeigt die Summe NUR, wenn alle stapelbaren Treffer denselben Namen
        tragen — bei "*" oder einer ungefilterten Truhe mit mehreren
        Currency-Sorten wäre eine Summe über verschiedene Item-Typen hinweg
        (Chaos + Portal Scrolls + …) bedeutungslos (Peter, 2026-07-28: "*"
        ergab "Stack total: 604.911" quer über die ganze Liga). Verborgen
        auch, wenn gar nichts Stapelbares sichtbar ist, statt immer
        "Stack total: 0" zu zeigen.

        Signatur akzeptiert beliebige Args, weil sie direkt an mehrere
        unterschiedliche Proxy-Signale gehängt ist (modelReset,
        layoutChanged, rowsInserted/-Removed mit je eigenen Parametern)."""
        total = 0
        names: set[str] = set()
        for row in range(self.proxy.rowCount()):
            source_row = self.proxy.mapToSource(self.proxy.index(row, 0)).row()
            item = self.table_model.item_at(source_row)
            if item is not None and item.stackSize:
                total += item.stackSize
                names.add(item.display_name)
        self._stack_sum_label.setText(f"Stack total: {total:,}" if len(names) == 1 else "")

    def _update_summaries(self, *_args) -> None:
        """Einziger Anschlusspunkt für beide Statuszeilen-Summen (Stack,
        Wert) — siehe FALLSTRICKE #39: nur an modelReset hängen bzw. GENAU
        EINMAL explizit nach jeder Filteränderung aufrufen, nie an
        rowsInserted/rowsRemoved/layoutChanged."""
        self._update_stack_sum()
        self._update_value_sum()

    def _update_value_sum(self) -> None:
        """Gesamt-Chaos-Wert der aktuell sichtbaren (gefilterten) Zeilen,
        soweit poe.ninja dafür einen Preis kennt — anders als die Stack-
        Summe unabhängig vom Item-Namen sinnvoll (verschiedene Item-Typen
        lassen sich in Chaos aufaddieren, anders als in Stack-Größe).
        Bleibt leer, solange kein Preis-Index für die aktuelle Liga
        vorliegt oder kein sichtbares Item einen Preis hat."""
        total = 0.0
        known = False
        for row in range(self.proxy.rowCount()):
            source_row = self.proxy.mapToSource(self.proxy.index(row, 0)).row()
            value = self.table_model.value_at(source_row)
            if value is not None:
                total += value
                known = True
        if not known:
            self._value_sum_label.setText("")
            return
        index = self._price_indexes.get(self._current_league)
        self._value_sum_label.setText(f"Value: {format_chaos_value(total, index)}")

    # --- Spalten-Sichtbarkeit + Reihenfolge der Item-Tabelle --------- #

    # "Type" ist standardmäßig aus: die Rarity steckt bereits in der
    # Namensfarbe. Die Tab-Spalte wird automatisch verwaltet (aus bei
    # Einzelfach, an bei Aggregat) und ist deshalb nicht konfigurierbar
    # (CONFIGURABLE_COLUMNS, siehe item_table.py).
    DEFAULT_HIDDEN_COLUMNS = frozenset({"Type"})

    def _settings(self) -> QSettings:
        """INI-Datei statt Registry, konsistent zum Datei-Cache-Ansatz."""
        return QSettings(str(config.APP_DATA_DIR / "ui-settings.ini"),
                         QSettings.Format.IniFormat)

    def _default_column_config(self) -> list[tuple[str, bool]]:
        return [(name, name not in self.DEFAULT_HIDDEN_COLUMNS) for name in CONFIGURABLE_COLUMNS]

    def _load_column_config(self) -> list[tuple[str, bool]]:
        """Reihenfolge + Sichtbarkeit als JSON-Liste (Peter, 2026-08-01:
        Settings-Dialog mit Drag&Drop-Reihenfolge statt nur einer reinen
        Sichtbarkeits-Menge). Fehlt eine konfigurierbare Spalte im
        gespeicherten Stand (z. B. weil sie erst später hinzukam), wird sie
        sichtbar ans Ende angehängt statt stillschweigend zu verschwinden."""
        stored = self._settings().value("item_table/column_config")
        if stored:
            try:
                raw = json.loads(str(stored))
                order = [(str(d["name"]), bool(d["visible"])) for d in raw
                        if str(d.get("name", "")) in CONFIGURABLE_COLUMNS]
            except (ValueError, TypeError, KeyError):
                order = []
            if order:
                seen = {name for name, _ in order}
                order += [(name, True) for name in CONFIGURABLE_COLUMNS if name not in seen]
                return order
        # Migration von der alten reinen Sichtbarkeits-Einstellung (keine
        # Reihenfolge) — sonst Standardreihenfolge, alles sichtbar außer "Type".
        legacy = self._settings().value("item_table/hidden_columns")
        if legacy is not None:
            hidden = {name for name in str(legacy).split(";") if name}
            return [(name, name not in hidden) for name in CONFIGURABLE_COLUMNS]
        return self._default_column_config()

    def _save_column_config(self, column_config: list[tuple[str, bool]]) -> None:
        payload = json.dumps([{"name": name, "visible": visible} for name, visible in column_config])
        self._settings().setValue("item_table/column_config", payload)

    def _apply_column_config(self, column_config: list[tuple[str, bool]]) -> None:
        """Setzt Sichtbarkeit UND visuelle Reihenfolge. Die Tab-Spalte
        bleibt fix an erster Stelle (sie ist nicht Teil von
        ``column_config``, ihre Sichtbarkeit steuert allein die
        Einzelfach-/Aggregat-Logik andernorts)."""
        header = self.table.horizontalHeader()
        header.moveSection(header.visualIndex(TAB_COL), 0)
        target_visual = 1
        for name, visible in column_config:
            col = COLUMNS.index(name)
            self.table.setColumnHidden(col, not visible)
            header.moveSection(header.visualIndex(col), target_visual)
            target_visual += 1

    def _toggle_column(self, name: str) -> None:
        """Vom Header-Rechtsklickmenü genutzt: Sichtbarkeit EINER Spalte
        umschalten, Reihenfolge bleibt unangetastet."""
        column_config = [(n, (not visible) if n == name else visible)
                         for n, visible in self._load_column_config()]
        self._apply_column_config(column_config)
        self._save_column_config(column_config)

    def _load_regex_enabled(self) -> bool:
        """Default AN — entspricht PoEs eigener Truhensuche (§4.11)."""
        stored = self._settings().value("item_table/regex_search")
        if stored is None:
            return True
        return str(stored).lower() in ("true", "1")

    def _on_regex_toggled(self, enabled: bool) -> None:
        self._regex_search_enabled = enabled
        self._settings().setValue("item_table/regex_search", enabled)
        self.proxy.set_regex_enabled(enabled)
        # Laufende Suche sofort mit dem neuen Modus neu auswerten, statt
        # bis zum nächsten Tastendruck den alten Treffer-Stand zu zeigen.
        if self._filter_edit.text():
            self._apply_debounced_search_filter()
        else:
            self._update_summaries()

    def _build_column_filter_edit(self, col: int) -> QLineEdit:
        """Eingabefeld für den Spalten-Filter im Header-Rechtsklick-Menü,
        inklusive Autovervollständigen über die tatsächlich in dieser
        Spalte vorkommenden Werte (Peter, 2026-08-02: "eine Art
        Autovervollständigen mit Combobox über die Items in der Spalte").
        Eigene Methode statt inline in ``_on_table_header_menu``, damit sie
        ohne den blockierenden ``QMenu.exec()`` testbar ist."""
        edit = QLineEdit(self.proxy.column_filter(col))
        edit.setPlaceholderText("e.g. >=20, <45, =text, substring")
        values = self.table_model.distinct_values(col)
        if values:
            completer = QCompleter(values, edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            # Contains statt StartsWith: passt zum Filter selbst, der auch
            # ohne Operator eine reine Teilstring-Suche ist (_expression_matches).
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            edit.setCompleter(completer)
        return edit

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
            edit = self._build_column_filter_edit(clicked_col)
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
        visible_names = {name for name, visible in self._load_column_config() if visible}
        for i, name in enumerate(COLUMNS):
            if i == TAB_COL:
                continue
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name in visible_names)
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
        self._update_summaries()

    def _clear_column_filters(self) -> None:
        self.proxy.clear_column_filters()
        self._status_msg.setText(
            f"All column filters cleared — {self.table_model.rowCount()} items")
        self._update_summaries()

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
        w.rate_limit_changed.connect(self._on_rate_limit_changed)
        w.status.connect(self._on_status)
        w.busy_changed.connect(self._on_busy_changed)
        w.job_error.connect(self._on_error)
        w.bulk_progress.connect(self._on_bulk_progress)
        w.bulk_finished.connect(self._on_bulk_finished)
        w.offline_changed.connect(self._on_offline_changed)
        w.prices_loaded.connect(self._on_prices_loaded)

    # --- Worker-Slots (Main-Thread) ------------------------------------ #

    def _on_rate_limit_changed(self, policy: str, rules: list[dict],
                               wait_s: float) -> None:
        """Dashboard aktualisieren und die Rest-Sperre merken.

        Der ``RateLimitManager`` meldet während einer Zwangspause im
        Sekundentakt die Restzeit (§rate_limiter._countdown). Das ist die
        EINZIGE Quelle dafür: die selbst auferlegte Pause (Fenster voll,
        kein HTTP 429) steckt in keinem Header und taucht deshalb auch in
        ``snapshot()`` nicht auf. Der Bulk-Dialog zeigt sie damit an, statt
        minutenlang scheinbar zu hängen."""
        self.dashboard.update_state(policy, rules, wait_s)
        self._rate_limit_wait_until = (time.monotonic() + wait_s) if wait_s > 0 else 0.0

    def _on_logged_in(self, account_name: str) -> None:
        """``account_name`` kommt aus einem frischen ``/profile``-Aufruf
        (§ApiWorker._after_auth) — sowohl nach einem interaktiven Login als
        auch nach einem kalten Start mit noch gültigem gespeichertem Token.

        Weicht es vom Konto ab, dessen Daten gerade im Speicher stehen
        (``self._account_name``, gesetzt von ``_restore_cached_data`` beim
        kalten Start oder einem vorherigen Login in dieser Session), ist
        das ein Kontowechsel: der spekulativ geladene oder noch übrige
        Stand des ALTEN Kontos wird verworfen, nicht vermischt (Peter,
        2026-08-02: "Wenn ich den Account wechsle, habe ich dann meine
        eigenen Daten?"). Der Normalfall — dieselbe Person startet neu
        oder loggt sich erneut mit demselben Konto ein — durchläuft diesen
        Zweig gar nicht (`self._account_name` stimmt schon überein)."""
        if self._account_name and account_name != self._account_name:
            self._switch_active_account_data(account_name)
        self._account_name = account_name
        self._settings().setValue(self._ACCOUNT_SETTING_KEY, account_name)
        self._logged_in = True
        self._login_button.setText(f"⚷ {account_name}")
        self._login_button.setMenu(self._account_menu)
        self._login_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._update_online_controls_enabled()
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

        Ändert BEWUSST NICHTS an ``self._account_name`` oder den geladenen
        Fach-/Item-/Charakterdaten — ein unfreiwilliger Token-Ablauf soll
        die gerade sichtbare (Cache-)Ansicht nicht wegreißen. Ein echter
        Kontowechsel läuft stattdessen über ``_on_logout_clicked`` (bewusst
        vom Nutzer ausgelöst) oder wird in ``_on_logged_in`` erkannt."""
        self._logged_in = False
        self._login_button.setText("🔑 Log in")
        self._login_button.setMenu(None)
        self._login_button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        self._status_msg.setText(reason)
        self._update_online_controls_enabled()

    def _on_logout_clicked(self) -> None:
        """Nutzer wählt "Log out" im Konto-Menü (Peter, 2026-08-02, zum
        fehlenden Logout: "Für ein öffentliches Werkzeug eine Sackgasse").

        Anders als ein unfreiwilliger Token-Ablauf (``_on_login_required``,
        der die sichtbare Ansicht bewusst NICHT anfasst) ist das ein
        gewollter Session-Schnitt: die im Speicher gehaltenen Fach-/Item-/
        Charakterdaten dieses Kontos werden geleert, NICHT von der Platte
        gelöscht (Peters Entscheidung: "zu gefährlich, das kann der Nutzer
        über den Explorer erledigen") — nach einem Login mit einem ANDEREN
        Konto bleibt dadurch nichts vom alten sichtbar oder vermischt sich
        damit. Das eigentliche Token-Löschen + der UI-Rücksprung auf
        "🔑 Log in" laufen über den Worker (``LogoutJob`` → ``login_
        required``-Signal → ``_on_login_required``), exakt wie bei jedem
        anderen Abmelde-Grund."""
        self.worker.submit(LogoutJob())
        self._reset_session_data()
        self._account_name = ""
        self._rebuild_league_combo(None)

    def _reset_session_data(self) -> None:
        """Leert alle konto-/liga-gebundenen Daten im Speicher UND die
        sichtbaren Widgets — geteilt von ``_on_logout_clicked`` und
        ``_switch_active_account_data``. Absichtlich NICHT betroffen:
        ``_price_indexes`` (poe.ninja-Preise gelten pro Liga, nicht pro
        Konto, ein Neuabruf nur wegen des Kontowechsels wäre verschwendet)
        und ``_offline``/``_live_leagues`` (Spielzustand, kein Konto-Bezug).
        """
        self._all_characters = []
        self._stash_trees = {}
        self._items = {}
        self._last_loaded = {}
        self._character_items = {}
        self._character_items_loaded = {}
        self._leaf_stashes = []
        self._current_league = ""
        self._current_tab_name = ""
        self._current_stash_id = None
        self._current_character_name = None
        self._current_stash_selection = None
        self._showing_aggregate = False
        self._search_all_active = False
        self._large_search_items = None
        self._item_history.clear()
        self._filter_edit.clear()
        self.tree.set_stashes([])
        self.character_list.set_characters([])
        self.table_model.set_items([])
        self.history_model.set_entries([])

    def _switch_active_account_data(self, account_name: str) -> None:
        """Von ``_on_logged_in`` gerufen, wenn das gerade bestätigte Konto
        NICHT dem entspricht, dessen Daten im Speicher stehen (siehe dort).
        Leert zunächst alles (``_reset_session_data``), lädt danach den
        eigenen Cache-Stand des neuen Kontos (falls vorhanden — ein noch
        nie auf diesem Rechner genutztes Konto startet einfach leer, wird
        aber nicht mit dem alten vermischt)."""
        self._reset_session_data()
        cached = data_cache.load(data_cache.path_for(account_name))
        if cached is not None:
            self._all_characters = cached.characters
            self._stash_trees = {league: self._nest_folder_members(tree)
                                 for league, tree in cached.stash_trees.items()}
            self._items = cached.items_by_league
            self._last_loaded = cached.last_loaded
            self._character_items = cached.character_items
            self._character_items_loaded = cached.character_items_loaded
        self._rebuild_league_combo(None)

    def _update_online_controls_enabled(self) -> None:
        """Sperrt Online-Funktionen, solange kein gültiger Login besteht.

        Ohne dieses Gate blieb z. B. "Load All Tabs" bei abgelaufenem oder
        fehlendem Token anklickbar, solange noch ein Daten-Cache aus einer
        früheren Sitzung vorlag (der auch ohne Login sichtbar bleibt, siehe
        ``_restore_cached_data``): der Fortschrittsdialog öffnete sich, der
        zugehörige Job wurde vom Worker aber lautlos verworfen
        (``ApiWorker._skip_unauthenticated``) — der Dialog blieb dadurch für
        immer bei 0 % hängen, ohne jede Fehlermeldung.

        Bewusst NICHT betroffen: Stash-Baum, Charakterliste und
        Liga-Auswahl bleiben nutzbar, damit gecachte Daten weiter offline
        durchsuchbar sind — genau der Zweck des Caches."""
        self._refresh_action.setEnabled(self._logged_in)
        self._load_all_action.setEnabled(self._logged_in)
        self._refresh_mode_combo.setEnabled(self._logged_in)

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
        self._current_stash_selection = None
        # Itemliste gehoerte zur vorigen Liga (Fach/Charakter dort ausgewaehlt) —
        # ohne dieses Leeren blieb sie nach einem Liga-Wechsel sichtbar stehen,
        # obwohl keine Auswahl mehr dazu passt (Peter, 2026-08-03).
        self.table_model.set_items([])
        self.history_model.set_entries([])
        self._status_msg.setText(f"{league}: select a tab or character to view items")
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
        elif self.worker.rate_limiter.pacing_blocked("stash-list-request-limit"):
            # Fenster für Fach-LISTEN-Abrufe schon zu voll (z. B. mehrere
            # schnelle Liga-Wechsel hintereinander) — der gecachte Baum
            # steht bereits, der nächste Auto-Sweep oder ein manueller
            # Refresh holt die Bestätigung nach (FALLSTRICKE #47/#48).
            self._ensure_prices_loaded(league)
        else:
            # … und trotzdem im Hintergrund bestätigen/aktualisieren (wie bisher).
            self.worker.submit(FetchStashListJob(league))
            self._ensure_prices_loaded(league)
        # ERST NACH _ensure_prices_loaded: bei einem Cache-Treffer landet der
        # Preis-Index synchron in self._price_indexes (siehe dort) — davor
        # aufgerufen würde stets None sehen, auch wenn der Cache-Treffer
        # direkt danach eintrifft.
        self.table_model.set_price_index(self._price_indexes.get(league))
        self.history_model.set_price_index(self._price_indexes.get(league))
        # Stash-Modus soll sofort auf die neue Liga umsteigen statt den
        # Rest-Takt der vorherigen Liga abzuwarten. NICHT zurückgesetzt:
        # _refresh_mode_policy — die Policy eines Fach-Abrufs
        # ("stash-request-limit") ist liga-unabhängig, ein Reset hier
        # würde `pacing_blocked`/`steady_pace_interval_s` bis zum ersten
        # Job der neuen Liga auf den globalen, kontaminierbaren
        # `_last_policy`-Fallback zurückwerfen — exakt die Lücke, die
        # FALLSTRICKE #33 schon einmal geschlossen hat (FALLSTRICKE #48).
        self._refresh_mode_pending = False
        self._refresh_mode_next_due = 0.0
        self._stash_mode_round_picks = 0
        self._stash_mode_coverage_cursor = 0
        self._stash_mode_list_refresh_due = False
        self._refresh_mode_priority_id = None  # Fach-IDs gelten nur innerhalb einer Liga

    def _ensure_prices_loaded(self, league: str) -> None:
        """Preise für eine Liga bereitstellen: Disk-Cache zuerst (kein
        Netzwerk, sofort verfügbar), sonst Nachladen im Hintergrund über
        den Worker — unabhängig vom GGG-Login/Online-Status, poe.ninja ist
        ein eigener, unauthentifizierter Dienst."""
        if league in self._price_indexes:
            return
        cached = price_cache.load(league)
        if cached is not None:
            self._price_indexes[league] = cached
            return
        self.worker.submit(FetchPricesJob(league))

    def _on_prices_loaded(self, league: str, index: PriceIndex) -> None:
        self._price_indexes[league] = index
        price_cache.save(league, index)
        if league == self._current_league:
            # Preise treffen meist NACH den Items ein (Hintergrund-Abruf,
            # §_ensure_prices_loaded) — Value-Spalte/-Summe füllen sich
            # dadurch nachträglich, ohne dass der Nutzer neu klicken muss.
            self.table_model.set_price_index(index)
            self.history_model.set_price_index(index)
            self._update_value_sum()
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

    def _clear_view_relative_column_filters(self) -> None:
        """Tab- und Position-Spalte sind relativ zur gerade angezeigten
        Ansicht (Charakter-Slot- vs. Truhenfach-Namen, Fach-Position vs.
        gar keine Position) — ein Filter darauf verliert beim Wechsel zu
        einer anderen Ansicht seinen Sinn und kann dort ALLE Items
        unsichtbar machen, ohne dass der Grund erkennbar ist, wenn die
        Spalte in der neuen Ansicht sogar automatisch ausgeblendet ist
        (Peter, 2026-08-02: "Tab->MainInventory gibt es im Stash nicht und
        es werden deshalb keine Items angezeigt"). Aufgerufen an jeder
        Stelle, die auf eine tatsächlich ANDERE Quelle umschaltet (Baum-
        Klick, Charakter-Klick, Aggregat/Suche betreten) — NICHT bei einem
        stillen Refresh derselben Ansicht, dort soll ein aktiver Filter auf
        anderen Spalten (Name, Value, …) bestehen bleiben."""
        if self.proxy.filtered_columns() & {TAB_COL, POSITION_COL}:
            self.proxy.set_column_filter(TAB_COL, "")
            self.proxy.set_column_filter(POSITION_COL, "")

    def _on_stash_selected(self, stash_id: str, name: str) -> None:
        self._clear_view_relative_column_filters()
        self._showing_aggregate = False
        self._search_all_active = False  # Baum-Klick beendet die liga-weite Suchansicht
        self._large_search_items = None
        self._current_stash_selection = None  # Einzelauswahl beendet eine evtl. Mehrfachauswahl
        self._clear_search_field_on_selection()
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
        self._clear_view_relative_column_filters()
        self._showing_aggregate = False
        self._current_stash_selection = None  # Refresh eines Einzelfachs beendet eine Mehrfachauswahl
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
                self._carry_over_stamps(tab.children, children)
                self._restamp_from_cached_items(league, children)
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

    @staticmethod
    def _carry_over_stamps(old: list[StashTab], new: list[StashTab]) -> None:
        """Selbst vergebene Metadaten (Präfix ``poeview_``) von den alten auf
        die frisch abgerufenen Unter-Tabs übertragen, zugeordnet über die ID.

        Ein erneuter Abruf des Eltern-Fachs liefert die Kinder komplett neu —
        und Unique-Stash-Kinder sind in der API namenlos. Ohne diese
        Übernahme fällt jedes bereits getaufte Fach (§_stamp_category) auf
        "UniqueStash" zurück, sobald das Eltern-Fach nochmal geladen wird:
        real beobachtet nach einem "Load All Tabs"-Lauf, der Spezial-Tabs
        immer neu abruft — von 20 benannten Fächern blieb nur das eine
        übrig, dessen Items NACH dem Eltern-Abruf durchkamen. Der Verlust
        wanderte über ``_persist_cache`` auch gleich in den Datei-Cache.

        Nur ``poeview_``-Schlüssel wandern mit: alles andere kommt von GGG
        und muss die frische Antwort gewinnen lassen (eine im Spiel geleerte
        Item-Anzahl darf nicht am alten Stand kleben bleiben).
        """
        stamps = {tab.id: {k: v for k, v in tab.metadata.items()
                           if k.startswith("poeview_")}
                  for tab in old}
        for tab in new:
            tab.metadata.update(stamps.get(tab.id) or {})

    def _restamp_from_cached_items(self, league: str, children: list[StashTab]) -> None:
        """Namenlose Unter-Tabs, deren Items schon im Cache liegen, sofort
        (neu) taufen — ohne dafür einen Request auszulösen.

        Zweck ist die Reparatur bereits verlorener Namen: Cache-Dateien, in
        denen die Kategorie-Stempel vor dem Fix (§_carry_over_stamps)
        überschrieben wurden, heilen so beim nächsten Abruf des Eltern-Fachs
        von selbst, statt zu warten, bis jedes einzelne Unter-Fach wieder
        an der Reihe ist. Dieselbe Regel wie ``_stamp_category``: nur echte
        Namenlose, und nur wenn sich aus den Items überhaupt eine dominante
        Kategorie ergibt."""
        cached = self._items.get(league, {})
        for tab in children:
            if ((tab.name.strip() and not is_ggg_suffix(tab.name))
                    or tab.metadata.get("map")
                    or tab.metadata.get("poeview_category")):
                continue
            category = dominant_category(cached.get(tab.id) or [])
            if category:
                tab.metadata["poeview_category"] = category

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
        if (tab.name.strip() and not is_ggg_suffix(tab.name)) or tab.metadata.get("map"):
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
        self._current_stash_selection = None
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
        self._current_stash_selection = None
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

    def _show_stash_selection(self, stash_ids: list[str]) -> None:
        """Mehrfachauswahl im Stash-Baum (Peter, 2026-08-02: "Wenn ich im
        Stash-Tree ein oder mehrere Stashs bzw. Überordner auswähle, soll
        die Itemliste dies wiederspiegeln und nur Items aus diesen
        Ordnern/Tabs anzeigen"), verdrahtet an ``StashTree.selection_
        changed``. ``stash_ids`` sind bereits rekursiv aufgelöste
        Blatt-Fach-IDs — Ordner/Gruppen sind für diese Methode nicht mehr
        sichtbar.

        NUR aus dem Cache — eine Mehrfachauswahl darf NIE selbst einen
        API-Abruf auslösen: ein Shift-Klick über 20 nie geladene Fächer
        würde sonst 20 Requests auf einmal abfeuern und das Rate-Limit
        sprengen. Nicht gecachte Fächer werden in der Statuszeile benannt,
        nicht automatisch nachgeladen — Laden bleibt eine ausdrückliche
        Handlung (⟳ oder "Load All Tabs").

        ``_current_stash_id``/``_current_character_name``/
        ``_current_tab_name`` bleiben ABSICHTLICH unverändert: sie zeigen
        weiter auf das zuletzt EINZELN angeklickte Fach bzw. den zuletzt
        angeklickten Charakter, damit die Refresh-Modi "Single"/"Stash",
        der Zonenwechsel-Trigger und "Auto" unbeeinflusst von einer
        Mehrfachauswahl weiterlaufen (ToDo.md-Entscheidung — "eine
        Mehrfachauswahl ändert daran nichts"). ``_current_stash_selection``
        trägt stattdessen die WAS-WIRD-GERADE-ANGEZEIGT-Information für
        ``_leave_search_all`` (Rückkehr nach dem Verlassen einer globalen
        Suche) und ``_default_export_filename`` (CSV-Dateiname)."""
        self._clear_view_relative_column_filters()
        self._showing_aggregate = True  # blockiert stille Einzelfach-Overwrites (§_on_stash_items)
        self._search_all_active = False
        self._large_search_items = None
        self._current_stash_selection = stash_ids
        self._clear_search_field_on_selection()
        league_items = self._items.get(self._current_league, {})
        positions = self._tab_positions()
        tree = self._stash_trees.get(self._current_league, [])
        items: list[Item] = []
        sources: list[str] = []
        tab_indices: list[int | None] = []
        result_stash_ids: list[str | None] = []
        loaded = 0
        for stash_id in stash_ids:
            cached = league_items.get(stash_id)
            if cached is None:
                continue
            loaded += 1
            stash = self._find_stash(tree, stash_id)
            name = stash.display_name if stash is not None else stash_id
            items.extend(cached)
            sources.extend([name] * len(cached))
            tab_indices.extend([positions.get(stash_id)] * len(cached))
            result_stash_ids.extend([stash_id] * len(cached))
        self.table.setColumnHidden(TAB_COL, False)  # mehrere Fächer: Herkunft zeigen
        self.table_model.set_items(items, sources, tab_indices, result_stash_ids,
                                   request_icons=False)  # lazy
        tabs_word = "tab" if len(stash_ids) == 1 else "tabs"
        status = f"{len(stash_ids)} {tabs_word} selected: {loaded} loaded"
        not_loaded = len(stash_ids) - loaded
        if not_loaded:
            status += f", {not_loaded} never loaded (select ⟳ or Load All Tabs to fetch)"
        status += f" — {len(items)} items"
        self._status_msg.setText(status)

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

        # Der BALKEN läuft über die tatsächlichen Abrufe, nicht über
        # Truhenplätze: nur die Abrufe wachsen bei jedem Schritt. Ein großer
        # MapStash bündelt hunderte Sektionen auf EINEM Platz — an Plätzen
        # gemessen stünde die Anzeige dort über eine Stunde still
        # (FALLSTRICKE #42). Die Platz-Zahl bleibt als Text im Label
        # (_on_bulk_progress), weil sie die Frage "wie viele meiner Fächer
        # sind durch" beantwortet.
        positions = self._tab_positions()

        self._bulk_dialog = QProgressDialog(
            "Loading stash tabs…", "Cancel", 0, len(to_fetch), self)
        self._bulk_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._bulk_dialog.setMinimumDuration(0)
        self._bulk_dialog.canceled.connect(self.worker.cancel_bulk)
        self._bulk_progress = None
        self._bulk_next_fetch_at = 0.0
        self.worker.submit(FetchAllItemsJob(self._current_league, to_fetch, positions))

    @staticmethod
    def _format_remaining(seconds: float) -> str:
        """"about 2 h 55 min remaining" — grob gerundet, weil die Schätzung
        über Stunden hinweg ohnehin nur größenordnungsgenau ist."""
        if seconds < 0:
            return ""
        minutes = int(seconds // 60)
        if minutes < 1:
            return "less than a minute remaining"
        if minutes < 60:
            return f"about {minutes} min remaining"
        return f"about {minutes // 60} h {minutes % 60} min remaining"

    def _on_bulk_progress(self, progress: BulkProgress) -> None:
        """Balken läuft über die ABRUFE — nur die wachsen bei jedem Schritt.
        Der Truhenplatz-Zähler steht bei einem großen Spezial-Tab sonst über
        eine Stunde still (FALLSTRICKE #42), beantwortet aber als Text die
        Frage "wie viele meiner Fächer sind durch" und bleibt deshalb
        daneben stehen — nur eben nicht mehr als "stash tabs" beschriftet,
        was er nie war (FALLSTRICKE #37).

        Zusätzlich wandert die Auswahl im Stash-Baum auf das gerade
        abgerufene Fach (Peter, 2026-07-30: "dann sieht man das auch ein
        bisschen mehr"). ``highlight_stash`` klappt die nötigen
        Eltern-Ordner auf und scrollt hin, löst aber bewusst kein
        ``stash_selected`` aus — der Bulk-Lauf soll die Item-Tabelle nicht
        bei jedem Tick umschalten."""
        if self._bulk_dialog is None:
            return
        self._bulk_progress = progress
        self._bulk_next_fetch_at = time.monotonic() + progress.next_wait_s
        self._bulk_dialog.setValue(progress.done_requests)
        self.tree.highlight_stash(progress.stash_id)
        self._update_bulk_label()

    def _bulk_wait_line(self) -> str:
        """Sekundengenaue Auskunft, worauf gerade gewartet wird.

        Zwischen zwei Abrufen liegen ~11s Takt (§_fetch_all_items) und
        gelegentlich eine mehrminütige Rate-Limit-Zwangspause. Ohne
        Countdown ist beides von außen nicht von einem Absturz zu
        unterscheiden — dieselbe Frage wie beim Auto-Refresh-Countdown
        ("ca. 5 Minuten gewartet ohne dass irgendwas passiert ist")."""
        now = time.monotonic()
        locked_for = self._rate_limit_wait_until - now
        if locked_for > 1:
            return f"⏸ Rate limit — resuming in {round(locked_for)}s"
        pace_left = self._bulk_next_fetch_at - now
        if pace_left > 0:
            return f"Next tab in {round(pace_left)}s"
        return "Fetching…"

    def _update_bulk_label(self) -> None:
        """Label des Bulk-Dialogs neu setzen. Läuft auch aus dem
        Sekunden-Tick (§_update_auto_refresh_countdown), damit der Countdown
        zwischen zwei Fortschritts-Ticks weiterläuft — ein eigener QTimer
        wäre dafür überflüssig."""
        progress = self._bulk_progress
        if self._bulk_dialog is None or progress is None:
            return
        lines = [f"Loaded: {progress.name}",
                 f"Section {progress.done_requests} of {progress.total_requests}"
                 f"  ·  tab {progress.done_slots} of {progress.total_slots}",
                 self._bulk_wait_line()]
        eta = self._format_remaining(progress.remaining_s)
        if eta:
            lines.append(eta)
        self._bulk_dialog.setLabelText("\n".join(lines))

    def _on_bulk_finished(self, success: int, total: int) -> None:
        if self._bulk_dialog is not None:
            self._bulk_dialog.close()
            self._bulk_dialog = None
        self._bulk_progress = None
        self._bulk_next_fetch_at = 0.0
        self._status_msg.setText(f"All tabs loaded: {success}/{total} successful.")
        self._show_aggregate()

    def _show_aggregate(self) -> None:
        """Items aller bereits geladenen Tabs und Charaktere dieser Liga
        zusammen anzeigen (lokal filter-/exportierbar), siehe `_league_wide_items`."""
        self._clear_view_relative_column_filters()
        self._showing_aggregate = True
        self._search_all_active = False
        self._large_search_items = None
        self._current_tab_name = "All Tabs"
        self._current_stash_id = None  # Rückkehr aus der Suche landet wieder hier
        self._current_character_name = None
        self._current_stash_selection = None
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
        ein Fach geht weiterhin: Baum-Klick oder Spalten-Filter auf "Tab".

        Das Umschalten in/aus dem Aggregat läuft SOFORT (nur einmal pro
        Such-Session), der eigentliche Zeilen-Filter dagegen gedämpft über
        ``_search_debounce`` — sonst kostet ``invalidateFilter()`` bei
        zehntausenden Items spürbar Zeit bei JEDEM Tastendruck."""
        if text and not self._search_all_active:
            self._enter_search_all()
        elif not text and self._search_all_active:
            self._leave_search_all()
        self._search_debounce.start()

    def _apply_debounced_search_filter(self) -> None:
        if self._large_search_items is not None:
            self._run_large_search(self._filter_edit.text())
        else:
            self.proxy.setFilterFixedString(self._filter_edit.text())
            self._update_summaries()

    def _enter_search_all(self) -> None:
        self._clear_view_relative_column_filters()
        self._search_all_active = True
        self._showing_aggregate = True  # späte Einzel-Ergebnisse nicht reinfunken lassen
        self._current_character_name = None
        items, sources, tab_indices, stash_ids = self._league_wide_items()
        self.table.setColumnHidden(TAB_COL, False)  # Herkunft ist Teil der Antwort
        if len(items) > self.LIVE_SEARCH_ITEM_LIMIT:
            # "On demand" statt live (FALLSTRICKE #40, Peter 2026-07-28):
            # das komplette ungefilterte Aggregat NIE als Qt-Modell aufbauen
            # (allein das kostet bei 200k Items ~8s) — nur zwischenspeichern,
            # _run_large_search() füllt das Modell dann direkt mit den
            # gefilterten Treffern, sobald der Dämpfer abgelaufen ist.
            self._large_search_items = (items, sources, tab_indices, stash_ids)
            self.table_model.set_items([])
            self._status_msg.setText(
                f"{len(items)} items in this league — keep typing, "
                "results appear once you pause")
            return
        self._large_search_items = None
        # request_icons=False: sonst würde die Suche zigtausend Icon-Jobs in
        # die Worker-Queue schieben — Icons kommen lazy für sichtbare Zeilen.
        self.table_model.set_items(items, sources, tab_indices, stash_ids, request_icons=False)
        loaded = len({s for s in sources})
        self._status_msg.setText(
            f"Searching {loaded} loaded tabs/characters ({len(items)} items) — "
            "clear the field to return to the tab view")

    def _run_large_search(self, text: str) -> None:
        """"On demand"-Suche für Ligen oberhalb LIVE_SEARCH_ITEM_LIMIT.

        Filtert reines Python direkt auf den in `_enter_search_all`
        zwischengespeicherten Listen (kein Qt-Modell, kein
        Python↔Qt-Aufruf-Overhead pro Zeile) — bei 200.000 Items gemessen
        ~180ms statt der ~8s, die das bloße BEFÜLLEN eines Qt-Modells mit
        derselben Menge kostet. Nur die TREFFER bekommen danach eine
        Tabellenzeile spendiert; Typ- und Spalten-Filter greifen wie gehabt
        über den Proxy auf diese (viel kleinere) Ergebnismenge.

        Sanduhr statt Fortschrittsanzeige: die Aktion ist kurz genug
        (Zielgröße < 1s), dass ein `QProgressDialog` überdimensioniert wäre
        — der Cursor genügt als Rückmeldung "hier passiert gerade etwas"."""
        items, sources, tab_indices, stash_ids = self._large_search_items
        text = text.strip()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if text == "*":
                matched = range(len(items))
            else:
                # Dieselbe Muster-Logik wie im Proxy (§item_table), damit
                # der Regex-Umschalter in beiden Suchpfaden identisch wirkt.
                text_lower = text.lower()
                pattern = compile_search(text_lower, self._regex_search_enabled)
                matched = [i for i, (item, source) in enumerate(zip(items, sources))
                          if matches_search(ItemTableModel._build_haystack(item, source),
                                           text_lower, pattern)]
            matched_items = [items[i] for i in matched]
            matched_sources = [sources[i] for i in matched]
            matched_tabs = [tab_indices[i] for i in matched]
            matched_stash_ids = [stash_ids[i] for i in matched]
            self.table_model.set_items(matched_items, matched_sources, matched_tabs,
                                       matched_stash_ids, request_icons=False)
            self.proxy.setFilterFixedString("")  # Modell enthält bereits nur Treffer
            loaded = len({s for s in matched_sources})
        finally:
            QApplication.restoreOverrideCursor()
        self._status_msg.setText(
            f"{len(matched_items)} of {len(items)} items match ({loaded} tabs/characters) — "
            "clear the field to return to the tab view")
        self._update_summaries()

    def _leave_search_all(self) -> None:
        self._search_all_active = False
        self._large_search_items = None
        # Mehrfachauswahl zuerst prüfen: `_current_stash_id` bleibt während
        # einer Mehrfachauswahl unverändert (siehe `_show_stash_selection`),
        # zeigt hier also noch auf das zuletzt EINZELN angeklickte Fach —
        # ohne diese Reihenfolge würde das Verlassen der Suche fälschlich
        # dorthin zurückspringen statt zur Mehrfachauswahl.
        if self._current_stash_selection is not None:
            self._show_stash_selection(self._current_stash_selection)
        elif self._current_stash_id is not None:
            self._on_stash_selected(self._current_stash_id, self._current_tab_name)
        elif self._leaf_stashes:
            self._show_aggregate()
        else:
            self.table_model.set_items([])

    def _clear_search_field_on_selection(self) -> None:
        """Auswahl eines Stash-Tabs/Ordners oder Charakters leert das
        Suchfeld (Peter, 2026-08-02: "Die Suche sollte meiner Meinung nach
        Global weiter funktionieren und beim Auswählen eines Stash-Tabs
        oder Ordners oder Characters evtl. sogar gelöscht werden") —
        Auswahl bestimmt den angezeigten Umfang, das Suchfeld bleibt für
        das globale Muster reserviert statt unsichtbar weiterzufiltern.

        Nur bei vorhandenem Text leeren, sonst löst jeder Klick unnötig
        ``_on_filter_text_changed``/den Such-Debounce aus. MUSS aufgerufen
        werden, NACHDEM ``_search_all_active`` bereits auf ``False`` steht
        (bei ``_on_stash_selected``/``_on_character_selected`` der Fall):
        sonst würde ``.clear()`` über ``_on_filter_text_changed`` einen
        Re-Entry in ``_leave_search_all()`` auslösen, die selbst wieder
        eine Ansicht aufbaut — mitten im Aufruf, der diese Ansicht gerade
        erst festlegt."""
        if self._filter_edit.text():
            self._filter_edit.clear()

    # --- CSV-Export ------------------------------------------------------ #

    # Zweiter Dateityp statt eines eigenen Dialogs mit Häkchen: Der
    # Speichern-Dialog hat die Auswahlliste ohnehin, und die Roh-JSON-
    # Variante ist genau das — dieselbe Datei mit einer Zusatzspalte
    # (siehe csv_export.py, warum sie nicht die Voreinstellung ist).
    _CSV_FILTER = "CSV files (*.csv)"
    _CSV_RAW_FILTER = "CSV with raw JSON column (*.csv)"

    def _export_csv(self) -> None:
        """Toolbar-Knopf: alle aktuell sichtbaren (gefilterten) Zeilen."""
        self._export_rows(self._visible_rows(), "No items loaded to export.")

    def _export_selected_csv(self) -> None:
        """Rechtsklick-Menü (Peter, 2026-08-02): nur die markierten Zeilen.
        Die Item-Tabelle erlaubt Mehrfachauswahl (Qt-Vorgabe
        ``ExtendedSelection``), Strg-/Umschalt-Klick funktioniert also."""
        self._export_rows(self._selected_rows(), "No items selected to export.")

    def _export_rows(self, rows: list[tuple[str, Item]], empty_hint: str) -> None:
        if not rows:
            QMessageBox.information(self, "CSV Export", empty_hint)
            return
        default_path = str(config.downloads_dir() / self._default_export_filename(len(rows)))
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Items as CSV", default_path,
            f"{self._CSV_FILTER};;{self._CSV_RAW_FILTER}")
        if not path:
            return
        count = export_items(path, rows,
                             price_index=self._price_indexes.get(self._current_league),
                             raw_json=selected_filter == self._CSV_RAW_FILTER)
        self._status_msg.setText(f"Exported {count} items to {path}.")

    def _default_export_filename(self, count: int) -> str:
        """Dateiname-Vorschlag: Liga + Umfang (aktiver Filtertext, Mehrfach-
        auswahl oder Tab-/Aggregat-Name) + Item-Anzahl + Zeitstempel.

        Anzahl und Zeitstempel kamen dazu (Peter, 2026-08-03: "etwas
        aussagekräftiger"), weil "Export selected items" und "Export
        visible items" aus derselben Ansicht sonst denselben Namen
        vorschlagen — ein 5- und ein 200-Item-Export derselben Truhe waren
        im Downloads-Ordner nicht mehr auseinanderzuhalten, und ein
        zweiter Export derselben Ansicht überschrieb den ersten
        kommentarlos, sobald man den Dialog nur bestätigte.

        Die Liga gehört immer mit rein — Items sind nie liga-übergreifend
        gültig, das soll auch am Dateinamen erkennbar sein.

        Mehrfachauswahl-Sonderfall: `_current_tab_name` bleibt während einer
        Mehrfachauswahl UNVERÄNDERT (zeigt weiter auf das zuletzt einzeln
        angeklickte Fach, siehe `_show_stash_selection`) — für den
        Dateinamen wird deshalb hier direkt aus `_current_stash_selection`
        abgeleitet, statt den irreführenden alten Namen zu verwenden.
        """
        filter_text = self._filter_edit.text().strip()
        if filter_text:
            base = sanitize_filename(filter_text)
        elif self._current_stash_selection is not None:
            base = sanitize_filename(f"{len(self._current_stash_selection)}-tabs-selected")
        else:
            base = sanitize_filename(self._current_tab_name)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        parts = [p for p in (sanitize_filename(self._current_league, ""), base,
                             f"{count}items", timestamp) if p]
        return f"poe-view2-{'-'.join(parts)}.csv"

    def _visible_rows(self) -> list[tuple[str, Item]]:
        """(Tab-Name, Item)-Paare für die AKTUELL sichtbaren (gefilterten) Zeilen."""
        return self._rows_for([self.proxy.index(row, 0)
                               for row in range(self.proxy.rowCount())])

    def _selected_rows(self) -> list[tuple[str, Item]]:
        """(Tab-Name, Item)-Paare der markierten Zeilen, in Anzeige-
        Reihenfolge. ``selectedRows`` liefert je Zeile genau einen Index
        (nicht je Zelle), sortiert wird nach der sichtbaren Position statt
        nach Auswahl-Reihenfolge — sonst hinge die Reihenfolge im Export
        daran, in welcher Folge geklickt wurde."""
        indexes = self.table.selectionModel().selectedRows()
        return self._rows_for(sorted(indexes, key=lambda idx: idx.row()))

    def _rows_for(self, indexes: list) -> list[tuple[str, Item]]:
        rows: list[tuple[str, Item]] = []
        for index in indexes:
            source_idx = self.proxy.mapToSource(index)
            item = self.table_model.item_at(source_idx.row())
            if item is not None:
                rows.append((self.table_model.source_at(source_idx.row()), item))
        return rows

    def _on_character_selected(self, char: Character) -> None:
        """Zeigt Ausrüstung + Inventar des Charakters in der Item-Tabelle —
        wie bei Stash-Fächern: Cache-Treffer zeigen sofort an, sonst wird
        einmalig nachgeladen (kein automatisches Neuladen bei jedem Klick,
        Doku §4.4/§5)."""
        self._clear_view_relative_column_filters()
        self._search_all_active = False  # Charakter-Klick beendet die liga-weite Suchansicht
        self._large_search_items = None
        self._current_stash_selection = None  # Charakter-Auswahl beendet eine Mehrfachauswahl
        self._clear_search_field_on_selection()
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
        self._clear_view_relative_column_filters()
        self._current_stash_selection = None  # Charakter-Refresh beendet eine Mehrfachauswahl
        self._current_character_name = char.name
        self._status_msg.setText(f"Loading equipment: {char.name}…")
        self.worker.submit(FetchCharacterItemsJob(char.name))

    def _on_character_items(self, name: str, items: list[Item], silent: bool) -> None:
        """``name`` kommt aus dem Signal, nicht aus der Auswahl — sonst könnte
        ein spät eintreffender Job Daten eines inzwischen abgewählten
        Charakters in die aktuelle Ansicht einsickern lassen (analog
        `_on_stash_items`)."""
        previous_items = self._character_items.get(name)  # vor dem Überschreiben: Diff-Basis
        self._character_items[name] = items
        self._character_items_loaded[name] = datetime.now(timezone.utc).isoformat()
        self._log_character_item_history(name, previous_items, items)
        self._persist_cache()
        if silent:
            # Policy-Name jetzt festhalten, siehe Kommentar in
            # _count_silent_refresh.
            self._refresh_mode_policy = self.worker.rate_limiter.last_policy
            self._note_refresh_mode_job_done()
        if name == self._paperdoll_pending_char:
            # Unabhängig von _current_character_name: der Doppelklick galt
            # genau diesem Charakter, auch wenn die Auswahl inzwischen
            # weitergesprungen ist.
            self._paperdoll_pending_char = None
            self._open_paperdoll(name, items)
        if name != self._current_character_name:
            return
        self._show_character_items(name, items, previous_items)

    def _on_character_paperdoll_requested(self, char: Character) -> None:
        """Doppelklick auf einen Charakter (ToDo.md: "Doppelklick auf einen
        Char 'beleuchtet' diesen"). Der vorangehende Einzelklick (Teil
        derselben Doppelklick-Sequenz) hat _on_character_selected bereits
        ausgelöst — bei fehlendem Cache wartet die Paperdoll auf dessen
        Ergebnis (siehe _on_character_items)."""
        cached = self._character_items.get(char.name)
        if cached is not None:
            self._open_paperdoll(char.name, cached)
        else:
            self._paperdoll_pending_char = char.name

    def _open_paperdoll(self, name: str, items: list[Item]) -> None:
        char = next((c for c in self._all_characters if c.name == name), None)
        if char is None:
            return
        self._paperdoll_dialog = PaperdollDialog(char, items, self.table_model.pixmap_for,
                                                 parent=self)
        self._paperdoll_dialog.show()

    @staticmethod
    def _diff_character_items(
            previous_items: list[Item] | None,
            items: list[Item]) -> tuple[frozenset[str], frozenset[str], list[Item]]:
        """Vergleicht den vorigen mit dem aktuellen Item-Stand eines
        Charakters (Peter 2026-08-01: "die Zeilen hervorgehoben (Türkis),
        welche sich geändert haben"; verschwundene Items grau/durchgestrichen
        statt sofort zu verschwinden). ``previous_items=None`` heißt "kein
        vorheriger Ladevorgang zum Vergleichen" (erstes Öffnen dieses
        Charakters) — dann bewusst KEIN Hervorheben, sonst wäre beim
        allerersten Anzeigen sofort alles "neu".

        Items ohne ``id`` (in echten Daten bislang nicht beobachtet, laut
        Modell aber möglich) bleiben unberücksichtigt — ohne stabile
        Kennung ist "gleiches Item, anderer Zustand" von "verschwunden +
        neues Item" nicht unterscheidbar.

        Rückgabe: (added_ids, changed_ids, removed_items).
        - ``added_ids``: ``item.id`` kam in ``previous_items`` gar nicht
          vor — ein echter Neuzugang (z. B. Loot, Handel).
        - ``changed_ids``: ``item.id`` existierte schon, aber der Item-Wert
          hat sich geändert (z. B. Stack-Größe) — bewusst GETRENNT von
          ``added_ids``: ein neu aufgetauchtes Item ist etwas anderes als
          ein vorhandenes, das sich nur verändert hat. Die Türkis-
          Hervorhebung deckt beide Fälle gleich ab (``_show_character_
          items``), der Charakter-Item-Verlauf (Peter, 2026-08-02:
          ``_log_character_item_history``) dagegen NUR ``added_ids``, um
          reine Stack-Größen-Änderungen nicht als "neues Item" zu loggen.
        - ``removed_items``: Item-Objekte aus ``previous_items``, die im
          aktuellen Stand fehlen — der Aufrufer der Türkis-/Grau-Anzeige
          hängt sie ans Ende der angezeigten Liste an, damit sie für GENAU
          EINEN Refresh-Zyklus sichtbar bleiben (sie stecken nicht in
          ``self._character_items``, der eigentlichen Diff-Basis, also
          fallen sie beim nächsten Refresh von selbst wieder raus)."""
        if previous_items is None:
            return frozenset(), frozenset(), []
        previous_by_id = {item.id: item for item in previous_items if item.id}
        current_ids = {item.id for item in items if item.id}
        added_ids = frozenset(item.id for item in items
                              if item.id and item.id not in previous_by_id)
        changed_ids = frozenset(
            item.id for item in items
            if item.id and item.id in previous_by_id and item != previous_by_id[item.id]
        )
        removed_items = [item for item_id, item in previous_by_id.items()
                         if item_id not in current_ids]
        return added_ids, changed_ids, removed_items

    @staticmethod
    def _stack_size_changes(previous_items: list[Item] | None,
                            items: list[Item]) -> list[tuple[Item, int]]:
        """Items, deren Stack-Größe sich seit dem letzten Ladevorgang
        geändert hat (Peter, 2026-08-03: "In unserer Item-History-Liste
        berücksichtigen wir keine Items die sich ändern, wie Currency ...
        sobald sich Currency ändert, wandert diese wieder ganz oben auf die
        Liste mit Vermerk, wieviel sich geändert hat" — bewusst nicht auf
        Currency beschränkt, jedes stapelbare Item zählt, Currency ist nur
        das häufigste Beispiel; und bewusst nur Charakter-Inventar, siehe
        Peters Antwort "Nur die im Charakter-Inventar").

        GETRENNT von ``changed_ids`` in ``_diff_character_items`` (die auch
        auf beliebige andere Feldänderungen anschlägt, z. B. Identifizieren)
        — hier zählt ausschließlich eine tatsächliche Stack-Größen-Differenz,
        sonst würde z. B. ein gerade identifiziertes Item fälschlich als
        "Menge geändert" geloggt. Items, die gerade erst neu aufgetaucht
        sind, haben keinen Vorgänger und tauchen hier nicht auf (die zählen
        als ``added``, nicht als ``changed``)."""
        if previous_items is None:
            return []
        previous_by_id = {item.id: item for item in previous_items if item.id}
        changes = []
        for item in items:
            previous = previous_by_id.get(item.id) if item.id else None
            if previous is None:
                continue
            delta = (item.stackSize or 0) - (previous.stackSize or 0)
            if delta != 0:
                changes.append((item, delta))
        return changes

    def _log_character_item_history(self, name: str, previous_items: list[Item] | None,
                                    items: list[Item]) -> None:
        """Protokolliert neu aufgetauchte/verschwundene/mengenmäßig
        veränderte Items eines Charakters im globalen Verlauf (Peter,
        2026-08-02: "eine Liste mit den letzten 120 Items, die durchs
        Inventar gewandert sind ... was du gerade in die Truhe getan hast
        oder verkauft hast oder gehandelt hast"; Stack-Änderungen wie bei
        Currency ergänzt am 2026-08-03, siehe ``_stack_size_changes``).
        Läuft für JEDEN Charakter, unabhängig davon, ob er gerade angezeigt
        wird — anders als die Türkis-/Grau-Anzeige in
        ``_show_character_items``, die nur die aktuell offene Ansicht
        betrifft. ``previous_items=None`` (erster Ladevorgang dieses
        Charakters) loggt bewusst nichts, sonst würde jeder erstmalige
        Charakter-Load die komplette Ausrüstung als "neu" eintragen."""
        added_ids, _changed_ids, removed_items = self._diff_character_items(previous_items, items)
        stack_changes = self._stack_size_changes(previous_items, items)
        if not added_ids and not removed_items and not stack_changes:
            return
        now = datetime.now(timezone.utc)
        for item in items:
            if item.id in added_ids:
                self._item_history.appendleft(HistoryEntry(now, "added", name, item))
        for item, delta in stack_changes:
            self._item_history.appendleft(HistoryEntry(now, "changed", name, item, delta))
        for item in removed_items:
            self._item_history.appendleft(HistoryEntry(now, "removed", name, item))
        self.history_model.set_entries(list(self._item_history))

    def _show_character_items(self, name: str, items: list[Item],
                              previous_items: list[Item] | None = None) -> None:
        """Slot (``inventoryId``, z. B. "Weapon"/"BodyArmour"/"MainInventory")
        übernimmt die Rolle der Tab-Spalte — analog zu den Aggregat-Ansichten
        der Stash-Tabs. Kein Truhenfach beteiligt: Position-Spalte zeigt nur
        die Item-Koordinate (falls vorhanden), Baum-Hervorhebung entfällt.

        ``previous_items`` ist der Item-Stand VOR diesem Refresh (``None``
        beim ersten Anzeigen bzw. aus dem Cache, siehe
        ``_on_character_selected``) — Grundlage der Türkis-/Grau-Diff-
        Hervorhebung, siehe ``_diff_character_items``."""
        self._showing_aggregate = False
        self._search_all_active = False
        self._large_search_items = None
        self._current_stash_id = None
        self._current_stash_selection = None
        self.table.setColumnHidden(TAB_COL, False)
        added_ids, changed_ids, removed_items = self._diff_character_items(previous_items, items)
        display_items = items + removed_items
        sources = [item.inventoryId or "?" for item in display_items]
        removed_ids = frozenset(item.id for item in removed_items if item.id)
        self.table_model.set_items(display_items, sources, [None] * len(display_items),
                                   [None] * len(display_items),
                                   changed_ids=added_ids | changed_ids, removed_ids=removed_ids)
        self._status_msg.setText(f"{name}: {len(items)} items (equipment + inventory)")

    def _on_icon(self, url: str, data: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        self.table_model.set_icon(url, pixmap)
        self.history_model.set_icon(url, pixmap)
        if self._pending_card_art and self._pending_card_art[0] == url:
            _, dialog = self._pending_card_art
            self._pending_card_art = None
            dialog.set_icon_pixmap(pixmap)

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

    def _on_table_row_double_clicked(self, index) -> None:
        """Doppelklick auf ein Item: vergrößerte Ansicht (ToDo.md, Peter
        2026-07-31) — dieselben Daten wie das kompakte Detail-Panel, nur
        ohne dessen Zeilen-Kürzung und mit größerem Icon."""
        source_idx = self.proxy.mapToSource(index)
        item = self.table_model.item_at(source_idx.row())
        if item is None:
            return
        self._item_zoom_dialog = ItemZoomDialog(item, self.table_model.pixmap_for(item),
                                                parent=self)
        self._item_zoom_dialog.show()
        if item.frameType == 6:  # Divination Card — echtes Artwork nachladen
            self._request_card_art(item, self._item_zoom_dialog)

    def _request_card_art(self, item: Item, dialog: ItemZoomDialog) -> None:
        """Ersetzt das generische (für jede Div-Card identische) Icon durch
        das echte Karten-Artwork (FALLSTRICKE #52). Cache-Treffer sind ein
        schneller, synchroner Datei-Read (wie an anderen Stellen auch),
        sonst läuft der Download wie jedes andere Icon über den Worker."""
        url = external_tools.divination_card_art_url(item)
        if url is None:
            return
        cached = icon_cache.load(url)
        if cached is not None:
            pixmap = QPixmap()
            if pixmap.loadFromData(cached):
                dialog.set_icon_pixmap(pixmap)
            return
        self._pending_card_art = (url, dialog)
        self.worker.submit(FetchIconJob(url))

    def _on_table_row_menu(self, pos) -> None:
        """Rechtsklick auf ein Item: externe Tools dazu öffnen (ToDo.md,
        Peter 2026-07-30) und CSV-Export (Peter, 2026-08-02)."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        # Eine bestehende Mehrfachauswahl NICHT zerstören: Rechtsklick
        # INNERHALB der Auswahl lässt sie stehen (sonst könnte man 20
        # markierte Zeilen nie exportieren — das Öffnen des Menüs hätte die
        # Auswahl gerade auf eine Zeile zusammengestrichen), Rechtsklick
        # außerhalb wählt wie gewohnt die angeklickte Zeile.
        if not self.table.selectionModel().isRowSelected(index.row()):
            self.table.selectRow(index.row())
        source_idx = self.proxy.mapToSource(index)
        item = self.table_model.item_at(source_idx.row())
        if item is None:
            return
        menu = self._build_item_tools_menu(item)
        self._add_export_actions(menu)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _add_export_actions(self, menu: QMenu) -> None:
        """Export-Einträge ans Ende eines Item-Kontextmenüs. Die Anzahl steht
        im Text, damit vor dem Speichern-Dialog klar ist, was gleich in der
        Datei landet."""
        menu.addSeparator()
        selected = len(self.table.selectionModel().selectedRows())
        export_selected = menu.addAction(f"💾 Export selected items ({selected})…")
        export_selected.triggered.connect(self._export_selected_csv)
        export_visible = menu.addAction(
            f"💾 Export visible items ({self.proxy.rowCount()})…")
        export_visible.triggered.connect(self._export_csv)

    def _build_item_tools_menu(self, item: Item) -> QMenu:
        """Losgelöst von ``_on_table_row_menu``, damit Tests die
        Menü-Zusammenstellung prüfen können, ohne ``QMenu.exec()`` (blockiert
        ohne echte Nutzerinteraktion) auszulösen. Einträge kommen aus den
        konfigurierbaren ``ToolEntry``s (Settings-Dialog), es gibt keine
        fest verdrahteten und ab Werk auch keine vorbelegten — siehe
        ``external_tools``-Modul-Docstring.

        Ohne einen einzigen aktiven Eintrag (Auslieferungszustand) zeigt das
        Menü statt eines leeren Popups einen deaktivierten Hinweis auf den
        Settings-Dialog — ein leeres Kontextmenü sieht sonst wie ein Fehler
        aus."""
        menu = QMenu(self.table)
        for entry in self._load_tool_entries():
            if not entry.enabled:
                continue
            url = external_tools.build_url(entry, item)
            menu.addAction(f"{entry.name} öffnen",
                           lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        if menu.isEmpty():
            hint = menu.addAction("No item tools configured — see Settings")
            hint.setEnabled(False)
        return menu

    def _on_history_row_double_clicked(self, index) -> None:
        """Doppelklick auf einen Verlaufs-Eintrag: dieselbe vergrößerte
        Ansicht wie in der Item-Tabelle (Peter, 2026-08-02: "nochmal kurz
        nachschauen, was du gerade ... verkauft hast oder gehandelt
        hast") — kein eigener Proxy, der Verlauf hat kein Filter/Sort."""
        entry = self.history_model.entry_at(index.row())
        if entry is None:
            return
        item = entry.item
        self._item_zoom_dialog = ItemZoomDialog(item, self.history_model.pixmap_for(item),
                                                parent=self)
        self._item_zoom_dialog.show()
        if item.frameType == 6:
            self._request_card_art(item, self._item_zoom_dialog)

    def _on_history_row_menu(self, pos) -> None:
        """Rechtsklick auf einen Verlaufs-Eintrag: dieselben externen Tools
        wie in der Item-Tabelle (§_build_item_tools_menu)."""
        index = self.history_table.indexAt(pos)
        if not index.isValid():
            return
        entry = self.history_model.entry_at(index.row())
        if entry is None:
            return
        menu = self._build_item_tools_menu(entry.item)
        menu.exec(self.history_table.viewport().mapToGlobal(pos))

    def _load_tool_entries(self) -> list[external_tools.ToolEntry]:
        stored = self._settings().value("external_tools/entries")
        return external_tools.tools_from_json(stored if isinstance(stored, str) else None)

    def _save_tool_entries(self, entries: list[external_tools.ToolEntry]) -> None:
        self._settings().setValue("external_tools/entries", external_tools.tools_to_json(entries))

    def _load_zone_watcher_config(self) -> tuple[bool, str]:
        settings = self._settings()
        enabled = str(settings.value("zone_watcher/enabled", "")).lower() in ("true", "1")
        path = str(settings.value("zone_watcher/log_path", "") or "")
        return enabled, path

    def _save_zone_watcher_config(self, enabled: bool, path: str) -> None:
        settings = self._settings()
        settings.setValue("zone_watcher/enabled", enabled)
        settings.setValue("zone_watcher/log_path", path)

    def _apply_zone_watcher_config(self, enabled: bool, path: str) -> None:
        """Ersetzt einen laufenden Watcher komplett statt ihn umzukonfigurieren
        — einfacher als ein zweites Update-Codepfad und läuft nur beim
        Programmstart bzw. nach dem Settings-Dialog, also selten genug,
        dass der Neuaufbau nicht ins Gewicht fällt."""
        if self._zone_watcher is not None:
            self._zone_watcher.setParent(None)
            self._zone_watcher.deleteLater()
            self._zone_watcher = None
        if not enabled:
            return
        resolved = resolve_client_log_path(path)
        if resolved is None:
            return  # ungültiger/leerer Pfad — Dialog zeigt das schon live an, keine weitere Fehlermeldung nötig
        self._zone_watcher = ZoneWatcher(resolved, self)
        self._zone_watcher.zone_changed.connect(self._on_zone_changed)

    def _on_zone_changed(self, zone_name: str) -> None:
        """Peter, 2026-08-01: "Erst nach Zonenwechsel gibt es einen
        Refresh" — live bestätigt (FALLSTRICKE #58). Lädt NUR die gerade
        offene Ansicht neu (wie der gezielte Teil von
        ``_maybe_auto_refresh``), kein Sweep, kein Burst — ein einzelner
        Request pro Zonenwechsel. Respektiert den Pause-Modus (explizite
        Nutzerwahl "keine Hintergrund-Anfragen") und die harte
        Rate-Limit-Obergrenze, sonst identisch zu jedem anderen stillen
        Refresh."""
        if (self._refresh_mode == "pause" or self._bulk_dialog is not None
                or not self._logged_in or not self._current_league
                or self._current_league_is_archived()
                or self.worker.rate_limiter.pacing_blocked()):
            return
        if self._refresh_current_view():
            self._on_status(f"Zone changed to {zone_name!r} — refreshing current view")

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self._load_tool_entries(), self._load_column_config(),
                                *self._load_zone_watcher_config(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_tool_entries(dialog.result_entries())
            column_config = dialog.result_column_config()
            self._save_column_config(column_config)
            self._apply_column_config(column_config)
            zone_enabled, zone_path = dialog.result_zone_watcher_config()
            self._save_zone_watcher_config(zone_enabled, zone_path)
            self._apply_zone_watcher_config(zone_enabled, zone_path)

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
        if self._refresh_mode in self.STEPPING_REFRESH_MODES:
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
        self._update_bulk_label()  # Countdown im Bulk-Dialog weiterzählen
        # Sicherheitsnetz für Single/Stash: falls die Job-Kette (§_drive_
        # refresh_mode) je stockt — etwa weil ein Fehler den erwarteten
        # Erfolgs-Signal-Pfad übersprungen hat —, stößt der ohnehin
        # laufende Sekunden-Timer sie spätestens hier wieder an.
        self._drive_refresh_mode()
        if not self._current_league:
            self._auto_refresh_countdown_label.setText("")
            return
        if self._refresh_mode == "pause":
            self._auto_refresh_countdown_label.setText(
                "Refresh mode: Pause — no background requests")
            return
        if self._refresh_mode in self.STEPPING_REFRESH_MODES:
            mode_name = self._refresh_mode_combo.currentText()
            # Pausiert der Takt wegen zu vollen Fensters, gehört genau das
            # ins Label — ein weiterlaufender Countdown, der bei 0s stehen
            # bleibt, sähe wieder wie ein Hänger aus (§pacing_blocked).
            if self.worker.rate_limiter.pacing_blocked(self._refresh_mode_policy):
                self._auto_refresh_countdown_label.setText(
                    f"Refresh mode: {mode_name} — waiting for rate-limit headroom")
                return
            seconds = max(0, round(self._refresh_mode_next_due - time.monotonic()))
            self._auto_refresh_countdown_label.setText(
                f"Refresh mode: {mode_name} — next update in {seconds}s")
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
        # _refresh_mode_policy bewusst NICHT zurückgesetzt — siehe
        # Kommentar in _on_league_changed (FALLSTRICKE #48).
        self._refresh_mode_priority_id = None
        self.dashboard.set_paused(self._refresh_mode == "pause")
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
        dadurch beim Rundlauf schneller wieder dran.

        Einmal geladene Remove-only-Fächer (`_is_remove_only_tab`) fallen aus
        diesem Rundlauf raus (Peter, 2026-08-02: "da hier niemals neue Items
        hinzukommen und nur herausgenommen werden können") — sie kommen nur
        noch dran, wenn es sonst KEIN anderes gefülltes Fach gibt. Vor dem
        ersten Laden sind sie ganz normal in ``empty`` und werden über den
        üblichen Rundlauf durch die leeren Fächer trotzdem einmal geladen."""
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
        regular = [s for s in non_empty if not self._is_remove_only_tab(s)]
        cycle_pool = regular or non_empty

        if cycle_pool and self._stash_mode_round_picks >= len(cycle_pool):
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
        return min(cycle_pool or self._leaf_stashes, key=sort_key)

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

        Anders als Auto (§_auto_refresh_blocked_reason) wird kein festes
        Budget für manuelle Klicks reserviert — der Nutzer hat den Modus
        bewusst gewählt, um den Pool für genau dieses Ziel einzusetzen.
        Eine Obergrenze gibt es trotzdem: ``rate_limiter.pacing_blocked()``
        stoppt den Takt, sobald das Fenster ohnehin schon zu voll ist.
        Ohne sie taktete der Modus stur weiter, während ungetaktete
        Requests (Klicks, Liga-Wechsel, Programmstart) dasselbe Fenster
        mitfüllten — real endete das in 289s Zwangspause
        (FALLSTRICKE #47)."""
        if self._refresh_mode not in self.STEPPING_REFRESH_MODES:
            return  # "auto" läuft am eigenen Timer, "pause" gar nicht
        if (self._refresh_mode_pending or not self._logged_in
                or not self._current_league or self._current_league_is_archived()):
            return
        if self._bulk_dialog is not None:
            # "Load All Tabs" taktet sich selbst durch die ganze Truhe
            # (§ApiWorker._fetch_all_items). Liefe der Modus daneben weiter,
            # verdoppelte sich die Anfragerate und beide zusammen liefen
            # prompt in die 300s-Sperre, die jeder für sich vermeidet.
            return
        if self.worker.rate_limiter.pacing_blocked(self._refresh_mode_policy):
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
        self._refresh_current_view()
        candidate = self._pick_auto_refresh_candidate()
        if candidate is not None and candidate.id != current_id:
            self.worker.submit(FetchStashItemsJob(
                self._current_league, candidate.id, candidate.display_name,
                parent_id=candidate.parent, silent=True))

    def _refresh_current_view(self) -> bool:
        """Lädt das gerade angezeigte Fach oder den gerade angezeigten
        Charakter neu, unabhängig vom Alter der Daten — der gezielte
        (nicht der Sweep-)Teil von ``_maybe_auto_refresh``, gemeinsam
        genutzt mit ``_on_zone_changed`` (§ZoneWatcher). Gibt zurück, ob
        überhaupt etwas angezeigt war, das sich neu laden ließ."""
        current_id = self._current_stash_id
        if current_id is not None:
            self.worker.submit(FetchStashItemsJob(
                self._current_league, current_id, self._current_tab_name,
                parent_id=self._parent_id_of(current_id), silent=True))
            return True
        if self._current_character_name is not None:
            self.worker.submit(FetchCharacterItemsJob(self._current_character_name, silent=True))
            return True
        return False

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

    @staticmethod
    def _is_remove_only_tab(stash: StashTab) -> bool:
        """GGGs Zusatz-Hinweis " (Remove-only)" steckt im `name`-Feld selbst
        (siehe `models.is_ggg_suffix`), sowohl bei Top-Level-Fächern als auch
        bei Unique-Stash-Kindern — ein solches Fach kann nur noch schrumpfen,
        nie wachsen (Peter, 2026-08-02: "da hier niemals neue Items
        hinzukommen und nur herausgenommen werden können"). Genutzt von
        `_pick_auto_refresh_candidate` UND `_pick_stash_mode_candidate`, um
        solche Fächer beim Refresh nachrangig zu behandeln."""
        return "remove-only" in stash.name.lower()

    def _pick_auto_refresh_candidate(self) -> StashTab | None:
        """Ältester Tab der aktuellen Liga — inkl. noch nie geladener Tabs (⬇).

        Noch nie geladene Tabs gelten als "unendlich alt" und werden immer
        als Kandidat betrachtet (die 1-Tag-Schonfrist gilt nur für bereits
        bekannte Daten — es gibt nichts zu schonen, wenn noch gar keine
        Daten da sind). So füllt sich der Stash über die Zeit von selbst,
        ohne dass 391 Tabs einzeln angeklickt werden müssen.
        Remove-only-Fächer (`_is_remove_only_tab`) werden nachrangig behandelt
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
        preferred = [pair for pair in candidates if not self._is_remove_only_tab(pair[1])]
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
