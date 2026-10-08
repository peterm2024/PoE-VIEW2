"""Leveling-Plan für die Anzeige (§4.60.14): eine Rechnung für Baum-Fenster,
Statusleiste und das kleine Fenster neben dem Spiel.

Peter, 2026-10-08: "Im Baum-Bild", "Eigenes kleines Fenster", "Hinweis
beim Levelaufstieg" — alle drei. Damit sie nie Verschiedenes sagen,
rechnet nur ``progress`` (aus ``services.leveling``).
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from poe_view.services import leveling, passive_tree, tree_history
from poe_view.services.leveling import Plan, Step
from poe_view.services.passive_tree import Tree
from poe_view.ui import tree_report


def build_plan(characters: dict, name: str) -> Plan | None:
    """Der gespeicherte Plan mit dem Baum seiner Ziel-Konfiguration (ist
    sie gelöscht, gibt es keinen)."""
    roh = tree_history.leveling(characters, name)
    if roh is None:
        return None
    ziel = tree_history.configs(characters, name).get(roh["target"])
    if ziel is None:
        return None
    return Plan(ziel.get("passives") or {}, [int(h) for h in roh.get("priority") or ()])


@dataclass
class Progress:
    title: str                      # Name der Ziel-Konfiguration
    steps: list[Step]               # alle, vom Klassenstart bis zum Ziel
    level: int
    quest: int                      # wirksame Quest-Punkte (``seen_quest`` oder von Hand)
    quest_seen: int = 0             # die der echte Baum belegt — darunter geht es nicht

    @property
    def points(self) -> int:
        return leveling.points_earned(self.level, self.quest)

    @property
    def index(self) -> int:
        """Der Schritt, der jetzt dran ist: der mit dem zuletzt bekommenen
        Punkt (Punkt 12 → Schritt 12). Ohne Punkt (Level 1) der erste."""
        return max(self.points, 1) - 1

    @property
    def now(self) -> Step | None:
        return self.steps[self.index] if self.index < len(self.steps) else None

    @property
    def upcoming(self) -> list[Step]:
        return self.steps[self.index:]

    def points_text(self) -> str:
        quest = f" + {self.quest} quest" if self.quest else ""
        return (f"level {self.level}{quest} = {self.points} "
                f"{'point' if self.points == 1 else 'points'}")

    def now_text(self, tree: Tree) -> str:
        """"Point 12/96: Strength (towards Arsonist)"."""
        if self.now is None:
            return f"plan complete ({len(self.steps)} points)"
        nummer = f"Point {self.index + 1}/{len(self.steps)}"
        if self.points == 0:
            nummer = "First point (level 2)"
        return f"{nummer}: {step_text(tree, self.now)}"


def progress(tree: Tree, characters: dict, name: str, class_name: str,
             level: int | None = None) -> Progress | None:
    """Wo der Charakter im Plan steht. Ohne bekanntes Level das des
    aktuellen Baums."""
    plan = build_plan(characters, name)
    if plan is None or tree is None:
        return None
    if not level:
        level = (tree_history.current(characters, name) or {}).get("level") or 1
    roh = tree_history.leveling(characters, name) or {}
    echt = (tree_history.current(characters, name) or {}).get("passives") or {}
    gesehen = seen_quest(tree, echt, level)
    # Beide schon höchstens 24 (``seen_quest``, ``change_quest``).
    quest = max(tree_history.quest_points(characters, name), gesehen)
    return Progress(roh.get("target", ""), leveling.sequence(tree, plan, class_name), level,
                    quest, gesehen)


def seen_quest(tree: Tree, passives: dict, level: int) -> int:
    """Quest-Punkte, die der echte Baum belegt: Hat er mehr Punkte
    vergeben, als das Level hergibt, kamen die übrigen aus Quests (Peter:
    "Warum resettet sich der tree auf 80/103 wenn ich 'now' drücke?" —
    Level 81, 103 Punkte vergeben, 0 Quest-Punkte eingetragen)."""
    vergeben = tree_report.used_points(tree, passives)[0]
    return min(max(vergeben - max(level - 1, 0), 0), passive_tree.QUEST_POINTS)


def change_quest(characters: dict, name: str, stand: Progress, delta: int) -> bool:
    """"+1 quest"/"−1 quest": vom wirksamen Wert aus, nie unter das, was
    der echte Baum belegt, nie über alle Quest-Punkte. True, wenn sich
    etwas geändert hat."""
    neu = min(max(stand.quest + delta, stand.quest_seen), passive_tree.QUEST_POINTS)
    if neu == stand.quest:
        return False
    tree_history.set_quest_points(characters, name, neu)
    return True


def step_text(tree: Tree, step: Step, towards: bool = True) -> str:
    """"Strength (towards Arsonist)", bei einer Mastery ihr Effekt."""
    n = tree.nodes[step.node]
    if step.kind == leveling.MASTERY_STEP:
        werte = " / ".join(n.effects.get(step.effect, ())) or str(step.effect)
        return f"{n.name}: {werte}"
    ziel = tree.nodes.get(step.target)
    if towards and ziel is not None and ziel.id != n.id:
        return f"{n.name} (towards {ziel.name})"
    return n.name


def status_text(tree: Tree, stand: Progress | None) -> str:
    """Für die Statusleiste: kurz, nur das Nötigste."""
    if stand is None:
        return ""
    if stand.now is None:
        return f"Leveling “{stand.title}”: plan complete"
    return f"Leveling: {stand.now_text(tree)}"


def quest_buttons(on_change: Callable[[int], None]) -> tuple[QPushButton, QPushButton]:
    """"+1 quest" und "−1 quest" — für die Punkte aus Quests, die weder Log
    noch API melden (Peter: "manuell hinzuzufügen bzw. bei einem Fehlklick
    wieder zu entfernen")."""
    plus = QPushButton("+1 quest")
    plus.setToolTip("A quest gave you a passive point")
    plus.clicked.connect(lambda: on_change(1))
    minus = QPushButton("−1 quest")
    minus.setToolTip("Take back a quest point added by mistake "
                     "(not below what your tree already shows)")
    minus.clicked.connect(lambda: on_change(-1))
    return plus, minus


def update_quest_buttons(plus: QPushButton, minus: QPushButton,
                         stand: Progress | None) -> None:
    plus.setEnabled(stand is not None and stand.quest < passive_tree.QUEST_POINTS)
    minus.setEnabled(stand is not None and stand.quest > stand.quest_seen)


class LevelingWindow(QWidget):
    """Das kleine Fenster neben dem Spiel: immer oben, ohne Eintrag in der
    Taskleiste, die nächsten Punkte untereinander."""

    ROWS = 6

    def __init__(self, parent: QWidget | None = None,
                 on_quest: Callable[[str, int], None] | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Leveling plan")
        self.head = QLabel()
        self.head.setWordWrap(True)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self._on_quest = on_quest
        self.quest_plus, self.quest_minus = quest_buttons(
            lambda d: self._on_quest and self._on_quest(self.character, d))
        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        knoepfe.addWidget(self.quest_minus)
        knoepfe.addWidget(self.quest_plus)
        aufbau = QVBoxLayout(self)
        aufbau.addWidget(self.head)
        aufbau.addWidget(self.body, 1)
        aufbau.addLayout(knoepfe)
        self.resize(320, 240)
        self.character = ""

    def show_progress(self, tree: Tree | None, character: str, stand: Progress | None) -> None:
        self.character = character
        if tree is None or stand is None:
            self.head.setText(f"{character}: no leveling plan")
            self.body.setText("")
            update_quest_buttons(self.quest_plus, self.quest_minus, None)
            return
        e = html.escape
        self.head.setText(f"<b>{e(character)}</b> · {e(stand.points_text())}<br>"
                          f"towards “{e(stand.title)}”")
        zeilen = []
        for i, s in enumerate(stand.upcoming[:self.ROWS]):
            nummer = stand.index + i + 1
            text = html.escape(step_text(tree, s))
            zeilen.append(f"<b>▶ {nummer}. {text}</b>" if i == 0 else f"{nummer}. {text}")
        if not zeilen:
            zeilen.append("Plan complete.")
        self.body.setText("<br>".join(zeilen))
        update_quest_buttons(self.quest_plus, self.quest_minus, stand)
