"""Beobachtete Stapelgrößen (§4.45).

Peter, 2026-08-15: "So weiss ich auf einen Blick, wieviel ich von z.B.
'Wild Crystallised Lifeforce' besitze."
"""

from __future__ import annotations

from poe_view.api.models import Item
from poe_view.ui.favourites import (INCOMPLETE_MARK, ROW_HEIGHT,
                                    FavouriteRow, FavouritesTable,
                                    favourite_rows, reordered)


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
    """Ein leerer Rahmen neben dem Textblock behauptete, es gaebe hier
    etwas zu sehen."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 5)])
    tabelle.set_rows([])

    assert tabelle.isVisible() is False


def test_die_tabelle_verlangt_keine_hoehe_sondern_fuellt_sie(qapp):
    """Peter, 2026-08-16: "die volle uns verbliebene Hoehe". Der
    Vorgabewert einer QTableWidget waren gemessene 164 px — damit haette
    die Tabelle den Graphen darunter auf 60 px zusammengedrueckt. Sie
    soll die Hoehe des Textblocks daneben ausfuellen, nicht selbst
    welche einfordern; was nicht hineinpasst, wird gescrollt."""
    tabelle = FavouritesTable()
    eine = FavouritesTable()
    eine.set_rows([FavouriteRow("Chaos Orb", 5)])
    tabelle.set_rows([FavouriteRow(f"Item {i}", i) for i in range(20)])

    assert tabelle.rowCount() == 20
    assert tabelle.sizeHint().height() == ROW_HEIGHT + 2
    assert tabelle.sizeHint().height() == eine.sizeHint().height()


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


# --------------------- Umsortieren per Ziehen ---------------------------- #
#
# Peter, 2026-08-16: "Koennten wir die Fav-Item-Liste per Drag&Drop
# umsortieren?" Geprueft wird die Rechnung (``reordered``), das Umhaengen
# der Tabelle (``move_row``), die Ablagestelle unter dem Mauszeiger
# (``drop_index``) und dass die Tabelle ueberhaupt ziehbar EINGERICHTET
# ist — ohne das letzte laesst sich kein Eintrag anfassen, und keiner der
# anderen Tests wuerde es merken.

VIER = ["Chaos Orb", "Divine Orb", "Exalted Orb", "Vaal Orb"]


def test_ein_eintrag_wandert_nach_oben():
    assert reordered(VIER, 2, 0) == ["Exalted Orb", "Chaos Orb",
                                     "Divine Orb", "Vaal Orb"]


def test_ein_eintrag_wandert_nach_unten_und_landet_nicht_zu_tief():
    """Der Off-by-one-Fall: Nach dem Herausnehmen rutscht alles dahinter
    eine Stelle vor. Ohne die Korrektur laege "Chaos Orb" hier hinter
    "Exalted Orb" statt davor."""
    assert reordered(VIER, 0, 2) == ["Divine Orb", "Chaos Orb",
                                     "Exalted Orb", "Vaal Orb"]


def test_ans_ende_ziehen_geht():
    assert reordered(VIER, 0, 4) == ["Divine Orb", "Exalted Orb",
                                     "Vaal Orb", "Chaos Orb"]


def test_auf_die_eigene_stelle_ziehen_aendert_nichts():
    assert reordered(VIER, 1, 1) == VIER
    assert reordered(VIER, 1, 2) == VIER


def test_eine_unsinnige_zeile_laesst_die_liste_in_ruhe():
    """Kommt aus ``currentRow()`` eine -1 (nichts ausgewaehlt), darf das
    Ziehen die Liste nicht durcheinanderbringen."""
    assert reordered(VIER, -1, 2) == VIER
    assert reordered(VIER, 9, 2) == VIER


def test_die_tabelle_haengt_die_zeile_um_und_meldet_die_neue_reihenfolge(qapp):
    """Beides zusammen: Wuerde sie nur melden, bliebe die Zeile bis zur
    naechsten Zaehlung liegen und das Ziehen saehe aus, als haette es
    nicht funktioniert."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow(name, i) for i, name in enumerate(VIER)])
    gemeldet: list[list[str]] = []
    tabelle.order_changed.connect(gemeldet.append)

    assert tabelle.move_row(3, 0) is True

    assert [z.name for z in tabelle.rows()][0] == "Vaal Orb"
    assert gemeldet == [["Vaal Orb", "Chaos Orb", "Divine Orb", "Exalted Orb"]]


def test_die_mengen_ziehen_mit_um(qapp):
    """Umgehaengt werden ganze Zeilen. Blieben die Zahlen stehen, waere
    die Tabelle nach einem Zug schlicht falsch."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 5), FavouriteRow("Divine Orb", 3)])

    tabelle.move_row(1, 0)

    assert [(z.name, z.total) for z in tabelle.rows()] == [("Divine Orb", 3),
                                                           ("Chaos Orb", 5)]


def test_ein_zug_ohne_wirkung_meldet_nichts(qapp):
    """Sonst schriebe jedes versehentliche Anfassen die Einstellungen
    neu."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 5), FavouriteRow("Divine Orb", 3)])
    gemeldet: list[list[str]] = []
    tabelle.order_changed.connect(gemeldet.append)

    assert tabelle.move_row(0, 0) is False

    assert gemeldet == []


def test_unterhalb_der_letzten_zeile_bedeutet_ans_ende(qapp):
    """Sonst waere ausgerechnet die letzte Position nur zu erreichen,
    indem man die untere Haelfte der letzten Zeile trifft."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER])
    tabelle.resize(200, 400)

    assert tabelle.drop_index(390) == 4


def test_die_mitte_einer_zeile_entscheidet_ueber_davor_und_dahinter(qapp):
    """Ohne die Unterscheidung liesse sich kein Eintrag VOR die erste
    Zeile setzen."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER])
    tabelle.resize(200, 400)

    assert tabelle.drop_index(1) == 0
    assert tabelle.drop_index(ROW_HEIGHT - 1) == 1


def test_die_tabelle_ist_ueberhaupt_ziehbar_eingerichtet(qapp):
    """Der eigentliche Regressionstest. ``move_row`` liesse sich auch
    dann pruefen, wenn kein Mensch eine Zeile anfassen kann — genau so
    war die Tabelle vorher eingestellt (``NoSelection``, kein
    ``dragEnabled``), und Qts ``startDrag`` zieht nur, was ausgewaehlt
    ist."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView

    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow("Chaos Orb", 5)])

    assert tabelle.dragEnabled()
    assert tabelle.viewport().acceptDrops()
    assert tabelle.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove
    assert tabelle.selectionMode() != QAbstractItemView.SelectionMode.NoSelection
    assert not tabelle.dragDropOverwriteMode()
    flags = tabelle.item(0, 0).flags()
    assert flags & Qt.ItemFlag.ItemIsDragEnabled
    assert not flags & Qt.ItemFlag.ItemIsDropEnabled


class _Ablage:
    """Ein Ablage-Ereignis zum Anfassen.

    Ein echtes ``QDropEvent`` hilft hier nicht: Sein ``source()`` kommt
    aus Qts laufendem Drag-Vorgang und ist ausserhalb eines solchen
    ``None`` — der Test wuerde also immer im Ignorieren-Zweig landen.
    ``dropEvent`` ist eine Python-Methode und nimmt jedes Objekt, das
    sich wie das Ereignis verhaelt.
    """

    def __init__(self, quelle, y: float) -> None:
        self._quelle, self._y = quelle, y
        self.angenommen = False
        self.aktion = None

    def source(self):
        return self._quelle

    def position(self):
        from PySide6.QtCore import QPointF

        return QPointF(5.0, self._y)

    def setDropAction(self, aktion) -> None:  # noqa: N802 — Qt-Namensschema
        self.aktion = aktion

    def accept(self) -> None:
        self.angenommen = True

    def ignore(self) -> None:
        self.angenommen = False


def test_das_ablegen_sortiert_wirklich_um(qapp):
    """Die Verdrahtung selbst: Ereignis rein, neue Reihenfolge raus.
    ``move_row`` und ``drop_index`` einzeln zu pruefen genuegt nicht —
    sie muessen auch verbunden sein."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER])
    tabelle.resize(200, 400)
    gemeldet: list[list[str]] = []
    tabelle.order_changed.connect(gemeldet.append)
    tabelle.setCurrentCell(0, 0)
    tabelle.remember_drag_row()

    tabelle.dropEvent(_Ablage(tabelle, 390))   # unterhalb der letzten Zeile

    assert [z.name for z in tabelle.rows()][-1] == "Chaos Orb"
    assert gemeldet == [["Divine Orb", "Exalted Orb", "Vaal Orb", "Chaos Orb"]]


def test_eine_aenderung_waehrend_des_ziehens_verschiebt_den_richtigen(qapp):
    """Der Grund, warum beim Aufnehmen der NAME gemerkt wird und nicht
    die Zeilennummer: Qts Drag laeuft in einer eigenen
    Ereignisschleife, in der ``set_rows`` durchkommt. Nachgemessen
    ueberlebt die Zeilennummer das — sie zeigt danach aber auf einen
    ANDEREN Eintrag, wenn inzwischen ein Favorit weiter oben entlassen
    wurde. Hier wird "Exalted Orb" gezogen; ueber die alte Nummer 2
    landete stattdessen "Vaal Orb" oben."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER])
    tabelle.resize(200, 400)
    tabelle.setCurrentCell(2, 0)                 # "Exalted Orb"
    tabelle.remember_drag_row()

    # Waehrend der Zug laeuft, wird "Chaos Orb" entlassen — alles
    # darunter rutscht eine Zeile hoch.
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER[1:]])
    assert tabelle.currentRow() == 2, "Voraussetzung des Tests entfallen"

    tabelle.dropEvent(_Ablage(tabelle, 1))       # ganz nach oben

    assert [z.name for z in tabelle.rows()] == ["Exalted Orb", "Divine Orb",
                                                "Vaal Orb"]


def test_ein_waehrend_des_zugs_entlassener_favorit_wird_nicht_verschoben(qapp):
    """Wer den gezogenen Eintrag nicht mehr findet, laesst die Liste in
    Ruhe — irgendetwas anderes an seine Stelle zu schieben waere
    schlimmer als ein wirkungsloser Zug."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER])
    tabelle.resize(200, 400)
    tabelle.setCurrentCell(0, 0)                 # "Chaos Orb"
    tabelle.remember_drag_row()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER[1:]])
    gemeldet: list[list[str]] = []
    tabelle.order_changed.connect(gemeldet.append)

    tabelle.dropEvent(_Ablage(tabelle, 390))

    assert [z.name for z in tabelle.rows()] == VIER[1:]
    assert gemeldet == []


def test_etwas_von_aussen_wird_nicht_angenommen(qapp):
    """Ein Item aus der Haupttabelle hierher zu ziehen saehe aus, als
    wuerde es aufgenommen. Dafuer gibt es den Rechtsklick — ein
    stillschweigend verworfener Ablauf waere schlimmer als gar keiner."""
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER])
    gemeldet: list[list[str]] = []
    tabelle.order_changed.connect(gemeldet.append)

    ereignis = _Ablage(None, 10)
    tabelle.dropEvent(ereignis)

    assert ereignis.angenommen is False
    assert [z.name for z in tabelle.rows()] == VIER
    assert gemeldet == []


def test_eine_echte_mausbewegung_startet_den_zug(qapp):
    """Der Test, der heute frueh gefehlt haette: gebaut, geprueft,
    gemeldet — und auf Peters Schirm nicht benutzbar. Alle anderen Tests
    hier rufen ``move_row``/``dropEvent`` selbst auf und wuerden auch
    dann gruen bleiben, wenn kein Mensch eine Zeile anfassen kann.

    ``startDrag`` wird ueberschrieben, damit kein modaler Drag-Lauf
    startet und den Testlauf anhaelt; geprueft wird nur, OB Qt es auf
    eine Mausbewegung hin aufruft — und mit welcher Zeile."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    gerufen: list[str] = []

    class Mitschrift(FavouritesTable):
        def startDrag(self, actions):  # noqa: N802 — Qt-Namensschema
            self.remember_drag_row()
            gerufen.append(self._drag_name)

    tabelle = Mitschrift()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER])
    tabelle.resize(200, 200)
    tabelle.show()
    QTest.qWaitForWindowExposed(tabelle)

    start = QPoint(40, ROW_HEIGHT + ROW_HEIGHT // 2)      # zweite Zeile
    QTest.mousePress(tabelle.viewport(), Qt.MouseButton.LeftButton, pos=start)
    assert tabelle.currentRow() == 1, "das Druecken waehlt die Zeile nicht aus"
    for schritt in (5, 15, 40, 80):
        QTest.mouseMove(tabelle.viewport(), start + QPoint(0, schritt))
        qapp.processEvents()
    QTest.mouseRelease(tabelle.viewport(), Qt.MouseButton.LeftButton,
                       pos=start + QPoint(0, 80))

    assert gerufen == ["Divine Orb"]
    tabelle.close()


# ------------------- Einfuegestrich und Move-Action ---------------------- #
#
# Peter, 2026-08-16, nach dem ersten Anlauf: "fuehlt sich nicht richtig
# an, da stimmt was nicht." Nachgemessen waren es zwei Dinge: Beim Ziehen
# war UEBERHAUPT KEINE Rueckmeldung zu sehen, wohin der Eintrag faellt,
# und der Drop meldete MoveAction, worauf Qts startDrag hinterher
# clearOrRemove() aufruft und eine Zeile loescht.

def _strich_zeilen(tabelle) -> list[int]:
    """Auf welchen Bildzeilen liegt der Einfuegestrich?

    Ermittelt als UNTERSCHIED zweier Aufnahmen desselben Widgets, mit und
    ohne Strich. Ihn an seiner Farbe zu erkennen ging daneben: Er traegt
    die Auswahlfarbe, und die ausgewaehlte Zeile traegt sie auch — im
    Offscreen-Betrieb (helle Palette) sind beide identisch, und der Test
    hielt eine markierte Zeile fuer einen 19 px hohen Strich.

    Beide Bilder vom ECHTEN Widget (``grab()``), nie nachgebaut."""
    gemerkt = tabelle._drop_line
    tabelle.show_drop_line(-1)
    ohne = tabelle.grab().toImage()
    tabelle.show_drop_line(gemerkt)
    mit = tabelle.grab().toImage()
    x = mit.width() // 2
    return [y for y in range(mit.height())
            if mit.pixel(x, y) != ohne.pixel(x, y)]


def _tabelle_mit_vier(qapp):
    tabelle = FavouritesTable()
    tabelle.set_rows([FavouriteRow(name, 0) for name in VIER])
    tabelle.resize(200, 160)
    tabelle.show()
    return tabelle


def test_ohne_zug_gibt_es_keinen_strich(qapp):
    assert _strich_zeilen(_tabelle_mit_vier(qapp)) == []


def test_waehrend_des_zugs_zeigt_ein_strich_die_stelle(qapp):
    """Das eigentliche "fuehlt sich nicht richtig an": Man zog und sah
    nicht, wo der Eintrag landen wuerde. Qts eigener Indikator hilft
    nicht — er meldet ueber die volle Zeilenhoehe ``OnItem`` und zeichnet
    einen Rahmen um eine Zeile statt einer Linie dazwischen."""
    tabelle = _tabelle_mit_vier(qapp)

    tabelle.dragMoveEvent(_Ablage(tabelle, 50))
    qapp.processEvents()

    assert _strich_zeilen(tabelle) != []


def test_der_strich_liegt_da_wo_auch_eingefuegt_wird(qapp):
    """Sonst waere er schlimmer als keiner: Er verspraeche eine Stelle
    und der Eintrag landete woanders."""
    tabelle = _tabelle_mit_vier(qapp)

    for maus_y in (2, 30, 70, 150):
        tabelle.dragMoveEvent(_Ablage(tabelle, maus_y))
        qapp.processEvents()
        ziel = tabelle.drop_index(maus_y)
        kante = (tabelle.rowViewportPosition(ziel) if ziel < tabelle.rowCount()
                 else tabelle.rowViewportPosition(tabelle.rowCount() - 1)
                 + tabelle.rowHeight(tabelle.rowCount() - 1))
        gezeichnet = _strich_zeilen(tabelle)

        assert gezeichnet, f"kein Strich bei y={maus_y}"
        # Der Rahmen des Widgets verschiebt das ganze Bild um denselben
        # Betrag gegen die Viewport-Koordinaten; verglichen wird deshalb
        # der Abstand, nicht die absolute Zahl.
        versatz = gezeichnet[0] - kante
        assert 0 <= versatz <= 4, (
            f"Strich bei y={maus_y} liegt {versatz} px neben der "
            f"Einfuegestelle vor Zeile {ziel}")


def test_am_ende_der_liste_bleibt_der_strich_sichtbar(qapp):
    """Unterhalb der letzten Zeile ist die haeufigste Stelle ueberhaupt
    (dorthin zieht man, wer ans Ende soll). Ohne Anschlag laege der
    Strich ausserhalb des sichtbaren Bereichs."""
    tabelle = _tabelle_mit_vier(qapp)

    tabelle.dragMoveEvent(_Ablage(tabelle, 150))
    qapp.processEvents()

    assert _strich_zeilen(tabelle) != []


def test_der_strich_verschwindet_beim_verlassen(qapp):
    from PySide6.QtGui import QDragLeaveEvent

    tabelle = _tabelle_mit_vier(qapp)
    tabelle.dragMoveEvent(_Ablage(tabelle, 50))
    qapp.processEvents()

    tabelle.dragLeaveEvent(QDragLeaveEvent())
    qapp.processEvents()

    assert _strich_zeilen(tabelle) == []


def test_der_strich_verschwindet_nach_dem_ablegen(qapp):
    """Der Strich steht bewusst GANZ OBEN, die verschobene Zeile landet
    unten: Der Strich traegt die Auswahlfarbe, und die verschobene Zeile
    ist nach dem Zug ausgewaehlt — laegen beide uebereinander, waere der
    Strich im Bild nicht von der Markierung zu unterscheiden und der
    Test bewiese nichts. (Genau so war es zuerst; aufgefallen ist es nur
    an der Gegenprobe, die den Test nicht zum Fallen brachte.)"""
    tabelle = _tabelle_mit_vier(qapp)
    tabelle.dragMoveEvent(_Ablage(tabelle, 2))       # Strich vor Zeile 0
    qapp.processEvents()
    assert _strich_zeilen(tabelle), "Voraussetzung des Tests entfallen"
    tabelle.setCurrentCell(0, 0)
    tabelle.remember_drag_row()

    tabelle.dropEvent(_Ablage(tabelle, 150))         # ans Ende, waehlt Zeile 3
    qapp.processEvents()

    assert _strich_zeilen(tabelle) == []


def test_der_drop_meldet_keine_move_action(qapp):
    """Qts ``startDrag`` ruft nach einem Drop mit ``MoveAction``
    ``clearOrRemove()`` auf und loescht die noch ausgewaehlten Zeilen aus
    dem Modell. Hier haben wir die Zeilen selbst schon umgehaengt — die
    Auswahl steht danach auf einer FREMDEN Zeile, und die verschwaende.

    Nachgemessen: Nach ``move_row`` umfasst die Auswahl weiterhin eine
    volle Zeile ueber beide Spalten, also genau die Bedingung, unter der
    ``clearOrRemove`` loescht."""
    from PySide6.QtCore import Qt

    tabelle = _tabelle_mit_vier(qapp)
    tabelle.setCurrentCell(0, 0)
    tabelle.remember_drag_row()
    ereignis = _Ablage(tabelle, 150)

    tabelle.dropEvent(ereignis)

    assert ereignis.aktion != Qt.DropAction.MoveAction
    assert ereignis.angenommen is True          # angenommen ist es trotzdem


def test_die_verschobene_zeile_bleibt_markiert(qapp):
    """Die Auswahl haengt an der Zeilennummer, und die zeigt nach dem
    Umhaengen auf einen anderen Eintrag. Ohne Nachfuehren zieht man einen
    Eintrag nach unten und oben leuchtet ein fremder Name auf."""
    tabelle = _tabelle_mit_vier(qapp)
    tabelle.selectRow(0)

    tabelle.move_row(0, 4)

    markiert = sorted({i.row()
                       for i in tabelle.selectionModel().selectedIndexes()})
    assert markiert == [3]
    assert tabelle.name_at(3) == "Chaos Orb"
