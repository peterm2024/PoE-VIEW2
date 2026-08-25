"""Tests für das Album-Fenster der Mod-Sammlung (§4.52, Stufe 3).

Reine Anzeige einer bereits gefüllten ``ModCollection`` — kein
Netzzugriff, kein Worker nötig."""

from poe_view.services.mod_collection import (CORRUPTED_OFFSET, LEGACY_LEAGUE,
                                              ModCollection)
from poe_view.ui.mod_album import (COLUMNS, EXAMPLE_COL, IDENTITY_COL,
                                   KIND_COL, RANGE_COL, ModAlbumDialog,
                                   combined_range_text, format_record_detail,
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


# ------------------------------ Range-Spalte ----------------------------- #

def test_the_range_column_combines_every_pot_by_default(qapp) -> None:
    """Ohne Liga-/Raritaets-Auswahl zeigt Range die Spanne ueber ALLES —
    genau die Frage, die Peter gestellt hat: "was ist das Minimum/Maximum,
    das ich je gesehen habe"."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2, league="Allflame")
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=3)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    idx = dialog._proxy.index(0, RANGE_COL)
    assert dialog._proxy.data(idx) == "41–96"


def test_the_range_column_narrows_with_the_league_filter(qapp) -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2, league="Allflame")
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=2)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    index = dialog._league_combo.findData("Allflame")
    assert index != -1
    dialog._league_combo.setCurrentIndex(index)

    idx = dialog._proxy.index(0, RANGE_COL)
    assert dialog._proxy.data(idx) == "41"


def test_the_range_column_shows_a_dash_with_no_matching_pot(qapp) -> None:
    """Kombination, fuer die es in der Sammlung keinen Topf gibt: keine
    erfundene Zahl, sondern ein Strich."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2)
    sammlung.clear_new()

    from poe_view.services.mod_collection import UNKNOWN_RARITY
    record = sammlung.get("explicitMods", "+41 to maximum Life")

    assert combined_range_text(record, "Allflame", None) == "–"
    assert combined_range_text(record, None, lambda r: r == UNKNOWN_RARITY) == "–"


def test_a_single_valued_range_shows_no_dash() -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2)
    sammlung.clear_new()
    record = sammlung.get("explicitMods", "+41 to maximum Life")

    assert combined_range_text(record, None, None) == "41"


def test_multi_number_mods_keep_their_spans_separate() -> None:
    """``Adds # to # Fire Damage`` hat zwei Zahlen mit unterschiedlicher
    Bedeutung — die Range-Spalte darf sie nicht zu einer verschmelzen."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "Adds 2 to 6 Fire Damage", rarity=2)
    sammlung.observe("explicitMods", "Adds 1 to 4 Fire Damage", rarity=2)
    sammlung.clear_new()
    record = sammlung.get("explicitMods", "Adds 2 to 6 Fire Damage")

    assert combined_range_text(record, None, None) == "1–2, 4–6"


# ------------------------------ Liga-/Raritaetsfilter --------------------- #

def test_league_filter_only_lists_leagues_actually_present(qapp) -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2, league="Allflame")
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    werte = {dialog._league_combo.itemData(i) for i in range(dialog._league_combo.count())}

    assert "Allflame" in werte
    assert None in werte                 # "All leagues"
    assert "SSF R Allflame" not in werte  # nie beobachtet


def test_the_permanent_leagues_pot_is_selectable_by_itself(qapp) -> None:
    """Der leere String ist eine ECHTE Liga (der Altbestand) und darf
    nicht mit dem "keine Auswahl"-Sentinel verwechselt werden."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2)  # Altbestand
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=2, league="Allflame")
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    index = dialog._league_combo.findData(LEGACY_LEAGUE)
    assert index != -1
    assert dialog._league_combo.itemText(index) != "All leagues"
    dialog._league_combo.setCurrentIndex(index)

    idx = dialog._proxy.index(0, RANGE_COL)
    assert dialog._proxy.data(idx) == "41"


def test_rarity_filter_groups_normal_magic_and_rare_together(qapp) -> None:
    """Normal (0), Magic (1) und Rare (2) sind dieselbe Identitaet
    (``+# to maximum Life``), landen also ohnehin in EINEM Datensatz —
    die Gruppe zeigt hier, dass die Range-Spalte ueber alle drei
    Raritaeten geht, sobald die Gruppe ausgewaehlt ist."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+10 to maximum Life", rarity=0)
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=1)
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=2)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    index = dialog._rarity_combo.findData("Normal / Magic / Rare")
    assert index != -1
    dialog._rarity_combo.setCurrentIndex(index)

    assert dialog._proxy.rowCount() == 1
    idx = dialog._proxy.index(0, RANGE_COL)
    assert dialog._proxy.data(idx) == "10–96"


def test_rarity_filter_excludes_unique_from_the_grouped_rarities(qapp) -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2)
    sammlung.observe("explicitMods", "+1500 to maximum Life", rarity=3)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    index = dialog._rarity_combo.findData("Normal / Magic / Rare")
    dialog._rarity_combo.setCurrentIndex(index)

    idx = dialog._proxy.index(0, RANGE_COL)
    assert dialog._proxy.data(idx) == "41"


def test_the_rarity_filter_only_lists_groups_actually_present(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung())  # nur Rare (2) und Magic (1)

    werte = {dialog._rarity_combo.itemData(i) for i in range(dialog._rarity_combo.count())}

    assert "Unique" not in werte         # kein Unique in der Test-Sammlung
    assert "Normal / Magic / Rare" in werte


def test_league_and_rarity_filters_combine(qapp) -> None:
    """Drei GETRENNTE Identitaeten, damit die Zeilen-Sichtbarkeit selbst
    geprueft wird — nicht nur, was in der Range-Spalte einer ohnehin
    einzigen Zeile steht (das haette eine kaputte Zeilenfilterung nicht
    gemerkt, wenn zufaellig nur eine Identitaet vorkommt)."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2, league="Allflame")
    sammlung.observe("explicitMods", "+96 to Strength", rarity=3, league="Allflame")
    sammlung.observe("explicitMods", "+10 to Dexterity", rarity=2)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    dialog._league_combo.setCurrentIndex(dialog._league_combo.findData("Allflame"))
    dialog._rarity_combo.setCurrentIndex(dialog._rarity_combo.findData("Normal / Magic / Rare"))

    assert dialog._proxy.rowCount() == 1
    idx = dialog._proxy.index(0, IDENTITY_COL)
    assert dialog._proxy.data(idx) == "# to maximum Life"


# --------------------------- Corrupted-Filter ---------------------------- #

def test_corrupted_is_its_own_rarity_group(qapp) -> None:
    """Peter, 2026-08-25: "...auch zwischen Unique, Corrupted, (Normal/
    Magic/Rare)..." — ein corrupted Rare landet unter "Corrupted", nicht
    unter "Normal / Magic / Rare"."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2 + CORRUPTED_OFFSET)
    sammlung.observe("explicitMods", "+10 to Dexterity", rarity=2)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    werte = {dialog._rarity_combo.itemData(i) for i in range(dialog._rarity_combo.count())}
    assert "Corrupted" in werte

    index = dialog._rarity_combo.findData("Corrupted")
    dialog._rarity_combo.setCurrentIndex(index)

    assert dialog._proxy.rowCount() == 1
    idx = dialog._proxy.index(0, IDENTITY_COL)
    assert dialog._proxy.data(idx) == "# to maximum Life"


def test_corrupted_stays_out_of_the_grouped_rarities(qapp) -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2 + CORRUPTED_OFFSET)
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=2)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    index = dialog._rarity_combo.findData("Normal / Magic / Rare")
    dialog._rarity_combo.setCurrentIndex(index)

    idx = dialog._proxy.index(0, RANGE_COL)
    assert dialog._proxy.data(idx) == "96"


def test_corrupted_rare_and_corrupted_unique_are_both_just_corrupted(qapp) -> None:
    """Die Gruppe fasst absichtlich ueber alle Basis-Raritaeten hinweg
    zusammen — anders als bei der Sammlung selbst (§4.52.1), wo Rare und
    Unique fuer die BEWERTUNG streng getrennt bleiben."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to Strength", rarity=2 + CORRUPTED_OFFSET)
    sammlung.observe("explicitMods", "+41 to Strength", rarity=3 + CORRUPTED_OFFSET)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    index = dialog._rarity_combo.findData("Corrupted")
    dialog._rarity_combo.setCurrentIndex(index)

    assert dialog._proxy.rowCount() == 1


def test_the_detail_panel_names_the_corrupted_pot(qapp) -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2 + CORRUPTED_OFFSET)
    sammlung.clear_new()
    record = sammlung.get("explicitMods", "+41 to maximum Life")

    text = format_record_detail(record)

    assert "Corrupted Rare" in text


def test_a_negative_range_reads_unambiguously() -> None:
    """Ein Gedankenstrich direkt vor einem Minus liest sich wie ein
    dritter Strich (gemessen an Peters Bestand: ``Physical Damage taken
    from Attack Hits`` reicht von -47 bis -14)."""
    from poe_view.ui.mod_album import _spread_text

    assert _spread_text([(-47.0, -14.0)]) == "-47 to -14"
    assert "–" not in _spread_text([(-47.0, -14.0)])
    assert _spread_text([(-47.0, 14.0)]) == "-47–14"

