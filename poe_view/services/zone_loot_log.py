"""Was in welcher Zone ins Inventar gewandert ist — die Rohdaten zur
Lukrativität (§4.56.6).

Peter, 2026-09-26: "Evtl. sogar die Lukrativität der Zone (soweit das
möglich ist, hängt ja auch von den Map-Mods ab) anhand des Loots." Und
einen Tag später, auf die Rückfrage, woran sie sich überhaupt messen
ließe: "Ich denke aus der Sicht eines typischen PoE-Spielers wird die
Lukrativität in Chaos gemessen. Aus meiner Sicht, SSF Ruthless, wird die
Lukrativität in Währung, Blue- und Yellow-Items gemessen. Natürlich auch
in XP/h. Sozusagen Itemdichte und Monsterdichte. Aber beides hängt von
vielem ab. Einfach mal beobachten."

Genau das tut diese Datei: **beobachten, nicht bewerten.** Eine Zeile je
Veröffentlichung, mit der Zone daneben — Zählungen nach Seltenheit, die
Währung im Klartext, der Chaos-Wert für die geläufige Sicht und der
Erfahrungs-Zuwachs für die Monsterdichte. Was davon eine brauchbare
Kennzahl ergibt, entscheidet die Auswertung in ein paar Wochen, nicht
diese Datei.

**Warum die Zone daneben überhaupt steht — und welche.** Peters Vermutung
war: "Wir bekommen ja unmittelbar nach dem Auftauchen aus der Map die
Zonenwechsel-Aktualisierung von GGG, evtl. können wir das auch benutzen.
Aber ist trotzdem nicht zu 100 % sicher." An seinem echten Programmlog
nachgezählt (287 beobachtete Inventar-Änderungen über vier Logdateien):

| Abstand zum Zonenwechsel | Anteil aller Änderungen | nur Zuwächse |
|---|---|---|
| gleichzeitig (0 s) | 66 % | 62 % |
| ≤ 60 s | 78 % | 74 % |
| ≤ 300 s | 89 % | 83 % |

Die Vermutung stimmt also — mit einem Haken, den erst die Zonennamen
zeigen: Von den 108 Zuwächsen unmittelbar nach einem Wechsel landeten
**95 im Hideout**, sieben in Sarn. Die Beute gehört damit fast nie der
Zone, in der sie auftaucht, sondern der Zone davor.

Daraus folgt die Zuordnungsregel, und sie ist dieselbe, die die XP-Rate
schon benutzt (§_XpWatch): **Eine Veröffentlichung kurz nach einem
Zonenwechsel berichtet über die Zone, die gerade VERLASSEN wurde; eine
spätere über die aktuelle.** Sie deckt beide Richtungen ab, ohne
Sonderfall:

- Map → Hideout, Zuwachs gleichzeitig → die Map hat ihn geliefert.
- Hideout → Map, Zuwachs gleichzeitig → er kam aus der Truhe, nicht von
  Monstern. Die Zeile fällt weg, weil eine Ruhezone nichts droppt.
- Zuwachs mitten in der Map (real: +16 nach 408 s in Phantasmagoria) →
  die laufende Zone.

**Was unsicher bleibt und deshalb nicht weggerechnet wird:** Was
zwischen zwei Abrufen ins Inventar kommt, kann gedroppt, gekauft,
gehandelt oder aus der Truhe geholt sein — die API sagt nur, dass es da
ist. Die 26 % Zuwächse ohne Zonenwechsel in der Nähe werden der
laufenden Zone zugerechnet, obwohl ein Teil davon Handel sein dürfte. Die
Spalte ``trigger`` hält beide Fälle auseinander, damit sich die Frage
später an den Daten statt an einer Annahme klären lässt.

**Zwei Zeitspalten, und nur eine davon ist ein Nenner.** ``seconds``
ist die Verweildauer in der Zone, ``interval`` der Abschnitt, den diese
eine Zeile abdeckt. Bei mehreren Veröffentlichungen in derselben Zone
wächst die erste über die zweite hinweg — wer aus ihr eine Rate bildet,
zählt dieselbe Zeit mehrfach. Peters erste fünf Zeilen zeigten das
sofort: 260 s und 324 s für dieselbe Map, die 324 enthielten die 260.
Für XP/h und Items/h gilt deshalb ``interval``.

**Sie läuft nur bei uns.** In der ausgelieferten .exe bleibt sie still
(§``enabled``) — eine Mitschrift, aus der noch keine Anzeige geworden
ist, hat auf fremden Rechnern nichts zu suchen. Für die Messung an
Peters echten Spielabenden schaltet ``POEVIEW_ZONE_LOOT_LOG=1`` sie in
der .exe wieder ein.

**Karten zählen als das, was sie sind** — eine gefundene Karte ist ein
normales, magisches oder seltenes Item und steht in dessen Spalte. Ein
eigener Eimer dafür wäre geraten (am Item-Rohdatum hängt kein sicheres
Merkmal, das nicht auch Nicht-Karten träfe); wer sie braucht, findet sie
in einer späteren Auswertung über die Basistypen.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from poe_view import config
from poe_view.api.models import Item

log = logging.getLogger(__name__)

# Die Eimer, in die eine Veröffentlichung sortiert wird. Peters Worte
# ("Währung, Blue- und Yellow-Items") sind ``currency``/``magic``/``rare``;
# die übrigen kosten nichts und beantworten die Nachfrage, bevor sie
# gestellt wird.
BUCKETS = ("normal", "magic", "rare", "unique", "gem", "currency", "card", "other")

# frameType → Eimer (``models.FRAME_TYPE_NAMES``). Relikt (9) und Foil
# (10) sind Spielarten des Uniques und zählen als solches; Quest (7) und
# Prophecy (8) fallen unter ``other``.
_BUCKET_OF_FRAME = {0: "normal", 1: "magic", 2: "rare", 3: "unique",
                    4: "gem", 5: "currency", 6: "card", 9: "unique",
                    10: "unique"}

FIELDNAMES = [
    "timestamp", "character", "league",
    "zone", "area_id", "instance", "level", "trigger", "seconds", "interval",
    "experience", "experience_gain",
    *BUCKETS, "chaos", "currency_detail",
]

# Ab wann wird die Mitschrift beiseitegelegt? Eine Zeile wiegt rund 200
# Bytes, eine Spielstunde bringt gut 60 — fünf Megabyte reichen für
# mehrere hundert Spielstunden. Die Grenze steht trotzdem da: Gemessen
# wird über Wochen, und eine Datei, die nur wächst, ist ein Fehler auf
# Raten.
_MAX_BYTES = 5_000_000


# Umgebungsvariable, die die Entscheidung unten überstimmt —
# "1"/"true"/… schaltet ein, "0"/"false" aus (dasselbe Muster wie
# ``gem_xp_log._ENABLE_ENV``).
_ENABLE_ENV = "POEVIEW_ZONE_LOOT_LOG"
_OFF_VALUES = frozenset({"", "0", "false", "no", "off", "nein"})


def enabled() -> bool:
    """Läuft die Mitschrift überhaupt?

    Peter, 2026-09-27: "Die Beute-Mitschrift wäre ja im Release mit
    dabei, obwohl das rein für das Development ist." Richtig — solange
    keine Anzeige daraus geworden ist, schreibt sie eine Datei, mit der
    niemand außer uns etwas anfangen kann. Deshalb dieselbe Regel wie
    bei der Gem-Mitschrift (§``gem_xp_log.enabled``): Aus dem Quellcode
    heraus läuft sie von selbst mit, in der gepackten .exe bleibt sie
    still, niemand muss vor einem Release daran denken.

    ``POEVIEW_ZONE_LOOT_LOG`` überstimmt beides — und das ist hier
    nicht der Randfall, sondern der Normalfall: Gemessen werden soll an
    Peters echten Spielabenden, und die spielt er mit der .exe. Ohne
    diesen Schalter gäbe es nie Daten, und die Frage "Spalte oder
    nicht?" bliebe für immer offen."""
    override = os.environ.get(_ENABLE_ENV)
    if override is not None:
        return override.strip().lower() not in _OFF_VALUES
    return not config.RUNNING_AS_EXE


def log_path() -> Path:
    """Funktion statt Konstante — ``config.LOG_DIR`` bei Importzeit
    einzufrieren, ließe Tests in Peters echtes Datenverzeichnis schreiben
    (CLAUDE.md, "Tests"; derselbe Grund wie bei ``gem_xp_log.log_path``)."""
    return config.LOG_DIR / "zone-loot-log.csv"


class Tally(NamedTuple):
    """Was eine Veröffentlichung an Zuwachs gebracht hat."""

    counts: dict[str, int]
    chaos: float
    currency_detail: str

    @property
    def empty(self) -> bool:
        return not any(self.counts.values())


def _bucket(item: Item) -> str:
    return _BUCKET_OF_FRAME.get(item.frameType, "other")


def tally(added: list[Item], stack_gains: list[tuple[Item, int]],
          price_index=None) -> Tally:
    """Zuwachs sortieren: neu aufgetauchte Items UND gewachsene Stapel.

    **Der zweite Teil ist der wichtigere.** Währung landet meist auf einem
    Stapel, den es schon gibt — ein Chaos Orb mehr ist keine
    Item-Neuheit, sondern ``stackSize`` 12 → 13. Ohne die Stapel-Zuwächse
    wäre ausgerechnet die Größe unsichtbar, die Peter zuerst genannt hat.
    Gezählt wird bei Währung die STÜCKZAHL, nicht der Stapel: Zwei Chaos
    Orbs sind zwei, egal ob sie zusammen ankamen.

    Schrumpfende Stapel gehen nicht ein. Sie sind ein Abgang (ausgegeben,
    in die Truhe gelegt) und haben in einer Ertragsrechnung nichts
    verloren — ein negativer Eintrag würde eine Zone dafür bestrafen,
    dass in ihr gecraftet wurde."""
    counts = dict.fromkeys(BUCKETS, 0)
    chaos = 0.0
    waehrung: dict[str, int] = {}
    for item in added:
        eimer = _bucket(item)
        menge = (item.stackSize or 1) if eimer == "currency" else 1
        counts[eimer] += menge
        if eimer == "currency":
            waehrung[item.display_name] = waehrung.get(item.display_name, 0) + menge
        chaos += _chaos(item, menge, price_index)
    for item, delta in stack_gains:
        if delta <= 0:
            continue
        eimer = _bucket(item)
        counts[eimer] += delta
        if eimer == "currency":
            waehrung[item.display_name] = waehrung.get(item.display_name, 0) + delta
        chaos += _chaos(item, delta, price_index)
    detail = "; ".join(f"{name} {menge}" for name, menge in sorted(waehrung.items()))
    return Tally(counts, chaos, detail)


def _chaos(item: Item, menge: int, price_index) -> float:
    """Chaos-Wert, sofern poe.ninja ihn kennt — sonst nichts.

    Ein unbekannter Preis ist ausdrücklich kein Wert von 0 (FALLSTRICKE
    #39): In SSF Ruthless, wo Peter spielt, kennt poe.ninja die halbe
    Liga nicht, und eine Summe, die fehlende Preise als wertlos verbucht,
    wäre systematisch zu niedrig. Die Spalte ist deshalb eine
    UNTERGRENZE, und die Zählungen daneben sind das, worauf man sich
    verlassen kann."""
    if price_index is None:
        return 0.0
    preis = price_index.price_for(item)
    return preis * menge if preis else 0.0


class Row(NamedTuple):
    """Eine Zeile der Mitschrift: eine Veröffentlichung, einer Zone
    zugerechnet."""

    character: str
    league: str
    zone: str
    area_id: str
    instance: str
    level: int
    trigger: str
    # Die ganze Verweildauer in der Zone bis zu diesem Zeitpunkt.
    seconds: float
    # **Der Abschnitt, den DIESE Zeile abdeckt** — und der einzige
    # Nenner, mit dem man rechnen darf. ``seconds`` waechst ueber
    # mehrere Veroeffentlichungen derselben Zone hinweg; wer damit eine
    # Rate bildet, zaehlt dieselbe Zeit mehrfach. Real in Peters ersten
    # fuenf Zeilen aufgetreten: zwei Veroeffentlichungen derselben Map
    # mit 260 s und 324 s, wobei die 324 die 260 enthielten. Der
    # Abschnitt beginnt beim SPAETEREN von Zonenbetreten und voriger
    # Veroeffentlichung — dieselbe Regel wie bei der XP-Rate
    # (``MainWindow._interval_seconds``).
    interval: float
    experience: int
    experience_gain: int


def append(row: Row, counted: Tally, path: Path | None = None) -> None:
    """Eine Zeile anhängen. Der Aufrufer entscheidet, ob es etwas zu
    schreiben gibt — eine Veröffentlichung ohne Beute ist trotzdem eine
    Aussage (die Zone hat in dieser Zeit nichts gegeben), eine bloße
    Abfrage ohne Veröffentlichung dagegen nicht.

    Tut gar nichts, wenn die Mitschrift abgeschaltet ist (§``enabled``).
    Die Prüfung sitzt hier und nicht an der Aufrufstelle im Hauptfenster:
    Wer sie ausschalten will, soll das an EINER Stelle finden — dieselbe
    Begründung wie bei ``gem_xp_log.append``."""
    if not enabled():
        return
    pfad = path or log_path()
    zeile = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "character": row.character,
        "league": row.league,
        "zone": row.zone,
        "area_id": row.area_id,
        "instance": row.instance,
        "level": row.level or "",
        "trigger": row.trigger,
        "seconds": f"{row.seconds:.0f}",
        "interval": f"{row.interval:.0f}",
        "experience": row.experience or "",
        "experience_gain": row.experience_gain,
        **counted.counts,
        "chaos": f"{counted.chaos:.2f}" if counted.chaos else "",
        "currency_detail": counted.currency_detail,
    }
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        _retire_stale(pfad)
        neu = not pfad.exists()
        with pfad.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if neu:
                writer.writeheader()
            writer.writerow(zeile)
    except OSError as fehler:
        log.warning("Zonen-Beute nicht mitschreibbar: %s", fehler)


def _retire_stale(path: Path) -> None:
    """Eine Mitschrift mit anderen Spalten oder über der Größengrenze
    beiseitelegen, statt sie unbrauchbar zu machen.

    Beim Spaltenwechsel ist das der Unterschied zwischen "der alte Stand
    bleibt auswertbar" und "ab hier stehen Werte unter falschen
    Überschriften, rückwirkend auch für den Teil, der stimmte" — dieselbe
    Lehre wie bei ``gem_xp_log._retire_foreign_header``."""
    if not path.exists():
        return
    try:
        zu_gross = path.stat().st_size >= _MAX_BYTES
        with path.open("r", encoding="utf-8", newline="") as f:
            kopf = next(csv.reader(f), None)
    except OSError:
        return
    if kopf == FIELDNAMES and not zu_gross:
        return
    beiseite = path.with_name(
        f"{path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    path.rename(beiseite)
    log.info("Zonen-Beute-Mitschrift beiseitegelegt (%s): %s",
             "zu groß" if zu_gross else "andere Spalten", beiseite.name)
