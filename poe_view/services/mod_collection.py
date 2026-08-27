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
                                 extra_mod_lines, item_category, map_tier)
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
VERSION = 5

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
MOD_KINDS = ("explicitMods", "implicitMods", ENCHANT_MOD_FIELD,
             *EXTRA_MOD_FIELDS)

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")

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
    # Das Kontenbuch für die Tier-Ableitung, je Basis-Kategorie: je WERT
    # die Zahl der Sichtungen und die iLvl-Spanne, ``wert -> [n, il_min,
    # il_max]``. Daraus kommt beides: die Pareto-Front für die Bänder
    # (``tier_front``) UND die Zeile je Band im Album ("Count | Min |
    # Max | iLvl" — Peters Tabelle, 2026-08-27).
    #
    # **Eine eigene Achse, nicht Liga × Rarität.** Ein Ring rollt eine
    # andere Tier-Tabelle als eine Rüstung, bei identischem Text; ohne
    # diese Trennung verschmiert die Leiter. Die Liga dagegen spielt für
    # die Tier-Schwellen keine Rolle und würde die Belege nur ausdünnen —
    # sie fehlt hier deshalb bewusst, obwohl ``spans`` sie führt.
    tier_ledger: dict[str, dict[float, list[int]]] = field(default_factory=dict)

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
                                   category=category)

    def observe_tier_evidence(self, values: Sequence[float], *, ilvl: int,
                              rarity: int, category: str) -> bool:
        """Nur das Tier-Kontenbuch führen, ohne die Album-Zählstände.

        Getrennt von ``observe``, weil ein alter Stand die Belege
        nachtragen muss, OHNE dass die Sichtungen ein zweites Mal in die
        Spannen gezählt werden (``ModCollection.backfill_tiers``).

        Gibt zurück, ob der Beleg überhaupt taugte."""
        if not tierable(rarity, ilvl) or not category or len(values) != 1:
            return False
        konto = self.tier_ledger.setdefault(category, {})
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

    def tier_front(self, category: str) -> list[tuple[float, int]]:
        """Die Pareto-Front (Wert hoch, iLvl niedrig) aus dem Kontenbuch —
        die Eingabe für ``mod_tiers.bands``. Für die Front zählt je Wert
        nur sein NIEDRIGSTES iLvl, deshalb verliert die Ableitung nichts
        gegenüber dem früheren direkten Mitschreiben (Aufbau 3/4)."""
        front: list[tuple[float, int]] = []
        for wert, (_, il_min, _il_max) in sorted(
                self.tier_ledger.get(category, {}).items()):
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
            "ledger": {kat: [[_as_number(wert), *zeile]
                             for wert, zeile in sorted(konto.items())]
                       for kat, konto in sorted(self.tier_ledger.items())
                       if konto},
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
        ledger = row.get("ledger")
        if isinstance(ledger, dict):
            for kat, zeilen in ledger.items():
                if not isinstance(kat, str) or not isinstance(zeilen, list):
                    continue
                konto = {}
                for zeile in zeilen:
                    if (isinstance(zeile, list) and len(zeile) == 4
                            and all(isinstance(x, (int, float)) for x in zeile)):
                        konto[float(zeile[0])] = [int(zeile[1]),
                                                  int(zeile[2]), int(zeile[3])]
                if konto:
                    eintrag.tier_ledger[kat] = konto

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
            _liga, rarity = item_buckets(item)
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
                            category=category):
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
        return gezaehlt

    def observe_items(self, items: Iterable) -> int:
        return sum(self.observe_item(item) for item in items)

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
        for zeile in zeilen:
            if not isinstance(zeile, dict):
                continue
            eintrag = ModRecord.from_row(zeile)
            if eintrag is not None:
                sammlung._records[(eintrag.kind, eintrag.identity)] = eintrag
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
