# Beobachtetes Verhalten von Path of Exile

Diese Datei sammelt, wie sich **Spiel und Server über die Zeit** verhalten
— nicht, wie die API aufgebaut ist (das steht in
[ggg-api.md](ggg-api.md)), und nicht, warum PoE-VIEW2 etwas so löst wie es
das tut (das steht in [ARCHITEKTUR.md](../ARCHITEKTUR.md)).

**Warum getrennt?** Weil diese Klasse Wissen anders altert und anders
belegt wird. Eine JSON-Struktur sieht man einmal und weiß sie. Ob GGG die
Erfahrung eines Charakters sofort oder erst beim Zonenwechsel
veröffentlicht, lässt sich nur über Stunden messen — und wer es nicht
nachgemessen hat, rät. Beim Bau der XP/h-Anzeige sind daraus an einem
einzigen Abend drei falsche Annahmen entstanden, jede davon plausibel
(§ *Widerlegtes*).

**Regeln für Einträge hier:**

1. Nur Beobachtetes. Jeder Eintrag nennt, **woran** er gemessen wurde.
2. Was nicht bestätigt werden konnte, steht unter *Unbestätigtes* —
   nicht weglassen, sonst wird es beim nächsten Mal wieder vermutet.
3. Was sich als falsch herausgestellt hat, steht unter *Widerlegtes* und
   wird nicht gelöscht. Eine plausible falsche Annahme kommt sonst
   zurück.
4. Zahlen mit Datum. Ein Verhalten kann sich mit einer Liga ändern.

Messwerkzeuge, mit denen das hier entstanden ist: PoEs eigene
`Client.txt` (Zonenwechsel, Handel, Identifizieren), das Programm-Log
(`%LOCALAPPDATA%\PoE-VIEW2\logs\poe-view2.log`, seit 2026-08-11 mit einer
Zeile je Erfahrungs-Veröffentlichung) und die Gem-XP-Mitschrift
(ARCHITEKTUR.md §4.35).

---

## 1. Wann liefert die API neue Daten?

**Die API zeigt neue Daten praktisch nur nach einem Zonenwechsel.**
Häufiger zu fragen bringt nichts — in einem Fenster von 27 Minuten ohne
Zonenwechsel hat PoE-VIEW2 rund hundert Mal gefragt und **einmal** etwas
Neues bekommen (2026-08-10).

Über 91 protokollierte Inventar-Änderungen (2026-08-07 bis -10):

| Abstand zum letzten Zonenwechsel | Anteil |
|---|---|
| 0–5 s | 62 % |
| 6–30 s | 1 % |
| 31–120 s | 12 % |
| 2–10 min | 20 % |
| über 10 min | 5 % |

Die späten Fälle sind echte Nachzügler: Der Server veröffentlicht
irgendwann auch ohne Zonenwechsel, aber unvorhersehbar (einmal +26 Items
nach 1803 Sekunden und 113 Abrufen).

**Erfahrung erscheint erst, wenn eine Zone verlassen wird.** In allen
bisher protokollierten Fällen fiel eine Erfahrungs-Veröffentlichung 1–3
Sekunden nach einem Zonenwechsel an. Wer wissen will, wie viel Erfahrung
in der laufenden Map schon verdient wurde, kann das über die API nicht
erfahren — die Zahl existiert außerhalb des Spiels erst danach.

**Eine Zone ohne Zuwachs erzeugt gar keine Veröffentlichung.** Der
Zonenwechsel vom Hideout in eine Map ändert die Erfahrung nicht, also
gibt es nichts zu melden. Praktische Folge: Jede
Erfahrungs-Veröffentlichung gehört zu genau einer Zone, in der etwas
passiert ist — nämlich der gerade verlassenen.

### Der Azurite Mine (Delve) ist ein blinder Fleck

Die Fahrt zurück zum Händler im Delve erzeugt **keinen** Eintrag in der
`Client.txt`. Gemessen am 2026-08-10: zwischen 21:21:41 und 21:49:26
steht dort 27 Minuten lang keine einzige `You have entered`-Zeile,
obwohl in der Zeit acht Händler-Ereignisse anfielen. Wer den
Zonenwechsel als einzigen Auslöser benutzt, ist dort blind.

Der blinde Fleck betrifft aber **nur den Händler-Bereich**: Ein Port
innerhalb der Mine schreibt sehr wohl `You have entered Azurite Mine`
und löst damit alles Weitere aus (2026-08-11, 22:59:11 — neue Daten
0,3 Sekunden später).

### Händler: Identifizieren und Verkaufen verhalten sich unterschiedlich

| Ereignis | Neue Daten verfügbar |
|---|---|
| `N Items identified` | teils **sofort** (0,4 s gemessen), teils erst später |
| `Trade accepted` | nie sofort; gemessen 17 s, 32 s, 57 s oder erst beim nächsten Zonenwechsel |

Zwei Volltreffer am 2026-08-10: Nach `12 Items identified` (22:54:30) und
`4 Items identified` (23:00:04) lagen die neuen Daten jeweils 0,4
Sekunden später vor — nachdem davor 35 bzw. 9 Abrufe vergeblich
gewesen waren.

---

## 2. Die `Client.txt` als Ereignisquelle

Reines Lesen dieser Textdatei ist von GGG erlaubt (anders als
Speicherzugriffe auf den laufenden Client — die wären ein Bann-Risiko und
kommen nicht in Frage).

Ausgezählt in einer echten Datei mit 81.639 Zeilen (2026-08-10):

| Zeile | Häufigkeit | Bedeutung |
|---|---|---|
| `: You have entered <Zone>.` | 3829 | Zonenwechsel |
| `: Trade accepted.` | 1028 | Verkauf an NPC **und** Spielerhandel |
| `: N Items identified` | 821 | Mehrzahl |
| `: 1 Item identified` | 78 | eigene Schreibweise, leicht zu übersehen |
| `: Trade cancelled.` | 60 | nichts geändert |
| `: You have killed N.N monsters.` | 204 | |
| `: You have received an Atlas Skill Point.` | 146 | |
| `: <Charakter> (<Klasse>) is now level N` | mehrfach | Stufenaufstieg |
| `: Reached level N in H:MM:SS` | 73 | mit Spielzeit |
| `: You have received a Passive Skill Point.` | 41 | |
| `: Your Stash Tab with the Unique Affinity does not have enough space for this item.` | 31 | |
| `: Item on cursor destroyed.` | 27 | |

Format einer Zeile:
`2026/08/01 21:44:37 15181671 cffb0658 [INFO Client 18604] : You have entered The Coast.`

Nicht in der Datei: irgendetwas über Erfahrungspunkte unterhalb eines
Stufenaufstiegs, Beute, Währung oder den Inhalt der Truhe.

---

## 3. Erfahrung des Charakters

- `character.experience` ist die **kumulierte Gesamterfahrung**, nicht
  der Fortschritt innerhalb der Stufe. Beobachtete Größenordnungen:
  Stufe 87 ≈ 1,63 Mrd., Stufe 89 ≈ 1,80 Mrd.
- Sie kommt **in Schüben**: In einer Spielstunde (231 Messpunkte,
  2026-08-10) hatten nur **8 von 230** Messschritten überhaupt einen
  Zuwachs, mit Abständen von anderthalb bis siebzehn Minuten.
- Größenordnung bei einem eingespielten Charakter auf Stufe 89:
  40–163 Mio. XP/h je nach Zone, gemessen über die Verweildauer in der
  jeweiligen Zone (2026-08-11). Ein Trial oder ein kurzer Stadtlauf liegt
  deutlich unter einer vollen Map.

---

## 4. Sockel-Gems

**Alle gesockelten Gems bekommen exakt denselben Zuwachs.** Über eine
Spielstunde und acht Veröffentlichungen hinweg war der Zuwachs bei jedem
aktiven Gem auf die Einheit gleich (12.187.472 XP, 2026-08-10). Ein
einzelnes Gem taugt damit als Stellvertreter für alle — solange es
durchgehend gesockelt und nicht am Anschlag ist.

**Auch die Gems im Wechsel-Waffenset.** Gegengemessen über 21
Veröffentlichungen (2026-08-11): Jedes durchgehend gesockelte Gem stand
bei 33.501.737 XP Zuwachs — die in `Weapon2` und `Offhand2` genauso wie
die im aktiven Set. Die naheliegende Gegenvermutung ("das inaktive Set
geht leer aus") ist damit erledigt.

Unterschiedliche **Stände** kommen allein aus der Vorgeschichte:

- Ein **ausgesockeltes** Gem bekommt nichts. `Summon Skitterbots` war
  zehn Minuten draußen und fehlten danach exakt die 1.066.352 XP des
  einen Schubs in diesem Fenster.
- Ein **frisch gesockeltes** Gem bekommt nur so viel, wie bis zu seiner
  Obergrenze passt. `Ice Nova`, neu eingesetzt, nahm von einem Schub über
  1.066.352 nur 147.967 auf.

**Gems steigen nicht von selbst auf.** Voller Erfahrungsbalken heißt
"wartet auf den Klick", und bis dahin ist die Erfahrung eingefroren. So
hält man Gems absichtlich auf Stufe 1.

**Felder eines Sockel-Gems** (roh, kein eigenes Pydantic-Modell):

- `additionalProperties` → Eintrag `Experience` mit
  `values[0][0] = "66921722/212046017"` und `progress` (0…1).
- `nextLevelRequirements` erscheint **nur**, wenn der Balken voll ist,
  und nennt die Anforderungen der nächsten Stufe — **unabhängig davon,
  ob sie erfüllt sind**. Das Feld allein sagt also nicht, ob ein Gem
  festhängt.
- `requirements` nennt die Anforderungen der **aktuellen** Stufe.
- `properties` → `Level`, `Quality` (wie bei Items, `values[0][0]`).

**Ob ein Gem wirklich blockiert ist, lässt sich nur über die Attribute
entscheiden** — und die liefert der Charakter-Endpunkt nicht. Was hilft:
Was der Charakter TRÄGT, erfüllt er zwingend, also ergeben die
`requirements` der angelegten Ausrüstung eine sichere Untergrenze. Diese
beweist "erfüllt", niemals "nicht erfüllt" — an einem echten Charakter
lagen die Untergrenzen bei Str ≥ 151 / Int ≥ 131 / Dex ≥ 108, die
tatsächlichen Werte bei 280 / 145 / 114 (Passivbaum und Juwelen).

Ein real beobachteter Blockade-Fall (2026-08-11): Ein Vaal Blade Vortex
auf Stufe 12 verlangt für die nächste Stufe `Level 53; Dex 119` bei
tatsächlichen 114 Dex.

---

## 5. Items

- **Die Erfahrung der Sockel-Gems ist Teil der Item-Daten.** Ein
  sockelbares Ausrüstungsteil sieht deshalb beim Spielen bei fast jedem
  Abruf "verändert" aus: Zwischen zwei nur zwölf Sekunden
  auseinanderliegenden Abrufen hatten 25 von 29 Gems neue Werte. Wer
  Items vergleicht, um Änderungen anzuzeigen, muss die Erfahrung vorher
  herausrechnen.
- **Item-IDs bleiben stabil**, auch über Zonenwechsel hinweg — eine
  naheliegende Gegenvermutung, die sich an den Logs widerlegen ließ.
- **Die `requirements` eines Items sind das Maximum über das Item selbst
  und seine Sockel-Gems.** Einträge, die von den Gems stammen, tragen
  `"suffix": "(gem)"`. Beispiel (2026-08-11): eine Wand mit
  `Level 68 (gem) / Str 66 (gem) / Dex 87 (gem) / Int 95 (gem)` — jede
  Zahl der Höchstwert der drei Gems darin; ein Sceptre daneben zeigt
  `Str 95` und `Int 131` **ohne** Suffix, das ist die Waffe selbst.
  Folge: Ein Gem-Aufstieg ändert nicht nur `socketedItems`, sondern
  gegebenenfalls auch die `requirements` des tragenden Items.
- **Flaschen ändern sich beim Spielen dauernd.** In `properties` steht
  `Currently has {0} Charges`; der Wert wandert mit jeder Benutzung. Ein
  Item-Vergleich hält Flaschen deshalb regelmäßig für "geändert"
  (viermal an einem Abend, 2026-08-11) — dieselbe Sorte Rauschen wie die
  Gem-Erfahrung, nur seltener.
- **Angelegte Ausrüstung ändert sich sonst gar nicht.** Über zwanzig
  Minuten Spielzeit wiesen Ringe, Amulett und Gürtel kein einziges
  abweichendes Feld auf.

---

## 6. Unbestätigtes

Hier steht, was gesucht und **nicht** gefunden wurde. Nicht als
"existiert nicht" lesen, sondern als "mit diesen Mitteln nicht
nachweisbar".

- **Ein Schalter, der den Erfahrungsgewinn eines Gems abschaltet.**
  Weder in den Rohdaten noch in der öffentlichen Dokumentation zu
  finden. Was danach aussieht, erklärt sich vollständig durch die beiden
  bekannten Fälle: Gem ausgesockelt, oder Balken voll und nicht
  geklickt.
- **Die genaue Formel für die Erfahrungsstrafe** nach Charakterstufe und
  Zonenstufe. Bekannt ist, dass es sie gibt; die Zahlen wurden nicht
  nachgemessen und deshalb nirgends implementiert.
- **Erfahrungsverlust beim Tod ab Akt 5.** Allgemein bekannt, in unseren
  eigenen Daten aber nie beobachtet. Die Auswertung ist darauf
  vorbereitet (ein Rückgang zählt als normale Änderung), belegt ist er
  nicht.

---

## 7. Widerlegtes

Plausible Annahmen, die sich als falsch erwiesen haben. Sie stehen hier,
damit sie nicht zurückkommen.

- **"GGG vergibt Ausrüstung bei Zonenwechseln neue Item-IDs."** Wäre die
  bequemste Erklärung für fälschlich als neu erkannte Items gewesen. In
  den Logs kommt das dafür nötige Muster (gleichzeitiger Zu- und Abgang
  derselben Größenordnung) kein einziges Mal vor.
- **"Die Reihenfolge von `socketedItems` ist zwischen zwei Abrufen
  instabil."** Klang zwingend, weil Pydantics Listenvergleich darauf
  anspringt. Über 47 aufeinanderfolgende Messpunkte war die Reihenfolge
  **ausnahmslos** stabil. Die echte Ursache war die Gem-Erfahrung.
- **"Gems bekommen unterschiedlich viel Erfahrung, je nachdem wie oft
  der Skill benutzt wird."** Aus einem einzelnen Snapshot geschlossen, in
  dem die Gems sehr unterschiedliche Stände hatten. Ein Snapshot zeigt
  aber Bestände, und die Frage war eine nach Zuwächsen — die sind
  identisch.
- **"Wenn nach dem Herausrechnen der Gem-Erfahrung immer noch
  Ausrüstung türkis leuchtet, ist ein Rest des Fehlers übrig."** Am
  2026-08-11 leuchteten Waffe und Schildhand als einzige angelegte
  Teile. Der Abgleich jeder einzelnen Markierung des Abends mit der
  Gem-Mitschrift ergab: **alle** gingen auf einen echten
  Gem-Stufenaufstieg oder einen Sockelwechsel zurück. Frisch
  eingesockelte Gems auf niedriger Stufe steigen im Minutentakt auf und
  lassen ihr Item dadurch bei fast jedem Zonenwechsel aufleuchten — das
  sieht aus wie der alte Fehler, ist aber die richtige Anzeige.
- **"Beim Veröffentlichen steht der Charakter in der Zone, in die er
  gerade zurückgekehrt ist."** Meist ja, aber nicht immer: Die
  Veröffentlichung kann eintreffen, wenn er längst in der nächsten Zone
  ist. Wer darauf eine Zeitmessung stützt, bekommt Nenner von wenigen
  Sekunden und Raten im Milliardenbereich.

---

## 8. Was PoE-VIEW2 daraus macht

Nur als Wegweiser — die Begründungen stehen jeweils dort:

| Beobachtung | Umsetzung |
|---|---|
| Daten kommen beim Zonenwechsel | Zonen-Beobachter, ARCHITEKTUR.md §ZoneWatcher |
| Delve ist blind, Händler veröffentlicht | Händler-Trigger, §4.36 |
| Gem-Erfahrung steckt in den Item-Daten | `_stable_item_dump`, §4.33 |
| Flaschen-Ladungen schwanken dauernd | `_VOLATILE_ITEM_PROPERTIES`, §4.33 |
| Ein Gem-Aufstieg ändert das ganze Item | grüne Hervorhebung, §4.33 |
| Erfahrung kommt in Schüben, Zone für Zone | XP/h über die Verweildauer, §4.34 |
| Gem-Zustände, Attribut-Untergrenze | Gem-Mitschrift, §4.35 |
