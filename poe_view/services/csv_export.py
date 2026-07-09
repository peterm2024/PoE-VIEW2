"""CSV-Export der Item-Tabelle.

Reine Python-Funktion (kein Qt), exportiert die tatsächlichen Item-Felder
statt nur der formatierten Anzeige-Strings — für die Weiterverarbeitung in
Excel/Sheets ist der rohe Wert nützlicher als "–" für "kein Wert".

Semikolon als Trenner + UTF-8-BOM ("utf-8-sig"), damit Excel unter
deutscher Locale die Datei ohne manuellen Text-Import korrekt öffnet.
"""

from __future__ import annotations

import csv

from poe_view.api.models import Item, gem_level, gem_quality

FIELDNAMES = ["Tab", "Name", "Rarity", "TypeLine", "BaseType", "Level",
             "Quality", "StackSize", "ItemLevel", "Corrupted"]


def export_items(path: str, rows: list[tuple[str, Item]]) -> int:
    """Schreibt (tab_name, item)-Paare als CSV nach ``path``. Gibt die Zeilenzahl zurück."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter=";")
        writer.writeheader()
        for tab_name, item in rows:
            writer.writerow({
                "Tab": tab_name,
                "Name": item.display_name,
                "Rarity": item.rarity,
                "TypeLine": item.typeLine,
                "BaseType": item.baseType,
                "Level": gem_level(item) or "",
                "Quality": gem_quality(item) or "",
                "StackSize": item.stackSize or "",
                "ItemLevel": item.ilvl or "",
                "Corrupted": "ja" if item.corrupted else "",
            })
    return len(rows)
