"""Was eine Zone dem Charakter noch an Erfahrung bringt.

Path of Exile straft Erfahrung ab, wenn Charakter- und Gebietslevel
auseinanderliegen. Bis hierher konnte PoE-VIEW2 die Strafe nur MESSEN
(aus dem Verhältnis Gem-Zuwachs zu Charakter-Zuwachs, siehe
``docs/api-notes/poe-verhalten.md`` §4) — und das immer erst im
Nachhinein. Seit der Gebietslevel aus der Client.txt kommt
(``zone_watcher._AREA_LINE``), lässt sie sich vorher ausrechnen.

**Die Formel stammt aus der Community, nicht aus unseren Daten.** Sie
steht so im PoE-Wiki und in jedem Rechner im Netz; GGG hat sie nie
veröffentlicht. Deshalb ist sie hier als das gekennzeichnet, was sie
ist, und wird gegen Peters eigene Messungen gegengerechnet
(``poe-verhalten.md`` §4.1) statt geglaubt. Wo Anzeige und Wirklichkeit
auseinandergehen, hat die Messung recht.
"""

from __future__ import annotations

# Ab diesem Charakterlevel greift die zusätzliche Hürde (siehe
# ``experience_multiplier``): Jedes weitere Level kostet noch einmal
# extra, unabhängig vom Gebiet.
_EXTRA_PENALTY_FROM_LEVEL = 95

# Tiefer als das fällt der Anteil nicht — auch das Teil der Formel, und
# der Grund, warum ein Level-100-Charakter in einer Tier-1-Map nicht
# exakt null, sondern lächerlich wenig bekommt.
_MINIMUM_SHARE = 0.01


def safe_zone(character_level: int) -> int:
    """Wie weit Gebiets- und Charakterlevel auseinanderliegen dürfen,
    bevor überhaupt gestraft wird. Wächst mit dem Charakterlevel: Auf
    Stufe 96 sind es neun Level in jede Richtung, auf Stufe 16 vier."""
    return 3 + character_level // 16


def experience_multiplier(character_level: int, zone_level: int) -> float:
    """Der Anteil der Erfahrung, der bei diesem Gebietslevel ankommt
    (1.0 = voll). Community-Formel, siehe Modulkopf.

    ``zone_level <= 0`` heißt "unbekannt" (keine ``Generating
    level``-Zeile gesehen) und liefert 1.0 — die Anzeige soll dann
    nichts behaupten."""
    if character_level <= 0 or zone_level <= 0:
        return 1.0
    diff = max(abs(zone_level - character_level) - safe_zone(character_level), 0)
    anteil = ((character_level + 5)
              / (character_level + 5 + diff ** 2.5)) ** 1.5
    if character_level >= _EXTRA_PENALTY_FROM_LEVEL:
        anteil *= 1 / (1 + 0.1 * (character_level - (_EXTRA_PENALTY_FROM_LEVEL - 1)))
    return max(anteil, _MINIMUM_SHARE)


def penalty_caption(character_level: int, zone_level: int) -> str:
    """Kurztext für die Zonen-Anzeige, oder "" wenn es nichts zu sagen
    gibt.

    Ohne Strafe bleibt die Anzeige leer statt "100 %": Die Zahl
    interessiert erst, wenn sie weh tut, und eine Zeile, die immer etwas
    zeigt, wird nicht mehr gelesen. Unter 10 % steht eine Stelle hinter
    dem Komma — zwischen 4 % und 0,8 % liegt der Unterschied zwischen
    "zäh" und "sinnlos", und gerundet sähe beides gleich aus."""
    anteil = experience_multiplier(character_level, zone_level)
    if anteil >= 0.995:
        return ""
    return f"{anteil:.1%} XP" if anteil < 0.1 else f"{anteil:.0%} XP"
