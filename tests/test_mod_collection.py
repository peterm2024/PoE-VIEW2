"""Tests fuer die Mod-Sammlung (ARCHITEKTUR.md §4.52).

Peter, 2026-08-24: "Ich finde die Idee mit der eigenen Datenbank am besten,
hat etwas von einer Briefmarkensammlung."

Geprueft wird die Rechnung, nicht die Anzeige: Identitaet, Spannen je
Raritaet, Bewertung, und die Regeln ums Speichern. Die Sammlung ist der
einzige Ort, an dem ein laengst verkauftes Item noch existiert — deshalb
liegt hier mehr Gewicht auf "geht nichts verloren" als sonst irgendwo.
"""

from __future__ import annotations

import json

import pytest

from poe_view.api.models import Item
from poe_view.services import mod_collection as mc
from poe_view.services.mod_collection import (CORRUPTED_OFFSET, LEGACY_LEAGUE,
                                              tierable,
                                              MAP_RARITY, MIN_LEAGUE_OBSERVATIONS,
                                              UNKNOWN_RARITY, ModCollection,
                                              ModRecord, base_rarity,
                                              collection_bucket, is_corrupted_bucket,
                                              item_buckets, league_bucket,
                                              mod_identity, mod_values)

RARE, UNIQUE, MAGIC = 2, 3, 1


def _item(**felder) -> Item:
    felder.setdefault("typeLine", "Gold Ring")
    return Item.model_validate(felder)


# --------------------------- Die Identitaet ---------------------------- #

def test_the_identity_is_the_line_without_its_numbers() -> None:
    """Zwei Rolls desselben Mods muessen im selben Eintrag landen —
    sonst waere die Sammlung eine Liste von Einzelstuecken."""
    assert mod_identity("+96 to maximum Life") == "# to maximum Life"
    assert mod_identity("+91 to maximum Life") == "# to maximum Life"
    # Das Vorzeichen gehoert zur Zahl und verschwindet mit ihr: Sonst
    # waeren "+40% to Fire Resistance" und "-60% to Fire Resistance" zwei
    # Mods, und die Spanne zeigte den negativen Roll nie.
    assert mod_identity("-96 to maximum Life") == "# to maximum Life"


def test_sign_and_decimals_belong_to_the_number() -> None:
    """Sonst waeren "+96", "96" und "-96" drei verschiedene Mods, und
    "0.5% of Damage" traege eine halbe Zahl in der Identitaet."""
    assert mod_identity("-60% to Fire Resistance") == "#% to Fire Resistance"
    assert mod_identity("60% to Fire Resistance") == "#% to Fire Resistance"
    assert mod_identity("0.5% of Damage Leeched") == "#% of Damage Leeched"


def test_the_values_keep_their_order() -> None:
    """Bei "Adds 1 to 5" ist die erste Zahl das Minimum und die zweite
    das Maximum — zwei getrennte Spannen, nicht eine gemeinsame."""
    assert mod_values("Adds 1 to 5 Lightning Damage") == [1.0, 5.0]


# ---------------------------- Das Sammeln ------------------------------ #

def test_two_rolls_of_one_mod_become_one_entry_with_a_span() -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", ilvl=84, rarity=RARE)
    sammlung.observe("explicitMods", "+91 to maximum Life", ilvl=70, rarity=RARE)

    eintrag = sammlung.get("explicitMods", "+80 to maximum Life")
    assert len(sammlung) == 1
    assert eintrag.count == 2
    assert eintrag.span(RARE).spread == [(91.0, 96.0)]
    assert (eintrag.span(RARE).ilvl_low, eintrag.span(RARE).ilvl_high) == (70, 84)


def test_each_number_gets_its_own_span() -> None:
    """"Adds 3 to 90" ist kein besserer Roll als "Adds 5 to 80", wenn man
    nur auf die erste Zahl schaut — beide Positionen zaehlen einzeln."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "Adds 3 to 90 Fire Damage", rarity=RARE)
    sammlung.observe("explicitMods", "Adds 5 to 80 Fire Damage", rarity=RARE)

    eintrag = sammlung.get("explicitMods", "Adds 1 to 1 Fire Damage")
    assert eintrag.span(RARE).spread == [(3.0, 5.0), (80.0, 90.0)]


def test_the_same_line_on_two_kinds_stays_apart() -> None:
    """Dieselbe Zeile bedeutet als Verzauberung etwas anderes als als
    Affix — und rollt aus einer anderen Tabelle."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+10% to Fire Resistance", rarity=RARE)
    sammlung.observe("enchantMods", "+10% to Fire Resistance", rarity=RARE)

    assert len(sammlung) == 2


# ------------------------ Trennung nach Raritaet ----------------------- #

def test_a_unique_does_not_widen_the_span_of_a_rare() -> None:
    """Der Befund, der diese Trennung erzwungen hat (gemessen an Peters
    Bestand): In einem Topf reichte "#% increased Attack Speed" von 3 bis
    100, weil Uniques feste Werte tragen, die kein Affix je rollt. Die
    Frage "ist das ein guter Roll?" war damit nicht mehr zu beantworten."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "27% increased Attack Speed", rarity=RARE)
    sammlung.observe("explicitMods", "3% increased Attack Speed", rarity=RARE)
    sammlung.observe("explicitMods", "100% increased Attack Speed", rarity=UNIQUE)

    eintrag = sammlung.get("explicitMods", "10% increased Attack Speed")
    assert eintrag.span(RARE).spread == [(3.0, 27.0)]
    assert eintrag.span(UNIQUE).spread == [(100.0, 100.0)]
    assert eintrag.count == 3           # gesammelt ist trotzdem alles


def test_maps_get_their_own_bucket() -> None:
    """Map-Mods sind keine Ausruestungs-Affixe: Sie rollen aus einer
    anderen Tabelle und oft in die andere Richtung ("-60% to Fire
    Resistance" ist dort eine Strafe fuer den Spieler). Die API fuehrt
    Maps aber als Magic oder Rare."""
    karte = _item(typeLine="Toxic Grove Map (Tier 6)", frameType=RARE,
                  explicitMods=["-60% to Fire Resistance"])
    ring = _item(frameType=RARE, explicitMods=["+40% to Fire Resistance"])
    sammlung = ModCollection()
    sammlung.observe_item(karte)
    sammlung.observe_item(ring)

    eintrag = sammlung.get("explicitMods", "+1% to Fire Resistance")
    assert eintrag.span(MAP_RARITY).spread == [(-60.0, -60.0)]
    assert eintrag.span(RARE).spread == [(40.0, 40.0)]


# ------------------------ Corrupted-Aufschlag --------------------------- #
#
# Peter, 2026-08-25: "...auch zwischen Unique, Corrupted, (Normal/Magic/
# Rare)..." — die Album-Anzeige soll danach filtern koennen.


def test_a_corrupted_item_gets_a_different_bucket_than_the_same_rarity() -> None:
    """Der eigentliche Punkt: Ein corrupted Rare landet NICHT im selben
    Topf wie ein gewoehnliches Rare — manche Corruption-Ergebnisse haben
    eine eigene Wertetabelle (z.B. grosse negative Resistenzen als
    Strafe), die sonst die gewoehnliche Spanne verzerrt haetten."""
    normal = _item(frameType=RARE, corrupted=False)
    korrumpiert = _item(frameType=RARE, corrupted=True)

    assert collection_bucket(normal) != collection_bucket(korrumpiert)


def test_corrupted_rare_and_corrupted_unique_stay_apart() -> None:
    """Der Aufschlag darf die Rarity-Trennung nicht wieder aufheben, die
    §4.52.1 ueberhaupt erst erzwungen hat."""
    rare = _item(frameType=RARE, corrupted=True)
    unique = _item(frameType=UNIQUE, corrupted=True)

    assert collection_bucket(rare) != collection_bucket(unique)


def test_maps_do_not_get_the_corrupted_offset() -> None:
    """Maps haben schon ihren eigenen Topf, und Kartenkorruption fuegt
    keine neuen Implicit-Zeilen mit eigener Tabelle hinzu wie bei
    Ausruestung — der Grund fuer den Aufschlag greift dort nicht."""
    karte = _item(typeLine="Toxic Grove Map (Tier 6)", frameType=RARE, corrupted=True)

    assert collection_bucket(karte) == MAP_RARITY


def test_base_rarity_undoes_the_offset() -> None:
    korrumpiert = collection_bucket(_item(frameType=RARE, corrupted=True))

    assert is_corrupted_bucket(korrumpiert) is True
    assert base_rarity(korrumpiert) == RARE
    assert is_corrupted_bucket(RARE) is False
    assert base_rarity(RARE) == RARE


def test_base_rarity_handles_the_boundary_at_normal() -> None:
    """frameType 0 ("Normal") plus Aufschlag trifft genau
    ``CORRUPTED_OFFSET`` selbst — ein ``>`` statt ``>=`` haette genau
    diesen einen Fall uebersehen."""
    korrumpiert = collection_bucket(_item(frameType=0, corrupted=True))

    assert korrumpiert == CORRUPTED_OFFSET
    assert is_corrupted_bucket(korrumpiert) is True
    assert base_rarity(korrumpiert) == 0


def test_an_uncorrupted_item_keeps_the_plain_rarity() -> None:
    assert collection_bucket(_item(frameType=RARE, corrupted=False)) == RARE


def test_corrupted_items_get_their_own_spans() -> None:
    korrupt = _item(frameType=RARE, corrupted=True,
                    explicitMods=["-60% to Cold Resistance"])
    normal = _item(frameType=RARE, corrupted=False,
                   explicitMods=["+40% to Cold Resistance"])
    sammlung = ModCollection()
    sammlung.observe_item(korrupt)
    sammlung.observe_item(normal)

    eintrag = sammlung.get("explicitMods", "+1% to Cold Resistance")
    assert eintrag.span(RARE).spread == [(40.0, 40.0)]
    assert eintrag.span(RARE + CORRUPTED_OFFSET).spread == [(-60.0, -60.0)]


def test_an_item_without_a_rarity_is_not_counted_as_white() -> None:
    """``frameType`` 0 heisst "Normal". Ein fehlendes Feld heisst "weiss
    ich nicht" — beides gleichzusetzen waere eine erfundene Aussage."""
    sammlung = ModCollection()
    sammlung.observe_item(_item(explicitMods=["+5 to Strength"]))

    eintrag = sammlung.get("explicitMods", "+5 to Strength")
    assert eintrag.rarities == [UNKNOWN_RARITY]


# ---------------------------- Die Bewertung ---------------------------- #

def test_the_rating_places_a_roll_in_what_you_have_seen() -> None:
    sammlung = ModCollection()
    for wert in (80, 96):
        sammlung.observe("explicitMods", f"+{wert} to maximum Life", rarity=RARE)
    eintrag = sammlung.get("explicitMods", "+80 to maximum Life")

    assert eintrag.rating("+80 to maximum Life", RARE) == 0.0
    assert eintrag.rating("+96 to maximum Life", RARE) == 1.0
    assert eintrag.rating("+88 to maximum Life", RARE) == pytest.approx(0.5)


def test_a_single_sighting_gives_no_rating() -> None:
    """Aus einem einzigen Wert laesst sich nicht sagen, ob er gut ist.
    Ein erfundener Vergleich waere schlimmer als keiner."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=RARE)
    eintrag = sammlung.get("explicitMods", "+96 to maximum Life")

    assert eintrag.rating("+96 to maximum Life", RARE) is None


def test_the_rating_stays_inside_its_own_rarity() -> None:
    """Ein Rare gegen die festen Werte eines Uniques zu vergleichen
    ergaebe eine Zahl, die nichts bedeutet."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "3% increased Attack Speed", rarity=UNIQUE)
    sammlung.observe("explicitMods", "100% increased Attack Speed", rarity=UNIQUE)
    eintrag = sammlung.get("explicitMods", "10% increased Attack Speed")

    assert eintrag.rating("10% increased Attack Speed", UNIQUE) is not None
    assert eintrag.rating("10% increased Attack Speed", RARE) is None


def test_a_line_without_numbers_has_nothing_to_rate() -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "Cannot be Frozen", rarity=RARE)
    eintrag = sammlung.get("explicitMods", "Cannot be Frozen")

    assert eintrag.count == 1
    assert eintrag.rating("Cannot be Frozen", RARE) is None


# ------------------------ Aus einem echten Item ------------------------ #

def test_the_colour_markup_does_not_end_up_in_the_identity() -> None:
    """GGG faerbt manche Mod-Texte (``<currencyitem>{...}``). Wer die
    rohen Felder liest, sammelt dieselbe Zeile zweimal — einmal mit
    Markup, einmal ohne."""
    sammlung = ModCollection()
    sammlung.observe_item(_item(frameType=RARE,
                                explicitMods=["<currencyitem>{+96 to maximum Life}"]))
    sammlung.observe_item(_item(frameType=RARE, explicitMods=["+91 to maximum Life"]))

    assert len(sammlung) == 1
    assert "<" not in sammlung.records()[0].identity


def test_the_rarer_mod_fields_are_collected_too() -> None:
    """``utilityMods`` (Flaschen) haben in Peters Bestand 2083 Items —
    beim ersten Entwurf dieser Datei hatte ich das Feld vergessen. Genau
    davor warnt der Kommentar an ``EXTRA_MOD_FIELDS``."""
    flasche = _item(typeLine="Quicksilver Flask", frameType=MAGIC,
                    utilityMods=["25% increased Movement Speed"])
    sammlung = ModCollection()
    sammlung.observe_item(flasche)

    assert sammlung.get("utilityMods", "25% increased Movement Speed") is not None


# ---------------------------- Speichern -------------------------------- #

def test_the_collection_survives_the_round_trip(tmp_path) -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", ilvl=84, rarity=RARE)
    sammlung.observe("explicitMods", "+80 to maximum Life", ilvl=70, rarity=RARE)
    sammlung.observe("explicitMods", "Adds 1 to 5 Fire Damage", rarity=UNIQUE)

    pfad = tmp_path / "sammlung.json"
    assert sammlung.save(pfad) is True
    zurueck = mc.load(pfad)

    assert len(zurueck) == 2
    eintrag = zurueck.get("explicitMods", "+90 to maximum Life")
    assert eintrag.count == 2
    assert eintrag.span(RARE).spread == [(80.0, 96.0)]
    assert eintrag.span(RARE).ilvl_high == 84


def test_nothing_new_means_nothing_written(tmp_path) -> None:
    """Ohne diese Frage schriebe jeder Refresh die ganze Datei neu."""
    pfad = tmp_path / "sammlung.json"
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=RARE)
    assert sammlung.save(pfad) is True

    assert sammlung.save(pfad) is False


def test_a_shrinking_collection_is_not_written(tmp_path) -> None:
    """Die Sammlung waechst nur. Wuerde sie schrumpfen, ist etwas kaputt
    — und der alte Stand ist das einzige Exemplar (FALLSTRICKE #62)."""
    pfad = tmp_path / "sammlung.json"
    voll = ModCollection()
    for attribut in ("Strength", "Dexterity", "Intelligence", "Life", "Mana"):
        voll.observe("explicitMods", f"+5 to maximum {attribut}", rarity=RARE)
    voll.save(pfad)

    duenn = ModCollection()
    duenn.observe("explicitMods", "+5 to maximum Strength", rarity=RARE)

    assert duenn.save(pfad) is False
    assert len(mc.load(pfad)) == 5


def test_an_unreadable_file_is_never_overwritten(tmp_path) -> None:
    """Sie koennte reparierbar sein. Ein stiller Neuanfang waere der
    Verlust der ganzen Sammlung."""
    pfad = tmp_path / "sammlung.json"
    pfad.write_text("{kaputt", encoding="utf-8")

    sammlung = mc.load(pfad)

    assert len(sammlung) == 0
    assert sammlung.dirty is False          # nichts zu speichern = nichts zu ueberschreiben
    assert sammlung.save(pfad) is False
    assert pfad.read_text(encoding="utf-8") == "{kaputt"


def test_one_broken_row_does_not_cost_the_collection(tmp_path) -> None:
    pfad = tmp_path / "sammlung.json"
    pfad.write_text(json.dumps({"version": mc.VERSION, "mods": [
        {"identity": "# to maximum Life", "kind": "explicitMods", "count": 3},
        {"kaputt": True},
        {"identity": "", "kind": "explicitMods"},
        {"identity": "# to Strength", "kind": "kein solches Feld"},
    ]}), encoding="utf-8")

    sammlung = mc.load(pfad)

    assert len(sammlung) == 1
    assert sammlung.get("explicitMods", "+5 to maximum Life").count == 3


def test_whole_numbers_stay_whole_in_the_file(tmp_path) -> None:
    """Sonst staende in der Datei 96.0 fuer etwas, das im Spiel 96 heisst."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=RARE)
    pfad = tmp_path / "sammlung.json"
    sammlung.save(pfad)

    assert "96.0" not in pfad.read_text(encoding="utf-8")


def test_each_account_gets_its_own_file() -> None:
    """Wie beim Daten-Cache und beim XP-Verlauf."""
    assert mc.path_for("TestAccount#1234") != mc.path_for("Anderer#1")
    assert "TestAccount" in mc.path_for("TestAccount#1234").name


# ------------------------- Was ist neu? -------------------------------- #

def test_the_first_sighting_is_marked_as_new() -> None:
    """Das Sammler-Erlebnis. Ohne diesen Merker gaebe es es nicht: Die
    Anzeige sieht ein Item immer erst, NACHDEM es eingetragen wurde — zum
    Anzeigezeitpunkt ist also nichts mehr neu."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=RARE)

    assert sammlung.is_new("explicitMods", "+80 to maximum Life") is True
    assert sammlung.is_new("explicitMods", "+80 to Strength") is False


def test_the_starting_stock_is_not_a_find() -> None:
    """6125 Eintraege auf einmal sind kein Fund — nach der Erstbefuellung
    aus dem Cache faengt das Zaehlen von vorn an."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=RARE)
    sammlung.clear_new()

    assert sammlung.is_new("explicitMods", "+96 to maximum Life") is False

    sammlung.observe("explicitMods", "+40 to Strength", rarity=RARE)
    assert sammlung.is_new("explicitMods", "+40 to Strength") is True


def test_a_second_sighting_of_a_known_mod_is_no_find() -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=RARE)
    sammlung.clear_new()
    sammlung.observe("explicitMods", "+91 to maximum Life", rarity=RARE)

    assert sammlung.is_new("explicitMods", "+91 to maximum Life") is False


# ------------------------- Die Ligen-Töpfe ----------------------------- #
#
# Peter, 2026-08-24: "Wir sollten beruecksichtigen, dass sich die Werte der
# Mods im Laufe der verschiedenen Ligen geaendert haben."
#
# Gemessen an seinem Bestand: 98 % der Items liegen in DAUERHAFTEN Ligen,
# und die sammeln seit Jahren die Items jeder abgelaufenen Liga ein. Das
# Liga-Feld sagt, wo ein Item LIEGT, nicht wo es gerollt wurde.


def test_the_permanent_leagues_share_one_pot() -> None:
    """Sie lassen sich nicht entmischen: Ein Ring aus Kalandra liegt heute
    in Standard. Sie getrennt zu fuehren taeuschte eine Trennschaerfe vor,
    die es nicht gibt."""
    assert league_bucket("Standard") == LEGACY_LEAGUE
    assert league_bucket("Solo Self-Found") == LEGACY_LEAGUE
    assert league_bucket("Hardcore SSF Ruthless") == LEGACY_LEAGUE
    assert league_bucket(None) == LEGACY_LEAGUE


def test_a_temporary_league_gets_its_own_pot() -> None:
    """Dort wurde alles in dieser Liga gerollt, also nach ihrer Tabelle —
    der einzige Topf, dessen Spanne einen Zeitpunkt bezeichnet."""
    assert league_bucket("Allflame") == "Allflame"
    assert league_bucket("SSF R Allflame") == "SSF R Allflame"


def test_an_unknown_league_counts_as_temporary() -> None:
    """Die richtige Richtung zum Irren: Eine neue dauerhafte Liga stuende
    fuer sich, statt stillschweigend in den Altbestand zu rutschen."""
    assert league_bucket("Nachste Liga") == "Nachste Liga"


def test_the_pot_comes_from_the_item_not_from_the_view() -> None:
    ring = _item(frameType=RARE, league="Standard")
    frisch = _item(frameType=RARE, league="Allflame")

    assert item_buckets(ring) == (LEGACY_LEAGUE, RARE)
    assert item_buckets(frisch) == ("Allflame", RARE)


def test_a_new_league_does_not_widen_the_old_stock() -> None:
    sammlung = ModCollection()
    sammlung.observe_item(_item(frameType=RARE, league="Standard",
                                explicitMods=["+96 to maximum Life"]))
    sammlung.observe_item(_item(frameType=RARE, league="Allflame",
                                explicitMods=["+41 to maximum Life"]))

    eintrag = sammlung.get("explicitMods", "+50 to maximum Life")
    assert eintrag.span(RARE, LEGACY_LEAGUE).spread == [(96.0, 96.0)]
    assert eintrag.span(RARE, "Allflame").spread == [(41.0, 41.0)]
    assert eintrag.count == 2


# ---------- Worauf sich eine Bewertung stuetzt ------------------------- #

def test_a_thin_league_falls_back_to_the_old_stock() -> None:
    """Unter einer Handvoll Rolls ist eine Spanne mehr Zufall als
    Aussage. Dann wird gegen den Altbestand verglichen — und die Antwort
    sagt, dass sie es tut.

    ZWEI verschiedene Werte in der jungen Liga, nicht einer: Bei einem
    einzigen ist die Spanne ohnehin entartet und liefert keinen Vergleich
    — die Schwelle wuerde dann gar nicht befragt, und der Test pruefte
    etwas anderes, als er behauptet."""
    sammlung = ModCollection()
    for wert in (41, 96):
        sammlung.observe("explicitMods", f"+{wert} to maximum Life", rarity=RARE)
    for wert in (50, 60):
        sammlung.observe("explicitMods", f"+{wert} to maximum Life", rarity=RARE,
                         league="Allflame")
    eintrag = sammlung.get("explicitMods", "+50 to maximum Life")
    assert eintrag.span(RARE, "Allflame").count < MIN_LEAGUE_OBSERVATIONS

    # In Allflame waere +60 der Bestwert; im Altbestand ist er Mittelmass.
    wert, grundlage = eintrag.rating_with_basis("+60 to maximum Life", RARE, "Allflame")
    assert grundlage == LEGACY_LEAGUE
    assert wert is not None and wert < 1.0


def test_a_league_with_enough_sightings_stands_on_its_own() -> None:
    sammlung = ModCollection()
    for wert in (41, 96):
        sammlung.observe("explicitMods", f"+{wert} to maximum Life", rarity=RARE)
    for wert in range(50, 50 + MIN_LEAGUE_OBSERVATIONS):
        sammlung.observe("explicitMods", f"+{wert} to maximum Life", rarity=RARE,
                         league="Allflame")
    eintrag = sammlung.get("explicitMods", "+50 to maximum Life")

    hoechster = 50 + MIN_LEAGUE_OBSERVATIONS - 1
    wert, grundlage = eintrag.rating_with_basis(f"+{hoechster} to maximum Life",
                                                RARE, "Allflame")
    assert grundlage == "Allflame"
    assert wert == 1.0, "in DIESER Liga der beste, im Altbestand waere er Mittelmass"


def test_the_first_version_of_the_file_becomes_the_old_stock(tmp_path) -> None:
    """Die Fassung vor der Ligen-Trennung kannte keine Ligen. Was dort
    steht, ist ununterscheidbar gemischt — also genau das, was der
    Altbestand ist. (Zeilen-Ebene: Auf Datei-Ebene wird ein Stand vor
    Aufbau 7 ohnehin neu gezaehlt, siehe unten.)"""
    eintrag = ModRecord.from_row({
        "identity": "# to maximum Life", "kind": "explicitMods", "count": 7,
        "by_rarity": {"2": {"count": 7, "lows": [41], "highs": [96]}},
    })

    assert eintrag.count == 7
    assert eintrag.span(RARE, LEGACY_LEAGUE).spread == [(41.0, 96.0)]


def test_the_rating_says_how_many_sightings_carry_it() -> None:
    """Ein Stern sagte "bester Roll, den ich kenne". Ein gefuellter Balken
    sieht dagegen nach einer Skala aus — wie belastbar die ist, kann nur
    entscheiden, wer die Zahl der Sichtungen kennt (§4.52.2)."""
    eintrag = ModRecord("+# to maximum Life", "explicitMods")
    for wert in (41, 60, 96):
        eintrag.observe(f"+{wert} to maximum Life", rarity=2)

    wert, grundlage, sichtungen = eintrag.rating_detail("+96 to maximum Life", 2)

    assert wert == 1.0
    assert grundlage == LEGACY_LEAGUE
    assert sichtungen == 3


def test_the_sighting_count_belongs_to_the_pot_that_was_used() -> None:
    """Faellt der Vergleich auf den Altbestand zurueck, ist die Zahl die
    des Altbestands — nicht die der duennen Liga, die gerade verworfen
    wurde. Sonst haette der Aufrufer eine Zahl, die zu einer anderen
    Spanne gehoert."""
    eintrag = ModRecord("+# to maximum Life", "explicitMods")
    for wert in range(41, 97):
        eintrag.observe(f"+{wert} to maximum Life", rarity=2)
    eintrag.observe("+50 to maximum Life", rarity=2, league="Allflame")

    _, grundlage, sichtungen = eintrag.rating_detail("+96 to maximum Life", 2, "Allflame")

    assert grundlage == LEGACY_LEAGUE
    assert sichtungen == 56


def test_an_unknown_pot_reports_no_sightings() -> None:
    eintrag = ModRecord("+# to maximum Life", "explicitMods")
    eintrag.observe("+96 to maximum Life", rarity=2)

    wert, grundlage, sichtungen = eintrag.rating_detail("+96 to maximum Life", 3)

    assert wert is None
    assert grundlage == LEGACY_LEAGUE
    assert sichtungen == 0


# ---------------------- Belege fuer die Tier-Ableitung ------------------- #
#
# Peter, 2026-08-25: "wir kennen das Item-Level; ... dadurch den Tier im
# Laufe der Zeit feststellen koennen." Die Sammlung SAMMELT die Belege;
# gedeutet werden sie erst in ``services/mod_tiers.py``.


def test_only_rolled_affixes_count_as_tier_evidence() -> None:
    """Normal hat keine Affixe, Unique feste Werte, Korrumpiertes bringt
    eigene Wertebereiche mit — nichts davon sagt etwas ueber Tiers."""
    assert tierable(1, 50) is True          # Magic
    assert tierable(2, 50) is True          # Rare
    assert tierable(0, 50) is False         # Normal
    assert tierable(3, 50) is False         # Unique
    assert tierable(MAP_RARITY, 50) is False
    assert tierable(UNKNOWN_RARITY, 50) is False
    assert tierable(2 + CORRUPTED_OFFSET, 50) is False


def test_an_item_without_a_level_gives_no_tier_evidence() -> None:
    """Ohne Item-Level gibt es keine Achse, an der sich etwas aufloesen
    liesse."""
    assert tierable(2, 0) is False


def test_observing_an_item_records_tier_evidence() -> None:
    sammlung = ModCollection()
    sammlung.observe_item(_item(frameType=RARE, ilvl=42, baseType="Gold Ring",
                                typeLine="Gold Ring",
                                explicitMods=["+27% to Cold Resistance"]))

    eintrag = sammlung.get("explicitMods", "+27% to Cold Resistance")
    # Ohne Liga am Item landet der Beleg im Altbestands-Topf "" —
    # die Liga ist seit Aufbau 6 die aeusserste Ebene (§VERSION).
    assert eintrag.tier_ledger == {"": {"Ring": {27.0: [1, 42, 42]}}}
    assert eintrag.tier_front("Ring") == [(27.0, 42)]


def test_a_unique_contributes_a_span_but_no_tier_evidence() -> None:
    """Die Sichtung zaehlt weiter — nur fuer die Tier-Frage taugt sie
    nicht."""
    sammlung = ModCollection()
    sammlung.observe_item(_item(frameType=UNIQUE, ilvl=80, baseType="Gold Ring",
                                typeLine="Gold Ring",
                                explicitMods=["+27% to Cold Resistance"]))

    eintrag = sammlung.get("explicitMods", "+27% to Cold Resistance")
    assert eintrag.count == 1
    assert eintrag.tier_ledger == {}


def test_multi_number_mods_give_no_tier_evidence() -> None:
    """"Adds # to #" haette zwei Achsen; die Front ist auf eine ausgelegt."""
    sammlung = ModCollection()
    sammlung.observe_item(_item(frameType=RARE, ilvl=42, baseType="Gold Ring",
                                typeLine="Gold Ring",
                                explicitMods=["Adds 2 to 6 Fire Damage"]))

    eintrag = sammlung.get("explicitMods", "Adds 2 to 6 Fire Damage")
    assert eintrag.count == 1
    assert eintrag.tier_ledger == {}


def test_backfilling_tiers_does_not_touch_any_count() -> None:
    """Der Kern des Nachtrags. Die Sammlung ist der einzige Ort, an dem
    ein verkauftes Item noch existiert — eine verdoppelte Zaehlung liesse
    sich nie wieder herausrechnen. Deshalb NICHT neu einlesen."""
    item = _item(frameType=RARE, ilvl=42, baseType="Gold Ring",
                 typeLine="Gold Ring", explicitMods=["+27% to Cold Resistance"])
    sammlung = ModCollection()
    sammlung.observe_item(item)
    eintrag = sammlung.get("explicitMods", "+27% to Cold Resistance")
    vorher_count = eintrag.count
    vorher_spanne = eintrag.span(RARE).count

    sammlung.backfill_tiers([item, item, item])

    assert eintrag.count == vorher_count
    assert eintrag.span(RARE).count == vorher_spanne


def test_backfilling_adds_the_evidence_a_v2_file_lacks() -> None:
    """Ein Stand ohne Belege bekommt sie nachtraeglich — sonst blieben
    Baender fuer immer leer, weil neu eingelesen nie wird."""
    item = _item(frameType=RARE, ilvl=42, baseType="Gold Ring",
                 typeLine="Gold Ring", explicitMods=["+27% to Cold Resistance"])
    sammlung = ModCollection()
    sammlung.observe_item(item)
    eintrag = sammlung.get("explicitMods", "+27% to Cold Resistance")
    eintrag.tier_ledger.clear()             # wie ein Stand nach Aufbau 2

    assert sammlung.has_tier_evidence() is False
    assert sammlung.backfill_tiers([item]) == 1
    assert sammlung.has_tier_evidence() is True


def test_backfilling_ignores_lines_the_collection_does_not_know() -> None:
    """Der Nachtrag darf keine neuen Eintraege anlegen — er ergaenzt nur."""
    sammlung = ModCollection()
    fremd = _item(frameType=RARE, ilvl=42, baseType="Gold Ring",
                  typeLine="Gold Ring", explicitMods=["+27% to Cold Resistance"])

    assert sammlung.backfill_tiers([fremd]) == 0
    assert len(sammlung) == 0


def test_tier_evidence_survives_a_round_trip(tmp_path) -> None:
    sammlung = ModCollection()
    sammlung.observe_item(_item(frameType=RARE, ilvl=42, baseType="Gold Ring",
                                typeLine="Gold Ring",
                                explicitMods=["+27% to Cold Resistance"]))
    ziel = tmp_path / "sammlung.json"
    sammlung.save(ziel)

    zurueck = mc.load(ziel)

    eintrag = zurueck.get("explicitMods", "+27% to Cold Resistance")
    assert eintrag.tier_ledger == {"": {"Ring": {27.0: [1, 42, 42]}}}


def test_a_v2_file_without_tiers_still_loads(tmp_path) -> None:
    """Eine Zeile ohne Tier-Feld ist keine kaputte Zeile."""
    eintrag = ModRecord.from_row(
        {"identity": "# to maximum Life", "kind": "explicitMods",
         "count": 7, "example": "+96 to maximum Life",
         "spans": {"": {"2": {"count": 7, "lows": [41], "highs": [96],
                              "ilvl_low": 10, "ilvl_high": 80}}}})

    assert eintrag.count == 7
    assert eintrag.tier_ledger == {}



# --------------------------- Erst gesehen am --------------------------- #

def test_a_new_record_carries_its_first_seen_date() -> None:
    """Nur der ERSTE Kontakt setzt das Datum — jede weitere Sichtung
    liesse es sonst wandern, und "zuletzt eingetragen" hiesse in
    Wahrheit "zuletzt gesehen"."""
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2)
    record = sammlung.get("explicitMods", "+41 to maximum Life")
    erster_kontakt = record.first_seen

    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=2)

    assert erster_kontakt > 0
    assert record.first_seen == erster_kontakt


def test_first_seen_survives_the_roundtrip() -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2)
    vorher = sammlung.get("explicitMods", "+41 to maximum Life").first_seen

    kopie = ModCollection.from_payload(sammlung.to_payload())

    assert kopie.get("explicitMods", "+41 to maximum Life").first_seen == vorher


def test_an_old_payload_yields_the_founding_stock() -> None:
    """Ein Stand nach Aufbau 3 kennt das Feld nicht — 0 heisst
    Grundstock, und ein nachtraeglich erfundenes Datum waere eine
    Behauptung (§VERSION)."""
    alte_zeile = {"identity": "+# to maximum Life", "kind": "explicitMods",
                  "count": 5, "example": "+41 to maximum Life"}

    eintrag = ModRecord.from_row(alte_zeile)

    assert eintrag.first_seen == 0.0


def test_the_founding_stock_writes_no_date_into_the_file() -> None:
    """6000+ Grundstock-Eintraege mit einer bedeutungslosen 0 wuerden die
    Datei nur verlaengern."""
    eintrag = ModRecord(identity="+# to maximum Life", kind="explicitMods")

    assert "first_seen" not in eintrag.to_row()


def test_new_keys_is_a_snapshot_of_this_sessions_finds() -> None:
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+41 to maximum Life", rarity=2)
    sammlung.clear_new()
    sammlung.observe("implicitMods", "+20% to Fire Resistance", rarity=2)

    schluessel = sammlung.new_keys()

    assert ("implicitMods", "#% to Fire Resistance") in schluessel
    assert ("explicitMods", "# to maximum Life") not in schluessel


# --------------------------- Das Kontenbuch ----------------------------- #
# Aufbau 5: je Kategorie und WERT die Sichtungen samt iLvl-Spanne —
# Peters Tabelle ("Count | Min | Max | iLvl-Min | iLvl-Max") braucht
# Zaehlungen je Band, und die kann eine blosse Front nicht liefern.

def test_the_ledger_accumulates_count_and_ilvl_span_per_value() -> None:
    sammlung = ModCollection()
    for ilvl in (42, 35, 60):
        sammlung.observe_item(_item(frameType=RARE, ilvl=ilvl,
                                    baseType="Gold Ring", typeLine="Gold Ring",
                                    explicitMods=["+27% to Cold Resistance"]))

    eintrag = sammlung.get("explicitMods", "+27% to Cold Resistance")
    assert eintrag.ledgers()["Ring"] == {27.0: [3, 35, 60]}


def test_the_front_takes_the_lowest_level_of_each_value() -> None:
    """Fuer die Baender zaehlt je Wert nur sein NIEDRIGSTES iLvl — die
    Ableitung verliert gegenueber dem frueheren direkten Mitschreiben
    der Front nichts."""
    eintrag = ModRecord(identity="#% to Cold Resistance", kind="explicitMods")
    eintrag.tier_ledger[""] = {"Ring": {12.0: [5, 14, 70], 18.0: [2, 26, 80]}}

    assert eintrag.tier_front("Ring") == [(12.0, 14), (18.0, 26)]


def test_a_dominated_value_disappears_from_the_front_but_not_the_ledger() -> None:
    """Das Kontenbuch vergisst nichts; nur die Front filtert."""
    eintrag = ModRecord(identity="#% to Cold Resistance", kind="explicitMods")
    eintrag.tier_ledger[""] = {"Ring": {12.0: [5, 30, 70], 18.0: [2, 26, 80]}}

    assert eintrag.tier_front("Ring") == [(18.0, 26)]
    assert len(eintrag.ledgers()["Ring"]) == 2


def test_an_old_tiers_block_is_dropped_on_load(tmp_path) -> None:
    """Aufbau 3/4 traegt nur die Front — ohne Zaehlungen waere sie im
    Kontenbuch eine Zeile mit erfundenem n. Verwerfen, der Nachtrag baut
    das Buch beim naechsten Start aus dem Cache neu auf."""
    eintrag = ModRecord.from_row(
        {"identity": "#% to Cold Resistance", "kind": "explicitMods",
         "count": 7, "example": "+27% to Cold Resistance",
         "spans": {"": {"2": {"count": 7, "lows": [6], "highs": [48],
                              "ilvl_low": 5, "ilvl_high": 80}}},
         "tiers": {"Ring": [[27, 42]]}})

    assert eintrag.count == 7                    # nichts verloren
    assert eintrag.tier_ledger == {}             # aber kein erfundenes n


# ----------------------- Die Liga-Ebene (Aufbau 6) ---------------------- #
# Peters Album-Screenshot mit Liga-Filter "SSF R Allflame" zeigte Slots
# und Haekchen ueber ALLE Ligen — das Kontenbuch kannte die Liga nicht.
# Seit Aufbau 6 steht sie als aeusserste Ebene davor (§VERSION).

def test_the_ledger_keeps_leagues_apart() -> None:
    sammlung = ModCollection()
    for liga, ilvl in (("Allflame", 42), ("", 60)):
        sammlung.observe_item(_item(frameType=RARE, ilvl=ilvl, league=liga,
                                    baseType="Gold Ring", typeLine="Gold Ring",
                                    explicitMods=["+27% to Cold Resistance"]))

    eintrag = sammlung.get("explicitMods", "+27% to Cold Resistance")
    assert eintrag.tier_ledger == {
        "Allflame": {"Ring": {27.0: [1, 42, 42]}},
        "": {"Ring": {27.0: [1, 60, 60]}},
    }
    assert eintrag.ledgers("Allflame") == {"Ring": {27.0: [1, 42, 42]}}


def test_ledgers_without_a_league_merge_all_pots() -> None:
    """``None`` heisst "alle Ligen": Sichtungen addiert, iLvl-Spannen
    vereinigt — exakt der Stand, den das Kontenbuch vor der
    Liga-Trennung fuehrte."""
    eintrag = ModRecord(identity="#% to Cold Resistance", kind="explicitMods")
    eintrag.tier_ledger["Allflame"] = {"Ring": {27.0: [2, 40, 55]}}
    eintrag.tier_ledger[""] = {"Ring": {27.0: [3, 35, 60], 33.0: [1, 70, 70]}}

    assert eintrag.ledgers() == {
        "Ring": {27.0: [5, 35, 60], 33.0: [1, 70, 70]}}


def test_ledgers_hands_out_copies_not_the_book_itself() -> None:
    """Wer die Antwort veraendert, veraendert nichts — sonst koennte ein
    Anzeige-Renderer das Kontenbuch still beschaedigen."""
    eintrag = ModRecord(identity="#% to Cold Resistance", kind="explicitMods")
    eintrag.tier_ledger["Allflame"] = {"Ring": {27.0: [2, 40, 55]}}

    eintrag.ledgers("Allflame")["Ring"][27.0][0] = 999

    assert eintrag.tier_ledger["Allflame"]["Ring"][27.0] == [2, 40, 55]


def test_the_front_can_follow_a_single_league() -> None:
    eintrag = ModRecord(identity="#% to Cold Resistance", kind="explicitMods")
    eintrag.tier_ledger["Allflame"] = {"Ring": {12.0: [1, 30, 30]}}
    eintrag.tier_ledger[""] = {"Ring": {18.0: [1, 26, 26]}}

    assert eintrag.tier_front("Ring", "Allflame") == [(12.0, 30)]
    assert eintrag.tier_front("Ring") == [(18.0, 26)]


def test_backfilling_sorts_the_evidence_into_league_pots() -> None:
    """Der Nachtrag kennt die Liga jedes Cache-Items — genau deshalb
    darf der Sprung auf Aufbau 6 den alten Block einfach verwerfen."""
    item = _item(frameType=RARE, ilvl=42, league="Allflame",
                 baseType="Gold Ring", typeLine="Gold Ring",
                 explicitMods=["+27% to Cold Resistance"])
    sammlung = ModCollection()
    sammlung.observe_item(item)
    eintrag = sammlung.get("explicitMods", "+27% to Cold Resistance")
    eintrag.tier_ledger.clear()

    assert sammlung.backfill_tiers([item]) == 1
    assert eintrag.tier_ledger == {"Allflame": {"Ring": {27.0: [1, 42, 42]}}}


def test_a_v5_ledger_without_the_league_level_is_dropped_on_load(tmp_path) -> None:
    """Aufbau 5 fuehrte die Kategorie direkt aussen. Ein erfundener
    Liga-Topf waere eine Behauptung — verwerfen, der Nachtrag baut das
    Buch liga-getrennt neu (wie beim tiers-Block aus Aufbau 3/4)."""
    eintrag = ModRecord.from_row(
        {"identity": "#% to Cold Resistance", "kind": "explicitMods",
         "count": 7, "example": "+27% to Cold Resistance",
         "spans": {"": {"2": {"count": 7, "lows": [6], "highs": [48],
                              "ilvl_low": 5, "ilvl_high": 80}}},
         "ledger": {"Ring": [[27, 3, 35, 60]]}})

    assert eintrag.count == 7                    # nichts verloren
    assert eintrag.tier_ledger == {}             # aber kein erfundener Topf


# ------------------ Aufbau 7: Sichtung = Item, nicht Abruf ------------- #
# Peter, 2026-08-28 spaet: "T2 71x gesehen? Kontrollier das doch bei
# Gelegenheit nach" — ein Paar Boots, 81 Charakter-Abrufe seit dem
# Neuaufbau. Jeder Abruf zaehlte alles erneut.

def _zeile(**felder) -> dict:
    return {"identity": "# to maximum Life", "kind": "explicitMods", "count": 7,
            "example": "+96 to maximum Life", "first_seen": 1_700_000_000.0,
            "spans": {"": {"2": {"count": 7, "lows": [41], "highs": [96],
                                 "ilvl_low": 10, "ilvl_high": 80}}},
            **felder}


def test_a_file_before_v7_keeps_only_hulls_and_asks_for_a_rebuild(tmp_path) -> None:
    """Die Zaehlstaende aus Aufbau <= 6 sind Abrufe, keine Items — sie
    werden nicht uebernommen. Was bleibt, ist ``first_seen``: Das laesst
    sich aus dem Cache nicht wiedergewinnen."""
    ziel = tmp_path / "alt.json"
    ziel.write_text(json.dumps({"version": 6, "mods": [_zeile()]}), encoding="utf-8")

    zurueck = mc.load(ziel)

    eintrag = zurueck.get("explicitMods", "+96 to maximum Life")
    assert zurueck.needs_rebuild is True
    assert eintrag.count == 0 and eintrag.spans == {} and eintrag.tier_ledger == {}
    assert eintrag.first_seen == 1_700_000_000.0


def test_a_v7_file_loads_as_it_is(tmp_path) -> None:
    ziel = tmp_path / "neu.json"
    ziel.write_text(json.dumps({"version": 7, "mods": [_zeile()]}), encoding="utf-8")

    zurueck = mc.load(ziel)

    assert zurueck.needs_rebuild is False
    assert zurueck.get("explicitMods", "+96 to maximum Life").count == 7


def test_an_empty_file_needs_no_rebuild() -> None:
    assert ModCollection.from_payload({"version": 3, "mods": []}).needs_rebuild is False


def test_a_hull_keeps_its_first_seen_when_it_is_counted_again(tmp_path) -> None:
    """Der Neuaufbau laeuft ueber ``observe`` — und der darf das alte Datum
    nicht durch "heute" ersetzen, sonst waeren 6000 Eintraege auf einmal
    die Neuzugaenge dieser Woche."""
    ziel = tmp_path / "alt.json"
    ziel.write_text(json.dumps({"version": 6, "mods": [_zeile()]}), encoding="utf-8")
    zurueck = mc.load(ziel)

    zurueck.observe("explicitMods", "+50 to maximum Life", rarity=2)

    eintrag = zurueck.get("explicitMods", "+50 to maximum Life")
    assert eintrag.count == 1
    assert eintrag.first_seen == 1_700_000_000.0
    assert ("explicitMods", "# to maximum Life") not in zurueck.new_keys()


def test_prune_unseen_drops_the_hulls_nothing_filled(tmp_path) -> None:
    ziel = tmp_path / "alt.json"
    ziel.write_text(json.dumps({"version": 6, "mods": [
        _zeile(), _zeile(identity="#% to Cold Resistance")]}), encoding="utf-8")
    zurueck = mc.load(ziel)
    zurueck.observe("explicitMods", "+50 to maximum Life", rarity=2)

    assert zurueck.prune_unseen() == 1
    assert zurueck.needs_rebuild is False
    assert len(zurueck) == 1
    assert zurueck.dirty is True


def test_retire_moves_the_old_file_aside(tmp_path) -> None:
    """Die alte Datei wird nicht ueberschrieben, sondern beiseitegelegt:
    ``save`` lehnt Schrumpfen ab, und der Neuaufbau kann kleiner sein
    (verkaufte Items). Ohne Datei daneben gibt es nichts, wogegen es
    schrumpfen koennte."""
    ziel = tmp_path / "mod-collection-x.json"
    ziel.write_text("{}", encoding="utf-8")

    weg = mc.retire(ziel)

    assert not ziel.exists()
    assert weg == tmp_path / f"mod-collection-x.pre-v{mc.VERSION}.json"
    assert weg.exists()
    assert mc.retire(ziel) is None


def test_fresh_items_skips_what_the_previous_fetch_already_had() -> None:
    alt = _item(id="a", frameType=RARE, explicitMods=["+27% to Cold Resistance"])
    gleich = _item(id="a", frameType=RARE, explicitMods=["+27% to Cold Resistance"])
    gecraftet = _item(id="a", frameType=RARE,
                      explicitMods=["+27% to Cold Resistance", "+50 to maximum Life"])
    neu = _item(id="b", frameType=RARE, explicitMods=["+27% to Cold Resistance"])

    frisch = mc.fresh_items([gleich, gecraftet, neu], [alt])

    assert frisch == [gecraftet, neu]


def test_a_refetch_does_not_count_twice() -> None:
    """Der Kern: dasselbe Item zweimal abgeholt ist EINE Sichtung."""
    item = _item(id="a", frameType=RARE, ilvl=42,
                 explicitMods=["+27% to Cold Resistance"])
    sammlung = ModCollection()
    sammlung.observe_items(mc.fresh_items([item], []))
    sammlung.observe_items(mc.fresh_items([item], [item]))

    assert sammlung.get("explicitMods", "+27% to Cold Resistance").count == 1


def test_the_league_level_survives_a_round_trip(tmp_path) -> None:
    sammlung = ModCollection()
    sammlung.observe_item(_item(frameType=RARE, ilvl=42, league="Allflame",
                                baseType="Gold Ring", typeLine="Gold Ring",
                                explicitMods=["+27% to Cold Resistance"]))
    ziel = tmp_path / "sammlung.json"
    sammlung.save(ziel)

    zurueck = mc.load(ziel)

    eintrag = zurueck.get("explicitMods", "+27% to Cold Resistance")
    assert eintrag.tier_ledger == {"Allflame": {"Ring": {27.0: [1, 42, 42]}}}


# ------------------------ Hauptwerte (Aufbau 8) ------------------------- #
# Peter, 2026-08-29: "den Ruestungswert und Schadenswert in Abhaengigkeit
# von der jeweiligen Ruestungs- oder Waffenart" — Rohwerte einzeln.

def _prop(name, *werte):
    return {"name": name, "values": [[w, 0] for w in werte]}


def test_base_stat_line_puts_the_category_first() -> None:
    from types import SimpleNamespace
    prop = SimpleNamespace(name="Armour", values=[["668", 0]])

    assert mc.base_stat_line("Body Armour", prop) == "Body Armour: Armour 668"
    assert mc.base_stat_line("", prop) is None


def test_damage_ranges_are_written_with_to_not_a_dash() -> None:
    """``mod_values("42-127")`` laese -127 als negative Zahl."""
    from types import SimpleNamespace
    prop = SimpleNamespace(name="Physical Damage", values=[["42-127", 0]])

    zeile = mc.base_stat_line("Bow", prop)

    assert zeile == "Bow: Physical Damage 42 to 127"
    assert mc.mod_values(zeile) == [42.0, 127.0]
    assert mc.mod_identity(zeile) == "Bow: Physical Damage # to #"


def test_elemental_damage_is_the_sum_over_the_elements() -> None:
    from types import SimpleNamespace
    prop = SimpleNamespace(name="Elemental Damage",
                           values=[["133-269", 4], ["10-20", 5], ["1-4", 6]])

    assert mc.base_stat_line("Bow", prop) == "Bow: Elemental Damage 144 to 293"


def test_only_base_stats_become_lines() -> None:
    from types import SimpleNamespace
    for name in ("Quality", "Memory Strands", "Weapon Range: {0} metres", "Bow"):
        prop = SimpleNamespace(name=name, values=[["+7%", 0]])
        assert mc.base_stat_line("Bow", prop) is None
    assert mc.base_stat_line("Wand", SimpleNamespace(name="Critical Strike Chance",
                                                     values=[["8.00%", 0]])) == (
        "Wand: Critical Strike Chance 8.00%")


def test_base_stat_lines_of_a_weapon_and_a_chest() -> None:
    bogen = _item(typeLine="Death Bow", frameType=RARE, ilvl=70,
                  properties=[_prop("Bow"), _prop("Physical Damage", "42-127"),
                              _prop("Critical Strike Chance", "6.50%"),
                              _prop("Attacks per Second", "1.40"),
                              _prop("Quality", "+10%")])
    brust = _item(typeLine="Plate Vest", frameType=RARE, ilvl=70,
                  properties=[_prop("Armour", "668"), _prop("Energy Shield", "87")])

    assert mc.base_stat_lines(bogen) == ["Bow: Physical Damage 42 to 127",
                                         "Bow: Critical Strike Chance 6.50%",
                                         "Bow: Attacks per Second 1.40"]
    assert mc.base_stat_lines(brust) == ["Body Armour: Armour 668",
                                         "Body Armour: Energy Shield 87"]


def test_observing_an_item_collects_its_base_stats() -> None:
    sammlung = ModCollection()
    sammlung.observe_item(_item(typeLine="Plate Vest", frameType=RARE, ilvl=70,
                                properties=[_prop("Armour", "668")]))

    eintrag = sammlung.get(mc.BASE_STAT_KIND, "Body Armour: Armour 500")
    assert eintrag is not None and eintrag.count == 1
    assert eintrag.span(RARE).spread == [(668.0, 668.0)]
    assert eintrag.tier_ledger == {}           # kein Tier-Konto fuer Hauptwerte
    assert sammlung.has_base_stats() is True


def test_backfilling_base_stats_adds_them_without_touching_mod_counts() -> None:
    item = _item(typeLine="Plate Vest", frameType=RARE, ilvl=70,
                 explicitMods=["+96 to maximum Life"],
                 properties=[_prop("Armour", "668")])
    sammlung = ModCollection()
    sammlung.observe("explicitMods", "+96 to maximum Life", rarity=RARE, ilvl=70)
    assert sammlung.has_base_stats() is False

    assert sammlung.backfill_base_stats([item]) == 1

    assert sammlung.has_base_stats() is True
    assert sammlung.get("explicitMods", "+96 to maximum Life").count == 1
    assert sammlung.get(mc.BASE_STAT_KIND, "Body Armour: Armour 1").count == 1


def test_base_stats_survive_the_round_trip() -> None:
    sammlung = ModCollection()
    sammlung.observe_item(_item(typeLine="Plate Vest", frameType=RARE, ilvl=70,
                                properties=[_prop("Armour", "668")]))

    kopie = ModCollection.from_payload(sammlung.to_payload())

    assert kopie.has_base_stats() is True
    assert kopie.get(mc.BASE_STAT_KIND, "Body Armour: Armour 1").count == 1
