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

        self._layout.addWidget(self._policy)
        self._layout.addStretch()
        self._layout.addWidget(self._led)
        self._layout.addWidget(self._wait)
        self._set_led(DASH_OK, "OK")

    def update_state(self, policy: str, rules: list[dict], wait_s: float) -> None:
        self._policy.setText(f"Policy: {policy or '–'}")
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
            label.setText(f'{rule["current"]}/{rule["max"]} · {rule["window_s"]} s')
        for bar, label in self._bars[len(rules):]:
            bar.hide(); label.hide()

        if wait_s > 0:
            self._set_led(DASH_BAD, "WAITING")
            self._wait.setText(f"Waiting: {wait_s:.0f} s")
        else:
            colour = DASH_WARN if worst >= 0.6 else DASH_OK
            self._set_led(colour, "OK")
            self._wait.setText("")

    def _ensure_bars(self, count: int) -> None:
        while len(self._bars) < count:
            bar = QProgressBar()
            bar.setFixedWidth(140)
            bar.setTextVisible(False)
            label = QLabel()
            # vor Stretch/LED einfügen: Position 1 + 2*i
            insert_at = 1 + 2 * len(self._bars)
            self._layout.insertWidget(insert_at, bar)
            self._layout.insertWidget(insert_at + 1, label)
            self._bars.append((bar, label))
        for bar, label in self._bars[:count]:
            bar.show(); label.show()

    def _set_led(self, colour: str, tooltip: str) -> None:
        self._led.setStyleSheet(f"color: {colour}; font-size: 14px;")
        self._led.setToolTip(tooltip)
