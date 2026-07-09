"""ApiWorker: EIN Thread für alle API-Zugriffe (docs/ARCHITEKTUR.md §4.5).

Jobs kommen über eine Queue herein und werden sequenziell abgearbeitet —
Absicht: so bleibt das Rate-Limiting deterministisch und trivial. Ergebnisse
gehen ausschließlich per Qt-Signal zurück an den Main-Thread; die UI fasst
den Client nie direkt an.

LabVIEW-Äquivalent: die Consumer-Loop eines Queued Message Handlers;
die Signale entsprechen User Events an das Main-VI.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

import httpx
from PySide6.QtCore import QThread, Signal

from poe_view import config
from poe_view.api import oauth
from poe_view.api.client import AuthError, PoeApiClient
from poe_view.api.models import StashTab
from poe_view.api.rate_limiter import RateLimitManager
from poe_view.services import icon_cache, token_store

log = logging.getLogger(__name__)


# --------------------------- Job-Typen --------------------------------- #
# ≙ Message-Cluster des QMH. Ein Job = ein Eintrag in der Queue.

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


@dataclass
class FetchStashItemsJob:
    league: str
    stash_id: str
    stash_name: str


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


@dataclass
class _StopJob:
    pass


class ApiWorker(QThread):
    """Arbeitet die Job-Queue ab, bis ``stop()`` gerufen wird."""

    # Signale (≙ User Events). 'object' statt konkreter Typen, damit
    # pydantic-Modelle und Listen unverändert durchgereicht werden können.
    logged_in = Signal(str)                    # Profil-/Account-Name
    login_required = Signal(str)               # Grund (Anzeige im UI)
    leagues_loaded = Signal(object)            # list[str]
    characters_loaded = Signal(object)         # list[Character]
    stash_list_loaded = Signal(object)         # list[StashTab]
    stash_items_loaded = Signal(str, str, object)  # stash_id, name, list[Item]
    icon_loaded = Signal(str, object)          # url, bytes
    rate_limit_changed = Signal(str, object, float)  # policy, rules, wait_s
    job_error = Signal(str)                    # Fehlertext für die Statusbar
    status = Signal(str)                       # Verlaufstext ("Lade …"), NICHT der Busy-Zustand
    busy_changed = Signal(bool)                # True, solange irgendein Job läuft (für den UI-Spinner)
    bulk_progress = Signal(int, int, str)      # done, total, aktueller Tab-Name
    bulk_finished = Signal(int, int)           # success_count, total

    def __init__(self) -> None:
        super().__init__()
        self._jobs: queue.Queue = queue.Queue()
        self._cancel_bulk = threading.Event()
        # Callback der Qt-freien API-Schicht → Qt-Signal (Schichtengrenze).
        self.rate_limiter = RateLimitManager(status_callback=self._on_rate_limit)
        self.client = PoeApiClient(self.rate_limiter)

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
            self.busy_changed.emit(True)
            try:
                self._dispatch(job)
            except AuthError as exc:
                token_store.delete_token()
                self.login_required.emit(str(exc))
            except Exception as exc:  # noqa: BLE001 — Worker darf nie sterben
                log.exception("Job %s fehlgeschlagen", type(job).__name__)
                self.job_error.emit(f"{type(job).__name__}: {exc}")
            finally:
                self.busy_changed.emit(False)
        self.client.close()

    def _dispatch(self, job) -> None:
        """Cases mit eigenem Abschlusstext (z. B. stash_items_loaded) emittieren
        bewusst KEIN "Bereit" — Signale sind FIFO, es käme als Letztes an und
        würde die spezifischere Meldung sofort überschreiben."""
        match job:
            case BootstrapJob():
                self._bootstrap()
            case LoginJob():
                self._login()
            case LogoutJob():
                token_store.delete_token()
                self.login_required.emit("Abgemeldet.")
            case FetchLeaguesJob():
                self.status.emit("Lade Ligen …")
                self.leagues_loaded.emit(self.client.get_leagues())
                self.status.emit("Bereit")
            case FetchCharactersJob():
                self.status.emit("Lade Charaktere …")
                self.characters_loaded.emit(self.client.get_characters())
                self.status.emit("Bereit")
            case FetchStashListJob(league=league):
                self.status.emit(f"Lade Stash-Liste ({league}) …")
                self.stash_list_loaded.emit(self.client.get_stashes(league))
                self.status.emit("Bereit")
            case FetchStashItemsJob(league=league, stash_id=sid, stash_name=name):
                self.status.emit(f"Lade Items: {name} …")
                stash = self.client.get_stash(league, sid)
                self.stash_items_loaded.emit(sid, name, stash.items)
            case FetchIconJob(url=url):
                self._fetch_icon(url)
            case FetchAllItemsJob(league=league, stashes=stashes):
                self.status.emit(f"Lade alle Tabs ({league}) …")
                self._fetch_all_items(league, stashes)

    # ------------------------------------------------------------------ #

    def _bootstrap(self) -> None:
        token = token_store.load_token()
        if not token_store.is_valid(token):
            self.login_required.emit("Kein gültiges Token — bitte einloggen.")
            return
        self.client.set_token(token["access_token"])
        self._after_auth()

    def _login(self) -> None:
        self.status.emit("Warte auf Login im Browser …")
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

    def _fetch_all_items(self, league: str, stashes: list[StashTab]) -> None:
        """Holt Items Tab für Tab; ein fehlschlagender Tab bricht die anderen nicht ab."""
        self._cancel_bulk.clear()
        total = len(stashes)
        success = 0
        for done, stash in enumerate(stashes, start=1):
            if self._cancel_bulk.is_set():
                log.info("Bulk-Laden abgebrochen nach %d/%d Tabs", done - 1, total)
                break
            try:
                fetched = self.client.get_stash(league, stash.id)
                self.stash_items_loaded.emit(stash.id, stash.name, fetched.items)
                success += 1
            except Exception:
                log.exception("Bulk-Laden: Tab %s fehlgeschlagen", stash.name)
            self.bulk_progress.emit(done, total, stash.name)
        self.bulk_finished.emit(success, total)

    def _on_rate_limit(self, policy: str, rules: list[dict], wait_s: float) -> None:
        """Läuft im Worker-Thread; Signal-Emission ist threadsicher (queued)."""
        self.rate_limit_changed.emit(policy, rules, wait_s)
