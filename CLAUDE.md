Diese Datei liest Claude Code automatisch bei jeder Session in diesem
Repo. Sie hält knapp fest, was sich nicht aus dem Code ableiten lässt —
Ausführliches steht in den verlinkten Dateien. Persönliches (Namen,
Konto, Arbeitsweise des Maintainers) steht in einer gitignoreten
`CLAUDE.local.md`, die Claude Code zusätzlich liest, falls vorhanden.

## Was das Projekt ist

PoE-VIEW2: PySide6-Desktop-Viewer für Path of Exile über die offizielle
GGG-API. Öffentliches Repo, MIT-Lizenz. Startpunkt der Doku:
[README.md](README.md).

## Environment

**`python`/`pytest` immer aus dem Projekt-venv aufrufen**, nicht über den
`PATH` — auf der Entwicklungsmaschine zeigt das System-`python` auf ein
fremdes venv:

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe main.py
```

Die volle Testsuite dauert rund sieben Minuten (gut 2000 Tests). Vor der
Aussage "die Tests sind grün" tatsächlich laufen lassen, nicht aus einem
Teillauf schließen.

## Sprache

Kommunikation, Doku, Code-Kommentare: **Deutsch.** Oberfläche, README,
Hilfe-Dialog, GitHub-Metadaten (Repo-Beschreibung, Topics, Release-Text):
**Englisch** — das ist die Grenze, die fremde Leser sehen. Einzige
Ausnahme von der Doku-Regel: `docs/api-notes/poe-verhalten.md` ist
bewusst Englisch (siehe Datei-Kopf dort).

## Bevor irgendetwas an einen Screenshot, Testdaten oder einen Commit geht

- **Keine echten Konto- oder Charakternamen ins Repo** — in Tests,
  Screenshots und Doku erfundene Namen benutzen (`WitchOfPeter`,
  `PeterM`, `TestAccount#1234`, `Demo Ranger`, …).
- **Keine privaten E-Mail-Adressen ins Repo.**
- Screenshots/Demo-Daten: `tools/make_screenshots.py` erzeugt sie aus
  erfundenen Daten, ohne Zugriff auf den echten Cache. Nie von Hand
  aufnehmen — das ist der Weg, auf dem echte Namen versehentlich in die
  README geraten sind.
- `ToDo.md`, `.env`, `config.json`, `*.token`, `CLAUDE.local.md` sind
  gitignored.

## Tests

- **Schreiben das echte `%LOCALAPPDATA%\PoE-VIEW2\` niemals an** — die
  Autouse-Fixture in `tests/conftest.py` patcht `APP_DATA_DIR`, `LOG_DIR`
  und alle Downloads. Ein neues Modul, das aus `config.*` einen Pfad
  ableitet und hineinschreibt, MUSS ihn als Funktion bilden (nicht als
  beim Import eingefrorene Modul-Konstante), sonst greift der Schutz
  nicht.
- **UI-Größen/-Farben nicht offscreen messen.** `QT_QPA_PLATFORM=
  offscreen` (das Testsetup) hat eine andere Schriftbreite, eine helle
  Palette und andere Qt-Untergrenzen als ein echtes Windows. Für
  Pixel-/Kontrast-/Breitenfragen ohne die Umgebungsvariable messen,
  das gemalte Pixel prüfen, nicht den gesetzten Wert. Einzelheiten:
  FALLSTRICKE #55, #71, #95.
- **Nach jedem Fix eine Gegenprobe:** Fix kurz herausnehmen, der neue
  Test muss fallen. Sonst ist unklar, ob der Test die Regression
  überhaupt fängt.
- Farbentscheidungen werden gerechnet (WCAG-Kontrast für Text/Grund,
  CIEDE2000/ΔE für zwei Flächen nebeneinander), nicht per Auge beurteilt.

## Vor dem Commit/Release

- Commit-Messages enden mit `Co-Authored-By: Claude <noreply@anthropic.com>`
  (Modellname anpassen).
- Release-Ablauf, inklusive der Schritte, die schon mehrfach vergessene
  Features gefunden haben (README gegen Changelog lesen): siehe
  [RELEASING.md](RELEASING.md).

## Wo was steht — nicht duplizieren, dort nachschlagen

| Frage | Datei |
|---|---|
| Warum ist X so gebaut, wie es gebaut ist? | [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md) |
| Welcher Bug, welche Ursache, welcher Fix? | [FALLSTRICKE_UND_WORKAROUNDS.md](FALLSTRICKE_UND_WORKAROUNDS.md) |
| Was hat sich wann geändert? | [CHANGELOG.md](CHANGELOG.md) |
| Wie tickt das Spiel/die API wirklich (gemessen)? | [docs/api-notes/poe-verhalten.md](docs/api-notes/poe-verhalten.md), [docs/api-notes/ggg-api.md](docs/api-notes/ggg-api.md) |
| Wie released man? | [RELEASING.md](RELEASING.md) |
| Was sieht ein Nutzer/Fremder zuerst? | [README.md](README.md) |

Bei Bug-Reports zuerst den echten Log (`%LOCALAPPDATA%\PoE-VIEW2\logs\
poe-view2.log`) bzw. den echten Cache ansehen, nicht aus der
Beschreibung raten.
