Hier ist ein komplettes Architektur- und Projekt-Briefing für **"PoE-VIEW"**, speziell übersetzt in Python-Konzepte. Mit diesem Leitfaden kann ein Python-Entwickler sofort loslegen und die LabVIEW-Struktur in sauberen Python-Code überführen.

---

# Projekt-Briefing: PoE-VIEW (Python Edition)

**Projektziel:** Ein Community-Tool für *Path of Exile* (PoE), das über die offizielle GGG-API Accounts, Charaktere und Stash-Tabs ausliest, filtert und übersichtlich darstellt.

**Empfohlener Tech-Stack (Python):**

* **Netzwerk & API:** `httpx` (für asynchrones HTTP und Connection Pooling) oder `requests`.
* **GUI-Framework:** `PyQt6` / `PySide6` (ideal für komplexe Tree-Views und Tabellen) oder `CustomTkinter`.
* **Datenstrukturierung:** `pydantic` oder `dataclasses` für das komplexe JSON-Parsing.
* **Concurrency:** `asyncio` (empfohlen, da API-Calls und UI-Updates Hand in Hand gehen) oder `threading`.

---

### 1. Authentifizierung (OAuth2 mit PKCE)

GGG nutzt OAuth2 mit PKCE (Proof Key for Code Exchange).

* **Ablauf:** Der User klickt auf "Login" -> Python generiert einen `code_verifier` und `code_challenge` -> Öffnet den Browser zur GGG-Login-Seite.
* **Callback:** Du musst in Python einen temporären lokalen Webserver (z. B. via `http.server` oder ein winziges `FastAPI`/`Flask`-Skript auf `localhost:PORT`) starten, um den Redirect-Callback abzufangen und den `code` zu extrahieren.
* **Token-Tausch:** Den `code` gegen das Access-Token tauschen (10 Stunden gültig). Token lokal speichern (verschlüsselt oder im Keychain/Cred-Manager).

### 2. Netzwerk-Architektur

Um SSL-Handshakes zu minimieren (Performance!), nutze eine persistente Session.

* Erstelle eine globale Instanz von `httpx.AsyncClient()` oder `requests.Session()`.
* Setze die Standard-Header einmalig:
* `Authorization: Bearer <dein_token>`
* `User-Agent: PoE-VIEW (contact: deine@email.de)` *(Pflicht für die GGG-API!)*



### 3. Das Herzstück: Der Rate-Limit-Manager

GGG straft zu schnelle Anfragen sofort mit einem HTTP 429 (Too Many Requests) und Temporär-Banns ab. Dies ist die wichtigste Komponente des Projekts. In LabVIEW haben wir eine "Functional Global Variable" (FGV) genutzt. **In Python baust du hierfür eine Singleton-Klasse oder einen zentralen Async-Manager.**

**Die GGG-Header:**
GGG sendet drei Header, die geparst werden müssen:

* `X-Rate-Limit-Policy` (z.B. `stash-list-request-limit`)
* `X-Rate-Limit-Account` (Limit-Regeln, z.B. `10:15:60,30:60:300` -> `Max:Window:LockTime`)
* `X-Rate-Limit-Account-State` (Aktueller Verbrauch, z.B. `1:15:0,1:60:0` -> `Current:Window:CurrentLock`)

**Python-Implementierung (Logik):**

```python
class RateLimitManager:
    def __init__(self):
        self.states = {} # Speichert Limits und Timestamps pro Policy

    async def wait_if_needed(self, policy_name: str):
        # Wird VOR JEDEM API-Call aufgerufen!
        # Prüft in self.states, ob CurrentCount >= MaxRequests.
        # Wenn ja: berechne Wartezeit -> WindowSize - (CurrentTime - LastUpdate)
        # Blockiert asynchron: await asyncio.sleep(wait_time)
        pass

    def update_state(self, headers: dict):
        # Wird NACH JEDEM API-Call aufgerufen!
        # Parst die 3 X-Rate-Limit Header per Regex oder string.split(':')
        # Aktualisiert den Zähler und den Timestamp in self.states
        pass

```

### 4. Datenverarbeitung (JSON Parsing)

Die PoE-API-Responses sind tief verschachtelt.

* **Stash-Tree:** Stashes können Unterordner haben. Du erhältst ein JSON mit `stashes` und darin ggf. `children`. Eine rekursive Funktion ist nötig, um dies in ein UI-Element (wie `QTreeView`) zu mappen.
* **Items & Gems:** Die Item-Struktur liegt unter `stash -> items`.
* *Die Schwierigkeit:* Attribute wie "Level" oder "Quality" bei Gems haben keinen festen Key. Sie liegen in einem Array namens `properties`.
* *Lösung:* Eine Schleife über `item['properties']`, die nach `if prop['name'] == 'Level':` sucht und den Wert aus dem extrem verschachtelten Array `prop['values'][0][0]` extrahiert.


* **Icon-Caching:** Lade die Item-Icons (Bilder-URLs im JSON) via HTTP herunter und speichere sie lokal (z. B. im `.appdata`-Ordner). Prüfe vor jedem Download, ob das Icon (`z.B. Chaos_Orb.png`) schon existiert.

### 5. Das User Interface (UI)

Da der Rate-Limiter API-Calls oft für 10 bis 60 Sekunden pausieren muss, **darf die UI niemals blockieren**.

* Nutze strikte Trennung: UI im Main-Thread, API-Calls in Worker-Threads (`QThread`) oder asynchron (`asyncio` Event-Loop).
* **UI-Elemente:**
* *Linke Seite:* Ein Tree-Control für Stash-Tabs und Ordner. Bei Klick auf einen Tab -> Fetch Items.
* *Rechte Seite:* Eine Multi-Column Listbox / Table (z. B. `QTableView`), welche die Items/Gems anzeigt (inkl. Spalten für Level, Qualität, Typ und sortierbar).
* *Das Dashboard (Wichtig!):* Nutze Fortschrittsbalken (`QProgressBar`) im UI, die über Signale/Events vom `RateLimitManager` gefüttert werden. Sie zeigen dem User den Auslastungs-Status (z.B. "10/15 Requests verbraucht") an, damit er weiß, warum die App gerade wartet.



### 6. Security & Open-Source-Compliance

* Das **Client Secret** der OAuth2-App darf niemals hart im Python-Code (`.py`) stehen! Nutze eine `.env` Datei oder ein `config.json`, welches in der `.gitignore` steht.
* Weise in der Readme darauf hin, dass die User im Idealfall ihre eigene Client-ID von GGG generieren oder du stellst das Tool als registrierte public App zur Verfügung (dann gibt es kein Secret für Clients, sondern PKCE reicht).
* Baue einen Disclaimer ins UI: *"This tool is not affiliated with Grinding Gear Games."*

---

**Fazit für den Python-Dev:** Das Schwierigste an diesem Projekt ist nicht das Abrufen der Daten, sondern das korrekte Orchestrieren des asynchronen State-Managements für das Rate-Limiting und die saubere Extraktion der tief verschachtelten Item-Properties aus dem JSON. Mit `asyncio` und `pydantic` hast du in Python dafür aber die perfekten Werkzeuge zur Hand!