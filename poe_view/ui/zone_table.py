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
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (QAbstractItemModel, QByteArray, QModelIndex,
                            QSortFilterProxyModel, Qt)
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QTreeView,
                               QVBoxLayout, QWidget)

from poe_view.services.csv_export import sanitize_filename
from poe_view.ui.column_filter import (PLACEHOLDER, FilterHeader,
                                       expression_matches)
from poe_view.services.experience import experience_multiplier
from poe_view.services.league_log import UNKNOWN
from poe_view.ui.theme import DASH_BAD, DASH_OK, DASH_WARN, blend
from poe_view.services.zone_catalog import (CATEGORIES, NO_LEVEL, REST,
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
#
# "Visits" zählt Karten, "Entries" jeden Eintritt (Peter, 2026-10-01:
# "wird hier jeder Besuch gezählt (auch Händlerbesuche) oder die gesamte
# Map?" — und dann: "Ja bitte beide Spalten", §zone_catalog.LevelStats).
COLUMNS = ("Group", "Zone", "Tier", "Monster Level", "Visits", "Entries",
           "Deaths", "Monsters", "XP/h", "Avg. time", "Last seen", "Area id")
(_GROUP_COL, _NAME_COL, _TIER_COL, _LEVEL_COL, _VISITS_COL, _ENTRIES_COL,
 _DEATHS_COL, _MONSTERS_COL, _XP_COL, _TIME_COL, _SEEN_COL, _ID_COL) = range(12)

_HEADER_TOOLTIPS = {
    _VISITS_COL: "Separate runs. Going back into the same map — after a "
                 "vendor trip or a death —\nis still the same visit. "
                 "Hideouts and towns count every entry.",
    _ENTRIES_COL: "Every time you entered, including each return to the "
                  "same map.\nMany entries per visit mean many trips out "
                  "and back in.",
    _TIME_COL: "Average time per visit, all entries of a map added up.",
    _XP_COL: "Experience per hour your character would get here NOW: the pace "
             "measured before the\nlevel penalty, times today's penalty. "
             "Measured from publications covering exactly one zone,\n"
             "without a death. Fills in as you play.",
    _LEVEL_COL: "Shaded by how much experience your character still gets "
                "here:\ngreen 100 %, yellow 50 % or more, red below. A "
                "collapsed zone shows its best level.",
    _MONSTERS_COL: "Monsters killed per visit, from your /kills readings in "
                   "Client.txt:\nthe pace measured between two readings with "
                   "exactly one map in between,\ntimes the average time per "
                   "visit. Empty until such a pair of readings exists.",
}


# Die Tönung der Level-Zelle (Peter, 2026-10-03: "die Zonen, in denen sich
# momentan Leveling lohnt (100%) grün einfärben, die Zonen, welche noch
# mehr als 50% ... bringen gelb, die anderen rot"). Die Ampel der Anwendung
# zu 40 % in den Grund gemischt, Schrift unverändert. Gerechnet, nativ:
# dunkel Text 6,2–8,9:1 auf der Tönung, hell 12–15:1; Abstand zum
# ungetönten Grund ΔE 22–33. Als reine Schriftfarbe fiele Rot dunkel auf
# 3,2:1 und Gelb hell auf 2,2:1.
_AMPEL_ANTEIL = 0.4
_GELB_AB = 0.5


def _ampel(anteil: float) -> str:
    if anteil >= 0.999:
        return DASH_OK
    return DASH_WARN if anteil >= _GELB_AB else DASH_BAD


def _ampel_brush(anteil: float) -> QBrush:
    grund = QApplication.palette().color(QPalette.ColorRole.Base)
    return QBrush(blend(grund, QColor(_ampel(anteil)), _AMPEL_ANTEIL))


def _xp_now(by_level: dict, character_level: int) -> tuple[float, float]:
    """(XP pro Stunde für den Charakter jetzt, gemessene Sekunden) über
    die gegebenen Stufen — jede mit IHRER Strafe, dann zusammengezählt.
    Ohne Charakterstufe gilt keine Strafe (``experience_multiplier``
    liefert dann 1,0)."""
    xp = sum(w.xp_base * experience_multiplier(character_level, lv)
             for lv, w in by_level.items() if lv != NO_LEVEL)
    sekunden = sum(w.xp_seconds for lv, w in by_level.items() if lv != NO_LEVEL)
    return (xp * 3600 / sekunden if sekunden else 0.0), sekunden


def _xp_text(rate: float, sekunden: float) -> str:
    if not sekunden:
        return ""
    return f"{rate / 1e6:.1f} M" if rate >= 1e5 else f"{rate / 1e3:.0f} k"


def _monster_text(zahlen) -> str:
    """"884" — oder leer, solange nichts gemessen ist (§zone_catalog.
    attribute_kills). Ohne Durchschnittszeit lässt sich nicht je Besuch
    hochrechnen; dann steht das Tempo da, damit die Messung nicht
    verschwindet."""
    if not zahlen.kill_seconds:
        return ""
    if zahlen.average_seconds:
        return str(round(zahlen.monsters_per_visit))
    return f"{zahlen.kills_per_minute:.0f}/min"


def _monster_tooltip(zahlen) -> str | None:
    if not zahlen.kill_seconds:
        return None
    return (f"{zahlen.kills_per_minute:.1f} kills per minute, measured over "
            f"{_dauer_text(zahlen.kill_seconds) or '0 s'} ({zahlen.kills} kills)."
            "\nPer visit = this pace × the average time per visit.")

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

    def set_records(self, records: list[ZoneRecord]) -> None:
        """Neuer Stand aus dem Katalog (Aktualisieren, §ZoneTableDialog
        .refresh) — Liga und Charakterlevel bleiben, wie sie sind."""
        self.beginResetModel()
        self._records = records
        self.endResetModel()

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
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        if role == Qt.ItemDataRole.ToolTipRole:
            return _HEADER_TOOLTIPS.get(section)
        return None

    def display_text(self, row: int, col: int) -> str:
        """Der Text, den die oberste Ebene in dieser Zelle zeigt —
        Grundlage des Spalten-Filters (§column_filter). Bewusst der
        ANGEZEIGTE Text und nicht der Rohwert: Gefiltert wird, was man
        sieht, sonst passt "4–5" im Feld auf nichts."""
        wert = self._zone_data(self.record_at(row), col,
                               Qt.ItemDataRole.DisplayRole)
        return wert if isinstance(wert, str) else ""

    def distinct_values(self, col: int) -> list[str]:
        """Die in dieser Spalte tatsächlich vorkommenden Werte, für die
        Autovervollständigung. Nur die Gebiete der laufenden Liga — was
        anderswo vorkam, ist hier nicht filterbar und stünde als
        Vorschlag, der auf nichts passt."""
        werte = {self.display_text(zeile, col)
                 for zeile in range(len(self._records))
                 if self._records[zeile].seen_in(self._league)}
        werte.discard("")
        werte.discard("–")
        return sorted(werte)

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
                    str(zahlen.visits), str(zahlen.entries),
                    str(zahlen.deaths) if zahlen.deaths else "",
                    _monster_text(zahlen),
                    _xp_text(*_xp_now(zahlen.by_level, self._character_level)),
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
            if col == _ENTRIES_COL:
                return zahlen.entries
            if col == _DEATHS_COL:
                return zahlen.deaths
            if col == _MONSTERS_COL:
                return zahlen.monsters_per_visit if zahlen.kill_seconds else -1
            if col == _XP_COL:
                rate, sekunden = _xp_now(zahlen.by_level, self._character_level)
                return rate if sekunden else -1
            if col == _TIME_COL:
                return zahlen.average_seconds
            return (self._zone_data(record, col, Qt.ItemDataRole.DisplayRole)
                    or "").lower()
        if role == Qt.ItemDataRole.ToolTipRole and col == _LEVEL_COL:
            return self._level_tooltip(record)
        if role == Qt.ItemDataRole.ToolTipRole and col == _MONSTERS_COL:
            return _monster_tooltip(zahlen)
        if role == Qt.ItemDataRole.ToolTipRole and col == _XP_COL:
            return self._xp_tooltip(zahlen.by_level)
        if role == Qt.ItemDataRole.BackgroundRole and col == _LEVEL_COL:
            anteile = [experience_multiplier(self._character_level, lv)
                       for lv in record.stats(self._league).levels]
            return self._shade(record, max(anteile, default=None))
        if role == Qt.ItemDataRole.ToolTipRole and col == _TIME_COL:
            return (f"{zahlen.visits} visits ({zahlen.entries} entries), "
                    f"{_dauer_text(zahlen.seconds) or '0 s'} in total"
                    if zahlen.seconds else None)
        return None

    def _shade(self, record: ZoneRecord, anteil: float | None):
        """Tönung nur mit bekannter Charakterstufe und nur für Zonen mit
        Monstern — Hideout und Städte bleiben ungefärbt."""
        if not self._character_level or anteil is None or record.category == REST:
            return None
        return _ampel_brush(anteil)

    def _xp_tooltip(self, by_level: dict) -> str | None:
        rate, sekunden = _xp_now(by_level, self._character_level)
        if not sekunden:
            return None
        basis = sum(w.xp_base for lv, w in by_level.items() if lv != NO_LEVEL) * 3600 / sekunden
        wer = (f"at character level {self._character_level}"
               if self._character_level else "without a character level, so no penalty")
        return (f"{rate / 1e6:.2f} M XP per hour {wer}.\n"
                f"Measured before the penalty: {basis / 1e6:.2f} M per hour "
                f"over {_dauer_text(sekunden) or '0 s'}.")

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
                    str(zahlen.visits), str(zahlen.entries),
                    str(zahlen.deaths) if zahlen.deaths else "",
                    _monster_text(zahlen),
                    _xp_text(*_xp_now({level: zahlen}, self._character_level)),
                    _dauer_text(zahlen.average_seconds),
                    zahlen.last_seen.replace("T", " "), "")[col]
        if role == NUMERIC_SORT_ROLE:
            if col == _TIER_COL:
                return tier if tier else -1
            if col == _LEVEL_COL:
                return level
            if col == _VISITS_COL:
                return zahlen.visits
            if col == _ENTRIES_COL:
                return zahlen.entries
            if col == _DEATHS_COL:
                return zahlen.deaths
            if col == _MONSTERS_COL:
                return zahlen.monsters_per_visit if zahlen.kill_seconds else -1
            if col == _XP_COL:
                rate, sekunden = _xp_now({level: zahlen}, self._character_level)
                return rate if sekunden else -1
            if col == _TIME_COL:
                return zahlen.average_seconds
            return level
        if role == Qt.ItemDataRole.ToolTipRole and col == _TIME_COL:
            return (f"{zahlen.visits} visits ({zahlen.entries} entries), "
                    f"{_dauer_text(zahlen.seconds) or '0 s'} in total"
                    if zahlen.seconds else None)
        if role == Qt.ItemDataRole.ToolTipRole and col == _MONSTERS_COL:
            return _monster_tooltip(zahlen)
        if role == Qt.ItemDataRole.ToolTipRole and col == _XP_COL:
            return self._xp_tooltip({level: zahlen})
        if role == Qt.ItemDataRole.BackgroundRole and col == _LEVEL_COL:
            return self._shade(record, experience_multiplier(self._character_level, level)
                               if level != NO_LEVEL else None)
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
        self._column_filters: dict[int, str] = {}

    # --- Spalten-Filter (Peter, 2026-09-27: "Bitte auch hier nochmal so
    # eine Art Excel-Filter einbauen ... sowas haben wir ja schon in der
    # Item-List") — dieselben Methodennamen wie in ``ItemFilterProxy``,
    # damit wer eine kennt, die andere auch kennt.

    def set_column_filter(self, col: int, expr: str) -> None:
        expr = (expr or "").strip()
        self.beginFilterChange()
        if expr:
            self._column_filters[col] = expr
        else:
            self._column_filters.pop(col, None)
        self.endFilterChange()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, col, col)

    def column_filter(self, col: int) -> str:
        return self._column_filters.get(col, "")

    def filtered_columns(self) -> set[int]:
        return set(self._column_filters)

    def clear_column_filters(self) -> None:
        cols = list(self._column_filters)
        self.beginFilterChange()
        self._column_filters.clear()
        self.endFilterChange()
        for col in cols:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, col, col)

    # Keine Lupe im Spaltennamen wie in der Item-Liste: Hier steht der
    # Filter in seinem Feld direkt darunter (§FilterHeader) — ein
    # aktiver Filter ist damit ohnehin zu sehen, und die Lupe machte nur
    # die Spalte breiter.

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
        for spalte, ausdruck in self._column_filters.items():
            if not expression_matches(ausdruck, model.display_text(row, spalte)):
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
                            "Monster level", "Visits", "Entries", "Deaths",
                            "Total seconds", "Average seconds", "Last seen",
                            "Kills counted", "Kill seconds", "Kills per minute",
                            "Monsters per visit", "Base XP per hour",
                            "XP seconds"])
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
                        w.visits, w.entries, w.deaths, round(w.seconds),
                        round(w.average_seconds),
                        w.last_seen.replace("T", " "),
                        w.kills if w.kill_seconds else "",
                        round(w.kill_seconds) if w.kill_seconds else "",
                        round(w.kills_per_minute, 1) if w.kill_seconds else "",
                        round(w.monsters_per_visit) if w.kill_seconds
                        and w.average_seconds else "",
                        round(w.base_xp_per_hour) if w.xp_seconds else "",
                        round(w.xp_seconds) if w.xp_seconds else "",
                    ])


class ZoneTableDialog(QDialog):
    def __init__(self, records: list[ZoneRecord], parent: QWidget | None = None,
                 character_level: int = 0, account_name: str = "",
                 league: str | None = None,
                 reload: Callable[[], list[ZoneRecord] | None] | None = None) -> None:
        """``league`` ist die Vorauswahl — die zuletzt gespielte Liga,
        denn wer die Tabelle öffnet, meint den Atlas, auf dem er gerade
        steht (Peter, 2026-09-26: "die Zonen hier [hängen] auch von der
        aktuellen Season ab", und dann: "Wir machen Liga, statt
        Season").

        ``reload`` holt einen frischen Stand aus der Client.txt (Peter,
        2026-10-01: "wir brauchen einen aktualisieren Button in der
        Anzeige für die Zonen oder eine automatische aktualisierung") —
        beides hängt daran: der Knopf und das MainWindow, das bei jedem
        Zonenwechsel ``refresh`` ruft, solange die Tabelle offen ist."""
        super().__init__(parent)
        self.setWindowTitle("Zones")
        self.resize(880, 560)
        # Wie beim Mod-Album: Ein QDialog bekommt unter Windows sonst
        # keinen Maximieren-Knopf, und 381 Zeilen wollen Platz.
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self._account_name = account_name
        self._reload = reload

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
        self._fill_league_combo(records, league)
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
        self._refresh_button = QPushButton("⟳ Refresh")
        self._refresh_button.setToolTip(
            "Read the latest zones from Client.txt.\nWhile this window is "
            "open, it also updates by itself on every zone change.")
        self._refresh_button.clicked.connect(self.refresh)
        self._refresh_button.setVisible(reload is not None)

        kopf = QHBoxLayout()
        kopf.addWidget(self._league_combo)
        kopf.addWidget(self._group_combo)
        kopf.addWidget(self._search, 1)
        kopf.addWidget(self._count_label)
        kopf.addWidget(self._refresh_button)
        kopf.addWidget(self._export_button)

        self._view = QTreeView()
        # Der Spaltenkopf trägt die Filterfelder (§column_filter
        # .FilterHeader) — VOR setModel und setSortingEnabled gesetzt,
        # damit die Ansicht ihn von Anfang an als ihren eigenen führt.
        self._filter_header = FilterHeader(self._view)
        self._view.setHeader(self._filter_header)
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
        kopfzeile = self._filter_header
        kopfzeile.set_column_count(
            len(COLUMNS), f"Filter this column: {PLACEHOLDER}")
        kopfzeile.filter_changed.connect(self.apply_column_filter)
        kopfzeile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        kopfzeile.customContextMenuRequested.connect(self._on_header_menu)
        # Auch Name und Kennung nach Inhalt, nicht mehr gestreckt (Peter,
        # 2026-10-02: "wir könnten die Größe des Fensters überarbeiten
        # abhängig von der optimierten Spaltenbreite"). Gestreckt teilten
        # sie sich jeden freien Pixel — an seinem Bildschirm stand
        # "Zone" 280 Pixel breit über Namen von 120. Jetzt bestimmen die
        # Spalten das Fenster (§_fit_to_columns), und wird es größer
        # gezogen, nimmt die letzte Spalte den Rest
        # (``stretchLastSection``, die Voreinstellung des Baums).
        # Die Breiten werden EINMAL nach dem Inhalt bemessen und stehen
        # dann still (Interactive, von Hand ziehbar). Mit
        # ResizeToContents passten sie sich bei jedem Filter neu an — und
        # das Feld, in das man gerade tippt, rutschte unter dem Cursor
        # weg (an Peters Bildschirm gesehen: "Map" in Group, die Spalte
        # wurde schmaler, sobald "Side Area" herausgefiltert war).
        for spalte in range(len(COLUMNS)):
            kopfzeile.setSectionResizeMode(spalte,
                                           QHeaderView.ResizeMode.Interactive)
            self._view.resizeColumnToContents(spalte)
        self._update_suggestions()

        aufbau = QVBoxLayout(self)
        aufbau.addLayout(kopf)
        aufbau.addWidget(self._view)
        self._update_count()
        self._fit_to_columns()

    def _fit_to_columns(self) -> None:
        """Das Fenster so breit wie die Spalten nach ihrem Inhalt (höchstens
        90 % des Bildschirms), so hoch wie die Zeilen (höchstens 70 %). Darunter nie schmaler als die Kopfzeile mit Liga,
        Suche und Knöpfen, sonst würden die zusammengedrückt."""
        bildschirm = (self.parentWidget().screen() if self.parentWidget()
                      else QGuiApplication.primaryScreen())
        frei = bildschirm.availableGeometry() if bildschirm else None
        rand = self.layout().contentsMargins()
        rahmen = 2 * self._view.frameWidth()
        rollbalken = self._view.verticalScrollBar().sizeHint().width()
        kopf = self._filter_header
        # Aus dem Inhalt gerechnet statt aus ``sectionSize``: Die letzte
        # Spalte wird gestreckt (``stretchLastSection``), ihre aktuelle
        # Größe hängt also am Fenster — vor dem ersten Anzeigen ist das
        # noch dasselbe, danach nicht mehr.
        spalten = sum(max(self._view.sizeHintForColumn(c), kopf.sectionSizeHint(c))
                      for c in range(kopf.count()) if not kopf.isSectionHidden(c))
        breite = max(spalten + rahmen + rollbalken + rand.left() + rand.right(),
                     self.layout().itemAt(0).sizeHint().width()
                     + rand.left() + rand.right())
        zeile = max(self._view.sizeHintForRow(0), 1) if self._proxy.rowCount() else 20
        hoehe = (rand.top() + rand.bottom() + self.layout().spacing()
                 + self.layout().itemAt(0).sizeHint().height()
                 + kopf.sizeHint().height() + rahmen
                 + zeile * max(self._proxy.rowCount(), 8)
                 + self._view.horizontalScrollBar().sizeHint().height())
        if frei is not None:
            breite = min(breite, int(frei.width() * 0.9))
            # Höhe knapper als die Breite: 381 Zonen füllten sonst jeden
            # Bildschirm von oben bis unten, und ein Fenster, das alles
            # verdeckt, ist kein Nachschlagefenster mehr.
            hoehe = min(hoehe, int(frei.height() * 0.7))
        self.resize(breite, hoehe)

    # --- Spalten-Filter: Felder im Kopf (§column_filter.FilterHeader) -- #

    def apply_column_filter(self, col: int, expr: str) -> None:
        """Wird bei jedem Tastendruck im Feld gerufen. Steht der Text
        nicht schon im Feld (Aufruf von außen), wird er dort eingetragen
        — das Feld ist die eine Stelle, die den Filter zeigt."""
        if self._filter_header.filter_text(col) != (expr or "").strip():
            self._filter_header.set_filter_text(col, expr)
            return  # das Feld meldet sich über filter_changed zurück
        self._proxy.set_column_filter(col, expr)
        self._update_count()

    def _update_suggestions(self) -> None:
        """Vorschläge je Feld aus dem, was in DIESER Liga in der Spalte
        steht (§ZoneTreeModel.distinct_values)."""
        for spalte in range(len(COLUMNS)):
            self._filter_header.set_suggestions(
                spalte, self._model.distinct_values(spalte))

    def _on_header_menu(self, pos) -> None:
        if not self._proxy.filtered_columns():
            return
        menu = QMenu(self._view)
        loeschen = menu.addAction("✕ Clear all column filters")
        loeschen.triggered.connect(self._clear_column_filters)
        menu.exec(self._filter_header.mapToGlobal(pos))

    def _clear_column_filters(self) -> None:
        self._filter_header.clear_filters()

    # --- Gemerkter Zustand (Peter, 2026-10-02) ------------------------- #

    def view_state(self) -> dict:
        """Was beim nächsten Öffnen wieder so stehen soll: Gruppe, Suche,
        Spaltenfilter, Sortierung, aufgeklappte Gebiete, Fenster.

        Peter, 2026-10-02: "bei Zones: welche filter ausgewählt, gruppe".
        Die Liga bewusst NICHT: Sie richtet sich beim Öffnen nach der
        zuletzt gespielten (§__init__) — eine gemerkte stünde nach dem
        Start einer neuen Liga auf der alten, und genau dann schaut man
        nach. Spalten über ihren NAMEN, nicht die Nummer: Kommt eine
        Spalte dazu, landete ein Filter sonst in der falschen."""
        kopf = self._filter_header
        sortiert = kopf.sortIndicatorSection()
        return {
            "group": self._group_combo.currentData() or "",
            "search": self._search.text(),
            "filters": {COLUMNS[c]: kopf.filter_text(c)
                        for c in range(len(COLUMNS)) if kopf.filter_text(c)},
            "sort": ([COLUMNS[sortiert],
                      "desc" if kopf.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
                      else "asc"]
                     if 0 <= sortiert < len(COLUMNS) else None),
            "expanded": sorted(self._expanded_area_ids()),
            "geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
        }

    def apply_view_state(self, state: object) -> None:
        """Gegenstück zu ``view_state``. Verträgt alles, was in einer
        Einstellungsdatei stehen kann — auch Unsinn: Ein kaputter Eintrag
        darf das Fenster nicht am Öffnen hindern, er fällt dann eben auf
        die Voreinstellung zurück."""
        if not isinstance(state, dict):
            return
        gruppe = state.get("group")
        if isinstance(gruppe, str) and self._group_combo.findData(gruppe) >= 0:
            self._group_combo.setCurrentIndex(self._group_combo.findData(gruppe))
        suche = state.get("search")
        if isinstance(suche, str):
            self._search.setText(suche)
        filter_ = state.get("filters")
        if isinstance(filter_, dict):
            for name, text in filter_.items():
                if name in COLUMNS and isinstance(text, str):
                    self._filter_header.set_filter_text(COLUMNS.index(name), text)
        sortierung = state.get("sort")
        if (isinstance(sortierung, list) and len(sortierung) == 2
                and sortierung[0] in COLUMNS):
            self._view.sortByColumn(
                COLUMNS.index(sortierung[0]),
                Qt.SortOrder.DescendingOrder if sortierung[1] == "desc"
                else Qt.SortOrder.AscendingOrder)
        offen = state.get("expanded")
        if isinstance(offen, list):
            self._restore_expanded({a for a in offen if isinstance(a, str)})
        fenster = state.get("geometry")
        if isinstance(fenster, str) and fenster:
            # Anders als das Hauptfenster (FALLSTRICKE #93) braucht der
            # Dialog kein vorgezogenes winId(): An Peters vier Monitoren
            # gemessen, mit und ohne Elternfenster, bleibt er auch so auf
            # dem Monitor links vom Hauptmonitor.
            self.restoreGeometry(QByteArray.fromBase64(fenster.encode("ascii")))

    # --- Aktualisieren ------------------------------------------------- #

    def refresh(self) -> None:
        """Frischen Stand holen und einsetzen. Ohne ``reload`` (oder wenn
        er nichts liefert, z. B. weil der Zonen-Beobachter inzwischen aus
        ist) bleibt alles, wie es ist."""
        if self._reload is None:
            return
        records = self._reload()
        if records is not None:
            self.set_records(records)

    def set_records(self, records: list[ZoneRecord]) -> None:
        """Den neuen Stand einsetzen, OHNE dass sich die Ansicht unter dem
        Nutzer wegdreht: Liga, Gruppe, Suche, Spaltenfilter, Sortierung,
        aufgeklappte Gebiete, Auswahl und Scrollposition bleiben. Sonst
        risse jeder Zonenwechsel die Tabelle zurück an den Anfang, und
        die automatische Aktualisierung wäre eine Störung statt einer
        Hilfe."""
        aufgeklappt = self._expanded_area_ids()
        auswahl = self._selected_area_id()
        scroll = self._view.verticalScrollBar().value()
        liga = self._model.league()

        self._league_combo.blockSignals(True)
        self._league_combo.clear()
        self._fill_league_combo(records, liga)
        self._league_combo.blockSignals(False)
        self._model.set_records(records)
        # Fehlt die gewählte Liga im neuen Stand (sollte nie vorkommen —
        # der Katalog vergisst nichts), zeigt die Box jetzt etwas anderes
        # als das Modell. Die Box gewinnt.
        self._model.set_league(self._league_combo.currentData())
        self._resort()
        self._restore_expanded(aufgeklappt)
        self._select_area_id(auswahl)
        self._view.verticalScrollBar().setValue(scroll)
        self._update_suggestions()
        self._update_count()

    def _fill_league_combo(self, records: list[ZoneRecord], league: str | None) -> None:
        for name in _league_choices(records):
            self._league_combo.addItem(
                "Unknown (no character could be matched)"
                if name == UNKNOWN else name, name)
        self._league_combo.addItem("All leagues", None)
        if league is not None and self._league_combo.findData(league) >= 0:
            self._league_combo.setCurrentIndex(self._league_combo.findData(league))
        else:
            self._league_combo.setCurrentIndex(self._league_combo.count() - 1
                                               if league is None else 0)

    def _expanded_area_ids(self) -> set[str]:
        gefunden = set()
        for zeile in range(self._proxy.rowCount()):
            index = self._proxy.index(zeile, 0)
            if self._view.isExpanded(index):
                record = self._model.record_for(self._proxy.mapToSource(index))
                if record is not None:
                    gefunden.add(record.area_id)
        return gefunden

    def _restore_expanded(self, area_ids: set[str]) -> None:
        if not area_ids:
            return
        for zeile in range(self._proxy.rowCount()):
            index = self._proxy.index(zeile, 0)
            record = self._model.record_for(self._proxy.mapToSource(index))
            if record is not None and record.area_id in area_ids:
                self._view.expand(index)

    def _selected_area_id(self) -> str | None:
        index = self._view.currentIndex()
        if not index.isValid():
            return None
        record = self._model.record_for(self._proxy.mapToSource(index))
        return record.area_id if record is not None else None

    def _select_area_id(self, area_id: str | None) -> None:
        if area_id is None:
            return
        for zeile in range(self._proxy.rowCount()):
            index = self._proxy.index(zeile, 0)
            record = self._model.record_for(self._proxy.mapToSource(index))
            if record is not None and record.area_id == area_id:
                self._view.setCurrentIndex(index)
                return

    def _resort(self) -> None:
        """Nach einem Modell-Reset die gewählte Sortierung neu anwenden,
        sonst steht die Tabelle in der Reihenfolge des Katalogs da."""
        kopf = self._view.header()
        self._view.sortByColumn(kopf.sortIndicatorSection(),
                                kopf.sortIndicatorOrder())

    def _on_group_changed(self) -> None:
        self._proxy.set_group(self._group_combo.currentData() or "")
        self._update_count()

    def _on_league_changed(self) -> None:
        """Die Liga wechselt die Zahlen UND die Zeilen: Zonen, die es
        dort nicht gab, verschwinden. Nach dem Modell-Reset muss die
        Sortierung neu angewandt werden, sonst steht die Tabelle in der
        Reihenfolge des Katalogs da."""
        # Bis 2026-10-01 stand hier ``horizontalHeader()`` — das hat eine
        # QTableView, ein QTreeView nicht. Der Aufruf warf, die Zahlen
        # wechselten zwar (das Modell war schon umgestellt), Sortierung
        # und Zähler blieben aber auf dem alten Stand.
        self._model.set_league(self._league_combo.currentData())
        self._resort()
        self._update_suggestions()
        self._update_count()

    def _update_count(self) -> None:
        # Gesamt sind die Zonen DIESER Liga, nicht alle im Katalog: Sonst
        # stünde nach dem Wechsel auf eine Liga mit zwei Zonen "2 of 4"
        # da, als versteckte ein Filter zwei davon.
        sichtbar = self._proxy.rowCount()
        liga = self._model.league()
        gesamt = sum(1 for zeile in range(self._model.rowCount())
                     if self._model.record_at(zeile).seen_in(liga))
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
