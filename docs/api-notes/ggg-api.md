# Notizen zur GGG-API

Diese Datei hält fest, wie sich die offizielle Path-of-Exile-API in der
Praxis verhält. Wo die offizielle Dokumentation von den tatsächlich
beobachteten Antworten abweicht, gilt das hier Dokumentierte: Alle
JSON-Strukturen unten stammen aus echten API-Antworten, nicht aus der
Doku.

Hier steht die **Form** der API. Wie sich Spiel und Server über die Zeit
verhalten — wann neue Daten überhaupt erscheinen, wie Erfahrung anfällt,
was die `Client.txt` hergibt — steht daneben in
[poe-verhalten.md](poe-verhalten.md). Die ist als einzige Datei des
Projekts auf Englisch (Peter, 2026-08-12): Sie richtet sich nicht nur an
uns, sondern an jeden, der gegen GGGs API entwickelt, und der
Forumsbeitrag verlinkt sie.

Basis-URL: `https://api.pathofexile.com`

## OAuth2 mit PKCE

| Parameter | Wert |
|---|---|
| Client-ID | `poeview` (registrierte public App, kein Client-Secret) |
| Redirect-URI | `http://localhost:64338/callback` (fester Port **64338**) |
| Scopes | `account:profile account:stashes account:characters account:leagues` |
| Authorize-URL | `https://www.pathofexile.com/oauth/authorize` |
| Token-URL | `https://www.pathofexile.com/oauth/token` |

**Authorize-Request** (Query-Parameter):

```
?client_id=<id>&response_type=code&scope=<scopes>&state=<hex16>
&redirect_uri=<uri>&code_challenge=<challenge>&code_challenge_method=S256
```

- `code_challenge` = Base64URL(SHA-256(code_verifier)).
- `state` = 64-Bit-Zufallszahl als `%016x`. Der Callback wird auf
  Gleichheit geprüft (CSRF-Schutz).

**Token-Request:** POST, `Content-Type: application/x-www-form-urlencoded`:

```
client_id=<id>&grant_type=authorization_code&code=<code>
&redirect_uri=<uri>&scope=<scopes>&code_verifier=<verifier>
```

Die Antwort enthält `expires_in: 36000`, das Access-Token gilt also
10 Stunden. Ein Refresh-Token liefert GGG für public clients nicht.

**Callback-Server:** lokaler `http.server` auf Port 64338, der eine
statische Erfolgsseite ausliefert und sich danach beendet. Browser fragen
oft zusätzlich `/favicon.ico` an, der Server muss also mehrere Requests
verkraften, bevor der eigentliche Callback eintrifft.

**User-Agent:** GGG schreibt das Format vor
(<https://www.pathofexile.com/developer/docs>):

```
OAuth {clientId}/{version} (contact: {contact})
```

Der Kontakt identifiziert die Anwendung, nicht den einzelnen Nutzer.
Details zur Handhabung im Projekt: ARCHITEKTUR.md §7.1.

## Endpunkte

| Endpunkt | Zweck | Methode im Client |
|---|---|---|
| `/profile` | Account-Profil | `get_profile()` |
| `/account/leagues` | Liga-Liste | `get_leagues()` |
| `/character` | Charakter-Liste (name, class, league, level) | `get_characters()` |
| `/character/<name>` | Ausrüstung + Inventar eines Charakters | `get_character_items(name)` |
| `/stash/<league>` | Stash-Tab-Liste einer Liga (ohne Items) | `get_stashes(league)` |
| `/stash/<league>/<stash_id>` | Items eines Tabs | `get_stash(league, stash_id)` |
| `/stash/<league>/<stash_id>/<substash_id>` | Items eines Spezial-Tab-Kinds | `get_stash(league, substash_id, parent_id=stash_id)` |

Liga-Namen enthalten Leerzeichen (`SSF Ruthless`), Pfadsegmente müssen
daher URL-encodiert werden (`urllib.parse.quote`).

## Spezial-Tabs: MapStash und UniqueStash

Diese Tabs antworten am Einzel-Tab-Endpunkt mit `children` statt `items`
(ein Unter-Tab pro Map-Sektion bzw. Unique-Kategorie). Items gibt es nur
über den Substash-Endpunkt mit beiden IDs im Pfad. Die Kinder erscheinen
nicht in der Liga-Stash-Liste, sondern existieren erst nach dem
Einzel-Abruf des Spezial-Tabs.

Beobachtete Kind-Strukturen:

```jsonc
// MapStash-Kind (aktive Liga): name="1" ist wertlos, der echte Name steht
// in metadata.map.name, der Tier ist Teil des Namens (kein tier-Feld).
{ "id": "4917132724", "name": "1", "type": "MapStash", "index": null,
  "parent": "911e88f182", "folder": null,
  "metadata": { "items": 8,
                "map": { "section": "tier6", "name": "Map (Tier 6)", "index": 0 } },
  "children": [], "items": [] }

// MapStash-Kind einer Remove-only-Liga: name ist nur das Suffix
// " (Remove-only)" mit führendem Leerzeichen, gehört an map.name angehängt.
// map.section: "tier1"…"tier16", "unique", "special".
{ "name": " (Remove-only)",
  "metadata": { "items": 2,
                "map": { "section": "unique", "name": "Death and Taxes", "index": 0 } } }

// UniqueStash-Kind: namenlos, nur die Item-Anzahl.
{ "id": "deecbe452b", "name": "", "type": "UniqueStash", "index": null,
  "parent": "5859dab84a", "folder": null,
  "metadata": { "items": 5 }, "children": [], "items": [] }
```

Weitere Beobachtungen: `metadata.items` nennt die Item-Anzahl je Kind,
ersetzt aber keinen Substash-Abruf. Der MapStash-Eltern-Tab trägt
`metadata.map.series` (Stash-Serie der Liga). `parent` ist bei Kindern
zuverlässig gefüllt.

## Stash-Liste

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

- `metadata.colour` ist Hex **ohne** `#`-Präfix.
- Kind-Tabs tragen ein `folder`-Feld mit der ID des Eltern-Ordners.
- **Ordner-Inhalte kommen in der Praxis FLACH**, nicht wie oben verschachtelt:
  jedes Mitglied steht als eigener Eintrag auf oberster Ebene, erkennbar nur
  am gesetzten `folder`, während das `children`-Feld des Ordners leer bleibt.
  In der echten Standard-Liga (2026-07) waren 121 der 165 Einträge der
  obersten Ebene solche Ordner-Mitglieder. Beide Formen müssen unterstützt
  werden, siehe `MainWindow._nest_folder_members` und FALLSTRICKE #38.
- Der `index` eines Ordner-Mitglieds setzt die Zählung seines Ordners fort
  (Ordner "Special" idx=11 → Mitglieder 12–24) und **überschneidet sich mit
  denen anderer Ordner** ("M\*" idx=12 → Mitglieder 13–17). Ordnet man die
  flache Liste nach `index`, landen fremde Ordner mitten in den Mitgliedern
  eines anderen.
- Beobachtete Typen: `Folder`, `QuadStash`, `CurrencyStash`, `MapStash`,
  `UniqueStash`, `GemStash`. Das Datenmodell hält `type` bewusst als
  freien String, nicht als Enum.
- `index` ist **nicht** als stabile Tab-Nummer verwendbar, siehe
  FALLSTRICKE_UND_WORKAROUNDS.md #21.

## Einzel-Tab

Antwort-Key ist `stash` (Singular). Spezial-Tabs tragen zusätzlich
`metadata.layout`, das für die Anzeige ohne Bedeutung ist.

```jsonc
{ "stash": { "id": "bc9b09a3d3", "folder": "14a377d1b7", "name": "Gems",
             "type": "GemStash", "index": 11,
             "metadata": { "colour": "590000", "layout": { "...": "..." } },
             "items": [ "..." ] } }
```

## Items

Mehrere Felder verhalten sich anders, als die Doku nahelegt:

- **Level und Quality** haben keine festen Keys, sondern liegen als
  Einträge im `properties`-Array. Der Wert steckt in `values[0][0]`.
- **Map-Attribute** (Item Quantity, Item Rarity, Pack Size, Map Drop
  Chance) stehen ebenfalls in `properties`, nicht in `explicitMods`.
- **Anforderungen** (Level, Str, Dex, Int) liegen im `requirements`-Array.
  Attributnamen kommen sowohl kurz (`Str`) als auch lang (`Strength`) vor.
  Heist-Ausrüstung trägt zusätzlich einen Eintrag `Level {0} in {1}`, der
  ein Job-Level meint und kein Charakter-Level.
- **`explicitMods`/`implicitMods`** enthalten überwiegend Strings, bei
  manchen Items aber Objekte der Form `{"description": "..."}`, siehe
  FALLSTRICKE_UND_WORKAROUNDS.md #25.
- **`x`/`y`** geben die Gitterposition innerhalb des Tabs an.
- **`inventoryId`** nennt bei Charakter-Items den Ausrüstungsslot
  (`Weapon`, `BodyArmour`, `MainInventory`, …).
