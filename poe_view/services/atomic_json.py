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
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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
        os.replace(tmp, path)
    except OSError:
        # Nur die Nebendatei aufräumen — an der eigentlichen Datei wurde
        # noch nichts verändert, sie bleibt auf ihrem letzten gültigen
        # Stand. Das Aufräumen darf den ursprünglichen Fehler nicht
        # verdecken, deshalb missing_ok und kein zweiter try/except.
        tmp.unlink(missing_ok=True)
        raise
