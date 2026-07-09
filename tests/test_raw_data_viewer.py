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
