"""Tests für die beiden Login-Dialoge (§4.47).

Peter, 2026-08-21: "habe gerade schon wieder vergessen mich einzuloggen
-> Als nächstes: Willkommensdialog mit Loginmöglichkeit. Und einen
Popup, wenn der Login ausläuft."
"""

from poe_view.ui.login_prompts import SessionExpiredDialog, WelcomeDialog


def test_willkommensdialog_zeigt_den_stand_der_lokalen_daten(qapp) -> None:
    """Peters Wahl: "Login plus Stand der lokalen Daten" — der Dialog soll
    beantworten, ob sich das Einloggen ueberhaupt lohnt."""
    dialog = WelcomeDialog("Stored on this PC: 12 league(s).")
    assert "Stored on this PC: 12 league(s)." in _texte(dialog)


def test_willkommensdialog_zeigt_den_erste_schritte_teil_nur_beim_ersten_start(qapp) -> None:
    """Peter: "beim ersten Start zum Konfigurieren und Login", danach nur
    noch der Login-Teil. Beim allerersten Start gibt es nie ein gueltiges
    Token, "erster Start" und "nicht angemeldet" fallen also zusammen —
    unterschiedlich ist nur der INHALT."""
    erster = " ".join(_texte(WelcomeDialog("egal", first_run=True)))
    spaeter = " ".join(_texte(WelcomeDialog("egal", first_run=False)))

    assert "Getting started" in erster
    assert "Client.txt" in erster       # der eine Punkt, den niemand von selbst findet
    assert "Getting started" not in spaeter


def test_erste_schritte_fuehren_in_den_echten_settings_dialog(qapp) -> None:
    """Bewusst kein Nachbau der Zone-Refresh-Bedienelemente hier: Eine
    Kopie samt Pfad-Pruefung waere beim naechsten Umbau die Stelle, die
    stehen bleibt."""
    dialog = WelcomeDialog("egal", first_run=True)
    gerufen = []
    dialog.settings_requested.connect(lambda: gerufen.append(True))

    _knopf(dialog, "settings").click()

    assert gerufen == [True]


def test_willkommensdialog_meldet_den_login_und_schliesst_sich(qapp) -> None:
    dialog = WelcomeDialog("egal")
    gerufen = []
    dialog.login_requested.connect(lambda: gerufen.append(True))

    _knopf(dialog, "Log in").click()

    assert gerufen == [True]
    assert dialog.result() == WelcomeDialog.DialogCode.Accepted


def test_offline_weiterarbeiten_loest_keinen_login_aus(qapp) -> None:
    """Der Cache soll ohne Login durchsuchbar bleiben (FALLSTRICKE #46) —
    "Continue offline" ist deshalb ein vollwertiger Weg, kein Abbruch."""
    dialog = WelcomeDialog("egal")
    gerufen = []
    dialog.login_requested.connect(lambda: gerufen.append(True))

    _knopf(dialog, "Continue offline").click()

    assert gerufen == []
    assert dialog.result() == WelcomeDialog.DialogCode.Rejected


def test_haekchen_spiegelt_den_gespeicherten_stand(qapp) -> None:
    assert WelcomeDialog("egal", show_on_startup=True).show_again.isChecked()
    assert not WelcomeDialog("egal", show_on_startup=False).show_again.isChecked()


def test_beide_dialoge_sind_nicht_modal(qapp) -> None:
    """Peters Entscheidung. Ein modaler Dialog wuerde ausgerechnet das
    Durchsuchen der lokalen Daten blockieren, das ohne Login ausdruecklich
    weiter funktionieren soll (§4.8, FALLSTRICKE #46)."""
    assert WelcomeDialog("egal").isModal() is False
    assert SessionExpiredDialog().isModal() is False


def test_ablauf_popup_sagt_dass_die_lokalen_daten_bleiben(qapp) -> None:
    """Ohne diesen Satz liest sich die Meldung wie ein Abbruch, obwohl
    fast alles weiterlaeuft."""
    text = " ".join(_texte(SessionExpiredDialog()))
    assert "expired" in text.lower()
    assert "stays browsable" in text


def test_ablauf_popup_zeigt_den_grund_nur_wenn_es_einen_gibt(qapp) -> None:
    mit = " ".join(_texte(SessionExpiredDialog("HTTP 401: token rejected")))
    ohne = " ".join(_texte(SessionExpiredDialog()))
    assert "HTTP 401: token rejected" in mit
    assert "401" not in ohne


def test_ablauf_popup_meldet_den_login(qapp) -> None:
    dialog = SessionExpiredDialog()
    gerufen = []
    dialog.login_requested.connect(lambda: gerufen.append(True))

    _knopf(dialog, "Log in").click()

    assert gerufen == [True]


def _texte(dialog) -> list[str]:
    from PySide6.QtWidgets import QLabel
    return [w.text() for w in dialog.findChildren(QLabel)]


def _knopf(dialog, teil: str):
    from PySide6.QtWidgets import QPushButton
    treffer = [b for b in dialog.findChildren(QPushButton)
               if teil.lower() in b.text().lower()]
    assert len(treffer) == 1, f"{teil!r}: {[b.text() for b in dialog.findChildren(QPushButton)]}"
    return treffer[0]


# --- Gedaempfte Nebenzeile: gerechnet, nicht begutachtet -------------- #

def _kanal(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _kontrast(vorne, hinten) -> float:
    def leucht(rgb):
        r, g, b = rgb
        return 0.2126 * _kanal(r) + 0.7152 * _kanal(g) + 0.0722 * _kanal(b)
    a, b = leucht(vorne), leucht(hinten)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _palette(text: str, grund: str):
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    p.setColor(QPalette.ColorRole.WindowText, QColor(text))
    p.setColor(QPalette.ColorRole.Window, QColor(grund))
    return p


def test_gedaempfte_zeile_bleibt_in_BEIDEN_designs_lesbar(qapp) -> None:
    """``color: palette(mid)`` war hier nachweislich falsch: In Peters
    dunklem Windows-Design ergibt das #282828 auf #1e1e1e, also 1.13:1 —
    keine Daempfung, sondern Unsichtbarkeit. Ein fest eingetipptes Grau
    waere der zweite Fehler (im hellen Design ein Fleck), also wird aus
    der Palette gerechnet. Beide Richtungen muessen WCAG AA (4.5:1) fuer
    normalen Text schaffen."""
    from poe_view.ui.login_prompts import muted_colour

    for text, grund, name in [("#ffffff", "#1e1e1e", "dunkel (Peters Windows)"),
                              ("#000000", "#ffffff", "hell")]:
        farbe = muted_colour(_palette(text, grund))
        grund_rgb = tuple(int(grund[i:i + 2], 16) for i in (1, 3, 5))
        k = _kontrast((farbe.red(), farbe.green(), farbe.blue()), grund_rgb)
        assert k >= 4.5, f"{name}: nur {k:.2f}:1 ({farbe.name()} auf {grund})"


def test_gedaempfte_zeile_ist_wirklich_gedaempft(qapp) -> None:
    """Gegenstueck zum Test oben: Lesbar allein reicht nicht, sonst waere
    "einfach die normale Textfarbe nehmen" die Loesung — die Zeile soll
    sich sichtbar vom Haupttext abheben."""
    from poe_view.ui.login_prompts import muted_colour

    palette = _palette("#ffffff", "#1e1e1e")
    farbe = muted_colour(palette)
    assert farbe.name() != "#ffffff"
    voll = _kontrast((255, 255, 255), (30, 30, 30))
    gedaempft = _kontrast((farbe.red(), farbe.green(), farbe.blue()), (30, 30, 30))
    assert gedaempft < voll


# --- Bleibt ueber dem Hauptfenster (§4.47) ---------------------------- #

def test_dialoge_nehmen_ein_elternfenster_an(qapp) -> None:
    """Peter, 2026-08-22: "Koennen wir den Login-Dialog auf Top-Layer legen,
    so dass er sich nicht vom Hauptfenster verdecken laesst? Nicht modal,
    aber Top-Layer."

    Geprueft wird der MECHANISMUS, nicht das Ergebnis: Offscreen gibt es
    keinen Fenstermanager, die tatsaechliche Stapelreihenfolge ist dort
    nicht zu messen (dieselbe Lehre wie FALLSTRICKE #71). Die Elternschaft
    ist das, was Windows fuer die Reihenfolge auswertet."""
    from PySide6.QtWidgets import QWidget
    eltern = QWidget()

    for dialog in (WelcomeDialog("egal", parent=eltern),
                   SessionExpiredDialog("egal", parent=eltern)):
        assert dialog.parent() is eltern


def test_elternteil_macht_die_dialoge_nicht_modal(qapp) -> None:
    """Der Punkt, an dem eine fruehere Fassung dieses Codes falsch lag: Ein
    Elternteil bindet den Dialog in die Fenster-Reihenfolge ein, macht ihn
    aber NICHT modal. Beides zusammen ist genau Peters Wunsch."""
    from PySide6.QtWidgets import QWidget
    eltern = QWidget()

    assert WelcomeDialog("egal", parent=eltern).isModal() is False
    assert SessionExpiredDialog("egal", parent=eltern).isModal() is False


def test_dialoge_schweben_nicht_ueber_fremden_programmen(qapp) -> None:
    """Gegenstueck: WindowStaysOnTopHint waere der naheliegende, aber
    falsche Weg — der Dialog laege dann auch ueber Path of Exile im
    Fenstermodus und ueber dem Browser, in dem man sich anmelden soll.
    Peters Satz nennt ausdruecklich das Hauptfenster."""
    from PySide6.QtCore import Qt as QtNs
    from PySide6.QtWidgets import QWidget
    eltern = QWidget()

    for dialog in (WelcomeDialog("egal", parent=eltern),
                   SessionExpiredDialog("egal", parent=eltern)):
        assert not (dialog.windowFlags() & QtNs.WindowType.WindowStaysOnTopHint)


def test_dialoge_gehen_auch_ohne_elternteil(qapp) -> None:
    """Die uebrigen Tests hier bauen sie ohne Elternteil — das muss
    weiterhin funktionieren, sonst waere jeder davon nur noch ein Test
    seiner eigenen Vorbedingung."""
    assert WelcomeDialog("egal").parent() is None
    assert SessionExpiredDialog().parent() is None
