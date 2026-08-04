"""Tests für das Hilfe-Fenster (Peter, 2026-08-03: "Punkt 5 wäre eine
kleine Hilfe-Funktion").

Geprüft wird nicht die Formulierung, sondern dass die Hilfe genau die
Stellen abdeckt, an denen der Spielertest hängen geblieben ist — sonst
veraltet sie unbemerkt, während die Oberfläche weiterläuft.
"""

from PySide6.QtWidgets import QDialog

from poe_view.ui.help_dialog import TOPICS, HelpDialog
from poe_view.ui.main_window import MainWindow


def _all_text() -> str:
    return "\n".join(body for _title, body in TOPICS).lower()


def test_every_topic_has_a_title_and_content(qapp) -> None:
    assert TOPICS, "keine Themen vorhanden"
    for title, body in TOPICS:
        assert title.strip(), "Thema ohne Titel"
        assert len(body.strip()) > 200, f"Thema {title!r} ist fast leer"


def test_selecting_a_topic_shows_its_text(qapp) -> None:
    dialog = HelpDialog()
    assert dialog._topics.count() == len(TOPICS)

    dialog._topics.setCurrentRow(1)
    shown = dialog._text.toPlainText()

    assert TOPICS[1][0].split()[0].lower() in shown.lower()
    dialog.deleteLater()


def test_the_help_explains_what_the_player_test_stumbled_over(qapp) -> None:
    """Die vier Stellen, die sich im Spielertest (2026-08-03) nicht von
    selbst erklärt haben: die unbeschrifteten Typ-Filter, das Format der
    Positionsspalte, die Symbole im Verlauf und die in SSF-Ligen leer
    bleibende Wertspalte."""
    text = _all_text()
    assert "ssf" in text and "poe.ninja" in text      # leere Wertspalte
    assert "#2" in text and "grid coordinate" in text  # Positionsspalte
    assert "↑" in text and "↓" in text and "±" in text  # Verlaufssymbole
    for rarity in ("normal", "magic", "rare", "unique", "currency"):
        assert rarity in text                          # Typ-Filter-Legende


def test_the_help_explains_the_two_counts_in_load_all_tabs(qapp) -> None:
    """Peters vertagter Punkt vom 2026-08-02: "Ich denke, dass die meisten
    User mit den Zahlen nicht klar kommen." Section- und Tab-Zähler laufen
    absichtlich auseinander."""
    text = _all_text()
    assert "section" in text and "tab" in text
    assert "map" in text and "unique" in text  # Grund fuer die Differenz


def test_the_help_explains_the_unchanged_hint_in_the_status_bar(qapp) -> None:
    """"unchanged for 12m" ist neues Vokabular in der Statuszeile, und der
    dahinterstehende Sachverhalt ist nicht zu erraten: Die API
    veroeffentlicht neue Fach-Inhalte oft erst nach einem Zonenwechsel
    (FALLSTRICKE #58). Ohne diese Erklaerung liest sich der Hinweis wie
    ein Defekt."""
    text = _all_text()
    assert "unchanged for" in text
    assert "zone" in text  # der Ausweg, nicht nur die Feststellung


def test_the_help_is_written_in_english_like_the_rest_of_the_ui(qapp) -> None:
    """Oberfläche und README sind englisch, Kommentare und Projektdoku
    deutsch (bewusste Trennung). Ein deutscher Hilfetext wäre für die
    Zielgruppe wertlos — dieser Test hält die Grenze."""
    text = _all_text()
    for german in (" und ", " oder ", " nicht ", " werden ", " einstellungen"):
        assert german not in text, f"deutscher Text in der Hilfe: {german!r}"


def test_toolbar_button_opens_the_help_and_reuses_it(qapp) -> None:
    """Nicht modal und nur einmal gebaut: die Hilfe soll offen bleiben
    können, während man das Erklärte ausprobiert."""
    win = MainWindow()

    win._open_help_dialog()
    first = win._help_dialog
    assert isinstance(first, QDialog) and first.isVisible()

    win._open_help_dialog()
    assert win._help_dialog is first  # wiederverwendet, kein zweites Fenster

    first.close()
    win.worker.stop()
    win.worker.wait(5000)


def test_the_about_topic_carries_the_disclaimer(qapp) -> None:
    """Peter, 2026-08-04: "für Punkt 2 geht uns langsam der Platz aus. Wir
    koennten den Disclaimer in die Hilfe packen." Er hat vorher bei Path of
    Building nachgesehen — das zeigt gar keinen. Aus der Statuszeile ist er
    damit raus, aber im Wortlaut muss er erhalten bleiben: Es ist GGGs
    vorgeschriebene Formulierung, kein selbstgewaehlter Text."""
    from poe_view import __version__, config

    about = next(body for title, body in TOPICS if title.startswith("About"))

    assert config.DISCLAIMER in about
    assert __version__ in about
    assert "poe.ninja" in about  # zweite Nicht-Zugehoerigkeit, wie in der README


def test_the_disclaimer_is_no_longer_in_the_status_bar(qapp) -> None:
    """Gegenstueck zum Test oben: er darf genau einmal existieren, nicht
    an beiden Stellen — sonst waere die Platzersparnis wieder dahin."""
    from PySide6.QtWidgets import QLabel

    from poe_view import config
    from poe_view.ui.main_window import MainWindow

    win = MainWindow()
    texts = [w.text() for w in win.statusBar().findChildren(QLabel)]

    assert config.DISCLAIMER not in texts

    win.worker.stop()
    win.worker.wait(5000)
