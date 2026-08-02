# PoE-VIEW2 — Architektur

PoE-VIEW2 ist eine Desktop-Anwendung, die über die offizielle GGG-API
Accounts, Charaktere und Stash-Tabs ausliest, filtert und darstellt.

Dieses Dokument beschreibt den Aufbau der Anwendung und begründet die
getroffenen Entscheidungen. Es richtet sich an Entwickler, die am Code
arbeiten oder ihn nachvollziehen wollen.

---

## 1. Ziele & Nicht-Ziele

**Ziele**

- Account-Login via OAuth2 (PKCE), Token-Verwaltung
- Charaktere und Stash-Tabs (inkl. verschachtelter Ordner) anzeigen
- Items mit ihren Eigenschaften tabellarisch darstellen, sortier- und filterbar
- Item-Icons anzeigen, mit lokalem Cache
- Striktes, für den Nutzer sichtbares Rate-Limit-Management (kein 429, kein Bann)
- Open-Source-tauglich: keine Secrets im Code, Disclaimer vorhanden

**Nicht-Ziele**

- Trade- und Preis-Funktionen, Markt-Anbindung
- Schreibende API-Zugriffe
- Mehrbenutzer- oder Serverbetrieb; PoE-VIEW2 ist eine lokale Desktop-App

---

## 2. Tech-Stack

| Bereich | Wahl | Begründung |
|---|---|---|
| GUI | **PySide6** (Qt 6) | Ausgereifte Tree-Views und Tabellen, Signale/Slots für die Thread-Kommunikation. LGPL-lizenziert und damit Open-Source-kompatibel. |
| HTTP | **httpx** (synchron) | Persistente Session mit festen Headern, Connection-Pooling. |
| Datenmodelle | **pydantic v2** | Validiertes JSON-Parsing mit `extra="allow"` für unbekannte API-Felder. |
| Nebenläufigkeit | **QThread-Worker + Qt-Signale** | Siehe 2.1. |
| Konfiguration | `.env` (optional, in `.gitignore`) | Überschreibt die Standardwerte in `config.py`. |
| Token-Speicherung | `keyring` (Windows Credential Manager) | Kein Klartext-Token auf der Platte. |

### 2.1 Threads statt asyncio

Die Entscheidung fiel bewusst gegen `asyncio`:

- Qt bringt einen eigenen Event-Loop mit. `asyncio` parallel zu betreiben
  erfordert eine Brücke wie `qasync` und damit eine zusätzliche
  Abhängigkeit samt Fehlerquelle.
- Die Anwendung setzt wenige, streng sequenzielle API-Calls ab.
  Parallelität ist wegen des Rate-Limits ohnehin nicht erwünscht, `asyncio`
  brächte also keinen praktischen Vorteil.

Daraus folgt: Die UI läuft im Main-Thread. Sämtliche API-Calls laufen in
einem einzigen Worker-Thread, der Aufträge aus einer Queue sequenziell
abarbeitet. Ergebnisse gehen per Qt-Signal zurück an die UI. Die
Oberfläche blockiert deshalb auch dann nicht, wenn der Rate-Limiter 60
Sekunden wartet.

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

Die API-Schicht ist dadurch ohne GUI testbar, auch offline mit
gespeicherten JSON-Antworten.

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
│   │   ├── rate_limiter.py     # RateLimitManager
│   │   └── models.py           # pydantic: Character, StashTab, Item, ItemProperty
│   ├── services/
│   │   ├── api_worker.py       # QThread + Job-Queue
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

Ablauf (erprobte Parameter siehe
[api-notes/ggg-api.md](api-notes/ggg-api.md)):

1. `code_verifier` (Zufallsstring), `code_challenge` (SHA-256, base64url) und
   `state` (64-Bit-Zufall, `%016x`) erzeugen.
2. Lokalen HTTP-Server auf `http://localhost:64338` starten (Standardbibliothek
   `http.server`, ein einziger Request) — Port 64338 ist als Redirect-URI der
   Client-Registrierung fest hinterlegt.
3. Browser mit der GGG-Authorize-URL öffnen (`webbrowser.open`).
4. Callback abfangen, `state` prüfen (CSRF-Schutz), `code` extrahieren,
   Erfolgsseite ausliefern, Server beenden.
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
    """Zentraler GET: erzwingt den Rate-Limit-Check vor und das
    State-Update nach jedem Request. Kein Endpunkt kann das umgehen."""
    self.rate_limiter.check_and_wait(policy_hint)
    resp = self._http.get(self.BASE_URL + path)
    self.rate_limiter.update_from_headers(resp.headers)
    if resp.status_code == 429:
        # Retry-After respektieren, genau einmal wiederholen
        ...
    resp.raise_for_status()
    return resp
```

- Endpunkte (v1): `get_profile()`, `get_leagues()`, `get_characters()`,
  `get_character(name)`, `get_stashes(league)`, `get_stash(league, stash_id)`.
- Liga-Namen können Leerzeichen enthalten (`SSF Ruthless`) → Pfadsegmente
  immer per `urllib.parse.quote` encoden.

### 4.3 Rate-Limit-Manager (`api/rate_limiter.py`)

Die zentrale Komponente der Anwendung: Sie verhindert HTTP 429 und die
daraus folgenden temporären Sperren. Threadsicher über `threading.Lock`
(aktuell greift nur ein API-Thread darauf zu, der Lock hält die
Anforderung dennoch fest).

**Datenmodell:**

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
    last_update: float          # Timestamp des letzten Header-Updates
```

**Header-Parsing.** Das Format ist hier explizit festgehalten, weil die
Zuordnung von Regel zu Verbrauch eine bekannte Fehlerquelle ist:

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
  Warte-Countdown über einen Callback nach außen. Der `ApiWorker`
  verbindet diesen Callback mit dem Qt-Signal
  `rate_limit_changed(policy, rules, wait_remaining_s)`, das wiederum das
  Dashboard speist. So bleibt der Manager selbst frei von Qt-Abhängigkeiten.
- `headroom_fraction()` — wie viel Budget ist über alle bekannten Policies
  hinweg noch frei (Minimum, konservativ)? Genutzt vom Auto-Refresh-Guard.
- `steady_pace_interval_s(policy_name=None)` — empfohlener Mindestabstand
  zwischen Requests für einen gleichmäßigen Dauerbetrieb (Single-/Stash-
  Refresh-Modus, §4.8): die knappste Regel der angegebenen (oder sonst
  zuletzt benutzten) Policy, geteilt auf ihr Fenster. Bewusst NICHT über
  alle Policies gemittelt — GGG vergibt pro Endpunkt-Art eine eigene
  Policy, siehe FALLSTRICKE #33. Der Nenner ist
  `max_hits - SAFETY_MARGIN - 1`, also eins WENIGER als die Schwelle, ab
  der `_required_wait` bremst: ein Takt, der die Schwelle exakt trifft,
  löst im Dauerbetrieb genau die Sperre aus, die er verhindern soll
  (FALLSTRICKE #34).
- `_log_header_detail(policy, state)` — schreibt bei jedem
  `update_from_headers` eine INFO-Zeile JE Regel mit den rohen Header-Werten
  (`current/max`, `window_s`, `lock_rest`) und dem gelernten Absenkungs-Takt
  (`letzte_absenkung_vor`, `takt`). Vorher stand im Log nur, DASS ein
  Request lief (httpx-Zeile), nie WAS der Header meldete — erst mit dieser
  Zeile ließ sich beweisen, dass GGGs Zähler blockweise statt gleitend
  sinkt (§4.8, FALLSTRICKE #45, Runde 6).
- `pacing_blocked(policy_name=None)` — harte Obergrenze für den
  gleichmäßigen Takt (Single-/Stash-Modus): `True`, sobald eine Regel
  schon voller ist als `PACING_FILL_LIMIT` (0.85) ihrer Bremsschwelle.
  Ergänzt `steady_pace_interval_s()`, das für sich genommen nicht reicht:
  der berechnete Takt unterstellt ein leeres Fenster und sich selbst als
  einzigen Verbraucher, während ungetaktete Requests (Klicks,
  Liga-Wechsel, Programmstart) dasselbe Kontingent mitfüllen
  (FALLSTRICKE #47).
- `snapshot()` — aktueller Anzeige-Stand ohne Seiteneffekt auf einen
  echten Request, fürs periodische UI-Polling (siehe unten).
- `_decay_expired_rules(state)` — setzt abgelaufene Fenster lokal zurück,
  auch OHNE dass ein neuer Request das anstößt. Wird von `check_and_wait`,
  `headroom_fraction` und `snapshot` gleichermaßen genutzt — sonst könnte
  eine Auto-Refresh-Pause sich über veraltete Zähler selbst
  aufrechterhalten (FALLSTRICKE #32). Der 1-Sekunden-UI-Timer in
  `MainWindow` ruft `snapshot()` bei jedem Tick ab, damit das Dashboard
  auch ohne laufende Requests sichtbar mitläuft.

### 4.4 Datenmodelle (`api/models.py`)

pydantic-Modelle mit `extra="allow"` (die API liefert mehr Felder, als wir
modellieren — nichts geht verloren, nichts bricht bei API-Erweiterungen):

- `Character`: name, class_, level, league, experience, …
- `StashTab`: id, name, type, index, colour (`#rrggbb` → via `QColor` in der UI),
  `children: list[StashTab]` (rekursiv — Ordner!), `items: list[Item]`
- `Item`: id, name, typeLine, baseType, icon (URL), frameType (Rarity),
  `properties: list[ItemProperty]`, sockets, …
- `ItemProperty`: name, `values: list[tuple[str, int]]`

**`explicitMods`/`implicitMods`: Einträge können String oder Objekt sein.**
GGG liefert für manche Items, etwa Currency-Beschreibungstexte, einzelne
Mod-Einträge als `{"description": "..."}`-Objekt statt als String. Ohne
Gegenmaßnahme scheitert die pydantic-Validierung für den gesamten
Stash-Tab, nicht nur für das betroffene Item. Ein
`field_validator(mode="before")` auf `Item` reduziert jeden dict-Eintrag
vor der Typprüfung auf sein `description`-Feld; Strings bleiben
unverändert (siehe FALLSTRICKE_UND_WORKAROUNDS.md #25).

**Gem-Level und Quality** haben keine festen JSON-Keys, sondern liegen im
`properties`-Array. Dafür gibt es dokumentierte Helper:

```python
def get_property(item: Item, prop_name: str) -> str | None:
    """Sucht eine Property per Name; der Wert steckt in values[0][0].

    Die API hat keine festen Keys für Level oder Quality, beide liegen
    als Einträge im 'properties'-Array. Quality kommt als '+20%'.
    """
```

### 4.5 API-Worker (`services/api_worker.py`)

Ein `QThread` mit Job-Queue:

- Jobs sind kleine Objekte: `FetchCharacters`, `FetchStashList(league)`,
  `FetchStashItems(league, stash_id)`, `FetchIcon(url)`, `Login` und weitere.
- Der Worker arbeitet die Queue **sequenziell** ab. Ein Request nach dem
  anderen hält den Rate-Limiter einfach und deterministisch.
- Ergebnisse/Fehler per Signal: `characters_loaded`, `stash_list_loaded`,
  `stash_items_loaded(league, stash_id, name, items, silent)` (die Liga
  reist explizit im Signal mit, siehe FALLSTRICKE_UND_WORKAROUNDS.md #10),
  `icon_loaded(url, bytes)`, `error(job, message)`, `rate_limit_changed(...)`.
- Icon-Downloads bekommen **niedrige Priorität** (eigene Queue oder
  Prioritäts-Queue): Erst Daten, dann Bilder.
- **Daten-Jobs laufen nur mit gesetztem Token.** `_skip_unauthenticated()`
  verwirft alles aus `_NEEDS_AUTH`, solange `client.has_token` False ist
  (Bootstrap/Login stellen die Anmeldung selbst her, Logout und der
  CDN-Icon-Download brauchen keine). Grund: `_build_ui()` reiht beim Start
  einen `FetchStashListJob` mit ein, noch bevor feststeht, ob überhaupt
  ein gültiges Token existiert — ohne diesen Guard ging der ohne
  `Authorization`-Header raus und kassierte einen garantierten 401
  (FALLSTRICKE #35). Passend dazu verwirft der `AuthError`-Handler das
  gespeicherte Token nur, wenn es auch mitgeschickt wurde: ein 401 ohne
  Token ist selbstverschuldet und sagt nichts über dessen Gültigkeit aus.

#### 4.5.1 Status-Text vs. Busy-Zustand — zwei getrennte Signale

`status(str)` trägt den Verlaufstext ("Lade Items: Currency 1 …"),
`busy_changed(bool)` steuert ausschließlich den Spinner. Die Trennung hat
einen konkreten Grund.

*Ursprünglicher Fehler:* `_dispatch()` sendete am Ende jedes Jobs
`status.emit("Bereit")`. Qt verarbeitet Cross-Thread-Signale auf dem
Main-Thread in der Reihenfolge des Absendens, deshalb traf dieses "Bereit"
stets nach `stash_items_loaded` ein und überschrieb die spezifischere
Meldung "Currency 1: 45 Items" sofort wieder. Auffällig war das nur bei
Tabs aus dem Netz; bei einem Cache-Treffer folgte kein "Bereit", das den
Text hätte verdrängen können.

*Lösung:* `run()` sendet `busy_changed(True/False)` per `try/finally` um
jeden Job, unabhängig von dessen Inhalt. `status.emit("Bereit")` bleibt
den Jobs vorbehalten, deren Ergebnis-Signal in der UI keinen eigenen
Abschlusstext setzt (Ligen, Charaktere, Stash-Liste). Jobs mit eigenem
Abschlusstext (`FetchStashItemsJob`, `FetchAllItemsJob`) senden es nicht.

#### 4.5.2 Job-Reihenfolge beim Start

`MainWindow.__init__` reiht `BootstrapJob()` vor dem Aufruf von
`self._build_ui()` ein, nicht danach. Der Grund (FALLSTRICKE #30):
`_build_ui()` ruft zuletzt `_populate_cached_leagues()` auf, das bei
vorhandenem Cache sofort `_on_league_changed()` und damit
`worker.submit(FetchStashListJob(liga))` auslöst.

Da der `ApiWorker` seine Queue strikt nach FIFO abarbeitet, liefe dieser
Job vor dem Bootstrap, wenn der Bootstrap erst danach eingereiht würde,
und zwar mit einem `PoeApiClient` ohne gesetztes Token. GGG antwortet mit
HTTP 401, woraufhin der `AuthError`-Handler das gespeicherte, tatsächlich
noch stundenlang gültige Token löscht. Der unmittelbar folgende Bootstrap
findet dann kein Token mehr vor. Ergebnis wäre ein überflüssiger Neu-Login
bei praktisch jedem Start mit gecachter Liga.

`submit()` ist reine Queue-Einreihung und funktioniert bereits vor
`worker.start()`. Maßgeblich ist die Reihenfolge der `submit()`-Aufrufe,
nicht die der umgebenden Funktionsaufrufe.

### 4.6 Icon-Cache (`services/icon_cache.py`)

- Cache-Ordner: `%LOCALAPPDATA%/PoE-VIEW2/icon-cache/`
- Dateiname = Hash der URL (URLs enthalten Query-Parameter/Sonderzeichen).
- Ablauf: Cache-Hit → sofort `QPixmap`; Miss → `FetchIcon`-Job → Signal → Anzeige.
- Icon-CDN-Downloads laufen ebenfalls über den Rate-Limiter (eigene, milde Policy).

### 4.7 Persistenter Daten-Cache (`services/data_cache.py`)

Charaktere, Stash-Struktur und bereits geladene Items überstehen einen
Neustart. Als Speicher dient eine JSON-Datei
(`%LOCALAPPDATA%/PoE-VIEW2/data-cache.json`) statt einer Datenbank; der
Datenumfang von einigen hundert Items rechtfertigt keine.

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

`StashTree` hat vier Spalten: Name, **# (Item-Anzahl)**, Status und
**Pos.**

Die Status-Spalte zeigt genau einen von zwei sich gegenseitig
ausschließenden Zuständen: entweder "⬇" als reinen Text, solange der Tab
nie geladen wurde, oder, sobald er mindestens einmal geladen wurde, einen
Refresh-Button, dessen Beschriftung zugleich das Alter der Daten trägt.
Heute geladene Tabs erscheinen mit exakter lokaler Uhrzeit
("⟳ 14:32:46"), ältere mit Tagesangabe ("⟳ vor 3d",
`stash_tree.format_age()`). Ursprünglich stand dort pauschal "heute", was
jeden Auto-Refresh innerhalb desselben Tages unsichtbar machte
(FALLSTRICKE #29); die sekundengenaue Uhrzeit macht jeden 40-Sekunden-Tick
des Live-Refresh (§4.8) nachvollziehbar.

Die **#-Spalte** trägt die Item-Anzahl. Zuvor stand die Zahl als
"(N Items)" im Namen, was die Namensspalte unübersichtlich machte. Als
Quelle dient entweder die tatsächlich geladene Anzahl (`len(items)`, die
alles andere überschreibt) oder bei noch nicht geladenen Map- und
Unique-Kindern der API-Hinweis `metadata.items`, den GGG bereits vor dem
Laden mitschickt. Gruppen- und Ordner-Knoten zeigen die Summe ihrer
bekannten Kind-Anzahlen (`StashTree._refresh_ancestor_totals`, rekursiv
nach oben durchgereicht, sobald sich eine Zahl ändert).

Die **Pos.-Spalte** (2026-07-26) zeigt die 1-basierte Position eines Fachs
in der echten Truhen-Reihenfolge, geliefert von
`MainWindow._tab_positions()`. Peter fehlte ein Zeilenheader zum
"Durchzählen der echten Truhenfächer", wie ihn `QTableView` (ItemList) mit
seinem `verticalHeader()` hat — `QTreeView` kennt dieses Konzept nicht,
die Pos.-Spalte ist das Äquivalent dafür. `MainWindow` übergibt die
Positionen bei jedem Rendern (`set_stashes`, `set_children`) explizit mit;
`_stash_trees` muss dabei schon den neuen Stand tragen. Ordner- und
Gruppenknoten belegen keinen eigenen Truhenplatz und bleiben leer.

**Gezählt wird die Truhen-Leiste, nicht `_leaf_stashes`.** Die beiden
Listen beantworten verschiedene Fragen, und die Verwechslung war ein
echter Fehler: `_leaf_stashes` sind die ladbaren EINHEITEN, dort fällt ein
Map-/Unique-Eltern-Tab heraus (Container) und seine Sektionen sind die
Einträge. Direkt daraus nummeriert bekamen genau diese Spezial-Tabs gar
keine Position, während jede ihrer Sektionen eine verbrauchte und alle
folgenden Fächer verschob. In Peters echtem Cache ergab das für Standard
923 statt der tatsächlichen 391 Positionen — ein einziger Map-Stash belegte
dort 271 davon. `_tab_positions()` läuft deshalb über `_stash_trees` und
zählt, was in der Leiste einen Platz belegt; die Sektionen eines
Spezial-Tabs erben dessen Nummer, damit auch Items aus ihnen den richtigen
Truhenplatz anzeigen.

#### 4.7.2 Namensspalte nach Datenalter abgeblendet

Zusätzlich zum Alters-Text im Status-Button färbt `StashTree._apply_age_color`
die Namensspalte jedes geladenen Fachs ein: unter 1 Stunde normale
Textfarbe ("aktuell"), unter 3 Stunden leicht Richtung Hintergrund
gemischt, älter deutlicher (`_blend`, Faktoren 0.35 / 0.6). Bewusst kein
fest codierter Grauton (Peters ursprüngliche Idee war "Weiß/Hellgrau/
Dunkelgrau") — stattdessen wird die tatsächliche Theme-Textfarbe
(`QPalette.ColorRole.Text`) zur tatsächlichen Hintergrundfarbe
(`QPalette.ColorRole.Base`) hin gemischt, damit es auf hellem wie dunklem
Theme lesbar bleibt. Nie geladene Fächer sowie reine Ordner-/
Gruppenknoten (kein Zeitstempel) bleiben unangetastet.

Da das Alter auch ohne neue Daten weiterwandert, ruft
`MainWindow._update_auto_refresh_countdown` (der ohnehin laufende
Sekunden-Tick, §4.8) zusätzlich `StashTree.refresh_age_colors()` auf —
kein eigener Timer nötig.

Zusätzlich bekommt das zuletzt per `StashTree.mark_loaded()`
aktualisierte Fach Türkis statt der normalen Alters-Farbe
(`_mark_just_updated`) — sichtbar, welches Fach ein automatischer Sweep
(Refresh-Modus Single/Stash, §4.8) gerade angefasst hat, ohne im
40-Sekunden-Countdown danach suchen zu müssen. Es gibt immer höchstens
eine Türkis-Markierung; ein weiterer `mark_loaded()`-Aufruf lässt sie zum
neuen Fach wandern, das vorherige fällt auf seine reguläre Alters-Farbe
zurück. `set_stashes()` (Liga-Wechsel/Neustart) setzt die Markierung
zurück, da ein Fach aus der vorherigen Liga sonst irreführend wäre.

### 4.8 Hintergrund-Auto-Refresh (`MainWindow._maybe_auto_refresh`)

Ein `QTimer` im Main-Thread lädt alle `AUTO_REFRESH_INTERVAL_MS` (40 s)
im Hintergrund bis zu zwei Stash-Tabs neu, ohne Zutun des Nutzers:

1. **Das gerade angezeigte Fach ODER der gerade angezeigte Charakter**
   (`MainWindow._current_stash_id` bzw. `_current_character_name`, beide
   schließen sich gegenseitig aus — siehe §4.13) — IMMER, unabhängig vom
   Alter (die 1-Tag-Schonfrist des Sweeps unten gilt hier nicht), damit
   die aktuell geöffnete Ansicht "lebt". Ist die
   Aggregat-/Alle-Tabs-Ansicht aktiv, sind beide `None` und dieser Schritt
   entfällt. Charaktere haben KEINEN eigenen Sweep (siehe §4.13) — nur
   das gerade offene Fach ODER der gerade offene Charakter wird hier
   behandelt, nie beide gleichzeitig.
2. **Der normale Sweep-Kandidat** (`_pick_auto_refresh_candidate`, siehe
   unten) — füllt nach und nach den Rest der Truhe. Ist er identisch mit
   dem gerade angezeigten Fach, wird er nicht doppelt angefragt.

**Korrektur (FALLSTRICKE #27):** Ein stiller (`silent=True`) Treffer für
GENAU das gerade offene Einzelfach zeichnet inzwischen auch die sichtbare
Tabelle neu (`MainWindow._on_stash_items` prüft zusätzlich
`stash_id == self._current_stash_id`) — ursprünglich aktualisierte der
Live-Refresh nur den Cache/die Alters-Anzeige im Baum, nicht die Tabelle
selbst, "lebte" also gar nicht sichtbar. Ein stiller Treffer für ein
ANDERES Fach (der Sweep-Kandidat) oder während einer Aggregat-/Such-
Ansicht bleibt weiterhin unangetastet.

Da pro Tick jetzt bis zu zwei statt einem Job rausgeht, wurde
`AUTO_REFRESH_INTERVAL_MS` verdoppelt (20 s → 40 s) — die
Gesamt-Anfragerate ans Rate-Limit bleibt damit wie vorher, sonst würde ein
Tick den Worker-Thread in `RateLimitManager.check_and_wait` in eine
Warteschleife (Timeout) laufen lassen.

**Auswahl (`_pick_auto_refresh_candidate`):**

1. Kandidaten sind alle Tabs der **aktuell angezeigten Liga**, die entweder
   **noch nie geladen wurden** ODER deren letzter Ladezeitpunkt
   **mindestens `AUTO_REFRESH_MIN_AGE` (1 Tag)** zurückliegt — jüngere,
   bereits bekannte Daten fasst der Hintergrund-Worker nicht an ("man weiß
   ja, was man getan hat"). Noch nie geladene Tabs gelten
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
`AUTO_REFRESH_MIN_HEADROOM` (10 %) des Rate-Limit-Fensters frei sind —
sonst wird der Tick übersprungen. Nur eine kleine Notreserve, kein
50/50-Splitting: Auto- und manuelle Jobs laufen ohnehin durch dieselbe
FIFO-Queue und werden vom Rate-Limiter gleich gedrosselt, die Reserve
verhindert lediglich, dass ein manueller Klick ausgerechnet den letzten
freien Request vor einer 429-Sperre wegschnappt. Zusätzlich pausiert der Auto-Refresher
komplett, während der Worker gerade mit etwas anderem beschäftigt ist
(`_worker_busy`) oder ein Bulk-Load ("Alle Tabs laden") läuft — und
solange `MainWindow._logged_in` `False` ist (FALLSTRICKE #28: ein mitten
in der Session abgelaufener Token führte sonst dazu, dass JEDER Tick
erneut mit dem bereits als ungültig bekannten Token gegen die API lief —
real im Log beobachtet über mehrere Minuten alle 40s in Folge HTTP 401,
bis der Nutzer den Login-Button von Hand bemerkte). `_on_login_required`
setzt das Flag auf `False`, `_on_logged_in` wieder auf `True`.

Dasselbe Flag sperrt über `_update_online_controls_enabled()` auch die
Toolbar-Aktionen "⟳ Refresh", "⇊ Load All Tabs" und den
Refresh-Modus-Umschalter, solange kein Login besteht (FALLSTRICKE #46).
Ohne dieses Gate blieben sie anklickbar, weil der Daten-Cache Liga,
Charakterliste und Stash-Baum auch ohne Login sichtbar hält
(`_restore_cached_data`, §4.7) — ein Klick auf "Load All Tabs" öffnete
dann den Fortschrittsdialog, der zugehörige Job wurde vom Worker aber
lautlos verworfen (`ApiWorker._skip_unauthenticated`) und der Dialog hing
für immer bei 0 %. Bewusst NICHT gesperrt: Stash-Baum, Charakterliste,
Liga-Auswahl und "💾 Export CSV" — sie arbeiten mit bereits geladenen bzw.
gecachten Daten und sollen offline durchsuchbar bleiben.

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
("Auto-refresh: X of Y stash tabs updated",
`MainWindow._update_auto_refresh_label`) zählt die in dieser Session
still aktualisierten Tabs der aktuellen Liga gegen die Gesamtzahl der
Tabs — der Nutzer kann so jederzeit prüfen, dass der Hintergrund-Refresher
tatsächlich arbeitet. Gezählt wird pro Fach nur der **erste** stille
Ladevorgang DIESER SESSION (`_count_silent_refresh` führt ein eigenes,
NICHT persistiertes Session-Set `_auto_refresh_counted` je Liga) — bewusst
nicht anhand von `_last_loaded` (das überlebt Neustarts über den
Datei-Cache): Bei einer bereits vollständig heruntergeladenen Liga wäre
`already_loaded` für jeden Tab von Anfang an wahr, der Zähler bliebe dann
für immer bei 0 stehen, obwohl der Sweep sichtbar weiterläuft
(FALLSTRICKE #31).

**"Y" ist die Zahl echter Truhenplätze, nicht `len(_leaf_stashes)`.**
`_leaf_stashes` beschreibt die ladbaren EINHEITEN (§4.7.1) — für Map-/
Unique-Stashs zählt das jede Sektion einzeln, obwohl sie in der
Truhen-Leiste EIN Fach sind. `_update_auto_refresh_label` zählt "Y"
deshalb als `len(set(self._tab_positions().values()))` (eindeutige
Truhenplätze), und `_count_silent_refresh` dedupliziert "X" über
denselben Platz (`_tab_positions(league).get(stash_id, stash_id)`) statt
über die rohe `stash_id` — sonst zählen zwei Sektionen desselben Map-Tabs
als zwei aktualisierte "Tabs" (real beobachtet: "939" statt 391
tatsächlicher Fächer, FALLSTRICKE #36). `_tab_positions()` akzeptiert dafür
einen optionalen `league`-Parameter, da `_count_silent_refresh` mit der
Liga AUS DEM SIGNAL rechnet, nicht zwangsläufig der aktiven (FALLSTRICKE #10).

**Sekündliche Countdown-Anzeige** (`MainWindow._update_auto_refresh_countdown`,
per `QTimer` unabhängig vom 40s-Auto-Refresh-Takt) zeigt zusätzlich
entweder "Next auto-refresh in Xs" (`_auto_refresh_timer.remainingTime()`)
oder den Grund, warum der nächste Tick nichts täte
(`_auto_refresh_blocked_reason()` — no league, busy, not logged in, league
ended, rate limit budget) — Countdown-Text und tatsächliches Verhalten
teilen sich dieselbe Guard-Methode, damit sie nie auseinanderlaufen.
Derselbe Timer-Tick ruft auch `RateLimitManager.snapshot()` ab und füttert
damit das Rate-Limit-Dashboard, unabhängig von echten Requests (siehe
§4.3, FALLSTRICKE #32).

**Refresh-Modus (`MainWindow._drive_refresh_mode`):** Ein Dropdown in der
Toolbar ("Mode: Auto / Single / Stash / Pause", additiv neben dem normalen
"Refresh"-Button) schaltet zwischen vier Strategien um:

- **Auto** — das oben beschriebene Verhalten (Standard).
- **Single** — hält ausschließlich die aktuell gewählte Zeile (Fach oder
  Charakter, `_pick_single_target`) aktuell, im Takt von
  `steady_pace_interval_s()`.
- **Stash** — zyklisiert endlos durch die ganze Truhe der aktuellen Liga,
  gefüllte Fächer (Items > 0) vor leeren (`_pick_stash_mode_candidate`), im
  selben Takt. Sonst würde ein einmal als leer bekanntes Fach nie wieder
  geprüft, selbst wenn es inzwischen gefüllt wurde: sobald eine
  vollständige Runde durch alle AKTUELL gefüllten Fächer durch ist
  (`_stash_mode_round_picks` erreicht deren Anzahl), hängt sich EIN
  zusätzlicher Pick für das nächste noch leere Fach an, danach beginnt die
  Zählung neu. Bewusst kein fester Anteil (z. B. "jeder 10. Pick") —
  die Häufigkeit passt sich automatisch an die Truhengröße an (bei 5
  gefüllten Fächern alle 5 Picks eins, bei 80 gefüllten alle 80). Der
  Rundlauf durch die leeren Fächer (`_stash_mode_coverage_cursor`, ein
  Listen-Index) folgt dabei der FÄCHERREIHENFOLGE, nicht dem Alter:
  verschiebt der Nutzer im Spiel ein Fach weiter nach vorne, rückt es in
  `_leaf_stashes` ebenso weiter nach vorne und ist dadurch schneller wieder
  dran — mit Alter als Kriterium hätte diese Absicht keine Wirkung gehabt.
  Keine Sonderbehandlung nach Position (z. B. "die vordersten 10 immer
  frisch") — das soll später über eine Favoriten-Markierung gelöst werden,
  nicht über einen festen Index (Peter: stört sich an starren Positionen).

  Derselbe Rundenabschluss löst zusätzlich `_stash_mode_list_refresh_due`
  aus: der nächste Tick lädt (`_drive_refresh_mode`) statt eines weiteren
  Item-Picks einmalig die Fach-**Liste** still nach (`FetchStashListJob(...,
  silent=True)`, ausgewertet in `_on_stash_list`). Grund: Auto/Single/Stash
  aktualisieren sonst ausschließlich Items einzelner Fächer — verschiebt,
  benennt oder entfernt der Nutzer ein Fach im Spiel, bliebe das unsichtbar,
  bis er manuell auf "⟳ Refresh" klickt oder die Liga wechselt (Peters
  Rückfrage "Bekommen wir das mit?"). Läuft auch dann mit, wenn gerade kein
  einziges Fach leer ist — sonst bliebe eine komplett bekannte, aber
  umsortierte Truhe für immer unentdeckt. Kein fester Zeit-Takt: derselbe
  Rundenmechanismus wie beim Leer-Fach-Coverage-Pick, damit die Häufigkeit
  ebenso mit der Truhengröße skaliert, und dieselbe Rate-Limit-Policy wie
  Item-Abrufe (`stash-request-limit`, real bestätigt — anders als bei
  Charakteren gibt es hier KEINE getrennte Listen-Policy), also derselbe
  Budget-Topf.

  **Remove-only-Fächer** (`MainWindow._is_remove_only_tab`, Namensmuster
  wie bei §4.10) fallen, sobald einmal geladen, aus dem normalen Rundlauf
  der gefüllten Fächer raus (Peter, 2026-08-02: "da hier niemals neue
  Items hinzukommen und nur herausgenommen werden können") — sie kommen
  nur noch dran, wenn es sonst KEIN anderes gefülltes Fach gibt. Das
  bestimmt auch die Rundenlänge: sie zählen nicht mehr zu den Picks, nach
  denen der Coverage-/Listen-Refresh-Tick fällig wird. Vor dem ersten
  Laden sind sie von einem normalen leeren Fach nicht zu unterscheiden
  (`item_counts` kennt sie noch nicht) und laufen ganz regulär im
  Leer-Fach-Rundlauf mit — dieselbe Nachrangigkeit gilt schon länger für
  `_pick_auto_refresh_candidate` im Auto-Modus (oben), war für den
  Stash-Modus aber ein offener ToDo-Punkt.

- **Pause** — gar keine Hintergrund-Anfragen (Peter, 2026-07-30). Weder die
  Takt-Kette (Single/Stash) noch der 40s-Timer (Auto) feuern; manuelle
  Klicks, die ⟳-Buttons im Baum und "Load All Tabs" funktionieren
  unverändert und bekommen das volle Rate-Limit-Budget. Gedacht für den
  Fall, dass jemand das Budget bewusst freihalten will — etwa während
  parallel ein anderes PoE-Tool läuft oder nach einer Zwangspause. Die
  Umsetzung ist bewusst ein zusätzlicher Modus im vorhandenen Dropdown
  statt eines eigenen An/Aus-Schalters: die vier Zustände schließen sich
  gegenseitig aus, ein separater Schalter hätte widersprüchliche
  Kombinationen ("Stash-Modus AN, aber pausiert") möglich gemacht.
  `STEPPING_REFRESH_MODES` (= Single/Stash) hält die Unterscheidung
  "treibt sich selbst im Takt weiter" an einer Stelle; alle Guards, die
  vorher `!= "auto"` prüften, fragen jetzt diese Menge ab.

  Das Rate-Limit-Dashboard bekommt beim Umschalten in "Pause" sofort ein
  `(Paused)` neben dem Policy-Namen (`RateLimitDashboard.set_paused`,
  Peter 2026-07-30: "Wenn ich den Pause-Mode aktiviere verbleibt der
  Policy-Status unverändert"). Der Hinweis ist ein dauerhaft gemerkter
  Zustand in `RateLimitDashboard`, kein einmaliges `setText`: der ohnehin
  laufende Sekunden-Tick ruft `update_state` unabhängig vom Refresh-Modus
  auf (§_update_auto_refresh_countdown) und würde einen einmaligen Text
  sofort wieder überschreiben.

  **Die Verbrauchszahl ist der rohe, zuletzt gemeldete GGG-Wert — ohne
  Glättung.** Das war nicht immer so: fünf Runden lang (2026-07-30,
  FALLSTRICKE #45) wurde versucht, den Verbrauch zwischen zwei Requests
  gleitend "herunterzurechnen", zuerst pauschal-linear, dann exakt pro
  eigenem Treffer plus gemessenem Takt für den Rest. Auslöser war die
  berechtigte Beobachtung, dass der Wert bis zum vollen Fensterablauf
  stehen blieb und dann abrupt auf 0 sprang (`_decay_expired_rules`,
  weiterhin bewusst konservativ für die reale Warte-Entscheidung,
  FALLSTRICKE #34/#32). Die Annahme dahinter — GGGs Fenster altere
  gleitend, jeder Treffer falle genau `window_s` nach SEINEM Zeitpunkt
  einzeln heraus — erwies sich anhand echter Header-Logs
  (`RateLimitManager._log_header_detail`, siehe unten) als **falsch**:

  > Frische Session, 30/300s-Regel, keinerlei Altlast: der Zähler stieg im
  > ~11s-Takt sauber von 1 bis 27, blieb dann stehen und sprang **um 4-5 auf
  > einmal** — 11 solcher Sprünge im Abstand von durchschnittlich **59,7s**.
  > Ein einzelner Treffer kann unmöglich nach 65 Sekunden aus einem
  > 300s-Fenster fallen; GGG zählt diese Regel offenbar in **~5 Blöcken à
  > ~60s** (300 ÷ 5 = 60, und 60s ÷ 11s ≈ 5,4 Treffer passen exakt zu den
  > beobachteten Sprunggrößen), nicht gleitend pro Einzeltreffer.

  Die Konsequenz: `RateLimitRule.current` wird jetzt unverändert
  weitergereicht, kein Interpolieren mehr zwischen zwei Headern. Das ist
  nicht nur einfacher, sondern auch ehrlicher — der alte Ansatz hat ein
  falsches Modell fünf Runden lang immer genauer ausgebaut, statt die
  Grundannahme infrage zu stellen. `PolicyState.request_times`,
  `RateLimitRule.observe_unknown`/`drain_s`, `RateLimitManager.
  window_coverage()` und der Sync-Balken im Dashboard sind ersatzlos
  entfernt — sie modellierten alle dasselbe, jetzt widerlegte
  Gleitfenster-Verhalten.

  **`next_free_s` schätzt stattdessen den gelernten Block-Rhythmus.**
  `RateLimitRule.observe()` merkt sich JEDE beobachtete Absenkung
  (unabhängig von ihrer Größe) und lernt daraus den Abstand zwischen zwei
  Absenkungen (`drop_interval_s`). Ab der zweiten Beobachtung ergibt sich
  eine grobe Vorhersage: letzte Absenkung + gelernter Abstand − jetzt. Das
  ist explizit KEINE Zusage für einen bestimmten Treffer (das war die
  falsche Prämisse der Vorgänger-Rundem), sondern der Durchschnittstakt der
  Absenkungen selbst — im Dashboard deshalb immer mit `~` markiert
  (`12/30 · 300 s · next in ~0:52`). Ohne zwei beobachtete Absenkungen
  bleibt der Wert `None`, statt geraten zu werden — genau wie die
  ursprüngliche Motivation für dieses Feld: eine völlig normale Ruhephase
  soll nicht wie ein Hänger aussehen (Peter, 2026-07-30). An echten
  Header-Logs verifiziert: die Vorhersage läuft sauber auf 0 herunter und
  trifft den realen Sprung auf die Sekunde genau.

Single/Stash reservieren kein FESTES Budget für manuelle Klicks (anders
als Auto) — der Nutzer hat den Modus bewusst gewählt, um den Pool für
genau dieses Ziel einzusetzen. Eine Obergrenze gibt es trotzdem:
`rate_limiter.pacing_blocked()` stoppt den Takt, sobald das Fenster
ohnehin schon zu voll ist (§4.3, FALLSTRICKE #47). Ohne sie taktete der
Modus stur weiter, während ungetaktete Requests (Klicks auf ungeladene
Fächer, Liga-Wechsel, Programmstart) dasselbe Kontingent mitfüllten — die
Restmarge des berechneten Takts beträgt genau EINEN Treffer und war damit
sofort weg; real endete das in 289s Zwangspause. Die Pause steht im
Countdown-Label ("waiting for rate-limit headroom") statt eines bei 0s
hängenden Countdowns. Beide takten GLEICHMÄSSIG statt in
einem Burst, ausgelöst vom selben 1-Sekunden-Timer wie der Countdown
(`_refresh_mode_next_due`, ein `time.monotonic()`-Zeitstempel) — ein
Burst-dann-Warten hätte denselben Gesamtdurchsatz, sähe aber minutenlang
aus wie "nichts passiert" (für einen einmaligen Sofort-Burst gibt es
bereits "Load All Tabs"). Der Takt selbst kommt aus
`RateLimitManager.steady_pace_interval_s(self._refresh_mode_policy)` —
`_refresh_mode_policy` ist der beim EIGENEN letzten Job gemerkte
Policy-Name, nicht der globale `rate_limiter.last_policy`, der von jedem
beliebigen (auch fremden) Request überschrieben werden kann
(FALLSTRICKE #33). **Wird bei Liga- und Modus-Wechsel bewusst NICHT
zurückgesetzt** (FALLSTRICKE #48): die Policy einer Fach-Anfrage hängt am
Endpunkt-Typ, nicht an der Liga, ein Reset würfe `pacing_blocked()`/
`steady_pace_interval_s()` bis zum ersten Job der neuen Liga wieder auf
den kontaminierbaren globalen Fallback zurück — real beobachtet direkt
neben einem `FetchStashListJob` mit ANDERER Policy, der `_last_policy`
kurz zuvor überschrieben hatte.

Ein Liga-Wechsel selbst kann ebenfalls zur Fensterfülle beitragen:
`_on_league_changed` löst neben dem sofortigen Refresh-Modus-Tick auch
`FetchStashListJob(league)` aus, um die (evtl. veraltete) gecachte
Fach-Liste zu bestätigen. Bei mehreren schnellen Wechseln hintereinander
entfällt dieser Abruf, sobald `pacing_blocked("stash-list-request-limit")`
meldet, dass auch DIESES (von `stash-request-limit` getrennte) Fenster
schon zu voll ist — der gecachte Baum bleibt trotzdem sofort sichtbar, ein
späterer Auto-Sweep oder manueller Refresh bestätigt die Liste nach.

Die Fälligkeit des nächsten Takts setzt `_note_refresh_mode_job_done()`
beim EINTREFFEN der Antwort, nicht `_drive_refresh_mode()` beim Absenden.
Wartet der Rate-Limiter mitten im Job minutenlang (`check_and_wait`), wäre
eine beim Absenden gesetzte Fälligkeit längst abgelaufen und der nächste
Pick feuerte sofort hinterher — real hat sich daraus eine endlose Kette
aus 300s-Sperren aufgeschaukelt (FALLSTRICKE #34). Derselbe Handler
bedient alle drei Abschluss-Pfade (Fach, Charakter, Fehler), damit auch
ein Fehlschlag keinen Sofort-Retry auslöst.

Ein bewusster Auswahlwechsel bei einem Cache-Treffer löst KEINEN eigenen
Request aus. Das angeklickte Fach wird stattdessen als nächstes Ziel
vorgemerkt (`_prioritise_selection_in_refresh_mode` →
`_refresh_mode_priority_id`, einmalig) und beim nächsten regulären Takt
zuerst geladen. Eine frühere Fassung übersprang den Takt und lud sofort;
das war ein Extra-Request neben dem gleichmäßigen Takt und hat mit dazu
beigetragen, das Rate-Limit-Fenster auf die Sperrschwelle zu treiben
(FALLSTRICKE #34). Der konservative Weg kostet bis zu einen Takt
Wartezeit (~11s bei 30/300s), hält die Anfragerate dafür unabhängig vom
Klickverhalten konstant. Für Charaktere braucht es gar keine Vormerkung:
der Single-Modus zielt ohnehin immer auf die aktuelle Auswahl
(`_pick_single_target`).

**Migration von Bestandsdaten:** Cache-Dateien von vor dem
`last_loaded`-Feature enthalten keine Zeitstempel — ohne Gegenmaßnahme
blieben alle bereits geladenen Tabs für immer als "nie geladen" (⬇)
markiert und für den Auto-Refresher unsichtbar (Cache-Treffer lösen keinen
Fetch aus und würden daher nie einen Zeitstempel nachtragen).
`data_cache._backfill_last_loaded()` vergibt beim Laden die mtime der
Cache-Datei als konservativen Ersatz-Zeitstempel (siehe
FALLSTRICKE_UND_WORKAROUNDS.md #12).

#### 4.7.3 Kontextmenü: Alle öffnen/schließen

Dasselbe Kontextmenü trägt zusätzlich "▸ Expand All"/"▾ Collapse All"
(`StashTree._on_context_menu`, `QTreeWidget.expandAll`/`collapseAll`) —
anders als "🔍 View Raw Data" nicht an ein bestimmtes Fach gebunden,
sondern gilt für den ganzen Baum und steht deshalb IMMER zur Verfügung,
auch bei Rechtsklick auf einen Ordner oder in den leeren Bereich
unterhalb der letzten Zeile. Bei über 100 Fächern in tief verschachtelten
Ordnern (Map-/Unique-Sektionen, §4.10) wäre Knoten-für-Knoten-Aufklappen
sonst mühsam.

### 4.9 Rohdaten-Mini-Viewer (`ui/raw_data_viewer.py`)

Debug-/Inspektions-Werkzeug: Rechtsklick auf einen Stash-Tab
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
  ; Statuszeile nennt "X Items aus N von M geladenen
   Unter-Fächern". Kein API-Call — was fehlt, holt der Auto-Refresher
   oder ein Klick aufs jeweilige Fach.

**Merge-Pflicht beim Listen-Refresh:** Die Liga-LISTE kennt die Kinder von
Spezial-Tabs NICHT. Ohne Gegenmaßnahme würde jeder Listen-Refresh (Liga-
Wechsel, "Aktualisieren") die bereits entdeckten Kinder wieder verwerfen —
`MainWindow._merge_known_children()` überträgt sie deshalb in jede frisch
geladene Liste, bevor sie den alten Baum ersetzt. Auf **Ordner** wird dabei
nicht gepfropft (`elif not stash.is_folder`): die füllt `_nest_folder_members`
aus der Liste selbst, ein leerer Ordner ist also echt leer — sonst kämen im
Spiel herausgezogene Fächer wieder zurück.

**Ordner kommen flach (§`_nest_folder_members`, FALLSTRICKE #38):** Anders als
das Beispiel in `docs/api-notes/ggg-api.md` nahelegt, liefert GGG die Fächer
eines Ordners nicht im `children`-Array des Ordners, sondern als eigene
Einträge auf oberster Ebene, erkennbar allein am gesetzten `folder`-Feld
(echte Standard-Liga: 121 von 165 Einträgen). Ohne Umformung stünden sie im
Baum oben statt im Ordner und schöben sich zwischen die echten Fächer — die
Reihenfolge wich dadurch sichtbar von der im Spiel ab. `_nest_folder_members()`
hängt sie unter ihren Ordner und läuft an **beiden** Eintrittspunkten: in
`_on_stash_list` vor dem Merge und beim Cache-Laden (`_load_cache`), damit
bestehende Caches ohne Listen-Refresh geheilt werden. Kennt ein Ordner ein
Mitglied bereits, ersetzt der frische Eintrag den alten und übernimmt dessen
entdeckte Unter-Tabs — das beseitigt Dubletten, die vorher entstanden, wenn
ein Ordner sowohl flach als auch gepfropft im Baum hing. Die Zählsemantik
(§4.7.1, `_tab_positions()`) bleibt unberührt: jedes echte Fach behält genau
eine Nummer, Ordner selbst bekommen keine.

**Sektions-Gruppierung im Baum (nur Anzeige):** Ein Map-Stash kann 100+
Fächer haben — flach war das "uferlos". Der `StashTree`
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

**GGG-Suffixe im `name`-Feld gelten NICHT als "schon echt benannt"**
(`models.is_ggg_suffix`, Peter 2026-07-30, Screenshot). Ein Zusatz-Hinweis
wie " (Remove-only)" steckt bei GGG im `name`-Feld des Kindes selbst statt
in einem eigenen Feld, erkennbar am führenden Leerzeichen — bislang nur
für Map-Kinder ausgewertet (Suffix an `metadata.map.name` anhängen). Bei
Unique-Kindern eines Remove-only-Tabs prüfte sowohl `display_name` als
auch `_stamp_category`/`_restamp_from_cached_items` bloß `tab.name.strip()`
— ein reiner Suffix ist damit truthy und wurde fälschlich als vollständiger
Name gewertet. Ergebnis: JEDES Kind eines Remove-only-Uniq-Tabs zeigte nur
noch "(Remove-only)" statt z. B. "Ring (Remove-only)", und die
Kategorie-Stempelung lief nie an, weil der Guard sie für "schon benannt"
hielt. `is_ggg_suffix()` bündelt die Erkennung an einer Stelle für alle
drei Verwendungen.

**Der Stempel muss einen erneuten Abruf des ELTERN-Fachs überleben**
(`_carry_over_stamps`, Peter 2026-07-30). `_on_stash_children` ersetzt die
Kind-Objekte komplett durch die frische API-Antwort — und dort sind
Unique-Kinder wieder namenlos. Ohne Übernahme fiel jedes bereits getaufte
Fach auf "UniqueStash" zurück, sobald das Eltern-Fach nochmal geladen
wurde; besonders auffällig nach "Load All Tabs", das Spezial-Tabs
grundsätzlich neu abruft (§4.10). Über `_persist_cache` wanderte der
Verlust gleich in den Datei-Cache. Übertragen werden ausschließlich
`poeview_`-Schlüssel, zugeordnet über die Fach-ID; alle echten API-Felder
gewinnt die frische Antwort (eine im Spiel geleerte Item-Anzahl darf nicht
am alten Stand kleben bleiben). Zusätzlich tauft
`_restamp_from_cached_items` namenlose Fächer neu, deren Items noch im
Cache liegen — damit heilen bereits beschädigte Cache-Dateien beim
nächsten Eltern-Abruf von selbst, ohne einen zusätzlichen Request.

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
zurückzuholen (FALLSTRICKE #18).

**Spalten-Filter (Excel-artig):**
Header-Rechtsklick zeigt oben ein Eingabefeld für die angeklickte Spalte
(`QWidgetAction`), Enter übernimmt. Ausdrücke: `>=20`, `<45`, `=Text`,
`!=…`, sonst Teilstring; numerisch wird verglichen, sobald Operand UND
Zelle eine Zahl hergeben. Aktive Filter markieren den Header mit 🔍
(`ItemFilterProxy.headerData`-Override), sind UND-verknüpft untereinander
und mit dem globalen Suchfeld, und die Statuszeile nennt Treffer/Gesamt.
Bewusst NICHT persistiert (wie in Excel: Filter sind Arbeitszustand). Das
Eingabefeld trägt zusätzlich einen `QCompleter` über
`ItemTableModel.distinct_values(col)` — sortierte, eindeutige
Anzeigewerte der Spalte über alle geladenen Zeilen, contains-Matching
(passend zum Filter selbst) — Peter, 2026-08-02: "eine Art
Autovervollständigen mit Combobox über die Items in der Spalte"
(`MainWindow._build_column_filter_edit`).

**View-relative Filter (Tab/Position) werden beim View-Wechsel gelöscht.**
Tab- und Position-Spalte sind relativ zur gerade angezeigten Quelle
(Charakter-Slot- vs. Truhenfach-Namen; Fach-Position vs. gar keine) — ein
Filter darauf verliert beim Wechsel zu einer anderen Quelle seinen Sinn
und kann dort ALLE Items unsichtbar machen, ohne erkennbaren Grund, wenn
die Spalte in der neuen Ansicht sogar automatisch ausgeblendet ist (Peter,
2026-08-02: "Tab->MainInventory gibt es im Stash nicht und es werden
deshalb keine Items angezeigt"). `MainWindow._clear_view_relative_column_
filters()` löscht deshalb genau diese zwei Filter an jeder Stelle, die auf
eine ANDERE Quelle umschaltet (Baum-Klick, Charakter-Klick, Aggregat/Suche
betreten) — nicht bei einem stillen Refresh derselben Ansicht. Filter auf
item-eigenen Spalten (Name, Base, Value, …) bleiben davon unberührt und
überleben einen View-Wechsel bewusst, sonst ginge der "mehrere Fächer
vergleichen"-Workflow bei jedem Klick verloren.

**Liga-weite Suche:** Tippen ins
Suchfeld schaltet die Tabelle auf ALLE gecachten Items der aktuellen Liga
um (Tab-Spalte = Herkunfts-Fach), Leeren des Felds kehrt zur vorher
gewählten Ansicht zurück (`_current_stash_id` als Rückkehrziel; Baum-Klick
während der Suche beendet sie ebenfalls). Liga-Wechsel zieht eine aktive
Suche auf die neue Liga um. Eingrenzen auf ein Fach: Baum-Klick oder
Spalten-Filter auf der Tab-Spalte. Ein eingebauter Clear-Button
(`setClearButtonEnabled`) leert das Feld per Klick auf das "x" am rechten
Rand. `_league_wide_items()` (§4.13) liefert zusätzlich Ausrüstung und
Inventar aller bereits geladenen Charaktere derselben Liga mit; als
Herkunft steht dann "Charaktername: Slot" statt eines Fach-Namens,
Position und Baum-Hervorhebung entfallen mangels Truhenfach. Das gilt
gleichermaßen für "Alle Tabs laden" (`_show_aggregate`), da beide
dieselbe Aggregationsfunktion nutzen.

Die globale Suche durchsucht Name, Typ, Tab, `explicitMods`,
`implicitMods` **und Properties**. Properties sind notwendig, weil
Map-Attribute wie Item Quantity, Item Rarity, Pack Size und Map Drop
Chance nicht in `explicitMods` stehen, sondern als eigene
`properties`-Einträge (`{"name": "Item Quantity", "values": [["+23%",
1]]}`). Ohne deren Text im durchsuchten Bereich waren betroffene Maps
über die Suche nicht auffindbar. `implicitMods` fehlte lange im
Suchindex, obwohl im Datenmodell längst vorhanden — eine Suche nach
einem Implicit (z. B. einem Ring-Widerstand) fand entsprechend nichts.

**Regex-Suche und Socket-Muster (Umschalter ".*", standardmäßig AN).**
PoE hat keinen eigenen Socket-Filter: Spieler suchen im Spiel per
regulärem Ausdruck über den Item-Text und klicken sich diese Muster
üblicherweise auf [poe.re](https://poe.re) zusammen
([veiset/poe-vendor-string](https://github.com/veiset/poe-vendor-string)).
Ein 3-Link aus zwei roten und einem grünen Socket ist dort
`r-r-g|r-g-r|g-r-r` (alle Permutationen), "irgendein 4-Link" ist
`-\w-.-`, "irgendein 6-Link" `(-\w){5}`; mehrere Kriterien verknüpft der
Generator per `|` zu einer einzigen Alternation.

Damit dieselben Strings hier unverändert funktionieren, steht
`Item.socket_string` mit im Suchindex — Farben einer Link-Gruppe mit `-`
verbunden, Gruppen durch Leerzeichen getrennt ("R-R-R-R-R-R",
"B B-B-B-B-B"), exakt die Schreibweise, die PoE selbst durchsucht.
Neben R/G/B liefert die API auch `A` (Abyss), `W` (weiß) und `DV`
(Resonator); sie werden unverändert übernommen, sonst verschöbe sich die
Link-Zählung gegenüber der Anzeige im Spiel. **Gegen echte Daten
kreuzgeprüft:** über 6639 Items mit Sockets stimmen die Treffermengen von
`-\w-.-`, `(-\w){4}` und `(-\w){5}` exakt mit `max_links >= 4/5/6`
überein (405/123/82 Items, keine einzige Abweichung).

`compile_search()`/`matches_search()` (item_table.py) kapseln die
Modus-Entscheidung und werden von BEIDEN Suchpfaden genutzt — dem Proxy
und der On-Demand-Suche für große Ligen (`_run_large_search`, §FALLSTRICKE
#40) —, damit der Umschalter überall identisch wirkt. Ein ungültiges
Muster (beim Tippen praktisch immer kurz der Fall, etwa nach einer
offenen Klammer) fällt still auf die Teilstring-Suche zurück, statt die
Liste leerlaufen zu lassen. Der Modus wird in `ui-settings.ini`
gespeichert. **Kosten gemessen** bei 50.000 Items (die
`LIVE_SEARCH_ITEM_LIMIT`-Schwelle): 43ms für das komplexeste
poe.re-Muster, 10ms für eine gewöhnliche Klartextsuche (gegenüber 7,5ms
im Teilstring-Modus) — beides weit unter dem 350ms-Dämpfer und damit
nicht spürbar.

**Zeilen-Filter läuft gedämpft, nicht bei jedem Tastendruck sofort**
(`MainWindow._search_debounce`, `SEARCH_DEBOUNCE_MS = 350`, FALLSTRICKE
#39). Bei liga-weiten Aggregaten mit mehreren zehntausend Items (Peter,
2026-07-28: "All Tabs liefert mir 19704 Items") kostet
`ItemFilterProxy.setFilterFixedString()` → `invalidateFilter()` →
`filterAcceptsRow()` je Zeile spürbar Zeit — gemessen ~23-25ms pro
kompletten Durchlauf über ~20.000 Zeilen, dominiert vom Python↔Qt-
Aufruf-Overhead selbst, nicht vom String-Aufbau innerhalb der Zeile
(Caching des Haystacks brachte im Benchmark keinen messbaren Unterschied,
23 vs. 25ms). Bei jedem Tastendruck sofort angewendet, ruckelte das
merklich. `_on_filter_text_changed()` startet deshalb nur noch einen
Single-Shot-Timer neu (`QTimer.start()` auf einem bereits laufenden Timer
setzt ihn zurück); erst nach 350ms Tipppause wendet
`_apply_debounced_search_filter()` den Filter tatsächlich an. Das
Umschalten in/aus dem Aggregat (`_enter_search_all`/`_leave_search_all`)
bleibt bewusst SOFORT, da es ohnehin nur einmal pro Such-Session läuft,
nicht pro Tastendruck.

**Suchtext und Item-Haystack sind vorgerechnet, nicht pro Filterdurchlauf
neu gebaut** (`ItemFilterProxy._search_text_lower`,
`ItemTableModel._search_haystacks`/`_build_haystack()`). Bringt für den
oben gemessenen Fall selbst kaum etwas (der Aufruf-Overhead dominiert),
vermeidet aber unnötige Arbeit, wenn `invalidateFilter()` OHNE
Textänderung läuft — z. B. beim Umschalten eines Typ-Filters während eine
Suche aktiv ist.

**Der Dämpfer allein reichte nicht — der eigentliche Showstopper war eine
`O(n²)`-Falle in `_update_stack_sum()` (FALLSTRICKE #39, Problem 3).**
Peters Rückmeldung nach dem Dämpfer: "Jeder Buchstabe führt zu sehr langen
(Minutenlang) Pausen" — ein einziger Tastendruck reichte bereits. Ursache:
`_stack_sum_label` (§4.7) hing zunächst zusätzlich an `layoutChanged`/
`rowsInserted`/`rowsRemoved`. Mit angehängter `QTableView` (immer der
Fall) emittiert `QSortFilterProxyModel` bei einer Filteränderung NICHT
ein Signal, sondern eines PRO ZUSAMMENHÄNGENDEM BLOCK neu versteckter/
sichtbarer Zeilen — bei einer Textsuche über ein Aggregat mit über die
ganze Liste verstreuten Treffern (19704 Items, jede 50. passend) waren
das 395 einzelne `rowsRemoved`-Aufrufe für EINEN Suchtext. Jeder rief
`_update_stack_sum()` mit einer erneuten `O(sichtbare Zeilen)`-Schleife
auf — zusammen `O(n²)`, gemessen 9,5 Sekunden für einen simulierten
Tastendruck. Ein Benchmark OHNE angehängte `QTableView` (wie der erste
Benchmark oben) findet diesen Bug nicht: ohne View feuern diese Signale
gar nicht synchron.

`_stack_sum_label` hängt seither NUR an `modelReset` (garantiert genau
ein Signal pro `set_items()`-Aufruf, unabhängig von Zeilenzahl oder
Streuung). Überall sonst, wo sich der Proxy-Filter ändert, ruft der
jeweilige Aufrufer `_update_stack_sum()` stattdessen explizit und genau
einmal auf: `_apply_debounced_search_filter()`, `_on_type_toggled()`,
`_apply_column_filter()`, `_clear_column_filters()`. Derselbe
19704-Items-Testfall lief danach in 29ms statt 9,5s. **Regel:** Ein
Handler, der selbst über `proxy.rowCount()` iteriert, darf nie an
`rowsInserted`/`rowsRemoved`/`layoutChanged` eines
`QSortFilterProxyModel` hängen — nur `modelReset` feuert garantiert genau
einmal pro Änderung.

**"On demand" statt live oberhalb `LIVE_SEARCH_ITEM_LIMIT = 50_000`
Items** (FALLSTRICKE #40). Auch mit gedämpftem, günstigem Filterdurchlauf
bleibt ein Problem: `_enter_search_all()` baut beim ALLERERSTEN Zeichen im
Suchfeld das komplette ungefilterte Liga-Aggregat als Qt-Modell auf, bevor
überhaupt gefiltert wird — `ItemTableModel.set_items()` kostet dafür
gemessen ~0,66s bei 19704 Items, ~1,76s bei 50.000, ~3,76s bei 100.000,
~7,93s bei 200.000 (Peter, 2026-07-28: "andere haben noch viel größere
Truhen"). Das skaliert linear mit der Item-Zahl, unabhängig vom
Suchtext — ein Dämpfer allein kann das nicht beheben, weil schon der
ERSTE Tastendruck den vollen Aufbau auslöst.

Oberhalb der Schwelle wird das ungefilterte Aggregat deshalb NIE als
Qt-Modell aufgebaut. `_enter_search_all()` speichert `items`/`sources`/
`tab_indices`/`stash_ids` nur roh in `self._large_search_items`, leert die
Tabelle und zeigt "X items in this league — keep typing…". Läuft der
Dämpfer ab, übernimmt `_run_large_search()`: reine Python-Filterung direkt
auf den zwischengespeicherten Listen (`ItemTableModel._build_haystack()`
wiederverwendet, kein doppelter Code — kein Qt-Modell, kein
Python↔Qt-Aufruf-Overhead pro Zeile), danach bekommen NUR die Treffer via
`table_model.set_items()` eine Tabellenzeile. Während der Filterung zeigt
`QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)` eine Sanduhr
statt eines eigenen `QProgressDialog` — die Aktion ist kurz genug, dass
ein Dialog überdimensioniert wäre. `proxy.setFilterFixedString("")`
danach lässt Typ- und Spalten-Filter unverändert über die (jetzt kleine)
Ergebnismenge laufen. `"*"` bleibt bewusst die Ausnahme: zeigt weiterhin
buchstäblich alles, auch oberhalb der Schwelle — dafür nimmt der Klick
einmalig den vollen Modell-Aufbau in Kauf, da explizit angefordert.

Gemessen über den echten Code-Pfad, mehrere Läufe (der jeweils erste in
einem frischen Prozess ist durch Pydantic-/Qt-Kaltstart langsamer, kein
wiederkehrender Effekt): 50.000 Items ≈ 82ms, 100.000 ≈ 162ms, 200.000 ≈
350ms im eingeschwungenen Zustand, bis zu ~800ms beim allerersten
Suchlauf der Sitzung.

**`*` als Suchtext zeigt alles an**, gedacht für den Komplett-Export
einer Truhe oder Liga über den CSV-Export (`_visible_rows` exportiert
ohnehin die aktuell sichtbaren Zeilen). Technischer Haken:
`QSortFilterProxyModel.setFilterFixedString` escaped den Text intern für
die Regex (`"*"` wird zu `"\*"`), das zurückgelesene
`filterRegularExpression().pattern()` ist also nie der Rohtext.
`ItemFilterProxy` überschreibt `setFilterFixedString` deshalb und merkt
sich den unescapten Suchtext selbst.

**Lazy-Icon-Loading:** Aggregat-Ansichten (Suche, "Alle Tabs",
Spezial-Eltern) rufen `set_items(…, request_icons=False)` auf — Icons
werden erst angefordert, wenn Qt die Zeile tatsächlich malt
(`data()`/DecorationRole). Eifriges Anfordern würde bei ~15.000 Items
ebenso viele Icon-Jobs in die sequenzielle Worker-Queue schieben und
manuelle Klicks minutenlang hinter CDN-Fetches einreihen.

**Position-Spalte ("#3 (4, 7)").** Der Tab-Name allein unterscheidet
gleichnamige Fächer nicht, wie sie in der Praxis häufig vorkommen (etwa
mehrere Heist-Fächer). Die Position-Spalte zeigt deshalb zusätzlich die
1-basierte Position des Herkunfts-Tabs sowie die Gitter-Koordinate des
Items darin (`x`/`y` am Item).

`StashTab.index` ist als Tab-Nummer **nicht** geeignet: Der Wert bezieht
sich auf die Position innerhalb der Liga, in der ein Tab ursprünglich
angelegt wurde. Beim Liga-Ende wandern Fächer nach Standard und behalten
ihren alten `index`, sodass dort mehrere Fächer denselben Wert tragen
(FALLSTRICKE #21). `MainWindow._tab_positions()` leitet die Nummer
stattdessen aus der aktuellen Reihenfolge der API-Antwort ab (1-basierter
Platz in der Truhen-Leiste, siehe §4.7.1). Nur diese ist frei von
Liga-Historie. Items aus einer Map-/Unique-Sektion tragen dabei die Nummer
ihres Eltern-Tabs — das ist der Truhenplatz, an dem sie physisch liegen.

Anders als die Tab-Spalte verwaltet die Anwendung diese Spalte nicht
selbst: Sie bleibt auch im Einzelfach sichtbar, wo sie die Koordinate
innerhalb des geöffneten Tabs zeigt, und lässt sich über das Header-Menü
ein- und ausblenden. Die Tab-Nummer wird an jeder `set_items()`-Aufrufstelle
mitgegeben; `ItemTableModel` führt dafür `_tab_indices` parallel zu
`_sources`. Sortiert wird über `NUMERIC_SORT_ROLE` mit dem Tupel-Schlüssel
`(Tab-Nr., x, y)`, unbekannte Werte als `-inf`. Ohne diesen Schlüssel
sortierte die Spalte alphabetisch, "#10" landete also vor "#2".

**Baum-Hervorhebung bei Zeilenauswahl.** `ItemTableModel` führt
zusätzlich `_stash_ids` parallel zu `_sources` und `_tab_indices`.
`MainWindow._on_row_selected` ruft damit `StashTree.highlight_stash(stash_id)`
auf, was die nötigen Eltern-Ordner aufklappt, den Fokus auf den Knoten
setzt und ihn ins Bild scrollt. Besonders nützlich ist das in der
`*`-Ansicht, wo Items aus vielen Fächern gemischt erscheinen.

Entscheidend dabei: `highlight_stash` verwendet `QTreeWidget.setCurrentItem`
statt eines simulierten Klicks. Qt löst `itemClicked` (das Signal, an dem
`stash_selected` hängt) ausschließlich bei echten Mausklicks aus, nicht
bei programmatischen Selektionsänderungen. Die laufende Suche oder
Aggregat-Ansicht in der Item-Tabelle bleibt dadurch unverändert.

**Typ-Filter** (8 Checkboxen neben dem Liga-Feld,
`MainWindow.TYPE_FILTER_ENTRIES`; ursprünglich ein "Rarity-Filter" mit
vier Checkboxen, später um Gem, Currency, Divination Card und eine
Sammel-Kategorie erweitert): Normal/Magic/Rare/Unique/Gem/Currency/Div Card
(frameType 0–6) sowie **"Sonstige"** (`theme.OTHER_TYPE = -1`, pink) für
alles ohne eigene Kategorie, also Quest, Prophecy, Relic und unbekannte
frameTypes (`item_table._type_key()` bildet jeden frameType auf sich
selbst oder auf `OTHER_TYPE` ab). Die Checkboxen tragen keine Textlabel,
da die Typnamen dafür zu lang wären; stattdessen ist die Rand- und
Füllfarbe der Checkbox die Typ-Farbe (`theme.RARITY_COLORS`, für
"Sonstige" `theme.TYPE_FILTER_COLOR`), der Name steht im Tooltip. Alle
acht sind standardmäßig aktiv. Abwählen blendet ausschließlich die
betreffende Kategorie aus (`ItemFilterProxy.set_type_visible`),
UND-verknüpft mit Text- und Spalten-Filtern.

### 4.12 Offline-Modus

Fällt die GGG-API aus, etwa an einem Patchday, war die Anwendung früher
praktisch unbenutzbar, obwohl der Datei-Cache (`data_cache.json`) längst
Stash-Daten enthielt. Ursache war, dass das Liga-Dropdown ausschließlich
über das Live-Signal `leagues_loaded` befüllt wurde. Ohne Netzwerk traf
dieses Signal nie ein, das Dropdown blieb leer, und ohne ausgewählte Liga
führte kein UI-Pfad zu den vorhandenen Cache-Daten.

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

### 4.13 Charakter-Ausrüstung (`MainWindow._on_character_selected`)

Klick auf einen Charakter zeigt Ausrüstung + Inventar in derselben
Item-Tabelle wie Stash-Fächer — bewusst KEINE eigene Paperdoll-Ansicht,
um die gesamte vorhandene Infrastruktur (Spalten, Filter, Suche
innerhalb der Ansicht, Icon-Lazy-Loading, CSV-Export) wiederzuverwenden.

**Endpunkt:** `GET /character/{name}` (`PoeApiClient.get_character_items`)
liefert ein `character`-Objekt (Singular, wie `stash` beim Einzel-Tab)
mit den Item-Listen `equipment`/`inventory`/`jewels`/`rucksack` — der
Client fasst alle vier zu einer einzigen `list[Item]` zusammen. Diese
Feldnamen stammen aus der offiziell dokumentierten GGG-Schema-Beschreibung;
anders als sämtliche Stash-Strukturen in diesem Projekt sind sie **NICHT**
an echten Rohdaten verifiziert (kein Zugriff auf einen echten
Charakter-Endpunkt-Response beim Bau dieses Features) — siehe
FALLSTRICKE_UND_WORKAROUNDS.md #26. Fehlende Listen werden als leer
behandelt statt einen Fehler zu werfen.

**Slot statt Tab:** `Item.inventoryId` (neues typisiertes Feld, z. B.
`"Weapon"`, `"BodyArmour"`, `"MainInventory"`) übernimmt die Rolle der
Tab-Spalte — exakt dasselbe Muster wie bei den Stash-Aggregat-Ansichten
(§4.10/§4.11), nur dass hier der Ausrüstungs-Slot statt des Tab-Namens
steht. Kein Truhenfach ist beteiligt: `_current_stash_id` wird auf `None`
gesetzt (keine Baum-Hervorhebung), die Position-Spalte zeigt nur die
Item-Koordinate, falls die API eine liefert (bei ausgerüsteten Items
vermutlich nicht, bei Inventar-Items evtl. schon).

**Cache-Verhalten identisch zu Stash-Fächern:** `MainWindow._character_items`
(Charaktername → Items) + `_character_items_loaded` (→ ISO-Zeitstempel)
werden wie `_items`/`_last_loaded` in `data_cache.CachedData` persistiert
(überlebt einen Neustart) und überleben ohne Login/Netzwerk (analog
§4.12 Offline-Modus — cache-first, kein Zwang zum erneuten Abruf).
Ein Klick auf einen bereits geladenen Charakter zeigt sofort den Cache,
kein automatisches Neuladen. `_on_character_items` prüft
`name == self._current_character_name` (analog
`_on_stash_items`/`league != self._current_league`), damit ein spät
eintreffendes Ergebnis eines inzwischen abgewählten Charakters nur noch
gecacht, aber nicht mehr angezeigt wird.

**Aktuell halten: zwei Wege, analog zu den Stash-Tabs.** Wie oft GGG das
Charakter-Inventar serverseitig aktualisiert, ist nicht dokumentiert und
ließ sich nicht verlässlich ermitteln. Die Anwendung macht deshalb
stattdessen ihre eigene Aktualität kontrollierbar:

1. **Automatisch, nur der gerade angezeigte Charakter:** Ist
   `_current_character_name` gesetzt, nimmt `_maybe_auto_refresh` (§4.8)
   ihn statt des Stash-Fachs als "aktuelle Ansicht"-Job (`silent=True`,
   `FetchCharacterItemsJob`) — beide schließen sich gegenseitig aus, pro
   Tick geht höchstens einer der beiden raus. Anders als Stash-Tabs haben
   Charaktere KEINEN eigenen Sweep-Mechanismus: Die Charakterliste ist
   klein genug, dass "andere Charaktere irgendwann von selbst auffrischen"
   keinen Mehrwert hätte — nicht angezeigte Charaktere bleiben unverändert,
   bis sie angeklickt oder manuell aktualisiert werden.
2. **Manuell, für JEDEN Charakter:** Rechtsklick in der Charakterliste →
   "⟳ Aktualisieren" (`CharacterList.character_refresh_requested` →
   `MainWindow._on_character_refresh`) — bewusst AM Cache vorbei, analog
   `_on_stash_refresh`, und schaltet die Ansicht auf diesen Charakter um
   (wie ein Klick, nur mit erzwungenem Neuladen statt Cache-Treffer).

---

### 4.14 Preis-Anzeige (`api/ninja.py`, `services/price_cache.py`)

Value-Spalte in der Item-Tabelle + Gesamtwert in der Statuszeile, auf
Basis der öffentlichen poe.ninja-Economy-API. Umfang bewusst begrenzt
(Entscheidung siehe ToDo.md): alle Preis-Kategorien AUSSER `BaseType`
(Rare-Item-Basen — mit Abstand die teuerste Kategorie beim Abruf, und
ohne iLvl-/Influence-Bewertung ohnehin unzuverlässig). Rare-Items ohne
Basis-Preis bleiben deshalb grundsätzlich ohne Wertangabe.

**API-Instabilität als Designvorgabe:** poe.ninja hat seine komplette
Preis-API am 2026-06-28 ohne Vorankündigung umgestellt — jede zu diesem
Zeitpunkt kursierende Doku (inkl. mehrerer GitHub-Repos) war schlagartig
falsch (`/api/data/currencyoverview` liefert seither 404). Die aktuellen
Routen wurden empirisch ermittelt:

- `/poe1/api/economy/stash/current/currency/overview?league=X&type=Currency|Fragment`
  → `lines[].currencyTypeName`/`chaosEquivalent`
- `/poe1/api/economy/stash/current/item/overview?league=X&type=…`
  → `lines[].name`/`chaosValue` (+ `gemLevel`/`gemQuality`/`corrupted`
  bei Gems, `links` bei Weapons/Armour)
- `/poe1/api/economy/exchange/current/overview?league=X&type=…`
  → `items[].id→name` getrennt von `lines[].id`/`primaryValue`

`fetch_price_index()` behandelt jede Kategorie einzeln als best-effort:
schlägt eine fehl (Netzwerk, eine erneute stille API-Umstellung), fehlt
nur diese eine Preisgruppe — kein Abbruch, keine Exception nach außen.
Traffic ist gering: alle ~30 Requests zusammen ≈ 1,2 MB komprimiert pro
Liga (real gemessen), da jede Anfrage eine ganze Kategorie statt eines
Einzel-Items liefert.

**Zwei Fälle, in denen der Item-Name allein nicht zum richtigen Preis
führt** (`PriceIndex`, drei getrennte interne Dicts: `_simple`/`_gems`/
`_links`):

1. **Gems** tragen bei poe.ninja mehrere Preis-Varianten pro Name
   (Level/Qualität/Corrupted) — real beobachtet bis Faktor 13 Unterschied
   zwischen benachbarten Varianten. `PriceIndex._gem_price` verlangt einen
   EXAKTEN Treffer auf allen drei Werten; ohne exakte Übereinstimmung gibt
   es keinen Näherungswert, sondern `None` (unbekannt) — ein falscher Preis
   um eine Größenordnung wäre schlimmer als gar keiner.
2. **Unique Weapons/Armour** werden ab 5-/6-Link separat bepreist (alles
   darunter bzw. ohne Sockets läuft unter einem Basis-Preis, Bucket
   `None`) — dafür trägt `Item` seit diesem Feature `sockets: list[Socket]`
   und `max_links` (größte Socket-Gruppe). `PriceIndex._link_price`
   matcht auf den passenden Bucket, mit Fallback auf den nächst niedrigeren
   bekannten (ein Item mit 6 Links, für das kein 6-Link-Preis gelistet
   ist, bekommt den 5-Link- bzw. sonst den Basis-Preis statt gar keinen).
3. **Chaos Orb** ist ein eigener Sonderfall: poe.ninja listet die
   Referenzwährung nicht gegen sich selbst (kein `chaosEquivalent`-Eintrag
   für "Chaos Orb"). `PriceIndex` seedet ihn deshalb fest mit `1.0`.

**Cache mit TTL** (`services/price_cache.py`): JSON-Datei analog
`data_cache.py`, 6 Stunden TTL (Preise bewegen sich über Stunden, nicht
Minuten). `MainWindow._ensure_prices_loaded()` prüft den Disk-Cache
zuerst und stößt nur bei einem Miss einen `FetchPricesJob` im
`ApiWorker` an — eigener, persistenter `httpx`-Client, unabhängig von
Rate-Limiter/Auth-Zustand der GGG-API (poe.ninja braucht keinen
Login). Bei archivierten Ligen (§4.12) wird kein Preis-Job abgeschickt,
dieselbe Regel wie beim Stash-Request.

**Kürzere TTL für ein leeres Ergebnis** (FALLSTRICKE #49): `PriceIndex.
is_empty` erkennt "außer der Chaos-Orb-Referenz keine einzige echte
Preiszeile". `price_cache.save()` vermerkt das als `empty`-Flag im
Cache-Eintrag; `load()` wendet dafür `EMPTY_TTL_SECONDS` (1h) statt der
vollen `TTL_SECONDS` (6h) an, sofern der Aufrufer keine explizite TTL
übergibt. Zwei Ursachen sehen für den Aufrufer gleich aus: ein
transienter Abruf-Fehler (real beobachtet: "Standard" bekam einmal eine
leere Antwort, obwohl poe.ninja Sekunden später wieder normal
antwortete) ODER eine Liga, die poe.ninja PRINZIPIELL nicht führt — reale
Prüfung gegen poe.ninjas `/economy/leagues` ergab, dass SSF-/private
Ligen wie Peters "Solo Self-Found" dort gar nicht gelistet sind: ohne
Spieler-Handel gibt es keine Handelsaktivität, aus der sich Preise
ableiten ließen. Für SSF bleibt die Value-Spalte deshalb dauerhaft
weitgehend leer — bewusst nicht bei jedem Liga-Wechsel neu versucht
(würde ~30 nutzlose Requests pro Wechsel gegen poe.ninja auslösen),
sondern höchstens einmal pro Stunde.

**Anzeige** (`item_table.py`): `format_chaos_value()` wählt Chaos für
kleine Beträge, Divine sobald der Gegenwert mindestens einen Divine Orb
erreicht (Divine-Kurs kommt aus `PriceIndex.divine_rate`, keine feste
Konstante). Unbekannt bleibt immer LEER, nie `0` — dieselbe Lehre wie bei
der Stack-Summe (FALLSTRICKE #39): ein unbekannter Preis ist etwas
anderes als ein wertloses Item. Werte unter einem Chaos werden dezent
Richtung Hintergrund abgeblendet (`theme.dimmed_text()`, seit §4.20 aus
dieser Stelle herausgezogen — dieselbe Mischung wie die
Alters-Abblendung im Stash-Baum, §4.7) — ein optischer Hinweis auf
wahrscheinlichen Schrott, ohne eine feste Grautönung, die auf hellem wie
dunklem Theme falsch aussähe.

Die Tabelle startet voreingestellt aufsteigend nach Value sortiert
(`self.table.sortByColumn(VALUE_COL, ...)` in `_build_ui()`) statt in
roher API-Reihenfolge — Peters Entscheidung 2026-07-30 für "Schrott-Items
finden" (ToDo.md): unbekannte Preise landen dank `NUMERIC_SORT_ROLE`s
`float("-inf")`-Fallback zusammen mit den geringsten bekannten Werten ganz
oben. Nur der Startzustand; ein Klick auf eine andere Spalte überschreibt
ihn wie jede normale Sortierung (`setSortingEnabled(True)` lässt Qt sie
danach eigenständig verwalten). Die numerische Sortierbarkeit der
Value-Spalte selbst gab es schon vorher — neu ist nur, dass sie von
Anfang an aktiv ist.

Die Gesamtwert-Anzeige in der Statuszeile (`_update_value_sum`) folgt
strikt derselben Update-Disziplin wie die Stack-Summe: nur über
`_update_summaries()` an `proxy.modelReset` gehängt bzw. explizit nach
jeder Filteränderung aufgerufen, nie an `rowsInserted`/`rowsRemoved`
(FALLSTRICKE #39 — genau dort saß der O(n²)-Bug). Anders als die
Stack-Summe ist eine Wert-Summe über verschiedene Item-Typen hinweg
sinnvoll (Chaos-Werte lassen sich aufaddieren, Stack-Größen
unterschiedlicher Items nicht) — sie erscheint deshalb auch bei
gemischten Treffern, nicht nur bei einheitlichem Item-Namen.

### 4.15 Eigene Item-Nachschlagewerke per Rechtsklick (`ui/external_tools.py`, `ui/settings_dialog.py`)

Rechtsklick auf eine Item-Zeile öffnet ein Kontextmenü mit Links zu
Nachschlagewerken, die der Nutzer selbst einträgt. Die reine
URL-Erzeugung sitzt bewusst in einem eigenen, Qt-freien Modul
(`external_tools.py`) — `MainWindow._build_item_tools_menu(item)`
verkabelt sie nur noch an `QDesktopServices.openUrl`. Diese Trennung war
auch für die Tests nötig: `QMenu.exec()` öffnet eine blockierende
Nested-Event-Loop und lässt sich nicht sinnvoll direkt aufrufen,
`_build_item_tools_menu()` dagegen liefert das fertige `QMenu`-Objekt
ohne es anzuzeigen.

**Ab Werk ist die Liste LEER** (Peter, 2026-08-02: "Wir nehmen das
komplett raus und verallgemeinern die Benutzung in der Anleitung, ohne
Bezug auf die Wiki und PoEDB. Damit sind wir hier komplett unabhängig von
Internetseiten und jeder Benutzer hat individuell die Möglichkeit, eine
Seite einzubinden"). Vorher waren zwei konkrete Nachschlagewerke
vorbelegt; ob deren Betreiber damit einverstanden sind, aus einer fremden
Anwendung heraus direkt geöffnet zu werden, war nie geklärt (ToDo.md:
"Seitenbetreiber unbedingt fragen") und hätte den Release blockiert. Mit
leerer Vorbelegung entfällt die Frage: die Anwendung kontaktiert von sich
aus keine Drittanbieter-Seite, und wer einen Eintrag anlegt, trifft diese
Entscheidung bewusst selbst. Zeigt das Menü dadurch gar keinen Eintrag,
steht dort statt eines leeren Popups (sähe wie ein Fehler aus) ein
deaktivierter Hinweis auf den Settings-Dialog.

Jeder Menüeintrag ist ein `ToolEntry(name, url_template, enabled)`;
`url_template` enthält genau einen Platzhalter `{slug}`, den `build_url()`
mit Leerzeichen→Unterstrich ersetzt (MediaWiki-Konvention,
Original-Schreibweise inkl. Apostrophe bleibt erhalten). Persistiert wird
als JSON-Array (`tools_to_json`/`tools_from_json`) unter
`external_tools/entries` in derselben `ui-settings.ini` wie die übrigen
UI-Einstellungen (§ *_settings()*). Der Toolbar-Button "⚙ Settings" öffnet
`SettingsDialog` (Tabelle mit Aktiv-Checkbox/Name/URL-Vorlage-Spalten,
Hinzufügen/Entfernen-Buttons) — bei OK schreibt
`MainWindow._open_settings_dialog()` die bearbeitete Liste zurück, bei
Abbrechen bleibt der alte Stand unangetastet. Eine bewusst geleerte Liste
wird als `"[]"` gespeichert und bleibt leer; nur ein fehlender oder
kaputter Wert fällt auf `DEFAULT_TOOLS` zurück.

**Welcher Name für `{slug}` eingesetzt wird, hängt von der Rarity ab**
(`_lookup_name()`, Peter 2026-08-01: "Hier sollten wir nach dem Base
gehen. Uniques können jedoch gezielt gesucht werden"). Nur Uniques
(`frameType == 3`) haben einen Eigennamen, unter dem sich ein Item
überhaupt gezielt nachschlagen lässt. Bei Rares trägt `item.name` zwar
auch einen Namen, der ist aber zufällig gewürfelt und hat nirgends eine
eigene Seite (real geprüft: "Vortex Bane" für ein Rare-Messer, dessen
`baseType` zuverlässig "Gutting Knife" liefert). Magic-Items haben gar
keinen `name`, aber ihr `typeLine` enthält die gewürfelten
Präfix-/Suffix-Wörter mit im Text ("Fleet Citrine Amulet of the
Flatworm") — auch hier ist `baseType` die bereinigte Fassung ("Citrine
Amulet"). Für alle übrigen Rarities (Normal, Gems, Currency, Divination
Cards, …) ist `baseType` ohnehin schon der Anzeigename (keine Affixe
möglich). `_lookup_name()` liefert daher `item.name` nur für Uniques,
sonst `item.baseType` (mit `typeLine`/`name` als Sicherheitsnetz, falls
`baseType` einmal leer sein sollte).

**Klammern im `{slug}` werden prozent-kodiert** (`_underscore_name()`,
FALLSTRICKE #57): Map-Items tragen als `baseType` z. B. "Map (Tier 16)".
Mindestens ein real getestetes Nachschlagewerk lehnt literale Klammern im
Pfad mit 404 ab und verlangt `%28`/`%29`; MediaWiki akzeptiert beide
Schreibweisen, die Kodierung ist dort also unschädlich und deshalb
generell aktiv.

**Ein Zwei-Werte-Schema passt bewusst nicht hinein.** Ein zwischenzeitlich
gebauter Deep-Link auf eine Preis-Seite brauchte Liga UND Item in einer
eigenen Slug-Konvention (klein, Satzzeichen entfernt, Bindestrich statt
Unterstrich) und war zudem auf Currency/Fragmente (`frameType == 5`)
beschränkt, weil das Schema für andere Kategorien unbestätigt blieb. Das
Ein-Platzhalter-Modell dafür zu verkomplizieren war Peters bewusste
Entscheidung dagegen — bliebe ein eigenes Vorhaben (z. B. ein zweites
`{league}`-Feld in der Vorlage).

Ein weiterer, geplanter Sonderfall (Item als Text in die Zwischenablage
statt eines Links) wurde probeweise gebaut und wieder entfernt: das
Zielwerkzeug lehnt einen Import ohne "Advanced mod descriptions"
(Tag-Kopfzeile pro Mod plus Wertspanne statt Wälzwert, z. B.
`+20(20-30)%` statt `+29%`) komplett ab, live bestätigt. Diese Daten
(Mod-ID/Tier/Spannen) liefert GGGs API nachweislich nie — echte
Stash-Cache-Dumps geprüft, kein Item trägt je ein "extended"-Feld dafür.
Ohne externe Mod-Datenbank (z. B. RePoE) wäre der Import dauerhaft kaputt,
nicht nur ungenau; deshalb komplett entfernt statt einen wissentlich
fehlschlagenden Weg anzubieten. Siehe FALLSTRICKE #50.

### 4.16 Charakter-Paperdoll (`ui/paperdoll.py`)

Doppelklick auf einen Charakter (`CharacterList.character_paperdoll_requested`)
öffnet ein separates, nicht-modales Fenster mit der Ausrüstung als
Puppenlayout statt als flache Tabellenzeilen (ToDo.md: "Doppelklick auf
einen Char 'beleuchtet' diesen", Peter 2026-07-31). Reine Anzeige bereits
geladener Daten — `PaperdollDialog` bekommt Items direkt übergeben, kein
eigener Netzzugriff, kein Wissen über Worker/Icon-Cache (Icons kommen über
einen injizierten `pixmap_for`-Callback, üblicherweise
`MainWindow.table_model.pixmap_for`).

Zehn feste Kern-Slots (Helm, Waffe, Amulett, Zweithand, Rüstung, 2× Ring,
Gürtel, Handschuhe, Stiefel) nach GGGs realen `inventoryId`-Werten
(Peters Stash-Cache geprüft, 2026-07-31 — **"Helm" nicht "Helmet"**,
**"Offhand"/"Offhand2" nicht "Shield"**). Leere Slots bleiben als
deaktivierter Platzhalter-Button sichtbar (kein leeres Loch im Layout).
Zusätzlich, nur wenn tatsächlich vorhanden:

- **Flaschen** (`inventoryId == "Flask"`, alle fünf tragen denselben Wert
  — die Reihenfolge kommt aus der `x`-Koordinate, 0–4).
- **Waffentausch-Set** (`Weapon2`/`Offhand2`) und **Trinket** (Ritual-/
  Necropolis-Liga-Feature) — nicht jeder Charakter hat beides.
- **Jewels im Passiv-Baum** (`PassiveJewels`) als reine Namensliste, nicht
  als Doll-Slot: es sind potenziell Dutzende, ihre `x`-Koordinate ist eine
  Position im Passiv-Baum, keine sinnvolle Sortierung fürs Layout.

Klick auf einen belegten Slot zeigt das Item im eingebetteten `ItemDetail`
(demselben Widget, das auch die Haupttabelle nutzt) — kein Duplikat der
Detail-Darstellung.

Doppelklick-Timing: `_on_character_paperdoll_requested` öffnet sofort bei
Cache-Treffer. Ohne Cache-Treffer merkt sich `MainWindow` den Charakter in
`_paperdoll_pending_char` — der vorangehende Einzelklick derselben
Doppelklick-Sequenz hat über `_on_character_selected` bereits einen
`FetchCharacterItemsJob` ausgelöst, `_on_character_items` öffnet die
Paperdoll nach, sobald das Ergebnis eintrifft. Dieser Check läuft bewusst
VOR dem `name != self._current_character_name`-Ausstieg: der Doppelklick
galt dem angeklickten Charakter, unabhängig davon, ob die Auswahl bis zum
Eintreffen der Daten weitergesprungen ist.

Bewusst NICHT im Doll: `MainInventory`-Items (der Rucksack) — die zeigt
die Haupttabelle bereits beim einfachen Klick auf den Charakter, ein
Duplikat in der Paperdoll hätte keinen Mehrwert. "Beleuchten" heißt hier
nur die AUSRÜSTUNG.

### 4.17 Vergrößerte Item-Ansicht (`ui/item_zoom.py`)

Doppelklick auf eine Zeile der Item-Tabelle (`table.doubleClicked`, Qt-
eigenes Signal, keine eigene Mouse-Event-Behandlung nötig) öffnet
`ItemZoomDialog`: großes Icon statt der 64px im kompakten `ItemDetail`,
und der VOLLSTÄNDIGE Mod-/Property-Text ohne dessen `lines[:12]`-Kürzung —
genau das ist der Zweck des Fensters, eine erneute Kürzung wäre sinnlos
(ToDo.md: "Doppelklick auf ein Item 'beleuchtet' dies", Peter 2026-07-31).

Das Icon skaliert um einen FESTEN Faktor (`_ZOOM_FACTOR = 2`, also 200 %
der Originalgröße) statt auf eine feste Box ODER die Fensterbreite — Peter
probierte die Fensterbreiten-Variante zuerst live aus ("das ging schief"):
normale, kleine Item-Icons wurden dabei auf hunderte Pixel aufgeblasen und
wirkten verpixelt. Der erste feste Faktor (300 %) war Peter dann beim
Live-Test noch zu groß, 200 % ist der aktuelle Stand (Peter, 2026-07-31).
Ein fester Faktor auf die tatsächliche Originalgröße bleibt für jedes
Icon proportional maßvoll — bei Divination-Card-Artwork (~237×170px)
ergibt das ~474×340px, deutlich größer als das generische 64px-Icon, ohne
zu verzerren (`Qt.AspectRatioMode.KeepAspectRatio` sichert das zusätzlich
ab). Reagiert bewusst NICHT mehr auf Fenstergrößenänderungen.

Zwei Teile der ursprünglichen Idee sind NICHT enthalten, aus denselben
Datengründen wie beim Craft-of-Exile-Rückzug (FALLSTRICKE #50):

- **Tier-Level/Stat-Wertebereiche** ("Range der Stats (Balken)", T0/T1/T2)
  bräuchten Mod-ID/Tier/Spannen-Rohdaten, die GGGs API nachweislich nie
  liefert.
- **Beliebtheit als Crafting-Basis / Build-Nutzung** bräuchte eine neue,
  eigenständige Anbindung an poe.ninjas Build-Suche — der bestehende
  `api/ninja.py`-Client holt ausschließlich Preise, keine Build-Daten.

Beide bleiben als zurückgestellte Ideen in ToDo.md vermerkt.

**Divination Cards (frameType 6):** GGGs Stash-API liefert für JEDE
Div-Card dasselbe generische Icon (`2DItems/Divination/InventoryIcon.png`
— real geprüft an Peters Stash-Cache, alle acht dort vorkommenden Karten
trugen identisch dieselbe URL), das wäre in dieser vergrößerten Ansicht
wertlos. `_on_table_row_double_clicked` fordert deshalb zusätzlich das
echte Artwork an (`external_tools.divination_card_art_url`, GGGs eigenes
CDN `web.poecdn.com/image/divination-card/<Name ohne Leerzeichen>.png`,
live an zehn echten PoEDB-Kartenseiten verifiziert, FALLSTRICKE #52).
Cache-Treffer (`icon_cache.load`) aktualisieren das Icon sofort synchron,
sonst läuft der Download wie jedes andere Item-Icon über
`FetchIconJob`/`icon_loaded` — `MainWindow._pending_card_art` merkt sich
dafür (URL, Ziel-Dialog), `_on_icon` löst es beim Eintreffen auf. Da
`web.poecdn.com` GGGs eigenes CDN ist (nicht PoEDB/Wiki/poe.ninja selbst),
gilt die "Seitenbetreiber fragen"-Vorsicht der anderen drei Rechtsklick-
Tools hier nicht.

**Wichtig, von Peter am echten Ergebnis geprüft (2026-07-31):** Diese URL
liefert NUR das bloße Illustrations-Panel (querformatig, ~237×170px) —
KEINEN vollständigen Karten-Look mit Pergament-Rahmen, Titel-Schriftrolle,
Tier-Box oder Flavour-Text (das ist eine eigene, von Wikis komponierte
Darstellung, kein einzelnes GGG-Asset). Peter fand über die Wiki-Seite
eine solche Voll-Karten-Ansicht als optische Referenz; Text (Flavour,
Tier, Stack) käme ohnehin nicht von GGG und ist laut Peter "nicht so
wichtig" — nur ein rein dekorativer Rahmen wurde umgesetzt
(`ItemZoomDialog._build_card_frame`, Qt-Stylesheet: Pergament-farbenes
Titel-Banner um `self._name`, dunkler umrandeter Rahmen um Titel+Icon).
Reine Optik, keine neuen Daten — nur bei `frameType == 6` aktiv.

### 4.18 Konfigurierbare Item-Spalten (`ui/item_table.py`, `ui/settings_dialog.py`)

Peter, 2026-08-01: "Wir haben ja alle möglichen Attribute pro Item. Daher
benötigen wir jetzt die Möglichkeit, die angezeigten Spalten
einzustellen." Der Settings-Dialog (§4.15) bekam dafür einen zweiten
Reiter "Columns" (`QTabWidget`, `SettingsDialog._build_columns_tab`):
eine `QListWidget` mit einer Checkbox-Zeile pro konfigurierbarer Spalte
(`item_table.CONFIGURABLE_COLUMNS` — alle `COLUMNS` außer "Tab", siehe
unten), Reihenfolge per Drag&Drop (`setDragDropMode(InternalMove)`).
`SettingsDialog.result_column_config()` liefert die editierte Liste als
`list[tuple[name, visible]]` in der gewählten Reihenfolge zurück.

**Reihenfolge über die VISUELLE Header-Position, nicht über die
logischen Spalten-Indizes.** `MainWindow._apply_column_config()` ruft für
jede Spalte `header.moveSection(header.visualIndex(col), target_visual)`
auf — die logischen Indizes (`COLUMNS.index(name)`, worüber Sortierung,
Spalten-Filter und `setColumnWidth` weiterhin arbeiten) bleiben dabei
unverändert. Das entkoppelt "wo steht die Spalte" komplett von "welchen
Index hat sie im Code" — genau wie Qt das eigene Drag-Umsortieren im
Header selbst umsetzen würde (hier aber bewusst NICHT per Header-Drag,
sondern nur über den Settings-Dialog, siehe unten).

**Tab-Spalte bleibt fix an visueller Position 0** und ist nicht Teil der
konfigurierbaren Liste — ihre Sichtbarkeit steuert weiterhin allein die
Einzelfach-/Aggregat-Logik (§4.7.1 u. a.), unabhängig von Peters
Spalten-Auswahl.

**Persistenz + Migration:** Sichtbarkeit UND Reihenfolge zusammen als
JSON-Array (`{"name":..., "visible":...}`) unter
`item_table/column_config` in `ui-settings.ini` — dieselbe Datei wie die
übrigen UI-Einstellungen. Ersetzt die alte, reine Sichtbarkeits-Menge
(`item_table/hidden_columns`, ";"-getrennte Namen ohne Reihenfolge):
`MainWindow._load_column_config()` übernimmt eine noch vorhandene alte
Einstellung automatisch als Startreihenfolge, damit eine bestehende
Auswahl beim Umstieg nicht verloren geht. Fehlt eine konfigurierbare
Spalte im gespeicherten JSON (z. B. weil sie erst später hinzukam), wird
sie sichtbar ans Ende angehängt statt zu verschwinden. Das
Header-Rechtsklick-Menü (§4.11) bleibt als schneller Ein/Aus-Schalter für
eine einzelne Spalte erhalten (`_toggle_column`) — beide Wege schreiben
denselben JSON-Stand.

**Bewusst nicht umgesetzt (Peters Idee, gemeinsam auf später vertagt):**
je Stash-Tab-TYP eine eigene Standard-Spaltenauswahl/-Reihenfolge (z. B.
Waffen-Tabs mit Sockets/Qualität vorn, Karten-Tabs mit Tier vorn), später
sogar pro einzelnem Truhenfach — ursprünglich als Baum-Struktur im
Settings-Dialog gedacht. Offene Frage dafür, noch ungeklärt: Die
Item-Tabelle zeigt meist Items aus mehreren/allen Tabs gleichzeitig
(liga-weite Suche, "Alle Tabs laden", §4.11) statt nur eines einzelnen
Tabs — bei typ-abhängigen Spalten müsste erst geklärt werden, was in
so einer gemischten Ansicht gilt. Diese globale, typ-unabhängige
Konfiguration ist bewusst der erste, einfachere Ausbauschritt.

### 4.19 Zonenwechsel-Trigger für den Live-Refresh (`services/zone_watcher.py`)

Peter, 2026-08-01: "Ich habe die Vermutung, dass sich der Stash-Inhalt
erst aktualisiert, wenn wir die Zone gewechselt haben." Live beobachtet
bestätigt: nach einem Zonenwechsel zeigt sich eine Änderung praktisch
sofort. Ein LÄNGERER Beobachtungszeitraum zeigte aber (FALLSTRICKE #58,
Nachtrag): der Zonenwechsel ist nicht der EINZIGE Auslöser — GGGs
Stash-API liefert neue Daten offenbar auch unabhängig davon irgendwann,
nur deutlich langsamer (Peters Schätzung: "alle 5 Minuten?", nicht exakt
gemessen), vermutlich ein serverseitiger Cache mit eigener, vom
Zonenwechsel unabhängiger Ablauffrist. Der Zonenwechsel-Trigger ist daher
als BESCHLEUNIGER für den häufigen Fall zu verstehen, nicht als Ersatz
für den bestehenden getakteten Refresh (§4.8) — der bleibt unverändert
aktiv und deckt weiterhin Sessions ohne Zonenwechsel ab (z. B. lange
Handwerks-Sessions im Hideout). `ZoneWatcher` (`services/zone_watcher.py`)
beobachtet dafür Peters eigene, lokale `Client.txt` (PoE schreibt dort
bei jedem Zonenwechsel eine Zeile `... : You have entered <Zone>.`) und
meldet jeden erkannten Wechsel über ein Qt-Signal — reines LESEN einer
Text-Logdatei, von GGG ausdrücklich erlaubt (anders als Speicherzugriffe
auf den laufenden Client-Prozess, die ein Bann-Risiko wären).

**Ereignisgesteuert statt Polling** (Peters Vorschlag, 2026-08-01: "Wir
könnten auch den Windows-Watcher benutzen"): `QFileSystemWatcher` nutzt
die betriebssystem-eigene Änderungsbenachrichtigung und meldet sich erst,
wenn PoE tatsächlich neue Zeilen anhängt — kein eigener Timer, kein
Sekundentakt-Polling. `ZoneWatcher.check_now()` liest dann nur die seit
dem letzten Aufruf neu angehängten Bytes (Byte-Offset gemerkt, nicht die
ganze Datei neu eingelesen) und meldet jede erkannte Zonenwechsel-Zeile
darin einzeln über `zone_changed(zone_name)`. Startet am AKTUELLEN
Dateiende — frühere Zeilen (vor Programmstart) interessieren nicht, ein
mehrere MB großes Log von Beginn an einzulesen wäre unnötig teuer. Wird
die Datei kleiner als der zuletzt gemerkte Stand (PoE-Neustart mit
frischer Client.txt), beobachtet `check_now()` wieder ab Position 0,
statt hängen zu bleiben.

**Peter gibt den Pfad explizit an, kein Rätselraten** (Peter, 2026-08-01:
"Wir werden den User aber explizit über eine Pfadangabe die richtige
Datei bzw. lediglich den PoE-Pfad angeben lassen"): Settings-Dialog (§4.15),
dritter Reiter "Zone Refresh" — eine Checkbox (Feature standardmäßig AUS)
und ein Pfadfeld samt "Durchsuchen…"-Button. `resolve_client_log_path()`
akzeptiert entweder direkt die Client.txt oder nur den
PoE-Installationsordner (probiert dann `<Ordner>/logs/Client.txt`, dann
`<Ordner>/Client.txt`) und zeigt sofort eine Live-Rückmeldung
("✓ Gefunden: …" / "✗ Keine Client.txt an diesem Pfad gefunden"), damit
Peter nicht blind einen Pfad einträgt und hofft. Persistiert als
`zone_watcher/enabled` + `zone_watcher/log_path` in `ui-settings.ini`.
`MainWindow._apply_zone_watcher_config()` baut den `ZoneWatcher` bei
aktivierter Funktion und gültigem Pfad komplett neu auf (einfacher als
ein Update-Codepfad, läuft nur beim Programmstart bzw. nach dem
Settings-Dialog) — ungültiger/leerer Pfad lässt das Feature bewusst
inaktiv, ohne separate Fehlermeldung (der Dialog zeigt das ja schon live).

**`_on_zone_changed()` lädt NUR die gerade offene Ansicht neu** — den
gleichen gezielten Job wie der erste Teil von `_maybe_auto_refresh`
(jetzt als gemeinsames `_refresh_current_view()` herausgezogen), kein
Sweep, kein Burst, ein einzelner Request pro Zonenwechsel. Respektiert
den Pause-Refresh-Modus (explizite Nutzerwahl "keine
Hintergrund-Anfragen") und `rate_limiter.pacing_blocked()` als harte
Obergrenze, sonst identisch zu jedem anderen stillen Refresh
(`silent=True`).

### 4.20 Charakter-Refresh-Diff: geänderte/verschwundene Items hervorheben

Peter, 2026-08-01: "Wenn ich das Character-Inventar beobachte hätte ich
gerne die Zeilen hervorgehoben (Türkis), welche sich geändert haben. Die
Items die seit dem letzten Mal verschwunden sind, könnten wir in Grau und
durchgestrichen darstellen." Direkte Ergänzung zum Zonenwechsel-Trigger
(§4.19) — der sorgt für häufigere Charakter-Refreshes, aber ohne
Hervorhebung ließe sich das kaum ablesen: die Tabelle sortiert bei jedem
`set_items()` neu auf, ein neu hinzugekommenes/verändertes Item geht in
20+ unveränderten Zeilen unter.

**Identität über `item.id`, nicht Objektgleichheit** — GGGs Item-ID ist
über Refreshes hinweg stabil (real geprüft, Peters Cache), auch wenn sich
z. B. die Stack-Größe eines Currency-Stacks ändert. `MainWindow.
_diff_character_items(previous_items, items)` (statische Methode, pures
Set-basiertes Vergleichen, keine Model-Abhängigkeit — leicht isoliert
testbar) vergleicht den Item-Stand VOR dem gerade eingetroffenen Refresh
mit dem neuen und liefert `(added_ids, changed_ids, removed_items)`:

- **Neu** (`added_ids`): `item.id` gab es in `previous_items` gar nicht —
  ein echter Neuzugang (Loot, Handel).
- **Geändert** (`changed_ids`): `item.id` existierte schon, aber der
  komplette Item-Wert (Pydantic-Gleichheit, erfasst auch
  `extra="allow"`-Zusatzfelder) unterscheidet sich vom vorigen Stand mit
  derselben id — deckt Stack-Größen-, Mod- oder Property-Änderungen ab,
  ohne Feld für Feld selbst zu vergleichen. Bewusst GETRENNT von
  `added_ids` (Peter, 2026-08-02, §4.21): die Türkis-Hervorhebung hier
  behandelt beide gleich (`added_ids | changed_ids`), der Charakter-Item-
  Verlauf dagegen NUR `added_ids` — eine reine Stack-Größen-Änderung soll
  dort nicht als "neues Item" auftauchen.
- **Verschwunden** (`removed_items`): `item.id` gab es vorher, taucht im
  neuen Stand aber nicht mehr auf.
- Items ganz ohne `id` (im echten Cache bislang nie beobachtet, laut
  Pydantic-Modell aber möglich) bleiben unberücksichtigt — ohne stabile
  Kennung ist "gleiches Item, neuer Zustand" von "verschwunden + neues
  Item zufällig an derselben Stelle" nicht unterscheidbar.
- `previous_items=None` (erstes Anzeigen dieses Charakters, kein
  Vergleichswert vorhanden — auch ein Cache-Treffer in
  `_on_character_selected` zeigt ohne Diff an) liefert bewusst leere
  Ergebnisse, sonst wäre beim allerersten Öffnen sofort die komplette
  Ausrüstung "neu".

**Verschwundene Items bleiben für GENAU EINEN Refresh-Zyklus sichtbar**
statt sofort aus der Tabelle zu fallen — `_show_character_items()` hängt
sie ans Ende der angezeigten Liste an (`items + removed_items`), OHNE sie
in `self._character_items[name]` (der eigentlichen Diff-Basis fürs
nächste Mal) mit zu speichern. Sie fallen beim übernächsten Refresh
deshalb von selbst wieder raus, ohne eigene Aufräum-Logik.

**Rendering in `ItemTableModel`** (`item_table.py`): `set_items()` nimmt
zusätzlich `changed_ids`/`removed_ids` entgegen (Default: leere Menge —
Stash-Ansichten kennen kein Refresh-Diff und färben dadurch nie versehentlich
nach). Geänderte Zeilen bekommen einen türkis getönten Zeilenhintergrund
(`theme.ROW_CHANGED_COLOR`, zur Palette-Hintergrundfarbe gemischt —
hell wie dunkel lesbar). Verschwundene Zeilen bekommen für ALLE Spalten
eine gedimmte Textfarbe (`theme.dimmed_text()`, derselbe Mischalgorithmus
wie die "wahrscheinlich Schrott"-Dimmung der Value-Spalte, §4.14 — jetzt
aus dieser Stelle herausgezogen und geteilt) sowie durchgestrichenen Text
(`QFont.setStrikeOut`) statt der sonstigen Rarity-Färbung.

### 4.21 Charakter-Item-Verlauf: die letzten 120 Items, die durchs Inventar gewandert sind

Peter, 2026-08-02: "Ich überlege gerade, ob es sinnvoll ist, eine Liste
mit den letzten 120 Items zu pflegen, die durchs Inventar gewandert sind.
Intension dahinter ist, dass du nochmal kurz nachschauen kannst, was du
gerade in die Truhe getan hast oder verkauft hast oder gehandelt hast."
Baut direkt auf §4.20 auf: dieselbe Diff-Erkennung (`_diff_character_
items`) liefert schon "neu"/"verschwunden" pro Charakter-Refresh — hier
wird daraus zusätzlich ein rollierendes Protokoll statt nur einer
Zeilen-Hervorhebung.

**Global statt an die aktuell offene Ansicht gebunden** (Peter: "Wenn wir
das Global machen") — `MainWindow._log_character_item_history()` läuft in
`_on_character_items()` für JEDEN Charakter, dessen Daten eintreffen,
unabhängig davon, ob er gerade angezeigt wird (anders als die Türkis-/
Grau-Hervorhebung aus §4.20, die nur die offene Ansicht betrifft). Nur
`added_ids` (echte Neuzugänge) und `removed_items` werden geloggt,
NICHT `changed_ids` — eine reine Stack-Größen-Änderung ist kein
"Item ist durchs Inventar gewandert". `previous_items=None` (erster
Ladevorgang eines Charakters) loggt nichts, aus demselben Grund wie bei
der Türkis-Hervorhebung: sonst wäre der komplette Startbestand beim
ersten Laden fälschlich "neu".

**Eigenes Spaltenformat statt Wiederverwendung der Item-Tabelle**
(`ui/item_history.py`, `ItemHistoryModel`) — ursprünglich als "Header ist
der gleiche wie oben, deshalb nicht angezeigt" angedacht, aber ein
Log-Eintrag hat andere Bedürfnisse als eine Bestandsanzeige: Zeitpunkt und
Ereignistyp (↑ neu / ↓ verschwunden) sind Pflicht, welcher Charakter
betroffen war wird bei einem GLOBALEN Verlauf über mehrere Charaktere
hinweg ebenfalls relevant, während Tab/Position (siehe FALLSTRICKE #59)
hier komplett bedeutungslos wären. Spalten: Time, Character, Event, Icon,
Name, Base, Stack, Value — bewusst ohne Mods/Req-Stats/Type, das bläht die
kompakte Zeile unnötig auf (ein Doppelklick öffnet bei Bedarf die normale
vergrößerte Item-Ansicht, §4.17). `HistoryEntry` (Zeitstempel, Ereignis,
Charaktername, `Item`) ist eine eigene, unabhängige Datenklasse — das
Model kennt nur fertige Einträge, keine Diff-Logik.

**Rollierendes Log, 120 Einträge, neueste zuerst** — `MainWindow.
_item_history: deque[HistoryEntry] = deque(maxlen=120)`. Neue Einträge
kommen per `appendleft()` rein: `maxlen` verdrängt dadurch automatisch das
ÄLTESTE Ende, ganz ohne eigene Aufräum-Logik, und Zeile 0 ist immer das
jüngste Ereignis — wichtig für die standardmäßig kollabierte Anzeige (nur
eine Zeile sichtbar, siehe unten). Icons und Preise teilen sich dieselbe
Infrastruktur wie die Haupttabelle: `_on_icon()` reicht jedes geladene
Icon zusätzlich an `history_model.set_icon()` weiter, `set_price_index()`
wird an jeder Stelle mitgerufen, die auch `table_model.set_price_index()`
aufruft.

**UI: vertikaler `QSplitter` statt fixer Höhe** — `self.table` und
`self.history_table` liegen übereinander in einem
`QSplitter(Qt.Orientation.Vertical)`; die Starthöhe des Verlaufs
entspricht Header + einer Datenzeile (`horizontalHeader().sizeHint().
height() + verticalHeader().defaultSectionSize() + 2×frameWidth()`),
kann per Ziehen am Splitter-Griff aber beliebig aufgezogen werden (Peter:
"kann aufgezogen werden") — ganz ohne eigene Resize-Logik, das bringt
`QSplitter` von Haus aus mit. Rechtsklick (externe Tools) und Doppelklick
(vergrößerte Ansicht) funktionieren wie in der Haupttabelle, jeweils über
eigene, parallele Handler (`_on_history_row_menu`/`_on_history_row_
double_clicked`) — der Verlauf hat weder Proxy noch Sortierung/Filter,
die bestehenden Handler der Haupttabelle sind zu eng an `self.proxy`/
`self.table_model` gebunden, um sie direkt wiederzuverwenden.

### 4.22 Erweiterter CSV-Export (`services/csv_export.py`)

Peter, 2026-08-02: "Im CSV hätte ich gerne alle Eigenschaften eines Items
gehabt. Auch hätte ich gerne den Export ins Rechtsklick-Menü übernommen."
Der bisherige Export (§4.11-Umgebung, `MainWindow._export_csv`) schrieb
nur 10 feste Spalten (Name, Rarity, TypeLine, BaseType, Level, Quality,
StackSize, ItemLevel, Corrupted) — Value, Anforderungen, Sockets/Links,
Mods, Influences, Position und die meisten Merkmale fehlten.

**Fester, breiter Spaltensatz statt Vereinigung aller Felder** — `Item`
erlaubt beliebige Zusatzfelder von GGG (`extra="allow"`), und Items sind
je nach Typ höchst ungleich aufgebaut (ein Gem hat andere Properties als
ein Rüstungsteil). Eine Vereinigung aller real vorkommenden Felder ergäbe
eine über 100 Spalten breite, zu 90 % leere Tabelle. `FIELDNAMES` in
`csv_export.py` listet stattdessen einen festen Satz — alles, was die App
auch selbst anzeigt oder intern kennt: Position (`Tab`/`InventoryId`/`X`/
`Y`), `Category` (`item_category()`), Anforderungen (`ReqLevel`/`ReqStr`/
`ReqDex`/`ReqInt`), `Sockets`/`Links`, `Identified`/`Corrupted` sowie
sieben Ja/Nein-Merkmale ohne eigenes Modellfeld (`Mirrored` — GGG nennt
das Feld intern `duplicated` — `Fractured`, `Synthesised`, `Veiled`,
`Replica`, `Searing`, `Tangled`), `Influences`, `Properties`, sieben
Mod-Arten (`ImplicitMods`/`ExplicitMods`/`CraftedMods`/`EnchantMods`/
`FracturedMods`/`VeiledMods`/`UtilityMods`), `Note`, `ValueChaos` und
`ItemId`. Mehrwertige Felder (Mod-Listen, Properties) landen zusammen-
gefasst in EINER Zelle, getrennt durch `" | "` — pro Eintrag eine eigene
Spalte wäre nicht vorhersagbar breit.

Zugriff auf Felder ohne Modell-Attribut (die sieben Merkmale, `note`,
`influences`, sowie Mod-Arten jenseits von `explicitMods`/`implicitMods`)
läuft über `item.model_extra` (`_extra()`/`_joined_list()`) — pydantics
Sammelstelle für `extra="allow"`-Felder, die die API liefert, aber die
niemand als eigenes Attribut deklariert hat.

**`ValueChaos` ist eine reine Zahl ohne Einheit** — anders als die
Value-Spalte im UI (`format_chaos_value`, Chaos/Divine je nach Höhe):
"2.3div" ist in einer Tabellenkalkulation nicht weiterverarbeitbar, eine
einheitliche Chaos-Zahl schon. `export_items()` bekommt dafür optional
den `PriceIndex` der aktuellen Liga übergeben (`MainWindow._export_rows`
reicht `self._price_indexes.get(self._current_league)` durch); fehlt er
(SSF-Liga ohne poe.ninja-Daten) oder kennt er das Item nicht, bleibt die
Zelle leer statt 0 — dieselbe Regel wie bei der Value-Spalte
(FALLSTRICKE #39: unbekannter Preis ≠ wertloses Item).

**`RawJSON`-Spalte: restlos alles, aber Opt-in.** Wer wirklich jedes
Feld braucht (auch eins ohne eigene Spalte), bekommt es über einen
zweiten Dateityp im Speichern-Dialog (`_CSV_RAW_FILTER` neben
`_CSV_FILTER`, `QFileDialog.getSaveFileName` liefert den gewählten Filter
als zweiten Rückgabewert). Dann hängt `export_items(..., raw_json=True)`
`item.model_dump(mode="json")` als zusätzliche letzte Spalte an. Bewusst
NICHT die Voreinstellung: ein einzelnes Item-JSON ist mehrere Kilobyte
groß, ein liga-weiter Export über zehntausende Items würde damit
dreistellige Megabyte erreichen.

**Export per Rechtsklick, zwei Bereiche.** `_on_table_row_menu` hängt
über `_add_export_actions()` zwei Einträge ans Item-Kontextmenü:
"Export selected items (n)" (`_selected_rows()`, aus
`selectionModel().selectedRows()`, nach sichtbarer Zeilenposition
sortiert statt nach Klick-Reihenfolge) und "Export visible items (n)"
(identisch zum bisherigen Toolbar-Weg, `_visible_rows()`). Beide teilen
sich `_rows_for()` als gemeinsamen Kern. Die Anzahl steht im Menütext,
damit vor dem Speichern-Dialog klar ist, was gleich in der Datei landet.

Dabei repariert: `_on_table_row_menu` rief bislang bedingungslos
`self.table.selectRow(index.row())` auf — ein Rechtsklick INNERHALB
einer bestehenden Mehrfachauswahl hätte diese auf die angeklickte Zeile
zusammengestrichen, noch bevor das Menü überhaupt erscheint. Mehrere
markierte Zeilen wären dadurch nie exportierbar gewesen. Jetzt nur noch,
wenn die geklickte Zeile NICHT schon Teil der Auswahl ist
(`selectionModel().isRowSelected`); ein Rechtsklick außerhalb wählt wie
gewohnt die angeklickte Zeile.

**Export auch im Stash-Baum-Kontextmenü** (Peter, 2026-08-03: "im
Stash-Tree das 'Export visible Items'-Rechtsklick menu auch aufnehmen") —
`StashTree.export_visible_requested` (parameterloses Signal, `ui/
stash_tree.py`) ist an `MainWindow._export_csv` verdrahtet, exakt
dieselbe Methode wie der Toolbar-Button. Der Eintrag steht überall im
Kontextmenü zur Verfügung (Fach, Ordner, leerer Bereich) — er bezieht
sich auf das, was gerade in der Item-Tabelle sichtbar ist, unabhängig
vom angeklickten Knoten, genau wie "Alle öffnen"/"Alle schließen" sich
auf den ganzen Baum statt auf einen einzelnen Knoten beziehen. Bewusst
OHNE Item-Anzahl im Menütext (anders als die beiden Export-Einträge im
Item-Tabellen-Kontextmenü, §oben) — das würde `StashTree` an
`MainWindow.proxy.rowCount()` koppeln, für eine rein kosmetische Zahl.

### 4.23 Stash-Baum-Mehrfachauswahl + Suchfeld-Verhalten

Peter, 2026-08-02, im Anschluss an den CSV-Export: "Wenn ich im
Stash-Tree ein oder mehrere Stashs bzw. Überordner auswähle, soll die
Itemliste dies wiederspiegeln und nur Items aus diesen Ordnern/Tabs
anzeigen. Die Suche sollte meiner Meinung nach Global weiter
funktionieren und beim Auswählen eines Stash-Tabs oder Ordners oder
Characters evtl. sogar gelöscht werden."

**Suchfeld-Teil zuerst umgesetzt, unabhängig von der Mehrfachauswahl.**
`MainWindow._clear_search_field_on_selection()` leert das Suchfeld und
beendet `_search_all_active`, aufgerufen von `_on_stash_selected` und
`_on_character_selected` (nach dem Setzen von `_search_all_active =
False`, NIE davor — sonst würde `.clear()` über
`_on_filter_text_changed` einen Re-Entry in `_leave_search_all()`
auslösen, die selbst wieder eine Ansicht aufbaut, mitten im Aufruf, der
diese Ansicht gerade erst festlegt). Nur bei vorhandenem Text geleert,
sonst löst jeder Klick unnötig den Such-Debounce aus. Bewusst NICHT an
den Refresh-Buttons (Rechtsklick → "Aktualisieren") verdrahtet — Peter
sprach ausdrücklich von "Auswählen", nicht "Aktualisieren".

**Ordner-Klicks waren zuvor komplett wirkungslos** — `_build_node`
(§Modul-Docstring `stash_tree.py`) setzt `_DATA_ROLE` nur auf
Blatt-Knoten, ein Ordner-Klick löste also gar kein `stash_selected`-Signal
aus. Das erklärte einen scheinbar zweiten Bug ("Suchfeld leert sich beim
Special-Ordner nicht") — es war derselbe fehlende Anschluss, nicht ein
zusätzlicher Fehler im Suchfeld-Fix.

**Mehrfachauswahl, `ui/stash_tree.py`:** `ExtendedSelection` statt
`SingleSelection`. `_on_click` liest die AKTUELLE Auswahl
(`selectedItems()`), nicht nur den angeklickten Knoten — bei
Strg-/Umschalt-Klick-Sequenzen hat Qt die Auswahl bereits aktualisiert,
bevor der Slot läuft. Der alte Einzelpfad (`stash_selected`, inklusive
automatischem Nachladen bei Cache-Miss) gilt NUR, wenn genau EIN Knoten
ausgewählt ist UND er selbst ein Blatt-Fach ist — eine STRUKTURELLE,
keine inhaltliche Unterscheidung: ein Ordner mit zufällig nur einem Kind
zählt trotzdem als Mehrfachauswahl (neues Signal `selection_changed`),
sonst wäre für den Nutzer nicht vorhersehbar, ob ein Ordner-Klick einen
Abruf auslöst oder nicht. Ein Strg-Klick, der eine Mehrfachauswahl auf
ein einzelnes Fach zurückstutzt, fällt dagegen zurecht auf den alten Pfad
zurück — der verbleibende Knoten IST dann wieder ein direkt
ausgewähltes Blatt.

`_leaf_ids_under(item)` löst Ordner UND die synthetischen
Map-Sektionsgruppen ("Tier 6", §`group_map_children`) gleich auf: beide
sind im Widget-Baum strukturell identisch (ein Knoten mit Kindern, ohne
eigene `_DATA_ROLE`) — kein Sonderfall für Gruppen nötig, die Rekursion
über den Widget-Baum reicht. `_collect_leaf_ids` dedupliziert (Strg-Klick
auf einen Ordner UND eines seiner eigenen Kinder würde dessen ID sonst
doppelt liefern).

**`MainWindow._show_stash_selection(stash_ids)`, verdrahtet an
`selection_changed`:** zeigt NUR bereits gecachte Items der übergebenen
Fächer — löst NIE selbst einen API-Abruf aus. Kritisch: ein Shift-Klick
über 20 nie geladene Fächer würde sonst 20 Requests auf einmal
abfeuern und das Rate-Limit sprengen (§2, Policy-Fenster). Nicht
gecachte Fächer werden gezählt und in der Statuszeile genannt ("3 tabs
selected: 2 loaded, 1 never loaded … — 142 items"), nicht automatisch
nachgeladen; Laden bleibt eine ausdrückliche Handlung (⟳ oder "Load All
Tabs"). `_showing_aggregate = True` verhindert wie bei den bestehenden
Aggregat-Ansichten, dass ein stiller Hintergrund-Refresh eines EINZELNEN
Fachs (§4.8) die Mehrfachauswahl-Ansicht überschreibt.

**`_current_stash_id`/`_current_character_name`/`_current_tab_name`
bleiben beim Aufruf ABSICHTLICH unverändert** — sie zeigen weiter auf
das zuletzt EINZELN angeklickte Fach bzw. den zuletzt angeklickten
Charakter. Die Refresh-Modi "Single"/"Stash", "Auto" (§_refresh_
current_view) und der Zonenwechsel-Trigger (§4.19) hängen an genau
diesen Feldern und laufen dadurch unbeeinflusst von einer
Mehrfachauswahl im Hintergrund weiter — bewusste Entscheidung
("Mehrfachauswahl ändert daran nichts"), keine Lücke: der zuletzt
individuell gewählte Kontext bleibt so lange "aktuell", bis der Nutzer
wieder etwas EINZELN auswählt. Ein neues Feld
`_current_stash_selection: list[str] | None` trägt stattdessen die
WAS-WIRD-GERADE-ANGEZEIGT-Information für zwei Stellen, die sie
brauchen:

- `_leave_search_all()` prüft `_current_stash_selection` VOR
  `_current_stash_id` — sonst würde das Verlassen einer globalen Suche
  fälschlich zum zuletzt einzeln angeklickten Fach zurückspringen statt
  zur Mehrfachauswahl. Die globale Suche selbst (Peter: "sollte …
  Global weiter funktionieren") bleibt davon unberührt, sie arbeitet
  ohnehin auf `_league_wide_items()` unabhängig von der aktuellen
  Ansicht.
- `_default_export_filename()` leitet daraus einen Dateinamen ab
  ("poe-view2-Standard-3-tabs-selected.csv") statt des irreführenden
  `_current_tab_name`, das ja weiterhin das zuletzt einzeln gewählte
  Fach nennt.

`_current_stash_selection` wird bei jedem anderen View-Wechsel auf
`None` zurückgesetzt (`_on_stash_selected`, `_on_stash_refresh`,
`_show_items`, `_show_special_parent_aggregate`, `_show_aggregate`,
`_show_character_items`, `_on_character_selected`,
`_on_character_refresh`, `_on_league_changed`) — symmetrisch zum
bestehenden Muster bei `_current_stash_id`/`_current_character_name`.

**Bewusst nicht gelöst:** Der Zonenwechsel-Trigger und der gezielte Teil
von "Auto" refreshen weiterhin nur das zuletzt einzeln gewählte Fach im
Hintergrund, nicht alle Fächer einer aktiven Mehrfachauswahl — das wäre
zusätzliche Komplexität für einen Randfall, den Peter nicht angefragt
hat, und die Auswirkung ist harmlos (`_showing_aggregate` verhindert ein
sichtbares Überschreiben, das Fach wird nur im Hintergrund/Cache
aktueller).

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
│ [███████░░] 8/15 · 15 s · next in ~4s  [██░░░░░░] 12/90 · 300 s · ~2:19●│
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
verschwunden.

**Zwei Toolbar-Zeilen** (Peter, 2026-08-01: die erste Zeile wurde bei
schmalerem Fenster am rechten Rand abgeschnitten — Liga-Wahl, Typ-Filter
und Suche waren dann unsichtbar). Zwei getrennte `QToolBar`-Instanzen,
per `self.addToolBarBreak()` zwischen ihnen erzwungen auf zwei Zeilen:
oben Login/Refresh/Mode/Load-All-Tabs/Export/Settings, darunter
Liga-Wahl, Typ-Filter, Suchfeld und Regex-Umschalter — die Widgets, die am
ehesten gleichzeitig gebraucht werden und am meisten horizontalen Platz
beanspruchen.

**Mindestfenstergröße 800x600** (`setMinimumSize`, Peter, 2026-08-01:
"pragmatisch auf die bekannte Größe"), damit die zweite Zeile nie in den
Toolbar-Overflow-Pfeil "…" kollabiert und die Suche verschwinden lässt.
Die Breiten-Schwelle wurde real am Fenster gemessen (NICHT mit dem
Offscreen-Test-Setup — dessen fehlende echte Schriftart verzerrt
Pixelbreiten, siehe FALLSTRICKE #55): Suchfeld weg unterhalb 740px,
wieder da ab 745px. 800px ist bewusst kein exaktes Mindestmaß, sondern
der gängige Standard-Wert mit ordentlichem Puffer; die Höhe 600 ist
ungemessen (kein bekanntes Abschneide-Problem), ebenfalls der übliche
Standard.

**Elemente & Verhalten:**

| Bereich | Widget | Verhalten |
|---|---|---|
| Navigation: Charaktere | `CharacterList` (`QListWidget`) | Bewusst KEIN Tree — Charaktere haben keine Unterstruktur (spart eine Ebene samt Auf- und Zuklapp-Klick). Flach, absteigend nach Level, liga-gefiltert (`MainWindow._apply_character_league_filter`, siehe §5.1). Höhe begrenzt (`setMaximumHeight`), damit der Stash-Baum den meisten Platz bekommt. |
| Navigation: Stash | `StashTree` (`QTreeWidget`), 3 Spalten, **Header sichtbar** | Kein umschließender "Stash"-Wurzelknoten mehr — die Tabs SIND die Top-Level-Einträge (spart eine weitere Ebene). Ordner rekursiv (children), Map-Fächer zusätzlich nach Sektion gruppiert (§4.10). Namensspalte per `QHeaderView.ResizeMode.Interactive` (NICHT `Stretch` — Stretch-Spalten lassen sich in Qt nicht per Maus verbreitern, das war ein echter Bug) mit großzügiger Startbreite, per Header-Rand manuell nachziehbar. Tab-Farbe aus API als kleines Icon-Quadrat VOR dem Namen, bewusst NICHT als Textfarbe (manche API-Farben sind auf dunklem Grund sonst unlesbar). Klick auf Tab → `FetchStashItems`-Job, sofern nicht bereits im Cache. Spalte 2 (**#**) zeigt die Item-Anzahl (eigene Spalte statt "(N Items)"-Text im Namen; Details §4.7.1). Spalte 3 zeigt GENAU EINEN von DREI sich gegenseitig ausschließenden Zuständen (§4.7.1, §4.12): **⬇**-Text, solange nie geladen; ein **⟳-Button mit Alters-Beschriftung** (exakte Uhrzeit "⟳ 14:32:46" bei heute geladenen Daten, sonst "⟳ vor 3d") sobald mindestens einmal geladen — Klick lädt genau diesen Tab bewusst AM Cache vorbei neu (`stash_refresh_requested`-Signal); oder **📴** statt ⟳, solange GGG nicht erreichbar ist (Offline-Modus, §4.12) — derselbe Button, nur die Beschriftung ändert sich, ein Klick versucht trotzdem ein Neuladen. Rechtsklick öffnet ein Kontextmenü mit "🔍 Rohdaten anzeigen" (`raw_data_requested`-Signal, §4.9) — öffnet/aktualisiert den nicht-modalen Rohdaten-Mini-Viewer — sowie "▸ Expand All"/"▾ Collapse All" für den ganzen Baum (§4.7.3), Letzteres unabhängig davon, worauf geklickt wurde. |
| Typ-Filter (Toolbar, neben Liga) | 8× `_TypeFilterCheckBox` (eigene `QCheckBox`-Unterklasse) | Normal/Magic/Rare/Unique/Gem/Currency/Div Card + "Sonstige" (§4.11) — Farbe des Käschchens = Typ-Farbe (Pink für "Sonstige"), Name nur im Tooltip. Alle acht standardmäßig an. Drei Gesten statt reinem An/Aus (Peter, 2026-07-28): ein modifierloser Klick zeigt NUR diesen Typ (`solo_requested`-Signal → `_solo_type_filter`) — der weitaus häufigere Wunsch als "nur diesen einen abwählen"; Strg+Klick bleibt das native `QCheckBox`-Einzel-Umschalten (dazu-/wegnehmen aus einer bereits eingeschränkten Ansicht, per `super().mousePressEvent()` durchgereicht); Strg+Umschalt+Klick oder Doppelklick setzen über `reset_requested` wieder alle Typen an. Ein normaler Doppelklick würde von Qt sonst als zwei Einzelklicks gewertet (Haken am Ende unverändert) — deshalb eigene `mouseDoubleClickEvent`-Behandlung. |
| Item-Tabelle rechts oben | `QTableView` + `QSortFilterProxyModel` | Spalten: Icon, Tab, **Position** ("#3 (4, 7)", Tab-Nummer plus Item-Koordinate, §4.11, unterscheidet gleichnamige Fächer), Name, **Base** (`item.baseType`, z. B. "Sun Plate", "Crimson Jewel" — anders als Name bei Uniques/Rares immer die reine Basis statt des Fantasienamens), Typ, Level, Quality, Stack, iLvl, **Anf.Lvl, Str, Dex, Int** (aus dem `requirements`-Array, §4.11), **Mods** (explicitMods, überwiegend Map-Modifikatoren, Tooltip zeilenweise) und **Value** (poe.ninja-Chaos-Wert × Stack, §4.14; leer bei unbekanntem Preis, unter 1 Chaos dezent Richtung Hintergrund abgeblendet). Klick auf den Spaltenkopf sortiert numerisch über `NUMERIC_SORT_ROLE`, also nach echten Zahlen statt nach Strings; Zeilen ohne Wert ("–") landen unten. Das Suchfeld sucht fächerübergreifend über die ganze Liga und schließt Item-Properties wie "Item Quantity" ein; ein eingebauter Clear-Button leert es, `*` zeigt alles an (gedacht für den Komplett-Export, §4.11). Je Spalte lässt sich über das Header-Rechtsklick-Menü zusätzlich ein Filter-Ausdruck setzen (`>=20`, `<45`, `=Text`, Teilstring), aktive Filter markiert ein 🔍 im Header. Sichtbarkeit UND Reihenfolge sind konfigurierbar (§4.18) — schnelles Ein/Aus per Header-Rechtsklick, volle Kontrolle inkl. Drag&Drop-Reihenfolge über den Settings-Dialog (⚙-Toolbar-Button, Reiter "Columns") — und werden in `%LOCALAPPDATA%/PoE-VIEW2/ui-settings.ini` gespeichert; "Typ" ist standardmäßig aus, da die Rarity bereits die Namensfarbe bestimmt. Die Tab-Spalte verwaltet die Anwendung selbst und ist nicht konfigurierbar: aus bei Einzelfach-Auswahl, an in Aggregat-Ansichten ("Alle Tabs", Spezial-Tab-Elternknoten, liga-weite Suche), wo sie die Herkunft trägt ("Map (Tier 1)"). |
| Item-Detail rechts unten | eigenes Widget | Großes Icon, Name in Rarity-Farbe (frameType) mit Tag-Suffix `[Unidentified, Corrupted]` (nur die zutreffenden Tags), eigene Zeile mit iLvl/Req.Lvl/Req.Str/Dex/Int (dieselben Helfer wie die Tabellenspalten, §4.11 — hier bewusst NUR im Detail-Panel, nicht zusätzlich in der Tabelle), Properties, Mods. Aktualisiert bei Zeilenauswahl. |
| Rate-Limit-Dashboard | `QProgressBar` pro Regel + Status-LED + Countdown | Gefüttert über das Signal `rate_limit_changed` und den 1-Sekunden-Tick (§4.8). Farbe je Regel: grün < 60 %, gelb < 90 %, rot ab 90 %/Wartephase. Countdown zeigt verbleibende Wartezeit; `(Paused)` neben dem Policy-Namen, solange der Refresh-Modus "Pause" aktiv ist. Jedes Regel-Label nennt zusätzlich eine grobe Restzeit bis zur nächsten Absenkung des Zählers (`12/30 · 300 s · next in ~2:19`, §4.8, immer mit `~` — GGGs Zähler sinkt blockweise, nicht gleitend pro Treffer, FALLSTRICKE #45 Runde 6) — ohne sie sieht eine völlig normale Phase, in der noch gar nichts frei werden kann, wie ein Hänger aus. *Intention: Der User soll immer sehen, WARUM die App gerade wartet.* |
| Statusbar | `QStatusBar` + `QProgressBar` (busy) | Login-Status, laufender Job, permanenter GGG-Disclaimer. Die `QProgressBar` läuft mit `setRange(0, 0)` im "busy"-Modus (Qt animiert das eingebaut, kein eigener Timer nötig). Sichtbarkeit hängt am eigenen `busy_changed`-Signal des Workers (`True` rund um jeden Job), NICHT am `status`-Text — siehe §4.5.1 zur Begründung. Ein permanentes **Offline-Banner** ("📴 Offline — GGG nicht erreichbar, zeige zwischengespeicherte Daten", §4.12) erscheint bei Konnektivitätsproblemen — als eigenes Label, damit die nächste "Lade …"-Statusmeldung es nicht überschreibt. Ein zweites permanentes Label (`_stack_sum_label`) zeigt die Summe der Stack-Größe über die aktuell sichtbaren (gefilterten) Zeilen ("Stack total: 12,345") — Items ohne Stack-Größe (Ausrüstung) zählen nicht mit, und die Zeile erscheint NUR, wenn alle stapelbaren Treffer denselben `display_name` tragen (FALLSTRICKE #39: bei "*" oder einer ungefilterten Truhe mit mehreren Currency-Sorten wäre eine Summe über verschiedene Item-Typen hinweg bedeutungslos). Ein drittes permanentes Label (`_value_sum_label`, §4.14) zeigt den Gesamt-Chaos-Wert derselben sichtbaren Zeilen ("Value: 1,234c") — anders als die Stack-Summe AUCH über verschiedene Item-Namen hinweg sinnvoll, erscheint also schon bei einem einzigen Item mit bekanntem Preis. Beide Summen-Labels hängen NUR an `proxy.modelReset` (`_update_summaries`, garantiert genau ein Signal pro `set_items()`) und werden zusätzlich an jeder Stelle, die den Filter ändert, GENAU EINMAL explizit aufgerufen (`_apply_debounced_search_filter`, `_on_type_toggled`, `_apply_column_filter`, `_clear_column_filters`) — NICHT an `layoutChanged`/`rowsInserted`/`-Removed` (FALLSTRICKE #39, zweiter Teil: genau das war der O(n²)-Bug). |

**"Alle Tabs laden" (Bulk) und CSV-Export:** Über den Toolbar-Button "⇊ Alle
Tabs laden" holt der `ApiWorker` (`FetchAllItemsJob`) die Items sämtlicher
Nicht-Ordner-Tabs der aktuellen Liga sequenziell — jeder Tab durchläuft
denselben Rate-Limit-Check wie eine Einzelabfrage, ein `QProgressDialog`
zeigt Fortschritt (`bulk_progress`-Signal) und erlaubt Abbrechen nach dem
aktuellen Tab (`ApiWorker.cancel_bulk()`). Die Reihenfolge (`_load_all_items`)
stellt die ältesten bzw. noch nie geladenen Fächer nach vorne
(`_last_loaded`, `_NEVER_LOADED`-Sentinel wie bei `_pick_stash_mode_candidate`)
— bricht der Nutzer über "Abbrechen" vorzeitig ab, sind die dringendsten
Fächer schon durch, nicht die per Zufall der Truhen-Reihenfolge nach vorne
gerutschten.

Zwischen zwei Tabs wartet die Schleife einen **gleichmäßigen Takt** aus
`steady_pace_interval_s()` — dieselbe Rate wie der Stash-Refresh-Modus
(§4.8, bei 30 Anfragen/300s rund 11s je Tab), nur einmal durch alle Fächer
statt endlos. Ohne diese Bremse feuerte die Schleife die Tabs so schnell
wie möglich durch, füllte binnen ~29 Tabs das Rate-Limit-Fenster und lief
in die 300-Sekunden-Zwangspause (dieselbe Mechanik wie FALLSTRICKE #34).
Der Durchsatz ist dadurch nicht geringer, nur gleichmäßig statt "Sprint,
dann fünf Minuten Stillstand" — und der Fortschrittsbalken läuft sichtbar
weiter. Gewartet wird über `_cancel_bulk.wait(...)` statt `time.sleep`,
damit "Abbrechen" sofort greift und nicht erst den Takt aussitzen muss.
**Fortschritt wird in ZWEI Einheiten gemeldet** (`bulk_progress` überträgt
einen `BulkProgress`-Datensatz statt einzelner Signal-Parameter — bei acht
Feldern wäre am Empfänger nicht mehr zu erkennen, welche Zahl welche ist),
weil keine allein genügt:

- **Truhenplätze** beantworten "wie viele meiner Fächer sind durch". Eine
  Map-/Unique-Sektion braucht zwar einen eigenen Request, teilt sich aber
  den Platz ihres Eltern-Tabs; `FetchAllItemsJob` bekommt dafür
  `positions` (`_tab_positions()`) mit. Ohne diese Gruppierung zeigte der
  Dialog "58/561" (ladbare Einheiten) statt "58/391" (echte Fächer) —
  FALLSTRICKE #37.
- **Abrufe** sind die Einheit, in der die Arbeit tatsächlich anfällt, und
  daher das Maximum des `QProgressDialog`. An Truhenplätzen gemessen
  stünde der Balken bei einem großen Spezial-Tab sehr lange still: in
  Peters SSF-Liga bündelt ein MapStash 365 Sektionen auf einem Platz —
  67 Minuten unveränderte Anzeige, bei insgesamt 1088 Abrufen gegenüber
  519 Plätzen (FALLSTRICKE #42).

Der Balken läuft also über die Abrufe, das Label nennt beide Zahlen
("Section 128 of 1088 · tab 3 of 519"). Beide Angaben sind korrekt —
falsch war nie die Zahl, sondern sie als "stash tabs" zu beschriften.

**Restzeit** kommt aus `max(steady_pace_interval_s(), elapsed /
done_requests)`. Reines `elapsed / done` wäre am Anfang grob zu
optimistisch, weil der erste Abruf ohne Taktpause läuft — bei 1088
Abrufen hätte der Dialog "etwa 5 min" für einen real dreistündigen Lauf
angezeigt. Der Soll-Takt trägt die Schätzung ab dem ersten Tick, die
Messung übernimmt, sobald Rate-Limit-Zwangspausen die Lage tatsächlich
verschlechtert haben.

**Sekunden-Countdown und Baum-Fokus** (Peter, 2026-07-30). Zwischen zwei
Abrufen liegen ~11s, gelegentlich eine mehrminütige Zwangspause — ohne
Countdown ist beides von außen nicht von einem Absturz zu unterscheiden
(dieselbe Rückfrage wie beim Auto-Refresh: "ca. 5 Minuten gewartet ohne
dass irgendwas passiert ist"). Der Dialog zeigt deshalb eine Zeile
"Next tab in 8s" bzw. "⏸ Rate limit — resuming in 287s". Zwei Details:

- Der Worker meldet die kommende Taktpause selbst mit (`next_wait_s`) —
  es ist exakt die Pause, die seine Schleife gleich abwartet, also keine
  Schätzung der UI. Heruntergezählt wird im ohnehin laufenden
  1-Sekunden-Tick (`_update_auto_refresh_countdown` → `_update_bulk_label`),
  ein eigener `QTimer` wäre überflüssig.
- Die Rate-Limit-Zwangspause kommt NICHT aus `snapshot()`: Sie ist selbst
  auferlegt (Fenster voll, kein HTTP 429) und steckt deshalb in keinem
  Header. Einzige Quelle ist der Sekunden-Countdown des
  `RateLimitManager` über `rate_limit_changed`, den `_on_rate_limit_changed`
  jetzt mitschneidet, statt ihn nur ans Dashboard durchzureichen. Sie hat
  Vorrang vor dem 11s-Takt.

Parallel wandert die Auswahl im Stash-Baum auf das gerade abgerufene Fach
(`StashTree.highlight_stash`, klappt Eltern-Ordner auf und scrollt hin).
Bewusst über `highlight_stash` und nicht über einen simulierten Klick: das
löst kein `stash_selected` aus, die Item-Tabelle wird also nicht bei jedem
Tick umgeschaltet. Dafür trägt `BulkProgress` die `stash_id` mit — Namen
allein reichen nicht, Map-/Unique-Sektionen tragen dieselben.

Solange der Bulk-Dialog offen ist, pausiert der Refresh-Modus
(`_drive_refresh_mode`) — sonst liefen beide Taktgeber parallel und
verdoppelten die Anfragerate. Nach Abschluss zeigt die
Item-Tabelle alle geladenen Tabs zusammen (`MainWindow._show_aggregate`) —
dafür trägt jede Zeile in der neuen **Tab-Spalte** ihren Herkunfts-Tab, damit
der Bezug beim Filtern/Sortieren über den gesamten Stash nicht verloren geht.
Der Toolbar-Button "💾 CSV exportieren" schreibt die aktuell sichtbaren
(gefilterten) Zeilen — egal ob Einzeltab oder Aggregat — über
`services/csv_export.py` als Semikolon-CSV mit UTF-8-BOM (Excel/de-DE-kompatibel);
Spaltensatz und der zweite Export-Weg per Rechtsklick sind in §4.22
beschrieben. Der Speicherdialog startet im echten Windows-Downloads-Ordner
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
Charaktere/Stash konsistent liga-scoped.

**Sortierung/Gliederung des Liga-Dropdowns
(`MainWindow._rebuild_league_combo`):** Gültige (Live-)
Ligen stehen oben, abgelaufene — nur noch im Datei-Cache vorhandene, von
GGG nicht mehr gelistete — Ligen darunter, per einer nicht-anwählbaren
Überschrift-Zeile ("── Beendete Ligen (nur Cache, kein Online-Zugriff) ──",
`_ARCHIVED_HEADER`, per `QStandardItem.setEnabled(False)` deaktiviert)
abgetrennt — bewusst KEIN blanker `insertSeparator`, damit für den Nutzer
explizit sichtbar ist, WARUM diese Ligen unten stehen ("als Offline-Liga
anhängen"), nicht nur eine positionelle Trennung.
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

**Archivierte Ligen: kein Online-Zugriff mehr (Liga-Start
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
(grün). Gem und Divination Card haben einen deutlichen Hue-Abstand: Gem
zieht Richtung Grün, Divination Card Richtung Blau. Die ursprünglichen
Töne #3fb8ae und #0ebac5 waren nebeneinander kaum zu unterscheiden.

---

## 6. Fehlerbehandlung & Robustheit

- **HTTP 401:** Token abgelaufen → Signal an UI → Login-Dialog anbieten.
- **HTTP 429:** Sollte durch den Rate-Limiter nie auftreten. Falls doch:
  `Retry-After`-Header respektieren, State als "gesperrt" markieren,
  Dashboard rot, einmaliger Retry. Vorfall loggen (Hinweis auf Parser-Lücke).
- **Netzwerkfehler:** Job schlägt fehl → `error`-Signal → nicht-modale
  Statusmeldung; kein automatischer Endlos-Retry.
- **Logging:** `logging`-Modul, Datei in `%LOCALAPPDATA%/PoE-VIEW2/logs/`.
  Alle Requests werden mit ihren Policy-Headern protokolliert. Diese
  Logdatei ist die wichtigste Grundlage für Rate-Limit-Analysen und hat
  bereits mehrfach Fehlerursachen aufgedeckt (FALLSTRICKE #28, #30).

## 7. Security & Open Source

- Client-ID und Kontaktadresse haben funktionierende Standardwerte in
  `config.py`; `.env` (Vorlage: `.env.example`) überschreibt sie nur bei
  Bedarf und steht in `.gitignore`. Als *public client* mit PKCE gibt es
  **kein** Client-Secret — es gibt also nichts Geheimes zu verteilen.
- Access-Token nur im Windows Credential Manager, nie auf Platte/im Repo.
- Disclaimer in UI (Statusbar + Über-Dialog) und README:
  *"This product isn't affiliated with or endorsed by Grinding Gear Games in any way."*
- Lizenz: MIT (siehe `LICENSE`).

### 7.1 Kontaktadresse im User-Agent

GGG schreibt das Format `OAuth {clientId}/{version} (contact: {contact})`
vor ([Doku](https://www.pathofexile.com/developer/docs)). Der Kontakt
identifiziert laut Doku und GGGs eigenem Beispiel die **Anwendung bzw.
deren Betreiber**, nicht den einzelnen Endnutzer — deshalb steht in
`config.DEFAULT_CONTACT_EMAIL` eine feste, bewusst öffentliche
Projekt-Adresse, und Nutzer einer fertigen `.exe` müssen nichts
konfigurieren. Das ist ein eigens angelegter Alias, **keine private
Adresse** (die Regel aus FALLSTRICKE #3 gilt unverändert weiter).

Wer PoE-VIEW2 forkt und selbst verteilt, sollte `POE_CONTACT_EMAIL` per
`.env` auf die eigene Adresse setzen — sonst landen GGG-Rückfragen zur
fremden Distribution beim ursprünglichen Autor.

## 8. Entwicklungsstand

Die ursprünglich geplanten Meilensteine (Grundgerüst, Authentifizierung,
Rate-Limiter, Datenschicht, UI, Politur) sind abgeschlossen. Seither sind
zahlreiche Funktionen hinzugekommen, die nicht Teil der ersten Planung
waren: Offline-Modus, Charakter-Ausrüstung, Typ- und Spalten-Filter,
liga-weite Suche, Auto-Refresh und die Behandlung archivierter Ligen.

Der aktuelle Stand lässt sich über den [CHANGELOG](../CHANGELOG.md) und
die Git-Historie nachvollziehen; die technischen Hintergründe einzelner
Entscheidungen stehen in
[FALLSTRICKE_UND_WORKAROUNDS.md](../FALLSTRICKE_UND_WORKAROUNDS.md).

Eine Reihenfolge-Empfehlung aus der Anfangszeit gilt weiterhin: Der
Rate-Limiter muss stehen, bevor die ersten umfangreichen API-Abfragen
laufen.
