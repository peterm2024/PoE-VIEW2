"""CSV-Export der Item-Tabelle.

Reine Python-Funktion (kein Qt), exportiert die tatsächlichen Item-Felder
statt nur der formatierten Anzeige-Strings — für die Weiterverarbeitung in
Excel/Sheets ist der rohe Wert nützlicher als "–" für "kein Wert".

Semikolon als Trenner + UTF-8-BOM ("utf-8-sig"), damit Excel unter
deutscher Locale die Datei ohne manuellen Text-Import korrekt öffnet.

Spaltensatz (Peter, 2026-08-02: "Im CSV hätte ich gerne alle Eigenschaften
eines Items"): ein FESTER, breiter Satz statt der Vereinigung aller real
vorkommenden Felder. Grund: Items sind höchst ungleich aufgebaut und
``Item`` erlaubt beliebige Zusatzfelder von GGG (``extra="allow"``) — eine
Vereinigung ergäbe eine über 100 Spalten breite, fast leere Tabelle, und
die verschachtelten Listen (properties, requirements, sockets, Mods)
passen ohnehin nicht je Eintrag in eine eigene Spalte. Listen landen
deshalb zusammengefasst in EINER Zelle, getrennt durch " | ".

Wirklich restlos alles liefert die Roh-JSON-Spalte (``raw_json=True``, im
Speichern-Dialog als eigener Dateityp wählbar): das unveränderte
API-Objekt je Item. Bewusst NICHT die Voreinstellung — ein einzelnes
Item-JSON ist mehrere Kilobyte groß, ein liga-weiter Export über
zehntausende Items würde damit dreistellige Megabyte erreichen.
"""

from __future__ import annotations

import csv
import json
import re

from poe_view.api.models import (Item, gem_level, gem_quality, item_category,
                                 req_attribute, req_level, strip_display_markup)
from poe_view.api.ninja import PriceIndex

# Mehrwertige Felder (Mod-Listen, Properties) in einer Zelle.
_LIST_SEP = " | "

# Mod-Arten, die GGG als eigene Liste liefert. Nur ``explicitMods`` und
# ``implicitMods`` stehen im Datenmodell; der Rest kommt über extra="allow"
# durch und wird hier über model_extra gelesen — deshalb eine Tabelle
# (Spaltenname → JSON-Feld) statt fester Attributzugriffe.
_MOD_FIELDS = (
    ("ImplicitMods", "implicitMods"),
    ("ExplicitMods", "explicitMods"),
    ("CraftedMods", "craftedMods"),
    ("EnchantMods", "enchantMods"),
    ("FracturedMods", "fracturedMods"),
    ("VeiledMods", "veiledMods"),
    ("UtilityMods", "utilityMods"),      # Flaschen
)

# Ja/Nein-Merkmale aus dem JSON, die kein Modellfeld haben.
_FLAG_FIELDS = (
    ("Mirrored", "duplicated"),          # GGG nennt gespiegelte Items "duplicated"
    ("Fractured", "fractured"),
    ("Synthesised", "synthesised"),
    ("Veiled", "veiled"),
    ("Replica", "replica"),
    ("Searing", "searing"),              # Eldritch-Implicits
    ("Tangled", "tangled"),
)

FIELDNAMES = [
    "Tab", "InventoryId", "X", "Y",
    "Name", "Rarity", "TypeLine", "BaseType", "Category",
    "ItemLevel", "Level", "Quality", "StackSize",
    "ReqLevel", "ReqStr", "ReqDex", "ReqInt",
    "Sockets", "Links",
    "Identified", "Corrupted",
    *[name for name, _ in _FLAG_FIELDS],
    "Influences",
    "Properties",
    *[name for name, _ in _MOD_FIELDS],
    "Note", "ValueChaos", "ItemId",
]

RAW_JSON_FIELD = "RawJSON"

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename(text: str, fallback: str = "items") -> str:
    """Macht einen String zu einem gültigen Windows-Dateinamens-Bestandteil."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", text).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned[:60] or fallback


def _extra(item: Item, field: str) -> object:
    """Zusatzfeld aus dem API-JSON (``extra="allow"``), ``None`` wenn nicht da."""
    return (item.model_extra or {}).get(field)


def _joined_list(item: Item, field: str) -> str:
    """Listenfeld als eine Zelle. Deckt Modellfelder und Zusatzfelder ab.

    GGGs Färbungs-Markup fällt dabei weg (``strip_display_markup``): In
    einer Tabellenkalkulation ist ``<currencyitem>{3x Orb of Fusing}``
    unbrauchbar. Der Filter steht hier und nicht am Modellfeld, weil
    ``craftedMods`` und Konsorten gar keine Modellfelder sind, sondern
    über ``extra="allow"`` durchkommen — sie brauchen dieselbe
    Behandlung. Wer die Rohfassung will, exportiert mit ``raw_json``."""
    value = getattr(item, field, None)
    if value is None:
        value = _extra(item, field)
    if not isinstance(value, list):
        return ""
    return _LIST_SEP.join(strip_display_markup(str(entry)) for entry in value)


def _properties_text(item: Item) -> str:
    """properties als fertige Zeilen (§``ItemProperty.display_text``):
    Platzhalter im Namen werden mit ihren Werten gefüllt, wertlose
    Einträge wie die Waffenklasse ("Bow") bleiben ohne Doppelpunkt
    stehen."""
    return _LIST_SEP.join(prop.display_text for prop in item.properties)


def _influences_text(item: Item) -> str:
    """GGG liefert Einflüsse als Objekt ({"shaper": true, "elder": true}),
    nicht als Liste — die gesetzten Schlüssel sind das Ergebnis."""
    influences = _extra(item, "influences")
    if not isinstance(influences, dict):
        return ""
    return _LIST_SEP.join(sorted(name for name, active in influences.items() if active))


def _flag(item: Item, field: str) -> str:
    return "yes" if _extra(item, field) else ""


def _value_chaos(item: Item, price_index: PriceIndex | None) -> str:
    """Chaos-Wert × Stack, wie in der Value-Spalte — hier aber als reine
    Zahl ohne Einheit und ohne Divine-Umrechnung: In einer Tabellen-
    kalkulation ist eine einheitliche Zahl weiterverarbeitbar, "2.3div"
    dagegen nicht. Unbekannt bleibt leer statt 0 (FALLSTRICKE #39)."""
    if price_index is None:
        return ""
    unit_price = price_index.price_for(item)
    if unit_price is None:
        return ""
    return f"{unit_price * (item.stackSize or 1):.2f}"


def _row(tab_name: str, item: Item, price_index: PriceIndex | None) -> dict[str, str]:
    row = {
        "Tab": tab_name,
        "InventoryId": item.inventoryId,
        "X": "" if item.x is None else str(item.x),
        "Y": "" if item.y is None else str(item.y),
        "Name": item.display_name,
        "Rarity": item.rarity,
        "TypeLine": item.typeLine,
        "BaseType": item.baseType,
        "Category": item_category(item) or "",
        "ItemLevel": item.ilvl or "",
        "Level": gem_level(item) or "",
        "Quality": gem_quality(item) or "",
        "StackSize": item.stackSize or "",
        "ReqLevel": req_level(item) or "",
        "ReqStr": req_attribute(item, "Str") or "",
        "ReqDex": req_attribute(item, "Dex") or "",
        "ReqInt": req_attribute(item, "Int") or "",
        "Sockets": item.socket_string,
        "Links": item.max_links or "",
        # identified ist das einzige Merkmal, dessen INTERESSANTER Zustand
        # "nein" ist — deshalb hier ausgeschrieben statt als leere Zelle.
        "Identified": "yes" if item.identified else "no",
        "Corrupted": "yes" if item.corrupted else "",
        "Influences": _influences_text(item),
        "Properties": _properties_text(item),
        "Note": str(_extra(item, "note") or ""),
        "ValueChaos": _value_chaos(item, price_index),
        "ItemId": item.id or "",
    }
    row.update({name: _flag(item, field) for name, field in _FLAG_FIELDS})
    row.update({name: _joined_list(item, field) for name, field in _MOD_FIELDS})
    return row


def export_items(path: str, rows: list[tuple[str, Item]],
                 price_index: PriceIndex | None = None,
                 raw_json: bool = False) -> int:
    """Schreibt (tab_name, item)-Paare als CSV nach ``path``. Gibt die Zeilenzahl zurück.

    ``price_index`` füllt die ValueChaos-Spalte; ohne Index (Liga ohne
    poe.ninja-Daten, z. B. SSF) bleibt sie leer statt 0.
    ``raw_json`` hängt das unveränderte API-Objekt als letzte Spalte an.
    """
    fieldnames = FIELDNAMES + ([RAW_JSON_FIELD] if raw_json else [])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for tab_name, item in rows:
            row = _row(tab_name, item, price_index)
            if raw_json:
                row[RAW_JSON_FIELD] = json.dumps(item.model_dump(mode="json"),
                                                 ensure_ascii=False)
            writer.writerow(row)
    return len(rows)
