"""Rate-Limit-Dashboard: ein Balken pro Regel, Status-LED, Warte-Countdown.

Wird ausschließlich über das Signal ``rate_limit_changed`` gefüttert
Der Nutzer soll immer
sehen, WARUM die App gerade pausiert (docs/ARCHITEKTUR.md §5).
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar

from poe_view.ui.theme import DASH_BAD, DASH_OK, DASH_WARN


class RateLimitDashboard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 4)

        self._policy = QLabel("Policy: –")
        self._led = QLabel("●")
        self._wait = QLabel("")
        self._bars: list[tuple[QProgressBar, QLabel]] = []
        self._policy_name = ""
        self._paused = False  # Refresh-Modus "Pause", siehe set_paused()

        self._layout.addWidget(self._policy)
        self._layout.addStretch()
        self._layout.addWidget(self._led)
        self._layout.addWidget(self._wait)
        self._set_led(DASH_OK, "OK")

    @staticmethod
    def _short_time(seconds: float) -> str:
        """"45s" / "2:30"."""
        total = int(round(max(0.0, seconds)))
        if total < 60:
            return f"{total}s"
        return f"{total // 60}:{total % 60:02d}"

    def set_paused(self, paused: bool) -> None:
        """Refresh-Modus "Pause" sichtbar machen (Peter, 2026-07-30: die
        Anzeige blieb beim Umschalten unverändert stehen).

        Die reinen Zahlen (aktueller Verbrauch je Regel) bleiben unverändert
        korrekt — GGG zählt sie unabhängig davon, ob PoE-VIEW2 selbst gerade
        Requests schickt. Nur das Label bekommt sofort einen sichtbaren
        Hinweis, DAMIT der Umschalt-Klick auch etwas in diesem Widget
        auslöst. Als eigener, dauerhaft gemerkter Zustand (nicht nur ein
        einmaliges ``setText``): der Sekunden-Tick ruft ``update_state``
        weiterhin unabhängig vom Refresh-Modus auf (§_update_auto_refresh_
        countdown) und würde einen einmaligen Text sonst gleich wieder
        überschreiben."""
        self._paused = paused
        self._policy.setText(self._policy_text())

    def _policy_text(self) -> str:
        suffix = " (Paused)" if self._paused else ""
        return f"Policy: {self._policy_name or '–'}{suffix}"

    def update_state(self, policy: str, rules: list[dict], wait_s: float) -> None:
        self._policy_name = policy
        self._policy.setText(self._policy_text())
        self._ensure_bars(len(rules))
        worst = 0.0
        for (bar, label), rule in zip(self._bars, rules):
            ratio = rule["current"] / rule["max"] if rule["max"] else 0.0
            worst = max(worst, ratio)
            bar.setMaximum(rule["max"])
            bar.setValue(min(rule["current"], rule["max"]))
            colour = DASH_BAD if (ratio >= 0.9 or rule["locked"]) \
                else DASH_WARN if ratio >= 0.6 else DASH_OK
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {colour}; }}")
            label.setText(self._rule_text(rule))
            label.setToolTip(self._rule_tooltip(rule))
        for bar, label in self._bars[len(rules):]:
            bar.hide(); label.hide()

        if wait_s > 0:
            self._set_led(DASH_BAD, "WAITING")
            self._wait.setText(f"Waiting: {wait_s:.0f} s")
        else:
            colour = DASH_WARN if worst >= 0.6 else DASH_OK
            self._set_led(colour, "OK")
            self._wait.setText("")

    @staticmethod
    def _rule_text(rule: dict) -> str:
        """"12/30 · 300 s · next in ~2:19".

        Die Restzeit ist IMMER eine grobe Schätzung: reale Header-Daten
        zeigten, dass GGGs Zähler nicht gleitend pro Treffer sinkt, sondern
        blockweise alle ~window_s/5 Sekunden (FALLSTRICKE #45, Runde 6) —
        deshalb konsequent mit "~" statt einer erfundenen Präzision. Ohne
        die Angabe sieht eine völlig normale Phase, in der der Zähler
        gerade zwischen zwei Absenkungen steht, wie ein Hänger aus. Fehlt
        sie (noch keine zwei Absenkungen beobachtet), bleibt sie weg statt
        geraten zu werden."""
        text = f'{rule["current"]}/{rule["max"]} · {rule["window_s"]} s'
        next_free = rule.get("next_free_s")
        if next_free is not None:
            text += f" · next in ~{RateLimitDashboard._short_time(next_free)}"
        return text

    @staticmethod
    def _rule_tooltip(rule: dict) -> str:
        tip = (f'{rule["current"]} of {rule["max"]} requests used in the last '
               f'{rule["window_s"]} s.')
        if rule.get("next_free_s") is not None:
            tip += ("\nGGG's counter doesn't slide continuously per request — "
                    "it drops in batches roughly every window/5 seconds. This "
                    "is the average interval between drops observed so far, "
                    "not an exact countdown for a specific request.")
        return tip

    def _ensure_bars(self, count: int) -> None:
        while len(self._bars) < count:
            bar = QProgressBar()
            bar.setFixedWidth(140)
            bar.setTextVisible(False)
            label = QLabel()
            # vor Stretch/LED einfügen; davor steht fest der Policy-Name,
            # daher Offset 1.
            insert_at = 1 + 2 * len(self._bars)
            self._layout.insertWidget(insert_at, bar)
            self._layout.insertWidget(insert_at + 1, label)
            self._bars.append((bar, label))
        for bar, label in self._bars[:count]:
            bar.show(); label.show()

    def _set_led(self, colour: str, tooltip: str) -> None:
        self._led.setStyleSheet(f"color: {colour}; font-size: 14px;")
        self._led.setToolTip(tooltip)
