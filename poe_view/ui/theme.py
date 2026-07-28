"""Farb-Konstanten der UI: PoE-Rarity-Farben und Dashboard-Ampel.

Quelle Rarity ↔ frameType: docs/ARCHITEKTUR.md §5.
"""

from PySide6.QtGui import QColor


def blend(colour: QColor, towards: QColor, factor: float) -> QColor:
    """Mischt ``colour`` zu ``factor`` Anteilen Richtung ``towards`` —
    ergibt "gedimmt" statt eines festen Grautons, der auf hellem wie
    dunklem Theme falsch aussähe. Genutzt für die Alters-Abblendung im
    Stash-Baum (stash_tree.py) und die Value-Spalten-Dimmung
    (item_table.py)."""
    return QColor(
        round(colour.red() * (1 - factor) + towards.red() * factor),
        round(colour.green() * (1 - factor) + towards.green() * factor),
        round(colour.blue() * (1 - factor) + towards.blue() * factor),
    )


RARITY_COLORS = {
    0: "#e8e6e3",  # Normal
    1: "#8888ff",  # Magic
    2: "#d9d955",  # Rare
    3: "#c96f2e",  # Unique
    4: "#2ecc94",  # Gem: deutlich grüner als Divination Card (
                   # die beiden waren zuvor kaum zu unterscheiden)
    5: "#b3a06a",  # Currency
    6: "#1fa8e0",  # Divination Card — deutlich blauer/cyaniger als Gem
    9: "#82ad6a",  # Relic
}

# Sentinel (kein echter frameType) für den Typ-Filter (MainWindow, item_table):
# alles ohne eigene Checkbox (Quest, Prophecy, Relic, Unbekanntes) landet
# hier — Pink, weil in RARITY_COLORS noch frei.
OTHER_TYPE = -1
TYPE_FILTER_COLOR = "#e05fae"

DASH_OK = "#6fae5c"
DASH_WARN = "#d3a94e"
DASH_BAD = "#c05b4d"
