"""Wer hat wann gespielt — und damit: in welcher Liga? (§4.56.4)

Peter, 2026-09-26: "MapSideArea sind keine eigenen Maps, das sind
meistens Vaal-Side-Areas. Diese kommen aber in SSF Ruthless nicht vor.
hier müssen wir noch zwischen den aktuellen Leagues unterscheiden." Und
kurz darauf: "Können wir eigentlich den gespielten Char über die
client.txt herausfinden?"

**Ja, punktuell.** Zwei Zeilenarten nennen den Charakter beim Namen:

```
: KRN_… (Chieftain) is now level 83
: KRN_… has been slain.
```

In Peters Log sind das 256 Aufstiege und 226 Tode, zusammen 482
Zeitmarken über 5,5 Monate. Rechnet man jeden Zonen-Eintritt dem
Charakter der nächstgelegenen Marke zu, deckt das

| Fenster | Zonen-Eintritte |
|---|---|
| 1 h | 84 % |
| 3 h | 89 % |
| 6 h | 92 % |
| 12 h | 94 % |

Der Beleg, dass die Zuordnung trägt: Von Peters zehn Vaal-Side-Areas
ließen sich neun einem Charakter zuweisen, **alle neun in "Allflame",
keine in "SSF R Allflame"** — genau die Unterscheidung, um die er
gebeten hat. Über die ganze Season verteilt stehen 1050 Eintritte in
Allflame gegen 951 in SSF R Allflame; zusammengeworfen wäre die Hälfte
der Tabelle falsch.

**Es bleibt aber eine Interpolation.** Ein Charakterwechsel ohne Tod
und ohne Aufstieg dazwischen fällt durch. Deshalb schreibt das Programm
ab jetzt mit, was es ohnehin weiß: Bei jeder Erfahrungs-Veröffentlichung
steht fest, welcher Charakter gerade spielt und in welcher Liga er ist
(``MainWindow._on_character_snapshot``). Dieses Protokoll ist
lückenlos, die Marken aus dem Log füllen nur die Zeit davor.

**Warum die Liga und nicht die Season** (Peter: "Wir machen Liga, statt
Season"): Liga-Namen tragen die Season bereits in sich — "SSF R
Allflame" und "SSF R Mirage" sind verschiedene Einträge. Eine
Season-Trennung wäre damit doppelt gemoppelt, eine Liga-Trennung ist
zusätzlich feiner.

**Was die Liga NICHT hergibt: die Vergangenheit.** Nach dem Ende einer
Season wandern die Charaktere in die permanente Liga; die Liga-Angabe
sagt dann, wo sie heute sind, nicht wo sie gespielt wurden (gemessen:
alle 170 Tode vor dem Allflame-Start entfallen auf Charaktere, die heute
in "SSF Ruthless" stehen). Für Zeiten vor der ältesten bekannten Season
bleibt es deshalb bei ``UNKNOWN``.
"""

from __future__ import annotations

import json
import logging
import re
from bisect import bisect_left
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from poe_view import config
from poe_view.services.atomic_json import write_json

log = logging.getLogger(__name__)

VERSION = 1

# Kein Charakter zuordenbar. Eigener Wert statt eines leeren Strings,
# damit er in der Oberfläche als Auswahl auftauchen kann: "weiß ich
# nicht" ist eine Aussage, die man sehen soll.
UNKNOWN = "unknown"

# Wie weit darf eine Zeitmarke vom Zonen-Eintritt entfernt sein? Sechs
# Stunden decken 92 % ab und sind trotzdem enger als eine Spielsitzung
# lang; zwölf brächten zwei Prozentpunkte mehr und würden bereits über
# einen Schlaf hinweg raten.
MARK_WINDOW = timedelta(hours=6)

# "2026/04/13 11:22:45 … ] : KRN_LZ_COTA (Chieftain) is now level 83"
# "2026/09/22 22:31:07 … ] : KRN_LZ_COTA has been slain."
_MARK_RE = re.compile(
    r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}).*\] : (\S+)"
    r"(?: \([^)]+\) is now level \d+| has been slain)")


class Mark(NamedTuple):
    """Ein Zeitpunkt, zu dem ein bestimmter Charakter nachweislich
    gespielt hat."""

    at: datetime
    character: str


def marks_from_log(log_path: Path) -> list[Mark]:
    """Alle Zeitmarken aus der Client.txt, aufsteigend."""
    try:
        roh = log_path.read_bytes()
    except OSError:
        log.warning("Liga-Zuordnung: Client.txt nicht lesbar: %s", log_path)
        return []
    gefunden: list[Mark] = []
    for zeile in roh.decode("utf-8", errors="replace").splitlines():
        if " is now level " not in zeile and " has been slain" not in zeile:
            continue
        treffer = _MARK_RE.search(zeile)
        if treffer:
            gefunden.append(Mark(
                datetime.strptime(treffer.group(1), "%Y/%m/%d %H:%M:%S"),
                treffer.group(2)))
    gefunden.sort()
    return gefunden


def sessions_path() -> Path:
    """Als Funktion, nicht als Modul-Konstante: Die Testfixture patcht
    ``APP_DATA_DIR`` (CLAUDE.md, "Tests")."""
    return config.APP_DATA_DIR / "league-sessions.json"


def load_sessions(path: Path | None = None) -> list[Mark]:
    """Das mitgeschriebene Protokoll: Zeitpunkt und Charakter, wie das
    Programm sie live gesehen hat."""
    pfad = path or sessions_path()
    try:
        rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rohdaten, dict) or rohdaten.get("version") != VERSION:
        return []
    gefunden: list[Mark] = []
    for zeile in rohdaten.get("marks") or []:
        try:
            gefunden.append(Mark(datetime.fromisoformat(str(zeile["at"])),
                                 str(zeile["character"])))
        except (KeyError, TypeError, ValueError):
            continue
    gefunden.sort()
    return gefunden


def record_seen(character: str, at: datetime, path: Path | None = None,
                max_marks: int = 20000) -> None:
    """Festhalten, dass dieser Charakter zu diesem Zeitpunkt gespielt
    hat. Aufgerufen bei jeder Erfahrungs-Veröffentlichung.

    **Verdichtet auf eine Marke je Charakter und Viertelstunde**: Ein
    Spielabend bringt sonst hunderte Zeilen, die alle dasselbe sagen.
    Für die Zuordnung reicht ein Punkt je Viertelstunde bei weitem — das
    Fenster, in dem gesucht wird, ist sechs Stunden breit."""
    pfad = path or sessions_path()
    marken = load_sessions(pfad)
    viertel = at.replace(minute=at.minute // 15 * 15, second=0, microsecond=0)
    if any(m.character == character and m.at == viertel for m in marken):
        return
    marken.append(Mark(viertel, character))
    marken.sort()
    del marken[:-max_marks]
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        write_json(pfad, {
            "version": VERSION,
            "marks": [{"at": m.at.isoformat(timespec="seconds"),
                       "character": m.character} for m in marken],
        })
    except OSError as fehler:
        log.warning("Liga-Protokoll nicht speicherbar: %s", fehler)


def character_at(moment: datetime, marks: list[Mark],
                 window: timedelta = MARK_WINDOW) -> str:
    """Der Charakter der nächstgelegenen Marke, wenn sie nah genug
    liegt — sonst ``""``."""
    if not marks:
        return ""
    zeiten = [m.at for m in marks]
    i = bisect_left(zeiten, moment)
    beste, abstand = "", window
    for k in (i - 1, i):
        if 0 <= k < len(marks):
            d = abs(marks[k].at - moment)
            if d <= abstand:
                beste, abstand = marks[k].character, d
    return beste


# Was an eine Liga gehaengt wird, deren Name aus der Zeit VOR der
# laufenden Season stammt. Siehe ``league_at``.
EARLIER_SUFFIX = " (earlier)"


def league_at(moment: datetime, marks: list[Mark],
              leagues: dict[str, str], trusted_since: datetime | None = None,
              window: timedelta = MARK_WINDOW) -> str:
    """Die Liga, in der zu diesem Zeitpunkt gespielt wurde.

    ``leagues`` bildet Charakternamen auf ihre HEUTIGE Liga ab (aus der
    Charakterliste). ``trusted_since`` ist der Beginn der laufenden
    Season.

    **Vor dieser Grenze bekommt der Name ein ``(earlier)`` angehängt**,
    statt zu ``UNKNOWN`` zu werden. Der Grund ist eine Halbwahrheit, die
    man nutzen kann: Beim Season-Ende wandern die Charaktere in die
    permanente Liga, ihr heutiger Name sagt also nicht mehr, in welcher
    SEASON sie spielten — wohl aber, in welcher SPIELART. Ein Charakter,
    der heute in "SSF Ruthless" steht, hat auch damals Ruthless gespielt,
    und genau darauf zielte die Frage ("Diese kommen aber in SSF Ruthless
    nicht vor"). Der Zusatz hält die alten Zahlen trotzdem von den
    heutigen getrennt — sonst mischten sich zwei Atlanten in einer
    Zeile."""
    name = character_at(moment, marks, window)
    liga = leagues.get(name)
    if not liga:
        return UNKNOWN
    if trusted_since is not None and moment < trusted_since:
        return liga + EARLIER_SUFFIX
    return liga
