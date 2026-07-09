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
│   │   └── token_store.py      # keyring-Wrapper
│   └── ui/
│       ├── main_window.py
│       ├── stash_tree.py
│       ├── item_table.py       # TableModel + SortFilterProxy
│       ├── item_detail.py
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
  `stash_items_loaded(stash_id, items)`, `icon_loaded(url, bytes)`,
  `error(job, message)`, `rate_limit_changed(...)`.
- Icon-Downloads bekommen **niedrige Priorität** (eigene Queue oder
  Prioritäts-Queue): Erst Daten, dann Bilder.

### 4.6 Icon-Cache (`services/icon_cache.py`)

- Cache-Ordner: `%LOCALAPPDATA%/PoE-VIEW2/icon-cache/`
- Dateiname = Hash der URL (URLs enthalten Query-Parameter/Sonderzeichen).
- Ablauf: Cache-Hit → sofort `QPixmap`; Miss → `FetchIcon`-Job → Signal → Anzeige.
- Icon-CDN-Downloads laufen ebenfalls über den Rate-Limiter (eigene, milde Policy).

---

## 5. UI-Konzept (Oberflächenvorschlag)

Ein Hauptfenster, drei Bereiche + Dashboard. (Interaktives HTML-Mockup: siehe
Artifact-Link im Projektverlauf / `docs/ui-mockup.html`.)

```
┌────────────────────────────────────────────────────────────────────────┐
│  PoE-VIEW2                                              [– □ ✕]        │
├────────────────────────────────────────────────────────────────────────┤
│ Datei   Account   Ansicht   Hilfe                                      │
├────────────────────────────────────────────────────────────────────────┤
│ [🔑 Login] [⟳ Aktualisieren]  Liga: [Settlers ▾]   🔍 [Item-Filter…  ] │
├──────────────────────┬─────────────────────────────────────────────────┤
│ NAVIGATION           │ ITEMS — "Currency 1"          (142 Items)       │
│                      ├──────┬────────────┬─────────┬──────┬──────┬─────┤
│ 👤 Charaktere        │ Icon │ Name       │ Typ     │ Lvl  │ Qual │ Stk │
│  ├ MeinChar (91)     ├──────┼────────────┼─────────┼──────┼──────┼─────┤
│  └ Zweitchar (67)    │ [ø]  │ Divine Orb │ Currency│  –   │  –   │ 12  │
│                      │ [◆]  │ Awakened…  │ Gem     │  5   │ 20%  │  1  │
│ 🗄 Stash (Ordner-Baum)│ [▣]  │ Chaos Orb  │ Currency│  –   │  –   │ 843 │
│  ├ 📁 Currency        │ …    │            │         │      │      │     │
│  │  ├ Currency 1  ◀──│      │ (Spalten sortierbar, Filter oben)        │
│  │  └ Currency 2     ├──────┴────────────┴─────────┴──────┴──────┴─────┤
│  ├ 📁 Gems            │ ITEM-DETAIL                                     │
│  │  └ Leveling       │ ┌────┐  Awakened Multistrike Support            │
│  ├ Maps              │ │IMG │  Gem · Level 5 · Quality +20%            │
│  └ Uniques           │ └────┘  Requires Level 72 · corrupted           │
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
| Navigation links | `QTreeWidget`, 3 Spalten, **Header sichtbar** | Zwei Wurzelknoten: *Charaktere* und *Stash*, beide **flach** (kein Liga-Level). Stash-Ordner rekursiv (children). Namensspalte per `QHeaderView.ResizeMode.Stretch` — nimmt den restlichen Platz ein und lässt sich per Header-Rand manuell nachziehen (behebt abgeschnittene Namen wie "KRN…"). Tab-Farbe aus API als kleines Icon-Quadrat VOR dem Namen, bewusst NICHT als Textfarbe (manche API-Farben sind auf dunklem Grund sonst unlesbar). Klick auf Tab/Char → `FetchStashItems`/`FetchCharacter`-Job. Bereits geladene Tabs kommen aus dem Speicher-Cache (kein erneuter API-Call, außer via "Aktualisieren"). Spalte 2: **⬇**-Marker, solange der Tab noch nicht geladen ist (`StashTree.mark_loaded`). Spalte 3: **⟳-Button** je Tab, lädt genau diesen Tab bewusst AM Cache vorbei neu (`stash_refresh_requested`-Signal). |
| Item-Tabelle rechts oben | `QTableView` + `QSortFilterProxyModel` | Spalten: Icon, Tab, Name, Typ, Level, Quality, Stack, iLvl. Klick auf Spaltenkopf sortiert; Suchfeld filtert live über Name+Typ+Tab (kein API-Call — gefiltert wird lokal). |
| Item-Detail rechts unten | eigenes Widget | Großes Icon, Name in Rarity-Farbe (frameType), Properties, Mods. Aktualisiert bei Zeilenauswahl. |
| Rate-Limit-Dashboard | `QProgressBar` pro Regel + Status-LED + Countdown | Wird ausschließlich über das Signal `rate_limit_changed` gefüttert. Farbe: grün < 60 %, gelb < 90 %, rot ab 90 %/Wartephase. Countdown zeigt verbleibende Wartezeit. *Intention: Der User soll immer sehen, WARUM die App gerade wartet.* |
| Statusbar | `QStatusBar` + `QProgressBar` (busy) | Login-Status, laufender Job, permanenter GGG-Disclaimer. Die `QProgressBar` läuft mit `setRange(0, 0)` im "busy"-Modus (Qt animiert das eingebaut, kein eigener Timer nötig) und ist sichtbar, solange das `status`-Signal des Workers etwas anderes als `"Bereit"` meldet (`MainWindow._on_status`) — deckt damit jeden laufenden Job inkl. Rate-Limit-Wartezeit ab. |

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
