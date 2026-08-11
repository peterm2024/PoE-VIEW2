"""Erzeugt die README-Screenshots aus erfundenen Daten.

Aufruf: python tools/make_screenshots.py

**Warum ein Generator und keine Handarbeit.** Für die README gilt eine
harte Regel (sie steht auch über den Bildern): Es dürfen keine echten
Konto-, Charakter- oder Item-Namen zu sehen sein. Von Hand aufgenommene
Bilder halten diese Regel nur so lange, wie beim Aufnehmen jemand daran
denkt — und sie müssen bei jeder Oberflächenänderung neu aufgenommen
werden, sonst zeigt die README eine Version, die es nicht mehr gibt. Die
alten drei Bilder vom 2026-08-02 zeigten deshalb noch die Statuszeile von
vor dem Aufräumen, ohne Hilfe-Knopf, ohne Uhr, ohne Zonenanzeige.

Dieses Skript nimmt beides ab: Die Daten sind erfunden und stehen unten
im Klartext, und der nächste Lauf bringt die Bilder auf den aktuellen
Stand der Oberfläche.

**Kein Zugriff auf echte lokale Daten.** ``config.APP_DATA_DIR`` wird auf
ein temporäres Verzeichnis umgebogen, bevor das Fenster entsteht — sonst
läse der Generator Peters Cache und schriebe ihm womöglich seine
Spalteneinstellungen um. Dieselbe Vorsichtsmaßnahme wie in
``tests/conftest.py``, und aus demselben Grund: In diesem Projekt sind
schon zweimal Daten verlorengegangen, weil etwas in die echte Datei
geschrieben hat, das es nicht sollte (FALLSTRICKE #62).

**Läuft NICHT headless**, anders als die Testsuite. Mit
``QT_QPA_PLATFORM=offscreen`` fehlen Qt sowohl die Systemschriften als
auch die Systempalette: Der erste Versuch lieferte Bilder, in denen jedes
Zeichen ein leeres Kästchen war und die Oberfläche hell statt dunkel
erschien — das dunkle Aussehen kommt unter Windows 11 aus der
Systemeinstellung, die Anwendung setzt selbst keine Palette. Das Fenster
erscheint während des Laufs also kurz auf dem Bildschirm. Das ist der
Preis dafür, dass die Bilder so aussehen wie das Programm.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QSplitter  # noqa: E402

from poe_view import config  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="poe-view2-screenshots-"))
config.APP_DATA_DIR = _TMP  # VOR jedem Import, der das Fenster baut

from poe_view.api.models import Character, Item, StashTab  # noqa: E402
from poe_view.api.ninja import PriceIndex  # noqa: E402
from poe_view.services import data_cache, token_store  # noqa: E402

data_cache._CACHE_FILE = _TMP / "unused.json"
token_store.load_token = lambda: None  # kein echtes Konto, kein echter Login

from poe_view.ui.item_history import HistoryEntry  # noqa: E402
from poe_view.ui.main_window import MainWindow  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
LEAGUE = "Demo League"
ACCOUNT = "Demo#1234"  # kurz genug, dass der Toolbar-Knopf ihn nicht kürzt

# --------------------------------------------------------------------- #
# Erfundene Daten. Namen bewusst als solche erkennbar ("Demo …") — ein
# Screenshot soll niemanden glauben machen, hier stünde ein echtes Konto.

_RARES = [
    ("Doom Grip", "Titan Gauntlets", 84,
     ["+78 to maximum Life", "+34% to Fire Resistance", "+29% to Cold Resistance"]),
    ("Vaal Regalia", "Vaal Regalia", 81,
     ["+112 to maximum Energy Shield", "+18% to all Elemental Resistances"]),
    ("Hubris Circlet", "Hubris Circlet", 79,
     ["+91 to maximum Mana", "+22% to Lightning Resistance"]),
    ("Two-Toned Boots", "Two-Toned Boots", 83,
     ["30% increased Movement Speed", "+40 to maximum Life"]),
    ("Stygian Vise", "Stygian Vise", 86,
     ["+45 to Strength and Intelligence", "+12% to Chaos Resistance"]),
    ("Hate Song", "Opal Sceptre", 85,
     ["+118 to maximum Life", "18% increased Cast Speed", "+1 to Level of all Fire Skills"]),
    ("Dread Veil", "Lion Pelt", 84,
     ["+96 to maximum Life", "+31% to Cold Resistance"]),
    ("Beast Coil", "Amethyst Ring", 86,
     ["+38 to maximum Life", "+15% to Chaos Resistance", "Adds 12 to 19 Chaos Damage"]),
    ("Rift Clasp", "Onyx Amulet", 83,
     ["+21 to all Attributes", "+27% to Fire Resistance", "9% increased Attack Speed"]),
    ("Storm Bite", "Vaal Axe", 82,
     ["Adds 18 to 340 Lightning Damage", "24% increased Attack Speed"]),
]

_CURRENCY = [("Chaos Orb", 42), ("Divine Orb", 3), ("Orb of Alchemy", 88),
             ("Orb of Scouring", 24), ("Orb of Chance", 61), ("Vaal Orb", 12)]

_GEMS = [("Determination", 21, 20), ("Molten Strike", 20, 23), ("Anomalous Haste", 20, 18)]

_MAPS = [("Toxic Grove Map", 14), ("Sandy Seabed Map", 11)]

# Sichtbare Spalten für die Bilder, in dieser Reihenfolge. Alles Weitere
# (Level, Qual., Str/Dex/Int) bleibt aus — es würde die Value-Spalte aus
# dem sichtbaren Bereich schieben.
#
# Die Icon-Spalte ist AUS (Peter, 2026-08-07). Sie bliebe in diesen
# Bildern zwangsläufig leer: Der Generator arbeitet mit erfundenen Items
# und ohne Netzzugriff, und GGGs Icon-URLs sind undurchsichtige
# CDN-Token, die sich aus einem Item-Namen nicht bauen lassen. Eine
# eingeschaltete, aber immer leere Spalte sieht nach Defekt aus.
_COLUMN_CONFIG = [(name, name in ("Position", "Name", "Base", "Stack",
                                  "iLvl", "Mods", "Value"))
                  for name in ("Icon", "Position", "Name", "Base", "Type", "Level",
                               "Qual.", "Stack", "iLvl", "Req.Lvl", "Str", "Dex",
                               "Int", "Mods", "Value")]

_PRICES = {"Chaos Orb": 1.0, "Divine Orb": 171.2, "Orb of Alchemy": 0.08,
           "Orb of Scouring": 0.26, "Orb of Chance": 0.06, "Vaal Orb": 0.37,
           "Determination": 3.0, "Molten Strike": 1.4, "Anomalous Haste": 22.0,
           "Toxic Grove Map": 2.0, "Sandy Seabed Map": 0.5,
           "Storm Bite": 14.0, "Beast Coil": 6.5}


def _rare(name: str, base: str, ilvl: int, mods: list[str], x: int, y: int) -> Item:
    return Item.model_validate({
        "id": f"rare-{name}", "name": name, "typeLine": base, "baseType": base,
        "frameType": 2, "ilvl": ilvl, "explicitMods": mods, "x": x, "y": y,
        "identified": True,
        "requirements": [{"name": "Level", "values": [[str(ilvl - 12), 0]]}],
    })


def _currency(name: str, stack: int, x: int, y: int) -> Item:
    return Item.model_validate({
        "id": f"cur-{name}", "typeLine": name, "baseType": name, "frameType": 5,
        "stackSize": stack, "maxStackSize": 5000, "x": x, "y": y,
    })


def _gem(name: str, level: int, quality: int, x: int, y: int) -> Item:
    return Item.model_validate({
        "id": f"gem-{name}", "typeLine": name, "baseType": name, "frameType": 4,
        "x": x, "y": y,
        "properties": [{"name": "Level", "values": [[str(level), 0]]},
                       {"name": "Quality", "values": [[f"+{quality}%", 1]]}],
    })


def _map_item(name: str, tier: int, x: int, y: int) -> Item:
    return Item.model_validate({
        "id": f"map-{name}", "typeLine": name, "baseType": name, "frameType": 0,
        "ilvl": 68 + tier, "x": x, "y": y,
        "properties": [{"name": "Map Tier", "values": [[str(tier), 0]]},
                       {"name": "Item Quantity", "values": [["+64%", 1]]}],
    })


def _price_index() -> PriceIndex:
    index = PriceIndex()
    index._simple.update(_PRICES)
    return index


def _stashes() -> list[StashTab]:
    colours = {"Currency": "aa9a68", "Rares": "d4b800", "Gems": "1ba29b",
               "Maps": "cc66aa"}
    return [StashTab(id=key.lower(), name=key, type="PremiumStash", index=i,
                     metadata={"colour": colours[key]})
            for i, key in enumerate(("Currency", "Rares", "Gems", "Maps"), start=1)]


def _items_by_tab() -> dict[str, list[Item]]:
    return {
        "currency": [_currency(n, s, i % 4, i // 4) for i, (n, s) in enumerate(_CURRENCY)],
        "rares": [_rare(n, b, lvl, mods, i % 5, i // 5)
                  for i, (n, b, lvl, mods) in enumerate(_RARES)],
        "gems": [_gem(n, lv, q, i, 0) for i, (n, lv, q) in enumerate(_GEMS)],
        "maps": [_map_item(n, t, i, 0) for i, (n, t) in enumerate(_MAPS)],
    }


def _characters() -> list[Character]:
    return [
        Character.model_validate({"name": "Demo Ranger", "league": LEAGUE, "classId": 5,
                                  "ascendancyClass": 1, "class": "Deadeye", "level": 96,
                                  "experience": 4_250_334_444}),
        Character.model_validate({"name": "Demo Witch", "league": LEAGUE, "classId": 1,
                                  "ascendancyClass": 2, "class": "Occultist", "level": 88,
                                  "experience": 1_998_112_003}),
    ]


def _socketed_gem(level: int) -> dict:
    """Sockel-Gem im Aufbau der echten API-Daten (Rohfeld, kein eigenes
    Modell — siehe ARCHITEKTUR.md §4.33). Steigt zwischen den beiden
    Ständen unten um eine Stufe und erzeugt damit im dritten Bild die
    GRÜNE Hervorhebung, die es sonst nirgends zu sehen gäbe."""
    return {
        # Bewusst NICHT "Molten Strike": Das steht unten im Verlauf und
        # sähe aus, als hinge beides zusammen.
        "id": "demo-gem-1", "typeLine": "Blade Vortex", "socket": 0, "colour": "B",
        "properties": [{"name": "Level", "values": [[str(level), 0]], "displayMode": 0}],
        "additionalProperties": [
            {"name": "Experience", "values": [[f"{level * 1_000_000}/226180911", 0]],
             "progress": 0.42, "displayMode": 2},
        ],
    }


def _character_items(before: bool) -> list[Item]:
    """Zwei Stände desselben Inventars — der Unterschied erzeugt im dritten
    Bild die Türkis-/Grün-/Grau-Hervorhebung, um die es dort geht."""
    worn = [
        _rare("Dread Veil", "Lion Pelt", 84, ["+96 to maximum Life"], 0, 0),
        _rare("Vaal Regalia", "Vaal Regalia", 81, ["+112 to maximum Energy Shield"], 0, 0),
        _rare("Beast Coil", "Amethyst Ring", 86, ["+38 to maximum Life"], 0, 0),
    ]
    for item, slot in zip(worn, ("Helm", "BodyArmour", "Ring")):
        item.inventoryId = slot
    worn[1].socketedItems = [_socketed_gem(19 if before else 20)]
    if before:
        bag = [_currency("Chaos Orb", 39, 0, 0), _currency("Orb of Alchemy", 88, 1, 0),
               _rare("Rift Clasp", "Onyx Amulet", 83, ["+21 to all Attributes"], 2, 0)]
    else:
        # Chaos Orbs sind mehr geworden, das Amulett ist weg, zwei Dinge neu.
        bag = [_currency("Chaos Orb", 44, 0, 0), _currency("Orb of Alchemy", 88, 1, 0),
               _map_item("Toxic Grove Map", 14, 3, 0),
               _rare("Storm Bite", "Vaal Axe", 82,
                     ["Adds 18 to 340 Lightning Damage"], 4, 0)]
    for item in bag:
        item.inventoryId = "MainInventory"
    return worn + bag


# --------------------------------------------------------------------- #

def _build_window() -> MainWindow:
    win = MainWindow()
    win.resize(1500, 820)
    # Der BootstrapJob findet (absichtlich) kein Token und meldet "No valid
    # token — please log in". Diese Meldung soll die Bilder nicht erreichen;
    # die Verbindung wird deshalb gekappt, statt den gesetzten Zustand
    # hinterher immer wieder zu reparieren. Der Worker läuft weiter, hat
    # aber nichts mehr zu tun — es wird kein Job abgeschickt.
    win.worker.login_required.disconnect(win._on_login_required)
    win.worker.status.disconnect(win._on_status)
    items = _items_by_tab()
    now = datetime.now(timezone.utc)

    win._account_name = ACCOUNT
    win._logged_in = True
    win._login_button.setText(f"⚷ {ACCOUNT}")
    win._current_league = LEAGUE
    win._stash_trees[LEAGUE] = _stashes()
    win._leaf_stashes = list(win._stash_trees[LEAGUE])
    win._items[LEAGUE] = items
    win._last_loaded[LEAGUE] = {
        sid: (now - timedelta(minutes=7 + i * 3)).isoformat()
        for i, sid in enumerate(items)
    }
    win._all_characters = _characters()
    win._character_items = {"Demo Ranger": _character_items(before=False)}

    win._league_combo.blockSignals(True)
    win._league_combo.clear()
    win._league_combo.addItem(LEAGUE)
    win._league_combo.blockSignals(False)
    win.tree.set_stashes(win._stash_trees[LEAGUE], win._last_loaded[LEAGUE],
                         {sid: len(v) for sid, v in items.items()},
                         win._tab_positions())
    win.character_list.set_characters(win._all_characters)
    win.table_model.set_price_index(_price_index())
    win.history_model.set_price_index(_price_index())
    # Weniger Spalten als die Voreinstellung: Sonst schiebt die volle
    # Breite (Level/Qual./Str/Dex/Int) ausgerechnet die Value-Spalte aus
    # dem Bild — die, von der der README-Text daneben handelt. Gezeigt
    # wird damit auch, dass die Spaltenauswahl konfigurierbar ist.
    win._apply_column_config(_COLUMN_CONFIG)

    # Zonenanzeige und Rate-Limit-Dashboard sind Teil der Oberfläche und
    # sollen deshalb gefüllt sein — beides ohne Netzwerk, direkt gesetzt.
    win._zone_label.setText("The Demo Sands")
    win.worker.rate_limiter.update_from_headers({
        "X-Rate-Limit-Policy": "stash-request-limit",
        "X-Rate-Limit-Rules": "Account",
        "X-Rate-Limit-Account": "15:10:60,30:300:1800",
        "X-Rate-Limit-Account-State": "3:10:0,12:300:0",
    })
    win._on_rate_limit_changed(*win.worker.rate_limiter.snapshot())
    return win


def _demo_session_state(win: MainWindow) -> None:
    """Angemeldeter Zustand, vor jeder Aufnahme gesetzt."""
    win._logged_in = True
    win._login_button.setText(f"⚷ {ACCOUNT}")
    win._update_online_controls_enabled()
    # "unchanged for" (§4.31) im Bild zeigen, ohne minutenlang zu warten.
    # Zweimal aufrufen: Der erste Aufruf merkt sich den Inhalt und setzt
    # den Zeitpunkt dabei auf jetzt — erst danach lässt er sich
    # zurückdatieren, ohne gleich wieder überschrieben zu werden.
    win._note_view_updated()
    win._view_content_since = datetime.now() - timedelta(minutes=6)
    win._note_view_updated()
    win._update_refresh_status()


def _row_of(win: MainWindow, display_name: str) -> int:
    """Zeilennummer eines Items in der ANGEZEIGTEN (gefilterten,
    sortierten) Reihenfolge — feste Indizes wären beim nächsten
    Datenzusatz still falsch."""
    for row in range(win.proxy.rowCount()):
        item = win.table_model.item_at(win.proxy.mapToSource(win.proxy.index(row, 0)).row())
        if item is not None and item.display_name == display_name:
            return row
    raise LookupError(f"{display_name!r} steht nicht in der Tabelle")


def _shot(win: MainWindow, name: str) -> None:
    app = QApplication.instance()
    _demo_session_state(win)
    # Nach dem Setzen der Texte MUSS das Layout noch einmal laufen: Sonst
    # behält die Statuszeile die Breiten von vorher und schneidet den
    # längeren Text ab — real passiert: "unchanged for 6m" stand im Label
    # und fehlte trotzdem im Bild.
    for _ in range(3):
        app.processEvents()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    assert win.grab().save(str(path)), f"{name} ließ sich nicht schreiben"
    print(f"  {path.relative_to(OUT.parent.parent)}  ({path.stat().st_size // 1024} KB)")


def _overview(win: MainWindow) -> None:
    """Liga-weite Suche: alle Fächer und Charaktere in EINER Tabelle."""
    win._filter_edit.setText("*")
    win._enter_search_all()
    win._apply_debounced_search_filter()
    win._note_view_updated()
    win._update_refresh_status()
    _shot(win, "uebersicht.png")


def _item_details(win: MainWindow) -> None:
    """Ein einzelnes Fach mit ausgewähltem Item und seinen Mods."""
    win._filter_edit.clear()
    win._search_all_active = False
    win._current_stash_id = "rares"
    win._current_tab_name = "Rares"
    win._show_items("rares", win._items[LEAGUE]["rares"], "Rares")
    win.table.selectRow(5)
    win._on_row_selected(win.proxy.index(5, 0), None)
    win._note_view_updated()
    _shot(win, "item-details.png")


def _character_history(win: MainWindow) -> None:
    """Charakter-Inventar nach einem Refresh: Hervorhebung + Verlauf."""
    win._current_stash_id = None
    win._current_character_name = "Demo Ranger"
    before, after = _character_items(before=True), _character_items(before=False)
    # Erst die Vergleichsbasis dieser "Sitzung" setzen, dann den neuen
    # Stand — sonst unterdrückt der Schutz gegen gecachte Vergleichsbasen
    # die Hervorhebung, genau wie im echten Betrieb (§4.29).
    win._session_fetched_chars.add("Demo Ranger")
    win._character_items["Demo Ranger"] = before
    win._on_character_items("Demo Ranger", after, silent=False)

    now = datetime.now(timezone.utc)
    win.history_model.set_entries([
        HistoryEntry(now - timedelta(seconds=8), "added", "Demo Ranger", after[-1]),
        HistoryEntry(now - timedelta(seconds=8), "added", "Demo Ranger", after[-2]),
        HistoryEntry(now - timedelta(seconds=8), "changed", "Demo Ranger", after[3], 5),
        HistoryEntry(now - timedelta(seconds=8), "removed", "Demo Ranger", before[-1]),
        HistoryEntry(now - timedelta(minutes=4), "added", "Demo Witch",
                     _currency("Divine Orb", 1, 0, 0)),
        HistoryEntry(now - timedelta(minutes=6), "removed", "Demo Witch",
                     _gem("Molten Strike", 20, 23, 0, 0)),
    ])
    # Verlaufs-Panel aufziehen: Es ist im Betrieb auf eine Zeile
    # eingeklappt, für das Bild soll es zeigen, was es kann.
    splitter = win.history_table.parent()
    if isinstance(splitter, QSplitter):
        splitter.setSizes([460, 260])
    # Ein Item AUS DIESER Ansicht auswählen: Sonst zeigt das Detail-Panel
    # noch den Fund aus dem vorigen Bild, der hier gar nicht vorkommt.
    row = _row_of(win, "Storm Bite")
    win.table.selectRow(row)
    win._on_row_selected(win.proxy.index(row, 0), None)
    win._note_view_updated()
    _shot(win, "charakter-verlauf.png")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    win = _build_window()
    win.show()
    print("Screenshots aus erfundenen Daten:")
    _overview(win)
    _item_details(win)
    _character_history(win)
    win.worker.stop()
    win.worker.wait(5000)
    app.processEvents()


if __name__ == "__main__":
    main()
