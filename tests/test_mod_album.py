"""Tests für das Album-Fenster der Mod-Sammlung (§4.52, Stufe 3).

Reine Anzeige einer bereits gefüllten ``ModCollection`` — kein
Netzzugriff, kein Worker nötig."""

from poe_view.services.mod_collection import LEGACY_LEAGUE, ModCollection
from poe_view.ui.mod_album import (COLUMNS, EXAMPLE_COL, IDENTITY_COL,
                                   KIND_COL, ModAlbumDialog, format_record_detail,
                                   kind_label, league_label, rarity_label)


def _sammlung() -> ModCollection:
    sammlung = ModCollection()
    for wert in (41, 96):
        sammlung.observe("explicitMods", f"+{wert} to maximum Life", rarity=2)
    sammlung.observe("implicitMods", "+20% to Fire Resistance", rarity=2)
    sammlung.observe("utilityMods", "25% increased Movement Speed", rarity=1)
    sammlung.clear_new()
    return sammlung


# ------------------------------ Anzeigenamen ---------------------------- #

def test_rarity_label_covers_the_two_special_pots() -> None:
    from poe_view.services.mod_collection import MAP_RARITY, UNKNOWN_RARITY

    assert rarity_label(MAP_RARITY) == "Map"
    assert rarity_label(UNKNOWN_RARITY) == "Unknown rarity"
    assert rarity_label(2) == "Rare"
    assert rarity_label(3) == "Unique"


def test_league_label_names_the_legacy_pot() -> None:
    assert "Permanent" in league_label(LEGACY_LEAGUE)
    assert league_label("Allflame") == "Allflame"


def test_kind_label_falls_back_to_the_raw_field_name() -> None:
    assert kind_label("explicitMods") == "Explicit"
    assert kind_label("somethingUnknown") == "somethingUnknown"


# -------------------------------- Detailtext ----------------------------- #

def test_the_detail_lists_every_pot_the_mod_was_seen_in() -> None:
    sammlung = _sammlung()
    record = sammlung.get("explicitMods", "+96 to maximum Life")

    text = format_record_detail(record)

    assert "seen 2× in total" in text
    assert "Rare" in text
    assert "41" in text and "96" in text


def test_a_single_valued_span_shows_no_dash() -> None:
    """Ein einziger je gesehener Wert ist ein Punkt, keine Spanne — ``41``,
    nicht ``41–41``."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2)
    sammlung.clear_new()
    record = sammlung.get("explicitMods", "+41 to maximum Life")

    text = format_record_detail(record)

    assert "41–41" not in text
    assert "41" in text


# ------------------------------ Modell/Tabelle --------------------------- #

def test_the_dialog_lists_every_record(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung())

    assert dialog._model.rowCount() == 3


def test_columns_match_their_header(qapp) -> None:
    from PySide6.QtCore import Qt

    dialog = ModAlbumDialog(_sammlung())

    for col, name in enumerate(COLUMNS):
        assert dialog._model.headerData(
            col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == name
    assert dialog._model.headerData(
        0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) is None


def test_selecting_a_row_fills_the_detail_panel(qapp) -> None:
    from PySide6.QtCore import Qt

    dialog = ModAlbumDialog(_sammlung())
    idx = dialog._proxy.index(0, IDENTITY_COL)
    dialog._table.setCurrentIndex(idx)

    assert dialog._detail.toPlainText() != ""


# -------------------------------- Suche/Filter --------------------------- #

def test_search_filters_by_identity_text(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung())

    dialog._search.setText("maximum life")

    assert dialog._proxy.rowCount() == 1


def test_search_matches_nothing_shows_zero_rows(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung())

    dialog._search.setText("nonsense that does not occur")

    assert dialog._proxy.rowCount() == 0


def test_kind_filter_narrows_to_that_kind_only(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung())

    index = dialog._kind_combo.findData("utilityMods")
    assert index != -1
    dialog._kind_combo.setCurrentIndex(index)

    assert dialog._proxy.rowCount() == 1
    row = dialog._model.record_at(dialog._proxy.mapToSource(dialog._proxy.index(0, 0)).row())
    assert row.kind == "utilityMods"


def test_search_and_kind_filter_combine(qapp) -> None:
    """Beide Bedingungen muessen gelten, nicht nur eine — sonst liesse
    sich mit dem Kind-Filter die Textsuche aushebeln."""
    sammlung = _sammlung()
    sammlung.observe("utilityMods", "+41 to maximum Life", rarity=1)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    dialog._search.setText("maximum life")
    index = dialog._kind_combo.findData("utilityMods")
    dialog._kind_combo.setCurrentIndex(index)

    assert dialog._proxy.rowCount() == 1
    row = dialog._model.record_at(dialog._proxy.mapToSource(dialog._proxy.index(0, 0)).row())
    assert row.kind == "utilityMods"
    assert "maximum Life" in row.identity


def test_the_kind_filter_only_lists_kinds_actually_present(qapp) -> None:
    """Kein Eintrag fuer ``craftedMods`` im Menue, wenn die Sammlung
    keinen einzigen hat — eine leere Auswahl waere ein totes Filter-Item."""
    dialog = ModAlbumDialog(_sammlung())

    werte = {dialog._kind_combo.itemData(i) for i in range(dialog._kind_combo.count())}

    assert "craftedMods" not in werte
    assert "utilityMods" in werte


def test_the_count_label_reflects_the_filtered_total(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung())

    dialog._search.setText("maximum life")

    assert "1" in dialog._count_label.text()
    assert "3" in dialog._count_label.text()
