"""Tests der Tier-Ableitung (ARCHITEKTUR.md §4.52.4).

Peter, 2026-08-25: "anhand der Gauss-Verteilung sollten wir die
verschiedenen Ranges eigentlich auseinanderkennen koennen und dadurch den
Tier im Laufe der Zeit feststellen koennen."

Geprueft wird beides: dass die Ableitung trifft, wenn die Belege sie
tragen — UND dass sie schweigt, wenn nicht. Das Schweigen ist hier der
wichtigere Teil: Eine geratene Tier-Leiter waere schlechter als gar
keine, weil sie wie Wissen aussieht.
"""

from poe_view.services.mod_collection import add_evidence
from poe_view.services.mod_tiers import (MAX_LOWEST_ILVL, MIN_EVIDENCE_POINTS,
                                         bands, carries_bands, why_silent)

# Eine echte Front aus Peters Bestand: "#% to Cold Resistance", alle
# Basen, 1323 Beobachtungen auf 15 Punkte eingedampft.
ECHTE_FRONT = [(6, 6), (10, 10), (11, 11), (16, 15), (17, 17), (22, 25),
               (23, 26), (25, 33), (29, 42), (33, 52), (34, 53), (35, 55),
               (41, 61), (48, 72), (75, 83)]


# ----------------------------- Pareto-Front ----------------------------- #

def test_a_dominated_point_changes_nothing() -> None:
    """Ein schlechterer Wert auf einem hoeheren Item-Level sagt nichts,
    was nicht schon dasteht."""
    front = add_evidence([], 40, 60)

    assert add_evidence(front, 30, 70) is front
    assert add_evidence(front, 40, 60) is front


def test_a_better_point_pushes_the_worse_one_out() -> None:
    """Derselbe Wert auf niedrigerem Level ersetzt den alten Beleg —
    sonst wuechse die Front mit jeder Sichtung."""
    front = add_evidence([], 40, 60)
    front = add_evidence(front, 40, 30)

    assert front == [(40, 30)]


def test_a_higher_value_at_a_lower_level_absorbs_everything_below() -> None:
    front = [(10, 20), (20, 40), (30, 60)]

    assert add_evidence(front, 35, 15) == [(35, 15)]


def test_the_front_keeps_the_staircase() -> None:
    """Jeder Punkt muss etwas Eigenes beitragen: mehr Wert ODER weniger
    Level als alle anderen."""
    front = []
    for wert, ilvl in [(10, 20), (12, 25), (11, 22), (30, 60), (9, 5)]:
        front = add_evidence(front, wert, ilvl)

    assert front == [(9, 5), (10, 20), (11, 22), (12, 25), (30, 60)]


def test_the_front_is_capped() -> None:
    """Sie ist von Natur aus kurz, aber ein Mod mit sehr vielen Werten
    darf die Datei nicht aufblaehen.

    Die Punkte muessen eine echte TREPPE bilden (Wert steigt UND iLvl
    steigt) — der erste Anlauf liess das iLvl fallen, damit dominierte
    jeder neue Punkt alle vorigen, und die Front blieb bei Laenge 1. Der
    Test prueft dann nichts."""
    front = []
    for i in range(200):
        front = add_evidence(front, i, i)

    assert len(front) == 40


# ------------------------------- Baender -------------------------------- #

def test_the_real_front_reproduces_the_known_tier_ladder() -> None:
    """Die Probe aufs Exempel an echten Daten. Die PoE-Resistenzleiter
    endet auf 11/17/23/29/35/41 — mindestens 17, 23, 35 und 41 muessen
    als Bandgrenzen herauskommen."""
    obergrenzen = {b.high for b in bands(ECHTE_FRONT)}

    assert {17, 23, 35, 41} <= obergrenzen


def test_bands_are_contiguous_and_ordered() -> None:
    """Die Untergrenze eines Bandes ist die Obergrenze des vorigen plus
    eins — genau die Annahme, die im Modul dokumentiert ist."""
    baender = bands(ECHTE_FRONT)

    assert baender[0].low is None
    for vorher, jetzt in zip(baender, baender[1:]):
        assert jetzt.low == vorher.high + 1
        assert jetzt.high > vorher.high
        assert jetzt.from_ilvl >= vorher.from_ilvl


def test_the_top_band_carries_the_best_value_seen() -> None:
    """Sonst fehlte ausgerechnet der Bereich, in dem die eigenen Funde
    liegen."""
    assert bands(ECHTE_FRONT)[-1].high == ECHTE_FRONT[-1][0]


# ------------------------------ Schweigen -------------------------------- #

def test_endgame_only_evidence_yields_no_bands() -> None:
    """Der wichtigste Fall. Ab iLvl 75 sind fast alle Tiers freigeschaltet
    — die Einhuellende hat dort nichts mehr zu trennen, und keine Menge
    weiterer Maps aendert daran etwas (gemessen: F1 0,25)."""
    endgame = [(40, 75), (44, 78), (46, 80), (48, 84), (50, 85)]

    assert bands(endgame) == []
    assert carries_bands(endgame) is False


def test_too_few_points_yield_no_bands() -> None:
    knapp = [(10, 5), (20, 8)]

    assert len(knapp) < MIN_EVIDENCE_POINTS
    assert bands(knapp) == []


def test_evidence_reaching_low_levels_does_carry() -> None:
    tief = [(6, 5), (12, 14), (18, 26), (24, 38), (30, 50)]

    assert min(il for _, il in tief) <= MAX_LOWEST_ILVL
    assert carries_bands(tief) is True
    assert bands(tief) != []


def test_the_silence_explains_itself() -> None:
    """Ein leeres Feld saehe aus wie ein Fehler. Der Grund gehoert
    dazu — und er nennt den Ausweg."""
    endgame = [(40, 75), (44, 78), (46, 80), (48, 84), (50, 85)]

    grund = why_silent(endgame)

    assert "75" in grund
    assert "level" in grund.lower()
    assert why_silent([(10, 5)]) != grund


def test_evidence_without_any_jump_yields_no_bands() -> None:
    """Lauter kleine Schritte heisst: keine erkennbare Grenze. Dann lieber
    nichts sagen, als eine Grenze zu erfinden."""
    glatt = [(10, 5), (11, 6), (12, 7), (13, 8), (14, 9)]

    assert bands(glatt) == []
