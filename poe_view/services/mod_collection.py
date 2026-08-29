"""Die Mod-Sammlung: jede je gesehene Mod-Zeile, mit dem, was sie zeigte.

Peter, 2026-08-24: "Ich finde die Idee mit der eigenen Datenbank am besten,
hat etwas von einer Briefmarkensammlung: Einfach mal jedes Objekt in der
Hand gehalten zu haben und von PoE-VIEW kategorisiert und eingetragen."

**Was hier steht, ist Beobachtung, keine Wahrheit.** Die GGG-Konto-API
liefert Mod-Zeilen als fertigen Text — kein Affix-Name, kein Tier, keine
Wertspanne (nachgemessen am 2026-08-24 an Peters Cache: kein einziges
``extended``/``magnitudes``-Feld). Was diese Sammlung kennt, ist deshalb
ausschließlich, was durch Peters Hände ging: "so oft gesehen, so hoch
und so niedrig gerollt, auf Items dieser Stufen". Der Satz "das ist ein
gutes Tier" steht hier nicht und darf hier nicht stehen — dafür gibt es
den Weg über die Zwischenablage (geplant, siehe ARCHITEKTUR §4.52).

**Die Identität einer Zeile ist die Zeile ohne ihre Zahlen.**
``+96 to maximum Life`` und ``+91 to maximum Life`` sind derselbe Mod mit
zwei Rolls, ``Adds 1 to 5 Lightning Damage`` hat zwei Zahlen und braucht
zwei getrennte Spannen. Diese eine Umformung trägt die ganze Sammlung —
und später auch die Gruppierung mehrzeiliger Affixe, denn zwei Zeilen,
die immer gemeinsam auftreten, sind mit hoher Wahrscheinlichkeit ein
Affix.

**Größenordnung, gemessen statt geschätzt** (Peters Cache, 2026-08-24):
59.249 Items, 200.954 Mod-Zeilen, davon **6.125 verschiedene
Identitäten** — 5.198 explizite, 406 implizite, 320 Verzauberungen, der
Rest Randfälle. Das sind 1,5 MB JSON und 1,3 Sekunden zum Einlesen; ein
Datenbank-Server wäre hier Aufwand ohne Gegenwert. Knapp ein Viertel der
Identitäten kam genau einmal vor — die Sammlung hat von Anfang an
seltene Stücke.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from poe_view import config
from poe_view.api.models import (ENCHANT_MOD_FIELD, EXTRA_MOD_FIELDS,
                                 all_extra_mod_pairs, extra_mod_lines,
                                 item_category, map_tier)
from poe_view.services.atomic_json import write_json
from poe_view.services.csv_export import sanitize_filename

log = logging.getLogger(__name__)

# Erhöhen, sobald sich der Aufbau eines Eintrags ändert. Anders als beim
# XP-Verlauf wird ein alter Stand hier NICHT weggeworfen: Die Sammlung ist
# der einzige Ort, an dem ein längst verkauftes Item noch existiert. Eine
# fremde Version wird stattdessen gelesen, so gut es geht, und beim
# nächsten Speichern in die neue Form gebracht.
#
# 2 (2026-08-24): Spannen liegen je Ligen-Topf statt nur je Rarität
# (§4.52.1). Ein Stand nach Aufbau 1 wird als Altbestand übernommen —
# genau das ist er ja: ununterscheidbar gemischt.
#
# 3 (2026-08-25): ``tier_evidence`` je Eintrag — die Pareto-Front der
# Paare (Wert hoch, iLvl niedrig), aus der sich Tier-Grenzen ableiten
# lassen (§4.52.4, ``services/mod_tiers.py``). Ein Stand nach Aufbau 2
# hat sie nicht; sie wird beim nächsten Start aus dem Cache nachgetragen,
# ohne die Zählstände anzufassen (``backfill_tiers``).
#
# 4 (2026-08-27): ``first_seen`` je Eintrag — Wanduhrzeit des ERSTEN
# Auftauchens, damit das Album "zuletzt eingetragen" sortieren kann
# (§4.52.5). 0 heißt Grundstock: Der Eintrag war schon da, bevor das
# Datum mitgeschrieben wurde, und ein nachträglich erfundenes wäre eine
# Behauptung. Nicht nachtragbar — der Cache weiß nicht, WANN ein Item
# zum ersten Mal durch die Truhe ging.
#
# 5 (2026-08-28): ``tier_ledger`` statt der bloßen Pareto-Front — je
# Basis-Kategorie und WERT die Sichtungen samt iLvl-Spanne. Peter wollte
# je Tier-Band eine Zeile "Count | Min | Max | iLvl-Min | iLvl-Max",
# und Zählungen je Band lassen sich aus einer Front nicht gewinnen. Die
# Front ist umgekehrt aus dem Kontenbuch jederzeit ableitbar
# (``tier_front``), deshalb ersetzt es sie, statt daneben zu liegen.
# Ein alter ``tiers``-Block wird beim Laden verworfen; der Nachtrag aus
# dem Cache (``backfill_tiers``) läuft dann beim nächsten Start von
# selbst wieder an, wie beim Sprung von Aufbau 2 auf 3. Gemessen an
# Peters Cache: 32.258 Wert-Zeilen, ~0,7 MB.
#
# 6 (2026-08-28): Das Kontenbuch bekommt eine LIGA-Ebene davor —
# ``liga_topf -> kategorie -> wert``, dieselben Töpfe wie ``spans``
# (§league_bucket). Anlass war Peters Album-Screenshot mit Liga-Filter
# "SSF R Allflame": Slots, Häkchen und Leitern rechneten über ALLE
# Ligen, der Filter daneben behauptete das Gegenteil. Die Tier-
# SCHWELLEN hängen zwar nicht an der Liga (die Begründung von Aufbau 5
# stimmt weiter), aber die SAMMLUNG tut es — "welche Tiers habe ich in
# dieser Liga gerollt" ist genau die Frage, die ein Liga-Filter stellt.
# Ohne Filter merged ``ledgers(None)`` die Töpfe wieder zusammen und
# liefert exakt den alten Stand. Ein ``ledger``-Block aus Aufbau 5
# (Kategorie direkt außen) wird beim Laden verworfen — der Cache kennt
# die Liga jedes Items, also baut ``backfill_tiers`` das Buch beim
# nächsten Start liga-getrennt neu, wie bei den Sprüngen davor.
#
# 7 (2026-08-29): **Die Zählstände selbst waren falsch.** Seit dem Bau
# der Sammlung reichte das Fenster bei JEDEM Abruf eines Fachs oder
# Charakters alle Items erneut an ``observe_items`` — und der Charakter
# wird beim Auto-Refresh alle ~56 s abgeholt. Peter sah im Album seiner
# frischen Liga "T2 71× gesehen" für EIN Paar Boots (81 Abrufe seit dem
# Neuaufbau). Eine Sichtung heißt seither "ein Item durch die Hände
# gegangen", nicht "eine Abfrage" (``fresh_items``), und ein Stand aus
# Aufbau ≤ 6 wird nicht übernommen, sondern aus dem Cache neu gezählt —
# jedes Item genau einmal. Behalten wird dabei NUR ``first_seen`` je
# Eintrag (das lässt sich aus dem Cache nicht wiedergewinnen); Einträge,
# die beim Neuaufbau nicht mehr auftauchen (verkauft, zerlegt), fallen
# weg — Peters Entscheidung, weil die alten Zahlen sonst für immer
# verfälscht blieben. Die alte Datei bleibt daneben liegen (``retire``).
#
# 8 (2026-08-29): Hauptwerte als eigene Art ``BASE_STAT_KIND`` —
# Rüstung, Ausweichen, Energieschild, Schaden, Crit, APS je Kategorie
# als Pseudo-Zeilen ("Body Armour: Armour 668"), §4.52.8. Das
# Dateiformat ändert sich NICHT, nur eine neue Art steht in den Zeilen;
# ein Stand ohne sie (``has_base_stats`` False) bekommt sie beim
# nächsten Start aus dem Cache nachgetragen (``backfill_base_stats``),
# ohne einen Mod-Zählstand anzufassen.
VERSION = 8

# Die Felder der API, deren Inhalt gesammelt wird — die Art eines
# Eintrags IST der Feldname. Getrennt gehalten statt in einen Topf
# geworfen: Dieselbe Zeile bedeutet als Verzauberung etwas anderes als
# als Affix, und die Spannen unterscheiden sich.
#
# Die Liste kommt bewusst aus ``api.models`` und wird hier nicht neu
# aufgezählt. Beim ersten Entwurf dieser Datei hatte ich sie abgeschrieben
# und dabei ``utilityMods`` vergessen — 2083 Items in Peters Bestand, und
# genau der Fehler, vor dem der Kommentar an ``EXTRA_MOD_FIELDS`` warnt
# ("Genau EINE davon zu vergessen ist der Fehler, den es zu verhindern
# gilt"). Eine Liste an zwei Orten ist eine Liste, die auseinanderläuft.
# ``BASE_STAT_KIND`` ist der eine Eintrag, der NICHT aus der API kommt:
# die Hauptwerte eines Items (Rüstung, Schaden, …) als eigene Art, damit
# sie denselben Weg gehen wie Mod-Zeilen — Spannen je Liga und Rarität,
# Karte im Album, Balken am Item (§4.52.8). Der Name ist erfunden und
# kollidiert absichtlich mit keinem API-Feld.
BASE_STAT_KIND = "baseStats"
MOD_KINDS = ("explicitMods", "implicitMods", ENCHANT_MOD_FIELD,
             *EXTRA_MOD_FIELDS, BASE_STAT_KIND)

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")

# Die Hauptwerte, die als Pseudo-Zeile in die Sammlung gehen (Peter,
# 2026-08-29: "den Rüstungswert und Schadenswert in Abhängigkeit von der
# jeweiligen Rüstungs- oder Waffenart" — Rohwerte einzeln, seine Wahl).
# Gemessen an seinem Cache tragen Rüstungsteile Armour/Evasion/Energy
# Shield/Ward, Schilde dazu Chance to Block, Waffen Physical Damage,
# Critical Strike Chance, Attacks per Second und Elemental Damage.
# Quality, Weapon Range und Memory Strands sind absichtlich nicht dabei:
# keine Basiseigenschaft, die man sammelt.
BASE_STATS = ("Armour", "Evasion Rating", "Energy Shield", "Ward",
              "Chance to Block", "Physical Damage", "Elemental Damage",
              "Critical Strike Chance", "Attacks per Second")

# Eine Schadens-Spanne der API: ``"42-127"``. NICHT über ``_NUMBER``
# lesen — dort wäre ``-127`` eine negative Zahl.
_DAMAGE_RANGE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$")


def base_stat_line(category: str, prop) -> str | None:
    """Die Pseudo-Zeile eines Hauptwerts, oder ``None`` für alles, was
    keiner ist: ``"Body Armour: Armour 668"``,
    ``"Bow: Physical Damage 42 to 127"``.

    Die Kategorie steht vorn, weil ein Rüstungswert nur je Rüstungsart
    etwas bedeutet — 668 ist auf Handschuhen enorm und auf einer
    Brustrüstung mager. Schadens-Spannen werden mit ``to`` geschrieben
    wie im Spiel ("Adds 42 to 127"), nicht mit Bindestrich: ``mod_values``
    läse ``-127`` sonst als negative Zahl. Elementarschaden ist die SUMME
    über die Elemente — Feuer, Kälte und Blitz stehen in der API als drei
    Werte, gesammelt wird der Gesamtwert, der beim Vergleichen zählt."""
    name = getattr(prop, "name", "")
    if name not in BASE_STATS or not category:
        return None
    werte = getattr(prop, "values", None) or []
    if name == "Elemental Damage":
        lo = hi = 0.0
        for eintrag in werte:
            treffer = _DAMAGE_RANGE.match(str(eintrag[0])) if eintrag else None
            if treffer is None:
                return None
            lo += float(treffer.group(1))
            hi += float(treffer.group(2))
        if not werte:
            return None
        return f"{category}: {name} {_as_number(lo)} to {_as_number(hi)}"
    try:
        wert = str(werte[0][0])
    except (IndexError, TypeError):
        return None
    treffer = _DAMAGE_RANGE.match(wert)
    if treffer:
        return f"{category}: {name} {treffer.group(1)} to {treffer.group(2)}"
    return f"{category}: {name} {wert}"


def base_stat_lines(item) -> list[str]:
    """Alle Hauptwert-Zeilen eines Items (§base_stat_line)."""
    category = item_category(item) or ""
    if not category:
        return []
    zeilen = []
    for prop in getattr(item, "properties", None) or []:
        zeile = base_stat_line(category, prop)
        if zeile is not None:
            zeilen.append(zeile)
    return zeilen

# Ab so vielen fehlenden Einträgen gilt ein Speichervorgang als
# Datenverlust und wird abgelehnt. Die Sammlung wächst nur; sie schrumpft
# höchstens, wenn etwas kaputt ist (dieselbe Lehre wie beim Daten-Cache,
# FALLSTRICKE #62 — dort haben zwei echte Verluste die Regel erzwungen).
_SHRINK_TOLERANCE = 0


def mod_identity(line: str) -> str:
    """Die Zeile ohne ihre Zahlen — die Identität des Mods.

    ``+96 to maximum Life`` → ``+# to maximum Life``. Vorzeichen und
    Nachkommastellen gehören zur Zahl und verschwinden mit ihr, sonst
    wären ``+96`` und ``96`` zwei verschiedene Mods."""
    return _NUMBER.sub("#", line).strip()


def mod_values(line: str) -> list[float]:
    """Die Zahlen der Zeile, in ihrer Reihenfolge.

    Die Reihenfolge ist bedeutungstragend: Bei ``Adds 1 to 5 Lightning
    Damage`` ist die erste Zahl das Minimum des Schadens und die zweite
    sein Maximum. Zwei getrennte Spannen also, nicht eine gemeinsame."""
    return [float(treffer) for treffer in _NUMBER.findall(line)]


# So viele Punkte darf eine Front höchstens behalten. Sie ist durch die
# Zahl der Tiers von Natur aus kurz (gemessen an Peters Bestand: p50=1,
# p99=9, längste 27), aber ein Mod mit vielen Zahlenwerten und breitem
# iLvl-Bereich könnte sie theoretisch aufblähen. Die Kappung wirft die
# Punkte mit dem HÖCHSTEN iLvl weg — die tragen am wenigsten bei, denn
# die Auflösung kommt von unten (§4.52.4).
_MAX_EVIDENCE = 40

# Obergrenze für das Tier-Kontenbuch: so viele VERSCHIEDENE Werte darf
# eine Kategorie führen. Gemessen an Peters Cache liegt das Maximum bei
# 76 (``# to maximum Life``); die Grenze ist reine Vorsicht gegen einen
# Mod, der irgendwann mit Nachkommastellen in jeder Schattierung rollt.
_MAX_LEDGER_VALUES = 512


def add_evidence(front: list[tuple[float, int]], wert: float,
                 ilvl: int) -> list[tuple[float, int]]:
    """Einen Beleg in die Pareto-Front einarbeiten.

    Die Front hält genau die Paare, für die es keinen anderen Beleg mit
    gleichzeitig **höherem oder gleichem Wert UND niedrigerem oder
    gleichem iLvl** gibt. Das ist die Treppe "was war auf welchem Item-
    Level höchstens drin" — und ihre Länge hängt an der Zahl der Tiers,
    nicht an der Zahl der Beobachtungen. 1323 Sichtungen von ``#% to Cold
    Resistance`` schrumpfen so auf 15 Punkte.

    Jeder Punkt ist ein BELEG, keine Schätzung: "diesen Wert habe ich auf
    diesem Item-Level gesehen". Fehlende Daten können die Treppe nur zu
    vorsichtig machen, nie falsch."""
    for w, il in front:
        if w >= wert and il <= ilvl:
            return front                      # schon dominiert
    neu = [(w, il) for w, il in front if not (wert >= w and ilvl <= il)]
    neu.append((wert, ilvl))
    neu.sort()
    if len(neu) > _MAX_EVIDENCE:
        neu = neu[:_MAX_EVIDENCE]
    return neu


def _as_number(wert: float) -> float | int:
    """Ganze Zahlen als ``int`` ablegen — sonst stünde in der Datei
    ``96.0`` für etwas, das im Spiel ``96`` heißt."""
    return int(wert) if float(wert).is_integer() else wert


@dataclass
class RaritySpan:
    """Was eine Identität AUF EINER RARITÄT gezeigt hat.

    Die Trennung ist keine Kosmetik, sondern kam aus der Messung: In
    einem Topf reichte ``# to maximum Life`` in Peters Bestand von −148
    bis +500 — dieselbe Zeile steht auf Rares als gerollter Affix, auf
    Uniques mit festem Wert und auf korrumpierten Sachen mit negativem.
    Eine Spanne über all das beantwortet die Frage "ist das ein guter
    Roll?" nicht, sie verhindert sie."""

    count: int = 0
    lows: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    ilvl_low: int = 0
    ilvl_high: int = 0

    def observe(self, values: Sequence[float], ilvl: int) -> None:
        self.count += 1
        if not self.lows:
            self.lows = list(values)
            self.highs = list(values)
        elif len(values) == len(self.lows):
            for i, wert in enumerate(values):
                self.lows[i] = min(self.lows[i], wert)
                self.highs[i] = max(self.highs[i], wert)
        if ilvl > 0:
            self.ilvl_low = min(self.ilvl_low or ilvl, ilvl)
            self.ilvl_high = max(self.ilvl_high, ilvl)

    @property
    def spread(self) -> list[tuple[float, float]]:
        return list(zip(self.lows, self.highs))

    def rating(self, values: Sequence[float]) -> float | None:
        """Wo liegt dieser Roll in dem, was bisher zu sehen war?

        0.0 = der schlechteste bisher gesehene, 1.0 = der beste.
        ``None``, wenn es nichts zu vergleichen gibt — keine Zahl, oder
        die Spanne besteht noch aus einem einzigen Wert. Ein erfundener
        Vergleich wäre schlimmer als keiner.

        Über ALLE Zahl-Positionen gemittelt: Bei ``Adds # to #`` ist
        weder die erste noch die zweite allein aussagekräftig."""
        if not values or len(values) != len(self.lows):
            return None
        anteile = [(wert - tief) / (hoch - tief)
                   for wert, tief, hoch in zip(values, self.lows, self.highs)
                   if hoch > tief]
        return sum(anteile) / len(anteile) if anteile else None

    def to_row(self) -> dict:
        return {"count": self.count,
                "lows": [_as_number(w) for w in self.lows],
                "highs": [_as_number(w) for w in self.highs],
                "ilvl_low": self.ilvl_low, "ilvl_high": self.ilvl_high}

    @classmethod
    def from_row(cls, row: object) -> "RaritySpan":
        spanne = cls()
        if not isinstance(row, dict):
            return spanne
        def zahlen(schluessel: str) -> list[float]:
            werte = row.get(schluessel) or []
            return ([float(w) for w in werte if isinstance(w, (int, float))]
                    if isinstance(werte, list) else [])
        spanne.count = int(row.get("count") or 0)
        spanne.lows, spanne.highs = zahlen("lows"), zahlen("highs")
        if len(spanne.lows) != len(spanne.highs):
            spanne.lows = spanne.highs = []
        spanne.ilvl_low = int(row.get("ilvl_low") or 0)
        spanne.ilvl_high = int(row.get("ilvl_high") or 0)
        return spanne


# Rarität eines Items, wenn die API keine nennt. Eigener Wert statt 0
# ("Normal"), damit ein fehlendes Feld nicht als weiße Ausrüstung gezählt
# wird — das wäre eine Behauptung, die niemand aufgestellt hat.
UNKNOWN_RARITY = -1

# Maps bekommen einen eigenen Topf, obwohl die API sie als Magic oder
# Rare führt. Gemessen an Peters Bestand: Ohne die Trennung reichte
# ``#% to Fire Resistance`` bei "Rare" von −60 bis +92, weil eine Map mit
# "-60% to Fire Resistance" (die Strafe für den Spieler) in denselben
# Topf fiel wie ein Ring mit "+92%". Map-Mods sind keine Ausrüstungs-
# Affixe; sie rollen aus einer anderen Tabelle und in andere Richtungen.
MAP_RARITY = -2


# Die dauerhaften Ligen. Sie sammeln seit Jahren die Items aus jeder
# abgelaufenen Liga ein — ein Ring aus Kalandra liegt heute in Standard.
# Sie in EINEN Topf zu werfen ist deshalb keine Vereinfachung, sondern die
# ehrliche Beschreibung: Was dort liegt, wurde irgendwann gerollt, und
# wann, weiß niemand. Gemessen an Peters Bestand liegen dort 98 % seiner
# Items (58.190 von 59.244).
#
# Eine unbekannte Liga gilt als temporär und bekommt ihren eigenen Topf.
# Das ist die richtige Richtung zum Irren: Eine neue dauerhafte Liga
# stünde dann für sich, statt stillschweigend in den Altbestand zu
# rutschen.
PERMANENT_LEAGUES = frozenset({
    "Standard", "Hardcore", "Solo Self-Found", "Hardcore SSF",
    "Ruthless", "Hardcore Ruthless", "SSF Ruthless", "Hardcore SSF Ruthless",
})

# Der Topf für alles aus den dauerhaften Ligen. Leerer String, damit er in
# der JSON-Datei kurz ist und beim Sortieren vorne steht.
LEGACY_LEAGUE = ""

# So viele Beobachtungen braucht die eigene Liga, bevor ihre Spanne den
# Vergleich trägt. Darunter wird gegen den Altbestand verglichen und das
# in der Anzeige gesagt. Die Zahl ist eine Setzung, keine Messung: Unter
# einer Handvoll Rolls ist eine Spanne mehr Zufall als Aussage.
MIN_LEAGUE_OBSERVATIONS = 5


def league_bucket(league: str | None) -> str:
    """In welchen Ligen-Topf gehört ein Item dieser Liga?

    Temporäre Ligen bekommen einen eigenen — dort wurde alles in dieser
    Liga gerollt, also nach der Werte-Tabelle dieser Liga. Die dauerhaften
    teilen sich den Altbestand (siehe ``PERMANENT_LEAGUES``)."""
    if not league or league in PERMANENT_LEAGUES:
        return LEGACY_LEAGUE
    return league


# Aufschlag für Corrupted-Items, addiert auf die echte Rarität statt
# eines eigenen Topfs wie bei ``MAP_RARITY``: Ein corrupted Rare bleibt
# damit von einem corrupted Unique getrennt (der eigentliche Grund für
# die Rarity-Bucketierung, §4.52.1) — UND von einem gewöhnlichen Rare.
# Manche Corruption-Ergebnisse sind eigene Implicit-Zeilen mit eigener
# Wertetabelle (etwa eine grosse negative Resistenz als Strafe), die
# sonst die Spanne des gewöhnlichen Topfs verzerrt hätten.
#
# Peter, 2026-08-25: "...auch zwischen Unique, Corrupted, (Normal/Magic/
# Rare)..." — wählbar in der Album-Anzeige (``ui/mod_album.py``).
#
# **Nur NEUE Beobachtungen werden getrennt.** Ein Wert, der VOR dieser
# Änderung im gewöhnlichen Topf gelandet ist, bleibt dort für immer stehen
# — ``RaritySpan`` kennt nur "je gesehen", kein Rückgängig. Die Trennung
# wirkt nur nach vorn, wie schon bei der Liga-Trennung (§4.52.1: "Ein
# Stand nach Aufbau 1 wird als Altbestand übernommen").
#
# Maps bekommen den Aufschlag NICHT: Sie haben bereits ihren eigenen Topf
# (``MAP_RARITY``), und Kartenkorruption fügt keine neuen Implicit-Zeilen
# mit eigener Tabelle hinzu wie bei Ausrüstung — der Mechanismus, der den
# Aufschlag hier überhaupt rechtfertigt, greift dort nicht.
CORRUPTED_OFFSET = 1000


def is_corrupted_bucket(rarity: int) -> bool:
    """War die Rarität dieses Topfs mit dem Corrupted-Aufschlag codiert?"""
    return rarity >= CORRUPTED_OFFSET


def base_rarity(rarity: int) -> int:
    """Die zugrunde liegende Rarität ohne den Corrupted-Aufschlag."""
    return rarity - CORRUPTED_OFFSET if is_corrupted_bucket(rarity) else rarity


def collection_bucket(item) -> int:
    """In welchen Topf gehören die Mods dieses Items?

    Die Rarität aus ``frameType``, außer bei Maps — die kommen in ihren
    eigenen (siehe ``MAP_RARITY``). Corrupted-Items bekommen zusätzlich
    den ``CORRUPTED_OFFSET`` aufaddiert (siehe dort)."""
    if map_tier(item) is not None:
        return MAP_RARITY
    # ``frameType`` ist im Modell mit 0 vorbelegt, und 0 heisst "Normal".
    # Ein Item, dessen Antwort das Feld gar nicht enthielt, waere damit
    # stillschweigend weisse Ausruestung. ``model_fields_set`` sagt, was
    # wirklich in der Antwort stand.
    gesetzt = getattr(item, "model_fields_set", ())
    if "frameType" not in gesetzt:
        rarity = UNKNOWN_RARITY
    else:
        wert = getattr(item, "frameType", None)
        rarity = int(wert) if isinstance(wert, int) else UNKNOWN_RARITY
    return rarity + CORRUPTED_OFFSET if getattr(item, "corrupted", False) else rarity


def tierable(rarity: int, ilvl: int) -> bool:
    """Taugt eine Beobachtung aus diesem Topf für die Tier-Ableitung?

    Nur **gerollte Affixe auf unkorrumpierten Magic-/Rare-Items**, und
    nur mit bekanntem Item-Level. Alles andere trägt nichts bei oder
    verfälscht:

    * Normal (0) hat keine Affixe, Unique (3) feste Werte statt Rolls.
    * Maps rollen aus einer eigenen Tabelle (§MAP_RARITY).
    * Korrumpiertes bringt Vaal-Ergebnisse mit eigenen Wertebereichen
      mit — in Peters Bestand steht deshalb ein `-40` in derselben
      Zeile, die sonst bei +6 anfängt.
    * Ohne Item-Level gibt es keine Achse, an der sich etwas auflösen
      ließe.

    **Korrumpiertes braucht keine eigene Abfrage**, obwohl es der erste
    Entwurf hatte: Der Aufschlag (``CORRUPTED_OFFSET``) hebt die Rarität
    auf 1001/1002, und die stehen nicht in ``(1, 2)``. Die zusätzliche
    Prüfung war toter Code — aufgefallen, weil ihre Gegenprobe überlebte
    (sie herauszunehmen änderte nichts)."""
    return ilvl > 0 and rarity in (1, 2)


def item_buckets(item) -> tuple[str, int]:
    """Ligen- und Raritäts-Topf eines Items, wie die Sammlung sie braucht.

    Die Liga kommt vom ITEM, nicht aus der Auswahl im Fenster: Ein Ring in
    Standard gehört in den Altbestand, auch wenn man gerade die laufende
    Liga betrachtet."""
    return league_bucket(getattr(item, "league", "")), collection_bucket(item)


def item_fingerprint(item) -> tuple:
    """Woran die Sammlung ein Item wiedererkennt: seine ID plus alle
    Mod-Zeilen. Die ID allein reicht nicht — ein gecraftetes Item behält
    sie und hat trotzdem neue Zeilen, die gezählt werden sollen."""
    return (getattr(item, "id", None), getattr(item, "typeLine", ""),
            tuple(item.explicit_mods), tuple(item.implicit_mods),
            tuple(all_extra_mod_pairs(item)),
            tuple(extra_mod_lines(item, ENCHANT_MOD_FIELD)))


def fresh_items(items: Iterable, previous: Iterable) -> list:
    """Nur die Items, die es im vorigen Stand desselben Fachs/Charakters
    noch nicht gab — der Filter vor jedem ``observe_items`` (§VERSION,
    Aufbau 7).

    Eine Sichtung soll "ein Item durch die Hände gegangen" heißen. Ohne
    diesen Filter zählte jeder Abruf desselben Fachs alles erneut, und
    der Charakter wird beim Auto-Refresh alle ~56 s abgeholt: Peters
    Boots standen nach 81 Abrufen mit "71× gesehen" im Album. Verglichen
    wird gegen den vorigen Stand des GLEICHEN Behälters, nicht gegen die
    ganze Sammlung — das braucht keinen Speicher, und ein Item, das in
    ein anderes Fach wandert, zählt höchstens einmal mehr."""
    bekannt = {item_fingerprint(alt) for alt in previous}
    return [item for item in items if item_fingerprint(item) not in bekannt]


@dataclass
class ModRecord:
    """Was die Sammlung über eine Mod-Identität weiß.

    ``example`` ist die zuerst gesehene Zeile im Original, damit die
    Anzeige nicht aus Identität und Zahlen wieder einen Satz bauen muss.
    Die Spannen liegen je Rarität daneben (siehe ``RaritySpan``)."""

    identity: str
    kind: str
    count: int = 0
    example: str = ""
    # Wanduhrzeit des ersten Auftauchens (§VERSION, Aufbau 4). 0 heißt
    # Grundstock — der Eintrag ist älter als die Aufzeichnung des Datums.
    first_seen: float = 0.0
    # Spannen je Ligen-Topf und darin je Rarität. Zwei Ebenen statt eines
    # zusammengesetzten Schlüssels, damit die Datei lesbar bleibt und der
    # Altbestand als eigener Block sichtbar ist.
    spans: dict[str, dict[int, RaritySpan]] = field(default_factory=dict)
    # Das Kontenbuch für die Tier-Ableitung, je Ligen-Topf und darin je
    # Basis-Kategorie: je WERT die Zahl der Sichtungen und die iLvl-
    # Spanne, ``liga -> kategorie -> wert -> [n, il_min, il_max]``.
    # Daraus kommt beides: die Pareto-Front für die Bänder
    # (``tier_front``) UND die Zeile je Band im Album ("Count | Min |
    # Max | iLvl" — Peters Tabelle, 2026-08-27).
    #
    # Die Kategorie ist eine eigene Achse, keine Verfeinerung der
    # Rarität: Ein Ring rollt eine andere Tier-Tabelle als eine Rüstung,
    # bei identischem Text; ohne diese Trennung verschmiert die Leiter.
    # Die LIGA steht seit Aufbau 6 davor (§VERSION): Die Schwellen
    # hängen nicht an ihr, wohl aber die Antwort "welche Tiers habe ICH
    # dort gerollt" — und die stellt das Album mit Liga-Filter. Wer alle
    # Ligen meint, fragt ``ledgers(None)`` und bekommt die Töpfe
    # zusammengelegt; nie direkt in dieses Feld greifen.
    tier_ledger: dict[str, dict[str, dict[float, list[int]]]] = field(
        default_factory=dict)

    def observe(self, line: str, *, ilvl: int = 0,
                rarity: int = UNKNOWN_RARITY,
                league: str = LEGACY_LEAGUE,
                category: str = "") -> None:
        """Eine weitere Sichtung einarbeiten."""
        self.count += 1
        if not self.example:
            self.example = line
        je_liga = self.spans.setdefault(league, {})
        spanne = je_liga.get(rarity)
        if spanne is None:
            spanne = je_liga[rarity] = RaritySpan()
        werte = mod_values(line)
        spanne.observe(werte, ilvl)
        self.observe_tier_evidence(werte, ilvl=ilvl, rarity=rarity,
                                   category=category, league=league)

    def observe_tier_evidence(self, values: Sequence[float], *, ilvl: int,
                              rarity: int, category: str,
                              league: str = LEGACY_LEAGUE) -> bool:
        """Nur das Tier-Kontenbuch führen, ohne die Album-Zählstände.

        Getrennt von ``observe``, weil ein alter Stand die Belege
        nachtragen muss, OHNE dass die Sichtungen ein zweites Mal in die
        Spannen gezählt werden (``ModCollection.backfill_tiers``).

        Gibt zurück, ob der Beleg überhaupt taugte."""
        if not tierable(rarity, ilvl) or not category or len(values) != 1:
            return False
        konto = self.tier_ledger.setdefault(league, {}).setdefault(category, {})
        zeile = konto.get(values[0])
        if zeile is None:
            if len(konto) >= _MAX_LEDGER_VALUES:
                # Reine Vorsicht — gemessen sind es höchstens 76
                # verschiedene Werte je Topf. Bestehende Werte zählen
                # weiter, nur neue kämen nicht mehr dazu.
                return False
            konto[values[0]] = [1, ilvl, ilvl]
            return True
        zeile[0] += 1
        zeile[1] = min(zeile[1], ilvl)
        zeile[2] = max(zeile[2], ilvl)
        return True

    def ledgers(self, league: str | None = None
                ) -> dict[str, dict[float, list[int]]]:
        """Das Kontenbuch, gesehen durch die Liga-Auswahl des Albums:
        ``kategorie -> wert -> [n, il_min, il_max]``.

        ``None`` heißt "alle Ligen" — die Töpfe werden zusammengelegt
        (Sichtungen addiert, iLvl-Spannen vereinigt) und ergeben exakt
        den Stand, den das Kontenbuch vor der Liga-Trennung führte. Ein
        Liga-Schlüssel liefert nur diesen Topf. Die Antwort ist immer
        eine frische Kopie; wer sie verändert, verändert nichts."""
        if league is not None:
            return {kat: {wert: list(zeile)
                          for wert, zeile in konto.items()}
                    for kat, konto in self.tier_ledger.get(league, {}).items()}
        ergebnis: dict[str, dict[float, list[int]]] = {}
        for je_liga in self.tier_ledger.values():
            for kat, konto in je_liga.items():
                ziel = ergebnis.setdefault(kat, {})
                for wert, (n, il_min, il_max) in konto.items():
                    zeile = ziel.get(wert)
                    if zeile is None:
                        ziel[wert] = [n, il_min, il_max]
                    else:
                        zeile[0] += n
                        zeile[1] = min(zeile[1], il_min)
                        zeile[2] = max(zeile[2], il_max)
        return ergebnis

    def tier_front(self, category: str,
                   league: str | None = None) -> list[tuple[float, int]]:
        """Die Pareto-Front (Wert hoch, iLvl niedrig) aus dem Kontenbuch —
        die Eingabe für ``mod_tiers.bands``. Für die Front zählt je Wert
        nur sein NIEDRIGSTES iLvl, deshalb verliert die Ableitung nichts
        gegenüber dem früheren direkten Mitschreiben (Aufbau 3/4)."""
        front: list[tuple[float, int]] = []
        for wert, (_, il_min, _il_max) in sorted(
                self.ledgers(league).get(category, {}).items()):
            front = add_evidence(front, wert, il_min)
        return front

    @property
    def leagues(self) -> list[str]:
        return sorted(self.spans)

    @property
    def rarities(self) -> list[int]:
        return sorted({rarity for je_liga in self.spans.values() for rarity in je_liga})

    def span(self, rarity: int, league: str = LEGACY_LEAGUE) -> RaritySpan | None:
        return self.spans.get(league, {}).get(rarity)

    def rating(self, line: str, rarity: int = UNKNOWN_RARITY,
               league: str = LEGACY_LEAGUE) -> float | None:
        """Der Vergleich bleibt INNERHALB von Liga und Rarität. Ohne
        Eintrag dafür gibt es keinen Vergleich, auch wenn andere Töpfe
        Werte hätten."""
        spanne = self.span(rarity, league)
        return spanne.rating(mod_values(line)) if spanne is not None else None

    def rating_with_basis(self, line: str, rarity: int = UNKNOWN_RARITY,
                          league: str = LEGACY_LEAGUE
                          ) -> tuple[float | None, str]:
        """Bewertung plus die Angabe, WORAUF sie sich stützt.

        Die eigene Liga zählt erst ab ``MIN_LEAGUE_OBSERVATIONS``
        Sichtungen; darunter ist ihre Spanne mehr Zufall als Aussage, und
        dann wird gegen den Altbestand verglichen. Welcher Topf es war,
        gehört zur Antwort — eine Bewertung, deren Grundlage man nicht
        kennt, ist keine."""
        wert, grundlage, _ = self.rating_detail(line, rarity, league)
        return wert, grundlage

    def rating_detail(self, line: str, rarity: int = UNKNOWN_RARITY,
                      league: str = LEGACY_LEAGUE
                      ) -> tuple[float | None, str, int]:
        """Dasselbe wie ``rating_with_basis``, zusätzlich mit der Zahl der
        Sichtungen, auf denen die Bewertung steht.

        Die Zahl gehört dazu, seit die Anzeige einen BALKEN daraus macht
        (§4.52.2): Ein Stern sagte "bester Roll, den ich kenne", ein
        gefüllter Balken sieht dagegen nach einer Skala aus. Wie belastbar
        die ist, hängt daran, wie oft die Zeile schon durch Peters Hände
        ging — und das kann nur der Aufrufer entscheiden, weil dieselbe
        Spanne für eine Randnotiz reicht und für eine Skala nicht."""
        eigene = self.span(rarity, league)
        if (league != LEGACY_LEAGUE and eigene is not None
                and eigene.count >= MIN_LEAGUE_OBSERVATIONS):
            wert = eigene.rating(mod_values(line))
            if wert is not None:
                return wert, league, eigene.count
        alt = self.span(rarity, LEGACY_LEAGUE)
        if alt is None:
            return None, LEGACY_LEAGUE, 0
        return alt.rating(mod_values(line)), LEGACY_LEAGUE, alt.count

    def to_row(self) -> dict:
        return {
            "identity": self.identity,
            "kind": self.kind,
            "count": self.count,
            "example": self.example,
            # Nur wenn bekannt — 6000+ Grundstock-Einträge mit einer
            # bedeutungslosen 0 würden die Datei nur verlängern.
            **({"first_seen": self.first_seen} if self.first_seen > 0 else {}),
            "spans": {liga: {str(rarity): spanne.to_row()
                             for rarity, spanne in sorted(je_liga.items())}
                      for liga, je_liga in sorted(self.spans.items())},
            "ledger": {liga: {kat: [[_as_number(wert), *zeile]
                              for wert, zeile in sorted(konto.items())]
                              for kat, konto in sorted(je_liga.items())
                              if konto}
                       for liga, je_liga in sorted(self.tier_ledger.items())
                       if any(je_liga.values())},
        }

    @classmethod
    def from_row(cls, row: dict) -> "ModRecord | None":
        """Eine Zeile aus der Datei. ``None``, wenn sie unbrauchbar ist —
        eine kaputte Zeile darf nicht die ganze Sammlung kosten."""
        identity = row.get("identity")
        kind = row.get("kind")
        if not isinstance(identity, str) or not identity or kind not in MOD_KINDS:
            return None
        eintrag = cls(identity=identity, kind=kind,
                      count=int(row.get("count") or 0),
                      example=str(row.get("example") or ""))
        first_seen = row.get("first_seen")
        if isinstance(first_seen, (int, float)) and first_seen > 0:
            eintrag.first_seen = float(first_seen)
        def raritaeten_lesen(quelle: object) -> dict[int, RaritySpan]:
            ergebnis: dict[int, RaritySpan] = {}
            if isinstance(quelle, dict):
                for schluessel, spanne in quelle.items():
                    try:
                        rarity = int(schluessel)
                    except (TypeError, ValueError):
                        continue
                    ergebnis[rarity] = RaritySpan.from_row(spanne)
            return ergebnis

        # Ein ``tiers``-Block aus Aufbau 3/4 (die bloße Front) wird
        # bewusst NICHT übernommen: Ohne Zählungen wäre er im Kontenbuch
        # eine Zeile mit erfundenem ``n`` — der Nachtrag aus dem Cache
        # baut stattdessen beim nächsten Start das volle Buch auf.
        # Ein ``ledger``-Block aus Aufbau 5 (Kategorie direkt außen, der
        # Wert der zweiten Ebene ist dann eine LISTE statt eines dicts)
        # fällt aus demselben Grund durch das ``isinstance``-Sieb: Er
        # kennt die Liga nicht, und ein erfundener Liga-Topf wäre eine
        # Behauptung — der Nachtrag kennt sie (§VERSION, Aufbau 6).
        ledger = row.get("ledger")
        if isinstance(ledger, dict):
            for liga, je_liga in ledger.items():
                if not isinstance(liga, str) or not isinstance(je_liga, dict):
                    continue
                for kat, zeilen in je_liga.items():
                    if not isinstance(kat, str) or not isinstance(zeilen, list):
                        continue
                    konto = {}
                    for zeile in zeilen:
                        if (isinstance(zeile, list) and len(zeile) == 4
                                and all(isinstance(x, (int, float))
                                        for x in zeile)):
                            konto[float(zeile[0])] = [int(zeile[1]),
                                                      int(zeile[2]),
                                                      int(zeile[3])]
                    if konto:
                        eintrag.tier_ledger.setdefault(liga, {})[kat] = konto

        spans = row.get("spans")
        if isinstance(spans, dict):
            for liga, je_liga in spans.items():
                if isinstance(liga, str):
                    eintrag.spans[liga] = raritaeten_lesen(je_liga)
        elif "by_rarity" in row:
            # Aufbau der ersten Fassung, vor der Ligen-Trennung: Alles, was
            # dort steht, ist ununterscheidbar gemischt — also genau das,
            # was der Altbestand ist. Lieber übernehmen als wegwerfen.
            eintrag.spans[LEGACY_LEAGUE] = raritaeten_lesen(row.get("by_rarity"))
        return eintrag


class ModCollection:
    """Alle gesehenen Mod-Zeilen eines Kontos.

    Reine Datenhaltung ohne Qt und ohne Dateizugriff im Konstruktor: Die
    Sammlung lässt sich damit ohne Fenster und ohne Verzeichnis prüfen,
    und die Oberfläche bekommt sie fertig gefüllt gereicht."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ModRecord] = {}
        self._dirty = False
        # Was seit dem letzten ``clear_new()`` zum ersten Mal auftauchte.
        # Ohne diesen Merker gäbe es das Sammler-Erlebnis nicht: Die
        # Anzeige sieht ein Item immer erst, NACHDEM es eingetragen wurde
        # — zum Anzeigezeitpunkt ist also nichts mehr neu.
        self._new: set[tuple[str, str]] = set()
        # Ein Stand aus Aufbau ≤ 6 trägt falsche Zählstände (§VERSION,
        # Aufbau 7): Die Einträge sind dann nur noch Hüllen mit
        # ``first_seen``, und das Fenster muss sie aus dem Cache neu
        # füllen (``prune_unseen`` räumt danach auf, was nicht mehr da ist).
        self.needs_rebuild = False

    # ------------------------------ Füllen ---------------------------- #

    def observe(self, kind: str, line: str, *, ilvl: int = 0,
                rarity: int = UNKNOWN_RARITY,
                league: str = LEGACY_LEAGUE,
                category: str = "") -> ModRecord | None:
        """Eine einzelne Mod-Zeile aufnehmen. Gibt den Eintrag zurück,
        oder ``None`` bei einer unbekannten Art bzw. leerem Text."""
        if kind not in MOD_KINDS or not line:
            return None
        identity = mod_identity(line)
        if not identity:
            return None
        schluessel = (kind, identity)
        eintrag = self._records.get(schluessel)
        if eintrag is None:
            eintrag = self._records[schluessel] = ModRecord(identity, kind)
            eintrag.first_seen = time.time()
            self._new.add(schluessel)
        eintrag.observe(line, ilvl=ilvl, rarity=rarity, league=league,
                        category=category)
        self._dirty = True
        return eintrag

    def backfill_tiers(self, items: Iterable) -> int:
        """Tier-Belege nachtragen, ohne einen einzigen Zählstand anzufassen.

        Ein Stand nach Aufbau 2 kennt die Belege nicht (§VERSION). Ihn
        einfach neu einzulesen wäre der naheliegende Weg und der falsche:
        Jede Sichtung zählte dann doppelt, und die Sammlung ist der
        einzige Ort, an dem ein verkauftes Item noch existiert — eine
        verdoppelte Zählung liesse sich nie wieder herausrechnen.

        Gibt die Zahl der Belege zurück, die wirklich etwas geändert
        haben."""
        getroffen = 0
        for item in items:
            ilvl = int(getattr(item, "ilvl", 0) or 0)
            liga, rarity = item_buckets(item)
            if not tierable(rarity, ilvl):
                continue
            category = item_category(item) or ""
            if not category:
                continue
            for kind, zeilen in (("explicitMods", item.explicit_mods),
                                 ("implicitMods", item.implicit_mods)):
                for line in zeilen:
                    eintrag = self._records.get((kind, mod_identity(line)))
                    if eintrag is None:
                        continue
                    if eintrag.observe_tier_evidence(
                            mod_values(line), ilvl=ilvl, rarity=rarity,
                            category=category, league=liga):
                        getroffen += 1
                        self._dirty = True
        return getroffen

    def has_tier_evidence(self) -> bool:
        """Trägt die Sammlung überhaupt schon Tier-Belege? Die Frage
        entscheidet, ob ein Nachtrag nötig ist — auch beim Sprung von
        Aufbau 3/4 auf 5: Der alte ``tiers``-Block wird beim Laden
        verworfen, das Kontenbuch ist dann leer, und der Nachtrag läuft
        beim nächsten Start von selbst wieder an."""
        return any(r.tier_ledger for r in self._records.values())

    def observe_item(self, item) -> int:
        """Alle Mod-Zeilen eines Items aufnehmen; gibt deren Anzahl zurück.

        Gelesen wird über die aufbereiteten Wege der Modelle
        (``explicit_mods``, ``extra_mod_lines``), nicht über die rohen
        Felder: Sonst landete GGGs Färbungs-Markup
        (``<currencyitem>{…}``) in der Identität, und dieselbe Zeile
        stünde je nach Herkunft zweimal in der Sammlung."""
        ilvl = int(getattr(item, "ilvl", 0) or 0)
        liga, rarity = item_buckets(item)
        category = item_category(item) or ""
        gezaehlt = 0
        for kind, zeilen in (("explicitMods", item.explicit_mods),
                             ("implicitMods", item.implicit_mods)):
            for line in zeilen:
                if self.observe(kind, line, ilvl=ilvl, rarity=rarity,
                                league=liga, category=category) is not None:
                    gezaehlt += 1
        for kind in (ENCHANT_MOD_FIELD, *EXTRA_MOD_FIELDS):
            for line in extra_mod_lines(item, kind):
                if self.observe(kind, line, ilvl=ilvl, rarity=rarity,
                                league=liga) is not None:
                    gezaehlt += 1
        # Die Hauptwerte (§4.52.8) — ohne Kategorie-Argument: Sie steht
        # schon in der Zeile, und ein Tier-Konto gibt es für sie nicht.
        for line in base_stat_lines(item):
            if self.observe(BASE_STAT_KIND, line, ilvl=ilvl, rarity=rarity,
                            league=liga) is not None:
                gezaehlt += 1
        return gezaehlt

    def observe_items(self, items: Iterable) -> int:
        return sum(self.observe_item(item) for item in items)

    def backfill_base_stats(self, items: Iterable) -> int:
        """Nur die Hauptwerte nachtragen (§4.52.8) — für einen Stand, der
        vor Aufbau 8 entstand. Anders als ``backfill_tiers`` DARF hier
        gezählt werden: Die Einträge existieren noch gar nicht, es gibt
        nichts zu verdoppeln. Gibt die Zahl der eingetragenen Zeilen
        zurück."""
        getroffen = 0
        for item in items:
            ilvl = int(getattr(item, "ilvl", 0) or 0)
            liga, rarity = item_buckets(item)
            for line in base_stat_lines(item):
                if self.observe(BASE_STAT_KIND, line, ilvl=ilvl, rarity=rarity,
                                league=liga) is not None:
                    getroffen += 1
        return getroffen

    def has_base_stats(self) -> bool:
        """Kennt die Sammlung schon Hauptwerte? Entscheidet über den
        Nachtrag beim Start (§_restore_mod_collection)."""
        return any(kind == BASE_STAT_KIND for kind, _ in self._records)

    # ------------------------------ Lesen ----------------------------- #

    def get(self, kind: str, line: str) -> ModRecord | None:
        """Was ist über die Identität DIESER Zeile bekannt?"""
        return self._records.get((kind, mod_identity(line)))

    def is_new(self, kind: str, line: str) -> bool:
        """Kam diese Zeile seit dem letzten ``clear_new()`` zum ersten Mal
        vor? Das ist der Fund, den ein Sammler sehen will."""
        return (kind, mod_identity(line)) in self._new

    def clear_new(self) -> None:
        """Den Grundstock zum Bekannten erklären.

        Nach der Erstbefüllung aus dem Cache wäre sonst ALLES neu — 6125
        Funde auf einmal sind kein Fund. Ab hier zählt nur noch, was
        wirklich frisch hereinkommt."""
        self._new.clear()

    def prune_unseen(self) -> int:
        """Nach dem Neuaufbau (§VERSION, Aufbau 7): Hüllen wegwerfen, die
        beim Neuzählen aus dem Cache nicht mehr aufgetaucht sind — das
        sind die inzwischen verkauften oder zerlegten Items. Gibt zurück,
        wie viele es waren."""
        tot = [key for key, r in self._records.items() if r.count == 0]
        for key in tot:
            del self._records[key]
        if tot:
            self._dirty = True
        self.needs_rebuild = False
        return len(tot)

    def new_keys(self) -> frozenset[tuple[str, str]]:
        """Die Funde dieser Sitzung als Schnappschuss — fürs Album, das
        beim Öffnen den Stand einfriert (§ui/mod_album.py) und deshalb
        nicht bei jeder Karte die lebende Sammlung fragen soll."""
        return frozenset(self._new)

    def records(self) -> list[ModRecord]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)

    @property
    def dirty(self) -> bool:
        """Gibt es etwas zu speichern? Ohne diese Frage schriebe jeder
        Refresh die ganze Datei neu, auch wenn nichts Neues dabei war."""
        return self._dirty

    def counts_by_kind(self) -> dict[str, int]:
        zaehler: dict[str, int] = {}
        for (kind, _), _ in self._records.items():
            zaehler[kind] = zaehler.get(kind, 0) + 1
        return zaehler

    # ---------------------------- Speichern --------------------------- #

    def to_payload(self) -> dict:
        return {"version": VERSION,
                "mods": [eintrag.to_row() for eintrag in self._records.values()]}

    @classmethod
    def from_payload(cls, payload: object) -> "ModCollection":
        sammlung = cls()
        if not isinstance(payload, dict):
            return sammlung
        zeilen = payload.get("mods")
        if not isinstance(zeilen, list):
            return sammlung
        version = payload.get("version")
        alt = not isinstance(version, int) or version < 7
        for zeile in zeilen:
            if not isinstance(zeile, dict):
                continue
            eintrag = ModRecord.from_row(zeile)
            if eintrag is None:
                continue
            if alt:
                # Aufbau ≤ 6 zählte jeden Abruf als Sichtung (§VERSION,
                # Aufbau 7): Nur die Hülle mit ``first_seen`` bleibt, der
                # Rest wird aus dem Cache neu gezählt.
                eintrag = ModRecord(identity=eintrag.identity, kind=eintrag.kind,
                                    first_seen=eintrag.first_seen)
            sammlung._records[(eintrag.kind, eintrag.identity)] = eintrag
        sammlung.needs_rebuild = alt and bool(sammlung._records)
        return sammlung

    def save(self, path: Path) -> bool:
        """Ablegen, wenn es etwas abzulegen gibt. ``True``, wenn wirklich
        geschrieben wurde.

        **Mit Plausibilitätsprüfung**, und die ist hier wichtiger als
        anderswo: Ein verkauftes Item lebt nur noch in dieser Datei
        weiter. Würde der neue Stand weniger Einträge haben als der alte,
        ist etwas kaputt — dann lieber gar nicht schreiben und den alten
        Stand behalten (dieselbe Regel wie beim Daten-Cache)."""
        if not self._dirty:
            return False
        vorher = _count_in_file(path)
        if vorher is not None and len(self._records) < vorher - _SHRINK_TOLERANCE:
            log.warning("Mod-Sammlung NICHT gespeichert: %d Einträge im Speicher, "
                        "%d in der Datei — das wäre ein Verlust.",
                        len(self._records), vorher)
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, self.to_payload())
        self._dirty = False
        return True


def path_for(account_name: str) -> Path:
    """Je Konto eine Datei, wie beim Daten-Cache und beim XP-Verlauf.

    Als Funktion und nicht als Modul-Konstante, damit der Testschutz in
    ``tests/conftest.py`` greift."""
    safe = sanitize_filename(account_name, fallback="account")
    return config.APP_DATA_DIR / f"mod-collection-{safe}.json"


def load(path: Path) -> ModCollection:
    """Die Sammlung holen. Eine fehlende Datei ist der Normalfall beim
    ersten Start; eine unlesbare wird gemeldet, aber nicht überschrieben
    — sie könnte reparierbar sein, und ein stiller Neuanfang wäre der
    Verlust der ganzen Sammlung."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ModCollection()
    except (OSError, json.JSONDecodeError):
        log.warning("Mod-Sammlung %s nicht lesbar — sie wird NICHT überschrieben.",
                    path, exc_info=True)
        sammlung = ModCollection()
        sammlung._dirty = False
        return sammlung
    return ModCollection.from_payload(payload)


def retire(path: Path) -> Path | None:
    """Die alte Datei vor dem Neuaufbau beiseitelegen statt überschreiben
    (``mod-collection-X.json`` → ``mod-collection-X.pre-v7.json``).

    Zwei Gründe: Der Neuaufbau kann WENIGER Einträge haben als die alte
    Datei (verkaufte Items), und ``save`` lehnt Schrumpfen zu Recht ab —
    ohne Datei daneben gibt es nichts, wogegen es schrumpfen könnte. Und
    die alten Zahlen bleiben nachlesbar, falls jemand sie doch noch
    braucht. Gibt den neuen Pfad zurück, ``None`` ohne Datei."""
    if not path.exists():
        return None
    ziel = path.with_name(f"{path.stem}.pre-v{VERSION}{path.suffix}")
    if ziel.exists():
        ziel.unlink()
    path.rename(ziel)
    return ziel


def _count_in_file(path: Path) -> int | None:
    """Wie viele Einträge stehen in der Datei? ``None``, wenn es keine
    gibt oder sie nicht lesbar ist — dann gibt es nichts zu verlieren."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    zeilen = payload.get("mods") if isinstance(payload, dict) else None
    return len(zeilen) if isinstance(zeilen, list) else None


def summary(collection: ModCollection) -> str:
    """Eine Zeile fürs Log und die Statusleiste."""
    je_art = collection.counts_by_kind()
    teile = [f"{anzahl} {art}" for art, anzahl in sorted(je_art.items())]
    return f"{len(collection)} Mod-Zeilen gesammelt ({', '.join(teile)})"
