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

Ein ursprünglich geplanter Sonderfall (Zwischenablage-Export statt Link)
wurde wieder entfernt (FALLSTRICKE #50): das Zielwerkzeug erwartete
Mod-Tags, Tier und Wertspannen, die GGGs API nachweislich nie liefert
(echte Stash-Cache-Dumps geprüft: kein Item trägt je ein "extended"-Feld
damit) und lehnte den Import ohne sie komplett ab statt nur ungenau zu
sein. Kommt frühestens mit einer externen Mod-Datenbank (z. B. RePoE)
wieder in Frage — ein eigenes, größeres Vorhaben.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from poe_view.api.models import Item

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


def _lookup_name(item: Item) -> str:
    """Nur Uniques (frameType 3) haben einen Eigennamen, unter dem sich ein
    Item in einem Nachschlagewerk gezielt finden lässt (Peter, 2026-08-01:
    "Uniques können jedoch gezielt gesucht werden"). Rares TRAGEN zwar auch
    einen ``name``, aber der ist eine zufällig gewürfelte
    Fantasiebezeichnung ohne eigene Seite — real an Peters Cache geprüft:
    ``name`` z. B. "Vortex Bane" für ein Rare-Messer, während ``baseType``
    zuverlässig den Basis-Typ trägt ("Gutting Knife"). Magic-Items haben
    gar keinen ``name``, aber ihr ``typeLine`` enthält die gewürfelten
    Präfix-/Suffix-Wörter mit im Text ("Fleet Citrine Amulet of the
    Flatworm") — auch hier ist ``baseType`` die bereinigte Fassung
    ("Citrine Amulet"). Für alle anderen Rarities (Normal, Gems, Currency,
    Divination Cards, …) ist ``baseType`` ohnehin schon der Anzeigename
    (real geprüft, keine Affixe möglich)."""
    if item.frameType == 3 and item.name:
        return item.name
    return item.baseType or item.typeLine or item.name or "?"


def build_url(entry: ToolEntry, item: Item) -> str:
    """``{slug}`` in der Vorlage durch den (nach Rarity passenden, siehe
    ``_lookup_name``) Item-Namen ersetzen (Leerzeichen -> Unterstrich).
    Weitere Platzhalter gibt es bewusst nicht — das deckt Ein-Wert-Schemas
    ab, wie sie MediaWiki-artige Seiten nutzen, siehe Modul-Docstring."""
    return entry.url_template.replace("{slug}", _underscore_name(_lookup_name(item)))


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


def _card_art_word(word: str) -> str:
    cleaned = "".join(ch for ch in word if ch.isalnum())
    return cleaned[:1].upper() + cleaned[1:].lower()


def divination_card_art_url(item: Item) -> str | None:
    """Reales Artwork einer Divination Card statt des von GGGs Stash-API
    gelieferten Icons — das ist für JEDE Karte identisch (immer derselbe
    generische Kartenrücken, ``2DItems/Divination/InventoryIcon.png``,
    real geprüft an Peters Stash-Cache, 2026-07-31) und deshalb für eine
    vergrößerte Ansicht wertlos.

    URL-Muster PascalCase ohne Trenner, live an zehn echten Karten
    verifiziert: Leerzeichen verschwinden, jedes Wort wird groß
    geschrieben — AUCH kleine Füllwörter ("of" -> "Of", "Rain of Chaos" ->
    "RainOfChaos") — und Satzzeichen INNERHALB eines Wortes fallen weg,
    ohne das Wort zu zerteilen ("Hunter's Reward" -> "HuntersReward",
    NICHT "HunterSReward" — das Apostroph trennt kein neues Wort ab)."""
    if item.frameType != 6:
        return None
    slug = "".join(_card_art_word(word) for word in item.display_name.split())
    return f"{_DIVINATION_CARD_ART_BASE}/{slug}.png" if slug else None
