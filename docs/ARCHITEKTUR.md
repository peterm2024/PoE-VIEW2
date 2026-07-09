# PoE-VIEW2 — Architektur & Konzept

**Stand:** 2026-07-09 · **Status:** Entwurf (v0.1)

PoE-VIEW2 ist die Python-Referenzimplementierung des LabVIEW-Tools **PoE-VIEW**:
ein Community-Tool, das über die offizielle GGG-API Accounts, Charaktere und
Stash-Tabs ausliest, filtert und übersichtlich darstellt.

> **Dokumentations-Leitlinie:** Dieses Projekt dient als Vorlage für eine spätere
> (Rück-)Portierung nach LabVIEW. Deshalb dokumentieren wir nicht nur *was* der
> Code tut (funktionell), sondern auch *warum* er so gebaut ist (intentionell).
> Jedes Modul erhält einen Docstring mit einem Abschnitt **"LabVIEW-Äquivalent"**,
> der beschreibt, wie das Konzept in LabVIEW umgesetzt wird/wurde.

---

## 1. Ziele & Nicht-Ziele

**Ziele**

- Account-Login via OAuth2 (PKCE), Token-Verwaltung
- Charaktere und Stash-Tabs (inkl. verschachtelter Ordner) anzeigen
- Items mit Eigenschaften (Level, Quality bei Gems, …) tabellarisch darstellen, sortier- und filterbar
- Item-Icons anzeigen (mit lokalem Cache)
- Striktes, für den User sichtbares Rate-Limit-Management (kein 429/Bann)
- Saubere, LabVIEW-portierbare Architektur mit ausführlicher Dokumentation
- Open-Source-tauglich (keine Secrets im Code, Disclaimer)

**Nicht-Ziele (vorerst)**

- Trade-/Preis-Funktionen, Markt-Anbindung
- Schreibende API-Zugriffe
- Mehrbenutzer-/Serverbetrieb — das Tool ist eine lokale Desktop-App

---

## 2. Tech-Stack & Begründung

| Bereich | Wahl | Begründung (Intention) |
|---|---|---|
| GUI | **PySide6** (Qt 6) | Tree-Views, Tabellen, Signale/Slots — entspricht 1:1 den LabVIEW-Konzepten (Tree Control, Multicolumn Listbox, User Events). LGPL-lizenziert, Open-Source-kompatibel. |
| HTTP | **httpx** (synchron, mit `Client`) | Persistente Session mit festen Headern = LabVIEW "persistenter HTTP-Client-Handle". |
| Datenmodelle | **pydantic v2** | Validiertes JSON-Parsing; Modelle entsprechen LabVIEW-Clustern/Typedefs. |
| Nebenläufigkeit | **QThread-Worker + Qt-Signale** (bewusst *kein* asyncio) | Siehe 2.1 — beste Abbildbarkeit auf LabVIEW. |
| Konfiguration | `.env` / `config.json` (in `.gitignore`) | Kein Client-Secret im Code (Open-Source-Compliance). |
| Token-Speicherung | `keyring` (Windows Credential Manager) | Entspricht der LabVIEW-Lösung "externe Datei", aber sicherer. |

### 2.1 Warum Threads statt asyncio?

Gemini hatte `asyncio` empfohlen. Wir entscheiden uns **bewusst dagegen**
*(Entscheidung bestätigt 2026-07-09; eine LabVIEW-Rückportierung ist
inzwischen optional, das Argument gilt auch ohne sie)*:

- **Einfachste robuste Qt-Integration:** Qt hat einen eigenen Event-Loop;
  asyncio daneben zu betreiben erfordert eine Brücke (z. B. `qasync`) —
  eine zusätzliche Abhängigkeit und Fehlerquelle ohne Nutzen für uns.
- Die App macht wenige, **sequenzielle** API-Calls — Parallelität ist nicht
  gewollt (Rate-Limit!), asyncio brächte hier keinen praktischen Vorteil.
- Bonus LabVIEW: Das Modell *"Worker-Thread + Queue + blockierendes Sleep"*
  entspricht exakt LabVIEWs QMH/Producer-Consumer mit `Wait (ms)`. Falls
  doch je portiert wird, bleibt die Ablauflogik 1:1 übertragbar —
  `asyncio`-Coroutinen hätten kein LabVIEW-Gegenstück.

**Regel:** UI läuft im Main-Thread. Alle API-Calls laufen in einem einzigen
API-Worker-Thread, der Aufträge aus einer Queue abarbeitet (sequenziell — das
vereinfacht auch das Rate-Limiting). Ergebnisse gehen per Qt-Signal zurück an
die UI. Die UI blockiert dadurch nie, auch wenn der Rate-Limiter 60 s wartet.

### 2.2 Konzept-Mapping Python ↔ LabVIEW

Diese Tabelle ist der "Rosetta-Stein" für die spätere Portierung:

| LabVIEW | Python (PoE-VIEW2) |
|---|---|
| Functional Global Variable (FGV) | Singleton-Klasse mit `threading.Lock` (`RateLimitManager`) |
| Shift-Register-State der FGV | Instanzattribute der Singleton-Klasse |
| Cluster / Typedef | pydantic-Modell bzw. `dataclass` |
| User Event → Main-VI | Qt-Signal → Slot im MainWindow |
| Queued Message Handler / Producer-Consumer | `ApiWorker` (QThread) + `queue.Queue` von Job-Objekten |
| `Wait (ms)` im FGV-Case "Check & Wait" | `time.sleep()` im Worker-Thread (nie im Main-Thread!) |
| Tree Control | `QTreeWidget` |
| Multicolumn Listbox | `QTableView` + `QAbstractTableModel` + `QSortFilterProxyModel` |
| Picture Control | `QLabel` mit `QPixmap` |
| Persistenter HTTP-Client-Handle | `httpx.Client`-Instanz mit Default-Headern |
| Hex-Farbe → U32 | `QColor("#rrggbb")` |
| Fehler-Cluster | Exceptions + `error`-Signal des Workers |

---

## 3. Schichtenarchitektur

Strikte Trennung in drei Schichten. **Abhängigkeiten zeigen nur nach unten**;
die API-Schicht weiß nichts von Qt, die UI weiß nichts von HTTP.

```
┌─────────────────────────────────────────────────────────┐
│  UI-Schicht (PySide6)                                   │
│  MainWindow · StashTree · ItemTable · ItemDetail        │
│  RateLimitDashboard · LoginDialog                       │
└───────────────▲─────────────────────┬───────────────────┘
                │ Qt-Signale          │ Jobs (Queue)
┌───────────────┴─────────────────────▼───────────────────┐
│  Service-/Worker-Schicht                                │
│  ApiWorker (QThread) · IconCache · TokenStore           │
└───────────────▲─────────────────────┬───────────────────┘
                │ pydantic-Modelle    │ Aufrufe
┌───────────────┴─────────────────────▼───────────────────┐
│  API-Schicht (reines Python, kein Qt!)                  │
│  OAuthPkceFlow · PoeApiClient · RateLimitManager        │
│  models (Character, StashTab, Item, …)                  │
└─────────────────────────────────────────────────────────┘
```

*Intention:* Die API-Schicht ist ohne GUI testbar (pytest, auch offline mit
gespeicherten JSON-Antworten) und entspricht in LabVIEW den SubVIs ohne
Frontpanel-Bezug.

### 3.1 Projektstruktur

```
PoE-VIEW2/
├── docs/
│   ├── ARCHITEKTUR.md          ← dieses Dokument
│   └── api-notes/              ← Beobachtungen zur GGG-API (Header, JSON-Beispiele)
├── poe_view/
│   ├── __init__.py
│   ├── config.py               # Pfade, Client-ID, User-Agent, .env-Laden
│   ├── api/
│   │   ├── oauth.py            # OAuth2 PKCE + lokaler Callback-Server
│   │   ├── client.py           # PoeApiClient: httpx.Client, Header, Endpunkte
│   │   ├── rate_limiter.py     # RateLimitManager (≙ FGV)
│   │   └── models.py           # pydantic: Character, StashTab, Item, ItemProperty
│   ├── services/
│   │   ├── api_worker.py       # QThread + Job-Queue (≙ QMH-Loop)
│   │   ├── icon_cache.py       # Icon-Download + Datei-Cache
│   │   ├── data_cache.py       # Charaktere/Stash/Items überleben einen Neustart
│   │   ├── csv_export.py       # Item-Export als CSV
│   │   └── token_store.py      # keyring-Wrapper
│   └── ui/
│       ├── main_window.py
│       ├── character_list.py   # flache Charakterliste (kein Tree)
│       ├── stash_tree.py       # Stash-Baum (Tabs = Top-Level-Items, kein Wrapper)
│       ├── item_table.py       # TableModel + SortFilterProxy
│       ├── item_detail.py
│       ├── raw_data_viewer.py  # Rohdaten-Mini-Viewer (Rechtsklick im Baum)
│       └── rate_limit_dashboard.py
├── tests/
│   ├── fixtures/               # gespeicherte API-JSON-Antworten
│   ├── test_rate_limiter.py
│   └── test_models.py
├── main.py                     # Einstiegspunkt
├── requirements.txt
├── .env.example                # Vorlage: POE_CLIENT_ID, POE_CONTACT_EMAIL
├── .gitignore
└── README.md
```

---

## 4. Kernkomponenten

### 4.1 OAuth2 mit PKCE (`api/oauth.py`)

Ablauf (identisch zur LabVIEW-Implementierung; erprobte Parameter siehe
[api-notes/labview-test-vi.md](api-notes/labview-test-vi.md)):

1. `code_verifier` (Zufallsstring), `code_challenge` (SHA-256, base64url) und
   `state` (64-Bit-Zufall, `%016x`) erzeugen.
2. Lokalen HTTP-Server auf `http://localhost:64338` starten (Standardbibliothek
   `http.server`, ein einziger Request) — Port 64338 ist als Redirect-URI der
   Client-Registrierung fest hinterlegt.
3. Browser mit der GGG-Authorize-URL öffnen (`webbrowser.open`).
4. Callback abfangen → `state` prüfen (CSRF-Schutz, ≙ "State OK?" im Test-VI)
   → `code` extrahieren → Erfolgsseite ausliefern → Server beenden.
5. `code` + `code_verifier` gegen Access-Token tauschen (gültig ~10 h).
6. Token im Windows Credential Manager speichern (`keyring`); beim App-Start
   prüfen, ob ein gültiges Token existiert → Login-Schritt überspringen.

*Client-ID:* `poeview` (registrierte public App, kein Secret — PKCE genügt)
*Scopes:* `account:profile account:stashes account:characters account:leagues`

### 4.2 API-Client (`api/client.py`)

- Eine `httpx.Client`-Instanz für die gesamte Laufzeit (Connection-Pooling,
  minimale SSL-Handshakes) mit festen Headern:
  - `Authorization: Bearer <token>`
  - `User-Agent: OAuth poe-view2/<version> (contact: <email>)` — **Pflicht** laut GGG.
- Jeder Request läuft durch eine zentrale Methode `_get(path, policy)`:

```python
def _get(self, path: str, policy_hint: str) -> httpx.Response:
    """Zentraler GET. LabVIEW-Äquivalent: SubVI 'HTTP GET wrapped'.

    Intention: Rate-Limit-Check VOR und State-Update NACH jedem
    Request erzwingen — kein Endpunkt kann das umgehen.
    """
    self.rate_limiter.check_and_wait(policy_hint)   # ≙ FGV-Case "Check & Wait"
    resp = self._http.get(self.BASE_URL + path)
    self.rate_limiter.update_from_headers(resp.headers)  # ≙ Header-Parsing
    if resp.status_code == 429:
        # Defensive: Retry-After respektieren, einmal wiederholen
        ...
    resp.raise_for_status()
    return resp
```

- Endpunkte (v1): `get_profile()`, `get_leagues()`, `get_characters()`,
  `get_character(name)`, `get_stashes(league)`, `get_stash(league, stash_id)`.
- Liga-Namen können Leerzeichen enthalten (`SSF Ruthless`) → Pfadsegmente
  immer per `urllib.parse.quote` encoden.

### 4.3 Rate-Limit-Manager (`api/rate_limiter.py`) — das Kernsystem

Direkte Übersetzung der LabVIEW-FGV. Threadsicher via `threading.Lock`
(in v1 nur ein API-Thread, aber der Lock dokumentiert die Intention und
entspricht der Nicht-Reentranz einer FGV).

**Datenmodell** (≙ FGV-Cluster):

```python
@dataclass
class RateLimitRule:
    max_hits: int        # MaxRequests   (aus X-Rate-Limit-Account,  Feld 1)
    window_s: int        # WindowSize    (Feld 2)
    lock_s: int          # LockTime      (Feld 3)
    current: int = 0     # CurrentCount  (aus ...-Account-State, Feld 1)
    active_lock_s: int = 0  # laufende Sperre (State, Feld 3)

@dataclass
class PolicyState:
    policy_name: str            # aus X-Rate-Limit-Policy
    rules: list[RateLimitRule]  # mehrere Regeln, z. B. "10:15:60,30:300:1800"
    last_update: float          # Timestamp (≙ LastUpdate im Shift-Register)
```

**Header-Parsing** — hier steckte der LabVIEW-Bug (Mapping Current/Max),
deshalb halten wir das Format explizit fest:

- `X-Rate-Limit-Account` = Regeln: `Max:Window:LockTime[,Max:Window:LockTime…]`
- `X-Rate-Limit-Account-State` = Verbrauch: `Current:Window:AktiveSperre[,…]`
- Die Zuordnung Regel ↔ State erfolgt **über die Window-Größe (Feld 2)**,
  nicht über die Array-Position.
- Es kann zusätzlich `X-Rate-Limit-Ip` / `-Ip-State` geben → gleiche Logik,
  eigener Policy-Eintrag.

**Verhalten:**

- `check_and_wait(policy)` — vor jedem Request. Berechnet über *alle* Regeln
  der Policy die maximal nötige Wartezeit und blockiert per `time.sleep()`
  (im Worker-Thread). Konservative Strategie: Warten, sobald
  `current >= max_hits - safety_margin` (Marge: 1), statt erst bei Erreichen.
- `update_from_headers(headers)` — nach jedem Request: Header parsen,
  State + Timestamp aktualisieren.
- **Status-Callback:** Der Manager meldet jede Zustandsänderung und jeden
  Warte-Countdown über einen Callback nach außen (≙ User Event an das Main-VI).
  Der `ApiWorker` verdrahtet diesen Callback mit einem Qt-Signal
  `rate_limit_changed(policy, rules, wait_remaining_s)` → füttert das Dashboard.
  *Intention:* Der Manager selbst bleibt Qt-frei (Schichtentrennung).

### 4.4 Datenmodelle (`api/models.py`)

pydantic-Modelle mit `extra="allow"` (die API liefert mehr Felder, als wir
modellieren — nichts geht verloren, nichts bricht bei API-Erweiterungen):

- `Character`: name, class_, level, league, experience, …
- `StashTab`: id, name, type, index, colour (`#rrggbb` → via `QColor` in der UI),
  `children: list[StashTab]` (rekursiv — Ordner!), `items: list[Item]`
- `Item`: id, name, typeLine, baseType, icon (URL), frameType (Rarity),
  `properties: list[ItemProperty]`, sockets, …
- `ItemProperty`: name, `values: list[tuple[str, int]]`

**Gem-Level/Quality** (die bekannte Sonderlocke) als dokumentierte Helper:

```python
def get_property(item: Item, prop_name: str) -> str | None:
    """Sucht eine Property per Name. Wert steckt in values[0][0].

    Intention: Die API hat KEINE festen Keys für Level/Quality —
    sie liegen als Einträge im 'properties'-Array. Quality kommt
    als '+20%' und wird hier normalisiert.
    LabVIEW-Äquivalent: Schleife über properties-Array im SubVI
    'Extract Gem Info'.
    """
```

### 4.5 API-Worker (`services/api_worker.py`)

Ein `QThread` mit Job-Queue — das Python-Pendant zum LabVIEW-QMH:

- Jobs sind kleine Objekte: `FetchCharacters`, `FetchStashList(league)`,
  `FetchStashItems(league, stash_id)`, `FetchIcon(url)`, `Login`, …
- Der Worker arbeitet die Queue **sequenziell** ab (ein Request nach dem
  anderen → Rate-Limiter bleibt einfach und deterministisch).
- Ergebnisse/Fehler per Signal: `characters_loaded`, `stash_list_loaded`,
  `stash_items_loaded(league, stash_id, name, items, silent)` (die Liga
  reist explizit im Signal mit, siehe FALLSTRICKE_UND_WORKAROUNDS.md #10),
  `icon_loaded(url, bytes)`, `error(job, message)`, `rate_limit_changed(...)`.
- Icon-Downloads bekommen **niedrige Priorität** (eigene Queue oder
  Prioritäts-Queue): Erst Daten, dann Bilder.

#### 4.5.1 Status-Text vs. Busy-Zustand — zwei getrennte Signale

`status(str)` (Verlaufstext, z. B. "Lade Items: Currency 1 …") und
`busy_changed(bool)` (steuert nur den Spinner) sind bewusst getrennt.

*Ursprünglicher Bug:* `_dispatch()` emittierte früher am Ende JEDES Jobs
unbedingt `status.emit("Bereit")`. Da Qt Cross-Thread-Signale FIFO in der
Reihenfolge des Absendens auf dem Main-Thread verarbeitet, kam dieses
"Bereit" nach `stash_items_loaded` immer als Letztes an und überschrieb die
gerade erst gesetzte, spezifischere Meldung ("Currency 1: 45 Items") sofort
wieder — sichtbar war es nur, wenn der Tab aus dem Netz kam (bei einem
Cache-Treffer gab es kein nachfolgendes "Bereit", das den Text stiehlt).

*Lösung:* `run()` emittiert `busy_changed(True/False)` rund um JEDEN Job
(`try/finally`), unabhängig vom Inhalt. `status.emit("Bereit")` gibt es nur
noch in den Cases, deren Ergebnis-Signal in der UI KEINEN eigenen
Abschlusstext setzt (Ligen, Charaktere, Stash-Liste). Cases mit eigenem
Abschlusstext (`FetchStashItemsJob`, `FetchAllItemsJob`) emittieren bewusst
kein "Bereit".

### 4.6 Icon-Cache (`services/icon_cache.py`)

- Cache-Ordner: `%LOCALAPPDATA%/PoE-VIEW2/icon-cache/`
- Dateiname = Hash der URL (URLs enthalten Query-Parameter/Sonderzeichen).
- Ablauf: Cache-Hit → sofort `QPixmap`; Miss → `FetchIcon`-Job → Signal → Anzeige.
- Icon-CDN-Downloads laufen ebenfalls über den Rate-Limiter (eigene, milde Policy).

### 4.7 Persistenter Daten-Cache (`services/data_cache.py`)

Charaktere, Stash-Struktur und bereits geladene Items überleben einen
Neustart — eine JSON-Datei (`%LOCALAPPDATA%/PoE-VIEW2/data-cache.json`)
statt einer Datenbank: Der Datenumfang rechtfertigt keine Datenbank, und
JSON ist 1:1 nach LabVIEW portierbar ("Flatten/Unflatten to JSON").

- **Struktur:** `stash_trees: {Liga: [StashTab, …]}` (Baum OHNE Items — die
  Stash-LISTE der API liefert nie Items, die kommen ausschließlich vom
  Einzel-Tab-Endpunkt) getrennt von `items_by_league: {Liga: {stash_id:
  [Item, …]}}`, plus `last_loaded: {Liga: {stash_id: ISO-Zeitstempel}}`
  (wann ein Tab zuletzt erfolgreich geladen wurde — Basis für die
  Alters-Anzeige im Baum und den Hintergrund-Auto-Refresher, siehe §4.8) und
  `characters` (ligenübergreifend) sowie `account_name`.
- **In-Memory-Pendant:** `MainWindow` hält dieselbe Form bereits zur
  Laufzeit (`self._stash_trees`, `self._items`) — der Datei-Cache ist
  einfach ein Snapshot davon. Ein Liga-Wechsel prüft zuerst, ob die Liga
  schon bekannt ist (aus dieser Session ODER vom letzten Programmstart
  wiederhergestellt) und zeigt sie dann **sofort** an, während im
  Hintergrund trotzdem ein `FetchStashListJob` zur Bestätigung/Aktualisierung
  läuft (`_activate_stash_tree`) — der Aufrufer kann Live- und Cache-Daten
  nicht unterscheiden, dieselbe Rendering-Logik bedient beide.
- **Schreiben:** bei jeder relevanten Änderung (`_on_stash_list`,
  `_on_stash_items`, `_on_characters`) wird der volle Snapshot synchron neu
  geschrieben — bewusst keine Debounce-/Thread-Komplexität für diesen
  Datenumfang (siehe FALLSTRICKE_UND_WORKAROUNDS.md #9 falls das je zum
  Performance-Problem wird).
- **"Aktualisieren" räumt den Item-Cache NICHT mehr leer:** Seit es
  Refresh-Buttons je Tab gibt, ist ein globales Verwerfen aller Items
  unnötig — der globale Refresh aktualisiert nur noch Stash-Liste und
  Charaktere.

#### 4.7.1 Ein Status-/Alters-Symbol statt zwei getrennter Spalten

`StashTree` hat bewusst nur EINE Zusatzspalte statt vormals zwei (Nutzer-
Feedback: "wir benötigen im Stash-Tree nur entweder das Download-Symbol
oder das Refresh-Symbol") — die beiden Zustände schließen sich pro Tab
gegenseitig aus: **entweder** "⬇" (noch nie geladen, reiner Text) **oder**,
sobald mindestens einmal geladen, ein Refresh-Button, dessen Beschriftung
zugleich das Alter der Daten trägt ("⟳ heute", "⟳ vor 3d",
`stash_tree.format_age()`). Das spart eine Spalte UND macht auf einen Blick
sichtbar, welche Tabs mal wieder dran wären.

### 4.8 Hintergrund-Auto-Refresh (`MainWindow._maybe_auto_refresh`)

Ein `QTimer` im Main-Thread (alle `AUTO_REFRESH_INTERVAL_MS` = 20 s) lädt
im Hintergrund höchstens **einen** bereits bekannten, aber veralteten
Stash-Tab neu — der Nutzer muss dafür nichts tun, alte Daten "verwesen"
aber nicht auf unbestimmte Zeit (Nutzer-Feedback).

**Auswahl (`_pick_auto_refresh_candidate`):**

1. Kandidaten sind alle Tabs der **aktuell angezeigten Liga**, die entweder
   **noch nie geladen wurden** ODER deren letzter Ladezeitpunkt
   **mindestens `AUTO_REFRESH_MIN_AGE` (1 Tag)** zurückliegt — jüngere,
   bereits bekannte Daten fasst der Hintergrund-Worker nicht an ("man weiß
   ja, was man getan hat", Nutzer-Feedback). Noch nie geladene Tabs gelten
   als "unendlich alt" (`MainWindow._NEVER_LOADED`) und sind IMMER
   Kandidaten — die 1-Tag-Schonfrist gilt nur für bereits bekannte Daten,
   bei einem leeren Tab gibt es nichts zu schonen. So füllt sich der
   gesamte Stash über die Zeit von selbst, ohne dass jeder Tab einzeln
   angeklickt werden muss (z. B. bei 391 Tabs).
2. Tabs, deren Name `"Remove-only"` enthält, werden **nachrangig**
   behandelt — sie kommen nur dran, wenn es sonst keinen anderen
   Kandidaten gibt.
3. Aus den verbleibenden Kandidaten gewinnt der mit dem **ältesten**
   Ladezeitpunkt (noch nie geladene Tabs gewinnen dabei immer gegen jeden
   bereits bekannten, auch sehr alten Tab).

**Budget-Schutz:** Vor jedem Auto-Refresh-Versuch prüft
`RateLimitManager.headroom_fraction()` (Minimum der "noch frei"-Anteile
über alle bekannten Policies/Regeln), ob mindestens
`AUTO_REFRESH_MIN_HEADROOM` (50 %) des Rate-Limit-Fensters frei sind —
sonst wird der Tick übersprungen. So bleibt dem Nutzer immer genug Budget
für eigene, manuelle Refreshs übrig. Zusätzlich pausiert der Auto-Refresher
komplett, während der Worker gerade mit etwas anderem beschäftigt ist
(`_worker_busy`) oder ein Bulk-Load ("Alle Tabs laden") läuft.

**Job läuft "silent":** `FetchStashItemsJob(..., silent=True)` unterdrückt
sowohl den Status-Text (`ApiWorker._dispatch`) als auch das Umschalten der
sichtbaren Item-Tabelle (`MainWindow._on_stash_items`) — der Nutzer merkt
vom Hintergrund-Refresh nichts außer der aktualisierten Alters-Anzeige im
Baum. Das Ergebnis-Signal `stash_items_loaded` trägt seit diesem Feature
die Liga explizit mit (nicht mehr implizit über `self._current_league`
zum Zeitpunkt des Eintreffens) — sonst könnte ein spät eintreffender
Hintergrund-Job Daten einer inzwischen verlassenen Liga in die aktuell
angezeigte Liga einsickern lassen.

**Sichtbarer Nachweis:** Ein permanentes Label rechts in der Statusleiste
("Auto-Refresh: X von Y Stash-Tabs aktualisiert",
`MainWindow._update_auto_refresh_label`) zählt die in dieser Session
still aktualisierten Tabs der aktuellen Liga gegen die Gesamtzahl der
Tabs — der Nutzer kann so jederzeit prüfen, dass der Hintergrund-Refresher
tatsächlich arbeitet (Nutzer-Feedback).

**Migration von Bestandsdaten:** Cache-Dateien von vor dem
`last_loaded`-Feature enthalten keine Zeitstempel — ohne Gegenmaßnahme
blieben alle bereits geladenen Tabs für immer als "nie geladen" (⬇)
markiert und für den Auto-Refresher unsichtbar (Cache-Treffer lösen keinen
Fetch aus und würden daher nie einen Zeitstempel nachtragen).
`data_cache._backfill_last_loaded()` vergibt beim Laden die mtime der
Cache-Datei als konservativen Ersatz-Zeitstempel (siehe
FALLSTRICKE_UND_WORKAROUNDS.md #12).

### 4.9 Rohdaten-Mini-Viewer (`ui/raw_data_viewer.py`)

Debug-/Inspektions-Werkzeug (Nutzer-Wunsch): Rechtsklick auf einen Stash-Tab
im Baum → Kontextmenü "🔍 Rohdaten anzeigen" → ein eigenständiges,
NICHT-modales Fenster (`RawDataViewer`, `Qt.WindowType.Window`) zeigt die
Tab-Daten als eingerücktes JSON.

- **Läuft parallel:** Da das Fenster nicht-modal ist, bleibt das
  Hauptfenster voll bedienbar — der Viewer blockiert nichts.
- **Folgt der Auswahl:** Einmal geöffnet, aktualisiert sich der Viewer bei
  JEDEM weiteren Tab-Wechsel automatisch (`MainWindow._update_raw_viewer`,
  aufgerufen aus `_show_items`) — ohne erneuten Rechtsklick. Das gilt
  sowohl für Klicks auf andere Tabs als auch für einen Refresh des gerade
  angezeigten Tabs. Nur `silent`-Hintergrund-Refreshs (§4.8) lösen bewusst
  KEIN Viewer-Update aus (dieselbe "silent lässt die Anzeige in Ruhe"-Regel
  wie bei Status-Text und Item-Tabelle).
- **Keine echten Rohdaten nötig:** Statt die HTTP-Response-Bytes gesondert
  zwischenzuspeichern, setzt `MainWindow._build_raw_stash_payload` die
  Tab-Metadaten (aus der bereits geladenen Stash-Liste) und die Items (aus
  dem Item-Cache) wieder zu einem Objekt zusammen. Das ist dank
  `extra="allow"` in allen pydantic-Modellen (`api/models.py`) verlustfrei
  — jedes Feld, das die API sendet (auch unbekannte/zukünftige), übersteht
  den Pydantic-Roundtrip. Spart einen weiteren Persistenz-Layer, der nur
  für diesen Debug-Viewer existieren würde.

### 4.10 Spezial-Tabs: MapStash & UniqueStash

Spezial-Tabs verhalten sich am Einzel-Tab-Endpunkt grundlegend anders als
normale Tabs: Die Antwort enthält **`children` statt `items`** — ein
Unter-Tab pro Map-Typ (MapStash) bzw. pro Unique-Kategorie (UniqueStash).
Die Items eines Unter-Tabs kommen ausschließlich vom
**Substash-Endpunkt** `/stash/<liga>/<eltern_id>/<kind_id>`
(`PoeApiClient.get_stash(league, stash_id, parent_id=...)`).

**Entdeckungs-Fluss (selbstorganisierend):**

1. In der Liga-Stash-LISTE sieht ein MapStash wie ein normaler Tab aus
   (keine children) → er zählt als Leaf und ist klick-/auto-refreshbar.
2. Sein erster Abruf liefert children → der Worker erkennt das
   (`_emit_stash_result`: children und keine items) und emittiert
   `stash_children_loaded` statt `stash_items_loaded`; jedes Kind bekommt
   dabei `parent` gesetzt (die API füllt das Feld nicht immer).
3. `MainWindow._on_stash_children` verankert die Kinder im Liga-Baum
   (`_stash_trees`), hängt sie per `StashTree.set_children()` unter den
   Knoten (OHNE Baum-Neuaufbau — Aufklapp-Zustand bleibt) und berechnet
   `_leaf_stashes` neu: Der Spezial-Tab ist jetzt Container (wie ein
   Ordner), seine **Kinder sind die ladbaren Einheiten** — mit eigenen
   ⬇/⟳-Markern, Refresh-Buttons, Cache-Einträgen und Zeitstempeln, exakt
   wie normale Tabs. Auto-Refresh (§4.8) und "Alle Tabs laden" arbeiten
   dadurch automatisch auch die Unter-Tabs ab (via `stash.parent`).
4. Klick auf ein Kind → `FetchStashItemsJob(..., parent_id=...)` →
   Substash-Endpunkt → Items wie gewohnt.

**Merge-Pflicht beim Listen-Refresh:** Die Liga-LISTE kennt die Kinder von
Spezial-Tabs NICHT. Ohne Gegenmaßnahme würde jeder Listen-Refresh (Liga-
Wechsel, "Aktualisieren") die bereits entdeckten Kinder wieder verwerfen —
`MainWindow._merge_known_children()` überträgt sie deshalb in jede frisch
geladene Liste, bevor sie den alten Baum ersetzt.

---

## 5. UI-Konzept (Oberflächenvorschlag)

Ein Hauptfenster: Navigation links (Charaktere + Stash getrennt), Items
rechts, Dashboard unten. (Interaktives HTML-Mockup: siehe Artifact-Link im
Projektverlauf / `docs/ui-mockup.html` — zeigt noch den ursprünglichen
gemeinsamen Baum, die textliche Beschreibung unten ist aktuell.)

```
┌────────────────────────────────────────────────────────────────────────┐
│  PoE-VIEW2                                              [– □ ✕]        │
├────────────────────────────────────────────────────────────────────────┤
│ Datei   Account   Ansicht   Hilfe                                      │
├────────────────────────────────────────────────────────────────────────┤
│ [🔑 Login] [⟳ Aktualisieren]  Liga: [Settlers ▾]   🔍 [Item-Filter…  ] │
├──────────────────────┬─────────────────────────────────────────────────┤
│ Charaktere            │ ITEMS — "Currency 1"          (142 Items)       │
│  MeinChar (91)        ├──────┬────────────┬─────────┬──────┬──────┬─────┤
│  Zweitchar (67)       │ Icon │ Name       │ Typ     │ Lvl  │ Qual │ Stk │
│ Stash                 ├──────┼────────────┼─────────┼──────┼──────┼─────┤
│  ▪ Currency 1  ⟳heute │ [ø]  │ Divine Orb │ Currency│  –   │  –   │ 12  │
│  ▪ Currency 2      ⬇  │ [◆]  │ Awakened…  │ Gem     │  5   │ 20%  │  1  │
│  📁 Gems              │ [▣]  │ Chaos Orb  │ Currency│  –   │  –   │ 843 │
│    ▪ Leveling  ⟳vor 3d│ …    │            │         │      │      │     │
│  📁 Maps              │      │ (Spalten sortierbar, Filter oben)        │
│  ▪ Uniques         ⬇  ├──────┴────────────┴─────────┴──────┴──────┴─────┤
│                       │ ITEM-DETAIL                                     │
│                       │ ┌────┐  Awakened Multistrike Support            │
│                       │ │IMG │  Gem · Level 5 · Quality +20%            │
│                       │ └────┘  Requires Level 72 · corrupted           │
├──────────────────────┴─────────────────────────────────────────────────┤
│ RATE-LIMIT   Policy: stash-request-limit                                │
│ [████████░░░░░░░] 8/15 (15 s)   [██░░░░░░░░░░░░░] 12/90 (300 s)  ● OK  │
│ Warte: – s                                                              │
├─────────────────────────────────────────────────────────────────────────┤
│ Bereit · Eingeloggt als PeterM · Not affiliated with Grinding Gear Games│
└─────────────────────────────────────────────────────────────────────────┘
```

**Elemente & Verhalten:**

| Bereich | Widget | Verhalten |
|---|---|---|
| Navigation: Charaktere | `CharacterList` (`QListWidget`) | Bewusst KEIN Tree — Charaktere haben keine Unterstruktur (Nutzer-Feedback: spart eine Ebene samt Auf-/Zuklapp-Klick). Flach, absteigend nach Level, liga-gefiltert (`MainWindow._apply_character_league_filter`, siehe §5.1). Höhe begrenzt (`setMaximumHeight`), damit der Stash-Baum den meisten Platz bekommt. |
| Navigation: Stash | `StashTree` (`QTreeWidget`), 2 Spalten, **Header sichtbar** | Kein umschließender "Stash"-Wurzelknoten mehr — die Tabs SIND die Top-Level-Einträge (spart eine weitere Ebene). Ordner rekursiv (children). Namensspalte per `QHeaderView.ResizeMode.Interactive` (NICHT `Stretch` — Stretch-Spalten lassen sich in Qt nicht per Maus verbreitern, das war ein echter Bug) mit großzügiger Startbreite, per Header-Rand manuell nachziehbar. Tab-Farbe aus API als kleines Icon-Quadrat VOR dem Namen, bewusst NICHT als Textfarbe (manche API-Farben sind auf dunklem Grund sonst unlesbar). Klick auf Tab → `FetchStashItems`-Job, sofern nicht bereits im Cache. Spalte 2 zeigt GENAU EINEN der beiden sich gegenseitig ausschließenden Zustände (§4.7.1): **⬇**-Text, solange nie geladen, oder ein **⟳-Button mit Alters-Beschriftung** ("⟳ vor 3d") sobald mindestens einmal geladen — Klick lädt genau diesen Tab bewusst AM Cache vorbei neu (`stash_refresh_requested`-Signal). Rechtsklick öffnet ein Kontextmenü mit "🔍 Rohdaten anzeigen" (`raw_data_requested`-Signal, §4.9) — öffnet/aktualisiert den nicht-modalen Rohdaten-Mini-Viewer. |
| Item-Tabelle rechts oben | `QTableView` + `QSortFilterProxyModel` | Spalten: Icon, Tab, Name, Typ, Level, Quality, Stack, iLvl. Klick auf Spaltenkopf sortiert; Suchfeld filtert live über Name+Typ+Tab (kein API-Call — gefiltert wird lokal). |
| Item-Detail rechts unten | eigenes Widget | Großes Icon, Name in Rarity-Farbe (frameType), Properties, Mods. Aktualisiert bei Zeilenauswahl. |
| Rate-Limit-Dashboard | `QProgressBar` pro Regel + Status-LED + Countdown | Wird ausschließlich über das Signal `rate_limit_changed` gefüttert. Farbe: grün < 60 %, gelb < 90 %, rot ab 90 %/Wartephase. Countdown zeigt verbleibende Wartezeit. *Intention: Der User soll immer sehen, WARUM die App gerade wartet.* |
| Statusbar | `QStatusBar` + `QProgressBar` (busy) | Login-Status, laufender Job, permanenter GGG-Disclaimer. Die `QProgressBar` läuft mit `setRange(0, 0)` im "busy"-Modus (Qt animiert das eingebaut, kein eigener Timer nötig). Sichtbarkeit hängt am eigenen `busy_changed`-Signal des Workers (`True` rund um jeden Job), NICHT am `status`-Text — siehe §4.5.1 zur Begründung. |

**"Alle Tabs laden" (Bulk) und CSV-Export:** Über den Toolbar-Button "⇊ Alle
Tabs laden" holt der `ApiWorker` (`FetchAllItemsJob`) die Items sämtlicher
Nicht-Ordner-Tabs der aktuellen Liga sequenziell — jeder Tab durchläuft
denselben Rate-Limit-Check wie eine Einzelabfrage, ein `QProgressDialog`
zeigt Fortschritt (`bulk_progress`-Signal) und erlaubt Abbrechen nach dem
aktuellen Tab (`ApiWorker.cancel_bulk()`). Nach Abschluss zeigt die
Item-Tabelle alle geladenen Tabs zusammen (`MainWindow._show_aggregate`) —
dafür trägt jede Zeile in der neuen **Tab-Spalte** ihren Herkunfts-Tab, damit
der Bezug beim Filtern/Sortieren über den gesamten Stash nicht verloren geht.
Der Toolbar-Button "💾 CSV exportieren" schreibt die aktuell sichtbaren
(gefilterten) Zeilen — egal ob Einzeltab oder Aggregat — über
`services/csv_export.py` als Semikolon-CSV mit UTF-8-BOM (Excel/de-DE-kompatibel).
Der Speicherdialog startet im echten Windows-Downloads-Ordner
(`config.downloads_dir()`, per Registry ermittelt — respektiert eine vom User
verschobene Downloads-Location) und schlägt einen Dateinamen vor
(`MainWindow._default_export_filename`): **immer** die aktuelle Liga voran
(Items sind nie liga-übergreifend gültig), danach aktiver Item-Filtertext,
sonst der Name des Tabs bzw. "Alle Tabs" im Aggregat — z. B.
`poe-view2-Settlers-Chaos-Orb.csv` oder `poe-view2-Settlers-Alle-Tabs.csv`.

**Liga-Dropdown als einzige Quelle der Wahrheit:** Charaktere kommen von
`/character` ligenübergreifend, werden aber NICHT mehr im Baum nach Liga
gruppiert — stattdessen filtert `MainWindow._apply_character_league_filter`
lokal auf `char.league == aktuelle Liga`, gesteuert vom selben Dropdown, das
auch die Stash-Tabs bestimmt. Ein Wechsel zwischen Ligen ist bei Items/Stash
ohnehin nicht möglich; die Vereinheitlichung spart eine Baum-Ebene und macht
Charaktere/Stash konsistent liga-scoped (Nutzer-Feedback 2026-07-09).

**Rarity-Farben** (frameType → Textfarbe im Detail/Namen):
0 normal (weiß), 1 magic (blau), 2 rare (gelb), 3 unique (orange), 4 gem (türkis), 5 currency (gold).

---

## 6. Fehlerbehandlung & Robustheit

- **HTTP 401:** Token abgelaufen → Signal an UI → Login-Dialog anbieten.
- **HTTP 429:** Sollte durch den Rate-Limiter nie auftreten. Falls doch:
  `Retry-After`-Header respektieren, State als "gesperrt" markieren,
  Dashboard rot, einmaliger Retry. Vorfall loggen (Hinweis auf Parser-Lücke).
- **Netzwerkfehler:** Job schlägt fehl → `error`-Signal → nicht-modale
  Statusmeldung; kein automatischer Endlos-Retry.
- **Logging:** `logging`-Modul, Datei in `%LOCALAPPDATA%/PoE-VIEW2/logs/`.
  Alle Requests mit Policy-Headern loggen (Debug-Level) — Gold wert bei
  Rate-Limit-Analysen und später als Referenz für die LabVIEW-Portierung.

## 7. Security & Open Source

- Client-ID/Kontakt-E-Mail in `.env` (Vorlage: `.env.example`); `.env` steht
  in `.gitignore`. Als *public client* mit PKCE gibt es **kein** Client-Secret.
- Access-Token nur im Windows Credential Manager, nie auf Platte/im Repo.
- Disclaimer in UI (Statusbar + Über-Dialog) und README:
  *"This product isn't affiliated with or endorsed by Grinding Gear Games in any way."*
- Lizenz: MIT (siehe `LICENSE`).
- Die Kontakt-E-Mail für den User-Agent kommt ausschließlich aus der lokalen
  `.env` (`POE_CONTACT_EMAIL`) — sie steht nirgends im Repository.

## 8. Roadmap / Meilensteine

| # | Meilenstein | Inhalt | Definition of Done |
|---|---|---|---|
| M0 | Gerüst | Projektstruktur, config, Logging, leeres MainWindow | App startet, Fenster sichtbar |
| M1 | Auth | OAuth2 PKCE, Callback-Server, TokenStore | Login-Roundtrip liefert Profil-Namen |
| M2 | Rate-Limiter | Manager + Header-Parsing + Unit-Tests (Fixtures!) | Tests grün, inkl. Mehrfach-Regeln & Sperre |
| M3 | Daten | Client-Endpunkte + pydantic-Modelle + Worker | Charaktere & Stash-Liste im Log/CLI |
| M4 | UI-Basis | Tree, Tabelle, Dashboard verdrahtet | Tab anklicken → Items erscheinen, Dashboard live |
| M5 | Politur | Icons+Cache, Item-Detail, Filter/Sortierung, Disclaimer | v0.1-Release auf GitHub |

*Empfohlene Reihenfolge-Intention: Der Rate-Limiter (M2) kommt VOR den ersten
massenhaften API-Calls (M3+) — dieselbe Lektion wie im LabVIEW-Projekt.*
