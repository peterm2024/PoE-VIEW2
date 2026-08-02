"""Tests für die konfigurierbare Rechtsklick-Verlinkung eigener
Nachschlagewerke. Reine URL-/Text-Bausteine, siehe
poe_view/ui/external_tools.py — keine Qt-Abhängigkeit, kein Mocking nötig.

Die Tests nutzen durchweg einen neutralen Beispiel-Host: PoE-VIEW2 bringt
ab Werk keine Seite mehr mit (Peter, 2026-08-02), die Slug-Regeln gelten
unabhängig vom konkreten Ziel."""

from poe_view.api.models import Item
from poe_view.ui import external_tools
from poe_view.ui.external_tools import ToolEntry

_TEMPLATE = "https://example.test/wiki/{slug}"


def _item(**kwargs) -> Item:
    return Item.model_validate(kwargs)


def _url(item: Item) -> str:
    return external_tools.build_url(ToolEntry("Example", _TEMPLATE), item)


# --- build_url: {slug}-Platzhalter, Original-Schreibweise, Unterstrich statt Leerzeichen ---

def test_build_url_uses_the_unique_name_for_uniques() -> None:
    item = _item(name="Tabula Rasa", typeLine="Simple Robe", baseType="Simple Robe", frameType=3)
    assert _url(item) == "https://example.test/wiki/Tabula_Rasa"


def test_build_url_keeps_apostrophes_in_a_unique_name() -> None:
    item = _item(name="Hinekora's Lock", typeLine="Hinekora's Lock", baseType="Hinekora's Lock", frameType=3)
    assert _url(item) == "https://example.test/wiki/Hinekora's_Lock"


def test_build_url_uses_the_base_type_without_a_unique_name() -> None:
    item = _item(typeLine="Vaal Regalia", baseType="Vaal Regalia", frameType=2)
    assert _url(item) == "https://example.test/wiki/Vaal_Regalia"


# --- Rare/Magic: der zufällig gewürfelte Name hat nirgends eine eigene
# --- Seite, also nach dem Base-Typ verlinken (Peter, 2026-08-01) ---

def test_build_url_uses_the_base_type_for_a_rare_item_ignoring_its_flavour_name() -> None:
    """Reales Beispiel aus Peters Cache: Rare-Messer "Vortex Bane" hat
    keine eigene Nachschlage-Seite, "Gutting Knife" (der Base-Typ) schon."""
    item = _item(name="Vortex Bane", typeLine="Gutting Knife", baseType="Gutting Knife", frameType=2)
    assert _url(item) == "https://example.test/wiki/Gutting_Knife"


def test_build_url_uses_the_base_type_for_a_magic_item_stripping_affixes() -> None:
    """Reales Beispiel: ``typeLine`` trägt die gewürfelten Affixe mit im
    Text, ``baseType`` ist die bereinigte Fassung ohne Präfix/Suffix."""
    item = _item(typeLine="Fleet Citrine Amulet of the Flatworm", baseType="Citrine Amulet", frameType=1)
    assert _url(item) == "https://example.test/wiki/Citrine_Amulet"


# --- Klammern werden prozent-kodiert (Peter, 2026-08-01: "Map (Tier 16)"
# --- gab bei einem real getesteten Nachschlagewerk einen 404) ---

def test_build_url_percent_encodes_parentheses_in_a_map_tier_name() -> None:
    """Mindestens ein real getesteter Server lehnt literale Klammern im
    Pfad ab (404) und verlangt "%28"/"%29"; MediaWiki akzeptiert beide
    Formen, die Kodierung ist also universell unschädlich."""
    item = _item(typeLine="Map (Tier 16)", baseType="Map (Tier 16)", frameType=0)
    assert _url(item) == "https://example.test/wiki/Map_%28Tier_16%29"


def test_build_url_percent_encodes_parentheses_for_a_magic_map_too() -> None:
    """Magic-Karten laufen über _lookup_name() auf baseType — auch dort
    steckt "(Tier N)" drin, real an Peters Cache geprüft."""
    item = _item(typeLine="Fleet Map of the Flatworm (Tier 5)", baseType="Map (Tier 5)", frameType=1)
    assert _url(item) == "https://example.test/wiki/Map_%28Tier_5%29"


# --- DEFAULT_TOOLS: ab Werk bewusst leer ---

def test_no_tools_are_preconfigured_out_of_the_box() -> None:
    """Peter, 2026-08-02: "Wir nehmen das komplett raus ... Damit sind wir
    hier komplett unabhängig von Internetseiten." Ohne Vorbelegung
    kontaktiert PoE-VIEW2 von sich aus keine Drittanbieter-Seite; wer
    einen Eintrag anlegt, entscheidet das bewusst selbst."""
    assert external_tools.DEFAULT_TOOLS == ()


# --- tools_to_json / tools_from_json: Persistenz über QSettings ---

def test_json_roundtrip_preserves_all_fields() -> None:
    entries = [ToolEntry("Custom Wiki", "https://example.test/{slug}", enabled=False)]
    restored = external_tools.tools_from_json(external_tools.tools_to_json(entries))
    assert restored == entries


def test_tools_from_json_falls_back_to_defaults_when_empty() -> None:
    assert external_tools.tools_from_json(None) == list(external_tools.DEFAULT_TOOLS)
    assert external_tools.tools_from_json("") == list(external_tools.DEFAULT_TOOLS)


def test_tools_from_json_falls_back_to_defaults_on_garbage() -> None:
    assert external_tools.tools_from_json("{not json") == list(external_tools.DEFAULT_TOOLS)


def test_deliberately_emptied_list_is_preserved_not_refilled() -> None:
    """Löscht der Nutzer alle Einträge im Settings-Dialog, wird "[]"
    gespeichert — das ist eine bewusste Wahl und darf nicht als "noch nie
    konfiguriert" gedeutet und aus DEFAULT_TOOLS neu befüllt werden. Mit
    der heutigen leeren Vorbelegung fällt beides zusammen; der Test hält
    die Unterscheidung fest, falls je wieder etwas vorbelegt wird."""
    assert external_tools.tools_from_json(external_tools.tools_to_json([])) == []


# --- divination_card_art_url: GGGs eigenes CDN, an echten Karten verifiziert ---

def _card(name: str) -> Item:
    return _item(name=name, typeLine=name, baseType=name, frameType=6)


def test_card_art_url_for_a_simple_two_word_name() -> None:
    assert (external_tools.divination_card_art_url(_card("The Doctor"))
            == "https://web.poecdn.com/image/divination-card/TheDoctor.png")


def test_card_art_url_capitalises_lowercase_filler_words() -> None:
    assert (external_tools.divination_card_art_url(_card("Rain of Chaos"))
            == "https://web.poecdn.com/image/divination-card/RainOfChaos.png")


def test_card_art_url_drops_apostrophes_without_splitting_the_word() -> None:
    """Reales Gegenbeispiel wäre "HunterSReward" (Apostroph als
    Worttrenner) — das Muster ist aber "HuntersReward", live bestätigt."""
    assert (external_tools.divination_card_art_url(_card("Hunter's Reward"))
            == "https://web.poecdn.com/image/divination-card/HuntersReward.png")
    assert (external_tools.divination_card_art_url(_card("The Saint's Treasure"))
            == "https://web.poecdn.com/image/divination-card/TheSaintsTreasure.png")


def test_card_art_url_handles_more_than_two_words() -> None:
    assert (external_tools.divination_card_art_url(_card("A Dab of Ink"))
            == "https://web.poecdn.com/image/divination-card/ADabOfInk.png")
    assert (external_tools.divination_card_art_url(_card("Chaotic Disposition"))
            == "https://web.poecdn.com/image/divination-card/ChaoticDisposition.png")


def test_card_art_url_is_none_for_non_divination_card_items() -> None:
    assert external_tools.divination_card_art_url(_item(typeLine="Chaos Orb", frameType=5)) is None
