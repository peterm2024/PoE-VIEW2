"""Nur eine Instanz darf ein Konto bewirtschaften.

Peter, 2026-08-05: "Zweitstart theoretisch ja, aber nur im Offline-Modus
bzw. anderer Account. Ich will nicht, dass beide gleichzeitig Daten
refreshen und dann beide versuchen den neuen Inhalt zu schreiben."

Der Anspruch gilt bewusst PRO KONTO, nicht pro Programm: Zwei Instanzen
mit verschiedenen Konten stören einander nicht — sie schreiben in
getrennte Cache-Dateien (``data_cache.path_for``) und verbrauchen
getrennte Rate-Limit-Budgets, weil GGG pro Konto zählt (FALLSTRICKE #65).
Nur zwei Instanzen auf DEMSELBEN Konto sind das Problem.

**Warum eine Byte-Bereichs-Sperre und keine Datei, deren bloßes
Vorhandensein "belegt" bedeutet:** Eine solche Marker-Datei überlebt
einen Absturz und sperrt danach dauerhaft aus — der Nutzer müsste von
Hand aufräumen, und die häufigste Rückmeldung wäre "ich kann das
Programm nicht mehr starten". ``msvcrt.locking`` hängt dagegen am
Prozess: Stirbt er, gibt das Betriebssystem die Sperre frei. Es gibt
damit keine verwaisten Sperren, die man je aufräumen müsste.
"""

from __future__ import annotations

import logging
from pathlib import Path

from poe_view.services import data_cache

try:  # pragma: no cover — auf Windows immer vorhanden, das Zielsystem
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]

log = logging.getLogger(__name__)


def path_for(account_name: str) -> Path:
    """Sperrdatei neben der Cache-Datei desselben Kontos — dieselbe
    Namensbereinigung, damit beide zuverlässig zusammenpassen."""
    cache = data_cache.path_for(account_name)
    return cache.with_name(cache.name + ".lock")


class InstanceLock:
    """Exklusiver Anspruch auf ein Konto, gehalten bis zum Freigeben oder
    bis zum Ende des Prozesses."""

    def __init__(self, account_name: str) -> None:
        self.account_name = account_name
        self.path = path_for(account_name)
        self._handle = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> bool:
        """``True``, wenn diese Instanz das Konto jetzt bewirtschaften
        darf. ``False`` heißt: Eine andere Instanz hat es bereits.

        Ohne ``msvcrt`` (also außerhalb von Windows, praktisch nur in
        einer fremden Entwicklungsumgebung) wird bewusst ``True``
        geliefert. Die Alternative wäre, dort grundsätzlich in den
        Nur-Lese-Modus zu gehen — das würde eine Einschränkung erfinden,
        wo gar kein Konflikt nachgewiesen ist."""
        if self.held:
            return True
        if msvcrt is None:  # pragma: no cover
            return True
        handle = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.path, "a+b")
            handle.seek(0)  # locking() sperrt ab der aktuellen Position
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            if handle is not None:
                handle.close()
            log.info("Konto %s wird bereits von einer anderen Instanz "
                    "bewirtschaftet — diese läuft nur lesend.", self.account_name)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        """Gibt den Anspruch frei. Mehrfach aufrufbar.

        Das Schließen allein gäbe die Sperre schon frei; das ausdrückliche
        Entsperren steht davor, damit die Reihenfolge auch dann stimmt,
        wenn das Schließen scheitert."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if msvcrt is not None:  # pragma: no branch
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            log.debug("Sperre für %s ließ sich nicht ausdrücklich lösen — "
                     "das Schließen erledigt es.", self.account_name, exc_info=True)
        finally:
            handle.close()
