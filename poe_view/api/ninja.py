"""poe.ninja-Preis-Client (docs/ARCHITEKTUR.md §4.14).

Liefert Chaos-Preise für Items einer Liga, best-effort: jeder Fehler
(Netzwerk, eine erneute API-Umstellung wie am 2026-06-28 — siehe
FALLSTRICKE_UND_WORKAROUNDS.md #41) darf höchstens zu fehlenden Preisen
führen, nie zum Absturz. Kein Auth nötig, andere Basis-URL als die
GGG-API (``poe_view.api.client``).

Umfang bewusst ohne "BaseType" (Rare-Item-Basen) — mit Abstand die
teuerste Kategorie beim Abruf und ohne iLvl-/Influence-Bewertung
ohnehin unzuverlässig (Entscheidung siehe ToDo.md).
"""

from __future__ import annotations

import logging

import httpx

from poe_view.api.models import Item, gem_level, gem_quality

log = logging.getLogger(__name__)

_BASE_URL = "https://poe.ninja/poe1/api/economy"

_CURRENCY_TYPES = ("Currency", "Fragment")
_ITEM_TYPES = (
    "Incubator", "Beast", "UniqueMap", "Map", "UniqueJewel", "UniqueFlask",
    "UniqueWeapon", "UniqueArmour", "UniqueAccessory", "SkillGem",
    "ClusterJewel", "Vial", "Invitation", "UniqueRelic",
)
_EXCHANGE_TYPES = (
    "DivinationCard", "Oil", "Scarab", "Fossil", "Resonator", "Essence",
    "HelmetEnchant", "DeliriumOrb", "Omen", "AllflameEmber", "Artifact", "Tattoo",
)

# poe.ninja führt nur 5-/6-Link separat; alles andere (0-4 Links oder gar
# keine Sockets) läuft unter dem Basis-Preis (Bucket None). Ein Item mit
# z. B. 6 Links, für das kein 6-Link-Preis existiert, bekommt den nächst-
# niedrigeren bekannten Bucket statt gar keinen Preis.
_LINK_FALLBACK_ORDER = {6: (6, 5, None), 5: (5, None), None: (None, 5, 6)}


class PriceIndex:
    """Preis-Nachschlage für eine Liga. Wird über ``fetch_price_index``
    befüllt, nie direkt von außen — die drei internen Dicts entsprechen
    den drei Arten, wie poe.ninja Preise pro Name gruppiert (einfach,
    Gem-Variante, Link-Bucket)."""

    def __init__(self) -> None:
        # Chaos Orb ist die Referenzwährung, gegen die alle anderen
        # chaosEquivalent/chaosValue-Felder umgerechnet sind — poe.ninja
        # listet es deshalb nicht gegen sich selbst (real geprüft: kein
        # "Chaos Orb"-Eintrag in der Currency-Route). Ohne diesen Seed
        # würde Chaos Orb fälschlich als "Preis unbekannt" erscheinen.
        self._simple: dict[str, float] = {"Chaos Orb": 1.0}
        self._gems: dict[str, list[tuple[int | None, int, bool, float]]] = {}
        self._links: dict[str, dict[int | None, float]] = {}

    @property
    def divine_rate(self) -> float | None:
        """Chaos-Gegenwert eines Divine Orb — Basis für die Chaos/Divine-
        Umschaltung in der Anzeige (siehe ``item_table.format_chaos_value``)."""
        return self._simple.get("Divine Orb")

    @property
    def is_empty(self) -> bool:
        """True, wenn außer der eingebauten Chaos-Orb-Referenz keine
        einzige echte Preiszeile ankam.

        Zwei sehr unterschiedliche Ursachen sehen für den Aufrufer gleich
        aus: ein transienter Abruf-Fehler (kurz retry-würdig) ODER eine
        Liga, die poe.ninja dauerhaft gar nicht führt — reale Prüfung
        gegen poe.ninjas eigene ``/economy/leagues``-Liste ergab, dass
        private/SSF-Ligen wie "Solo Self-Found" dort gar nicht auftauchen:
        ohne Spieler-Handel gibt es keine Handelsaktivität, aus der sich
        Preise ableiten ließen (FALLSTRICKE #49). ``price_cache`` nutzt
        dieses Flag für eine kürzere TTL, damit ein solches Ergebnis nicht
        die vollen 6h als vermeintlicher Erfolg festgehalten wird."""
        return len(self._simple) <= 1 and not self._gems and not self._links

    def price_for(self, item: Item) -> float | None:
        """Chaos-Wert EINES Items, ohne stackSize-Multiplikation — das
        macht der Aufrufer. ``None`` heißt unbekannt, nie 0 (ein
        unbekannter Preis ist etwas anderes als ein wertloses Item,
        siehe FALLSTRICKE #39 zur Stack-Summe)."""
        name = item.display_name
        if name in self._gems:
            return self._gem_price(item, self._gems[name])
        if name in self._links:
            return self._link_price(item, self._links[name])
        return self._simple.get(name)

    def _gem_price(self, item: Item,
                    variants: list[tuple[int | None, int, bool, float]]) -> float | None:
        """Exakter Abgleich über Level/Qualität/Corrupted — poe.ninja
        listet nur eine Handvoll Varianten pro Gem-Name, und die
        Preisspanne zwischen ihnen kann einen zweistelligen Faktor
        betragen. Kein Näherungstreffer: lieber kein Preis als ein um
        eine Größenordnung falscher."""
        level_str = gem_level(item)
        level = int(level_str) if level_str and level_str.isdigit() else None
        quality_str = gem_quality(item)
        quality = 0
        if quality_str:
            digits = quality_str.strip("+%")
            if digits.isdigit():
                quality = int(digits)
        for v_level, v_quality, v_corrupted, chaos in variants:
            if v_level == level and v_quality == quality and v_corrupted == item.corrupted:
                return chaos
        return None

    def _link_price(self, item: Item, buckets: dict[int | None, float]) -> float | None:
        links = item.max_links
        requested = 6 if links >= 6 else 5 if links >= 5 else None
        for bucket in _LINK_FALLBACK_ORDER[requested]:
            if bucket in buckets:
                return buckets[bucket]
        return None


def fetch_price_index(league: str, http: httpx.Client | None = None) -> PriceIndex:
    """Preise aller unterstützten Kategorien einer Liga abrufen und
    mergen. Best-effort über die Kategorien hinweg: eine fehlgeschlagene
    Kategorie hinterlässt nur eine Lücke im Index, kein Abbruch."""
    owns_client = http is None
    client = http or httpx.Client(timeout=20.0, headers={
        "User-Agent": "PoE-VIEW2-price-lookup (+https://github.com/peterm2024/PoE-VIEW2)",
    })
    index = PriceIndex()
    try:
        for item_type in _CURRENCY_TYPES:
            _merge_currency(index, client, league, item_type)
        for item_type in _ITEM_TYPES:
            _merge_item(index, client, league, item_type)
        for item_type in _EXCHANGE_TYPES:
            _merge_exchange(index, client, league, item_type)
    finally:
        if owns_client:
            client.close()
    return index


def _get(http: httpx.Client, path: str, league: str, item_type: str) -> dict | None:
    try:
        resp = http.get(f"{_BASE_URL}/{path}", params={"league": league, "type": item_type})
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError:
        log.warning("poe.ninja-Preisabruf fehlgeschlagen: %s type=%s league=%s",
                   path, item_type, league, exc_info=True)
        return None


def _merge_currency(index: PriceIndex, http: httpx.Client, league: str, item_type: str) -> None:
    data = _get(http, "stash/current/currency/overview", league, item_type)
    if not data:
        return
    for line in data.get("lines", []):
        name = line.get("currencyTypeName")
        chaos = line.get("chaosEquivalent")
        if name and chaos is not None:
            index._simple[name] = chaos


def _merge_exchange(index: PriceIndex, http: httpx.Client, league: str, item_type: str) -> None:
    data = _get(http, "exchange/current/overview", league, item_type)
    if not data:
        return
    names = {entry["id"]: entry["name"] for entry in data.get("items", [])
             if "id" in entry and "name" in entry}
    for line in data.get("lines", []):
        name = names.get(line.get("id"))
        chaos = line.get("primaryValue")
        if name and chaos is not None:
            index._simple[name] = chaos


def _merge_item(index: PriceIndex, http: httpx.Client, league: str, item_type: str) -> None:
    data = _get(http, "stash/current/item/overview", league, item_type)
    if not data:
        return

    if item_type == "SkillGem":
        for line in data.get("lines", []):
            name = line.get("name")
            chaos = line.get("chaosValue")
            if not name or chaos is None:
                continue
            variant = (line.get("gemLevel"), line.get("gemQuality") or 0,
                      bool(line.get("corrupted")), chaos)
            index._gems.setdefault(name, []).append(variant)
        return

    # Erst pro Name gruppieren, DANN entscheiden ob link-bewusst — sonst
    # könnte je nach Zeilen-Reihenfolge der Basis-Preis eines Namens in
    # _simple landen und der 5-/6-Link-Preis derselben Zeile getrennt
    # davon in _links, sodass price_for() den Basis-Preis nie wiederfindet.
    groups: dict[str, list[tuple[int | None, float]]] = {}
    link_aware: set[str] = set()
    for line in data.get("lines", []):
        name = line.get("name")
        chaos = line.get("chaosValue")
        if not name or chaos is None:
            continue
        groups.setdefault(name, []).append((line.get("links"), chaos))
        if "links" in line:
            link_aware.add(name)

    for name, entries in groups.items():
        if name in link_aware:
            index._links.setdefault(name, {}).update(dict(entries))
        else:
            index._simple[name] = entries[-1][1]
