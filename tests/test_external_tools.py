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


def test_card_art_url_prefers_the_filename_the_api_delivers() -> None:
    """Die aus dem Namen gebauten Pfade oben stimmen — bei 345 von 373
    Kartentypen. Die restlichen 28 heissen auf dem CDN voellig anders, und
    dort liefert GGGs eigenes ``artFilename`` die einzige richtige
    Antwort. Alle vier Faelle stammen aus Peters Cache und sind am
    2026-08-06 live gegen das CDN geprueft: mit dem konstruierten Namen
    404, mit ``artFilename`` 200."""
    for name, art_filename in (
        ("Mawr Blaidd", "RussiaDivinationCard"),    # gar kein Bezug zum Namen
        ("The Cartographer", "TheMapmaker"),        # frueherer Kartenname
        ("Rebirth", "BirthOfTheThree"),             # frueherer Kartenname
        ("Light and Truth", "LigthAndTruth"),       # Tippfehler auf GGGs Seite
    ):
        card = _item(name=name, typeLine=name, baseType=name, frameType=6,
                    artFilename=art_filename)
        assert (external_tools.divination_card_art_url(card)
                == f"https://web.poecdn.com/image/divination-card/{art_filename}.png")


def test_card_art_url_falls_back_to_the_name_without_artfilename() -> None:
    """``artFilename`` kam an allen 976 Karten im Cache vor, aber die
    Rekonstruktion bleibt als Rueckfallebene stehen: Ein Feld, das die API
    einmal weglaesst, soll kein Artwork kosten. Ein leeres Feld zaehlt
    dabei wie ein fehlendes."""
    card = _item(name="The Doctor", typeLine="The Doctor", baseType="The Doctor",
                frameType=6, artFilename="   ")
    assert (external_tools.divination_card_art_url(card)
            == "https://web.poecdn.com/image/divination-card/TheDoctor.png")


# --- Item-Textexport fuer Path of Building (ARCHITEKTUR.md §4.38) ------ #

def _sceptre() -> Item:
    """Eine echte Waffe aus Peters Cache, auf das Noetige gekuerzt — samt
    der wertlosen ersten Property, in der GGG die Waffenklasse fuehrt."""
    return Item.model_validate({
        "name": "Soul Bane", "typeLine": "Opal Sceptre", "baseType": "Opal Sceptre",
        "frameType": 2, "ilvl": 70, "identified": True,
        "properties": [
            {"name": "Sceptre", "values": []},
            {"name": "Quality", "values": [["+20%", 1]]},
            {"name": "Critical Strike Chance", "values": [["8.00%", 0]]},
        ],
        "requirements": [
            {"name": "Level", "values": [["68", 0]]},
            {"name": "Str", "values": [["95", 0]]},
        ],
        "sockets": [{"group": 0, "sColour": "W"}, {"group": 1, "sColour": "W"}],
        "implicitMods": ["40% increased Elemental Damage"],
        "explicitMods": ["69% increased Fire Damage", "+109 to maximum Mana"],
    })


def test_the_item_text_follows_the_games_own_format() -> None:
    """Genau das Format, das PoE bei Strg+C in die Zwischenablage legt —
    denn genau das erwartet Path of Building beim Einfuegen (sein eigener
    Hilfetext nennt Strg+C ausdruecklich)."""
    text = external_tools.item_export_text(_sceptre())

    assert text.startswith("Item Class: Sceptres\nRarity: Rare\n"
                           "Soul Bane\nOpal Sceptre\n--------\n")
    assert "Requirements:\nLevel: 68\nStr: 95" in text
    assert "Sockets: W W" in text
    assert "Item Level: 70" in text
    # Implizite und explizite Mods in GETRENNTEN Abschnitten — daran
    # unterscheidet PoBs Parser die beiden Sorten.
    assert ("40% increased Elemental Damage\n--------\n"
            "69% increased Fire Damage") in text


def test_the_weapon_class_property_does_not_become_a_mod_line() -> None:
    """GGG fuehrt die Waffenklasse als wertlose erste Property. Im
    Spieltext steht sie ausschliesslich in der Kopfzeile — bliebe sie
    stehen, bekaeme PoBs Parser ein nacktes "Sceptre" zwischen den
    Eigenschaften vorgesetzt."""
    text = external_tools.item_export_text(_sceptre())

    assert "Item Class: Sceptres" in text
    assert "\nSceptre\n" not in text


def test_augmented_values_are_marked_like_in_game() -> None:
    """Der zweite Eintrag je Wert ist GGGs Formathinweis; die 1 bedeutet
    "aufgewertet" (an Peters echtem Cache abgelesen: Qualitaet und
    per Affix erhoehter Schaden tragen sie, die unveraenderte kritische
    Trefferchance nicht)."""
    text = external_tools.item_export_text(_sceptre())

    assert "Quality: +20% (augmented)" in text
    assert "Critical Strike Chance: 8.00%\n" in text


def test_an_item_without_sockets_or_mods_has_no_empty_sections() -> None:
    """Ein leerer Abschnitt wuerde als doppelter Trenner erscheinen und
    PoB eine Mod-Zeile ohne Inhalt vorsetzen."""
    text = external_tools.item_export_text(
        Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5}))

    assert "--------\n--------" not in text
    assert "Sockets:" not in text
    assert text.startswith("Rarity: Currency\nChaos Orb")


def test_magic_and_normal_items_get_a_single_name_line() -> None:
    """Nur Rare und Unique tragen einen Eigennamen ueber der Basis. Bei
    Magic steckt der Affix-Text bereits in typeLine, genau wie im Spiel —
    eine zweite Zeile waere dort eine Dopplung."""
    text = external_tools.item_export_text(Item.model_validate({
        "typeLine": "Sanctified Ruby Ring of the Flatworm",
        "baseType": "Ruby Ring", "frameType": 1}))

    # Ohne Eigenschaften, Sockel und Mods bleibt es beim Kopf allein —
    # kein Trenner ohne einen Abschnitt dahinter.
    assert text == ("Item Class: Rings\nRarity: Magic\n"
                    "Sanctified Ruby Ring of the Flatworm\n")


def test_state_lines_come_last() -> None:
    """"Unidentified" und "Corrupted" stehen im Spieltext ganz unten."""
    text = external_tools.item_export_text(Item.model_validate({
        "name": "Dread Veil", "baseType": "Lion Pelt", "frameType": 2,
        "identified": False, "corrupted": True}))

    assert text.endswith("--------\nUnidentified\nCorrupted\n")


def test_a_flask_gets_no_guessed_item_class() -> None:
    """PoE unterscheidet vier Flaschen-Klassen (Life/Mana/Hybrid/Utility),
    unsere Kategorie kennt nur "Flask". Lieber keine Kopfzeile als eine
    falsche — PoB leitet die Klasse ohnehin aus dem Basistyp ab."""
    text = external_tools.item_export_text(Item.model_validate({
        "typeLine": "Divine Life Flask", "baseType": "Divine Life Flask",
        "frameType": 0}))

    assert "Item Class:" not in text
    assert text.startswith("Rarity: Normal\nDivine Life Flask")


def test_enchantments_and_utility_mods_are_not_lost() -> None:
    """Beim ersten Anlauf exportiert wurden nur explicitMods und
    implicitMods — aufgefallen erst beim Vergleich mit PoB. In Peters
    echtem Bestand tragen 2274 Items eine ``enchantMods``-Zeile und 2083
    eine ``utilityMods``; beides wertet PoB aus. Die Verzauberung bekommt
    einen eigenen Abschnitt VOR den impliziten Mods (so zeigt es das
    Spiel, und PoB zaehlt sie zu den Implicits)."""
    text = external_tools.item_export_text(Item.model_validate({
        "typeLine": "Granite Flask", "baseType": "Granite Flask", "frameType": 1,
        "enchantMods": ["Adds 4 Passive Skills"],
        "implicitMods": ["10% increased Frenzy Charge Duration"],
        "explicitMods": ["34% reduced Duration"],
        "utilityMods": ["+1500 to Armour"],
    }))

    assert ("Adds 4 Passive Skills\n--------\n"
            "10% increased Frenzy Charge Duration\n--------\n"
            "34% reduced Duration\n+1500 to Armour") in text


def test_mod_markup_is_stripped_from_the_extra_lists() -> None:
    """Die Zusatzlisten kommen ueber ``extra="allow"`` roh mit — anders
    als explicitMods/implicitMods gibt es fuer sie keine aufbereitete
    Eigenschaft im Modell. Ohne eigenes Entfernen stuende GGGs
    Faerbungs-Markup im Text."""
    text = external_tools.item_export_text(Item.model_validate({
        "typeLine": "Chaos Orb", "frameType": 5,
        "utilityMods": ["<enchanted>{+35% to all Elemental Resistances}"],
    }))

    assert "+35% to all Elemental Resistances" in text
    assert "<enchanted>" not in text
