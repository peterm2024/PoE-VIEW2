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

        # Synchronisierungsbalken: wie viel des Rate-Limit-Fensters deckt
        # unsere eigene Messung ab (§set_sync). Steht direkt neben dem
        # Policy-Namen, weil er dessen Zahlen qualifiziert.
        self._sync = QProgressBar()
        self._sync.setFixedWidth(95)
        self._sync.setRange(0, 100)

        self._layout.addWidget(self._policy)
        self._layout.addWidget(self._sync)
        self._layout.addStretch()
        self._layout.addWidget(self._led)
        self._layout.addWidget(self._wait)
        self._set_led(DASH_OK, "OK")
        self.set_sync(0.0, 0.0)

    def set_sync(self, fraction: float, remaining_s: float) -> None:
        """Abdeckung des Rate-Limit-Fensters durch unsere eigene Messung
        (``RateLimitManager.window_coverage()``).

        GGGs Zähler überlebt unseren Prozess: direkt nach dem Start stammen
        die gemeldeten Treffer aus einer früheren Sitzung, deren Zeitpunkte
        wir nicht kennen — die Verbrauchsanzeige ist dann geschätzt statt
        gemessen (FALLSTRICKE #45). Ohne diesen Balken war das unsichtbar
        und führte prompt zur Rückfrage, warum die Anzeige nach einem
        Neustart alle 30s statt alle 11s herunterzählt.

        Rot → frisch gestartet, überwiegend geschätzt. Gelb → teils
        gemessen. Grün → das Fenster ist vollständig durch eigene Messungen
        abgedeckt, ab hier ist die Anzeige exakt.

        Die Restzeit steht im Balken selbst, nicht nur in der Farbe: bei
        Gelb wäre sonst nicht zu erkennen, ob noch 10 Sekunden oder zwei
        Minuten fehlen."""
        percent = int(round(max(0.0, min(1.0, fraction)) * 100))
        self._sync.setValue(percent)
        if percent >= 100:
            colour = DASH_OK
            self._sync.setFormat("Sync ✓")
            tip = ("Rate-limit window fully covered by our own measurements — "
                   "the usage numbers above are exact.")
        else:
            colour = DASH_WARN if percent >= 50 else DASH_BAD
            self._sync.setFormat(f"Sync {self._short_time(remaining_s)}")
            tip = (f"Syncing: {percent}% of the rate-limit window is covered by "
                   f"our own measurements, exact in {self._short_time(remaining_s)}.\n"
                   "GGG's counter outlives the app — hits from a previous run have "
                   "no known timestamp, so their share of the usage numbers above "
                   "is estimated rather than measured.")
        self._sync.setStyleSheet(f"QProgressBar::chunk {{ background: {colour}; }}")
        self._sync.setToolTip(
            tip + "\n\nNote: hits caused by another tool on the same account stay "
            "unknown even at 100%.")

    @staticmethod
    def _short_time(seconds: float) -> str:
        """"45s" / "2:30" — muss in einen 95px-Balken passen."""
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
        """"12/30 · 300 s · next in 2:19" — die Restzeit sagt, wann der
        nächste belegte Platz wieder frei wird.

        Ohne sie sieht eine völlig normale Phase wie ein Hänger aus: hat die
        App gerade zwölf Anfragen abgesetzt, kann vor Ablauf der ersten 300s
        nichts frei werden, der Zähler steht also minutenlang still (Peter,
        2026-07-30). Fehlt die Angabe (kein eigener Treffer im Fenster,
        z. B. direkt nach dem Start), bleibt sie weg statt geraten zu
        werden."""
        text = f'{rule["current"]}/{rule["max"]} · {rule["window_s"]} s'
        next_free = rule.get("next_free_s")
        if next_free is not None:
            text += f" · next in {RateLimitDashboard._short_time(next_free)}"
        return text

    @staticmethod
    def _rule_tooltip(rule: dict) -> str:
        tip = (f'{rule["current"]} of {rule["max"]} requests used in the last '
               f'{rule["window_s"]} s (sliding window).')
        if rule.get("next_free_s") is not None:
            tip += ("\nEach request frees its slot exactly "
                    f'{rule["window_s"]} s after it was made — the countdown is '
                    "the oldest one we know of. Requests from before the app "
                    "started (see the sync bar) may free up sooner.")
        return tip

    def _ensure_bars(self, count: int) -> None:
        while len(self._bars) < count:
            bar = QProgressBar()
            bar.setFixedWidth(140)
            bar.setTextVisible(False)
            label = QLabel()
            # vor Stretch/LED einfügen; davor stehen fest der Policy-Name
            # und der Sync-Balken, daher Offset 2.
            insert_at = 2 + 2 * len(self._bars)
            self._layout.insertWidget(insert_at, bar)
            self._layout.insertWidget(insert_at + 1, label)
            self._bars.append((bar, label))
        for bar, label in self._bars[:count]:
            bar.show(); label.show()

    def _set_led(self, colour: str, tooltip: str) -> None:
        self._led.setStyleSheet(f"color: {colour}; font-size: 14px;")
        self._led.setToolTip(tooltip)
