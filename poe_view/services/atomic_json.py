"""JSON-Datei so schreiben, dass sie nie halb fertig auf der Platte liegt.

Anlass (Peter, 2026-08-04): "Hab gerade gesehen, dass ich mehrere
Instanzen von PoE-VIEW gleichzeitig offen hatte. Konsequenzen?" Das Log
belegt zwei Starts binnen 29 Sekunden. Beide Instanzen schreiben in
dieselbe Cache-Datei, und die wurde bis dahin direkt überschrieben
(``path.write_text(...)``). Ein 52-MB-Schreibvorgang dauert lange genug,
dass zwei davon sich überlappen können — das Ergebnis wäre kein
Datenverlust im bisherigen Sinn, sondern kaputtes JSON. ``data_cache.
load()`` fängt das zwar ab und liefert ``None``, aber für den Nutzer
sieht "Datei unlesbar" genauso aus wie "Daten weg", und der
Überschreibschutz in ``_persist_cache`` greift danach nicht mehr: Er
vergleicht gegen den zuletzt GESCHRIEBENEN Umfang, und der ist nach
einem fehlgeschlagenen Laden 0.

Dieselbe Lücke besteht ohne zweite Instanz: Absturz, Stromausfall oder
ein beendeter Prozess mitten im Schreiben hinterlassen eine abgeschnittene
Datei. Beide Datenverluste dieser Woche (FALLSTRICKE #62) entstanden beim
ZURÜCKSCHREIBEN — dies ist derselbe Angriffspunkt, nur über einen dritten
Weg.

Verfahren: erst vollständig in eine Nebendatei schreiben, dann per
``os.replace`` an ihren Platz schieben. Das Ersetzen ist auf einem
Laufwerk atomar (unter Windows ``MoveFileEx`` mit
``MOVEFILE_REPLACE_EXISTING``) — es gibt also keinen Zeitpunkt, zu dem
eine halbe Datei sichtbar wäre. Die Nebendatei trägt die Prozess-ID im
Namen, damit zwei Instanzen sich nicht gegenseitig die Nebendatei
zerschreiben; am Ende gewinnt schlicht der spätere Schreibvorgang, und
das Ergebnis ist in jedem Fall eine vollständige Datei.

**Nachtrag 2026-08-07 — das Ersetzen kann an einem bloßen LESER
scheitern.** Im Log eines Spielabends standen zwei ``PermissionError
[WinError 5]`` auf ``os.replace``. Ursache war ein zweiter Prozess, der
die 67-MB-Datei zum Lesen geöffnet hatte (in dem Fall ein
Auswertungsskript). Windows lässt ``MoveFileEx`` auf eine Datei, die ein
anderer Prozess offen hält, nicht zu, solange dieser sie nicht
ausdrücklich zum Löschen freigegeben hat — und Pythons ``open()`` tut das
nicht. Ein Virenscanner, der eine frisch geschriebene 67-MB-Datei prüft,
verhält sich genauso.

Das ist der Preis der Atomarität: Der frühere direkte Schreibvorgang wäre
durchgelaufen (dafür mit dem Risiko einer halben Datei). Weil solche
Leser immer nur kurz zugreifen, wird das Ersetzen jetzt ein paar Mal
wiederholt, statt beim ersten Versuch aufzugeben.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Wartezeiten zwischen den Versuchen, das Ersetzen durchzubekommen. Vier
# Wiederholungen, zusammen 0,75 s — knapp genug, dass ein blockierter
# Speichervorgang die Oberfläche nicht spürbar anhält (``_persist_cache``
# läuft synchron im GUI-Thread), lang genug für einen Leser oder einen
# Virenscanner, der die Datei gerade durchsieht. Wer länger blockiert,
# blockiert dauerhaft; dann hilft auch Warten nicht.
_RETRY_DELAYS_S = (0.05, 0.1, 0.2, 0.4)


def write_json(path: Path, payload: Any) -> None:
    """Schreibt ``payload`` als JSON nach ``path`` — vollständig oder gar
    nicht. Schlägt das Schreiben fehl, bleibt die bisherige Datei
    unangetastet; die Nebendatei wird aufgeräumt.

    Löst dieselben Ausnahmen aus wie ein direkter Schreibvorgang
    (``OSError``) — die Aufrufer protokollieren sie bereits und dürfen
    daran nichts ändern: Ein fehlgeschlagenes Speichern darf die
    Anwendung nicht abbrechen, aber es darf auch nicht so aussehen, als
    wäre es gelungen."""
    write_text(path, json.dumps(payload))


def write_text(path: Path, text: str) -> None:
    """Wie ``write_json``, für schon fertigen JSON-Text."""
    write_chunks(path, (text,))


def write_chunks(path: Path, chunks: Iterable[str]) -> None:
    """Wie ``write_text``, der Text kommt aber in Stücken. Der Daten-Cache
    (``data_cache.Snapshot.write``) schreibt so Fach für Fach, statt 77 MB
    erst zu einem Text zusammenzukleben: Zusammenkleben und Umwandeln in
    Bytes laufen in C und halten dabei die GIL — die Oberfläche stand
    solange (gemessen 2026-10-06)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as datei:
            for stueck in chunks:
                datei.write(stueck)
        _replace_with_retries(tmp, path)
    except OSError:
        # Nur die Nebendatei aufräumen — an der eigentlichen Datei wurde
        # noch nichts verändert, sie bleibt auf ihrem letzten gültigen
        # Stand. Das Aufräumen darf den ursprünglichen Fehler nicht
        # verdecken, deshalb missing_ok und kein zweiter try/except.
        tmp.unlink(missing_ok=True)
        raise


def remove_stale_temp(path: Path, min_age_s: float = 3600.0) -> int:
    """Liegengebliebene Nebendateien von ``path`` löschen — Reste eines
    Schreibvorgangs, den ein Absturz oder ein hart beendeter Prozess
    abgebrochen hat. Bei Peter lagen am 2026-10-06 vier davon neben dem
    Daten-Cache, zusammen 310 MB (aus September und Oktober). Nur Dateien,
    die älter sind als ``min_age_s``: Eine zweite Instanz könnte gerade
    schreiben. Gibt die Zahl der gelöschten Dateien zurück."""
    weg = 0
    grenze = time.time() - min_age_s
    for rest in path.parent.glob(f"{path.name}.*.tmp"):
        mitte = rest.name[len(path.name) + 1:-len(".tmp")]
        try:
            if mitte.isdigit() and rest.stat().st_mtime < grenze:
                rest.unlink()
                weg += 1
        except OSError:
            log.debug("Nebendatei %s ließ sich nicht löschen", rest.name)
    if weg:
        log.info("%d liegengebliebene Nebendatei(en) von %s gelöscht", weg, path.name)
    return weg


def _replace_with_retries(tmp: Path, path: Path) -> None:
    """``os.replace`` mit kurzen Wiederholungen (siehe Modul-Docstring).

    Wiederholt wird NUR das Ersetzen, nicht das Schreiben der Nebendatei —
    die liegt fertig da, ein erneutes Serialisieren wäre verschwendete
    Zeit und würde den Speichervorgang bei jedem Versuch verlängern.

    Der letzte Versuch läuft ohne Netz: Scheitert auch er, fliegt seine
    Ausnahme unverändert nach oben. Ein stillschweigend verschlucktes
    Scheitern wäre hier das Schlimmste — der Aufrufer glaubte dann,
    gespeichert zu haben."""
    for delay in _RETRY_DELAYS_S:
        try:
            os.replace(tmp, path)
            return
        except OSError as exc:
            log.debug("Atomares Ersetzen von %s fehlgeschlagen (%s), "
                      "neuer Versuch in %.2f s", path.name, exc, delay)
            time.sleep(delay)
    os.replace(tmp, path)
