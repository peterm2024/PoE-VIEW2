"""Tests für den Charakterbogen-Export (Peter, 2026-08-21: "eine Hommage
... im Stile der alten Pen&Paper RPGs"). Reine Textfunktion, kein Qt
nötig — wie ``external_tools.item_export_text``.
"""

from __future__ import annotations

from poe_view.api.models import Character, Item
from poe_view.ui.character_sheet import build_character_sheet


def _char(**kwargs) -> Character:
    daten = {"name": "TestHeld", "class": "Trickster", "level": 42}
    daten.update(kwargs)
    return Character.model_validate(daten)


def _item(slot: str, name: str = "Something", **kwargs) -> Item:
    return Item.model_validate({"typeLine": name, "baseType": name,
                                "inventoryId": slot, **kwargs})


def _gem(name: str, level: str, colour: str = "S", progress: float | None = None) -> dict:
    gem: dict = {"typeLine": name, "colour": colour, "frameType": 4,
                "properties": [{"name": "Level", "values": [[level, 0]]}]}
    if progress is not None:
        gem["additionalProperties"] = [
            {"name": "Experience", "values": [["1/2", 0]], "progress": progress}]
    return gem


# ------------------------------- Kopf ------------------------------------ #

def test_der_kopf_nennt_name_klasse_stufe_und_liga():
    text = build_character_sheet(_char(league="Standard"), [])
    assert "# TestHeld" in text
    assert "Trickster — Level 42 — Standard" in text


def test_ohne_liga_faellt_der_bindestrich_weg():
    text = build_character_sheet(_char(league=None), [])
    assert "Standard" not in text
    assert "Trickster — Level 42" in text
    assert "Trickster — Level 42 —" not in text


def test_die_live_beobachtete_stufe_ueberschreibt_character_level():
    """``level``/``experience`` kommen aus ``_XpWatch`` und sind aktueller
    als das, was der Charakter-Endpunkt zuletzt lieferte."""
    text = build_character_sheet(_char(level=1), [], level=99)
    assert "Level 99" in text
    assert "Level 1" not in text


def test_ohne_erfahrung_wird_keine_unbekannte_zahl_behauptet():
    text = build_character_sheet(_char(), [])
    assert "XP total" not in text


def test_die_erfahrung_wird_wie_im_leveling_feld_formatiert():
    """Dieselbe Formatierung wie ``leveling_panel.py``: normales
    Leerzeichen als Tausendertrennzeichen, kein schmales."""
    text = build_character_sheet(_char(), [], experience=2_006_431_775)
    assert "XP total: 2 006 431 775" in text


# ---------------------------- Ausruestung --------------------------------- #

def test_jeder_kernslot_erscheint_auch_leer():
    """Ein Papierbogen zeigt die Silhouette vollständig — leer bleibt
    sichtbar, statt zu verschwinden."""
    text = build_character_sheet(_char(), [])
    assert "| Weapon | — | — | — |" in text
    assert "| Boots | — | — | — |" in text


def test_ein_ausgeruestetes_item_erscheint_im_richtigen_slot():
    text = build_character_sheet(_char(), [_item("Helm", "Lion Pelt")])
    assert "| Helmet | Lion Pelt |" in text


def test_rarity_und_basistyp_stehen_dabei():
    item = _item("BodyArmour", "Shroud of the Lightless", baseType="Occultist's Vestment",
                frameType=3)
    text = build_character_sheet(_char(), [item])
    assert "Shroud of the Lightless (Occultist's Vestment)" in text
    assert "| Unique |" in text


def test_moddzeilen_werden_mit_html_umbruch_zusammengefasst():
    """Eine Markdown-Tabellenzelle kennt keine echten Zeilenumbrüche —
    ``<br>`` ist der uebliche Ausweg (GitHub-Flavored Markdown, funktioniert
    auch beim Drucken über den Browser)."""
    item = _item("Amulet", explicitMods=["+10 to Strength", "+20 to Dexterity"])
    text = build_character_sheet(_char(), [item])
    assert "+10 to Strength<br>+20 to Dexterity" in text


def test_tausch_slots_erscheinen_nur_wenn_belegt():
    ohne = build_character_sheet(_char(), [])
    assert "Weapon (swap)" not in ohne

    mit = build_character_sheet(_char(), [_item("Weapon2", "Rustic Sash")])
    assert "Weapon (swap)" in mit
    assert "Rustic Sash" in mit


def test_trinket_erscheint_nur_wenn_getragen():
    ohne = build_character_sheet(_char(), [])
    assert "Trinket" not in ohne

    mit = build_character_sheet(_char(), [_item("Trinket", "Lucky Charm")])
    assert "Trinket" in mit


def test_flaschen_stehen_in_positionsreihenfolge():
    flaschen = [_item("Flask", "Zweite", x=1), _item("Flask", "Erste", x=0)]
    text = build_character_sheet(_char(), flaschen)
    assert text.index("Erste") < text.index("Zweite")


def test_inventar_items_landen_nicht_auf_dem_bogen():
    """Nur getragene Ausruestung — der Rucksack ist kein Slot."""
    text = build_character_sheet(_char(), [_item("MainInventory", "Sollte fehlen")])
    assert "Sollte fehlen" not in text


# -------------------------------- Gems ------------------------------------ #

def test_ohne_sockel_gems_steht_ein_hinweis():
    text = build_character_sheet(_char(), [_item("Helm", "Leerer Helm")])
    assert "No socketed gems" in text


def test_ein_gem_erscheint_unter_seinem_ausruestungsteil():
    item = _item("Weapon", "Darkwood Sceptre",
                socketedItems=[_gem("Fireball", "4", "I", progress=0.57)])
    text = build_character_sheet(_char(), [item])
    assert "### Weapon — Darkwood Sceptre" in text
    assert "[Int] Fireball — level 4, 57% to next" in text


def test_das_attribut_kuerzel_wird_ausgeschrieben():
    """S/D/I aus GGGs ``colour``-Feld werden Str/Dex/Int — die Kürzel
    allein sagen einem Fremden nichts."""
    item = _item("Weapon", socketedItems=[
        _gem("Rot", "1", "S", progress=0.1), _gem("Gruen", "1", "D", progress=0.1),
        _gem("Blau", "1", "I", progress=0.1)])
    text = build_character_sheet(_char(), [item])
    assert "[Str] Rot" in text
    assert "[Dex] Gruen" in text
    assert "[Int] Blau" in text


def test_gems_ohne_bekanntes_attribut_bleiben_ohne_tag():
    item = _item("Weapon", socketedItems=[_gem("Grau", "1", "G", progress=0.1)])
    text = build_character_sheet(_char(), [item])
    assert "] Grau" not in text
    assert "- Grau — level 1" in text


def test_ein_fertiges_gem_traegt_kein_prozent():
    """Nutzt dieselbe ``tooltip``-Eigenschaft wie der Gem-Balken — die
    Formulierung darf hier nicht auseinanderlaufen."""
    item = _item("Weapon", socketedItems=[_gem("Quickstep", "1 (Max)", "G")])
    text = build_character_sheet(_char(), [item])
    assert "Quickstep — level 1 (Max)" in text
    assert "% to next" not in text


def test_leere_slots_bekommen_keinen_gem_abschnitt():
    """Nur der belegte Slot bekommt eine Ueberschrift — ein leerer Slot
    (hier: alles ausser Weapon) erzeugt keine, auch wenn ``by_slot`` fuer
    ihn ``None`` zurueckgibt."""
    item = _item("Weapon", "Darkwood Sceptre",
                socketedItems=[_gem("Fireball", "4", "I", progress=0.5)])
    text = build_character_sheet(_char(), [item])
    ueberschriften = [z for z in text.splitlines() if z.startswith("###")]
    assert ueberschriften == ["### Weapon — Darkwood Sceptre"]


def test_mehrere_gems_im_selben_item_stehen_untereinander():
    item = _item("BodyArmour", socketedItems=[
        _gem("Erstes", "5", "I", progress=0.2), _gem("Zweites", "3", "I", progress=0.1)])
    text = build_character_sheet(_char(), [item])
    assert text.index("Erstes") < text.index("Zweites")
