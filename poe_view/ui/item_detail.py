"""Item-Detail-Panel: großes Icon, Name in Rarity-Farbe, Properties und Mods.

"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from poe_view.api.models import Item, req_attribute, req_level
from poe_view.ui.theme import RARITY_COLORS


class ItemDetail(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._icon = QLabel()
        self._icon.setFixedSize(64, 64)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name = QLabel("No item selected")
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
        tags = [tag for tag, present in
               (("Unidentified", not item.identified), ("Corrupted", item.corrupted))
               if present]
        suffix = f"  [{', '.join(tags)}]" if tags else ""
        self._name.setText(item.display_name + suffix)
        self._name.setStyleSheet(f"font-weight:600; font-size:13px; color:{colour};")

        lines: list[str] = [item.rarity + (f" · {item.typeLine}" if item.name else "")]
        requirement_bits = []
        if item.ilvl:
            requirement_bits.append(f"iLvl {item.ilvl}")
        if req_level(item):
            requirement_bits.append(f"Req. Lvl {req_level(item)}")
        for label in ("Str", "Dex", "Int"):
            value = req_attribute(item, label)
            if value:
                requirement_bits.append(f"Req. {label} {value}")
        if requirement_bits:
            lines.append(" · ".join(requirement_bits))
        for prop in item.properties:
            if prop.display_value:
                lines.append(prop.display_text)
        lines.extend(item.implicit_mods)
        lines.extend(item.explicit_mods)
        self._props.setText("\n".join(lines[:12]))

        if pixmap:
            self._icon.setPixmap(pixmap.scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self._icon.clear()
