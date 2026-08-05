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

# Anteil der Bremsschwelle, den der gleichmäßige Takt (Single-/Stash-Modus)
# höchstens SELBST belegen darf — der Rest bleibt Reserve für ungetaktete
# Requests (Klicks, Liga-Wechsel, Programmstart). Siehe pacing_blocked().
PACING_FILL_LIMIT = 0.85


def _pacing_budget(rule: "RateLimitRule") -> int:
    """Wie viele Treffer je Fenster der gleichmäßige Takt höchstens
    belegen darf — die EINE Zahl, aus der sowohl der Takt
    (``steady_pace_interval_s``) als auch die Notbremse
    (``pacing_blocked``) abgeleitet werden.

    Bis 2026-08-05 hatten die beiden getrennte Vorstellungen davon: Der
    Takt rechnete mit ``max_hits - SAFETY_MARGIN - 1`` (bei 30/300s also
    28), die Bremse stoppte schon bei ``(max_hits - SAFETY_MARGIN) *
    PACING_FILL_LIMIT`` (24,65). Der Takt zielte damit auf ein Budget,
    das die Bremse gar nicht zuließ — im Dauerbetrieb lief er
    zwangsläufig in seine eigene Bremse. An Peters Log vom 2026-08-04
    nachgerechnet: 26 Abrufe im Fenster vor der Bremse, davon 23 allein
    vom Takt; es blieben 1,6 Abrufe Luft, und drei Zonenwechsel-Refreshs
    kippten es. Ergebnis war eine fünfminütige Zwangspause
    (FALLSTRICKE #64).

    Peters Entscheidung dazu (2026-08-06): "machen wir 15% langsamer" —
    seltenere Zwangspausen sind ihm den längeren Takt wert. Bei 30/300s
    ergibt das 13,0s statt 10,7s nominal.

    Rückgabe bewusst als Bruchzahl: Die Bremse vergleicht direkt gegen
    sie und behält damit exakt ihre bisherige Schwelle (bei 30/300s
    greift sie unverändert ab 25). Der Takt rundet selbst ab und zieht
    noch einen Treffer ab — er soll das Budget im Dauerbetrieb nicht
    ausschöpfen, sondern darunter bleiben.
    """
    return (rule.max_hits - SAFETY_MARGIN) * PACING_FILL_LIMIT


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

    # --- Anzeige-Inferenz: wann sinkt GGGs Zähler das nächste Mal? ------ #
    # Reale Header-Daten (2026-07-30, FALLSTRICKE #45 Runde 6) zeigten: GGG
    # zählt NICHT gleitend pro Treffer, sondern senkt den Zähler in Blöcken
    # von rund window_s/5 Sekunden auf einen Schlag (bei 30 Treffern/300s
    # beobachtet: Sprünge von 4-5 Treffern alle ~60s, exakt was unser
    # ~11s-Takt in einen ~60s-Eimer packt). Frühere Fassungen dieser Klasse
    # versuchten fünf Runden lang, das Altern EXAKT pro Treffer zu simulieren
    # ("next in 2:19" auf die Sekunde) — das Modell war von Anfang an falsch,
    # nicht nur ungenau. Jetzt wird nur noch der GROBE Rhythmus gelernt, mit
    # dem der Zähler tatsächlich sinkt.
    last_drop_at: float = 0.0             # wann zuletzt eine Absenkung beobachtet wurde
    drop_interval_s: float | None = None  # gemessener Abstand zweier Absenkungen

    def observe(self, new_current: int, now: float) -> None:
        """Übernimmt den neu gemeldeten Verbrauch und lernt dabei den Takt,
        in dem GGGs Zähler von sich aus sinkt (siehe Klassen-Kommentar).
        Jede Absenkung — egal wie groß — ist ein Datenpunkt für diesen Takt."""
        if new_current < self.current:
            if self.last_drop_at:
                self.drop_interval_s = now - self.last_drop_at
            self.last_drop_at = now
        self.current = new_current

    def next_free_estimate_s(self, now: float) -> float | None:
        """Grobe Schätzung, wann der Zähler das nächste Mal sinkt.

        Keine Zusage für einen bestimmten EIGENEN Treffer — das würde die
        inzwischen widerlegte Annahme gleitenden Alterns wiederholen (siehe
        FALLSTRICKE #45). Nur der gelernte Rhythmus der Absenkungen selbst.
        ``None``, solange wir noch keine zwei davon beobachtet haben."""
        if not self.drop_interval_s or not self.last_drop_at:
            return None
        return max(0.0, self.last_drop_at + self.drop_interval_s - now)

    def snapshot(self, now: float) -> dict:
        """Anzeige-Daten für das Dashboard, als reine Python-Typen."""
        return {
            "group": self.rule_group,
            "current": self.current,
            "max": self.max_hits,
            "window_s": self.window_s,
            "locked": self.active_lock_s > 0,
            "next_free_s": self.next_free_estimate_s(now),
        }


@dataclass
class PolicyState:
    """Aktueller Zustand einer Policy."""

    policy_name: str
    rules: dict[tuple[str, int], RateLimitRule] = field(default_factory=dict)
    last_update: float = 0.0  # Zeitstempel des letzten Header-Updates


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
        "Policy-Statusleiste aktualisiert sich während der Pause nicht").

        Bewusst ohne ``RateLimitRule.observe()``: dieser Reset ist unsere
        eigene, konservative Annahme (volles Fenster abgelaufen), keine
        tatsächlich beobachtete GGG-Absenkung — er soll den gelernten
        Absenkungs-Takt nicht verfälschen."""
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
            now = self._now()
            for group in rule_groups:
                self._parse_group(state, group,
                                  headers.get(f"X-Rate-Limit-{group}", ""),
                                  headers.get(f"X-Rate-Limit-{group}-State", ""),
                                  now)
            state.last_update = now
            self._last_policy = policy
            self._log_header_detail(policy, state)
        self._emit(policy, 0.0)

    def _log_header_detail(self, policy: str, state: PolicyState) -> None:
        """Rohe Header-Werte JE Regel plus unsere Inferenz mitschreiben.

        Bislang stand im Log nur, DASS ein Request lief (httpx-Zeile) — die
        eigentlichen X-Rate-Limit-Zahlen waren nirgends nachvollziehbar. Erst
        mit dieser Zeile ließ sich beweisen, dass GGGs Zähler blockweise statt
        gleitend sinkt (FALLSTRICKE_UND_WORKAROUNDS.md #45, Runde 6). Bewusst
        INFO statt DEBUG, damit die Datei bei einem realen Vorfall ohne
        Neustart mit anderem Log-Level bereits die Antwort enthält."""
        for rule in state.rules.values():
            since_drop = (f"{state.last_update - rule.last_drop_at:.1f}s"
                          if rule.last_drop_at else "-")
            takt = f"{rule.drop_interval_s:.1f}s" if rule.drop_interval_s else "-"
            log.info(
                "Rate-Limit-Header %s/%s: current=%d/%d window=%ds lock_rest=%.1fs "
                "letzte_absenkung_vor=%s takt=%s",
                policy, rule.rule_group, rule.current, rule.max_hits, rule.window_s,
                rule.active_lock_s, since_drop, takt)

    def _parse_group(self, state: PolicyState, group: str,
                     rules_str: str, state_str: str, now: float) -> None:
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
            rule.observe(current, now)
            rule.active_lock_s = lock_rest

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
                usable = max(1, int(_pacing_budget(rule)) - 1)
                intervals.append(rule.window_s / usable)
            return max(intervals) if intervals else DEFAULT_PACING_INTERVAL_S

    def pacing_blocked(self, policy_name: str | None = None) -> bool:
        """Ist das Fenster für den gleichmäßigen Takt schon zu voll?

        Der Takt allein (``steady_pace_interval_s``) reicht als Schutz
        nicht. Er hält im Dauerbetrieb zwar knapp unter der Bremsschwelle,
        rechnet dabei aber so, als wäre das Fenster leer und als kämen
        ausschließlich seine eigenen Requests darin vor. Real kommen
        ungetaktete Requests dazu: Klicks auf noch nicht geladene Fächer,
        Liga-Wechsel, die Abrufe direkt nach dem Programmstart. Die füllen
        dasselbe Fenster mit, der Takt zählt unbeirrt weiter — und seine
        Restmarge von genau EINEM Treffer ist sofort aufgebraucht (real
        beobachtet 2026-07-30: 18 ungetaktete Requests in den ersten 55s
        nach dem Start, danach kletterte der Takt schnurstracks bis 29/30
        und löste 289s Zwangspause aus, FALLSTRICKE #47).

        Deshalb zusätzlich diese harte Obergrenze: Der Takt darf das
        Fenster höchstens bis ``PACING_FILL_LIMIT`` der Bremsschwelle
        füllen und pausiert darüber, bis GGGs Zähler wieder sinkt. Ein
        bloß proportionales Ausbremsen genügt nicht — in den ersten
        ``window_s`` nach dem Start fällt überhaupt nichts heraus (GGG
        senkt blockweise, §RateLimitRule), der Zähler erreichte die
        Schwelle also auch langsam getaktet unweigerlich.

        Als Anteil statt als feste Reserve formuliert, damit auch knappe
        Kontingente sinnvoll bleiben: bei "5 pro 300s" ergäbe ein fester
        Abzug von 3 eine Obergrenze von 1, der Takt käme nie zum Zug.
        """
        with self._lock:
            state = self._policies.get(policy_name or self._last_policy)
            if state is None:
                return False
            self._decay_expired_rules(state)
            return any(rule.current >= _pacing_budget(rule)
                       for rule in state.rules.values())

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
            now = self._now()
            return (self._last_policy,
                    [r.snapshot(now) for r in state.rules.values()], wait)

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
            now = self._now()
            snap = [r.snapshot(now) for r in state.rules.values()] if state else []
        self._callback(policy_name, snap, wait_remaining)
