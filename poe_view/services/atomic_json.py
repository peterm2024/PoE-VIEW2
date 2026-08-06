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
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        _replace_with_retries(tmp, path)
    except OSError:
        # Nur die Nebendatei aufräumen — an der eigentlichen Datei wurde
        # noch nichts verändert, sie bleibt auf ihrem letzten gültigen
        # Stand. Das Aufräumen darf den ursprünglichen Fehler nicht
        # verdecken, deshalb missing_ok und kein zweiter try/except.
        tmp.unlink(missing_ok=True)
        raise


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
