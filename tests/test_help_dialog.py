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
    """Peters Punkt vom 2026-08-02: "Ich denke, dass die meisten User mit
    den Zahlen nicht klar kommen." Abruf- und Tab-Zaehler laufen
    absichtlich auseinander."""
    text = _all_text()
    assert "requests" in text and "tab" in text
    assert "section" in text                   # die Einheit dahinter
    assert "map" in text and "unique" in text  # Grund fuer die Differenz


def test_the_help_does_not_describe_a_dialog_that_no_longer_exists(qapp) -> None:
    """Der Fortschrittsdialog hiess bis 2026-08-06 "Section x of 1456" —
    das Wort ist raus, weil es in PoEs Truhen-Oberflaeche keine
    Entsprechung hat. Eine Hilfe, die Beschriftungen nennt, die es nicht
    mehr gibt, ist schlimmer als gar keine: Sie schickt den Nutzer nach
    etwas suchen, das er nie finden wird."""
    text = _all_text()
    assert "section x of" not in text


def test_the_help_covers_what_came_after_it_was_written(qapp) -> None:
    """Die Hilfe entstand am 2026-08-03. Alles, was danach an sichtbarer
    Oberflaeche dazukam, muss nachgezogen werden — sonst waechst genau die
    Luecke wieder, gegen die sie gebaut wurde."""
    import re

    # Zeilenumbruch normalisieren: Der Hilfetext ist auf Zeilenlaenge
    # umbrochen, ein gesuchter Satz steht deshalb selten am Stueck.
    text = re.sub(r"\s+", " ", _all_text())

    assert "read-only" in text          # zweite Instanz auf demselben Konto
    assert "pin" in text                # Spaltenfilter per Rechtsklick
    assert "unchanged for" in text      # Statuszeile
    assert "no prices for this league" in text  # SSF-Hinweis
    assert "backup" in text             # Sicherungen beim Start
    # Die zweite Hervorhebungsfarbe (Peter, 2026-08-11): Gruen fuer einen
    # Gem-Aufstieg. Eine Farbe, die niemand erklaert, ist genau die Sorte
    # Luecke, gegen die die Hilfe gebaut wurde — zumal Peter selbst
    # gefragt hat, warum ausgerechnet Waffe und Schildhand leuchten.
    assert "a socketed gem gained a level" in text
    assert "flask charges" in text      # was NICHT als Aenderung zaehlt


def test_the_help_says_where_the_backups_are_and_how_to_use_one(qapp) -> None:
    """Eine Sicherung, von der niemand weiss, ist keine. Es gibt bewusst
    keinen Wiederherstellen-Knopf (dieselbe Ueberlegung wie beim
    fehlenden Loeschen-Knopf) — dann muss die Hilfe den Weg von Hand
    beschreiben, sonst ist die Funktion praktisch nicht vorhanden."""
    import re

    text = re.sub(r"\s+", " ", _all_text())
    assert "backups" in text            # der Ordnername
    assert "24 hours" in text           # die Aufbewahrungsfrist
    assert "unpack" in text             # der Weg zurueck


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


def test_the_about_topic_shows_the_application_icon(qapp) -> None:
    """Peter, 2026-08-07: "wir haben ja ein so schoenes Icon, das
    koennten wir auch noch irgendwo dezent benutzen". Qts Rich Text
    braucht dafuer eine echte file:-URL — ein roher Windows-Pfad mit
    Backslashes wuerde als relative Adresse gelesen und blieb leer."""
    from poe_view.ui.help_dialog import _icon_src

    about = next(body for title, body in TOPICS if title.startswith("About"))
    src = _icon_src()

    assert src.startswith("file:///"), src
    assert src.endswith("PoE-VIEW2.png"), src
    assert f'<img src="{src}"' in about


def test_qt_really_resolves_the_about_icon(qapp) -> None:
    """Der Test oben prueft nur den Text. Ob Qt die Adresse auch
    AUFLOESEN kann, ist eine andere Frage — genau daran scheitern
    Windows-Pfade in Rich Text lautlos: das Bild fehlt einfach, ohne
    Fehlermeldung. Hier wird das gerenderte Dokument befragt."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QTextDocument

    from poe_view.ui.help_dialog import TOPICS, HelpDialog, _icon_src

    dialog = HelpDialog()
    dialog._topics.setCurrentRow(
        next(i for i, (title, _) in enumerate(TOPICS) if title.startswith("About")))

    loaded = dialog._text.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl(_icon_src()))

    assert loaded is not None and not loaded.isNull()
    dialog.deleteLater()


def test_the_about_icon_degrades_to_nothing_if_the_file_is_missing(
        qapp, monkeypatch, tmp_path) -> None:
    """In der gepackten .exe steckt die Datei nur dann im Bundle, wenn
    sie in PoE-VIEW2.spec unter ``datas`` steht. Fehlt sie, soll das
    Hilfe-Fenster sie weglassen statt einen leeren Bildrahmen zu
    zeigen — der saehe nach Fehler aus, das Fehlen faellt nicht auf."""
    from poe_view.ui import help_dialog

    monkeypatch.setattr(help_dialog.config, "APP_ICON_PNG", tmp_path / "weg.png")

    assert help_dialog._icon_src() == ""


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


def test_the_help_says_why_there_is_no_poe2_support(qapp) -> None:
    """Ein Eintrag "PoE2 raw data" im Konto-Menue eines Programms, das
    laut README PoE1 liest, wirft genau eine Frage auf — die Hilfe muss
    sie beantworten, samt dem Grund (kein Truhen-Endpunkt fuer PoE2)."""
    text = _all_text()
    assert "path of exile 2" in text
    assert "not on the stash endpoints" in text
    assert "poe2 raw data" in text
    # Und den gemessenen Befund, nicht nur die gelesene Doku: Der
    # Parameter wird ueberhaupt nicht ausgewertet (2026-08-15).
    assert "byte-identical" in text
