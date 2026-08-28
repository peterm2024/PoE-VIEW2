"""Tests für das Album-Fenster der Mod-Sammlung (§4.52, Stufe 3).

Reine Anzeige einer bereits gefüllten ``ModCollection`` — kein
Netzzugriff, kein Worker nötig."""

from poe_view.services.mod_collection import (CORRUPTED_OFFSET, LEGACY_LEAGUE,
                                              ModCollection)
from poe_view.services import mod_tiers
from poe_view.ui.mod_album import (BANDS_HEADING, COLUMNS, COUNT_COL,
                                   EXAMPLE_COL, IDENTITY_COL, KIND_COL,
                                   LADDER_HEADING, RANGE_COL, ModAlbumDialog,
                                   collected_tiers, combined_range_text,
                                   format_record_detail, kind_label,
                                   league_label, matching_count,
                                   range_column_text, rarity_label,
                                   record_detail_html, tier_number,
                                   tier_progress)


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


# ------------------- Seen zeigt dieselbe Auswahl wie Range --------------- #

def test_seen_follows_the_same_selection_as_range(qapp) -> None:
    """Peter fiel es an einem Screenshot auf: Chaos-Res zeigte Range "13"
    und daneben 897 Sichtungen — die Range kam aus dem gefilterten Topf,
    die Zahl aus allen zusammen. Zwei Spalten nebeneinander, die von
    verschiedenen Populationen reden."""
    sammlung = ModCollection()
    for _ in range(5):
        sammlung.observe("explicitMods", "+13 to maximum Life", rarity=2,
                         league="Allflame")
    for _ in range(90):
        sammlung.observe("explicitMods", "+26 to maximum Life", rarity=2)
    sammlung.clear_new()
    dialog = ModAlbumDialog(sammlung)

    ohne = dialog._proxy.index(0, COUNT_COL)
    assert dialog._proxy.data(ohne) == 95          # alle Toepfe zusammen

    dialog._league_combo.setCurrentIndex(dialog._league_combo.findData("Allflame"))

    mit = dialog._proxy.index(0, COUNT_COL)
    assert dialog._proxy.data(mit) == 5            # nur der gewaehlte Topf
    assert dialog._proxy.data(dialog._proxy.index(0, RANGE_COL)) == "13"


def test_the_unfiltered_count_still_equals_the_records_own_total(qapp) -> None:
    """Jede Beobachtung zaehlt in genau eine Spanne — ungefiltert muss die
    Summe deshalb wieder der Gesamtzahl entsprechen. Faellt das
    auseinander, geht beim Einsortieren etwas verloren."""
    sammlung = _sammlung()
    for record in sammlung.records():
        assert matching_count(record, None, None) == record.count


# --------------------------- Tier-Baender im Album ----------------------- #

def _mit_belegen(front) -> "ModCollection":
    """Eine Sammlung, deren Eintrag genau diese Belege traegt — als
    Kontenbuch mit je einer Sichtung pro Punkt (Aufbau 5)."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+27% to Cold Resistance", rarity=2)
    sammlung.clear_new()
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")
    record.tier_ledger["Ring"] = {float(wert): [1, il, il]
                                  for wert, il in front}
    return sammlung


def test_the_detail_shows_inferred_bands() -> None:
    sammlung = _mit_belegen([(6, 5), (12, 14), (18, 26), (24, 38), (30, 50)])
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record)

    assert "Tiers" in text
    assert "Ring" in text
    assert "item level" in text


def test_the_detail_says_why_it_stays_silent() -> None:
    """Der haeufigste Fall bei einem Endgame-Bestand — und er ist kein
    Mangel der Sammlung, sondern eine Eigenschaft der Items."""
    sammlung = _mit_belegen([(40, 75), (44, 78), (46, 80), (48, 84), (50, 85)])
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record)

    assert "Tiers" in text
    # Auf den GRUND pruefen, nicht auf "75" — die Zahl steht auch in der
    # Kopfzeile des Abschnitts ("item level 75-85"), der Test waere ohne
    # den Grund gruen geblieben.
    assert mod_tiers.why_silent([(40, 75), (44, 78), (46, 80),
                                 (48, 84), (50, 85)]) in text
    # Keine geratene Leiter: keine Zeile der Form "12–17  from item level 3".
    band_zeilen = [z for z in text.splitlines()
                   if "from item level" in z and "–" in z.split("from")[0]]
    assert band_zeilen == []


def test_a_record_without_evidence_shows_no_tier_section() -> None:
    """Kein leerer Abschnitt, wo es nichts zu sagen gibt."""
    record = _sammlung().get("explicitMods", "+96 to maximum Life")

    assert "Tiers" not in format_record_detail(record)


def test_the_band_section_marks_what_is_proven_and_what_is_assumed() -> None:
    """Die Grenze zwischen Beleg und Annahme muss im Fenster stehen, nicht
    nur im Quelltext — sonst liest sich die Leiter wie Spielwissen."""
    sammlung = _mit_belegen([(6, 5), (12, 14), (18, 26), (24, 38), (30, 50)])
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record)

    assert "proven" in text
    assert "assume" in text



# ---------------------------- Kartenansicht ----------------------------- #
# §4.52.5 — das Album-Gefuehl: Karten, Sortier-Linsen, Sammlungs-Puls.

def _sammlung_mit_neuzugang() -> ModCollection:
    """Grundstock aus zwei Mods, danach EIN frischer Fund (Einzelstueck)."""
    sammlung = ModCollection()
    for wert in (41, 96):
        sammlung.observe("explicitMods", f"+{wert} to maximum Life", rarity=2)
    sammlung.observe("implicitMods", "+20% to Fire Resistance", rarity=2)
    sammlung.observe("implicitMods", "+25% to Fire Resistance", rarity=2)
    sammlung.clear_new()
    sammlung.observe("explicitMods", "+30% to Cold Resistance", rarity=2)
    return sammlung


def test_the_model_knows_which_records_are_new(qapp) -> None:
    from poe_view.ui.mod_album import NEW_ROLE, RECORD_ROLE

    dialog = ModAlbumDialog(_sammlung_mit_neuzugang())
    model = dialog._model

    je_identitaet = {model.data(model.index(r, 0), RECORD_ROLE).identity:
                     model.data(model.index(r, 0), NEW_ROLE)
                     for r in range(model.rowCount())}

    assert je_identitaet["#% to Cold Resistance"] is True
    assert je_identitaet["# to maximum Life"] is False


def test_the_identity_column_carries_its_full_text_as_tooltip(qapp) -> None:
    """Die laengste Identitaet in Peters Bestand ist 381 Zeichen lang —
    auf einer Karte stehen davon zwei Zeilen, der Rest braucht den
    Tooltip."""
    dialog = ModAlbumDialog(_sammlung())
    model = dialog._model
    idx = model.index(0, IDENTITY_COL)

    from PySide6.QtCore import Qt
    assert model.data(idx, Qt.ItemDataRole.ToolTipRole) == model.data(
        idx, Qt.ItemDataRole.DisplayRole)


def test_newest_finds_sorts_the_fresh_record_first(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung_mit_neuzugang())
    index = dialog._sort_combo.findData("Newest finds")
    assert index >= 0

    dialog._sort_combo.setCurrentIndex(index)

    oberste = dialog._proxy.index(0, IDENTITY_COL).data()
    assert oberste == "#% to Cold Resistance"


def test_seen_once_first_sorts_the_singles_to_the_top(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung_mit_neuzugang())
    index = dialog._sort_combo.findData("Seen once first")

    dialog._sort_combo.setCurrentIndex(index)

    erster = dialog._proxy.index(0, COUNT_COL).data()
    letzter = dialog._proxy.index(dialog._proxy.rowCount() - 1, COUNT_COL).data()
    assert erster == 1
    assert letzter == 2


def test_the_album_opens_on_the_cards(qapp) -> None:
    """Die Karten SIND das Album — die Tabelle bleibt das Werkzeug einen
    Klick dahinter."""
    dialog = ModAlbumDialog(_sammlung())

    assert dialog._stack.currentWidget() is dialog._cards
    assert dialog._sort_combo.isEnabled()


def test_switching_to_the_table_restores_header_sorting(qapp) -> None:
    """Eine uebrig gebliebene Sortier-Rolle wuerde jeden Kopf-Klick auf
    der Mod-Spalte still umdeuten (FIRST_SEEN statt Text)."""
    from PySide6.QtCore import Qt
    dialog = ModAlbumDialog(_sammlung_mit_neuzugang())
    dialog._sort_combo.setCurrentIndex(dialog._sort_combo.findData("Newest finds"))

    dialog._toggle_view()

    assert dialog._stack.currentWidget() is dialog._table
    assert not dialog._sort_combo.isEnabled()
    assert dialog._proxy.sortRole() == Qt.ItemDataRole.DisplayRole


def test_both_views_share_one_selection(qapp) -> None:
    dialog = ModAlbumDialog(_sammlung())

    assert dialog._cards.selectionModel() is dialog._table.selectionModel()


def test_the_cards_render_without_errors(qapp) -> None:
    """Rauchtest fuers Zeichnen: neu + Einzelstueck + Auswahl in einem
    Bild. KEINE Pixel-Aussage — Farben werden am echten Fenster gemessen,
    nicht offscreen (CLAUDE.md)."""
    from PySide6.QtGui import QPixmap
    dialog = ModAlbumDialog(_sammlung_mit_neuzugang())
    dialog.resize(700, 400)
    dialog.show()
    dialog._cards.setCurrentIndex(dialog._proxy.index(0, 0))

    bild = QPixmap(dialog._cards.viewport().size())
    dialog._cards.viewport().render(bild)

    assert not bild.isNull()


def test_the_greeting_counts_singles_and_news() -> None:
    from poe_view.ui.mod_album import collection_greeting
    sammlung = _sammlung_mit_neuzugang()

    text = collection_greeting(sammlung.records(), sammlung.new_keys())

    assert "3 mods" in text
    # Nur Cold Res ist ein Einzelstueck — Fire Res wurde zweimal gesehen.
    assert "1 of them seen exactly once" in text
    assert "1 new this session" in text
    assert "Latest find:" in text


def test_the_detail_names_the_entry_date_only_when_known() -> None:
    from poe_view.services.mod_collection import ModRecord
    from poe_view.ui.mod_album import first_seen_text
    sammlung = _sammlung_mit_neuzugang()

    frisch = sammlung.get("explicitMods", "+30% to Cold Resistance")
    grundstock = ModRecord(identity="# to Armour", kind="explicitMods")

    assert "entered the collection on 20" in format_record_detail(frisch)
    assert first_seen_text(grundstock) == ""
    assert "entered the collection" not in format_record_detail(grundstock)


# --------------------------- Die Band-Tabelle ---------------------------- #
# Peters Wunsch (2026-08-27): je Tier eine Zeile "Count | Min | Max |
# iLvl-Min | iLvl-Max" — und die Baender heissen vorerst PROZENT der
# gesehenen Spanne, nicht T-Nummern: "Wenn wir Zahlen benutzen ist das
# mit Ingame verwechselbar und gerade am Anfang stimmt das noch nicht."

def _konto_mit_zwei_baendern() -> dict:
    """Werte 6-8 auf niedrigen Stufen, 18-20 auf hohen. TIER_JUMP misst
    den Abstand im ITEM-LEVEL der Einhuellenden: Innerhalb einer Gruppe
    bleiben die iLvl-Schritte darunter (5->7, 26->28), dazwischen liegt
    der Sprung (7->26) — genau zwei Baender."""
    return {6.0: [4, 5, 20], 8.0: [7, 7, 30], 18.0: [2, 26, 60],
            20.0: [1, 28, 33]}


def test_the_band_table_counts_per_band() -> None:
    from poe_view.services.mod_collection import ModRecord
    from poe_view.ui.mod_album import band_table
    eintrag = ModRecord(identity="#% to Cold Resistance", kind="explicitMods")
    eintrag.tier_ledger["Ring"] = _konto_mit_zwei_baendern()
    baender = mod_tiers.bands(eintrag.tier_front("Ring"))

    zeilen = band_table(eintrag.tier_ledger["Ring"], baender)

    # Kopfzeile + eine Zeile je Band
    assert len(zeilen) == 1 + len(baender)
    assert "Seen" in zeilen[0] and "Values" in zeilen[0]
    # Band 1: 4+7 Sichtungen der Werte 6-8 auf Stufen 5-30
    assert "11" in zeilen[1] and "6–8" in zeilen[1] and "5–30" in zeilen[1]
    # Band 2: 2+1 Sichtungen der Werte 18-20 auf Stufen 26-60
    assert "3" in zeilen[2] and "18–20" in zeilen[2] and "26–60" in zeilen[2]


def test_the_bands_are_labelled_in_percent_not_tiers() -> None:
    """Die unterste Bandgrenze ist 0 %, die oberste 100 % — und nirgends
    steht ein "T", das nach Spielwissen aussieht."""
    from poe_view.services.mod_collection import ModRecord
    from poe_view.ui.mod_album import band_table
    eintrag = ModRecord(identity="#% to Cold Resistance", kind="explicitMods")
    eintrag.tier_ledger["Ring"] = _konto_mit_zwei_baendern()
    baender = mod_tiers.bands(eintrag.tier_front("Ring"))

    zeilen = band_table(eintrag.tier_ledger["Ring"], baender)

    assert zeilen[1].startswith("0–")
    assert "100 %" in zeilen[-1]
    assert not any(z.lstrip().startswith("T") for z in zeilen[1:])


def test_every_ledger_value_lands_in_exactly_one_band() -> None:
    """Auch ein halbzahliger Wert zwischen zwei ganzzahligen Grenzen darf
    nicht durchfallen — die Summe der Band-Zaehler ist die Zahl aller
    Sichtungen."""
    from poe_view.services.mod_collection import ModRecord
    from poe_view.ui.mod_album import band_table
    konto = _konto_mit_zwei_baendern()
    konto[11.5] = [9, 12, 12]      # zwischen Band 1 (bis 8) und Band 2 (ab 9)
    eintrag = ModRecord(identity="#% to Cold Resistance", kind="explicitMods")
    eintrag.tier_ledger["Ring"] = konto
    baender = mod_tiers.bands(eintrag.tier_front("Ring"))

    zeilen = band_table(konto, baender)

    # Aufbau einer Zeile: "0–14 %   11  6–8   5–30" — das dritte Token
    # ist der Zaehler (das zweite ist das %-Zeichen des Labels).
    gezaehlt = sum(int(z.split()[2]) for z in zeilen[1:])
    assert gezaehlt == sum(z[0] for z in konto.values())


def test_the_detail_shows_the_band_table_with_sightings() -> None:
    sammlung = _mit_belegen([(6, 5), (12, 14), (18, 26), (24, 38), (30, 50)])
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record)

    assert "sightings" in text
    assert "%" in text
    assert "Seen" in text


def test_only_the_band_table_is_monospace() -> None:
    """Peter, 2026-08-28: "Durch die gesperrte Schrift im Info-Feld ist
    dieses Feld kaum noch lesbar. Falls wir eine Tabelle hier machen
    darf nur diese Tabelle in gesperrter Schrift sein." Der Fliesstext
    bleibt also draussen vor dem <pre>-Block, die Tabelle drin."""
    from poe_view.ui.mod_album import record_detail_html
    sammlung = _mit_belegen([(6, 5), (12, 14), (18, 26), (24, 38), (30, 50)])
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    html = record_detail_html(record, "TestMono")

    kopf, _, tabelle = html.partition("<pre")
    assert "seen 1× in total" in kopf          # Fliesstext: proportional
    assert "TestMono" in tabelle               # Tabelle: feste Schrift
    assert "Tiers, inferred" in tabelle
    assert "Seen" in tabelle


def test_a_record_without_bands_needs_no_pre_block() -> None:
    from poe_view.ui.mod_album import record_detail_html
    record = _sammlung().get("explicitMods", "+96 to maximum Life")

    html = record_detail_html(record, "TestMono")

    assert "<pre" not in html
    assert "seen 2× in total" in html


# ------------- Die echten Tier-Leitern aus dem Mod-Wissen (§4.53) -------- #

def _leiter(*sprossen, kategorien=("Ring",)):
    """Ein Mod-Wissen mit derselben Leiter fuer jede genannte Kategorie.
    Sprossen als (required_level, low, high)."""
    from poe_view.services.mod_knowledge import Knowledge, TierStep
    stufen = [TierStep(lv, lo, hi) for lv, lo, hi in sprossen]
    return Knowledge({("#% to Cold Resistance", kat): list(stufen)
                     for kat in kategorien})


def _mit_konto(werte: dict, kategorie: str = "Ring") -> ModCollection:
    """Sammlung mit einem Eintrag, dessen Kontenbuch genau diese
    Wert-zu-Sichtungszahl-Zuordnung traegt."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+27% to Cold Resistance", rarity=2)
    sammlung.clear_new()
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")
    record.tier_ledger[kategorie] = {float(w): [n, 50, 60] for w, n in werte.items()}
    return sammlung


def test_tier_one_is_the_last_rung_not_the_first() -> None:
    """PoE zaehlt von oben: die zuletzt freigeschaltete Sprosse ist T1."""
    from poe_view.services.mod_knowledge import TierStep
    ladder = [TierStep(1, 6, 11), TierStep(24, 12, 17), TierStep(48, 18, 23)]

    assert tier_number(ladder, 0) == "T3"
    assert tier_number(ladder, 2) == "T1"


def test_collected_tiers_counts_rungs_not_sightings() -> None:
    from poe_view.services.mod_knowledge import TierStep
    ladder = [TierStep(1, 6, 11), TierStep(24, 12, 17), TierStep(48, 18, 23)]

    # 200 Sichtungen, aber nur in zwei der drei Sprossen.
    assert collected_tiers({7.0: [199, 5, 9], 20.0: [1, 60, 60]}, ladder) == (2, 3)
    assert collected_tiers({}, ladder) == (0, 3)


def test_the_ladder_shows_the_rungs_you_have_not_rolled_yet() -> None:
    """Der Sammelalbum-Teil: die leeren Felder gehoeren dazu, sonst
    saehe eine halbe Sammlung aus wie eine volle."""
    sammlung = _mit_konto({7: 3, 20: 5})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record, _leiter((1, 6, 11), (24, 12, 17), (48, 18, 23)))

    assert "not seen yet" in text          # T2 (12-17) fehlt
    assert "2 of 3 tiers collected" in text


def test_a_complete_ladder_says_nothing_is_missing() -> None:
    sammlung = _mit_konto({7: 3, 14: 2, 20: 5})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record, _leiter((1, 6, 11), (24, 12, 17), (48, 18, 23)))

    assert "3 of 3 tiers collected" in text
    assert "not seen yet" not in text


def test_values_outside_every_rung_get_their_own_line() -> None:
    """Gecraftete, mit Essenz gerollte und beeinflusste Mods rollen aus
    eigenen Tabellen - ihre Werte liegen neben der Leiter. Sie zu
    verschweigen waere falsch, gerade die hohen sind interessant."""
    sammlung = _mit_konto({7: 3, 99: 2})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record, _leiter((1, 6, 11), (24, 12, 17)))

    assert "beyond the ladder" in text
    assert "99" in text
    # Und sie zaehlen NICHT als gesammeltes Tier.
    assert "1 of 2 tiers collected" in text


def test_the_real_ladder_replaces_the_estimated_bands() -> None:
    """Wo eine echte Leiter bekannt ist, hat die Schaetzung nichts mehr
    zu suchen - zwei Tabellen fuer dieselbe Frage wuerden sich
    widersprechen."""
    sammlung = _mit_konto({7: 3, 14: 2, 20: 5})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record, _leiter((1, 6, 11), (24, 12, 17), (48, 18, 23)))

    assert LADDER_HEADING in text
    assert BANDS_HEADING not in text


def test_without_a_ladder_the_estimated_bands_stay() -> None:
    """Peters Begruendung fuer die Prozent-Baender gilt unveraendert
    dort weiter, wo wir die echte Leiter nicht haben."""
    sammlung = _mit_belegen([(6, 5), (12, 14), (18, 26), (24, 38), (30, 50)])
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = format_record_detail(record, _leiter())   # Leiter ohne Sprossen

    assert BANDS_HEADING in text
    assert LADDER_HEADING not in text
    assert "%" in text


def test_a_record_can_show_both_tables_at_once() -> None:
    """Ein Mod auf zwei Kategorien, von denen nur eine eine Leiter hat:
    beide Tabellen stehen da, getrennt beschriftet."""
    sammlung = _mit_konto({7: 3, 20: 5})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")
    record.tier_ledger["Amulet"] = {float(w): [1, il, il]
                                   for w, il in [(6, 5), (12, 14), (18, 26),
                                                (24, 38), (30, 50)]}

    text = format_record_detail(record, _leiter((1, 6, 11), (24, 12, 17)))

    assert LADDER_HEADING in text
    assert BANDS_HEADING in text
    # Die echte Leiter zuerst - sie ist die belastbarere Aussage.
    assert text.index(LADDER_HEADING) < text.index(BANDS_HEADING)


def test_categories_are_ordered_by_sightings_not_alphabetically() -> None:
    """Feuerresistenz hat in Peters Bestand 24 Kategorien zu je elf
    Zeilen. Alphabetisch stuende eine Kategorie mit zwei Sichtungen
    ueber einer mit zweihundert.

    BEIDE Kategorien brauchen hier eine Leiter, sonst landen sie in
    verschiedenen Bloecken und der Test prueft nur deren Reihenfolge
    (so gebaut ueberlebte er seine Gegenprobe)."""
    sammlung = _mit_konto({7: 2}, kategorie="Amulet")
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")
    record.tier_ledger["Ring"] = {7.0: [200, 50, 60]}

    text = format_record_detail(
        record, _leiter((1, 6, 11), kategorien=("Ring", "Amulet")))

    assert text.index("Ring") < text.index("Amulet")


def test_only_the_tables_are_monospace_whichever_comes_first() -> None:
    """record_detail_html teilt an der ERSTEN Tabellen-Ueberschrift.
    Bei einer echten Leiter ist das eine andere als bei den Baendern."""
    sammlung = _mit_konto({7: 3, 20: 5})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    html = record_detail_html(record, "Courier New",
                             _leiter((1, 6, 11), (24, 12, 17), (48, 18, 23)))

    kopf, _, tabelle = html.partition("<pre")
    assert LADDER_HEADING not in kopf      # Ueberschrift gehoert zur Tabelle
    assert LADDER_HEADING in tabelle
    assert "seen 1" in kopf                # Fliesstext bleibt proportional


# ------------------------- Der Tier-Zaehler in der Range ----------------- #

def test_the_range_column_appends_the_tier_progress() -> None:
    sammlung = _mit_konto({7: 3, 20: 5})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    text = range_column_text(record, None, None,
                            _leiter((1, 6, 11), (24, 12, 17), (48, 18, 23)))

    assert text.endswith("2/3")


def test_the_tier_progress_disappears_once_a_pot_filter_is_active() -> None:
    """Die Range links zeigt dann nur die ausgewaehlten Toepfe, das
    Kontenbuch dahinter kennt weder Liga noch Raritaet. Zwei Zahlen ueber
    verschiedene Populationen in einer Zelle - genau das, was Peter an
    der frueheren Seen-Spalte aufgefallen ist."""
    sammlung = _mit_konto({7: 3, 20: 5})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")
    ladder = _leiter((1, 6, 11), (24, 12, 17), (48, 18, 23))

    assert "/" not in range_column_text(record, LEGACY_LEAGUE, None, ladder)
    assert "/" not in range_column_text(record, None, lambda r: r == 2, ladder)


def test_without_mod_knowledge_the_range_column_is_unchanged() -> None:
    sammlung = _mit_konto({7: 3, 20: 5})
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    assert (range_column_text(record, None, None, None)
            == combined_range_text(record, None, None))


def test_the_tier_progress_follows_the_category_with_the_most_sightings() -> None:
    """Ein Mod, der ueberwiegend auf Ringen durch die Haende geht, soll
    seinen Ring-Stand zeigen - nicht den einer Kategorie, von der
    zufaellig ein Stueck herumliegt."""
    sammlung = _mit_konto({7: 2}, kategorie="Amulet")
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")
    record.tier_ledger["Ring"] = {7.0: [200, 50, 60], 14.0: [50, 50, 60]}

    # Beide Kategorien haben hier eine Leiter, damit wirklich die
    # SICHTUNGSZAHL entscheidet und nicht die Verfuegbarkeit.
    stand = tier_progress(record, _leiter((1, 6, 11), (24, 12, 17),
                                         kategorien=("Ring", "Amulet")))
    assert stand == (2, 2)          # Ring: Werte 7 und 14 treffen beide Sprossen
    # Amulet allein haette nur eine getroffen.
    assert collected_tiers(record.tier_ledger["Amulet"],
                          _leiter((1, 6, 11), (24, 12, 17),
                                 kategorien=("Amulet",)).ladder(
                                     "#% to Cold Resistance", "Amulet")) == (1, 2)


def test_tier_progress_is_none_when_no_ladder_matches() -> None:
    sammlung = _mit_konto({7: 3}, kategorie="Belt")
    record = sammlung.get("explicitMods", "+27% to Cold Resistance")

    assert tier_progress(record, _leiter((1, 6, 11))) is None
    assert tier_progress(record, None) is None
