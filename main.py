"""Einstiegspunkt: python main.py"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication

from poe_view import config
from poe_view.ui.main_window import MainWindow


def _setup_logging() -> None:
    """Konsole + rotierende Datei; Request-/Rate-Limit-Details auf DEBUG.

    Die Logdatei ist bewusst ausführlich — sie ist unsere Referenz für
    Rate-Limit-Analysen (und ggf. für eine spätere LabVIEW-Portierung).
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
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
