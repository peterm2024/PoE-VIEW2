"""Tests für die Regex-Suche und den Socket-Suchindex.

Prüft gezielt mit echten, auf poe.re erzeugten Mustern (siehe
veiset/poe-vendor-string, src/utils/OutputString.ts), dass die dort
zusammengeklickten Strings hier unverändert funktionieren.
"""

from poe_view.api.models import Item
from poe_view.ui.item_table import (ItemFilterProxy, ItemTableModel,
                                    compile_search, split_search_terms)

# Original-Ausgaben des poe.re-Generators
POE_RE_4LINK = r"-\w-.-"          # generate4LinkStr: irgendein 4-Link
POE_RE_6LINK = r"(-\w){5}"        # generate6LinkStr: irgendein 6-Link
POE_RE_RRG = "r-r-g|r-g-r|g-r-r"  # twoAndOne("r","g"): 3-Link, zwei rote + ein grüner
POE_RE_4L_RRG = r"-\w-.-|r-r-g|r-g-r|g-r-r"  # beides mit | verknüpft (addExpression)


def _item(socket_spec: str = "", name: str = "Test Item") -> Item:
    sockets = []
    if socket_spec:
        for group, chunk in enumerate(socket_spec.split(" ")):
            for colour in chunk.split("-"):
                sockets.append({"group": group, "sColour": colour})
    return Item.model_validate({"typeLine": name, "sockets": sockets})


def _haystack(socket_spec: str, name: str = "Test Item") -> str:
    return ItemTableModel._build_haystack(_item(socket_spec, name), "Tab 1")


def _matches(pattern: str, socket_spec: str, name: str = "Test Item") -> bool:
    return compile_search(pattern.lower(), regex_enabled=True).matches(
        _haystack(socket_spec, name))


# --- Socket-String landet im Suchindex ------------------------------------- #

def test_socket_string_is_part_of_the_search_index() -> None:
    assert "r-r-r-r-r-r" in _haystack("R-R-R-R-R-R")


# --- poe.re-Muster: Link-Anzahl -------------------------------------------- #

def test_poe_re_four_link_pattern_matches_a_four_link() -> None:
    assert _matches(POE_RE_4LINK, "G-R-R-R")


def test_poe_re_four_link_pattern_does_not_match_a_three_link() -> None:
    """Kernprobe der Mechanik: '-\\w-.-' braucht drei '-' und trifft
    deshalb einen 3-Link NICHT."""
    assert not _matches(POE_RE_4LINK, "B-B-G")


def test_poe_re_six_link_pattern_matches_only_a_six_link() -> None:
    assert _matches(POE_RE_6LINK, "R-R-R-R-R-R")
    assert not _matches(POE_RE_6LINK, "B B-B-B-B-B")  # 5-Link + einzelner


# --- poe.re-Muster: Farbkombination ---------------------------------------- #

def test_poe_re_rrg_matches_all_three_permutations() -> None:
    assert _matches(POE_RE_RRG, "R-R-G")
    assert _matches(POE_RE_RRG, "R-G-R")
    assert _matches(POE_RE_RRG, "G-R-R")


def test_poe_re_rrg_does_not_match_other_colour_combinations() -> None:
    assert not _matches(POE_RE_RRG, "R-R-B")
    assert not _matches(POE_RE_RRG, "G-G-R")


def test_poe_re_rrg_requires_the_sockets_to_be_linked() -> None:
    """Unverlinkt ("R R G") steht ohne '-' im Suchindex und darf nicht
    als 3-Link durchgehen."""
    assert not _matches(POE_RE_RRG, "R R G")


def test_poe_re_combined_four_link_or_rrg_matches_either() -> None:
    assert _matches(POE_RE_4L_RRG, "G-R-R-R")  # über den 4-Link-Teil
    assert _matches(POE_RE_4L_RRG, "R-R-G")    # über den Farb-Teil
    assert not _matches(POE_RE_4L_RRG, "B-B-B")


# --- compile_search / matches_search --------------------------------------- #

def test_plain_text_still_matches_as_substring_in_regex_mode() -> None:
    """Wer nur einen Namen sucht, soll vom Regex-Modus nichts merken."""
    assert _matches("chaos", "", name="Chaos Orb")


def test_invalid_pattern_falls_back_to_substring_search() -> None:
    """Beim Tippen ist das Muster ständig kurz unfertig (offene Klammer
    o. ä.) — die Liste darf dabei nicht leerlaufen."""
    assert compile_search("(unfertig", regex_enabled=True).matches(
        "ein (unfertig-er text")


def test_regex_disabled_treats_pattern_characters_literally() -> None:
    assert not compile_search(POE_RE_RRG.lower(), regex_enabled=False).matches(
        _haystack("R-R-G"))


def test_an_empty_query_matches_everything() -> None:
    leer = compile_search("", regex_enabled=True)
    assert not leer                    # falsy: der Aufrufer filtert gar nicht erst
    assert leer.matches("irgendwas")


# --- Proxy-Integration ------------------------------------------------------ #

def _proxy_with(items: list[Item]) -> tuple[ItemFilterProxy, ItemTableModel]:
    model = ItemTableModel()
    model.set_items(items)
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)
    return proxy, model


def test_proxy_filters_by_poe_re_pattern_when_regex_enabled(qapp) -> None:
    proxy, _ = _proxy_with([_item("R-R-G", "Sechs-Link"), _item("B-B-B", "Blau")])
    proxy.set_regex_enabled(True)
    proxy.setFilterFixedString(POE_RE_RRG)
    assert proxy.rowCount() == 1


def test_proxy_ignores_pattern_when_regex_disabled(qapp) -> None:
    proxy, _ = _proxy_with([_item("R-R-G", "Sechs-Link"), _item("B-B-B", "Blau")])
    proxy.set_regex_enabled(False)
    proxy.setFilterFixedString(POE_RE_RRG)
    assert proxy.rowCount() == 0  # als reiner Text kommt der String nirgends vor


def test_proxy_toggling_regex_reevaluates_the_active_search(qapp) -> None:
    proxy, _ = _proxy_with([_item("R-R-G", "Sechs-Link")])
    proxy.set_regex_enabled(False)
    proxy.setFilterFixedString(POE_RE_RRG)
    assert proxy.rowCount() == 0

    proxy.set_regex_enabled(True)

    assert proxy.rowCount() == 1


# --- Mehrere Begriffe, UND-verknuepft (Peter, 2026-08-13) ------------------ #
#
# Vorlage ist das Hilfe-Fenster der Spiel-eigenen Truhensuche, das Peter
# angehaengt hat: "Type multiple keywords by separating them with a
# space" / "Combine space-separated text into a single keyword by
# enclosing it in quotation marks".

def _ring() -> Item:
    """Ein Ring, dessen zwei Suchbegriffe in VERSCHIEDENEN Mod-Zeilen
    stehen — der Fall, der vorher nicht zu finden war. 38.128 der 59.042
    Items in Peters Bestand tragen zwei oder mehr Mod-Zeilen."""
    return Item.model_validate({
        "typeLine": "Amethyst Ring", "baseType": "Amethyst Ring", "frameType": 2,
        "explicitMods": ["+38 to maximum Life", "+15% to Chaos Resistance"],
    })


def test_two_keywords_match_across_different_mod_lines() -> None:
    """Der eigentliche Punkt: "life resistance" steht nirgends
    buchstaeblich nebeneinander, gemeint sind aber beide Eigenschaften."""
    haystack = ItemTableModel._build_haystack(_ring(), "Tab 1")

    assert compile_search("life resistance", regex_enabled=True).matches(haystack)
    assert compile_search("life resistance", regex_enabled=False).matches(haystack)


def test_all_keywords_must_match_not_just_one() -> None:
    """UND, nicht ODER — sonst waere die zweite Eingabe wertlos, weil sie
    die Treffermenge vergroessert statt sie einzugrenzen."""
    haystack = ItemTableModel._build_haystack(_ring(), "Tab 1")

    assert not compile_search("life armour", regex_enabled=True).matches(haystack)


def test_quotation_marks_hold_a_phrase_together() -> None:
    """Sonst gaebe es keinen Weg mehr, nach einem Text MIT Leerzeichen zu
    suchen — und "maximum life" faende auch ein Item mit "maximum mana"
    und "life regeneration"."""
    passt = Item.model_validate({"typeLine": "Ring", "explicitMods": ["+38 to maximum Life"]})
    passt_nicht = Item.model_validate({
        "typeLine": "Ring",
        "explicitMods": ["+38 to maximum Mana", "6% increased Life Regeneration"]})

    muster = compile_search('"maximum life"', regex_enabled=True)
    assert muster.matches(ItemTableModel._build_haystack(passt, "Tab 1"))
    assert not muster.matches(ItemTableModel._build_haystack(passt_nicht, "Tab 1"))


def test_an_unclosed_quote_still_searches() -> None:
    """Beim Tippen ist das Anfuehrungszeichen zwangslaeufig kurz offen.
    Wie beim unfertigen Regex darf die Liste dabei nicht leerlaufen."""
    assert split_search_terms('"maximum life') == ["maximum life"]


def test_a_poe_re_pattern_survives_the_splitting() -> None:
    """Der Grund, warum am Leerzeichen getrennt werden DARF: poe.re-Muster
    enthalten keine. Sie bleiben ein einziger Begriff."""
    assert split_search_terms(POE_RE_4L_RRG) == [POE_RE_4L_RRG]
    assert _matches(POE_RE_4L_RRG, "R-R-G")


def test_a_regex_with_spaces_needs_quotes_now() -> None:
    """Die eine bewusste Verhaltensaenderung, hier festgehalten statt
    verschwiegen: Ein Muster MIT Leerzeichen war vorher eines, jetzt sind
    es zwei Begriffe. Anfuehrungszeichen stellen das alte Verhalten her."""
    haystack = ItemTableModel._build_haystack(
        Item.model_validate({"typeLine": "Vaal Axe", "explicitMods": ["Adds 18 to 340 Lightning"]}),
        "Tab 1")

    assert compile_search(r'"adds \d+ to"', regex_enabled=True).matches(haystack)


def test_socketed_gem_names_are_searchable() -> None:
    """Wie im Spiel: "The Gems and Microtransactions of those items are
    also searched." Betrifft nur 125 Items in Peters Bestand — aber das
    sind die angelegten, und "wo steckt meine Determination?" ist genau
    die Frage, fuer die man sonst jedes Teil einzeln anklickt."""
    helm = Item.model_validate({
        "typeLine": "Hubris Circlet", "baseType": "Hubris Circlet",
        "socketedItems": [{"typeLine": "Determination", "baseType": "Determination"}]})
    haystack = ItemTableModel._build_haystack(helm, "Tab 1")

    assert compile_search("determination", regex_enabled=True).matches(haystack)
    # Und weiterhin kombinierbar mit allem anderen:
    assert compile_search("determination hubris", regex_enabled=True).matches(haystack)


# --- Feld-Suchen ilvl:/tier: (Peter, 2026-08-13) ---------------------------- #

def _ilvl_item(ilvl: int, name: str = "Ring") -> str:
    return ItemTableModel._build_haystack(
        Item.model_validate({"typeLine": name, "ilvl": ilvl}), "Tab 1")


def test_ilvl_search_matches_exactly_that_level() -> None:
    """Peter, 2026-08-13: "Ilvl:84 bedeutet genau 84." Bestaetigt, nicht
    geraten — fuer Bereiche gibt es die Spalten-Filter (">=84")."""
    assert compile_search("ilvl:84", regex_enabled=True).matches(_ilvl_item(84))
    assert not compile_search("ilvl:84", regex_enabled=True).matches(_ilvl_item(85))


def test_a_partial_level_does_not_match_a_longer_one() -> None:
    """Der Grund fuer die Wortgrenzen: Als Teilstring gelesen faende
    "ilvl:8" alles von 80 bis 89 — und beim Tippen sieht man genau das
    kurz aufblitzen, was wie ein Treffer aussieht und keiner ist."""
    assert not compile_search("ilvl:8", regex_enabled=True).matches(_ilvl_item(84))
    assert compile_search("ilvl:8", regex_enabled=True).matches(_ilvl_item(8))


def test_tier_search_reads_the_tier_out_of_the_name() -> None:
    """GEMESSEN, nicht angenommen: Von 59.042 Items in Peters Bestand
    traegt KEIN EINZIGES eine Property "Map Tier"; 13.417 tragen die Tier
    im typeLine ("Map (Tier 6)"). Die erste Fassung las die Property und
    fand auf echten Daten nichts — sichtbar wurde das erst bei der
    Gegenprobe am echten Cache, weil ich die Property in meinen eigenen
    Demo-Daten selbst erfunden hatte."""
    karte = Item.model_validate({"typeLine": "Map (Tier 6)", "ilvl": 69})
    haystack = ItemTableModel._build_haystack(karte, "Maps")

    assert compile_search("tier:6", regex_enabled=True).matches(haystack)
    assert not compile_search("tier:16", regex_enabled=True).matches(haystack)
    # Und die Tier eines Valdo's Map, das den Namen anders aufbaut:
    valdo = ItemTableModel._build_haystack(
        Item.model_validate({"typeLine": "Valdo's Map (Tier 11)"}), "Maps")
    assert compile_search("tier:11", regex_enabled=True).matches(valdo)


def test_a_field_search_combines_with_ordinary_keywords() -> None:
    """Der eigentliche Nutzen: zusammen mit allem anderen. "ilvl:84 ring"
    ist genau die Eingabe, die man aus dem Spiel mitbringt."""
    assert compile_search("ilvl:84 ring", regex_enabled=True).matches(
        _ilvl_item(84, "Amethyst Ring"))
    assert not compile_search("ilvl:84 amulet", regex_enabled=True).matches(
        _ilvl_item(84, "Amethyst Ring"))


def test_an_operator_stays_an_ordinary_term_instead_of_pretending() -> None:
    """``ilvl:>=84`` ist NICHT umgesetzt. Es faellt auf die gewoehnliche
    Suche zurueck und findet nichts, statt stillschweigend etwas anderes
    zu tun, als dort steht — dafuer gibt es die Spalten-Filter."""
    assert not compile_search("ilvl:>=84", regex_enabled=False).matches(_ilvl_item(90))


def test_field_search_works_with_the_regex_toggle_off_too() -> None:
    """Im Teilstring-Modus ist "ilvl:84" dasselbe gemeint — der
    Umschalter darf daran nichts aendern."""
    assert compile_search("ilvl:84", regex_enabled=False).matches(_ilvl_item(84))
    assert not compile_search("ilvl:84", regex_enabled=False).matches(_ilvl_item(840))
