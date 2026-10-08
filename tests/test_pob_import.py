"""Bäume aus Path-of-Building-Builds (§4.60.9): Code, pobb.in, Auswahl."""

from __future__ import annotations

import base64
import zlib

import httpx
import pytest

from poe_view.services import passive_tree as pt
from poe_view.services import pob_import as pi
from poe_view.services import tree_history as th
from tests.test_passive_tree import _ROH, _fenster


@pytest.fixture
def baum() -> pt.Tree:
    return pt.parse_tree(_ROH, ruthless=True)


@pytest.fixture(autouse=True)
def keine_offenen_meldungen(monkeypatch) -> None:
    """Eine unerwartete Meldung scheitert sofort — offscreen wartete sie
    sonst ewig auf einen Klick (in der Gegenprobe so hängen geblieben)."""
    from poe_view.ui import passive_tree_dialog as modul

    def unerwartet(*a, **k):
        raise AssertionError(f"unerwartete Meldung: {a[1:3]}")
    for art in ("warning", "question", "information", "critical"):
        monkeypatch.setattr(modul.QMessageBox, art, staticmethod(unerwartet))


def _code(specs: str, active: int = 1, wurzel: str = "PathOfBuilding") -> str:
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><{wurzel}><Build className="Marauder"/>'
           f'<Tree activeSpec="{active}">{specs}</Tree></{wurzel}>')
    return base64.urlsafe_b64encode(zlib.compress(xml.encode("utf-8"))).decode("ascii")


def _spec(baum, title: str, hashes: list[int], klasse: str = "Juggernaut", url: bool = True,
          **attr) -> str:
    link = pt.encode_url(baum, {"hashes": hashes}, klasse)
    attribute = " ".join(f'{k}="{v}"' for k, v in attr.items())
    inhalt = f"<URL>\n\t\t\t{link}\n\t\t</URL>" if url else ""
    return f'<Spec title="{title}" treeVersion="3_28" {attribute}>{inhalt}</Spec>'


def test_a_build_code_yields_its_trees_with_clean_titles(baum) -> None:
    """Pohx' Build: ein Info-Baum, dann einer je Levelabschnitt; Titel mit
    PoB-Farbcodes ("^2Going Block Based ^7{6}")."""
    code = _code(_spec(baum, "^1CHECK POB NOTES", [])
                 + _spec(baum, "Lvl 01-30 {1}", [10, 11])
                 + _spec(baum, "Lvl 90 ^2Going Block  Based ^x33FF77{6}", [10, 11, 12]), active=3)
    baeume = pi.decode_code(code)
    assert [b.title for b in baeume] == ["CHECK POB NOTES", "Lvl 01-30 {1}",
                                         "Lvl 90 Going Block Based {6}"]
    assert [b.active for b in baeume] == [False, False, True]
    assert pt.allocated(baeume[2].link.passives) == {10, 11, 12}
    assert pt.class_name_of(baum, baeume[2].link.class_index,
                            baeume[2].link.ascendancy_index) == "Juggernaut"
    # Zeilenumbrüche im eingefügten Code stören nicht.
    assert len(pi.decode_code(code[:40] + "\n  " + code[40:])) == 3


def test_without_url_the_tree_comes_from_the_spec_attributes(baum) -> None:
    """PoB schreibt die URL immer mit; fehlt sie doch, die Attribute — dort
    stehen Masteries als {Knoten,Effekt} und Cluster-Knoten über 65536."""
    code = _code(_spec(baum, "Bare", [], url=False, classId=1, ascendClassId=1,
                       nodes="10,11,12,65538", masteryEffects="{40,777},{41,779}"))
    link = pi.decode_code(code)[0].link
    assert (link.class_index, link.ascendancy_index) == (1, 1)
    assert link.passives == {"hashes": [10, 11, 12], "hashes_ex": [65538],
                             "mastery_effects": {"40": 777, "41": 779}}
    # Untitled: nummeriert.
    assert pi.decode_code(_code(_spec(baum, "", [10])))[0].title == "Tree 1"


@pytest.mark.parametrize("text", [
    "nonsense", "", base64.urlsafe_b64encode(b"not zlib at all").decode(),
    base64.urlsafe_b64encode(zlib.compress(b"<not xml")).decode(),
])
def test_garbage_is_not_a_build(text) -> None:
    with pytest.raises(pi.PobImportError):
        pi.decode_code(text)


def test_a_build_without_trees_or_of_another_kind_is_refused(baum) -> None:
    with pytest.raises(pi.PobImportError, match="no passive tree"):
        pi.decode_code(_code(_spec(baum, "x", [10]), wurzel="SomethingElse"))
    with pytest.raises(pi.PobImportError, match="no readable"):
        pi.decode_code(_code('<Spec title="broken"><URL>https://x/AAAA</URL></Spec>'))


def test_a_code_that_inflates_too_much_is_refused(baum, monkeypatch) -> None:
    """Schutz vor einer zlib-Bombe: höchstens MAX_XML entpackt."""
    code = _code(_spec(baum, "x" * 5000, [10]))
    monkeypatch.setattr(pi, "MAX_XML", 1000)
    with pytest.raises(pi.PobImportError, match="too large"):
        pi.decode_code(code)


@pytest.mark.parametrize("text, roh", [
    ("https://pobb.in/KMJMGblyFcI7", "https://pobb.in/KMJMGblyFcI7/raw"),
    ("pobb.in/KMJMGblyFcI7/", "https://pobb.in/KMJMGblyFcI7/raw"),
    (" https://pobb.in/KMJMGblyFcI7/raw ", "https://pobb.in/KMJMGblyFcI7/raw"),
    ("http://www.pobb.in/abc_D-9", "https://pobb.in/abc_D-9/raw"),
    ("https://pastebin.com/Xy12ab", "https://pastebin.com/raw/Xy12ab"),
    ("https://pastebin.com/raw/Xy12ab", "https://pastebin.com/raw/Xy12ab"),
    ("https://www.pathofexile.com/passive-skill-tree/AAAABgEA", None),
    ("https://pobb.in.evil.example/abc", None),
    ("eNrsvXt32", None),
])
def test_which_links_are_fetched(text, roh) -> None:
    assert pi.remote_url(text) == roh


def test_a_pobb_link_is_fetched_from_its_raw_address(baum) -> None:
    code = _code(_spec(baum, "Lvl 01-30", [10, 11]))
    gefragt = []

    def antwort(request: httpx.Request) -> httpx.Response:
        gefragt.append(str(request.url))
        return httpx.Response(200, text=code)

    with httpx.Client(transport=httpx.MockTransport(antwort)) as http:
        baeume = pi.read("https://pobb.in/KMJMGblyFcI7", http)
    assert gefragt == ["https://pobb.in/KMJMGblyFcI7/raw"]
    assert [b.title for b in baeume] == ["Lvl 01-30"]


@pytest.mark.parametrize("antwort, meldung", [
    (lambda r: httpx.Response(404, text="gone"), "answered 404"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)), "could not reach"),
])
def test_a_failed_fetch_says_why(antwort, meldung) -> None:
    with httpx.Client(transport=httpx.MockTransport(antwort)) as http:
        with pytest.raises(pi.PobImportError, match=meldung):
            pi.read("pobb.in/abc", http)


def test_our_own_client_names_the_program() -> None:
    """Das echte ``_http`` ersetzt die Autouse-Fixture; sein Kopf steht in
    ``USER_AGENT`` (Programm und Repo, keine Kontaktadresse)."""
    from poe_view import __version__
    assert pi.USER_AGENT == f"PoE-VIEW2/{__version__} (+https://github.com/peterm2024/PoE-VIEW2)"


def test_the_test_suite_never_reaches_pobb() -> None:
    """Die Autouse-Fixture sperrt das Netz: ohne eigenen Client ein Fehler."""
    with pytest.raises(pi.PobImportError, match="could not reach"):
        pi.read("https://pobb.in/KMJMGblyFcI7")


# --- Im Fenster ---------------------------------------------------------- #

def _antworten(modul, monkeypatch, *texte):
    werte = iter([(t, True) for t in texte])
    monkeypatch.setattr(modul.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: next(werte)))


def test_a_build_with_several_trees_becomes_several_configurations(qapp, baum,
                                                                   monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    from poe_view.ui.passive_tree_dialog import CONFIG
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    code = _code(_spec(baum, "^1INFO", []) + _spec(baum, "Lvl 01-30 {1}", [10, 11, 20])
                 + _spec(baum, "Lvl 31-40 {2}", [10, 11, 12, 14]), active=3)
    _antworten(modul, monkeypatch, code)
    gezeigt = []
    monkeypatch.setattr(dialog, "_choose_trees",
                        lambda b: gezeigt.append([x.title for x in b]) or b[1:])
    dialog._import_link()
    assert gezeigt == [["INFO", "Lvl 01-30 {1}", "Lvl 31-40 {2}"]]
    konfigs = th.configs(zeichen, "WitchOfPeter")
    assert set(konfigs) == {"Lvl 01-30 {1}", "Lvl 31-40 {2}"}
    assert pt.allocated(konfigs["Lvl 31-40 {2}"]["passives"]) == {10, 11, 12, 14}
    assert konfigs["Lvl 01-30 {1}"]["source"] == "pob" and konfigs["Lvl 01-30 {1}"]["level"] == 30
    assert dialog._selected() == (CONFIG, "Lvl 01-30 {1}") and gespeichert == [1]
    dialog.close()


def test_the_choice_preselects_trees_with_points(qapp, baum, monkeypatch) -> None:
    """Der Info-Baum (nur der Start) ist nicht vorgewählt."""
    from poe_view.ui import passive_tree_dialog as modul
    dialog, _zeichen, _ = _fenster(qapp, baum)
    baeume = pi.decode_code(_code(_spec(baum, "INFO", []) + _spec(baum, "A", [10, 11])
                                  + _spec(baum, "B", [10]), active=2))
    texte = []
    def zeigen(fenster):
        liste = fenster.findChild(modul.QListWidget)
        texte.extend(liste.item(i).text() for i in range(liste.count()))
        return modul.QDialog.DialogCode.Accepted
    monkeypatch.setattr(modul.QDialog, "exec", zeigen)
    assert [b.title for b in dialog._choose_trees(baeume)] == ["A", "B"]
    assert texte[1] == "A — Juggernaut, 2 points (active in Path of Building)"
    monkeypatch.setattr(modul.QDialog, "exec", lambda f: modul.QDialog.DialogCode.Rejected)
    assert dialog._choose_trees(baeume) == []
    dialog.close()


def test_existing_names_are_asked_for_and_duplicates_numbered(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    th.save_config(zeichen, "WitchOfPeter", "Same", {"hashes": [10]}, level=30, ruthless=True,
                   source="link")
    code = _code(_spec(baum, "Same", [10, 11]) + _spec(baum, "Same", [10, 11, 12]))
    monkeypatch.setattr(dialog, "_choose_trees", lambda b: b)
    fragen = []
    monkeypatch.setattr(dialog, "_ask", lambda titel, text: fragen.append(text) or False)
    _antworten(modul, monkeypatch, code)
    dialog._import_link()
    assert "1 of these names exist already (“Same”)" in fragen[0]
    assert pt.allocated(th.configs(zeichen, "WitchOfPeter")["Same"]["passives"]) == {10}
    monkeypatch.setattr(dialog, "_ask", lambda titel, text: True)
    _antworten(modul, monkeypatch, code)
    dialog._import_link()
    konfigs = th.configs(zeichen, "WitchOfPeter")
    assert pt.allocated(konfigs["Same"]["passives"]) == {10, 11}
    assert pt.allocated(konfigs["Same (2)"]["passives"]) == {10, 11, 12}
    assert gespeichert == [1]
    dialog.close()


def test_a_build_with_one_tree_asks_for_a_name_suggesting_its_title(qapp, baum,
                                                                    monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, _ = _fenster(qapp, baum)
    vorschlaege = []
    werte = iter([(_code(_spec(baum, "^2Endgame", [10, 11, 12])), True), ("Mine", True)])
    monkeypatch.setattr(modul.QInputDialog, "getText", staticmethod(
        lambda *a, **k: vorschlaege.append(k.get("text")) or next(werte)))
    monkeypatch.setattr(dialog, "_choose_trees", lambda b: pytest.fail("keine Auswahl nötig"))
    dialog._import_link()
    assert vorschlaege[1] == "Endgame"
    assert th.configs(zeichen, "WitchOfPeter")["Mine"]["source"] == "pob"
    dialog.close()


def test_a_pobb_link_is_imported_end_to_end(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, _ = _fenster(qapp, baum)
    code = _code(_spec(baum, "From pobb", [10, 11]))
    monkeypatch.setattr(pi, "_http", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=code) if r.url.path == "/abc/raw"
        else httpx.Response(404))))
    _antworten(modul, monkeypatch, "https://pobb.in/abc", "From pobb")
    dialog._import_link()
    assert "From pobb" in th.configs(zeichen, "WitchOfPeter")
    # Ein Abruf, der scheitert, sagt warum — und speichert nichts.
    warnungen = []
    monkeypatch.setattr(modul.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnungen.append(a[2])))
    _antworten(modul, monkeypatch, "https://pobb.in/missing")
    dialog._import_link()
    assert warnungen == ["Nothing to import (pobb.in answered 404)."]
    dialog.close()


def test_other_classes_are_asked_for_once(qapp, baum, monkeypatch) -> None:
    from poe_view.ui import passive_tree_dialog as modul
    dialog, zeichen, gespeichert = _fenster(qapp, baum)
    code = _code(_spec(baum, "W1", [31], klasse="Witch") + _spec(baum, "W2", [31], klasse="Witch"))
    monkeypatch.setattr(dialog, "_choose_trees", lambda b: b)
    fragen = []
    monkeypatch.setattr(modul.QMessageBox, "question", staticmethod(
        lambda *a, **k: fragen.append(a[2]) or modul.QMessageBox.StandardButton.No))
    _antworten(modul, monkeypatch, code)
    dialog._import_link()
    assert fragen == ["These trees are for a Witch, not a Juggernaut. Import anyway?"]
    assert th.configs(zeichen, "WitchOfPeter") == {} and gespeichert == []
    dialog.close()
