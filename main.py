"""Einstiegspunkt: python main.py"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from poe_view import config
from poe_view.ui.main_window import MainWindow


def _setup_logging() -> None:
    """Konsole + rotierende Datei; Request-/Rate-Limit-Details auf DEBUG.

    Die Logdatei ist bewusst ausführlich; sie ist die Referenz für
    Rate-Limit-Analysen und hat bereits mehrfach Fehlerursachen
    aufgedeckt (siehe FALLSTRICKE_UND_WORKAROUNDS.md #28, #30).
    """
    config.ensure_dirs()
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler(config.LOG_DIR / "poe-view2.log",
                            maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> int:
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("PoE-VIEW2")
    # Ohne das trägt das Fenster beim Start aus der Quelle heraus das
    # allgemeine Python-Symbol. Die gepackte .exe bekommt ihr Icon zwar
    # ohnehin fest eingebettet (siehe PoE-VIEW2.spec), aber ein zweiter
    # Weg schadet nicht — und für die Entwicklung ist es der einzige.
    app.setWindowIcon(QIcon(str(config.APP_ICON)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
