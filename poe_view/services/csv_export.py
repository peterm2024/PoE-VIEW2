"""CSV-Export der Item-Tabelle.

Reine Python-Funktion (kein Qt), exportiert die tatsächlichen Item-Felder
statt nur der formatierten Anzeige-Strings — für die Weiterverarbeitung in
Excel/Sheets ist der rohe Wert nützlicher als "–" für "kein Wert".

Semikolon als Trenner + UTF-8-BOM ("utf-8-sig"), damit Excel unter
deutscher Locale die Datei ohne manuellen Text-Import korrekt öffnet.
"""

from __future__ import annotations

import csv
import re

from poe_view.api.models import Item, gem_level, gem_quality

FIELDNAMES = ["Tab", "Name", "Rarity", "TypeLine", "BaseType", "Level",
             "Quality", "StackSize", "ItemLevel", "Corrupted"]

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename(text: str, fallback: str = "items") -> str:
    """Macht einen String zu einem gültigen Windows-Dateinamens-Bestandteil."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", text).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned[:60] or fallback


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
                "Corrupted": "yes" if item.corrupted else "",
            })
    return len(rows)
