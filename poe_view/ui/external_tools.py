"""Rechtsklick-Verlinkung zu externen Item-Tools (ToDo.md: "andere Tools
per Rechtsklick anbinden? PoEdb.tw, poe.ninja, craftofexile").

Reine URL-Bausteine ohne Qt-Abhängigkeit — ``main_window.py`` verkabelt
sie an das Rechtsklick-Kontextmenü der Item-Tabelle.

Die Menüeinträge sind seit Peters Idee (2026-08-01, "Rechtsklick-Menü ist
variabel") konfigurierbar: statt fest verdrahteter Funktionen pro Anbieter
gibt es eine Liste von ``ToolEntry`` (Name + URL-Vorlage mit ``{slug}``-
Platzhalter), die Peter über den Settings-Dialog (``settings_dialog.py``)
bearbeiten kann — z. B. um ein eigenes Wiki einzutragen oder einen
Eintrag zu deaktivieren, falls ein Seitenbetreiber widerspricht (ToDo.md:
"Seitenbetreiber unbedingt fragen"). ``DEFAULT_TOOLS`` liefert die
bisherigen zwei Einträge (PoEDB, PoE Wiki) als Startbelegung.

poe.ninja (frameType-5-Deep-Link) wurde dabei erst einmal herausgenommen
(Peter, 2026-08-01): das URL-Schema braucht zwei Werte (Liga + Item-Slug
in einer anderen Slug-Konvention als PoEDB/Wiki) und passt nicht ins
einfache Ein-Platzhalter-Schema der übrigen Tools. Bleibt ein eigenes,
späteres Vorhaben, falls das generische Schema um ein zweites Feld
erweitert wird.

Ein vierter, ursprünglich geplanter Eintrag (Craft of Exile) wurde wieder
entfernt (FALLSTRICKE #50): CoE erwartet fürs Item-Import "Advanced mod
descriptions" mit einer Tag-Kopfzeile pro Mod und einer Wertspanne statt
des Wälzwerts — Daten, die GGGs API nachweislich nie liefert (echte
Stash-Cache-Dumps geprüft: kein Item trägt je ein "extended"-Feld mit
Mod-Tags/Tier/Spanne). Ohne die Kopfzeile lehnt CoE den Import komplett
ab, nicht nur ungenau. Peters Entscheidung (2026-07-31): Eintrag raus,
bis eine externe Mod-Datenbank (z. B. RePoE) als eigenes, größeres
Vorhaben ansteht.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from poe_view.api.models import Item

# GGGs eigene CDN — kein Drittanbieter, deshalb ohne die "Seitenbetreiber
# fragen"-Vorsicht der konfigurierbaren Tools (ToDo.md). Muster live an
# poedb.tw-Kartenseiten verifiziert (2026-07-31): jede Div-Card-Seite
# bettet ihr Artwork von genau hier ein.
_DIVINATION_CARD_ART_BASE = "https://web.poecdn.com/image/divination-card"


@dataclass
class ToolEntry:
    """Ein konfigurierbarer Rechtsklick-Menüeintrag. ``url_template``
    enthält genau einen Platzhalter ``{slug}``, der durch den Item-Namen
    ersetzt wird (siehe ``build_url``)."""

    name: str
    url_template: str
    enabled: bool = True


# Startbelegung des Settings-Dialogs bzw. Fallback, solange QSettings noch
# keinen eigenen Stand gespeichert hat.
DEFAULT_TOOLS: tuple[ToolEntry, ...] = (
    ToolEntry("PoEDB", "https://poedb.tw/us/{slug}"),
    ToolEntry("PoE Wiki", "https://www.poewiki.net/wiki/{slug}"),
)


def _underscore_name(text: str) -> str:
    """MediaWiki-Konvention — real geprüft: "Essence_Drain", "Chaos_Bolt".
    Apostrophe & Co. bleiben erhalten, das sind gültige URL-Zeichen.
    Klammern werden dagegen prozent-kodiert (Peter, 2026-08-01: Karten wie
    "Map (Tier 16)" gaben über unser Menü einen 404, obwohl PoEDBs eigene
    Suche dieselbe Seite fand) — PoEDBs Server verlangt "%28"/"%29" statt
    literaler Klammern im Pfad, live bestätigt: poedb.tw/us/Map_(Tier_16)
    → 404, poedb.tw/us/Map_%28Tier_16%29 → 200 (aus PoEDBs eigenem
    Autocomplete-Suchindex ausgelesen). poewiki.net akzeptiert dagegen
    BEIDE Schreibweisen, die Kodierung schadet also dort nicht. Siehe
    FALLSTRICKE #57."""
    slug = text.strip().replace(" ", "_")
    return slug.replace("(", "%28").replace(")", "%29")


def _lookup_name(item: Item) -> str:
    """Nur Uniques (frameType 3) haben einen auf PoEDB/Wiki gezielt
    such- und verlinkbaren Eigennamen (Peter, 2026-08-01: "Uniques können
    jedoch gezielt gesucht werden"). Rares TRAGEN zwar auch einen
    ``name``, aber der ist eine zufällig gewürfelte Fantasiebezeichnung
    ohne eigene Wiki-Seite ("PoEdb findet viele Items nicht unter dem
    Eigennamen (Rare, Magic)") — real an Peters Cache geprüft: ``name``
    z. B. "Vortex Bane" für ein Rare-Messer, während ``baseType``
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
    Weitere Platzhalter gibt es bewusst nicht — das deckt PoEDB/
    Wiki-artige Ein-Wert-Schemas ab, siehe Modul-Docstring."""
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
