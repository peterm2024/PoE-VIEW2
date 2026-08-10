# Release-Prozess

Diese Anleitung richtet sich an Maintainer. Die Versionierung folgt
[SemVer](https://semver.org/lang/de/) (`MAJOR.MINOR.PATCH`); der
Versionsstand in `CHANGELOG.md` und in `poe_view/__init__.py`
(`__version__`) muss übereinstimmen.

## 1. Version festlegen

1. `poe_view/__init__.py` → `__version__` auf die neue Version setzen.
2. `CHANGELOG.md`: Abschnitt `[Unveröffentlicht]` in `## [X.Y.Z] - JJJJ-MM-TT`
   umbenennen, neuen leeren `[Unveröffentlicht]`-Abschnitt darüber anlegen.
3. Tests ausführen (`pytest`). Nur bei vollständig grüner Suite weitermachen.
4. Hat sich die Oberfläche seit dem letzten Release sichtbar geändert:
   `python tools/make_screenshots.py`. Das Skript erzeugt die drei
   README-Bilder neu, aus erfundenen Daten und ohne Zugriff auf den
   echten Cache — von Hand aufgenommene Bilder sind dagegen genau der
   Weg, auf dem versehentlich echte Konto- oder Charakternamen in die
   README geraten. Es läuft NICHT headless, das Fenster erscheint kurz.
5. Geänderte Dateien committen (z. B. `Release vX.Y.Z vorbereiten`).

## 2. Windows-.exe bauen

Einmalig, in der `.venv`:

```bash
pip install -r requirements-build.txt
```

Danach bei jedem Release:

```bash
pyinstaller PoE-VIEW2.spec
```

Ergebnis ist `dist/PoE-VIEW2.exe`, eine eigenständige Datei von rund
60 MB. Sie enthält Python und Qt und setzt auf dem Zielrechner nichts
weiter voraus.

Das Anwendungssymbol steckt fertig als `assets/PoE-VIEW2.ico` im Repo
und muss für einen Release nicht angefasst werden. Nur wenn sich die
Grafik ändert, die Vorlagen in `assets/icon/` austauschen und einmal
`python tools/make_icon.py` laufen lassen — das baut die sieben
Größenstufen neu zusammen.

**Vor dem Hochladen manuell testen.** Die `.exe` in einen leeren Ordner
kopieren, ausdrücklich ohne `.env`, da Nutzer sie genau so erhalten.
Anschließend starten und den vollständigen Login-Flow durchspielen:
Browser öffnet sich, Anmeldung bei GGG, Rückkehr in die Anwendung, Liga
und Stash laden. PyInstaller-Builds können an Stellen brechen, die im
Betrieb über `python main.py` nie auffallen, etwa bei fehlenden Hidden
Imports oder bei Pfaden relativ zu `__file__` statt zur `.exe` (siehe
`poe_view/config.py`).

**Bekannter Stolperstein:** Windows SmartScreen und Virenscanner warnen
bei unsignierten Anwendungen vor einem unbekannten Herausgeber. Das ist
bei nicht codesignierten PyInstaller-Builds normal. Ein entsprechender
Hinweis im Release-Text erspart Rückfragen.

## 3. Tag + GitHub Release

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z dist/PoE-VIEW2.exe \
  --title "vX.Y.Z" \
  --notes-file <(sed -n "/## \[X.Y.Z\]/,/## \[/p" CHANGELOG.md | sed '$d')
```

Der `--notes-file`-Ausdruck schneidet den passenden Abschnitt aus dem
Changelog heraus. Alternativ lässt sich der Text manuell einfügen;
`gh release create` fragt sonst interaktiv danach.

## 4. Einmalig: Repo-Metadaten für Auffindbarkeit

**Die Repo-Beschreibung ("About") gehört auf Englisch** — sie steht
neben der README und im GitHub-Suchergebnis, richtet sich also an
dieselbe Leserschaft. Damit gilt hier dieselbe Grenze wie im ganzen
Projekt: Oberfläche und alles nach außen Sichtbare englisch,
Projektdoku und Code-Kommentare deutsch. Sie ist die einzige
nutzersichtbare Stelle, die außerhalb des Repos liegt und deshalb von
keinem Test erfasst wird (Peter fand sie am 2026-08-07 auf Deutsch,
nachdem v0.6.0 schon veröffentlicht war).

Für die Auffindbarkeit entscheidend: Die
GitHub-Topics (Repo-Seite, Zahnrad neben "About") steuern die
GitHub-interne Suche und die Indexierung durch Suchmaschinen. Git-Tags
tun das nicht. Gesetzt sind (Stand 2026-08-10, GitHub erlaubt bis zu 20):

```
path-of-exile, pathofexile, poe, poe1, poe-tools, ggg-api, poeview,
stash, stash-tabs, exile, game-tools, pyside6, qt, python, desktop-app,
windows
```

Die Auswahl beruht auf den tatsächlichen Nutzungszahlen, abgefragt über
`gh api "search/repositories?q=topic:<name>&per_page=1" --jq .total_count`.
Drei Erkenntnisse daraus, die man ohne Messung nicht hätte:

- **Die kleinen Topics sind der eigentliche Fundweg.** Unter `python`
  liegen über 800.000 Repos — dort taucht ein Projekt ohne Sterne nie
  auf. `poe-tools` hat 7 Einträge; dort steht man sofort auf Seite 1.
  Die großen Topics sind Etikett, nicht Fundweg.
- **`pathofexile` (323 Repos) ist verbreiteter als `path-of-exile`
  (200).** Beide Schreibweisen mitzunehmen kostet nichts.
- **Mehrdeutige Topics ziehen das falsche Publikum an.** `inventory`
  (3122) gehört zur Warenwirtschaft und wurde deshalb gestrichen.

**Nachtrag 2026-08-10: `poe-api` gegen `poe1` getauscht.** Die
Mehrdeutigkeits-Regel oben hat einen Fall übersehen, den man nicht
erraten kann — "Poe" heißt auch **Quoras KI-Plattform**, und die
beherrscht das Topic: unter den 13 Einträgen von `poe-api` stehen
`poe-api-wrapper` (1099★), `poe-openai-proxy` (456★) und ein
Claude-Telegram-Bot, PoE-VIEW2 lag auf dem letzten Platz. Bei `poe`
dasselbe Bild, dort führt ein chinesischer Chatbot mit 18.908★ vor Path
of Building. `poe` bleibt trotzdem drin (Etikett, kein Fundweg), `poe-api`
nicht — es kostet einen Platz und liefert das falsche Publikum.

`poe1` (11 Repos, alle echtes Path of Exile 1) ist der Ersatz: klein
genug für Seite 1 und inhaltlich richtig, seit PoE 2 die Unterscheidung
für Suchende überhaupt erst nötig macht. Dazu kamen `stash-tabs` (jetzt
4 Repos — die wörtlichste Beschreibung dessen, was das Programm zeigt,
und eine Seite, die man vollständig liest) und `exile`, das Insider-Wort
der Spielerschaft (NeverSinks Lootfilter, Exilence, PAL2). Bei `exile`
ohne Illusionen: Platz 30 von rund 34, also das Ende der ersten Seite.
Es kostet nichts und das Publikum stimmt, ein Fundweg ist es vorerst
nicht. Null Treffer und damit von vornherein wertlos:
`pathofexile-api`, `path-of-exile-api`, `poe-stash`,
`path-of-exile-tools`, `poe-tool`.

Damit sind 16 der 20 Plätze belegt. Die verbleibenden vier bewusst frei
gelassen: Ein Topic, das man nur nimmt, um die Liste zu füllen, ist
genau der Fall, den die Mehrdeutigkeits-Regel oben verhindern soll.

`ggg-api` und `poeview` haben null Treffer und bringen als Fundweg
zunächst nichts. Sie bleiben trotzdem drin: `poeview` ist die bei GGG
registrierte Client-ID aus dem User-Agent (siehe `poe_view/config.py`) —
wer sie in einem Log sieht und danach sucht, soll hier landen.
