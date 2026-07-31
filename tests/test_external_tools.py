"""Tests für die Rechtsklick-Verlinkung externer Tools (ToDo.md: "andere
Tools per Rechtsklick anbinden?"). Reine URL-/Text-Bausteine, siehe
poe_view/ui/external_tools.py — keine Qt-Abhängigkeit, kein Mocking nötig."""

from poe_view.api.models import Item
from poe_view.ui import external_tools


def _item(**kwargs) -> Item:
    return Item.model_validate(kwargs)


# --- poedb_url / wiki_url: Original-Schreibweise, Unterstrich statt Leerzeichen ---

def test_poedb_url_uses_the_unique_name_with_underscores() -> None:
    item = _item(name="Tabula Rasa", typeLine="Simple Robe", baseType="Simple Robe", frameType=3)
    assert external_tools.poedb_url(item) == "https://poedb.tw/us/Tabula_Rasa"


def test_poedb_url_falls_back_to_the_base_type_without_a_unique_name() -> None:
    item = _item(typeLine="Vaal Regalia", baseType="Vaal Regalia", frameType=2)
    assert external_tools.poedb_url(item) == "https://poedb.tw/us/Vaal_Regalia"


def test_poedb_url_keeps_apostrophes_unlike_the_ninja_slug() -> None:
    item = _item(typeLine="Hinekora's Lock", baseType="Hinekora's Lock", frameType=5)
    assert external_tools.poedb_url(item) == "https://poedb.tw/us/Hinekora's_Lock"


def test_wiki_url_uses_the_same_underscore_convention() -> None:
    item = _item(name="Tabula Rasa", typeLine="Simple Robe", baseType="Simple Robe", frameType=3)
    assert external_tools.wiki_url(item) == "https://www.poewiki.net/wiki/Tabula_Rasa"


# --- ninja_url: nur für Currency, bestätigtes Deep-Link-Schema ---

def test_ninja_url_builds_the_confirmed_currency_deep_link() -> None:
    item = _item(typeLine="Hinekora's Lock", baseType="Hinekora's Lock", frameType=5)
    assert (external_tools.ninja_url(item, "Allflame")
            == "https://poe.ninja/poe1/economy/allflame/currency/hinekoras-lock")


def test_ninja_url_lowercases_and_hyphenates_a_multi_word_league() -> None:
    item = _item(typeLine="Chaos Orb", baseType="Chaos Orb", frameType=5)
    assert (external_tools.ninja_url(item, "Hardcore Allflame")
            == "https://poe.ninja/poe1/economy/hardcore-allflame/currency/chaos-orb")


def test_ninja_url_is_none_for_non_currency_items() -> None:
    item = _item(name="Tabula Rasa", typeLine="Simple Robe", baseType="Simple Robe", frameType=3)
    assert external_tools.ninja_url(item, "Standard") is None


def test_ninja_url_is_none_without_a_known_league() -> None:
    item = _item(typeLine="Chaos Orb", baseType="Chaos Orb", frameType=5)
    assert external_tools.ninja_url(item, "") is None


# --- divination_card_art_url: GGGs eigenes CDN, live an poedb.tw verifiziert ---

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
