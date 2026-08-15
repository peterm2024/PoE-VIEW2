"""Beobachtete Stapelgrößen (§4.45).

Peter, 2026-08-15: "So weiss ich auf einen Blick, wieviel ich von z.B.
'Wild Crystallised Lifeforce' besitze."
"""

from __future__ import annotations

from poe_view.api.models import Item
from poe_view.ui.favourites import (INCOMPLETE_MARK, MAX_VISIBLE_ROWS,
                                    ROW_HEIGHT, FavouriteRow, FavouritesTable,
                                    favourite_rows)


def _summe(items, name: str) -> int:
    return favourite_rows(items, [name])[0].total

SCHMAL = " "  # schmales Leerzeichen, wie beim XP-Gesamtwert daneben


def _stapel(name: str, groesse: int | None) -> Item:
    return Item(typeLine=name, stackSize=groesse)


# ---------------------------- Zaehlen ------------------------------------ #

def test_gleiche_namen_werden_addiert():
    items = [_stapel("Wild Crystallised Lifeforce", 1200),
             _stapel("Wild Crystallised Lifeforce", 3612),
             _stapel("Chaos Orb", 40)]
    assert _summe(items, "Wild Crystallised Lifeforce") == 4812


def test_ein_nicht_vorhandenes_item_ergibt_null():
    """Null ist eine Aussage — eine verschwindende Zeile waere keine."""
    assert _summe([_stapel("Chaos Orb", 40)], "Divine Orb") == 0


def test_ohne_stapelgroesse_zaehlt_das_item_als_eines():
    """Waffen, Ruestung und Karten tragen kein ``stackSize``. Wer sie
    beobachtet, will trotzdem wissen, wie viele herumliegen."""
    items = [_stapel("Headhunter", None), _stapel("Headhunter", None)]
    assert _summe(items, "Headhunter") == 2


def test_der_anzeigename_entscheidet_nicht_der_basistyp():
    """Ein Unique traegt seinen Namen in ``name``, die Waehrung in
    ``typeLine`` — beobachtet wird, was in der Tabelle steht."""
    unique = Item(name="Headhunter", typeLine="Leather Belt", frameType=3)
    assert _summe([unique], "Headhunter") == 1
    assert _summe([unique], "Leather Belt") == 0


def test_leere_liste_ergibt_null():
    assert _summe([], "Chaos Orb") == 0


# ---------------------------- favourite_rows ----------------------------- #

def test_die_reihenfolge_ist_die_des_nutzers_nicht_die_menge():
    """Eine Zeile, die je nach Bestand die Position wechselt, kann man
    nicht "auf einen Blick" ablesen."""
    items = [_stapel("Chaos Orb", 5), _stapel("Divine Orb", 900)]
    zeilen = favourite_rows(items, ["Chaos Orb", "Divine Orb"])
    assert [z.name for z in zeilen] == ["Chaos Orb", "Divine Orb"]


def test_jeder_beobachtete_name_bekommt_eine_zeile_auch_ohne_bestand():
    zeilen = favourite_rows([], ["Chaos Orb", "Divine Orb"])
    assert [(z.name, z.total) for z in zeilen] == [("Chaos Orb", 0),
                                                   ("Divine Orb", 0)]


def test_ohne_beobachtete_namen_gibt_es_keine_zeilen():
    assert favourite_rows([_stapel("Chaos Orb", 5)], []) == []


# ------------------------------ Zahlentext ------------------------------- #

def test_tausender_werden_wie_beim_xp_wert_getrennt():
    """Beide Zahlen stehen im selben Panel — mit verschiedenen
    Trennzeichen sieht es nach zwei Programmen aus."""
    assert FavouriteRow("x", 4812).total_text == f"4{SCHMAL}812"


def test_eine_unvollstaendige_summe_traegt_ein_zeichen():
    text = FavouriteRow("x", 4812, complete=False).total_text
    assert text.startswith(INCOMPLETE_MARK)
    assert f"4{SCHMAL}812" in text


def test_eine_vollstaendige_summe_traegt_keines():
    assert INCOMPLETE_MARK not in FavouriteRow("x", 4812).total_text


def test_null_wird_normal_dargestellt():
    assert FavouriteRow("x", 0).total_text == "0"


# ------------------------------- Widget ---------------------------------- #

def test_die_tabelle_zeigt_name_und_menge(qapp):
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Wild Crystallised Lifeforce", 4812)])

    assert tabelle.rowCount() == 1
    assert tabelle.item(0, 0).text() == "Wild Crystallised Lifeforce"
    assert tabelle.item(0, 1).text() == f"4{SCHMAL}812"


def test_der_volle_name_steht_im_tooltip(qapp):
    """Die Spalte ist schmal; "Wild Crystallised Lifeforce" steht dort
    selten ganz."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Wild Crystallised Lifeforce", 1)])
    assert tabelle.item(0, 0).toolTip() == "Wild Crystallised Lifeforce"


def test_das_zeichen_fuer_unvollstaendig_erklaert_sich_im_tooltip(qapp):
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 5, complete=False)])
    assert "loaded" in tabelle.item(0, 1).toolTip()


def test_ohne_zeilen_verschwindet_die_tabelle_ganz(qapp):
    """Ein leerer Rahmen ueber dem Graphen behauptete, es gaebe hier
    etwas zu sehen."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 5)])
    tabelle.set_rows([])

    assert tabelle.isVisible() is False
    assert tabelle.height() == 0


def test_die_hoehe_waechst_nur_bis_zur_obergrenze(qapp):
    """Darueber wird gescrollt, sonst frisst die Tabelle den Graphen."""
    tabelle = FavouritesTable()
    viele = [FavouriteRow(f"Item {i}", i) for i in range(MAX_VISIBLE_ROWS + 6)]
    tabelle.set_rows(viele)

    assert tabelle.rowCount() == len(viele)
    assert tabelle.height() <= MAX_VISIBLE_ROWS * ROW_HEIGHT + 2


def test_ein_neuer_stand_ersetzt_den_alten(qapp):
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Alt", 1), FavouriteRow("Auch alt", 2)])
    tabelle.set_rows([FavouriteRow("Neu", 3)])

    assert tabelle.rowCount() == 1
    assert tabelle.item(0, 0).text() == "Neu"


def test_die_tabelle_kennt_den_namen_einer_zeile(qapp):
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 5)])

    assert tabelle.name_at(0) == "Chaos Orb"
    assert tabelle.name_at(7) == ""


def test_die_mengenspalte_bleibt_bei_engem_fenster_lesbar(qapp):
    """Ohne Untergrenze drueckt der Splitter die Tabelle auf null — und
    die Zahl, der einzige Grund fuer die Tabelle, geht als Erstes."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Wild Crystallised Lifeforce", 999_999)])
    assert tabelle.minimumSizeHint().width() > 80


class _ZaehlendesItem:
    """Merkt sich, wie oft nach dem Anzeigenamen gefragt wurde."""

    def __init__(self, name: str, stack: int) -> None:
        self._name = name
        self.stackSize = stack
        self.zugriffe = 0

    @property
    def display_name(self) -> str:
        self.zugriffe += 1
        return self._name


def test_jedes_item_wird_genau_einmal_angesehen():
    """Zwoelf Namen einzeln zu zaehlen kostete an Peters echtem Bestand
    (58.621 Items) 81 ms statt 11 — und gezaehlt wird nach JEDEM
    eintreffenden Fach, bei "Load All Tabs" also tausendfach.

    Gezaehlt werden hier die Zugriffe und nicht die Zeit: Eine Messung
    waere auf einem langsameren Rechner oder unter Last unzuverlaessig,
    die Zahl der Durchlaeufe ist es nie. Bei einem Scan je Name stuende
    hier die Anzahl der Namen."""
    items = [_ZaehlendesItem("Chaos Orb", 5), _ZaehlendesItem("Divine Orb", 3)]

    favourite_rows(items, ["Chaos Orb", "Divine Orb", "Exalted Orb",
                           "Orb of Fusing"])

    assert [i.zugriffe for i in items] == [1, 1]


def test_ein_generator_genuegt_als_eingabe():
    """``_items_of_current_league`` reicht einen Generator herein, damit
    fuer die Zaehlung keine 59.000 Eintraege lange Liste entsteht."""
    items = [_stapel("Chaos Orb", 5), _stapel("Divine Orb", 3)]

    zeilen = favourite_rows(iter(items), ["Chaos Orb", "Divine Orb"])

    assert [(z.name, z.total) for z in zeilen] == [("Chaos Orb", 5),
                                                   ("Divine Orb", 3)]


def test_ein_favorit_laesst_sich_aus_der_tabelle_heraus_entlassen(qapp):
    """Sonst haette die Funktion eine Sackgasse: Ein beobachtetes Item,
    von dem gerade nichts mehr da ist, steht in keiner Item-Tabelle mehr
    und waere ueber den Rechtsklick dort nie wieder zu entfernen."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 0)])
    gemeldet: list[str] = []
    tabelle.remove_requested.connect(gemeldet.append)

    menu = tabelle.build_context_menu(0)
    assert menu is not None
    assert "Stop watching" in menu.actions()[0].text()
    menu.actions()[0].trigger()

    assert gemeldet == ["Chaos Orb"]


def test_rechtsklick_neben_die_zeilen_oeffnet_kein_menue(qapp):
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 5)])
    assert tabelle.build_context_menu(-1) is None
    assert tabelle.build_context_menu(9) is None
