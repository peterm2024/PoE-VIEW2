"""Farb-Konstanten der UI: PoE-Rarity-Farben und Dashboard-Ampel.

Quelle Rarity ↔ frameType: docs/ARCHITEKTUR.md §5.
"""

RARITY_COLORS = {
    0: "#e8e6e3",  # Normal
    1: "#8888ff",  # Magic
    2: "#d9d955",  # Rare
    3: "#c96f2e",  # Unique
    4: "#3fb8ae",  # Gem
    5: "#b3a06a",  # Currency
    6: "#0ebac5",  # Divination Card
    9: "#82ad6a",  # Relic
}

# Sentinel (KEIN echter frameType) für den Typ-Filter (MainWindow, item_table):
# alles ohne eigene Checkbox (Quest, Prophecy, Relic, Unbekanntes) landet
# hier — Pink, weil in RARITY_COLORS noch frei (Nutzer-Feedback).
OTHER_TYPE = -1
TYPE_FILTER_COLOR = "#e05fae"

DASH_OK = "#6fae5c"
DASH_WARN = "#d3a94e"
DASH_BAD = "#c05b4d"
