"""Tests für die Erfahrungs-Strafe (``services/experience.py``).

Die Formel ist Community-Wissen, kein eigenes Messergebnis — geprüft
wird deshalb, was sich unabhängig davon sagen lässt: die Eckpunkte, die
Monotonie und dass die Anzeige schweigt, wenn sie nichts weiß.
"""

import pytest

from poe_view.services.experience import (experience_multiplier,
                                          penalty_caption, safe_zone)


def test_the_safe_zone_grows_with_the_character_level() -> None:
    """Ein Charakter auf Stufe 16 darf vier Level abweichen, einer auf 96
    neun — genau deshalb trifft die Strafe erst spät und dann hart."""
    assert safe_zone(16) == 4
    assert safe_zone(96) == 9
    assert safe_zone(1) == 3


def test_inside_the_safe_zone_nothing_is_lost() -> None:
    for zone in range(78 - safe_zone(78), 78 + safe_zone(78) + 1):
        assert experience_multiplier(78, zone) == 1.0


def test_the_share_falls_the_further_the_zone_is_below_the_character() -> None:
    werte = [experience_multiplier(90, zone) for zone in (83, 80, 75, 70, 68)]
    assert werte == sorted(werte, reverse=True)
    assert werte[0] > 0.5 > werte[-1]


def test_a_level_95_character_pays_twice() -> None:
    """Ab Stufe 95 kostet jedes weitere Level noch einmal extra,
    unabhängig vom Gebiet. Ohne diesen Teil der Formel sähe der Sprung
    von 94 auf 95 wie ein Gewinn aus (die sichere Zone wächst dort)."""
    assert experience_multiplier(95, 95) < 1.0
    assert experience_multiplier(96, 96) < experience_multiplier(95, 95)


def test_the_share_never_falls_below_one_percent() -> None:
    """Auch ein Level-100-Charakter in einer Tier-1-Map bekommt noch
    etwas — nicht null. Wer das nicht kennt, hält die Anzeige sonst für
    kaputt."""
    assert experience_multiplier(100, 68) == 0.01


def test_an_unknown_zone_level_claims_nothing() -> None:
    """Ohne ``Generating level``-Zeile im Log ist der Level 0. Dann soll
    die Anzeige nichts behaupten, statt eine Strafe zu erfinden."""
    assert experience_multiplier(96, 0) == 1.0
    assert experience_multiplier(0, 80) == 1.0
    assert penalty_caption(0, 68) == ""


def test_the_caption_stays_empty_without_a_penalty() -> None:
    """Eine Zeile, die immer etwas zeigt, wird nicht mehr gelesen — die
    Strafe erscheint erst, wenn es eine gibt."""
    assert penalty_caption(78, 78) == ""
    assert penalty_caption(78, 75) == ""


def test_the_caption_gets_a_decimal_where_it_matters() -> None:
    """Zwischen 4 % und 0,8 % liegt der Unterschied zwischen "zäh" und
    "sinnlos"; gerundet sähe beides gleich aus."""
    assert penalty_caption(85, 68) == "14% XP"
    assert penalty_caption(98, 68) == "1.0% XP"


# --- Erfahrungstabelle und Zeit bis zur nächsten Stufe (2026-10-02) ------

from poe_view.services.experience import (LEVEL_EXPERIENCE, MAX_LEVEL,  # noqa: E402
                                          experience_to_next_level,
                                          level_span, time_to_next_level)


def test_the_table_has_100_rising_levels_ending_where_the_api_ends() -> None:
    assert MAX_LEVEL == 100
    assert LEVEL_EXPERIENCE[0] == 0
    assert all(a < b for a, b in zip(LEVEL_EXPERIENCE, LEVEL_EXPERIENCE[1:]))
    assert LEVEL_EXPERIENCE[-1] == 4_250_334_444


def test_the_wiki_typo_at_level_34_is_corrected() -> None:
    """Im Wiki steht 8.384.398 — beide Nachbarn belegen 8.348.398."""
    assert LEVEL_EXPERIENCE[33] == 8_348_398


def test_a_real_character_sits_between_its_two_levels() -> None:
    """Peters Stand vom 2026-10-02: Stufe 79, 843.087.247 XP."""
    assert LEVEL_EXPERIENCE[78] <= 843_087_247 < LEVEL_EXPERIENCE[79]


def test_time_to_next_level() -> None:
    fehlt = experience_to_next_level(79, 843_087_247)
    assert fehlt == LEVEL_EXPERIENCE[79] - 843_087_247
    assert time_to_next_level(79, 843_087_247, 4_700_000) == pytest.approx(fehlt / 4_700_000 * 3600)
    assert level_span(79) == LEVEL_EXPERIENCE[79] - LEVEL_EXPERIENCE[78]


def test_no_projection_at_level_100_or_without_a_rate() -> None:
    assert time_to_next_level(100, 4_250_334_444, 1e6) is None
    assert time_to_next_level(79, 843_087_247, 0) is None
    assert time_to_next_level(79, 843_087_247, -2e6) is None
    assert experience_to_next_level(0, 0) is None
