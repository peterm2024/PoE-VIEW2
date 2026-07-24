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

#### 4.7.1 Status-/Alters-Symbol UND Item-Anzahl je eine eigene Spalte

`StashTree` hat drei Spalten: Name, **# (Item-Anzahl)** und Status.

Die Status-Spalte zeigt bewusst nur EINEN von zwei sich gegenseitig
ausschließenden Zuständen (Nutzer-Feedback: "wir benötigen im Stash-Tree
nur entweder das Download-Symbol oder das Refresh-Symbol"): **entweder**
"⬇" (noch nie geladen, reiner Text) **oder**, sobald mindestens einmal
geladen, ein Refresh-Button, dessen Beschriftung zugleich das Alter der
Daten trägt ("⟳ heute", "⟳ vor 3d", `stash_tree.format_age()`).

Die **#-Spalte** trägt die Item-Anzahl — ursprünglich stand die Zahl als
"(N Items)"-Text im Namen, das wurde als unübersichtlich empfunden
(Nutzer-Feedback). Quelle: entweder die tatsächlich geladene Anzahl
(`len(items)`, überschreibt alles andere) oder — bei noch nicht geladenen
Map-/Unique-Kindern — der API-Hinweis `metadata.items`, den GGG dort schon
vor dem eigentlichen Laden mitschickt. Gruppen- UND Ordner-Knoten zeigen
die Summe ihrer (bekannten) Kind-Anzahlen (`StashTree._refresh_ancestor_
totals`, rekursiv nach oben durchgereicht, sobald eine Zahl sich ändert).

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
5. Klick auf den ELTERN-Knoten (Struktur bekannt) →
   `MainWindow._show_special_parent_aggregate()`: zeigt die Items ALLER
   bereits geladenen Unter-Fächer zusammen, mit dem Fach-Namen
   ("Map (Tier 1)") in der automatisch eingeblendeten Tab-Spalte
   (Nutzer-Feedback); Statuszeile nennt "X Items aus N von M geladenen
   Unter-Fächern". Kein API-Call — was fehlt, holt der Auto-Refresher
   oder ein Klick aufs jeweilige Fach.

**Merge-Pflicht beim Listen-Refresh:** Die Liga-LISTE kennt die Kinder von
Spezial-Tabs NICHT. Ohne Gegenmaßnahme würde jeder Listen-Refresh (Liga-
Wechsel, "Aktualisieren") die bereits entdeckten Kinder wieder verwerfen —
`MainWindow._merge_known_children()` überträgt sie deshalb in jede frisch
geladene Liste, bevor sie den alten Baum ersetzt.

**Sektions-Gruppierung im Baum (nur Anzeige):** Ein Map-Stash kann 100+
Fächer haben — flach war das "uferlos" (Nutzer-Feedback). Der `StashTree`
gruppiert Map-Fächer deshalb nach `metadata.map.section` unter synthetische
Zwischenknoten: "Tier 1"–"Tier 16" (numerisch sortiert!), dann
"Unique Maps", dann "Special Maps" — jeweils mit Summen-Item-Zahl in der
**#-Spalte** (§4.7.1), nicht mehr im Namen (`group_map_children()` /
`grouped_leaf_label()`; Tier-Fächer heißen dort "Fach N" nach `map.index`,
Unique-/Special-Fächer nach `map.name`). Die Gruppenknoten tragen KEIN
`_DATA_ROLE` — nicht klick-/refreshbar, reine Ordnungshilfe. Die
Datenschicht (`_stash_trees`, `_leaf_stashes`, Cache, Auto-Refresh, Bulk)
bleibt bewusst flach; UniqueStash-Fächer (keine Sektions-Info) bleiben
auch in der Anzeige flach.

**Unique-Fächer werden nach dem ersten Item-Load "getauft":** Die API
liefert UniqueStash-Fächer völlig namenlos (nur `metadata.items` = Anzahl).
Sobald die Items eines Fachs erstmals geladen sind, bestimmt
`models.dominant_category()` per Mehrheitsentscheid die Item-Kategorie
("Two Handed Axe", "Ring", "Flask", …) und `MainWindow._stamp_category()`
schreibt sie als synthetischen Schlüssel `poeview_category` in die
Tab-Metadaten — damit landet sie im Datei-Cache und überlebt Neustarts;
der Baum-Knoten wird sofort umbenannt ("UniqueStash" → "Ring", Anzahl
steht separat in der #-Spalte). Der Auto-Refresher (§4.8) füllt die Namen
so über die Zeit von selbst auf.
Kategoriequelle (`models.item_category()`): Waffen nennen ihre Klasse als
erste Property (einziger Ort, wo die API sie direkt ausspricht), der Rest
läuft über die baseType-ENDUNG (endswith, nicht Substring — "Full
Ringmail" ist kein Ring!), Rüstungs-Properties als letzter Fallback →
"Body Armour". Der Rohdaten-Viewer (§4.9) filtert alle `poeview_*`-
Schlüssel heraus — er verspricht, die echte API-Antwort zu zeigen.

### 4.11 Anforderungs-Spalten, Spalten-Filter, liga-weite Suche

**Anf.Lvl / Str / Dex / Int kommen direkt von GGG — kein PoEDB nötig.**
Die Stash-API liefert bei ausrüstbaren Items ein `requirements`-Array
(gleiche Struktur wie `properties`); Cache-Analyse 2026-07-10: 17.449 von
28.138 gecachten Items tragen es. Dank `extra="allow"` lag es längst
verlustfrei im Datei-Cache — es musste nur angezeigt werden. Fallstricke
bei den Namen (`models.req_level()` / `req_attribute()`):

- Attribute erscheinen mal kurz ("Str"), mal lang ("Strength") — beide
  Varianten real beobachtet, werden normalisiert.
- Heist-Ausrüstung trägt `"Level {0} in {1}"` ("Level 2 in Any Job") —
  das ist ein **Job**-Level; `req_level()` vergleicht deshalb exakt auf
  `"Level"` statt per startswith.

**Numerische Sortierung (`NUMERIC_SORT_ROLE`):** Der Proxy sortiert über
eine UserRole, die für Zahlenspalten echte Floats liefert (erste Zahl im
Anzeigetext, "+20%" → 20.0; "–" → -inf, landet also ganz unten) und für
Textspalten den kleingeschriebenen Text. Vorher verglich Qt die
Anzeige-Strings: "113" < "56". `ItemFilterProxy.lessThan()` bricht
Gleichstände (z. B. mehrere "-inf" ohne iLvl, oder mehrere gleichnamige
Items) zusätzlich über die Zeilennummer im Quellmodell auf — sonst würde
ein Filter-Toggle (Typ-Checkbox, Spalten-Filter) zuvor ausgeblendete,
gleichwertige Items ans Ende werfen statt an ihre alte Position
zurückzuholen (Nutzer-Feedback, FALLSTRICKE #18).

**Spalten-Filter (Excel-artig, Nutzer-Feedback "20% Quality, iLvl <45"):**
Header-Rechtsklick zeigt oben ein Eingabefeld für die angeklickte Spalte
(`QWidgetAction`), Enter übernimmt. Ausdrücke: `>=20`, `<45`, `=Text`,
`!=…`, sonst Teilstring; numerisch wird verglichen, sobald Operand UND
Zelle eine Zahl hergeben. Aktive Filter markieren den Header mit 🔍
(`ItemFilterProxy.headerData`-Override), sind UND-verknüpft untereinander
und mit dem globalen Suchfeld, und die Statuszeile nennt Treffer/Gesamt.
Bewusst NICHT persistiert (wie in Excel: Filter sind Arbeitszustand).

**Liga-weite Suche (Nutzer-Feedback "fächerübergreifend"):** Tippen ins
Suchfeld schaltet die Tabelle auf ALLE gecachten Items der aktuellen Liga
um (Tab-Spalte = Herkunfts-Fach), Leeren des Felds kehrt zur vorher
gewählten Ansicht zurück (`_current_stash_id` als Rückkehrziel; Baum-Klick
während der Suche beendet sie ebenfalls). Liga-Wechsel zieht eine aktive
Suche auf die neue Liga um. Eingrenzen auf ein Fach: Baum-Klick oder
Spalten-Filter auf der Tab-Spalte. Ein eingebauter Clear-Button
(`setClearButtonEnabled`) leert das Feld per Klick auf das "x" am rechten
Rand.

Die globale Suche durchsucht Name/Typ/Tab/Mods **und Properties**
(Nutzer-Feedback: "nach Quantity gesucht, nur Chisel gefunden" — Map-
Attribute wie Item Quantity/Rarity/Pack Size/Map Drop Chance stecken NICHT
in `explicitMods`, sondern als eigene `properties`-Einträge, z. B.
`{"name": "Item Quantity", "values": [["+23%", 1]]}`; ohne deren Text im
Such-Haystack waren betroffene Maps nie über die Suche auffindbar).
**"\*" als Suchtext zeigt bewusst ALLES** — gedacht für den
Komplett-Export einer ganzen Truhe/Liga über den bestehenden CSV-Export
(`_visible_rows` exportiert ohnehin die aktuell sichtbaren/gefilterten
Zeilen). Technischer Haken: `QSortFilterProxyModel.setFilterFixedString`
escaped den Text intern für die interne Regex (`"*"` → `"\*"`), das
zurückgelesene `filterRegularExpression().pattern()` wäre also NIE der
Rohtext — `ItemFilterProxy` überschreibt `setFilterFixedString` deshalb,
um sich den unescapten Suchtext selbst zu merken.

**Lazy-Icon-Loading:** Aggregat-Ansichten (Suche, "Alle Tabs",
Spezial-Eltern) rufen `set_items(…, request_icons=False)` auf — Icons
werden erst angefordert, wenn Qt die Zeile tatsächlich malt
(`data()`/DecorationRole). Eifriges Anfordern würde bei ~15.000 Items
ebenso viele Icon-Jobs in die sequenzielle Worker-Queue schieben und
manuelle Klicks minutenlang hinter CDN-Fetches einreihen.

**Position-Spalte ("#3 (4, 7)", Nutzer-Feedback: "mehrere gleichnamige
Truhenfächer, z. B. Heist"):** Der Tab-NAME allein unterscheidet mehrere
gleichnamige Fächer nicht — die Position-Spalte zeigt zusätzlich die
1-basierte Position des Herkunfts-Tabs ("#3") sowie die Gitter-Koordinate
des Items darin (API-Felder `x`/`y` am Item, bisher ungenutzt trotz
`extra="allow"`). **NICHT** `StashTab.index` als Tab-Nummer verwenden —
Nutzer-Korrektur: der `index` bezieht sich auf die Position INNERHALB DER
LIGA, in der ein Tab ursprünglich angelegt wurde; beim Liga-Ende wandern
Fächer nach Standard und behalten dabei ihren alten `index`, mehrere
Fächer in Standard tragen also denselben Wert (FALLSTRICKE #21).
`MainWindow._tab_positions()` berechnet die Tab-Nummer stattdessen aus der
tatsächlichen, aktuellen Reihenfolge der API-Antwort (Position in
`_leaf_stashes`, 1-basiert durchnummeriert) — das ist die einzige
verlässliche Quelle, weil sie nicht von Liga-Historie kontaminiert ist.
Anders als die Tab-Spalte NICHT automatisch verwaltet — sie bleibt auch im
Einzelfach sichtbar (dort zeigt sie die Koordinate innerhalb des gerade
geöffneten Tabs) und ist ganz normal über das Header-Menü aus-/einblendbar.
Die Tab-Nummer wird an jeder `set_items()`-Aufrufstelle separat mitgegeben
(`ItemTableModel` führt dafür `_tab_indices` parallel zu `_sources`,
bereits 1-basiert) — MainWindows `_league_wide_items()` liefert sie für
Aggregat-/Suchansichten, `_show_items()`/`_show_special_parent_aggregate()`
je für Einzelfach bzw. Spezial-Tab-Kinder, jeweils über `_tab_positions()`.
Sortierung über `NUMERIC_SORT_ROLE` per eigenem Tupel-Schlüssel
`(Tab-Nr., x, y)` (Nutzer-Feedback: "#10" sortierte alphabetisch VOR
"#2") — unbekannte Werte als "-inf", konsistent mit den übrigen
Zahlenspalten.

**Baum-Hervorhebung bei Zeilenauswahl (Nutzer-Feedback, v. a. relevant bei
`*`):** `ItemTableModel` führt zusätzlich `_stash_ids` parallel zu
`_sources`/`_tab_indices` (an denselben Aufrufstellen mitgegeben —
`_show_items`, `_show_special_parent_aggregate`, `_league_wide_items`).
`MainWindow._on_row_selected` ruft darüber `StashTree.highlight_stash
(stash_id)` auf: klappt die nötigen Eltern-Ordner auf, setzt den Baum-
Fokus auf den Knoten und scrollt ihn ins Bild. Kritischer Punkt (Nutzer-
Feedback: "aufpassen, dass dadurch nicht automatisch die Suche geändert
wird") — `highlight_stash` nutzt bewusst `QTreeWidget.setCurrentItem`,
NICHT einen simulierten Klick: `itemClicked` (das Signal, an das
`stash_selected` gekoppelt ist) feuert laut Qt nur bei echten
Mausklicks, nicht bei programmatischen Selektionsänderungen — die
liga-weite Suche/Aggregat-Ansicht in der Item-Tabelle bleibt dadurch
garantiert unangetastet.

**Typ-Filter (8 Checkboxen neben dem Liga-Feld, `MainWindow.TYPE_FILTER_ENTRIES`,
Nutzer-Feedback — ursprünglich "Rarity-Filter" mit nur 4 Checkboxen, dann um
Gem/Currency/Divination Card sowie eine Sammel-Kategorie erweitert und
entsprechend umbenannt):** Normal/Magic/Rare/Unique/Gem/Currency/Div Card
(frameType 0–6) plus **"Sonstige"** (`theme.OTHER_TYPE = -1`, Pink) für
alles ohne eigene Kategorie — Quest, Prophecy, Relic, unbekannte
frameTypes (`item_table._type_key()` mappt jeden frameType auf sich selbst
oder auf `OTHER_TYPE`). Bewusst ohne Textlabel ("wären zu lang"),
stattdessen ist die Rand-/Füllfarbe der Checkbox selbst die Typ-Farbe
(`theme.RARITY_COLORS`, Pink aus `theme.TYPE_FILTER_COLOR` für "Sonstige"),
der Name steckt nur im Tooltip. Alle acht sind standardmäßig angehakt.
Abwählen versteckt NUR diese eine Kategorie
(`ItemFilterProxy.set_type_visible`), UND-verknüpft mit Text-/Spalten-Filtern.

### 4.12 Offline-Modus: GGG-Wartung/kein Netz überbrücken

Nutzer-Feedback vom Patchday/Liga-Start: "pathofexile.com is currently
down for maintenance" — die App war zu dem Zeitpunkt faktisch unbenutzbar,
obwohl der Datei-Cache (`data_cache.json`) längst Stash-Daten von vorher
enthielt. Ursache: Das Liga-Dropdown wurde ausschließlich vom LIVE-Signal
`leagues_loaded` befüllt; ohne Netzwerk kam dieses Signal nie an, also
blieb das Dropdown leer — der Cache war zwar da, aber unerreichbar, weil
kein UI-Pfad zu ihm führte.

**Erkennung (`api_worker._is_connectivity_issue`):** Unterscheidet
"wir sind offline" von echten Anwendungsfehlern, damit z. B. ein simpler
404 (falsch zusammengesetzter Substash-Pfad) NICHT fälschlich das
Offline-Banner auslöst:
- `httpx.TransportError` (DNS/Verbindung/Timeout) → immer Konnektivität.
- `ApiError` mit `status_code >= 500` → Server-/Wartungsfehler (502/503).
- `json.JSONDecodeError` → GGG liefert bei Wartung mitunter eine
  HTML-Seite mit HTTP 200 statt JSON; `resp.json()` scheitert dann.
- Alles andere (4xx, `AuthError`, …) bleibt ein normaler Fehler.

`ApiWorker.run()` fängt jede Job-Exception zentral ab: Konnektivitätsfehler
setzen `self._offline` und emittieren `offline_changed(bool)` — aber NUR
bei einer tatsächlichen Zustandsänderung (kein Signal-Spam bei mehreren
aufeinanderfolgenden Fehlversuchen). Jeder erfolgreiche Job setzt
`_offline` automatisch wieder zurück (`else`-Zweig von try/except) — der
Zustand heilt sich selbst, sobald GGG wieder erreichbar ist, ohne dass der
Nutzer etwas zurücksetzen müsste. **Silent-Jobs** (Hintergrund-Auto-Refresh,
§4.8) unterdrücken bei einem Konnektivitätsfehler bewusst das
`job_error`-Signal — bei stundenlanger Wartung würde sonst alle 20 s eine
Fehlermeldung den Status-Text (und damit gefühlt das Offline-Banner)
überschreiben; manuelle Klicks bekommen die Meldung weiterhin.

**Cache-first beim Start (`MainWindow._populate_cached_leagues`):** Das
Liga-Dropdown wird JETZT sofort nach dem Bau der UI aus
`self._stash_trees` (bereits aus dem Cache restauriert) befüllt —
komplett unabhängig davon, ob `BootstrapJob`/`FetchLeaguesJob` je eine
Antwort bekommen. Trifft später die LIVE-Ligenliste ein, ersetzt
`_on_leagues` das Dropdown wie bisher vollständig. Nebeneffekt: Gecachte
Stash-Daten sind jetzt sogar ohne gültiges Token durchsuch-/exportierbar
— ein Klick auf einen bereits geladenen Tab zeigt ihn aus
`self._items`, ganz ohne Netzwerk-Zugriff.

**Sichtbare Markierung:** Ein permanentes Banner in der Statusleiste
("📴 Offline — GGG nicht erreichbar, zeige zwischengespeicherte Daten",
`MainWindow._on_offline_changed`) — bewusst ein EIGENES Label, nicht der
transiente `_status_msg`, sonst würde die nächste "Lade …"-Meldung es
sofort wieder verdecken. Zusätzlich markiert `StashTree.set_offline(True)`
jeden bereits geladenen Tab im Baum: aus dem Refresh-Button "⟳ vor 3d"
wird "📴 vor 3d" (Tooltip erklärt, dass es Cache-Daten sind) — genau die
vom Nutzer gewünschte Kennzeichnung "dass das Truhenfach aus dem
Offline-Cache kommt". Nie geladene (⬇) Tabs bleiben unverändert, für sie
gibt es online wie offline nichts zu zeigen. Der Button bleibt klickbar —
ein Klick versucht trotzdem ein Neuladen und ist damit der Weg, wie die
App die Rückkehr aus der Wartung überhaupt bemerkt.

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
│ Stash          #  ⟳/⬇ ├──────┼────────────┼─────────┼──────┼──────┼─────┤
│  ▪ Currency 1  45 ⟳heu│ [ø]  │ Divine Orb │ Currency│  –   │  –   │ 12  │
│  ▪ Currency 2      ⬇  │ [◆]  │ Awakened…  │ Gem     │  5   │ 20%  │  1  │
│  📁 Gems              │ [▣]  │ Chaos Orb  │ Currency│  –   │  –   │ 843 │
│    ▪ Leveling  12 ⟳3d │ …    │            │         │      │      │     │
│  📁 Maps              │      │ (Spalten sortierbar, Filter oben)        │
│   🗂 Tier 6    58   ⬇ ├──────┴────────────┴─────────┴──────┴──────┴─────┤
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

**Toolbar-Kontextmenü deaktiviert:** `QMainWindow` bietet per Default ein
Rechtsklick-Kontextmenü über der Toolbar an, mit dem sich diese komplett
ausblenden lässt (`setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)`
am Fenster deaktiviert es). Ohne Menüleiste gäbe es dann keinen Weg mehr
zurück — Login, Refresh, Liga-Wahl, Typ-Filter und Suche wären komplett
verschwunden (Nutzer-Feedback: aus Versehen ausgelöst).

**Elemente & Verhalten:**

| Bereich | Widget | Verhalten |
|---|---|---|
| Navigation: Charaktere | `CharacterList` (`QListWidget`) | Bewusst KEIN Tree — Charaktere haben keine Unterstruktur (Nutzer-Feedback: spart eine Ebene samt Auf-/Zuklapp-Klick). Flach, absteigend nach Level, liga-gefiltert (`MainWindow._apply_character_league_filter`, siehe §5.1). Höhe begrenzt (`setMaximumHeight`), damit der Stash-Baum den meisten Platz bekommt. |
| Navigation: Stash | `StashTree` (`QTreeWidget`), 3 Spalten, **Header sichtbar** | Kein umschließender "Stash"-Wurzelknoten mehr — die Tabs SIND die Top-Level-Einträge (spart eine weitere Ebene). Ordner rekursiv (children), Map-Fächer zusätzlich nach Sektion gruppiert (§4.10). Namensspalte per `QHeaderView.ResizeMode.Interactive` (NICHT `Stretch` — Stretch-Spalten lassen sich in Qt nicht per Maus verbreitern, das war ein echter Bug) mit großzügiger Startbreite, per Header-Rand manuell nachziehbar. Tab-Farbe aus API als kleines Icon-Quadrat VOR dem Namen, bewusst NICHT als Textfarbe (manche API-Farben sind auf dunklem Grund sonst unlesbar). Klick auf Tab → `FetchStashItems`-Job, sofern nicht bereits im Cache. Spalte 2 (**#**) zeigt die Item-Anzahl (Nutzer-Feedback: eigene Spalte statt "(N Items)"-Text im Namen; Details §4.7.1). Spalte 3 zeigt GENAU EINEN von DREI sich gegenseitig ausschließenden Zuständen (§4.7.1, §4.12): **⬇**-Text, solange nie geladen; ein **⟳-Button mit Alters-Beschriftung** ("⟳ vor 3d") sobald mindestens einmal geladen — Klick lädt genau diesen Tab bewusst AM Cache vorbei neu (`stash_refresh_requested`-Signal); oder **📴** statt ⟳, solange GGG nicht erreichbar ist (Offline-Modus, §4.12) — derselbe Button, nur die Beschriftung ändert sich, ein Klick versucht trotzdem ein Neuladen. Rechtsklick öffnet ein Kontextmenü mit "🔍 Rohdaten anzeigen" (`raw_data_requested`-Signal, §4.9) — öffnet/aktualisiert den nicht-modalen Rohdaten-Mini-Viewer. |
| Typ-Filter (Toolbar, neben Liga) | 8× `QCheckBox` ohne Text | Normal/Magic/Rare/Unique/Gem/Currency/Div Card + "Sonstige" (§4.11) — Farbe des Käschchens = Typ-Farbe (Pink für "Sonstige"), Name nur im Tooltip. Alle acht standardmäßig an; Abwählen blendet nur diese eine Kategorie aus der Item-Tabelle aus. |
| Item-Tabelle rechts oben | `QTableView` + `QSortFilterProxyModel` | Spalten: Icon, Tab, **Position** ("#3 (4, 7)" — Tab-Index + Item-Koordinate, §4.11, unterscheidet gleichnamige Fächer), Name, Typ, Level, Quality, Stack, iLvl, **Anf.Lvl, Str, Dex, Int** (benötigter Level/Attribute aus dem `requirements`-Array der API, §4.11), **Mods** (explicitMods, v. a. Map-Modifikatoren; Tooltip zeilenweise). Klick auf Spaltenkopf sortiert — **numerisch** über `NUMERIC_SORT_ROLE` (echte Zahlen statt "113" < "56"-Stringvergleich, "–" ganz unten). Das Suchfeld sucht **fächerübergreifend über die ganze Liga**, durchsucht auch Item-Properties (z. B. "Item Quantity"), hat einen eingebauten Clear-Button, und zeigt bei `*` bewusst ALLES an — für den Komplett-Export einer Truhe/Liga (§4.11); zusätzlich je Spalte ein **Excel-artiger Filter-Ausdruck** (`>=20`, `<45`, `=Text`, Teilstring) über das Header-Rechtsklick-Menü, aktive Filter tragen 🔍 im Header. **Spalten per Rechtsklick auf den Header an-/abwählbar** (Nutzer-Feedback), Wahl persistiert in `%LOCALAPPDATA%/PoE-VIEW2/ui-settings.ini` (INI statt Registry — Datei-Ansatz, LabVIEW-portierbar); "Typ" ist default AUS (Rarity steckt bereits in der Namensfarbe). Die **Tab-Spalte wird automatisch verwaltet** und ist nicht im Menü: AUS bei Einzelfach-Auswahl (redundant), AN in Aggregat-Ansichten ("Alle Tabs", Spezial-Tab-Elternknoten, liga-weite Suche) — dort trägt sie die Fach-Herkunft ("Map (Tier 1)"). |
| Item-Detail rechts unten | eigenes Widget | Großes Icon, Name in Rarity-Farbe (frameType), Properties, Mods. Aktualisiert bei Zeilenauswahl. |
| Rate-Limit-Dashboard | `QProgressBar` pro Regel + Status-LED + Countdown | Wird ausschließlich über das Signal `rate_limit_changed` gefüttert. Farbe: grün < 60 %, gelb < 90 %, rot ab 90 %/Wartephase. Countdown zeigt verbleibende Wartezeit. *Intention: Der User soll immer sehen, WARUM die App gerade wartet.* |
| Statusbar | `QStatusBar` + `QProgressBar` (busy) | Login-Status, laufender Job, permanenter GGG-Disclaimer. Die `QProgressBar` läuft mit `setRange(0, 0)` im "busy"-Modus (Qt animiert das eingebaut, kein eigener Timer nötig). Sichtbarkeit hängt am eigenen `busy_changed`-Signal des Workers (`True` rund um jeden Job), NICHT am `status`-Text — siehe §4.5.1 zur Begründung. Ein permanentes **Offline-Banner** ("📴 Offline — GGG nicht erreichbar, zeige zwischengespeicherte Daten", §4.12) erscheint bei Konnektivitätsproblemen — als eigenes Label, damit die nächste "Lade …"-Statusmeldung es nicht überschreibt. |

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

**Sortierung/Gliederung des Liga-Dropdowns
(`MainWindow._rebuild_league_combo`, Nutzer-Feedback):** Gültige (Live-)
Ligen stehen oben, abgelaufene — nur noch im Datei-Cache vorhandene, von
GGG nicht mehr gelistete — Ligen darunter, per einer nicht-anwählbaren
Überschrift-Zeile ("── Beendete Ligen (nur Cache, kein Online-Zugriff) ──",
`_ARCHIVED_HEADER`, per `QStandardItem.setEnabled(False)` deaktiviert)
abgetrennt — bewusst KEIN blanker `insertSeparator`, damit für den Nutzer
explizit sichtbar ist, WARUM diese Ligen unten stehen ("als Offline-Liga
anhängen", Nutzer-Feedback), nicht nur eine positionelle Trennung.
Innerhalb der gültigen Ligen sortiert `_sort_by_content` die mit
tatsächlichem Spielstand (mindestens ein Charakter ODER bereits geladene
Items in dieser Liga) nach vorn: GGG legt pro Account automatisch leere
Hardcore-/Ruthless-Varianten an, ohne Sortierung landete der
Programmstart so zufällig auf einer komplett leeren Liga, nur weil die
API sie zuerst zurückgab ("Hardcore zuerst, alle Felder leer"). Der Sort
ist stabil — die relative Reihenfolge innerhalb "hat Inhalt"/"leer" bleibt
die der API bzw. (alphabetisch) des Caches. Ein Liga-Listen-Refresh
(`_on_leagues`) behält die aktuell ausgewählte Liga bei (`findText` auf
den bisherigen Text vor dem Neuaufbau) — bewusst OHNE `findText("")` bei
leerem Vorwert. Vor der ersten Live-Antwort (`live_leagues=None`,
Offline-Start §4.12) gilt der GESAMTE Cache als "oben", ohne Abtrennung —
wir wissen zu diesem Zeitpunkt noch nicht, was inzwischen abgelaufen ist.

**Archivierte Ligen: kein Online-Zugriff mehr (Nutzer-Feedback, Liga-Start
— die alte temporäre Liga ist beendet).** `MainWindow._live_leagues`
merkt sich die letzte `/account/leagues`-Antwort als Set;
`_current_league_is_archived()` prüft, ob die GERADE angezeigte Liga
darin fehlt (`None`, also vor der ersten Antwort, gilt NICHT als
archiviert — sonst würde ein Offline-Start jede gecachte Liga fälschlich
als tot markieren). Ist eine Liga archiviert, unterdrückt
`_archived_league_guard()` JEDEN Netzwerk-Versuch dafür und zeigt
stattdessen eine erklärende Statusmeldung — betrifft `_on_league_changed`
(kein `FetchStashListJob`), `_on_stash_selected`/`_on_stash_refresh`
(kein `FetchStashItemsJob`, auch nicht für unentdeckte Spezial-Tab-Kinder),
`_load_all_items` (zeigt nur den Cache-Aggregat, kein Bulk-Fetch),
`_refresh()` (kein Stash-Listen-Refresh, `/character` bleibt aber
liga-unabhängig sinnvoll) und `_maybe_auto_refresh` (kein Kandidat aus
einer archivierten Liga). Bewusst PRÄVENTIV statt "versuchen und Fehler
behandeln": unklar (und ohne Netzwerkzugriff in dieser Umgebung nicht
verifizierbar), ob GGG für eine tote Liga einen HTTP-Fehler liefert oder
still eine LEERE Erfolgsantwort — Letzteres würde beim bisherigen
Cache-Ersetzungs-Verhalten (`_on_stash_list` überschreibt `_stash_trees`
mit der Antwort) den kompletten gecachten Stand der toten Liga
unwiederbringlich löschen. Ein präventiver Verzicht auf den Versuch
vermeidet beide möglichen Ausfallarten gleichermaßen. `StashTree` zeigt
für die aktuell archivierte Liga dasselbe 📴 wie beim globalen
Offline-Modus (`_update_tree_offline_display` kombiniert beide
Bedingungen mit ODER) — der Refresh-Button bleibt klickbar, aber
`_on_stash_refresh` fängt den Klick vorher ab.

**Rarity-Farben** (frameType → Textfarbe im Detail/Namen, `theme.RARITY_COLORS`):
0 normal (weiß), 1 magic (blau), 2 rare (gelb), 3 unique (orange), 4 gem
(grün-türkis), 5 currency (gold), 6 divination card (blau-cyan), 9 relic
(grün). Gem/Divination Card bewusst mit deutlichem Hue-Abstand (Nutzer-Feedback:
die ursprünglichen Töne #3fb8ae/#0ebac5 waren nebeneinander kaum zu
unterscheiden) — Gem zieht Richtung Grün, Divination Card Richtung Blau.

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
