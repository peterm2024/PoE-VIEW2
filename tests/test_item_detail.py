"""Tests für das Item-Detail-Panel: Tag-Zeile (Unidentified/Corrupted)
und die Anforderungs-Zeile (iLvl/Req.Lvl/Str/Dex/Int)."""

from poe_view.api.models import Item
from poe_view.ui.item_detail import (_MAX_UNITS, ItemDetail, _blocks_to_html,
                                     _item_blocks)


def _item(**kwargs) -> Item:
    return Item.model_validate({"typeLine": "Sun Plate", "frameType": 2, **kwargs})


def test_identified_item_shows_no_tag(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(identified=True), None)
    assert "[" not in detail._name.text()


def test_unidentified_item_is_tagged(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(identified=False), None)
    assert "[Unidentified]" in detail._name.text()


def test_corrupted_item_is_tagged(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(corrupted=True), None)
    assert "[Corrupted]" in detail._name.text()


def test_unidentified_and_corrupted_both_shown(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(identified=False, corrupted=True), None)
    assert "[Unidentified, Corrupted]" in detail._name.text()


def test_requirement_line_shows_ilvl_and_req_level(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(ilvl=82, requirements=[{"name": "Level", "values": [["68", 0]]}]), None)
    assert "iLvl 82" in detail._props.text()
    assert "Req. Lvl 68" in detail._props.text()


def test_requirement_line_shows_attribute_requirements(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(requirements=[
        {"name": "Str", "values": [["155", 0]]},
        {"name": "Dex", "values": [["50", 0]]},
    ]), None)
    props = detail._props.text()
    assert "Req. Str 155" in props
    assert "Req. Dex 50" in props
    assert "Req. Int" not in props


def test_requirement_line_absent_when_nothing_known(qapp) -> None:
    detail = ItemDetail()
    detail.show_item(_item(), None)
    lines = detail._props.text().split("\n")
    assert not any("iLvl" in line or "Req." in line for line in lines)


# --- Gliederung in Bloecke (Peter, 2026-08-12: "etwas uebersichtlicher") --- #

def _blocks(item: Item) -> list[list[str]]:
    """Nur die Texte — die Marke prueft ``_blocks_mit_marke`` weiter
    unten, hier geht es um die Gliederung."""
    from poe_view.ui.item_detail import _item_blocks
    return [[zeile.text for zeile in b] for b in _item_blocks(item) if b]


def test_the_implicit_mod_is_its_own_block() -> None:
    """Der Kern der Ueberarbeitung. Vorher lief alles als flache Liste
    untereinander, und WELCHER Mod der implizite ist, war ueberhaupt
    nicht zu erkennen — im Spiel trennt ihn eine Linie ab."""
    blocks = _blocks(Item.model_validate({
        "typeLine": "Opal Sceptre", "name": "Soul Bane", "frameType": 2,
        "implicitMods": ["40% increased Elemental Damage"],
        "explicitMods": ["69% increased Fire Damage", "+109 to maximum Mana"],
    }))

    assert ["40% increased Elemental Damage"] in blocks
    assert ["69% increased Fire Damage", "+109 to maximum Mana"] in blocks


def test_properties_requirements_and_mods_are_separate_blocks() -> None:
    blocks = _blocks(Item.model_validate({
        "typeLine": "Opal Sceptre", "name": "Soul Bane", "frameType": 2, "ilvl": 70,
        "properties": [{"name": "Quality", "values": [["+20%", 1]]}],
        "requirements": [{"name": "Level", "values": [["68", 0]]}],
        "explicitMods": ["+109 to maximum Mana"],
    }))

    assert blocks == [
        ["Rare · Opal Sceptre"],
        ["Quality: +20%"],
        ["iLvl 70 · Req. Lvl 68"],
        ["+109 to maximum Mana"],
    ]


def test_enchantments_and_utility_mods_are_shown_at_all() -> None:
    """Dieselbe Luecke wie im Item-Textexport: Das Panel kannte nur
    explicitMods und implicitMods. Ein verzauberter Helm und jede
    Utility-Flasche zeigten ihren eigentlichen Inhalt gar nicht."""
    blocks = _blocks(Item.model_validate({
        "typeLine": "Granite Flask", "frameType": 1,
        "enchantMods": ["Adds 4 Passive Skills"],
        "implicitMods": ["10% increased Frenzy Charge Duration"],
        "utilityMods": ["+1500 to Armour"],
    }))

    # Verzauberung ueber dem impliziten Mod, Flaschen-Effekt bei den
    # expliziten — dieselbe Aufteilung wie im Textexport.
    assert blocks[-3:] == [
        ["Adds 4 Passive Skills"],
        ["10% increased Frenzy Charge Duration"],
        ["+1500 to Armour"],
    ]


def test_truncation_says_that_it_truncated(qapp) -> None:
    """Der eigentliche Mangel der alten Fassung war nicht die Grenze,
    sondern dass sie STILL zuschlug: Peters "Pain Crusher" lag mit exakt
    zwoelf Zeilen auf der Kante, ein Mod mehr waere wortlos verschwunden."""
    detail = ItemDetail()
    detail.show_item(Item.model_validate({
        "typeLine": "Sun Plate", "frameType": 2,
        "explicitMods": [f"Mod {n}" for n in range(40)]}), None)

    text = detail._props.text()
    assert "more" in text and "double-click" in text


def test_nothing_is_cut_off_silently_below_the_limit(qapp) -> None:
    """Gegenprobe: Solange es passt, taucht der Hinweis nicht auf."""
    detail = ItemDetail()
    detail.show_item(Item.model_validate({
        "typeLine": "Sun Plate", "frameType": 2,
        "explicitMods": ["+43 to Armour", "+27 to maximum Life"]}), None)

    assert "more" not in detail._props.text()


def test_mod_text_is_escaped_for_the_rich_text_label(qapp) -> None:
    """Das Panel rendert seit der Gliederung HTML (fuer die Trennlinien).
    Ein Mod-Text mit spitzen Klammern darf dadurch nicht als Markup
    gedeutet werden und verschwinden."""
    detail = ItemDetail()
    detail.show_item(Item.model_validate({
        "typeLine": "Sun Plate", "frameType": 2,
        "explicitMods": ["Deals <b>50</b> Damage"]}), None)

    assert "&lt;b&gt;" in detail._props.text()


def test_the_panel_height_does_not_change_with_the_item(qapp) -> None:
    """Peter, 2026-08-13: "Koennen wir den XP-Bereich unten
    ausrichten/fixieren? Dann wackelt das beim Item-Wechsel nicht so
    rum." Ein Ring mit zwei Mods und ein Unique mit acht liessen das
    Panel sonst bei jedem Klick springen — und mit ihm das Leveling-Feld
    daneben und den unteren Rand der Tabelle darueber."""
    detail = ItemDetail()
    hoehen = set()
    for mods in ([], ["+43 to Armour"], [f"Mod {n}" for n in range(30)]):
        detail.show_item(Item.model_validate({
            "typeLine": "Sun Plate", "frameType": 2, "explicitMods": mods}), None)
        hoehen.add(detail.height())

    assert len(hoehen) == 1


def test_the_panel_is_at_least_as_tall_as_its_own_icon(qapp) -> None:
    """Gegenprobe zur festen Hoehe: Ein Currency-Item ohne Mods darf das
    Panel nicht kleiner machen als das Bild, das darin steht."""
    assert ItemDetail().height() >= 64


def test_the_preferred_width_fits_a_typical_mod_line(qapp) -> None:
    """Grundlage der Splitter-Position (Peter: "anhand der Zeilenbreite
    berechnen"). Gemessen an 201.426 echten Mod-Zeilen passen 95 % in 68
    Zeichen; die Breite muss also mindestens so viel Text plus Icon
    fassen."""
    detail = ItemDetail()
    metrics = detail._props.fontMetrics()

    assert detail.preferred_width() >= metrics.averageCharWidth() * 68 + 64


# --- Hoehenbudget: Textzeilen UND Trennlinien (Peter, 2026-08-13) ------- #

def _einheiten(html: str) -> int:
    """Was das HTML an Zeilenhoehen kostet. Jedes ``<br>`` und jedes
    ``<hr>`` beginnt eine neue Textzeile, und jedes ``<hr>`` kostet
    zusaetzlich seine eigene (gemessene) Zeilenhoehe."""
    zeilen = html.count("<br>") + html.count("<hr>") + 1
    return zeilen + html.count("<hr>")


def _foe_portent() -> Item:
    """Peters Karte aus dem Screenshot vom 2026-08-13, bei der die letzte
    Mod-Zeile auf dem Rahmenrand stand."""
    return Item.model_validate({
        "id": "map-1", "name": "Foe Portent", "typeLine": "Waterways Map",
        "baseType": "Waterways Map", "frameType": 2, "ilvl": 69, "identified": True,
        "properties": [
            {"name": "Map Tier", "values": [["6", 0]]},
            {"name": "Item Quantity", "values": [["+68%", 1]]},
            {"name": "Item Rarity", "values": [["+78%", 1]]},
            {"name": "Monster Pack Size", "values": [["+26%", 1]]},
            {"name": "More Currency", "values": [["+94%", 1]]}],
        "enchantMods": ["Area is Influenced by the Originator's Memories"],
        "explicitMods": ["29% more Monster Life", "Monsters cannot be Stunned",
                         "Monsters' Action Speed cannot be modified to below Base Value",
                         "Monsters' Movement Speed cannot be modified to below Base Value",
                         "Monsters have 50% increased Accuracy Rating"],
    })


def test_a_five_block_map_fits_without_being_cut(qapp) -> None:
    """Peter, 2026-08-13: "und eine abgeschnittene Info....". Diese Karte
    braucht 13 Textzeilen in 5 Bloecken, also 17 Zeilenhoehen — die
    Fassung davor rechnete nur die 13 und schlug pauschal drei fuer
    Namenszeile und Linien drauf. Sie lief damit ueber den Rahmen, ohne
    es zu melden."""
    html = _blocks_to_html(_item_blocks(_foe_portent()))

    assert _einheiten(html) == 17
    assert "more (double-click" not in html          # nichts fehlt
    assert "Monsters have 50% increased Accuracy Rating" in html


def test_the_budget_counts_separators_not_just_lines(qapp) -> None:
    """Der Kern der Korrektur: Eine ``<hr>`` kostet gemessene 16 px, also
    eine volle Zeilenhoehe. Ein Item mit vielen kleinen Bloecken passt
    deshalb WENIGER Text als eines mit einem grossen — vorher wurden
    beide gleich behandelt."""
    viele_bloecke = _blocks_to_html([[f"Block {i}"] for i in range(6)]
                                    + [[f"Mod {i}" for i in range(20)]])
    ein_block = _blocks_to_html([[f"Mod {i}" for i in range(40)]])

    assert _einheiten(viele_bloecke) <= _MAX_UNITS
    assert _einheiten(ein_block) <= _MAX_UNITS
    # Der Block-reiche Fall zeigt weniger TEXT, weil die Linien mitzahlen.
    assert viele_bloecke.count("<br>") < ein_block.count("<br>")


def test_the_truncation_note_is_paid_for_out_of_the_budget(qapp) -> None:
    """Der Hinweis braucht selbst eine Zeile. Wird er nicht eingeplant,
    schiebt ausgerechnet die Meldung ueber das Abschneiden das Panel
    ueber seine feste Hoehe — der Fehler haette sich damit selbst
    verlaengert."""
    html = _blocks_to_html([[f"Mod {i}" for i in range(60)]])

    assert "more (double-click" in html
    assert _einheiten(html) <= _MAX_UNITS


def test_the_panel_is_tall_enough_for_its_own_budget(qapp) -> None:
    """Gegenprobe in Pixeln statt in Einheiten: Was das Budget zulaesst,
    muss auch hineinpassen. Genau diese Zusicherung fehlte."""
    panel = ItemDetail()
    zeile = panel._props.fontMetrics().lineSpacing()
    raender = (panel.layout().contentsMargins().top()
               + panel.layout().contentsMargins().bottom()
               + panel.layout().spacing())

    assert panel._full_height() >= (_MAX_UNITS + 1) * zeile + raender


# ---------------- Marken der Mod-Sammlung (§4.52) ---------------------- #

def test_only_mod_lines_get_a_mark() -> None:
    """Die Marke gehoert an die Mods, nicht an Eigenschaften oder
    Anforderungen — dort gibt es nichts zu sammeln."""
    from poe_view.api.models import Item
    from poe_view.ui.item_detail import _item_blocks

    item = Item.model_validate({
        "typeLine": "Gold Ring", "frameType": 2, "ilvl": 84,
        "implicitMods": ["+20% to Fire Resistance"],
        "explicitMods": ["+96 to maximum Life"],
    })

    bloecke = _item_blocks(item, lambda kind, line: "* ")
    flach = [zeile for block in bloecke for zeile in block]
    markiert = {zeile.text for zeile in flach if zeile.mark}

    assert markiert == {"+96 to maximum Life", "+20% to Fire Resistance"}
    assert not any(zeile.mark for zeile in flach if zeile.text.startswith("iLvl"))
    assert not any(zeile.mark for zeile in flach if zeile.text.startswith("Rare"))


def test_the_mark_knows_which_list_a_line_came_from() -> None:
    """Dieselbe Zeile bedeutet als Flaschen-Mod etwas anderes als als
    Affix. Ohne das Feld koennte die Sammlung sie nicht auseinanderhalten
    — und ohne ``all_extra_mod_pairs`` waere es beim Weg durchs Panel
    verloren gegangen."""
    from poe_view.api.models import Item
    from poe_view.ui.item_detail import _item_blocks

    flasche = Item.model_validate({
        "typeLine": "Quicksilver Flask", "frameType": 1,
        "utilityMods": ["25% increased Movement Speed"],
    })
    gesehen: list[str] = []
    _item_blocks(flasche, lambda kind, line: gesehen.append(kind) or "")

    assert gesehen == ["utilityMods"]


def test_the_mark_stays_html_while_the_mod_text_is_escaped() -> None:
    """Die Grenze, um die es bei ``Line`` geht. Die Balkenspalte MUSS als
    Markup durchkommen, sonst stuenden ``<span ...>`` als Text im Panel;
    der Mod-Text darf es NICHT, denn er kommt von GGGs Server."""
    from poe_view.ui.item_detail import Line, _blocks_to_html

    html = _blocks_to_html([[Line("+96 to <b>maximum</b> Life",
                                  '<span style="color:#fff">|</span>')]])

    assert '<span style="color:#fff">|</span>' in html
    assert "&lt;b&gt;maximum&lt;/b&gt;" in html
    assert "<b>" not in html


def test_a_bare_string_is_a_line_without_a_mark() -> None:
    """Damit die Tests des Hoehenbudgets mit ``[["Mod 1"]]`` lesbar
    bleiben — und ein blanker String nirgends unescaped durchrutscht."""
    from poe_view.ui.item_detail import _blocks_to_html

    assert "&lt;b&gt;" in _blocks_to_html([["<b>"]])


def test_the_preferred_width_leaves_room_for_the_bar_column(qapp) -> None:
    """Die Spalte steht VOR der Mod-Zeile. Wuerde sie nicht aufgeschlagen,
    knabberte sie die 68 Zeichen an, fuer die das Panel bemessen ist."""
    from poe_view.ui import mod_bar

    detail = ItemDetail()
    metrics = detail._props.fontMetrics()
    spalte = metrics.horizontalAdvance(mod_bar.CELL * (mod_bar.BAR_CELLS + 2))

    assert spalte > 0
    assert detail.preferred_width() >= metrics.averageCharWidth() * 68 + 64 + spalte



def test_the_tail_lands_after_the_escaped_text_and_is_not_escaped() -> None:
    """Das Tier-Etikett (§4.53.4) ist fertiges HTML HINTER der Zeile —
    der Mod-Text davor bleibt escaped."""
    item = Item.model_validate({"typeLine": "Gold Ring", "frameType": 2,
                                "explicitMods": ["+96 to <b>maximum</b> Life"]})
    bloecke = _item_blocks(item, tail=lambda kind, line: '<span>T1</span>')

    html = _blocks_to_html(bloecke)

    assert "&lt;b&gt;maximum&lt;/b&gt; Life<span>T1</span>" in html


def test_base_stat_lines_get_the_bar_column_and_the_rest_a_blank_one() -> None:
    """Hauptwerte (§4.52.8) bekommen die Balkenspalte wie Mod-Zeilen; die
    uebrigen Eigenschaften eine leere Spalte derselben Breite, damit
    der Block buendig bleibt."""
    item = Item.model_validate({
        "typeLine": "Plate Vest", "frameType": 2, "ilvl": 70,
        "properties": [{"name": "Armour", "values": [["668", 0]]},
                       {"name": "Quality", "values": [["+7%", 1]]}]})

    bloecke = _item_blocks(item, mark=lambda kind, line: f"[{kind}|{line}]")

    eigenschaften = bloecke[1]
    assert eigenschaften[0].mark == "[baseStats|Body Armour: Armour 668]"
    assert eigenschaften[1].mark == "[baseStats|]"
    assert _item_blocks(item)[1][0].mark == ""      # ohne Marken-Funktion nichts
