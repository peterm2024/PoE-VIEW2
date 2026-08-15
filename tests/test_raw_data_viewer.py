"""Tests für den Rohdaten-Mini-Viewer (Rechtsklick im Stash-Baum)."""

from poe_view.ui.raw_data_viewer import RawDataViewer


def test_show_payload_sets_title_and_pretty_json(qapp) -> None:
    viewer = RawDataViewer()
    viewer.show_payload("t1", "Currency 1", {"id": "t1", "items": [{"typeLine": "Chaos Orb"}]})

    assert "Currency 1" in viewer._title.text()
    assert "t1" in viewer._title.text()
    text = viewer._text.toPlainText()
    assert '"typeLine": "Chaos Orb"' in text
    assert viewer._text.isReadOnly()


def test_show_document_zeigt_beliebigen_text(qapp) -> None:
    """Dasselbe Fenster traegt auch den PoE2-Abzug (§4.43) — der ist Text,
    kein Tab-Objekt."""
    viewer = RawDataViewer()
    viewer.show_document("PoE2 raw data", "GET /character?realm=poe2\nFAILED — 403")

    assert viewer._title.text() == "PoE2 raw data"
    assert "FAILED — 403" in viewer._text.toPlainText()


def test_show_payload_baut_auf_show_document_auf(qapp) -> None:
    """Ein zweiter Weg, Text in dasselbe Feld zu schreiben, waere eine
    Stelle mehr, an der Titel und Inhalt auseinanderlaufen koennen."""
    viewer = RawDataViewer()
    viewer.show_document("vorher", "alt")
    viewer.show_payload("t2", "Maps", {"id": "t2"})

    assert "Maps" in viewer._title.text()
    assert "alt" not in viewer._text.toPlainText()
