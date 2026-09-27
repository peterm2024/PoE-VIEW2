"""Die Zonen-Tabelle: jedes je betretene Gebiet mit seinem Monsterlevel.

Peter, 2026-09-26: "Außerdem hätte ich gerne dann einen Menüpunkt
'Zones', wo eine Tabelle öffnet, unterteilt nach Story, Map und
Special-Maps, wo alle Zonen aufgeführt werden und deren Monster-Level.
[...] Die Zonen sollte man auch als csv exportieren können."

Die Daten kommen aus ``services/zone_catalog`` (dort steht, warum aus
der Client.txt und nicht aus einer mitgelieferten Liste). Diese Datei
ist nur die Anzeige.

**Warum ein Baum und keine flache Liste** (Peter, 2026-09-27): Eine Zone
hat keine Kartenstufe, ein BESUCH hat eine — seine Karten sind
nummerierte Items ("Map (Tier 4)") mit dem Text *"Travel to a Map of
this tier or lower"*, der Gebietslevel kommt also vom Item. Bazaar
erschien mit Tier 4 auf Level 71 und mit Tier 5 auf Level 72; Tode und
Verweildauer darüber zu mitteln löscht genau das, was interessiert.

Peters erster Vorschlag war eine Checkbox "zusammen" mit zwei Modi.
Der Baum ist dieselbe Idee ohne Schalter: Die Zeile zeigt zugeklappt die
Zusammenfassung, aufgeklappt eine Kindzeile je Stufe. Und er löst nebenbei
ein Problem, an dem die Checkbox gescheitert wäre — das Azurite Mine hat
37 Stufen (Delve-Tiefe) und die Fathomless Depths ebenso viele. Global
aufgeklappt läge die eine interessante Karten-Zeile unter 70 Zeilen
Rauschen; zugeklappt stört sie niemanden. Kinder gibt es deshalb nur,
wo es mehr als eine Stufe gibt.

**Warum eine Gruppen-Box und keine vier Abschnitte untereinander:** Eine
sortierbare Tabelle verträgt keine Zwischenüberschriften — der erste
Klick auf einen Spaltenkopf würde sie zerreißen. Die Gruppe steht
deshalb als eigene Spalte (mitsortierbar) und zusätzlich als Filter über
der Tabelle. Voreinstellung ist "All", damit die Tabelle beim Öffnen
zeigt, was sie hat.
"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import (QAbstractItemModel, QModelIndex,
                            QSortFilterProxyModel, Qt)
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTreeView, QVBoxLayout, QWidget)

from poe_view.services.csv_export import sanitize_filename
from poe_view.services.experience import experience_multiplier
from poe_view.services.league_log import UNKNOWN
from poe_view.services.zone_catalog import (CATEGORIES, NO_LEVEL,
                                            TIER_CATEGORIES, ZoneRecord,
                                            map_tier_from_level)


def _dauer_text(sekunden: float) -> str:
    """"7:12" oder "42 s" — Minuten:Sekunden, solange es Minuten gibt.
    Leer bei 0: Eine Zone, die nur einmal betreten und nie verlassen
    wurde, hat keine gemessene Dauer, und "0:00" wäre eine Behauptung."""
    if sekunden <= 0:
        return ""
    if sekunden < 60:
        return f"{round(sekunden)} s"
    return f"{int(sekunden // 60)}:{round(sekunden % 60):02d}"


def _league_choices(records: list[ZoneRecord]) -> list[str]:
    """Die Ligen, die im Katalog wirklich vorkommen — zuletzt gespielte
    zuerst, ``UNKNOWN`` ganz unten.

    Nicht die Liga-Liste aus der API: Eine Liga, in der dieses Konto nie
    gespielt hat, wäre ein Eintrag, der immer auf eine leere Tabelle
    führt. Sortiert wird nach dem jüngsten Besuch, weil die Namen selbst
    keine Ordnung tragen ("Allflame" vor "SSF R Allflame"?)."""
    zuletzt: dict[str, str] = {}
    for record in records:
        for name, werte in record.leagues.items():
            zuletzt[name] = max(zuletzt.get(name, ""), werte.last_seen)
    ohne_unbekannt = sorted((n for n in zuletzt if n != UNKNOWN),
                            key=lambda n: zuletzt[n], reverse=True)
    return ohne_unbekannt + ([UNKNOWN] if UNKNOWN in zuletzt else [])

# Spalten. "Monster Level" trägt bewusst den Namen, unter dem Peter
# gefragt hat, obwohl in der Client.txt "area level" steht: Für
# gewöhnliche Monster ist es dasselbe, und "Gebietslevel" beantwortet die
# Frage nicht, die jemand hat, der auf die Spalte schaut.
COLUMNS = ("Group", "Zone", "Tier", "Monster Level", "Visits", "Deaths",
           "Avg. time", "Last seen", "Area id")
(_GROUP_COL, _NAME_COL, _TIER_COL, _LEVEL_COL, _VISITS_COL, _DEATHS_COL,
 _TIME_COL, _SEEN_COL, _ID_COL) = range(9)

# Sortierrolle wie in der Item-Tabelle: "70–77" ist als Text sinnlos
# sortierbar, als Zahl (höchster gesehener Level) nicht.
NUMERIC_SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class ZoneTreeModel(QAbstractItemModel):
    """Oberste Ebene: ein Gebiet. Darunter: eine Zeile je Gebietslevel,
    aber nur, wenn es mehr als einen gibt (§Modul-Kopf).

    Die Eltern-Kind-Beziehung steckt in der ``internalId``: 0 heißt
    "oberste Ebene", jede andere Zahl ist die um eins erhöhte Zeile des
    Eltern-Gebiets. Kein eigener Knoten-Typ, weil der Baum genau zwei
    Ebenen tief ist und die Kinder nichts halten, was nicht schon im
    ``ZoneRecord`` steht — ein Knotenbaum daneben wäre ein zweiter
    Datenbestand, der mit dem ersten aus dem Tritt geraten kann."""

    def __init__(self, records: list[ZoneRecord], character_level: int = 0,
                 league: str | None = None) -> None:
        super().__init__()
        self._records = records
        self._character_level = character_level
        # ``None`` heißt "alle Ligen zusammen". Sonst zeigt die Tabelle
        # NUR die Zahlen dieser Liga — der Atlas baut sich mit jeder
        # Season um, und die Ligen einer Season unterscheiden sich im
        # Inhalt (Vaal-Side-Areas gibt es in Ruthless nicht).
        self._league = league

    def set_league(self, league: str | None) -> None:
        if league == self._league:
            return
        self.beginResetModel()
        self._league = league
        self.endResetModel()

    def league(self) -> str | None:
        return self._league

    def set_character_level(self, level: int) -> None:
        """Färbt die Level-Spalte danach ein, was dort noch zu holen ist
        — ohne Charakter bleibt sie ungefärbt."""
        if level == self._character_level:
            return
        self._character_level = level
        if self._records:
            self.dataChanged.emit(self.index(0, _LEVEL_COL, QModelIndex()),
                                  self.index(len(self._records) - 1, _LEVEL_COL,
                                             QModelIndex()))

    # --- Baumgerüst ---------------------------------------------------- #

    def levels_of(self, row: int) -> list[int]:
        """Die Stufen, die unter diesem Gebiet als Kinder erscheinen —
        leer bei nur einer, denn eine einzelne Kindzeile wiederholte
        bloß ihre Elternzeile."""
        record = self.record_at(row)
        if record is None:
            return []
        stufen = sorted(record.stats(self._league).by_level)
        return stufen if len(stufen) > 1 else []

    def index(self, row: int, column: int,
              parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, 0)
        return self.createIndex(row, column, parent.row() + 1)

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: A003 (Qt-API)
        if not index.isValid() or index.internalId() == 0:
            return QModelIndex()
        return self.createIndex(int(index.internalId()) - 1, 0, 0)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._records)
        if parent.internalId() != 0:          # Kinder haben keine Kinder
            return 0
        return len(self.levels_of(parent.row()))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole \
                and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def record_at(self, row: int) -> ZoneRecord | None:
        """Das Gebiet der obersten Ebene in dieser Zeile."""
        return self._records[row] if 0 <= row < len(self._records) else None

    def record_for(self, index: QModelIndex) -> ZoneRecord | None:
        """Das Gebiet zu einem beliebigen Index — bei einem Kind das des
        Eltern-Gebiets."""
        if not index.isValid():
            return None
        if index.internalId() == 0:
            return self.record_at(index.row())
        return self.record_at(int(index.internalId()) - 1)

    def level_for(self, index: QModelIndex) -> int | None:
        """Der Gebietslevel, für den diese Kindzeile steht — ``None`` für
        eine Zeile der obersten Ebene."""
        if not index.isValid() or index.internalId() == 0:
            return None
        stufen = self.levels_of(int(index.internalId()) - 1)
        return stufen[index.row()] if 0 <= index.row() < len(stufen) else None

    def data(self, index: QModelIndex, role):
        record = self.record_for(index)
        if record is None:
            return None
        level = self.level_for(index)
        return (self._child_data(record, level, index.column(), role)
                if level is not None
                else self._zone_data(record, index.column(), role))

    def _zone_data(self, record: ZoneRecord, col: int, role):
        """Die zusammengefasste Zeile eines Gebiets."""
        zahlen = record.stats(self._league)
        tier = record.tier_text(self._league)
        if role == Qt.ItemDataRole.DisplayRole:
            return (record.category, record.name or "–", tier,
                    record.level_text(self._league),
                    str(zahlen.visits),
                    str(zahlen.deaths) if zahlen.deaths else "",
                    _dauer_text(zahlen.average_seconds),
                    zahlen.last_seen.replace("T", " "),
                    record.area_id)[col]
        if role == NUMERIC_SORT_ROLE:
            # Leere Zellen ganz nach unten statt vorne: Eine Karte ohne
            # Tier ist keine Karte mit Tier 0.
            if col == _TIER_COL:
                return record.tier(self._league) or -1
            if col == _LEVEL_COL:
                return record.max_level(self._league)
            if col == _VISITS_COL:
                return zahlen.visits
            if col == _DEATHS_COL:
                return zahlen.deaths
            if col == _TIME_COL:
                return zahlen.average_seconds
            return (self._zone_data(record, col, Qt.ItemDataRole.DisplayRole)
                    or "").lower()
        if role == Qt.ItemDataRole.ToolTipRole and col == _LEVEL_COL:
            return self._level_tooltip(record)
        if role == Qt.ItemDataRole.ToolTipRole and col == _TIME_COL:
            return (f"{zahlen.visits} visits, "
                    f"{_dauer_text(zahlen.seconds) or '0 s'} in total"
                    if zahlen.seconds else None)
        return None

    def _child_data(self, record: ZoneRecord, level: int, col: int, role):
        """Eine Kindzeile: dieselben Spalten, aber nur die Zahlen DIESER
        Stufe. Gruppe, Name und Kennung bleiben leer — sie stünden
        wortgleich in der Elternzeile darüber, und die Einrückung sagt
        bereits, wozu die Zeile gehört."""
        zahlen = record.stats(self._league).by_level.get(level)
        if zahlen is None:
            return None
        tier = (map_tier_from_level(level)
                if record.category in TIER_CATEGORIES else None)
        if role == Qt.ItemDataRole.DisplayRole:
            return ("", "", str(tier) if tier else "",
                    str(level) if level != NO_LEVEL else "–",
                    str(zahlen.visits),
                    str(zahlen.deaths) if zahlen.deaths else "",
                    _dauer_text(zahlen.average_seconds),
                    zahlen.last_seen.replace("T", " "), "")[col]
        if role == NUMERIC_SORT_ROLE:
            if col == _TIER_COL:
                return tier if tier else -1
            if col == _LEVEL_COL:
                return level
            if col == _VISITS_COL:
                return zahlen.visits
            if col == _DEATHS_COL:
                return zahlen.deaths
            if col == _TIME_COL:
                return zahlen.average_seconds
            return level
        if role == Qt.ItemDataRole.ToolTipRole and col == _TIME_COL:
            return (f"{zahlen.visits} visits, "
                    f"{_dauer_text(zahlen.seconds) or '0 s'} in total"
                    if zahlen.seconds else None)
        if role == Qt.ItemDataRole.ToolTipRole and col == _LEVEL_COL \
                and self._character_level and level != NO_LEVEL:
            anteil = experience_multiplier(self._character_level, level)
            return (f"At character level {self._character_level}, level "
                    f"{level} yields {anteil:.1%} experience")
        return None

    def _level_tooltip(self, record: ZoneRecord) -> str | None:
        """Alle gesehenen Level einzeln, plus was der Charakter dort noch
        bekäme. Die Zelle zeigt nur die Spanne — bei ``Delve_Main`` mit 34
        Werten ist das die einzig lesbare Form, die Einzelwerte sind aber
        genau das, was man bei einer Spanne wissen will.

        Über alle Ligen hinweg steht zusätzlich, welcher Level aus
        welcher Liga stammt: Eine Spanne "68–76" ist dort meist gar
        keine Spanne, sondern ein Atlas-Umbau zwischen zwei Seasons."""
        levels = record.stats(self._league).levels
        if not levels:
            return None
        zeilen = ["Levels seen: " + ", ".join(str(x) for x in sorted(levels))]
        if self._league is None and len(record.leagues) > 1:
            zeilen += [f"  {name}: "
                       + ", ".join(str(x) for x in sorted(werte.levels))
                       for name, werte in sorted(record.leagues.items())
                       if werte.levels]
        if self._character_level:
            hoechster = record.max_level(self._league)
            anteil = experience_multiplier(self._character_level, hoechster)
            zeilen.append(f"At character level {self._character_level}, level "
                          f"{hoechster} yields {anteil:.1%} experience")
        return "\n".join(zeilen)


class ZoneFilterProxy(QSortFilterProxyModel):
    """Freitext über alle Spalten plus Gruppen-Vorwahl."""

    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(NUMERIC_SORT_ROLE)
        self._group = ""
        # Den Suchtext selbst halten statt ihn aus
        # ``filterRegularExpression().pattern()`` zurückzulesen: Qt
        # maskiert dort jedes Sonderzeichen, aus "blood aqueduct" wird
        # "blood\ aqueduct" — und die Aufteilung in Wörter fände damit
        # nichts mehr. Dieselbe Lösung wie in ``ItemFilterProxy``.
        self._words: list[str] = []

    def setFilterFixedString(self, text: str) -> None:  # noqa: N802 (Qt-API)
        self._words = text.lower().split()
        super().setFilterFixedString(text)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        """Nach Gruppe sortieren heißt: Story, Map, Special, Rest — in
        DIESER Reihenfolge und innerhalb jeder Gruppe nach Level.

        Peter hat die Tabelle "unterteilt nach Story, Map und
        Special-Maps" bestellt. Eine sortierbare Tabelle verträgt keine
        Zwischenüberschriften (der erste Klick auf einen Spaltenkopf
        würde sie zerreißen), aber genau so sieht sie beim Öffnen aus.
        Alphabetisch sortiert stünde stattdessen "Map, Rest, Special,
        Story" da — richtig sortiert und trotzdem verkehrt herum."""
        model = self.sourceModel()
        if left.parent().isValid():
            # Kindzeilen sind Stufen. In der Gruppen-Spalte stehen sie
            # alle leer — ohne diesen Zweig wäre ihre Reihenfolge dem
            # Zufall überlassen, und ausgerechnet die Stufe ist das
            # einzige, wonach man sie ordnen will.
            if left.column() != _GROUP_COL:
                return super().lessThan(left, right)
            return (model.level_for(left) or 0) < (model.level_for(right) or 0)
        if left.column() != _GROUP_COL:
            return super().lessThan(left, right)
        eins, zwei = model.record_at(left.row()), model.record_at(right.row())
        if eins is None or zwei is None:
            return super().lessThan(left, right)
        liga = model.league()
        return self._group_key(eins, liga) < self._group_key(zwei, liga)

    @staticmethod
    def _group_key(record: ZoneRecord, league: str | None) -> tuple[int, int, str]:
        reihenfolge = (CATEGORIES.index(record.category)
                       if record.category in CATEGORIES else len(CATEGORIES))
        return (reihenfolge, record.max_level(league), record.name.lower())

    def set_group(self, group: str) -> None:
        # begin/endFilterChange statt invalidateFilter — Letzteres ist
        # seit Qt 6.10 deprecated und warnt in jedem Testlauf (dieselbe
        # Stelle wie in ``ItemFilterProxy.set_column_filter``).
        self.beginFilterChange()
        self._group = group
        self.endFilterChange()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        # Kindzeilen folgen ihrem Gebiet: Ist das Gebiet gefiltert, sind
        # seine Stufen ohnehin nicht zu sehen; ist es sichtbar, gehören
        # alle seine Stufen dazu. Eine Stufe für sich zu filtern hieße,
        # eine Zone zu zeigen, deren Zahlen nicht mehr zu ihren Kindern
        # passen.
        if parent.isValid():
            return True
        model = self.sourceModel()
        record = model.record_at(row)
        if record is None:
            return False
        # Eine Zone, die in dieser Liga nie betreten wurde, gehört nicht
        # in die Tabelle — sonst stünde eine leere Level-Spalte da und
        # sähe aus wie ein Fehler. Genau das ist Peters Fall: In SSF
        # Ruthless gibt es keine Vaal-Side-Areas.
        if not record.seen_in(model.league()):
            return False
        if self._group and record.category != self._group:
            return False
        if not self._words:
            return True
        heuhaufen = f"{record.name} {record.area_id} {record.category} " \
                    f"{record.level_text(model.league())}".lower()
        return all(wort in heuhaufen for wort in self._words)


def export_zones(path: str, records: list[ZoneRecord],
                 league: str | None = None) -> None:
    """Die Zonen als CSV — Semikolon und UTF-8-BOM wie beim Item-Export
    (``services/csv_export``), damit Excel sie unter deutscher Locale
    ohne Text-Import öffnet.

    **Eine Zeile je Gebietslevel**, nicht je Gebiet — dieselbe Auflösung,
    die der Baum aufgeklappt zeigt. Die Zusammenfassung ließe sich aus
    diesen Zeilen jederzeit bilden, umgekehrt nicht: Aus "Bazaar, 6
    Besuche, 71–72" ist nicht mehr herauszuholen, wie viele davon auf
    welcher Stufe lagen. Die Dauer steht in Sekunden statt als "7:12",
    damit eine Tabellenkalkulation damit rechnen kann.

    Über alle Ligen hinweg (``league=None``) bekommt jede Liga ihre
    EIGENEN Zeilen statt einer zusammengeworfenen: Der Atlas baut sich
    mit jeder Season um, eine Zeile "Chateau 68–76" gäbe einen Wert
    wieder, den es nie gab."""
    with open(path, "w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.writer(datei, delimiter=";")
        schreiber.writerow(["League", "Group", "Zone", "Area id", "Tier",
                            "Monster level", "Visits", "Deaths",
                            "Total seconds", "Average seconds", "Last seen"])
        for record in records:
            namen = [league] if league is not None else sorted(record.leagues)
            for name in namen:
                zahlen = record.stats(name)
                for level, w in sorted(zahlen.by_level.items()):
                    tier = (map_tier_from_level(level)
                            if record.category in TIER_CATEGORIES else None)
                    schreiber.writerow([
                        name, record.category, record.name, record.area_id,
                        tier or "", level if level != NO_LEVEL else "",
                        w.visits, w.deaths, round(w.seconds),
                        round(w.average_seconds),
                        w.last_seen.replace("T", " "),
                    ])


class ZoneTableDialog(QDialog):
    def __init__(self, records: list[ZoneRecord], parent: QWidget | None = None,
                 character_level: int = 0, account_name: str = "",
                 league: str | None = None) -> None:
        """``league`` ist die Vorauswahl — die zuletzt gespielte Liga,
        denn wer die Tabelle öffnet, meint den Atlas, auf dem er gerade
        steht (Peter, 2026-09-26: "die Zonen hier [hängen] auch von der
        aktuellen Season ab", und dann: "Wir machen Liga, statt
        Season")."""
        super().__init__(parent)
        self.setWindowTitle("Zones")
        self.resize(880, 560)
        # Wie beim Mod-Album: Ein QDialog bekommt unter Windows sonst
        # keinen Maximieren-Knopf, und 381 Zeilen wollen Platz.
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self._account_name = account_name

        self._model = ZoneTreeModel(records, character_level, league)
        self._proxy = ZoneFilterProxy()
        self._proxy.setSourceModel(self._model)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search zones…")
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self._search.textChanged.connect(self._update_count)

        # Die Ligen, die im Katalog wirklich vorkommen, zuletzt gespielte
        # zuerst. ``UNKNOWN`` sammelt die Zeit, für die sich kein
        # Charakter zuordnen ließ (§league_log) — es steht unten.
        self._league_combo = QComboBox()
        self._league_combo.setToolTip(
            "The atlas is rebuilt every season, and the leagues of one "
            "season differ in content — Vaal side areas do not exist in "
            "Ruthless at all. This picks which league's zones and levels "
            "the table shows.")
        for name in _league_choices(records):
            self._league_combo.addItem(
                "Unknown (no character could be matched)"
                if name == UNKNOWN else name, name)
        self._league_combo.addItem("All leagues", None)
        if league is not None and self._league_combo.findData(league) >= 0:
            self._league_combo.setCurrentIndex(self._league_combo.findData(league))
        self._league_combo.currentIndexChanged.connect(self._on_league_changed)

        self._group_combo = QComboBox()
        self._group_combo.addItem("All groups", "")
        for gruppe in CATEGORIES:
            self._group_combo.addItem(gruppe, gruppe)
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)

        self._count_label = QLabel()
        self._export_button = QPushButton("💾 Export CSV")
        self._export_button.setToolTip(
            "Save the zones currently shown (filtered) as CSV")
        self._export_button.clicked.connect(self._export)

        kopf = QHBoxLayout()
        kopf.addWidget(self._league_combo)
        kopf.addWidget(self._group_combo)
        kopf.addWidget(self._search, 1)
        kopf.addWidget(self._count_label)
        kopf.addWidget(self._export_button)

        self._view = QTreeView()
        self._view.setModel(self._proxy)
        self._view.setSortingEnabled(True)
        # Beim Öffnen die bestellte Unterteilung (siehe
        # ``ZoneFilterProxy.lessThan``); jeder Spaltenkopf schaltet um.
        self._view.sortByColumn(_GROUP_COL, Qt.SortOrder.AscendingOrder)
        self._view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self._view.setUniformRowHeights(True)
        self._view.setAlternatingRowColors(True)
        # Nichts wird vorab aufgeklappt: Das Azurite Mine hätte 37
        # Kinder, die Fathomless Depths ebenso viele (§Modul-Kopf).
        self._view.setExpandsOnDoubleClick(True)
        kopfzeile = self._view.header()
        kopfzeile.setSectionResizeMode(_NAME_COL, QHeaderView.ResizeMode.Stretch)
        kopfzeile.setSectionResizeMode(_ID_COL, QHeaderView.ResizeMode.Stretch)
        for spalte in (_GROUP_COL, _TIER_COL, _LEVEL_COL, _VISITS_COL,
                       _DEATHS_COL, _TIME_COL, _SEEN_COL):
            kopfzeile.setSectionResizeMode(spalte,
                                           QHeaderView.ResizeMode.ResizeToContents)

        aufbau = QVBoxLayout(self)
        aufbau.addLayout(kopf)
        aufbau.addWidget(self._view)
        self._update_count()

    def _on_group_changed(self) -> None:
        self._proxy.set_group(self._group_combo.currentData() or "")
        self._update_count()

    def _on_league_changed(self) -> None:
        """Die Liga wechselt die Zahlen UND die Zeilen: Zonen, die es
        dort nicht gab, verschwinden. Nach dem Modell-Reset muss die
        Sortierung neu angewandt werden, sonst steht die Tabelle in der
        Reihenfolge des Katalogs da."""
        self._model.set_league(self._league_combo.currentData())
        self._view.sortByColumn(self._view.horizontalHeader().sortIndicatorSection(),
                                self._view.horizontalHeader().sortIndicatorOrder())
        self._update_count()

    def _update_count(self) -> None:
        sichtbar = self._proxy.rowCount()
        gesamt = self._model.rowCount()
        self._count_label.setText(
            f"{sichtbar} zones" if sichtbar == gesamt
            else f"{sichtbar} of {gesamt} zones")

    def visible_records(self) -> list[ZoneRecord]:
        """Was gerade in der Tabelle steht, in der Reihenfolge der
        Anzeige — der Export soll das speichern, was man sieht (dieselbe
        Regel wie beim Item-Export)."""
        gefunden = []
        for zeile in range(self._proxy.rowCount()):
            quelle = self._proxy.mapToSource(self._proxy.index(zeile, 0))
            record = self._model.record_at(quelle.row())
            if record is not None:
                gefunden.append(record)
        return gefunden

    def _export(self) -> None:
        # Die Liga steht im Dateinamen: Wer zwei Ligen vergleichen will,
        # exportiert zweimal und hätte sonst zweimal "zones.csv".
        liga = self._model.league()
        teile = ["zones", self._account_name, liga or "all-leagues"]
        vorschlag = sanitize_filename("-".join(t for t in teile if t), "zones")
        pfad, _ = QFileDialog.getSaveFileName(
            self, "Export zones as CSV", str(Path.home() / f"{vorschlag}.csv"),
            "CSV files (*.csv)")
        if not pfad:
            return
        try:
            export_zones(pfad, self.visible_records(), liga)
        except OSError as fehler:
            QMessageBox.warning(self, "Export failed", str(fehler))
