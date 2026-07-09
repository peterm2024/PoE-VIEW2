"""Rate-Limit-Manager — das Kernsystem (docs/ARCHITEKTUR.md §4.3).

GGG bestraft zu schnelle Anfragen mit HTTP 429 und Temporär-Banns. Dieser
Manager wird VOR jedem Request gefragt (``check_and_wait``) und NACH jedem
Request mit den Response-Headern gefüttert (``update_from_headers``).

Header-Format (Quelle: LabVIEW-Projekt, dort lag auch der historische Bug):
  X-Rate-Limit-Policy:        Name der Policy (z. B. "backend-item-request-limit")
  X-Rate-Limit-Rules:         Liste der Regel-Gruppen (z. B. "Account,Ip")
  X-Rate-Limit-<Rule>:        Regeln     "Max:Fenster_s:Sperre_s[,…]"
  X-Rate-Limit-<Rule>-State:  Verbrauch  "Aktuell:Fenster_s:RestSperre_s[,…]"

Die Zuordnung Regel ↔ State erfolgt über die FENSTERGRÖSSE (Feld 2), nicht
über die Array-Position — genau das war der Mapping-Bug im LabVIEW-Original.

LabVIEW-Äquivalent: FGV mit Cases "Check & Wait" / "Update"; der
``status_callback`` entspricht dem User Event an das Main-VI.
Threadsicherheit via Lock ≙ Nicht-Reentranz der FGV.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping

log = logging.getLogger(__name__)

# Sicherheitsmarge: warten, BEVOR das Limit ganz erreicht ist.
SAFETY_MARGIN = 1

# callback(policy_name, rules_snapshot, wait_remaining_s)
StatusCallback = Callable[[str, list[dict], float], None]


@dataclass
class RateLimitRule:
    """Eine Regel einer Policy (≙ ein Element des FGV-Cluster-Arrays)."""

    rule_group: str        # "Account" oder "Ip"
    max_hits: int          # Max Requests im Fenster
    window_s: int          # Fensterbreite in Sekunden
    lock_s: int            # Strafsperre bei Überschreitung
    current: int = 0       # zuletzt gemeldeter Verbrauch
    active_lock_s: float = 0.0  # Rest-Sperre zum Zeitpunkt des letzten Updates

    def snapshot(self) -> dict:
        """Anzeige-Daten für das UI-Dashboard (bewusst reine Python-Typen)."""
        return {
            "group": self.rule_group,
            "current": self.current,
            "max": self.max_hits,
            "window_s": self.window_s,
            "locked": self.active_lock_s > 0,
        }


@dataclass
class PolicyState:
    """Zustand einer Policy (≙ Shift-Register-Inhalt der FGV)."""

    policy_name: str
    rules: dict[tuple[str, int], RateLimitRule] = field(default_factory=dict)
    last_update: float = 0.0  # Zeitstempel des letzten Header-Updates


class RateLimitManager:
    """Zentrale, threadsichere Instanz — eine pro App (≙ FGV).

    Args:
        status_callback: wird bei jedem Update und im Warte-Countdown
            aufgerufen. Qt-frei; der ApiWorker verdrahtet ihn mit einem Signal.
        now: injizierbare Uhr für Tests (Default: ``time.monotonic``).
    """

    def __init__(self, status_callback: StatusCallback | None = None,
                 now: Callable[[], float] | None = None) -> None:
        self._lock = threading.Lock()
        self._policies: dict[str, PolicyState] = {}
        self._callback = status_callback
        self._now = now or time.monotonic
        self._last_policy: str = ""

    # ------------------------------------------------------------------ #
    # "Check & Wait" — vor jedem Request                                  #
    # ------------------------------------------------------------------ #

    def check_and_wait(self, policy_name: str | None = None) -> float:
        """Blockiert, bis ein Request sicher möglich ist. Gibt Wartezeit zurück.

        Muss im Worker-Thread laufen — ``time.sleep`` hier ist Absicht
        (≙ "Wait (ms)" in der FGV); die UI läuft im Main-Thread weiter.
        """
        name = policy_name or self._last_policy
        total_wait = 0.0
        while True:
            with self._lock:
                wait = self._required_wait(name)
            if wait <= 0:
                break
            total_wait += wait
            log.info("Rate-Limit: warte %.1f s (Policy %s)", wait, name)
            self._countdown(name, wait)
        # Optimistisch mitzählen: der gleich folgende Request belegt einen Slot.
        with self._lock:
            state = self._policies.get(name)
            if state:
                for rule in state.rules.values():
                    rule.current += 1
        self._emit(name, 0.0)
        return total_wait

    def _required_wait(self, policy_name: str) -> float:
        state = self._policies.get(policy_name)
        if state is None:
            return 0.0
        now = self._now()
        elapsed = now - state.last_update
        wait = 0.0
        for rule in state.rules.values():
            if rule.active_lock_s > 0:
                wait = max(wait, rule.active_lock_s - elapsed)
            elif rule.current >= rule.max_hits - SAFETY_MARGIN:
                # Konservativ: volles Fenster seit letztem Update abwarten.
                wait = max(wait, rule.window_s - elapsed)
        if wait > 0:
            return wait
        if elapsed > 0:
            # Fenster abgelaufen → lokale Zähler zurücksetzen; der nächste
            # Response-Header liefert ohnehin den echten Stand.
            for rule in state.rules.values():
                if elapsed >= rule.window_s:
                    rule.current = 0
                    rule.active_lock_s = 0.0
        return 0.0

    def _countdown(self, policy_name: str, wait: float) -> None:
        """In 1-s-Schritten schlafen und dem UI den Countdown melden."""
        remaining = wait
        while remaining > 0:
            self._emit(policy_name, remaining)
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step

    # ------------------------------------------------------------------ #
    # "Update" — nach jedem Request                                       #
    # ------------------------------------------------------------------ #

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Parst die X-Rate-Limit-Header einer Response und speichert den Stand."""
        policy = headers.get("X-Rate-Limit-Policy", "")
        if not policy:
            return  # Endpunkt ohne Rate-Limit (z. B. CDN-Icons)
        rule_groups = [g.strip() for g in headers.get("X-Rate-Limit-Rules", "").split(",") if g.strip()]
        with self._lock:
            state = self._policies.setdefault(policy, PolicyState(policy_name=policy))
            for group in rule_groups:
                self._parse_group(state, group,
                                  headers.get(f"X-Rate-Limit-{group}", ""),
                                  headers.get(f"X-Rate-Limit-{group}-State", ""))
            state.last_update = self._now()
            self._last_policy = policy
        self._emit(policy, 0.0)

    def _parse_group(self, state: PolicyState, group: str,
                     rules_str: str, state_str: str) -> None:
        """Regel- und State-String einer Gruppe parsen und ÜBER DAS FENSTER matchen."""
        # State zuerst indexieren: Fenstergröße → (aktuell, restsperre)
        usage_by_window: dict[int, tuple[int, float]] = {}
        for part in filter(None, (p.strip() for p in state_str.split(","))):
            current, window, lock_rest = (int(x) for x in part.split(":"))
            usage_by_window[window] = (current, float(lock_rest))
        for part in filter(None, (p.strip() for p in rules_str.split(","))):
            max_hits, window, lock_s = (int(x) for x in part.split(":"))
            rule = state.rules.setdefault(
                (group, window),
                RateLimitRule(rule_group=group, max_hits=max_hits,
                              window_s=window, lock_s=lock_s))
            rule.max_hits, rule.lock_s = max_hits, lock_s
            current, lock_rest = usage_by_window.get(window, (rule.current, 0.0))
            rule.current, rule.active_lock_s = current, lock_rest

    # ------------------------------------------------------------------ #

    def headroom_fraction(self) -> float:
        """Wie viel Luft ist über ALLE bekannten Policies hinweg noch frei (1.0 = alles frei)?

        Konservativ: das Minimum über alle Regeln, nicht nur die zuletzt
        benutzte Policy — genutzt vom Hintergrund-Auto-Refresher, damit der
        genug manuelles Budget für den Nutzer übrig lässt (Nutzer-Feedback).
        """
        with self._lock:
            fractions = []
            for state in self._policies.values():
                for rule in state.rules.values():
                    if rule.active_lock_s > 0:
                        return 0.0
                    if rule.max_hits > 0:
                        fractions.append((rule.max_hits - rule.current) / rule.max_hits)
            return min(fractions) if fractions else 1.0

    def register_penalty(self, retry_after_s: float, policy_name: str | None = None) -> None:
        """HTTP 429 trotz Vorsicht: Sperre aus Retry-After übernehmen."""
        name = policy_name or self._last_policy
        with self._lock:
            state = self._policies.setdefault(name, PolicyState(policy_name=name))
            for rule in state.rules.values() or []:
                rule.active_lock_s = max(rule.active_lock_s, retry_after_s)
            state.last_update = self._now()
        log.warning("HTTP 429 erhalten — Sperre %.0f s (Policy %s). "
                    "Bitte prüfen, ob der Parser eine Regel übersieht!", retry_after_s, name)
        self._emit(name, retry_after_s)

    def _emit(self, policy_name: str, wait_remaining: float) -> None:
        if self._callback is None:
            return
        with self._lock:
            state = self._policies.get(policy_name)
            snap = [r.snapshot() for r in state.rules.values()] if state else []
        self._callback(policy_name, snap, wait_remaining)
