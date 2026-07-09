"""PoeApiClient: persistente HTTP-Session + Endpunkte (docs/ARCHITEKTUR.md §4.2).

Jeder Request läuft durch ``_get`` — Rate-Limit-Check davor, State-Update
danach. Kein Endpunkt kann das umgehen.

LabVIEW-Äquivalent: der persistente HTTP-Client-Handle mit festen Headern;
``_get`` ≙ SubVI "HTTP GET wrapped".
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote

import httpx

from poe_view import config
from poe_view.api.models import Character, StashTab
from poe_view.api.rate_limiter import RateLimitManager

log = logging.getLogger(__name__)


class AuthError(Exception):
    """Token fehlt/abgelaufen (HTTP 401) — UI soll den Login anbieten."""


class ApiError(Exception):
    """Sonstiger API-Fehler mit Status und Kurztext."""


class PoeApiClient:
    def __init__(self, rate_limiter: RateLimitManager, access_token: str | None = None) -> None:
        self.rate_limiter = rate_limiter
        self._http = httpx.Client(
            base_url=config.API_BASE,
            headers={"User-Agent": config.user_agent()},
            timeout=30.0,
        )
        if access_token:
            self.set_token(access_token)

    def set_token(self, access_token: str) -> None:
        self._http.headers["Authorization"] = f"Bearer {access_token}"

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ #

    def _get(self, path: str, policy_hint: str | None = None) -> dict:
        """Zentraler GET mit Rate-Limit-Schleife und einmaligem 429-Retry."""
        self.rate_limiter.check_and_wait(policy_hint)
        resp = self._http.get(path)
        self.rate_limiter.update_from_headers(resp.headers)

        if resp.status_code == 429:
            # Sollte durch check_and_wait nie passieren → Parser-Lücke loggen,
            # Retry-After respektieren, genau EIN Wiederholungsversuch.
            retry_after = float(resp.headers.get("Retry-After", "10"))
            self.rate_limiter.register_penalty(retry_after)
            time.sleep(retry_after)
            resp = self._http.get(path)
            self.rate_limiter.update_from_headers(resp.headers)

        if resp.status_code == 401:
            raise AuthError("Nicht autorisiert — Token abgelaufen oder fehlend.")
        if resp.status_code >= 400:
            raise ApiError(f"HTTP {resp.status_code} für {path}: {resp.text[:200]}")
        return resp.json()

    # ------------------------------------------------------------------ #
    # Endpunkte (Pfade erprobt im LabVIEW-Test-VI)                        #
    # ------------------------------------------------------------------ #

    def get_profile(self) -> dict:
        return self._get("/profile")

    def get_leagues(self) -> list[str]:
        """Liga-IDs für das Dropdown (nur die Namen, mehr brauchen wir nicht)."""
        data = self._get("/account/leagues")
        return [entry["id"] for entry in data.get("leagues", [])]

    def get_characters(self) -> list[Character]:
        data = self._get("/character")
        return [Character.model_validate(c) for c in data.get("characters", [])]

    def get_stashes(self, league: str) -> list[StashTab]:
        """Stash-Tab-Liste (ohne Items). Liga-Namen können Leerzeichen enthalten!"""
        data = self._get(f"/stash/{quote(league)}")
        return [StashTab.model_validate(s) for s in data.get("stashes", [])]

    def get_stash(self, league: str, stash_id: str, parent_id: str | None = None) -> StashTab:
        """Einzelner Tab inkl. Items. Antwort-Key ist 'stash' (Singular!).

        ``parent_id`` gesetzt → Substash-Endpunkt (Kind eines Spezial-Tabs wie
        MapStash/UniqueStash): ``/stash/<league>/<parent_id>/<stash_id>``.
        Spezial-Tabs selbst liefern statt items ihre children — der Aufrufer
        (ApiWorker) unterscheidet die beiden Fälle.
        """
        if parent_id:
            path = f"/stash/{quote(league)}/{quote(parent_id)}/{quote(stash_id)}"
        else:
            path = f"/stash/{quote(league)}/{quote(stash_id)}"
        data = self._get(path)
        return StashTab.model_validate(data.get("stash", {}))
