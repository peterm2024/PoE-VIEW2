"""Mini-Viewer für die Rohdaten eines Stash-Tabs (Rechtsklick im Baum, Doku §5).

Ein eigenständiges, nicht-modales Fenster (``Qt.WindowType.Window``) — läuft
parallel zum Hauptfenster weiter und wird von ``MainWindow._update_raw_viewer``
bei jedem Tab-Wechsel aktualisiert ("sollte sich auch beim
Durchwechseln der Stash-Tabs aktualisieren"). Zeigt exakt die Felder, die die
GGG-API für den Tab liefert — dank ``extra="allow"`` in den pydantic-Modellen
(api/models.py) verlustfrei, auch unbekannte/zukünftige API-Felder.

Anzeige-VI geöffnet), das per User Event vom Hauptpanel aus aktualisiert wird.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QVBoxLayout


class RawDataViewer(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Raw Data Viewer")
        self.resize(560, 640)

        self._title = QLabel("")
        self._title.setStyleSheet("font-weight: 600; padding: 4px;")
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._text, stretch=1)

    def show_payload(self, stash_id: str, name: str, payload: dict) -> None:
        self.show_document(f"{name}  ·  id={stash_id}",
                           json.dumps(payload, indent=2, ensure_ascii=False,
                                      default=str))

    def show_document(self, title: str, text: str) -> None:
        """Beliebigen Text zeigen statt eines Tab-Objekts.

        Damit dient dasselbe Fenster auch dem PoE2-Abzug
        (§services/poe2_probe.py) — ein zweites Monospace-Textfenster
        daneben wäre dieselbe Anzeige mit anderem Namen. Das Hauptfenster
        hält dafür eine eigene Instanz, sonst überschriebe der nächste
        Tab-Wechsel den Abzug."""
        self._title.setText(title)
        self._text.setPlainText(text)
