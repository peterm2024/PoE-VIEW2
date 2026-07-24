"""Tests für die Tab-Herkunfts- und Mods-Spalte der ItemTableModel."""

from PySide6.QtCore import Qt

from poe_view.api.models import Item
from poe_view.ui.item_table import MODS_COL, ItemFilterProxy, ItemTableModel


def make_item(name: str, mods: list[str] | None = None) -> Item:
    return Item.model_validate({"typeLine": name, "explicitMods": mods or []})


def test_tab_column_shows_given_source(qapp) -> None:
    model = ItemTableModel()
    model.set_items([make_item("Chaos Orb"), make_item("Divine Orb")],
                    ["Currency 1", "Currency 2"])
    assert model.source_at(0) == "Currency 1"
    assert model.source_at(1) == "Currency 2"
    idx = model.index(0, 1)  # Tab-Spalte
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "Currency 1"


def test_missing_source_falls_back_to_dash(qapp) -> None:
    model = ItemTableModel()
    model.set_items([make_item("Chaos Orb")])  # sources=None
    idx = model.index(0, 1)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "–"


def test_name_column_unaffected_by_tab_column_insertion(qapp) -> None:
    model = ItemTableModel()
    model.set_items([make_item("Chaos Orb")], ["Currency 1"])
    idx = model.index(0, 2)  # Name-Spalte
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "Chaos Orb"


def test_mods_column_joins_explicit_mods(qapp) -> None:
    """Nutzer-Feedback: gerade bei Maps sind die Modifikatoren interessant."""
    model = ItemTableModel()
    map_item = make_item("Beach Map", mods=["Monsters deal 90% extra Damage as Fire",
                                            "Players are Cursed with Vulnerability"])
    model.set_items([map_item, make_item("Chaos Orb")], ["Maps", "Currency"])

    idx = model.index(0, MODS_COL)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == \
        "Monsters deal 90% extra Damage as Fire · Players are Cursed with Vulnerability"
    # Tooltip zeigt die Mods zeilenweise komplett (Spalte kann abschneiden)
    assert model.data(idx, Qt.ItemDataRole.ToolTipRole) == \
        "Monsters deal 90% extra Damage as Fire\nPlayers are Cursed with Vulnerability"
    assert model.data(model.index(1, MODS_COL), Qt.ItemDataRole.DisplayRole) == ""


def test_filter_matches_explicit_mods(qapp) -> None:
    model = ItemTableModel()
    model.set_items([make_item("Beach Map", mods=["Area is Beyond-touched"]),
                     make_item("Dunes Map")], ["Maps", "Maps"])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)

    proxy.setFilterFixedString("beyond")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 2), Qt.ItemDataRole.DisplayRole) == "Beach Map"


def test_filter_matches_property_text(qapp) -> None:
    """Nutzer-Feedback: Suche nach "Quantity" fand nur die Chisel (Mod-Text),
    nicht die Maps selbst — deren Quantity/Rarity/Drop Chance stecken als
    PROPERTY (nicht als explicitMods), z. B. {"name": "Item Quantity",
    "values": [["+23%", 1]]}. Reale Struktur, Cache-Analyse 2026-07-10."""
    model = ItemTableModel()
    map_with_quantity = Item.model_validate({
        "typeLine": "Oppressive Map", "properties": [
            {"name": "Item Quantity", "values": [["+23%", 1]]},
        ]})
    model.set_items([map_with_quantity, make_item("Dunes Map")], ["Maps", "Maps"])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)

    proxy.setFilterFixedString("quantity")

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 2), Qt.ItemDataRole.DisplayRole) == "Oppressive Map"


def test_wildcard_asterisk_shows_everything(qapp) -> None:
    """"*" im Suchfeld zeigt bewusst ALLES — für den Komplett-Export einer
    ganzen Truhe (Nutzer-Feedback). Ohne Sonderbehandlung würde "*" als
    escapter Regex-Text ("\\*") ankommen und NICHTS treffen."""
    model = ItemTableModel()
    model.set_items([make_item("Chaos Orb"), make_item("Beach Map")], ["A", "B"])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)

    proxy.setFilterFixedString("*")

    assert proxy.rowCount() == 2


def test_empty_filter_still_shows_everything(qapp) -> None:
    """Regression: das Umstellen auf ein eigenes _search_text-Feld darf das
    bisherige Verhalten bei leerem Suchfeld nicht verändern."""
    model = ItemTableModel()
    model.set_items([make_item("Chaos Orb")], ["A"])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)

    proxy.setFilterFixedString("")

    assert proxy.rowCount() == 1


# --- Anforderungs-Spalten (Anf.Lvl/Str/Dex/Int) + numerische Sortierung ---- #

def make_weapon(name: str, level: str, dex: str) -> Item:
    return Item.model_validate({"typeLine": name, "requirements": [
        {"name": "Level", "values": [[level, 0]]},
        {"name": "Dex", "values": [[dex, 0]]},
    ]})


def test_requirement_columns_show_values(qapp) -> None:
    from poe_view.ui.item_table import COLUMNS, ItemTableModel
    model = ItemTableModel()
    model.set_items([make_weapon("Gutting Knife", "56", "113"), make_item("Chaos Orb")])
    req_col = COLUMNS.index("Anf.Lvl")
    dex_col = COLUMNS.index("Dex")
    assert model.data(model.index(0, req_col), Qt.ItemDataRole.DisplayRole) == "56"
    assert model.data(model.index(0, dex_col), Qt.ItemDataRole.DisplayRole) == "113"
    assert model.data(model.index(1, req_col), Qt.ItemDataRole.DisplayRole) == "–"


def test_numeric_sort_role_orders_numbers_not_strings(qapp) -> None:
    """Regression: "113" sortierte als String VOR "56" — der Proxy sortiert
    jetzt über NUMERIC_SORT_ROLE (echte Zahlen, "–" ganz nach unten)."""
    from poe_view.ui.item_table import COLUMNS, NUMERIC_SORT_ROLE, ItemTableModel
    model = ItemTableModel()
    model.set_items([make_weapon("A", "113", "1"), make_weapon("B", "56", "1"),
                     make_item("Chaos Orb")])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)
    req_col = COLUMNS.index("Anf.Lvl")

    assert model.data(model.index(0, req_col), NUMERIC_SORT_ROLE) == 113.0
    assert model.data(model.index(2, req_col), NUMERIC_SORT_ROLE) == float("-inf")

    proxy.sort(req_col, Qt.SortOrder.AscendingOrder)
    shown = [proxy.data(proxy.index(r, req_col), Qt.ItemDataRole.DisplayRole)
             for r in range(proxy.rowCount())]
    assert shown == ["–", "56", "113"]


# --- Spalten-Filter-Ausdrücke (Excel-artig, Nutzer-Feedback) --------------- #

def test_expression_matches_variants() -> None:
    from poe_view.ui.item_table import _expression_matches
    assert _expression_matches(">=20", "+20%")          # "20% Quality"
    assert not _expression_matches(">20", "+20%")
    assert _expression_matches("<45", "44")             # "iLvl <45"
    assert not _expression_matches("<45", "–")          # ohne Zahl fällt raus
    assert _expression_matches("=beach map", "Beach Map")
    assert _expression_matches("!=20", "13")
    assert _expression_matches("beyond", "Area is Beyond-touched")  # Teilstring


def test_column_filter_reduces_rows_and_marks_header(qapp) -> None:
    from poe_view.ui.item_table import COLUMNS, ItemTableModel
    model = ItemTableModel()
    model.set_items([make_weapon("A", "56", "1"), make_weapon("B", "70", "1")])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)
    req_col = COLUMNS.index("Anf.Lvl")

    proxy.set_column_filter(req_col, "<60")
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 2), Qt.ItemDataRole.DisplayRole) == "A"
    assert proxy.headerData(req_col, Qt.Orientation.Horizontal,
                            Qt.ItemDataRole.DisplayRole) == "Anf.Lvl 🔍"

    proxy.clear_column_filters()
    assert proxy.rowCount() == 2
    assert proxy.headerData(req_col, Qt.Orientation.Horizontal,
                            Qt.ItemDataRole.DisplayRole) == "Anf.Lvl"


def test_column_filter_and_global_filter_combine(qapp) -> None:
    from poe_view.ui.item_table import COLUMNS, ItemTableModel
    model = ItemTableModel()
    model.set_items([make_weapon("Gutting Knife", "56", "1"),
                     make_weapon("Skinning Knife", "5", "1")])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)
    proxy.setFilterFixedString("knife")
    proxy.set_column_filter(COLUMNS.index("Anf.Lvl"), ">=50")
    assert proxy.rowCount() == 1


# --- Lazy-Icon-Loading (Aggregate fluten die Worker-Queue nicht) ----------- #

def test_lazy_icons_requested_on_paint_not_on_set(qapp) -> None:
    from poe_view.ui.item_table import ICON_COL, ItemTableModel
    requested: list[str] = []
    model = ItemTableModel(icon_requester=requested.append)
    item = Item.model_validate({"typeLine": "Chaos Orb", "icon": "https://cdn/x.png"})

    model.set_items([item], request_icons=False)
    assert requested == []  # kein eifriges Anfordern im Aggregat

    model.data(model.index(0, ICON_COL), Qt.ItemDataRole.DecorationRole)
    assert requested == ["https://cdn/x.png"]  # lazy beim ersten Painten

    model.data(model.index(0, ICON_COL), Qt.ItemDataRole.DecorationRole)
    assert requested == ["https://cdn/x.png"]  # und nur genau einmal


# --- Typ-Filter-Checkboxen (Nutzer-Feedback) ------------------------------- #

def test_type_filter_hides_unchecked_frame_types(qapp) -> None:
    model = ItemTableModel()
    model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "frameType": 0}),
        Item.model_validate({"typeLine": "Vaal Regalia", "frameType": 3}),
    ])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_type_visible(3, False)  # Unique abwählen

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 2), Qt.ItemDataRole.DisplayRole) == "Chaos Orb"

    proxy.set_type_visible(3, True)
    assert proxy.rowCount() == 2


def test_type_filter_covers_gem_currency_divination_card(qapp) -> None:
    """Nutzer-Feedback: Currency, Gems und Div Cards haben jetzt eigene
    Checkboxen (frameType 5/4/6) statt immer sichtbar zu bleiben."""
    model = ItemTableModel()
    model.set_items([
        Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5}),
        Item.model_validate({"typeLine": "Awakened Gem", "frameType": 4}),
        Item.model_validate({"typeLine": "The Fiend", "frameType": 6}),
    ])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_type_visible(5, False)  # Currency abwählen
    assert proxy.rowCount() == 2

    proxy.set_type_visible(4, False)  # Gem abwählen
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 2), Qt.ItemDataRole.DisplayRole) == "The Fiend"


def test_type_filter_other_bucket_covers_quest_prophecy_relic(qapp) -> None:
    """frameTypes ohne eigene Checkbox (Quest=7, Prophecy=8, Relic=9,
    unbekannt=99) laufen gemeinsam unter der "Sonstige"-Checkbox (OTHER_TYPE)."""
    from poe_view.ui.theme import OTHER_TYPE
    model = ItemTableModel()
    model.set_items([
        Item.model_validate({"typeLine": "Quest Item", "frameType": 7}),
        Item.model_validate({"typeLine": "Prophecy", "frameType": 8}),
        Item.model_validate({"typeLine": "Relic", "frameType": 9}),
        Item.model_validate({"typeLine": "Unbekannt", "frameType": 99}),
        Item.model_validate({"typeLine": "Chaos Orb", "frameType": 5}),
    ])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)

    proxy.set_type_visible(OTHER_TYPE, False)

    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 2), Qt.ItemDataRole.DisplayRole) == "Chaos Orb"


def test_type_filter_combines_with_text_search(qapp) -> None:
    model = ItemTableModel()
    model.set_items([
        Item.model_validate({"typeLine": "Beach Map", "frameType": 0}),
        Item.model_validate({"typeLine": "Beach Map", "frameType": 2}),
    ])
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)
    proxy.setFilterFixedString("beach")
    proxy.set_type_visible(0, False)

    assert proxy.rowCount() == 1


# --- Stabile Sortierung bei Filter-Toggle (Nutzer-Feedback) ---------------- #

def test_reactivating_filter_restores_original_order_on_ties(qapp) -> None:
    """Regression: "Nach dem Deaktivieren und Reaktivieren der Suchfilter
    sollte wieder die ursprüngliche Sortierreihenfolge auftauchen" — bei
    gleichem Sortierwert (hier: alle ohne iLvl, also "-inf") landeten
    reaktivierte Items sonst am Ende statt an ihrer alten Position."""
    from PySide6.QtWidgets import QTableView
    from poe_view.ui.item_table import COLUMNS, ItemTableModel
    model = ItemTableModel()
    items = [
        Item.model_validate({"typeLine": "Echo", "frameType": 0}),
        Item.model_validate({"typeLine": "Foxtrot", "frameType": 3}),
        Item.model_validate({"typeLine": "Golf", "frameType": 0}),
        Item.model_validate({"typeLine": "Hotel", "frameType": 3}),
        Item.model_validate({"typeLine": "India", "frameType": 0}),
    ]
    model.set_items(items)
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)
    table = QTableView()
    table.setModel(proxy)
    table.setSortingEnabled(True)
    table.sortByColumn(COLUMNS.index("iLvl"), Qt.SortOrder.AscendingOrder)  # alle "-inf": Ties
    names = lambda: [proxy.data(proxy.index(r, 2), Qt.ItemDataRole.DisplayRole)
                     for r in range(proxy.rowCount())]
    original = names()

    proxy.set_type_visible(3, False)  # Unique ausblenden ("deaktivieren")
    proxy.set_type_visible(3, True)   # wieder einblenden ("reaktivieren")

    assert names() == original


def test_duplicate_names_keep_source_order_after_filter_toggle(qapp) -> None:
    """Gleicher Bug, andere Ursache: mehrere Items mit identischem Namen
    (z. B. Currency-Stacks) sind beim Sortieren nach Name ebenfalls Ties."""
    model = ItemTableModel()
    items = [make_item("Chaos Orb") for _ in range(3)]
    model.set_items(items)
    proxy = ItemFilterProxy()
    proxy.setSourceModel(model)
    proxy.sort(2, Qt.SortOrder.AscendingOrder)

    proxy.set_column_filter(2, "chaos")
    proxy.set_column_filter(2, "")

    order = [proxy.mapToSource(proxy.index(r, 0)).row() for r in range(proxy.rowCount())]
    assert order == [0, 1, 2]
