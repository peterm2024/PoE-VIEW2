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

import re
import time
from functools import lru_cache
from html import escape as html_escape
from typing import Callable

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRect, QSize,
                            QSortFilterProxyModel, Qt)
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListView, QPushButton,
                               QSplitter, QStackedWidget, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem,
                               QTableView, QTextEdit, QVBoxLayout, QWidget)

from poe_view.api.models import (ENCHANT_MOD_FIELD, EXTRA_MOD_FIELDS,
                                 FRAME_TYPE_NAMES)
from poe_view.services import mod_tiers
from poe_view.services.mod_knowledge import tier_number  # noqa: F401 — Tests importieren es von hier
from poe_view.services.mod_collection import (LEGACY_LEAGUE, MAP_RARITY,
                                              UNKNOWN_RARITY, ModCollection,
                                              ModRecord, RaritySpan, base_rarity,
                                              is_corrupted_bucket, league_bucket)
from poe_view.ui import mod_bar
from poe_view.ui.theme import DASH_WARN, ROW_CHANGED_COLOR

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
    # Foil (10) zaehlt zu Unique: Valdos Foil-Uniques sind Uniques mit
    # Regenbogen-Rahmen, keine eigene Item-Klasse. Ohne diese Zeile
    # fiele frameType 10 in gar keine Filter-Gruppe.
    ("Unique", lambda r: r in (3, 10)),
    ("Corrupted", is_corrupted_bucket),
    ("Map", lambda r: r == MAP_RARITY),
    ("Gem / Currency / Card / Relic", lambda r: r in (4, 5, 6, 9)),
    ("Unknown rarity", lambda r: r == UNKNOWN_RARITY),
)
# Die Vorwahl beim Öffnen: die gerollten Items — das ist die Gruppe, um
# die es im Sammelalbum geht (Peter, 2026-08-29).
DEFAULT_RARITY_GROUP = RARITY_GROUPS[0][0]
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


def band_table(konto: dict[float, list[int]],
               baender: list[mod_tiers.Band]) -> list[str]:
    """Peters Tabelle (2026-08-27): je Band eine Zeile mit Sichtungen,
    Wert-Spanne und iLvl-Spanne aus dem Kontenbuch.

    **Die Bänder heißen Prozent, nicht T-Nummern** — Peters eigene
    Begründung: Nummern wären mit den Ingame-Tiers verwechselbar, und
    gerade am Anfang stimmen sie noch nicht. Prozent der gesehenen
    Spanne trägt keine solche Behauptung; sobald genug Daten das echte
    Tier-System hergeben, wird umbenannt.

    Jeder Wert des Kontos gehört zum ERSTEN Band, dessen Obergrenze er
    nicht übersteigt — so fällt auch ein halbzahliger Wert zwischen zwei
    ganzzahligen Grenzen nicht durch."""
    werte = sorted(konto)
    achse_lo, achse_hi = werte[0], baender[-1].high
    spannweite = (achse_hi - achse_lo) or 1.0

    def pct(wert: float) -> int:
        return round((wert - achse_lo) / spannweite * 100)

    zeilen = [f"{'Band':<11}{'Seen':>5}  {'Values':<14}Item levels"]
    zeiger = 0
    for band in baender:
        lo_eff = achse_lo if band.low is None else band.low
        drin: list[tuple[float, list[int]]] = []
        while zeiger < len(werte) and werte[zeiger] <= band.high:
            drin.append((werte[zeiger], konto[werte[zeiger]]))
            zeiger += 1
        if not drin:
            continue
        n = sum(zeile[0] for _, zeile in drin)
        il_lo = min(zeile[1] for _, zeile in drin)
        il_hi = max(zeile[2] for _, zeile in drin)
        label = f"{pct(lo_eff)}–{pct(band.high)} %"
        werte_text = _spread_text([(drin[0][0], drin[-1][0])])
        il_text = f"{il_lo}–{il_hi}" if il_hi != il_lo else _fmt_num(il_lo)
        zeilen.append(f"{label:<11}{n:>5}  {werte_text:<14}{il_text}")
    return zeilen


# Die zwei Überschriften im Steckbrief. Als Konstanten, weil
# ``record_detail_html`` den Text an der ERSTEN von beiden aufteilt:
# ab dort läuft die feste Schrift. Zwei Stellen mit demselben Literal
# wären genau die Art Kopie, die beim nächsten Umformulieren
# auseinanderläuft.
# Ohne Apostroph, mit Absicht: Die Konstante wird auch gegen den
# HTML-escapten Text verglichen (§record_detail_html), und ein
# Apostroph wird dort zu "&#x27;".
LADDER_HEADING = "Tiers, straight from game data"
BANDS_HEADING = "Tiers, inferred from item level"


def collected_mask(konto: dict[float, list[int]], ladder: list) -> list[bool]:
    """Je Sprosse der Leiter: schon ein Wert aus dem Kontenbuch darin?

    In Leiter-Reihenfolge (nach Freischalt-Level aufsteigend) — das
    LETZTE Element ist also T1. Die Slot-Leiste auf der Karte zeichnet
    genau diese Liste von links nach rechts: rechts außen sitzt das
    beste Tier, wie ein Fortschritt, der nach rechts wächst."""
    return [any(step.low <= wert <= step.high for wert in konto)
            for step in ladder]


def collected_tiers(konto: dict[float, list[int]],
                    ladder: list) -> tuple[int, int]:
    """(gesammelt, vorhanden) — wie viele Sprossen der Leiter schon ein
    Wert aus dem Kontenbuch getroffen hat.

    Das ist die eigentliche Sammel-Aussage: nicht "wie oft gesehen",
    sondern "wie vollständig". Werte, die in keine Sprosse fallen,
    zählen bewusst nicht mit — sie gehören keinem Tier an
    (§ladder_table)."""
    maske = collected_mask(konto, ladder)
    return sum(maske), len(maske)


def ladder_rows(konto: dict[float, list[int]],
                ladder: list) -> list[tuple[str, str, str, int, str]]:
    """Eine Zeile je Sprosse, von T1 abwärts, als reine Daten:
    (T-Nummer, Wertspanne, "from iLvl N", Sichtungen, bester Wert).

    Gemeinsame Quelle für die Text-Tabelle (``ladder_table``) und die
    gezeichnete im Steckbrief (``record_detail_html``) — zwei Renderer,
    EINE Zeilenlogik, sonst liefen sie beim nächsten Umbau auseinander."""
    zeilen = []
    for i, step in enumerate(ladder):
        drin = {wert: zeile for wert, zeile in konto.items()
               if step.low <= wert <= step.high}
        gesehen = sum(zeile[0] for zeile in drin.values())
        zeilen.append((tier_number(ladder, i),
                      _spread_text([(step.low, step.high)]),
                      f"from iLvl {step.required_level}",
                      gesehen,
                      _fmt_num(max(drin)) if drin else ""))
    return zeilen


def _beyond_the_ladder(konto: dict[float, list[int]],
                       ladder: list) -> tuple[int, str] | None:
    """(Sichtungen, Wertspanne) der Werte NEBEN der Leiter — oder None.

    Als SPANNE, nicht als Werteliste: Hier stehen zwei ganz verschiedene
    Dinge nebeneinander — Werte unter der untersten Sprosse (aus fremden
    Roll-Tabellen) und solche über der obersten (gecraftet, Essenz,
    beeinflusst). Eine Liste zeigte je nach Sortierung nur eine Sorte."""
    ausserhalb = {wert: zeile for wert, zeile in konto.items()
                 if not any(step.low <= wert <= step.high for step in ladder)}
    if not ausserhalb:
        return None
    n = sum(zeile[0] for zeile in ausserhalb.values())
    return n, _spread_text([(min(ausserhalb), max(ausserhalb))])


def ladder_table(konto: dict[float, list[int]], ladder: list) -> list[str]:
    """Die ECHTE Leiter als Tabelle, von T1 abwärts — mit den Lücken.

    Anders als ``band_table`` (geschätzte Bänder, §4.52.6) steht hier
    keine Vermutung: Die Sprossen kommen aus den Spieldaten selbst
    (§4.53). Deshalb dürfen auch die Zeilen dastehen, in denen NICHTS
    liegt — sie sind der Sammelalbum-Teil, die noch leeren Felder.

    Ein Wert kann in mehrere Sprossen fallen, weil sich manche Tiers in
    ihren Werten überlappen (Fire Resistance auf Ring: T7 ist 12–17,
    T6 ist 18–23, aber anderswo überschneiden sie sich). Er zählt dann
    für jede — das Kontenbuch weiß nicht, von welchem Item er kam, und
    eine Zuordnung zu erfinden wäre schlechter als beide zu nennen. An
    Peters Bestand gemessen betrifft das 3,8 % der Sichtungen."""
    zeilen = [f"{'':<5}{'Values':<12}{'':<16}{'Seen':>7}   Best"]
    for tier, werte, ab, gesehen, best in ladder_rows(konto, ladder):
        if gesehen:
            zeilen.append(f"{tier:<5}{werte:<12}{ab:<16}"
                         f"{gesehen:>6}×   {best}")
        else:
            zeilen.append(f"{tier:<5}{werte:<12}{ab:<16}"
                         f"{'not seen yet':>13}")
    ausserhalb = _beyond_the_ladder(konto, ladder)
    if ausserhalb:
        # Gecraftete, mit Essenz gerollte und beeinflusste Mods rollen
        # aus eigenen Tabellen, die hier nicht mitgebaut werden — ihre
        # Werte liegen deshalb neben der Leiter statt darauf. Sie
        # verschweigen wäre falsch: Es sind echte Sichtungen, und
        # gerade die hohen sind die interessanten.
        n, werte = ausserhalb
        zeilen.append(f"{'':<5}{'beyond the ladder':<28}{n:>6}×   {werte}")
    getroffen, gesamt = collected_tiers(konto, ladder)
    zeilen.append("")
    zeilen.append(f"{'':<5}{getroffen} of {gesamt} tiers collected")
    return zeilen


def _indent(zeilen: list[str], weite: int) -> list[str]:
    """Einrücken, aber Leerzeilen leer lassen — sonst bleibt unsichtbarer
    Leerraum stehen, den ein späterer Textvergleich stolpernd findet."""
    return [f"{'':<{weite}}{zeile}" if zeile else "" for zeile in zeilen]


def format_bands(record: ModRecord, knowledge=None,
                 league: str | None = None) -> list[str]:
    """Die Tier-Tabelle je Basis-Kategorie.

    **Zwei Quellen, klar getrennt beschriftet.** Kennt das Mod-Wissen
    (§4.53) eine echte Leiter für (Identität, Kategorie), steht sie hier
    — mit T-Nummern, Freischalt-Leveln und den noch leeren Sprossen.
    Sonst bleibt es bei den aus dem Item-Level GESCHÄTZTEN Prozent-
    Bändern (§4.52.4/§4.52.6), die keine Tier-Nummer behaupten dürfen.
    Peters Begründung für die Prozente von 2026-08-27 gilt unverändert
    dort weiter, wo wir die echte Leiter nicht haben — an seinem Bestand
    sind das 19 % der Sichtungen.

    Steht bewusst UNTER den Spannen: Die Spannen darüber sind, was
    dieses Konto gesehen hat; hier geht es um das, was das Spiel
    hergibt.

    ``league`` schränkt auf einen Ligen-Topf ein (``None`` = alle) —
    dieselbe Auswahl wie der Liga-Filter des Albums (§4.53.3)."""
    konten = record.ledgers(league)
    if not konten:
        return []
    echte: list[str] = []
    for kategorie, konto, ladder in _ladder_sections(record, knowledge, konten):
        echte.append(_section_head(kategorie, konto))
        echte.extend(_indent(ladder_table(konto, ladder), 4))
    geschaetzte = _band_lines(record, knowledge, konten, league)

    zeilen: list[str] = []
    if echte:
        zeilen += ["", LADDER_HEADING,
                   "(the ladder the game itself rolls from — T1 is the top "
                   "tier; empty", "rows are tiers you have not rolled yet)"]
        zeilen += echte
    zeilen += geschaetzte
    return zeilen


def _weighted_categories(konten: dict[str, dict[float, list[int]]]) -> list[str]:
    """Nach Sichtungen absteigend, nicht alphabetisch: Ein verbreiteter
    Mod wie Feuerresistenz hat in Peters Bestand 24 Kategorien, und jede
    Leiter ist elf Zeilen lang. Alphabetisch stünde "Amulet" oben, auch
    wenn die Kategorie zwei Sichtungen hat und "Ring" zweihundert.

    Arbeitet auf dem Ergebnis von ``ModRecord.ledgers`` — die Liga-
    Auswahl ist da schon hineingerechnet."""
    return sorted(konten,
                 key=lambda kat: (-sum(z[0] for z in konten[kat].values()),
                                 kat))


def _section_head(kategorie: str, konto: dict[float, list[int]]) -> str:
    sichtungen = sum(zeile[0] for zeile in konto.values())
    einheit = "sighting" if sichtungen == 1 else "sightings"
    return (f"  {kategorie}  ({sichtungen} {einheit}, "
            f"item level {min(z[1] for z in konto.values())}–"
            f"{max(z[2] for z in konto.values())})")


def _ladder_sections(record: ModRecord, knowledge,
                     konten: dict[str, dict[float, list[int]]]
                     ) -> list[tuple[str, dict, list]]:
    """(Kategorie, Konto, Leiter) für jede Kategorie MIT echter Leiter,
    nach Sichtungen sortiert — die gemeinsame Quelle beider Renderer.
    ``konten`` kommt vom Aufrufer (``ModRecord.ledgers``), damit die
    Liga-Auswahl nur EINMAL gerechnet wird."""
    if knowledge is None:
        return []
    ergebnis = []
    for kategorie in _weighted_categories(konten):
        ladder = knowledge.ladder(record.identity, kategorie)
        if ladder:
            ergebnis.append((kategorie, konten[kategorie], ladder))
    return ergebnis


def _band_lines(record: ModRecord, knowledge,
                konten: dict[str, dict[float, list[int]]],
                league: str | None = None) -> list[str]:
    """Der Prozent-Bänder-Block (Überschrift + Sektionen) als Text —
    nur die Kategorien OHNE echte Leiter, oder leer."""
    sektionen: list[str] = []
    for kategorie in _weighted_categories(konten):
        if knowledge is not None and knowledge.ladder(record.identity, kategorie):
            continue
        konto = konten[kategorie]
        sektionen.append(_section_head(kategorie, konto))
        front = record.tier_front(kategorie, league)
        baender = mod_tiers.bands(front)
        if not baender:
            sektionen.append(f"      {mod_tiers.why_silent(front)}")
            continue
        sektionen.extend(_indent(band_table(konto, baender), 6))
    if not sektionen:
        return []
    return ["", BANDS_HEADING,
            "(no ladder known for this one — bands as % of the seen "
            "span. Tier", "numbers would clash with the real ones "
            "while this is a guess. Upper", "bounds are proven, lower "
            "bounds assume tiers meet without gaps)"] + sektionen


# Farben des gezeichneten Steckbriefs, gerechnet gegen den Feld-Grund
# #2d2d2d (Skript im Scratchpad, 2026-08-28): T1 Gold 8,0 - T2 Silber
# 8,6 - T3 Bronze 5,6 - Uebrige 5,8 - Gedaempftes 4,8 - alle ueber der
# 4,5-Grenze fuer Fliesstext. Ab T4 traegt die Nummer keine eigene
# Farbe mehr: Drei Metalle versteht jeder sofort, zehn Farbstufen
# niemand.
# Die Metall-Farben der T-Nummern liegen in ``ui/mod_bar.py`` — das
# Item-Detail malt dieselben Etiketten, und eine Farbtabelle an zwei
# Orten liefe auseinander.
T_COLORS = mod_bar.TIER_COLORS
T_COLOR_REST = mod_bar.TIER_COLOR_REST
HTML_DIM = "#989898"
HTML_HEAD_BG = "#3a3a3a"
HTML_ROW_ALT_BG = "#333333"
HTML_BAR = "#8fbf7f"
HTML_GOLD = "#e8c15a"


def _tier_color(label: str) -> str:
    try:
        return T_COLORS.get(int(label.lstrip("T")), T_COLOR_REST)
    except ValueError:
        return T_COLOR_REST


def _seen_cell(gesehen: int) -> str:
    """Sichtungen als Mini-Balken plus Zahl. Logarithmisch, weil in
    Peters Bestand 2x neben 216x steht - linear waere entweder der
    kleine Balken unsichtbar oder der grosse gesprengt."""
    breite = min(8, 1 + int(gesehen).bit_length() // 2)
    balken = "▰" * breite
    return (f'<font color="{HTML_BAR}">{balken}</font> '
            f'<font color="{CARD_TEXT}">{gesehen}×</font>')


def _html_ladder_section(kategorie: str, konto: dict[float, list[int]],
                         ladder: list) -> str:
    """Eine Kategorie als gezeichnete Tabelle: Kopfzeile mit Grund,
    T-Nummern in Gold/Silber/Bronze, Zebra-Zeilen, ungerollte Tiers
    gedaempft, ``beyond the ladder`` und die Sammel-Bilanz darueber."""
    getroffen, gesamt = collected_tiers(konto, ladder)
    sichtungen = sum(zeile[0] for zeile in konto.values())
    il_lo = min(zeile[1] for zeile in konto.values())
    il_hi = max(zeile[2] for zeile in konto.values())
    bilanz = f"{getroffen} of {gesamt} tiers"
    if getroffen == gesamt:
        bilanz = (f'<font color="{HTML_GOLD}"><b>{bilanz} '
                  f'{COMPLETE_MARK}</b></font>')
    zellen = [f'<tr bgcolor="{HTML_HEAD_BG}"><td colspan="5">'
              f'<b>{html_escape(kategorie)}</b>'
              f'<font color="{CARD_TEXT_DIM}"> — {sichtungen} sightings, '
              f'item level {il_lo:g}–{il_hi:g} — </font>{bilanz}</td></tr>',
              f'<tr><td></td>'
              f'<td><font color="{CARD_TEXT_DIM}">Values</font></td>'
              f'<td><font color="{CARD_TEXT_DIM}">from iLvl</font></td>'
              f'<td><font color="{CARD_TEXT_DIM}">Seen</font></td>'
              f'<td><font color="{CARD_TEXT_DIM}">Best</font></td></tr>']
    for i, (tier, werte, ab, gesehen, best) in enumerate(ladder_rows(konto, ladder)):
        zebra = f' bgcolor="{HTML_ROW_ALT_BG}"' if i % 2 else ""
        ilvl = ab.removeprefix("from iLvl ")
        if gesehen:
            zellen.append(
                f'<tr{zebra}>'
                f'<td><font color="{_tier_color(tier)}"><b>{tier}</b></font></td>'
                f'<td>{html_escape(werte)}</td>'
                f'<td><font color="{CARD_TEXT_DIM}">{ilvl}</font></td>'
                f'<td>{_seen_cell(gesehen)}</td>'
                f'<td><font color="{HTML_BAR}">{best}</font></td></tr>')
        else:
            zellen.append(
                f'<tr{zebra}>'
                f'<td><font color="{HTML_DIM}">{tier}</font></td>'
                f'<td><font color="{HTML_DIM}">{html_escape(werte)}</font></td>'
                f'<td><font color="{HTML_DIM}">{ilvl}</font></td>'
                f'<td colspan="2"><font color="{HTML_DIM}">'
                f'<i>not seen yet</i></font></td></tr>')
    ausserhalb = _beyond_the_ladder(konto, ladder)
    if ausserhalb:
        n, werte = ausserhalb
        zellen.append(
            f'<tr><td></td>'
            f'<td colspan="2"><font color="{CARD_TEXT_DIM}">'
            f'<i>beyond the ladder</i></font></td>'
            f'<td>{_seen_cell(n)}</td>'
            f'<td><font color="{CARD_TEXT_DIM}">{html_escape(werte)}</font>'
            f'</td></tr>')
    # Ohne width="100%": Die Tabelle schrumpft auf ihre Inhaltsbreite,
    # sonst verteilt Qt die fünf Spalten gleichmäßig über das ganze Feld
    # und zwischen Values und iLvl klaffen fingerbreite Lücken.
    return ('<table cellspacing="0" cellpadding="3">'
            + "".join(zellen) + "</table>")


def record_detail_html(record: ModRecord, mono_family: str, knowledge=None,
                       league: str | None = None,
                       rarity_ok: RarityPredicate | None = None) -> str:
    """Der Steckbrief fuers Anzeige-Feld - drei Absaetze, drei Techniken:

    1. Der Fliesstext-Kopf (Beispielzeile, Toepfe, Spannen) in der
       normalen Schrift - das ganze Feld gesperrt zu setzen machte es
       kaum noch lesbar (Peter, 2026-08-28).
    2. Die echten Leitern als GEZEICHNETE Tabellen (Design-Runde
       2026-08-28, Peter: "gezeichnete Tabellen"): Zellen richten die
       Spalten aus, keine Monospace-Schrift mehr noetig; T-Nummern in
       Gold/Silber/Bronze, ungerollte Tiers gedaempft.
    3. Die geschaetzten Prozent-Baender weiterhin als ``<pre>`` in
       fester Schrift - sie bleiben eine Texttabelle, ausdruecklich
       schlichter als die echten Leitern: Der optische Rangunterschied
       IST die Botschaft (belegt gegen geraten).

    ``league`` und ``rarity_ok`` sind die Filter des Albums; beide
    greifen bis in die Spannen-Liste durch (§format_record_detail),
    die Liga zusaetzlich in Leitern und Baender (§4.53.3)."""
    zeilen = format_record_detail(record, knowledge, league,
                                  rarity_ok).splitlines()
    kandidaten = [zeilen.index(kopf) for kopf in (LADDER_HEADING, BANDS_HEADING)
                 if kopf in zeilen]
    start = min(kandidaten) if kandidaten else len(zeilen)
    teile = ["<br>".join(html_escape(z) for z in zeilen[:start])]

    konten = record.ledgers(league)
    sektionen = _ladder_sections(record, knowledge, konten)
    if sektionen:
        teile.append(f'<p><b>{html_escape(LADDER_HEADING)}</b><br>'
                     f'<font color="{CARD_TEXT_DIM}">the ladder the game '
                     f'itself rolls from — T1 is the top tier; dimmed '
                     f'rows are tiers you have not rolled yet</font></p>')
        teile.extend(_html_ladder_section(kategorie, konto, ladder)
                     for kategorie, konto, ladder in sektionen)

    baender = _band_lines(record, knowledge, konten, league)
    if baender:
        tabelle = html_escape("\n".join(baender))
        teile.append(f"<pre style=\"font-family:'{mono_family}',Consolas,"
                     f"monospace; margin:0;\">{tabelle}</pre>")
    return "".join(teile)


def seen_line(record: ModRecord, league: str | None,
              rarity_ok: RarityPredicate | None) -> str:
    """Die Sichtungs-Zeile des Steckbriefs: ``seen 1746× in total`` —
    oder mit aktivem Filter ``seen 212× in SSF R Allflame · 1746× in
    total``. Die Gesamtzahl bleibt als Nebensatz stehen, damit man
    nicht vergisst, dass die Auswahl ein Ausschnitt ist."""
    if league is None and rarity_ok is None:
        return f"seen {record.count}× in total"
    if league is not None and rarity_ok is None:
        wo = league_label(league)
    else:
        wo = "this selection"
    return (f"seen {matching_count(record, league, rarity_ok)}× in {wo}"
            f"  ·  {record.count}× in total")


def format_record_detail(record: ModRecord, knowledge=None,
                         league: str | None = None,
                         rarity_ok: RarityPredicate | None = None) -> str:
    """Der volle Steckbrief eines Eintrags, für das Detail-Feld.

    **Beide Filter greifen bis hierher durch** (Peter, 2026-08-28: "Wenn
    ich eine Sammlung anfange, dann meistens beim Start einer neuen
    Liga und da benötige ich keine Infos mehr zur alten Liga, die
    irritieren hier nur"): Die Spannen-Liste zeigt nur die Töpfe, die
    zur Auswahl passen — dieselbe Regel wie die Range-Spalte
    (§matching_spans). Der Tier-Teil folgt der Liga (§format_bands);
    die Rarität kennt er nicht."""
    zeilen = [record.example or record.identity,
             f"{kind_label(record.kind)}  ·  {seen_line(record, league, rarity_ok)}"]
    datum = first_seen_text(record)
    if datum:
        zeilen.append(datum)
    zeilen.append("")
    # ``liga``, nicht ``league`` — die Schleife lief hier schon, bevor es
    # den gleichnamigen Parameter gab, und hat ihn beim Umbau prompt
    # ueberschattet: Der Tier-Teil zeigte dann still die LETZTE Liga der
    # Spannen-Liste statt der gewaehlten.
    for liga in record.leagues:
        if league is not None and liga != league:
            continue
        for rarity in sorted(record.spans[liga]):
            if rarity_ok is not None and not rarity_ok(rarity):
                continue
            span = record.spans[liga][rarity]
            zeilen.append(f"{league_label(liga)}  ·  {rarity_label(rarity)}")
            zeilen.append(f"    {format_span(span)}")
    zeilen.extend(format_bands(record, knowledge, league))
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


def matching_count(record: ModRecord, league: str | None,
                   rarity_ok: RarityPredicate | None) -> int:
    """Wie viele Sichtungen liegen in den gerade ausgewählten Töpfen?

    Die Spalte "Seen" zeigte zuvor ``record.count``, also die Summe über
    ALLE Töpfe — direkt neben einer Range-Spalte, die nur die
    ausgewählten zeigt. Peter fiel es an einem Screenshot auf: Chaos-Res
    mit Range "13" und daneben "897 gesehen", obwohl in dem gefilterten
    Topf 33 Sichtungen lagen. Zwei Spalten nebeneinander, die von
    verschiedenen Populationen reden, sind schlimmer als eine fehlende.

    Ohne Filter ist die Summe wieder genau ``record.count`` — jede
    Beobachtung zählt in genau eine Spanne."""
    return sum(span.count for span in matching_spans(record, league, rarity_ok))


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


def tier_slots(record: ModRecord, knowledge,
               league: str | None = None) -> list[bool] | None:
    """Die Slot-Maske des Eintrags — oder ``None``, wenn für keinen
    seiner Töpfe eine echte Leiter bekannt ist.

    Bei mehreren Basis-Kategorien zählt die mit den MEISTEN Sichtungen:
    Ein Mod, der überwiegend auf Ringen durch die Hände geht, soll seinen
    Ring-Stand zeigen und nicht den einer Kategorie, von der zufällig ein
    Stück herumliegt. Der Steckbrief nennt ohnehin jede Kategorie
    einzeln.

    ``league`` folgt dem Liga-Filter des Albums (§4.53.3): Mit Filter
    zählen nur die Sichtungen dieses Ligen-Topfs — auch die Kategorie-
    Wahl richtet sich dann nach ihm."""
    if knowledge is None:
        return None
    konten = record.ledgers(league)
    if not konten:
        return None
    beste: tuple[int, list[bool]] | None = None
    for kategorie, konto in konten.items():
        ladder = knowledge.ladder(record.identity, kategorie)
        if not ladder:
            continue
        sichtungen = sum(zeile[0] for zeile in konto.values())
        if beste is None or sichtungen > beste[0]:
            beste = (sichtungen, collected_mask(konto, ladder))
    return beste[1] if beste else None


def tier_progress(record: ModRecord, knowledge,
                  league: str | None = None) -> tuple[int, int] | None:
    """"So viele der möglichen Tiers hast du" — dieselbe Kategorie-Wahl
    wie ``tier_slots``, nur verdichtet auf (gesammelt, vorhanden)."""
    maske = tier_slots(record, knowledge, league)
    return (sum(maske), len(maske)) if maske is not None else None


def card_border(record: ModRecord, slots: list[bool] | None,
                selected: bool) -> tuple[str, int]:
    """(Farbe, Strichbreite) des Kartenrands — die Rangordnung der
    Auszeichnungen:

    1. Auswahl schlägt alles (sonst verlöre man die Markierung aus dem
       Blick, sobald eine ausgezeichnete Karte angeklickt wird).
    2. Gold für die KOMPLETTE Leiter — die Panini-Semantik "Set voll".
    3. Silber für das Einzelstück (genau eine Sichtung) — vorher Gold,
       umgefärbt, damit Gold eindeutig Vollständigkeit heißt.
    4. Grau für alle anderen."""
    if selected:
        return CARD_BORDER_SELECTED, 2
    if slots and all(slots):
        return CARD_BORDER_COMPLETE, 2
    if record.count == 1:
        return CARD_BORDER_SINGLE, 2
    return CARD_BORDER, 1


def range_column_text(record: ModRecord, league: str | None,
                      rarity_ok: RarityPredicate | None, knowledge=None) -> str:
    """Die Range-Spalte samt Tier-Zähler: ``6–48 · 8/8``.

    **Der Zähler verschwindet nur noch beim Raritäts-Filter.** Das
    Kontenbuch hinter ihm kennt keine Rarität (es sammelt ausschließlich
    gerollte Affixe unkorrumpierter Magic-/Rare-Items,
    §mod_collection.tierable) — Range und Zähler wären dann zwei Zahlen
    über verschiedene Populationen in einer Zelle, genau das, was Peter
    an der früheren "Seen"-Spalte aufgefallen ist (§matching_count).
    Die LIGA dagegen kennt es seit Aufbau 6 (§4.53.3): Beim Liga-Filter
    folgen beide Zellenhälften derselben Auswahl, der Zähler bleibt."""
    text = combined_range_text(record, league, rarity_ok)
    if rarity_ok is not None:
        return text
    stand = tier_progress(record, knowledge, league)
    return text if stand is None else f"{text}  ·  {stand[0]}/{stand[1]}"


IDENTITY_COL, KIND_COL, RANGE_COL, COUNT_COL, EXAMPLE_COL = range(5)
COLUMNS = ("Mod", "Kind", "Range", "Seen", "Example")

# Zusatz-Rollen für die Kartenansicht. Die Karte zeigt Spalteninhalte
# (Name, Range, Seen) plus zwei Dinge, die keine Spalte sind: das
# Erst-gesehen-Datum (zum Sortieren) und "neu in dieser Sitzung".
RECORD_ROLE = Qt.ItemDataRole.UserRole
FIRST_SEEN_ROLE = Qt.ItemDataRole.UserRole + 1
NEW_ROLE = Qt.ItemDataRole.UserRole + 2
# list[bool] je Tier (§collected_mask) oder None ohne bekannte Leiter —
# die Slot-Leiste der Karte und ihr Gold-Rahmen hängen daran.
TIER_SLOTS_ROLE = Qt.ItemDataRole.UserRole + 3

# Die Sortier-Linsen der Kartenansicht — das ist der Trophäen-Teil des
# Albums: "Neuzugänge", "Arbeitspferde", "Einzelstücke" sind keine
# eigenen Seiten, sondern Sortierungen derselben Karten. Reihenfolge =
# Menü-Reihenfolge; der Schlüssel ist der Anzeigename (String statt
# Tupel als ``itemData`` — FALLSTRICKE #78).
ALBUM_SORTS: tuple[tuple[str, int, int, Qt.SortOrder], ...] = (
    ("A–Z", IDENTITY_COL, Qt.ItemDataRole.DisplayRole,
     Qt.SortOrder.AscendingOrder),
    ("Newest finds", IDENTITY_COL, FIRST_SEEN_ROLE,
     Qt.SortOrder.DescendingOrder),
    ("Most seen", COUNT_COL, Qt.ItemDataRole.DisplayRole,
     Qt.SortOrder.DescendingOrder),
    ("Seen once first", COUNT_COL, Qt.ItemDataRole.DisplayRole,
     Qt.SortOrder.AscendingOrder),
)
ALBUM_SORTS_BY_NAME = {name: (col, role, order)
                       for name, col, role, order in ALBUM_SORTS}

# Farben der Kartenansicht, alle gerechnet statt begutachtet (Skript im
# Scratchpad, 2026-08-27; Grundton ist der GEMESSENE Panel-Hintergrund
# #2d2d2d aus FALLSTRICKE #76, nicht QPalette.Window):
#   Karte #3c3c3c auf Grund #2d2d2d: CIEDE2000 4,8 — plus Rand #555555
#     mit dE 9,7 zur Karte, damit die Trennung nicht an der Fläche
#     allein hängt.
#   Name #e8e6e3 auf Karte: WCAG 9,4. Nebentext #b0b0b0: 5,4.
#   Range #8fbf7f: 5,5 — DASH_OK selbst läge mit 4,4 knapp UNTER 4,5.
#   Einzelstück-Rand DASH_WARN auf Karte: dE 52,8; als Text 5,3.
ALBUM_BG = "#2d2d2d"
CARD_BG = "#3c3c3c"
CARD_BORDER = "#555555"
# Silber statt des früheren Golds (Design-Runde 2026-08-28): Gold ehrt
# seither die VOLLSTÄNDIGKEIT (§CARD_BORDER_COMPLETE), und zwei goldene
# Ränder mit verschiedener Bedeutung nebeneinander wären nicht zu
# unterscheiden gewesen (dE der beiden Goldtöne nur 14,7 — Silber gegen
# Gold: 34,3). Silber auf Karte: WCAG 6,9, dE 54,9.
CARD_BORDER_SINGLE = "#c8ccd4"
CARD_BORDER_SELECTED = ROW_CHANGED_COLOR
# Sattes Gold für die komplette Leiter — die Panini-Semantik "Set voll".
# Auf Karte: WCAG 7,9, dE 64,5; gegen den Auswahl-Rand (Türkis) dE 44,8.
CARD_BORDER_COMPLETE = "#ffd700"
CARD_TEXT = "#e8e6e3"
CARD_TEXT_DIM = "#b0b0b0"
CARD_TEXT_RANGE = "#8fbf7f"
CARD_TEXT_NEW = DASH_WARN
# Slot-Leiste (ein Kästchen je Tier): gefüllt in mattem Gold (WCAG 5,6,
# dE 55 zur Karte), leere Slots nur als Umriss — die Lücke ist die
# Botschaft, sie soll sichtbar, aber leise sein.
SLOT_FILLED = "#dcb45f"
SLOT_EMPTY = "#6a6a6a"
COMPLETE_MARK = "✓"
CARD_PAD = 8
CARD_RADIUS = 6
# Kaestchen der Slot-Leiste: klein genug, dass auch 13 Life-Tiers in
# eine Karte passen (13*(10+3) = 169 px, die Karte ist ~260 breit).
SLOT_W = 10
SLOT_H = 7
SLOT_GAP = 3
NEW_MARK = "✦"

# Mod-Themen für Farbstreifen und Symbol auf der Karte (Design-Runde
# 2026-08-28, Peter: "Symbole und verschiedene Farben"). Die Farben
# folgen der Sprache des Spiels (Feuer rot, Kälte blau, Blitz gelb,
# Chaos giftgrün, ...), sind aber GERECHNET: jedes Paar CIEDE2000
# >= 12,4, jede Fläche >= 30 gegen den Kartengrund, jede Glyphe, die in
# Themenfarbe gemalt wird, WCAG >= 3 (Grenze für grafische Objekte —
# der Streifen trägt die Info nie allein, der Mod-Text steht daneben).
#
# REIHENFOLGE = PRIORITÄT, erste Übereinstimmung gewinnt: "Minions deal
# #% increased Damage" soll Minion sein, nicht irgendein späterer
# Treffer; "Energy Shield" darf nicht bei einem allgemeineren Muster
# hängenbleiben. Ein Zusatzsignal, keine Taxonomie — Mods ohne Treffer
# bleiben schlicht grau.
MOD_THEMES: tuple[tuple[str, str, str, str], ...] = (
    ("Minion", r"\bMinion", "#a868e8", "👥"),
    ("Energy Shield", r"\bEnergy Shield\b", "#8ad8d0", "◈"),
    ("Life", r"\bLife\b", "#e05a6a", "♥"),
    ("Mana", r"\bMana\b", "#6a8ae8", "💧"),
    ("Fire", r"\bFire\b|\bIgnite|\bBurning\b", "#e06c4a", "🔥"),
    ("Cold", r"\bCold\b|\bChill|\bFreeze|\bFrost", "#6ab8e8", "❄"),
    ("Lightning", r"\bLightning\b|\bShock", "#e8cf5a", "⚡"),
    ("Chaos", r"\bChaos\b|\bPoison|\bWither", "#98c838", "☠"),
    ("Armour", r"\bArmour\b|\bPhysical Damage Reduction\b", "#b08a5a", "🛡"),
    ("Evasion", r"\bEvasion\b|\bBlind\b", "#50c878", "💨"),
    ("Attack", r"\bAttack|\bAccuracy\b|\bMelee\b|\bProjectile", "#e8955a", "⚔"),
    ("Caster", r"\bSpell|\bCast\b|\bCast Speed\b", "#c898f0", "✨"),
    ("Speed", r"\bMovement Speed\b", "#e0e0e0", "»"),
    ("Attributes", r"\bStrength\b|\bDexterity\b|\bIntelligence\b|\bAttributes\b",
     "#e070c8", "✚"),
)
_THEME_PATTERNS = tuple((re.compile(muster), name, farbe, symbol)
                        for name, muster, farbe, symbol in MOD_THEMES)


@lru_cache(maxsize=8192)
def mod_theme(identity: str) -> tuple[str, str, str] | None:
    """(Themenname, Farbe, Symbol) — oder ``None`` für Mods ohne
    erkennbares Thema. Gecacht, weil der Karten-Delegate bei jedem
    Neuzeichnen fragt und die Antwort je Identität konstant ist."""
    for muster, name, farbe, symbol in _THEME_PATTERNS:
        if muster.search(identity):
            return name, farbe, symbol
    return None


def first_seen_text(record: ModRecord) -> str:
    """"entered the collection on 2026-08-27" — oder leer für den
    Grundstock: Ein Eintrag mit ``first_seen == 0`` ist älter als die
    Aufzeichnung des Datums, und ein erfundenes Datum wäre schlimmer als
    keines."""
    if record.first_seen <= 0:
        return ""
    tag = time.strftime("%Y-%m-%d", time.localtime(record.first_seen))
    return f"entered the collection on {tag}"


def collection_greeting(records: list[ModRecord],
                        new_keys: frozenset[tuple[str, str]]) -> str:
    """Der Sammlungs-Puls, solange keine Karte gewählt ist.

    Ein Album schlägt man auf und sieht zuerst den Stand der Sammlung —
    nicht einen grauen Platzhalter. Steht im Platzhaltertext des
    Detail-Felds, weil dort ohnehin Platz ist, bis etwas gewählt wird."""
    total = len(records)
    einzel = sum(1 for r in records if r.count == 1)
    neu = sum(1 for r in records if (r.kind, r.identity) in new_keys)
    zeilen = [f"Your collection: {total} mods — {einzel} of them seen "
              f"exactly once, {neu} new this session."]
    juengste = [r for r in records if r.first_seen > 0]
    if juengste:
        letzter = max(juengste, key=lambda r: r.first_seen)
        tag = time.strftime("%Y-%m-%d", time.localtime(letzter.first_seen))
        zeilen.append(f"Latest find: {letzter.identity} ({tag})")
    zeilen.append("")
    zeilen.append("Select a mod to see every rarity and league it has "
                  "been seen on.")
    return "\n".join(zeilen)


def album_stats(records: list[ModRecord], knowledge,
                league: str | None = None) -> str:
    """Die Sammel-Kopfzeile des Albums (Design-Runde 2026-08-28):
    Bestand, komplette Sets und der Tier-Fortschritt als Balken.

    Der Balken zählt SPROSSEN, nicht Mods: "wie viele der Tiers, die
    das Spiel für deine gesehenen Mods kennt, hast du schon gerollt" —
    das ist die Zahl, die beim Spielen tatsächlich wächst. Ohne
    geladenes Mod-Wissen bleibt nur der Bestand stehen; ein Balken ohne
    Grundgesamtheit wäre erfunden.

    ``league`` folgt der Liga-Combo des Albums (§4.53.3) — die
    Kopfzeile redet dann über dieselbe Population wie die Karten
    darunter."""
    teile = [f"{len(records):,} mods collected"]
    got = total = sets = 0
    for record in records:
        stand = tier_progress(record, knowledge, league)
        if stand is None:
            continue
        got += stand[0]
        total += stand[1]
        if stand[0] == stand[1]:
            sets += 1
    if total:
        teile.append(f"{sets} complete sets {COMPLETE_MARK}")
        anteil = got / total
        voll = round(anteil * 10)
        balken = "▰" * voll + "▱" * (10 - voll)
        teile.append(f"tiers {got:,}/{total:,} {balken} {anteil:.0%}")
    return "  ·  ".join(teile)


class ModAlbumModel(QAbstractTableModel):
    """Reine Anzeige einer bereits fertigen Liste — die Sammlung selbst
    bleibt dumm gegenüber Qt (§mod_collection.py)."""

    def __init__(self, records: list[ModRecord],
                 new_keys: frozenset[tuple[str, str]] = frozenset(),
                 knowledge=None) -> None:
        super().__init__()
        self._records = records
        # Die echten Tier-Leitern (§4.53) oder ``None``, solange kein
        # Mod-Wissen geladen ist. Nur lesend verwendet: fuer den
        # Tier-Zaehler in der Range-Spalte und die Leiter im Steckbrief.
        self._knowledge = knowledge
        # Schnappschuss der Sitzungs-Funde (``ModCollection.new_keys``) —
        # wie die Karteiliste selbst: Stand vom Öffnen, keine Live-Sicht.
        self._new_keys = new_keys
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
            # Seit die Slot-Leiste der Liga folgt (§4.53.3), hängt nicht
            # mehr nur Range/Seen an der Auswahl, sondern auch die Karte
            # selbst (TIER_SLOTS_ROLE liegt auf Spalte 0) — also alle
            # Spalten und alle Rollen neu zeichnen lassen.
            top = self.index(0, 0)
            bottom = self.index(len(self._records) - 1, len(COLUMNS) - 1)
            self.dataChanged.emit(top, bottom, [])

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role):
        record = self._records[index.row()]
        if role == RECORD_ROLE:
            return record
        if role == FIRST_SEEN_ROLE:
            return record.first_seen
        if role == NEW_ROLE:
            return (record.kind, record.identity) in self._new_keys
        if role == TIER_SLOTS_ROLE:
            # Folgt dem Liga-Filter (§4.53.3): Gold-Rahmen und Slots
            # zeigen den Stand der ausgewählten Liga, nicht aller.
            return tier_slots(record, self._knowledge, self._range_league)
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == IDENTITY_COL:
            # In der Tabelle wegen 381-Zeichen-Identitäten nützlich, in
            # der Kartenansicht notwendig: Dort wird ein langer Name nach
            # zwei Zeilen abgeschnitten.
            return record.identity
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        col = index.column()
        if col == IDENTITY_COL:
            return record.identity
        if col == KIND_COL:
            return kind_label(record.kind)
        if col == RANGE_COL:
            return range_column_text(record, self._range_league,
                                    self._range_rarities, self._knowledge)
        if col == COUNT_COL:
            # Dieselbe Auswahl wie die Range-Spalte daneben — siehe
            # ``matching_count``.
            return matching_count(record, self._range_league, self._range_rarities)
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


class ModCardDelegate(QStyledItemDelegate):
    """Eine Mod-Identität als Sammelkarte (§4.52.5).

    Warum ein Delegate auf einer ``QListView`` im IconMode statt echter
    Karten-Widgets: 6125 Karten als Widgets wären 6125 lebende Objekte;
    die Listenansicht zeichnet nur, was sichtbar ist, und Suche/Filter
    laufen unverändert über dasselbe Proxy-Modell wie die Tabelle.

    Aufbau einer Karte:
        [Themen-Streifen links] Symbol + Name (bis zwei Zeilen)
        Range (grün — dieselbe Auswahl-Logik wie die Range-Spalte)
        Slot-Leiste: ein Kästchen je Tier, gefüllt = gesammelt
        Art unten links, Sichtungen unten rechts (gedämpft)
    Rand nach Rang (§card_border): Auswahl > Gold (Leiter komplett,
    zusätzlich ✓ in der Fußzeile) > Silber (Einzelstück) > Grau.
    ✦ oben rechts: neu in dieser Sitzung (dasselbe Zeichen wie am Item,
    §mod_bar.NEW_MARK)."""

    def sizeHint(self, option: QStyleOptionViewItem,
                 index: QModelIndex) -> QSize:  # noqa: N802
        fm = option.fontMetrics
        # Breite aus der Schrift, nicht in Pixeln geraten: Platz für eine
        # mittellange Identität je Zeile. Höhe: zwei Namenszeilen, Range,
        # Fußzeile.
        breite = fm.horizontalAdvance("#% increased Global Critical Strike Chance")
        # + eine gute halbe Zeile für die Slot-Leiste unter der Range.
        return QSize(breite + 2 * CARD_PAD,
                     fm.height() * 4 + SLOT_H + 2 * CARD_PAD + 10)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        record = index.data(RECORD_ROLE)
        if record is None:
            return
        neu = bool(index.data(NEW_ROLE))
        range_text = index.siblingAtColumn(RANGE_COL).data(Qt.ItemDataRole.DisplayRole) or ""
        gesehen = index.siblingAtColumn(COUNT_COL).data(Qt.ItemDataRole.DisplayRole) or 0

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        karte = option.rect.adjusted(1, 1, -1, -1)

        slots = index.data(TIER_SLOTS_ROLE)
        gewaehlt = bool(option.state & QStyle.StateFlag.State_Selected)
        farbe, randbreite = card_border(record, slots, gewaehlt)
        painter.setPen(QPen(QColor(farbe), randbreite))
        painter.setBrush(QColor(CARD_BG))
        painter.drawRoundedRect(karte, CARD_RADIUS, CARD_RADIUS)

        fm = option.fontMetrics
        innen = karte.adjusted(CARD_PAD, CARD_PAD, -CARD_PAD, -CARD_PAD)

        # Themen-Streifen: ein schmales Band an der linken Innenkante,
        # unter dem Rand, damit Auswahl/Gold ihn nie verdecken müssen.
        thema = mod_theme(record.identity)
        if thema is not None:
            streifen = QRect(karte.left() + 2, karte.top() + CARD_RADIUS,
                             4, karte.height() - 2 * CARD_RADIUS)
            painter.fillRect(streifen, QColor(thema[1]))
            innen = innen.adjusted(6, 0, 0, 0)

        # ✦ zuerst, damit der Name weiß, wie viel Breite ihm bleibt.
        name_rechts = innen.right()
        if neu:
            stern_breite = fm.horizontalAdvance(NEW_MARK)
            painter.setPen(QColor(CARD_TEXT_NEW))
            painter.drawText(QRect(innen.right() - stern_breite, innen.top(),
                                   stern_breite, fm.height()),
                             Qt.AlignmentFlag.AlignRight, NEW_MARK)
            name_rechts -= stern_breite + 4

        name_rect = QRect(innen.left(), innen.top(),
                          name_rechts - innen.left(), fm.height() * 2)
        painter.setPen(QColor(CARD_TEXT))
        painter.setClipRect(name_rect)
        # Symbol als Teil des Namens-Strings: dieselbe Umbruch- und
        # Abschneide-Logik, keine eigene Positionsrechnung. Farb-Emoji
        # bringen ihre Farbe mit; Textglyphen erben CARD_TEXT — der
        # Streifen traegt die Themenfarbe, nicht das Zeichen.
        titel = f"{thema[2]} {record.identity}" if thema else record.identity
        painter.drawText(name_rect,
                         Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop,
                         titel)
        painter.setClipping(False)

        range_rect = QRect(innen.left(), name_rect.bottom() + 2,
                           innen.width(), fm.height())
        painter.setPen(QColor(CARD_TEXT_RANGE))
        painter.drawText(range_rect, Qt.AlignmentFlag.AlignLeft,
                         fm.elidedText(range_text, Qt.TextElideMode.ElideRight,
                                       range_rect.width()))

        if slots:
            self._paint_slots(painter, innen, range_rect.bottom() + 4, slots)

        fuss = QRect(innen.left(), innen.bottom() - fm.height() + 1,
                     innen.width(), fm.height())
        painter.setPen(QColor(CARD_TEXT_DIM))
        zaehler = f"{gesehen}×"
        if slots and all(slots):
            zaehler = f"{COMPLETE_MARK} {zaehler}"
        zaehler_breite = fm.horizontalAdvance(zaehler)
        painter.drawText(fuss, Qt.AlignmentFlag.AlignRight, zaehler)
        painter.drawText(fuss, Qt.AlignmentFlag.AlignLeft,
                         fm.elidedText(kind_label(record.kind),
                                       Qt.TextElideMode.ElideRight,
                                       fuss.width() - zaehler_breite - 8))
        painter.restore()

    @staticmethod
    def _paint_slots(painter: QPainter, innen: QRect, oben: int,
                     slots: list[bool]) -> None:
        """Die Slot-Leiste: ein Kästchen je Tier, von links (unterstes
        Tier) nach rechts (T1) — gefüllt heißt gesammelt, der Umriss
        allein ist die sichtbare Lücke (Panini-Prinzip). Bei sehr
        langen Leitern (Life: 13) schrumpfen die Kästchen, bis alle in
        die Kartenbreite passen."""
        n = len(slots)
        breite = min(SLOT_W, max(4, (innen.width() - (n - 1) * SLOT_GAP) // n))
        x = innen.left()
        for gefuellt in slots:
            rechteck = QRect(x, oben, breite, SLOT_H)
            if gefuellt:
                painter.fillRect(rechteck, QColor(SLOT_FILLED))
            else:
                painter.setPen(QPen(QColor(SLOT_EMPTY), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rechteck)
            x += breite + SLOT_GAP


class ModAlbumDialog(QDialog):
    def __init__(self, collection: ModCollection, parent: QWidget | None = None,
                 knowledge=None, league: str | None = None) -> None:
        """``league`` ist die Liga des Viewers beim Öffnen — das Album
        beginnt dann in ihrem Topf und mit "Normal / Magic / Rare"
        (Peter, 2026-08-29: "als Standard die aktuell im Viewer
        ausgewählte Liga nehmen sowie auf normal/magic/rare stellen").
        Vorbelegung, keine Sperre: Beide Boxen bleiben umschaltbar."""
        super().__init__(parent)
        self.setWindowTitle("Mod Collection")
        self.resize(900, 560)

        # ``None``, solange das Mod-Wissen (§4.53) nicht geladen ist —
        # beim ersten Start ohne Netz der Normalfall. Alles Weitere faellt
        # dann auf die geschaetzten Baender zurueck, nichts bricht.
        self._knowledge = knowledge
        records = sorted(collection.records(), key=lambda r: r.identity)
        # Für die Sammel-Kopfzeile, die beim Liga-Wechsel neu rechnet
        # (§_on_pot_filter_changed) — dieselbe Liste wie im Modell.
        self._records = records
        self._model = ModAlbumModel(records, collection.new_keys(), knowledge)
        self._proxy = ModAlbumProxy()
        self._proxy.setSourceModel(self._model)
        self._greeting = collection_greeting(records, collection.new_keys())

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
        # ``liga``, nicht ``league`` — der Parameter gleichen Namens wird
        # unten fuer die Vorwahl gebraucht (FALLSTRICKE #80, zum zweiten
        # Mal an diesem Tag: Die Schleife liess die LETZTE Liga stehen).
        seen_leagues = sorted({liga for record in records for liga in record.leagues})
        for liga in seen_leagues:
            self._league_combo.addItem(league_label(liga), liga)
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

        # Die Sortier-Linsen der Kartenansicht (§ALBUM_SORTS). In der
        # Tabelle sortiert der Spaltenkopf; dort ist die Box gesperrt,
        # statt versteckt — sonst spränge die Zeile beim Umschalten.
        self._sort_combo = QComboBox()
        for name, *_ in ALBUM_SORTS:
            self._sort_combo.addItem(name, name)
        self._sort_combo.currentIndexChanged.connect(self._on_album_sort_changed)

        # Benannt nach dem, wohin der Klick führt, nicht nach dem, was
        # gerade zu sehen ist — wie ein Abspielen/Pause-Knopf.
        self._view_button = QPushButton("☰ Show table")
        self._view_button.clicked.connect(self._toggle_view)

        top_row = QHBoxLayout()
        top_row.addWidget(self._search, stretch=1)
        top_row.addWidget(self._kind_combo)
        top_row.addWidget(self._league_combo)
        top_row.addWidget(self._rarity_combo)
        top_row.addWidget(self._sort_combo)
        top_row.addWidget(self._view_button)
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

        # Die Kartenansicht: dieselben Zeilen desselben Proxys, nur als
        # Raster gezeichnet (§ModCardDelegate). ``Batched`` legt die 6125
        # Karten häppchenweise aus, statt das Öffnen aufzuhalten.
        self._cards = QListView()
        self._cards.setModel(self._proxy)
        self._cards.setViewMode(QListView.ViewMode.IconMode)
        self._cards.setFlow(QListView.Flow.LeftToRight)
        self._cards.setWrapping(True)
        self._cards.setResizeMode(QListView.ResizeMode.Adjust)
        self._cards.setLayoutMode(QListView.LayoutMode.Batched)
        self._cards.setUniformItemSizes(True)
        self._cards.setSpacing(6)
        self._cards.setMovement(QListView.Movement.Static)
        self._cards.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._cards.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._cards.setItemDelegate(ModCardDelegate(self._cards))
        # Fester Grund statt Palette: Die Kartenfarben sind gegen
        # #2d2d2d gerechnet (§ALBUM_BG), nicht gegen QPalette.Base.
        self._cards.setStyleSheet(
            f"QListView {{ background-color: {ALBUM_BG}; border: none; }}")
        # EIN Auswahlzustand für beide Ansichten: Wer in der Tabelle eine
        # Zeile wählt und umschaltet, steht auf derselben Karte.
        self._cards.setSelectionModel(self._table.selectionModel())
        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)

        # Ein QTextEdit statt QPlainTextEdit, weil der Steckbrief ZWEI
        # Schriften braucht: Fließtext proportional, NUR die Band-Tabelle
        # fest (§band_table). Der erste Wurf setzte das ganze Feld auf
        # die feste Schrift — Peters Rückmeldung: "dadurch ist dieses
        # Feld kaum noch lesbar."
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._mono_family = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont).family()
        self._detail.setPlaceholderText(self._greeting)

        # Karten zuerst — sie SIND das Album; die Tabelle bleibt einen
        # Klick entfernt das Werkzeug für ernsthaftes Suchen.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._cards)
        self._stack.addWidget(self._table)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._stack)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Die Sammel-Kopfzeile (§album_stats) — über den Karten, damit
        # das Fenster als Sammlung beginnt, nicht als Suchmaske. Gold
        # wie die Komplett-Auszeichnung; auf dem Fenstergrund gerechnet
        # (WCAG 8,0 auf #2d2d2d).
        self._stats_label = QLabel(album_stats(records, knowledge))
        self._stats_label.setStyleSheet(f"color: {HTML_GOLD}; padding: 2px;")

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self._stats_label)
        layout.addWidget(splitter, stretch=1)

        self._update_count_label()
        self._on_album_sort_changed()
        # Erst jetzt, wo Kopfzeile und Detailfeld stehen — die Combos
        # loesen ``_on_pot_filter_changed`` aus, und das setzt beide.
        self._preselect(league, DEFAULT_RARITY_GROUP)

    def _preselect(self, league: str | None, rarity_group: str) -> None:
        """Liga-Topf des Viewers und die gerollten Raritaeten vorwaehlen —
        nur, wenn es die Eintraege gibt (eine Liga ohne einzige Sichtung
        steht nicht in der Box, dann bleibt es bei "All leagues")."""
        if league is not None:
            index = self._league_combo.findData(league_bucket(league))
            if index >= 0:
                self._league_combo.setCurrentIndex(index)
        index = self._rarity_combo.findData(rarity_group)
        if index >= 0:
            self._rarity_combo.setCurrentIndex(index)

    def _toggle_view(self) -> None:
        zur_tabelle = self._stack.currentWidget() is self._cards
        if zur_tabelle:
            self._stack.setCurrentWidget(self._table)
            self._view_button.setText("🃏 Show cards")
            self._sort_combo.setEnabled(False)
            # Die Tabelle sortiert über den Spaltenkopf und erwartet die
            # Anzeige-Rolle — eine übrig gebliebene FIRST_SEEN_ROLE würde
            # jeden Kopf-Klick auf der Mod-Spalte still umdeuten.
            self._proxy.setSortRole(Qt.ItemDataRole.DisplayRole)
            kopf = self._table.horizontalHeader()
            self._table.sortByColumn(kopf.sortIndicatorSection(),
                                     kopf.sortIndicatorOrder())
        else:
            self._stack.setCurrentWidget(self._cards)
            self._view_button.setText("☰ Show table")
            self._sort_combo.setEnabled(True)
            self._on_album_sort_changed()

    def _on_album_sort_changed(self) -> None:
        eintrag = ALBUM_SORTS_BY_NAME.get(self._sort_combo.currentData() or "")
        if eintrag is None or self._stack.currentWidget() is not self._cards:
            return
        spalte, rolle, richtung = eintrag
        self._proxy.setSortRole(rolle)
        self._proxy.sort(spalte, richtung)

    def _on_kind_changed(self) -> None:
        self._proxy.set_kind_filter(self._kind_combo.currentData() or "")
        self._update_count_label()

    def _on_pot_filter_changed(self) -> None:
        league = self._league_combo.currentData()
        rarities = RARITY_GROUPS_BY_NAME.get(self._rarity_combo.currentData() or "")
        self._proxy.set_pot_filter(league, rarities)
        self._model.set_range_filter(league, rarities)
        # Kopfzeile und offener Steckbrief folgen der Liga (§4.53.3) —
        # sonst behauptete der Filter etwas, das die Zahlen darunter
        # nicht einlösen.
        self._stats_label.setText(
            album_stats(self._records, self._knowledge, league))
        self._refresh_detail()
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
        if record is None:
            self._detail.setPlainText("")
            return
        self._detail.setHtml(
            record_detail_html(record, self._mono_family, self._knowledge,
                               self._league_combo.currentData(),
                               RARITY_GROUPS_BY_NAME.get(
                                   self._rarity_combo.currentData() or "")))

    def _refresh_detail(self) -> None:
        """Den offenen Steckbrief neu setzen — nötig, wenn sich nicht die
        Auswahl, sondern die Liga darunter geändert hat."""
        self._on_row_changed(self._table.selectionModel().currentIndex(),
                             QModelIndex())
