"""Stash-Baum links unten (docs/ARCHITEKTUR.md §5) — nur noch Stash-Tabs.

Kein umschließender "Stash"-Wurzelknoten mehr: Die Tabs sind direkt die
Top-Level-Einträge des Baums (spart eine Ebene, Nutzer-Feedback). Die
Charakterliste lebt separat in ``character_list.py``.

Drei Spalten: Name, Item-Anzahl ("#", Nutzer-Feedback — vorher stand die
Zahl als "(N Items)"-Text im Namen, das wurde als unübersichtlich
empfunden), und GENAU EINE Status-Spalte, die sich gegenseitig
ausschließende Zustände zeigt: "⬇" (Items noch nie geladen) als reiner
Text, oder — sobald mindestens einmal geladen — ein Refresh-Button, dessen
Beschriftung zugleich das Alter der zuletzt geladenen Daten zeigt —
heute geladene Fächer als exakte Uhrzeit ("⟳ 14:32:46", Nutzer-Feedback:
"heute" allein verschleierte, OB der Auto-Refresh gerade wirklich
gegriffen hat), ältere als Tage ("⟳ vor 3d"). Ist GGG nicht erreichbar (``set_offline``,
Nutzer-Feedback: GGG-Wartung am Patchday), wird aus dem ⟳ ein "📴" — die
Daten kommen dann garantiert aus dem Cache, nicht von einer frischen
Anfrage. Die Namensspalte ist per Maus verbreiterbar
(``Interactive`` statt ``Stretch`` — Stretch-Spalten lassen sich in Qt
NICHT manuell resizen).

LabVIEW-Äquivalent: Tree Control mit rekursivem Laden der children. Die
Tab-Farbe (metadata.colour, hex ohne '#') wird NICHT als Textfarbe verwendet
(einige API-Farben sind dunkel genug, um auf dunklem Grund unlesbar zu
werden) — stattdessen als kleines Farbquadrat vor dem Namen (Icon), Text
bleibt immer in der normalen, garantiert lesbaren Vordergrundfarbe.

Rechtsklick auf einen Tab öffnet ein Kontextmenü mit "Rohdaten anzeigen"
(``raw_data_requested``-Signal) — Aufhänger für den Mini-Viewer in
``ui/raw_data_viewer.py`` (Nutzer-Feedback).

``highlight_stash(stash_id)`` hebt einen Knoten hervor (Klick auf ein Item
in einer Aggregat-/Suchansicht, MainWindow._on_row_selected) — klappt
nötige Eltern-Ordner auf und scrollt hin, OHNE das ``stash_selected``-
Signal auszulösen (nutzt ``setCurrentItem`` statt eines echten Klicks):
sonst würde das versehentlich die gerade angezeigte Such-/Aggregat-Ansicht
in der Item-Tabelle überschreiben (Nutzer-Feedback).

Map-Stash-Kinder werden nach ``metadata.map.section`` gruppiert (Tier 1–16,
dann Unique Maps, dann Special Maps) — ein flacher Baum mit 100+ Fächern war
"uferlos" (Nutzer-Feedback). Die Gruppenknoten sind reine Anzeige-Hilfen
(kein _DATA_ROLE → nicht klick-/refreshbar); die Datenschicht
(MainWindow._stash_trees, _leaf_stashes, Cache) bleibt flach. Ihre
Item-Anzahl ist die Summe der (bekannten) Kind-Anzahlen.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QHeaderView, QMenu, QToolButton, QTreeWidget,
                               QTreeWidgetItem)

from poe_view.api.models import StashTab

_DATA_ROLE = Qt.ItemDataRole.UserRole
_LAST_LOADED_ROLE = Qt.ItemDataRole.UserRole + 1  # für set_offline(): Refresh-Button neu beschriften
_COL_NAME, _COL_COUNT, _COL_STATUS = 0, 1, 2
_UNLOADED_MARK = "⬇"


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
    desselben Tages unsichtbar machte (Nutzer-Feedback: "automatisch hat
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
    return f"vor {days}d"


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
        return f"Fach {int(info.get('index') or 0) + 1}"
    return str(info.get("name") or child.display_name)


class StashTree(QTreeWidget):
    stash_selected = Signal(str, str)          # stash_id, name
    stash_refresh_requested = Signal(str, str)  # stash_id, name
    raw_data_requested = Signal(str, str)       # stash_id, name

    def __init__(self) -> None:
        super().__init__()
        self.setColumnCount(3)
        self.setHeaderLabels(["Name", "#", ""])
        self.setIconSize(QSize(12, 12))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        header = self.header()
        header.setStretchLastSection(False)
        # Interactive statt Stretch: Stretch-Spalten sind in Qt NICHT per
        # Maus verbreiterbar (das war der Bug hinter "Spalten lassen sich
        # nicht verbreitern"). Initialbreite grob großzügig gewählt.
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(_COL_COUNT, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(_COL_NAME, 220)
        self.setColumnWidth(_COL_COUNT, 42)
        self.setColumnWidth(_COL_STATUS, 74)
        self.headerItem().setTextAlignment(_COL_COUNT, Qt.AlignmentFlag.AlignRight)
        self.headerItem().setToolTip(_COL_COUNT, "Anzahl Items (bekannt nach dem ersten Laden)")
        self.headerItem().setToolTip(
            _COL_STATUS, "⬇ = noch nicht geladen · ⟳ = neu laden (zeigt Alter der Daten) · "
            "📴 = Offline-Cache, GGG gerade nicht erreichbar")
        self._stash_nodes: dict[str, QTreeWidgetItem] = {}  # stash_id → Knoten
        self._offline = False  # GGG nicht erreichbar (MainWindow.set_offline)
        self.itemClicked.connect(self._on_click)

    def set_offline(self, offline: bool) -> None:
        """GGG nicht erreichbar (Wartung/kein Netz, Nutzer-Feedback Patchday):
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
                    item_counts: dict[str, int] | None = None) -> None:
        """Zeigt den Stash-Baum an — startet zugeklappt (auch Unterordner).

        ``last_loaded`` bildet stash_id → ISO-Zeitstempel des letzten
        erfolgreichen Ladens ab (MainWindow._last_loaded). Fehlt der Eintrag,
        gilt der Tab als noch nie geladen. ``item_counts`` überschreibt den
        API-Hinweis (metadata.items) mit der tatsächlich geladenen Anzahl.
        """
        self.clear()
        self._stash_nodes.clear()
        last_loaded = last_loaded or {}
        overrides = item_counts or {}
        for stash in stashes:
            self.addTopLevelItem(self._build_node(stash, overrides))
        # Status erst NACH dem Einhängen setzen — setItemWidget wirkt nur
        # auf Items, die bereits Teil des Baums sind.
        for stash_id, node in self._stash_nodes.items():
            self._set_status(node, stash_id, last_loaded.get(stash_id))

    def mark_loaded(self, stash_id: str, last_loaded_iso: str, count: int | None = None) -> None:
        """Nach einem erfolgreichen Ladevorgang: ⬇ durch Refresh-Button+Alter ersetzen
        und — falls bekannt — die Item-Anzahl-Spalte (inkl. Eltern-Gruppensumme) aktualisieren."""
        node = self._stash_nodes.get(stash_id)
        if node is None:
            return
        self._set_status(node, stash_id, last_loaded_iso)
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
                     expand: bool = True) -> None:
        """Hängt die entdeckten Unter-Tabs eines Spezial-Tabs (MapStash, …) unter
        dessen Knoten — OHNE den restlichen Baum neu aufzubauen (Aufklapp-Zustand
        und Scroll-Position bleiben erhalten)."""
        parent_node = self._stash_nodes.get(parent_id)
        if parent_node is None:
            return
        last_loaded = last_loaded or {}
        overrides = item_counts or {}
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
        if expand:
            parent_node.setExpanded(True)

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
        """Summe der Kind-Anzahlen nach oben durchreichen (Gruppen- UND
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
        """Kinder einhängen — Map-Fächer gruppiert nach Sektion (Nutzer-Feedback:
        100+ flache Fächer waren "uferlos"), alles andere flach."""
        grouped = group_map_children(children)
        if grouped is None:
            for child in children:
                parent_node.addChild(self._build_node(child, overrides))
            return
        for group_label, members in grouped:
            group_node = QTreeWidgetItem([f"🗂 {group_label}"])
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
        node = QTreeWidgetItem([f"{prefix}{label or stash.display_name}"])
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

    def _set_status(self, node: QTreeWidgetItem, stash_id: str,
                    last_loaded_iso: str | None) -> None:
        node.setData(_COL_STATUS, _LAST_LOADED_ROLE, last_loaded_iso)
        if last_loaded_iso is None:
            self.removeItemWidget(node, _COL_STATUS)
            node.setText(_COL_STATUS, _UNLOADED_MARK)
            node.setToolTip(_COL_STATUS, "Noch nicht geladen")
            return
        name: str = node.data(0, _DATA_ROLE).display_name
        age = format_age(last_loaded_iso)
        node.setText(_COL_STATUS, "")
        button = QToolButton()
        button.setAutoRaise(True)
        if self._offline:
            button.setText(f"📴 {age}")
            button.setToolTip(
                f"'{name}': Offline-Cache (zuletzt aktualisiert: {age}) — "
                "Klick versucht trotzdem ein Neuladen")
        else:
            button.setText(f"⟳ {age}")
            button.setToolTip(f"'{name}' neu laden")
        button.clicked.connect(lambda: self.stash_refresh_requested.emit(stash_id, name))
        self.setItemWidget(node, _COL_STATUS, button)

    def _on_click(self, item: QTreeWidgetItem) -> None:
        stash: StashTab | None = item.data(0, _DATA_ROLE)
        if stash is not None:
            self.stash_selected.emit(stash.id, stash.display_name)

    def highlight_stash(self, stash_id: str) -> None:
        """Hebt den Knoten eines Fachs hervor (Nutzer-Feedback: Klick auf ein
        Item in einer Aggregat-/Suchansicht soll das Herkunfts-Fach im Baum
        zeigen) — klappt dafür nötige Eltern-Knoten auf und scrollt hin.
        BEWUSST ``setCurrentItem`` statt eines simulierten Klicks: das löst
        KEIN ``itemClicked`` aus (nur echte Mausklicks tun das), die
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
        item = self.itemAt(pos)
        if item is None:
            return
        stash: StashTab | None = item.data(0, _DATA_ROLE)
        if stash is None:
            return  # Ordner-Knoten haben keine eigenen Rohdaten
        menu = QMenu(self)
        action = menu.addAction("🔍 Rohdaten anzeigen")
        action.triggered.connect(lambda: self.raw_data_requested.emit(stash.id, stash.display_name))
        menu.exec(self.viewport().mapToGlobal(pos))
