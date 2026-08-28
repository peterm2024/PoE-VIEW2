# Changelog

Alle nennenswerten Änderungen an PoE-VIEW2. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.0.0/), Versionierung
nach [SemVer](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Neu

- **Mod-Sammlung**: Jede Mod-Zeile, die durch die Truhe geht, wird
  aufgeschrieben — wie oft gesehen, wie hoch und wie niedrig gerollt, auf
  welchen Item-Stufen, getrennt nach Rarität. Die Sammlung füllt sich beim
  ersten Start aus dem vorhandenen Cache (bei einem gewachsenen Bestand
  rund 6000 verschiedene Mods) und wächst danach nebenbei weiter, ohne
  einen einzigen zusätzlichen Abruf. Sie sagt, was DU gesehen hast — nicht,
  was das Spiel erlaubt. Weil sich Mod-Werte von Liga zu Liga ändern,
  bekommt jede temporäre Liga ihren eigenen Topf; Standard und die übrigen
  dauerhaften Ligen teilen sich einen, denn dort liegen Items aus jeder je
  gespielten Liga nebeneinander.

- **Ein Balken vor jeder Mod-Zeile** zeigt, wo dieser Roll zwischen dem
  schlechtesten und dem besten liegt, den du von diesem Mod je gesehen
  hast. Voll heißt "der beste, den ich kenne", leer "der schlechteste" —
  und beide Enden sind genau: Ein Roll knapp unter dem Rekord füllt den
  Balken nicht ganz. Gedämpft bedeutet, dass für den Vergleich der
  Altbestand herhalten musste, weil die Liga des Items noch zu wenige
  Sichtungen hat. Kein Balken heißt, dass es nichts zu vergleichen gibt:
  Der Mod hat bisher nur einen einzigen Wert gezeigt oder weniger als fünf
  Sichtungen. ✦ steht weiterhin vor einem Mod, der zum ersten Mal
  auftaucht.

- **Tier-Bänder als Tabelle mit Zählungen**: Der Steckbrief eines Mods
  zeigt je abgeleitetem Band eine Zeile — wie oft gesehen, Wert-Spanne,
  Item-Stufen. Die Bänder heißen vorerst Prozent der gesehenen Spanne
  (z. B. "0–14 %") statt Tier-Nummern: Nummern wären mit den
  Ingame-Tiers verwechselbar, solange die Leiter unvollständig ist.
  Dafür führt die Sammlung jetzt je Mod-Wert Buch (Sichtungen und
  Item-Stufen je Wert statt nur der besten Belege); der Umbau trägt
  sich beim nächsten Start selbst aus dem Cache nach, ohne einen
  Zählstand anzufassen (Datei wächst um ~0,7 MB).

- **Das Album öffnet jetzt als Kartenansicht**: jede Mod-Identität eine
  Sammelkarte mit Name, Range und Sichtungszahl. Ein goldener Rand
  markiert Einzelstücke (nur einmal je gesehen), ✦ die Funde dieser
  Sitzung. Sortierbar nach Name, Neuzugängen, Häufigkeit oder
  "Einzelstücke zuerst" — Neuzugänge tragen dafür ab jetzt ihr
  Eintragsdatum (der Altbestand bleibt undatiert, ein erfundenes Datum
  wäre schlimmer als keines). Solange nichts gewählt ist, zeigt das
  Detail-Feld den Stand der Sammlung: Gesamtzahl, Einzelstücke, Funde
  der Sitzung, jüngster Fund. "Show table" schaltet zur bisherigen
  sortierbaren Tabelle um; Suche und Filter wirken in beiden Ansichten.

- **Ein Album zum Durchblättern der Mod-Sammlung** (neuer
  Werkzeugleisten-Knopf "📚 Mods"): durchsuchbar nach Text, Art (Explicit,
  Implicit, Enchant, Flask, …), Liga und Rarität, mit einer eigenen
  Range-Spalte (kleinster bis größter je gesehener Wert über die gerade
  ausgewählten Ligen/Raritäten) und dem vollen Steckbrief eines
  markierten Eintrags — jede Liga und Rarität, in der er je auftauchte,
  mit Sichtungszahl, Wertspanne und Item-Stufen. Die Rarität lässt sich
  zusätzlich auf "Corrupted" eingrenzen: Ein corrupted Item zählt jetzt
  in einem eigenen Topf, getrennt von einem gewöhnlichen derselben
  Rarität — manche Corruption-Ergebnisse rollen aus einer ganz anderen
  Tabelle (nur für neu hinzukommende Beobachtungen, Altbestand bleibt
  gemischt).

- **Vermutete Tier-Bänder** im Steckbrief des Albums, abgeleitet aus dem
  Item-Level: Ein Tier kann unterhalb seiner Freischaltung nicht
  auftreten, also verrät das niedrigste Item-Level, auf dem ein Wert je
  auftauchte, wo die Grenzen liegen. Obergrenzen sind belegt,
  Untergrenzen erschlossen — beides steht so im Fenster. Wo die Belege
  nichts hergeben, steht der Grund statt einer geratenen Leiter; bei
  einem reinen Endgame-Bestand ist das der Normalfall, weil ab
  Item-Level 75 fast alle Tiers verfügbar sind und sich nichts mehr
  trennen lässt. Scharf werden die Bänder, wenn man eine Liga von unten
  hochspielt.

- **Fundament einer echten Mod-Datenbank** (noch ohne sichtbare
  Auswertung): PoE-VIEW2 lädt jetzt bei jedem Start im Hintergrund
  öffentliche Spieldaten (RePoE) und baut daraus echte Tier-Leitern,
  statt sie nur aus dem Item-Level zu schätzen. Gegen einen echten,
  gewachsenen Bestand geprüft: 81 % aller bisher aufgezeichneten,
  tier-fähigen Sichtungen haben bereits eine belegte Leiter, und für
  Intelligenz auf Amuletten stimmen alle neun Stufen samt ihrer
  Freischalt-Level mit den bekannten Tabellen überein. Die Spieldaten selbst
  gehören GGG und werden deshalb nicht mit der App ausgeliefert,
  sondern bei Bedarf heruntergeladen und lokal vorgehalten, ähnlich dem
  bestehenden Preis-Cache — unabhängig vom Login, unauffällig, ohne
  eigene Anzeige.

- **Echte Tier-Leitern im Album.** Der Steckbrief eines Mods zeigt jetzt
  jede Stufe, die das Spiel für ihn kennt: T1 oben, mit dem Item-Level,
  ab dem sie überhaupt fallen kann, wie oft du sie gesehen hast und
  deinem besten Roll. **Die Stufen, die du noch nie gerollt hast, stehen
  mit da und bleiben leer** — das sind die Lücken im Album, und darunter
  steht, wie viele es sind ("6 of 8 tiers collected"). Ein Roll, der zu
  keiner Stufe gehört, bekommt eine eigene Zeile: Gecraftetes, mit
  Essenz Gerolltes und Beeinflusstes würfelt aus eigenen Tabellen. Für
  Mods, deren Leiter (noch) nicht bekannt ist, bleibt es bei den aus dem
  Item-Level geschätzten Prozent-Bändern, ausdrücklich als solche
  beschriftet. Die Range-Spalte in Tabelle und Karten zeigt den Zähler
  gleich mit; sie tritt zurück, sobald nach Liga oder Rarität gefiltert
  wird, weil der Tier-Stand über alle Ligen hinweg geführt wird.

- **Das Album sieht jetzt nach Sammelalbum aus.** Jede Karte trägt einen
  Farbstreifen und ein Symbol für ihr Thema — Feuer rot, Blitz gelb,
  Kälte blau, Chaos grün, wie im Spiel. Unter der Wertspanne sitzt eine
  Reihe kleiner Kästchen, eines je Tier: gefüllt heißt gerollt, ein
  leerer Umriss ist eine Lücke im Album. Komplette Sets bekommen einen
  goldenen Rahmen mit Häkchen; der Rahmen der Einzelstücke ist dafür von
  Gold auf Silber gewechselt, damit Gold eindeutig "vollständig" heißt.
  Über den Karten steht der Stand der Sammlung — wie viele Mods, wie
  viele komplette Sets, wie weit alle Tiers zusammen sind. Und im
  Steckbrief ist die Tier-Leiter jetzt eine gezeichnete Tabelle statt
  einer Textwand: T1 bis T3 in Gold, Silber und Bronze, Sichtungen als
  kleiner Balken, nie gerollte Stufen gedämpft. Nebenbei haben Valdos
  Foil-Uniques einen Namen bekommen, wo vorher ein rohes "frameType 10"
  stand.

### Behoben

- Die Beschriftung des Schnitts im XP-Graphen war unlesbar, wenn der
  Schnitt dicht unter der Spitze lag: Sie stand dann halb außerhalb des
  Bildes und in der Achsenbeschriftung. Jetzt weicht sie unter die Linie
  aus.

## [0.11.2] - 2026-08-24

### Behoben

- Ein Truhenfach, das es bei GGG nicht gibt (Map-Stash-Unterfächer, in
  die noch nie etwas gelegt wurde), brachte den automatischen Rundlauf
  zum Stillstand: Es galt als nie geladen und damit dauerhaft als
  ältester Kandidat, der Abruf scheiterte mit HTTP 404, und beim
  nächsten Takt war es wieder an der Reihe. Kein anderes Fach der Liga
  kam noch dran, und das Log füllte sich alle paar Sekunden mit
  Tracebacks. Solche Fächer fallen jetzt aus dem Rundlauf, mit einer
  erklärenden Zeile statt eines Fehlers; ein Klick versucht es
  weiterhin, und sobald das Fach wirklich existiert, ist es wieder
  dabei.

### Geändert

- Die zuletzt gewählte Liga kommt nach einem Neustart wieder. Vorher
  startete das Programm in der Liga mit dem meisten Inhalt — eine gute
  Vorgabe beim allerersten Start, aber nicht danach.
- Der Schnitt im XP-Graphen gilt jetzt für einen benannten Zeitraum und
  zeigt ihn auch: Er beginnt beim letzten Levelaufstieg, spätestens nach
  einer Spielpause von mehr als einer halben Stunde, und reicht nie über
  die drei Stunden des Graphen hinaus. Über dieser Strecke ist die Linie
  dick und durchgezogen, davor bleibt sie dünn gestrichelt; neben der
  Zahl steht, wie lang die Strecke ist ("⌀ 2M · 34 min"). Vorher mittelte
  sie über alles Sichtbare und wurde trotzdem über die volle Breite
  gezeichnet — die Zahl stimmte, ihr Geltungsbereich war erfunden.
- Das Log schreibt einmal je Sitzung mit, welche Felder GGGs Antwort auf
  einen Charakter-Abruf enthält und welche davon ungenutzt bleiben. Kostet
  keinen zusätzlichen Abruf und beantwortet Fragen der Art "liefert die
  API eigentlich X?" mit Daten statt mit Vermutungen. Taucht ein Feld auf,
  das wir noch nie gesehen haben — etwa nach einem GGG-Patch —, sagt das
  Log das gesondert und eine Stufe lauter.
- Hilfe und README nehmen die GGG-Anmeldeseite vorweg: dass dort
  „PoE-VIEW" ohne die 2 steht (der bei GGG registrierte Client-Name),
  dass der rote Kasten jede App ohne Client-Secret trifft und nichts
  über die eigene Anmeldung aussagt, und dass alle dort aufgezählten
  Rechte reine Leserechte sind.
- Die README sagt gleich zu Anfang, woher die 2 im Namen kommt:
  PoE-VIEW war ein LabVIEW-Programm, dieses hier ist die Neufassung in
  Python, und die GGG-Registrierung stammt noch vom Vorgänger — daher
  der ältere Name auf der Anmeldeseite.

## [0.11.1] - 2026-08-22

### Behoben

- Das Anmelde- und das Ablauf-Fenster ließen sich vom Hauptfenster
  verdecken. Beide liegen jetzt dauerhaft darüber, bleiben aber
  weiterhin nicht-modal — das Hauptfenster ist unterdessen bedienbar,
  und über andere Programme (Path of Exile, den Browser) legen sie sich
  bewusst nicht.

## [0.11.0] - 2026-08-22

### Hinzugefügt

- Häkchen "Hide empty" über dem Stash-Baum: Fächer, von denen bekannt
  ist, dass nichts darin liegt, verschwinden aus der Ansicht. Nie
  geladene Fächer bleiben stehen — eine leere Anzahl-Spalte heißt
  "unbekannt", nicht "leer". Reine Anzeige: Im Hintergrund werden
  weiterhin alle Fächer abgerufen, ein ausgeblendetes taucht also
  wieder auf, sobald etwas darin liegt.
- Die Statuszeile nennt neben der Wertsumme, wie alt die
  poe.ninja-Preise der aktuellen Liga sind ("poe.ninja 2 h ago"), mit
  dem genauen Abrufzeitpunkt im Tooltip. So ist ein tatsächlich
  billiges Item von einem veralteten Preis zu unterscheiden.
- Ein Willkommensfenster beim Start, wenn keine gültige Anmeldung
  vorliegt: Es nennt den Stand der lokal gespeicherten Daten und bietet
  Anmelden oder Weiterarbeiten ohne Anmeldung an. Beim allerersten Start
  kommt ein kurzer "Getting started"-Teil dazu. Abschaltbar über ein
  Häkchen im Fenster selbst.
- Läuft die Anmeldung mitten in der Sitzung ab, sagt das jetzt ein
  eigenes Fenster statt nur der Statuszeile. Beide Fenster blockieren
  nichts — die lokal gespeicherten Daten bleiben durchsuchbar. Nach einem
  selbst ausgelösten Abmelden erscheint bewusst keins von beiden.
- Rechtsklick auf einen Charakter, "Export character sheet…", erzeugt
  einen Charakterbogen als Markdown-Datei: Ausrüstung nach Körperslot
  (im Stile alter Pen&Paper-Rollenspiele) und die eingesetzten Gems
  samt Stufe, gruppiert nach dem Ausrüstungsteil, in dem sie stecken.
  Keine berechneten Werte wie Leben oder Resistenzen — GGGs API liefert
  sie nicht, sie entstehen im Spielclient aus dem vollen Passivbaum.

### Behoben

- Der Level in der Charakterliste blieb während einer Sitzung auf dem
  Stand vom Programmstart stehen — ein Charakter, der von Stufe 13 auf
  24 stieg, wurde stundenlang als "13" geführt. Liste und
  Charakterdaten kommen aus verschiedenen Endpunkten von GGG, und nur
  die Liste war stehengeblieben; der richtige Level lag bei jedem
  einzelnen Charakter-Abruf bereits vor und landete bisher nur im
  Leveling-Feld. Die Auswahl in der Liste überlebt das Aktualisieren.

### Geändert

- Der Auto-Modus taktet jetzt nach dem tatsächlichen Rate-Limit von GGG
  statt nach festen 40 Sekunden — demselben gerechneten Takt, den
  "Single" und "Stash" schon fahren. Zusätzlich frischt sein
  Hintergrund-Durchlauf die Truhe auch dann weiter auf, wenn jedes Fach
  jünger als einen Tag ist; bis dahin stand er in diesem Fall still, was
  im Alltag der Normalfall war. An einem echten Log gemessen: Die offene
  Ansicht wurde 195-mal aktualisiert, wo unter dem neuen Takt 632
  möglich gewesen wären, und das Rate-Limit-Fenster war dabei im Median
  nur zu gut einem Viertel ausgelastet.

## [0.10.0] - 2026-08-17

### Behoben

- Ein Abyss-Jewel im Gürtel oder Ring wurde als Gem gezählt und bekam im
  Leveling-Feld einen eigenen, dauerhaft leeren Balken. Jewels leveln
  nicht und gehören nicht in den Streifen.
- Ab etwa Stufe 91 blieben Level, Gesamterfahrung und XP/h im
  Leveling-Feld stehen und der Graph bekam keine neuen Abschnitte mehr.
  Ursache war die 32-Bit-Grenze von Qts `int` (2 147 483 647), die PoE
  mitten in Stufe 91 überschreitet — die Erfahrung kam dadurch nie in
  der Oberfläche an. Betroffen war jeder Charakter darüber; Stufe 100
  sind 4 250 334 444 Erfahrungspunkte.
- Die Gem-Balken waren verschwunden, seit die Favoriten-Tabelle neben
  sie gesetzt wurde: Sie meldeten keine eigene Breite an und bekamen
  deshalb keine.

### Hinzugefügt

- In die Beobachtungsliste passen jetzt mehr Zeilen: Sie sind 18 statt
  23 px hoch, wie ursprünglich vorgesehen — neben einem dreizeiligen
  Textblock sind das sieben Einträge ohne Scrollen statt fünf.
- Die Zeilen der Beobachtungsliste lassen sich per Ziehen umsortieren.
  Ein Strich zeigt beim Ziehen, wo der Eintrag landet; unter die letzte
  Zeile ziehen heißt ans Ende. Die Reihenfolge wird sofort gespeichert
  und steht beim nächsten Start wieder so da.
- Die Gem-Balken zeigen jetzt die **Stufe** als Höhe statt des
  Fortschritts zur nächsten Stufe — der Streifen ist damit ein Profil
  des Charakters und zeigt auf einen Blick, welches Gem zurückhängt. Der
  Fortschritt steht weiterhin darin, als schmale gelbe Linie über die
  ganze Balkenhöhe.
- Fertig gelevelte Gems (Stufe 20, korrumpiert 21, Awakened 5) sind
  jetzt ein voller Balken in der kräftigen Fassung ihrer Farbe — rot,
  grün, blau oder weiß. Vorher sahen sie aus wie ein Gem, das gerade
  eben die nächste Stufe erreicht hat.
- Gems mit wenig Fortschritt sahen im Balkenstreifen aus wie Lücken:
  Der leere Teil eines Balkens war gegen den dunklen Hintergrund
  praktisch unsichtbar. Er ist jetzt heller und damit als Balken
  erkennbar.
- Rechtsklick auf ein Item, "Watch stack size", und es steht mit seiner
  Gesamtmenge in einer Tabelle an der rechten Seite des Leveling-Felds,
  neben Stufe, Rate und Gem-Balken (sieben Zeilen ohne Scrollen). Gezählt
  wird über alle geladenen Fächer und Charaktere der Liga, sodass ein
  Blick genügt, um zu sehen, wie viel Lifeforce oder Währung
  zusammengekommen ist. Ein `≥` weist darauf hin, solange noch nicht
  jedes Fach geladen ist.
- Der XP-Graph ist nach einem Programmstart nicht mehr leer: Die
  gemessenen Abschnitte der letzten drei Stunden werden je Konto
  gespeichert und beim nächsten Start wieder eingezeichnet. Die
  Beobachtungsbasis wird bewusst nicht mitgenommen — sonst würde ein
  Levelaufstieg während der Programmpause als absurd hohe Rate
  erscheinen. Die erste neue Rate kommt also weiterhin mit der zweiten
  Veröffentlichung, aber der Verlauf davor bleibt sichtbar.
- Das Konto-Menü hat einen Eintrag "PoE2 raw data", der GGGs API nach
  dem PoE2-Realm fragt und die Antwort als Rohtext zeigt. Er stellt
  dieselbe Frage dreimal — ohne Realm, mit `poe2` und mit einem
  erfundenen Wert — und schreibt das Ergebnis des Vergleichs in
  Klartext über die Rohdaten. Das Programm liest weiterhin nur Path of
  Exile 1. Der Abzug landet zusätzlich als `poe2-probe.txt` im
  Profilordner.
- Erste Messung damit: GGG wertet den `realm`-Parameter nicht aus. Alle
  drei Varianten liefern bytegleich dieselben PoE1-Daten, auch die mit
  dem erfundenen Realm. Ob ein Konto PoE2-Charaktere hat, ist über
  diesen Weg also nicht feststellbar — unabhängig davon, dass die
  Truhen-Endpunkte für PoE2 ohnehin nicht vorgesehen sind.

### Geändert

- Fehlermeldungen der API nennen jetzt die Query mit, nicht nur den
  Pfad. Ohne sie wäre ein Fehlschlag mit `?realm=poe2` nicht von einem
  gewöhnlichen zu unterscheiden.

## [0.9.0] - 2026-08-13

### Behoben

- Veröffentlicht GGG die Erfahrung ausnahmsweise mitten in einer Karte
  statt beim Verlassen, war die darauf folgende XP/h-Angabe viel zu
  niedrig — im gemessenen Fall 38 statt 187 Millionen. Sie rechnete mit
  der ganzen Zeit in der Karte, obwohl der größere Teil davon schon
  abgerechnet war. Ein Abschnitt reicht jetzt höchstens bis zur vorigen
  Veröffentlichung zurück; im Graphen überlappen sich dadurch auch keine
  Balken mehr.

### Hinzugefügt

- Über dem XP-Graphen zeigt jetzt ein schmaler Balken je eingesetztem
  Gem, wie weit es zur nächsten Stufe ist — in der Farbe des Attributs,
  das es verlangt. Ein voller Balken heißt fertig; wartet das Gem nur
  auf einen Klick, sitzt eine gelbe Kappe darauf. Damit ist auf einen
  Blick zu sehen, welche Gems durch sind und welche noch Aufmerksamkeit
  brauchen.
- Verlässt man eine Map zwischendurch (Items verkaufen) und kommt
  zurück, erkennt der XP-Graph das jetzt als EINE Map: Hinter den
  einzelnen Aufenthalten liegt eine dunkelgrüne Fläche auf Höhe der
  Rate für die ganze Map. Die Lücke bleibt sichtbar — man sieht also,
  was der Ausflug gekostet hat.
- Eine gestrichelte Linie im Graphen zeigt die Gesamtrate über die
  angezeigten drei Stunden.

### Geändert

- Die Suche versteht jetzt mehrere Begriffe, so wie die Suche im Spiel:
  Durch Leerzeichen getrennte Wörter müssen ALLE zutreffen. `life
  resistance` findet damit Items mit beidem, auch wenn die zwei Wörter
  im Text nie nebeneinander stehen — vorher fand diese Eingabe nichts.
  Mehrere Wörter in Anführungszeichen bleiben ein Begriff (`"maximum
  life"`).
  Wer reguläre Ausdrücke benutzt: Jedes Wort ist ein eigenes Muster.
  Socket-Muster von poe.re enthalten keine Leerzeichen und funktionieren
  unverändert; ein Muster mit Leerzeichen gehört in Anführungszeichen.
- Mitgesucht werden jetzt auch die Namen der eingesetzten Gems — "wo
  steckt eigentlich meine Determination?" beantwortet die Suche selbst.
- Zwei Kurzformen aus dem Spiel funktionieren jetzt auch hier:
  `ilvl:84` findet Itemlevel genau 84, `tier:16` Map-Tier genau 16 —
  beides kombinierbar mit allem anderen (`ilvl:84 ring`). Für Bereiche
  bleibt der Spalten-Filter (`>=84`) der bessere Weg.
- **Strg+F** springt ins Suchfeld und markiert den bisherigen Text.

## [0.8.0] - 2026-08-13

### Hinzugefügt

- Rechtsklick auf ein Item bietet jetzt "Copy item text (for Path of
  Building)" an: Das Item landet im Textformat des Spiels in der
  Zwischenablage und lässt sich in Path of Building einfügen. Gedacht
  vor allem für Truhen-Items — Charaktere holt sich PoB selbst von GGGs
  Seite, an die Truhe kommt es nicht heran. Verzauberungen und
  Flaschen-Effekte sind dabei, ebenso Sockel, Qualität und Item-Level.
- Das Item-Detail unten ist nach Blöcken gegliedert — Eigenschaften,
  Anforderungen, impliziter und explizite Mods durch dünne Linien
  getrennt, wie im Spiel. Vorher lief alles als eine Liste
  untereinander, und welcher Mod der implizite ist, war gar nicht zu
  erkennen. Verzauberungen und Flaschen-Effekte werden jetzt überhaupt
  angezeigt; passt der Text nicht ins Panel, steht das dort, statt still
  abgeschnitten zu werden.
- Neben dem Item-Detail sitzt ein Leveling-Feld mit Stufe,
  Gesamterfahrung und XP/h des zuletzt abgeschlossenen Gebiets. Die
  Trennlinie zwischen beiden lässt sich verschieben.
- Eine Verbindungs-LED am rechten Ende der Statuszeile: grün, solange
  GGG antwortet, rot während einer Wartung, grau bevor überhaupt etwas
  abgefragt wurde. Sie geht von selbst wieder auf grün, sobald ein
  Abruf gelingt — ohne Neustart. Die Bedeutung der drei Farben steht im
  Hilfe-Fenster unter "Getting started".
- Darunter zeichnet ein Graph die letzten drei Stunden: ein Balken je
  abgeschlossenem Gebiet, so breit wie das Gebiet gedauert hat. Wo
  nichts steht, wurde keine Erfahrung gemacht — Pausen bleiben als
  Lücken sichtbar. Ein Gebiet, in dem unterm Strich Erfahrung verloren
  ging, hängt rot unter der Null-Linie.

### Behoben

- Billige Währung wurde teils viel zu hoch bewertet — ein Stapel von 921
  Wisdom Scrolls stand mit 4,9 Divine in der Tabelle. poe.ninja kann
  Kurse unter einem Chaos in einer Handelsrichtung nicht ausdrücken und
  meldet dort glatt „1 Chaos"; die Gegenrichtung wird jetzt zuverlässig
  ausgewertet, auch seit poe.ninja sie in umgekehrter Einheit angibt.
  Fehlt die Gegenrichtung ganz, bleibt die Wertspalte leer, statt eine
  Obergrenze als Preis auszugeben.
- Das Item-Detail schnitt lange Items wieder ab, ohne es zu sagen: Die
  Trennlinien zwischen den Blöcken brauchen selbst Platz, was bei der
  Höhe nicht mitgerechnet war. Das Feld ist 16 Pixel höher und zeigt
  jetzt 95 % aller Items vollständig; was darüber hinausgeht, wird wie
  vorgesehen gemeldet.
- Während einer GGG-Wartung meldete die Anwendung im Sekundentakt
  "League not found" und verdeckte damit ihren eigenen Offline-Hinweis.
  Der Truhen-Endpunkt beantwortet eine laufende Wartung nicht mit einem
  Serverfehler, sondern mit einer abgelehnten Anfrage — gemessen an
  einer echten Wartung in 19 von 22 Fällen, während der
  Charakter-Endpunkt gleichzeitig sauber "Server nicht verfügbar"
  meldete. Die Liga existierte dabei durchgehend. Solche Antworten
  zählen jetzt als Wartung: Es erscheint der normale Offline-Hinweis,
  und die zwischengespeicherten Daten bleiben durchsuchbar.
- Nach der ersten Karte einer Sitzung blieb die XP/h-Anzeige leer,
  obwohl alles Nötige gemessen war: Der Weg ins Hideout ändert die
  Erfahrung nicht, es gab also nur eine Veröffentlichung, und die
  Rechnung verlangte zwei. Sie nimmt jetzt den Stand beim
  Programmstart als Vergleichspunkt — allerdings nur, wenn dieser
  nachweislich vor dem Betreten des gemessenen Gebiets liegt,
  andernfalls wäre die Rate erfunden.

## [0.7.0] - 2026-08-12

### Hinzugefügt

- Das Anwendungssymbol erscheint jetzt auch in der README und im
  Hilfe-Fenster unter "About". Dafür legt `tools/make_icon.py` neben der
  mehrstufigen `.ico` eine einzelne `assets/PoE-VIEW2.png` an — weder
  GitHubs Markdown noch Qts Rich Text kommen mit einer mehrstufigen
  Icondatei zurecht.
- Charakter-XP/h in der Statuszeile, sobald ein Charakter offen ist —
  ohne zusätzlichen API-Request (Level und Erfahrung stecken bereits in
  der Antwort, die für die Ausrüstung ohnehin geladen wird). Gezeigt wird
  die Rate der zuletzt abgeschlossenen Zone, gerechnet über die Zeit, die
  der Charakter dort verbracht hat — Wartezeit im Hideout verwässert sie
  also nicht, und eine Pause lässt sie nicht absacken, sondern einfach
  stehen. Ab einer Minute steht dahinter, wie alt der Wert ist
  (`24.1M XP/h (3m ago)`), denn neue Erfahrung liefert die API von GGG
  erst, wenn eine Map verlassen wird. Erster Schritt einer größeren,
  noch offenen Idee (Gem-XP/h, ein echter Graph).
- Der Live-Refresh reagiert jetzt nicht mehr nur auf Zonenwechsel,
  sondern auch auf Händler-Verkäufe und das Identifizieren von Items —
  beides steht in PoEs eigener `Client.txt`, die für den Zonenwechsel
  ohnehin schon gelesen wird. Damit die zusätzlichen Anlässe kein
  Rate-Limit-Budget verbrennen, verschiebt jeder vorgezogene Abruf den
  nächsten regulären Takt um die eingesparte Zeit; eine Serie von
  Ereignissen ist auf vier Abrufe begrenzt, danach wird gewartet, bis
  der Takt wieder aufgeholt hat. Ob GGG zu diesen Anlässen tatsächlich
  neue Daten bereitstellt, ist unterschiedlich — verlässlich ist nach wie
  vor nur der Zonenwechsel. Der vorgezogene Abruf kostet aber nichts
  extra, weil er den nächsten regulären um dieselbe Zeit verschiebt.
- Ist in einem Item ein Sockel-Gem eine Stufe aufgestiegen, leuchtet die
  Zeile grün statt türkis. Damit ist der häufigste Grund, aus dem
  angelegte Ausrüstung überhaupt aufleuchtet, auf einen Blick von einem
  echten Neuzugang zu unterscheiden. Ein frisch eingesockeltes Gem bringt
  seine Stufe nur mit und bleibt türkis.

### Behoben

- Die kurzen Hänger beim Aktualisieren der Fächer sind weg. Ursache: Bei
  jedem eintreffenden Fach wurde der komplette Datenbestand neu in die
  Cache-Datei geschrieben — bei einer großen Truhe 1,4 Sekunden lang,
  und zwar im Vordergrund. Das Schreiben läuft jetzt in einem eigenen
  Thread, und mehrere Anforderungen kurz hintereinander fallen zu einer
  zusammen. In der Oberfläche bleiben davon 0,009 Sekunden übrig; beim
  Beenden wird auf den letzten Speichervorgang gewartet.
- Beim Spielen leuchtete ständig die halbe Ausrüstung türkis auf, als
  wäre gerade etwas Neues passiert, obwohl nichts geschehen war.
  Ursache: Die Erfahrung der Sockel-Gems zählt permanent hoch und ist
  Teil der Item-Daten — damit galt jedes sockelbare Ausrüstungsteil bei
  fast jedem Refresh als "geändertes Item" (in Peters Spielrunde
  gemessen: 25 von 29 Gems mit neuen Erfahrungswerten binnen zwölf
  Sekunden). Der Erfahrungsstand zählt für die Hervorhebung jetzt nicht
  mehr mit; ein Gem, das tatsächlich eine Stufe aufsteigt, wird
  weiterhin angezeigt.
- Aus demselben Grund leuchteten Flaschen regelmäßig auf: Ihre aktuelle
  Ladungszahl steht in den Item-Daten und schwankt beim Spielen
  ununterbrochen. Sie zählt für die Hervorhebung nicht mehr mit — die
  maximale Ladungszahl, die sich tatsächlich ändern kann, dagegen schon.

## [0.6.0] - 2026-08-07

### Hinzugefügt

- Hilfe-Fenster (Fragezeichen-Knopf in der Toolbar) mit elf Themen: was
  die Spalten bedeuten, wofür die Farbfilter stehen, wie Suche und
  Refresh-Modi arbeiten, warum die beiden Zähler in "Load All Tabs"
  auseinanderlaufen, was die Symbole im Item-Verlauf heißen, warum die
  Wertspalte in SSF-Ligen leer bleibt, und wo die eigenen Daten liegen.
  Das Fenster ist nicht modal — es kann offen bleiben, während man das
  Erklärte ausprobiert.
- Statuszeile zeigt jetzt "Updated HH:MM:SS" — wann der Inhalt der
  Tabelle zuletzt neu aufgebaut wurde. Damit ist auf einen Blick
  erkennbar, wie frisch das Angezeigte ist.
- Datum und Uhrzeit rechts oben in der Toolbar. Zusammen mit dem
  "Updated"-Zeitstempel der Statuszeile ist damit auch auf einem
  Screenshot allein erkennbar, wie aktuell die angezeigten Daten sind.
- Neben dem "Updated"-Zeitstempel erscheint "unchanged for 12m", wenn
  die Daten zwar weiter eintreffen, aber unverändert bleiben. Damit ist
  "wir holen nichts mehr" von "wir holen, die API liefert denselben
  Stand" zu unterscheiden — letzteres ist der Normalfall, solange im
  Spiel kein Zonenwechsel stattgefunden hat. Zeiten, in denen wegen des
  Rate-Limits gar nicht abgefragt wurde, zählen dabei nicht mit — die
  Angabe nennt nur geprüfte Zeit.
- Der Spaltenfilter (Rechtsklick auf einen Spaltenkopf) vervollständigt
  jetzt schon beim Tippen: Der passende Rest steht markiert hinter dem
  Cursor und wird mit Return oder Tab übernommen. Die bisherige
  Vorschlagsliste bleibt daneben bestehen — sie findet auch Werte, bei
  denen man nur einen Teil aus der Mitte kennt.
- Der Fortschrittsdialog von "Load All Tabs" erklärt jetzt seine
  Zahlen: Der Fach-Zähler steht vorn, die Abrufe heißen "requests"
  statt "Section" (ein Wort, das es in der Truhen-Oberfläche gar
  nicht gibt), eine kleine Tabelle rechnet vor, woraus sich die
  Gesamtzahl zusammensetzt, und die Restzeit nennt das Rate-Limit
  von GGG als Grund. Die Zahlen selbst waren immer richtig — sie
  sahen nur nach einem Widerspruch aus.
- "📌 Pin" im Rechtsklick-Menü der Item-Liste: setzt den Spaltenfilter
  auf genau den Wert der angeklickten Zelle. Rechtsklick auf
  "MainInventory" in der Tab-Spalte zeigt also nur noch Items von
  dort. Der Wert, nach dem man filtern will, steht meistens schon
  unter dem Mauszeiger — bisher musste man ihn im Header-Menü
  abtippen.
- Das Hilfe-Fenster ist auf dem Stand der Oberfläche: Es beschrieb
  noch den alten "Load All Tabs"-Dialog mit einem Zähler namens
  "Section", den es nicht mehr gibt, und kannte weder den
  Nur-Lese-Modus eines zweiten Fensters noch "Pin" und die
  Vervollständigung im Spaltenfilter.
- Die Symbole im Item-Verlauf (↑ ↓ ±) erklären sich jetzt per Tooltip.
- In Ligen, für die poe.ninja keine Preise führt, steht in der
  Statuszeile "No prices for this league" statt einer wortlos leeren
  Wertspalte. Der Tooltip nennt den Grund: Solo Self-Found hat keinen
  Handel, aus dem sich Preise ableiten ließen.
- **Der Daten-Cache wird bei jedem Programmstart gesichert**, bevor die
  neue Sitzung etwas daran ändern kann — nach
  `%LOCALAPPDATA%\PoE-VIEW2\backups`, gepackt auf etwa ein Zehntel
  (67 MB werden zu 7,5 MB, in einer Drittelsekunde). Der Dateiname nennt
  den Zeitpunkt. Sicherungen werden 24 Stunden aufbewahrt; die neueste
  bleibt immer erhalten, egal wie alt sie ist. Hat sich seit der letzten
  Sicherung nichts geändert, wird keine neue angelegt. Zurückgespielt
  wird von Hand über den Explorer — das Hilfe-Fenster beschreibt den Weg.
- Die vergrößerte Item-Ansicht (Doppelklick auf eine Zeile) zeigt jetzt
  den Spruchtext des Items — bei einer Divination Card das, was die Karte
  ausmacht, bei Uniques die Hintergrundgeschichte. Er steht zwischen Bild
  und Zahlen, kursiv in einer Serifenschrift und etwas größer; bei Karten
  innerhalb des Kartenrahmens, durch eine Zierlinie vom Artwork getrennt.
- Die Belohnung einer Divination Card erscheint in der Farbe, die GGG ihr
  selbst gibt: Währung gold, Gems grün, Uniques orange, "Corrupted" rot.
  Die Angabe steckt in denselben Auszeichnungen, die aus dem Text
  entfernt werden — statt sie wegzuwerfen, wird sie jetzt ausgewertet.
- Alle Texte in der vergrößerten Ansicht sind zentriert, wie in den
  Item-Tooltips des Spiels.
- Bei einer Divination Card steht statt "Stack Size: 7/5" der Fortschritt
  zum nächsten Satz: `1 ▮  +  ▮ ▮ ▯ ▯ ▯` — ein voller Satz (grün), und vom
  nächsten sind zwei von fünf Karten da. Damit ist ohne Kopfrechnen zu
  sehen, wie weit man ist. Die genauen Zahlen stehen im Tooltip. Nur bei
  Karten — bei Währung ist die Stapelgröße keine Satzgröße, sondern
  Lagerkapazität und reicht bis 50 000.
- Karten, von denen eine einzelne schon ein voller Satz ist ("Society's
  Remorse", "The Cartographer" und fünf weitere), zeigten bisher gar
  keine Stückzahl an — die API liefert für sie kein Stack-Size-Feld.
  Jetzt steht dort die Anzahl mit einem grünen Rechteck (`16 ▮`).

### Geändert

- Das Charakter-Fenster (Doppelklick auf einen Charakter) zeigt die
  Ausrüstung endlich lesbar: Die Hälfte der Namen war abgeschnitten — an
  einem echten Charaktersatz gemessen 87 von 171 Teilen, vier Flaschen
  lasen sich allesamt als "Flagell…" und waren nicht auseinanderzuhalten.
  Die Plätze sind jetzt breiter, brechen lange Namen auf zwei Zeilen um
  und zeigen die Basis statt des gewürfelten Fantasienamens eines Rares
  ("Gutting Knife" statt "Vortex Bane"); der vollständige Name steht im
  Tooltip. Ergebnis: kein einziger gekürzter Name mehr.
- Die Ausrüstungsplätze tragen jetzt die Rarity-Farben der Item-Tabelle —
  vorher war alles weiß, und man sah der Puppe nicht an, welches Teil das
  Unique ist.
- Die Juwelen aus dem Passiv-Baum sind anklickbar wie jeder andere Platz,
  mit Icon und Farbe. Vorher waren sie eine reine Textliste in einem
  Rollbereich, die einzigen Items im Fenster ohne Reaktion auf einen
  Klick, und die Liste schnitt regelmäßig mitten in einer Zeile ab.
- Die Ausrüstungsplätze liegen jetzt so wie in PoEs eigenem
  Inventar-Fenster: Ringe links und rechts der Rüstung, Amulett rechts
  neben dem Helm, Handschuhe/Gürtel/Stiefel auf einer Höhe. Bisher stand
  das Amulett zwischen den Waffen und die Ringe flankierten den Gürtel.
- Statuszeile aufgeräumt: Die beiden Refresh-Angaben sind zu einer
  zusammengefasst ("Single — next update in 1s · 0/94 tabs"), und der
  Hinweis zur fehlenden Zugehörigkeit zu Grinding Gear Games steht jetzt
  im Hilfe-Fenster unter "About" statt dauerhaft in der Statuszeile.
- Settings-Dialog und Charakter-Fenster sind jetzt durchgehend englisch
  wie die übrige Oberfläche. Vorher waren im Settings-Dialog nur die
  Reiter englisch und alle Beschriftungen deutsch; im Charakter-Fenster
  standen die Ausrüstungsplätze, "Ausrüstung", "Flasche" und "Jewels im
  Passiv-Baum" auf Deutsch.

- Der Hintergrund-Refresh taktet in den Modi "Single" und "Stash" etwas
  langsamer (bei GGGs üblichem Kontingent 13 statt 11 Sekunden).
  Grund: Der bisherige Takt schöpfte das Abruf-Kontingent so weit
  aus, dass schon wenige zusätzliche Abrufe — etwa durch mehrere
  Zonenwechsel kurz hintereinander — die Notbremse auslösten und
  der Refresh dann minutenlang ganz aussetzte. Etwas langsamer,
  dafür ohne diese Aussetzer.

### Behoben

- Markierte man im Fach-Baum einen Spezial-Tab ("Unique Items", "Map
  Stash") zusammen mit anderen Fächern, blieben seine Items in der
  Tabelle aus — und damit auch im CSV-Export. Ordner lösten sich richtig
  in ihre Fächer auf, Spezial-Tabs nicht: Sie sind technisch keine
  Ordner und galten deshalb als einzelnes Fach, unter dessen ID es aber
  gar keine Items gibt (die stecken in den Unter-Fächern). Maßgeblich
  ist jetzt allein, ob ein Knoten Unter-Knoten hat.
- Item-Eigenschaften mit Platzhaltern wurden falsch dargestellt: Statt
  "Consumes 35 of 65 Charges on use" stand dort "Consumes {0} of {1}
  Charges on use: 35" — die Platzhalter blieben stehen und der zweite
  Wert fehlte ganz. Betraf das Detail-Panel, die vergrößerte Item-
  Ansicht, den CSV-Export und den Suchindex.
- Item-Verlauf: Nach einem Programmstart tauchten dort Ereignisse auf,
  die längst vergangen waren — mit der aktuellen Uhrzeit versehen. Der
  Verlauf selbst wird nicht gespeichert, der Inventarstand der
  Charaktere schon; der erste Abruf nach dem Start verglich deshalb
  gegen einen womöglich wochenalten Stand. Protokolliert wird jetzt erst
  ab dem zweiten Abruf eines Charakters, der erste setzt nur die
  Vergleichsbasis.
- Währungen unter einem Chaos wurden alle mit genau einem Chaos
  bewertet — ein voller Stapel Scrolls of Wisdom stand dadurch mit 40c
  in der Value-Spalte statt mit 0,2c. Ursache war poe.ninjas
  "receive"-Seite, die kein kleineres Verhältnis als 1:1 ausdrücken
  kann; die Gegenrichtung derselben Zeile kennt den echten Kurs und wird
  jetzt verwendet. Betraf in der Liga Allflame 20 von 67 Währungen.
  Nebenbei behoben: poe.ninja rundet auf zwei Nachkommastellen, was sich
  bei großen Stapeln aufsummierte.
- Ein zweites PoE-VIEW2-Fenster mit demselben Konto läuft jetzt nur
  lesend: Der Cache bleibt vollständig durchsuchbar (Suche, Filter,
  Item-Details, CSV-Export), aber es ruft nichts ab und speichert nichts.
  Vorher hätten sich zwei Fenster gegenseitig die Daten überschrieben und
  sich obendrein das Abruf-Kontingent geteilt. Mit einem anderen Konto
  angemeldet, ist das zweite Fenster uneingeschränkt nutzbar. Die
  Statuszeile sagt, welcher Fall gerade gilt.
- Die lokalen Cache-Dateien werden jetzt vollständig oder gar nicht
  geschrieben. Vorher ging der Schreibvorgang direkt in die Zieldatei —
  bei über 50 MB dauert das lange genug, dass ein Absturz oder eine
  zweite gleichzeitig laufende Programminstanz eine unlesbare Datei
  hinterlassen konnte. Beobachtet wurde ein solcher Schaden nie; die
  Lücke gab es trotzdem.
- Gleiche Ursache, zweite Anzeige: Beim ersten Abruf nach dem
  Programmstart wurden Inventarzeilen türkis hervorgehoben und
  verschwundene Items grau angehängt, obwohl die Änderungen Tage
  zurücklagen. Auch die Hervorhebung vergleicht jetzt erst ab dem
  zweiten Abruf eines Charakters.
- Das Speichern der Cache-Dateien scheiterte gelegentlich, wenn ein
  anderes Programm die Datei gerade zum Lesen geöffnet hatte — Windows
  lässt das Ersetzen dann nicht zu, und ein Virenscanner auf einer frisch
  geschriebenen 67-MB-Datei tut genau das. Der Vorgang wird jetzt
  viermal in kurzem Abstand wiederholt (zusammen unter einer Sekunde),
  statt beim ersten Versuch aufzugeben. Verloren ging dabei nie etwas,
  der nächste Speichervorgang holte es nach; im Log stand aber ein
  Fehler, der wie ein Defekt aussah.
- Bei Divination Cards stand die Belohnung mit GGGs Färbungs-Anweisungen
  im Text: `<currencyitem>{3x Orb of Fusing}` statt "3x Orb of Fusing".
  Betraf 952 der 975 Karten in einem echten Stash und ausschließlich
  Karten — kein anderes Item trägt dieses Markup.
- Rund jede vierzehnte Divination Card blieb ohne Artwork und zeigte den
  generischen Kartenrücken. Der Dateiname wurde aus dem Kartennamen
  gebaut, obwohl die API ihn mitliefert; bei 28 von 373 Kartentypen
  weichen beide voneinander ab ("The Cartographer" heißt auf dem Server
  "TheMapmaker"). Jetzt zählt die Angabe der API.

## [0.5.1] - 2026-08-04

### Behoben

- Datenverlust beim Ab- und Wieder-Anmelden: Wer sich abmeldete und
  danach erneut mit demselben Konto anmeldete, bekam seine gespeicherten
  Truhen- und Charakterdaten nicht zurück — der leere Zustand wurde
  stattdessen über die vorhandene Datei geschrieben. Beim nächsten Start
  wirkte es, als müsse alles neu geladen werden. Die Daten kommen jetzt
  nach dem erneuten Anmelden wieder von der Platte.
- Zusätzlicher Schutz gegen Datenverlust: Die lokale Datendatei wird
  nicht mehr überschrieben, wenn dabei der allergrößte Teil des
  gespeicherten Bestands verlorenginge. Im Zweifel bleibt lieber zu viel
  gespeichert — beide bisherigen Datenverluste entstanden genau so, und
  der Schutz greift unabhängig davon, welcher Programmteil das
  Speichern auslöst.

## [0.5.0] - 2026-08-03

### Hinzugefügt

- Logout: der Konto-Button in der Toolbar öffnet nach dem Login jetzt ein
  Menü mit "Log out", statt einfach nur deaktiviert zu sein. Vorher gab
  es keinen Weg, sich mit einem anderen GGG-Konto anzumelden, ohne den
  gespeicherten Eintrag von Hand aus dem Windows-Anmeldeinformations-
  manager zu löschen. Ein Logout widerruft nur lokal die Anmeldung bei
  PoE-VIEW2 — die Freigabe auf der GGG-Kontoseite bleibt davon
  unberührt, dort lässt sie sich bei Bedarf separat entziehen.
- Cache-Trennung pro Konto: jedes GGG-Konto bekommt jetzt seine eigene
  lokale Datendatei statt einer gemeinsamen. Vorher blieben Stash-Baum,
  Items und Charaktere eines vorherigen Kontos nach einem Kontowechsel
  im Speicher stehen und vermischten sich mit dem neuen. Nichts wird
  dabei gelöscht — jedes Konto behält seinen eigenen Stand, auch beim
  Zurückwechseln. Existiert die kontospezifische Datei noch nicht (z. B.
  gleich nach der Umstellung), wird die alte gemeinsame Datei automatisch
  übernommen, sofern sie zum selben Konto gehört — die alte Datei bleibt
  dabei unverändert erhalten.
- Item-Verlauf: reine Mengenänderungen (z. B. Currency-Stacks) tauchen
  jetzt als eigenes Ereignis auf und wandern dabei ganz nach oben, mit
  Vermerk, wie viel sich geändert hat (z. B. "53 (+3)"). Vorher wurden
  solche Änderungen komplett ignoriert — nur echte Neuzugänge und
  verschwundene Items landeten im Verlauf. Gilt nur für das
  Charakter-Inventar, nicht für Stash-Fächer.
- Eigenes Anwendungssymbol: PoE-VIEW2 hat jetzt ein eigenes Icon in
  Explorer, Taskleiste und Fenstertitel statt des allgemeinen
  Standardsymbols. Es steckt in sieben Größenstufen in der Datei, wobei
  die kleinen Stufen eine bewusst vereinfachte Fassung der Grafik
  verwenden — sonst würde der Runenring bei 16 Pixeln unkenntlich.
- Live-Zonenanzeige in der Toolbar: zeigt die zuletzt aus der Client.txt
  erkannte Zone an — unabhängig davon, ob danach tatsächlich ein Refresh
  folgt (Pause-Modus/Rate-Limit können das weiterhin verhindern). Auch
  eine Diagnose-Anzeige nebenbei: bleibt sie leer, war der Zonen-
  Beobachter entweder deaktiviert oder hat nichts erkannt.

### Behoben

- Der Zonenwechsel-Refresh löste in Wirklichkeit nie aus: die
  Datei-Überwachung von Qt bemerkt neue Zeilen in PoEs Client.txt nicht,
  solange das Spiel läuft. Aufgefallen ist das erst durch die neue
  Zonenanzeige, die dauerhaft leer blieb; die Daten waren trotzdem nie
  veraltet, weil der reguläre getaktete Refresh unabhängig davon
  weiterlief — der Zonenwechsel beschleunigt ihn nur. Die Erkennung
  prüft die Datei jetzt selbst im 2-Sekunden-Takt.
- Ein Liga-Wechsel im Dropdown leerte die Itemliste bisher nicht — der
  zuletzt angezeigte Fach- oder Charakterinhalt der vorherigen Liga blieb
  sichtbar stehen, obwohl keine Auswahl mehr dazu passte. Die Liste wird
  jetzt beim Liga-Wechsel geleert, bis erneut ein Tab oder Charakter
  ausgewählt wird.

## [0.4.0] - 2026-08-03

### Hinzugefügt

- CSV-Export: deutlich breiterer Spaltensatz statt bisher 10 fester
  Spalten — jetzt u. a. Position (Tab/X/Y), Kategorie, alle
  Anforderungen (Level/Str/Dex/Int), Sockets/Links, sämtliche Mod-Arten
  (Implicit/Explicit/Crafted/Enchant/Fractured/Veiled/Utility),
  Influences, Merkmale (Mirrored/Fractured/Synthesised/Veiled/Replica/
  Searing/Tangled), Notiz, Chaos-Wert und Item-ID. Optional zusätzlich
  eine `RawJSON`-Spalte mit dem vollständigen, unveränderten API-Objekt
  je Item — über einen zweiten Dateityp im Speichern-Dialog wählbar,
  bewusst nicht die Voreinstellung (Dateigröße bei großen Exporten).
- Export per Rechtsklick auf ein Item: "Export selected items" (die
  markierten Zeilen, Mehrfachauswahl per Strg-/Umschalt-Klick möglich)
  und "Export visible items" (identisch zum bisherigen Toolbar-Knopf),
  jeweils mit der Anzahl im Menütext. "Export visible items" steht jetzt
  auch im Rechtsklick-Menü des Stash-Baums (auf einem Fach, einem Ordner
  oder im leeren Bereich) und der Charakterliste (mit oder ohne
  Charakter unter dem Cursor) zur Verfügung.
- Der vorgeschlagene CSV-Dateiname nennt jetzt zusätzlich die
  exportierte Item-Anzahl und einen Zeitstempel (z. B.
  `poe-view2-Settlers-Chaos-Orb-12items-2026-08-03_1542.csv`) — vorher
  schlugen "Export selected items" und "Export visible items" aus
  derselben Ansicht denselben Namen vor.
- Mehrfachauswahl im Stash-Baum: Strg-/Umschalt-Klick auf mehrere Fächer
  oder einen Ordner (auch die "Tier N"-Gruppen im Map-Stash) zeigt deren
  Items zusammen an. Zeigt ausschließlich bereits gecachte Items — löst
  nie selbst einen Abruf aus, nicht gecachte Fächer werden in der
  Statuszeile genannt ("3 tabs selected: 2 loaded, 1 never loaded").
  Einzelauswahl eines Fachs verhält sich unverändert, inklusive
  automatischem Nachladen bei Cache-Miss.
- Das Suchfeld wird beim Auswählen eines Stash-Tabs, Ordners oder
  Charakters jetzt automatisch geleert und die globale Suche beendet —
  vorher blieb ein Suchtext stehen und filterte unbemerkt weiter, sobald
  man in eine andere Ansicht wechselte. Die globale Suche selbst bleibt
  von jeder Ansicht aus uneingeschränkt nutzbar.

## [0.3.0] - 2026-08-02

### Behoben

- Ein Spalten-Filter auf der Tab-Spalte (Header-Rechtsklick) überlebte
  bisher den Wechsel von der Charakter- zur Truhen-Ansicht (oder zwischen
  zwei Truhenfächern) — passte der Filterwert dort auf keinen einzigen
  Fach-/Slot-Namen, verschwanden alle Items kommentarlos, ohne sichtbaren
  Hinweis (die Tab-Spalte ist im Einzelfach-View automatisch ausgeblendet,
  der 🔍-Marker also unsichtbar). Ein solcher Filter wird jetzt beim
  tatsächlichen Wechsel der angezeigten Quelle automatisch entfernt.
  Filter auf anderen Spalten (Name, Base, Value, …) bleiben unverändert
  über einen View-Wechsel hinweg erhalten.
- Refresh-Modus "Stash": bereits geladene Remove-only-Fächer (können nur
  schrumpfen, nie wachsen) wurden im Rundlauf wie jedes andere gefüllte
  Fach behandelt und damit unnötig oft neu geladen. Sie kommen jetzt nur
  noch dran, wenn es sonst kein anderes gefülltes Fach gibt — die gleiche
  Nachrangigkeit, die der Auto-Refresh-Modus schon hatte.
- Preis-Anzeige: Ein poe.ninja-Abruf ohne eine einzige Preiszeile (z. B.
  ein transienter Ausrutscher) wurde bislang wie ein normaler Erfolg 6
  Stunden lang gecacht — eine Liga konnte dadurch stundenlang ohne jeden
  Preis dastehen, obwohl poe.ninja längst wieder normal antwortete. Ein
  solches Ergebnis läuft jetzt nach 1 Stunde statt 6 Stunden ab.
  Hinweis: SSF-Ligen (z. B. "Solo Self-Found") werden von poe.ninja
  grundsätzlich nicht getrackt — ohne Spieler-Handel gibt es dort keine
  Handelsaktivität, aus der sich Preise ableiten ließen. Das ist eine
  Grenze der Datenquelle, kein Fehler in PoE-VIEW2.
- "Load All Tabs" wirkte bei großen Truhen eingefroren: Der
  Fortschrittsbalken zählte Truhenfächer, die Arbeit fällt aber pro Abruf
  an. Ein Map-Stash bündelt hunderte Sektionen in einem einzigen Fach —
  die Anzeige stand dadurch über eine Stunde auf derselben Zahl. Der
  Balken läuft jetzt über die tatsächlichen Abrufe, das Label nennt
  zusätzlich das Fach ("Section 128 of 1088 · tab 3 of 519") und eine
  geschätzte Restzeit.
- Unique-Stash: Die selbst vergebenen Fach-Namen ("Ring", "Sceptre", …)
  gingen verloren, sobald das Eltern-Fach erneut geladen wurde — nach
  einem "Load All Tabs"-Lauf hießen dadurch fast alle Unterfächer wieder
  "UniqueStash". Die Namen bleiben jetzt erhalten; bereits betroffene
  Caches füllen sich beim nächsten Laden des Eltern-Fachs wieder auf,
  soweit die Items noch zwischengespeichert sind.
- Unique-Stash: Kinder eines Remove-only-Tabs zeigten nur noch
  "(Remove-only)" statt der Kategorie ("Ring (Remove-only)") — der
  GGG-Suffix im Namensfeld wurde fälschlich als vollständiger Name
  gewertet.
- Rate-Limit-Dashboard zeigt jetzt sofort "(Paused)" neben dem
  Policy-Namen, sobald der Refresh-Modus "Pause" aktiv ist.
- Rate-Limit-Dashboard: der angezeigte Verbrauch je Regel zeigt jetzt immer
  den zuletzt von GGG gemeldeten Rohwert. Reale Header-Logs zeigten, dass
  GGGs Zähler nicht gleitend pro Treffer altert, sondern in Blöcken von
  ~60 Sekunden auf einmal sinkt — die vorherige, feiner gedachte
  Interpolation traf dadurch systematisch daneben. Die tatsächliche
  Warte-Entscheidung war davon nie betroffen und bleibt unverändert
  konservativ.
- Die Refresh-Modi "Single" und "Stash" liefen nach einiger Zeit in eine
  fünfminütige Zwangspause. Ihr gleichmäßiger Takt war so berechnet, dass
  er das Rate-Limit gerade eben nicht reißt — er unterstellte dabei aber,
  der einzige Verbraucher zu sein. Klicks auf noch nicht geladene Fächer,
  Liga-Wechsel und die Abrufe direkt nach dem Programmstart füllen dasselbe
  Kontingent jedoch mit, wodurch die verbleibende Marge von einer einzigen
  Anfrage sofort aufgebraucht war. Der Takt pausiert jetzt selbsttätig,
  sobald das Fenster zu voll ist, und nennt den Grund in der Statuszeile.
- Liga-Wechsel trugen weiterhin zur 300s-Zwangspause bei: der Abruf der
  Fach-LISTE der neu gewählten Liga lief ungebremst, und eine Lücke im
  gerade erst gebauten Rate-Limit-Schutz ließ auch den Refresh-Modus-Takt
  direkt danach ungebremst durch. Beides behoben — der Listen-Abruf
  entfällt jetzt bei zu vollem Fenster (der gecachte Baum bleibt sichtbar),
  und der Refresh-Modus-Schutz greift jetzt auch unmittelbar nach einem
  Liga- oder Modus-Wechsel zuverlässig.
- "Load All Tabs", "Refresh" und der Refresh-Modus-Umschalter blieben ohne
  gültigen Login anklickbar, solange noch ein Daten-Cache aus einer
  früheren Sitzung sichtbar war — der Fortschrittsdialog von "Load All
  Tabs" öffnete sich dann, hing aber für immer bei 0 %, weil der Job vom
  Worker lautlos verworfen wurde. Diese drei Online-Funktionen sind jetzt
  gesperrt, solange kein Login besteht; Stash-Baum, Charakterliste und
  Liga-Auswahl bleiben zum Durchsuchen des Caches weiter nutzbar.

### Hinzugefügt

- Frei konfigurierbare Item-Nachschlagewerke: Über den Settings-Dialog
  (Reiter "External Tools") lassen sich eigene Seiten mit Name und
  URL-Vorlage eintragen, in der `{slug}` durch den Item-Namen ersetzt
  wird. Ein Rechtsklick auf ein Item öffnet die so hinterlegten Seiten.
  Die Liste ist **ab Werk leer** — PoE-VIEW2 bringt bewusst keine fremde
  Seite mit und kontaktiert von sich aus keine; wer einen Eintrag anlegt,
  trifft diese Entscheidung selbst. Der Slug berücksichtigt dabei, dass
  nur Uniques einen eigenständig auffindbaren Namen haben: bei allen
  anderen Seltenheiten wird der Basis-Typ verlinkt statt eines zufällig
  gewürfelten Namens.
- Charakter-Item-Verlauf: ein neues, aufziehbares Panel unterhalb der
  Item-Tabelle protokolliert die letzten 120 Items, die neu im
  Charakter-Inventar aufgetaucht oder daraus verschwunden sind (↑/↓) —
  über alle Charaktere hinweg, unabhängig davon, welcher gerade angezeigt
  wird. Damit lässt sich kurz nachschauen, was man gerade in die Truhe
  gelegt, verkauft oder gehandelt hat. Eigenes, kompaktes Spaltenformat
  (Zeit, Charakter, Ereignis, Icon, Name, Base, Stack, Value);
  standardmäßig auf eine Zeile eingeklappt, per Ziehen am Splitter
  aufziehbar. Rechtsklick/Doppelklick funktionieren wie in der
  Haupttabelle (externe Tools, vergrößerte Ansicht).
- Charakter-Ansicht: Beim Beobachten eines Charakter-Inventars (z. B. per
  Zonenwechsel-Trigger, siehe unten) werden Zeilen, die sich seit dem
  letzten Refresh geändert haben oder neu hinzugekommen sind, türkis
  hervorgehoben. Aus dem Inventar verschwundene Items werden nicht
  sofort entfernt, sondern für einen Refresh-Zyklus grau und
  durchgestrichen angezeigt.
- Optionaler Zonenwechsel-Trigger für den Live-Refresh (Settings-Dialog,
  Reiter "Zone Refresh", standardmäßig AUS): PoE-VIEW2 kann die lokale
  Client.txt des Spiels beobachten (rein lesend, Pfad muss selbst
  eingetragen werden) und lädt die offene Truhe/den Charakter sofort neu,
  sobald PoE einen Zonenwechsel meldet — GGGs Stash-API liefert neue
  Daten offenbar ohnehin erst danach, gezieltes Nachladen spart also
  Rate-Limit-Budget gegenüber reinem Zeit-Takt.
- Neuer Settings-Dialog (⚙-Button in der Toolbar) mit einem Reiter
  "Columns": welche Item-Tabellen-Spalten sichtbar sind und in welcher
  Reihenfolge lässt sich dort per Häkchen und Drag & Drop einstellen,
  zusätzlich zum bisherigen schnellen Ein/Aus-Schalter im
  Header-Rechtsklickmenü. Beide Wege teilen sich denselben gespeicherten
  Stand.
- Fenster lässt sich nicht mehr kleiner als 800x600 ziehen — darunter
  wurden Bedienelemente in der Toolbar (u. a. das Suchfeld) hinter einem
  Overflow-Pfeil versteckt.
- Doppelklick auf ein Item öffnet eine vergrößerte Ansicht: großes Icon
  und der vollständige Property-/Mod-Text ohne die Zeilen-Kürzung des
  kompakten Detail-Panels. Bei Divination Cards zeigt sie das echte
  Karten-Artwork (GGGs eigenes CDN) statt des für jede Karte identischen
  generischen Icons aus der Stash-API, mit einem dekorativen
  Pergament-Rahmen angelehnt an die bekannte Karten-Optik.
- Doppelklick auf einen Charakter öffnet eine Paperdoll: Ausrüstung als
  Puppenlayout (Helm, Waffen, Rüstung, Ringe, Gürtel, Handschuhe, Stiefel,
  Flaschen, ggf. Waffentausch-Set/Trinket) statt flacher Tabellenzeilen,
  inklusive Liste der Jewels im Passiv-Baum. Klick auf einen Slot zeigt das
  Item im Detail-Panel.
- Item-Tabelle startet jetzt voreingestellt aufsteigend nach Wert sortiert
  statt in roher API-Reihenfolge — Items mit unbekanntem oder geringem
  Preis ("wahrscheinlich Schrott") gruppieren sich dadurch von selbst oben.
  Ein Klick auf eine andere Spalte überschreibt die Voreinstellung wie
  jede normale Sortierung.
- Rate-Limit-Dashboard: jede Regel zeigt jetzt zusätzlich eine grobe
  Schätzung, wann der Zähler das nächste Mal sinkt ("12/30 · 300 s · next
  in ~2:19", immer mit "~" — GGGs Zähler sinkt blockweise statt gleitend
  pro Treffer, sobald zwei Absenkungen beobachtet wurden, ist ihr
  ungefährer Rhythmus gelernt). Kurz nach dem Start kann bauartbedingt
  minutenlang nichts sinken — ohne diese Angabe sah der stillstehende
  Zähler wie ein Hänger aus.
- "Load All Tabs" zeigt im Fortschrittsdialog einen Sekunden-Countdown bis
  zum nächsten Abruf ("Next tab in 8s") und, falls das Rate-Limit gerade
  bremst, dessen Restzeit statt scheinbaren Stillstands. Zusätzlich springt
  der Stash-Baum jeweils auf das gerade abgerufene Fach und klappt es auf.
- Neuer Refresh-Modus **Pause**: keinerlei Hintergrund-Anfragen. Manuelle
  Klicks, die ⟳-Buttons im Baum und "Load All Tabs" funktionieren
  unverändert und bekommen das volle Rate-Limit-Budget.
- Log: jede Rate-Limit-Antwort schreibt jetzt zusätzlich eine Zeile mit den
  rohen X-Rate-Limit-Werten je Regel plus dem gelernten Absenkungs-Takt.
  Diese Rohdaten haben belegt, dass GGGs Zähler blockweise statt gleitend
  sinkt, siehe FALLSTRICKE_UND_WORKAROUNDS.md #45.
- Preis-Anzeige über poe.ninja: neue **Value**-Spalte in der Item-Tabelle
  (Chaos-Wert × Stack, Anzeige in Chaos oder Divine je nach Höhe) sowie
  Gesamtwert der sichtbaren Items in der Statuszeile. Umfasst Currency,
  Fragmente, Uniques (inkl. 5-/6-Link-Preise), Gems (exakt nach
  Level/Qualität/Corrupted), Divination Cards, Scarabs, Essences, Fossils
  u. a. — bewusst ohne Rare-Item-Basispreise. Unbekannte Preise bleiben
  leer statt 0; Items unter einem Chaos werden dezent abgeblendet. Preise
  werden pro Liga bis zu 6 Stunden gecacht.
- `Item.sockets`/`Item.max_links` im Datenmodell (Grundlage der
  Link-genauen Unique-Preis-Zuordnung).
- Neue **Base**-Spalte in der Item-Tabelle (`item.baseType`, z. B. "Sun
  Plate", "Crimson Jewel") — anders als Name bei Uniques/Rares immer die
  reine Item-Basis statt eines Fantasienamens.
- Item-Detail-Panel zeigt jetzt Itemlevel, Charakter-Levelanforderung und
  Attributs-Anforderungen (Str/Dex/Int) sowie eine "Unidentified"-Markierung
  für unidentifizierte Items (neben "Corrupted").
- **Regex-Suche** (Umschalter ".*" neben dem Suchfeld, standardmäßig an):
  Die Suche versteht jetzt reguläre Ausdrücke wie PoEs eigene Truhensuche.
  Sockets stehen dafür in derselben Schreibweise im Suchindex wie im Spiel
  ("R-R-G"), sodass auf poe.re zusammengeklickte Muster unverändert
  funktionieren — etwa `r-r-g|r-g-r|g-r-r` für einen 3-Link mit zwei roten
  und einem grünen Socket oder `(-\w){5}` für 6-Links. Ein unfertiges
  Muster fällt still auf die normale Textsuche zurück.

## [0.2.0] - 2026-07-29

### Hinzugefügt

- Refresh-Modus-Dropdown (Auto / Single / Stash) in der Toolbar: Single
  hält gezielt die aktuell gewählte Zeile aktuell, Stash zyklisiert durch
  die ganze Truhe — beide in einem gleichmäßigen, aus den echten
  Rate-Limit-Regeln abgeleiteten Takt statt eines Bursts. Stash bevorzugt
  gefüllte Fächer, hängt aber nach jeder vollständigen Runde durch diese
  automatisch einen Check für das nächste noch leere Fach an (Häufigkeit
  passt sich an die Truhengröße an) — reihum der Fächerreihenfolge nach,
  sodass ein im Spiel nach vorne verschobenes Fach automatisch schneller
  wieder drankommt.
- Sichtbarer Countdown bis zum nächsten Auto-Refresh-Tick bzw. der Grund,
  warum er gerade pausiert (Rate-Limit, Token, archivierte Liga, …).
- Stash-Baum: Name-Spalte skaliert automatisch mit dem Panel, Anzahl- und
  Status-Spalte bleiben dadurch immer sichtbar.
- Stash-Baum: Kontextmenü bietet jetzt "Expand All"/"Collapse All" für
  den ganzen Baum, unabhängig vom angeklickten Fach.
- Stash-Baum: neue Pos.-Spalte zeigt die tatsächliche Position eines
  Fachs in der Truhen-Reihenfolge (leer bei Ordnern/Gruppen) — ein
  Zeilenheader-Äquivalent für Bäume, die (anders als die ItemList) keinen
  eigenen vertikalen Header kennen.
- Stash-Baum: Name-Spalte geladener Fächer wird nach Datenalter
  abgeblendet (aktuell < 1h normal, < 3h leicht, älter deutlicher),
  damit veraltete Fächer sofort auffallen. Das zuletzt aktualisierte Fach
  ist zusätzlich türkis markiert, bis das nächste Fach an der Reihe ist.
- Der Stash-Modus lädt nach jeder vollständigen Runde durch die Truhe
  zusätzlich einmal die Fach-**Liste** still nach — Umsortierungen, neue
  oder entfernte Fächer im Spiel werden dadurch automatisch erkannt, ohne
  auf einen manuellen Refresh oder Liga-Wechsel zu warten.
- Typ-Filter-Symbole (Toolbar) reagieren jetzt auf drei Gesten statt nur
  simplem An/Aus: ein Klick zeigt nur diesen einen Typ, Strg+Klick
  schaltet gezielt einen weiteren Typ dazu oder wieder raus, und
  Strg+Umschalt+Klick sowie Doppelklick zeigen wieder alle Typen.
- Summe der Stack-Größe der gerade sichtbaren (gefilterten) Items in der
  Statuszeile — reagiert live auf Suche, Spalten- und Typ-Filter. Erscheint
  nur, wenn genau ein Item-Name sichtbar ist (sonst wäre die Summe über
  verschiedene Item-Typen hinweg bedeutungslos).

### Geändert

- Oberfläche und README vollständig auf Englisch umgestellt (internationale
  Zielgruppe). Code-Kommentare und interne Doku bleiben Deutsch.
- Auto-Refresh reserviert nur noch 10 % statt 50 % des Rate-Limit-Budgets
  für manuelle Klicks.
- Ein Klick auf ein Fach im Single-/Stash-Modus löst keinen sofortigen
  Extra-Request mehr aus, sondern stellt das Fach an den Anfang der
  Abarbeitungsliste — es ist damit beim nächsten regulären Takt dran.
  Das kostet ein paar Sekunden, hält die Anfragerate aber konstant.
- "Load All Tabs" beginnt jetzt mit den ältesten bzw. noch nie geladenen
  Fächern statt mit der zufälligen Truhen-Reihenfolge — bricht man vorzeitig
  ab, sind die dringendsten Fächer schon durch.
- Stash-Baum standardmäßig breiter (340 statt 260px), damit Name-, Anzahl-,
  Status- und Pos.-Spalte ohne manuelles Nachziehen sichtbar sind;
  Fensterbreite entsprechend erhöht, damit die Toolbar-Suche nicht hinter
  "…" verschwindet.

### Behoben

- Rate-Limit-Dashboard und der Auto-Refresh-Zähler ("X von Y Stash-Tabs")
  konnten dauerhaft veraltet bzw. bei 0 hängen bleiben, obwohl im
  Hintergrund weiter aktualisiert wurde.
- Der gleichmäßige Refresh-Takt konnte kurzzeitig mit der Rate-Limit-Policy
  eines fremden Endpunkts statt der eigenen rechnen.
- Beim Programmstart lief ohne gültiges Token trotzdem eine Stash-Abfrage
  los und scheiterte mit HTTP 401. Ein solcher selbstverschuldeter 401
  verwarf zudem das gespeicherte Token, was einen erneuten Browser-Login
  erzwingen konnte.
- "Load All Tabs" lief nach rund 29 Fächern in die 300-Sekunden-
  Zwangspause. Es lädt jetzt im gleichmäßigen Takt (~11s pro Fach) einmal
  durch die ganze Truhe; der Refresh-Modus pausiert solange.
- Map- und Unique-Stash-Tabs wurden bei der Positionsnummer übergangen:
  sie selbst bekamen keine, während jede ihrer internen Sektionen eine
  eigene verbrauchte und alle folgenden Fächer verschob (in einer echten
  Truhe 923 statt 391 Positionen). Gezählt wird jetzt, was in der
  Truhen-Leiste tatsächlich einen Platz belegt.
- Derselbe Zähl-Fehler betraf auch den Auto-Refresh-Zähler in der
  Statuszeile ("X of Y stash tabs updated") — Y zeigte die aufgeblähte
  Zahl ladbarer Einheiten (939) statt der tatsächlichen Fächer-Anzahl.
- Die Reihenfolge im Stash-Baum wich sichtbar von der im Spiel ab: Fächer,
  die im Spiel in einem Ordner liegen, standen auf der obersten Ebene und
  schoben sich zwischen die echten Fächer, während die Ordner leer blieben
  (in einer echten Truhe 165 statt 44 Einträge oben). Ordner-Inhalte hängen
  jetzt in ihrem Ordner, auch ohne ihn vorher anzuklicken.
- Nach dem Öffnen eines Ordners konnten dessen Fächer doppelt im Baum
  stehen — einmal oben, einmal im Ordner (in einer Liga 47 Fächer).
- Und ein drittes Mal denselben Fehler: der Fortschrittsbalken von
  "Load All Tabs" zeigte z. B. "58/561" statt "58/391" — mehrere
  Map-/Unique-Sektionen desselben Fachs zählten als mehrere Tabs statt
  als einer.
- Der Stash-Modus konnte sich in eine endlose Kette von 300-Sekunden-
  Zwangspausen aufschaukeln: nach einer Pause feuerten zwei Requests
  direkt hintereinander, was die nächste Pause auslöste. Der Takt zählt
  jetzt ab dem Eintreffen der Antwort statt ab dem Absenden und hält
  zusätzlich einen Request Sicherheitsabstand zur Sperrschwelle.
- Die Suche fand Implicit-Mods nicht — nur explicitMods flossen in den
  Suchindex ein, obwohl implicitMods im Datenmodell längst vorhanden war.
- Die Suche filterte bei jedem Tastendruck sofort — bei einem liga-weiten
  Aggregat mit mehreren zehntausend Items (z. B. "All Tabs" oder "*")
  spürbar langsam. Der Zeilen-Filter läuft jetzt gedämpft (350ms nach dem
  letzten Tastendruck).
- Die neue Stack-Summen-Anzeige (siehe oben) konnte bei einer Suche über
  ein liga-weites Aggregat mit stark verstreuten Treffern eine
  Zwangspause von mehreren Minuten auslösen — pro betroffener Zeile lief
  eine eigene Neuberechnung über die komplette sichtbare Menge statt
  einmal pro Sucheingabe.
- Bei sehr großen Ligen (deutlich mehr Fächer/Items als üblich) baute die
  Suche beim ersten Tastendruck das komplette ungefilterte Aggregat auf,
  bevor überhaupt gefiltert wurde — je nach Größe mehrere Sekunden
  Verzögerung, die kein Dämpfer beheben konnte. Oberhalb von 50.000 Items
  läuft die Suche jetzt "on demand": Sanduhr statt Live-Filterung, das
  Ergebnis erscheint, sobald man kurz aufhört zu tippen.

## [0.1.0] - 2026-07-25

Erste veröffentlichte Version.

### Hinzugefügt

- Login per OAuth2 (PKCE) direkt gegen die offizielle GGG-API, Access-
  Token im Windows Credential Manager.
- Rate-Limit-Manager mit Live-Dashboard (Regeln, Auslastung, Sperren).
- Stash-Baum mit Ordnern, Spezial-Tabs (Map-/Unique-Stash) automatisch
  nach Sektion bzw. Kategorie gruppiert.
- Item-Tabelle mit Icon, Herkunfts-Fach, Position (Tab-Nummer und
  Gitter-Koordinate), Name, Typ, Level, Qualität, Stack-Größe, iLvl,
  Anforderungen (Level, Str, Dex, Int) und Mods.
- Spalten-Filter mit Vergleichsausdrücken per Rechtsklick auf den
  Spaltenkopf.
- Liga-weite Suche über alle geladenen Fächer und Charaktere, mit `*` als
  Platzhalter für den vollständigen Export.
- Typ-Filter für Normal, Magic, Rare, Unique, Gem, Currency, Divination
  Card und Sonstige als farbige Checkboxen.
- Charakter-Ansicht: Ausrüstung und Inventar in derselben Tabelle wie
  Stash-Items, mit eigenem Auto-Refresh und manuellem Aktualisieren.
- CSV-Export der aktuell sichtbaren, gefilterten Items.
- Automatischer Hintergrund-Refresh für das geöffnete Fach oder den
  angezeigten Charakter, ergänzt um einen langsamen Durchlauf über die
  übrigen Fächer, ohne das Rate-Limit-Budget für manuelle Abfragen
  aufzubrauchen.
- Offline-Betrieb: zeigt bei GGG-Wartung oder fehlender Verbindung den
  zuletzt bekannten Cache-Stand, sichtbar als solcher markiert.
- Erkennung archivierter Ligen, um Datenverlust durch Abrufversuche gegen
  nicht mehr erreichbare Liga-Endpunkte zu vermeiden.
- Persistenter Daten-Cache über Neustarts hinweg sowie Icon-Cache.
- Rohdaten-Viewer je Stash-Tab.

Die technischen Hintergründe einzelner Entscheidungen stehen in
[FALLSTRICKE_UND_WORKAROUNDS.md](FALLSTRICKE_UND_WORKAROUNDS.md).

[Unveröffentlicht]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.11.2...HEAD
[0.11.2]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.11.1...v0.11.2
[0.11.1]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/peterm2024/PoE-VIEW2/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/peterm2024/PoE-VIEW2/releases/tag/v0.1.0
