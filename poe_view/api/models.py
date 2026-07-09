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
        """Map-Stash-Kinder haben oft KEIN name-Feld — der Anzeigename steckt
        dann in metadata.map ({name, tier, …})."""
        if self.name:
            return self.name
        map_info = self.metadata.get("map") or {}
        if map_info.get("name"):
            tier = map_info.get("tier")
            return f"{map_info['name']} (T{tier})" if tier else str(map_info["name"])
        return self.type or self.id[:8]


class Character(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    class_: str = Field("", alias="class")
    league: str | None = None
    level: int = 0
