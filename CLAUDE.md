Diese Datei liest Claude Code automatisch bei jeder Session in diesem
Repo. Sie soll knapp halten, was sonst jedes Mal neu erklärt werden
müsste — Ausführliches steht in den verlinkten Dateien, hier nur der
Wegweiser dorthin plus die Fallen, die sich nicht aus dem Code ableiten
lassen.

## Was das Projekt ist

PoE-VIEW2: PySide6-Desktop-Viewer für Path of Exile über die offizielle
GGG-API. Öffentliches Repo, MIT-Lizenz, in aktivem Alltagseinsatz bei
Peter. Startpunkt der Doku: [README.md](README.md).

## Environment — die eine Falle, die sofort zuschlägt

**`python`/`pytest` ohne Pfad treffen NICHT dieses Projekt.** Das System-
`python` zeigt auf ein fremdes venv. Immer explizit:

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe main.py
```

Volle Testsuite dauert 2–3 Minuten (aktuell ~1150 Tests). Vor jeder
größeren Aussage "die Tests sind grün" tatsächlich laufen lassen, nicht
aus einem Teillauf schließen.

## Sprache

Kommunikation, Doku, Code-Kommentare: **Deutsch.** Oberfläche, README,
Hilfe-Dialog, GitHub-Metadaten (Repo-Beschreibung, Topics, Release-Text):
**Englisch** — das ist die Grenze, die fremde Leser sehen. Einzige
Ausnahme von der Doku-Regel: `docs/api-notes/poe-verhalten.md` ist
bewusst Englisch (siehe Datei-Kopf dort).

## Bevor irgendetwas an einen Screenshot, Testdaten oder einen Commit geht

- **Kein echter Charaktername ins Repo.** Peters echte Charaktere heißen
  `KRN_RF_*`/`KRN_LZ_*` — nie in Tests, Screenshots oder Doku verwenden.
  Erfundene Namen benutzen (`WitchOfPeter`, `PeterM`, `TestAccount#1234`,
  `Demo Ranger`, …).
- **Keine private E-Mail ins Repo.** Der Projekt-Alias
  `poeview2@gmx.net` ist dagegen bewusst öffentlich.
- Der Kontoname `Gandol#4338` darf öffentlich sein (Peters Entscheidung).
- Screenshots/Demo-Daten: `tools/make_screenshots.py` erzeugt sie aus
  erfundenen Daten, ohne Zugriff auf den echten Cache. Nie von Hand
  aufnehmen — das ist der Weg, auf dem echte Namen versehentlich in die
  README geraten sind.
- **Keine Git-History-Rewrites** ohne ausdrückliche Ansage — hier schon
  einmal nötig gewesen (`git-filter-repo` vor dem Öffentlichschalten),
  seither Ausnahme, keine Routine.
- `ToDo.md`, `.env`, `config.json`, `*.token` sind gitignored. `ToDo.md`
  ist Peters Notizfeld — lesen, aber der Inhalt gehört nicht automatisch
  in Commits oder Doku.
- **Ein lokaler Hook blockiert `git commit`**, wenn die staged
  Änderungen ein bekanntes privates Muster enthalten (Charakternamen-
  Präfix `KRN_`, private E-Mail) — siehe `.claude/hooks/
  check_private_strings.py` und `.claude/private-strings.txt`. Beides
  liegt unter dem gitignoreten `.claude/`-Ordner, reist also NICHT mit
  dem Repo mit und existiert nur auf Peters Maschine, auf der er
  eingerichtet wurde. Ein blockierter Commit mit dieser Meldung ist kein
  Fehler — das Muster gehört raus, nicht der Hook umgangen.

## Tests

- **Schreiben Peters echten `%LOCALAPPDATA%\PoE-VIEW2\` niemals an** —
  die Autouse-Fixture in `tests/conftest.py` patcht `APP_DATA_DIR` und
  `LOG_DIR`. Ein neues Modul, das aus `config.*` einen Pfad ableitet und
  hineinschreibt, MUSS diesen Schutz kennen und als Funktion (nicht als
  eingefrorene Modul-Konstante) implementiert sein — siehe FALLSTRICKE
  #ähnliche Fälle unten.
- **UI-Größen/-Farben nicht offscreen messen.** `QT_QPA_PLATFORM=
  offscreen` (das Testsetup) hat eine andere Schriftbreite, eine helle
  Palette und andere Qt-Untergrenzen als Peters echtes Windows. Für
  Pixel-/Kontrast-/Breitenfragen ohne die Umgebungsvariable messen.
  Einzelheiten: FALLSTRICKE #55, #71.
- **Nach jedem Fix eine Gegenprobe:** Fix kurz herausnehmen, der neue
  Test muss fallen. Sonst ist unklar, ob der Test die Regression
  überhaupt fängt.
- Farbentscheidungen werden gerechnet (WCAG-Kontrast für Text/Grund,
  CIEDE2000/ΔE für zwei Flächen nebeneinander), nicht per Auge beurteilt.

## Vor dem Commit/Release

- Commit-Messages enden mit `Co-Authored-By: Claude <noreply@anthropic.com>`
  (Modellname anpassen). Nur committen/pushen, wenn ausdrücklich
  gewünscht.
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

## Arbeitsweise mit Peter

Peter ist kein Python-Programmierer, beurteilt Verhalten und Spielwissen,
nicht Code. Rhythmus: Feature umsetzen → Tests + Gegenprobe → Doku
(ARCHITEKTUR + FALLSTRICKE) nachziehen → knappe Zusammenfassung → auf
Feedback warten. Bei Architektur-/UX-Fragen: kurze Empfehlung mit
Trade-off geben, dann entscheiden lassen, nicht ungefragt umsetzen. Bei
Bug-Reports zuerst den echten Log (`%LOCALAPPDATA%\PoE-VIEW2\logs\
poe-view2.log`) bzw. den echten Cache ansehen, nicht aus der Beschreibung
raten.
