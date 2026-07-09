"""Stash-Baum links unten (docs/ARCHITEKTUR.md §5) — nur noch Stash-Tabs.

Kein umschließender "Stash"-Wurzelknoten mehr: Die Tabs sind direkt die
Top-Level-Einträge des Baums (spart eine Ebene, Nutzer-Feedback). Die
Charakterliste lebt separat in ``character_list.py``.

Jeder Stash-Tab-Knoten hat GENAU EINE Zusatzspalte (Nutzer-Feedback: "wir
benötigen im Stash-Tree nur entweder das Download-Symbol oder das
Refresh-Symbol" — beide Zustände schließen sich gegenseitig aus): entweder
"⬇" (Items noch nie geladen) als reiner Text, oder — sobald mindestens
einmal geladen — ein Refresh-Button, dessen Beschriftung zugleich das Alter
der zuletzt geladenen Daten zeigt ("⟳ heute", "⟳ vor 3d"). Die Namensspalte
ist per Maus verbreiterbar (``Interactive`` statt ``Stretch`` — Stretch-
Spalten lassen sich in Qt NICHT manuell resizen).

LabVIEW-Äquivalent: Tree Control mit rekursivem Laden der children. Die
Tab-Farbe (metadata.colour, hex ohne '#') wird NICHT als Textfarbe verwendet
(einige API-Farben sind dunkel genug, um auf dunklem Grund unlesbar zu
werden) — stattdessen als kleines Farbquadrat vor dem Namen (Icon), Text
bleibt immer in der normalen, garantiert lesbaren Vordergrundfarbe.

Rechtsklick auf einen Tab öffnet ein Kontextmenü mit "Rohdaten anzeigen"
(``raw_data_requested``-Signal) — Aufhänger für den Mini-Viewer in
``ui/raw_data_viewer.py`` (Nutzer-Feedback).

Map-Stash-Kinder werden nach ``metadata.map.section`` gruppiert (Tier 1–16,
dann Unique Maps, dann Special Maps) — ein flacher Baum mit 100+ Fächern war
"uferlos" (Nutzer-Feedback). Die Gruppenknoten sind reine Anzeige-Hilfen
(kein _DATA_ROLE → nicht klick-/refreshbar); die Datenschicht
(MainWindow._stash_trees, _leaf_stashes, Cache) bleibt flach.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QHeaderView, QMenu, QToolButton, QTreeWidget,
                               QTreeWidgetItem)

from poe_view.api.models import StashTab

_DATA_ROLE = Qt.ItemDataRole.UserRole
_COL_NAME, _COL_STATUS = 0, 1
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
    """"heute" / "vor 1d" / "vor 12d" — kurze Beschriftung für den Refresh-Button."""
    try:
        loaded_at = datetime.fromisoformat(last_loaded_iso)
    except ValueError:
        return "?"
    days = ((now or datetime.now(timezone.utc)) - loaded_at).days
    return "heute" if days <= 0 else f"vor {days}d"


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
    """Kurz-Label eines Fachs UNTER seinem Gruppenknoten: "Fach 3 (12 Items)"
    für Tier-Fächer (der Map-Name wäre dort nur die Gruppen-Wiederholung),
    sonst der Map-Name ("Death and Taxes (1 Items)")."""
    info = _map_info(child)
    section = str(info.get("section") or "")
    if section.startswith("tier"):
        base = f"Fach {int(info.get('index') or 0) + 1}"
    else:
        base = str(info.get("name") or child.display_name)
    count = child.metadata.get("items")
    return f"{base} ({count} Items)" if count is not None else base


class StashTree(QTreeWidget):
    stash_selected = Signal(str, str)          # stash_id, name
    stash_refresh_requested = Signal(str, str)  # stash_id, name
    raw_data_requested = Signal(str, str)       # stash_id, name

    def __init__(self) -> None:
        super().__init__()
        self.setColumnCount(2)
        self.setHeaderLabels(["Name", ""])
        self.setIconSize(QSize(12, 12))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        header = self.header()
        header.setStretchLastSection(False)
        # Interactive statt Stretch: Stretch-Spalten sind in Qt NICHT per
        # Maus verbreiterbar (das war der Bug hinter "Spalten lassen sich
        # nicht verbreitern"). Initialbreite grob großzügig gewählt.
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(_COL_NAME, 220)
        self.setColumnWidth(_COL_STATUS, 74)
        self.headerItem().setToolTip(
            _COL_STATUS, "⬇ = noch nicht geladen · ⟳ = neu laden (zeigt Alter der Daten)")
        self._stash_nodes: dict[str, QTreeWidgetItem] = {}  # stash_id → Knoten
        self.itemClicked.connect(self._on_click)

    def set_stashes(self, stashes: list[StashTab],
                    last_loaded: dict[str, str] | None = None) -> None:
        """Zeigt den Stash-Baum an — startet zugeklappt (auch Unterordner).

        ``last_loaded`` bildet stash_id → ISO-Zeitstempel des letzten
        erfolgreichen Ladens ab (MainWindow._last_loaded). Fehlt der Eintrag,
        gilt der Tab als noch nie geladen.
        """
        self.clear()
        self._stash_nodes.clear()
        last_loaded = last_loaded or {}
        for stash in stashes:
            self.addTopLevelItem(self._build_node(stash))
        # Status erst NACH dem Einhängen setzen — setItemWidget wirkt nur
        # auf Items, die bereits Teil des Baums sind.
        for stash_id, node in self._stash_nodes.items():
            self._set_status(node, stash_id, last_loaded.get(stash_id))

    def mark_loaded(self, stash_id: str, last_loaded_iso: str) -> None:
        """Nach einem erfolgreichen Ladevorgang: ⬇ durch Refresh-Button+Alter ersetzen."""
        node = self._stash_nodes.get(stash_id)
        if node is not None:
            self._set_status(node, stash_id, last_loaded_iso)

    def update_label(self, stash_id: str, label: str) -> None:
        """Namensspalte eines Knotens nachträglich ändern — z. B. wenn ein
        namenloses Unique-Fach nach dem Item-Load seine Kategorie bekommt."""
        node = self._stash_nodes.get(stash_id)
        if node is not None:
            node.setText(_COL_NAME, label)

    def set_children(self, parent_id: str, children: list[StashTab],
                     last_loaded: dict[str, str] | None = None,
                     expand: bool = True) -> None:
        """Hängt die entdeckten Unter-Tabs eines Spezial-Tabs (MapStash, …) unter
        dessen Knoten — OHNE den restlichen Baum neu aufzubauen (Aufklapp-Zustand
        und Scroll-Position bleiben erhalten)."""
        parent_node = self._stash_nodes.get(parent_id)
        if parent_node is None:
            return
        last_loaded = last_loaded or {}
        # Alte Kind-Knoten auch aus dem id→Knoten-Index entfernen (sonst
        # zeigen mark_loaded()-Aufrufe später auf tote Widget-Referenzen).
        # Rekursiv — mit Sektions-Gruppen liegen Fächer eine Ebene tiefer.
        self._drop_index_entries_below(parent_node)
        parent_node.takeChildren()
        self._attach_children(parent_node, children)
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

    def _attach_children(self, parent_node: QTreeWidgetItem,
                         children: list[StashTab]) -> None:
        """Kinder einhängen — Map-Fächer gruppiert nach Sektion (Nutzer-Feedback:
        100+ flache Fächer waren "uferlos"), alles andere flach."""
        grouped = group_map_children(children)
        if grouped is None:
            for child in children:
                parent_node.addChild(self._build_node(child))
            return
        for group_label, members in grouped:
            total = sum(m.metadata.get("items") or 0 for m in members)
            group_node = QTreeWidgetItem([f"🗂 {group_label} ({total} Items)"])
            parent_node.addChild(group_node)
            for child in members:
                group_node.addChild(self._build_node(child, label=grouped_leaf_label(child)))

    def _build_node(self, stash: StashTab, label: str | None = None) -> QTreeWidgetItem:
        """Rekursiv: Ordner enthalten children (beliebig tief)."""
        prefix = "📁 " if stash.is_folder else ""
        node = QTreeWidgetItem([f"{prefix}{label or stash.display_name}"])
        if not stash.is_folder:
            node.setData(0, _DATA_ROLE, stash)
            self._stash_nodes[stash.id] = node
        if stash.colour:
            node.setIcon(_COL_NAME, _colour_swatch(stash.colour))
        self._attach_children(node, stash.children)
        return node

    def _set_status(self, node: QTreeWidgetItem, stash_id: str,
                    last_loaded_iso: str | None) -> None:
        if last_loaded_iso is None:
            self.removeItemWidget(node, _COL_STATUS)
            node.setText(_COL_STATUS, _UNLOADED_MARK)
            node.setToolTip(_COL_STATUS, "Noch nicht geladen")
            return
        name: str = node.data(0, _DATA_ROLE).display_name
        node.setText(_COL_STATUS, "")
        button = QToolButton()
        button.setText(f"⟳ {format_age(last_loaded_iso)}")
        button.setAutoRaise(True)
        button.setToolTip(f"'{name}' neu laden")
        button.clicked.connect(lambda: self.stash_refresh_requested.emit(stash_id, name))
        self.setItemWidget(node, _COL_STATUS, button)

    def _on_click(self, item: QTreeWidgetItem) -> None:
        stash: StashTab | None = item.data(0, _DATA_ROLE)
        if stash is not None:
            self.stash_selected.emit(stash.id, stash.display_name)

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
