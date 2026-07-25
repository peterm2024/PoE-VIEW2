# Release-Prozess

Nur für Maintainer. Richtet sich nach [SemVer](https://semver.org/lang/de/)
(`MAJOR.MINOR.PATCH`) — Versionsstand in `CHANGELOG.md` und
`poe_view/__init__.py` (`__version__`) müssen synchron bleiben.

## 1. Version festlegen

1. `poe_view/__init__.py` → `__version__` auf die neue Version setzen.
2. `CHANGELOG.md`: Abschnitt `[Unveröffentlicht]` in `## [X.Y.Z] - JJJJ-MM-TT`
   umbenennen, neuen leeren `[Unveröffentlicht]`-Abschnitt darüber anlegen.
3. Tests laufen lassen (`pytest`) — nur bei grüner Suite weitermachen.
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

Ergebnis: `dist/PoE-VIEW2.exe` (Single-File, ~60 MB — enthält Python +
Qt, braucht auf dem Zielrechner nichts weiter installiert).

**Vor dem Hochladen manuell testen:** `.env` (mind. `POE_CONTACT_EMAIL`)
neben die `.exe` legen, starten, kompletten Login-Flow einmal durchspielen
(Browser öffnet sich, Login bei GGG, Rückkehr in die App, Liga/Stash
laden). PyInstaller-Builds können an Stellen brechen, die im
`python main.py`-Betrieb nie auffallen (fehlende Hidden Imports, Pfade
relativ zu `__file__` statt zur `.exe`, siehe `poe_view/config.py`).

**Bekannter Stolperstein:** Windows SmartScreen/Antivirus-Software warnt
bei unsignierten `.exe`-Dateien routinemäßig ("Unbekannter Herausgeber")
— das ist bei nicht codesignierten PyInstaller-Builds normal, keine
Fehlfunktion. Im Release-Text darauf hinweisen, damit Nutzer nicht
verunsichert sind.

## 3. Tag + GitHub Release

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z dist/PoE-VIEW2.exe \
  --title "vX.Y.Z" \
  --notes-file <(sed -n "/## \[X.Y.Z\]/,/## \[/p" CHANGELOG.md | sed '$d')
```

(Der `--notes-file`-Einzeiler schneidet den passenden Abschnitt aus dem
Changelog — bei Bedarf einfach den Text manuell in die Release-Notizen
kopieren, `gh release create` fragt sonst interaktiv danach.)

## 4. Einmalig: Repo-Metadaten für Auffindbarkeit

Keine Versionsaufgabe, aber für neue Besucher relevant — GitHub-"Topics"
(Repo-Seite → Zahnrad neben "About") sind der eigentliche Hebel für
GitHub-interne Suche und Google-Indexierung, nicht Git-Tags:

```
path-of-exile, poe, stash, inventory, ggg-api, pyside6, python, desktop-app
```
