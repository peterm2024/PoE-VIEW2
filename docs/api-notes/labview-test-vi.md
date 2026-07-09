# Erkenntnisse aus dem LabVIEW-Test-VI (PoE-VIEW)

**Quelle:** Blockdiagramm-Snippet des Test-VIs, 2026-07-09.
Diese Werte sind im LabVIEW-Original erprobt und werden für PoE-VIEW2
unverändert übernommen — sie sind die "Ground Truth" für die Portierung.

## OAuth2-Konfiguration (erprobt & funktionierend)

| Parameter | Wert |
|---|---|
| Client-ID | `poeview` (registrierte public App, kein Client-Secret → PKCE) |
| Redirect-URI | `http://localhost:64338/callback` (fester Port **64338**) |
| Scopes | `account:profile account:stashes account:characters account:leagues` |
| Authorize-URL | `https://www.pathofexile.com/oauth/authorize` |
| Token-URL | `https://www.pathofexile.com/oauth/token` |

**Authorize-Request** (Query-Parameter, wie im VI formatiert):

```
?client_id=<id>&response_type=code&scope=<scopes>&state=<hex16>
&redirect_uri=<uri>&code_challenge=<challenge>&code_challenge_method=S256
```

- `code_challenge` = Base64URL(SHA-256(code_verifier)) — im VI: SHA256-Block → Base64URL.
- `state` = 64-Bit-Zufallszahl, formatiert als `%016x`. Der Callback wird auf
  `state=`-Gleichheit geprüft ("State OK?") → **übernehmen wir** (CSRF-Schutz).

**Token-Request:** POST, `Content-Type: application/x-www-form-urlencoded`, Body:

```
client_id=<id>&grant_type=authorization_code&code=<code>
&redirect_uri=<uri>&scope=<scopes>&code_verifier=<verifier>
```

**Callback-Server:** In LabVIEW ein roher TCP-Listener auf Port 64338, der eine
statische HTML-Erfolgsseite zurückgibt ("Erfolg! PoE-VIEW hat den Code
empfangen. Du kannst dieses Fenster jetzt schliessen."). In Python:
`http.server` mit derselben Erfolgsseite (deutsch), ein Request, dann beenden.

**User-Agent:** Im VI `PoE-VIEW (Contact: <kontakt-e-mail>)` (API-Calls) bzw.
`PoE_VIEW 0.1` (Token-Request — inkonsistent). Für Python vereinheitlichen wir
auf das von GGG empfohlene Format:
`OAuth poeview/0.1 (contact: <kontakt-e-mail>)` — für **alle** Requests.
Die Kontakt-E-Mail steht ausschließlich in der lokalen `.env`
(`POE_CONTACT_EMAIL`), nie im Repository.

## Genutzte API-Endpunkte

Basis: `https://api.pathofexile.com`

| Endpunkt | Zweck | Python-Methode |
|---|---|---|
| `/profile` | Account-Profil | `get_profile()` |
| `/account/leagues` | Liga-Liste (für das Liga-Dropdown) | `get_leagues()` |
| `/character` | Charakter-Liste → name, class, league, level | `get_characters()` |
| `/stash/<league>` | Stash-Tab-Liste einer Liga | `get_stashes(league)` |
| `/stash/<league>/<stash_id>` | Items eines Tabs (Spezial-Tabs: children!) | `get_stash(league, stash_id)` |
| `/stash/<league>/<stash_id>/<substash_id>` | Items eines Spezial-Tab-Kinds | `get_stash(league, substash_id, parent_id=stash_id)` |

⚠️ **Spezial-Tabs (`MapStash`, `UniqueStash`)** antworten am Einzel-Tab-
Endpunkt mit `children` statt `items` (ein Unter-Tab pro Map-Typ bzw.
Unique-Kategorie; Map-Kinder oft ohne `name`, Anzeigename steckt in
`metadata.map` → `{name, tier, …}`). Items gibt es nur über den
Substash-Endpunkt mit BEIDEN IDs im Pfad. Diese Kinder erscheinen NICHT
in der Liga-Stash-Liste — sie existieren erst nach dem Einzel-Abruf des
Spezial-Tabs (Quelle: offizielle GGG-API-Doku; im LabVIEW-Test-VI noch
nicht abgedeckt).

⚠️ **Liga-Namen enthalten Leerzeichen** (z. B. `SSF Ruthless`) — in Python die
Pfadsegmente **URL-encoden** (`urllib.parse.quote`). Das LabVIEW-VI hängt den
Namen roh an die URL; das sollte auch dort noch abgesichert werden.

## Beobachtete JSON-Strukturen (Liga „SSF Ruthless")

**Stash-Liste** (`/stash/<league>`) — bestätigt das rekursive Ordner-Modell:

```jsonc
{ "stashes": [
    { "id": "34e9c51d50", "name": "#", "type": "QuadStash", "index": 0,
      "metadata": { "colour": "cc009a" } },
    { "id": "7dd8293e2a", "name": "Map", "type": "Folder", "index": 1,
      "metadata": { "folder": true, "colour": "7c5436" },
      "children": [
        { "id": "5980220058", "folder": "7dd8293e2a", "name": "$",
          "type": "CurrencyStash", "index": 2, "metadata": { "colour": "ffaa00" } },
        { "id": "911e88f182", "folder": "7dd8293e2a", "name": "M",
          "type": "MapStash", "index": 3, "metadata": { "colour": "888888" } }
      ] }
] }
```

Erkenntnisse fürs Datenmodell:

- `metadata.colour` ist Hex **ohne** `#`-Präfix (LabVIEW: → U32; Python: `QColor("#"+colour)`).
- Kind-Tabs tragen ein `folder`-Feld mit der ID des Eltern-Ordners.
- Beobachtete Tab-Typen: `Folder`, `QuadStash`, `CurrencyStash`, `MapStash`,
  `UniqueStash`, `GemStash` (Modell offen halten: `type: str`, kein Enum-Zwang).

**Einzel-Tab** (`/stash/<league>/<id>`, hier ein GemStash) — Antwort ist ein
`stash`-Objekt (Singular!), Spezial-Tabs haben zusätzliches `metadata.layout`
(Filter/Sektionen), das wir für die Anzeige ignorieren können:

```jsonc
{ "stash": { "id": "bc9b09a3d3", "folder": "14a377d1b7", "name": "Gems",
             "type": "GemStash", "index": 11,
             "metadata": { "colour": "590000", "layout": { "...": "..." } },
             "items": [ "..." ] } }
```

## Übernahme-Checkliste für den Python-Port

- [x] Client-ID, Port, Scopes, URLs → `config.py` / `.env.example`
- [x] `state`-Prüfung in den PKCE-Flow (war im Architektur-Entwurf noch nicht drin)
- [x] `get_leagues()` als Endpunkt ergänzt (Liga-Dropdown)
- [x] URL-Encoding für Liga-Namen
- [ ] Echte API-Antworten als Test-Fixtures speichern (`tests/fixtures/`),
      sobald der Client steht — die obigen Strukturen dienen bis dahin als Referenz.
