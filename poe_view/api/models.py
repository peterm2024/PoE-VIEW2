"""Datenmodelle für die GGG-API-Antworten (docs/ARCHITEKTUR.md §4.4).

Alle Modelle erlauben unbekannte Zusatzfelder (``extra="allow"``): die API
liefert weit mehr, als wir anzeigen — nichts bricht bei API-Erweiterungen.

LabVIEW-Äquivalent: Typedef-Cluster; ``get_property_value`` entspricht dem
SubVI "Extract Gem Info" (Schleife über das properties-Array).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# frameType → Rarity (Textfarbe im UI)
FRAME_TYPE_NAMES = {
    0: "Normal", 1: "Magic", 2: "Rare", 3: "Unique", 4: "Gem",
    5: "Currency", 6: "Divination Card", 7: "Quest", 8: "Prophecy", 9: "Relic",
}


class ItemProperty(BaseModel):
    """Ein Eintrag im properties-Array. values ist extrem verschachtelt:
    ``values[0][0]`` ist der Anzeigewert (z. B. "20 (Max)" oder "+20%")."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    values: list = Field(default_factory=list)

    @property
    def display_value(self) -> str | None:
        try:
            return str(self.values[0][0])
        except (IndexError, TypeError):
            return None


class Item(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str = ""                 # bei Currency/Gems oft leer …
    typeLine: str = ""             # … dann ist typeLine der Anzeigename
    baseType: str = ""
    icon: str = ""                 # CDN-URL, wird lokal gecacht
    frameType: int = 0
    ilvl: int | None = None
    stackSize: int | None = None
    corrupted: bool = False
    properties: list[ItemProperty] = Field(default_factory=list)
    explicitMods: list[str] = Field(default_factory=list)
    implicitMods: list[str] = Field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.name or self.typeLine or self.baseType or "?"

    @property
    def rarity(self) -> str:
        return FRAME_TYPE_NAMES.get(self.frameType, f"frameType {self.frameType}")


def get_property_value(item: Item, prop_name: str) -> str | None:
    """Property per Name suchen — es gibt KEINE festen JSON-Keys dafür."""
    for prop in item.properties:
        if prop.name == prop_name:
            return prop.display_value
    return None


def gem_level(item: Item) -> str | None:
    """Gem-Level, z. B. "5" — API liefert u. U. "5 (Max)", wir kürzen."""
    value = get_property_value(item, "Level")
    return value.split(" ")[0] if value else None


def gem_quality(item: Item) -> str | None:
    """Quality, normalisiert: API liefert "+20%"."""
    return get_property_value(item, "Quality")


# Waffen tragen ihre Item-Klasse als ERSTE Property (ohne Werte) — das ist
# der einzige Ort, an dem die API die Klasse direkt nennt.
_WEAPON_CLASSES = frozenset({
    "Bow", "Claw", "Dagger", "Rune Dagger", "One Handed Axe", "One Handed Mace",
    "One Handed Sword", "Thrusting One Handed Sword", "Sceptre", "Staff",
    "Warstaff", "Two Handed Axe", "Two Handed Mace", "Two Handed Sword",
    "Wand", "Fishing Rod",
})

# baseType-ENDUNG → Kategorie (endswith, NICHT substring: "Ringmail Coat"
# ist ein Body Armour, kein Ring!). Reihenfolge = Priorität.
_BASETYPE_CATEGORIES = (
    ("Flask", "Flask"), ("Jewel", "Jewel"), ("Quiver", "Quiver"), ("Ring", "Ring"),
    ("Talisman", "Amulet"), ("Amulet", "Amulet"),
    ("Sash", "Belt"), ("Vise", "Belt"), ("Belt", "Belt"),
    ("Greaves", "Boots"), ("Slippers", "Boots"), ("Boots", "Boots"), ("Shoes", "Boots"),
    ("Gauntlets", "Gloves"), ("Mitts", "Gloves"), ("Gloves", "Gloves"),
    ("Bascinet", "Helmet"), ("Burgonet", "Helmet"), ("Cage", "Helmet"),
    ("Casque", "Helmet"), ("Circlet", "Helmet"), ("Coif", "Helmet"),
    ("Crown", "Helmet"), ("Hood", "Helmet"), ("Helmet", "Helmet"),
    ("Mask", "Helmet"), ("Pelt", "Helmet"), ("Sallet", "Helmet"), ("Tricorne", "Helmet"),
    ("Buckler", "Shield"), ("Bundle", "Shield"), ("Shield", "Shield"),
)


def item_category(item: Item) -> str | None:
    """Item-Klasse/-Kategorie ("Two Handed Axe", "Ring", "Flask", …) — die API
    nennt sie nur bei Waffen direkt (erste Property), sonst Heuristik über
    die baseType-Endung, zuletzt Rüstungs-Properties → "Body Armour"."""
    if (item.properties and not item.properties[0].values
            and item.properties[0].name in _WEAPON_CLASSES):
        return item.properties[0].name
    base = item.baseType or item.typeLine
    for suffix, category in _BASETYPE_CATEGORIES:
        if base.endswith(suffix):
            return category
    if any(p.name in ("Armour", "Energy Shield", "Evasion Rating")
           for p in item.properties):
        return "Body Armour"
    return None


def dominant_category(items: list[Item]) -> str | None:
    """Häufigste Kategorie einer Item-Liste — benennt Unique-Stash-Fächer,
    die von der API völlig namenlos geliefert werden (Nutzer-Feedback)."""
    counts: dict[str, int] = {}
    for item in items:
        category = item_category(item)
        if category:
            counts[category] = counts.get(category, 0) + 1
    return max(counts, key=counts.get) if counts else None


class StashTab(BaseModel):
    """Stash-Tab; Ordner haben ``children`` (rekursiv) und metadata.folder=true.

    ``metadata.colour`` ist Hex OHNE '#'-Präfix (Beobachtung aus dem Test-VI).
    Spezial-Tabs (MapStash, UniqueStash) liefern beim Einzel-Abruf ebenfalls
    ``children`` (ein Unter-Tab pro Map-Typ bzw. Unique-Kategorie) statt
    ``items``; deren Items kommen vom Substash-Endpunkt und die Kinder tragen
    ``parent`` (ID des Spezial-Tabs) — nötig für den 3-Segment-URL-Pfad.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str = ""
    type: str = ""                 # Folder, QuadStash, CurrencyStash, MapStash, …
    index: int | None = None
    parent: str | None = None      # ID des Eltern-SPEZIAL-Tabs (nur bei Substashes)
    folder: str | None = None      # ID des Eltern-Ordners (nur bei Ordner-Kindern)
    metadata: dict = Field(default_factory=dict)
    children: list["StashTab"] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)

    @property
    def colour(self) -> str | None:
        c = self.metadata.get("colour")
        return f"#{c}" if c else None

    @property
    def is_folder(self) -> bool:
        return bool(self.metadata.get("folder")) or self.type == "Folder"

    @property
    def display_name(self) -> str:
        """Anzeigename aus den real beobachteten Spezial-Tab-Strukturen (echte
        Rohdaten 2026-07-09, siehe docs/api-notes/labview-test-vi.md):

        - Map-Kinder: metadata.map.name ("Map (Tier 6)" — der Tier steckt IM
          Namen, es gibt KEIN separates tier-Feld). Das name-Feld der Kinder
          ist daneben wertlos ("1"), AUSSER es ist ein GGG-Suffix mit
          führendem Leerzeichen (" (Remove-only)") — das hängen wir an.
        - Unique-Kinder: völlig namenlos (nur metadata.items = Anzahl) →
          Typ + Item-Anzahl, damit die Einträge unterscheidbar bleiben.
        """
        map_name = (self.metadata.get("map") or {}).get("name")
        if map_name:
            is_suffix = self.name != self.name.lstrip()  # " (Remove-only)" u. ä.
            return f"{map_name}{self.name}" if is_suffix else str(map_name)
        if self.name.strip():
            return self.name.strip()
        # Von UNS gestempelte Kategorie (dominant_category nach dem ersten
        # Item-Load, Präfix "poeview_" = synthetisch) — namenlose Unique-
        # Stash-Fächer heißen damit "Ring" statt "UniqueStash". Die
        # Item-Anzahl steht in der eigenen Baum-Spalte (Nutzer-Feedback),
        # nicht mehr im Namen.
        return self.metadata.get("poeview_category") or self.type or self.id[:8]


class Character(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    class_: str = Field("", alias="class")
    league: str | None = None
    level: int = 0
