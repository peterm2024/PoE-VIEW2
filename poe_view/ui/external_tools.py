"""Rechtsklick-Verlinkung zu externen Item-Tools (ToDo.md: "andere Tools
per Rechtsklick anbinden? PoEdb.tw, poe.ninja, craftofexile").

Reine URL-Bausteine ohne Qt-Abhängigkeit — ``main_window.py`` verkabelt
sie an den Rechtsklick-Kontextmenü der Item-Tabelle.

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

import re

from poe_view.api.models import Item

_POEDB_BASE = "https://poedb.tw/us/"
_WIKI_BASE = "https://www.poewiki.net/wiki/"
_NINJA_BASE = "https://poe.ninja/poe1/economy"

# GGGs eigene CDN — kein Drittanbieter, deshalb ohne die "Seitenbetreiber
# fragen"-Vorsicht der anderen drei Tools (ToDo.md). Muster live an
# poedb.tw-Kartenseiten verifiziert (2026-07-31): jede Div-Card-Seite
# bettet ihr Artwork von genau hier ein.
_DIVINATION_CARD_ART_BASE = "https://web.poecdn.com/image/divination-card"


def _underscore_name(text: str) -> str:
    """PoEDB/Wiki: Original-Schreibweise, nur Leerzeichen -> Unterstrich
    (MediaWiki-Konvention — real geprüft: "Essence_Drain", "Chaos_Bolt").
    Apostrophe & Co. bleiben erhalten, das sind gültige URL-Zeichen."""
    return text.strip().replace(" ", "_")


def _ninja_slug(text: str) -> str:
    """poe.ninja: alles klein, Satzzeichen entfernt, Leerzeichen ->
    Bindestrich — bestätigtes Beispiel (Peter, 2026-07-30):
    "Hinekora's Lock" -> "hinekoras-lock" (NICHT "hinekora-s-lock",
    das Apostroph verschwindet ersatzlos statt einen Bindestrich zu
    hinterlassen)."""
    cleaned = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s+", "-", cleaned.strip())


def poedb_url(item: Item) -> str:
    return _POEDB_BASE + _underscore_name(item.display_name)


def wiki_url(item: Item) -> str:
    return _WIKI_BASE + _underscore_name(item.display_name)


def ninja_url(item: Item, league: str) -> str | None:
    """Deep-Link auf poe.ninjas Item-Detailseite — nur für Currency/
    Fragmente (frameType 5), das einzige real bestätigte URL-Schema
    (Peters Link https://poe.ninja/poe1/economy/allflame/currency/
    hinekoras-lock, 2026-07-30). Für andere Kategorien (Uniques, Gems, …)
    ist das Website-Schema unbestätigt — lieber kein Link als ein
    falscher, der ins Leere führt."""
    if item.frameType != 5 or not league:
        return None
    return f"{_NINJA_BASE}/{_ninja_slug(league)}/currency/{_ninja_slug(item.display_name)}"


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
