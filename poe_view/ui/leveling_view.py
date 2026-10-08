"""Leveling-Plan für die Anzeige (§4.60.14): eine Rechnung für Baum-Fenster,
Statusleiste und das kleine Fenster neben dem Spiel.

Peter, 2026-10-08: "Im Baum-Bild", "Eigenes kleines Fenster", "Hinweis
beim Levelaufstieg" — alle drei. Damit sie nie Verschiedenes sagen,
rechnet nur ``progress`` (aus ``services.leveling``).
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from poe_view.services import leveling, passive_tree, tree_history
from poe_view.services.leveling import Plan, Step
from poe_view.services.passive_tree import Node, Tree


def build_plan(characters: dict, name: str) -> Plan | None:
    """Der gespeicherte Plan mit den Bäumen seiner Konfigurationen (eine
    gelöschte fällt heraus; fehlen alle, gibt es keinen)."""
    roh = tree_history.leveling(characters, name)
    if roh is None:
        return None
    konfigs = tree_history.configs(characters, name)
    stufen = [leveling.Stage(n, konfigs[n].get("passives") or {})
              for n in roh["stages"] if n in konfigs]
    if not stufen:
        return None
    return Plan(stufen, [int(h) for h in roh.get("priority") or ()])


@dataclass
class Progress:
    title: str
    stage_index: int
    stage_count: int
    stage_name: str
    steps: list[Step]
    done: int                       # vermutlich schon vergeben (seit dem Abruf)
    refund: list[Node] = field(default_factory=list)

    @property
    def now(self) -> Step | None:
        return self.steps[self.done] if len(self.steps) > self.done else None

    @property
    def upcoming(self) -> list[Step]:
        return self.steps[self.done:]


def progress(tree: Tree, characters: dict, name: str, class_name: str,
             api_level: int | None = None, live_level: int | None = None,
             limit: int = 10) -> Progress | None:
    """Wo der Charakter im Plan steht: Abschnitt, die nächsten ``limit``
    Schritte nach den vermutlich schon vergebenen, und was zurück muss."""
    plan = build_plan(characters, name)
    if plan is None or tree is None:
        return None
    aktuell = tree_history.current(characters, name) or {}
    passives = aktuell.get("passives") or {}
    api = api_level or aktuell.get("level") or 0
    live = live_level or api              # unter dem API-Level zählt nichts (assumed_done)
    erledigt = leveling.assumed_done(live, api)
    schritte = leveling.next_steps(tree, plan, passives, class_name, limit=erledigt + limit)
    have = leveling._haupt(tree, passive_tree.allocated(passives))
    index = leveling.stage_index(tree, plan, have)
    roh = tree_history.leveling(characters, name) or {}
    return Progress(roh.get("title") or plan.stages[0].name, index, len(plan.stages),
                    plan.stages[index].name, schritte, min(erledigt, len(schritte)),
                    leveling.to_refund(tree, plan, passives))


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
    return f"Next passive: {step_text(tree, stand.now)}"


class LevelingWindow(QWidget):
    """Das kleine Fenster neben dem Spiel: immer oben, ohne Eintrag in der
    Taskleiste, die nächsten Punkte untereinander."""

    ROWS = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Leveling plan")
        self.head = QLabel()
        self.head.setWordWrap(True)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        aufbau = QVBoxLayout(self)
        aufbau.addWidget(self.head)
        aufbau.addWidget(self.body, 1)
        self.resize(320, 220)
        self.character = ""

    def show_progress(self, tree: Tree | None, character: str, level: int,
                      stand: Progress | None) -> None:
        self.character = character
        if tree is None or stand is None:
            self.head.setText(f"{character}: no leveling plan")
            self.body.setText("")
            return
        e = html.escape
        self.head.setText(f"<b>{e(character)}</b> · level {level}<br>"
                          f"“{e(stand.title)}” · stage {stand.stage_index + 1}/"
                          f"{stand.stage_count}: {e(stand.stage_name)}")
        zeilen = []
        for i, s in enumerate(stand.upcoming[:self.ROWS]):
            text = html.escape(step_text(tree, s))
            zeilen.append(f"<b>▶ {text}</b>" if i == 0 else f"{i + 1}. {text}")
        if not zeilen:
            zeilen.append("Plan complete.")
        if stand.refund:
            zeilen.append(f"<i>{len(stand.refund)} to refund when convenient</i>")
        self.body.setText("<br>".join(zeilen))
