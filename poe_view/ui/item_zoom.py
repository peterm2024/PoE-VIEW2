"""Vergrößerte Item-Ansicht: Doppelklick auf eine Zeile in der Item-Tabelle
öffnet ein eigenes Fenster mit großem Icon und vollständigem Mod-/
Property-Text (ToDo.md: "Doppelklick auf ein Item 'beleuchtet' dies").

Bewusst NUR eine größere, vollständige Darstellung dessen, was die App
ohnehin schon kennt (dasselbe Modell wie das kompakte ``ItemDetail``, nur
ohne dessen ``lines[:12]``-Kürzung und mit einem deutlich größeren Icon).
Zwei Teile der ursprünglichen ToDo-Idee fehlen bewusst: Tier-Level/
Stat-Wertebereiche bräuchten Mod-ID/Tier-Rohdaten, die GGGs API
nachweislich nie liefert (FALLSTRICKE #50), und "Beliebtheit als
Crafting-Basis"/Build-Nutzung bräuchte eine eigenständige, neue
poe.ninja-Build-Anbindung (unser bestehender ``api/ninja.py``-Client holt
nur Preise, keine Build-Daten) — beides eigene, größere Vorhaben.

Für Divination Cards (frameType 6) ersetzt ``MainWindow`` das anfangs
übergebene Icon asynchron durch das echte Karten-Artwork (per
``set_icon_pixmap``, siehe ``external_tools.divination_card_art_url`` und
FALLSTRICKE #52) — GGGs Stash-API liefert für jede Div-Card dasselbe
generische Icon, das wäre für dieses Fenster wertlos. Das Artwork selbst
ist nur das bloße Illustrations-Panel ohne Rahmen/Titel (siehe
FALLSTRICKE #52) — ein schlichter Pergament-Rahmen samt Titel-Banner
gleicht das optisch an den echten Karten-Look an (Peters Wiki-Referenz,
2026-07-31), rein dekorativ, keine neuen Daten.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from poe_view.api.models import Item, item_category, req_attribute, req_level
from poe_view.ui.theme import RARITY_COLORS

# Fester Vergrößerungsfaktor statt Skalierung auf die Fensterbreite —
# Letzteres blies auch kleine, normale Item-Icons auf hunderte Pixel auf
# und sah dadurch verpixelt/falsch aus (Peter, 2026-07-31: "das ging
# schief... einfach fest auf 300% vergrößern, dann sollte das ganz gut
# ins Fenster passen"). 300% war Peter dann doch zu groß, 200% ist der
# aktuelle Stand (Peter, 2026-07-31).
_ZOOM_FACTOR = 2

# Rein optische Anlehnung an den Pergament-/Schriftrollen-Look echter
# Divination-Card-Darstellungen (z. B. im PoE-Wiki) — keine echten
# Karten-Assets, nur Farben/Rahmen in Qt-Stylesheet-Syntax.
_CARD_FRAME_STYLE = (
    "QFrame#cardFrame {"
    " background-color: #241a10;"
    " border: 3px solid #9c7b3f;"
    " border-radius: 10px;"
    "}"
)
_CARD_TITLE_STYLE = (
    "background-color: #d8c088; color: #2a1a0d; font-weight: 700;"
    " font-size: 15px; border: 2px solid #9c7b3f; border-radius: 6px;"
    " padding: 5px 12px;"
)


class ItemZoomDialog(QDialog):
    def __init__(self, item: Item, pixmap: QPixmap | None,
                parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(item.display_name)
        self.resize(420, 520)

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap:
            self.set_icon_pixmap(pixmap)

        colour = RARITY_COLORS.get(item.frameType, "#e8e6e3")
        tags = [tag for tag, present in
               (("Unidentified", not item.identified), ("Corrupted", item.corrupted))
               if present]
        suffix = f"  [{', '.join(tags)}]" if tags else ""
        self._name = QLabel(item.display_name + suffix)
        self._name.setWordWrap(True)
        self._name.setStyleSheet(f"font-weight:700; font-size:16px; color:{colour};")

        self._text = QLabel(self._build_text(item))
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._text.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._text)

        layout = QVBoxLayout(self)
        if item.frameType == 6:
            layout.addWidget(self._build_card_frame())
        else:
            layout.addWidget(self._icon)
            layout.addWidget(self._name)
        layout.addWidget(scroll, stretch=1)

    def _build_card_frame(self) -> QFrame:
        """Pergament-Rahmen mit Titel-Banner um Icon+Name für Divination
        Cards — rein optisch, siehe Modul-Docstring."""
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setStyleSheet(_CARD_TITLE_STYLE)
        frame = QFrame()
        frame.setObjectName("cardFrame")
        frame.setStyleSheet(_CARD_FRAME_STYLE)
        frame_layout = QVBoxLayout(frame)
        frame_layout.addWidget(self._name)
        frame_layout.addWidget(self._icon)
        return frame

    def set_icon_pixmap(self, pixmap: QPixmap) -> None:
        """Öffentlich, damit MainWindow das anfängliche (bei Divination
        Cards wertlose generische) Icon nachträglich durch echtes Artwork
        ersetzen kann, sobald der asynchrone Abruf fertig ist. Fester
        Faktor (_ZOOM_FACTOR) auf die Originalgröße, keine Skalierung auf
        die Fensterbreite — siehe Modul-Konstante."""
        self._icon.setPixmap(pixmap.scaled(
            pixmap.width() * _ZOOM_FACTOR, pixmap.height() * _ZOOM_FACTOR,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    @staticmethod
    def _build_text(item: Item) -> str:
        lines = [item.rarity + (f" · {item.typeLine}" if item.name else "")]

        category = item_category(item)
        if category:
            lines.append(f"Class: {category}")

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

        if item.socket_string:
            lines.append(f"Sockets: {item.socket_string}")

        prop_lines = [p.display_text for p in item.properties if p.display_value]
        if prop_lines:
            lines.append("")
            lines.extend(prop_lines)

        if item.implicitMods:
            lines.append("")
            lines.extend(item.implicitMods)

        if item.explicitMods:
            lines.append("")
            lines.extend(item.explicitMods)

        return "\n".join(lines).strip()
