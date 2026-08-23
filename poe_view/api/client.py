"""PoeApiClient: persistente HTTP-Session + Endpunkte (docs/ARCHITEKTUR.md §4.2).

Jeder Request läuft durch ``_get``: Rate-Limit-Check davor, State-Update
danach. Kein Endpunkt kann das umgehen.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote, urlencode

import httpx

from poe_view import config
from poe_view.api.models import Character, Item, StashTab
from poe_view.api.rate_limiter import RateLimitManager

log = logging.getLogger(__name__)


class AuthError(Exception):
    """Token fehlt/abgelaufen (HTTP 401) — UI soll den Login anbieten."""


class ApiError(Exception):
    """Sonstiger API-Fehler mit Status und Kurztext.

    ``status_code`` liegt offen, damit der Worker 5xx-Antworten (GGG-Wartung,
    Serverfehler) von echten Client-Fehlern (4xx) unterscheiden kann —
    Letztere sind kein Offline-Zustand, Erstere schon (§4.12).

    ``error_code``/``error_message`` tragen GGGs eigenen Fehler-Umschlag
    (``{"error": {"code": 2, "message": "Invalid query; League not
    found"}}``) getrennt daneben. Bis zum 2026-08-13 steckte er nur als
    Text in der Meldung; seit der Wartung an jenem Morgen ist er eine
    Entscheidungsgrundlage: GGG beantwortet dieselbe Wartung je nach
    Endpunkt mit 503 ODER mit einem 400, dessen Status allein in die Irre
    führt (§4.12)."""

    def __init__(self, status_code: int, message: str, *,
                 error_code: int | None = None, error_message: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_message = error_message


def _ggg_error_fields(resp: httpx.Response) -> dict:
    """GGGs Fehler-Umschlag aus der Antwort holen, soweit vorhanden.

    Bewusst wegwerfend: Bei Wartung kommt auch mal eine HTML-Seite statt
    JSON zurück, und eine Fehlerbehandlung, die selbst scheitern kann,
    verdeckt genau den Fehler, den sie beschreiben soll."""
    try:
        error = resp.json().get("error")
    except Exception:  # noqa: BLE001 — jede Antwort ohne JSON-Objekt
        return {}
    if not isinstance(error, dict):
        return {}
    return {"error_code": error.get("code"),
            "error_message": str(error.get("message", ""))}


def _target(path: str, params: dict[str, str] | None) -> str:
    """Pfad samt Query für Log- und Fehlertexte.

    Ohne die Query stünde in der Meldung nur ``/character`` — bei der
    PoE2-Abfrage (``?realm=poe2``, §services/poe2_probe.py) ist aber
    genau der Parameter die Aussage, und ein Fehler ohne ihn wäre nicht
    von einem gewöhnlichen PoE1-Fehler zu unterscheiden."""
    if not params:
        return path
    return f"{path}?{urlencode(params)}"


# Die Felder der Charakter-Antwort, die dieses Programm ausliest. Alles
# andere landet einmal je Sitzung als "ungenutzt" im Log
# (``_log_character_fields``) — wir heben die Rohantwort nirgends auf,
# also wäre sonst nicht zu sehen, was GGG sonst noch mitschickt.
_USED_CHARACTER_FIELDS = frozenset({
    "equipment", "inventory", "jewels", "rucksack", "level", "experience",
})


# Was am 2026-08-24 tatsächlich in der Antwort stand, gemessen an einem
# echten Charakter — verschachtelte Felder mit ihrem Elternfeld davor.
# Alles, was hier NICHT steht, meldet ``_log_character_fields`` als neu.
# Der Sinn ist die Warnung nach einem GGG-Patch oder Liga-Start: Ein neues
# Feld ist der Moment, in dem sich nachsehen lohnt (so ist die XP/h-Anzeige
# entstanden, §4.33). Ein Fehlalarm heißt hier nur "das hatten wir noch
# nicht" — etwa ein Feld, das es in Peters Liga nicht gibt.
_KNOWN_CHARACTER_FIELDS = frozenset({
    "class", "equipment", "experience", "id", "inventory", "jewels",
    "league", "level", "metadata", "name", "passives", "realm", "rucksack",
    "ruthless",
    "metadata.version",
    "passives.bandit_choice", "passives.hashes", "passives.hashes_ex",
    "passives.jewel_data", "passives.mastery_effects",
    "passives.pantheon_major", "passives.pantheon_minor",
    "passives.skill_overrides",
})


def _field_names(char: dict) -> list[str]:
    """Feldnamen eine Ebene tief: ``level``, ``passives.hashes``.

    Eine Ebene, nicht beliebig tief: Gold oder Ähnliches stünde entweder
    oben oder in einem der wenigen Objekte daneben. Der Inhalt von
    ``equipment`` dagegen sind Items, deren Felder wir längst kennen —
    die vollständig abzulaufen brächte nichts als Rauschen."""
    namen = []
    for schluessel, wert in char.items():
        namen.append(schluessel)
        if isinstance(wert, dict):
            namen.extend(f"{schluessel}.{unter}" for unter in wert)
    return namen


def _field_shape(wert: object) -> str:
    """Ein Feld in einem Wort: ``inventory[12]``, ``metadata{version}``,
    ``level``. Werte werden bewusst NICHT mitgeschrieben — die Zeile soll
    zeigen, was es gibt, und nicht den halben Charakter ins Log kippen."""
    if isinstance(wert, dict):
        return "{" + ",".join(sorted(wert)) + "}" if wert else "{}"
    if isinstance(wert, list):
        return f"[{len(wert)}]"
    return ""


class PoeApiClient:
    def __init__(self, rate_limiter: RateLimitManager, access_token: str | None = None) -> None:
        self.rate_limiter = rate_limiter
        # Einmal je Sitzung schreibt ``_log_character_fields`` die Felder
        # der Charakter-Antwort mit.
        self._character_fields_logged = False
        self._http = httpx.Client(
            base_url=config.API_BASE,
            headers={"User-Agent": config.user_agent()},
            timeout=30.0,
        )
        if access_token:
            self.set_token(access_token)

    def set_token(self, access_token: str) -> None:
        self._http.headers["Authorization"] = f"Bearer {access_token}"

    @property
    def has_token(self) -> bool:
        """Ist überhaupt ein Token gesetzt? Ein 401 OHNE gesetztes Token sagt
        nichts über die Gültigkeit des gespeicherten Tokens aus — er ist
        selbstverschuldet (§ApiWorker.run)."""
        return "Authorization" in self._http.headers

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ #

    def _get(self, path: str, policy_hint: str | None = None,
             params: dict[str, str] | None = None) -> dict:
        """Zentraler GET mit Rate-Limit-Schleife und einmaligem 429-Retry."""
        self.rate_limiter.check_and_wait(policy_hint)
        resp = self._http.get(path, params=params)
        self.rate_limiter.update_from_headers(resp.headers)

        if resp.status_code == 429:
            # Sollte durch check_and_wait nie passieren → Parser-Lücke loggen,
            # Retry-After respektieren, genau EIN Wiederholungsversuch.
            retry_after = float(resp.headers.get("Retry-After", "10"))
            self.rate_limiter.register_penalty(retry_after)
            time.sleep(retry_after)
            resp = self._http.get(path, params=params)
            self.rate_limiter.update_from_headers(resp.headers)

        if resp.status_code == 401:
            # Bislang loggten wir hier nur die feste Meldung — real
            # beobachtet: 401 trifft über den Tag verteilt wiederholt
            # NUR den Stash-Listen-Endpunkt (`GET /stash/{league}`), nie
            # einzelne Fächer/Charaktere mit demselben Token, obwohl die
            # weit häufiger laufen. Passt weder zu echtem Token-Ablauf
            # (dann müssten auch die häufigen Aufrufe scheitern) noch zum
            # bekannten Job-Reihenfolge-Bug (FALLSTRICKE #30, träfe nur den
            # Start). Body/Header (keine Secrets — das sind GGGs
            # ANTWORT-Header, nicht unser Authorization-Anfrage-Header)
            # protokollieren, um beim nächsten Auftreten den echten Grund
            # zu sehen statt weiter zu raten.
            log.warning("401 von GGG bei %s — Antwort-Header: %s, Body: %.200s",
                       _target(path, params), dict(resp.headers), resp.text)
            raise AuthError("Not authorized — token expired or missing.")
        if resp.status_code >= 400:
            raise ApiError(resp.status_code,
                           f"HTTP {resp.status_code} for {_target(path, params)}: "
                           f"{resp.text[:200]}",
                           **_ggg_error_fields(resp))
        return resp.json()

    # ------------------------------------------------------------------ #
    # Endpunkte (siehe docs/api-notes/ggg-api.md)                         #
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

    def get_character_items(self, name: str) -> tuple[int, int, list[Item]]:
        """Ausrüstung + Inventar EINES Charakters (Antwort-Key 'character',
        Singular, wie schon bei ``get_stash``). Die Item-Listen 'equipment'/
        'inventory'/'jewels'/'rucksack' entsprechen der offiziell dokumentierten
        GGG-Schema-Beschreibung — anders als die Stash-Endpunkte bislang nicht
        an echten Rohdaten verifiziert (siehe FALLSTRICKE_UND_WORKAROUNDS.md
        #26). Fehlende Listen werden als leer behandelt statt einen Fehler zu
        werfen — einzelne Feld-Abweichungen sollen nicht den ganzen Abruf
        scheitern lassen.

        Liefert zusätzlich ``level``/``experience`` desselben Charakters
        (Peter, 2026-08-10: XP/h-Anzeige) — dieselbe Antwort trägt beide
        Werte neben den Item-Listen, real geprüft an Peters Cache. Bisher
        wurden sie stillschweigend verworfen, obwohl sie bei jedem
        Auto-/Single-Refresh (alle ~13s, solange der Charakter offen ist)
        ohnehin schon ankommen — kein zusätzlicher Request nötig, nur ein
        zusätzliches Auslesen derselben Antwort."""
        data = self._get(f"/character/{quote(name)}")
        char = data.get("character", {})
        self._log_character_fields(name, char)
        items = (char.get("equipment", []) + char.get("inventory", [])
                 + char.get("jewels", []) + char.get("rucksack", []))
        return (char.get("level", 0), char.get("experience", 0),
                [Item.model_validate(i) for i in items])

    def _log_character_fields(self, name: str, char: dict) -> None:
        """Einmal je Sitzung mitschreiben, welche Felder ``/character/{name}``
        überhaupt liefert — und welche davon wir wegwerfen.

        Anlass (Peter, 2026-08-24): "Bekommen wir eigentlich die aktuelle
        Goldmenge angezeigt?" Beantworten ließ sich das nicht. Die
        Rohantwort wird nirgends aufgehoben, hier werden gezielt die
        bekannten Schlüssel herausgelesen, und das Rohdaten-Fenster gibt es
        nur für Truhenfächer. Was GGG sonst noch mitschickt, war damit
        unsichtbar.

        Die Zeile kostet keinen zusätzlichen Request: Der Abruf läuft
        ohnehin alle paar Sekunden, solange ein Charakter offen ist. Genau
        so ist die XP/h-Anzeige entstanden (§4.33) — ``level`` und
        ``experience`` lagen längst in jeder Antwort und wurden
        stillschweigend verworfen."""
        if self._character_fields_logged or not char:
            return
        self._character_fields_logged = True
        felder = [f"{schluessel}{_field_shape(wert)}"
                  for schluessel, wert in sorted(char.items())]
        ungenutzt = sorted(set(char) - _USED_CHARACTER_FIELDS)
        log.info("Charakter-Antwort (%s) trägt: %s — davon ungenutzt: %s",
                 name, ", ".join(felder),
                 ", ".join(ungenutzt) if ungenutzt else "(nichts)")
        neu = sorted(set(_field_names(char)) - _KNOWN_CHARACTER_FIELDS)
        if neu:
            # Eigene Zeile und eine Stufe lauter: Die Liste oben fällt
            # niemandem auf, der nicht ohnehin danach sucht. Genau dieser
            # Fall — GGG liefert plötzlich mehr — ist aber der einzige
            # Grund, warum die Mitschrift dauerhaft drinbleibt.
            log.warning("NEUE Felder in der Charakter-Antwort: %s. Bisher nicht "
                        "gesehen — lohnt einen Blick, ob etwas Brauchbares "
                        "dabei ist (_KNOWN_CHARACTER_FIELDS in api/client.py "
                        "nachziehen).", ", ".join(neu))

    # --- Rohabrufe für einen anderen Realm (PoE2-Abzug, §4.43) --------- #
    #
    # Bewusst neben den typisierten Endpunkten und nicht als Parameter an
    # ihnen: Die pydantic-Modelle sind an PoE1-Antworten gemessen, und ob
    # PoE2 dieselben Felder liefert, ist gerade die Frage, die der Abzug
    # beantworten soll. Ein ``Character.model_validate`` dazwischen würde
    # unbekannte Felder zwar dank ``extra="allow"`` durchlassen, aber bei
    # einem fehlenden Pflichtfeld den Abruf zum Absturz bringen — und
    # damit genau das Messergebnis verschlucken.

    def _realm_params(self, realm: str | None) -> dict[str, str] | None:
        return {"realm": realm} if realm else None

    def get_leagues_raw(self, realm: str | None = None) -> dict:
        return self._get("/account/leagues", params=self._realm_params(realm))

    def get_characters_raw(self, realm: str | None = None) -> dict:
        return self._get("/character", params=self._realm_params(realm))

    def get_character_raw(self, name: str, realm: str | None = None) -> dict:
        return self._get(f"/character/{quote(name)}",
                         params=self._realm_params(realm))

    # ------------------------------------------------------------------ #

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
