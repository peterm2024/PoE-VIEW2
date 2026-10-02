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


# Gesamterfahrung, die Stufe 1 bis 100 jeweils VORAUSSETZT — Index 0 ist
# Stufe 1. Peter, 2026-10-02: "Wir brauchen neben den XP/h auch eine
# Anzeige für Time to next Level".
#
# Quelle: Tabelle "Total XP" im PoE-Wiki, Artikel "Experience"
# (poewiki.net, abgerufen 2026-10-02). Spieldaten, wie die Strafformel
# oben; anders als bei den RePoE-Exporten (§4.53) sind es hundert Zahlen,
# die überall nachzulesen sind, keine Datenbank. Beim Übernehmen
# geprüft statt geglaubt:
#
# - Die Kette "Summe + Zuwachs = nächste Summe" bricht im Wiki an zwei
#   Stellen. Bei Stufe 34 steht 8.384.398 — ein Zahlendreher, beide
#   Nachbarn belegen 8.348.398. Bei Stufe 89 ist der ZUWACHS um 431
#   daneben, die Summen stimmen: Stufe 100 kommt so auf 4.250.334.444,
#   genau den Wert, an dem die Erfahrung in der API endet (§_XpWatch,
#   qlonglong).
# - Peters Charakter auf Stufe 79 stand am 2026-10-02 bei 843.087.247 —
#   zwischen den Werten für 79 und 80, wie es sein muss.
LEVEL_EXPERIENCE = (
    0, 525, 1_760, 3_781, 7_184,
    12_186, 19_324, 29_377, 43_181, 61_693,
    85_990, 117_506, 157_384, 207_736, 269_997,
    346_462, 439_268, 551_295, 685_171, 843_709,
    1_030_734, 1_249_629, 1_504_995, 1_800_847, 2_142_652,
    2_535_122, 2_984_677, 3_496_798, 4_080_655, 4_742_836,
    5_490_247, 6_334_393, 7_283_446, 8_348_398, 9_541_110,
    10_874_351, 12_361_842, 14_018_289, 15_859_432, 17_905_634,
    20_171_471, 22_679_999, 25_456_123, 28_517_857, 31_897_771,
    35_621_447, 39_721_017, 44_225_461, 49_176_560, 54_607_467,
    60_565_335, 67_094_245, 74_247_659, 82_075_627, 90_631_041,
    99_984_974, 110_197_515, 121_340_161, 133_497_202, 146_749_362,
    161_191_120, 176_922_628, 194_049_893, 212_684_946, 232_956_711,
    255_001_620, 278_952_403, 304_972_236, 333_233_648, 363_906_163,
    397_194_041, 433_312_945, 472_476_370, 514_937_180, 560_961_898,
    610_815_862, 664_824_416, 723_298_169, 786_612_664, 855_129_128,
    929_261_318, 1_009_443_795, 1_096_169_525, 1_189_918_242, 1_291_270_350,
    1_400_795_257, 1_519_130_326, 1_646_943_474, 1_784_977_296, 1_934_009_687,
    2_094_900_291, 2_268_549_086, 2_455_921_256, 2_658_074_992, 2_876_116_901,
    3_111_280_300, 3_364_828_162, 3_638_186_694, 3_932_818_530, 4_250_334_444,
)
MAX_LEVEL = len(LEVEL_EXPERIENCE)


def experience_to_next_level(level: int, experience: int) -> int | None:
    """Was bis zur nächsten Stufe fehlt — ``None`` auf Stufe 100 oder
    bei einer Stufe außerhalb der Tabelle."""
    if not 1 <= level < MAX_LEVEL:
        return None
    return max(LEVEL_EXPERIENCE[level] - experience, 0)


def level_span(level: int) -> int | None:
    """Wie viel Erfahrung die ganze Stufe umfasst (für "x % der Stufe")."""
    if not 1 <= level < MAX_LEVEL:
        return None
    return LEVEL_EXPERIENCE[level] - LEVEL_EXPERIENCE[level - 1]


def time_to_next_level(level: int, experience: int, rate: float) -> float | None:
    """Sekunden bis zur nächsten Stufe bei dieser Rate (XP/h) — ``None``
    ohne positive Rate oder auf Stufe 100. Eine reine Hochrechnung: Sie
    gilt nur, solange so weitergespielt wird wie im Zeitraum der Rate."""
    fehlt = experience_to_next_level(level, experience)
    if fehlt is None or rate <= 0:
        return None
    return fehlt / rate * 3600
