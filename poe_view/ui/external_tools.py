"""Rechtsklick-Verlinkung zu frei konfigurierbaren Item-Nachschlagewerken.

Reine URL-Bausteine ohne Qt-Abhängigkeit — ``main_window.py`` verkabelt
sie an das Rechtsklick-Kontextmenü der Item-Tabelle.

Die Menüeinträge sind eine Liste von ``ToolEntry`` (Name + URL-Vorlage mit
``{slug}``-Platzhalter), die der Nutzer über den Settings-Dialog
(``settings_dialog.py``) selbst pflegt.

**Ab Werk ist die Liste LEER** (Peters Entscheidung, 2026-08-02: "Wir
nehmen das komplett raus ... Damit sind wir hier komplett unabhängig von
Internetseiten und jeder Benutzer hat individuell die Möglichkeit, eine
Seite einzubinden"). Vorher waren zwei Nachschlagewerke vorbelegt; die
Frage, ob deren Betreiber mit dem direkten Öffnen aus einer fremden
Anwendung heraus einverstanden sind, war nie geklärt (ToDo.md:
"Seitenbetreiber unbedingt fragen"). Mit leerer Vorbelegung stellt sich
die Frage gar nicht mehr: PoE-VIEW2 selbst kontaktiert keine
Drittanbieter-Seite, und wer einen Eintrag anlegt, trifft diese
Entscheidung bewusst für sich.

Das Ein-Platzhalter-Schema (nur ``{slug}``) deckt Nachschlagewerke ab, die
ein Item über genau einen Namen im Pfad adressieren — das ist bei
MediaWiki-artigen Seiten der Normalfall. Seiten, die zusätzlich einen
zweiten Wert brauchen (etwa eine Liga), passen bewusst nicht hinein;
dafür müsste das Schema erst um ein zweites Feld erweitert werden.

Neben den Links gibt es EINEN eingebauten Eintrag, der nichts öffnet,
sondern in die Zwischenablage schreibt: ``item_export_text`` baut PoEs
eigenes Item-Textformat nach, wie es Path of Building erwartet (siehe
dort).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from poe_view.api.models import (ENCHANT_MOD_FIELD, FRAME_TYPE_NAMES,
                                 WEAPON_CLASSES, Item, all_extra_mod_lines,
                                 extra_mod_lines, item_category)

# GGGs eigenes CDN — dieselbe Quelle, aus der die App ohnehin schon jedes
# Item-Icon lädt, also kein zusätzlicher Drittanbieter (deshalb von der
# leeren Tool-Vorbelegung oben nicht betroffen). Muster 2026-07-31 an zehn
# echten Karten verifiziert.
_DIVINATION_CARD_ART_BASE = "https://web.poecdn.com/image/divination-card"


@dataclass
class ToolEntry:
    """Ein konfigurierbarer Rechtsklick-Menüeintrag. ``url_template``
    enthält genau einen Platzhalter ``{slug}``, der durch den Item-Namen
    ersetzt wird (siehe ``build_url``)."""

    name: str
    url_template: str
    enabled: bool = True


# Bewusst LEER: PoE-VIEW2 bringt keine Seite ab Werk mit (siehe
# Modul-Docstring). Der Nutzer legt seine Nachschlagewerke selbst im
# Settings-Dialog an.
DEFAULT_TOOLS: tuple[ToolEntry, ...] = ()


def _underscore_name(text: str) -> str:
    """MediaWiki-Konvention — real geprüft: "Essence_Drain", "Chaos_Bolt".
    Apostrophe & Co. bleiben erhalten, das sind gültige URL-Zeichen.
    Klammern werden dagegen prozent-kodiert: Items mit Klammern im Namen
    ("Map (Tier 16)") liefen bei einem real getesteten Nachschlagewerk in
    einen 404, weil dessen Server "%28"/"%29" statt literaler Klammern im
    Pfad verlangt; MediaWiki akzeptiert BEIDE Schreibweisen, die Kodierung
    ist dort also unschädlich. Siehe FALLSTRICKE #57."""
    slug = text.strip().replace(" ", "_")
    return slug.replace("(", "%28").replace(")", "%29")


def build_url(entry: ToolEntry, item: Item) -> str:
    """``{slug}`` in der Vorlage durch den (nach Rarity passenden, siehe
    ``Item.lookup_name``) Item-Namen ersetzen (Leerzeichen -> Unterstrich).
    Weitere Platzhalter gibt es bewusst nicht — das deckt Ein-Wert-Schemas
    ab, wie sie MediaWiki-artige Seiten nutzen, siehe Modul-Docstring.

    Die Regel "Uniques unter ihrem Eigennamen, alles andere unter der
    Basis" entstand hier (FALLSTRICKE #54: PoEDB fand Rares unter ihrem
    gewürfelten Fantasienamen nicht), steht aber seit 2026-08-06 im Modell
    — die Paperdoll beschriftet ihre Ausrüstungsplätze nach derselben
    Überlegung."""
    return entry.url_template.replace("{slug}", _underscore_name(item.lookup_name))


def tools_to_json(entries: list[ToolEntry]) -> str:
    return json.dumps([
        {"name": e.name, "url_template": e.url_template, "enabled": e.enabled}
        for e in entries
    ])


def tools_from_json(text: str | None) -> list[ToolEntry]:
    """Fällt auf ``DEFAULT_TOOLS`` zurück, wenn noch nichts gespeichert
    wurde oder der gespeicherte Wert kaputt ist (z. B. von Hand editierte
    INI-Datei)."""
    if not text:
        return [ToolEntry(e.name, e.url_template, e.enabled) for e in DEFAULT_TOOLS]
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return [ToolEntry(e.name, e.url_template, e.enabled) for e in DEFAULT_TOOLS]
    return [
        ToolEntry(str(d.get("name", "")), str(d.get("url_template", "")), bool(d.get("enabled", True)))
        for d in raw
    ]


# PoEs Item-Klassennamen für die `Item Class:`-Kopfzeile, ausgehend von
# ``models.item_category()``. Eine feste Tabelle, KEINE
# Pluralisierungsregel: Die Klassennamen des Spiels lassen sich nicht
# ableiten, sie muss man auswendig hinterlegen. "One Handed Sword" heißt
# als Klasse "One Hand Swords" (nicht "One Handed Swords"), "Staff" wird
# zu "Staves", "Helmet" zu "Helmets" — drei verschiedene Muster in drei
# Zeilen. Dieselbe Erkenntnis hatte schon der erste, wieder verworfene
# Anlauf 2026-07-31 (FALLSTRICKE #50).
#
# Was hier fehlt, bleibt WEG statt geraten zu werden: Die Zeile ist für
# Path of Building ohnehin entbehrlich (der Parser leitet die Klasse aus
# dem Basistyp ab und überliest sie), ein falscher Wert wäre also nur
# Ballast mit Fehlerpotenzial. "Flask" steht deshalb NICHT drin — PoE
# unterscheidet dort vier Klassen (Life/Mana/Hybrid/Utility Flasks), und
# unsere Kategorie kennt die Unterscheidung nicht.
_ITEM_CLASS_NAMES = {
    "Ring": "Rings", "Amulet": "Amulets", "Belt": "Belts",
    "Helmet": "Helmets", "Body Armour": "Body Armours",
    "Gloves": "Gloves", "Boots": "Boots", "Shield": "Shields",
    "Quiver": "Quivers", "Jewel": "Jewels",
    "Bow": "Bows", "Claw": "Claws", "Dagger": "Daggers",
    "Rune Dagger": "Rune Daggers", "Wand": "Wands", "Sceptre": "Sceptres",
    "Staff": "Staves", "Warstaff": "Warstaves", "Fishing Rod": "Fishing Rods",
    "One Handed Axe": "One Hand Axes", "One Handed Mace": "One Hand Maces",
    "One Handed Sword": "One Hand Swords",
    "Thrusting One Handed Sword": "Thrusting One Hand Swords",
    "Two Handed Axe": "Two Hand Axes", "Two Handed Mace": "Two Hand Maces",
    "Two Handed Sword": "Two Hand Swords",
}

_SECTION_SEPARATOR = "--------"

# Die Zusatz-Mod-Listen (Verzauberung, Flaschen-Effekt, …) stehen in
# ``models`` — das Detail-Panel braucht dieselbe Liste. Beim ersten
# Export fehlten sie, aufgefallen erst beim Vergleich mit echtem PoB.


def _export_property_lines(item: Item) -> list[str]:
    """Eigenschaften wie im Spiel, inklusive " (augmented)" hinter
    aufgewerteten Werten.

    Der zweite Eintrag je Wert (``["+20%", 1]``) ist GGGs Formathinweis.
    Dass die 1 genau "aufgewertet" bedeutet, ist an Peters echtem Cache
    abgelesen und nicht geraten: An einem Sceptre trugen Qualität (+20 %
    durch Currency) und Physischer Schaden (durch Affix erhöht) die 1,
    die unveränderte Kritische Trefferchance die 0."""
    lines = []
    for index, prop in enumerate(item.properties):
        # Die Waffenklasse als wertlose erste Eigenschaft überspringen:
        # GGG führt sie dort, im Spieltext steht sie ausschließlich in der
        # `Item Class:`-Kopfzeile. Ohne diese Zeile stünde bei jedem
        # Sceptre ein nacktes "Sceptre" zwischen den Eigenschaften, das
        # PoBs Parser als Mod-Zeile vorgesetzt bekäme.
        if index == 0 and not prop.values and prop.name in WEAPON_CLASSES:
            continue
        text = prop.display_text
        if not text:
            continue
        try:
            augmented = prop.values[0][1] == 1
        except (IndexError, TypeError):
            augmented = False
        lines.append(f"{text} (augmented)" if augmented and "{" not in prop.name else text)
    return lines


def item_export_text(item: Item) -> str:
    """Ein Item in PoEs eigenem Item-Textformat — dasselbe, was das Spiel
    bei Strg+C in die Zwischenablage legt, und damit das, was Path of
    Building beim Einfügen erwartet.

    Wunsch von Peters Betatester (2026-08-12): "Kann man eigentlich von da
    in den Path of Building rein copypasten?" Der Nutzen liegt bei
    STASH-Items: Charaktere importiert PoB selbst von GGGs Seite, an die
    Truhe kommt es nicht heran — "wäre dieser Ring ein Upgrade?" ist
    genau die Lücke.

    **Warum das hier geht und bei Craft of Exile nicht** (FALLSTRICKE
    #50, wo ein sehr ähnlich aussehender Export wieder ausgebaut wurde):
    CoE verlangt das Strg+ALT+C-Format ("Advanced mod descriptions") mit
    Mod-Tags, Tier und Wertspanne je Zeile — Daten, die GGGs API
    nachweislich nie liefert, weshalb der Import dort IMMER scheiterte.
    PoBs eigener Hilfetext nennt dagegen ausdrücklich Strg+C, das
    schlichte Item-Textformat. Dessen Bestandteile haben wir vollständig.

    Aufbau, Abschnitte durch ``--------`` getrennt, in der Reihenfolge des
    Spiels: Klasse und Rarität, Name (bei Rare/Unique zwei Zeilen: Eigen-
    und Basisname), Eigenschaften, Anforderungen, Sockel, Item-Level,
    implizite Mods, explizite Mods, Zustandszeilen.

    Leere Abschnitte fallen weg — ein Ring ohne Sockel bekommt keine
    leere Sockelzeile und keinen doppelten Trenner."""
    head = []
    class_name = _ITEM_CLASS_NAMES.get(item_category(item) or "")
    if class_name:
        head.append(f"Item Class: {class_name}")
    rarity = FRAME_TYPE_NAMES.get(item.frameType)
    if rarity:
        head.append(f"Rarity: {rarity}")
    # Bei Rare und Unique trägt ``name`` den gewürfelten bzw. Eigennamen
    # und ``baseType`` die Basis — das Spiel schreibt beide untereinander.
    # Sonst gibt es nur eine Zeile (``typeLine`` enthält bei Magic-Items
    # bereits die Affix-Bezeichnung, genau wie im Spiel).
    if item.name:
        head.append(item.name)
        head.append(item.baseType or item.typeLine)
    else:
        head.append(item.typeLine or item.baseType)

    sections: list[list[str]] = [head, _export_property_lines(item)]

    requirements = [prop.display_text for prop in item.requirements if prop.display_text]
    if requirements:
        sections.append(["Requirements:"] + requirements)
    if item.socket_string:
        sections.append([f"Sockets: {item.socket_string}"])
    if item.ilvl:
        sections.append([f"Item Level: {item.ilvl}"])
    # Verzauberungen stehen im Spieltext VOR den impliziten Mods und
    # bekommen einen eigenen Abschnitt — PoB zählt sie zu den Implicits.
    sections.append(extra_mod_lines(item, ENCHANT_MOD_FIELD))
    if item.implicit_mods:
        sections.append(list(item.implicit_mods))
    # Die übrigen Mod-Listen hängen an den expliziten statt eigene
    # Abschnitte zu bekommen: Wo genau das Spiel eine Utility-Flasche oder
    # einen Logbuch-Mod abtrennt, ist nicht nachgeprüft — und eine
    # geratene Abschnittsgrenze wäre schlechter als eine Zeile zu viel im
    # richtigen Block. Verloren gehen darf keine davon.
    weitere = all_extra_mod_lines(item)
    if item.explicit_mods or weitere:
        sections.append(list(item.explicit_mods) + weitere)

    state = []
    if not item.identified:
        state.append("Unidentified")
    if item.corrupted:
        state.append("Corrupted")
    if state:
        sections.append(state)

    body = f"\n{_SECTION_SEPARATOR}\n".join(
        "\n".join(lines) for lines in sections if lines)
    return body + "\n"


def _card_art_word(word: str) -> str:
    cleaned = "".join(ch for ch in word if ch.isalnum())
    return cleaned[:1].upper() + cleaned[1:].lower()


def divination_card_art_url(item: Item) -> str | None:
    """Reales Artwork einer Divination Card statt des von GGGs Stash-API
    gelieferten Icons — das ist für JEDE Karte identisch (immer derselbe
    generische Kartenrücken, ``2DItems/Divination/InventoryIcon.png``,
    real geprüft an Peters Stash-Cache, 2026-07-31) und deshalb für eine
    vergrößerte Ansicht wertlos.

    Den Dateinamen liefert die API selbst mit (``artFilename``, real
    geprüft an allen 976 Karten in Peters Cache) — er ist maßgeblich und
    wird bevorzugt. Der Name der Karte taugt NICHT als Ersatz dafür: Bei
    28 von 373 Kartentypen weichen beide voneinander ab, teils bis zur
    Unkenntlichkeit ("Mawr Blaidd" -> "RussiaDivinationCard", "The
    Cartographer" -> "TheMapmaker", "Rebirth" -> "BirthOfTheThree"), teils
    durch Tippfehler auf GGGs Seite ("Light and Truth" ->
    "LigthAndTruth"). Live gegen das CDN geprüft (2026-08-06): der aus dem
    Namen gebaute Pfad liefert dort 404, der aus ``artFilename`` gebaute
    200 — die Karte blieb also ohne Artwork.

    Nur wenn ``artFilename`` fehlt, wird der Name umgeformt: PascalCase
    ohne Trenner, live an zehn echten Karten verifiziert — Leerzeichen
    verschwinden, jedes Wort wird groß geschrieben, AUCH kleine Füllwörter
    ("of" -> "Of", "Rain of Chaos" -> "RainOfChaos"), und Satzzeichen
    INNERHALB eines Wortes fallen weg, ohne das Wort zu zerteilen
    ("Hunter's Reward" -> "HuntersReward", NICHT "HunterSReward" — das
    Apostroph trennt kein neues Wort ab)."""
    if item.frameType != 6:
        return None
    slug = item.artFilename.strip() or "".join(
        _card_art_word(word) for word in item.display_name.split())
    return f"{_DIVINATION_CARD_ART_BASE}/{slug}.png" if slug else None
