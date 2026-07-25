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
4. Beide Dateien committen (z. B. `Release vX.Y.Z vorbereiten`).

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
tun das nicht.

```
path-of-exile, poe, stash, inventory, ggg-api, pyside6, python, desktop-app
```
