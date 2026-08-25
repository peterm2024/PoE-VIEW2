"""Aus Belegen Tier-Bänder ableiten (§4.52.4).

Peter, 2026-08-25: "Ich weiß, dass Items mit einem Tier versehen sind;
wir kennen das Item-Level; wir wissen, dass ab einem bestimmten
Item-Level der nächste Tier freigeschaltet wird und dadurch der Range
erhöht wird; anhand der Gauss-Verteilung sollten wir die verschiedenen
Ranges eigentlich auseinanderkennen können."

**Der Gedanke stimmt, die Statistik geht anders aus.** Ein Gauß-Mixture
sucht getrennte Hügel — in PoE grenzen die Tiers aber lückenlos
aneinander (in Peters Daten sichtbar als Sechserraster: 11, 17, 23, 29,
35, 41, 45). Innerhalb eines Tiers ist der Roll gleichverteilt, zwischen
zweien liegt kein Tal, sondern eine Kante. Im reinen Werte-Histogramm
bliebe nur ein schwaches Signal: Die Dichte fällt an jeder Grenze etwas
ab, weil hohe Tiers auf weniger Items vorkommen.

**Das Item-Level ist dagegen kein statistisches Signal, sondern ein
Beweis.** Ein Tier KANN unterhalb seiner Freischaltung nicht auftreten.
Deshalb arbeitet dieses Modul nicht mit Verteilungen, sondern mit der
unteren Einhüllenden (``mod_collection.add_evidence``): jeder Punkt ist
ein Beleg, und fehlende Daten machen sie nur zu vorsichtig, nie falsch.

**Warum das hier getrennt von der Sammlung steht.** ``mod_collection``
sammelt Belege und verspricht ausdrücklich, nichts zu behaupten
("Beobachtung, keine Wahrheit"). Was hier passiert, IST eine Deutung:
Aus Belegen werden vermutete Grenzen. Die Trennung hält sichtbar, welche
Zahl woher kommt.

**Wie gut das geht — gemessen, nicht geschätzt.** Gegen künstliche Daten
mit bekannter Wahrheit:

| Item-Level der Belege | Beobachtungen | Güte (F1) |
|---|---|---|
| gleichverteilt 1–84 | 2000 | **1,00** |
| gleichverteilt 1–84 | 250 | 0,46 |
| wie in Peters Bestand | 2000 | 0,75 |
| nur 75–85 (Endgame) | beliebig | **0,25** |

Die Methode ist also in Ordnung; was sie braucht, ist **Streuung im
Item-Level**, nicht Masse. Bei reinem Endgame sind ab iLvl 75 alle Tiers
bis auf das letzte verfügbar — dann hat die Einhüllende nichts mehr zu
trennen, und weitere zehntausend Maps ändern daran nichts. In Peters
Bestand liegen 83,6 % der Magic-/Rare-Items bei iLvl 70+ und nur 7,0 %
unter iLvl 60. Die Bänder werden deshalb erst dann scharf, wenn er eine
Liga wieder von unten hochspielt.

Genau darum gibt es ``bands()`` mit einem Schweige-Kriterium: Lieber
keine Bänder als geratene.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# Ab diesem iLvl-Sprung zwischen zwei benachbarten Punkten der
# Einhüllenden gilt eine Tier-Grenze als erkannt. Kalibriert an Peters
# echten Resistenz-Daten (Cold/Fire/Lightning, alle Basen mit ≥ 200
# Beobachtungen) gegen das dort sichtbare Sechserraster: 4 traf am
# besten (F1 0,63), größere Schwellen kauften Genauigkeit mit immer mehr
# verpassten Grenzen (bei 8 nur noch F1 0,45).
TIER_JUMP = 4

# Bis hierher müssen die Belege nach unten reichen, sonst werden gar
# keine Bänder gezeigt. Der stärkste Prädiktor von allen getesteten
# (Front-Länge, iLvl-Spanne, Zahl der Beobachtungen): Reichen die Belege
# unter iLvl 19, liegt die Güte im Mittel bei 0,81; fangen sie erst bei
# iLvl 57 an, nur noch bei 0,24.
MAX_LOWEST_ILVL = 19

# Unter so vielen Punkten lohnt keine Aussage — zwei Punkte ergeben
# immer genau ein "Band", und das ist keine Erkenntnis.
MIN_EVIDENCE_POINTS = 4


@dataclass(frozen=True)
class Band:
    """Ein vermutetes Tier.

    ``high`` ist BELEGT: dieser Wert wurde gesehen. ``low`` ist
    ERSCHLOSSEN — es ist die Obergrenze des Bandes darunter plus eins,
    und das setzt voraus, dass Tiers lückenlos aneinandergrenzen. Für das
    unterste Band ist ``low`` unbekannt (``None``), denn darunter liegt
    kein Beleg, aus dem sich etwas schließen ließe.

    ``from_ilvl`` ist eine OBERE SCHRANKE für die Freischaltung: "auf
    diesem Item-Level habe ich es gesehen, spätestens dort gibt es das
    also". Das echte Erfordernis kann niedriger liegen."""

    low: float | None
    high: float
    from_ilvl: int


def bands(evidence: Sequence[tuple[float, int]]) -> list[Band]:
    """Die vermuteten Bänder — oder eine leere Liste, wenn die Belege sie
    nicht tragen.

    Leer heißt hier ausdrücklich "ich weiß es nicht", nicht "es gibt
    keine". Siehe ``MAX_LOWEST_ILVL``: Ohne Belege aus dem unteren
    Level-Bereich lässt sich nichts auflösen, und eine geratene Leiter
    wäre schlechter als gar keine."""
    if not carries_bands(evidence):
        return []
    front = sorted(evidence)
    grenzen = [i for i in range(len(front) - 1)
               if front[i + 1][1] - front[i][1] >= TIER_JUMP]
    if not grenzen:
        return []

    ergebnis: list[Band] = []
    start = 0
    vorherige_obergrenze: float | None = None
    for i in grenzen:
        ergebnis.append(Band(low=vorherige_obergrenze,
                             high=front[i][0],
                             from_ilvl=front[start][1]))
        vorherige_obergrenze = front[i][0] + 1
        start = i + 1
    # Der Rest oberhalb der letzten erkannten Grenze ist ein angefangenes
    # Band: Seine Obergrenze ist nur das Beste, was bisher auftauchte,
    # nicht das Ende des Tiers. Es kommt trotzdem mit — sonst fehlte
    # ausgerechnet der Bereich, in dem die eigenen Funde liegen.
    ergebnis.append(Band(low=vorherige_obergrenze,
                         high=front[-1][0],
                         from_ilvl=front[start][1]))
    return ergebnis


def carries_bands(evidence: Sequence[tuple[float, int]]) -> bool:
    """Tragen diese Belege überhaupt eine Aussage über Tiers?"""
    if len(evidence) < MIN_EVIDENCE_POINTS:
        return False
    return min(ilvl for _, ilvl in evidence) <= MAX_LOWEST_ILVL


def why_silent(evidence: Sequence[tuple[float, int]]) -> str:
    """Warum es keine Bänder gibt — als Satz für die Anzeige.

    Ein leeres Feld ohne Begründung sähe aus wie ein Fehler. Der
    häufigste Fall bei einem Endgame-Bestand ist der zweite, und er ist
    kein Mangel der Sammlung, sondern eine Eigenschaft der Items."""
    if len(evidence) < MIN_EVIDENCE_POINTS:
        return ("not enough evidence yet — tiers need mods seen across "
                "a range of item levels")
    tiefstes = min(ilvl for _, ilvl in evidence)
    if tiefstes > MAX_LOWEST_ILVL:
        return (f"every sighting comes from item level {tiefstes} or higher. "
                "By then most tiers are already unlocked, so nothing here "
                "tells them apart — more maps will not change that. "
                "Levelling a character through the campaign will.")
    return "no clear tier steps in the evidence"
