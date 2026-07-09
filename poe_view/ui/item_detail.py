"""Item-Detail-Panel: großes Icon, Name in Rarity-Farbe, Properties und Mods.

LabVIEW-Äquivalent: Picture Control + formatierte String-Anzeige.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from poe_view.api.models import Item
from poe_view.ui.theme import RARITY_COLORS


class ItemDetail(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._icon = QLabel()
        self._icon.setFixedSize(64, 64)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name = QLabel("Kein Item ausgewählt")
        self._name.setStyleSheet("font-weight: 600; font-size: 13px;")
        self._props = QLabel("")
        self._props.setWordWrap(True)

        text_col = QVBoxLayout()
        text_col.addWidget(self._name)
        text_col.addWidget(self._props)
        text_col.addStretch()

        layout = QHBoxLayout(self)
        layout.addWidget(self._icon)
        layout.addLayout(text_col, stretch=1)

    def show_item(self, item: Item, pixmap: QPixmap | None) -> None:
        colour = RARITY_COLORS.get(item.frameType, "#e8e6e3")
        suffix = "  [corrupted]" if item.corrupted else ""
        self._name.setText(item.display_name + suffix)
        self._name.setStyleSheet(f"font-weight:600; font-size:13px; color:{colour};")

        lines: list[str] = [item.rarity + (f" · {item.typeLine}" if item.name else "")]
        for prop in item.properties:
            value = prop.display_value
            if value:
                lines.append(f"{prop.name}: {value}")
        lines.extend(item.implicitMods)
        lines.extend(item.explicitMods)
        self._props.setText("\n".join(lines[:12]))

        if pixmap:
            self._icon.setPixmap(pixmap.scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self._icon.clear()
