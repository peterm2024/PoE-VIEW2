"""Stash-Baum (docs/ARCHITEKTUR.md §5).

Die Stash-Tabs sind direkt die Top-Level-Einträge des Baums; ein
umschließender Wurzelknoten würde nur eine Ebene kosten. Die
Charakterliste liegt separat in ``character_list.py``.

Der Baum hat vier Spalten:

* **Name** mit der Tab-Farbe als kleinem Farbquadrat davor. Die Farbe
  (``metadata.colour``, Hex ohne '#') dient bewusst nicht als Textfarbe,
  da einige API-Farben auf dunklem Grund unlesbar wären. Die Spalte ist
  per Maus verbreiterbar; dafür ist ``Interactive`` nötig, denn
  ``Stretch``-Spalten lassen sich in Qt nicht manuell verbreitern.
* **#** mit der Item-Anzahl.
* **Status** mit genau einem von zwei sich ausschließenden Zuständen:
  "⬇" als reiner Text, solange nie geladen wurde, sonst ein
  Refresh-Button, dessen Beschriftung das Alter der Daten trägt. Heute
  geladene Fächer erscheinen mit exakter Uhrzeit ("⟳ 14:32:46"), ältere
  mit Tagesangabe ("⟳ vor 3d"). Ist GGG nicht erreichbar
  (``set_offline``), wird aus dem ⟳ ein "📴"; die Daten stammen dann
  sicher aus dem Cache.
* **Pos.** mit der 1-basierten Position des Fachs in der echten
  Truhen-Reihenfolge, wie ``MainWindow._tab_positions()`` sie aus der
  API-Antwort ableitet (dieselbe Quelle, die auch den Stash-Modus-Rundlauf
  antreibt, §_pick_stash_mode_candidate in main_window.py). Peter fehlte
  ein Zeilenheader zum "Durchzählen der echten Truhenfächer" — Qt kennt
  das nur bei Tabellen, nicht bei Bäumen, daher diese Spalte als
  Äquivalent. Nur echte Fächer bekommen eine Zahl; Ordner- und
  Gruppenknoten (kein eigener Truhenplatz) bleiben leer.

Die Namensspalte geladener Fächer wird zusätzlich nach Datenalter
abgeblendet (aktuell < 1h in normaler Textfarbe, < 3h leicht, älter
deutlicher Richtung Hintergrundfarbe gemischt — ``_apply_age_color``),
damit veraltete Fächer im Baum sofort auffallen. Nie geladene Fächer und
reine Ordner-/Gruppenknoten bleiben unangetastet. ``refresh_age_colors()``
wird von ``MainWindow`` im ohnehin laufenden Sekunden-Tick aufgerufen,
damit das Alter auch ohne neue Daten weiterwandert.

Das zuletzt per ``mark_loaded()`` aktualisierte Fach bekommt statt der
normalen Alters-Farbe Türkis (``_mark_just_updated``) — so ist bei
automatischen Sweeps (Refresh-Modus Single/Stash) sofort sichtbar,
welches Fach gerade dran war. Die Markierung wandert mit jedem weiteren
``mark_loaded()``-Aufruf zum neuen Fach; das vorherige fällt zurück auf
seine reguläre Alters-Farbe.

Rechtsklick öffnet ein Kontextmenü: auf einem Fach zusätzlich "Rohdaten
anzeigen" (``raw_data_requested``, speist den Viewer in
``ui/raw_data_viewer.py``), überall (auch auf Ordnern oder im leeren
Bereich) "Export visible items" (``export_visible_requested`` — exportiert
das, was gerade in der Item-Tabelle zu sehen ist, unabhängig vom
angeklickten Knoten, genau wie der Toolbar-Button; Peter, 2026-08-03: "im
Stash-Tree das 'Export visible Items'-Rechtsklick menu auch aufnehmen")
sowie "Expand All"/"Collapse All" für den kompletten Baum
(``expandAll``/``collapseAll``) — bei über 100 Fächern in tief
verschachtelten Ordnern (Map-/Unique-Sektionen) sonst mühsames
Knoten-für-Knoten-Aufklappen.

**Mehrfachauswahl** (Peter, 2026-08-02: "Wenn ich im Stash-Tree ein oder
mehrere Stashs bzw. Überordner auswähle, soll die Itemliste dies
wiederspiegeln und nur Items aus diesen Ordnern/Tabs anzeigen") —
``ExtendedSelection`` statt ``SingleSelection``, Strg-/Umschalt-Klick
markiert mehrere Knoten. ``_on_click`` löst je nach Auswahl eines von
zwei Signalen aus: ist genau EIN Knoten ausgewählt UND ist er selbst ein
Blatt-Fach, feuert weiterhin das alte ``stash_selected`` — Einzelauswahl
verhält sich also in jeder Hinsicht unverändert, inklusive automatischem
Nachladen bei Cache-Miss. Das ist eine STRUKTURELLE Unterscheidung (was
wurde angeklickt), keine inhaltliche (worauf löst es sich auf): ein
Ordner mit zufällig nur einem Kind zählt trotzdem als Mehrfachauswahl,
sonst wäre für den Nutzer nicht vorhersehbar, ob ein Ordner-Klick einen
Abruf auslöst. In jedem anderen Fall (0, 2+ Knoten oder ein einzelner
Ordner/eine Gruppe) feuert stattdessen ``selection_changed`` mit der
Liste aller betroffenen Blatt-Fach-IDs (rekursiv aufgelöst,
dedupliziert) — ``MainWindow`` zeigt dafür NUR bereits gecachte Items an
und löst NIE einen API-Abruf aus
(ein Shift-Klick über 20 nie geladene Fächer würde sonst 20 Requests auf
einmal abfeuern und das Rate-Limit sprengen). Ordner UND die
synthetischen Map-Sektionsgruppen ("Tier 6") werden dabei gleich
behandelt: ``_leaf_ids_under`` sammelt einfach alle Kind-Knoten mit
``_DATA_ROLE`` unter einem Knoten ein, unabhängig davon, ob er ein
echter Ordner oder eine reine Anzeige-Gruppe ist — beide sind im
Widget-Baum strukturell identisch.

``highlight_stash(stash_id)`` hebt einen Knoten hervor, wenn in einer
Aggregat- oder Suchansicht eine Zeile ausgewählt wird
(``MainWindow._on_row_selected``). Die Methode klappt die nötigen
Eltern-Ordner auf und scrollt zum Knoten, löst aber kein
``stash_selected`` aus: Sie nutzt ``setCurrentItem`` statt eines echten
Klicks, weil sonst die laufende Such- oder Aggregat-Ansicht in der
Item-Tabelle überschrieben würde.

Map-Stash-Kinder werden nach ``metadata.map.section`` gruppiert (Tier
1–16, dann Unique Maps, dann Special Maps), da ein flacher Baum mit über
100 Fächern unübersichtlich ist. Die Gruppenknoten sind reine
Anzeige-Hilfen ohne ``_DATA_ROLE`` und daher weder klick- noch
aktualisierbar; die Datenschicht (``MainWindow._stash_trees``,
``_leaf_stashes``, Cache) bleibt flach. Ihre Item-Anzahl ist die Summe
der bekannten Kind-Anzahlen.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QMenu, QToolButton,
                               QTreeWidget, QTreeWidgetItem)

from poe_view.api.models import StashTab
from poe_view.ui.theme import blend as _blend

_DATA_ROLE = Qt.ItemDataRole.UserRole
_LAST_LOADED_ROLE = Qt.ItemDataRole.UserRole + 1  # für set_offline(): Refresh-Button neu beschriften
_COL_NAME, _COL_COUNT, _COL_STATUS, _COL_POSITION = 0, 1, 2, 3
_UNLOADED_MARK = "⬇"
_AGE_FRESH_H = 1    # < 1h: normale Textfarbe
_AGE_RECENT_H = 3   # < 3h: leicht abgeblendet, sonst stärker abgeblendet


def _colour_swatch(hex_colour: str, size: int = 12) -> QIcon:
    """Kleines farbiges Quadrat als Icon — sicherer als Text in dieser Farbe."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(QColor(hex_colour))
    painter.setPen(Qt.GlobalColor.transparent)
    painter.drawRoundedRect(0, 0, size, size, 2, 2)
    painter.end()
    return QIcon(pixmap)


def format_age(last_loaded_iso: str, *, now: datetime | None = None) -> str:
    """Exakte lokale Uhrzeit ("14:32:46") für heute geladene Fächer, sonst
    "vor 1d" / "vor 12d" — kurze Beschriftung für den Refresh-Button.

    Vorher stand hier pauschal "heute", was jeden Auto-Refresh innerhalb
    desselben Tages unsichtbar machte ("automatisch hat
    nicht hingehauen" — tatsächlich lief der Live-Refresh alle 40s
    zuverlässig, nur die Anzeige änderte sich den ganzen Tag über nie).
    Die Sekunden-Genauigkeit macht jeden einzelnen Tick sichtbar."""
    try:
        loaded_at = datetime.fromisoformat(last_loaded_iso)
    except ValueError:
        return "?"
    now_dt = now or datetime.now(timezone.utc)
    days = (now_dt - loaded_at).days
    if days <= 0:
        return loaded_at.astimezone().strftime("%H:%M:%S")
    return f"{days}d ago"


def _map_info(stash: StashTab) -> dict:
    return stash.metadata.get("map") or {}


def group_map_children(children: list[StashTab]) -> list[tuple[str, list[StashTab]]] | None:
    """Gruppiert Map-Stash-Kinder nach metadata.map.section.

    Rückgabe: [(Gruppen-Label, Kinder), …] — Tiers numerisch aufsteigend,
    danach "Unique Maps", danach "Special Maps". None, wenn die Kinder gar
    keine Sektions-Information haben (z. B. UniqueStash-Fächer) — dann
    bleibt die Anzeige flach.
    """
    if not any(_map_info(c).get("section") for c in children):
        return None
    groups: dict[str, list[StashTab]] = {}
    for child in children:
        groups.setdefault(str(_map_info(child).get("section") or "?"), []).append(child)

    def sort_key(section: str) -> tuple[int, int]:
        if section.startswith("tier"):
            try:
                return (0, int(section[4:]))
            except ValueError:
                return (0, 999)
        return {"unique": (1, 0), "special": (2, 0)}.get(section, (3, 0))

    def label(section: str) -> str:
        if section.startswith("tier"):
            return f"Tier {section[4:]}"
        return {"unique": "Unique Maps", "special": "Special Maps"}.get(section, section)

    result = []
    for section in sorted(groups, key=sort_key):
        members = sorted(groups[section],
                         key=lambda c: (str(_map_info(c).get("name") or ""),
                                        int(_map_info(c).get("index") or 0)))
        result.append((label(section), members))
    return result


def grouped_leaf_label(child: StashTab) -> str:
    """Kurz-Label eines Fachs UNTER seinem Gruppenknoten: "Fach 3" für
    Tier-Fächer (der Map-Name wäre dort nur die Gruppen-Wiederholung),
    sonst der Map-Name ("Death and Taxes")."""
    info = _map_info(child)
    section = str(info.get("section") or "")
    if section.startswith("tier"):
        return f"Tab {int(info.get('index') or 0) + 1}"
    return str(info.get("name") or child.display_name)


class StashTree(QTreeWidget):
    stash_selected = Signal(str, str)          # stash_id, name — GENAU EIN Blatt-Fach
    selection_changed = Signal(list)           # list[str] Blatt-Fach-IDs — Mehrfachauswahl/Ordner/Gruppe
    stash_refresh_requested = Signal(str, str)  # stash_id, name
    raw_data_requested = Signal(str, str)       # stash_id, name
    export_visible_requested = Signal()         # Rechtsklick-Kontextmenü, wie der Toolbar-Button

    def __init__(self) -> None:
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setColumnCount(4)
        self.setHeaderLabels(["Name", "#", "", "Pos."])
        self.setIconSize(QSize(12, 12))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        header = self.header()
        header.setStretchLastSection(False)
        # Name als Stretch-Spalte: füllt automatisch die verbleibende Breite
        # und schrumpft/wächst mit dem Panel — # und Status bleiben dadurch
        # immer sichtbar, ohne dass Name manuell verkleinert werden muss
        # (Peter: 391 echte Allflame-Tabs, teils mit langen Namen wie
        # "Caer Blaidd, Wolfpack's Den (Remove-only)", machten das nötig).
        # Kehrseite: Stretch-Spalten lassen sich in Qt nicht per Maus
        # verbreitern — hier gewollt, das manuelle Nachziehen soll ja
        # gerade entfallen. Zu breite Labels werden von Qt automatisch mit
        # "…" gekürzt; der volle Name steht im Tooltip (§_build_node).
        # # und Status sind auf reale Extremwerte aus einem 391-Tab-Cache
        # bemessen: # bis 5-stellig ("19133" bei Ordner-Summen), Status auf
        # den breitesten Fall "📴 14:32:46" (Offline + exakte Uhrzeit).
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_COUNT, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_POSITION, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(_COL_COUNT, 46)
        self.setColumnWidth(_COL_STATUS, 80)
        self.setColumnWidth(_COL_POSITION, 40)
        self.headerItem().setTextAlignment(_COL_COUNT, Qt.AlignmentFlag.AlignRight)
        self.headerItem().setTextAlignment(_COL_POSITION, Qt.AlignmentFlag.AlignRight)
        self.headerItem().setToolTip(_COL_COUNT, "Item count (known after the first load)")
        self.headerItem().setToolTip(
            _COL_STATUS, "⬇ = not loaded yet · ⟳ = reload (shows data age) · "
            "📴 = offline cache, GGG currently unreachable")
        self.headerItem().setToolTip(
            _COL_POSITION, "Position in the actual vault order (empty for folders/groups)")
        self._stash_nodes: dict[str, QTreeWidgetItem] = {}  # stash_id → Knoten
        self._offline = False  # GGG nicht erreichbar (MainWindow.set_offline)
        self._last_updated_id: str | None = None  # zuletzt per mark_loaded aktualisiertes Fach
        self.itemClicked.connect(self._on_click)

    def set_offline(self, offline: bool) -> None:
        """GGG nicht erreichbar (Wartung oder kein Netz):
        markiert alle bereits geladenen Fächer als "kommt aus dem
        Offline-Cache", statt sie unverändert wie frisch geladen wirken zu
        lassen. Nie geladene (⬇) Fächer bleiben unverändert — für sie gibt es
        ohnehin nichts anzuzeigen, online wie offline."""
        if offline == self._offline:
            return
        self._offline = offline
        for stash_id, node in self._stash_nodes.items():
            last_loaded_iso = node.data(_COL_STATUS, _LAST_LOADED_ROLE)
            if last_loaded_iso is not None:
                self._set_status(node, stash_id, last_loaded_iso)

    def set_stashes(self, stashes: list[StashTab], last_loaded: dict[str, str] | None = None,
                    item_counts: dict[str, int] | None = None,
                    positions: dict[str, int] | None = None) -> None:
        """Zeigt den Stash-Baum an — startet zugeklappt (auch Unterordner).

        ``last_loaded`` bildet stash_id → ISO-Zeitstempel des letzten
        erfolgreichen Ladens ab (MainWindow._last_loaded). Fehlt der Eintrag,
        gilt der Tab als noch nie geladen. ``item_counts`` überschreibt den
        API-Hinweis (metadata.items) mit der tatsächlich geladenen Anzahl.
        ``positions`` (MainWindow._tab_positions()) füllt die Pos.-Spalte.
        """
        self.clear()
        self._stash_nodes.clear()
        self._last_updated_id = None  # neuer Baum (Liga-Wechsel/Neustart) — alte Markierung wäre irreführend
        last_loaded = last_loaded or {}
        overrides = item_counts or {}
        positions = positions or {}
        for stash in stashes:
            self.addTopLevelItem(self._build_node(stash, overrides))
        # Status erst nach dem Einhängen setzen — setItemWidget wirkt nur
        # auf Items, die bereits Teil des Baums sind.
        for stash_id, node in self._stash_nodes.items():
            self._set_status(node, stash_id, last_loaded.get(stash_id))
            self._set_position(node, positions.get(stash_id))

    def mark_loaded(self, stash_id: str, last_loaded_iso: str, count: int | None = None) -> None:
        """Nach einem erfolgreichen Ladevorgang: ⬇ durch Refresh-Button+Alter ersetzen
        und — falls bekannt — die Item-Anzahl-Spalte (inkl. Eltern-Gruppensumme) aktualisieren.
        Markiert dieses Fach zusätzlich als "gerade aktualisiert" (Türkis), damit bei
        automatischen Sweeps (Single-/Stash-Modus, §MainWindow._drive_refresh_mode)
        sichtbar ist, welches Fach zuletzt dran war — die vorherige Markierung wandert."""
        node = self._stash_nodes.get(stash_id)
        if node is None:
            return
        self._set_status(node, stash_id, last_loaded_iso)
        self._mark_just_updated(stash_id)
        if count is not None:
            node.setText(_COL_COUNT, str(count))
            self._refresh_ancestor_totals(node)

    def update_label(self, stash_id: str, label: str) -> None:
        """Namensspalte eines Knotens nachträglich ändern — z. B. wenn ein
        namenloses Unique-Fach nach dem Item-Load seine Kategorie bekommt."""
        node = self._stash_nodes.get(stash_id)
        if node is not None:
            node.setText(_COL_NAME, label)

    def set_children(self, parent_id: str, children: list[StashTab],
                     last_loaded: dict[str, str] | None = None,
                     item_counts: dict[str, int] | None = None,
                     expand: bool = True,
                     positions: dict[str, int] | None = None) -> None:
        """Hängt die entdeckten Unter-Tabs eines Spezial-Tabs (MapStash, …) unter
        dessen Knoten — ohne den restlichen Baum neu aufzubauen (Aufklapp-Zustand
        und Scroll-Position bleiben erhalten)."""
        parent_node = self._stash_nodes.get(parent_id)
        if parent_node is None:
            return
        last_loaded = last_loaded or {}
        overrides = item_counts or {}
        positions = positions or {}
        # Alte Kind-Knoten auch aus dem id→Knoten-Index entfernen (sonst
        # zeigen mark_loaded()-Aufrufe später auf tote Widget-Referenzen).
        # Rekursiv — mit Sektions-Gruppen liegen Fächer eine Ebene tiefer.
        self._drop_index_entries_below(parent_node)
        parent_node.takeChildren()
        self._attach_children(parent_node, children, overrides)
        for child in children:
            node = self._stash_nodes.get(child.id)
            if node is not None:
                self._set_status(node, child.id, last_loaded.get(child.id))
                self._set_position(node, positions.get(child.id))
        if expand:
            parent_node.setExpanded(True)

    def _set_position(self, node: QTreeWidgetItem, position: int | None) -> None:
        node.setText(_COL_POSITION, "" if position is None else str(position))

    def _drop_index_entries_below(self, node: QTreeWidgetItem) -> None:
        for i in range(node.childCount()):
            child = node.child(i)
            stash = child.data(0, _DATA_ROLE)
            if stash is not None:
                self._stash_nodes.pop(stash.id, None)
            self._drop_index_entries_below(child)

    def _leaf_count(self, stash: StashTab, overrides: dict[str, int]) -> int | None:
        """Bekannte Item-Anzahl: tatsächlich geladen (overrides) schlägt den
        bloßen API-Hinweis (metadata.items bei Map-/Unique-Kindern)."""
        if stash.id in overrides:
            return overrides[stash.id]
        return stash.metadata.get("items")

    def _refresh_ancestor_totals(self, node: QTreeWidgetItem) -> None:
        """Summe der Kind-Anzahlen nach oben durchreichen (Gruppen- und
        Ordner-Knoten) — z. B. "Tier 6" zeigt die Summe seiner Fächer."""
        parent = node.parent()
        while parent is not None:
            total, any_known = 0, False
            for i in range(parent.childCount()):
                text = parent.child(i).text(_COL_COUNT)
                if text.isdigit():
                    total += int(text)
                    any_known = True
            if any_known:
                parent.setText(_COL_COUNT, str(total))
            parent = parent.parent()

    def _attach_children(self, parent_node: QTreeWidgetItem, children: list[StashTab],
                         overrides: dict[str, int]) -> None:
        """Kinder einhängen. Map-Fächer werden nach Sektion gruppiert, da
        über 100 flache Fächer unübersichtlich sind; alles andere bleibt
        flach."""
        grouped = group_map_children(children)
        if grouped is None:
            for child in children:
                parent_node.addChild(self._build_node(child, overrides))
            return
        for group_label, members in grouped:
            group_node = QTreeWidgetItem([f"🗂 {group_label}"])
            group_node.setToolTip(_COL_NAME, group_label)
            counts = [self._leaf_count(m, overrides) for m in members]
            if any(c is not None for c in counts):
                group_node.setText(_COL_COUNT, str(sum(c or 0 for c in counts)))
            parent_node.addChild(group_node)
            for child in members:
                group_node.addChild(self._build_node(child, overrides, label=grouped_leaf_label(child)))

    def _build_node(self, stash: StashTab, overrides: dict[str, int],
                    label: str | None = None) -> QTreeWidgetItem:
        """Rekursiv: Ordner enthalten children (beliebig tief)."""
        prefix = "📁 " if stash.is_folder else ""
        name = label or stash.display_name
        node = QTreeWidgetItem([f"{prefix}{name}"])
        node.setToolTip(_COL_NAME, name)  # voller Name, falls die Stretch-Spalte ihn kürzt
        if not stash.is_folder:
            node.setData(0, _DATA_ROLE, stash)
            self._stash_nodes[stash.id] = node
            count = self._leaf_count(stash, overrides)
            if count is not None:
                node.setText(_COL_COUNT, str(count))
        if stash.colour:
            node.setIcon(_COL_NAME, _colour_swatch(stash.colour))
        self._attach_children(node, stash.children, overrides)
        return node

    def _apply_age_color(self, node: QTreeWidgetItem, last_loaded_iso: str | None) -> None:
        """Namensspalte nach Datenalter abblenden: aktuell (< 1h) bleibt in
        normaler Textfarbe, bis 3h leicht, älter deutlicher Richtung
        Hintergrund gemischt. Relativ zur echten Theme-Textfarbe statt fest
        codierter Grautöne, damit es auf hellem wie dunklem Theme lesbar
        bleibt. Nie geladene Fächer (kein Zeitstempel) bleiben unangetastet."""
        if last_loaded_iso is None:
            return
        try:
            loaded_at = datetime.fromisoformat(last_loaded_iso)
        except ValueError:
            return
        age_h = (datetime.now(timezone.utc) - loaded_at).total_seconds() / 3600
        text = self.palette().color(QPalette.ColorRole.Text)
        base = self.palette().color(QPalette.ColorRole.Base)
        if age_h < _AGE_FRESH_H:
            colour = text
        elif age_h < _AGE_RECENT_H:
            colour = _blend(text, base, 0.35)
        else:
            colour = _blend(text, base, 0.6)
        node.setForeground(_COL_NAME, QBrush(colour))

    def _refresh_node_colour(self, node: QTreeWidgetItem, stash_id: str,
                             last_loaded_iso: str | None) -> None:
        """Türkis für das zuletzt per ``mark_loaded`` aktualisierte Fach,
        sonst die normale Alters-Abblendung — eine Stelle für beide Regeln,
        damit sie nie auseinanderlaufen (z. B. bei ``set_offline``)."""
        if stash_id == self._last_updated_id:
            node.setForeground(_COL_NAME, QBrush(QColor("turquoise")))
            return
        self._apply_age_color(node, last_loaded_iso)

    def _mark_just_updated(self, stash_id: str) -> None:
        """Wandert die Türkis-Markierung auf ``stash_id`` — das zuvor
        markierte Fach fällt zurück auf seine normale Alters-Farbe (nach
        einem echten Refresh ohnehin "aktuell", also meist ebenfalls hell,
        aber ohne die Sonderfarbe)."""
        previous = self._last_updated_id
        self._last_updated_id = stash_id
        if previous is not None and previous != stash_id:
            prev_node = self._stash_nodes.get(previous)
            if prev_node is not None:
                self._apply_age_color(prev_node, prev_node.data(_COL_STATUS, _LAST_LOADED_ROLE))
        node = self._stash_nodes.get(stash_id)
        if node is not None:
            self._refresh_node_colour(node, stash_id, node.data(_COL_STATUS, _LAST_LOADED_ROLE))

    def refresh_age_colors(self) -> None:
        """Regelmäßig (Sekunden-Tick in MainWindow) neu anwenden, damit ein
        Fach von "aktuell" nach "älter" wandert, auch ohne dass sich sonst
        etwas an ihm ändert. Die Türkis-Markierung (§_mark_just_updated)
        bleibt davon unberührt, da ``_refresh_node_colour`` sie kennt."""
        for stash_id, node in self._stash_nodes.items():
            self._refresh_node_colour(node, stash_id, node.data(_COL_STATUS, _LAST_LOADED_ROLE))

    def _set_status(self, node: QTreeWidgetItem, stash_id: str,
                    last_loaded_iso: str | None) -> None:
        node.setData(_COL_STATUS, _LAST_LOADED_ROLE, last_loaded_iso)
        self._refresh_node_colour(node, stash_id, last_loaded_iso)
        if last_loaded_iso is None:
            self.removeItemWidget(node, _COL_STATUS)
            node.setText(_COL_STATUS, _UNLOADED_MARK)
            node.setToolTip(_COL_STATUS, "Not loaded yet")
            return
        name: str = node.data(0, _DATA_ROLE).display_name
        age = format_age(last_loaded_iso)
        node.setText(_COL_STATUS, "")
        button = QToolButton()
        button.setAutoRaise(True)
        if self._offline:
            button.setText(f"📴 {age}")
            button.setToolTip(
                f"'{name}': offline cache (last updated: {age}) — "
                "clicking still attempts a reload")
        else:
            button.setText(f"⟳ {age}")
            button.setToolTip(f"Reload '{name}'")
        button.clicked.connect(lambda: self.stash_refresh_requested.emit(stash_id, name))
        self.setItemWidget(node, _COL_STATUS, button)

    def _leaf_ids_under(self, item: QTreeWidgetItem) -> list[str]:
        """Alle Blatt-Fach-IDs unter ``item`` — es selbst, falls es schon ein
        Blatt ist, sonst rekursiv über seine Kinder. Funktioniert für echte
        Ordner UND die synthetischen Map-Sektionsgruppen ("Tier 6")
        gleichermaßen: beide sind im Widget-Baum einfach Knoten mit Kindern,
        ohne eigene ``_DATA_ROLE`` — kein Sonderfall nötig."""
        stash: StashTab | None = item.data(0, _DATA_ROLE)
        if stash is not None:
            return [stash.id]
        ids: list[str] = []
        for i in range(item.childCount()):
            ids.extend(self._leaf_ids_under(item.child(i)))
        return ids

    def _collect_leaf_ids(self, items: list[QTreeWidgetItem]) -> list[str]:
        """Blatt-Fach-IDs aller übergebenen Knoten, dedupliziert (Klick auf
        einen Ordner UND gleichzeitig eines seiner eigenen Kinder per
        Strg-Klick würde dessen ID sonst doppelt liefern), Reihenfolge
        stabil nach erstem Auftreten."""
        ids: list[str] = []
        seen: set[str] = set()
        for item in items:
            for leaf_id in self._leaf_ids_under(item):
                if leaf_id not in seen:
                    seen.add(leaf_id)
                    ids.append(leaf_id)
        return ids

    def _on_click(self, item: QTreeWidgetItem) -> None:
        """Wertet die aktuelle Auswahl aus (``selectedItems()``), nicht nur
        den angeklickten Knoten — bei Strg-/Umschalt-Klick-Sequenzen hat Qt
        die Auswahl schon aktualisiert, bevor dieser Slot läuft.

        Der alte Einzelauswahl-Pfad (``stash_selected``, inklusive
        automatischem Nachladen bei Cache-Miss, siehe
        ``MainWindow._on_stash_selected``) gilt NUR, wenn genau EIN Knoten
        ausgewählt ist UND dieser Knoten selbst ein Blatt-Fach ist — nicht
        etwa, wenn sich die Auswahl zufällig auf ein einziges Fach AUFLÖST
        (z. B. ein Ordner mit genau einem Kind). Diese strukturelle statt
        inhaltliche Unterscheidung ist bewusst: Ordner/Gruppen sollen sich
        unabhängig davon, wie viele Kinder sie gerade haben, immer gleich
        verhalten (kein Auto-Nachladen), sonst wäre für den Nutzer nicht
        vorhersehbar, ob ein Ordner-Klick einen Abruf auslöst oder nicht.
        Ein Strg-Klick, der eine Mehrfachauswahl auf ein einzelnes FACH
        zurückstutzt, fällt dagegen zurecht auf den alten Pfad zurück — der
        verbleibende Knoten IST dann wieder ein direkt ausgewähltes Blatt.

        In jedem anderen Fall (0, 2+ Knoten, oder ein einzelner Ordner/eine
        Gruppe) übernimmt ``selection_changed`` mit allen betroffenen
        Blatt-IDs (rekursiv aufgelöst); MainWindow zeigt dafür NUR bereits
        Gecachtes an und löst nie selbst einen Abruf aus."""
        selected = self.selectedItems()
        if len(selected) == 1:
            stash: StashTab | None = selected[0].data(0, _DATA_ROLE)
            if stash is not None:
                self.stash_selected.emit(stash.id, stash.display_name)
                return
        leaf_ids = self._collect_leaf_ids(selected)
        if leaf_ids:
            self.selection_changed.emit(leaf_ids)

    def highlight_stash(self, stash_id: str) -> None:
        """Hebt den Knoten eines Fachs hervor (Klick auf ein
        Item in einer Aggregat-/Suchansicht soll das Herkunfts-Fach im Baum
        zeigen) — klappt dafür nötige Eltern-Knoten auf und scrollt hin.
        BEWUSST ``setCurrentItem`` statt eines simulierten Klicks: das löst
        kein ``itemClicked`` aus (nur echte Mausklicks tun das), die
        Suche/Aggregat-Ansicht in der Item-Tabelle bleibt also unangetastet."""
        node = self._stash_nodes.get(stash_id)
        if node is None:
            return
        parent = node.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.setCurrentItem(node)
        self.scrollToItem(node)

    def _on_context_menu(self, pos) -> None:
        """"View Raw Data" nur für Fächer mit eigenen Daten (kein
        Ordner-/Gruppenknoten); "Export visible items" (Peter, 2026-08-03)
        und "Expand All"/"Collapse All" gelten für den ganzen Baum bzw.
        die Item-Tabelle und stehen deshalb immer zur Verfügung, auch auf
        einem Ordner oder im leeren Bereich unterhalb der letzten Zeile —
        der Export bezieht sich auf das, was gerade in der Tabelle zu sehen
        ist, unabhängig vom angeklickten Knoten."""
        item = self.itemAt(pos)
        stash: StashTab | None = item.data(0, _DATA_ROLE) if item is not None else None
        menu = QMenu(self)
        if stash is not None:
            action = menu.addAction("🔍 View Raw Data")
            action.triggered.connect(lambda: self.raw_data_requested.emit(stash.id, stash.display_name))
            menu.addSeparator()
        menu.addAction("💾 Export visible items").triggered.connect(
            self.export_visible_requested.emit)
        menu.addSeparator()
        menu.addAction("▸ Expand All").triggered.connect(self.expandAll)
        menu.addAction("▾ Collapse All").triggered.connect(self.collapseAll)
        menu.exec(self.viewport().mapToGlobal(pos))
