"""Item-Tabelle: Model/View mit Sortierung und Live-Filter.

Aufgebaut aus QAbstractTableModel und QSortFilterProxyModel; Sortieren
und Filtern übernimmt damit Qt.

Icons werden asynchron nachgeladen: das Model meldet fehlende URLs über den
``icon_requester``-Callback (MainWindow → FetchIconJob) und bekommt die
fertigen Pixmaps via ``set_icon`` zurück. In Aggregat-Ansichten (liga-weite
Suche, "Alle Tabs laden") passiert das LAZY erst beim Painten der Zeile —
eifriges Anfordern würde die Worker-Queue mit zigtausend Icon-Jobs fluten.

Die Tab-Spalte trägt den Namen des Herkunfts-Tabs pro Item. Bei Auswahl
eines einzelnen Tabs ist sie redundant und wird vom MainWindow automatisch
ausgeblendet; in Aggregat-Ansichten ("Alle Tabs laden", Klick auf einen
Spezial-Tab-Elternknoten, liga-weite Suche) wird sie automatisch
eingeblendet — dort ordnet sie Items ihrem Fach zu ("Map (Tier 1)").

Die Position-Spalte ("#3 (4, 7)") zeigt die 1-basierte Position des
Herkunfts-Tabs INNERHALB DER AKTUELLEN LIGA-ANTWORT (MainWindow.
_tab_positions — nicht StashTab.index, siehe dort) plus die
Gitter-Koordinate des Items darin (API-Felder x/y) — der Name allein
unterscheidet gleichnamige Fächer nicht (Nutzer hat z. B. mehrere
"Heist"-Tabs). Anders als die Tab-Spalte nicht automatisch verwaltet:
normal toggle-/immer sichtbar, auch im Einzelfach nützlich (Koordinate
innerhalb des GERADE angezeigten Tabs).

Req.Lvl/Str/Dex/Int kommen aus dem requirements-Array der GGG-API — die
Daten waren dank ``extra="allow"`` längst im Cache, wurden nur nie gezeigt
(eine externe Quelle wie PoEDB ist dafür nicht nötig).

Die Base-Spalte zeigt ``item.baseType`` — anders als Name (kann bei
Uniques/Rares ein Fantasiename sein) immer die reine Item-Basis ("Sun
Plate", "Crimson Jewel"). "Unidentifiziert" wird bewusst NICHT hier,
sondern nur im Item-Detail-Panel markiert (``item_detail.py``) — in der
Tabelle wäre eine eigene Spalte/Markierung dafür Platzverschwendung, da
unidentifizierte Items selten sind.

Die Mods-Spalte zeigt die explicitMods (v. a. Map-Modifikatoren);
der Live-Filter durchsucht sie mit. Zusätzlich kann jede Spalte einen
eigenen Filter-Ausdruck tragen (">=20", "<45", "=Text", Teilstring) —
gesetzt über das Header-Rechtsklick-Menü, markiert mit 🔍 im Header.

Das Suchfeld folgt der Spiel-eigenen Truhensuche (Peter, 2026-08-13, mit
deren Hilfe-Fenster als Vorlage): Leerzeichen trennen mehrere Begriffe,
die ALLE zutreffen müssen; Anführungszeichen fassen einen mehrwortigen
Begriff zusammen. Jeder Begriff wird standardmäßig als regulärer Ausdruck
ausgewertet (Umschalter ".*" in der Toolbar), sodass auf poe.re
zusammengeklickte Muster unverändert funktionieren — dafür steht auch
``Item.socket_string`` ("R-R-G", Gruppen durch Leerzeichen) mit im
Suchindex, ebenso die Namen der Sockel-Gems. Ein unfertiges Muster fällt
für seinen Begriff still auf die Teilstring-Suche zurück, statt die Liste
zu leeren. Siehe ``SearchQuery``.

Acht Typ-Checkboxen (MainWindow, neben dem Liga-Feld) filtern zusätzlich
nach frameType — und-verknüpft mit allem anderen: die vier PoE-Rarities
(Normal/Magic/Rare/Unique), dazu Gem/Currency/Divination Card, und eine
letzte "Sonstige"-Checkbox (Pink) für alles ohne eigene Kategorie (Quest,
Prophecy, Relic, unbekannte frameTypes) — siehe ``_type_key``.

Die Value-Spalte zeigt den poe.ninja-Chaos-Wert × Stack-Größe, sobald
``set_price_index()`` einen ``PriceIndex`` liefert (MainWindow lädt ihn
asynchron pro Liga, siehe api/ninja.py + services/price_cache.py). Leer
heißt unbekannter Preis, nicht wertlos — nie 0. Werte unter einem Chaos
werden dezent Richtung Hintergrund abgeblendet ("wahrscheinlich Schrott").
"""

from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import (QAbstractTableModel, QModelIndex,
                            QSortFilterProxyModel, Qt)
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QPalette,
                           QPixmap)

from poe_view.api.models import (Item, gem_level, gem_quality, req_attribute,
                                 req_level)
from poe_view.api.ninja import PriceIndex
from poe_view.ui.theme import (OTHER_TYPE, RARITY_COLORS, ROW_CHANGED_COLOR,
                               ROW_GEM_LEVELED_COLOR, blend, dimmed_text)

# frameTypes mit eigener Checkbox (MainWindow.TYPE_FILTER_ENTRIES) — alles
# andere läuft für den Typ-Filter unter OTHER_TYPE ("Sonstige").
_EXPLICIT_TYPES = frozenset({0, 1, 2, 3, 4, 5, 6})


def _type_key(frame_type: int) -> int:
    return frame_type if frame_type in _EXPLICIT_TYPES else OTHER_TYPE

COLUMNS = ("Icon", "Tab", "Position", "Name", "Base", "Type", "Level", "Qual.", "Stack", "iLvl",
           "Req.Lvl", "Str", "Dex", "Int", "Mods", "Value")
ICON_COL = 0
TAB_COL = 1
POSITION_COL = 2       # Tab-Nr. + Gitter-Koordinate — unterscheidet gleichnamige Fächer
_NAME_COL = 3
BASE_COL = 4           # item.baseType — anders als Name (kann der Unique-/Rare-Name sein)
                       # immer die reine Basis ("Sun Plate", "Crimson Jewel")
_NUMERIC_FROM_COL = 6  # Level, Qual., Stack, iLvl, Req.Lvl, Str, Dex, Int
MODS_COL = 14          # Mods (v. a. Maps) — linksbündig, nicht numerisch
VALUE_COL = 15         # poe.ninja-Chaos-Wert × Stack — eigene Spalte NACH Mods,
                       # damit alle bestehenden Spalten-Indizes unverändert bleiben
# Spalten vor dem vorgerechneten _rows-Tupel (Icon, Tab, Position) — Offset
# für den Zugriff _rows[row][col - _ROWS_OFFSET] in display_text().
_ROWS_OFFSET = 3

# Über den Settings-Dialog konfigurierbar (Sichtbarkeit + Reihenfolge,
# Peter 2026-08-01) — alle Spalten außer "Tab", die MainWindow abhängig
# von Einzelfach- vs. Aggregat-Ansicht automatisch ein-/ausblendet
# (siehe Modul-Docstring) und die deshalb kein Nutzer-Konfigurationsziel
# ist.
CONFIGURABLE_COLUMNS = tuple(name for name in COLUMNS if name != "Tab")

# Unterhalb dieser Chaos-Schwelle wird die Value-Zelle dezent Richtung
# Hintergrund abgeblendet ("wahrscheinlich Schrott") — der von PoE-Spielern
# gebräuchliche Richtwert "ist es mindestens einen Chaos wert" (ToDo.md:
# "Wert eines Items schätzen? Schrott-Items finden").
_JUNK_THRESHOLD_CHAOS = 1.0


def format_chaos_value(chaos: float, price_index: PriceIndex | None) -> str:
    """"Zahl + Einheit": Chaos für kleine Beträge, sobald der Gegenwert
    mindestens einen Divine Orb erreicht in Divine — vermeidet fünf- bis
    sechsstellige Chaos-Zahlen bei teuren Items. Eigene Funktion (nicht nur
    Methode), damit MainWindow dieselbe Formatierung für die
    Gesamtwert-Anzeige in der Statuszeile wiederverwenden kann."""
    divine_rate = price_index.divine_rate if price_index else None
    if divine_rate and chaos >= divine_rate:
        divine = chaos / divine_rate
        return f"{divine:,.0f}div" if divine >= 10 else f"{divine:.1f}div"
    return f"{chaos:,.0f}c" if chaos >= 10 else f"{chaos:.1f}c"

# Sortierung/Vergleich über echte Zahlen statt Anzeigetext — sonst sortiert
# "113" vor "56" (Stringvergleich). Der Proxy nutzt diese Rolle als sortRole.
NUMERIC_SORT_ROLE = Qt.ItemDataRole.UserRole

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _first_number(text: str) -> float | None:
    """Erste Zahl im Anzeigetext ("+20%" → 20.0, "–" → None)."""
    m = _NUM_RE.search(text)
    return float(m.group().replace(",", ".")) if m else None


# Feld-Suchen aus der Spiel-eigenen Truhensuche ("Search for item level by
# typing ilvl:X", "Search for map tier by typing tier:X"). Peter,
# 2026-08-13: "Wir haben das zwar schon über die Spalten gelöst, aber wenn
# jemand das genauso sucht, STRG+F und dann ilvl:84, dann freut man sich
# wenn es funktioniert."
#
# **Exakt, nicht "mindestens"** — von Peter bestätigt, nicht geraten. Die
# Spalten-Filter (">=84") bleiben der Weg für Bereiche und können mehr;
# das hier ist die Fingergewohnheit aus dem Spiel.
#
# Umgesetzt als Marke IM Suchindex statt als Sonderfall im Vergleich: Das
# Item bringt "ilvl:84" als eigenes Wort mit, und der Suchbegriff wird
# dazu passend auf Wortgrenzen festgenagelt. Dadurch funktioniert es in
# BEIDEN Suchpfaden ohne eine Zeile Extralogik — und "ilvl:8" findet
# nicht versehentlich alles von 80 bis 89.
_SEARCH_FIELDS = ("ilvl", "tier")

# Woher die Map-Tier kommt. **Gemessen, nicht angenommen:** Über alle
# 59.042 Items in Peters Bestand trägt KEIN EINZIGES eine Property namens
# "Map Tier" — 13.417 tragen die Tier stattdessen im ``typeLine``, als
# "Map (Tier 6)". Die erste Fassung dieser Funktion las die Property und
# fand deshalb auf echten Daten nichts; aufgefallen ist das nur, weil die
# Gegenprobe am echten Cache lief. Gegen die eigenen Demo-Daten, in denen
# ich die Property selbst erfunden hatte, sah alles richtig aus.
_TIER_IN_NAME_RE = re.compile(r"\(tier (\d+)\)", re.IGNORECASE)


def _field_tokens(item: Item) -> str:
    """"ilvl:84 tier:6" — die durchsuchbaren Marken eines Items."""
    tokens = []
    if item.ilvl:
        tokens.append(f"ilvl:{item.ilvl}")
    tier = _TIER_IN_NAME_RE.search(item.typeLine or "")
    if tier:
        tokens.append(f"tier:{tier.group(1)}")
    return " ".join(tokens)


_FIELD_TERM_RE = re.compile(rf"^({'|'.join(_SEARCH_FIELDS)}):(\d+)$")


def _field_term_pattern(term: str) -> re.Pattern | None:
    """``ilvl:84`` → ein auf Wortgrenzen festgenageltes Muster, sonst
    ``None``. Nur Ziffern gelten als Wert: ``ilvl:>=84`` bleibt damit ein
    gewöhnlicher Begriff, statt stillschweigend etwas anderes zu tun, als
    dort steht."""
    m = _FIELD_TERM_RE.match(term)
    return re.compile(rf"\b{m.group(1)}:{m.group(2)}\b") if m else None


class ItemTableModel(QAbstractTableModel):
    def __init__(self, icon_requester: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self._items: list[Item] = []
        self._sources: list[str] = []         # Tab-Name pro Item (parallel zu _items)
        self._tab_indices: list[int | None] = []  # Tab-Position pro Item (Positions-Spalte)
        self._stash_ids: list[str | None] = []  # Herkunfts-Tab-ID (Baum-Hervorhebung)
        self._rows: list[tuple] = []          # vorgerechnete Anzeigewerte
        self._search_haystacks: list[str] = []  # vorgerechnet, bereits klein geschrieben
        self._pixmaps: dict[str, QPixmap] = {}
        self._requested: set[str] = set()
        self._icon_requester = icon_requester
        self._price_index: PriceIndex | None = None
        self._changed_ids: frozenset[str] = frozenset()
        self._removed_ids: frozenset[str] = frozenset()
        self._leveled_ids: frozenset[str] = frozenset()

    # --- Daten setzen -------------------------------------------------- #

    def set_items(self, items: list[Item], sources: list[str] | None = None,
                  tab_indices: list[int | None] | None = None,
                  stash_ids: list[str | None] | None = None,
                  request_icons: bool = True,
                  changed_ids: frozenset[str] = frozenset(),
                  removed_ids: frozenset[str] = frozenset(),
                  leveled_ids: frozenset[str] = frozenset()) -> None:
        """``sources[i]`` ist der Tab-Name von ``items[i]``. Ohne Angabe leer.
        ``tab_indices[i]`` ist die 1-basierte Position des Herkunfts-Tabs in
        der aktuellen API-Antwort (``MainWindow._tab_positions``, bewusst
        nicht ``StashTab.index``). Sie bildet die Grundlage der
        Positions-Spalte und unterscheidet gleichnamige Fächer, etwa
        mehrere Heist-Tabs. Ohne Angabe bleibt sie unbekannt.

        ``stash_ids[i]`` ist die Tab-ID von ``items[i]`` und ermöglicht es,
        bei Zeilenauswahl das richtige Fach im Stash-Baum hervorzuheben.
        Das ist vor allem in Aggregat- und Suchansichten mit mehreren
        Quell-Tabs relevant.

        ``request_icons=False`` für große Aggregate (liga-weite Suche,
        "Alle Tabs laden"): Icons werden dann lazy in ``data()`` angefordert,
        sobald Qt die Zeile tatsächlich malt — nur Sichtbares kostet Jobs.

        ``changed_ids``/``removed_ids`` (``item.id``, Peter 2026-08-01: "die
        Zeilen hervorgehoben (Türkis), welche sich geändert haben") kommen
        vom Charakter-Refresh-Diff (MainWindow._show_character_items) — hier
        nur zum Rendern durchgereicht, die Diff-Logik selbst kennt das Model
        nicht. ``removed_ids`` referenziert Items, die zwar noch in
        ``items`` stehen (damit sie sichtbar bleiben), aber im aktuellen
        Inventar nicht mehr existieren — Grau/Durchgestrichen statt Löschen,
        damit man sieht, was gerade verschwunden ist.

        ``leveled_ids`` ist eine Teilmenge von ``changed_ids`` und hebt
        den einen Fall heraus, den Peter auf einen Blick erkennen wollte
        (2026-08-11): In dem Item ist ein Sockel-Gem aufgestiegen. Grün
        statt Türkis, sonst identisch behandelt."""
        self.beginResetModel()
        self._items = items
        self._sources = sources if sources is not None else [""] * len(items)
        self._tab_indices = tab_indices if tab_indices is not None else [None] * len(items)
        self._stash_ids = stash_ids if stash_ids is not None else [None] * len(items)
        self._changed_ids = changed_ids
        self._removed_ids = removed_ids
        self._leveled_ids = leveled_ids
        self._rows = [self._precompute(item) for item in items]
        # Einmal pro Ladevorgang statt bei JEDEM Tastendruck neu zusammengebaut
        # (filterAcceptsRow lief vorher pro Zeile UND pro Tastendruck über
        # mehrere f-Strings/joins/lower() — bei liga-weiten Aggregaten mit
        # zehntausenden Items spürbar langsam, Peter 2026-07-28: "All Tabs
        # liefert mir 19704 Items").
        self._search_haystacks = [self._build_haystack(item, source)
                                  for item, source in zip(items, self._sources)]
        self.endResetModel()
        if request_icons and self._icon_requester:
            for item in items:
                self._request_icon(item)

    def _request_icon(self, item: Item) -> None:
        if self._icon_requester and item.icon \
                and item.icon not in self._pixmaps and item.icon not in self._requested:
            self._requested.add(item.icon)
            self._icon_requester(item.icon)

    @staticmethod
    def _precompute(item: Item) -> tuple:
        return (item.display_name, item.baseType or "–", item.rarity, gem_level(item) or "–",
                gem_quality(item) or "–",
                str(item.stackSize) if item.stackSize else "–",
                str(item.ilvl) if item.ilvl else "–",
                req_level(item) or "–",
                req_attribute(item, "Str") or "–",
                req_attribute(item, "Dex") or "–",
                req_attribute(item, "Int") or "–",
                " · ".join(item.explicit_mods))  # v. a. Map-Modifikatoren

    def content_signature(self) -> int:
        """Kennzahl über den ANGEZEIGTEN Inhalt — gleiche Zahl bedeutet
        gleiche Tabelle (MainWindow._note_view_updated, "unchanged for X").

        Gebildet aus den vorgerechneten Anzeigewerten und den Tab-Namen,
        nicht aus den Item-Objekten: Verglichen werden soll, was der
        Spieler sieht. Ein Feld, das in keiner Spalte auftaucht, soll die
        Anzeige nicht als "geändert" gelten lassen — und die Werte liegen
        aus ``set_items`` ohnehin schon fertig da, der Vergleich kostet
        also nichts obendrauf.

        Die Zahl ist nur INNERHALB eines Programmlaufs vergleichbar
        (Pythons String-Hashing ist pro Prozess zufällig). Sie wird
        nirgends gespeichert, insofern unerheblich."""
        return hash((tuple(self._rows), tuple(self._sources)))

    @staticmethod
    def _build_haystack(item: Item, source: str) -> str:
        """Durchsuchter Text für die globale Suche, bereits klein geschrieben.

        Properties (z. B. "Item Quantity: +23%") sind keine explicitMods —
        ohne sie fände die Suche Maps mit Quantity/Rarity/Pack Size/Drop
        Chance nie ("nach Quantity gesucht, nur Chisel gefunden" — die
        Chisel-Beschreibung nennt "Item Quantity" im Mod-Text, die Maps
        selbst tragen den Wert nur als Property).

        Die Namen der SOCKEL-GEMS zählen mit, wie im Spiel ("The Gems and
        Microtransactions of those items are also searched"). Betrifft in
        Peters Bestand nur 125 Items — aber das sind die angelegten, und
        "wo steckt eigentlich meine Determination?" ist genau die Frage,
        für die man sonst jedes Teil einzeln anklickt."""
        prop_text = " ".join(p.display_text for p in item.properties)
        gem_names = " ".join(
            f"{gem.get('typeLine', '')} {gem.get('baseType', '')}"
            for gem in (getattr(item, "socketedItems", None) or [])
            if isinstance(gem, dict))
        return (f"{item.display_name} {item.typeLine} {item.baseType} "
               f"{item.rarity} {source} {item.socket_string} "
               f"{' '.join(item.explicit_mods)} {' '.join(item.implicit_mods)} "
               f"{prop_text} {gem_names} {_field_tokens(item)}").lower()

    def set_price_index(self, index: PriceIndex | None) -> None:
        """Preise treffen meist ASYNCHRON nach ``set_items()`` ein (poe.ninja
        lädt im Hintergrund, §services/price_cache.py) — deshalb kein Reset,
        nur ein ``dataChanged`` für die Value-Spalte über alle Zeilen."""
        self._price_index = index
        if self._items:
            top_left = self.index(0, VALUE_COL)
            bottom_right = self.index(len(self._items) - 1, VALUE_COL)
            self.dataChanged.emit(top_left, bottom_right,
                                  [Qt.ItemDataRole.DisplayRole, NUMERIC_SORT_ROLE])

    def value_at(self, row: int) -> float | None:
        """Chaos-Gesamtwert EINER Zeile (Einzelpreis × Stack-Größe), ``None``
        wenn kein Preis-Index gesetzt ist oder poe.ninja für dieses Item
        keinen Preis kennt (z. B. ein Rare ohne Namens-Treffer)."""
        if self._price_index is None or not (0 <= row < len(self._items)):
            return None
        item = self._items[row]
        unit_price = self._price_index.price_for(item)
        return None if unit_price is None else unit_price * (item.stackSize or 1)

    def item_at(self, row: int) -> Item | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def source_at(self, row: int) -> str:
        return self._sources[row] if 0 <= row < len(self._sources) else ""

    def search_haystack_at(self, row: int) -> str:
        return self._search_haystacks[row] if 0 <= row < len(self._search_haystacks) else ""

    def distinct_values(self, col: int) -> list[str]:
        """Sortierte, eindeutige Anzeigewerte einer Spalte über ALLE
        geladenen Zeilen (nicht nur die gerade sichtbaren/gefilterten) —
        Grundlage der Autovervollständigung im Spalten-Filter
        (Header-Rechtsklick, Peter 2026-08-02: "eine Art
        Autovervollständigen mit Combobox über die Items in der Spalte").
        Der Platzhalter "–" (kein Wert) taugt nicht als Filter-Ziel und
        wird ausgeklammert."""
        values = {self.display_text(row, col) for row in range(len(self._items))}
        values.discard("–")
        values.discard("")
        return sorted(values)

    def stash_id_at(self, row: int) -> str | None:
        return self._stash_ids[row] if 0 <= row < len(self._stash_ids) else None

    def set_icon(self, url: str, pixmap: QPixmap) -> None:
        self._pixmaps[url] = pixmap
        for row, item in enumerate(self._items):
            if item.icon == url:
                idx = self.index(row, ICON_COL)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def pixmap_for(self, item: Item) -> QPixmap | None:
        return self._pixmaps.get(item.icon)

    # --- Qt-Model-API --------------------------------------------------- #

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return "" if section == ICON_COL else COLUMNS[section]
        return None

    def _position_text(self, row: int) -> str:
        """Tab-Nr. (bereits 1-basiert von MainWindow._tab_positions
        übergeben — Position in der aktuellen API-Antwort, nicht
        StashTab.index) + Gitter-Koordinate des Items — unterscheidet
        gleichnamige Fächer (z. B. mehrere "Heist"), die Tab-Spalte allein
        zeigt ja nur den (u. U. mehrdeutigen) Namen."""
        tab_index = self._tab_indices[row] if row < len(self._tab_indices) else None
        tab_part = f"#{tab_index}" if tab_index is not None else "–"
        item = self._items[row]
        if item.x is not None and item.y is not None:
            return f"{tab_part} ({item.x}, {item.y})"
        return tab_part

    def _position_sort_key(self, row: int) -> tuple[float, float, float]:
        """Numerischer Sortierschlüssel für die Position-Spalte: Tab-Nr.
        zuerst (unterscheidet Fächer), dann x, dann y — sonst würde "#10"
        alphabetisch vor "#2" einsortieren. Unbekannte
        Werte wie bei den übrigen Zahlenspalten als "-inf" (§ NUMERIC_SORT_ROLE)."""
        tab_index = self._tab_indices[row] if row < len(self._tab_indices) else None
        item = self._items[row]
        return (
            float(tab_index) if tab_index is not None else float("-inf"),
            float(item.x) if item.x is not None else float("-inf"),
            float(item.y) if item.y is not None else float("-inf"),
        )

    def display_text(self, row: int, col: int) -> str:
        """Anzeigetext einer Zelle — auch Basis der Spalten-Filter im Proxy."""
        if col == TAB_COL:
            return self._sources[row] or "–"
        if col == POSITION_COL:
            return self._position_text(row)
        if col == VALUE_COL:
            value = self.value_at(row)
            return format_chaos_value(value, self._price_index) if value is not None else ""
        if col > POSITION_COL:
            return self._rows[row][col - _ROWS_OFFSET]
        return ""

    def data(self, index: QModelIndex, role):
        item = self._items[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole and col >= TAB_COL:
            return self.display_text(index.row(), col)
        if role == NUMERIC_SORT_ROLE:
            # Numerische Spalten als Zahl sortieren ("–" ganz nach unten),
            # alle anderen weiterhin als (kleingeschriebener) Text.
            if col == POSITION_COL:
                return self._position_sort_key(index.row())
            if col == VALUE_COL:
                value = self.value_at(index.row())
                return value if value is not None else float("-inf")
            text = self.display_text(index.row(), col)
            if _NUMERIC_FROM_COL <= col < MODS_COL:
                number = _first_number(text)
                return number if number is not None else float("-inf")
            return text.lower()
        if role == Qt.ItemDataRole.ToolTipRole and col == MODS_COL:
            # Mods können lang werden — Tooltip zeigt sie zeilenweise komplett.
            return "\n".join(item.explicit_mods) or None
        if role == Qt.ItemDataRole.DecorationRole and col == ICON_COL:
            pm = self._pixmaps.get(item.icon)
            if pm:
                return pm.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            self._request_icon(item)  # lazy: erst wenn die Zeile sichtbar wird
        is_removed = bool(item.id) and item.id in self._removed_ids
        if role == Qt.ItemDataRole.ForegroundRole and is_removed:
            # Aus dem Inventar verschwunden (Charakter-Refresh-Diff) — grau
            # statt der sonstigen Rarity-/Value-Färbung, gilt für die ganze
            # Zeile, nicht nur einzelne Spalten.
            return QBrush(dimmed_text(QGuiApplication.palette()))
        if role == Qt.ItemDataRole.ForegroundRole and col == _NAME_COL:
            colour = RARITY_COLORS.get(item.frameType)
            if colour:
                return QBrush(QColor(colour))
        if role == Qt.ItemDataRole.ForegroundRole and col == VALUE_COL:
            value = self.value_at(index.row())
            if value is not None and value < _JUNK_THRESHOLD_CHAOS:
                return QBrush(dimmed_text(QGuiApplication.palette()))
        if role == Qt.ItemDataRole.FontRole and is_removed:
            font = QFont()
            font.setStrikeOut(True)
            return font
        if role == Qt.ItemDataRole.BackgroundRole and bool(item.id) and item.id in self._changed_ids:
            # Seit dem letzten Refresh geändert oder neu hinzugekommen
            # (Charakter-Refresh-Diff) — Türkis-Tönung des Zeilenhintergrunds,
            # zur Basisfarbe des Themes gemischt (hell wie dunkel lesbar).
            # Ist in dem Item ein Sockel-Gem aufgestiegen, gewinnt Grün:
            # ``leveled_ids`` ist die speziellere Aussage über dieselbe
            # Zeile, "geändert" stimmt daneben ohnehin auch.
            colour = (ROW_GEM_LEVELED_COLOR if item.id in self._leveled_ids
                      else ROW_CHANGED_COLOR)
            palette = QGuiApplication.palette()
            return QBrush(blend(QColor(colour), palette.color(QPalette.ColorRole.Base), 0.55))
        if role == Qt.ItemDataRole.TextAlignmentRole and (
                (_NUMERIC_FROM_COL <= col < MODS_COL) or col == VALUE_COL):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class SearchQuery:
    """Eine zerlegte Suchanfrage: mehrere Begriffe, UND-verknüpft.

    Peter, 2026-08-13, mit dem Hilfe-Fenster der Spiel-eigenen Suche als
    Vorlage: "Bin mit der Suche bei uns noch nicht zu 100% zufrieden."
    Bis dahin war der Suchtext EIN Muster — "life resistance" fand nur
    Items, bei denen die beiden Wörter buchstäblich nebeneinander stehen.
    Das kommt in Mod-Texten praktisch nie vor: 38.128 der 59.042 Items in
    Peters Bestand (64,6 %) tragen zwei oder mehr Mod-Zeilen, und genau
    dort will man zwei Begriffe kombinieren.

    Deshalb dieselbe Regel wie im Spiel ("Type multiple keywords by
    separating them with a space"): Leerzeichen trennen Begriffe, ALLE
    müssen zutreffen, und Anführungszeichen fassen einen mehrwortigen
    Begriff wieder zusammen ("two handed mace").

    Der Regex-Umschalter wirkt je Begriff, nicht auf die ganze Zeile —
    ``r-r-g|r-g-r`` bleibt damit ein Begriff und funktioniert
    unverändert, weil poe.re-Muster keine Leerzeichen enthalten. Ein
    Muster MIT Leerzeichen gehört ab jetzt in Anführungszeichen.
    """

    def __init__(self, terms: list[re.Pattern | str]) -> None:
        self._terms = terms

    def __bool__(self) -> bool:
        return bool(self._terms)

    def matches(self, haystack: str) -> bool:
        """``haystack`` ist bereits klein geschrieben
        (``ItemTableModel._build_haystack``)."""
        return all(term.search(haystack) if isinstance(term, re.Pattern)
                   else term in haystack
                   for term in self._terms)


def split_search_terms(text: str) -> list[str]:
    """Zerlegt den Suchtext in Begriffe. Anführungszeichen halten
    zusammen, was zusammengehört; ein nicht geschlossenes
    Anführungszeichen (beim Tippen der Normalfall) gilt bis zum Ende,
    statt die Suche bis zum zweiten Zeichen unbrauchbar zu machen."""
    terms: list[str] = []
    # Das schliessende Anfuehrungszeichen ist OPTIONAL — beim Tippen ist
    # es zwangslaeufig kurz offen, und dann soll der Rest der Zeile der
    # Begriff sein statt in Einzelwoerter zu zerfallen.
    for quoted, bare in re.findall(r'"([^"]*)"?|(\S+)', text):
        term = quoted if quoted else bare
        if term:
            terms.append(term)
    return terms


def compile_search(text: str, regex_enabled: bool) -> SearchQuery:
    """Suchtext in eine ``SearchQuery`` übersetzen. Gemeinsam genutzt von
    ``ItemFilterProxy`` und der On-Demand-Suche über große Ligen
    (MainWindow._run_large_search).

    Ein unfertiges Muster (beim Tippen praktisch immer kurz der Fall,
    etwa nach einer offenen Klammer) fällt für DIESEN Begriff still auf
    die Teilstring-Suche zurück, statt die ganze Liste zu leeren."""
    terms: list[re.Pattern | str] = []
    for term in split_search_terms(text.lower()):
        feld = _field_term_pattern(term)
        if feld is not None:
            # Unabhängig vom Regex-Umschalter: "ilvl:84" ist in beiden
            # Modi dasselbe gemeint, und als Teilstring gelesen träfe es
            # auch ilvl:840.
            terms.append(feld)
            continue
        if regex_enabled:
            try:
                terms.append(re.compile(term))
                continue
            except re.error:
                pass
        terms.append(term)
    return SearchQuery(terms)


# Vergleichsoperator am Anfang eines Spalten-Filter-Ausdrucks
_OP_RE = re.compile(r"^\s*(<=|>=|!=|<>|<|>|=)\s*(.+)$")


def _expression_matches(expr: str, cell_text: str) -> bool:
    """Excel-artige Mini-Ausdrücke: ">=20", "<45", "=Beach Map", sonst
    Teilstring. Numerisch wird verglichen, sobald Operand und Zelle eine
    Zahl hergeben ("+20%" zählt als 20) — sonst Textvergleich; Zellen ohne
    Zahl ("–") fallen bei <,>,<=,>= bewusst raus (wie in Excel)."""
    m = _OP_RE.match(expr)
    if not m:
        return expr.lower() in cell_text.lower()
    op, operand = m.group(1), m.group(2).strip()
    operand_num = _first_number(operand)
    cell_num = _first_number(cell_text)
    if op in ("=", "!=", "<>"):
        if operand_num is not None and cell_num is not None:
            equal = cell_num == operand_num
        else:
            equal = cell_text.strip().lower() == operand.lower()
        return equal if op == "=" else not equal
    if operand_num is None or cell_num is None:
        return False
    return {"<": cell_num < operand_num, "<=": cell_num <= operand_num,
            ">": cell_num > operand_num, ">=": cell_num >= operand_num}[op]


class ItemFilterProxy(QSortFilterProxyModel):
    """Filtert lokal über Name + Typ + Tab + Mods + Properties — kostet
    bewusst keine API-Calls. Zusätzlich je Spalte ein optionaler
    Filter-Ausdruck (Header-Rechtsklick), und-verknüpft mit dem globalen
    Suchfeld. "*" im Suchfeld zeigt bewusst alles (Komplett-Export)."""

    def __init__(self) -> None:
        super().__init__()
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortRole(NUMERIC_SORT_ROLE)
        self._column_filters: dict[int, str] = {}
        self._search_text = ""
        self._search_text_lower = ""
        self._regex_enabled = True
        self._search_query = SearchQuery([])
        self._hidden_types: set[int] = set()  # _type_key(frameType), per Checkbox abgewählt

    def set_regex_enabled(self, enabled: bool) -> None:
        self.beginFilterChange()
        self._regex_enabled = enabled
        self._compile_search()
        self.endFilterChange()

    def _compile_search(self) -> None:
        """Übersetzt den Suchtext in eine ``SearchQuery`` (mehrere
        Begriffe, UND-verknüpft — siehe dort)."""
        self._search_query = compile_search(self._search_text_lower, self._regex_enabled)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802 (Qt-API)
        """Eigene Tie-Break-Regel für gleiche Sortierwerte.

        Ohne sie ist der Vergleich bei Gleichstand (mehrere Items ohne
        iLvl, alle mit "-inf", oder mehrere gleichnamige Currency-Stacks)
        aus Sicht des Sortier-Algorithmus mit jeder beliebigen Position
        vereinbar. Qt sortiert bei einer Filteränderung nicht immer komplett
        neu, sondern fügt wieder sichtbare Zeilen inkrementell ein, wobei
        gleiche Werte an der aktuellen Einfügestelle (meist ans Ende der
        Gleichstand-Gruppe) landen statt an ihrer ursprünglichen Position.
        Die Original-Zeilennummer im Quellmodell als zweites Kriterium macht
        den Vergleich zu einer echten Totalordnung — es gibt dann für jedes
        Element nur noch EINE korrekte Position, unabhängig davon, in
        welcher Reihenfolge/wie oft Qt intern neu einsortiert."""
        source = self.sourceModel()
        role = self.sortRole()
        left_value = source.data(left, role)
        right_value = source.data(right, role)
        if left_value == right_value:
            return left.row() < right.row()
        return left_value < right_value

    # --- Typ-Checkboxen --------------------------------- #

    def set_type_visible(self, type_key: int, visible: bool) -> None:
        """``type_key`` ist ein frameType (0–6) oder ``theme.OTHER_TYPE``
        (Sammel-Kategorie "Sonstige")."""
        self.beginFilterChange()
        if visible:
            self._hidden_types.discard(type_key)
        else:
            self._hidden_types.add(type_key)
        self.endFilterChange()

    def setFilterFixedString(self, text: str) -> None:  # noqa: N802 (Qt-API)
        """Rohtext selbst merken statt über das (regex-escapte!) Pattern von
        Qt zurückzulesen — sonst würde "*" als "\\*" ankommen und nie als
        Wildcard erkannt werden. Klein geschrieben einmal HIER vorrechnen,
        nicht in filterAcceptsRow — sonst liefe .lower() auf dem Suchtext
        pro Zeile statt einmal pro Tastendruck."""
        self._search_text = text or ""
        self._search_text_lower = self._search_text.strip().lower()
        self._compile_search()
        super().setFilterFixedString(text)

    # --- Spalten-Filter -------------------------------------------------- #

    def set_column_filter(self, col: int, expr: str) -> None:
        expr = (expr or "").strip()
        # begin/endFilterChange statt invalidateFilter — Letzteres ist seit
        # Qt 6.10 deprecated (Warnung in jedem Testlauf).
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

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        value = super().headerData(section, orientation, role)
        if (role == Qt.ItemDataRole.DisplayRole
                and orientation == Qt.Orientation.Horizontal
                and section in self._column_filters and value):
            return f"{value} 🔍"  # aktiver Spalten-Filter sichtbar im Header
        return value

    # --- Zeilen-Filter ---------------------------------------------------- #

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        model: ItemTableModel = self.sourceModel()
        item = model.item_at(row)
        if item is None:
            return True
        if _type_key(item.frameType) in self._hidden_types:
            return False
        for col, expr in self._column_filters.items():
            if not _expression_matches(expr, model.display_text(row, col)):
                return False
        text = self._search_text.strip()
        if not text:
            return True
        if text == "*":
            # Wildcard: gesamten (bereits geladenen) Inhalt zeigen — z. B. um
            # eine komplette Truhe/Liga in einem Rutsch als CSV zu exportieren.
            return True
        # Haystack ist bereits beim Laden vorgerechnet und klein geschrieben
        # (ItemTableModel._build_haystack) — hier nur noch ein billiger
        # Test, kein erneutes Zusammenbauen pro Zeile/Tastendruck.
        return self._search_query.matches(model.search_haystack_at(row))
