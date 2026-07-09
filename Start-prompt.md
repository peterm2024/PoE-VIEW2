Hallo! Ich arbeite an einem LabVIEW-Projekt namens "PoE-VIEW", einem Tool für die Path of Exile API. Ich möchte unsere Arbeit hier fortsetzen. Hier ist das komplette Briefing zum aktuellen Stand:

**Architektur & Netzwerk:**
- OAuth2 (PKCE) ist implementiert. Token-Management funktioniert.
- Wir nutzen einen persistenten HTTP-Client-Handle mit festen Headern (Auth & User-Agent).

**Datenverarbeitung (JSON):**
- Wir können Charaktere und Stash-Listen abrufen.
- Verschachtelte Stashes (Ordner & Kinder) werden rekursiv in ein Tree-Control geladen. Hex-Farben wandeln wir in U32 um.
- Item-Abfragen funktionieren. Besonderheit: Bei Gems parsen wir verschachtelte "properties"-Arrays, um "Level" und "Quality" zu finden, und zeigen sie in einer Multicolumn Listbox an.
- Item-Icons werden via HTTP heruntergeladen und als Picture Control angezeigt (inkl. lokalem Caching).

**Rate-Limit-Manager (Das Kernsystem):**
- Wir haben eine Functional Global Variable (FGV) gebaut, die das Rate-Limit steuert, damit GGG uns nicht sperrt (z. B. Limit: 10:15:60).
- Nach jedem GET-Request extrahieren wir "X-Rate-Limit-Policy", "X-Rate-Limit-Account" und "X-Rate-Limit-Account-State" aus dem Header.
- Diese Strings werden geparst und im Shift-Register der FGV gespeichert (Cluster mit MaxRequests, WindowSize, LockTime, CurrentCount, LastUpdate Timestamp).
- Vor jedem neuen Request rufen wir den Case "Check & Wait" der FGV auf. Dieser berechnet die maximale Wartezeit aller Regeln und pausiert den Thread per "Wait (ms)", falls ein Limit erreicht ist.
- Die FGV sendet per "User Event" Status-Updates an das Main-VI, wo Progress-Bars, LEDs und ein Countdown die Auslastung anzeigen. Das Parsing-Problem (falsches Mapping von Current/Max) ist bereits behoben.

**Release-Planung:**
- Das Programm ist für Open Source vorbereitet (Client Secret ist in externer Datei, Disclaimer ist vorhanden).

**Nächster Schritt:**
Wir haben die Basis-Infrastruktur komplett fertig. Ich möchte jetzt an den Features weiterarbeiten. Bist du bereit und hast du den Kontext verstanden?