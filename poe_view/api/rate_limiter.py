"""Rate-Limit-Manager (docs/ARCHITEKTUR.md §4.3).

GGG beantwortet zu schnelle Anfragen mit HTTP 429 und temporären Sperren.
Dieser Manager wird vor jedem Request befragt (``check_and_wait``) und
nach jedem Request mit den Response-Headern aktualisiert
(``update_from_headers``).

Header-Format:
  X-Rate-Limit-Policy:        Name der Policy (z. B. "backend-item-request-limit")
  X-Rate-Limit-Rules:         Liste der Regel-Gruppen (z. B. "Account,Ip")
  X-Rate-Limit-<Rule>:        Regeln     "Max:Fenster_s:Sperre_s[,…]"
  X-Rate-Limit-<Rule>-State:  Verbrauch  "Aktuell:Fenster_s:RestSperre_s[,…]"

Die Zuordnung von Regel zu Verbrauch erfolgt über die Fenstergröße
(Feld 2), nicht über die Array-Position. Die Reihenfolge der Einträge ist
zwischen beiden Headern nicht garantiert identisch, siehe
FALLSTRICKE_UND_WORKAROUNDS.md #1.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping

log = logging.getLogger(__name__)

# Sicherheitsmarge: warten, bevor das Limit vollständig erreicht ist.
SAFETY_MARGIN = 1

# Fallback-Takt für steady_pace_interval_s(), solange noch keine echte
# Policy bekannt ist (vor dem ersten Request dieser Session).
DEFAULT_PACING_INTERVAL_S = 20.0

# callback(policy_name, rules_snapshot, wait_remaining_s)
StatusCallback = Callable[[str, list[dict], float], None]


@dataclass
class RateLimitRule:
    """Eine einzelne Regel innerhalb einer Policy."""

    rule_group: str        # "Account" oder "Ip"
    max_hits: int          # Max Requests im Fenster
    window_s: int          # Fensterbreite in Sekunden
    lock_s: int            # Strafsperre bei Überschreitung
    current: int = 0       # zuletzt gemeldeter Verbrauch
    active_lock_s: float = 0.0  # Rest-Sperre zum Zeitpunkt des letzten Updates

    def snapshot(self) -> dict:
        """Anzeige-Daten für das Dashboard, als reine Python-Typen.

        ``current`` ist hier der zuletzt von GGG gemeldete Rohwert; die
        gleitende Alterung für die Anzeige rechnet
        ``PolicyState.display_snapshot`` darüber."""
        return {
            "group": self.rule_group,
            "current": self.current,
            "max": self.max_hits,
            "window_s": self.window_s,
            "locked": self.active_lock_s > 0,
        }


@dataclass
class PolicyState:
    """Aktueller Zustand einer Policy."""

    policy_name: str
    rules: dict[tuple[str, int], RateLimitRule] = field(default_factory=dict)
    last_update: float = 0.0  # Zeitstempel des letzten Header-Updates
    # Zeitpunkte UNSERER eigenen Requests an diese Policy (monotonic), auf
    # das längste Fenster beschnitten — Grundlage der gleitenden
    # Anzeige-Alterung, siehe display_snapshot().
    request_times: list[float] = field(default_factory=list)

    def note_request(self, now: float) -> None:
        """Einen eigenen Request mitschreiben und alte Einträge wegwerfen.
        Aufzuheben ist nur, was ins längste Fenster fällt (bei 30/300s also
        höchstens ~30 Zeitstempel)."""
        self.request_times.append(now)
        longest = max((r.window_s for r in self.rules.values()), default=0)
        cutoff = now - longest
        self.request_times = [t for t in self.request_times if t > cutoff]

    def display_snapshot(self, now: float) -> list[dict]:
        """Anzeige-Stand aller Regeln mit GLEITENDEM Fenster.

        GGG zählt in einem gleitenden Fenster: jeder einzelne Treffer altert
        genau ``window_s`` nach seinem Zeitpunkt heraus, nicht erst das ganze
        Fenster auf einmal. Der gemeldete Rohwert ``rule.current`` steht
        dagegen bis zum nächsten Header still — die Anzeige fror dadurch bei
        z. B. "23/30" minutenlang ein und sprang dann in einem Schritt auf 0
        (Peter, 2026-07-30: "das sollte doch wieder weniger werden, je länger
        ich pausiere").

        Für UNSERE eigenen Requests ist die Alterung exakt bekannt — ihre
        Zeitpunkte stehen in ``request_times``. Sie fallen einzeln heraus,
        im selben Takt, in dem sie entstanden sind: läuft der Stash-Modus
        mit ~11s, tickt die Anzeige auch mit ~11s wieder herunter. Läuft
        das Fenster dagegen noch nicht voll (App gerade gestartet, kürzere
        Historie als ``window_s``), dauert es entsprechend länger bis zum
        ersten Tick — das ist die Realität, kein Hänger.

        Treffer, die wir NICHT selbst gemacht haben (anderes PoE-Tool,
        zweite Instanz, oder alles von vor dem App-Start), kennt nur die
        Summe im Header. Für sie bleibt die einzige mögliche Annahme eine
        gleichmäßige Verteilung übers Fenster, also lineares Abklingen.

        Dazu kommt ``next_free_s``: die Sekunden, bis der nächste belegte
        Platz wieder frei wird — also bis der älteste eigene Treffer aus dem
        Fenster fällt. Ohne diese Angabe wirkt eine ganz normale Phase wie
        ein Hänger: hat die App gerade erst zwölf Anfragen abgesetzt, KANN
        vor Ablauf der ersten 300s nichts frei werden, und der Zähler steht
        minutenlang still (Peter, 2026-07-30). ``None``, wenn wir keinen
        eigenen Treffer im Fenster haben — dann wissen wir es schlicht
        nicht. Liegen zusätzlich fremde/ältere Treffer im Fenster, ist der
        Wert eine OBERGRENZE: die sind älter und werden früher frei.

        Ausschliesslich für die ANZEIGE. Die tatsächliche
        Warte-Entscheidung (``_required_wait``, ``headroom_fraction``,
        ``steady_pace_interval_s``) rechnet unverändert mit dem
        konservativen ``rule.current``: ein dort zu früh gesenkter Zähler
        könnte einen echten HTTP 429 riskieren (FALLSTRICKE #34).
        """
        elapsed = max(0.0, now - self.last_update)
        snapshots = []
        for rule in self.rules.values():
            snap = rule.snapshot()
            snap["next_free_s"] = None
            window = rule.window_s
            if window > 0:
                # Eigene Treffer, die beim letzten Header im Fenster lagen …
                known = sum(1 for t in self.request_times
                            if t > self.last_update - window)
                # … und davon die, die JETZT noch drin sind.
                in_window = [t for t in self.request_times if t > now - window]
                unknown = max(0, rule.current - known)
                unknown_left = unknown * max(0.0, 1 - elapsed / window)
                snap["current"] = min(rule.current,
                                      len(in_window) + round(unknown_left))
                if in_window and snap["current"] > 0:
                    snap["next_free_s"] = max(0.0, min(in_window) + window - now)
            snapshots.append(snap)
        return snapshots


class RateLimitManager:
    """Zentrale, threadsichere Instanz; eine pro Anwendung.

    Args:
        status_callback: wird bei jedem Update und im Warte-Countdown
            aufgerufen. Ohne Qt-Bezug; der ApiWorker verbindet ihn mit einem Signal.
        now: injizierbare Uhr für Tests (Default: ``time.monotonic``).
    """

    def __init__(self, status_callback: StatusCallback | None = None,
                 now: Callable[[], float] | None = None) -> None:
        self._lock = threading.Lock()
        self._policies: dict[str, PolicyState] = {}
        self._callback = status_callback
        self._now = now or time.monotonic
        self._last_policy: str = ""
        # Lebensdauer dieser Instanz = Zeitraum, für den wir eigene
        # Request-Zeitpunkte lückenlos kennen (§window_coverage).
        self._started_at = self._now()

    @property
    def last_policy(self) -> str:
        """Name der zuletzt benutzten Policy — für Aufrufer, die sich den
        Namen zum Zeitpunkt EINES bestimmten (eigenen) Requests merken
        wollen, statt sich später auf den dann evtl. längst durch einen
        ANDEREN, dazwischengefunkten Request überschriebenen globalen
        Stand zu verlassen (siehe ``steady_pace_interval_s``)."""
        with self._lock:
            return self._last_policy

    # ------------------------------------------------------------------ #
    # "Check & Wait" — vor jedem Request                                  #
    # ------------------------------------------------------------------ #

    def check_and_wait(self, policy_name: str | None = None) -> float:
        """Blockiert, bis ein Request sicher möglich ist. Gibt Wartezeit zurück.

        Muss im Worker-Thread laufen. Das ``time.sleep`` hier ist Absicht;
        die UI läuft im Main-Thread unterdessen weiter.
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

    def _decay_expired_rules(self, state: PolicyState) -> None:
        """Setzt Regeln zurück, deren Fenster seit dem letzten Header-Update
        vollständig abgelaufen ist — ohne auf den nächsten echten Request zu
        warten. Sonst bliebe z. B. ``headroom_fraction()`` während einer
        Auto-Refresh-Pause für immer auf dem letzten (veralteten) Stand
        stehen: ohne Request kommt auch kein neuer Header mehr rein, der
        Zähler würde sich sonst nie mehr von selbst erholen (Rückfrage
        "Policy-Statusleiste aktualisiert sich während der Pause nicht")."""
        elapsed = self._now() - state.last_update
        if elapsed <= 0:
            return
        for rule in state.rules.values():
            if elapsed >= rule.window_s:
                rule.current = 0
                rule.active_lock_s = 0.0

    def _required_wait(self, policy_name: str) -> float:
        state = self._policies.get(policy_name)
        if state is None:
            return 0.0
        self._decay_expired_rules(state)
        now = self._now()
        elapsed = now - state.last_update
        wait = 0.0
        for rule in state.rules.values():
            if rule.active_lock_s > 0:
                wait = max(wait, rule.active_lock_s - elapsed)
            elif rule.current >= rule.max_hits - SAFETY_MARGIN:
                # Konservativ: volles Fenster seit letztem Update abwarten.
                wait = max(wait, rule.window_s - elapsed)
        return wait

    def _countdown(self, policy_name: str, wait: float) -> None:
        """In Sekundenschritten schlafen und den Countdown melden."""
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
            # Genau EIN eigener Request hat diese Antwort erzeugt — sein
            # Zeitpunkt trägt die gleitende Anzeige-Alterung
            # (§PolicyState.display_snapshot). Erst NACH _parse_group, damit
            # die Fenstergrößen fürs Beschneiden schon bekannt sind.
            state.note_request(state.last_update)
            self._last_policy = policy
        self._emit(policy, 0.0)

    def _parse_group(self, state: PolicyState, group: str,
                     rules_str: str, state_str: str) -> None:
        """Regel- und State-String einer Gruppe parsen, Zuordnung über die
        Fenstergröße (siehe Modul-Docstring)."""
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
        """Wie viel Luft ist über alle bekannten Policies hinweg noch frei (1.0 = alles frei)?

        Konservativ: das Minimum über alle Regeln, nicht nur die zuletzt
        benutzte Policy — genutzt vom Hintergrund-Auto-Refresher, damit der
        etwas Budget für manuelle Klicks übrig lässt. Zerfällt abgelaufene
        Fenster vorher lokal (§_decay_expired_rules), sonst könnte eine
        Auto-Refresh-Pause sich selbst aufrechterhalten: pausiert → kein
        Request mehr → kein Header-Update mehr → Zähler bleibt für immer
        auf dem alten (veralteten) Stand stehen.
        """
        with self._lock:
            fractions = []
            for state in self._policies.values():
                self._decay_expired_rules(state)
                for rule in state.rules.values():
                    if rule.active_lock_s > 0:
                        return 0.0
                    if rule.max_hits > 0:
                        fractions.append((rule.max_hits - rule.current) / rule.max_hits)
            return min(fractions) if fractions else 1.0

    def steady_pace_interval_s(self, policy_name: str | None = None) -> float:
        """Empfohlener Mindestabstand zwischen Requests für einen
        gleichmäßigen Dauerbetrieb (Single-/Stash-Refresh-Modus, §
        MainWindow._drive_refresh_mode) — die knappste Regel der
        angegebenen (oder sonst zuletzt benutzten) Policy, geteilt auf ihr
        Fenster, damit sie im Dauerbetrieb nie anschlägt.

        ``policy_name`` explizit übergeben, wenn der Aufrufer sich den
        Policy-Namen zum Zeitpunkt SEINES EIGENEN letzten Requests gemerkt
        hat (empfohlen!) — sonst wird ``_last_policy`` verwendet, der
        GLOBALE, von jedem beliebigen Request überschreibbare Stand. Real
        beobachtet: GGG vergibt pro Endpunkt-Art eine eigene Policy, sogar
        für Charakter-Liste (``character-list-request-limit``) und
        Einzelcharakter (``character-request-limit``) getrennt. Verließ
        sich der Single-Modus auf den globalen ``_last_policy``, konnte
        ein dazwischengefunkter Klick auf einen ANDEREN Endpunkt (z. B.
        der normale "Refresh"-Button, der die Charakterliste lädt) dessen
        Policy kurzzeitig einmischen und den Takt verfälschen (35s statt
        der erwarteten ~10s).

        Der Takt muss STRIKT unter der Schwelle bleiben, ab der
        ``_required_wait`` bremst (``current >= max_hits - SAFETY_MARGIN``) —
        also höchstens ``max_hits - SAFETY_MARGIN - 1`` Treffer je Fenster.
        Ein Takt von genau ``window / (max_hits - SAFETY_MARGIN)`` träfe die
        Schwelle im Dauerbetrieb punktgenau und löste dadurch selbst die
        Sperre aus, die er vermeiden soll: real beobachtet bei "30 pro 300s"
        mit exakt 29 Treffern im Fenster und anschließend 289s Zwangspause
        (FALLSTRICKE #34). Mit dem zusätzlichen Abzug bleibt bei 30/300s ein
        Takt von 300/28 ≈ 10.7s. Ohne bekannte Policy (vor dem ersten Request
        dieser Session) gilt ein konservativer Default."""
        with self._lock:
            state = self._policies.get(policy_name or self._last_policy)
            if state is None:
                return DEFAULT_PACING_INTERVAL_S
            self._decay_expired_rules(state)
            intervals = []
            for rule in state.rules.values():
                usable = rule.max_hits - SAFETY_MARGIN - 1
                if usable > 0:
                    intervals.append(rule.window_s / usable)
            return max(intervals) if intervals else DEFAULT_PACING_INTERVAL_S

    def snapshot(self) -> tuple[str, list[dict], float]:
        """Aktueller Anzeige-Stand der zuletzt benutzten Policy, ohne dafür
        einen echten Request auszulösen — fürs periodische UI-Polling
        (MainWindow-Sekundentimer), damit das Rate-Limit-Dashboard auch
        während einer Auto-Refresh-Pause sichtbar mitläuft statt
        einzufrieren, bis der nächste echte Request neue Header liefert."""
        with self._lock:
            state = self._policies.get(self._last_policy)
            if state is None:
                return self._last_policy, [], 0.0
            self._decay_expired_rules(state)
            wait = max((r.active_lock_s for r in state.rules.values()), default=0.0)
            return self._last_policy, state.display_snapshot(self._now()), wait

    def window_coverage(self) -> tuple[float, float]:
        """Wie weit deckt unsere eigene Messung das Rate-Limit-Fenster ab?

        Rückgabe ``(anteil, restsekunden)`` — ``anteil`` 0.0…1.0, ``rest``
        die Sekunden bis zur vollen Abdeckung (0.0, sobald erreicht).

        Hintergrund: GGGs Zähler überlebt unseren Prozess. Direkt nach dem
        Start meldet der Header deshalb Treffer, die eine FRÜHERE Sitzung
        (oder ein anderes Tool) verursacht hat — für die kennen wir keine
        Zeitpunkte und müssen in der Anzeige schätzen
        (§PolicyState.display_snapshot). Sobald diese Instanz aber ein
        volles Fenster lang läuft, kann kein Treffer im Fenster mehr aus
        der Zeit davor stammen: ab da ist die Anzeige exakt.

        Maßgeblich ist das LÄNGSTE Fenster der aktuellen Policy (bei
        "15/15s + 30/300s" also 300s) — das kürzere ist immer vorher fertig.
        Ohne bekannte Policy gibt es noch nichts zu wissen: 0.0.

        Achtung, die Abdeckung sagt nichts über FREMDEN Traffic: läuft
        parallel ein anderes Tool auf demselben Account, bleiben dessen
        Treffer dauerhaft unbekannt, auch bei Abdeckung 1.0.
        """
        with self._lock:
            state = self._policies.get(self._last_policy)
            longest = max((r.window_s for r in state.rules.values()),
                          default=0) if state else 0
            if longest <= 0:
                return 0.0, 0.0
            lifetime = self._now() - self._started_at
            return min(1.0, lifetime / longest), max(0.0, longest - lifetime)

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
            snap = state.display_snapshot(self._now()) if state else []
        self._callback(policy_name, snap, wait_remaining)
