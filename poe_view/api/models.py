"""Datenmodelle für die GGG-API-Antworten (docs/ARCHITEKTUR.md §4.4).

Alle Modelle erlauben unbekannte Zusatzfelder (``extra="allow"``): die API
liefert weit mehr, als wir anzeigen — nichts bricht bei API-Erweiterungen.

Beobachtetes Verhalten der einzelnen Felder: docs/api-notes/ggg-api.md.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# GGGs Färbungs-Markup in Mod- und Flavour-Texten: ``<tag>{Text}``, wobei
# das Tag die Farbe im Spiel-Tooltip bestimmt (``<currencyitem>`` gold,
# ``<corrupted>`` rot …) und ``<size:26>`` zusätzlich die Schriftgröße.
# Verschachtelung kommt real vor (``<size:26>{<rareitem>{Map}}``), deshalb
# wird von innen nach außen so lange ersetzt, bis sich nichts mehr ändert.
#
# Ausschließlich Divination Cards tragen es in ihren Mods (952 von 975
# Karten in Peters Cache, kein einziges anderes Item), Flavour-Texte auch
# bei Uniques. Ohne Filter stand wörtlich "<currencyitem>{3x Orb of
# Fusing}" im Fenster.
_DISPLAY_MARKUP = re.compile(r"<[a-zA-Z][a-zA-Z0-9]*(?::[^<>{}]*)?>\{([^{}]*)\}")

# Eine zweite, ganz andere Auszeichnung: DOPPELTE spitze Klammern
# verweisen auf Sonderglyphen (``<<HBGAa>><<HBG01>>…`` — die Runen-Schrift
# auf "The Messenger", "The Beachhead", "The Fracturing Spinner"). Die
# Glyphen haben wir nicht, also fällt der Verweis weg; was dann übrig
# bleibt, ist meist gar nichts — siehe ``Item.flavour_text``.
#
# Bewusst NUR die doppelte Form. Eine Regel, die alles in spitzen Klammern
# entfernt, verschluckt auch echten Text ("Bows & <Wands>") — und das
# unbemerkt. Bleibt umgekehrt einmal eine unpaarige Auszeichnung stehen,
# ist sie im Fenster zu sehen und damit zu bemerken. Sichtbar falsch ist
# besser als still gelöscht.
_LEFTOVER_TAG = re.compile(r"<<[^<>]*>>")

# frameType → Rarity (Textfarbe im UI)
FRAME_TYPE_NAMES = {
    0: "Normal", 1: "Magic", 2: "Rare", 3: "Unique", 4: "Gem",
    5: "Currency", 6: "Divination Card", 7: "Quest", 8: "Prophecy", 9: "Relic",
}


def strip_display_markup(text: str) -> str:
    """GGGs Färbungs-Markup entfernen und nur den lesbaren Text behalten.

    ``"<currencyitem>{3x Orb of Fusing}"`` → ``"3x Orb of Fusing"``.

    Die Zeilenenden kommen als ``\\r\\n`` bzw. als einzelnes ``\\r`` aus der
    API (real geprüft: Flavour-Texte enden zeilenweise auf ``\\r``) — ein
    stehengebliebenes ``\\r`` zeichnet Qt als Ersatzkästchen, deshalb wird
    hier auf ``\\n`` vereinheitlicht."""
    previous = None
    while previous != text:
        previous = text
        text = _DISPLAY_MARKUP.sub(r"\1", text)
    text = _LEFTOVER_TAG.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


# Dasselbe Markup, aber offen für den Blick hinein: Tag und Inhalt
# getrennt. ``<size:26>`` interessiert dabei nicht — die Schriftgröße
# bestimmt unsere Oberfläche selbst —, wohl aber der Farbname.
_MARKUP_SEGMENT = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)(?::[^<>{}]*)?>\{([^{}]*)\}")


def markup_segments(text: str) -> list[tuple[str | None, str]]:
    """Text in ``(Farbname, Inhalt)``-Abschnitte zerlegen.

    ``"<default>{Item Level:} <normal>{100}"`` →
    ``[("default", "Item Level:"), (None, " "), ("normal", "100")]``.

    Gegenstück zu ``strip_display_markup``: Statt die Auszeichnung
    wegzuwerfen, wird sie zugänglich gemacht. GGG sagt darin, in welcher
    Farbe das Spiel den Abschnitt zeigt — bei einer Divination Card also,
    ob die Belohnung eine Währung, ein Gem oder ein Unique ist. Diese
    Auskunft ist maßgeblich und lässt sich aus dem Text selbst nicht
    zurückgewinnen; ``<currencyitem>{3x Orb of Fusing}`` und
    ``<uniqueitem>{Doomfletch}`` unterscheiden sich sonst in nichts.

    ``None`` als Farbname heißt "keine Angabe" — der Abschnitt bekommt die
    normale Textfarbe. Verschachtelung wird vorher aufgelöst, sodass
    ``<size:26>{<rareitem>{Map}}`` als ``[("rareitem", "Map")]``
    herauskommt; ausschlaggebend ist immer die INNERSTE Angabe, denn sie
    steht dem Text am nächsten."""
    # Erst die äußeren Hüllen abtragen: Solange ein Tag nur ein einzelnes
    # weiteres Tag umschließt, ist die äußere Angabe für die Farbe ohne
    # Belang (in der Praxis ist es die Schriftgröße).
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"<[a-zA-Z][a-zA-Z0-9]*(?::[^<>{}]*)?>\{((?:[^{}]*\{[^{}]*\})+[^{}]*)\}",
                      r"\1", text)

    segments: list[tuple[str | None, str]] = []
    position = 0
    for match in _MARKUP_SEGMENT.finditer(text):
        if match.start() > position:
            segments.append((None, text[position:match.start()]))
        segments.append((match.group(1), match.group(2)))
        position = match.end()
    if position < len(text):
        segments.append((None, text[position:]))
    return [(tag, strip_display_markup(content)) for tag, content in segments if content]


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

    @property
    def display_text(self) -> str:
        """Fertige Zeile, wie sie das Spiel zeigt.

        Viele Eigenschaften tragen ihre Werte NICHT hinten dran, sondern
        als Platzhalter mitten im Namen: ``"Consumes {0} of {1} Charges
        on use"`` mit ``values=[['35', 0], ['65', 0]]`` ergibt "Consumes
        35 of 65 Charges on use". Wer nur ``display_value`` anhängt,
        bekommt "Consumes {0} of {1} Charges on use: 35" — die
        Platzhalter bleiben stehen und der zweite Wert fehlt ganz (Peter,
        2026-08-04, per Screenshot an einer Divine Life Flask).

        Drei Fälle, alle aus echten Daten belegt:

        * Platzhalter im Namen → jeder ``{i}`` wird durch ``values[i][0]``
          ersetzt.
        * Name ohne Platzhalter, aber mit Wert ("Quality", "+20%") →
          "Name: Wert", wie bisher.
        * Gar kein Wert (Waffenklasse als wertlose erste Eigenschaft,
          z. B. "Sceptre") → nur der Name, ohne Doppelpunkt.

        Der zweite Eintrag je Wert (``['35', 0]``) ist ein Formathinweis
        des Spiels (0 = normal, 1 = hervorgehoben) und für den reinen
        Text ohne Belang.
        """
        if "{" in self.name:
            text = self.name
            for index, entry in enumerate(self.values):
                try:
                    text = text.replace("{%d}" % index, str(entry[0]))
                except (IndexError, TypeError):
                    continue
            return text
        value = self.display_value
        return f"{self.name}: {value}" if value else self.name


class Socket(BaseModel):
    """Ein Socket-Eintrag. Items mit gleichem ``group`` sind miteinander
    verlinkt — die Link-Zahl eines Items ist die Größe seiner größten
    Gruppe (siehe ``Item.max_links``)."""

    model_config = ConfigDict(extra="allow")

    group: int = 0
    attr: str = ""
    sColour: str = ""


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
    x: int | None = None    # Gitter-Koordinate innerhalb des Stash-Tabs
    y: int | None = None
    inventoryId: str = ""  # bei Charakter-Items der Slot ("Weapon", "BodyArmour", "MainInventory", …)
    corrupted: bool = False
    identified: bool = True  # API liefert das Feld immer explizit, Default nur zur Sicherheit
    properties: list[ItemProperty] = Field(default_factory=list)
    requirements: list[ItemProperty] = Field(default_factory=list)
    # Mod-Texte SO, WIE GGG SIE LIEFERT — mit Färbungs-Markup. Für die
    # Anzeige nie direkt nehmen, sondern ``explicit_mods``/``implicit_mods``
    # (Text ohne Markup) oder ``markup_segments`` (Text MIT Farbangabe).
    # Die Rohfassung bleibt stehen, weil der Daten-Cache die Modelle
    # serialisiert: Würde hier schon gefiltert, wäre GGGs Farbangabe nach
    # dem ersten Speichern dauerhaft verloren.
    explicitMods: list[str] = Field(default_factory=list)
    implicitMods: list[str] = Field(default_factory=list)
    sockets: list[Socket] = Field(default_factory=list)
    # Der Spruchtext unter dem Item. Zeilenweise geliefert, aber das
    # Färbungs-Markup umschließt die GANZE Liste (``["<size:24>{Dread and
    # danger \\r", …, "can never wait.}"]``) — deshalb nie einzeln
    # auswerten, sondern über ``flavour_text``.
    flavourText: list[str] = Field(default_factory=list)
    # Dateiname des Divination-Card-Artworks, von GGG mitgeliefert. Nur
    # Karten haben ihn (real geprüft: 976 von 976).
    artFilename: str = ""
    # Wie viele Stück auf einen Stapel gehen. Bei einer Divination Card
    # ist das die SATZGRÖSSE (1 bis 27, real geprüft) — so viele muss man
    # sammeln, um sie einzulösen. Bei Währung dagegen reine Lagerkapazität
    # und bis 50000 groß; wer daraus etwas Grafisches baut, muss die
    # beiden Fälle trennen.
    maxStackSize: int | None = None

    @property
    def max_links(self) -> int:
        """Größe der größten Socket-Gruppe, 0 ohne Sockets."""
        if not self.sockets:
            return 0
        counts: dict[int, int] = {}
        for s in self.sockets:
            counts[s.group] = counts.get(s.group, 0) + 1
        return max(counts.values())

    @property
    def socket_string(self) -> str:
        """Sockets in derselben Schreibweise, die PoEs eigene Truhen-/
        Händlersuche durchsucht: Farben einer Link-Gruppe mit ``-``
        verbunden, Gruppen durch Leerzeichen getrennt ("R-R-R-R-R-R",
        "B B-B-B-B-B"). Damit greifen die auf poe.re zusammengeklickten
        Regex-Muster (``r-r-g|r-g-r|g-r-r``, ``-\\w-.-``, ``(-\\w){5}``)
        unverändert auch hier.

        Neben R/G/B liefert die API auch ``A`` (Abyss), ``W`` (weiß) und
        ``DV`` (Resonator) — unverändert übernommen, sonst verschöbe sich
        die Link-Zählung gegenüber dem, was im Spiel steht."""
        if not self.sockets:
            return ""
        groups: dict[int, list[str]] = {}
        for s in self.sockets:
            groups.setdefault(s.group, []).append(s.sColour)
        return " ".join("-".join(colours) for _, colours in sorted(groups.items()))

    @field_validator("explicitMods", "implicitMods", mode="before")
    @classmethod
    def _normalize_mods(cls, value: object) -> object:
        """GGG liefert einzelne Mod-Einträge mancher Items, etwa
        Currency-Beschreibungstexte, nicht als reinen String, sondern als
        ``{"description": "..."}``-Objekt. Das Format entspricht den ohnehin
        verschachtelten properties- und requirements-Werten. Auf den
        Anzeigetext reduzieren,
        bevor pydantic validiert, sonst schlägt der ganze Stash-Tab fehl."""
        if not isinstance(value, list):
            return value
        return [entry.get("description", str(entry)) if isinstance(entry, dict) else str(entry)
                for entry in value]

    @property
    def explicit_mods(self) -> list[str]:
        """``explicitMods`` als Anzeigetext, ohne GGGs Färbungs-Markup.

        Die camelCase-Felder tragen, was die API geliefert hat; die
        snake_case-Eigenschaften daneben sind das, was man anzeigt (wie
        ``display_name``, ``socket_string``, ``flavour_text``). Jede
        Anzeige, jeder Export und der Suchindex nehmen diese hier —
        ``explicitMods`` direkt zu lesen bedeutet, ``<currencyitem>{…}``
        in die Oberfläche zu schreiben."""
        return [strip_display_markup(mod) for mod in self.explicitMods]

    @property
    def implicit_mods(self) -> list[str]:
        """``implicitMods`` als Anzeigetext — siehe ``explicit_mods``."""
        return [strip_display_markup(mod) for mod in self.implicitMods]

    @property
    def flavour_text(self) -> str:
        """Der Spruchtext als fertiger Block, Markup entfernt.

        Erst zusammenfügen, dann filtern: Das Markup öffnet in der ersten
        und schließt in der letzten Zeile, zeilenweise gefiltert bliebe
        vorne ein ``<size:24>{`` und hinten ein ``}`` stehen.

        Leer, wenn nach dem Filtern nichts Lesbares übrig ist — bei den
        drei Items mit Runen-Schrift (siehe ``_LEFTOVER_TAG``) besteht der
        Text ausschließlich aus Glyphen-Verweisen, und eine Handvoll
        übriggebliebener Leerzeichen ist schlechter als gar keine Zeile."""
        joined = strip_display_markup("\n".join(self.flavourText)).strip()
        return joined if any(ch.isalnum() for ch in joined) else ""

    @property
    def display_name(self) -> str:
        return self.name or self.typeLine or self.baseType or "?"

    @property
    def lookup_name(self) -> str:
        """Der Name, unter dem ein Mensch dieses Item wiedererkennt.

        Anders als ``display_name``, das nimmt, was die API zuerst
        anbietet: Nur Uniques (frameType 3) haben einen Eigennamen, der
        etwas aussagt. Rares TRAGEN zwar auch einen ``name``, aber der ist
        eine zufällig gewürfelte Fantasiebezeichnung — real an Peters
        Cache geprüft: "Vortex Bane" für ein Rare-Messer, während
        ``baseType`` zuverlässig "Gutting Knife" trägt. Magic-Items haben
        gar keinen ``name``, ihr ``typeLine`` enthält aber die gewürfelten
        Präfix-/Suffix-Wörter mit im Text ("Fleet Citrine Amulet of the
        Flatworm") — auch hier ist ``baseType`` die bereinigte Fassung.
        Für alle übrigen Rarities ist ``baseType`` ohnehin schon der
        Anzeigename.

        Zwei Verwerter, eine Regel: die Rechtsklick-Verlinkung zu
        Nachschlagewerken (``ui/external_tools.py``, wo die Regel entstand
        — FALLSTRICKE #54, PoEDB fand Rares unter ihrem Fantasienamen
        nicht) und die Beschriftung der Ausrüstungsplätze in der
        Paperdoll, wo der Platz für "Flagellant's Quicksilver Flask of the
        Kaleidoscope" ohnehin nicht reicht."""
        if self.frameType == 3 and self.name:
            return self.name
        return self.baseType or self.typeLine or self.name or "?"

    @property
    def rarity(self) -> str:
        return FRAME_TYPE_NAMES.get(self.frameType, f"frameType {self.frameType}")


def get_property_value(item: Item, prop_name: str) -> str | None:
    """Property per Name suchen — es gibt keine festen JSON-Keys dafür."""
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


# Die API nennt Attribut-Anforderungen mal kurz ("Str"), mal lang
# ("Strength") — beides real beobachtet (Cache-Analyse 2026-07-10).
_REQUIREMENT_ALIASES = {
    "Str": ("Str", "Strength"),
    "Dex": ("Dex", "Dexterity"),
    "Int": ("Int", "Intelligence"),
}


def req_level(item: Item) -> str | None:
    """Benötigter Charakter-Level aus dem requirements-Array.

    Exakter Namensvergleich, kein startswith: Heist-Ausrüstung trägt
    "Level {0} in {1}" ("Level 2 in Any Job") — das ist ein Job-Level,
    kein Charakter-Level, und würde die Spalte verfälschen."""
    for req in item.requirements:
        if req.name == "Level":
            value = req.display_value
            return value.split(" ")[0] if value else None
    return None


def req_attribute(item: Item, short: str) -> str | None:
    """Attribut-Anforderung ("Str"/"Dex"/"Int"), Langformen inklusive."""
    names = _REQUIREMENT_ALIASES.get(short, (short,))
    for req in item.requirements:
        if req.name in names:
            return req.display_value
    return None


# Waffen tragen ihre Item-Klasse als ERSTE Property (ohne Werte) — das ist
# der einzige Ort, an dem die API die Klasse direkt nennt.
_WEAPON_CLASSES = frozenset({
    "Bow", "Claw", "Dagger", "Rune Dagger", "One Handed Axe", "One Handed Mace",
    "One Handed Sword", "Thrusting One Handed Sword", "Sceptre", "Staff",
    "Warstaff", "Two Handed Axe", "Two Handed Mace", "Two Handed Sword",
    "Wand", "Fishing Rod",
})

# baseType-ENDUNG → Kategorie (endswith, nicht substring: "Ringmail Coat"
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
    die von der API völlig namenlos geliefert werden."""
    counts: dict[str, int] = {}
    for item in items:
        category = item_category(item)
        if category:
            counts[category] = counts.get(category, 0) + 1
    return max(counts, key=counts.get) if counts else None


def is_ggg_suffix(name: str) -> bool:
    """Erkennt einen GGG-Zusatz-Hinweis im ``name``-Feld eines Kind-Tabs
    (" (Remove-only)" u. ä.) an seinem führenden Leerzeichen — GGG liefert
    ihn so statt eines separaten Feldes. So ein Suffix ist KEIN echter,
    eigenständiger Name: an einer Stelle definiert, weil sowohl
    ``StashTab.display_name`` (hier anhängen) als auch
    ``MainWindow._stamp_category``/``_restamp_from_cached_items`` (dort
    NICHT als "hat schon einen brauchbaren Namen" werten) sie brauchen —
    ein Unique-Stash-Kind mit reinem Suffix-Namen sah sonst nie seinen
    Kategorie-Stempel und zeigte nur noch "(Remove-only)" statt z. B.
    "Ring (Remove-only)" (real bei Peter beobachtet, 2026-07-30)."""
    return bool(name) and name != name.lstrip()


class StashTab(BaseModel):
    """Stash-Tab; Ordner haben ``children`` (rekursiv) und metadata.folder=true.

    ``metadata.colour`` ist Hex ohne '#'-Präfix.
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
        Rohdaten, siehe docs/api-notes/ggg-api.md):

        - Map-Kinder: metadata.map.name ("Map (Tier 6)" — der Tier steckt IM
          Namen, es gibt kein separates tier-Feld). Das name-Feld der Kinder
          ist daneben wertlos ("1"), AUSSER es ist ein GGG-Suffix mit
          führendem Leerzeichen (" (Remove-only)") — das hängen wir an.
        - Unique-Kinder: völlig namenlos (nur metadata.items = Anzahl) →
          von UNS gestempelte Kategorie (§_stamp_category). Ein GGG-Suffix
          (§is_ggg_suffix) hängt sich dabei ebenso an wie bei Map-Kindern,
          zählt aber NICHT als "schon echt benannt".
        """
        suffix = self.name if is_ggg_suffix(self.name) else ""
        map_name = (self.metadata.get("map") or {}).get("name")
        if map_name:
            return f"{map_name}{suffix}"
        if self.name.strip() and not suffix:
            return self.name.strip()
        # Von UNS gestempelte Kategorie (dominant_category nach dem ersten
        # Item-Load, Präfix "poeview_" = synthetisch) — namenlose Unique-
        # Stash-Fächer heißen damit "Ring" statt "UniqueStash". Die
        # Item-Anzahl steht in der eigenen Baum-Spalte,
        # nicht mehr im Namen.
        base = self.metadata.get("poeview_category") or self.type or self.id[:8]
        return f"{base}{suffix}"


class Character(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    class_: str = Field("", alias="class")
    league: str | None = None
    level: int = 0
