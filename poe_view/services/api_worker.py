"""ApiWorker: EIN Thread für alle API-Zugriffe (docs/ARCHITEKTUR.md §4.5).

Jobs kommen über eine Queue herein und werden sequenziell abgearbeitet —
Absicht: so bleibt das Rate-Limiting deterministisch und trivial. Ergebnisse
gehen ausschließlich per Qt-Signal zurück an den Main-Thread; die UI fasst
den Client nie direkt an.

"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field

import httpx
from PySide6.QtCore import QThread, Signal

from poe_view import config
from poe_view.api import ninja, oauth
from poe_view.api.client import ApiError, AuthError, PoeApiClient
from poe_view.api.models import StashTab
from poe_view.api.rate_limiter import RateLimitManager
from poe_view.services import icon_cache, poe2_probe, token_store

log = logging.getLogger(__name__)

OFFLINE_MESSAGE = ("GGG API unreachable (maintenance or no network) — "
                   "showing cached data.")


# Die eine 4xx-Antwort, die nachweislich KEIN Anwendungsfehler ist:
# GGGs Truhen-Endpunkt beantwortet eine laufende Wartung mit HTTP 400 und
# der Begründung, es gebe die Liga nicht. Gemessen an Peters Log vom
# 2026-08-13, 01:03:41 bis 01:17:41 — 22 Abruf-Zyklen im 40-Sekunden-Takt:
#
#   /character/<Name>  →  22 × 503
#   /stash/<Liga>/<Id> →  19 × 400 "Invalid query; League not found",
#                          3 × 503
#
# Die beiden Anfragen liegen je 170 ms auseinander, es ist dieselbe
# Wartung. Und die Liga gab es die ganze Zeit: Um 01:18:21 lieferte
# GENAU DIESELBE URL wieder 200. Der Statuscode allein taugt hier also
# nicht als Unterscheidungsmerkmal (ARCHITEKTUR.md §4.12, FALLSTRICKE #67).
#
# Warum am Text festgemacht und nicht am Fehlercode 2: Code 2 heißt bei
# GGG allgemein "Invalid query" und träfe auch einen von UNS falsch
# gebauten Substash-Pfad — genau den Fall, den die 4xx-Regel schützen
# soll. Der Text ist die engere Bedingung. Ändert GGG die Formulierung,
# fällt das Verhalten auf das alte zurück (laute Fehlermeldung), nicht
# auf ein verschlucktes Problem.
_MAINTENANCE_400_MESSAGE = "league not found"


def _is_maintenance_bad_request(exc: Exception) -> bool:
    """Ein 400, das in Wahrheit "GGG ist gerade weg" bedeutet."""
    return (isinstance(exc, ApiError) and exc.status_code == 400
            and _MAINTENANCE_400_MESSAGE in exc.error_message.lower())


def _is_connectivity_issue(exc: Exception) -> bool:
    """Unterscheidet "wir sind offline" (GGG-Wartung, kein Netz) von echten
    Anwendungsfehlern (§4.12) — nur Ersteres soll den Offline-Modus auslösen.

    httpx.TransportError: DNS/Verbindung/Timeout — nie ein Anwendungsfehler.
    ApiError mit 5xx: Server-/Wartungsfehler. 4xx bleiben echte Fehler (z. B.
    ein falsch zusammengesetzter Substash-Pfad) — mit der einen gemessenen
    Ausnahme oben. json.JSONDecodeError: GGG liefert bei Wartung mitunter
    eine HTML-Seite mit HTTP 200 statt JSON."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, ApiError) and exc.status_code >= 500:
        return True
    if _is_maintenance_bad_request(exc):
        return True
    return isinstance(exc, json.JSONDecodeError)


# --------------------------- Job-Typen --------------------------------- #
# Ein Job entspricht einem Eintrag in der Queue.

@dataclass
class BootstrapJob:
    """App-Start: gespeichertes Token prüfen, sonst Login anfordern."""


@dataclass
class LoginJob:
    """Interaktiver OAuth-Login (öffnet den Browser)."""


@dataclass
class LogoutJob:
    pass


@dataclass
class FetchLeaguesJob:
    pass


@dataclass
class FetchCharactersJob:
    pass


@dataclass
class FetchStashListJob:
    league: str
    silent: bool = False  # True = Stash-Modus-Rundlauf, kein Status-/Anzeige-Update


@dataclass
class FetchStashItemsJob:
    league: str
    stash_id: str
    stash_name: str
    parent_id: str | None = None  # gesetzt bei Kindern von Spezial-Tabs (MapStash, …)
    silent: bool = False  # True = Hintergrund-Auto-Refresh, kein Status-/Anzeige-Update


@dataclass
class FetchCharacterItemsJob:
    name: str
    silent: bool = False  # True = Hintergrund-Auto-Refresh (aktuell angezeigter Charakter)


@dataclass
class FetchIconJob:
    url: str


@dataclass
class FetchAllItemsJob:
    """Alle Items EINER Liga über alle (Nicht-Ordner-)Tabs hinweg laden.

    Läuft absichtlich sequenziell im Worker-Thread: jeder Tab durchläuft
    denselben Rate-Limit-Check wie eine Einzelabfrage, dauert also ggf.
    lange — deshalb die Fortschritts-Signale statt eines einzigen Ergebnisses.
    """

    league: str
    stashes: list[StashTab]  # bereits rekursiv abgeflachte Nicht-Ordner-Tabs
    # stash_id -> echter Truhenplatz (FALLSTRICKE #36): Map-/Unique-Sektionen
    # teilen sich den Platz ihres Eltern-Tabs. Fehlt ein Eintrag (z. B. in
    # Tests), zählt die stash_id selbst als eigener Platz.
    positions: dict[str, int] = field(default_factory=dict)


@dataclass
class FetchPricesJob:
    """poe.ninja-Preise für eine Liga. Unabhängig von der GGG-API — kein
    Auth nötig, läuft deshalb auch ohne gesetztes Token (``_NEEDS_AUTH``
    lässt diesen Job bewusst aus)."""

    league: str


@dataclass
class Poe2ProbeJob:
    """Einmaliger Rohdaten-Abzug der PoE2-Endpunkte (§4.43).

    Kein Bestandteil des normalen Betriebs — wird nur durch den Eintrag
    im Konto-Menü ausgelöst und liefert Text zum Ansehen, keine Daten für
    Tabelle oder Cache."""


@dataclass
class _StopJob:
    pass


@dataclass(frozen=True)
class BulkProgress:
    """Ein Fortschritts-Tick von "Alle Tabs laden".

    Bewusst ein Datensatz statt vieler Signal-Parameter: der Fortschritt
    braucht inzwischen zwei Zähl-Einheiten (§_fetch_all_items), zwei
    Zeitangaben und die Fach-Identität für die Baum-Hervorhebung. Als
    Positionsargumente wäre am Empfänger nicht mehr zu erkennen, welche
    Zahl welche ist.
    """

    done_requests: int    # tatsächliche Abrufe — wächst bei JEDEM Schritt
    total_requests: int
    done_slots: int       # echte Truhenplätze — Sektionen teilen sich einen
    total_slots: int
    name: str             # gerade abgerufenes Fach
    stash_id: str         # dito, für StashTree.highlight_stash()
    remaining_s: float    # Restzeit-Schätzung für den ganzen Lauf
    next_wait_s: float    # Taktpause bis zum nächsten Abruf (~11s)


# Anlässe für ``ApiWorker.login_required``. Alle drei bedeuten "kein
# gültiges Token mehr", verlangen im UI aber Verschiedenes: Beim Start
# ohne Token soll der Willkommensdialog kommen, bei einem Ablauf mitten
# in der Sitzung das Ablauf-Popup — und nach einem ausdrücklichen Logout
# gar nichts, denn dann weiß der Nutzer es selbst am besten.
LOGIN_NO_TOKEN = "no_token"    # Programmstart, kein/abgelaufenes Token gespeichert
LOGIN_EXPIRED = "expired"      # HTTP 401 aus einem laufenden Job
LOGIN_LOGGED_OUT = "logged_out"  # Nutzer hat selbst abgemeldet


def _is_missing_stash(job, exc: Exception) -> bool:
    """Ein Fach-Abruf, den GGG mit 404 beantwortet.

    Beobachtet am 2026-08-24 an Peters Map-Stash: Das Unterfach steht in
    der Fächerliste, der Abruf liefert aber ``404`` mit ``{"stash":null}``
    — solche Unterfächer entstehen serverseitig erst, wenn etwas darin
    liegt. Das ist eine gültige Antwort, kein Fehler; behandelt wird sie
    trotzdem, weil sie sich sonst nie erledigt (§4.50)."""
    return (isinstance(job, FetchStashItemsJob)
            and isinstance(exc, ApiError) and exc.status_code == 404)


class ApiWorker(QThread):
    """Arbeitet die Job-Queue ab, bis ``stop()`` gerufen wird."""

    # Signale. 'object' statt konkreter Typen, damit
    # pydantic-Modelle und Listen unverändert durchgereicht werden können.
    logged_in = Signal(str)                    # Profil-/Account-Name
    # Grund (Anzeige im UI) + ANLASS aus den LOGIN_*-Konstanten oben. Der Anlass ist
    # nachgerüstet, weil das UI die drei Fälle verschieden behandeln muss
    # (Willkommensdialog / Ablauf-Popup / kommentarlos) und der Grundtext
    # dafür eine untaugliche Grundlage ist: Er ist für Menschen
    # geschrieben und ändert sich mit jeder Umformulierung.
    login_required = Signal(str, str)          # Grund, Anlass
    leagues_loaded = Signal(object)            # list[str]
    characters_loaded = Signal(object)         # list[Character]
    stash_list_loaded = Signal(object, bool)   # list[StashTab], silent
    stash_items_loaded = Signal(str, str, str, object, bool)  # league, stash_id, name, list[Item], silent
    stash_children_loaded = Signal(str, str, str, object, bool)  # league, stash_id, name, list[StashTab], silent
    character_items_loaded = Signal(str, object, bool)  # Charaktername, list[Item], silent
    # Level/Erfahrung desselben Charakters, aus DERSELBEN Antwort wie oben
    # (Peter, 2026-08-10: XP/h-Anzeige) — eigenes Signal statt das obige zu
    # erweitern, damit die bestehenden Verwerter von ``character_items_loaded``
    # unangetastet bleiben.
    # ``qlonglong`` (64 Bit) statt ``int`` für die Erfahrung: Qts ``int``
    # ist 32-bittig und endet bei 2.147.483.647. In PoE wird dieser Wert
    # mitten in Stufe 91 überschritten (Stufe 100 sind 4.250.334.444) —
    # ab da warf ``emit`` einen OverflowError, das Signal kam nie an, und
    # die XP-Anzeige blieb auf ihrem letzten Stand stehen, während im
    # Terminal alle paar Sekunden eine Shiboken-Warnung auflief
    # (Peters Log vom 2026-08-16, 11:06:57, bei 2.151.302.311).
    character_snapshot_loaded = Signal(str, int, "qlonglong")  # Name, level, experience
    icon_loaded = Signal(str, object)          # url, bytes
    rate_limit_changed = Signal(str, object, float)  # policy, rules, wait_s
    job_error = Signal(str)                    # Fehlertext für die Statusbar
    # Ein Fach, das GGG mit 404 beantwortet: Liga, Fach-Id, Text für die
    # Statusleiste (leer bei einem stillen Hintergrund-Abruf). Ein eigenes
    # Signal statt eines Fehlertexts, weil der Empfänger es sich merken
    # MUSS: Ohne Ausschluss aus dem Rundlauf wählt ``_pick_auto_refresh_
    # candidate`` dasselbe Fach bei jedem Takt erneut (§4.50). Und bewusst
    # NICHT zusätzlich ``job_error`` — beide Empfänger geben die Kette des
    # taktenden Modus frei, zweimal freigeben verschluckt einen Takt.
    stash_missing = Signal(str, str, str)
    status = Signal(str)                       # Verlaufstext ("Lade …"), nicht der Busy-Zustand
    busy_changed = Signal(bool)                # True, solange irgendein Job läuft (für den UI-Spinner)
    bulk_progress = Signal(object)             # BulkProgress, siehe _fetch_all_items
    bulk_finished = Signal(int, int)           # success_count, total
    offline_changed = Signal(bool)             # True, solange GGG nicht erreichbar ist (§4.12)
    prices_loaded = Signal(str, object)        # league, PriceIndex
    poe2_probe_loaded = Signal(object)         # poe2_probe.Probe

    def __init__(self) -> None:
        super().__init__()
        self._jobs: queue.Queue = queue.Queue()
        self._cancel_bulk = threading.Event()
        self._offline = False
        # Vom MainWindow gesetzt, sobald feststeht, ob eine andere Instanz
        # dieses Konto bewirtschaftet (§_skip_read_only). Ein einfaches
        # Attribut genügt: Ein bool-Zuweisung ist in CPython unteilbar, und
        # ein Takt Verzögerung beim Umschalten ist folgenlos — im
        # schlimmsten Fall läuft ein bereits eingereihter Job noch durch.
        self.read_only = False
        # Callback der Qt-freien API-Schicht → Qt-Signal (Schichtengrenze).
        self.rate_limiter = RateLimitManager(status_callback=self._on_rate_limit)
        self.client = PoeApiClient(self.rate_limiter)
        # Eigener, persistenter Client für poe.ninja — andere Basis-URL,
        # kein Auth, keine Rate-Limit-Kopplung zur GGG-API.
        self._ninja_http = httpx.Client(timeout=20.0, headers={
            "User-Agent": "PoE-VIEW2-price-lookup (+https://github.com/peterm2024/PoE-VIEW2)",
        })

    # Von außen (Main-Thread) aufrufen:
    def submit(self, job) -> None:
        self._jobs.put(job)

    def stop(self) -> None:
        self._jobs.put(_StopJob())

    def cancel_bulk(self) -> None:
        """Bricht ein laufendes FetchAllItemsJob nach dem aktuellen Tab ab."""
        self._cancel_bulk.set()

    # ------------------------------------------------------------------ #

    def run(self) -> None:  # läuft im Worker-Thread
        while True:
            job = self._jobs.get()
            if isinstance(job, _StopJob):
                break
            if self._skip_unauthenticated(job) or self._skip_read_only(job):
                continue
            self.busy_changed.emit(True)
            try:
                self._dispatch(job)
            except AuthError as exc:
                # Ein gespeichertes Token nur verwerfen, wenn wir es
                # tatsächlich mitgeschickt haben — nur dann ist der 401 ein
                # Urteil ÜBER dieses Token. Ohne gesetztes Token ist der 401
                # selbstverschuldet; ein delete_token() würde dann ein evtl.
                # völlig intaktes Token vernichten (FALLSTRICKE #35).
                if self.client.has_token:
                    token_store.delete_token()
                self.login_required.emit(str(exc), LOGIN_EXPIRED)
            except Exception as exc:  # noqa: BLE001 — Worker darf nie sterben
                if _is_connectivity_issue(exc):
                    if _is_maintenance_bad_request(exc):
                        # Eine Zeile statt eines Tracebacks, aber nicht
                        # schweigen: Der Statuscode steht ohnehin in
                        # httpx' Log, GGGs Begründung nicht — und genau
                        # die hat den Fall aufgeklärt.
                        log.info("GGG antwortet auf %s mit HTTP 400 (%r) — als Wartung "
                                 "gewertet, siehe ARCHITEKTUR.md §4.12",
                                 type(job).__name__, exc.error_message)
                    self._set_offline(True)
                    # Hintergrund-Auto-Refresh (silent) soll bei anhaltender
                    # GGG-Wartung nicht alle paar Sekunden den Status-Text
                    # überschreiben — das würde das Offline-Banner (MainWindow)
                    # ständig verdecken. Manuelle Klicks bekommen die Meldung.
                    if not getattr(job, "silent", False):
                        self.job_error.emit(OFFLINE_MESSAGE)
                elif _is_missing_stash(job, exc):
                    # Kein Programmfehler, sondern GGGs Antwort auf ein Fach,
                    # das es serverseitig (noch) nicht gibt — deshalb eine
                    # Zeile statt eines Tracebacks. Der Empfänger nimmt es
                    # aus dem Rundlauf, sonst käme es bei jedem Takt wieder.
                    log.warning("Fach %r (%s) gibt es bei GGG nicht (HTTP 404) — "
                                "aus dem Rundlauf genommen, siehe ARCHITEKTUR.md §4.50",
                                job.stash_name, job.stash_id)
                    self.stash_missing.emit(
                        job.league, job.stash_id,
                        "" if job.silent
                        else f"{job.stash_name}: GGG does not have this tab")
                else:
                    log.exception("Job %s fehlgeschlagen", type(job).__name__)
                    self.job_error.emit(f"{type(job).__name__}: {exc}")
            else:
                self._set_offline(False)
            finally:
                self.busy_changed.emit(False)
        self.client.close()
        self._ninja_http.close()

    # Jobs, die ohne gültiges Token garantiert einen 401 kassieren. Bootstrap
    # und Login stellen die Authentifizierung selbst her, Logout und der
    # Icon-Download (CDN, ohne Auth-Header) brauchen sie nicht.
    _NEEDS_AUTH = (FetchLeaguesJob, FetchCharactersJob, FetchStashListJob,
                   FetchStashItemsJob, FetchCharacterItemsJob, FetchAllItemsJob,
                   Poe2ProbeJob)

    def _skip_unauthenticated(self, job) -> bool:
        """Verwirft Daten-Jobs, solange kein Token gesetzt ist.

        Beim Programmstart landet der ``BootstrapJob`` zwar zuerst in der
        Queue (FALLSTRICKE #30), aber die von ``_build_ui()`` mit
        eingereihten Daten-Jobs laufen trotzdem — auch dann, wenn Bootstrap
        gar kein gültiges Token gefunden hat. Sie gingen dadurch ohne
        Authorization-Header raus und kassierten einen sicheren 401. Real
        beobachtet: bei 42 von 58 Programmstarts genau ein solcher 401,
        jeweils 0,7s nach dem Laden des Daten-Caches (FALLSTRICKE #35).
        """
        if not isinstance(job, self._NEEDS_AUTH) or self.client.has_token:
            return False
        log.info("%s übersprungen — noch nicht angemeldet.", type(job).__name__)
        return True

    def _skip_read_only(self, job) -> bool:
        """Verwirft Daten-Jobs, solange eine ANDERE Instanz dieses Konto
        bewirtschaftet (Peter, 2026-08-05: "Ich will nicht, dass beide
        gleichzeitig Daten refreshen und dann beide versuchen den neuen
        Inhalt zu schreiben", §services/instance_lock.py).

        Bewusst hier und nicht in der Oberfläche. Daten-Jobs entstehen an
        einem knappen Dutzend Stellen — Auto-Refresh, Single-/Stash-Takt,
        Zonenwechsel, Klick auf ein ungeladenes Fach, Klick auf einen
        Charakter, "Load All Tabs", der manuelle Refresh-Knopf. Jede davon
        einzeln abzusichern hieße, sich auf Vollständigkeit zu verlassen,
        und die nächste neue Stelle fiele durch. Dieselbe Überlegung wie
        beim Überschreibschutz in ``_persist_cache`` (FALLSTRICKE #62):
        Ein Wächter, der den Weg nicht kennt, deckt auch die Wege ab, die
        es noch nicht gibt. Die Knöpfe in der Oberfläche werden trotzdem
        gesperrt — aber nur, damit niemand ins Leere klickt, nicht als
        Schutz.

        Nicht betroffen: Bootstrap (der Kontoname MUSS ermittelt werden,
        sonst wüsste die Instanz nie, ob sie das Konto vielleicht doch
        beanspruchen darf), Logout, Icons vom CDN und die poe.ninja-Preise
        — nichts davon läuft über GGGs Rate-Limit-Budget für dieses Konto,
        und der Preis-Cache verträgt zwei Schreiber (§atomic_json)."""
        if not self.read_only or not isinstance(job, self._NEEDS_AUTH):
            return False
        log.info("%s übersprungen — dieses Konto wird von einer anderen "
                "Instanz bewirtschaftet.", type(job).__name__)
        return True

    def _set_offline(self, offline: bool) -> None:
        if offline != self._offline:
            self._offline = offline
            self.offline_changed.emit(offline)

    def _dispatch(self, job) -> None:
        """Cases mit eigenem Abschlusstext (z. B. stash_items_loaded) emittieren
        bewusst kein "Bereit" — Signale sind FIFO, es käme als Letztes an und
        würde die spezifischere Meldung sofort überschreiben."""
        match job:
            case BootstrapJob():
                self._bootstrap()
            case LoginJob():
                self._login()
            case LogoutJob():
                token_store.delete_token()
                self.login_required.emit("Logged out.", LOGIN_LOGGED_OUT)
            case FetchLeaguesJob():
                self.status.emit("Loading leagues…")
                self.leagues_loaded.emit(self.client.get_leagues())
                self.status.emit("Ready")
            case FetchCharactersJob():
                self.status.emit("Loading characters…")
                self.characters_loaded.emit(self.client.get_characters())
                self.status.emit("Ready")
            case FetchStashListJob(league=league, silent=silent):
                if not silent:
                    self.status.emit(f"Loading stash list ({league})…")
                self.stash_list_loaded.emit(self.client.get_stashes(league), silent)
                if not silent:
                    self.status.emit("Ready")
            case FetchStashItemsJob(league=league, stash_id=sid, stash_name=name,
                                    parent_id=parent_id, silent=silent):
                if not silent:
                    self.status.emit(f"Loading items: {name}…")
                stash = self.client.get_stash(league, sid, parent_id)
                self._emit_stash_result(league, sid, name, stash, silent)
            case FetchCharacterItemsJob(name=name, silent=silent):
                if not silent:
                    self.status.emit(f"Loading equipment: {name}…")
                level, experience, items = self.client.get_character_items(name)
                self.character_items_loaded.emit(name, items, silent)
                self.character_snapshot_loaded.emit(name, level, experience)
                if not silent:
                    self.status.emit("Ready")
            case FetchIconJob(url=url):
                self._fetch_icon(url)
            case FetchAllItemsJob(league=league, stashes=stashes, positions=positions):
                self.status.emit(f"Loading all tabs ({league})…")
                self._fetch_all_items(league, stashes, positions)
            case Poe2ProbeJob():
                self.status.emit("Querying the PoE2 realm…")
                self.poe2_probe_loaded.emit(self._poe2_probe())
                self.status.emit("Ready")
            case FetchPricesJob(league=league):
                # Kein Status-Text: läuft meist unauffällig im Hintergrund
                # bei einem Liga-Wechsel, soll keine relevantere Meldung
                # (z. B. "Loading stash list…") überschreiben.
                index = ninja.fetch_price_index(league, self._ninja_http)
                self.prices_loaded.emit(league, index)

    # ------------------------------------------------------------------ #

    def _bootstrap(self) -> None:
        token = token_store.load_token()
        if not token_store.is_valid(token):
            # Grund mitprotokollieren (nie das Token selbst): "gar keins
            # gespeichert" und "gespeichert, aber abgelaufen" haben völlig
            # verschiedene Ursachen, und ohne diese Unterscheidung ließ sich
            # nicht klären, warum ein Token zwischen zwei Starts verschwand
            # (FALLSTRICKE #35).
            if token is None:
                log.info("Bootstrap: kein Token im Credential Manager.")
            else:
                age_h = (time.time() - float(token.get("obtained_at", 0))) / 3600
                log.info("Bootstrap: Token verworfen — vor %.1f h geholt, "
                         "expires_in=%s s.", age_h, token.get("expires_in"))
            self.login_required.emit("No valid token — please log in.", LOGIN_NO_TOKEN)
            return
        self.client.set_token(token["access_token"])
        self._after_auth()

    def _login(self) -> None:
        self.status.emit("Waiting for login in the browser…")
        token = oauth.run_login_flow()
        token_store.save_token(token)
        self.client.set_token(token["access_token"])
        self._after_auth()

    def _after_auth(self) -> None:
        profile = self.client.get_profile()
        self.logged_in.emit(profile.get("name", "?"))

    def _fetch_icon(self, url: str) -> None:
        data = icon_cache.load(url)
        if data is None:
            # CDN-Download ohne Auth-Header; eigener kurzer Client reicht,
            # die Icon-Last ist klein und läuft ohnehin sequenziell hier.
            resp = httpx.get(url, headers={"User-Agent": config.user_agent()},
                             timeout=30.0, follow_redirects=True)
            if resp.status_code != 200:
                return
            data = resp.content
            icon_cache.save(url, data)
        self.icon_loaded.emit(url, data)

    def _poe2_probe(self) -> poe2_probe.Probe:
        """Fragt die Endpunkte ab, die laut GGGs Referenz ``realm=poe2``
        annehmen — jeweils mit Kontrollabruf (§4.43).

        Die Kontrollen sind der eigentliche Inhalt. Peter hat den ersten
        Abzug angesehen und sofort gesehen, was mir entgangen war: "Das
        sind anscheinend alles Daten von PoE1." Ein Abzug, der nur nach
        ``poe2`` fragt, kann das nicht auseinanderhalten — er zeigt
        PoE1-Daten unter einer PoE2-Überschrift. Deshalb dieselbe Frage
        dreimal: ohne Realm, mit ``poe2``, mit einem erfundenen Wert.
        Sind alle drei bytegleich, wertet GGG den Parameter nicht aus,
        und das ist die Antwort.

        Den Charakter im Detail gibt es nur, wenn der Realm etwas
        verändert hat. Sonst wäre es ein PoE1-Charakter im PoE2-Abzug —
        ein Rate-Limit-Abruf für eine Antwort, die in die Irre führt.

        Fehlschläge landen im Ergebnis statt im Offline-Zustand: Ein 403
        oder 400 ist hier eine Messung. Nur ``AuthError`` fliegt weiter,
        damit ein wirklich totes Token wie überall sonst den Login
        anstößt statt still im Abzug zu verschwinden."""
        probe = poe2_probe.Probe(fetched_at=time.time())
        realm = poe2_probe.REALM
        ungueltig = poe2_probe.INVALID_REALM
        probe.calls.append(self._probe_call(
            "GET /character  (control, no realm)", poe2_probe.PLAIN,
            lambda: self.client.get_characters_raw()))
        probe.calls.append(self._probe_call(
            f"GET /character?realm={realm}", poe2_probe.POE2,
            lambda: self.client.get_characters_raw(realm)))
        probe.calls.append(self._probe_call(
            f"GET /character?realm={ungueltig}  (control, invented realm)",
            poe2_probe.INVALID,
            lambda: self.client.get_characters_raw(ungueltig)))
        probe.calls.append(self._probe_call(
            f"GET /account/leagues?realm={realm}", poe2_probe.LEAGUES,
            lambda: self.client.get_leagues_raw(realm)))
        if poe2_probe.realm_had_effect(probe.calls):
            for name in poe2_probe.character_names(probe.calls)[:1]:
                probe.calls.append(self._probe_call(
                    f"GET /character/{name}?realm={realm}", poe2_probe.DETAIL,
                    lambda n=name: self.client.get_character_raw(n, realm)))
        else:
            log.info("PoE2-Abzug: realm ohne Wirkung, Charakter-Detail "
                     "uebersprungen (§4.43)")
        return probe

    @staticmethod
    def _probe_call(label: str, role: str, call) -> poe2_probe.ProbeCall:
        try:
            data = call()
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001 — der Fehler IST das Ergebnis
            log.info("PoE2-Abzug: %s → %s: %s", label, type(exc).__name__, exc)
            return poe2_probe.ProbeCall(label, False, role=role,
                                        error=f"{type(exc).__name__}: {exc}")
        return poe2_probe.ProbeCall(label, True, data, role=role,
                                    digest=poe2_probe.digest_of(data))

    def _emit_stash_result(self, league: str, stash_id: str, name: str,
                           stash: StashTab, silent: bool) -> None:
        """Spezial-Tabs (MapStash, UniqueStash) antworten mit children statt items —
        beides läuft über unterschiedliche Signale zurück an die UI."""
        if stash.children and not stash.items:
            for child in stash.children:
                child.parent = child.parent or stash_id  # für den Substash-Endpunkt
            self.stash_children_loaded.emit(league, stash_id, name, stash.children, silent)
        else:
            self.stash_items_loaded.emit(league, stash_id, name, stash.items, silent)

    def _fetch_all_items(self, league: str, stashes: list[StashTab],
                         positions: dict[str, int]) -> None:
        """Holt Items Tab für Tab; ein fehlschlagender Tab bricht die anderen nicht ab.

        Läuft im GLEICHMÄSSIGEN Takt aus ``steady_pace_interval_s()`` — also
        derselben Rate wie der Stash-Refresh-Modus (bei 30 Anfragen/300s rund
        11s je Tab), nur einmal durch alle Fächer statt endlos. Ohne diese
        Bremse feuerte die Schleife die Tabs so schnell wie möglich durch,
        füllte damit binnen ~29 Tabs das Rate-Limit-Fenster und lief in die
        300-Sekunden-Zwangspause (dieselbe Mechanik wie FALLSTRICKE #34).
        Der Durchsatz ist dadurch nicht kleiner — nur gleichmäßig statt
        "Sprint, dann fünf Minuten Stillstand", und der Fortschrittsbalken
        läuft sichtbar weiter.

        Gewartet wird über ``_cancel_bulk.wait(...)`` statt ``time.sleep``:
        ein Klick auf "Abbrechen" greift dadurch sofort und muss nicht erst
        den laufenden Takt aussitzen.

        Fortschritt wird in ZWEI Einheiten gemeldet, weil beide gebraucht
        werden und keine allein genügt (FALLSTRICKE #37, #42):

        - ``done_requests``/``total_requests``: die tatsächlichen Abrufe.
          Nur diese Zahl wächst bei JEDEM Schritt und taugt deshalb für
          Balken und Restzeit.
        - ``done_slots``/``total_slots``: echte Truhenplätze. Map-/
          Unique-Sektionen teilen sich den Platz ihres Eltern-Tabs; diese
          Zahl beantwortet "wie viele meiner Fächer sind durch", steht
          dafür aber bei einem großen Spezial-Tab lange still (real
          gemessen: 365 Sektionen auf einem Platz = 67 Minuten).

        Dazu kommen ``remaining_s`` (Restzeit des ganzen Laufs) und
        ``next_wait_s`` (Taktpause bis zum nächsten Abruf) — Letzteres,
        damit die UI die ~11s zwischen zwei Ticks als Countdown zeigen kann
        statt scheinbar stillzustehen. Alles zusammen in ``BulkProgress``.
        """
        self._cancel_bulk.clear()
        total_slots = len({positions.get(s.id, s.id) for s in stashes})
        total_requests = len(stashes)
        done_slots: set[str | int] = set()
        success_slots: set[str | int] = set()
        policy: str | None = None
        started_at = time.monotonic()
        done_requests = 0
        for i, stash in enumerate(stashes, start=1):
            # Vor dem ERSTEN Tab nicht warten; danach je einen Takt — der
            # Policy-Name stammt aus dem eigenen letzten Request, nicht aus
            # dem globalen Stand (§steady_pace_interval_s, FALLSTRICKE #33).
            cancelled = (self._cancel_bulk.wait(self.rate_limiter.steady_pace_interval_s(policy))
                         if i > 1 else self._cancel_bulk.is_set())
            if cancelled:
                log.info("Bulk-Laden abgebrochen nach %d/%d Abrufen (%d/%d Truhenplätzen)",
                         done_requests, total_requests, len(done_slots), total_slots)
                break
            slot = positions.get(stash.id, stash.id)
            try:
                fetched = self.client.get_stash(league, stash.id, stash.parent)
                policy = self.rate_limiter.last_policy
                self._emit_stash_result(league, stash.id, stash.name, fetched, silent=False)
                success_slots.add(slot)
            except Exception:
                log.exception("Bulk-Laden: Tab %s fehlgeschlagen", stash.name)
            done_slots.add(slot)
            done_requests += 1
            # Restzeit über den SCHLECHTEREN von Soll-Takt und gemessener
            # Rate. Reines elapsed/done wäre am Anfang grob zu optimistisch,
            # weil der erste Abruf ohne Taktpause läuft (bei 1088 Abrufen:
            # "etwa 5 min" statt der realen ~3 h). Der Soll-Takt trägt vom
            # ersten Tick an, die Messung übernimmt, sobald Rate-Limit-
            # Zwangspausen die Sache tatsächlich verschlechtert haben.
            elapsed = time.monotonic() - started_at
            pace_s = self.rate_limiter.steady_pace_interval_s(policy)
            per_request = max(pace_s, elapsed / done_requests)
            remaining_s = per_request * (total_requests - done_requests)
            # ``next_wait_s`` ist genau die Pause, die die nächste
            # Schleifenrunde oben abwartet — die UI kann sie deshalb als
            # sekundengenauen Countdown anzeigen, statt zwischen zwei Ticks
            # elf Sekunden lang scheinbar stillzustehen. Nach dem letzten
            # Abruf wartet niemand mehr, also 0.
            next_wait_s = pace_s if done_requests < total_requests else 0.0
            self.bulk_progress.emit(BulkProgress(
                done_requests=done_requests, total_requests=total_requests,
                done_slots=len(done_slots), total_slots=total_slots,
                name=stash.name, stash_id=stash.id,
                remaining_s=remaining_s, next_wait_s=next_wait_s))
        self.bulk_finished.emit(len(success_slots), total_slots)

    def _on_rate_limit(self, policy: str, rules: list[dict], wait_s: float) -> None:
        """Läuft im Worker-Thread; Signal-Emission ist threadsicher (queued)."""
        self.rate_limit_changed.emit(policy, rules, wait_s)
