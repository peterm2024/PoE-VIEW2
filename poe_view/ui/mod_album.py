"""Das Album: durch die Mod-Sammlung blättern (§4.52, Stufe 3).

Peter, 2026-08-24: "Ich finde die Idee mit der eigenen Datenbank am
besten, hat etwas von einer Briefmarkensammlung: Einfach mal jedes Objekt
in der Hand gehalten zu haben und von PoE-VIEW kategorisiert und
eingetragen. Kann ja auch Spaß machen ;-)"

Die ersten beiden Stufen der Sammlung (aufschreiben, am Item anzeigen)
beantworten "wie gut ist DIESER Roll". Dieses Fenster beantwortet die
andere Frage, die eine Sammlung erst zur Sammlung macht: "was habe ich
eigentlich alles?" — durchsuchbar nach Text, Art, Liga und Rarität, mit
den vollen Spannen je Liga und Rarität für den markierten Eintrag.

**Ein Schnappschuss, keine Live-Ansicht.** Die Sammlung wächst nebenbei
weiter, während das Fenster offen ist; es zeigt den Stand vom Öffnen. Ein
Fenster, das sich unter der Maus neu sortiert, wäre für Durchblättern
schlechter als eines, das sich beim nächsten Öffnen einfach neu befüllt.

**Die Range-Spalte zeigt den Bereich über GENAU die Töpfe, die die
Liga-/Raritäts-Auswahl gerade durchlässt** — bei "All leagues" / "All
rarities" also über die ganze Sammlung. Das ist eine bewusste Wahl: Die
Spalte könnte auch versuchen, "den einen richtigen" Topf zu erraten, aber
das würde genau die Frage vortäuschen zu beantworten, die die Liga-/
Raritäts-Bucketierung (§4.52.1) aufgeworfen hat. Stattdessen zeigt sie
ehrlich die Vereinigung dessen, was gerade ausgewählt ist — schmaler,
sobald man Liga oder Rarität eingrenzt.

Peter, 2026-08-25, wollte zusätzlich nach "Unique, Corrupted,
(Normal/Magic/Rare)" filtern können. Corrupted ist dabei kein weiterer
Wert einer bestehenden Achse, sondern ein Aufschlag auf die Rarität selbst
(``mod_collection.CORRUPTED_OFFSET``) — ein corrupted Rare bekommt einen
anderen Topf als ein gewöhnliches Rare UND als ein corrupted Unique.
**Das gilt nur für neue Beobachtungen**: Ein Wert, der vor dieser
Änderung im gewöhnlichen Topf gelandet ist, bleibt dort stehen (siehe
Kommentar bei ``CORRUPTED_OFFSET``).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPlainTextEdit, QSplitter,
                               QTableView, QVBoxLayout, QWidget)

from poe_view.api.models import (ENCHANT_MOD_FIELD, EXTRA_MOD_FIELDS,
                                 FRAME_TYPE_NAMES)
from poe_view.services.mod_collection import (LEGACY_LEAGUE, MAP_RARITY,
                                              UNKNOWN_RARITY, ModCollection,
                                              ModRecord, RaritySpan, base_rarity,
                                              is_corrupted_bucket)

# Anzeigenamen der Mod-Arten. Eigene Tabelle statt einer aus
# ``csv_export.py`` übernommenen — die dortige ist auf Spaltenüberschriften
# zugeschnitten (``CraftedMods``), hier sind es Werte in einer Filter-Box.
KIND_LABELS = {
    "explicitMods": "Explicit",
    "implicitMods": "Implicit",
    ENCHANT_MOD_FIELD: "Enchant",
    "utilityMods": "Flask",
    "craftedMods": "Crafted",
    "fracturedMods": "Fractured",
    "veiledMods": "Veiled",
    "scourgeMods": "Scourge",
    "crucibleMods": "Crucible",
    "logbookMods": "Logbook",
    "ultimatumMods": "Ultimatum",
}
# Reihenfolge des Filter-Menüs: die häufigen zuerst (siehe ARCHITEKTUR
# §4.52, gemessen an Peters Bestand), Rest alphabetisch über EXTRA_MOD_FIELDS.
KIND_ORDER = ("explicitMods", "implicitMods", ENCHANT_MOD_FIELD, *EXTRA_MOD_FIELDS)

# Grobe Raritäts-Gruppen für den Filter — Peters eigene Gliederung
# ("Unique, Corrupted, (Normal/Magic/Rare), evtl. noch andere"). Rare/
# Magic/Normal in EINER Gruppe, weil Peter sie so benannt hat, obwohl die
# Sammlung sie intern längst getrennt hält — die Gruppe fasst beim
# Filtern nur wieder zusammen, was beim Anzeigen (Range-Spalte) ohnehin
# über alle passenden Töpfe geht.
#
# Ein PRÄDIKAT statt eines festen Zahlen-Tupels je Gruppe: "Corrupted"
# lässt sich nicht als endliche Liste schreiben — der Aufschlag
# (``CORRUPTED_OFFSET``) gilt auf JEDER Basis-Rarität, und die Gruppe
# soll unabhängig davon greifen, welche Rarität darunterliegt.
RarityPredicate = Callable[[int], bool]

RARITY_GROUPS: tuple[tuple[str, RarityPredicate], ...] = (
    ("Normal / Magic / Rare", lambda r: r in (0, 1, 2)),
    ("Unique", lambda r: r == 3),
    ("Corrupted", is_corrupted_bucket),
    ("Map", lambda r: r == MAP_RARITY),
    ("Gem / Currency / Card / Relic", lambda r: r in (4, 5, 6, 9)),
    ("Unknown rarity", lambda r: r == UNKNOWN_RARITY),
)
# Als Dict griffbereit für die Combo-Box: Ihre ``itemData`` trägt nur den
# Namen, nicht das Prädikat selbst — ``QComboBox.findData`` vergleicht
# Python-Tupel über den Umweg von QVariant manchmal nicht gleich, auch
# wenn sie es sind (in Peters Bestand reproduziert: ``findData((0, 1,
# 2))`` lieferte -1, obwohl genau dieses Tupel als ``itemData`` einer
# Zeile drinstand — dieselbe Vorsicht gilt für Funktionsobjekte). Ein
# Name als Schlüssel hat dieses Problem nicht, siehe ``KIND_LABELS``.
RARITY_GROUPS_BY_NAME: dict[str, RarityPredicate] = dict(RARITY_GROUPS)


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def rarity_label(rarity: int) -> str:
    """Menschenlesbarer Name eines Raritäts-Topfs — inklusive der beiden
    Sonderwerte der Sammlung, die kein ``frameType`` sind, und des
    Corrupted-Aufschlags (``CORRUPTED_OFFSET``)."""
    if is_corrupted_bucket(rarity):
        return f"Corrupted {rarity_label(base_rarity(rarity))}"
    if rarity == MAP_RARITY:
        return "Map"
    if rarity == UNKNOWN_RARITY:
        return "Unknown rarity"
    return FRAME_TYPE_NAMES.get(rarity, f"frameType {rarity}")


def league_label(league: str) -> str:
    return "Permanent leagues (Standard, SSF, …)" if league == LEGACY_LEAGUE else league


def _fmt_num(value: float) -> str:
    """``96.0`` -> ``"96"``, ``18.5`` -> ``"18.5"`` — ``g`` streicht
    genau die Nullen, die im Spiel auch nicht dastehen."""
    return f"{value:g}"


def _spread_text(spread: list[tuple[float, float]]) -> str:
    """``41–96``, aber ``-47 to -14`` statt ``-47–-14`` — ein Gedankenstrich
    direkt vor einem Minus liest sich wie ein dritter Strich (gemessen an
    Peters echtem Bestand: ``Physical Damage taken from Attack Hits``
    reicht von -47 bis -14). ``to`` ist zusätzlich dieselbe Formulierung,
    die das Spiel selbst für Spannen benutzt (``Adds 1 to 5 ... Damage``)."""
    if not spread:
        return "(no numbers)"
    teile = [_fmt_num(lo) if lo == hi
            else (f"{_fmt_num(lo)}–{_fmt_num(hi)}" if hi >= 0
                  else f"{_fmt_num(lo)} to {_fmt_num(hi)}")
            for lo, hi in spread]
    return ", ".join(teile)


def format_span(span: RaritySpan) -> str:
    """Eine Spanne als Zeile: Sichtungen, Werte, Item-Stufen.

    Mehrere Zahlen (``Adds # to # Lightning Damage``) bekommen mehrere
    Teilspannen, in der Reihenfolge, in der sie in der Zeile stehen —
    dieselbe Reihenfolge, die ``mod_values`` liest."""
    zeile = f"seen {span.count}× — {_spread_text(span.spread)}"
    if span.ilvl_high:
        zeile += f"  (iLvl {span.ilvl_low}–{span.ilvl_high})"
    return zeile


def format_record_detail(record: ModRecord) -> str:
    """Der volle Steckbrief eines Eintrags, für das Detail-Feld."""
    zeilen = [record.example or record.identity,
             f"{kind_label(record.kind)}  ·  seen {record.count}× in total",
             ""]
    for league in record.leagues:
        for rarity in sorted(record.spans[league]):
            span = record.spans[league][rarity]
            zeilen.append(f"{league_label(league)}  ·  {rarity_label(rarity)}")
            zeilen.append(f"    {format_span(span)}")
    return "\n".join(zeilen)


def matching_spans(record: ModRecord, league: str | None,
                   rarity_ok: RarityPredicate | None) -> list[RaritySpan]:
    """Alle Spannen des Eintrags, die zu Liga- UND Raritäts-Auswahl passen.

    ``None`` heißt "keine Einschränkung" auf dieser Achse — deshalb NICHT
    derselbe Sentinel wie ``LEGACY_LEAGUE`` (das ist der leere String und
    eine echte, wählbare Liga; ``None`` meint dagegen "alle Ligen")."""
    ergebnis = []
    for liga, je_liga in record.spans.items():
        if league is not None and liga != league:
            continue
        for rarity, span in je_liga.items():
            if rarity_ok is not None and not rarity_ok(rarity):
                continue
            ergebnis.append(span)
    return ergebnis


def combined_range_text(record: ModRecord, league: str | None,
                        rarity_ok: RarityPredicate | None) -> str:
    """Die Range-Spalte: der Wertebereich über alle Töpfe, die gerade
    ausgewählt sind — siehe Modulkopf, warum das absichtlich keine
    Vermutung über EINEN "richtigen" Topf ist."""
    spans = matching_spans(record, league, rarity_ok)
    if not spans:
        return "–"
    n = min(len(span.spread) for span in spans)
    spread = [(min(span.spread[i][0] for span in spans),
              max(span.spread[i][1] for span in spans))
             for i in range(n)]
    return _spread_text(spread)


IDENTITY_COL, KIND_COL, RANGE_COL, COUNT_COL, EXAMPLE_COL = range(5)
COLUMNS = ("Mod", "Kind", "Range", "Seen", "Example")


class ModAlbumModel(QAbstractTableModel):
    """Reine Anzeige einer bereits fertigen Liste — die Sammlung selbst
    bleibt dumm gegenüber Qt (§mod_collection.py)."""

    def __init__(self, records: list[ModRecord]) -> None:
        super().__init__()
        self._records = records
        # Steuert nur die RANGE_COL-Spalte, siehe ``combined_range_text``.
        # Getrennt vom Proxy-Filter gehalten, obwohl beide von denselben
        # Combo-Boxen gefuettert werden: Der Proxy entscheidet, welche
        # ZEILEN sichtbar sind, dieses Feld, was in einer sichtbaren Zeile
        # in EINER Spalte steht — zwei verschiedene Fragen.
        self._range_league: str | None = None
        self._range_rarities: RarityPredicate | None = None

    def record_at(self, row: int) -> ModRecord | None:
        return self._records[row] if 0 <= row < len(self._records) else None

    def set_range_filter(self, league: str | None,
                         rarities: RarityPredicate | None) -> None:
        self._range_league = league
        self._range_rarities = rarities
        if self._records:
            top = self.index(0, RANGE_COL)
            bottom = self.index(len(self._records) - 1, RANGE_COL)
            self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        record = self._records[index.row()]
        col = index.column()
        if col == IDENTITY_COL:
            return record.identity
        if col == KIND_COL:
            return kind_label(record.kind)
        if col == RANGE_COL:
            return combined_range_text(record, self._range_league, self._range_rarities)
        if col == COUNT_COL:
            return record.count
        if col == EXAMPLE_COL:
            return record.example
        return None


class ModAlbumProxy(QSortFilterProxyModel):
    """Textsuche über ``setFilterFixedString`` (läuft gegen die
    Mod-Spalte), plus Art, Liga und Rarität als unabhängige Filter —
    alle geltenden Bedingungen müssen gleichzeitig zutreffen, deshalb kein
    einfacher ``setFilterKeyColumn`` allein."""

    def __init__(self) -> None:
        super().__init__()
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(IDENTITY_COL)
        self._kind = ""
        self._league: str | None = None
        self._rarities: RarityPredicate | None = None

    def set_kind_filter(self, kind: str) -> None:
        # begin/endFilterChange statt invalidateFilter — Letzteres ist seit
        # Qt 6.10 deprecated (Warnung in jedem Testlauf, siehe item_table.py).
        self.beginFilterChange()
        self._kind = kind
        self.endFilterChange()

    def set_pot_filter(self, league: str | None,
                       rarities: RarityPredicate | None) -> None:
        """Liga und Rarität zusammen, weil sie in der Range-Spalte auch
        zusammen wirken (§combined_range_text) — eine Zeile ohne
        passenden Topf für die eine Achse hat für die andere ohnehin
        nichts zu zeigen."""
        self.beginFilterChange()
        self._league = league
        self._rarities = rarities
        self.endFilterChange()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        record = model.record_at(row)
        if record is None:
            return False
        if self._kind and record.kind != self._kind:
            return False
        if self._league is not None or self._rarities is not None:
            if not matching_spans(record, self._league, self._rarities):
                return False
        return super().filterAcceptsRow(row, parent)


class ModAlbumDialog(QDialog):
    def __init__(self, collection: ModCollection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mod Collection")
        self.resize(900, 560)

        records = sorted(collection.records(), key=lambda r: r.identity)
        self._model = ModAlbumModel(records)
        self._proxy = ModAlbumProxy()
        self._proxy.setSourceModel(self._model)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self._search.textChanged.connect(self._update_count_label)

        self._kind_combo = QComboBox()
        self._kind_combo.addItem("All kinds", "")
        seen_kinds = {record.kind for record in records}
        for kind in KIND_ORDER:
            if kind in seen_kinds:
                self._kind_combo.addItem(kind_label(kind), kind)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)

        # ``None`` ist der Sentinel für "keine Einschränkung" — nicht der
        # leere String, denn der ist ``LEGACY_LEAGUE`` selbst, eine echte
        # waehlbare Liga (siehe ``matching_spans``).
        self._league_combo = QComboBox()
        self._league_combo.addItem("All leagues", None)
        seen_leagues = sorted({league for record in records for league in record.leagues})
        for league in seen_leagues:
            self._league_combo.addItem(league_label(league), league)
        self._league_combo.currentIndexChanged.connect(self._on_pot_filter_changed)

        self._rarity_combo = QComboBox()
        self._rarity_combo.addItem("All rarities", "")
        seen_rarities = {rarity for record in records
                        for je_liga in record.spans.values() for rarity in je_liga}
        for label, rarity_ok in RARITY_GROUPS:
            if any(rarity_ok(rarity) for rarity in seen_rarities):
                self._rarity_combo.addItem(label, label)
        self._rarity_combo.currentIndexChanged.connect(self._on_pot_filter_changed)

        self._count_label = QLabel()

        top_row = QHBoxLayout()
        top_row.addWidget(self._search, stretch=1)
        top_row.addWidget(self._kind_combo)
        top_row.addWidget(self._league_combo)
        top_row.addWidget(self._rarity_combo)
        top_row.addWidget(self._count_label)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(IDENTITY_COL, Qt.SortOrder.AscendingOrder)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        # Feste Startbreiten fuer Mod/Kind/Range/Seen, der Rest geht an
        # Example. ``resizeColumnsToContents`` waere hier die falsche
        # Wahl: Die laengste Identitaet in Peters Bestand ist 381 Zeichen
        # lang, und danach richtet sich sonst die ganze Spalte.
        header.resizeSection(IDENTITY_COL, 260)
        header.resizeSection(KIND_COL, 70)
        header.resizeSection(RANGE_COL, 150)
        header.resizeSection(COUNT_COL, 50)
        header.setSectionResizeMode(EXAMPLE_COL, QHeaderView.ResizeMode.Stretch)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("Select a mod to see every rarity and league "
                                        "it has been seen on.")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._table)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(splitter, stretch=1)

        self._update_count_label()

    def _on_kind_changed(self) -> None:
        self._proxy.set_kind_filter(self._kind_combo.currentData() or "")
        self._update_count_label()

    def _on_pot_filter_changed(self) -> None:
        league = self._league_combo.currentData()
        rarities = RARITY_GROUPS_BY_NAME.get(self._rarity_combo.currentData() or "")
        self._proxy.set_pot_filter(league, rarities)
        self._model.set_range_filter(league, rarities)
        self._update_count_label()

    def _update_count_label(self) -> None:
        total = self._model.rowCount()
        shown = self._proxy.rowCount()
        self._count_label.setText(f"{shown} of {total}" if shown != total else str(total))

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self._detail.setPlainText("")
            return
        record = self._model.record_at(self._proxy.mapToSource(current).row())
        self._detail.setPlainText(format_record_detail(record) if record else "")
