"""Tests für die Beute-Mitschrift (``services/zone_loot_log.py``).

Peters Maßstab für die Lukrativität, 2026-09-27: "Aus meiner Sicht, SSF
Ruthless, wird die Lukrativität in Währung, Blue- und Yellow-Items
gemessen." Genau diese drei Eimer müssen stimmen; die Zahlen in den
Docstrings stammen aus der Messung an seinem echten Programmlog.
"""

import csv

from poe_view.api.models import Item
from poe_view.api.ninja import PriceIndex
from poe_view.services import zone_loot_log
from poe_view.services.zone_loot_log import Row, tally


def _item(id_: str, frame: int, name: str = "Thing", stack: int | None = None) -> Item:
    roh = {"id": id_, "typeLine": name, "frameType": frame}
    if stack is not None:
        roh["stackSize"] = stack
    return Item.model_validate(roh)


# --- Die Eimer ----------------------------------------------------------- #

def test_the_rarities_peter_named_get_their_own_buckets() -> None:
    """"Währung, Blue- und Yellow-Items" — frameType 5, 1 und 2."""
    gezaehlt = tally([_item("a", 1), _item("b", 2), _item("c", 2),
                      _item("d", 5, "Chaos Orb", 3)], [])

    assert gezaehlt.counts["magic"] == 1
    assert gezaehlt.counts["rare"] == 2
    assert gezaehlt.counts["currency"] == 3


def test_currency_counts_pieces_not_stacks() -> None:
    """Ein Stapel von drei Chaos Orbs ist drei Chaos Orbs. Zählte man
    Stapel, hinge die Zahl davon ab, wie das Inventar gerade aufgeräumt
    ist — keine Eigenschaft der Zone."""
    assert tally([_item("a", 5, "Chaos Orb", 3)], []).counts["currency"] == 3
    assert tally([_item("a", 2, "Rare Ring")], []).counts["rare"] == 1


def test_a_growing_stack_is_the_gain_that_would_otherwise_be_invisible() -> None:
    """Währung landet meist auf einem Stapel, den es schon gibt — ein
    Chaos Orb mehr ist keine Item-Neuheit, sondern ``stackSize`` 12 → 13.
    Ohne diesen Weg wäre ausgerechnet Peters erstgenannte Größe blind."""
    gezaehlt = tally([], [(_item("a", 5, "Chaos Orb", 13), 1)])

    assert gezaehlt.counts["currency"] == 1
    assert not gezaehlt.empty


def test_a_shrinking_stack_is_not_a_negative_gain() -> None:
    """Ausgeben oder Einlagern ist kein Ertrag. Ein negativer Eintrag
    würde eine Zone dafür bestrafen, dass in ihr gecraftet wurde."""
    gezaehlt = tally([], [(_item("a", 5, "Chaos Orb", 2), -9)])

    assert gezaehlt.counts["currency"] == 0
    assert gezaehlt.empty


def test_relics_and_foils_count_as_uniques() -> None:
    """frameType 9 und 10 sind Spielarten des Uniques (``FRAME_TYPE_NAMES``),
    kein eigener Rang."""
    assert tally([_item("a", 9), _item("b", 10)], []).counts["unique"] == 2


def test_an_unknown_frame_type_lands_in_other_instead_of_vanishing() -> None:
    assert tally([_item("a", 99)], []).counts["other"] == 1


def test_the_currency_detail_names_what_came_in() -> None:
    """Für SSF Ruthless ist "zwei Alterations" etwas anderes als "zwei
    Divines" — die reine Stückzahl verlöre genau das."""
    gezaehlt = tally([_item("a", 5, "Orb of Alteration", 2)],
                     [(_item("b", 5, "Chaos Orb", 4), 1)])

    assert gezaehlt.currency_detail == "Chaos Orb 1; Orb of Alteration 2"


def test_nothing_gained_is_empty() -> None:
    assert tally([], []).empty


# --- Der Chaos-Wert ------------------------------------------------------ #

def test_chaos_sums_only_what_poe_ninja_knows() -> None:
    """Ein unbekannter Preis ist kein Wert von 0 (FALLSTRICKE #39). In
    Ruthless kennt poe.ninja die halbe Liga nicht — die Spalte ist eine
    Untergrenze, die Zählungen daneben sind die verlässliche Aussage."""
    index = PriceIndex()          # kennt ab Werk nur "Chaos Orb" = 1.0
    gezaehlt = tally([_item("a", 5, "Chaos Orb", 3),
                      _item("b", 3, "Unbekanntes Unique")], [], index)

    assert gezaehlt.chaos == 3.0


def test_without_a_price_index_there_is_no_chaos_value() -> None:
    assert tally([_item("a", 5, "Chaos Orb", 3)], []).chaos == 0.0


# --- Die Datei ------------------------------------------------------------ #

def _row(**kwargs) -> Row:
    werte = dict(character="WitchOfPeter", league="Allflame", zone="Chateau",
                 area_id="MapWorldsChateau", instance="123", level=79,
                 trigger="zone change", seconds=284.0,
                 experience=4_200_000_000, experience_gain=12_345)
    return Row(**{**werte, **kwargs})


def test_a_row_lands_in_the_csv_with_its_header(tmp_path) -> None:
    pfad = tmp_path / "loot.csv"
    zone_loot_log.append(_row(), tally([_item("a", 2)], []), pfad)

    zeilen = list(csv.DictReader(pfad.open(encoding="utf-8")))
    assert len(zeilen) == 1
    assert zeilen[0]["zone"] == "Chateau"
    assert zeilen[0]["level"] == "79"
    assert zeilen[0]["rare"] == "1"
    assert zeilen[0]["experience_gain"] == "12345"
    assert zeilen[0]["trigger"] == "zone change"


def test_a_second_row_is_appended_not_a_second_header(tmp_path) -> None:
    pfad = tmp_path / "loot.csv"
    zone_loot_log.append(_row(), tally([], []), pfad)
    zone_loot_log.append(_row(zone="Cage"), tally([], []), pfad)

    assert [z["zone"] for z in csv.DictReader(pfad.open(encoding="utf-8"))] == \
        ["Chateau", "Cage"]


def test_a_file_with_other_columns_is_set_aside_instead_of_corrupted(tmp_path) -> None:
    """Sonst stünden ab hier Werte unter falschen Überschriften —
    rückwirkend auch für den Teil, der stimmte (``gem_xp_log``)."""
    pfad = tmp_path / "loot.csv"
    pfad.write_text("alte;spalten\n1;2\n", encoding="utf-8")

    zone_loot_log.append(_row(), tally([], []), pfad)

    assert [z["zone"] for z in csv.DictReader(pfad.open(encoding="utf-8"))] == ["Chateau"]
    assert [p.name for p in tmp_path.iterdir() if p.name != "loot.csv"]


def test_a_file_over_the_size_limit_is_set_aside(tmp_path, monkeypatch) -> None:
    """Eine Datei, die nur wächst, ist ein Fehler auf Raten — diese läuft
    anders als die Gem-Mitschrift auch in der ausgelieferten .exe."""
    pfad = tmp_path / "loot.csv"
    zone_loot_log.append(_row(), tally([], []), pfad)
    monkeypatch.setattr(zone_loot_log, "_MAX_BYTES", 10)

    zone_loot_log.append(_row(zone="Cage"), tally([], []), pfad)

    assert [z["zone"] for z in csv.DictReader(pfad.open(encoding="utf-8"))] == ["Cage"]


def test_an_unwritable_path_is_survived(tmp_path) -> None:
    """Eine Messung darf das Programm nicht mitreißen."""
    zone_loot_log.append(_row(), tally([], []), tmp_path / "loot.csv" / "tiefer.csv")


def test_the_log_path_follows_the_patched_log_dir() -> None:
    """Sonst schriebe ein Testlauf in Peters echtes Datenverzeichnis
    (CLAUDE.md, "Tests")."""
    from poe_view import config
    assert zone_loot_log.log_path().parent == config.LOG_DIR
