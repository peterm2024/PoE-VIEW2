"""Tests für den poe.ninja-Preis-Client — v. a. Gem-Varianten-Matching
und Link-Bucket-Zuordnung, die beiden Stellen, an denen ein Item-Name
allein nicht zum richtigen Preis führt (siehe ARCHITEKTUR.md §4.13)."""

from poe_view.api.models import Item
from poe_view.api.ninja import PriceIndex, _merge_currency, _merge_exchange, _merge_item


def _item(**kwargs) -> Item:
    return Item.model_validate(kwargs)


def _gem(name: str, level: str = "20", quality: str = "+20%", corrupted: bool = False) -> Item:
    return Item.model_validate({
        "typeLine": name,
        "frameType": 4,
        "corrupted": corrupted,
        "properties": [
            {"name": "Level", "values": [[level, 0]]},
            {"name": "Quality", "values": [[quality, 1]]},
        ],
    })


def _weapon(name: str, links: int = 0) -> Item:
    sockets = [{"group": 0, "attr": "S", "sColour": "R"} for _ in range(links)]
    return Item.model_validate({"name": name, "typeLine": name, "frameType": 3, "sockets": sockets})


# --- PriceIndex.price_for: einfache Namens-Zuordnung -------------------- #

def test_simple_lookup_by_display_name() -> None:
    index = PriceIndex()
    index._simple["Chaos Orb"] = 1.0
    assert index.price_for(_item(typeLine="Chaos Orb")) == 1.0


def test_simple_lookup_unknown_name_returns_none() -> None:
    index = PriceIndex()
    assert index.price_for(_item(typeLine="Irgendwas")) is None


def test_chaos_orb_is_seeded_as_the_reference_currency() -> None:
    """poe.ninja listet Chaos Orb nicht gegen sich selbst (real geprüft:
    kein Eintrag in der Currency-Route) — ohne Seed wäre der Preis
    fälschlich unbekannt statt 1."""
    index = PriceIndex()
    assert index.price_for(_item(typeLine="Chaos Orb", frameType=5)) == 1.0


# --- Gem-Matching --------------------------------------------------------- #

def test_gem_matches_exact_level_quality_corrupted() -> None:
    index = PriceIndex()
    index._gems["Item Quantity Support"] = [
        (20, 20, False, 730_848),
        (21, 23, True, 9_043_190),
    ]
    gem = _gem("Item Quantity Support", level="20", quality="+20%", corrupted=False)
    assert index.price_for(gem) == 730_848


def test_gem_no_exact_variant_returns_none_not_a_guess() -> None:
    """Lieber kein Preis als ein um eine Größenordnung falscher — die
    Differenz zwischen benachbarten Gem-Varianten kann Faktor 10+ sein."""
    index = PriceIndex()
    index._gems["Item Quantity Support"] = [(20, 20, False, 730_848)]
    gem = _gem("Item Quantity Support", level="19", quality="+15%", corrupted=False)
    assert index.price_for(gem) is None


def test_gem_corrupted_flag_must_match() -> None:
    index = PriceIndex()
    index._gems["X"] = [(20, 20, False, 100.0), (20, 20, True, 5.0)]
    assert index.price_for(_gem("X", "20", "+20%", corrupted=True)) == 5.0
    assert index.price_for(_gem("X", "20", "+20%", corrupted=False)) == 100.0


def test_gem_zero_quality_when_property_absent() -> None:
    index = PriceIndex()
    index._gems["Bare Gem"] = [(1, 0, False, 3.0)]
    gem = Item.model_validate({
        "typeLine": "Bare Gem", "frameType": 4,
        "properties": [{"name": "Level", "values": [["1", 0]]}],
    })
    assert index.price_for(gem) == 3.0


# --- Link-Bucket-Matching -------------------------------------------------- #

def test_link_aware_item_matches_exact_bucket() -> None:
    index = PriceIndex()
    index._links["Oni-Goroshi"] = {None: 3_617_276.0, 5: 40_000.0, 6: 29_808.0}
    assert index.price_for(_weapon("Oni-Goroshi", links=6)) == 29_808.0
    assert index.price_for(_weapon("Oni-Goroshi", links=5)) == 40_000.0
    assert index.price_for(_weapon("Oni-Goroshi", links=0)) == 3_617_276.0


def test_link_aware_item_falls_back_when_bucket_missing() -> None:
    """poe.ninja führt nur 5-/6-Link separat — fehlt der exakte Bucket
    (z. B. kein 6-Link gelistet), zählt der nächst niedrigere bekannte."""
    index = PriceIndex()
    index._links["Rare Sword"] = {None: 10.0, 5: 200.0}
    assert index.price_for(_weapon("Rare Sword", links=6)) == 200.0  # 6 fehlt -> 5
    assert index.price_for(_weapon("Rare Sword", links=4)) == 10.0   # kein Bucket -> Basis


def test_link_aware_item_with_only_high_buckets_falls_back_up() -> None:
    index = PriceIndex()
    index._links["Exotisch"] = {6: 1_000.0}
    assert index.price_for(_weapon("Exotisch", links=0)) == 1_000.0


# --- _merge_item: Gruppierung link-bewusster Namen ------------------------- #

def test_merge_item_keeps_base_price_reachable_alongside_link_price(monkeypatch) -> None:
    """Regression: Wenn die Basis-Zeile (ohne 'links') vor der 6-Link-
    Zeile im JSON steht, darf sie nicht isoliert in _simple landen, wo
    price_for() sie für einen Namen mit Link-Preisen nie mehr sucht."""
    import poe_view.api.ninja as ninja

    monkeypatch.setattr(ninja, "_get", lambda http, path, league, item_type: {
        "lines": [
            {"name": "Oni-Goroshi", "chaosValue": 3_617_276.0},
            {"name": "Oni-Goroshi", "links": 6, "chaosValue": 29_808.0},
        ]
    })
    index = PriceIndex()
    _merge_item(index, http=None, league="Standard", item_type="UniqueWeapon")
    assert "Oni-Goroshi" not in index._simple
    assert index.price_for(_weapon("Oni-Goroshi", links=0)) == 3_617_276.0
    assert index.price_for(_weapon("Oni-Goroshi", links=6)) == 29_808.0


def test_merge_item_non_link_aware_name_goes_to_simple(monkeypatch) -> None:
    import poe_view.api.ninja as ninja

    monkeypatch.setattr(ninja, "_get", lambda http, path, league, item_type: {
        "lines": [{"name": "Tabula Rasa", "chaosValue": 15.0}]
    })
    index = PriceIndex()
    _merge_item(index, http=None, league="Standard", item_type="UniqueArmour")
    assert index._simple["Tabula Rasa"] == 15.0
    assert "Tabula Rasa" not in index._links


def test_merge_item_skill_gem_builds_variant_list(monkeypatch) -> None:
    import poe_view.api.ninja as ninja

    monkeypatch.setattr(ninja, "_get", lambda http, path, league, item_type: {
        "lines": [
            {"name": "Melee Support", "gemLevel": 20, "gemQuality": 20,
             "corrupted": False, "chaosValue": 5.0},
            {"name": "Melee Support", "gemLevel": 21, "gemQuality": 23,
             "corrupted": True, "chaosValue": 500.0},
        ]
    })
    index = PriceIndex()
    _merge_item(index, http=None, league="Standard", item_type="SkillGem")
    assert index._gems["Melee Support"] == [
        (20, 20, False, 5.0),
        (21, 23, True, 500.0),
    ]


def test_merge_item_missing_data_leaves_index_untouched(monkeypatch) -> None:
    """Best-effort: ein 404/Netzwerkfehler (siehe _get) darf keine
    Exception werfen, nur eine Lücke hinterlassen."""
    import poe_view.api.ninja as ninja

    monkeypatch.setattr(ninja, "_get", lambda *a, **k: None)
    index = PriceIndex()
    _merge_item(index, http=None, league="Standard", item_type="UniqueWeapon")
    _merge_currency(index, http=None, league="Standard", item_type="Currency")
    _merge_exchange(index, http=None, league="Standard", item_type="DivinationCard")
    assert index._simple == {"Chaos Orb": 1.0} and index._gems == {} and index._links == {}


# --- _merge_currency / _merge_exchange ------------------------------------ #

def test_merge_currency_maps_type_name_to_chaos_equivalent(monkeypatch) -> None:
    import poe_view.api.ninja as ninja

    monkeypatch.setattr(ninja, "_get", lambda http, path, league, item_type: {
        "lines": [{"currencyTypeName": "Divine Orb", "chaosEquivalent": 220.0}]
    })
    index = PriceIndex()
    _merge_currency(index, http=None, league="Standard", item_type="Currency")
    assert index._simple["Divine Orb"] == 220.0


def test_merge_exchange_resolves_id_to_name_via_items_block(monkeypatch) -> None:
    import poe_view.api.ninja as ninja

    monkeypatch.setattr(ninja, "_get", lambda http, path, league, item_type: {
        "items": [{"id": "the-mayor", "name": "The Mayor"}],
        "lines": [{"id": "the-mayor", "primaryValue": 42.0}],
    })
    index = PriceIndex()
    _merge_exchange(index, http=None, league="Standard", item_type="DivinationCard")
    assert index._simple["The Mayor"] == 42.0


def test_merge_exchange_line_without_matching_item_is_skipped(monkeypatch) -> None:
    import poe_view.api.ninja as ninja

    monkeypatch.setattr(ninja, "_get", lambda http, path, league, item_type: {
        "items": [],
        "lines": [{"id": "unbekannt", "primaryValue": 42.0}],
    })
    index = PriceIndex()
    _merge_exchange(index, http=None, league="Standard", item_type="DivinationCard")
    assert index._simple == {"Chaos Orb": 1.0}
