"""Bäume aus Path-of-Building-Builds lesen (§4.60.9).

Peter, 2026-10-08: Pohx' Build-Guide verweist auf einen pobb.in-Link mit
neun Bäumen (je Levelabschnitt) und einem Info-Baum — "Evtl. sollten wir
die pobb.in Unterstützung hinzufügen".

Ein PoB-Code ist das Build-XML, zlib-gepackt und URL-sicher Base64-
kodiert. Darin steht je Baum ein ``<Spec>`` mit Titel und — von PoB
selbst geschrieben — der Planer-URL des Baums, die ``passive_tree.
decode_url`` schon liest (Masteries und Cluster-Knoten inklusive).
Fehlt sie, wird der Baum aus den Attributen des ``<Spec>`` gebaut.

pobb.in und pastebin.com liefern den Code unter einer Roh-Adresse; das
ist der einzige Netzabruf hier, und nur auf Wunsch des Nutzers.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import zlib
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx

from poe_view import __version__
from poe_view.services import passive_tree
from poe_view.services.passive_tree import TreeLink, TreeLinkError

log = logging.getLogger(__name__)

# Woher sich ein Code holen lässt: Seite → Roh-Adresse.
_QUELLEN = (
    (re.compile(r"^(?:https?://)?(?:www\.)?pobb\.in/(?:u/[^/\s]+/)?([A-Za-z0-9_-]+)/?(?:raw)?/?$"),
     "https://pobb.in/{}/raw"),
    (re.compile(r"^(?:https?://)?(?:www\.)?pastebin\.com/(?:raw/)?([A-Za-z0-9]+)/?$"),
     "https://pastebin.com/raw/{}"),
)
# Obergrenze für das entpackte XML: Pohx' Build sind 270 KB; ein Code, der
# sich zu mehr aufbläst, ist kein Build (Schutz vor einer zlib-Bombe).
MAX_XML = 20 * 1024 * 1024
# PoB-Farbcodes in Titeln: ^1 … ^9 und ^xRRGGBB.
_FARBE = re.compile(r"\^(?:x[0-9A-Fa-f]{6}|[0-9])")


class PobImportError(ValueError):
    """Kein lesbarer PoB-Build (oder der Abruf schlug fehl)."""


@dataclass
class BuildTree:
    """Ein Baum aus einem Build: Titel (ohne Farbcodes), der Baum und ob
    PoB ihn als aktiven markiert hat."""
    title: str
    link: TreeLink
    active: bool = False


def remote_url(text: str) -> str | None:
    """Roh-Adresse, wenn ``text`` ein pobb.in- oder pastebin-Link ist."""
    text = text.strip()
    for muster, roh in _QUELLEN:
        treffer = muster.match(text)
        if treffer:
            return roh.format(treffer.group(1))
    return None


USER_AGENT = f"PoE-VIEW2/{__version__} (+https://github.com/peterm2024/PoE-VIEW2)"


def _http() -> httpx.Client:
    return httpx.Client(timeout=20.0, follow_redirects=True,
                        headers={"User-Agent": USER_AGENT})


def fetch_code(url: str, http: httpx.Client | None = None) -> str:
    """Den Code von der Roh-Adresse holen."""
    client = http or _http()
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        log.warning("PoB-Import: Abruf von %s fehlgeschlagen: %s", url, exc)
        raise PobImportError(f"could not reach {httpx.URL(url).host}") from exc
    finally:
        if http is None:
            client.close()
    if resp.status_code != 200:
        log.warning("PoB-Import: %s antwortete mit Status %s", url, resp.status_code)
        raise PobImportError(f"{httpx.URL(url).host} answered {resp.status_code}")
    return resp.text


def clean_title(title: str) -> str:
    """"Lvl 90 ^2Going Block Based ^7{6}" → "Lvl 90 Going Block Based {6}"."""
    return " ".join(_FARBE.sub("", title).split())


def decode_code(code: str) -> list[BuildTree]:
    """Die Bäume eines PoB-Codes, in der Reihenfolge des Builds."""
    roh = "".join(code.split())
    try:
        gepackt = base64.urlsafe_b64decode(roh + "=" * (-len(roh) % 4))
        entpacker = zlib.decompressobj()
        xml = entpacker.decompress(gepackt, MAX_XML)
    except (binascii.Error, ValueError, zlib.error) as exc:
        raise PobImportError("not a Path of Building code") from exc
    if entpacker.unconsumed_tail:
        raise PobImportError("build is too large")
    try:
        wurzel = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise PobImportError("not a Path of Building code") from exc
    baum = wurzel.find("Tree")
    if wurzel.tag != "PathOfBuilding" or baum is None:
        raise PobImportError("no passive tree in this build")
    aktiv_roh = str(baum.get("activeSpec") or "1")
    aktiv = int(aktiv_roh) if aktiv_roh.isdigit() else 1
    ergebnis = []
    for nummer, spec in enumerate(baum.findall("Spec"), start=1):
        try:
            link = _spec_link(spec)
        except TreeLinkError as exc:
            log.warning("PoB-Import: Baum %s übersprungen (%s)", nummer, exc)
            continue
        titel = clean_title(spec.get("title") or "") or f"Tree {nummer}"
        ergebnis.append(BuildTree(titel, link, active=nummer == aktiv))
    if not ergebnis:
        raise PobImportError("no readable passive tree in this build")
    return ergebnis


def _spec_link(spec: ElementTree.Element) -> TreeLink:
    """Der Baum eines ``<Spec>``: über die Planer-URL, die PoB mitschreibt,
    sonst aus den Attributen (Knoten, Masteries, Klasse)."""
    url = (spec.findtext("URL") or "").strip()
    if url:
        return passive_tree.decode_url(url)
    try:
        knoten = [int(k) for k in (spec.get("nodes") or "").split(",") if k.strip()]
        meisterung = {str(int(a)): int(b) for a, b in
                      re.findall(r"\{(\d+),(\d+)\}", spec.get("masteryEffects") or "")}
        klasse = int(spec.get("classId") or 0)
        aszendenz = int(spec.get("ascendClassId") or 0)
    except ValueError as exc:
        raise TreeLinkError("unreadable tree") from exc
    passives: dict = {"hashes": [k for k in knoten if k < 65536]}
    cluster = [k for k in knoten if k >= 65536]       # wie decode_url: über dem Versatz
    if cluster:
        passives["hashes_ex"] = cluster
    if meisterung:
        passives["mastery_effects"] = meisterung
    return TreeLink(klasse, aszendenz, passives)


def read(text: str, http: httpx.Client | None = None) -> list[BuildTree]:
    """Was der Nutzer eingefügt hat: pobb.in-/pastebin-Link oder Code."""
    url = remote_url(text)
    code = fetch_code(url, http) if url else text
    return decode_code(code)
