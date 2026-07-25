# PoE-VIEW2

[![Release](https://img.shields.io/github/v/release/peterm2024/PoE-VIEW2?label=Release)](https://github.com/peterm2024/PoE-VIEW2/releases)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-blue.svg)](LICENSE)

Ein Desktop-Tool für **Path of Exile**. Es zeigt Charaktere und
Stash-Tabs über die offizielle GGG-API an, durchsucht sie liga-weit über
alle Fächer hinweg und hält die Daten automatisch aktuell, ohne das
API-Rate-Limit auszureizen. Ist die GGG-API nicht erreichbar, arbeitet
PoE-VIEW2 mit dem lokalen Cache weiter.

Der Login läuft per OAuth2 direkt gegen `api.pathofexile.com`. PoE-VIEW2
sieht das Passwort zu keinem Zeitpunkt, und es ist keine dritte Partei
beteiligt. Das Access-Token liegt im Windows Credential Manager.

## Screenshots

*Beide Screenshots zeigen synthetische Demo-Daten, keinen echten Account.*

Liga-weite Suche mit `*`: Stash-Tabs und Charaktere erscheinen gemeinsam
in einer Tabelle, die Tab-Spalte nennt die Herkunft. Oben die
Typ-Filter, unten das Rate-Limit-Dashboard.

![Liga-weite Suche über Fächer und Charaktere](docs/screenshots/uebersicht.png)

Einzelnes Stash-Fach mit ausgewähltem Item; die Mods stehen im
Detail-Panel darunter.

![Einzelnes Fach mit ausgewähltem Item und Mods](docs/screenshots/item-details.png)

## Features

- **Login per OAuth2 (PKCE)** gegen die offizielle GGG-API. Das
  Access-Token liegt im Windows Credential Manager, nicht als Klartext
  auf der Platte.
- **Stash-Baum** mit Ordnern; Spezial-Tabs (Map- und Unique-Stash) werden
  automatisch nach Sektion bzw. Kategorie gruppiert.
- **Item-Tabelle** mit Icon, Herkunfts-Fach, Position (Tab-Nummer und
  Gitter-Koordinate, unterscheidet auch gleichnamige Fächer), Name, Typ,
  Level, Qualität, Stack-Größe, iLvl, Anforderungen (Level, Str, Dex,
  Int) und Mods.
- **Spalten-Filter** per Rechtsklick auf einen Spaltenkopf, mit
  Vergleichsausdrücken wie `>=20` für Quality oder `<45` für iLvl.
- **Liga-weite Suche** über alle geladenen Fächer und Charaktere
  gleichzeitig. `*` als Suchtext zeigt den gesamten Bestand an, gedacht
  für den vollständigen Export einer Liga.
- **Typ-Filter** für Normal, Magic, Rare, Unique, Gem, Currency,
  Divination Card und Sonstige, als farbige Checkboxen neben der
  Liga-Auswahl.
- **Charakter-Ansicht**: Ausrüstung und Inventar erscheinen in derselben
  Tabelle wie Stash-Items und sind genauso durchsuch- und filterbar.
- **CSV-Export** der aktuell sichtbaren, gefilterten Items.
- **Automatischer Hintergrund-Refresh**: hält das geöffnete Fach oder den
  angezeigten Charakter aktuell und lädt nach und nach die übrigen Fächer
  nach, ohne das Rate-Limit-Budget für manuelle Abfragen aufzubrauchen.
- **Offline-Betrieb**: Bei GGG-Wartung oder fehlender Verbindung zeigt
  die Anwendung den zuletzt bekannten Stand aus dem Cache, sichtbar als
  solcher markiert (📴).
- **Rate-Limit-Dashboard** mit Regeln, aktueller Auslastung und aktiven
  Sperren.
- **Rohdaten-Viewer** je Stash-Tab, der die unveränderte API-Antwort
  anzeigt.

## Download (Windows, kein Python nötig)

Auf der [Releases-Seite](https://github.com/peterm2024/PoE-VIEW2/releases)
steht zu jeder Version eine fertig kompilierte `PoE-VIEW2.exe` bereit.
Herunterladen und starten genügt; es ist weder eine Installation noch
eine Konfiguration nötig. Beim ersten Start führt ein Klick auf "Login"
durch die GGG-Anmeldung im Browser.

Windows SmartScreen warnt bei unsignierten Anwendungen vor einem
"unbekannten Herausgeber". Das betrifft jede nicht codesignierte
Anwendung und lässt sich über "Weitere Informationen" und "Trotzdem
ausführen" bestätigen.

## Tech-Stack

- Python 3.12+, [PySide6](https://doc.qt.io/qtforpython/) (GUI),
  [httpx](https://www.python-httpx.org/) (HTTP),
  [pydantic v2](https://docs.pydantic.dev/) (Datenmodelle),
  [keyring](https://pypi.org/project/keyring/) (Token-Speicherung)
- OAuth2 mit PKCE gegen die offizielle GGG-API (kein Client-Secret nötig)

## Setup aus dem Quellcode

```bash
git clone https://github.com/peterm2024/PoE-VIEW2.git
cd PoE-VIEW2
python -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Eine `.env` ist nicht erforderlich; Client-ID und Kontaktadresse haben
funktionierende Standardwerte. Wer PoE-VIEW2 forkt und selbst verteilt,
sollte beide überschreiben (`.env.example` dient als Vorlage):

- **`POE_CLIENT_ID`** — Standard ist `poeview`, eine bei GGG registrierte
  öffentliche Client-ID. Eine eigene lässt sich unter
  <https://www.pathofexile.com/developer/docs/authorization> registrieren;
  der Redirect-Port `64338` muss dann mit dem dort hinterlegten
  Redirect-URI übereinstimmen.
- **`POE_CONTACT_EMAIL`** — Kontaktangabe im User-Agent. Sie identifiziert
  laut [GGG-Dokumentation](https://www.pathofexile.com/developer/docs) die
  Anwendung, nicht den einzelnen Nutzer, und sollte bei eigener
  Distribution auf die eigene Adresse zeigen.

Beim ersten Start öffnet der Login-Button den Standard-Browser für die
GGG-Anmeldung. Danach bleibt die Anmeldung bis zum Ablauf des Tokens
bestehen; die Gültigkeitsdauer gibt GGG vor.

Zum Bauen einer eigenen `.exe` siehe [RELEASING.md](RELEASING.md).

## Tests

```bash
pytest
```

Die Test-Suite deckt Datenmodelle, API-Client, Rate-Limiter, Worker und
die UI-Logik ab. Sie kommt ohne Netzwerkzugriff aus.

## Dokumentation

- [CHANGELOG.md](CHANGELOG.md) — Änderungen je Version.
- [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md) — Aufbau der Anwendung und
  Begründung der Entwurfsentscheidungen.
- [docs/api-notes/ggg-api.md](docs/api-notes/ggg-api.md) — beobachtetes
  Verhalten der GGG-API, inklusive Abweichungen von der offiziellen
  Dokumentation.
- [FALLSTRICKE_UND_WORKAROUNDS.md](FALLSTRICKE_UND_WORKAROUNDS.md) —
  gelöste technische Hürden samt Ursache und Lösung.

## Status

PoE-VIEW2 ist im täglichen Gebrauch. Login, Stash- und
Charakter-Ansichten, Suche, Filter, CSV-Export, Auto-Refresh und der
Offline-Betrieb funktionieren. Das Projekt entsteht in Einzelarbeit und
erhebt keinen Anspruch auf Vollständigkeit gegenüber der offiziellen
PoE-Website. Fehlerberichte und Pull Requests sind willkommen.

## Lizenz

[MIT](LICENSE)

## Disclaimer

This product isn't affiliated with or endorsed by **Grinding Gear Games**
in any way.
