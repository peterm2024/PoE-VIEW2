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

Unabhängig vom Release, aber für die Auffindbarkeit entscheidend: Die
GitHub-Topics (Repo-Seite, Zahnrad neben "About") steuern die
GitHub-interne Suche und die Indexierung durch Suchmaschinen. Git-Tags
tun das nicht. Gesetzt sind (Stand 2026-08-03, GitHub erlaubt bis zu 20):

```
path-of-exile, pathofexile, poe, poe-api, poe-tools, ggg-api, poeview,
stash, game-tools, pyside6, qt, python, desktop-app, windows
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

`ggg-api` und `poeview` haben null Treffer und bringen als Fundweg
zunächst nichts. Sie bleiben trotzdem drin: `poeview` ist die bei GGG
registrierte Client-ID aus dem User-Agent (siehe `poe_view/config.py`) —
wer sie in einem Log sieht und danach sucht, soll hier landen.
