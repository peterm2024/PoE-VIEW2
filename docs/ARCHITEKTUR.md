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
│   └── api-notes/
│       ├── ggg-api.md          ← Form der API: Endpunkte, JSON, OAuth
│       └── poe-verhalten.md    ← Verhalten von Spiel und Server über die Zeit
│                                 (englisch, siehe Kopf der Datei)
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
│   │   ├── cache_writer.py     # schreibt ihn im Hintergrund (§4.37)
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

**Was die Charakter-Antwort sonst noch trägt, steht seit dem 2026-08-24
im Log.** Anlass war Peters Frage "Bekommen wir eigentlich die aktuelle
Goldmenge angezeigt?", die sich nicht beantworten ließ: Die Rohantwort
wird nirgends aufgehoben, `get_character_items()` liest gezielt die
bekannten Schlüssel heraus, und das Rohdaten-Fenster (§4.9) gibt es nur
für Truhenfächer. Alles Übrige war damit unsichtbar.

`_log_character_fields()` schreibt deshalb **einmal je Sitzung** eine
Zeile mit allen Feldern der Antwort und nennt getrennt, welche davon
ungenutzt bleiben. Nur die Form, keine Werte (`inventory[12]`,
`metadata{version}`, `level`) — ein voller Charakter wären jedes Mal
einige hundert Kilobyte Log, die alles andere verdecken. Eine leere
Antwort verbraucht den einen Schuss nicht, sonst hätte ein
fehlgeschlagener erster Abruf die Frage für die ganze Sitzung
unbeantwortbar gemacht.

Das kostet **keinen zusätzlichen Request**: Der Abruf läuft ohnehin alle
paar Sekunden, solange ein Charakter offen ist. Genau so ist die
XP/h-Anzeige entstanden (§4.33) — `level` und `experience` lagen längst
in jeder Antwort und wurden stillschweigend verworfen. Die Zeile ist die
Verallgemeinerung dieser Lehre: nicht raten, was mitkommt, sondern es
einmal aufschreiben.

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
  Policy, siehe FALLSTRICKE #33. Der Nenner kommt aus `_pacing_budget()`,
  abgerundet und um eins verringert: ein Takt, der seine Schwelle exakt
  trifft, löst im Dauerbetrieb genau die Sperre aus, die er verhindern
  soll (FALLSTRICKE #34). Bei 30/300s ergibt das 300/23 ≈ 13,0s.
- `_pacing_budget(rule)` — **die eine Zahl, aus der sowohl der Takt als
  auch die Notbremse abgeleitet werden** (`(max_hits - SAFETY_MARGIN) *
  PACING_FILL_LIMIT`, bei 30/300s also 24,65). Bis 2026-08-05 hatten die
  beiden getrennte Vorstellungen davon: Der Takt rechnete mit 28 Treffern,
  die Bremse stoppte bei 24,65 — der Takt zielte also auf ein Budget, das
  die Bremse gar nicht zuließ, und lief im Dauerbetrieb zwangsläufig
  hinein. An Peters Log vom 2026-08-04 nachgerechnet: 26 Abrufe im
  Fenster vor der Bremse, davon 23 allein vom Takt; drei
  Zonenwechsel-Refreshs kippten es, Ergebnis war eine fünfminütige
  Zwangspause (FALLSTRICKE #64). Peters Entscheidung am 2026-08-06:
  "machen wir 15% langsamer" — seltenere Zwangspausen sind ihm den
  längeren Takt wert. Die Bremsschwelle selbst blieb dabei unverändert;
  nur der Takt leitet sich neu ab. Ein Eigenschafts-Test über mehrere
  Kontingente hält beide aneinander, damit sie nicht wieder auseinander
  laufen.
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
  `properties: list[ItemProperty]`, sockets, `flavourText: list[str]`,
  `artFilename` (nur Divination Cards), …
- `ItemProperty`: name, `values: list[tuple[str, int]]`

**`explicitMods`/`implicitMods`: Einträge können String oder Objekt sein.**
GGG liefert für manche Items, etwa Currency-Beschreibungstexte, einzelne
Mod-Einträge als `{"description": "..."}`-Objekt statt als String. Ohne
Gegenmaßnahme scheitert die pydantic-Validierung für den gesamten
Stash-Tab, nicht nur für das betroffene Item. Ein
`field_validator(mode="before")` auf `Item` reduziert jeden dict-Eintrag
vor der Typprüfung auf sein `description`-Feld; Strings bleiben
unverändert (siehe FALLSTRICKE_UND_WORKAROUNDS.md #25).

**GGGs Färbungs-Markup: camelCase roh, snake_case fertig.** Mod-Texte sind
für den Tooltip des Spiels formatiert: `<currencyitem>{3x Orb of Fusing}`
bestimmt die Farbe, `<size:26>{…}` zusätzlich die Schriftgröße, und beides
kann ineinander verschachtelt sein.

Das Feld `explicitMods` trägt deshalb weiterhin GENAU DAS, was die API
geliefert hat; die Eigenschaften `explicit_mods`/`implicit_mods` daneben
liefern denselben Text ohne Markup. Dieselbe Trennung wie bei
`display_name`, `socket_string`, `flavour_text` — camelCase ist die
Rohantwort, snake_case das, was man anzeigt. Jede Anzeige, der CSV-Export
und der Suchindex nehmen die snake_case-Fassung.

Warum nicht schon im Validator filtern (so war es einen Tag lang): Der
Daten-Cache serialisiert die Modelle. Was das Feld verliert, verliert die
Cache-Datei beim nächsten Speichern dauerhaft — und mit der Farbangabe
verschwände die einzige Auskunft darüber, ob eine Karte eine Währung oder
ein Unique verspricht. Genau das ist am 2026-08-06 einmal passiert, siehe
FALLSTRICKE #66.

`strip_display_markup()` ersetzt von innen nach außen, bis sich nichts
mehr ändert, und vereinheitlicht die Zeilenenden (`\r\n` und einzelnes
`\r` → `\n`; ein stehengebliebenes `\r` zeichnet Qt als Ersatzkästchen).
`markup_segments()` ist das Gegenstück: Es wirft die Auszeichnung nicht
weg, sondern gibt `(Farbname, Text)`-Abschnitte zurück — die Grundlage der
farbigen Belohnungszeile in §4.17.

Eine zweite, ganz andere Auszeichnung sind DOPPELTE spitze Klammern
(`<<HBGAa>><<HBG01>>`): Verweise auf eine Runen-Schrift, die wir nicht
haben. Sie fallen weg. Nur die doppelte Form — eine Regel, die alles in
spitzen Klammern entfernt, verschluckt auch echten Text ("Bows &
&lt;Wands&gt;"), und zwar unbemerkt. Bleibt umgekehrt eine unpaarige
Auszeichnung stehen, ist sie im Fenster zu sehen und damit zu bemerken.

**`flavourText` ist eine Liste, deren Markup die ganze Liste umschließt.**
Die API liefert den Spruchtext zeilenweise, aber `<size:24>{` steht in der
ersten und die schließende Klammer in der letzten Zeile. Deshalb gibt es
dafür keinen Validator, sondern die Eigenschaft `Item.flavour_text`: erst
zusammenfügen, dann filtern. Bleibt nichts Lesbares übrig — drei Items
tragen statt Text nur Verweise auf eine Runen-Schrift, zwei Karten
liefern von GGG selbst nur ein Leerzeichen —, ist das Ergebnis leer, und
die Anzeige lässt die Zeile ganz weg.

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
- **Vollständig oder gar nicht** (`services/atomic_json.py`, seit
  2026-08-05): geschrieben wird erst in eine Nebendatei mit Prozess-ID im
  Namen, dann per `os.replace` an ihren Platz geschoben — auf einem
  Laufwerk atomar. Vorher ging der Schreibvorgang direkt in die Zieldatei,
  und bei 52 MB dauert das lange genug, dass ein Absturz oder eine zweite
  Programminstanz ein Fragment hinterlassen könnte (FALLSTRICKE #65).
  Wichtig ist dabei das Zusammenspiel mit dem Überschreibschutz aus §4.24:
  Der vergleicht gegen den zuletzt GESCHRIEBENEN Umfang, und der ist nach
  einer unlesbaren Datei 0 — die kaputte Datei hätte ihn also stillgelegt,
  statt von ihm aufgefangen zu werden. Derselbe Weg schützt den
  Preis-Cache (§4.14).
- **Nur eine Instanz je Konto bewirtschaftet die Datei**
  (`services/instance_lock.py`, Peter 2026-08-05: "Zweitstart theoretisch
  ja, aber nur im Offline-Modus bzw. anderer Account"). Der Anspruch gilt
  PRO KONTO, nicht pro Programm: Zwei Fenster mit verschiedenen Konten
  schreiben in getrennte Dateien und verbrauchen getrennte
  Rate-Limit-Budgets (GGG zählt pro Konto, FALLSTRICKE #65). Bekommt eine
  Instanz das Konto nicht, läuft sie nur lesend — der Cache bleibt
  vollständig durchsuchbar, aber sie ruft nichts ab und schreibt nichts.
  Meldet sie sich mit einem anderen Konto an, wird sie vollwertig.
  Umgesetzt als Byte-Bereichs-Sperre (`msvcrt.locking`) statt einer
  Marker-Datei: Die Sperre hängt am Prozess und verschwindet mit ihm, es
  kann also keine verwaiste Sperre geben, die jemand aufräumen müsste.
  **Der Schutz sitzt im Worker** (`ApiWorker._skip_read_only`), nicht in
  den Klick-Handlern: Daten-Jobs entstehen an einem knappen Dutzend
  Stellen, und die nächste neue fiele sonst durch — dieselbe Überlegung
  wie beim pfad-unabhängigen Überschreibschutz (§4.24). Die gesperrten
  Knöpfe in der Oberfläche sind nur Höflichkeit, damit niemand ins Leere
  klickt.
- **Sicherung bei jedem Start** (`services/cache_backup.py`, Peter
  2026-08-06: "ein Backup mit Timestamp, das erst nach 24h gelöscht werden
  darf"). `MainWindow._backup_cached_data` läuft direkt nach
  `_restore_cached_data` und lange vor dem ersten `_persist_cache` — dem
  einzigen Zeitpunkt, an dem die Datei garantiert den Stand der VORIGEN
  Sitzung trägt.

  Die drei vorigen Cache-Schäden (#62 Datenverlust beim Ab- und
  Wieder-Anmelden, #65 zwei Instanzen, #66 ein Filter im Datenmodell, der
  sich beim Speichern durchschrieb) wurden je mit einem gezielten Wächter
  gegen genau ihren Fehler behoben. Die Sicherung ist die allgemeine
  Antwort: Sie greift auch gegen den Fehler, den noch niemand
  vorhergesehen hat.

  **gzip -6, an der echten Datei gemessen** (67,5 MB, 2026-08-06):
  kopieren 0,02 s / 67,5 MB · gzip -1 0,12 s / 12,4 MB · **gzip -6 0,33 s
  / 7,5 MB** · gzip -9 0,51 s / 7,7 MB. `-9` ist hier langsamer UND
  größer, kein Tippfehler. Erst durch die Kompression wird die
  24-Stunden-Regel bezahlbar: ein Tag voller Sicherungen kostet Megabytes
  statt Gigabytes. Bewusst synchron — eine Sicherung, die nebenher
  entsteht, könnte mit dem ersten Schreibvorgang um dieselbe Datei rennen,
  also mit genau dem, wogegen sie schützt.

  Vier Regeln, jede aus einem konkreten Versagen heraus: **Anlegen vor
  Aufräumen** (bräche das Anlegen ab, wären sonst die alten weg und die
  neue nicht da). **Die neueste bleibt immer** (sonst stünde man nach zwei
  Wochen Pause ganz ohne Sicherung da). **Unverändert wird nicht
  gesichert** — verglichen wird die mtime der Quelle mit dem Zeitstempel
  der neuesten Sicherung; ohne das verdrängten drei Neustarts hintereinander
  ältere, tatsächlich verschiedene Stände. **Fremde Dateien werden nie
  angefasst**: Der Zeitpunkt wird aus dem Dateinamen gelesen, was sich
  nicht als unsere Sicherung ausweist, bleibt liegen.

  `MAX_COUNT` ist nur eine Rückfallgrenze für den Fall, den die
  Altersregel nicht abdeckt (Neustart im Minutentakt mit Abrufen
  dazwischen). Zurückgespielt wird von Hand über den Explorer — kein
  Knopf, dieselbe Überlegung wie beim fehlenden Löschen-Knopf (Peter,
  2026-08-04: "zu gefährlich"). Das Hilfe-Fenster beschreibt den Weg.
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

Der Auto-Modus hat zwei Pflichten und erledigt je Takt genau **eine**,
abwechselnd:

1. **Das gerade angezeigte Fach ODER der gerade angezeigte Charakter**
   (`MainWindow._current_stash_id` bzw. `_current_character_name`, beide
   schließen sich gegenseitig aus — siehe §4.13) — IMMER, unabhängig vom
   Alter (die 1-Tag-Schonfrist des Sweeps unten gilt hier nicht), damit
   die aktuell geöffnete Ansicht "lebt". Ist die
   Aggregat-/Alle-Tabs-Ansicht aktiv, sind beide `None` und dieser Schritt
   entfällt. Charaktere haben KEINEN eigenen Sweep (siehe §4.13) — nur
   das gerade offene Fach ODER der gerade offene Charakter wird hier
   behandelt, nie beide gleichzeitig.
2. **Der Sweep** (`_drive_auto_sweep`) — frischt nach und nach den Rest
   der Truhe auf.

Liefert die Pflicht, die gerade an der Reihe ist, nichts (nichts
geöffnet bzw. kein Sweep-Kandidat), übernimmt die andere noch im SELBEN
Takt, statt ihn verfallen zu lassen.

**Korrektur (FALLSTRICKE #27):** Ein stiller (`silent=True`) Treffer für
GENAU das gerade offene Einzelfach zeichnet inzwischen auch die sichtbare
Tabelle neu (`MainWindow._on_stash_items` prüft zusätzlich
`stash_id == self._current_stash_id`) — ursprünglich aktualisierte der
Live-Refresh nur den Cache/die Alters-Anzeige im Baum, nicht die Tabelle
selbst, "lebte" also gar nicht sichtbar. Ein stiller Treffer für ein
ANDERES Fach (der Sweep-Kandidat) oder während einer Aggregat-/Such-
Ansicht bleibt weiterhin unangetastet.

**Der Takt kommt vom Rate-Limiter, nicht aus einer Konstante**
(FALLSTRICKE #72). Bis 2026-08-21 hing Auto an einem eigenen `QTimer` mit
festen `AUTO_REFRESH_INTERVAL_MS` (40 s) und war damit der einzige Modus,
der GGGs tatsächliches Budget nicht las. An Peters echtem Log gemessen
(Sitzung 2026-08-21, 00:13–02:30): 195 Charakter-Abrufe, wo unter dem
Takt, den Single/Stash längst fahren, 632 hineingepasst hätten; das
300-s-Fenster stand im Median bei 8 von 30 Treffern. Auto steht deshalb
jetzt mit in `STEPPING_REFRESH_MODES` und hängt an derselben
`_drive_refresh_mode`-Kette (unten) — der eigene Timer ist entfallen.

Dass es bei EINEM Job je Takt bleibt, ist dabei kein Detail: Der
gerechnete Takt beschreibt den Abstand zwischen zwei *Requests*, nicht
zwischen zwei Ticks. Beide Pflichten in einem Takt wären der doppelte
Durchsatz, den die Rechnung zulässt — genau der Fehler hinter FALLSTRICKE
#34 und #47. Der frühere Schutz gegen einen Doppel-Abruf (Sweep-Kandidat
gegen `_current_stash_id` prüfen) ist dafür entfallen: Zwischen beiden
Pflichten liegt jetzt ein voller Takt, in dem das offene Fach seinen
Zeitstempel bereits aufgefrischt hat — es ist danach das jüngste und wird
von beiden Kandidatenauswahlen ("ältester zuerst") von selbst gemieden.

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

**Rückfall auf den Stash-Rundlauf (`_drive_auto_sweep`).** Die 1-Tag-Regel
oben lässt in einer durchgeladenen Liga — dem Normalfall — irgendwann
KEINEN Kandidaten mehr übrig, und dann tat der Sweep früher schlicht
nichts: In Peters Log vom 2026-08-21 ging zwischen 00:14 und 01:30, also
76 Minuten lang, kein einziger Sweep-Abruf raus, ohne jede Spur in der
Oberfläche (FALLSTRICKE #72). Liefert `_pick_auto_refresh_candidate`
nichts, übernimmt deshalb `_pick_stash_mode_candidate` — derselbe
Rundlauf, den der Stash-Modus fährt (gefüllte Fächer vor leeren,
Remove-only zuletzt, Fach-Liste am Rundenende). Die 1-Tag-Regel bleibt
trotzdem vorne: Sie beantwortet eine andere Frage als der Rundlauf — sie
holt Unbekanntes nach, er hält Bekanntes frisch. Weil Auto damit auch
`_stash_mode_list_refresh_due` erbt, wertet `_drive_auto_sweep` das Flag
mit aus; sonst bliebe es für immer stehen (nur der Stash-Modus setzt es
sonst zurück) und eine im Spiel umsortierte Truhe unentdeckt.

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
per `QTimer`) zeigt zusätzlich entweder "&lt;Modus&gt; — next update in Xs"
(aus `_refresh_mode_next_due`) oder den Grund, warum der nächste Takt
nichts täte (`_refresh_idle_reason()`; im Auto-Modus zusätzlich
`_auto_refresh_blocked_reason()` — no league, busy, not logged in, league
ended, rate limit budget) — Anzeige und tatsächliches Verhalten
teilen sich dieselbe Guard-Methode, damit sie nie auseinanderlaufen.
Derselbe Sekunden-Tick treibt auch die Takt-Kette aller Modi an
(`_drive_refresh_mode`, unten) und ruft `RateLimitManager.snapshot()` ab und füttert
damit das Rate-Limit-Dashboard, unabhängig von echten Requests (siehe
§4.3, FALLSTRICKE #32).

**Refresh-Modus (`MainWindow._drive_refresh_mode`):** Ein Dropdown in der
Toolbar ("Mode: Auto / Single / Stash / Pause", additiv neben dem normalen
"Refresh"-Button) schaltet zwischen vier Strategien um:

- **Auto** — das oben beschriebene Verhalten (Standard): abwechselnd
  offene Ansicht und Sweep, im selben Takt wie die beiden folgenden Modi,
  aber mit der zusätzlichen Notreserve `AUTO_REFRESH_MIN_HEADROOM` für
  manuelle Klicks. Rechnerisch kommt damit jede der beiden Pflichten auf
  den doppelten Takt-Abstand (bei 30/300 s also rund 26 s) — mehr als die
  40 s von früher, und der Sweep läuft überhaupt erst wieder.
- **Single** — hält ausschließlich die aktuell gewählte Zeile (Fach oder
  Charakter, `_pick_single_target`) aktuell, im Takt von
  `steady_pace_interval_s()`. Weiterhin der schnellste Weg für EINE
  Ansicht: Ohne zweite Pflicht bekommt sie jeden Takt (rund 13 s).
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
`_on_stash_list` vor dem Merge und beim Cache-Laden
(`_restore_cached_data`), damit
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

**Zwei Vervollständigungen nebeneinander** (2026-08-06): Peter meldete
den Wunsch erneut an und präzisierte ihn: "direkt hinter dem Cursor
erscheint schon der passende Text, den ich nur noch durch Tab oder
return bestätigen muss." Gemeint war also die INLINE-Ergänzung, nicht die
Popup-Liste — die gab es seit dem 02.08., er hatte sie beim Arbeiten
schlicht nicht als das wahrgenommen, was er suchte. Beide bleiben
nebeneinander, weil sie Verschiedenes können: Die Inline-Ergänzung
(`_InlineCompleteLineEdit`) braucht einen PRÄFIX ("Main" →
"MainInventory") und setzt den Rest markiert hinter den Cursor; die
Popup-Liste sucht per Teilstring und findet "MainInventory" auch bei der
Eingabe "inv". Ergänzt wird ausschließlich beim WACHSEN der Eingabe —
sonst löscht die Rücktaste nur die Markierung, der Vorschlag steht sofort
wieder da, und man kommt nie mehr heraus. Eingesetzt wird der komplette
Treffer statt "Getipptes + Rest", damit im Feld am Ende genau die
Schreibweise steht, die in der Spalte vorkommt.

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

**Mehrere Begriffe, UND-verknüpft (2026-08-13).** Peter, mit dem
Hilfe-Fenster der Spiel-eigenen Truhensuche als Vorlage: "Bin mit der
Suche bei uns noch nicht zu 100% zufrieden." Bis dahin war der Suchtext
EIN Muster — `life resistance` fand nur Items, bei denen die beiden
Wörter buchstäblich nebeneinander stehen, und das kommt in Mod-Texten
praktisch nie vor. **38.128 der 59.042 Items in Peters Bestand (64,6 %)
tragen zwei oder mehr Mod-Zeilen**, und genau dort will man kombinieren.

Jetzt dieselbe Regel wie im Spiel: Leerzeichen trennen Begriffe, ALLE
müssen zutreffen, Anführungszeichen fassen einen mehrwortigen Begriff
zusammen. An Peters echten 715 Allflame-Items: `life resistance` 60
Treffer, `chaos resistance life` grenzt auf 4 ein, `"maximum life"`
schneidet gegenüber `maximum life` drei falsche weg.

Dass am Leerzeichen getrennt werden DARF, hängt an einer Eigenschaft der
poe.re-Muster: Sie enthalten keine Leerzeichen und bleiben deshalb ein
einziger Begriff. Ein Muster MIT Leerzeichen gehört ab jetzt in
Anführungszeichen — die einzige bewusste Verhaltensänderung, mit eigenem
Test festgehalten statt verschwiegen.

`compile_search()` (item_table.py) liefert die `SearchQuery` und wird von
BEIDEN Suchpfaden genutzt — dem Proxy und der On-Demand-Suche für große
Ligen (`_run_large_search`, §FALLSTRICKE #40) —, damit der Umschalter
überall identisch wirkt. Ein ungültiges Muster (beim Tippen praktisch
immer kurz der Fall, etwa nach einer offenen Klammer) fällt für SEINEN
Begriff still auf die Teilstring-Suche zurück, statt die Liste leerlaufen
zu lassen; dasselbe gilt für ein noch offenes Anführungszeichen, das bis
zum Zeilenende gilt.

**Sockel-Gems stehen mit im Suchindex**, wie im Spiel ("The Gems and
Microtransactions of those items are also searched"). Betrifft nur 125
Items in Peters Bestand — aber das sind die angelegten, und "wo steckt
eigentlich meine Determination?" ist genau die Frage, für die man sonst
jedes Teil einzeln anklickt.

**Feld-Suchen `ilvl:84` und `tier:16`**, ebenfalls aus der Spielsuche
("Search for item level by typing ilvl:X"). Peter: "Wir haben das zwar
schon über die Spalten gelöst, aber wenn jemand das genauso sucht, STRG+F
und dann ilvl:84, dann freut man sich wenn es funktioniert." **Exakt,
nicht "mindestens"** — von Peter bestätigt statt geraten; für Bereiche
bleiben die Spalten-Filter.

Umgesetzt als Marke IM Suchindex (`_field_tokens`: das Item bringt
"ilvl:84" als eigenes Wort mit) plus ein auf Wortgrenzen festgenageltes
Muster für den Begriff. Dadurch funktioniert es in beiden Suchpfaden ohne
Extralogik, und `ilvl:8` findet nicht alles von 80 bis 89. `ilvl:>=84`
bleibt bewusst ein gewöhnlicher Begriff und findet nichts, statt
stillschweigend etwas anderes zu tun, als dort steht.

**Woher die Tier kommt, war eine Messung wert.** Die erste Fassung las
eine Property "Map Tier" — und fand auf echten Daten nichts: Über 59.042
Items trägt KEIN EINZIGES diese Property, 13.417 tragen die Tier im
`typeLine` ("Map (Tier 6)", "Valdo's Map (Tier 11)"). Gegen die eigenen
Demo-Daten, in denen die Property erfunden war, sah alles richtig aus;
sichtbar wurde es erst bei der Gegenprobe am echten Cache. An allen
58.607 Items: `tier:6` 786 Treffer, `tier:16` 1362, `ilvl:84` 4510.

**Strg+F** (`MainWindow._focus_search_field`) springt ins Suchfeld und
MARKIERT den vorhandenen Text: Ein zweites Strg+F überschreibt die alte
Suche durch bloßes Tippen, lässt sie aber stehen, wenn man doch nur etwas
anhängen will. Der Modus wird in `ui-settings.ini`
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
- **`ApiError` mit 400 und der Begründung "League not found"** → ebenfalls
  Wartung, siehe unten. Die einzige gemessene 4xx-Ausnahme.
- Alles andere (4xx, `AuthError`, …) bleibt ein normaler Fehler.

**Die 4xx-Ausnahme, und warum sie so eng gefasst ist.** Die Regel "5xx ist
der Server, 4xx sind wir" hielt bis zum 2026-08-13. Peters Log jener
Nacht zeigt eine Wartung von 01:03:41 bis 01:17:41, 22 Abruf-Zyklen im
40-Sekunden-Takt, pro Zyklus eine Charakter- und eine Truhen-Anfrage im
Abstand von 170 ms:

| Endpunkt | Antworten während der Wartung |
|---|---|
| `/character/<Name>` | 22 × 503 |
| `/stash/<Liga>/<Id>` | **19 × 400**, 3 × 503 |

Der 400 trägt GGGs Umschlag `{"error": {"code": 2, "message": "Invalid
query; League not found"}}` — **und die Liga gab es die ganze Zeit**: Um
01:18:21 lieferte dieselbe URL wieder 200. Der Truhen-Endpunkt schiebt
die Schuld also auf die Anfrage, und zwar mit einer Begründung, die auf
die Liga des Nutzers zeigt.

Die Folge war kein Datenschaden, aber die Anwendung stellte sich vor die
eigene Diagnose: 19 Tracebacks im Log und 19 rote Meldungen über dem
Offline-Banner, das der 503 vom Charakter-Endpunkt korrekt gesetzt hatte.
Ausgerechnet die stillen Hintergrund-Refreshes, für die es die
Unterdrückung unten gibt, überschrieben es im 40-Sekunden-Takt.

Festgemacht ist die Ausnahme am **Text**, nicht am Fehlercode:
`_is_maintenance_bad_request()` prüft `status_code == 400` und
"league not found" in `ApiError.error_message`. Code 2 heißt bei GGG
allgemein "Invalid query" und träfe auch einen von UNS falsch gebauten
Substash-Pfad — genau den Fall, den die 4xx-Regel schützen soll. Ändert
GGG die Formulierung, fällt das Verhalten auf die laute Fehlermeldung
zurück statt auf ein verschlucktes Problem. Damit das überhaupt geht,
trägt `ApiError` seit demselben Tag `error_code`/`error_message` als
eigene Felder statt nur als Text in der Meldung (`client._ggg_error_
fields`, wegwerfend gegenüber Antworten ohne JSON).

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

**Der Level in der LISTE kommt aus einem anderen Endpunkt als die
Charakterdaten** (`MainWindow._apply_level_to_character_list`,
FALLSTRICKE #73). `_all_characters` — und damit die Beschriftung "Name
(Klasse Level)" — füllt ausschließlich `GET /character` (Plural). Der
läuft praktisch nie: in Peters Log 4 Listenabrufe gegen 1301
Einzelabrufe, der letzte beim Programmstart. Ein Charakter, der während
der Sitzung von Stufe 13 auf 24 stieg, stand deshalb stundenlang mit
"13" in der Liste. Der richtige Wert lag dabei die ganze Zeit vor:
`GET /character/{name}` liefert ihn mit, das Signal
`character_snapshot_loaded` trägt ihn — er landete nur ausschließlich im
Leveling-Feld (`_XpWatch`), nie in der Liste daneben.
`_on_character_snapshot` schreibt ihn jetzt zusätzlich in den passenden
`Character` und zeichnet die Liste neu, aber nur bei echter Änderung.

Die Listenabrufe zu häufen wäre der falsche Hebel gewesen:
`character-list-request-limit` ist mit real 2 pro 10 s und 5 pro 300 s
die knappste Policy überhaupt, und die Antwort enthält nichts, was hier
nicht schon vorliegt. Was der Weg NICHT abdeckt und auch nicht abdecken
kann: ein Charakter, der gar nicht abgerufen wird, altert weiter vor
sich hin, und ein im Spiel neu angelegter taucht erst beim nächsten
echten Listenabruf auf (Programmstart, Liga-Wechsel, "⟳ Refresh").

Weil die Liste dadurch mitten im Spielen neu gezeichnet wird, stellt
`CharacterList.set_characters` die Auswahl wieder her — über den
**Namen**, nicht die Zeilennummer: Die Liste ist nach Level sortiert,
ein Aufstieg kann den Charakter also verschieben. `setCurrentItem` löst
kein `itemClicked` aus, die Wiederherstellung kann somit keinen Abruf
nach sich ziehen.

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

**Drei Fälle, in denen der Item-Name allein nicht zum richtigen Preis
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

**Und ein Fall, in dem poe.ninjas eigene Zahl nicht stimmt.** Die
Currency-Route veröffentlicht `chaosEquivalent` aus der "receive"-Seite
des Handels, und die hat einen Boden: Das kleinste Verhältnis, das die
Handelsseite ausdrücken kann, ist 1:1. Jede Währung unterhalb eines
Chaos bekommt dadurch glatt 1 c — in der Liga Allflame real 20 von 67
Währungen, aus einem vollen Stapel Schriftrollen wurden so 40 c
(FALLSTRICKE #63, Peter 2026-08-05). Die "pay"-Seite derselben Zeile
trägt den echten Kurs (246 Rollen pro Chaos). `currency_chaos_value()`
rechnet deshalb aus der pay-Seite, wenn die receive-Seite genau auf dem
Boden steht und die pay-Seite ihr widerspricht — und holt nebenbei die
Stellen zurück, die `chaosEquivalent` durch Rundung auf zwei
Nachkommastellen verliert (0,01483 → 0,01, bei fünfstelligen Stapeln
nicht mehr gleichgültig). Beides greift nur dort, wo die Quelle sich
selbst widerspricht; eine eigenständige Aussage von poe.ninja bleibt
unangetastet.

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

**Und die leere Spalte sagt es auch.** Bis dahin stand dort schlicht
nichts, was im Spielertest (2026-08-03) wie ein Defekt aussah. Ist der
Index der aktuellen Liga `is_empty`, steht in der Statuszeile jetzt "No
prices for this league", die Begründung im Tooltip. Der Kurztext nennt
SSF bewusst NICHT: Ein vorübergehender Ausfall von poe.ninja sieht von
hier aus identisch aus (siehe oben), und eine falsche
Ursachenbehauptung wäre schlechter als gar keine — der Tooltip nennt
beide Möglichkeiten. Der Hinweis ersetzt die Summe auch dann, wenn
zufällig doch ein Wert zustande käme: In einem leeren Index bepreist
nur die fest eingebaute Chaos-Orb-Referenz überhaupt etwas, und "Value:
20c" neben lauter wertlos aussehenden Zeilen wäre irreführender als der
Hinweis. `_on_league_changed` ruft `_update_value_sum()` nach dem Setzen
des neuen Index explizit auf — der beim Leeren der Liste ausgelöste
`modelReset` lief noch gegen den Index der VORIGEN Liga.

**Versionsnummer neben der TTL** (`price_cache.CACHE_VERSION`): Die TTL
misst das Alter der DATEN, nicht das der Rechenvorschrift. Als die
Boden-Korrektur oben eingebaut wurde, hätte der Cache bis zu sechs
Stunden weiter die alten, um Faktor 246 zu hohen Werte ausgeliefert —
die Behebung wäre unsichtbar geblieben und hätte wie ein
fehlgeschlagener Fix ausgesehen. Einträge mit einer anderen Nummer
gelten deshalb als abgelaufen. Sie werden ignoriert, nicht gelöscht: Der
nächste Abruf derselben Liga überschreibt sie ohnehin, und ein Cache,
der von sich aus Daten wegwirft, ist in diesem Projekt schon zweimal
teuer geworden (§4.24, FALLSTRICKE #62).

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
**Sprachgrenze auch hier** (2026-08-05): Der Settings-Dialog war bis
dahin die einzige Stelle, an der die Trennung "Oberfläche englisch,
Kommentare und Projektdoku deutsch" verrutscht war — Reiter englisch,
Fenstertitel und sämtliche Beschriftungen deutsch. Beim Nachsehen fand
sich eine zweite: die Paperdoll (§4.16) mit deutschen Slot-Namen,
"Ausrüstung", "Flasche" und "Jewels im Passiv-Baum". Beide jetzt
englisch, beide mit einem Test abgesichert, der die sichtbaren Texte
einsammelt (Titel, Reiter, Labels, Knöpfe, Tabellenköpfe,
Platzhaltertexte) und auf Umlaute sowie typische deutsche Wörter prüft.
Ohne den Test verrutscht die Grenze beim nächsten neuen Feld wieder —
genau so ist sie ja entstanden.

UI-Einstellungen (§ *_settings()*). Der Toolbar-Button "⚙ Settings" öffnet
`SettingsDialog` (Tabelle mit "Active"/"Name"/"URL template"-Spalten,
"Add"/"Remove"-Buttons) — bei OK schreibt
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
CDN `web.poecdn.com/image/divination-card/<artFilename>.png`).
Cache-Treffer (`icon_cache.load`) aktualisieren das Icon sofort synchron,
sonst läuft der Download wie jedes andere Item-Icon über
`FetchIconJob`/`icon_loaded` — `MainWindow._pending_card_art` merkt sich
dafür (URL, Ziel-Dialog), `_on_icon` löst es beim Eintreffen auf. Da
`web.poecdn.com` GGGs eigenes CDN ist (nicht PoEDB/Wiki/poe.ninja selbst),
gilt die "Seitenbetreiber fragen"-Vorsicht der anderen drei Rechtsklick-
Tools hier nicht.

Der Dateiname kommt aus dem API-Feld `artFilename` und wird NICHT mehr aus
dem Kartennamen konstruiert. Die frühere Konstruktionsregel (PascalCase
ohne Trenner, an zehn Karten verifiziert) stimmt für 345 von 373
Kartentypen; die übrigen 28 heißen auf dem Server historisch anders
("The Cartographer" → `TheMapmaker`) und blieben ohne Artwork. Die Regel
steht nur noch als Rückfallebene für den Fall, dass die API das Feld
einmal weglässt — siehe FALLSTRICKE #66.

**Wichtig, von Peter am echten Ergebnis geprüft (2026-07-31):** Diese URL
liefert NUR das bloße Illustrations-Panel (querformatig, ~237×170px) —
KEINEN vollständigen Karten-Look mit Pergament-Rahmen, Titel-Schriftrolle,
Tier-Box oder Flavour-Text (das ist eine eigene, von Wikis komponierte
Darstellung, kein einzelnes GGG-Asset). Peter fand über die Wiki-Seite
eine solche Voll-Karten-Ansicht als optische Referenz; umgesetzt wurde
davon ein rein dekorativer Rahmen (`ItemZoomDialog._build_card_frame`,
Qt-Stylesheet: Pergament-farbenes Titel-Banner um `self._name`, dunkler
umrandeter Rahmen um Titel+Icon). Reine Optik, keine neuen Daten — nur bei
`frameType == 6` aktiv.

**Korrektur vom 2026-08-06:** Hier stand, der Text der Karte (Flavour,
Tier, Stack) "käme ohnehin nicht von GGG". Für Tier stimmt das, für die
beiden anderen nicht — Stack Size steht in `properties`, und den
Spruchtext liefert das Feld `flavourText` (12226 Items in Peters Cache,
davon 976 Karten und 9176 Uniques). Er wird jetzt angezeigt
(`ItemZoomDialog._flavour`, gespeist aus `Item.flavour_text`). Bei einer
Divination Card ist er der eigentliche Inhalt: Der Rahmen war gebaut, die
Karte blieb stumm. Im kompakten `ItemDetail` steht er bewusst nicht —
dort sind die Zeilen auf zwölf begrenzt, und die gehören den Mods.

**Gestaltung (Peter, 2026-08-06: "mit einer 'schöneren' Schrift in kursiv
und größer … sämtliche Texte mittig … evtl. noch etwas Farbe … vielleicht
ein paar Symbole"):**

- Der Spruchtext sitzt ZWISCHEN Bild und Zahlen; bei einer Karte innerhalb
  des Pergamentrahmens, denn er gehört zur Karte und ist keine Bemerkung
  darunter. Getrennt vom Artwork durch eine Zierlinie (`—— ◆ ——`).
- Kursive Serifenschrift, 130 % der normalen Größe, über
  `QFont.setFamilies` mit Ersatzkette. NICHT über ein Qt-Stylesheet:
  `font-family` nimmt dort nur den ersten Namen, eine Ersatzkette gäbe es
  damit nicht. Eine Schrift mitzuliefern wäre eine Lizenz- und
  Paketgrößenfrage für eine reine Geschmacksverbesserung.
- Die naheliegenden Zierzeichen ❦ (U+2766) und ❧ (U+2767) sind
  unbrauchbar: Windows zeichnet sie aus einer Farb-Emoji-Schrift, sie
  erscheinen als buntes Bildchen statt in der Rahmenfarbe — auch mit
  Variantenselektor U+FE0E und auch mit ausdrücklich gesetzter
  Serifenschrift (alle drei gerendert und angesehen). ◆ (U+25C6) und
  ❖ (U+2756) bleiben Text und nehmen die Farbe an.
- Der Textblock ist Rich Text (`_build_html`), alles zentriert wie in den
  Item-Tooltips des Spiels. **Farbig ist nur, was GGG selbst eingefärbt
  hat** (`theme.MARKUP_COLORS`): die Belohnungszeile einer Karte, in
  Währungsgold, Gem-Grün, Unique-Orange oder Korruptionsrot. Unsere
  eigenen Beschriftungen ("Class: …", "Sockets: …") bleiben schlicht,
  sonst sähe das Fenster wie ein Farbkasten aus und die Belohnung ginge
  in der Buntheit unter. Unbekannte Auszeichnungen bekommen KEINE
  Ersatzfarbe — eine geratene Farbe wäre schlechter als gar keine.
- `_text_lines` ist die gemeinsame Quelle für Klartext (`_build_text`,
  für Tooltips und Tests) und HTML (`_build_html`). Zwei getrennte
  Aufbauten wären auf Dauer zwei verschiedene Fenster.

**Satz-Fortschritt bei Divination Cards** (`_stack_line`, Peters Entwurf
2026-08-06): Statt "Stack Size: 7/5" steht dort `1 ▮  +  ▮ ▮ ▯ ▯ ▯` — ein
voller Satz (grün), und vom nächsten sind zwei von fünf Karten da. Die
Frage, die man an eine Karte hat, ist "wie weit bin ich?", und die
beantwortet "7/5" erst nach Kopfrechnen.

Warum die Aufteilung in Zahl UND Rechtecke, und nicht eins von beidem —
die Antwort steht in den Daten (alle 976 Karten aus Peters Cache
ausgewertet): Die **Satzgröße** liegt zwischen 1 und 27, die lässt sich
zeichnen. Die **Zahl der vollen Sätze** geht bis 116 (467 × "The Carrion
Crow" bei Satzgröße 4), die lässt sich nicht zeichnen. Bei 0 vollen Sätzen
entfällt die Zahl — das ist mit 495 von 976 Karten der häufigste Fall.

**Grün heißt an dieser Stelle immer und nur "vollständig".** Der erste
Entwurf schrieb `3×  ▯ ▯ ▯ ▯ ▯` für einen genau aufgehenden Satz — sachlich
richtig, liest sich aber wie "du hast nichts". Das grüne Rechteck hinter
der Zahl sagt, wovon sie spricht, und macht daraus `3 ▮  +  ▯ ▯ ▯ ▯ ▯`:
drei fertige Sätze und ein noch leerer vierter.

**Die Zeile hängt NICHT an der `Stack Size`-Property**, sondern rechnet
aus `stackSize`/`maxStackSize`. Grund ist ein Loch in den Daten, das Peter
an "Society's Remorse" fand: Karten mit Satzgröße 1 liefern gar keine
Property (real geprüft — alle 16 solchen Karten haben `properties: []`,
alle 960 übrigen eine). Bei ihnen stand dadurch überhaupt nichts, weder
Stückzahl noch Satzgröße, und "gar nichts" ist von einem Fehler nicht zu
unterscheiden. Sie zeigen jetzt nur die Anzahl mit grünem Rechteck
(`16 ▮`) — einen angefangenen Satz gibt es bei ihnen nicht.

Den Zahlentext behalten nur noch zwei Fälle: **alles außer Divination
Cards** (Peter: "die Rechtecke meine ich nur bei den Divination Cards" —
bei Währung ist `maxStackSize` keine Satzgröße, sondern Lagerkapazität,
real bis 50000) und Karten, bei denen eine der beiden Zahlen fehlt.

Die genauen Zahlen wandern in den Tooltip (`_stack_tooltip`) — 467 Karten
und 116 Sätze lassen sich nicht abzählen, die Auskunft darf aus der Zeile
verschwinden, nicht aus dem Fenster. Zwischen den Rechtecken steht ein
schmales Leerzeichen (U+2009): Aneinandergesetzt verschmelzen sie zu einem
Balken, und abzählen kann man den nicht mehr. Qts Rich-Text kennt
`letter-spacing` nicht, deshalb ein echtes Zeichen statt CSS.

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
und ein Pfadfeld samt "Browse…"-Button. `resolve_client_log_path()`
akzeptiert entweder direkt die Client.txt oder nur den
PoE-Installationsordner (probiert dann `<Ordner>/logs/Client.txt`, dann
`<Ordner>/Client.txt`) und zeigt sofort eine Live-Rückmeldung
("✓ Found: …" / "✗ No Client.txt found at this path"), damit
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

Die Ereignis-Spalte ist genau ein Zeichen breit; der Tooltip ist deshalb
die einzige Stelle, an der sie sich erklären kann (Spielertest
2026-08-03: "was bedeuten die Pfeile" war eine der Rückfragen).
`_EVENT_TOOLTIPS` deckt bewusst ALLE Ereignisarten ab und trägt das
Zeichen selbst im Text — sonst fiele beim nächsten neuen Symbol genau
das eine durch, und die Zuordnung Zeichen → Bedeutung wäre im Tooltip
nicht verankert. In allen anderen Spalten bleibt der Herkunftshinweis
("WitchOfPeter: Chaos Orb"), der bei einem Verlauf über ALLE Charaktere
hinweg die eigentliche Frage beantwortet.

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

Dieselbe Ergänzung folgt direkt danach für die Charakterliste (Peter,
2026-08-03: "Sollen wir das in der Character-Liste auch in den
Rechtsklick mit aufnehmen?") — `CharacterList.export_visible_requested`
(`ui/character_list.py`), ebenfalls an `MainWindow._export_csv`
verdrahtet. Dabei eine bewusste Verhaltensänderung: Das Kontextmenü der
Charakterliste zeigte bislang GAR NICHTS ohne einen Charakter unter dem
Cursor (`_on_context_menu` brach mit `if item is None: return` sofort
ab, da "⟳ Refresh" ohne Charakter-Bezug sinnlos ist). "Export visible
items" hat aber gar keinen Charakter-Bezug — es exportiert das, was
gerade in der Item-Tabelle sichtbar ist — und steht deshalb jetzt analog
zum Stash-Baum auch im leeren Bereich der Liste zur Verfügung. Die
zugehörige alte Regression-Sicherung
(`test_context_menu_does_nothing_without_an_item_under_cursor`) prüfte
genau das alte, jetzt bewusst aufgehobene Verhalten und wurde durch zwei
neue Tests ersetzt (mit/ohne Charakter unter dem Cursor).

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

`_leaf_ids_under(item)` fragt allein: **hat dieser Knoten Kinder?** Hat
er welche, ist er die Summe seiner Kinder; hat er keine, ist er selbst
das Blatt. Damit lösen sich Ordner, die synthetischen
Map-Sektionsgruppen ("Tier 6", §`group_map_children`) und die
Spezial-Tabs (§4.10) gleich auf, obwohl sie im Widget-Baum
unterschiedlich aussehen. `_collect_leaf_ids` dedupliziert (Strg-Klick
auf einen Ordner UND eines seiner eigenen Kinder würde dessen ID sonst
doppelt liefern).

Ursprünglich fragte die Methode stattdessen "hat dieser Knoten eigene
Daten?" (`_DATA_ROLE` gesetzt) und stieg nur bei Knoten ohne Daten ab.
Für Ordner und Gruppen stimmt das, für Spezial-Tabs nicht: Ein
UniqueStash/MapStash ist kein Ordner (`StashTab.is_folder` ist False)
und trägt deshalb sehr wohl eine eigene `_DATA_ROLE` — er galt als Blatt
und die Auswahl löste sich auf seine ID auf. Unter dieser ID liegen aber
keine Items; Spezial-Tabs liefern am Einzel-Endpunkt `children` statt
`items` (§4.10). Peter, 2026-08-07: Fach "1" und den Überordner "Unique
Items" markiert, im CSV-Export landeten nur die Items aus Fach "1". Ein
Spezial-Tab, dessen Unter-Fächer noch nicht entdeckt sind, bleibt
weiterhin sein eigenes Blatt — es gibt nichts, wohin abgestiegen werden
könnte, und die Statuszeile zählt ihn wahrheitsgemäß als noch nicht
geladen.

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
  ("poe-view2-Standard-3-tabs-selected-142items-2026-08-03_1542.csv")
  statt des irreführenden `_current_tab_name`, das ja weiterhin das
  zuletzt einzeln gewählte Fach nennt.

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

### 4.24 Logout + Konto-Trennung

Zwei zusammengehörige Themen aus demselben Gespräch (Peter, 2026-08-02):
(1) fehlender Logout ("Wer sich mit einem ANDEREN GGG-Konto anmelden
will, muss den Eintrag 'PoE-VIEW2' im Windows-Anmeldeinformations-
manager von Hand löschen ... für ein öffentliches Werkzeug eine
Sackgasse"), und (2) seine Rückfrage "Wenn ich den Account wechsle,
habe ich dann meine eigenen Daten?", die einen echten, bis dahin
unbemerkten Fehler aufdeckte.

**Logout-UI: derselbe Button, jetzt ein `QToolButton` mit Menü.** Vorher
war der nach dem Login auf `⚷ Kontoname` gesetzte Button (`QAction`)
schlicht DEAKTIVIERT — nach dem Login gab es keine Interaktion mehr.
Jetzt ein `QToolButton` (`self._login_button`): ausgeloggt verhält er
sich exakt wie die alte `QAction` (ein Klick löst direkt `LoginJob` aus,
kein Menü im Weg, da `self._login_button.menu()` dann `None` ist).
Eingeloggt hängt `_on_logged_in` das vorgefertigte `self._account_menu`
("🚪 Log out") an und schaltet `ToolButtonPopupMode.InstantPopup` ein —
derselbe Klick öffnet jetzt das Menü statt `clicked` auszulösen. Ein
einziger Button, ein einziger `clicked`-Handler für beide Zustände;
`_on_login_required` hängt das Menü wieder ab (`setMenu(None)`,
`DelayedPopup`) und setzt den Text zurück auf "🔑 Log in".

**Logout ist bewusst ein ANDERER Codepfad als ein unfreiwilliger
Token-Ablauf**, obwohl beide am Ende `_on_login_required` durchlaufen
(über `LogoutJob` → `token_store.delete_token()` → `login_required`-
Signal — dieser Worker-seitige Teil existierte als totes, nie
ausgelöstes Gerüst schon vor diesem Feature, siehe `api_worker.py`
`LogoutJob`/`_dispatch`). Ein Token-Ablauf MITTEN in der Session (z. B.
ein stiller Auto-Refresh-Tick, der auf einmal 401 bekommt) darf die
sichtbare Ansicht NICHT wegreißen — der Nutzer hat ja nichts getan, der
Cache-Stand bleibt so lange gültig, bis er sich aktiv neu anmeldet.
Ein bewusster Klick auf "Log out" ist dagegen ein Session-SCHNITT: der
Nutzer will explizit weg von diesem Konto, potenziell um sich mit einem
anderen anzumelden. `_on_logout_clicked` submitted `LogoutJob` (Token
weg) UND ruft sofort, synchron, `_reset_session_data()` (siehe unten) —
nicht erst wenn das `login_required`-Signal vom Worker-Thread
zurückkommt, sonst wäre die sichtbare Ansicht für einen Wimpernschlag
noch die alte.

**Cache-Trennung: eine Datei je Konto statt einer gemeinsamen**
(`services/data_cache.py`, `path_for(account_name)` —
`data-cache-<konto>.json`). Vorher gab es nur die eine `data-cache.json`
für alle Konten; `CachedData.account_name` wurde zwar gespeichert und
geladen, aber NIRGENDS verglichen (Peters Rückfrage deckte das auf).
Nach einem Kontowechsel blieben Stash-Baum, Items und Charaktere des
ALTEN Kontos im Speicher stehen — GGG antwortet dem neuen Konto mit
eigenen Fach-IDs, die alten Einträge wurden nie überschrieben, nur
ergänzt. `save()`/`load()` bleiben absichtlich auf den alten,
kontounabhängigen `_CACHE_FILE`-Pfad voreingestellt (optionaler `path`-
Parameter, `None` → alter Pfad) — bestehende Aufrufer/Tests
funktionieren unverändert weiter, nur `MainWindow` übergibt seit diesem
Feature immer explizit `path_for(...)`. Die alte gemeinsame Datei wird
dadurch nie gelöscht (Peters Entscheidung: "zu gefährlich, das kann der
Nutzer über den Explorer erledigen" — siehe unten), nur nicht mehr
beschrieben.

**Welches Konto beim kalten Start laden?** Ein echtes Henne-Ei-Problem:
`_restore_cached_data()` läuft in `MainWindow.__init__`, BEVOR der
Worker startet — der Kontoname kommt aber erst aus einem `/profile`-
Aufruf (`ApiWorker._after_auth`), der Netzwerk braucht. Ein Warten
darauf würde die Offline-Ansicht kaputt machen, die ja gerade OHNE jedes
Netzwerk funktionieren soll (Kernfeature, §4.12). Die Lösung: eine
zweite, rein lokale Gedächtnisstütze in `ui-settings.ini`
(`MainWindow._ACCOUNT_SETTING_KEY = "account/last_active"`), geschrieben
bei jedem erfolgreichen `_on_logged_in`. Beim kalten Start liest
`_restore_cached_data()` diesen Hinweis und lädt `path_for(hinweis)`
spekulativ — der Normalfall (dieselbe Person startet neu) trifft damit
sofort ins Schwarze.

**Realer Bug, noch am selben Tag gefunden (Peter: "er zeigt mir
momentan an, dass alles neu runtergeladen werden muss"):** der Fallback
auf den ALTEN gemeinsamen Pfad griff ursprünglich NUR, wenn der Hinweis
komplett FEHLTE. Sobald aber irgendeine — auch nur kurze — Sitzung
erfolgreich eingeloggt hatte, schrieb `_on_logged_in` den Hinweis sofort
(jeder Login tut das), UNABHÄNGIG davon, ob in dieser Sitzung je ein
vollständiger `_persist_cache()` gelaufen war. Peters Fall exakt: eine
kurze erste Sitzung mit dem neuen Code schrieb `account/last_active=
<Konto>`, ohne dass die 52 MB große alte `data-cache.json` je unter
dem neuen, kontospezifischen Pfad gesichert wurde. Jeder weitere Start
versuchte danach NUR NOCH die (fehlende) kontospezifische Datei, gab
auf und zeigte eine leere App — die reiche alte Datei lag unangetastet,
aber unsichtbar daneben. Ein bisschen Browsen in der leeren Sitzung
erzeugte dann sogar eine neue, aber winzige kontospezifische Datei (2
von 10 Ligen, 1 von 2295 Fächern) — real beobachtet.

**Fix:** Existiert die kontospezifische Datei nicht, wird zusätzlich die
alte gemeinsame Datei versucht — aber NUR übernommen, wenn ihr eigener
gespeicherter `account_name` zum Hinweis passt (oder gar kein Hinweis
existiert). Diese Bedingung ist kein Detail: ohne sie würde ein ECHTER
Kontowechsel, dessen neue Datei aus einer kurzen Sitzung noch fehlt,
fälschlich wieder die Daten des VORHERIGEN Kontos zeigen — accountname-
Gleichheit unterscheidet "meine eigene Migration" von "ein fremdes
Konto überschreiben". Eine Migration ergibt sich dadurch von selbst,
ganz ohne Kopier-/Umbenennungscode: der nächste `_persist_cache()`-
Aufruf schreibt bereits unter dem neuen, kontospezifischen Pfad.
Getestet: `test_restore_cached_data_falls_back_to_legacy_when_account_
file_is_missing` (der reale Fall) und `test_restore_cached_data_does_
not_leak_a_different_accounts_legacy_file` (die Schutzbedingung).

**Mismatch-Erkennung in `_on_logged_in`.** Die Spekulation beim kalten
Start kann danebenliegen — realistisches Beispiel, kein Konstrukt: das
gespeicherte Token ist über Nacht abgelaufen (10h Gültigkeit), der
Nutzer meldet sich am nächsten Tag über den "🔑 Log in"-Button neu an,
diesmal aber mit einem ANDEREN Konto (z. B. einem Zweitaccount). Dieser
Weg läuft NICHT über `_on_logout_clicked` (kein Logout fand statt), muss
den Kontowechsel also selbst erkennen: weicht das gerade bestätigte
Konto vom Konto ab, dessen Daten im Speicher stehen
(`self._account_name`, gesetzt entweder spekulativ beim kalten Start
oder von einem vorherigen Login in dieser Session), verwirft
`_switch_active_account_data` den alten Stand (`_reset_session_data`)
und lädt stattdessen den eigenen Cache-Stand des neuen Kontos (falls
vorhanden, sonst leer). Der ÜBERWIEGEND häufige Fall — dieselbe Person,
dasselbe Konto — durchläuft diesen Zweig gar nicht, `account_name`
stimmt schon überein.

**`_reset_session_data()`** ist der gemeinsame Kern für Logout UND
Mismatch-Kontowechsel: leert alle konto-/liga-gebundenen Felder
(`_stash_trees`, `_items`, `_last_loaded`, `_all_characters`,
`_character_items`, `_character_items_loaded`, `_leaf_stashes`,
`_current_league`/`_current_stash_id`/`_current_character_name`/
`_current_stash_selection`, Such- und Aggregat-Zustand, den
Item-Verlauf) UND die sichtbaren Widgets (Baum, Charakterliste,
Item-Tabelle, Verlaufs-Tabelle). Absichtlich NICHT betroffen:
`_price_indexes` (poe.ninja-Preise gelten pro LIGA, nicht pro Konto —
ein Neuabruf nur wegen des Kontowechsels wäre verschwendetes
Rate-Limit-Budget) sowie `_offline`/`_live_leagues` (Spielzustand ohne
Konto-Bezug).

**`_persist_cache()` schreibt nichts ohne aktives Konto** (`if not
self._account_name: return`). Ohne dieses Gate könnte ein spät
eintreffender Job — eine Antwort, die kurz nach einem Logout eintrifft,
weil sie schon vor dem Logout-Klick unterwegs war — eine FAST LEERE
`CachedData` über einen bestehenden, guten Kontostand schreiben und ihn
damit zerstören. Da `_account_name` nach einem Logout sofort auf `""`
steht, wird so ein verspäteter Persist-Versuch zuverlässig übersprungen.

**Nachtrag 2026-08-03 — der Logout löschte indirekt doch Daten.**
`_on_logout_clicked` leert den Speicher und setzt `_account_name` auf
leer. Die Weiche in `_on_logged_in` prüfte zusätzlich auf einen
gesetzten `_account_name` und griff deshalb ausgerechnet dann nicht,
wenn keiner gesetzt war: Nach einem Logout wurde beim erneuten Anmelden
nichts von der Platte nachgeladen, und der nächste `_persist_cache()`
schrieb den leeren Stand über die gefüllte Datei. Die Zusatzbedingung
ist entfallen; `_switch_active_account_data` stellt den Kontostand jetzt
bei jeder Anmeldung her, bei der er nicht schon im Speicher steht.
Vollständige Herleitung samt Log-Beweis: FALLSTRICKE #62.

Weil damit binnen zweier Tage zum zweiten Mal ein magerer Speicherstand
einen reichen Dateistand überschrieben hatte, kam auf Peters Wunsch ein
**pfad-unabhängiger Überschreibschutz** dazu: `_persist_cache()`
vergleicht den Umfang des Speicherstands (`_cache_scale`) mit dem des
zuletzt geladenen bzw. geschriebenen Stands und verweigert das Schreiben,
wenn davon weniger als ein Viertel übrig bliebe. Der Wächter kennt die
Ursache eines Einbruchs bewusst nicht — er soll auch Fehler abfangen,
die es noch nicht gibt. Details und die gewählte Fehlerrichtung: ebenda.

**Bewusst keine Löschfunktion für lokale Daten aus dem Tool heraus** —
Peters Entscheidung: "zu gefährlich. Wer seine Daten löschen will, kann
das über den Explorer erledigen." Kein Häkchen "auch die Items löschen"
im Logout, keine "alte Konten aufräumen"-Funktion. Cache-Dateien
verwaister Konten bleiben liegen, bis der Nutzer sie selbst entfernt.

**Bewusst nicht gelöst:** Der Zonenwechsel-Trigger/"Auto"-Modus
refreshen weiterhin nur das zuletzt einzeln gewählte Fach im
Hintergrund (`_current_stash_id`) — das bleibt nach einem Logout
`None`, nach einem Kontowechsel ebenfalls (`_reset_session_data`), sie
laufen also einfach ins Leere, bis der Nutzer wieder etwas auswählt.
Kein Sonderfall nötig.

### 4.25 Liga-Wechsel leert die Itemliste

Peter, 2026-08-03, direkt nach dem 0.4.0-Release: "Wenn ich die League
wechsle bleibt der aktuelle Inhalt der Itemliste erhalten. Das sollte
denke ich nicht sein."

`_on_league_changed` setzte bereits `_current_stash_id`,
`_current_character_name` und `_current_stash_selection` auf `None` und
löste bei vorhandenem Baum-Cache sogar `_activate_stash_tree` aus —
aber `table_model`/`history_model` selbst blieben unangetastet. Die
zuvor gezeigten Items einer anderen Liga standen also weiter in der
Tabelle, obwohl keine der zurückgesetzten Auswahl-Variablen mehr dazu
passte. Fix: `table_model.set_items([])` und
`history_model.set_entries([])` direkt beim Zurücksetzen der
Auswahl-Variablen, plus ein Platzhalter-Statustext ("select a tab or
character to view items") — Wert- und Stack-Summe leeren sich darüber
automatisch mit (`modelReset` → `_update_summaries`, siehe FALLSTRICKE
#39). Gegenprobe: Fix entfernt, `test_league_change_clears_the_visible_
item_list` schlägt fehl, restauriert wieder grün.

### 4.26 Item-Verlauf: Mengenänderungen (Currency) + Live-Zonenanzeige

Zwei kleine, unabhängige Anschlüsse aus demselben Gespräch (Peter,
2026-08-03).

**Mengenänderungen im Item-Verlauf.** Peter: "In unserer Item-History-
Liste berücksichtigen wir keine Items die sich ändern, wie Currency ...
sobald sich Currency ändert, wandert diese wieder ganz oben auf die
Liste mit Vermerk, wieviel sich geändert hat." Auf Nachfrage bewusst nur
Charakter-Inventar ("Nur die im Charakter-Inventar") — Stash-Fächer
laufen gar nicht durch diese Diff-Logik und blieben unangetastet.

Die Grundlage stand schon halb: `_diff_character_items` (§4.21) liefert
bereits `changed_ids`, die aber bislang bewusst verworfen wurden ("um
reine Stack-Größen-Änderungen nicht als 'neues Item' zu loggen"). Neu
ist `MainWindow._stack_size_changes()`, eine EIGENE, engere Prüfung als
`changed_ids`: nur eine tatsächliche `stackSize`-Differenz zählt, nicht
jede beliebige Feldänderung (`changed_ids` schlägt z. B. auch bei einem
gerade identifizierten Item an — das wäre fälschlich als
Mengenänderung geloggt worden). `HistoryEntry` bekam ein neues Feld
`stack_delta` (vorzeichenbehaftet) und `HistoryEventType` ein drittes
Mitglied `"changed"` (Symbol `±`); `ItemHistoryModel` hängt die Differenz
in der Stack-Spalte an, z. B. `53 (+3)`. Da neue Einträge per
`appendleft` vorne einsortiert werden (§Modul-Docstring
`item_history.py`), "wandert" ein sich änderndes Item automatisch ganz
nach oben — kein Sonderfall nötig. Gegenprobe: `_stack_size_changes()`
kurzgeschlossen, `test_a_stack_size_change_is_logged_as_a_changed_
history_entry_with_the_delta` und die Abnahme-Variante schlagen fehl,
restauriert wieder grün.

**Live-Zonenanzeige.** Peter zunächst: "Kannst du so eine Art LED oben
in die 'Menü'-Zeile einbauen, die kurz aufblinkt, wenn wir auf ein
Change-Ereignis der Client.txt reagieren? Momentan bin ich mir nicht
sicher ob wir das überhaupt machen." — beim Live-Test blinkte nichts
sichtbar (vermutlich lief noch der alte Prozess von vor dem Fix, Qt-Apps
laden Code nicht zur Laufzeit nach). Statt die Blink-LED zu debuggen,
Kurswechsel auf Peters eigenen, besseren Vorschlag: "Wir machen das
nicht mit einer LED, sondern geben dort Live die aktuelle Position des
Characters wieder, das ist denke ich noch besser."

Ein `QLabel` (`self._zone_label`, Startwert "–") in der Toolbar zeigt
IMMER die zuletzt aus der Client.txt erkannte Zone an — kein Blinken,
kein Timer, `_on_zone_changed` schreibt den Zonennamen direkt hinein.
Bewusst VOR den frühen Rückgaben der Methode platziert (Pause-Modus,
kein Login, archivierte Liga, Rate-Limit) — die Anzeige bestätigt "wir
haben einen Zonenwechsel in der Client.txt erkannt", nicht "wir haben
deswegen auch tatsächlich neu geladen". Genau diese Trennung ist der
Zweck: bleibt die Anzeige dauerhaft bei "–", weiß Peter, dass entweder
der Zonen-Beobachter deaktiviert ist oder die Client.txt keine
erkennbaren Zonenwechsel-Zeilen liefert — unabhängig davon, ob ein
Refresh geblockt wäre. Tooltip verweist auf "Settings > Zone Refresh".
Gegenprobe: Zuweisung entfernt, `test_zone_changed_updates_the_zone_
label_even_while_paused` schlägt fehl, restauriert wieder grün.

**Und genau das deckte sofort einen echten Fehler auf:** die Anzeige
blieb bei Peter dauerhaft leer. Der Zonenwechsel-Trigger (§4.8,
FALLSTRICKE #58) hatte in Wahrheit nie ausgelöst — Qts
`QFileSystemWatcher` meldet Anhänge an PoEs dauerhaft geöffnete
`Client.txt` auf Windows nicht. Aufgefallen war es vorher niemandem,
weil der Trigger rein additiv zum getakteten Refresh ist: der lief
weiter und aktualisierte die Daten trotzdem, nur langsamer. Seitdem
trägt ein Poll-Timer (2 s) die Erkennung, der Watcher bleibt als
beschleunigende Zugabe daneben. Vollständige Herleitung mit den drei
Messungen gegen Peters echte Dateien: FALLSTRICKE #61.

### 4.27 Anwendungssymbol

Peter hat die Grafik selbst erstellen lassen und in Paint.NET
nachbearbeitet (2026-08-03) — freigestellt, ohne Wasserzeichen, und vor
allem in **vier Detailgraden**: nur Zahnrad mit Auge, runde Fassung mit
Runenkranz, abgerundetes Quadrat mittlerer Dichte und die volle
Ausführung. Genau diese Staffelung ist der Grund für den ganzen Aufwand
hier: würde man nur die große Fassung einbetten, rechnet Windows sie für
die Taskleiste selbst auf 16 px herunter und der Runenring wird
unkenntlich. `tools/make_icon.py` ordnet deshalb jeder der sieben Stufen
(16/24/32/48/64/128/256) die passende Vorlage zu.

**Warum ein eigener ICO-Generator.** Qt kann `.ico` schreiben, aber nur
ein Bild pro Datei — für eine mehrstufige Icondatei reicht das nicht.
Statt dafür ein Bildbearbeitungspaket als Abhängigkeit aufzunehmen,
schreibt das Skript den ICO-Container selbst (Kopf, Verzeichnis,
Bilddaten); Laden, Skalieren und PNG-Kodierung übernimmt das ohnehin
vorhandene PySide6. Stufen bis 48 px liegen als klassisches DIB darin,
ab 64 px PNG-komprimiert — 256×256 unkomprimiert wären allein 256 KB.

Zwei Fallen, die dabei auffielen: `QBuffer(QByteArray())` stürzt ab,
weil Python den temporären Puffer sofort wieder freigibt (der
parameterlose Konstruktor tut es), und DIB-Einträge speichern ihre
Zeilen von UNTEN nach oben, bei doppelt eingetragener Höhe im Header.
Gegen den Zeilendreher — den klassischen Fehler dabei — sichert
`test_the_small_sizes_are_not_upside_down` ab: Gegenprobe mit
absichtlich nicht umgedrehten Zeilen schlägt fehl, zurückgedreht grün.
Die weiteren Tests in `tests/test_app_icon.py` prüfen den Container
strukturell (lückenlose Offsets bis exakt ans Dateiende), weil die
`.ico` als fertige Datei versioniert wird und sonst niemandem auffiele,
wenn sie beim Regenerieren kaputtginge.

**Zweifach eingebunden:** `icon=` in der Spec brennt das Symbol in die
`.exe` (das sieht Explorer), zusätzlich liegt dieselbe Datei über
`datas` im Bundle, weil `main.py` sie als Fenster-Icon setzt — nur so
trägt auch der Start aus der Quelle heraus nicht das Python-Symbol.
Dafür brauchte `config.py` einen zweiten Pfad: `PROJECT_ROOT` zeigt in
der gepackten Anwendung neben die `.exe` (dorthin legt der Nutzer seine
`.env`), Mitgeliefertes entpackt PyInstaller aber nach `sys._MEIPASS` —
dafür jetzt `BUNDLE_DIR`. Verifiziert wurde die fertige `.exe`, indem
die Nutzdaten aller sieben Stufen im Binary wiedergefunden wurden.

### 4.28 Hilfe-Fenster

Peter, 2026-08-03, im Anschluss an einen Spielertest: "Punkt 5 wäre eine
kleine Hilfe-Funktion". Auslöser war die Beobachtung, dass die
Oberfläche sich an mehreren Stellen nicht selbst erklärt — acht
unbeschriftete Farbkästchen als Typ-Filter, `#2 (0, 0)` in der
Positionsspalte, die Pfeile im Item-Verlauf, die in SSF-Ligen dauerhaft
leere Wertspalte (die wie ein Defekt aussieht, aber eine Grenze der
Datenquelle ist) und die beiden auseinanderlaufenden Zähler in
"Load All Tabs".

`ui/help_dialog.py`: Themenliste links, Text rechts, Inhalte als HTML in
einer Modul-Konstante `TOPICS` — an einer Stelle pflegbar, ohne
Widget-Code anzufassen. Die Legende der Typ-Filter zieht ihre Farben aus
`theme.RARITY_COLORS` statt aus eingetippten Werten, sonst liefe sie beim
nächsten Farbwechsel aus dem Ruder.

**Bewusst nicht modal** (`show()` statt `exec()`): Man soll nachschlagen
und das Erklärte gleichzeitig ausprobieren können. Das Fenster wird
einmal gebaut und wiederverwendet; die Referenz hängt am Hauptfenster,
ohne sie sammelte Python es sofort wieder ein.

**Texte auf Englisch**, wie die übrige Oberfläche und die README —
Kommentare und Projektdoku bleiben deutsch. Ein Test hält diese Grenze
(`test_the_help_is_written_in_english_like_the_rest_of_the_ui`), weil
sie sich beim Nachpflegen sonst leicht verwischt. Die weiteren Tests
prüfen nicht die Formulierung, sondern dass genau die Stellen abgedeckt
bleiben, an denen der Spielertest hängen geblieben ist.

**Dabei aufgefallen:** Der Settings-Dialog ist sprachlich gemischt —
Reiter englisch, Fenstertitel und Fließtext deutsch. Das bricht dieselbe
Grenze und ist noch offen.

**Die Hilfe altert mit der Oberfläche mit — dagegen Tests.** Am
2026-08-06 fiel bei Peters Rückfrage ("Muss die Hilfe aktualisiert
werden?") auf, dass sie den Fortschrittsdialog noch mit einem Zähler
namens "Section" beschrieb, den §4.32 gerade abgeschafft hatte. Eine
Hilfe, die Beschriftungen nennt, die es nicht mehr gibt, ist schlimmer
als gar keine: Sie schickt den Nutzer nach etwas suchen, das er nie
finden wird. Seither sichern drei Tests das ab — einer prüft, dass die
abgeschaffte Beschriftung NICHT mehr vorkommt, einer, dass die nach dem
Bau der Hilfe hinzugekommenen Anzeigen (Nur-Lese-Modus, "Pin",
"unchanged for", "No prices for this league") vorkommen, und einer hält
die Sprachgrenze. Sie prüfen bewusst Stichworte, nicht Formulierungen:
Die Hilfe soll umformuliert werden dürfen, ohne dass Tests brechen —
aber nicht stillschweigend hinter der Oberfläche zurückbleiben.

### 4.29 "Updated HH:MM:SS" + Verlauf ohne gecachte Vergleichsbasis

Zwei Beobachtungen Peters vom 2026-08-04, beide aus dem laufenden Spiel
heraus.

**"Im Single-Modus tat sich nichts."** Peter beobachtete sein Inventar
während des Spielens; die Tabelle blieb stehen, erst ein Klick ins
Fenster brachte sie auf Stand. Das Log widerlegte die naheliegende
Erklärung sofort: `GET /character/...` lief durchgehend alle ~13 s mit
`200 OK`. Auch der Anzeige-Pfad hat keine versteckte Abbruchbedingung —
`_show_character_items` setzt das Modell bedingungslos neu, sobald der
aktualisierte Charakter der ausgewählte ist. Damit blieben zwei
Möglichkeiten übrig, die sich von außen nicht unterscheiden ließen:
Ansicht wird nicht neu GESETZT oder nur nicht neu GEZEICHNET.

Statt zu raten wieder erst Sichtbarkeit (dieselbe Lehre wie FALLSTRICKE
#61): `_note_view_updated` schreibt bei jedem Neuaufbau der Tabelle die
Uhrzeit in die Statuszeile. Angehängt an `proxy.modelReset` — dasselbe
Signal wie die Summen, es feuert genau einmal pro `set_items()` und
damit aus JEDER Ansicht heraus, ohne dass ein Aufrufer daran denken
muss. Läuft die Zeit weiter, während die Tabelle unverändert aussieht,
ist es ein Zeichenproblem; steht sie still, ist es Logik. Unabhängig von
der Diagnose beantwortet sie dauerhaft die Frage "wie frisch ist das?".

**Uhr in der Toolbar.** Peter, direkt im Anschluss: "Füge doch oben
rechts außen in der ersten Zeile noch das aktuelle Datum und die Uhrzeit
ein, dann sieht man im gleichen Screenshot was Sache ist." Der Zweck ist
nicht, die Uhrzeit zu kennen — die steht in der Taskleiste —, sondern
dass ein Screenshot für sich allein auswertbar wird: Erst im Vergleich
mit dieser Uhr sagt das "Updated HH:MM:SS" der Statuszeile, ob die
Ansicht frisch ist oder seit zehn Minuten steht. Genau dieser Vergleich
ist bei der offenen Single-Modus-Frage der entscheidende. Datum bewusst
in fester, ISO-naher Schreibweise: Ein Tage später auftauchender
Screenshot soll eindeutig bleiben, und 04.08. gegen 08.04. wäre genau
die Mehrdeutigkeit, die man dabei nicht gebrauchen kann. Die Uhr hängt
am bereits laufenden Sekundentakt des Refresh-Countdowns — ein zweiter
Timer für dieselbe Frequenz wäre Verschwendung.

**Statuszeile aufgeräumt.** Peter, als die "unchanged for"-Ergänzung
zur Sprache kam: "Ich glaube für Punkt 2 geht uns langsam der Platz
aus." Zwei Maßnahmen, beide ohne Informationsverlust.

Erstens standen dort zwei Refresh-Angaben nebeneinander, die sich
teilweise dasselbe sagten: "Auto-refresh: 0 of 94 stash tabs updated |
Refresh mode: Single — next update in 1s". Daraus wurde eine Anzeige,
zusammengesetzt aus `_refresh_state_text()` (was der Hintergrund-Refresh
gerade tut) und `_sweep_counter_text()` (wie weit der Rundlauf ist):
"Single — next update in 1s · 0/94 tabs". Das halbiert den Platzbedarf.

Zweitens ist der GGG-Disclaimer aus der Statuszeile ins Hilfe-Fenster
gewandert, in ein eigenes Thema "About". Peters Begründung war eine
empirische: "Hab gerade in PoB nachgeschaut, da gibts gar keinen
Disclaimer" — Path of Building ist das bekannteste Werkzeug dieser
Community. Der Wortlaut bleibt unangetastet, weil er GGGs vorgegebene
Formulierung ist und kein selbstgewählter Text; er steht weiterhin auch
in der README. Zwei Tests sichern beides ab: dass er im About-Thema
steht UND dass er nicht mehr in der Statuszeile auftaucht — sonst wäre
die Platzersparnis beim nächsten Nachpflegen wieder dahin.

Nebenwirkung des Zusammenlegens: Die gemeinsame Anzeige liest jetzt auch
den Countdown des Auto-Refresh-Timers. Der wurde bisher NACH `_build_ui()`
angelegt, das aber schon den Cache-Baum rendert und dabei die Anzeige
aktualisiert — der Timer musste deshalb vor den UI-Aufbau wandern.

**Verlauf zeigte längst Vergangenes.** Peter: "in meiner History war
noch Kishara's Star drin. Ein Item, das ich schon lange nicht mehr
habe." Ursache ist eine Asymmetrie, die beim Bau nicht auffiel: Der
Verlauf (`_item_history`, reines `deque` im Speicher) überlebt keinen
Neustart — der Inventarstand der Charaktere (`character_items`) aber
schon. Der erste Abruf eines Charakters nach dem Start verglich deshalb
den frischen Stand gegen einen womöglich wochenalten und schrieb
sämtliche zwischenzeitlichen Änderungen mit `datetime.now()` ins
Protokoll. Für einen Verlauf, der zeigen soll, was gerade durchs
Inventar wandert, ist das schlicht falsch.

Behoben über `_session_fetched_chars`: Der erste Abruf eines Charakters
IN DIESER SITZUNG setzt nur die Vergleichsbasis und protokolliert
nichts — dieselbe Regel, die für den allerersten Abruf überhaupt schon
galt (`previous_items=None`), nur konsequent auf "aus der Datei geladen"
ausgeweitet. Beim Logout wird die Menge geleert, sonst gälte der Stand
des abgemeldeten Kontos als Basis für das nächste.

Nachtrag vom 2026-08-05: Derselbe Vergleich speist eine zweite Anzeige,
die Türkis-/Grau-Hervorhebung (§4.20) — und die war zunächst nicht
mitgefixt. Beim ersten Abruf nach dem Programmstart leuchtete deshalb
weiter auf, was sich seit Tagen geändert hatte, und verschwundene Items
hingen als graue Zeilen darunter. Die Ursache war dieselbe, nur eine
Ebene weiter vorn: `_show_character_items` ruft `_diff_character_items`
selbst auf und lief an der Sperre vorbei. Konsequenz für den Aufbau: Ob
die Vergleichsbasis taugt, entscheidet jetzt `_on_character_items` EINMAL
(`stale_baseline`) und reicht die Auskunft an beide Verwerter weiter,
statt dass jeder für sich in der Menge nachsieht. Der Vergleich ist
entweder gültig oder nicht; wohin sein Ergebnis fließt, ändert daran
nichts. Die vorige Bauweise hätte sonst auch beim dritten Verwerter
wieder versagt — und sie war reihenfolgeabhängig: Wer zuerst nachsah,
trug den Namen ein und nahm dem Zweiten die Antwort weg.

### 4.30 Eigenschaften mit Platzhaltern im Namen

Peter, 2026-08-04, per Screenshot einer Divine Life Flask: Im
Detail-Panel stand "Consumes {0} of {1} Charges on use: 15".

GGGs `properties`-Array trägt seine Werte nicht immer hinten an, sondern
oft als Platzhalter MITTEN im Namen. An echten Daten aus dem Cache
belegt: `{"name": "Consumes {0} of {1} Charges on use", "values":
[["35", 0], ["65", 0]]}`. Der bisherige `display_value` griff nur
`values[0][0]` ab und hängte es hinten an — die Platzhalter blieben
stehen, der zweite Wert verschwand spurlos.

Neu ist `ItemProperty.display_text`, das die fertige Zeile liefert und
drei Fälle abdeckt, alle aus echten Daten belegt: Platzhalter im Namen
werden der Reihe nach durch `values[i][0]` ersetzt; ein Name ohne
Platzhalter behält die Form "Name: Wert" ("Quality: +20%"); eine
Eigenschaft ganz ohne Wert bleibt nackt stehen (die Waffenklasse als
wertlose erste Eigenschaft, "Sceptre" statt "Sceptre: ").

Bewusst an der Wurzel im Datenmodell behoben statt in der Anzeige: Die
Formatierung war an VIER Stellen dupliziert — Detail-Panel, vergrößerte
Ansicht, CSV-Export und der Suchindex der Tabelle. Letzterer ist der
unauffälligste, aber nicht der unwichtigste Fall: Wer nach dem sucht,
was er auf dem Bildschirm liest, hätte einen Treffer sonst verfehlt.

Wenn weniger Werte als Platzhalter geliefert werden, bleibt der
überzählige Platzhalter stehen, statt eine Ausnahme auszulösen — ein
sichtbarer Schönheitsfehler ist besser als ein leeres Detail-Panel.

### 4.32 "Load All Tabs": der Dialog erklärt seine eigenen Zahlen

Letzter offener Punkt aus dem Spielertest (Peter, 2026-08-03, anhand
eines Screenshots: "Loaded: (Remove-only) / Section 42 of 1456 · tab 1 of
362 / about 4 h 12 min remaining" — "Ich denke, dass die meisten User mit
den Zahlen nicht klar kommen"). Die Zahlen selbst waren nie falsch
(FALLSTRICKE #37/#42), sie erklärten sich nur nicht.

Vier Eingriffe, alle rein an der Vermittlung:

**Der Fach-Zähler steht vorn.** "tab 3 of 362 — 42 of 1456 requests"
statt umgekehrt: Ein Spieler kennt Truhenfächer, Abrufe sind die
technische Größe dahinter. Der Balken hängt weiterhin an den Abrufen —
das ist die tatsächlich anfallende Arbeit, und ein Balken über
Truhenplätze stünde bei einem großen Map-Stash über eine Stunde still.

**"Section" ist verschwunden.** Das Wort hat in PoEs Truhen-Oberfläche
keine Entsprechung und tauchte für den Nutzer aus dem Nichts auf. Jetzt
heißt es schlicht "requests".

**Die Aufschlüsselung als kleine Tabelle mit Summe**
(`_bulk_breakdown` / `_bulk_breakdown_html`, Peters Vorschlag am
2026-08-06: "noch eine Zeile für die Erklärung der Berechnung … oder als
mini Tabelle und anschließend als Summe"):

```
      289  plain tabs
     1017  sections in one map tab
      145  sections in one unique tab
        5  sections in one unique tab
     ----
     1456  requests in total
```

Damit löst sich der scheinbare Widerspruch der beiden Zähler in eine
Rechnung auf, die man nachvollziehen kann. Zahlen rechtsbündig, damit
die Summe unter ihren Summanden steht — als Fließtext ließe sich das
nicht auf einen Blick prüfen. Umgesetzt als Rich Text im Dialog-Label
(eigenes `QLabel` mit ausdrücklichem `RichText`-Format, statt sich auf
Qts Auto-Erkennung zu verlassen); eine Monospace-Schrift für den ganzen
Dialog hätte auch "Loading: …" und die Restzeit nach Konsole aussehen
lassen. Berechnet wird die Aufschlüsselung EINMAL beim Öffnen: Die
Zusammensetzung steht mit `to_fetch` fest, `total_requests` wächst
während des Laufs nicht. Ohne Spezial-Fach entfällt die Tabelle ganz —
dann sind beide Zähler gleich und es gibt nichts zu erklären. Mehr als
sechs Zeilen werden zusammengefasst, damit die Erklärung nicht länger
wird als der Dialog. Die Sammelzeile nennt dabei die Art mit, sofern es
nur eine gibt ("192 sections in 12 further unique tabs"): Die erste
Fassung sagte neutral "special tabs" und ließ damit genau die Frage
offen, die Peter nach dem ersten echten Lauf stellen musste — es waren
zwölf Unique-Fächer, und das hätte dastehen können. Bei gemischten Arten
bleibt das neutrale Wort, weil dann nichts Genaueres stimmt.

**Remove-only-Fächer lädt "Load All Tabs" bewusst mit.** In Peters
SSF-Liga stecken 572 der 1110 Sektionen in Fächern, die nur noch
schrumpfen können — über die Hälfte der Ladezeit. Ein Überspringen wurde
erwogen und verworfen (Peter, 2026-08-06): "Den Button drückt man eh nur
wenn man mal alles haben will, der Rest geht dann über die verschiedenen
Modi." Der Hintergrund-Refresh behandelt sie ohnehin nachrangig (§4.8);
der Komplett-Lauf soll komplett sein.

**Die Restzeit nennt ihren Grund.** "about 4 h 12 min remaining (GGG rate
limit)" — ohne den Zusatz liest sich die Zahl wie ein Defekt, obwohl sie
allein an GGGs Kontingent hängt und einmalig anfällt.

Nicht angefasst: die Zahlen selbst und der Bezugspunkt des Balkens. Beide
waren korrekt und sind es geblieben.

### 4.31 "unchanged for X": abgeholt ist nicht neu

Der Zeitstempel aus §4.29 beantwortet, wann die Tabelle zuletzt neu
aufgebaut wurde — nicht, ob dabei etwas Neues ankam. Genau diese Lücke
war bei Peters Single-Modus-Frage der offene Rest: Die Anzeige lief
sichtbar mit, die Zahlen blieben trotzdem stehen. Aufgelöst hat das erst
ein Screenshot-Vergleich von Hand (Portal Scroll 26 → 29 im Spiel, in
PoE-VIEW2 eine Minute lang 26): GGG veröffentlicht neue Fach-Inhalte
oft erst nach einem Zonenwechsel (FALLSTRICKE #58). Das Werkzeug
arbeitete korrekt, die Quelle lieferte Altes.

Der Zusatz macht diese Unterscheidung ablesbar, ohne dass jemand
Screenshots vergleichen muss. Drei Fälle, sauber getrennt:

| Anzeige | Bedeutung |
|---|---|
| Zeitstempel steht still | Wir holen nichts mehr (Pause, Rate-Limit, Token) |
| Zeitstempel läuft, "unchanged for 12m" | Wir holen, GGG liefert denselben Stand |
| Zeitstempel läuft, kein Zusatz | Alles in Ordnung |

Zwei Entwurfsentscheidungen tragen das:

**Verglichen wird, was der Spieler sieht.** `ItemTableModel.
content_signature()` bildet die Kennzahl aus den vorgerechneten
Anzeigewerten (`_rows`) und den Tab-Namen, nicht aus den Item-Objekten.
Ein API-Feld, das in keiner Spalte auftaucht, soll die Anzeige nicht als
"geändert" gelten lassen — sonst widerspräche die Statuszeile dem
Bildschirm. Die Werte liegen aus `set_items()` ohnehin fertig vor, der
Vergleich kostet also nichts obendrauf, auch bei liga-weiten Aggregaten
mit zehntausenden Zeilen.

**Gemessen wird bis zum letzten Neuaufbau, nicht bis jetzt.** Ohne
Neuaufbau haben wir nicht nachgesehen, und "unchanged" würde eine
Prüfung behaupten, die nicht stattgefunden hat. Dadurch friert im
Pause-Modus die ganze Anzeige gemeinsam ein, statt dass der Zusatz
munter weiterzählt, während der Zeitstempel steht. Unterhalb einer
Minute bleibt er ganz weg: Im Single-Modus liegen ~13 s zwischen zwei
Abrufen, und dass sich dazwischen nichts geändert hat, ist der
Normalfall und keine Meldung wert. Der Zusatz soll auffallen, wenn er
auftaucht.

**Und Pausen zwischen zwei Neuaufbauten zählen ebenfalls nicht mit**
(Nachtrag 2026-08-05, FALLSTRICKE #64). Der Absatz oben war einen Tag
lang nur die halbe Konsequenz: Er deckt den Fall ab, dass der letzte
Neuaufbau lange her ist — aber zwischen ZWEI Neuaufbauten kann ebenfalls
eine Pause liegen, und die wurde beim nächsten in voller Länge als
geprüfte Zeit verbucht. Real gemessen: Von einer 9-Minuten-Anzeige waren
fünf Minuten eine Rate-Limit-Pause. `_tick_unchanged_accounting` schreibt
am ohnehin laufenden Sekundentakt mit, wie lange nicht abgefragt wurde,
und `_unchanged_duration_text` zieht das ab.

Entscheidend ist dabei nicht der Zähler, sondern die gemeinsame Quelle:
`_refresh_idle_reason()` beantwortet "fragt der Hintergrund-Refresh
gerade gar nicht ab?" für BEIDE Verwerter — die Statuszeilen-
Beschriftung (`_refresh_state_text`) und die Buchführung. Vorher steckte
die Bedingung nur in der Beschriftung, und genau ihr Auseinanderlaufen
war der Fehler: Das eine Segment der Statuszeile meldete "waiting for
rate-limit headroom", das andere zählte dieselbe Pause als Prüfung mit.
Dieselbe Bauform wie beim `stale_baseline` in §4.29 — eine Frage, eine
Antwort, zwei Verwerter.

---

### 4.33 Ausrüstung "als frisch erkannt" nach einem Zonenwechsel: mitzählende Gem-Erfahrung

Peter, 2026-08-10 (ToDo.md): "Beim Refresh der Itemliste nach dem
Zonenwechsel aus einer Map ins Hideout werden auch die angelegten Items
als frisch erkannt." Betrifft die Türkis-Hervorhebung aus §4.20 — sie
soll geänderte/neue Items zeigen, meldete nach Peters Beobachtung aber
auch bereits getragene Ausrüstung, mit der nichts geschehen war.

**Erste Vermutung (GGG vergibt Ausrüstung bei Zonenwechseln neue
Item-IDs) widerlegt, bevor irgendetwas geändert wurde.** Gegen Peters
echte Logs geprüft: `_log_publish_interval` (§_PublishWatch, 2026-08-05)
protokolliert für jede Inventaränderung Zu-/Abgänge in einer Zeile. Eine
ID-Neuvergabe müsste dort als GLEICHZEITIGER Zu- UND Abgang derselben
Größenordnung direkt nach einem Zonenwechsel auftauchen. Das Muster kam
in den Logs nicht vor — was dort steht (`+N/-0` während einer Map, ein
späterer `+0/-N`-Sprung auf die Grundausstattung), erklärt sich
vollständig durch normales Loot-Sammeln und den Truhen-Abwurf im
Hideout. Die reine Zähl-Statistik konnte aber nicht zeigen, ob
stattdessen ein FELD eines bereits getragenen Items zwischen zwei
Abrufen kippt — dafür fehlte das Feld selbst.

**Deshalb zunächst instrumentiert statt geraten gefixt** — dieselbe
Reihenfolge wie bei der Zonenwechsel-Frage in §_PublishWatch: erst
Sichtbarkeit schaffen, dann urteilen. `MainWindow._log_character_item_
diff()` protokolliert seither eine INFO-Zeile, wenn ein Item (anfangs nur
auf einem Ausrüstungs-Slot, `paperdoll.EQUIPPED_SLOTS` — dieselbe
Liste, die auch die Puppe aus §4.16 befüllt) innerhalb von
`_ZONE_EQUIP_DIFF_LOG_WINDOW_S = 5s` nach dem letzten Zonenwechsel als
neu oder geändert auffällt, im zweiten Fall mit den tatsächlich
abweichenden Feldnamen (`_differing_fields`), nie mit den Werten.

**Noch am selben Tag geliefert: 8 von 8 sockelbaren Ausrüstungsteilen,
alle im selben Feld.** Peters nächster Spielabend zeigte beim Zonenwechsel
"The Sarn Encampment" acht INFO-Zeilen binnen 2 Millisekunden, jede mit
demselben Befund: `abweichende Felder: socketedItems`. Betroffen waren
ausschließlich die Slots, die überhaupt Sockel haben können (Weapon,
Weapon2, Offhand, Offhand2, Gloves, Boots, Helm, BodyArmour) —
Amulett, Ringe, Gürtel und Flaschen (nicht sockelbar) blieben unauffällig.
Acht verschiedene Sockel-Gems hätten nicht im selben Sekundenbruchteil
zufällig gleichzeitig eine echte inhaltliche Änderung erfahren; das
Muster zeigt stattdessen etwas Strukturelles.

**Erste Erklärung (instabile Listen-Reihenfolge) war naheliegend — und
falsch.** Dass zwei identische Gems in vertauschter Reihenfolge über
Pydantics Listenvergleich (`Item.__eq__`, feldweise über alle Attribute
inkl. `extra="allow"`) als "verschieden" gelten, ließ sich zwar in einem
Minimaltest zeigen; dass GGG tatsächlich umsortiert, aber nicht. Der
erste Versuch normalisierte deshalb nur die Reihenfolge — und Peter
meldete beim nächsten Spielabend: "Meine angelegten Gegenstände werden
immer noch markiert."

**Nachgemessen statt nachgebessert.** Die inzwischen laufende
Gem-XP-Mitschrift (§4.35) hatte 47 aufeinanderfolgende Messpunkte aus
Peters echter Spielrunde aufgezeichnet, samt der Reihenfolge, in der die
Gems je Slot ankamen. Auswertung: **null** reine
Reihenfolge-Änderungen über alle 47 Punkte — die Vermutung war
widerlegt. Dieselben Daten zeigten dafür die echte Ursache: Zwischen
zwei nur zwölf Sekunden auseinanderliegenden Abrufen hatten **25 von 29
Sockel-Gems neue Erfahrungswerte**. Die Erfahrung zählt beim Spielen
schlicht permanent hoch, steckt in `socketedItems` — und macht damit
jedes sockelbare Ausrüstungsteil bei praktisch jedem Refresh zu einem
"geänderten" Item. Genau acht Slots, genau die sockelbaren, genau das
beobachtete Muster.

**Fix:** `_stable_item_dump(item)` (Modulebene, `main_window.py`) ersetzt
in `_diff_character_items` den rohen Pydantic-Vergleich. Sie ruft
`item.model_dump()` und entfernt darin über `_gem_without_experience()`
aus jedem Sockel-Gem die Einträge aus
`_VOLATILE_GEM_PROPERTIES = ("Experience",)`; zusätzlich sortiert sie
`_VOLATILE_LIST_ORDER_FIELDS = ("socketedItems",)` nach der `id` jedes
Eintrags. Die Sortierung bleibt als kostenlose Vorsichtsmaßnahme
bestehen, ist aber ausdrücklich als **unbelegt** gekennzeichnet, damit
sie niemand später als gemessene Tatsache weiterträgt.

Beides kann eine ECHTE Änderung nicht verstecken: Die Gem-STUFE bleibt
im Vergleich (ein Gem, das aufsteigt, soll sichtbar sein — nur sein
Erfahrungsbalken fliegt raus), ein ausgetauschtes Gem unterscheidet sich
weiter in seiner `id`. `_gem_without_experience()` gibt bewusst eine neue
Dict-Ebene zurück, statt zu filtern und zurückzuschreiben: `model_dump()`
reicht die über `extra="allow"` mitgeführten Rohfelder unkopiert durch,
eine Änderung an Ort und Stelle verstümmelte also den
zwischengespeicherten Item-Zustand — und damit ausgerechnet die
Grundlage der Mitschrift aus §4.35.

`_differing_fields` (die Diagnose-Zeile von oben) nutzt dieselbe
Normalisierung, sonst würde sie nach dem Fix weiterhin "geändert"
behaupten, obwohl der eigentliche Vergleich das längst nicht mehr so
sieht.

**Zwischenschritt, der sich als Fehlspur erwies — und trotzdem bleibt.**
Auf Peters Screenshot schien die ganze Tabelle türkis, auch Ringe und
Flaschen, also Slots ohne Sockel, für die die Gem-Erfahrung als Erklärung
ausscheidet. Ein feldweiser Vergleich seines echten Caches über zwanzig
Minuten Spielzeit fand an genau diesen Items **kein einziges**
abweichendes Feld — ein Widerspruch, der sich auflöste, als Peter selbst
klarstellte: "Schau dir den Screenshot nochmal genau an, die Ringe und Co.
leuchten gar nicht." Betroffen war nur die Ausrüstung, der Fix greift also
vollständig.

Die daraufhin gebaute Erweiterung der Diagnose bleibt trotzdem bestehen:
Sie deckt jetzt ALLE Slots ab statt nur `EQUIPPED_SLOTS` (die Zeile
benennt die Ausrüstung weiterhin als solche) und schreibt bei jedem
Refresh eine Zusammenfassung "Hervorhebung *Charakter*: N von M
angezeigten Zeilen (X neu, Y geändert, davon Z mit Gem-Aufstieg)". Die
alte Beschränkung war eine
Wette darauf, WO der Fehler steckt; liegt sie daneben, kostet das einen
ganzen Spielabend Wartezeit. Und die Zusammenfassung hätte den
Widerspruch oben in einer Zeile aufgelöst, statt ihn über einen
Cache-Vergleich und eine Rückfrage zu klären: Weicht ihr N von dem ab,
was auf dem Bildschirm zu sehen ist, liegt der Fehler in der Darstellung
statt im Vergleich.

**Dritte Meldung, 2026-08-11 — diesmal war die Anzeige im Recht.** Peter:
"komischerweise wurde auch Weapon und Offhand markiert, aber als einzige
der angelegten Items." Genau dafür war die Diagnose gebaut, und sie hat
den Fall in einem Durchgang geklärt: Die Zusammenfassungszeile
(22:59:13, 7 von 23 Zeilen) und die Gem-Mitschrift zeigen für dieselbe
Sekunde `Increased Area of Effect Support 3 → 5` in `Weapon2` und
`Minion Life Support 5 → 8` in `Offhand`. Beide Gems hatte Peter zwölf
Minuten vorher frisch eingesockelt (davor steckten dort Armageddon Brand
und Elemental Army Support); auf niedriger Stufe steigen sie im
Minutentakt auf. Der Abgleich JEDER Ausrüstungs-Markierung des Abends
gegen die Mitschrift ließ keinen unerklärten Fall übrig — alle gingen
auf einen Stufenaufstieg oder einen Sockelwechsel zurück, also auf
genau die Änderungen, die die Hervorhebung zeigen SOLL. Nebenbefund
derselben Auswertung, in `docs/api-notes/poe-verhalten.md` festgehalten:
Die `requirements` eines Items sind das Maximum über das Item und seine
Gems (Gem-Anteile tragen `"suffix": "(gem)"`), weshalb ein
Gem-Aufstieg zusätzlich das Feld `requirements` kippen lässt.

**Zwei Folgeentscheidungen, beide von Peter am selben Abend.**

*Flaschen-Ladungen fallen aus dem Vergleich.* Sie stehen in
`properties` als `Currently has {0} Charges` und schwanken beim Spielen
dauernd — dieselbe Sorte Rauschen wie die Gem-Erfahrung, an einem Abend
viermal grundlos aufgeleuchtet. Peter: "Flaschen-Ladungen spielen
generell keine Rolle, da sich die maximale Anzahl nicht ändert und beim
Spielen die aktuellen Ladungen ständig schwanken." Umgesetzt als
`_VOLATILE_ITEM_PROPERTIES` in `_stable_item_dump` — bewusst nur diese
eine Eigenschaft und nicht `properties` als Ganzes, denn dort steht auch
die Stapelgröße von Währung, und die ist eine echte Änderung.

*Ein Gem-Aufstieg wird grün statt türkis.* Peter: "die Markierungsfarbe
für gelevelte Gems auf Grün ändern, dann erkennt man sofort dass ein Gem
eine Stufe aufgestiegen ist." `MainWindow._gem_leveled_ids()` vergleicht
je Item die Stufe jedes Sockel-Gems mit dem vorigen Stand und reicht die
betroffenen `item.id` als `leveled_ids` ans Tabellenmodell weiter, das
dort `ROW_GEM_LEVELED_COLOR` statt `ROW_CHANGED_COLOR` mischt. Nur Gems,
die in BEIDEN Ständen stecken, zählen: Ein frisch eingesockeltes Gem
bringt seine Stufe mit, ohne aufgestiegen zu sein — das ist ein
Sockelwechsel und bleibt türkis.

Die Berechnung sitzt bewusst NEBEN `_diff_character_items` statt darin:
Sie ist eine zusätzliche Aussage ÜBER eine bereits erkannte Änderung,
keine weitere Art von Änderung. `leveled_ids` ist deshalb immer eine
Teilmenge von `changed_ids`, und im Model gewinnt die speziellere
Aussage.

Peters Alternativvorschlag — die Zeile in der Farbe des aufgestiegenen
Gems (Rot/Grün/Blau) — wurde verworfen, mit Begründung im Theme
hinterlegt: In einem Item können mehrere Gems verschiedener Farben
gleichzeitig aufsteigen (am 2026-08-11 im Schild ein blaues und ein
rotes), dann gäbe es keine richtige Antwort; außerdem kollidierten Blau
und Rot mit der Rarity-Färbung und dem Korruptionsrot des Markups. Grün
ist dasselbe `DASH_OK` wie überall sonst in der Anwendung.

Die Zusammenfassungszeile nennt seither beide Farben ("*N* neu, *M*
geändert, davon *K* mit Gem-Aufstieg") — sonst ließe sich der Bildschirm
nicht mehr gegen sie prüfen, und genau dafür ist sie da.

Getestet: `tests/test_main_window_helpers.py` — mitzählende Gem-Erfahrung
zählt nicht als Änderung, Gegenprobe Stufenaufstieg zählt weiterhin, die
Normalisierung lässt den zwischengespeicherten Item-Zustand unberührt,
Mechanismus und Zeitfenster der Diagnose-Zeile, Rucksack-Items werden
mitgeloggt aber nicht als Ausrüstung benannt, Zusammenfassung mit
Gegenprobe (ohne Hervorhebung keine Zeile).

---

### 4.34 Charakter-XP/h (erster Schritt einer größeren Idee)

Peter, 2026-08-10, direkt aus der §4.33-Diagnose entstanden: Beim
Aufräumen von `socketedItems` fiel auf, dass jedes Sockel-Gem sein
eigenes `additionalProperties`-"Experience"-Feld mitbringt
(`{"name": "Experience", "values": [["66921722/212046017", 0]],
"progress": 0.32}`, real geprüft an Peters Cache) — und dass GGGs
`/character/{name}`-Antwort denselben Gedanken auch eine Ebene höher
trägt: `level`/`experience` DES CHARAKTERS liegen direkt neben den
Item-Listen (`equipment`/`inventory`/`jewels`/`rucksack`), wurden von
`PoeApiClient.get_character_items()` aber bislang komplett verworfen.
Peters Idee daraufhin: ein kleiner Graph für Gem-XP/h und Charakter-
XP/h, dazu eine Benachrichtigung bei Stufe 20 und eine Anzeige, ob ein
Gem gerade pausiert ist (EP-Zuwachs lässt sich in PoE gezielt
abschalten).

**Peters Ausgangsannahme war richtig — die Zwischenkorrektur hier war
falsch.** Peters Vermutung: "die Gems bekommen ja eh alle die gleiche
XP, einer reicht als Stellvertreter". Aus einem einzelnen Snapshot
seines Charakters schien das widerlegt: Mehrere Gems teilten sich exakt
denselben XP-STAND, andere lagen weit zurück, einige standen auf Stufe
1 — woraus hier zunächst geschlossen wurde, ein Gem bekomme XP nur für
das, was der Skill selbst bewirkt.

Die Messung über eine volle Spielstunde (§4.35, 231 Messpunkte) zeigt
das Gegenteil: **Jedes gesockelte Gem bekam in jedem einzelnen Schritt
exakt denselben Zuwachs** — über acht XP-Sprünge hinweg zusammen
12.187.472 XP, bei allen 25 aktiven Gems auf die Einheit gleich. Der
unterschiedliche STAND kommt allein aus der Vorgeschichte (wann ein Gem
gesockelt wurde, wie oft es zwischendurch draußen war), nicht aus einer
unterschiedlichen Zuteilung. Genau das ließ sich aus einem einzelnen
Snapshot nicht sehen: Er zeigt Bestände, die Frage war aber eine nach
Zuwächsen.

Die beiden Abweichungen im Datensatz bestätigen die Regel, statt sie zu
brechen:

- `Summon Skitterbots` fehlt zwischen 21:04 und 21:14 komplett aus den
  Daten (Peter hatte es kurz ausgesockelt) und verpasste dadurch genau
  den einen Sprung von 1.066.352 XP, der in dieser Zeit lag — sein
  Rückstand am Ende beträgt exakt diesen Betrag.
- `Ice Nova` wurde um 21:04 frisch gesockelt und bekam beim nächsten
  Sprung nicht die vollen 1.066.352, sondern 147.967 — genau so viel,
  wie bis zu seiner Obergrenze noch hineinpasste.

Für die Anzeige heißt das: Ein einzelnes Gem TAUGT als Stellvertreter,
solange es durchgehend gesockelt und nicht am Anschlag ist.

**Umgesetzt, ausdrücklich nur der erste, kleinste Schritt: Charakter-
XP/h als Zahl, kein Graph, keine Gems.** Drei Gründe für diese
Reihenfolge: (1) Charakter-`experience` ist ein einzelner Wert ohne
Peters Fehleinschätzung, die erst noch aufgeklärt werden musste. (2)
Ein Graph braucht eine Zeitreihe — die gibt es noch nicht, nur den
jeweils letzten Stand (wie beim Cache generell). (3) Eine Zahl lässt
sich in einem Zug bauen UND testen, ein neues Diagramm-Widget wäre ein
eigener Entwurfsschritt.

**Kein zusätzlicher Request.** `PoeApiClient.get_character_items()`
liefert jetzt `tuple[level, experience, items]` statt nur `items` —
dieselbe Antwort, nur nicht mehr teilweise verworfen. Der Worker emittiert
dafür ein neues, EIGENES Signal `character_snapshot_loaded(name, level,
experience)` neben dem unveränderten `character_items_loaded` — bewusst
nicht das bestehende Signal erweitert, damit dessen etablierte
Verwerter (u. a. `_on_character_items`, in Dutzenden Tests direkt
aufgerufen) unangetastet bleiben.

**`_XpWatch` (Dataclass) hält pro Charakter EINEN Session-Durchschnitt**
— bewusst keine gleitende Rate der letzten Minuten, das wäre die
naheliegende Verfeinerung, sobald der eigentliche Graph gebaut wird
(dafür reicht ein Wert pro Charakter nicht mehr, dann braucht es eine
echte Zeitreihe).

**Gemessen wird von Veröffentlichung zu Veröffentlichung, nicht bis
"jetzt".** Peter, 2026-08-10: "Wir müssen die XP-Berechnung pausieren,
sobald sie sich nicht mehr ändert." Die erste Fassung teilte den Zuwachs
durch die verstrichene Uhrzeit seit dem ersten Abruf — steht der
Charakter still, wächst dabei nur der Nenner und die Anzeige sinkt,
obwohl gar nichts passiert ist.

**Zweiter Anlauf nötig: nur das letzte Intervall, und darin nur die
aktive Zeit.** Peter, 2026-08-11: "Ingame wird mir meine momentane XP/h
bei 182.3M angezeigt, im Tool bei 14.1M." Die Fassung von gestern
verhinderte zwar, dass Zeit NACH der letzten Veröffentlichung
verwässert — nicht aber die Pausen DAZWISCHEN. An seiner Sitzung
nachgerechnet: vier Veröffentlichungen in 114 Minuten, darunter eine
Lücke von 87 Minuten ohne Spiel. Über die ganze Spanne 2,3 Mio./h, über
das letzte Intervall 23,8 Mio./h — Faktor 10,4, genau die Größenordnung
seiner Abweichung.

Der Rest steckte im Nenner, und dafür brauchte es zwei Anläufe.

**Erster Anlauf, falsch:** die Uhr beim ersten Zonenwechsel NACH einer
Veröffentlichung starten — unter der Annahme, der Charakter stehe beim
Veröffentlichen immer in der Zone, in die er gerade zurückgekehrt ist.
Peter entlarvte das binnen einer Runde ("Hatte gerade 1.53B XP/h"). Sein
Protokoll zeigt, warum:

| Zeit | Ereignis |
|---|---|
| 22:07:37 | Zonenwechsel → Trial of Lingering Pain |
| 22:07:40 | Veröffentlichung +9.677.329 |
| 22:10:01 | Zonenwechsel → Plaza |
| 22:10:04 | Veröffentlichung +2.192.450 |

Die Veröffentlichung um 22:07:40 kam, als er längst in der nächsten Zone
war. Der "erste Zonenwechsel danach" war deshalb nicht der Aufbruch,
sondern schon wieder der Ausgang — drei Sekunden vor der nächsten
Veröffentlichung. 2.192.450 XP auf 3 Sekunden ergeben 2,99 Mrd. XP/h.

**Richtig ist die Verweildauer in der zuletzt verlassenen Zone**
(`_zone_dwell_seconds`, gespeist aus dem ZoneWatcher, der ohnehin läuft):
Eine Veröffentlichung folgt 1–3 Sekunden auf einen Zonenwechsel und
trägt die Erfahrung, die in der gerade verlassenen Zone verdient wurde.
Der Nenner ist damit der Abstand der letzten beiden Zonenwechsel — für
die 22:10:04-Zeile die 144 Sekunden im Trial statt drei, also 54,8
Mio./h.

Auch das kommt ohne eine Liste von Städten und Hideouts aus, aber aus
einem anderen Grund als zunächst gedacht: **Eine Zone, in der nichts
verdient wurde, erzeugt beim Verlassen gar keine Veröffentlichung** — die
Erfahrung hat sich ja nicht geändert. Jede Veröffentlichung gehört damit
von selbst zu einer Zone, in der etwas passiert ist. Ist die
Zonen-Beobachtung aus (Standard) oder folgt eine Veröffentlichung
ausnahmsweise nicht auf einen Zonenwechsel (Händler, §4.36 — dort liegen
17 bis 57 Sekunden dazwischen, `_XP_ZONE_TRIGGER_WINDOW_S` fängt das ab),
fällt die Rechnung auf das volle Intervall zurück.

**Nie länger als seit der vorigen Veröffentlichung** (`_interval_seconds`,
ergänzt 2026-08-13 aus Peters Live-Daten). Sein Log jenes Abends:

```
18:29:07  Zone betreten (Burial Chambers)
18:36:53  +14.550.145 in 485s (volles Intervall)   <- MITTEN in der Map
18:38:52  +6.167.471 in 582s in der verlassenen Zone -> 38,1 Mio./h
```

GGG veröffentlicht meist beim Zonenwechsel, aber rund 5 % kommen als
Nachzügler mittendrin (`poe-verhalten.md` §1). Passiert das, sind bei der
nächsten Veröffentlichung große Teile der Verweildauer längst
abgerechnet — hier 466 der 582 Sekunden. Die übrigen 6,17 Mio. wurden in
119 Sekunden verdient: **186,6 Mio./h, nicht 38,1**.

Dieselbe Erfahrung lässt sich nicht zweimal verdienen. Ein Abschnitt
beginnt deshalb beim SPÄTEREN von Zonenbetreten und voriger
Veröffentlichung. Im Normalfall liegt die Veröffentlichung vor dem
Betreten (sie fiel beim Verlassen der vorigen Zone an), dann ändert die
Grenze nichts — alle bisherigen Messungen bleiben unverändert.

Ebenso wichtig ist die Nebenwirkung im Graphen (§4.40): Ohne diese
Grenze überlappen sich zwei Balken zeitlich und beanspruchen dieselben
Minuten doppelt.

Gegen Peters echte Runde gerechnet, alte gegen neue Regel:

| Veröffentlichung | Zuwachs | erster Anlauf | Verweildauer | Zone |
|---|---|---|---|---|
| 22:02:48 | 9.136.411 | 147,7 Mio./h | 149,5 Mio./h | Mineral Pools (220 s) |
| 22:07:40 | 9.677.329 | 160,8 Mio./h | 162,8 Mio./h | Plaza (214 s) |
| 22:10:04 | 2.192.450 | **2.988,6 Mio./h** | 54,8 Mio./h | Trial of Lingering Pain (144 s) |
| 22:11:36 | 1.025.082 | **1.528,1 Mio./h** | 40,1 Mio./h | Plaza (92 s) |
| 22:15:04 | 2.668.286 | 103,7 Mio./h | 106,9 Mio./h | Dark Forest (90 s) |

Die niedrigen Werte in der Mitte sind kein Rest des Fehlers, sondern das
Ergebnis: Ein Trial und ein kurzer Plaza-Lauf bringen tatsächlich weniger
als eine volle Map. Peters Anzeige im Spiel stand in derselben Runde bei
182,3 Mio./h — dieselbe Größenordnung wie die 147 bis 163 der
Map-Zeilen.

**Schneller geht es nicht.** In Peters Protokoll fiel JEDE
Veröffentlichung mit der Rückkehr ins Hideout zusammen; die Erfahrung
einer Map erscheint erst, wenn er sie verlässt. Peters Wunsch "XP/h erst
am Ende der Map ist sehr unschön" beschreibt damit GGGs Verhalten, nicht
unseres — außerhalb des Spiels existiert die Zahl vorher nirgends, und
im Spiel läse man sie nur über einen Speicherzugriff aus, der ein
Bann-Risiko wäre. Was bleibt, ist die Rate ehrlich zu datieren: Die
Statuszeile hängt ab einer Minute " (7m ago)" an, sonst sähe eine alte
Zahl aus wie eine frische.

**Jede Veröffentlichung steht jetzt im Log.** Über die Charakter-XP gab
es bis dahin keine einzige Zeile — als Peters Anzeige um Faktor 13
danebenlag, musste die Ursache über die Gem-Mitschrift ERSCHLOSSEN
werden, weil die eigentlichen Zahlen nirgends standen. Das ist der
Fehler, den man genau einmal macht (`_log_xp_publication`, ein paar
Zeilen pro Spielstunde).

Die Messung aus §4.35 zeigt, warum eine Pausenerkennung über eine
Schwelle ("seit N Sekunden keine Änderung") der falsche Weg gewesen
wäre: GGG veröffentlicht die Erfahrung in Schüben, in einer Spielstunde
nur achtmal, mit Abständen von anderthalb bis **siebzehn** Minuten. Jede
Schwelle unter zwanzig Minuten hätte mitten im Spielen pausiert, jede
darüber die echte Pause zu spät bemerkt.

Deshalb ohne Schwelle: Der Zeitzähler läuft nur von Veröffentlichung zu
Veröffentlichung. Hört die Erfahrung auf zu kommen, hört auch die
gemessene Spanne auf zu wachsen — die Anzeige friert von selbst ein,
ohne dass irgendwo "pausiert" entschieden werden müsste. Nebeneffekt,
der die Zahl zusätzlich ehrlicher macht: Die erste beobachtete
Veröffentlichung enthält Erfahrung, die teils VOR dem Sitzungsstart
verdient wurde; als Startpunkt statt als Zuwachs verwendet, fällt sie
sauber heraus. Ein Rückgang zählt wie jede andere Änderung — ab Akt 5
kostet der Tod Erfahrung, und ein Intervall, in dem mehr gestorben als
verdient wurde, ist eine Aussage.

Dieselbe
Session-lokal-Regel wie überall sonst in diesem Bereich (`_PublishWatch`,
`stale_baseline`): ein aus der Datei geladener alter Stand taugt nicht
als Basis, sonst würde ein Levelaufstieg während einer Pause vor dem
heutigen Sitzungsstart als absurd hohe Rate ausgewiesen. `_on_character_
snapshot()` läuft bei JEDEM Abruf mit, auch beim stillen Hintergrund-
Refresh eines nicht angezeigten Charakters — mehr Messpunkte für eine
stabilere Rate, unabhängig davon, was gerade sichtbar ist.

An Peters nächster Runde nachgerechnet, wie groß allein dieser erste
Schritt ausmachte: Im Abschnitt 22:30–23:10 kamen 3.140.232 Gem-XP in
drei Schüben zwischen 22:45 und 23:00 an. Über die Uhrzeit gerechnet
ergibt das 4,8 Mio. XP/h, über die Spanne der Veröffentlichungen 11,0
Mio. — die ersten fünfzehn Minuten hatte er in der Stadt identifiziert
und verkauft.

Angezeigt (erst ab der zweiten beobachteten Änderung, vorher `None`,
keine Falschbehauptung wie "0 XP/h"): in der Statuszeile neben der
Item-Anzahl, sobald ein Charakter offen ist — `_format_xp_rate()` wählt
automatisch K/M/B passend zur Größenordnung von PoEs kumulierter
Erfahrung (typischerweise zweistellige Millionen pro Stunde).

Getestet: `tests/test_client.py`, `tests/test_api_worker.py` (die neue
Signal-Emission), `tests/test_main_window_helpers.py` (Baseline ohne
Rate, eine einzelne Änderung reicht noch nicht, Intervall zwischen zwei
Veröffentlichungen mit unveränderten Abrufen dazwischen, Einfrieren nach
drei Stunden Stillstand, Peters Zahlenbeispiel mit der 87-Minuten-Lücke,
eine frühere Pause zieht die Rate nicht herunter, Verweildauer der
verlassenen Zone als Nenner, eine mitten in der nächsten Zone
eintreffende Veröffentlichung sprengt die Rate nicht, Rückfall aufs volle
Intervall ohne nahen Zonenwechsel, Altersvermerk in der Statuszeile, jede
Veröffentlichung im Log, ein Rückgang durch Tod, Formatierung).
Gegenproben gefahren: Mit der Spannen-Rechnung schlägt Peters
Zahlenbeispiel fehl, ohne die Verweildauer-Regel sein 1,53-Mrd.-Fall.

**Offen für eine Fortsetzung:** Gem-XP/h pro Gem (kein Stellvertreter),
ein echter Zeitreihen-Speicher fürs Diagramm selbst, die Stufe-20-
Benachrichtigung, sowie die von Peter zusätzlich
vorgeschlagene, aber vorerst zurückgestellte "reduzierte/angepasste"
Charakter-XP/h nach Level und Zone (PoEs Erfahrungs-Straf-Formel — nicht
zuverlässig genug bekannt, um sie ungeprüft zu implementieren, siehe
ToDo.md).

---

### 4.35 Gem-XP-Mitschrift für die Messung (`services/gem_xp_log.py`)

Peter, 2026-08-10, noch am selben Abend: "Ich werde demnächst eine Runde
spielen, da können wir mal die XP/h pro Gem messen. Die genauen Werte
bzw. der Verlauf würde mich interessieren." Vorbereitung auf genau die
Messung, die §4.34 als Voraussetzung für eine PRO-GEM-Anzeige nennt —
ohne echte Zeitreihe lässt sich die dort widerlegte "ein Gem reicht"-
Annahme nicht weiter auswerten.

**Zwei Fälle sollten unterscheidbar sein, die Peter ausdrücklich nannte:**
ein Gem, das absichtlich nicht weitergelevelt wird, und eines, das gerade
NICHT weiterleveln KANN, weil eine Voraussetzung (meist ein Attribut)
fehlt. Vor der Messung sah es so aus, als trenne das Feld
`nextLevelRequirements` beide sauber: Genau die Level-1-Gems tragen es
und stehen mit `progress: 1` auf ihrer Experience. Die Spalte hieß
deshalb zunächst `capped_by_requirement`.

**Die Messung hat das korrigiert** (eine Spielstunde, 231 Messpunkte).
`nextLevelRequirements` nennt schlicht die Anforderungen der NÄCHSTEN
Stufe — unabhängig davon, ob sie erfüllt sind. Nachgerechnet an Peters
eigener Ausrüstung: `Blood Rage` verlangt 50 Dex, sein Charakter hat
nachweislich mindestens 108; `Lifetap Support` verlangt 21 Str bei
mindestens 151. (Die frühere Angabe "Peters Charakter hat nur 41 Dex"
in einer vorigen Fassung dieses Abschnitts war falsch.) Kein einziges
seiner Gems war blockiert.

Die eigentliche Mechanik dahinter, aus dem Verlauf abgelesen und von
Peter bestätigt: **Gems steigen in PoE nicht von selbst auf.** Solange
nicht geklickt wird, bleibt der Balken voll und die Erfahrung
eingefroren. `Ice Nova`, um 21:04 frisch gesockelt, ging in einem
einzigen Erfahrungsschub von Stufe 1 auf 4 (Peter levelte es gezielt) und
stand danach still, obwohl alle Anforderungen erfüllt waren. Genau so
hält er auch `Blood Rage`, `Frostblink` und `Lifetap Support` absichtlich
auf Stufe 1.

Damit sind es drei Zustände statt zwei, alle drei aus der Mitschrift
ablesbar: **levelt normal** (kein `nextLevelRequirements`), **wartet auf
Level-Up** (`waiting_for_levelup`) und **pausiert** — Peters drittes
Wort dafür, dass ein Gem ausgesockelt ist. Es taucht dann gar nicht auf
und verpasst jeden Erfahrungsschub in der Zeit; an `Summon Skitterbots`
nachgewiesen, dem nach zehn Minuten draußen exakt der eine Schub von
1.066.352 XP fehlte, der in dieses Fenster fiel.

Peters ursprünglicher zweiter Fall bleibt trotzdem darstellbar, nur
braucht er einen Abgleich statt eines Feldes: `_attribute_floor()` leitet
aus der GETRAGENEN Ausrüstung eine sichere Untergrenze für Level, Str,
Dex und Int ab (was der Charakter trägt, erfüllt er zwingend), und
`requirement_met` hält die Gem-Anforderung dagegen.

**Diese Spalte kennt nur `True` und leer, und das ist der Punkt.** Die
erste Fassung hieß `requirement_unmet` und meldete `True`, sobald eine
Anforderung die Untergrenze übersteigt — ein Fehlschluss: Über einer
UNTERgrenze zu liegen sagt nichts darüber aus, ob der Charakter den Wert
erreicht. Peters echte Attribute liegen weit über dem, was seine
Ausrüstung verlangt (Passivbaum, Juwelen), die Spalte hätte also
reihenweise Gems fälschlich als festhängend gemeldet. Beweisbar ist nur
die andere Richtung: Liegt die Anforderung UNTER etwas, das der Charakter
ohnehin trägt, ist sie sicher erfüllt. Für alles andere steht die
Untergrenze selbst in der Zeile (`attribute_floor`) — damit lässt sich
beim Auswerten gegen den tatsächlichen Attributwert rechnen, den nur der
Charakterbogen im Spiel kennt.

Peter hat seine echten Werte anschließend genannt, womit die Ableitung
einmal gegengeprüft ist: Str 280 gegen eine Untergrenze von 151, Int 145
gegen 131, Dex 114 gegen 108. Alle drei Grenzen halten, und der Abstand
zeigt zugleich, warum die Gegenrichtung nicht funktioniert — bei Str
liegen 129 Punkte zwischen Beleg und Wirklichkeit. Nur bei seinem
schwächsten Attribut ist die Grenze fast exakt. Die Slot-Liste
dafür (`_WORN_SLOTS`) ist bewusst eine eigene, knappe — nicht
`paperdoll.EQUIPPED_SLOTS`: Ein Import aus dem UI-Paket zöge Qt-Widgets
in einen reinen Service, und die beiden Listen haben gegenläufige
Ansprüche (die dort muss vollständig sein, diese hier sicher).

**Läuft nur beim Entwickeln, nicht im ausgelieferten Programm.** Peter,
2026-08-10: "Den Gem-Log lassen wir nicht in der Release drin, das ist
dort unnütz." Trifft zu — die Mitschrift ist ein Messwerkzeug für die
Fragen aus §4.34, kein Feature: rund 1,8 MB pro Spielstunde, die nur
jemand auswertet, der weiß, wonach er sucht. `enabled()` macht das an
der Auslieferungsform fest (`config.RUNNING_AS_EXE`, dieselbe
`sys.frozen`-Erkennung, die dort schon die Pfade auflöst) statt an einer
Einstellung: Aus dem Quellcode heraus läuft sie von selbst mit, in der
gepackten .exe bleibt sie still. Niemand muss daran denken, sie vor
einem Release abzuschalten, und beim Weiterentwickeln ist sie ohne Zutun
da. `POEVIEW_GEM_XP_LOG=1` überstimmt das für den einen absehbaren Fall,
der sonst durchs Raster fiele: eine fertig gebaute .exe vor dem Release
noch einmal mit Mitschrift durchspielen.

Die Prüfung sitzt in `append()` selbst, nicht an der Aufrufstelle in
`_on_character_items` — wer die Mitschrift abschalten will, soll das an
EINER Stelle finden, und ein künftiger zweiter Aufrufer erbt die
Entscheidung, ohne sie zu kennen. Abgeschaltet heißt dabei wirklich
nichts anfassen, auch nicht das Beiseitelegen einer älteren Datei
(sonst benennt ein ausgeliefertes Programm ungefragt Dateien um). Und
weil sie nie bei einem Nutzer ankommt, steht sie auch nicht im
CHANGELOG.

**Eine Zeile pro Sockel-Gem, bei jedem Charakter-Abruf** (`gem_xp_log.
append()`, verdrahtet in `_on_character_items`) — auch im stillen
Hintergrund-Refresh, unabhängig davon, welcher Charakter gerade angezeigt
wird (mehr Messpunkte für den Verlauf). Spalten: Zeitstempel, Charakter,
Slot, Gem-ID/-Name, Support-Flag, Level, Qualität, Erfahrung (aktuell/
Maximum/Anteil), `waiting_for_levelup`, `requirement_met`, die lesbare
Fassung von `nextLevelRequirements` und die belegte Attribut-Untergrenze
`attribute_floor`. Ändern sich die Spalten,
legt `_retire_foreign_header()` eine vorhandene Mitschrift unter ihrem
Zeitstempel beiseite, statt Zeilen unter fremde Überschriften zu
schreiben — sonst wäre die Datei stillschweigend unbrauchbar, und zwar
rückwirkend auch für den Teil, der vorher gestimmt hat (Peters erste
Messstunde steckt in einer Datei mit der alten Spalte).
Reine CSV statt eines eigenen Zeitreihen-Formats
— für eine Handvoll Spielstunden zieht man das genauso gut in jede
Tabellenkalkulation, und es ist in einer Zeile erklärt. Ohne Sockel-Gems
(Ringe, Amulett, Rucksack) wird nichts geschrieben, auch keine leere
Zeile.

**`log_path()` ist eine Funktion, keine Konstante** — dieselbe Falle wie
bei `cache_backup.directory()`: `config.LOG_DIR` wird beim Import von
`config.py` EINMAL aus dem damaligen `APP_DATA_DIR` berechnet und ändert
sich nicht mehr mit, wenn ein Test später `APP_DATA_DIR` umbiegt. Das fiel
erst beim Testen selbst auf: Der bestehende, seit §_isolated_local_state
laufende Test-Schutz patcht `APP_DATA_DIR`, aber `LOG_DIR` blieb davon
unberührt — jeder Test, der eine Charakter-Aktualisierung simuliert
(Dutzende in `test_main_window_helpers.py`), hätte sonst in Peters ECHTEN
Log-Ordner geschrieben. `tests/conftest.py`s Autouse-Fixture patcht
`config.LOG_DIR` deshalb jetzt zusätzlich und direkt, nicht nur
`APP_DATA_DIR` — ein systemischer Fix, der jeden künftigen Code vor
demselben Fehler schützt, nicht nur diesen einen.

**Was die erste Messung ergeben hat** (2026-08-10, 21:00–22:00, 231
Messpunkte, keine Lücke) — die Grundlage für jede weitere Arbeit an §4.34:

- **Alle gesockelten Gems bekommen exakt denselben Zuwachs.** Peters
  Ausgangsannahme war richtig, siehe die Richtigstellung in §4.34.
- **Die Erfahrung kommt in Schüben, nicht kontinuierlich.** In 230
  Messschritten gab es NUR ACHT mit Zuwachs; sieben davon 1–3 Sekunden
  nach einem Zonenwechsel, der achte nach einer Händler-Interaktion
  (§4.36). Über die Stunde ergibt das 12.187.472 XP, also rund 12,2 Mio.
  XP/h — die Fünf-Minuten-Werte schwanken dabei zwischen 0 und 38 Mio.
  **Für die geplante Anzeige heißt das: Alle 16 Sekunden zu messen bringt
  nichts.** Ein Graph braucht einen Punkt je Veröffentlichung (Treppe)
  oder eine Glättung über mindestens 10–15 Minuten; eine Momentanrate
  zwischen zwei Abrufen wäre fast immer null.

**Der Blockade-Fall, erstmals beobachtet (2026-08-10, 23:21:58).** Peter
hat ihn eigens erzeugt: "Ich werde jetzt einfach mal einen Gem leveln,
dessen Bedingungen ich irgendwann nicht mehr erfülle." Ein Vaal Blade
Vortex, über eine knappe Stunde von Stufe 5 auf 12 hochgeklickt, steht
seither mit vollem Balken und `nextLevelRequirements: Level 53; Dex 119`
— bei tatsächlichen 114 Dex. Zum ersten Mal hängt ein Gem wirklich fest
statt nur zu warten.

Die Spalten verhalten sich dabei genau wie entworfen: Bei den drei
absichtlich auf Stufe 1 gehaltenen Gems steht `requirement_met = True`
(50 Dex, 21 Str, 20 Int liegen unter der belegten Untergrenze, sie
warten also nachweislich freiwillig), beim Blade Vortex bleibt die
Spalte leer — 119 Dex liegt über der Untergrenze von 108, und mehr gibt
die Ausrüstung nicht her. Zusammen mit `attribute_floor` in derselben
Zeile ist der Fall mit einer einzigen Zahl von außen entschieden.

Nebenbefund für eine mögliche Verfeinerung: Ein Sockel-Gem trägt auch
seine EIGENEN `requirements` (der Blade Vortex auf Stufe 12: Dex 113).
Steigt ein Gem beobachtet eine Stufe auf, sind dessen Anforderungen in
diesem Moment zwingend erfüllt — daraus ließe sich eine deutlich engere
Untergrenze gewinnen als aus der Ausrüstung. Im vorliegenden Fall wären
das 113 statt 108 gewesen, was den Blade Vortex mit seinen geforderten
119 aber immer noch nicht entschieden hätte. Deshalb vorerst nicht
gebaut.

Getestet: `tests/test_gem_xp_log.py` (still in der .exe, von selbst
aktiv aus dem Quellcode, Umgebungsvariable in beide Richtungen,
abgeschaltet wird keine vorhandene Datei angefasst, Header nur einmal, normal
levelndes Gem vs. wartendes, nachweislich erfüllte Anforderung, der
offene Fall über der Untergrenze, ein Attribut ohne jeden Beleg, nur
getragene Teile zählen für die Untergrenze, ältere Mitschrift mit anderen Spalten wird beiseitegelegt,
mehrere Charaktere in einer Datei, keine Zeile ohne Sockel-Gems),
`tests/test_main_window_helpers.py` (Ende-zu-Ende-Verdrahtung über
`_on_character_items`).

---

### 4.36 Händler-Trigger und das Burst-Budget der Ereignis-Refreshes

Peter, 2026-08-10, aus der Beobachtung heraus: "Die Interaktion mit einem
Händler, Verkaufen, Identifizieren, ... triggert auch das Senden der
neuesten Items von GGG-Seite. Gibt es dabei einen Clients.txt-Eintrag?"
Derselbe Gedanke wie beim Zonenwechsel (§ZoneWatcher, FALLSTRICKE #58):
nicht öfter fragen, sondern **zu den Zeitpunkten fragen, an denen GGG
überhaupt etwas Neues zu liefern hat**.

**Die Frage war beantwortbar, ohne zu raten.** Peters echte Client.txt
(81.639 Zeilen) durchgezählt:

| Zeile | Häufigkeit | Verwendet |
|---|---|---|
| `: Trade accepted.` | 1028× | ja — Verkauf an NPC *und* Spielerhandel |
| `: N Items identified` | 821× | ja |
| `: 1 Item identified` | 78× | ja (eigene Schreibweise!) |
| `: Trade cancelled.` | 60× | **nein** — dabei ändert sich nichts |

`_INVENTORY_LINES` im `ZoneWatcher` erkennt die drei oberen und meldet sie
über ein eigenes Signal `inventory_event(beschreibung)`. Getrennt von
`zone_changed`, weil der Zonenwechsel zusätzlich die Zonen-Anzeige und die
Messungen aus §_PublishWatch füttert — ein Händler-Verkauf hat dort nichts
verloren. Der Refresh selbst ist für beide derselbe
(`_refresh_current_view`). Kosten: null zusätzliche Datei-Zugriffe, die
Client.txt wird ohnehin alle 2 s auf neue Bytes geprüft.

**Das Rate-Limit-Problem und Peters Lösung dafür.** Mehr Trigger heißt
mehr Requests in genau dem 300s-Fenster, das der gleichmäßige Takt
(§_drive_refresh_mode) sorgfältig freihält — und "Trade accepted" kommt
beim Ausräumen des Rucksacks in schneller Folge. Peters Vorschlag:

> "Die dadurch gesparte Zeit auf den Timer zum nächsten Trigger addieren.
> Dann haben wir meinetwegen 4 Trigger kurz hintereinander, aber der 5.
> Trigger kommt dann trotzdem erst nach 60 Sekunden und ab dann wieder
> alle 15 Sekunden oder so."

Zwei Teile, beide umgesetzt:

1. **Schuldenrechnung.** `_note_refresh_mode_job_done` setzt die
   Fälligkeit auf `max(jetzt, bisheriger Termin) + Intervall` statt auf
   `jetzt + Intervall`. Im gewöhnlichen Fall ändert das nichts (der Job
   lief ja, WEIL er fällig war, dann liegt der alte Termin bereits in der
   Vergangenheit). Ein vorgezogener Abruf zahlt dagegen seine Ersparnis
   zurück, statt die Uhr auf null zu stellen — der Gesamtdurchsatz bleibt
   damit exakt der des ungetriggerten Takts, nur anders verteilt.
2. **Burst-Grenze.** Die Schuldenrechnung allein hält keinen einzigen
   Trigger auf; sie verschiebt nur den nächsten Takt. Zwanzig Verkäufe in
   Folge wären zwanzig Requests in wenigen Sekunden und damit sofort
   GGGs 5-pro-10s-Regel. `_trigger_budget_spent()` lässt einen Trigger
   deshalb nur durch, solange der Takt weniger als
   `_TRIGGER_BURST_INTERVALS = 4` Intervalle voraus ist.

Die Grenze steht in **Intervallen**, nicht in festen 60 Sekunden: Das
Takt-Intervall berechnet der Rate-Limiter live aus GGGs tatsächlich
gemeldeten Regeln (`steady_pace_interval_s`, bei "30 Treffer/300s" rund
10-15 s). Peters Verhältnis bleibt damit auch dann erhalten, wenn GGG die
Regel ändert, während eine fest verdrahtete Minute stillschweigend zu
großzügig oder zu knapp würde. Verglichen wird gegen ein **halbes**
Intervall vor dem vollen Vielfachen — nach vier Triggern steht die Schuld
exakt auf vier Intervallen, und ein Vergleich genau auf diesen Wert
entschiede über Mikrosekunden Uhrdrift, ob der fünfte noch durchrutscht.

**Der Zonenwechsel teilt sich dasselbe Budget.** Er war bis dahin
ungedeckelt; seit beide Trigger dieselbe Schuldenrechnung füttern, wäre
eine Ausnahme für ihn ein Loch in genau der Grenze, die sie zieht — wer
zwischen Hideout und Map hin- und herportet, löste sonst beliebig viele
Abrufe aus. Die gemeinsamen Abbruchgründe (Pause-Modus, laufendes "Load
All Tabs", kein Login, `pacing_blocked()`) stehen dafür jetzt in
`_event_refresh_blocked()` statt zweimal ausgeschrieben.

**Nachtrag aus der Messstunde: Wo der Zonenwechsel als Auslöser komplett
ausfällt.** Peter, 2026-08-10: "Wenn ich aus der Mine zurück zum Händler
dort porte, wird die Itemliste nicht aktualisiert, d. h. ich kann dort
identifizieren und handeln, ohne dass unser Tool das mitbekommt. Erst
wenn ich diesen Händler-Bereich wieder verlasse und in die Mine gehe,
wird das Tool aktualisiert." Gegen seine Client.txt geprüft und
bestätigt: Zwischen 21:21:41 und 21:49:26 steht dort **27 Minuten lang
keine einzige `You have entered`-Zeile**, obwohl in dieser Zeit acht
Händler-Ereignisse anfielen (zweimal identifizieren + verkaufen, dann
noch einmal dasselbe). Die Fahrt zum Händler im Delve erzeugt keinen
Zonenwechsel — für den Zonen-Auslöser ist dieser Bereich unsichtbar.

Wichtig für die Einordnung des Triggers oben: Die App hat in diesen 27
Minuten trotzdem rund hundertmal gefragt (der Charakter wird im
Single-Modus alle ~16 s abgerufen, die Mitschrift aus §4.35 belegt es
lückenlos) und dabei **ein einziges Mal** neue Daten bekommen. Das
Problem ist also nicht, dass zu selten gefragt würde, sondern dass GGG
dort nichts veröffentlicht. Der Händler-Trigger kann das nicht heilen —
er hilft dort, wo GGG tatsächlich veröffentlicht und nur der Auslöser
fehlte (in einer normalen Stadt lagen zwischen "Trade accepted" und der
neuen Antwort gemessene 9 bis 30 Sekunden), und in den Modi, die
seltener als das fragen (Auto: 40 s).

**Eine feste Verzögerung wäre trotzdem falsch.** Der erste Blick auf die
Daten legte sie nahe (9–57 Sekunden zwischen "Trade accepted" und den
neuen Daten, also feuert ein Trigger nach 1–3 Sekunden zu früh). Eine
Stunde später widersprach Peter: "Jetzt gerade habe ich Items
identifiziert, nachdem ich aus der Mine gekommen bin, und konnte sie
sofort im Tool sehen." Nachgesehen — und beides stimmt, die Spanne ist
nur viel größer als gedacht:

| Ereignis | Neue Daten sichtbar | Abstand |
|---|---|---|
| 22:21:35 `Trade accepted` | 22:25:18 | 3 min 43 s |
| 22:26:04 `11 Items identified` | 22:26:07 | 3 s |

Bei einer Streuung von drei Sekunden bis knapp vier Minuten trifft keine
feste Wartezeit. Der Trigger bleibt deshalb bei "sofort": billig,
gelegentlich genau richtig, und die Fälle, die er verpasst, holt der
reguläre Takt ohnehin ein. (Peters Beobachtung kam übrigens NICHT vom
neuen Trigger — sein laufendes Programm stammt von vor diesem Commit, im
Log steht keine einzige `Inventar-Ereignis erkannt`-Zeile. Was er sah,
war der gewöhnliche 16-Sekunden-Takt.)

**In Peters Spielrunde bestätigt (2026-08-10, 22:30–23:24).** Zwölf
erkannte Ereignisse, davon **zwei Volltreffer**: Bei `12 Items
identified` (22:54:30) und `4 Items identified` (23:00:04) lagen die
neuen Daten **0,4 Sekunden später** vor. Beide fielen in genau die
Lücke, die Peter beschrieben hatte — die App hatte davor 35 bzw. 9 Mal
vergeblich gefragt, und ein Zonenwechsel war nicht in Sicht (das Log
vermerkt "kein Zonenwechsel bekannt"). Ohne den Trigger hätte er auf den
nächsten Zonenwechsel warten müssen, im ersten Fall neun Minuten lang.

Daraus schien ein Unterschied zwischen den beiden Zeilenarten zu folgen —
"Identifizieren veröffentlicht sofort, ein Verkauf nicht". **Diese
Aussage hat der größere Datensatz nicht gehalten**, siehe den nächsten
Absatz. Kein einziges `Trade accepted` lieferte unmittelbar Daten
(gemessen 17 s, 32 s oder erst mit dem nächsten Zonenwechsel); dieser
Teil steht weiterhin.

**Nachgemessen an 30 Ereignissen — der Trigger ist nicht nachweisbar
wirksam.** Peter, 2026-08-12: "Mir ist gerade aufgefallen, dass ich beim
Händler meine Gegenstände identifiziert habe, diese aber in der Itemliste
noch als unidentifiziert angezeigt werden. Evtl. triggert hier nur das
Zurückkehren in die Basis, und was wir bisher gesehen haben, war Zufall
bzw. ein günstiger Zeitpunkt." Über beide Spielabende ausgewertet:

| | |
|---|---|
| Identifizier-Ereignisse | 30 |
| davon lösten sofort einen Abruf aus | 30 (0,4 s später) |
| davon lieferten binnen 6 s neue Daten | 7 |
| davon **ohne** Zonenwechsel in den 30 s davor | **2** |

Fünf der sieben Treffer lagen 2–4 Sekunden nach einem Zonenwechsel ins
Hideout — dort ist der Zonen-Auslöser die mindestens ebenso gute
Erklärung, die beiden Ursachen sind in diesen Fällen nicht trennbar. Die
zwei sauberen Treffer sind genau die beiden aus dem Absatz oben; sie
liegen sechs Minuten auseinander am selben Abend. 2 von 30 ist keine
Wirkung, sondern liegt in dem Bereich, den GGGs ohnehin auftretende
Spätveröffentlichungen erzeugen (§4.19: 5 % der Änderungen kommen später
als zehn Minuten, 20 % nach zwei bis zehn). Gegenprobe, damit die
Fehlschläge überhaupt etwas beweisen: Alle 30 Ereignisse haben
tatsächlich einen Abruf ausgelöst, keines wurde vom Burst-Budget
geschluckt.

**Der Trigger bleibt trotzdem drin, und zwar aus einem anderen Grund als
bisher angenommen: Er ist gratis.** Durch die Schuldenrechnung (Punkt 1
oben) verschiebt ein vorgezogener Abruf den nächsten regulären um genau
dieselbe Zeit — die Anzahl der Requests bleibt gleich, nur ihre Lage
ändert sich. Einen Abruf auf einen Moment zu legen, in dem sich im Spiel
etwas getan hat, ist nie schlechter als ihn auf die Uhr zu legen, selbst
wenn er meistens ins Leere greift. Was NICHT bleiben darf, ist die
Behauptung, er wirke: Sie stand hier und in `poe-verhalten.md`, beruhte
auf zwei Fällen und hat Peter zu Recht stutzig gemacht.

Getestet: `tests/test_zone_watcher.py` (beide Schreibweisen des
Identifizierens, abgebrochener Handel löst nichts aus, getrennte
Signale), `tests/test_main_window_helpers.py` (Trigger löst Refresh aus,
Pause blockiert, vorgezogener Abruf verschiebt statt zurückzusetzen,
regulärer Takt zählt weiterhin ab jetzt, Peters Zahlenbeispiel mit vier
durchgelassenen und dem fünften geblockten Trigger, Erholung des Budgets,
Zonenwechsel im selben Budget, volle Kette über den Watcher).

---

### 4.37 Die Freezes beim Aktualisieren der Fächer: der Cache-Schreiber

Peter, 2026-08-12: "Gibt es eine Möglichkeit, die kurzzeitigen Freezes
beim Updaten der Fächer zu umgehen? Evtl. in den Hintergrund auslagern."

**Erst gemessen, dann gebaut.** Der Verdacht fiel sofort auf
`_persist_cache()` — es lief bei JEDEM eintreffenden Fach
(`_on_stash_items`) und schrieb dabei den KOMPLETTEN Bestand neu, nicht
etwa nur das geänderte Fach. An Peters echtem Cache (58.432 Stash-Items,
76 MB) nachgemessen:

| Teil eines Speichervorgangs | Dauer |
|---|---|
| Charaktere, Stash-Bäume, Charakter-Items umwandeln | 0,009 s |
| äußere Dicts flach kopieren | < 0,001 s |
| **58.432 Stash-Items umwandeln (`model_dump`)** | **0,981 s** |
| JSON erzeugen | 0,40 s |
| Datei schreiben | 0,08 s |
| **gesamt** | **≈ 1,4 s** |

1,4 Sekunden Stillstand pro Fach. Bei "Load All Tabs" über ein paar
hundert Abschnitte summiert sich das zu Minuten.

**Die Trennlinie folgt der Messung.** `data_cache.Snapshot` teilt den
Vorgang genau dort, wo die Tabelle es nahelegt: Alles unter 0,01 s
passiert weiterhin sofort im GUI-Thread, der Rest wandert in
`services/cache_writer.py`. Gemessen bleiben davon **0,009 s** im
GUI-Thread übrig statt 1,4 s.

**Warum das ohne tiefe Kopie sicher ist.** Ein Hintergrund-Thread, der
Daten serialisiert, die der GUI-Thread weiter verändert, ist ein
klassischer Fehler. Hier trägt es, weil die Item-Listen im Betrieb immer
als GANZES ersetzt werden (`self._items[league][stash_id] = items`) und
nie an Ort und Stelle wachsen — über alle Schreibstellen in
`main_window.py` geprüft, inklusive der `extend`-Aufrufe (die bauen
Aggregat-Listen auf, sie verändern keine zwischengespeicherten). Eine
flache Kopie der äußeren Dicts genügt damit. Die Stash-BÄUME dagegen
werden sehr wohl in place verändert (`_stamp_category` schreibt in
`tab.metadata`), deshalb werden genau sie sofort umgewandelt — sie kosten
mit 0,004 s ohnehin nichts. Ein Test hält das fest: Nach dem Snapshot
werden Item-Liste, Liga und Kontoname geändert, und in der Datei steht
trotzdem der Stand von vorher.

**Zusammenfassen statt takten.** Der Schreiber hält genau einen
wartenden Snapshot; trifft ein neuer ein, während noch geschrieben wird,
ersetzt er den wartenden. Damit fällt eine Serie von Anforderungen von
selbst auf "die gerade laufende plus die neueste" zusammen — ohne
Verzögerungs-Timer, für den man eine Wartezeit erfinden müsste, die
niemand begründen kann. Gegengemessen: 50 Anforderungen in Folge kosten
den GUI-Thread 3,6 s statt 73 s.

**Was die GIL davon übrig lässt.** Das Umwandeln ist reines Python und
gibt die GIL nur alle paar Millisekunden ab. Der GUI-Thread kommt
dadurch regelmäßig zum Zug, statt 1,4 s am Stück zu stehen — aus einem
harten Einfrieren wird eine kurze zähere Phase. Die verbleibenden 3,6 s
oben sind genau diese Konkurrenz. Ganz weg wäre sie nur mit einem
eigenen Prozess, durch den dieselben 76 MB müssten; das kostete mehr als
es spart.

**Beim Beenden wird gewartet.** Der Thread ist ein Daemon und stürbe mit
dem Prozess. `closeEvent` ruft deshalb `flush()`, bevor die Konto-Sperre
fällt, und protokolliert eine Zeitüberschreitung, statt sie zu
verschweigen — sonst hieße "geschlossen" stillschweigend "letzte
Änderung verloren".

**Der Überschreibschutz bleibt unverändert.** `_persisted_scale` wird
weiterhin sofort gesetzt, nicht erst nach dem tatsächlichen Schreiben —
genau wie in der synchronen Fassung, die den Wert auch dann setzte, wenn
das Schreiben scheiterte. Er beschreibt den zuletzt BEABSICHTIGTEN
Umfang; hinge er am Erfolg, hielte er nach dem ersten asynchronen
Speichervorgang jeden weiteren für einen Rückgang.

Ein Fehler im Hintergrund-Thread wird gefangen und protokolliert, statt
den Thread mitzunehmen: Ohne ihn würde ab da still nichts mehr
gespeichert, während die Anwendung weiterläuft. Dieser Fall kam nicht
aus dem Kopf, sondern aus dem ersten Testlauf — er hat den Thread
tatsächlich gekillt.

Getestet: `tests/test_cache_writer.py` (Snapshot schreibt dieselbe Datei
wie der synchrone Weg, Entkopplung von späteren Änderungen, `request()`
blockiert nicht, Zusammenfassen auf den neuesten Stand, `flush()` meldet
eine Zeitüberschreitung statt Erfolg, ein Fehler tötet den Schreiber
nicht und steht im Log), `tests/test_main_window_helpers.py` (Anforderung
statt Schreibvorgang beobachtet, Konto-Trennung, Überschreibschutz).

---

### 4.38 Item-Textexport für Path of Building

Peters Betatester, 2026-08-12: "Kann man eigentlich von da in den Path of
Building rein copypasten?" Rechtsklick auf ein Item bietet seither
"📋 Copy item text (for Path of Building)" an — PoEs eigenes
Item-Textformat in der Zwischenablage.

**Der Nutzen liegt bei TRUHEN-Items.** Charaktere holt sich PoB selbst
von GGGs Seite; an die Truhe kommt es nicht heran. "Wäre dieser Ring ein
Upgrade?" ist genau die Lücke, und PoE-VIEW2 hat die Ringe schon
geladen.

**Warum das trägt, obwohl derselbe Export 2026-07-31 wieder ausgebaut
wurde** (FALLSTRICKE #50): Damals war das Ziel Craft of Exile, und CoE
verlangt das **Strg+ALT+C**-Format ("Advanced mod descriptions") mit
Mod-Tags, Tier und Wertspanne je Zeile. Diese Daten liefert GGGs API
nachweislich nie — gegen einen echten 47-MB-Stash-Cache geprüft, kein
Item trägt je ein "extended"-Feld —, weshalb der Import dort IMMER
scheiterte und das Feature zu Recht verschwand. PoBs eigener Hilfetext
nennt dagegen **Strg+C**, das schlichte Item-Textformat. Dessen
Bestandteile haben wir vollständig. Der Unterschied steckt in einer
einzigen Taste, und er entscheidet zwischen "geht gar nicht" und "geht".

Gegengeprüft wurde außerdem PoBs Parser selbst (`Classes/Item.lua`,
`Item:ParseRaw`, quelloffen) statt sich auf das Format zu verlassen, wie
man es in Erinnerung hat: `Rarity:` schaltet den Parser in den
Spiel-Modus, `--------` trennt die Abschnitte, `Item Class:` wird
**gelesen und verworfen** (die Klasse leitet PoB aus dem Basistyp ab).

**Aufbau** (`external_tools.item_export_text`), Abschnitte durch
`--------` getrennt, in der Reihenfolge des Spiels: Klasse und Rarität,
Name, Eigenschaften, Anforderungen, Sockel, Item-Level, implizite Mods,
explizite Mods, Zustandszeilen. Drei Stellen, an denen es nicht beim
Abschreiben der Felder bleibt:

- **Die Waffenklasse fällt aus den Eigenschaften heraus.** GGG führt sie
  als wertlose erste Property (`{"name": "Sceptre", "values": []}`) —
  das ist der einzige Ort, an dem die API sie überhaupt nennt, weshalb
  `item_category` sie von dort liest. Im Spieltext steht sie
  ausschließlich in der Kopfzeile; bliebe sie stehen, bekäme PoBs Parser
  ein nacktes "Sceptre" als Mod-Zeile vorgesetzt. `WEAPON_CLASSES` ist
  deshalb jetzt öffentlich: dieselbe Liste, einmal zum Lesen, einmal zum
  Überspringen.
- **`_ITEM_CLASS_NAMES` ist eine feste Tabelle, keine
  Pluralisierungsregel.** "One Handed Sword" heißt als Klasse "One Hand
  Swords", "Staff" wird zu "Staves", "Helmet" zu "Helmets" — drei
  Muster in drei Zeilen, das lässt sich nicht ableiten. Dieselbe
  Erkenntnis hatte schon der verworfene erste Anlauf. Was fehlt, bleibt
  WEG statt geraten: Flaschen bekommen gar keine Klassenzeile, weil PoE
  dort vier Klassen unterscheidet (Life/Mana/Hybrid/Utility) und unsere
  Kategorie nur "Flask" kennt. Da PoB die Zeile ohnehin überliest,
  kostet das nichts.
- **" (augmented)" hinter aufgewerteten Werten** — der zweite Eintrag je
  Wert ist GGGs Formathinweis. Dass die 1 genau "aufgewertet" bedeutet,
  ist an echten Daten abgelesen und nicht angenommen: An einem Sceptre
  trugen Qualität und per Affix erhöhter Schaden die 1, die unveränderte
  kritische Trefferchance die 0.

**Nachtrag aus der ersten Probe in echtem PoB (2026-08-12) — es fehlten
Mod-Listen.** Der Import lief auf Anhieb, und der Vergleich zwischen
unserem Text und PoBs Innenansicht deckte einen Fehler auf, den kein
Test gefunden hätte: Exportiert wurden nur `explicitMods` und
`implicitMods`. GGG führt aber mehr Listen, und im echten Bestand sind
sie alles andere als selten — gezählt über 59.005 Items:
`enchantMods` 2274 (Labyrinth-Weihe, Cluster-Jewel-Notables),
`utilityMods` 2083 (der Effekt jeder Utility-Flasche), `logbookMods` 46,
`scourgeMods` 11, `crucibleMods` 8, `veiledMods` 6, `ultimatumMods` 5.
Ein verzauberter Helm und jede Utility-Flasche verloren beim Export also
genau das, was sie ausmacht.

Sie kommen über `extra="allow"` roh mit, brauchen deshalb eigenes
Entfernen des Färbungs-Markups (`_raw_mod_lines`) — die aufbereiteten
Eigenschaften `explicit_mods`/`implicit_mods` gibt es nur für die zwei
deklarierten Felder. Die Verzauberung bekommt einen eigenen Abschnitt
VOR den impliziten Mods (so zeigt es das Spiel, und PoB zählt sie zu den
Implicits); alle übrigen hängen an den expliziten, statt jeweils einen
eigenen Abschnitt zu erfinden — wo genau das Spiel eine Utility-Flasche
oder einen Logbuch-Mod abtrennt, ist nicht nachgeprüft, und eine
geratene Abschnittsgrenze wäre schlechter als eine Zeile im
benachbarten Block. Verlorengehen darf keine.

Leere Abschnitte fallen weg, sonst stünden zwei Trenner hintereinander
und PoB bekäme eine leere Mod-Zeile. Der Menüeintrag steht FEST im
Kontextmenü und nicht in der konfigurierbaren Tool-Liste: Deren leere
Vorbelegung begründet sich damit, niemanden ungefragt zu kontaktieren
(§4.15) — ein Zwischenablage-Export kontaktiert niemanden.

**Was ein Test hier nicht leisten kann:** ob PoB den Text am Ende
akzeptiert. Das entscheidet nur ein echtes Einfügen; der Parser-Blick
oben senkt das Risiko, ersetzt die Probe aber nicht — und genau die
Probe hat dann auch die fehlenden Mod-Listen zutage gefördert, nicht
einer der Tests.

**Gegen das Original geprüft (2026-08-12).** Peter hat dasselbe Item im
Spiel mit Strg+C kopiert und beide Texte nebeneinandergelegt. Sie
stimmen in JEDEM Kopf-Abschnitt überein: Klasse, Rarität, beide
Namenszeilen, Eigenschaften samt `(augmented)`, Anforderungen, Sockel,
Item-Level. Auch die Anforderungen, die durch die gesockelten Gems
hochgezogen sind (§4.33), stehen im Original genauso drin — die
Entscheidung, sie unverändert zu übernehmen, war also richtig.

Der einzige Unterschied liegt bei den Mods: In Peters Client ist
**"Advanced mod descriptions"** eingeschaltet, sein Text trägt deshalb
Affix-Namen, Tier und Wertspanne je Zeile (`35(33-38)% increased Armour
and Energy Shield`). Das ist dieselbe Zusatzinformation, an der Craft of
Exile gescheitert ist — sie kommt aus dem Client, nicht aus der API, und
kein noch so sorgfältiger Nachbau kann sie herbeischaffen. Für PoB
genügt der Wälzwert.

Nebenbei geklärt: Ein erster Versuch zeigte in PoB zwei
Eldritch-Implicits, die weder in unserem Text noch in GGGs Daten für
dieses Item stehen (`implicitMods: []`, während drei andere Handschuhe
desselben Kontos ihre Eldritch-Implicits sehr wohl dort tragen). Ein
zweiter Versuch in einem frisch angelegten Charakter zeigte sie nicht —
PoB hatte sie aus dem vorher geladenen Item behalten. Das Original aus
dem Spiel hat ebenfalls keinen Implicit-Abschnitt.

Getestet: `tests/test_external_tools.py` (Format im Ganzen, Waffenklasse
wird nicht zur Mod-Zeile, aufgewertete Werte, keine leeren Abschnitte,
eine Namenszeile bei Magic statt zweier, Zustandszeilen zuletzt, keine
geratene Klasse bei Flaschen), `tests/test_main_window_helpers.py`
(Menüeintrag schreibt in die Zwischenablage, die vorhandenen
Tool-Menü-Tests zählen ihn nicht mit).

---

### 4.39 Item-Detail nach Blöcken, Leveling-Panel daneben

Peter, 2026-08-12: "Wir sollten unsere Item-Darstellung etwas
überarbeiten... Zumindest etwas übersichtlicher, den grafischen
Schnickschnack brauchen wir vorerst nicht."

**Was daran wirklich fehlte, war nicht Schönheit.** Das Panel warf alles
in eine flache Liste: Rarität, Anforderungen, Eigenschaften, impliziter
und explizite Mods untereinander ohne jede Trennung. Damit war **nicht
zu erkennen, welcher Mod der implizite ist** — im Spiel trennt ihn eine
Linie ab, hier stand er einfach als erste Zeile zwischen den anderen.

Umgesetzt mit derselben Gliederung wie im Spiel, aber ohne dessen
Rahmen und Schriftbild: dünne `<hr>`-Linien zwischen den Blöcken
(Peters Wahl unter drei vorgelegten Entwürfen), sonst nichts.
`_item_blocks()` liefert die Blöcke als reine Daten ohne Qt und ist
dadurch ohne Fenster prüfbar; `_blocks_to_html()` setzt sie zusammen.

**Zwei inhaltliche Mängel kamen beim Umbau mit ans Licht:**

- *Stilles Abschneiden.* Die alte Grenze von zwölf Zeilen schnitt ohne
  Hinweis ab, und Peters "Pain Crusher" lag mit exakt zwölf Zeilen auf
  der Kante — ein Mod mehr wäre wortlos verschwunden. Die Grenze bleibt,
  sagt jetzt aber Bescheid und verweist auf die vergrößerte Ansicht.
- *Fehlende Mod-Listen.* Dieselbe Lücke wie im Item-Textexport (§4.38):
  angezeigt wurden nur `explicitMods` und `implicitMods`. Ein
  verzauberter Helm und jede Utility-Flasche zeigten damit gerade das
  nicht, was sie ausmacht. Die Feldliste steht seither EINMAL in
  `models` (`ENCHANT_MOD_FIELD`, `EXTRA_MOD_FIELDS`,
  `all_extra_mod_lines`) statt zweimal in der Oberfläche — genau eine
  der beiden Stellen zu vergessen war der Fehler, und beide taten es
  zunächst.

**Der Splitter unten.** Peter, direkt nach dem Umbau: "Kannst du das
Item-Feld unten in der Breite begrenzen durch splitten? Sonst ziehen
sich die horizontalen Linien über die ganze Breite. Ich hätte den
rechten (freien) Bereich hier gerne für unsere Leveling-Infos
(XP/h-Graph) benutzt." Ein waagerechter `QSplitter` trägt jetzt links
`ItemDetail` und rechts `LevelingPanel`, verschiebbar, Startverhältnis
3:1.

**Beide Maße sind gemessen, nicht gegriffen** (Peter, 2026-08-13: "Die
Trennlinienposition können wir ja anhand der Zeilenbreite berechnen.
Können wir den XP-Bereich unten ausrichten/fixieren? Dann wackelt das
beim Item-Wechsel nicht so rum"). Vorher standen dort 900/300 Pixel aus
der Luft.

*Breite* (`ItemDetail.preferred_width`): Über alle 201.426 Mod-Zeilen in
Peters Bestand liegt der Median bei 34 Zeichen, 90 % passen in 58,
**95 % in 68**. Auf 68 Zeichen ist das Panel ausgelegt; der Rest bricht
um, abgeschnitten wird nichts. Die längste gefundene Zeile hat 381
Zeichen (eine Jewel-Beschreibung) — dafür gibt es keine sinnvolle
Panelbreite. Beim Vergrößern des Fensters wächst das Leveling-Feld, das
Item-Detail behält seine Breite: Ein Text, der breiter wird, gewinnt
nichts, die Fläche für den späteren Graphen schon.

*Höhe*: fest, sonst sprang das Panel bei jedem Klick — ein Ring mit zwei
Mods gegen ein Unique mit acht — und mit ihm das Leveling-Feld daneben
und der untere Rand der Tabelle darüber. Da die Höhe dauerhaft reserviert
ist, kostet jede Zeile doppelt, also auch hier gezählt.

**Korrigiert am 2026-08-13, weil die erste Messung die falsche Einheit
zählte.** Sie ergab "14 Zeilen decken 96,5 %" und daraus 300 px. Gezählt
waren aber nur TEXTZEILEN; die Trennlinien zwischen den Blöcken kosten
ebenfalls Platz, und zwar gemessene 16 px — **eine volle Zeilenhöhe je
Linie**, nicht den Bruchteil, der pauschal eingeplant war. Real deckte
das 300-px-Panel damit 91,8 % ab, nicht 96,5 %. Aufgefallen ist es Peter
an einer Karte, deren letzte Mod-Zeile auf dem Rahmenrand stand.

Neu gemessen über 59.043 Items, in der Einheit, auf die es ankommt
(Textzeilen + Trennlinien):

| Einheiten | Panelhöhe | abgedeckt |
|---|---|---|
| 14 | 268 px | 84,1 % |
| 16 | 300 px | 91,8 % ← bisher |
| **17** | **316 px** | **95,5 % ← jetzt** |
| 18 | 332 px | 97,6 % |
| 20 | 364 px | 99,3 % |

`_MAX_UNITS` steht auf 17. Das kostet die Tabelle 16 Pixel und holt die
Abdeckung auf den Stand, der die ganze Zeit behauptet war; die nächsten
zwei Prozent kosten nochmal so viel. Das längste Item braucht 29
Einheiten — dafür Platz vorzuhalten wäre absurd.

**Die Kürzung zählt jetzt dieselbe Einheit.** Sie zählte vorher ebenfalls
nur Textzeilen und meldete deshalb bei einem block-reichen Item gar
nichts, obwohl es überlief — genau das stille Abschneiden, das dieser
Umbau abschaffen sollte, nur durch eine andere Tür. Ein Item mit vielen
kleinen Blöcken zeigt seither weniger Text als eines mit einem großen,
was der Wirklichkeit entspricht. Und der Hinweis selbst wird aus dem
Budget bezahlt: Wird gekürzt, sinkt das Budget vorab um eine Zeile —
sonst schöbe ausgerechnet die Meldung über das Abschneiden das Panel über
seine feste Höhe.

`LevelingPanel` (`ui/leveling_panel.py`) zeigt Stufe, Gesamterfahrung
und die Rate aus §4.34 — dieselben Zahlen wie die Statuszeile, nur
größer und dauerhaft. Der Graph darunter kam einen Tag später dazu
(§4.40); beim Umbau des Detail-Panels blieb die Fläche bewusst leer,
weil er einen Zeitreihen-Speicher braucht und damit ein eigenes
Vorhaben ist.

Fehlt die Rate noch, steht dort *warum* ("Rate follows after the next
zone change") statt eines leeren Feldes — GGG veröffentlicht Erfahrung
erst beim Verlassen einer Zone (§1 in `poe-verhalten.md`), und ein
leeres Feld sähe nach einem Fehler aus. Beim Wechsel auf ein Truhenfach
wird das Panel geleert: Die Anzeige gehört zu EINEM Charakter, eine
stehengebliebene Rate neben einem Fach behauptete einen Zusammenhang,
den es nicht gibt.

Getestet: `tests/test_item_detail.py` (impliziter Mod als eigener Block,
Blockfolge im Ganzen, Verzauberung und Flaschen-Effekt überhaupt
sichtbar, Kürzung sagt es und schweigt sonst, HTML-Maskierung der
Mod-Texte, Höhe bleibt über drei sehr verschiedene Items gleich, Panel
nie kleiner als sein Icon, Breite fasst eine typische Mod-Zeile),
`tests/test_leveling_panel.py` (Anzeige der Werte, Begründung statt
leerem Feld, Leeren beim Fach-Wechsel).

---

### 4.40 Der XP/h-Verlauf: ein Balken je Abschnitt (`ui/xp_graph.py`)

Zwei Sachen an einem Tag, beide von Peter angestoßen (2026-08-13) und
beide am selben Punkt: Die Rate maß nur von Veröffentlichung zu
Veröffentlichung und warf alles davor weg.

**Erstens: die erste Map einer Sitzung lieferte keine Rate.** Peter:
"Ich habe eine Anfangs-XP im Tool gehabt und bin vom Hideout in eine
Map gegangen. Nach der Map (ca. 10 Minuten) zurück ins Hideout und da
habe ich eine End-XP bekommen, aber noch keine Rate, was theoretisch
jetzt möglich wäre."

Er hatte recht, und der Grund ist eine Kette, die sich erst im
Zusammenhang zeigt: Der Weg INS Hideout ändert die Erfahrung nicht (dort
wird nichts verdient), also erzeugt er auch keine beobachtete Änderung.
Nach der Map gab es damit genau EINE, und `_xp_per_hour` verlangte zwei.
Der Nenner — die zehn Minuten in der Map — lag längst gemessen vor
(§4.34), es fehlte nur der Vorgänger im Zähler.

Der stand die ganze Zeit daneben: `_XpWatch.since_experience`, der
Sitzungs-Startwert. Warum er trotzdem nicht allgemein taugt, ist seit
dem 2026-08-10 als Test festgehalten — was in der ersten Änderung
steckt, wurde teils schon VOR dem Programmstart verdient, und gegen die
Zeit seit dem Start gerechnet ergäbe das eine erfundene Rate. Genau so
kam am 2026-08-11 die 1,53-Mrd.-Anzeige zustande.

`_baseline_starts_the_interval()` grenzt deshalb eng ein. Der Startwert
zählt nur, wenn **alle drei** Bedingungen halten:

1. Der Nenner kommt aus der Verweildauer in der verlassenen Zone, nicht
   aus dem vollen Intervall. Ohne eingeschaltete Zonen-Beobachtung
   bleibt es beim alten, vorsichtigen Verhalten.
2. Die Zone wurde erst betreten, nachdem die Sitzung ihren Startwert
   gelesen hatte. Alles seither Dazugekommene gehört damit in diese
   Zone — die Zone davor hätte beim Verlassen eine eigene
   Veröffentlichung ausgelöst, und die wäre eine beobachtete Änderung
   gewesen.
3. Dazu ein Sicherheitsabstand in Höhe des Auslöse-Fensters (10 s):
   Fällt der Programmstart in die ein bis drei Sekunden zwischen einem
   Zonenwechsel und seiner Veröffentlichung, ist der Startwert noch der
   Stand VOR der letzten Zone.

**Zweitens: der Graph.** Peter beantwortete damit auch die Frage, die
seit dem Vortag offen war ("Was kommt auf die x-Achse?"): "Wir zeichnen
einen Graph über die letzten 3 Stunden, das sollte eigentlich reichen.
Die meisten Gamer schließen eine Map innerhalb von 5 Minuten ab. Die
berechnete XP/h des letzten Abschnitts schreiben wir einfach in den
Graph."

Das löst den Einwand auf, an dem die Idee hing. Eine Kurve über
Momentanwerte gibt es gar nicht zu zeichnen — GGG veröffentlicht die
Erfahrung nur beim Zonenwechsel, rund achtmal pro Stunde. Was es gibt,
ist pro Abschnitt eine fertig gemessene Rate, und die hat neben ihrem
Wert auch eine **Dauer**. Also Balken statt Linie, gezeichnet über die
tatsächlich gemessene Zeitspanne:

- Die Breite zeigt, wie lange der Abschnitt gedauert hat. Eine
  Zehn-Minuten-Map und ein Zwei-Minuten-Trial sehen verschieden aus,
  obwohl beide einen Wert liefern.
- **Die Lücken sind echt.** Wo nichts gezeichnet ist, wurde keine
  Erfahrung gemacht — Pause, Stadt, Truhe sortieren. Eine durchgezogene
  Linie müsste dort etwas behaupten.
- Ein Abschnitt mit Verlust (Tod ab Akt 5) hängt rot unter der
  Null-Linie, statt herausgefiltert zu werden — dieselbe Entscheidung
  wie bei `_format_xp_rate`, das das Vorzeichen ebenfalls stehen lässt.

Der Speicher dafür ist `_XpWatch.history`, session-lokal wie alles
andere dort: ein aus der Datei geladener Verlauf zeigte nach einer Nacht
Pause Balken, die mit dem heutigen Abend nichts zu tun haben. Er bleibt
klein — bei acht Veröffentlichungen pro Stunde sind drei Stunden zwei
Dutzend Einträge, und was aus dem Fenster fällt, wird beim Anfügen
verworfen. Die **Anzeige** benutzt ihn ausdrücklich nicht: Sie bleibt
bei der zuletzt gemessenen Rate, weil ein Mittelwert über drei Stunden
etwas anderes beantwortet als "wie schnell komme ich gerade voran".

`MainWindow._watch_rate()` ist seither die einzige Stelle, an der aus
einem Beobachtungsstand eine Rate wird — Anzeige und Graph teilen sie
sich, damit die Kurve nicht etwas anderes behaupten kann als die Zahl
darüber. Die y-Achse skaliert auf die höchste sichtbare Rate; eine feste
Obergrenze gäbe es nicht sinnvoll, weil die Größenordnung zwischen einem
Charakter in Akt 2 und einem in den Maps um Zehnerpotenzen auseinander
liegt. Das Zeitfenster wandert bei jedem Refresh weiter, ein eigener
Timer wäre Aufwand für nichts: Solange ein Charakter offen ist, läuft
ohnehin alle paar Sekunden ein Abruf.

**Eine Map mit Unterbrechung (2026-08-13, am selben Abend).** Peter war
in einer Map, ging kurz Items verkaufen und danach zurück, um sie fertig
zu clearen. Aus dem Log: 6:02 in der Map (+14.643.224 → 145,6 Mio./h),
56 s im Hideout, 1:52 in der Map (+686.080 → 22,1 Mio./h). Beide Werte
sind richtig, aber die Kennzahl nannte danach 22,1 — die Rate des
Aufräumens, nicht die der Map.

Zusammenfassen liegt nahe und war ausdrücklich NICHT gewollt. Peter:
"Zusammenfassen will ich die beiden Balken nicht, weil hier sieht man
wirklich schön wann man raus und wieder rein ist und was das gekostet
hat." Stattdessen eine **dunkelgrüne Fläche hinter den Balken**, über
beide Aufenthalte hinweg, auf Höhe der gemeinsamen Rate (116,4 Mio./h) —
die Lücke bleibt dabei sichtbar und zeigt genau, was der Ausflug gekostet
hat. Dazu eine **gestrichelte Linie** auf der Gesamtrate über alles
Sichtbare; sie steht ruhig, während die Abschnitte springen. Über
*alles* Sichtbare rechnete sie bis zum 2026-08-23 — seither über einen
begrenzten Zeitraum, siehe §4.40.1.

Die gemeinsame Rate ist Erfahrung durch GESPIELTE Zeit, nicht das Mittel
der beiden Raten: (145,6 + 22,1) / 2 wären 83,9 Mio./h, richtig sind
116,4 — der erste Abschnitt war dreimal so lang.

**Dass sich das überhaupt gruppieren lässt, hing an einem Fund in der
Client.txt.** Am Zonennamen ist "zurück in dieselbe Map" nicht von
"nächste Map gleichen Namens" zu unterscheiden, beide schreiben `You have
entered Bramble Valley`. Ein paar Zeilen davor steht aber
`Client-Safe Instance ID = 2308728564`, und die war bei Peters beiden
Betreten IDENTISCH (die des Hideouts dazwischen nicht). `ZoneWatcher`
liest sie seither mit (`last_instance_id`), `_XpWatch.interval_instance`
trägt sie bis in den `XpPoint`.

Die Kennung gehört dabei der Zone, die VERLASSEN wurde — dieselbe
Verschiebung wie beim Zeitstempel, und die Stelle, an der man sich
vertut. Es ist eine DEBUG-Zeile: Fehlt sie, bleibt die Kennung leer und
nichts wird gruppiert. Lieber nicht gruppieren als falsch gruppieren.

#### 4.40.1 Der Zeitraum, für den der Schnitt gilt (2026-08-23)

Peter, mit einem Bild seines Leveling-Feldes: "Wenn ich mir den
XP-Bereich anschaue, sollten wir die durchschnittlich 2M XP/h unbedingt
ändern. Wir müssen auf alle Fälle irgendwie kenntlich machen, für
welchen Bereich die gelten."

Auf dem Bild standen zwei Balken ganz rechts, zusammen keine zehn
Minuten — und quer über die volle Breite die gestrichelte Linie mit
"⌀ 2M". **Die Zahl war richtig, die Aussage über ihren Geltungsbereich
falsch.** Der Schnitt rechnete über alles Sichtbare, die Achse darunter
sagte "3 h ago → now", und beides zusammen behauptete drei Stunden, die
nie gemessen wurden. Ein Fehler ohne Rechenfehler: Jeder Wert stimmte,
die Zeichnung log.

**Der Zeitraum** (`average_window`) beginnt seither beim JÜNGSTEN dieser
drei Ereignisse — Peters Vorgabe, "der Zeitpunkt seit dem letzten Level
zusammen mit der aktuellen Sessionlänge (hier aber maximal 3 h)":

1. drei Stunden zurück, die Breite des Graphen,
2. der letzte Levelaufstieg,
3. das Ende der letzten Pause von mehr als 30 Minuten.

Die **30 Minuten** sind nicht gegriffen: GGG veröffentlicht die
Erfahrung im laufenden Betrieb mit Abständen von anderthalb bis
siebzehn Minuten (gemessen, §4.35). Jede Schwelle in dieser
Größenordnung würde mitten im Spielen trennen — derselbe Grund, aus dem
`_XpWatch` für die Rate ganz ohne Pausenerkennung auskommt. Dreißig
Minuten lassen fast das Doppelte Luft und erkennen trotzdem jede Pause,
die den Namen verdient.

**Der Abschnitt MIT dem Levelaufstieg zählt noch dazu.** Der Aufstieg
fällt mitten in eine Zone, die Veröffentlichung danach trägt schon die
neue Stufe. Ihn auszuschließen hieße, direkt nach einem Aufstieg gar
keinen Schnitt zu haben; ihn mitzunehmen kostet den Teil der Zone vor
dem Aufstieg. Die kleinere Ungenauigkeit gewinnt.

**Gezeichnet** wird der Zeitraum, statt ihn zu behaupten (Peters
Vorgabe): Über seiner Strecke ist die Linie dick (3 px) und
durchgezogen, davor bleibt sie dünn und gestrichelt — dort GILT der
Schnitt nicht, dort ist er nur noch Vergleichsmaß für die älteren
Balken. Dazu steht die Länge der Strecke neben der Zahl
("⌀ 2M · 34 min"), weil die x-Achse nur ihre beiden Enden beschriftet
und man die Länge sonst schätzen müsste.

**Wo die Beschriftung steht, ist eine eigene Entscheidung** (Peter,
2026-08-24, mit einem Bild: "ich kann die XP/h hier nicht lesen"). Sie
stand über der Linie — bei einem Schnitt dicht unter der Spitze landete
sie dadurch oberhalb des Widgets und obendrein in der Spitzen-
Beschriftung. `label_top()` weicht seither unter die Linie aus, hält aber
die erste Zeile frei (dort steht die Spitze) und bleibt im Bild. Als
reine Funktion neben dem Widget, weil sich eine Platzierung sonst nur
mit dem Auge prüfen lässt.

Das Dunkelgrün ist gemessen, nicht gewählt (CIEDE2000 gegen alles,
worauf die Linie zu liegen kommt): Hintergrund ΔE 32,5, Map-Fläche 11,9,
Balken 21,4. Ein Schritt dunkler (Mischfaktor 0,45 statt 0,35)
verschwände auf der Map-Fläche — ΔE 6,0.

**Was dafür an Daten dazukam:** `XpPoint.level`, die Stufe zum Zeitpunkt
der Veröffentlichung. Ohne sie ließe sich der letzte Aufstieg im Verlauf
nicht finden. Stufe 0 heißt "unbekannt" und trennt nie — lieber gar
nicht trennen als an einer erfundenen Stelle. Der gespeicherte Verlauf
(§4.44) steht deshalb auf `VERSION = 2`; ein Stand ohne Stufe wird
verworfen statt über einen Aufstieg hinweggerechnet.

Die Geometrie steht als reine Funktion (`graph_layout`) neben dem
Widget. Fehler in einer Zeichenroutine findet man sonst nur mit dem
Auge, und das skaliert schlecht auf Fälle wie "Abschnitt von zwei
Sekunden" (Mindestbreite, sonst unsichtbar — und ausgerechnet die
kurzen Abschnitte tragen die höchsten Raten).

Getestet: `tests/test_xp_graph.py` (rechter Rand ist das Jetzt, Breite
folgt der Dauer, Lücken bleiben Lücken, Ausscheiden nach drei Stunden,
Verlust unter der Null-Linie, Mindestmaße, leere Achse,
Achsenbeschriftung gröber als die Zahl daneben; für §4.40.1: der
Aufstieg und die Pause beenden den Zeitraum, siebzehn Minuten Lücke
dagegen nicht, unbekannte Stufen trennen nie, die Strecke beginnt am
Anfang ihres ersten Abschnitts und läuft nicht aus dem Bild),
`tests/test_main_window_helpers.py` (Peters Ablauf Hideout → Map →
Hideout liefert jetzt eine Rate; die drei Gegenproben zu den
Bedingungen oben; Verlauf wächst je Abschnitt, vergisst nach drei
Stunden und kommt im Widget an).

---

### 4.41 Verbindungs-LED in der Statuszeile

Peter, 2026-08-13, unmittelbar nach der Wartungs-Auswertung (§4.12):
"Wir könnten während der Wartungsdauer eine LED rot leuchten lassen und
wenn die Wartung vorbei ist, diese wieder auf grün setzen."

Ein farbiger Punkt links vom Offline-Banner, in derselben Ampel wie das
Rate-Limit-Dashboard. **Kein neuer Zustand und keine neue Erkennung** —
die LED hängt an `offline_changed`, das es seit §4.12 gibt und das genau
an den beiden gewünschten Flanken feuert.

**Warum drei Zustände und nicht zwei.** Das Offline-Banner kann nur
"kaputt" sagen: Im Normalfall ist es leer, und leer heißt sowohl "alles
in Ordnung" als auch "noch nichts versucht". Genau diese Lücke soll die
LED schließen, also darf sie sie nicht selbst wieder aufreißen.

| Farbe | Bedeutung | Ausgelöst von |
|---|---|---|
| Grau | Noch kein Abruf — nicht angemeldet, oder nichts gelaufen | Start, `_on_login_required` |
| Grün | Letzter Abruf erfolgreich | `_on_logged_in`, `offline_changed(False)` |
| Rot | GGG nicht erreichbar (Wartung/kein Netz) | `offline_changed(True)` |

Zwei Anschlüsse daran sind nicht offensichtlich:

- **Der Login färbt grün.** Ohne ihn bliebe die LED eine ganze
  störungsfreie Sitzung lang grau: `offline_changed` meldet nur
  ZUSTANDSWECHSEL, und wer nie offline war, bekommt nie ein Signal. Der
  Login ist selbst ein geglückter Abruf (`/profile`) und damit der
  Beleg, der für Grün fehlt.
- **Ein abgelaufenes Token färbt GRAU, nicht rot.** Ohne Token fragen wir
  gar nicht erst (§`_skip_unauthenticated`). Über GGGs Erreichbarkeit
  sagt das nichts — Rot hieße "GGG ist weg", obwohl der Server
  einwandfrei laufen kann. Der Logout läuft über denselben Weg
  (`LogoutJob` → `login_required`) und braucht deshalb keinen eigenen
  Anschluss.

Farben in `theme.py` (`LED_UNKNOWN`/`LED_ONLINE`/`LED_OFFLINE`), Zustände
als Tabelle `MainWindow._LED_STATES` mit Farbe UND Tooltip nebeneinander:
Die LED allein sagt "rot", der Tooltip sagt, was das für die angezeigten
Daten bedeutet. Dieselbe Legende steht im Hilfe-Fenster unter "Getting
started", gebaut aus denselben Konstanten.

Getestet: `tests/test_main_window_helpers.py` (Startfarbe grau, beide
Flanken der Wartung, Login färbt ohne Störung grün, Token-Ablauf grau
statt rot).

---

### 4.42 Gem-Fortschritt über dem XP-Graphen (`ui/gem_progress.py`)

Peter, 2026-08-13: "Oberhalb des XP-Graphen machen wir einen Bereich in
dem die XP als vertikale Linie je Gem zur nächsten Stufe prozentual
angegeben sind und einen dunklen Bereich mit hellem Bereich füllen ...
Dadurch sollte man gut erkennen können ob ein Gem fertig auf Stufe 20
gelevelt ist."

Ein schmaler Balken je Sockel-Gem (5 px breit, 60 hoch), in der Farbe des
Attributs, das es verlangt; der helle Teil ist der Fortschritt zur
nächsten Stufe, der dunkle der Rest. Reihenfolge wie in der Paperdoll,
Tooltip je Balken mit Name, Stufe und Prozentwert.

**Die schwierigste Frage daran beantwortet GGG selbst.** "Ist das Gem
fertig?" wäre aus Stufe und Gem-Art herzuleiten — ein Awakened-Gem ist
bei 5 fertig, ein normales bei 20, ein korrumpiertes kann bei 21 stehen.
Nichts davon ist nötig: Über Peters 449 Sockel-Gems (16 Charaktere)
steht die Stufe im Klartext als `"20 (Max)"`, `"5 (Max)"`, `"21 (Max)"`,
und genau diesen 226 Gems fehlt zugleich das `Experience`-Feld. Zwei
unabhängige Merkmale, beide ohne Rechnerei.

Daraus drei Zustände, jeder an echten Daten abgezählt:

| Zustand | Merkmal | Anzahl | Darstellung |
|---|---|---|---|
| Fertig | "(Max)" in der Stufe, kein Erfahrungsfeld | 226 | voller Balken in der gesättigten Gem-Farbe |
| **Wartet auf einen Klick** | Balken voll, aber nicht Max | **65** | Füllung + gelbe Kappe |
| Am Leveln | Fortschritt < 1 | 157 | Füllung + gelbe Erfahrungslinie |

**Der mittlere Zustand ist nicht kosmetisch.** Gems steigen in PoE nicht
von selbst auf (`poe-verhalten.md` §4); ein voller Balken unterhalb der
Höchststufe ist Charakterstärke, die auf einen Mausklick wartet — 65
Stück allein in Peters Bestand. Ohne eigene Markierung sähe das aus wie
"fertig", und genau das ist die Frage, die der Streifen beantworten soll.
Die Kappe trägt die Warnfarbe des Rate-Limit-Dashboards, mit derselben
Bedeutung: hier passiert nichts von allein.

Fehlen BEIDE Merkmale (weder "(Max)" noch Erfahrung), bleibt der Balken
leer statt voll: Ein voller Balken hieße "fertig", und das wäre eine
Behauptung ohne Grundlage. In Peters Bestand tritt der Fall seit dem
Jewel-Filter (s. u.) nicht mehr auf — der frühere Einzelfall WAR das
Jewel —, aber GGG darf jederzeit ein Gem ohne diese Felder liefern.

#### Die Höhe ist die Stufe, nicht der Fortschritt

Peter, 2026-08-16: "Die aktuelle Stufe des Gems ist wichtiger als die
aktuelle Erfahrung." Die erste Fassung füllte den Balken mit dem
Fortschritt zur nächsten Stufe. Damit standen bis zu 33 Balken auf
zufälligen Prozentwerten und sahen alle gleich wichtig aus — man konnte
dem Streifen ansehen, wie weit einzelne Gems im Moment sind, aber nicht,
wie weit der Charakter ist. Mit der Stufe als Höhe wird er zu einem
Profil: Welches Gem hängt zurück, sieht man ohne einen einzigen Tooltip.

Drei Dinge stehen jetzt gleichzeitig im Balken:

| Element | Bedeutung | Warum so |
|---|---|---|
| Füllhöhe, Gem-Farbe | Stufe / 20 | die Hauptaussage, deshalb die Fläche |
| 1 px Linie, `GEM_XP_LINE` (#ffff00) | Fortschritt zur nächsten Stufe | nachgeordnet, deshalb eine Linie |
| Voller Balken, gesättigte Farbe (`GEM_COLORS_DONE`) | fertig | keine Kontur, sondern Farbe (s. u.) |
| Gelbe Kappe, `DASH_WARN` | wartet auf einen Klick | unverändert |

**Die Erfahrungslinie läuft über die ganze Balkenhöhe, nicht innerhalb
der Stufe.** Innerhalb wäre ihr Spielraum eine Zwanzigstel-Höhe, bei
60 px also 3 px — eine Linie, die sich nicht bewegt, ist Zierde. Über
die volle Höhe gelesen sagt sie dasselbe (Fortschritt in Prozent) und
ist ablesbar. Bei 0 % und 100 % hält ein Anschlag sie im Balken, statt
sie unten heraus- oder oben wegfallen zu lassen.

**Stufe/20 gilt stur, auch für Gems mit kleinerer Höchststufe.** Über
Peters 6248 Gems gezählt gibt es solche zuhauf (Portal, Quickstep,
Convocation, Detonate Mines = 1; Empower/Enhance/Enlighten = 3; Brand
Recall = 6), und ihre Höchststufe steht in keinem API-Feld — sie wäre
nur über eine gepflegte Namensliste zu erraten, die mit jeder Liga
veralten würde. Nötig ist das nicht: Sobald so ein Gem fertig ist, trägt
es "(Max)" und wird voll gezeichnet. Nur ein *unfertiges* Enlighten
steht zu tief im Balken — und das ist der Zustand, in dem "hier fehlt
noch etwas" ohnehin stimmt.

**Fertige Gems sind ein voller Balken in der gesättigten Gem-Farbe**
(Peter: "Fertig gelevelte Gems werden einfach als intensiver 5px Balken
dargestellt, z.B. 0xff0000"). Vier Farben, nicht eine: Ein einheitliches
Rot für alles Fertige würde bei 226 von 449 Gems die Attribut-Zuordnung
wegwerfen, also bei der Hälfte des Streifens. Zu Grau gibt es keine
gesättigte Fassung, dort ist Weiß die Entsprechung (Peter: "bei weißen
Gems benutzen wir Grau ↔ Weiß"). Die gelben Gems, die es seit kurzem
gibt, fallen über denselben Weg wie jedes unbekannte Farbkürzel dorthin,
ohne dass wir das Kürzel kennen müssten — in Peters Bestand kommt keines
vor (S 179, I 170, D 120, G 4).

Gemessen, weil eine Farbentscheidung ohne Zahl geraten ist: fertig gegen
levelnd liegt bei ΔE2000 = 16,6 (rot) bis 31,4 (blau), in derselben
Größenordnung wie der hell/dunkel-Unterschied im Balken selbst (21–30),
der nachweislich lesbar ist. Die vier fertigen Farben liegen 33–87
auseinander, die Attributfarbe bleibt also erkennbar. **Für Flächen ist
ΔE2000 das richtige Maß, nicht WCAG-Kontrast**: Der misst Helligkeit und
gilt für Text auf Grund; nach ihm hätten reines Rot und das gedämpfte
Rot nur 1,06:1, obwohl sie sofort zu unterscheiden sind.

#### Warum es kein gelber Rahmen wurde

Der erste Anlauf am selben Tag war genau das: ein gelber Rahmen um
fertige Gems. Er war gebaut, gemessen und gemeldet — und Peter konnte
ihn auf seinem Schirm nicht finden. Der Grund: Ein fertiges Gem hat
einen VOLLEN Balken, der Rahmen lag also auf der hellen Gem-Farbe, mit
1,13:1 gegen Grün und 1,01:1 gegen Grau. Physisch vorhanden, optisch
nicht existent. Mein erster Reparaturversuch — die Füllung um einen
Pixel einrücken — war sogar pixelgleich wirkungslos, weil der Rahmen
zuletzt gezeichnet wird und die Füllung darunter ohnehin überdeckt
(nachgemessen: 0 von 300 Pixeln verschieden). Was dann half, war ein
dunkler Nachbar: die Gem-Farbe nur noch als 1 px Kern, links und rechts
Hintergrund, dann der Rahmen.

Das funktionierte, aber der Preis war die Gem-Farbe selbst — von 5 px
Balken blieb 1 px Farbe übrig. Peters Neuentwurf löst dasselbe Problem
ohne diesen Preis, und daraus die Regel: **Auf 5 px Breite trägt eine
Farbfläche, keine Kontur.** Der Rahmen samt `_MAXED_CORE_W` ist wieder
entfernt.

**Der leere Teil eines Balkens war ebenfalls unsichtbar**, aus demselben
Grund und im selben Bildschirmfoto: 1,02–1,21:1 gegen den Hintergrund.
Balken mit wenig Füllung sahen dadurch aus wie Lücken im Streifen, und
"hier steckt kein Gem" ließ sich nicht von "Gem auf Stufe 3"
unterscheiden. `_EMPTY_DIM` von 0,68 auf 0,45 gesenkt: jetzt 1,44–2,29:1.

Beides zusammen ist eine Lehre über das Vorgehen: **Farben gehören
gemessen, nicht begutachtet** — und zwar gegen den Hintergrund, auf dem
sie wirklich liegen. Der Offscreen-Betrieb der Tests hat eine HELLE
Palette (das dunkle Aussehen kommt von Windows, nicht von einer eigenen
Palette), deshalb setzen die Tests die Fensterfarbe selbst auf ein
Dunkelgrau, bevor sie Pixel vergleichen.

**Nicht jedes ``socketedItems`` ist ein Gem.** Peter, 2026-08-16: "Belt
gibts glaube ich nicht für Gems, nur für Jewels." Er hat damit einen
Fehler aufgedeckt: Ein Abyss-Jewel sitzt in derselben Liste wie die
Gems, levelt aber nicht — und bekam einen eigenen, ewig leeren Balken.
Genau dieses eine Jewel war jener vermeintliche Sonderfall "ein Gem,
dessen Stufe die API nicht mitliefert", der hier und im Modul-Docstring
als bekannte Ausnahme vermerkt stand. Seit der Filter auf ``frameType
== 4`` steht, bleibt in seinem Bestand kein Balken ohne Beleg
(448 Gems: 227 fertig, 65 wartend, 156 am Leveln).

Nebenwirkung des Filters, die zweimal zugeschlagen hat: Testhilfen und
die Demo-Daten für die README-Bilder bauten Gems **ohne**
``frameType``. Beide mussten nachziehen — wer Daten nachbaut, muss
nachbauen, was der Code prüft.

**Gem-Farben sind hier richtig**, anders als bei der Zeilen-Markierung
(§4.33): Dort ging es um EIN Item, in dem mehrere verschiedenfarbige Gems
gleichzeitig aufsteigen können, weshalb Grün gewählt wurde. Hier hat
jedes Gem seinen eigenen Balken.

Getestet: `tests/test_gem_progress.py` (alle drei Zustände, Awakened und
korrumpierte Höchststufen, fehlende Belege, Farbzuordnung samt "G" und
leer, Reihenfolge, Ausblenden ohne Gems, Zeichnen aller Zustände). Die
Darstellung wird an Pixelspalten des ECHTEN Widgets geprüft, auf einer
selbst gesetzten dunklen Palette: Höhe folgt der Stufe und nicht dem
Fortschritt (Stufe 10 bei 90 % Fortschritt füllt halb), Deckel bei
Stufe 21, Erfahrungslinie über die ganze Höhe (25 % und 75 % liegen
30 px auseinander) und an beiden Enden im Balken, fertiges Gem
einfarbig satt und ohne Linie, fertig gegen Stufe 20 unterscheidbar,
Kappe erhalten. Jede dieser Aussagen ist gegengeprüft — die Änderung
zurückgenommen, der Test muss fallen; sieben von sieben tun es.

### 4.43 PoE2-Rohdaten-Abzug (`services/poe2_probe.py`)

Peter, 2026-08-15: "Evtl. könnten wir einen Button PoE2-Info einbauen,
der einfach mal die Rohdaten in einem extra Fenster zurückgibt, was wir
bekommen. Evtl. können wir dann anhand dieser Informationen weiter
sehen."

Ein Eintrag im Konto-Menü fragt die PoE2-Endpunkte ab und zeigt das
Ergebnis als Text. Kein Betriebsmittel: nichts davon geht in Tabelle,
Cache oder Preisrechnung, und das Programm liest weiterhin PoE1.

**Was GGGs Referenz sagt.** Die Spiele werden über einen
`realm`-Query-Parameter unterschieden, nicht über eigene Pfade und nicht
über einen eigenen OAuth-Scope — das bestehende Token deckt die Abfrage
also mit ab. Gelesen am 2026-08-15:

| Endpunkt | erlaubte `realm`-Werte |
|---|---|
| `/account/leagues` | `pc`, `xbox`, `sony`, `poe2` |
| `/character`, `/character/<name>` | `xbox`, `sony`, `poe2` |
| `/stash/...` | nur `xbox`, `sony` |

Dazu GGGs eigener Hinweis auf derselben Seite: "There are currently
limited APIs that return PoE2 game information."

**Was gemessen dabei herauskommt: nichts.** Der erste Abzug lief am
2026-08-15 gegen Peters Konto, und Peter sah sofort, was mir entgangen
war — "das sind anscheinend alles Daten von PoE1". Die Nachmessung
bestätigt es und geht weiter: Vier Varianten desselben Aufrufs (ohne
Realm, `poe2`, `xbox`, ein frei erfundener Wert) liefern **bytegleiche
Antworten** — dieselbe Prüfsumme, 50 PoE1-Charaktere, Feld `realm`
überall `pc`. Auf dem Liga-Endpunkt dasselbe Bild.

Der erfundene Realm ist der entscheidende Abruf. Käme dort ein Fehler,
wäre `poe2` ein anerkannter Wert ohne Daten. Da auch er dieselben Bytes
liefert, wertet GGG den Parameter schlicht nicht aus. Die Frage "hat
dieses Konto PoE2-Charaktere?" ist über diesen Endpunkt gar nicht
stellbar.

**Die fehlende Truhen-Zeile bleibt trotzdem die wichtigste.** Selbst
wenn der Parameter wirkte: Ohne Truhen-Endpunkt gibt es für PoE2 keine
Fächer, keine liga-weite Suche und keine Gesamtsumme — also genau die
Funktion, für die es dieses Programm gibt. Ein PoE2-Modus wäre eine
halbe Anwendung. Deshalb der Abzug statt eines Features.

**Kontrollabrufe sind der Inhalt, nicht die Zugabe.** Die erste Fassung
fragte nur nach `poe2` und zeigte dann PoE1-Daten unter einer
PoE2-Überschrift — ein Abzug, der die eigene Frage nicht beantworten
kann und den Leser aktiv in die Irre führt. Jetzt läuft derselbe Aufruf
dreimal (ohne Realm, mit `poe2`, mit dem erfundenen Wert), und der
Vergleich der Prüfsummen steht als Urteil in Klartext über den
Rohdaten. Das Charakter-Detail wird nur geholt, wenn der Realm die
Antwort tatsächlich verändert hat; sonst wäre es ein PoE1-Charakter im
PoE2-Abzug. Bytegleiche Antworten werden nur einmal ausgeschrieben —
dreimal dieselbe 50-Charakter-Liste verdeckt das Wenige, worauf es
ankommt.

**Rohabrufe neben den typisierten Endpunkten** (`get_leagues_raw`,
`get_characters_raw`, `get_character_raw`). Die pydantic-Modelle sind an
PoE1 gemessen; ob PoE2 dieselben Felder liefert, ist gerade die offene
Frage. Ein `model_validate` dazwischen ließe unbekannte Felder zwar dank
`extra="allow"` durch, brächte aber bei einem fehlenden Pflichtfeld den
Abruf zum Absturz — und verschluckte damit das Messergebnis.

**Fehlschläge sind Ergebnisse, keine Abbrüche.** Jeder Abruf wird
einzeln aufgefangen und mit seinem Fehlertext in den Abzug geschrieben;
ein 403 auf die Charakterliste ist hier die Antwort auf die Frage. Nur
`AuthError` fliegt weiter, damit ein wirklich totes Token wie überall
sonst den Login anstößt. Aus demselben Grund trägt die Fehlermeldung
seit diesem Feature die Query mit (`_target`): ohne sie stünde dort nur
`/character`, und ein PoE2-Fehlschlag wäre von einem gewöhnlichen
PoE1-Fehler nicht zu unterscheiden.

**Nur der erste gefundene Charakter** wird im Detail geholt. Die Frage
ist strukturell — wo PoE2 seine Skill-Gems ablegt, wie `runeMods`
aussieht, welche Felder es überhaupt gibt —, und die beantwortet ein
Charakter genauso wie zehn. Jeder weitere kostete nur
Rate-Limit-Kontingent.

**Anzeige im vorhandenen `RawDataViewer`**, um eine eigene Instanz
erweitert. Ein zweites Monospace-Textfenster daneben wäre dieselbe
Anzeige mit anderem Namen; eine gemeinsame Instanz ginge nicht, weil der
Stash-Betrachter bei jedem Tab-Wechsel überschrieben wird und den Abzug
beim ersten Klick im Baum mitnähme. Der Abzug landet zusätzlich als
`poe2-probe.txt` im Profilordner: Ein vollständiges Charakter-JSON ist
zu lang für einen Bildschirmfoto-Ausschnitt, weitergeben lässt sich nur
die Datei. Der Pfad wird bei jedem Aufruf neu aus `config.APP_DATA_DIR`
gebildet und ist deshalb vom Testschutz erreichbar (dieselbe Falle wie
bei `cache_backup` und `LOG_DIR`).

Der Text nennt die Konto- und Charakternamen, die er enthält, und die
nicht abgefragten Truhen-Endpunkte samt Grund — sonst liest sich ein
Abzug ohne Fächer wie ein Fehler des Programms statt wie eine Grenze der
API.

Getestet: `tests/test_poe2_probe.py` (Prüfsumme unabhängig von der
Schlüsselreihenfolge, Wirkungserkennung samt Fehlschlägen, Urteilstext
in allen drei Ausgängen, Namensauslese nur aus der PoE2-Antwort,
Deduplizierung gleicher Antworten, Spaltenausrichtung, Ablagepfad gegen
den Testschutz, Abrufreihenfolge mit Kontrollen, Detail nur bei
Wirkung, `AuthError` weitergereicht, Token- und Read-only-Sperre), dazu
`tests/test_client.py` (Realm als Query, Encoding, Query in der
Fehlermeldung, 429-Retry behält sie) und
`tests/test_main_window_helpers.py` (Menüeintrag, Fenster beim Klick,
Read-only-Absage, Anzeige und Ablage, eigenes Fenster).

### 4.44 XP-Verlauf über den Programmstart hinweg (`services/xp_history.py`)

Peter, 2026-08-15: "Mit jeder neuen Version die ich teste beginnen die
XP-Daten wieder von vorne. Könnten wir uns das nicht merken?"

**Der Verlauf wird aufgehoben, die Basis ausdrücklich nicht.** Das ist
die ganze Entscheidung. Die Punkte im Graphen sind abgeschlossene
Messungen — Zeitpunkt, Dauer, Rate —, sie wieder anzuzeigen erfindet
nichts. Der Beobachtungsstand des `_XpWatch` (seit wann, mit welchem
Erfahrungswert) bleibt dagegen sitzungslokal, aus dem Grund, der dort
schon vor diesem Feature im Docstring stand: Ein Levelaufstieg während
einer Pause vor dem Sitzungsstart käme sonst als absurd hohe Rate
heraus. Vergangenheit lässt sich speichern, eine Behauptung über die
Gegenwart nicht.

Für Peter heißt das: Der Graph ist nach dem Start sofort wieder gefüllt,
aber die erste neue Rate kommt weiterhin erst mit der zweiten
beobachteten Veröffentlichung (oder mit der ersten, wenn
`_baseline_starts_the_interval` greift). Die Lücke zwischen altem und
neuem Balken ist die Programmpause und wird als solche gezeichnet — wie
jede andere Pause im Graphen auch (§4.40).

**Die Zeitstempel müssen umgerechnet werden.** Die Punkte laufen intern
auf `time.monotonic()`, einer Uhr ohne festen Nullpunkt: Nach einem
Neustart bedeutet derselbe Zahlenwert einen völlig anderen Augenblick.
Gespeichert wird deshalb Wanduhrzeit, geladen wird zurückgerechnet.
Beide Richtungen bekommen `now_mono` und `now_wall` als Parameter statt
selbst auf die Uhr zu sehen — nur so ist die Umrechnung ohne laufende
Zeit prüfbar, und genau sie ist die Stelle, an der ein Fehler nicht
auffiele: Ein falscher Nullpunkt setzt Balken an die falsche Stelle,
ohne dass irgendetwas abstürzt.

Beim Laden fällt weg, was älter ist als das Graph-Fenster (drei
Stunden), und ebenso alles, was in der Zukunft liegt — gestellte Uhr,
Sommerzeit, eine von einem anderen Rechner kopierte Datei. Sechzig
Sekunden Toleranz, damit die beiden Uhrabfragen sich nicht in die Quere
kommen.

**Je Konto eine Datei** (`xp-history-<Konto>.json`), wie beim
Daten-Cache und aus demselben Grund. Geschrieben wird nach jedem neuen
Abschnitt statt beim Beenden: Ein Absturz ist genau der Fall, nach dem
man den Verlauf vermisst. Das kostet nichts — bei rund acht
Veröffentlichungen pro Stunde (§4.35) sind drei Stunden zwei Dutzend
Zeilen, ein Bruchteil dessen, wofür sich beim Daten-Cache der
`cache_writer` lohnt. Ein Schreibfehler wird protokolliert und sonst
ignoriert; der Verlauf ist Komfort und darf die laufende Messung nicht
stören. Ein unlesbarer oder versionsfremder Stand ist kein Fehlerfall,
sondern einfach kein Verlauf.

Das Modul kennt `XpPoint` nicht, sondern nur ein Protokoll mit seinen
Feldern — die Dienstschicht soll die Oberfläche nicht importieren, und
zu speichern sind ohnehin nur Zahlen.

**`VERSION = 2` seit dem 2026-08-23**: Jede Zeile trägt seither die
Stufe mit, ohne die der Schnitt im Graphen nicht beim letzten
Levelaufstieg enden kann (§4.40.1). Ein Stand ohne sie wird verworfen —
er würde den Zeitraum über einen Aufstieg hinwegziehen, und der Verlauf
ist Komfort, kein Datenbestand, für den sich eine Migration lohnte.

Getestet: `tests/test_xp_history.py` (Alter übersteht den Neustart,
Programmpause zählt mit, Kürzen auf das Fenster, Punkte aus der Zukunft,
Uhr-Toleranz, Sortierung, Konto-Trennung, Versionswechsel, kaputte
Nutzlast und kaputte Einzelzeilen, Datei fehlt/unlesbar) und
`tests/test_main_window_helpers.py` (Verlauf übersteht einen echten
zweiten `MainWindow`, Basis wird nicht wiederhergestellt, ohne
Kontonamen keine Datei, zwei Konten getrennt, Schreibfehler stört die
Messung nicht).

### 4.45 Beobachtete Stapelgrößen (`ui/favourites.py`)

Peter, 2026-08-15: "Oft gibt es Items, deren Stapelgröße ich gerne
beobachten würde, z.B. Lifeforce. ... So weiß ich auf einen Blick,
wieviel ich von z.B. 'Wild Crystallised Lifeforce' besitze."

Eine schmale zweispaltige Tabelle rechts neben dem Textblock des
Leveling-Felds: Name links, Menge rechts. Gezählt wird über alle
geladenen Fächer **und** Charaktere der aktuellen Liga — Währung liegt
oft im Rucksack.

**Die Anordnung entstand in zwei Schritten** (Peter, 2026-08-16). Zuerst
saß die Tabelle unten im Streifen neben den Gem-Balken, dann kam sie
nach oben rechts neben den Textblock — und schließlich: "Können wir den
Platz neben den Gem-Balken nicht auch noch für die Fav-Tabelle nutzen?"
Jetzt stehen Titel, Zahlen und Balken links untereinander, die Tabelle
rechts daneben über die ganze Höhe.

Der Platz reicht auch im Extremfall. **38 Sockel-Gems sind das Maximum,
das ein Charakter tragen kann** — 6 Rüstung + 6 Waffe + 6 Zweitwaffe +
4 Helm + 4 Handschuhe + 4 Stiefel + 3 + 3 Schildhand + je 1 Sockel in
den beiden Ringen. Peter hat die Zahl vorgerechnet und anschließend
meine Herleitung berichtigt: Der Gürtel nimmt keine Gems, nur Jewels,
dafür zählen beide Ringe (§4.42). Die Summe bleibt 38; sein eigener
Höchstwert liegt bei 33 Gems, Median 30 über 16 Charaktere. 38 Balken
sind 264 px, bei 554 px Innenbreite bleiben 284 px für die Tabelle.

Dabei entscheidet ein Detail über die Aufteilung: Die Tabelle **verlangt**
senkrecht nur eine Zeile (`sizeHint`) und **füllt** den Rest über
`Expanding`. Mit dem Vorgabewert einer `QTableWidget` — gemessen 164 px —
hätte sie den Graphen darunter auf 60 px zusammengedrückt. Was nicht in
die Höhe des Textblocks passt, wird gescrollt.

Gemessen an einem 578×325-Panel: Die Tabelle wuchs von 38 über 61 auf
141 px — sieben Zeilen statt zwei (mit den 18-px-Zeilen von unten; mit
den 23 px, die der Header vorher erzwang, waren es nur fünf) —, Graph
und Gem-Balken blieben bei 154 bzw. 60 px.
Der Graph gewinnt also **nichts**, anders als von mir
zunächst vorhergesagt: Die Gem-Balken sind mit 60 px ohnehin höher, als
die Tabelle je war. Gewonnen ist Platz für die Tabelle selbst, aus einer
Fläche, die vorher leer stand.

**Der Textblock braucht dabei eine Mindestbreite**, aus der Schrift
abgeleitet (`QFontMetrics` über "2 000 000 000 XP total") statt in
Pixeln geraten. Ohne sie zog die Tabelle bei WENIGEN Gems so viel Breite
an sich, dass die Zahlenzeile umbrach — und jede zusätzliche Textzeile
ging direkt vom Graphen ab: 126 statt 154 px, ausgerechnet beim
schmaleren Balkenstreifen der kleinere Graph. Der Fließtext ("Rate
follows after the next zone change") darf weiterhin umbrechen.

Zur Messung selbst: Alle Pixelwerte hier stammen aus dem
Offscreen-Betrieb, dessen Ersatzschrift **gut doppelt so breit** ist wie
eine echte Windows-Schrift. Für Verhältnisse und Regressionen taugen
sie, als absolute Vorgabe nicht — deshalb steht in den Tests kein
einziger Pixelwert, sondern nur Vergleiche (gleiche Graph-Höhe bei 12
und 38 Gems).

**Aufgenommen wird per Rechtsklick** in der Item-Tabelle (Peters
Entscheidung gegen eine Eingabeliste im Settings-Dialog). Derselbe
Eintrag entlässt wieder. Beobachtet wird der Anzeigename, nicht das
angeklickte Exemplar. Der Vorteil gegenüber dem Abtippen ist nicht die
Bequemlichkeit, sondern dass ein Tippfehler unmöglich wird: Eine Zeile,
die wegen eines falschen Buchstabens ewig 0 zeigt, sieht aus wie ein
leeres Fach.

**Die Tabelle hängt nicht am gewählten Charakter.** `clear()` im
Leveling-Panel lässt sie ausdrücklich stehen — Stapelgrößen will man
auch beim Stöbern in den Fächern sehen, und das Panel ist ohnehin immer
sichtbar.

**Ein `≥` vor der Zahl, solange nicht jedes Fach der Liga geladen ist.**
Ohne dieses Zeichen sähe eine frisch gestartete Sitzung mit halbem Cache
wie ein Bestandsverlust aus. Ein beobachtetes Item ohne Bestand zeigt
`0` statt zu verschwinden: Null ist eine Aussage.

**Ein Durchlauf für alle Namen.** An Peters echtem Bestand gemessen
(58.621 Items): zwölf Namen einzeln zu zählen kostete 81 ms, in einem
Durchlauf 11 ms — und gezählt wird nach jedem eintreffenden Fach, bei
"Load All Tabs" also über tausendmal hintereinander. Dieselbe Falle wie
beim Modellaufbau der Großsuche: Was einzeln billig aussieht, wird durch
die Wiederholung teuer. Aus demselben Grund liefert
`_items_of_current_league` einen Generator, statt `_league_wide_items`
zu benutzen — Letzteres baut zusätzlich drei parallele Listen mit
Fachname, Position und Fach-ID auf, die hier niemand braucht.

Der Testbeweis dafür zählt **Zugriffe, nicht Millisekunden**: Ein
Item-Doppelgänger merkt sich, wie oft nach seinem Anzeigenamen gefragt
wurde. Eine Zeitmessung wäre auf einem langsameren Rechner unzuverlässig,
die Zahl der Durchläufe ist es nie. Der erste Anlauf prüfte stattdessen,
ob ein Generator durchläuft — das fiel bei einer Sabotage mit
vorgeschaltetem `list(items)` nicht auf und bewies damit nichts über die
Laufzeit.

Höchstens zwölf Beobachtungen (`_MAX_FAVOURITES`); wie viele davon ohne
Scrollen sichtbar sind, ergibt sich aus der Höhe des Textblocks daneben.
Die Zeilen sind mit 18 px flacher als in der Haupttabelle, damit mehr
hineinpassen — **das musste dem senkrechten Header abgerungen werden**.
Er erzwingt eine aus Schrift und Stil berechnete Untergrenze, unter die
`setRowHeight` nicht kommt; auf Peters Windows waren das 23 px, die
Zeilen also ein Fünftel höher als vorgesehen (bei 141 px Panelhöhe sechs
Einträge statt sieben). Dass der Header versteckt ist, ändert daran
nichts. `verticalHeader().setMinimumSectionSize(ROW_HEIGHT)` senkt die
Grenze; nachgemessen liegt danach weder in der obersten noch in der
untersten Bildzeile eines Eintrags ein Schriftpixel — die 8-pt-Schrift
ist 15 px hoch. Warum der naheliegende Test dafür nichts taugt, steht in
FALLSTRICKE #71: Offscreen liegt dieselbe Untergrenze bei 15, dort kommt
die Zeilenhöhe auch ohne den Eingriff durch. Wer mehr will, führt Inventar —
dafür ist die Haupttabelle da. Gespeichert wird als JSON-Liste in `ui-settings.ini`,
bewusst nicht als QSettings-Stringliste: Die zerlegt einen einzelnen
Eintrag beim Zurücklesen je nach Plattform wieder in Zeichen.

Gegen Peters echten Cache geprüft, bevor irgendetwas gebaut wurde: Die
vier Lifeforce-Sorten heißen dort genau so, wie er sie genannt hat
(81.352 Wild, 79.773 Primal, 69.751 Vivid, 2 Sacred). 94 % aller Items
tragen gar kein `stackSize` — die zählen als eines, damit sich auch
Karten und Uniques beobachten lassen.

#### Umsortieren per Ziehen

Peter, 2026-08-16: "Könnten wir die Fav-Item-Liste per Drag&Drop
umsortieren?" Die Konsequenz aus der Entscheidung darüber: Wenn die
Reihenfolge bewusst nicht nach Menge sortiert wird, damit jede Zeile
ihren Platz behält, dann muss der Platz auch wählbar sein — sonst bleibt
nur, die halbe Liste zu entlassen und neu anzulegen.

Qts `InternalMove` wird eingeschaltet, aber nicht benutzt: Bei einer
Tabelle schiebt es ZELLEN und lässt leere Zeilen zurück. `dropEvent`
behandelt das Ereignis deshalb abschließend, rechnet die neue
Reihenfolge selbst aus (`reordered`, eine reine Funktion — die
Off-by-one-Fälle lassen sich so ohne echtes Drag&Drop prüfen) und ruft
`super()` nicht auf. Die Tabelle hängt die Zeilen sofort selbst um und
meldet erst danach: Wer nur meldete, überließe die Anzeige dem Empfänger
des Signals, und bis zur nächsten Zählung sähe das Ziehen aus, als hätte
es nicht funktioniert.

**Der erste Anlauf funktionierte und fühlte sich trotzdem falsch an.**
Peter, direkt nach dem Ausprobieren: "Fühlt sich nicht richtig an, da
stimmt was nicht." Nachgemessen waren es drei Dinge, keines davon in
den bestehenden Tests sichtbar:

1. **Es gab überhaupt keine Rückmeldung, wohin der Eintrag fällt.** Qts
   Einfügestrich entsteht in `QAbstractItemView::dragMoveEvent` — der
   hier überschrieben und nicht aufgerufen wurde. Und selbst mit Aufruf
   käme nichts Brauchbares: Qt meldet an JEDER Position einer 23-px-Zeile
   `OnItem` (an allen y-Werten durchgemessen), zeichnet also einen Rahmen
   um eine Zeile statt einer Linie dazwischen. Die 2-px-Ränder, in denen
   Qt `AboveItem`/`BelowItem` melden würde, sind mit der Maus praktisch
   nicht zu treffen. Der Strich wird deshalb selbst gezeichnet, an
   genau der Stelle, an der auch eingefügt wird.
2. **Nach dem Zug stand die Markierung auf der falschen Zeile.** Die
   Auswahl hängt an der Zeilennummer; die zeigt nach dem Umhängen auf
   einen anderen Eintrag. Man zog etwas nach unten, und oben leuchtete
   ein fremder Name auf. Jetzt wandert die Auswahl mit.
3. **Der Drop meldete `MoveAction`** — und darauf ruft Qts `startDrag`
   `clearOrRemove()` auf und löscht die noch ausgewählten Zeilen aus dem
   Modell. Gedacht ist das für den Fall, dass die Zeilen woanders neu
   entstanden sind; hier haben wir sie selbst umgehängt. Nachgemessen ist
   die Bedingung erfüllt: Nach `move_row` umfasst die Auswahl weiterhin
   eine volle Zeile über beide Spalten. Beobachten ließ sich die Löschung
   nicht — dafür bräuchte es einen echten Drag-Lauf, und `QDrag::exec`
   öffnet unter Windows eine native Schleife, die sich nicht
   nachstellen lässt. `IgnoreAction` nimmt Qt den Anlass; angenommen ist
   das Ereignis trotzdem.

Drei Feinheiten, jede aus einem gemessenen Befund:

- **`setDragDropMode(InternalMove)` genügt.** Es setzt `dragEnabled` und
  `acceptDrops` von sich aus, auf dem Widget wie auf dem Viewport. Die
  drei einzeln nachzuziehen sah gründlich aus, war aber wirkungslos —
  aufgefallen, weil eine Gegenprobe (`setDragEnabled(False)`) den Test
  nicht zum Fallen brachte.
- **`NoSelection` musste weichen.** Qts `startDrag` zieht, was ausgewählt
  IST; mit der bisherigen Einstellung wäre die Auswahl immer leer
  geblieben und kein Zug zustande gekommen. `NoFocus` bleibt: Die
  Auswahl wird dadurch in der gedämpften Inaktiv-Farbe gezeichnet.
- **Gemerkt wird der NAME, nicht die Zeilennummer.** Qts Drag läuft in
  einer eigenen Ereignisschleife, in der die Mengen-Zählung durchkommt
  und `set_rows` aufruft. Nachgemessen überlebt die Zeilennummer das
  zwar (nur bei leerer Liste wird sie -1) — sie zeigt danach aber auf
  einen ANDEREN Eintrag, wenn währenddessen ein Favorit weiter oben
  entlassen wurde. Ist der gezogene Name verschwunden, passiert nichts.

Die neue Reihenfolge wird sofort gespeichert, nicht erst beim Beenden:
Der Zweck der Liste ist, dass sie über Sitzungen gleich bleibt.
Anschließend wird nicht neu gezählt — die Tabelle hat die Zeilen samt
Mengen schon umgehängt, ein zweiter Durchlauf über alle Items der Liga
brächte dieselben Zahlen noch einmal.

Getestet: `tests/test_favourites.py` (Addition, fehlender Bestand,
Items ohne Stapelgröße, Anzeigename statt Basistyp, Reihenfolge,
Zahlenformat samt `≥`, Tooltips, Verschwinden ohne Zeilen, Höhengrenze,
Mindestbreite, ein Durchlauf, Generator als Eingabe; fürs Ziehen:
Rechnung samt Off-by-one und Grenzfällen, Umhängen mitsamt Mengen,
Ablagestelle unter dem Mauszeiger, Ablehnen von außen, Änderung während
des Zugs) und `tests/test_main_window_helpers.py` (Aufnehmen und
Entlassen über das Kontextmenü, Überleben eines Neustarts — auch das
der Reihenfolge —, Summe aus Fächern und Charakteren, `≥` bei halb
geladener Liga, Obergrenze, Item ohne brauchbaren Namen) sowie
`tests/test_leveling_panel.py` für die Anordnung (Tabelle rechts vom
Textblock, füllt dessen Höhe, Gem-Balken bleiben darunter, Graph behält
den Rest).

**Ein Test prüft, dass sich überhaupt etwas anfassen lässt**, mit echten
Mausereignissen über `QTest` und einem `startDrag`, das nur mitschreibt
statt einen modalen Drag-Lauf zu öffnen. Alle anderen Tests hier rufen
`move_row`/`dropEvent` selbst auf und blieben auch dann grün, wenn kein
Mensch eine Zeile greifen kann — genau der Fehler, der am selben Tag
beim Fertig-Rahmen der Gem-Balken passiert ist: gebaut, geprüft,
gemeldet, auf dem Schirm nicht benutzbar.

Der Einfügestrich wird als **Unterschied zweier Aufnahmen** desselben
Widgets geprüft, mit und ohne Strich, nicht an seiner Farbe. Der erste
Anlauf suchte nach der Highlight-Farbe — die trägt aber auch die
ausgewählte Zeile, und im Offscreen-Betrieb (helle Palette) sind beide
identisch: Der Test hielt eine markierte Zeile für einen 19 px hohen
Strich. Aus demselben Grund steht der Strich in den Tests bewusst NICHT
auf der Zeile, die nach dem Zug ausgewählt ist — sonst wäre er im Bild
nicht von der Markierung zu trennen und der Test bewiese nichts.
Aufgefallen ist auch das nur an der Gegenprobe, die den Test nicht zum
Fallen brachte.

### 4.46 Charakterbogen-Export (`ui/character_sheet.py`)

Peter, 2026-08-21: "eine Hommage, mit den ganzen Eigenschaften und Items
und verwendeten Gems und Levels, im Stile der alten Pen&Paper RPGs."
Rechtsklick auf einen Charakter (Kontextmenü der `CharacterList`) →
Speichern-Dialog → Markdown-Datei.

**Keine berechneten Werte.** Peter hatte ursprünglich an das
Spiel-eigene Charakterblatt gedacht — Leben, Mana, Energieschild, die
drei Attribute, DPS-Aufschlüsselung. Nachgemessen am kompletten Cache
eines Charakters (`character_items`, alle Item-Rohdaten): Kein einziges
dieser Felder existiert irgendwo als Schlüssel, weder in der
Charakterliste noch im Item-Endpunkt. Diese Zahlen entstehen im
Spielclient aus dem VOLLEN Passivbaum plus sämtlichen Item-Mods —
dieselbe Rechnung, die Path of Building nachbaut. Sie nachzubilden wäre
ein eigenes Projekt, kein Feature nebenbei. Der Bogen zeigt deshalb
Ausrüstung und Gems; die Hommage an alte Papierbögen kommt über die
**Form** (Gliederung nach Körperslot, leere Plätze bleiben sichtbar),
nicht über erfundene Zahlen.

**Slot-Reihenfolge und -Beschriftung kommen aus der Paperdoll**, nicht
aus einer zweiten Liste: `DOLL_SLOTS`/`SWAP_SLOTS`/`TRINKET_SLOT` standen
bis dahin `paperdoll.py`-intern (`_DOLL_SLOTS` etc.) und wurden dafür
öffentlich gemacht — derselbe Grund, aus dem `EQUIPPED_SLOTS` schon
vorher öffentlich war: eine zweite, eigene Liste liefe bei der nächsten
Slot-Änderung leicht auseinander. Die zehn Kernplätze erscheinen immer,
auch leer (die Silhouette eines Papierbogens bleibt vollständig);
Tausch-Waffenset und Trinket nur, wenn tatsächlich etwas darin steckt —
dieselbe Regel wie in der Paperdoll selbst.

**Gems stehen gruppiert unter dem Ausrüstungsteil, in dem sie sitzen**,
mit einem Attribut-Kürzel ausgeschrieben (`Str`/`Dex`/`Int` statt GGGs
`S`/`D`/`I` — ein Kürzel allein sagt einem Fremden nichts) und demselben
`tooltip`-Text wie der Gem-Balken über dem XP-Graphen (§4.42): "level 4,
57% to next" bzw. "level 1 (Max)". Zwei Darstellungen derselben Zahl
dürfen nicht auseinanderlaufen, deshalb dieselbe Quelle. Nur `gem_progress_of`
selbst entscheidet außerdem, ob überhaupt ein Gem vorliegt — ``item=None``
(kein Slot belegt) braucht keinen eigenen Zweig, weil `getattr(None, …)`
dort ohnehin auf den Vorgabewert fällt.

**Mods** kommen aus denselben Funktionen wie `item_export_text`
(implizit, explizit, alle Zusatzlisten wie Verzauberung/Fraktur) — aber
ohne dessen PoB-Abschnittstrennung, ein Papierbogen muss nicht zwischen
"implizit" und "explizit" unterscheiden. In einer Markdown-Tabellenzelle
gibt es keinen echten Zeilenumbruch; mehrere Mods stehen deshalb durch
`<br>` getrennt (GitHub-Flavored Markdown, funktioniert auch beim
Drucken über den Browser).

**Stufe und Erfahrung kommen aus `_XpWatch`**, nicht aus
`Character.level` — dieselbe Zahl, die das Leveling-Feld zeigt. Ohne
laufende Beobachtung (Charakter nie geöffnet) fällt die Anzeige auf
`character.level` zurück und lässt die Erfahrung ganz weg, statt eine
unbekannte Zahl zu behaupten.

**Der Export ist eine ausdrückliche Handlung wie der CSV-Export**: Ist
der Charakter noch nie geöffnet worden (`_character_items` kennt ihn
nicht), erscheint ein Hinweis statt eines leeren Blatts oder eines
stillen Wartens auf einen Ladevorgang — anders als die Paperdoll, die
bei fehlendem Cache auf das Ergebnis des gerade laufenden Klicks wartet.
Ein Export soll nicht raten, wann "gerade eben geladen" gemeint ist.

Getestet: `tests/test_character_sheet.py` (reine Funktion — Kopf,
Ausrüstungstabelle samt leerer Slots und Tausch-/Trinket-Bedingung,
Flaschen-Reihenfolge, Mod-Zusammenfassung, Gem-Gruppierung samt
Attribut-Tag und Sonderfall "(Max)") und drei Verdrahtungstests in
`tests/test_main_window_helpers.py` (Datei entsteht mit erwartetem
Inhalt, Hinweis statt Dialog ohne geladene Items, Signal der
Charakterliste kommt im Hauptfenster an). Sieben Gegenproben an der
reinen Funktion, drei weitere an der Verdrahtung, alle greifen.

---

### 4.47 Login sichtbar machen (`ui/login_prompts.py`)

Peter, 2026-08-21: "habe gerade schon wieder vergessen mich
einzuloggen". Ein fehlender Login machte sich bis dahin nur zweifach
bemerkbar — die Beschriftung des Toolbar-Knopfes wechselte auf
"🔑 Log in", und in der Statuszeile stand ein Satz, den die nächste
Meldung überschreiben kann. Der eigentliche Grund, warum das so leicht
zu übersehen ist, steckt aber in einer früheren Entscheidung: Weil der
Datei-Cache Baum, Charakterliste und Items auch ohne Login weiter
anzeigt (§4.7, §4.12, FALLSTRICKE #46), **sieht ein nicht angemeldetes
PoE-VIEW2 aus wie ein angemeldetes, das gerade nichts Neues findet.**

Zwei Dialoge, beide nicht-modal (Peters Entscheidung): Ein modaler
Dialog würde ausgerechnet das Durchsuchen der lokalen Daten blockieren,
das ohne Login ausdrücklich weiterlaufen soll.

**Drei Anlässe, ein Signal.** `ApiWorker.login_required` meldete bisher
nur einen Grundtext. Der taugt nicht als Unterscheidungsmerkmal — er ist
für Menschen geschrieben und ändert sich mit jeder Umformulierung —, das
Signal trägt deshalb jetzt zusätzlich einen Anlass aus `LOGIN_NO_TOKEN`
/ `LOGIN_EXPIRED` / `LOGIN_LOGGED_OUT`:

| Anlass | Auslöser | Reaktion |
|---|---|---|
| `LOGIN_NO_TOKEN` | Programmstart ohne gültiges Token (`_bootstrap`) | `WelcomeDialog` |
| `LOGIN_EXPIRED` | HTTP 401 aus einem laufenden Job | `SessionExpiredDialog` |
| `LOGIN_LOGGED_OUT` | Nutzer meldet sich selbst ab | nichts |

Der dritte Fall ist der Grund für die Unterscheidung: Nach einem selbst
ausgelösten Logout wäre ein Fenster "Sie sind nicht mehr angemeldet"
eine Frechheit. Der Aufräumteil in `_on_login_required` läuft in allen
drei Fällen gleich, nur der Hinweis nicht.

**Wann der Willkommensdialog kommt.** Peters Wunsch war "beim ersten
Start zum Konfigurieren und Login, danach nur noch wenn kein Token da
ist". Beides ist dieselbe Bedingung — beim allerersten Start GIBT es nie
ein gültiges Token. Unterschiedlich ist nur der Inhalt: `first_run`
(Merker `welcome/seen` in `ui-settings.ini`) blendet zusätzlich einen
"Getting started"-Abschnitt ein. Der führt bewusst in den echten
Settings-Dialog, statt dessen Bedienelemente hier ein zweites Mal
aufzubauen — eine Kopie des Zone-Refresh-Feldes samt Pfad-Prüfung wäre
beim nächsten Umbau die Stelle, die stehen bleibt.

Das Häkchen "Show this when I am not logged in" (`welcome/on_startup`)
schaltet den Dialog ab, **wirkt aber erst nach dem ersten Start**: Beim
allerersten Mal erscheint er in jedem Fall, sonst gäbe es keine
Gelegenheit, ihn überhaupt zu sehen.

**Der Datenstand im Dialog** (`_cache_summary_text`) beantwortet, ob sich
das Einloggen lohnt. Gezählt werden die Fächer MIT DATEN
(`_last_loaded`), nicht die bekannten: Ein Baum mit 2295 Einträgen, von
denen zwei geladen sind, wäre eine irreführende Zahl.

**Beide Dialoge hängen als Kind am Hauptfenster** (Peter, 2026-08-22:
"Können wir den Login-Dialog auf Top-Layer legen, so dass er sich nicht
vom Hauptfenster verdecken lässt? Nicht modal, aber Top-Layer"). Genau
das ist die ganze Technik dahinter: Ein Kind-Dialog liegt beim
Fenstermanager dauerhaft über seinem Elternfenster. Vorher waren es zwei
gleichrangige Fenster, und ein Klick ins Hauptfenster schob den Dialog
dahinter.

Nativ gegen die WinAPI gemessen (offscreen gibt es keinen
Fenstermanager, die Stapelreihenfolge ist dort nicht prüfbar — dieselbe
Lehre wie FALLSTRICKE #71):

| | `transientParent` | nach `raise_()` aufs Hauptfenster |
|---|---|---|
| mit Elternteil | Hauptfenster | Dialog bleibt oben |
| ohne (bis 2026-08-22) | keiner | Dialog rutscht dahinter |

**Bewusst NICHT `WindowStaysOnTopHint`:** Das hielte den Dialog über
allem, auch über Path of Exile im Fenstermodus und über dem Browser, in
dem man sich gerade anmelden soll. Ein Elternteil reicht genau so weit
wie die Anforderung. Und es macht den Dialog **nicht** modal — das
entscheidet allein `setModal`/`windowModality`. (Eine frühere Fassung
behauptete im Code das Gegenteil und begründete damit, keinen Elternteil
zu setzen; das war schlicht falsch.)

Gemerkt werden sie trotzdem als Attribut — nicht mehr, um sie am Leben
zu halten (das tut jetzt der Elternteil), sondern um sie
wiederzufinden: schließen nach einem geglückten Login, und beim
Ablauf-Popup verhindern, dass sich mehrere stapeln. `closeEvent`
schließt sie ausdrücklich; nötig wäre es mit Elternteil nicht mehr,
aber es macht die Absicht sichtbar. `_close_login_prompts` räumt sie
außerdem nach jedem erfolgreichen Login weg, auch wenn der über den
Toolbar-Knopf lief, während das Popup offenstand. Vom Ablauf-Popup gibt
es nur EIN Exemplar: Nach einem 401 läuft die Reihe bereits eingereihter
Jobs weiter und meldet jeweils denselben Anlass — ohne diese Sperre
stapelten sich die Fenster.

**Zwei Befunde aus dem nativen Probelauf**, die offscreen unsichtbar
geblieben wären (FALLSTRICKE #55, #71, #74):

1. Ohne Mindestbreite schrumpft Qt den Dialog auf die Breite des
   längsten Knopfes — gemessen 262 px, worin die umbrechenden Absätze zu
   sechs- und siebenzeiligen Türmen werden. `_MIN_WIDTH = 430` bringt sie
   auf drei bis vier Zeilen.
2. `color: palette(mid)` für die Detailzeile ergab in Peters dunklem
   Windows-Design **1.13:1** — keine Dämpfung, sondern Unsichtbarkeit.
   Ersetzt durch `muted_colour()`, das die Textfarbe zu 65 % in Richtung
   Hintergrund mischt und dadurch in beiden Systemdesigns über 4.5:1
   bleibt (gemessen: 7.69:1 dunkel).

---

### 4.48 Leere Fächer ausblenden (`StashTree.set_hide_empty`)

Peter: "Neben dem Titel 'Stash' eine Checkbox mit 'Hide empty stashes' —
dient lediglich zur Anzeige, im Hintergrund werden natürlich weiterhin
alle Stashes gescannt, sonst würden wir niemals mitbekommen, das ein
Stash nicht mehr leer ist."

Diese Zusicherung ist keine Absichtserklärung, sondern folgt aus der
Umsetzung: Ausgeblendet wird über `QTreeWidgetItem.setHidden` am
Baumknoten. `MainWindow._leaf_stashes` — die Liste, aus der sich Sweep,
Refresh-Modi und "Load All Tabs" bedienen — sieht davon nichts. Ein
ausgeblendetes Fach wird also weiter abgerufen, und `mark_loaded`
bewertet die Ausblendung danach neu; es taucht von selbst wieder auf.
An Peters echtem Cache gemessen: 71 von 152 Baumknoten verschwinden
(47 %), `_leaf_stashes` bleibt unverändert bei 128.

**Maßstab ist die angezeigte Anzahl**, nicht ein interner Wert:
Ausgeblendet wird genau, was in der Anzahl-Spalte als `0` steht. Eine
LEERE Anzahl-Spalte heißt "unbekannt" (noch nie geladen, ⬇), nicht
"leer" — würden diese Fächer mitverschwinden, käme der Nutzer nie an
eines heran, das er noch gar nicht kennt, und ausgerechnet die sind die
interessanten. Ordner und Sektions-Gruppen verschwinden nur, wenn nichts
mehr darunter sichtbar ist.

Neu bewertet wird an drei Stellen: `set_stashes` (neuer Baum),
`set_children` (Sektionen eines Spezial-Fachs kommen nach) und
`mark_loaded` (erst der Ladevorgang macht aus "unbekannt" eine Null —
und umgekehrt). Der Stand liegt in `ui-settings.ini` unter
`stash_tree/hide_empty`.

---

### 4.49 poe.ninja-Datenstand (`price_cache.fetched_at`)

Peter: "Wir brauchen irgendwo die Info, welcher Datenstand von PoE.Ninja
ist." Der Cache vermerkte `fetched_at` schon immer, gab es aber nicht
heraus.

`fetched_at()` ist bewusst von `load()` getrennt: `load()` liefert bei
einem abgelaufenen Eintrag `None` — für den Aufrufer heißt das "neu
abrufen" —, und genau in dem Moment ist die Frage "wie alt sind die
Preise gerade?" am interessantesten. Die Prüfung auf `CACHE_VERSION`
bleibt trotzdem: Ein Eintrag aus einer anderen Rechenvorschrift
beschreibt keine Preise, die noch angezeigt würden, dann wäre auch sein
Alter irreführend.

Angezeigt neben der Wertsumme in der Statuszeile ("Value: 12 div  ·
poe.ninja 2 h ago"), weil beides dieselbe Frage beantwortet: wie ernst
ist diese Zahl zu nehmen. **Auch ohne Summe**, denn dass Preise
vorliegen, ist eine andere Aussage als dass eine Summe zustande kommt —
sonst verschwände die Altersangabe genau dann, wenn man sich fragt,
warum nichts bepreist ist. Der Tooltip nennt den genauen Zeitpunkt und
die TTL.

An Peters echtem Cache: Allflame 2 h, Hardcore 2 min, SSF Allflame 26 h,
SSF R Allflame 37 min, Standard 2 min — die Spannweite macht sichtbar,
was vorher unsichtbar war.

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
(`MainWindow._default_export_filename(count)`): **immer** die aktuelle
Liga voran (Items sind nie liga-übergreifend gültig), danach aktiver
Item-Filtertext, sonst der Name des Tabs bzw. "Alle Tabs" im Aggregat,
danach die tatsächlich exportierte Item-Anzahl und ein Zeitstempel — z. B.
`poe-view2-Settlers-Chaos-Orb-12items-2026-08-03_1542.csv`. Anzahl und
Zeitstempel kamen dazu (Peter, 2026-08-03: "etwas aussagekräftiger"),
weil "Export selected items" und "Export visible items" (§4.22) aus
derselben Ansicht sonst denselben Namen vorschlugen — ein 5- und ein
200-Item-Export derselben Truhe waren im Downloads-Ordner nicht mehr
unterscheidbar, und ein zweiter Export überschrieb den ersten
kommentarlos, sobald man den Speichern-Dialog nur bestätigte. Der Zähler
kommt vom Aufrufer (`_export_rows(rows, ...)` kennt `len(rows)` bereits),
nicht aus einem erneuten Blick auf die Tabelle — Auswahl- und
Sichtbar-Export benutzen dieselbe Methode, aber mit unterschiedlicher
Zählbasis.

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
- Disclaimer im Hilfe-Fenster (Thema "About") und in der README:
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

### 4.50 Fächer, die es bei GGG nicht gibt (`ApiWorker.stash_missing`)

GGG führt Map-Stash-Unterfächer in der Fächerliste, beantwortet den
Abruf aber mit `404` und `{"stash":null}`, solange nichts darin liegt.
Das ist eine gültige Antwort. Zum Problem wurde sie durch die
Auswahlregel des Rundlaufs: Ein nie geladenes Fach gilt als unendlich
alt (damit sich eine frische Truhe von selbst füllt), der Abruf
scheitert, es wird kein Ladezeitpunkt geschrieben — also ist dasselbe
Fach beim nächsten Takt wieder das älteste. Der Rundlauf kam an kein
anderes Fach mehr heran (Messung und Vorgeschichte: FALLSTRICKE #75).

Der Worker unterscheidet diesen Fall deshalb von einem Fehler: kein
`job_error` mit Traceback, sondern `stash_missing(liga, kennung, text)`
und eine erklärende Zeile im Log. `MainWindow._missing_stashes` hält die
betroffenen Kennungen **je Liga** (Fach-Kennungen sind ligaweit
vergeben), beide Rundläufe überspringen sie, und ein geglückter Abruf
nimmt das Fach wieder auf — legt der Nutzer eine Karte hinein, gibt es
das Fach plötzlich.

Der Merker ist **sitzungslokal und steht nicht im Cache**: Ob es ein Fach
gibt, entscheidet GGG, nicht unser letzter Programmlauf. Ein bewusster
Klick versucht es ohnehin weiter — ausgeschlossen ist nur der
automatische Rundlauf.

Der Text für die Statusleiste reist **im selben Signal** mit (leer bei
einem stillen Abruf), statt zusätzlich als `job_error` zu kommen: Beide
Empfänger geben die Kette des taktenden Modus frei, und zweimal
freigeben verschluckt einen Takt.

### 4.51 Die Liga der letzten Sitzung (`league/last`)

Peter, 2026-08-24: "Wir sollten uns merken, welche Liga zuletzt
ausgewählt war, und die nach dem Neustart anzeigen." Vorher entschied
`_sort_by_content()` den Start — also die Liga mit dem meisten Inhalt.
Das ist eine brauchbare Vorgabe für den allerersten Start und eine
schlechte für jeden weiteren: Wer in der aktuellen Liga spielt, deren
Truhe aber noch dünn ist, landete jedes Mal wieder in Standard.

Der Merker liegt in der `ui-settings.ini` neben den anderen
Oberflächen-Einstellungen und wird bei jedem Liga-Wechsel geschrieben.
Gelesen wird er **nur, wenn noch nichts gewählt ist**:

```python
previous = self._league_combo.currentText() or self._load_last_league()
```

Das ist die ganze Logik, und die Reihenfolge ist der Punkt. Andersherum
risse jeder Rebuild mitten in der Sitzung — neue Liga-Antwort,
Kontowechsel — die Auswahl auf den Startwert zurück. Dass beide Werte
auseinanderlaufen können, ist kein Sonderfall: Ein zweites Fenster
(Nur-Lese-Instanz) schreibt in dieselbe Datei.

**Ohne Prüfung, ob es die Liga noch gibt.** Temporäre Ligen enden; der
gemerkte Name steht dann in keiner Liste mehr, `findText` findet ihn
nicht, und die Auswahl fällt wie bisher auf den ersten Eintrag. Eine
eigene Prüfung wäre dieselbe Entscheidung ein zweites Mal, getroffen an
einer Stelle, die die fertige Liste noch gar nicht kennt.

### 4.52 Die Mod-Sammlung (`services/mod_collection.py`)

Peter, 2026-08-24: "Ich finde die Idee mit der eigenen Datenbank am
besten, hat etwas von einer Briefmarkensammlung: Einfach mal jedes Objekt
in der Hand gehalten zu haben und von PoE-VIEW kategorisiert und
eingetragen. Kann ja auch Spaß machen ;-)"

Vorgeschichte ist die Frage nach Affixen statt Mod-Zeilen. Die
GGG-Konto-API liefert Mod-Zeilen als fertigen Text: kein Affix-Name, kein
Tier, keine Wertspanne. **Nachgemessen am 2026-08-24 an Peters Cache:
kein einziges `extended`/`magnitudes`-Feld** — diese Angaben gibt es in
der Public-Stash- und der Trade-API, nicht in unserer. Eine fremde
Mod-Datenbank (RePoE o. ä.) wäre der übliche Ausweg; sie muss zur
laufenden Liga passen und bringt fremde Daten ins Repo.

**Was diese Sammlung stattdessen tut: aufschreiben, was durch die eigenen
Hände ging.** Kein Tier, keine wahre Spanne — sondern "so oft gesehen, so
hoch und so niedrig gerollt, auf Items dieser Stufen". Das ist ehrlich,
braucht niemanden sonst, veraltet bei keinem Patch und ist ab dem
zehnten Item nützlich statt ab dem zehntausendsten.

**Ein Primitiv trägt alles:** die Zeile ohne ihre Zahlen.
`+96 to maximum Life` → `# to maximum Life`. Das Vorzeichen gehört zur
Zahl und verschwindet mit ihr, sonst wären `+40%` und `-60%` zwei Mods
und die Spanne zeigte den negativen Roll nie. Dieselbe Umformung trägt
später die Gruppierung mehrzeiliger Affixe: Zwei Zeilen, die immer
gemeinsam auftreten, sind mit hoher Wahrscheinlichkeit ein Affix.

**Vier Messungen an Peters echtem Bestand haben den Entwurf geformt:**

1. **Die Sammlung ist klein.** 200.954 Mod-Zeilen aus 59.249 Items ergeben
   6.125 Identitäten, 1,5 MB JSON. Ein Datenbank-Server wäre Aufwand ohne
   Gegenwert. Knapp ein Viertel kam genau einmal vor.
2. **Ein Topf für alle Raritäten wäre wertlos.** `#% increased Attack
   Speed` reichte darin von 3 bis 100. Getrennt: Rare 3–27 (die echte
   Affix-Spanne über alle Tiers), Unique 4–100 (feste Werte, die kein
   Affix rollt). Die Spannen liegen deshalb **je Rarität** im Eintrag, und
   der Vergleich bleibt innerhalb einer Rarität.
3. **Maps bekommen einen eigenen Topf**, obwohl die API sie als Magic
   oder Rare führt: Ihre Mods rollen aus einer anderen Tabelle und oft in
   die andere Richtung ("-60% to Fire Resistance" ist dort eine Strafe).
   Erkannt über `models.map_tier()` — dieselbe Messung, die schon der
   Suchindex braucht, deshalb dorthin gezogen statt abgeschrieben.
4. **Das Erstbefüllen kostet 1,3 Sekunden.** Zu viel für einen Rutsch beim
   Start, also in Scheiben von 4000 Items über den Ereignis-Zyklus.

**Die Datei ist unersetzlich**, und das steuert die Schreibregeln: Ein
verkauftes Item lebt nur noch dort weiter. Die Sammlung wächst deshalb
nur — würde der neue Stand weniger Einträge haben als der alte, wird gar
nicht geschrieben. Eine unlesbare Datei wird nie überschrieben, sie
könnte reparierbar sein. Je Konto eine Datei, atomar geschrieben,
höchstens einmal pro Minute (1,5 MB nach jedem geladenen Fach wären
dieselbe Verschwendung, wegen der der Daten-Cache seinen `cache_writer`
hat).

**Angezeigt wird sie am Item, als Balkenspalte vor der Mod-Zeile** —
siehe §4.52.2. Die erste Fassung nutzte dafür Zeichen (`★` für den besten
Roll, `☆` für denselben Bestwert gegen den Altbestand gemessen, `✦` für
einen Erstfund); der Balken sagt dasselbe und dazu alles zwischen den
Extremen. Was aus der Zeichen-Fassung geblieben ist, ist die harte Regel
dahinter: **vorangestellt und von fester Breite.** Das ist keine
Geschmacksfrage — das Detail-Panel bricht lange Zeilen um, zählt sein
Höhenbudget aber in Zeilen. Ein angehängtes "deine 41–96" würde die
längsten Mod-Zeilen umbrechen lassen und das Panel still über seine feste
Höhe schieben, der Fehler aus §4.39.

#### 4.52.1 Ligen: warum eine Datei je Liga die falsche Antwort wäre

Peter, 2026-08-24: "Wir sollten berücksichtigen, dass sich die Werte der
Mods im Laufe der verschiedenen Ligen geändert haben. Evtl. sollten wir
die Modsammlung auf die jeweilige Liga beziehen, d.h. für jede Liga ein
eigenes File."

Der Einwand stimmt, die naheliegende Lösung nicht. **Das Liga-Feld sagt,
wo ein Item LIEGT — nicht, in welcher Liga es GEROLLT wurde.** Standard
und Solo Self-Found sammeln seit Jahren die Items jeder abgelaufenen Liga
ein; ein Ring aus Kalandra liegt heute in Standard. Gemessen an Peters
Bestand:

| Liga | Items | Art |
|---|---|---|
| Solo Self-Found | 31.929 | dauerhaft |
| Standard | 22.896 | dauerhaft |
| SSF Ruthless | 3.365 | dauerhaft |
| Allflame + SSF-Varianten | 1.053 | temporär |

**98 % liegen in dauerhaften Ligen.** Eine Datei je Liga hätte sie in drei
Töpfe geschaufelt, die genauso gemischt sind wie vorher. Dazu ein
statistischer Preis: Die Liga als volle Achse verdoppelt die Zellen
(7.815 → 16.304), jede also dünner besetzt — und dünne Zellen liefern
schlechte Spannen.

Deshalb: **ein Topf je temporärer Liga, ein gemeinsamer für alle
dauerhaften** (`LEGACY_LEAGUE`). Temporäre Ligen sind sauber — dort wurde
alles in dieser Liga gerollt, nach ihrer Tabelle. Der Altbestand bleibt
dicht besetzt, wo Dichte möglich ist, und heißt, was er ist.

Der Topf kommt vom **Item**, nicht aus der Auswahl im Fenster: Ein Ring in
Standard gehört in den Altbestand, auch während man die laufende Liga
betrachtet. Eine unbekannte Liga gilt als temporär — die richtige
Richtung zum Irren, denn eine neue dauerhafte Liga stünde dann für sich,
statt stillschweigend in den Altbestand zu rutschen.

**Die Bewertung nimmt die eigene Liga erst ab
`MIN_LEAGUE_OBSERVATIONS` (5) Sichtungen** und sagt in der Anzeige,
worauf sie sich stützt (voller Farbton: eigener Topf, gedämpft:
Altbestand — §4.52.2). Die Zahl ist
eine Setzung, keine Messung: Unter einer Handvoll Rolls ist eine Spanne
mehr Zufall als Aussage. Eine Bewertung, deren Grundlage man nicht kennt,
ist keine — deshalb reist die Grundlage in `rating_with_basis()` mit dem
Wert mit, statt in einer Fußnote zu stehen.

**Was auch das nicht löst:** Wann ein Item im Altbestand gerollt wurde,
weiß niemand. Ein Legacy-Roll von vor drei Jahren steht dort neben einem
von gestern. Die Sammlung kann das nicht auflösen, und sie behauptet es
auch nicht — sie sagt "so habe ich es gesehen", und im Altbestand heißt
das: irgendwann.

**Warum es den Merker `is_new` überhaupt braucht:** Die Anzeige sieht ein
Item immer erst, NACHDEM es eingetragen wurde — zum Anzeigezeitpunkt ist
also nichts mehr neu. Die Sammlung merkt sich deshalb, was seit dem
letzten `clear_new()` zum ersten Mal auftauchte. Nach der Erstbefüllung
wird einmal aufgeräumt: 6.125 Funde auf einmal sind kein Fund.

**Geplant, noch nicht gebaut:** ein Feld zum Einfügen des Strg+C-Textes
aus dem Spiel. Mit eingeschalteten "Advanced mod descriptions" trägt der
genau das, was der API fehlt — Affix-Name, Tier und echte Wertspanne in
geschweiften Klammern. Ein eingefügtes Item lehrt die Sammlung nicht nur
über sich selbst, sondern über die ZEILE: Sie gilt danach für jedes
andere Item mit derselben Zeile. Damit baut sich die Sammlung ihre eigene
Tier-Tabelle auf, aus dem eigenen Client, ohne fremde Daten. Was von dort
kommt, ist gemessen; was aus API-Zeilen kommt, ist beobachtet — beides
muss in der Anzeige unterscheidbar bleiben.

Getestet: `tests/test_mod_collection.py` (Identität, Spannen je Zahl und
je Rarität, Map-Topf, Bewertung samt der Fälle ohne Vergleich, Neufunde,
Runde durch die Datei, kaputte Zeilen, Schrumpfschutz, unlesbare Datei),
`tests/test_item_detail.py` (nur Mod-Zeilen bekommen eine Marke; das Feld
einer Zeile überlebt den Weg durchs Panel),
`tests/test_main_window_helpers.py` (geladene Fächer landen in der
Sammlung, Balken nur innerhalb der Rarität, Erstbefüllung in Scheiben).

#### 4.52.2 Der Balken vor der Mod-Zeile (`ui/mod_bar.py`)

Peter, 2026-08-24: "Können wir hinter die Mods eine Progressbar machen,
die anzeigt, wo der Mod im Vergleich zu anderen liegt? In etwa so:
|||||||I|| oder so ähnlich?" — und, nachdem die Zeichen-Variante an ihre
Grenzen kam: "Oder wir nehmen keine Balkenzeichen sondern definieren hier
eine extra Spalte mit einem Rechteck und das wird prozentual gefüllt."

Der Balken ist die Verallgemeinerung des Sterns: Er zeigt nicht nur den
Bestwert, sondern die Lage des Rolls in dem, was die Sammlung kennt.
`RaritySpan.rating()` liefert diese Zahl längst; sichtbar war bisher nur
ihr oberes Ende.

**Was ihn überhaupt trägt** (gemessen an Peters Bestand, 202.182
Mod-Zeilen):

| | Anteil |
|---|---|
| Balken | 75,8 % |
| kein Vergleich (nur ein Wert je gesehen) | 23,6 % |
| Zeile der Sammlung unbekannt | 0,6 % |

Der Median-Balken steht auf **218 Sichtungen**; nur 3,2 % auf unter zehn.
Unter `MIN_BAR_OBSERVATIONS` (5) wird gar keiner gezeichnet — das kostet
0,8 % der Zeilen und nimmt die heraus, bei denen zwei Rolls wie eine
Skala aussähen. Eigene Zahl, nicht `MIN_LEAGUE_OBSERVATIONS`: Jene
entscheidet, welcher Topf den Vergleich trägt, diese, ob ein Vergleich
überhaupt gezeigt wird.

**Warum ein gezeichnetes Rechteck und kein Balken aus Zeichen.** Peters
erster Vorschlag war `|||||||I||`; die Messung hat ihn widerlegt, und
zwar an der Stelle, an der man es nicht erwartet — nicht am Balken,
sondern an den 23,6 % Zeilen OHNE Balken. Die brauchen eine Lücke von
exakt der Balkenbreite, sonst rutscht ihr Text nach links. Alle Zeichen
des Block- und Rahmen-Bereichs (U+2500…U+259F) sind gleich breit, in
jeder Schriftgröße; **kein Leerzeichen der Schrift hält dazu ein festes
Verhältnis** — gemessen über 8 bis 14 pt schwankt NBSP zwischen 2,25 und
3,0 Blockbreiten. Ein Rechteck aus gefärbten geschützten Leerzeichen hat
das Problem nicht: Die Spalte besteht IMMER aus derselben Zahl Zellen,
gefärbt wird nur, was gefüllt ist. Die Lücke ist dieselbe Spalte,
ungefärbt.

**Aufbau der Spalte:** 14 Zellen plus zwei Zellen Abstand, bei 9 pt
gemessene 42 px breit und damit rund 7 % Auflösung. Der Erstfund behält
sein `✦` (plus zehn Zellen Auffüllung, die die Spaltenbreite auf ±1 px
trifft) — ein goldener Vollbalken war die naheliegende Alternative und
wurde verworfen, weil er sich als "Maximum" liest, und das ist beim
Erstfund gerade die falsche Aussage. **Die Ränder sind geklemmt:** ganz
voll nur bei genau 1.0, ganz leer nur bei genau 0.0. Ohne das sähe ein
Roll bei 0,97 aus wie der beste je gesehene — und genau diese Aussage ist
die einzige, die der Balken hart trifft.

**Farben, gerechnet gegen den gemessenen Panel-Grund `#2d2d2d`:** Spur
`#4a4a4a` (Kontrast 1,55, ΔE 9,5 — sichtbar, aber leise), Füllung
`DASH_OK` für den eigenen Topf und ein um 25 % zum Grund gemischter Ton
für den Altbestand (ΔE 10,3 zwischen beiden). Das ist die Unterscheidung,
die vorher `★` und `☆` trugen.

**Der Preis:** Die Spalte steht vor der Mod-Zeile, also braucht dieselbe
Zeile mehr Platz. `ItemDetail.preferred_width()` schlägt sie auf, damit
die 68 Zeichen erhalten bleiben, für die das Panel bemessen ist; bei
gleicher Panelbreite deckt es 93,0 % der Items ohne Abschneiden ab statt
94,2 %.

**Zwei Fallen lagen auf dem Weg**, beide nur im echten Fenster sichtbar:
Der Panel-Grund ist `#2d2d2d`, obwohl `QPalette.Window` `#1e1e1e` meldet
(FALLSTRICKE #76), und Qt schneidet führenden Leerraum am Blockanfang
weg, wodurch die erste Mod-Zeile nach einer Trennlinie ihren Balken in
den Block DAVOR bekam (FALLSTRICKE #77).

**Die Marke ist HTML und wird nicht escaped**, der Mod-Text schon.
Deshalb trägt `item_detail.Line` beide Hälften in getrennten Feldern:
Wären sie ein String, müsste beim Zusammensetzen jemand entscheiden,
welcher Teil escaped wird — und das ist der Weg, auf dem fremder Text
irgendwann als Markup durchrutscht.

Getestet: `tests/test_mod_bar.py` (Füllstand samt beider Klemmungen,
gleiche Zellenzahl in allen Fällen, Farben je Topf, die Schwelle, kein
Balken ohne Zahl, und dass der Balken im Block SEINER Mod-Zeile landet —
geprüft am geparsten `QTextDocument`, weil die Frage nicht an der Schrift
hängt), `tests/test_item_detail.py` (die Escaping-Grenze in beide
Richtungen, Panelbreite).

#### 4.52.3 Das Album: durch die Sammlung blättern (`ui/mod_album.py`)

Peter, 2026-08-24, derselbe Satz, der die ganze Sammlung angestoßen hat:
"Ich finde die Idee mit der eigenen Datenbank am besten, hat etwas von
einer Briefmarkensammlung: Einfach mal jedes Objekt in der Hand gehalten
zu haben und von PoE-VIEW kategorisiert und eingetragen." Die ersten
beiden Stufen beantworten "wie gut ist DIESER Roll" — am Item, im
Moment. Eine Sammlung ist aber erst eine Sammlung, wenn man auch OHNE ein
Item in der Hand durchblättern kann, was man hat. Das ist die dritte
Stufe.

**Aufbau**, bewusst schlicht gehalten — ein Fenster für einen
Nachschlage-Blick, kein eigenes Datenmodell mit eigenen Regeln:

- Eine sortierbare Tabelle (Mod, Art, **Range**, Häufigkeit,
  Beispieltext) über `ModCollection.records()`, ungefiltert 6.125 Zeilen
  bei Peters Bestand.
- Eine Textsuche gegen die Identität (`QSortFilterProxyModel`,
  `setFilterFixedString`) und drei unabhängige Filter daneben — Art
  (Explicit/Implicit/Enchant/…), Liga und Rarität. Alle geltenden
  Bedingungen müssen gleichzeitig zutreffen, sonst ließe sich mit einem
  Filter ein anderer aushebeln. Jedes Menü listet nur Werte, die die
  Sammlung tatsächlich enthält; ein Eintrag ohne Treffer wäre eine
  Sackgasse.
- Ein Klick auf eine Zeile füllt ein Textfeld mit dem vollen Steckbrief:
  jede (Liga, Rarität), in der der Mod je auftauchte, mit Sichtungszahl,
  Wertspanne und Item-Stufen-Bereich — genau die Daten, die
  `RaritySpan`/`ModRecord` ohnehin schon führen, hier nur ausgeschrieben
  statt auf eine einzelne Zahl verdichtet wie am Item.

**Die Range-Spalte, Peters Nachtrag vom 25.08.: "Mir fehlt in der Mod
Collection die Spalte mit Range (minimum to maximum)."** Zeigt den
Wertebereich über GENAU die Töpfe, die Liga- und Raritäts-Filter gerade
durchlassen — bei "All leagues"/"All rarities" also über die ganze
Sammlung. Das ist eine bewusste Wahl gegen die naheliegende Alternative,
für jede Zeile "den einen richtigen" Topf zu erraten: Das würde exakt die
Frage vortäuschen zu beantworten, die die Liga-/Raritäts-Bucketierung
(§4.52.1) überhaupt aufgeworfen hat. Am echten Bestand sichtbar: `# to
maximum Life` zeigt ungefiltert `-148–500` (genau der historische
Ausreißer, der §4.52.1 zur Rarity-Trennung geführt hat), gefiltert auf
"Normal / Magic / Rare" `-148–203`, auf "Unique" `4–500` — die Spalte
zeigt ehrlich, was gerade eingeschlossen ist, statt eine homogene
Population zu unterstellen, die es ohne Filter nicht gibt.

**Liga- und Raritäts-Filter sind gleichzeitig Zeilen- UND
Range-Spalten-Filter** — mit derselben Auswahl gefüttert, aus demselben
Grund: Eine Zeile ohne passenden Topf für die eine Achse hätte für die
andere ohnehin nichts zu zeigen. Der Liga-Filter listet jede in der
Sammlung vorkommende Liga; `None` ist der Sentinel für "keine
Einschränkung" und bewusst NICHT der leere String — der ist
`LEGACY_LEAGUE` selbst, eine echte, einzeln wählbare Liga (der
Altbestand). Beide zu verwechseln hätte den Altbestand unwählbar gemacht.

**Rarität wird in Gruppen gefiltert, nicht einzeln** — Peters eigene
Gliederung ("Unique, Corrupted, (Normal/Magic/Rare), evtl. noch
andere"): Normal/Magic/Rare in einer Gruppe, Unique separat, Corrupted
als eigene Gruppe über alle Basis-Raritäten hinweg, dazu Map und ein
Sammeltopf für Gem/Currency/Card/Relic. Die Gruppen sind als PRÄDIKATE
definiert (`Callable[[int], bool]`), nicht als feste Zahlen-Tupel —
"Corrupted" lässt sich nicht als endliche Liste schreiben, weil der
Aufschlag (siehe unten) auf jeder Basis-Rarität gilt.

Als Combo-Box-Daten stehen die Rarity-Gruppen unter ihrem NAMEN, nicht
dem Prädikat selbst — `QComboBox.findData` verglich zwei identische
Python-Tupel an anderer Stelle gemessen nicht als gleich (FALLSTRICKE
#78), ein String-Schlüssel hat das Problem nicht (dieselbe Lösung wie
beim Art-Filter).

**Corrupted ist kein weiterer Wert einer bestehenden Achse, sondern ein
Aufschlag auf die Rarität selbst** (`mod_collection.CORRUPTED_OFFSET =
1000`, addiert in `collection_bucket()`, wenn `item.corrupted`). Ein
corrupted Rare bekommt damit einen anderen Topf als ein gewöhnliches Rare
UND als ein corrupted Unique — beides nötig, denn manche
Corruption-Ergebnisse sind eigene Implicit-Zeilen mit eigener
Wertetabelle (etwa eine große negative Resistenz als Strafe), die sonst
die Spanne des gewöhnlichen Topfs verzerrt hätten, während die
Rarity-Trennung aus §4.52.1 (Rare ≠ Unique) erhalten bleiben muss.

Diese Bauweise wurde bewusst gegen zwei Alternativen gewählt:

- **Ein eigener Topf, der `frameType` ganz ersetzt** (wie bei `MAP_RARITY`)
  wäre die einfachere Lösung gewesen, hätte aber genau die Rare/Unique-
  Vermischung wieder eingeführt, die §4.52.1 beheben sollte — ein
  corrupted Rare und ein corrupted Unique landeten dann im selben Topf.
- **Eine dritte Verschachtelungsebene** (`spans[league][rarity][corrupted]`)
  wäre am saubersten benannt, hätte aber die Datenstruktur, das
  Dateiformat und jede Stelle betroffen, die `rarity` als einzelnen int
  entgegennimmt (`ModRecord.span()`, `rating()`, `rating_detail()`,
  `mod_bar.py`). Der Aufschlag braucht dagegen NICHTS davon zu ändern:
  `ModRecord.spans` bleibt `dict[str, dict[int, RaritySpan]]`, nur der
  Zahlenraum der inneren Schlüssel wird breiter. Maps bekommen den
  Aufschlag NICHT — Kartenkorruption fügt keine neuen Implicit-Zeilen mit
  eigener Tabelle hinzu wie bei Ausrüstung, der Grund für den Aufschlag
  greift dort nicht.

**Der Balken am Item (§4.52.2) trennt automatisch mit**, ohne dass
`mod_bar.py` etwas davon weiß: Er bekommt seine Rarität über
`item_buckets()`/`collection_bucket()` und vergleicht ohnehin nur
innerhalb desselben Zahlenwerts — ein corrupted Item landet jetzt einfach
in einem anderen Zahlenwert und wird nur noch gegen andere corrupted
Items derselben Basis-Rarität verglichen. Nebenwirkung: Manche Mod-Zeilen
rutschen dadurch unter `MIN_BAR_OBSERVATIONS` und zeigen vorübergehend
keinen Balken mehr, bis genug corrupted Sichtungen zusammengekommen sind
— derselbe Tausch von Abdeckung gegen Richtigkeit wie beim Map-Topf.

**Nur NEUE Beobachtungen werden getrennt.** Ein Wert, der vor dieser
Änderung im gewöhnlichen Topf gelandet ist (corrupted oder nicht, beides
ununterscheidbar gemischt), bleibt dort für immer stehen — `RaritySpan`
kennt nur "je gesehen", kein Rückgängig. Dieselbe Regel wie bei der
Liga-Trennung: Gemessen an Peters Bestand haben 4.622 von 59.253 Items
(rund 7,8 %) `corrupted=true`; ihre bereits gespeicherten Beiträge zu den
alten, ungetrennten Töpfen bleiben, wo sie sind, und nur der weitere
Zuwachs trennt sich sauber.

**Ein Schnappschuss, keine Live-Ansicht.** Jeder Klick auf den
Werkzeugleisten-Knopf öffnet eine neue Instanz mit dem aktuellen Stand
der Sammlung (dieselbe Bauweise wie die Paperdoll, §4.7) — kein
Abonnement auf künftige Beobachtungen. Ein Fenster zum Durchblättern, das
sich unter der Maus neu sortiert, wäre schlechter als eines, das beim
nächsten Öffnen einfach frisch befüllt ist.

Getestet: `tests/test_mod_collection.py` (Corrupted-Aufschlag trennt von
gewöhnlicher UND von Unique-Rarität, trifft Maps nicht, die
Grenzwert-Falle bei `frameType 0` — ein `>` statt `>=` hätte genau diesen
einen Fall übersehen), `tests/test_mod_album.py` (Anzeigenamen inklusive
der beiden Sonder-Raritäten und "Corrupted X", der Steckbrief-Text, alle
vier Filter einzeln und kombiniert, die Corrupted-Gruppe über
Basis-Raritäten hinweg, die Range-Spalte inklusive mehrzahliger Mods,
negativer Spannen und der Liga-Sentinel-Falle, jedes Menü ohne leere
Einträge), `tests/test_main_window_helpers.py` (der Werkzeugleisten-Knopf
öffnet das Fenster mit der tatsächlichen Sammlung des laufenden
Fensters).

#### 4.52.4 Tier-Bänder aus dem Item-Level (`services/mod_tiers.py`)

Peter, 2026-08-25: "Ich weiß, dass Items mit einem Tier versehen sind;
wir kennen das Item-Level; wir wissen, dass ab einem bestimmten
Item-Level der nächste Tier freigeschaltet wird und dadurch der Range
erhöht wird; anhand der Gauss-Verteilung sollten wir die verschiedenen
Ranges eigentlich auseinanderkennen können."

**Der Gedanke stimmt, die Statistik geht anders aus — und das ist der
Kern dieses Abschnitts.**

**Warum Gauß nicht greift.** PoE-Tiers grenzen lückenlos aneinander. In
Peters Daten ist das Sechserraster direkt sichtbar: Plateaus bei 11, 17,
23, 29, 35, 41, 45. Zwischen 11 und 12 liegt kein Tal, sondern eine
Kante. Innerhalb eines Tiers ist der Roll gleichverteilt, nicht
glockenförmig. Ein Gauß-Mixture sucht getrennte Hügel — hier gibt es
keine. Im reinen Werte-Histogramm bliebe nur ein schwaches Signal übrig:
Die Dichte fällt an jeder Grenze etwas ab, weil hohe Tiers auf weniger
Items vorkommen.

**Das Item-Level ist kein statistisches Signal, sondern ein Beweis.** Ein
Tier KANN unterhalb seiner Freischaltung nicht auftreten. Die belastbare
Größe ist deshalb die untere Einhüllende: "das niedrigste iLvl, auf dem
ich je einen Wert ≥ t gesehen habe". Sie ist von Natur aus monoton, und
fehlende Daten machen sie nur zu vorsichtig, nie falsch.

**Gerechnet wird mit der Pareto-Front** (`mod_collection.add_evidence`).
Ein Beleg zählt nur, wenn kein anderer gleichzeitig einen höheren Wert
UND ein niedrigeres iLvl hat. Das ist genau die Treppe, und ihre Länge
hängt an der Zahl der Tiers, nicht an der Zahl der Beobachtungen: 1323
Sichtungen von `#% to Cold Resistance` schrumpfen auf 15 Punkte.
GESPEICHERT wurde die Front nur in Aufbau 3/4; seit Aufbau 5 liegt
stattdessen das Werte-Kontenbuch in der Datei (§4.52.6), aus dem
`ModRecord.tier_front` sie bei Bedarf ableitet — für die Front zählt je
Wert ohnehin nur sein niedrigstes iLvl, die Ableitung verliert also
nichts.

**Die Basis-Kategorie ist eine eigene Achse, die Liga nicht.** Ein Ring
rollt eine andere Tier-Tabelle als eine Rüstung, bei identischem
Mod-Text; ohne diese Trennung verschmiert die Leiter. Die Liga dagegen
spielt für die Tier-Schwellen keine Rolle und würde die Belege nur
ausdünnen — sie fehlt im Kontenbuch deshalb bewusst, obwohl `spans`
sie führt.

**Belegt werden nur gerollte Affixe** (`mod_collection.tierable`):
unkorrumpierte Magic-/Rare-Items mit bekanntem Item-Level. Normal hat
keine Affixe, Unique feste Werte, Maps eine eigene Tabelle, und
Korrumpiertes bringt Vaal-Ergebnisse mit eigenen Wertebereichen mit. Der
Corrupted-Aufschlag (§4.52.2) erledigt den letzten Fall schon von selbst,
weil er die Rarität aus dem Bereich `(1, 2)` heraushebt.

**Wie gut die Ableitung ist — gemessen gegen künstliche Daten mit
bekannter Wahrheit:**

| Item-Level der Belege | Beobachtungen | Güte (F1) |
|---|---|---|
| gleichverteilt 1–84 | 2000 | **1,00** |
| gleichverteilt 1–84 | 250 | 0,46 |
| wie in Peters Bestand | 2000 | 0,75 |
| nur 75–85 (Endgame) | beliebig | **0,25** |

**Die Methode ist also in Ordnung; was ihr fehlt, ist Streuung im
Item-Level — nicht Masse.** In Peters Bestand liegen 83,6 % der
Magic-/Rare-Items bei iLvl 70+ und nur 7,0 % unter iLvl 60. Ab iLvl 75
sind alle Tiers bis auf das letzte verfügbar; die Einhüllende hat dort
nichts mehr zu trennen, und weitere zehntausend Maps ändern daran
nichts. Scharf werden die Bänder erst, wenn eine Liga wieder von unten
hochgespielt wird.

**Deshalb schweigt `bands()` lieber.** Das Kriterium ist das tiefste
Belegs-iLvl — der stärkste der getesteten Prädiktoren (gegen
Front-Länge, iLvl-Spanne und Zahl der Beobachtungen): Reichen die Belege
unter iLvl 19, liegt die Güte im Mittel bei 0,81; fangen sie erst bei
iLvl 57 an, nur noch bei 0,24. An Peters Bestand tragen 189 von 2.144
Töpfen mit Belegen (8,8 %) überhaupt Bänder. Wo nicht, nennt
`why_silent()` den Grund — ein leeres Feld sähe aus wie ein Fehler, und
der häufigste Grund ist kein Mangel der Sammlung, sondern eine
Eigenschaft der Items.

**Warum das ein eigenes Modul ist.** `mod_collection` sammelt Belege und
verspricht ausdrücklich, nichts zu behaupten ("Beobachtung, keine
Wahrheit"). Bänder abzuleiten IST eine Behauptung. Die Trennung hält
sichtbar, welche Zahl woher kommt — und dieselbe Grenze steht in der
Anzeige: Obergrenzen sind belegt, Untergrenzen erschlossen (aus der
Annahme, dass Tiers lückenlos aneinandergrenzen). Eine Tier-NUMMER wird
bewusst nicht vergeben: Solange unbekannt ist, wie viele Tiers über dem
höchsten gesehenen liegen, wäre "T3" eine Erfindung.

**Der Nachtrag für vorhandene Sammlungen** (`backfill_tiers`) trägt die
Belege aus dem Cache nach, **ohne einen einzigen Zählstand anzufassen**.
Einfach neu einzulesen wäre der naheliegende Weg und der falsche: Jede
Sichtung zählte doppelt, und die Sammlung ist der einzige Ort, an dem ein
verkauftes Item noch existiert — eine verdoppelte Zählung ließe sich nie
wieder herausrechnen. Kostet gemessene 0,33 s für 59.253 Items.

Getestet: `tests/test_mod_tiers.py` (Pareto-Logik in beide Richtungen,
die Kappung, die echte Front aus Peters Bestand reproduziert die
bekannte Resistenzleiter, Bänder grenzen lückenlos aneinander — und vor
allem: Endgame-Belege ergeben KEINE Bänder, und das Schweigen begründet
sich selbst), `tests/test_mod_collection.py` (nur gerollte Affixe zählen
als Beleg, der Nachtrag lässt jeden Zählstand unberührt und legt keine
Einträge an, Runde durch die Datei, ein Stand nach Aufbau 2 lädt weiter),
`tests/test_mod_album.py` (Bänder im Steckbrief, der Grund beim
Schweigen, die Kennzeichnung von Beleg gegen Annahme).

#### 4.52.5 Die Kartenansicht: das Album als Album (`ui/mod_album.py`)

Peter, 2026-08-27, mit einem Screenshot der Tabelle: "das fühlt sich
irgendwie nicht wie ein Sammel-Album an." Die Diagnose dahinter: Ein
Briefmarkenalbum hat Seiten, Prunkstücke und sichtbare Lücken — die
Tabelle hatte nichts davon, sie war ehrlich eine Datenbank-Ansicht.
Zwei der drei Zutaten waren ohne neue Datenquelle zu haben und sind
diese Stufe; die dritte (Lücken = "was es im Spiel gibt, aber du nie
gesehen hast") bräuchte eine externe Mod-Liste und bleibt ein eigenes
Vorhaben.

**Karten statt Zeilen.** Eine `QListView` im IconMode mit einem
`QStyledItemDelegate` (`ModCardDelegate`) zeichnet jede Mod-Identität
als Karte: Name (zwei Zeilen, Volltext im Tooltip — die längste
Identität in Peters Bestand hat 381 Zeichen), Range in Grün, Art und
Sichtungszahl gedämpft in der Fußzeile. Bewusst KEINE 6.125
Karten-Widgets: Die Listenansicht zeichnet nur Sichtbares
(`LayoutMode.Batched`, `uniformItemSizes`), und weil sie auf DEMSELBEN
Proxy-Modell sitzt wie die Tabelle, wirken Suche und alle Filter in
beiden Ansichten identisch, ohne eine Zeile doppelter Filterlogik.
Beide Ansichten teilen sich zudem EIN `QItemSelectionModel` — wer in
der Tabelle eine Zeile wählt und umschaltet, steht auf derselben Karte.

**Trophäen als Sortier-Linsen, nicht als eigene Seiten.** "Newest
finds", "Most seen" und "Seen once first" sind Sortierungen derselben
Karten (`ALBUM_SORTS`): Einzelstücke tragen zusätzlich einen goldenen
Rand (`DASH_WARN` — die App hat genau ein Bernstein, und es bedeutet
"besonders"), Sitzungs-Funde ein ✦ (dasselbe Zeichen wie am Item,
§4.52.2). In der Tabelle sortiert weiter der Spaltenkopf; beim
Umschalten dorthin wird die Sortier-Rolle auf `DisplayRole`
zurückgesetzt, sonst deutete eine übrig gebliebene `FIRST_SEEN_ROLE`
jeden Kopf-Klick auf der Mod-Spalte still um.

**"Zuletzt eingetragen" braucht ein Datum: `first_seen`** (Aufbau 4 der
Datei, §`VERSION`). Nur der ERSTE Kontakt setzt es; ein alter Stand lädt
mit 0 = Grundstock, denn der Cache weiß nicht, WANN ein Item erstmals
durch die Truhe ging, und ein nachträglich erfundenes Datum wäre eine
Behauptung. Der Grundstock schreibt das Feld gar nicht erst in die Datei
(6.000+ bedeutungslose Nullen). Im Steckbrief steht das Datum als
"entered the collection on …", im Grundstock-Fall gar nichts.

**Der Sammlungs-Puls statt eines grauen Platzhalters.** Solange keine
Karte gewählt ist, zeigt das Detail-Feld den Stand der Sammlung
(`collection_greeting`): Gesamtzahl, Einzelstücke, Funde dieser Sitzung,
jüngster Fund mit Datum. Ein Album schlägt man auf und sieht zuerst,
wie es um die Sammlung steht.

**Farben gerechnet, nicht begutachtet** (gegen den GEMESSENEN Grund
`#2d2d2d` aus FALLSTRICKE #76, den die Ansicht per Stylesheet erzwingt,
statt `QPalette.Base` zu vertrauen): Karte `#3c3c3c` (ΔE 4,8 zum Grund)
mit Rand `#555555` (ΔE 9,7 zur Karte), Name `#e8e6e3` (WCAG 9,4),
Nebentext `#b0b0b0` (5,4), Range `#8fbf7f` (5,5 — `DASH_OK` selbst läge
mit 4,4 knapp unter 4,5), Einzelstück-Rand `DASH_WARN` (ΔE 52,8).

Getestet: `tests/test_mod_album.py` (Rollen, Sortier-Linsen, geteilte
Auswahl, Rücksetzen der Sortier-Rolle, Zeichnen ohne Fehler, Puls-Text,
Datum nur wo bekannt) und `tests/test_mod_collection.py` (Datum nur beim
ersten Kontakt, Runde durch die Datei, Grundstock schreibt kein Feld,
`new_keys` als Schnappschuss).

#### 4.52.6 Das Werte-Kontenbuch und die Band-Tabelle

Peter, 2026-08-27, zur Tier-Anzeige im Album: Er wollte je Tier eine
Zeile der Form `Count | Min | Max | iLvl-Min | iLvl-Max`. Aus einer
Pareto-Front lassen sich aber keine Zählungen je Band gewinnen — sie
hält von jedem Wert nur den besten Beleg. Aufbau 5 der Datei ersetzt
die gespeicherte Front deshalb durch das **Kontenbuch**
(`ModRecord.tier_ledger`): je Basis-Kategorie und WERT die Zahl der
Sichtungen samt iLvl-Spanne (`wert → [n, il_min, il_max]`). Die Front
ist daraus jederzeit ableitbar (`tier_front`), die Umkehrung nicht —
darum ersetzt das Buch die Front, statt daneben zu liegen. Gemessen an
Peters Cache: 32.258 Wert-Zeilen, ~0,7 MB, größtes Konto 76 Werte
(`# to maximum Life`); die Kappung `_MAX_LEDGER_VALUES = 512` ist reine
Vorsicht.

**Der Sprung von Aufbau 3/4 auf 5 nutzt den vorhandenen Nachtrag.** Ein
alter `tiers`-Block wird beim Laden verworfen — ohne Zählungen wäre er
im Kontenbuch eine Zeile mit erfundenem `n`. Danach ist
`has_tier_evidence()` falsch, und derselbe Mechanismus, der beim Sprung
auf Aufbau 3 die Belege aus dem Cache nachtrug (`backfill_tiers`,
§4.52.4), baut beim nächsten Start das volle Buch auf, ohne einen
Album-Zählstand anzufassen.

**Die Bänder heißen Prozent, nicht T-Nummern** (`mod_album.band_table`).
Peters eigene Begründung: "Wenn wir Zahlen benutzen ist das mit Ingame
verwechselbar und gerade am Anfang stimmt das noch nicht." Jedes Band
trägt seinen Anteil an der gesehenen Wertspanne (`0–14 %`, `21–100 %`);
sobald genug Daten das echte Tier-System hergeben, wird umbenannt. In
der Tabelle steht je Band: Sichtungen, Wert-Spanne, iLvl-Spanne — jeder
Wert des Kontos gehört zum ERSTEN Band, dessen Obergrenze er nicht
übersteigt, damit auch halbzahlige Werte zwischen zwei ganzzahligen
Grenzen nicht durchfallen. Das Detail-Feld ist seither eine feste
Schrift (`QFontDatabase.systemFont(FixedFont)`), sonst stünden die
Spalten nur ungefähr untereinander.

Getestet: `tests/test_mod_collection.py` (Kontenbuch akkumuliert je
Wert, Front aus dem Buch nimmt je Wert das niedrigste iLvl, alter
`tiers`-Block wird verworfen und der Nachtrag springt an) und
`tests/test_mod_album.py` (Zählungen je Band, Prozent-Beschriftung ohne
ein einziges "T", kein Wert fällt zwischen zwei Bänder, Tabelle im
Steckbrief).

### 4.53 Das Fundament der echten Mod-Datenbank (`services/mod_knowledge.py`)

Peter beim Betrachten der Prozent-Bänder aus §4.52.6, nach einem
Vergleich mit CraftOfExiles Intelligence-Tabelle: "was sehe ich hier
und was bringt mir das? [...] Ich bin mir nicht sicher, ob wir hier was
Sinnvolles machen oder einem Gespenst hinterherjagen." Eine
Machbarkeitsmessung (read-only gegen Peters echten Bestand, nichts
davon gespeichert) beantwortete das: **kein Gespenst.** RePoE
(`repoe-fork/repoe`, aktiv gepflegt, Exporte unter
`https://repoe-fork.github.io/`) liefert Mod-Definitionen, Stat-
Übersetzungen und Item-Basen als offene JSON-Exporte aus dem
Spielclient selbst — daraus lassen sich echte Tier-Leitern bauen, ohne
selbst tausende Beobachtungen zu brauchen.

**Lizenz-Falle, deshalb Laufzeit-Download statt Repo-Bündelung.** RePoEs
CODE ist MIT, die generierten DATEN gehören laut dessen eigenem
`LICENSE.md` GGG. Genau wie der poe.ninja-Preis-Cache (`price_cache.py`)
lädt `mod_knowledge.py` die drei Dateien deshalb zur Laufzeit
(`fetch()`, TTL 7 Tage — RePoE ändert sich mit Spiel-Patches, nicht mit
Sitzungen) und hält sie unter `%LOCALAPPDATA%/PoE-VIEW2/mod-knowledge/`
vor, statt sie mitzuliefern. Ein Teil-Download (Abbruch nach der ersten
von drei Dateien) darf keinen inkonsistenten Stand hinterlassen — erst
wenn alle drei da sind, schreibt `fetch()` sie und den Manifest.

**Die Übersetzung stat_id+Wert → Mod-Identität braucht die
`index_handlers` (negate, divide_by_X, ...) nicht.** `mod_identity()`
(§4.52, `mod_collection.py`) ersetzt JEDE Ziffernfolge durch `#` — für
die Identität reicht ein plausibel-numerisch gerenderter Text,
`render_identity()` rendert deshalb nur grob (Vorzeichen/Format aus der
passenden `condition`) und verzichtet auf die exakte Umrechnung. Das
war Teil der Messung, keine Abkürzung erst hier.

**Die Ground-Truth-Leiter ist über (Identität, `item_category()`)
geschlüsselt**, im selben Namensraum wie `ModRecord.tier_ledger` — nur
so sind beide vergleichbar. Da RePoEs Eligibility über Item-BASIS-Tags
läuft ("dex_boots", nicht "boots"), aber `item_category()` gröber ist
("Boots"), bildet `build()` je Kategorie die Vereinigung aller Tags
ausgelieferter Basen (`base_items.json`, `release_state: released`) und
prüft ein Mod als eligible, sobald er für IRGENDEINEN Tag dieser
Vereinigung ein positives Gewicht trägt. Eine Annäherung (kann einen
Mod fälschlich einer ganzen Kategorie zuschlagen, der nur eine
Rüstungsvariante trifft) — dieselbe, mit der die Kernzahl unten
gemessen wurde, und über alle ausgelieferten Basen sogar vollständiger
als die ursprüngliche Messung gegen nur Peters eigenen Bestand.

**Zwei Sackgassen der ursprünglichen Messung stecken jetzt als
Regressionstests im Modul selbst** (`tests/test_mod_knowledge.py`,
Gegenprobe gefahren): Slot-Tags statt Basis-Tags hätten lokale
Verteidigungs-Mods (Evasion/Armour/ES-%) verpasst; `domain: "item"`
statt `("item", "misc")` hätte normale Jewels komplett ausgelassen
(Jewels laufen unter `"misc"`) — beide Filter sind hier fest verdrahtet
und beide Gegenproben rissen den erwarteten Test.

**Kernzahl, validiert gegen das fertige Modul (nicht nur das
Mess-Skript):** 68,0 % von Peters 111.619 tier-fähigen Sichtungen haben
eine belegte Leiter (36,1 % der 2.144 Identität/Kategorie-Paare) — mehr
als die ursprünglichen 63,3 %, weil `build()` Tags aus ALLEN
ausgelieferten Basen zieht statt nur aus Peters eigenen. Die
verbleibenden Lücken (waffentyp-bedingte Jewel-Mods, Hybrid-ES/Armour,
Cluster-Jewels, Abyssal-Sockets) sind noch nicht angefasst.

`build()` liefert ein schreibgeschütztes `Knowledge`-Objekt
(`ladder(identity, category)`, `has(...)`), `get()` hält es als
Im-Speicher-Singleton — das Bauen liest und verarbeitet ~30 MB JSON,
das lohnt sich nicht bei jeder Abfrage neu.

**Das Laden ist verdrahtet, eine UI-Auswertung noch nicht.** Ein neuer
`FetchModKnowledgeJob` (`services/api_worker.py`) läuft — wie
`FetchPricesJob` — ohne Login und ohne GGGs Rate-Limit-Budget zu
berühren, deshalb weder in `_NEEDS_AUTH` noch von `_skip_read_only`
betroffen. `MainWindow` reiht ihn einmal pro Programmstart ein, direkt
nach `BootstrapJob` (Reihenfolge spielt hier anders als bei Bootstrap
keine Rolle — der Job hängt an nichts, was `_build_ui()` auslöst). Im
Worker-Thread ruft er `ensure_fresh()` (Download nur bei Bedarf) und
danach IMMER `get(rebuild=True)`: Selbst ein bereits frischer
Platten-Cache muss einmal pro Prozess aus JSON in Python-Objekte
geparst werden, das ist der eigentlich teure Teil, nicht der Download
selbst. Das Ergebnis (`Knowledge | None`) landet über das Signal
`mod_knowledge_loaded` in `MainWindow._mod_knowledge` — bisher nur
gespeichert und geloggt, von keiner UI-Stelle gelesen.

**`_cache_dir()` ist eine Funktion, keine Modul-Konstante** — dieselbe
Regel wie bei `cache_backup.directory()`: `config.APP_DATA_DIR` bei
Modul-Import einzufrieren hätte den Testschutz (`tests/conftest.py`
biegt `APP_DATA_DIR` pro Test auf ein Temp-Verzeichnis um) wirkungslos
gemacht. Aus demselben Grund patcht `conftest.py`s Autouse-Fixture
zusätzlich `mod_knowledge.fetch` auf einen Fehlschlag: Ohne diese Zeile
hätte JEDES `MainWindow()` in der Testsuite (der Cache in einem frischen
Temp-Verzeichnis ist nie "fresh") real gegen `repoe-fork.github.io`
abgerufen.

Dieser Abschnitt ist damit das FUNDAMENT samt Lade-Pipeline (Stufe 1
eines vierstufigen Plans — Album-Range gegen die echte Spanne, echte
T-Nummern statt Prozent, Geisterkarten für nie gesehene Mods), Stufe
2–4 (die eigentliche UI-Auswertung) stehen noch aus.

Getestet: `tests/test_mod_knowledge.py` (Download/Cache-Lebenszyklus
gegen gemocktes HTTP, Leiter-Bau gegen kleine RePoE-artige Fixtures,
beide Sackgassen der Messung als Regressionstest), `tests/
test_api_worker.py` (Dispatch ruft `ensure_fresh` dann `get(rebuild=
True)`, kein Status-Text, läuft ohne Token) und `tests/
test_main_window_helpers.py` (Job steht nach Bootstrap in der Queue,
`_on_mod_knowledge_loaded` speichert das Ergebnis inklusive `None`).

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
