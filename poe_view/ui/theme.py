"""Farb-Konstanten der UI: PoE-Rarity-Farben und Dashboard-Ampel.

Quelle Rarity ↔ frameType: docs/ARCHITEKTUR.md §5.
"""

from PySide6.QtGui import QColor, QPalette


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

# Ampel des Rate-Limit-Dashboards. Steht hier oben, weil STACK_COLORS
# weiter unten dasselbe Grün wiederverwendet.
DASH_OK = "#6fae5c"
DASH_WARN = "#d3a94e"
DASH_BAD = "#c05b4d"

# GGGs Färbungs-Markup in Mod-Texten (``<currencyitem>{3x Orb of Fusing}``,
# siehe api/models.markup_segments) → unsere Farben. Wo das Tag einer
# Rarity entspricht, wird bewusst DIESELBE Farbe wie in der Item-Tabelle
# genommen: Ein Kartentext, der ein Unique verspricht, soll dieselbe
# Orange-Nuance tragen wie ein Unique in der Liste.
#
# Die Liste stammt nicht aus GGGs Doku, sondern aus echten Daten — es sind
# genau die dreizehn Tags, die in Peters Stash vorkommen (2026-08-06).
# Unbekannte Tags bekommen keine Farbe, keinen Ersatzwert: Eine geratene
# Farbe wäre schlechter als gar keine.
MARKUP_COLORS = {
    "whiteitem": RARITY_COLORS[0],
    "normal": RARITY_COLORS[0],
    "magicitem": RARITY_COLORS[1],
    "rareitem": RARITY_COLORS[2],
    "uniqueitem": RARITY_COLORS[3],
    "gemitem": RARITY_COLORS[4],
    "currencyitem": RARITY_COLORS[5],
    "divination": RARITY_COLORS[6],
    "corrupted": "#d20000",   # PoEs Korruptionsrot
    "augmented": "#8888ff",   # aufgewerteter Wert, wie ein Magic-Affix
    "enchanted": "#b4b4ff",
    "fractured": "#a29162",
    "default": None,          # ausdrücklich "normale Textfarbe"
}

# Satz-Fortschritt einer Divination Card (item_zoom): vorhandene Karten in
# der Kartenfarbe, fehlende gedämpft. Eigene Namen, keine GGG-Tags — der
# Bindestrich schließt eine Verwechslung mit dem Markup oben aus, dessen
# Tags durchweg reine Buchstaben sind.
STACK_COLORS = {
    # Volle Sätze: dasselbe Grün wie die "alles in Ordnung"-Anzeige des
    # Rate-Limit-Dashboards. Ein Grün in der ganzen Anwendung, und es
    # bedeutet an beiden Stellen dasselbe — fertig.
    "stack-complete": DASH_OK,
    "stack-full": RARITY_COLORS[6],
    # Fester mittlerer Grauton statt palette-abhängiger Dimmung: Die
    # Zeile wird als HTML-Text gebaut, dort steht keine Palette zur
    # Verfügung. Auf hellem wie dunklem Untergrund bleibt er sichtbar,
    # ohne mit den gefüllten Rechtecken zu konkurrieren.
    "stack-empty": "#6f6f6f",
}

# Sentinel (kein echter frameType) für den Typ-Filter (MainWindow, item_table):
# alles ohne eigene Checkbox (Quest, Prophecy, Relic, Unbekanntes) landet
# hier — Pink, weil in RARITY_COLORS noch frei.
OTHER_TYPE = -1
TYPE_FILTER_COLOR = "#e05fae"

# Zeilen-Hervorhebung beim Beobachten des Charakter-Inventars (Peter
# 2026-08-01: "die Zeilen hervorgehoben (Türkis), welche sich geändert
# haben" seit dem vorigen Refresh) — item_table.py.
ROW_CHANGED_COLOR = "#1fa8a8"


def dimmed_text(palette: QPalette) -> QColor:
    """Textfarbe zu 50% Richtung Hintergrund gemischt — "wahrscheinlich
    Schrott" (Value-Spalte) bzw. "aus dem Inventar verschwunden" (Zeilen im
    Charakter-Refresh-Diff, item_table.py) statt eines festen Grautons, der
    auf hellem wie dunklem Theme falsch aussähe."""
    return blend(palette.color(QPalette.ColorRole.Text),
                palette.color(QPalette.ColorRole.Base), 0.5)
