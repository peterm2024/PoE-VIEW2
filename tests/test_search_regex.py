"""Tests für die Regex-Suche und den Socket-Suchindex.

Prüft gezielt mit echten, auf poe.re erzeugten Mustern (siehe
veiset/poe-vendor-string, src/utils/OutputString.ts), dass die dort
zusammengeklickten Strings hier unverändert funktionieren.
"""

from poe_view.api.models import Item
from poe_view.ui.item_table import (ItemFilterProxy, ItemTableModel,
                                    compile_search, matches_search)

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
    text = pattern.lower()
    return matches_search(_haystack(socket_spec, name), text,
                         compile_search(text, regex_enabled=True))


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
    assert compile_search("(unfertig", regex_enabled=True) is None
    assert matches_search("ein (unfertig-er text", "(unfertig", None)


def test_regex_disabled_treats_pattern_characters_literally() -> None:
    assert compile_search(POE_RE_RRG, regex_enabled=False) is None
    assert not matches_search(_haystack("R-R-G"), POE_RE_RRG.lower(), None)


def test_compile_search_returns_none_for_empty_text() -> None:
    assert compile_search("", regex_enabled=True) is None


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
