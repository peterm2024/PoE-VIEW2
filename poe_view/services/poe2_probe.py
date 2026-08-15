"""Rohdaten-Abzug der PoE2-Endpunkte (docs/ARCHITEKTUR.md §4.43).

GGGs API unterscheidet die Spiele über einen ``realm``-Query-Parameter,
nicht über eigene Pfade oder einen eigenen OAuth-Scope. Das bestehende
Token deckt die Abfrage also mit ab. Am 2026-08-15 aus GGGs eigener
Referenz gelesen (https://www.pathofexile.com/developer/docs/reference):

- ``/account/leagues``  — ``realm`` erlaubt ``pc``, ``xbox``, ``sony``, ``poe2``
- ``/character``        — ``realm`` erlaubt ``xbox``, ``sony``, ``poe2``
- ``/stash/...``        — ``realm`` erlaubt nur ``xbox`` oder ``sony``

Dazu GGGs Hinweis auf derselben Seite: "There are currently limited APIs
that return PoE2 game information."

Dieses Modul stellt nur die Aufbereitung: Der Abruf liegt im ApiWorker
(``_poe2_probe``), die Anzeige im RawDataViewer. Hier steht, was
Qt-frei und ohne Netz testbar ist.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from poe_view import __version__, config

REALM = "poe2"


@dataclass
class ProbeCall:
    """Ergebnis genau eines Abrufs.

    Fehlschläge werden mitgeführt statt geworfen: Ob ein Endpunkt für
    PoE2 überhaupt antwortet, ist die eigentliche Frage dieses Abzugs —
    ein 403 oder 400 ist hier ein Messergebnis, kein Abbruchgrund.
    """

    label: str
    ok: bool
    data: object = None
    error: str = ""


@dataclass
class Probe:
    calls: list[ProbeCall] = field(default_factory=list)
    fetched_at: float = 0.0


def character_names(calls: list[ProbeCall]) -> list[str]:
    """Charakternamen aus der Liste, soweit eine zurückkam.

    Bewusst über die Antwortstruktur statt über das ``Character``-Modell:
    Das Modell ist an PoE1 gemessen, und ob PoE2 dieselben Felder liefert,
    ist gerade die offene Frage."""
    for call in calls:
        if not call.ok or not isinstance(call.data, dict):
            continue
        characters = call.data.get("characters")
        if isinstance(characters, list):
            return [c["name"] for c in characters
                    if isinstance(c, dict) and c.get("name")]
    return []


def report_path() -> Path:
    """Ablageort des Abzugs, bei jedem Aufruf neu aus ``config`` gebildet.

    Als Funktion und nicht als Modul-Konstante: Eine beim Import
    eingefrorene, aus ``config.APP_DATA_DIR`` abgeleitete Konstante wäre
    vom Testschutz in ``tests/conftest.py`` nicht mehr erreichbar und
    schriebe in den echten Profilordner (dieselbe Falle wie bei
    ``cache_backup`` und ``LOG_DIR``)."""
    return config.APP_DATA_DIR / "poe2-probe.txt"


def save_report(text: str) -> Path:
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def build_report(probe: Probe) -> str:
    """Der vollständige Abzug als Text — dasselbe, was das Fenster zeigt
    und was in der Datei landet. Eine Quelle, damit beide nicht
    auseinanderlaufen."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(probe.fetched_at))
    lines = [
        f"PoE-VIEW2 {__version__} — raw PoE2 API probe",
        f"Fetched: {stamp} (local time)",
        "",
        "This dump contains your account name and your character names.",
        "Look before you share it.",
        "",
    ]
    for call in probe.calls:
        lines.append("=" * 72)
        lines.append(call.label)
        lines.append("=" * 72)
        if call.ok:
            lines.append(json.dumps(call.data, indent=2, ensure_ascii=False,
                                    default=str))
        else:
            lines.append(f"FAILED — {call.error}")
        lines.append("")
    lines.append("=" * 72)
    lines.append(
        "Not asked for: the stash endpoints. GGG's reference lists only "
        "xbox and sony\nas realm values there, so PoE2 stash tabs are not "
        "reachable through the API\nat all — see docs/ARCHITEKTUR.md §4.43."
    )
    return "\n".join(lines)
