"""Vergrößerte Item-Ansicht: Doppelklick auf eine Zeile in der Item-Tabelle
öffnet ein eigenes Fenster mit großem Icon und vollständigem Mod-/
Property-Text (ToDo.md: "Doppelklick auf ein Item 'beleuchtet' dies").

Bewusst NUR eine größere, vollständige Darstellung dessen, was die App
ohnehin schon kennt (dasselbe Modell wie das kompakte ``ItemDetail``, nur
ohne dessen ``lines[:12]``-Kürzung und mit einem deutlich größeren Icon).
Zwei Teile der ursprünglichen ToDo-Idee fehlen bewusst: Tier-Level/
Stat-Wertebereiche bräuchten Mod-ID/Tier-Rohdaten, die GGGs API
nachweislich nie liefert (FALLSTRICKE #50), und "Beliebtheit als
Crafting-Basis"/Build-Nutzung bräuchte eine eigenständige, neue
poe.ninja-Build-Anbindung (unser bestehender ``api/ninja.py``-Client holt
nur Preise, keine Build-Daten) — beides eigene, größere Vorhaben.

Für Divination Cards (frameType 6) ersetzt ``MainWindow`` das anfangs
übergebene Icon asynchron durch das echte Karten-Artwork (per
``set_icon_pixmap``, siehe ``external_tools.divination_card_art_url`` und
FALLSTRICKE #52) — GGGs Stash-API liefert für jede Div-Card dasselbe
generische Icon, das wäre für dieses Fenster wertlos. Das Artwork selbst
ist nur das bloße Illustrations-Panel ohne Rahmen/Titel (siehe
FALLSTRICKE #52) — ein schlichter Pergament-Rahmen samt Titel-Banner
gleicht das optisch an den echten Karten-Look an (Peters Wiki-Referenz,
2026-07-31), rein dekorativ, keine neuen Daten.

Als einzige Ansicht zeigt dieses Fenster auch den Spruchtext
(``Item.flavour_text``). Bei einer Divination Card ist er der eigentliche
Inhalt — ein Kartenrahmen ohne ihn bleibt stumm —, bei Uniques die
Hintergrundgeschichte. Im kompakten ``ItemDetail`` hat er bewusst keinen
Platz: dort sind die Zeilen auf zwölf begrenzt, und die gehören den Mods.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from poe_view.api.models import (Item, item_category, markup_segments,
                                 req_attribute, req_level)
from poe_view.ui.theme import MARKUP_COLORS, RARITY_COLORS, STACK_COLORS

# Fester Vergrößerungsfaktor statt Skalierung auf die Fensterbreite —
# Letzteres blies auch kleine, normale Item-Icons auf hunderte Pixel auf
# und sah dadurch verpixelt/falsch aus (Peter, 2026-07-31: "das ging
# schief... einfach fest auf 300% vergrößern, dann sollte das ganz gut
# ins Fenster passen"). 300% war Peter dann doch zu groß, 200% ist der
# aktuelle Stand (Peter, 2026-07-31).
_ZOOM_FACTOR = 2

# Rein optische Anlehnung an den Pergament-/Schriftrollen-Look echter
# Divination-Card-Darstellungen (z. B. im PoE-Wiki) — keine echten
# Karten-Assets, nur Farben/Rahmen in Qt-Stylesheet-Syntax.
_CARD_FRAME_STYLE = (
    "QFrame#cardFrame {"
    " background-color: #241a10;"
    " border: 3px solid #9c7b3f;"
    " border-radius: 10px;"
    "}"
)
# Gedämpftes Blaugrau für den Spruchtext — dieselbe Rolle wie im Spiel:
# deutlich zurückgenommen gegenüber den Mods darüber, aber auf dunklem wie
# hellem Untergrund noch lesbar.
_FLAVOUR_COLOR = "#7d8aa0"

# Der Spruchtext bekommt eine Serifenschrift: Er ist Prosa, kein Datenfeld,
# und hebt sich dadurch von den Zahlen darüber ab, ohne laut zu werden
# (Peter, 2026-08-06: "mit einer 'schöneren' Schrift in kursiv und
# größer"). Eine Schrift MITZULIEFERN wäre eine Lizenz- und
# Paketgrößen-Frage für eine reine Geschmacksverbesserung — deshalb eine
# Reihe von Kandidaten, die Windows selbst mitbringt (alle vier am
# 2026-08-06 auf Peters Rechner vorhanden). ``setFamilies`` probiert sie
# der Reihe nach durch; ist keine da, bleibt die normale Schrift, nur
# kursiv und größer.
_SERIF_FAMILIES = ["Georgia", "Palatino Linotype", "Constantia", "Cambria"]
_FLAVOUR_SCALE = 1.3

# Zierteiler zwischen Artwork und Spruchtext im Kartenrahmen, in der
# Rahmenfarbe — er trennt die beiden Teile der Karte, ohne eine harte
# Linie zu ziehen.
#
# Die naheliegenden Zierzeichen ❦ (U+2766) und ❧ (U+2767) sind
# UNBRAUCHBAR: Windows zeichnet sie aus einer Farb-Emoji-Schrift, sie
# erscheinen also als buntes Bildchen statt in der Rahmenfarbe — auch mit
# Variantenselektor U+FE0E und auch mit ausdrücklich gesetzter
# Serifenschrift (alle drei am 2026-08-06 gerendert und angesehen). ◆
# (U+25C6) und ❖ (U+2756) bleiben Text und nehmen die Farbe an.
_CARD_ORNAMENT = "—— ◆ ——"

_CARD_TITLE_STYLE = (
    "background-color: #d8c088; color: #2a1a0d; font-weight: 700;"
    " font-size: 15px; border: 2px solid #9c7b3f; border-radius: 6px;"
    " padding: 5px 12px;"
)
_CARD_ORNAMENT_STYLE = "color: #9c7b3f; font-size: 15px; padding: 2px;"

# Satz-Fortschritt einer Divination Card (Peters Vorschlag, 2026-08-06):
# vorne die Zahl der vollen Sätze, dahinter je ein Rechteck pro Karte des
# angefangenen Satzes, gefüllt für vorhandene, leer für fehlende.
#
# Beide Zahlen brauchen ihre eigene Darstellungsform, und zwar aus den
# Daten heraus: Die Satzgröße liegt zwischen 1 und 27 (real geprüft, alle
# 976 Karten) — das lässt sich zeichnen. Die Zahl der vollen Sätze geht
# bis 116 (467 × "The Carrion Crow" bei Satzgröße 4) — das lässt sich
# nicht zeichnen und bleibt eine Zahl.
#
# ⬛/⬜ (U+2B1B/U+2B1C) sind unbrauchbar, Windows zeichnet sie als
# Farb-Emoji (gerendert und angesehen, wie beim Zierteiler oben). ▮/▯
# bleiben Text, sind schmal genug für den schlimmsten Fall und sehen
# nebenbei aus wie hochkant liegende Karten.
#
# Zwischen den Rechtecken steht ein schmales Leerzeichen (U+2009):
# Aneinandergesetzt verschmelzen sie zu einem Balken, und abzählen — worum
# es hier gerade geht — kann man ihn dann nicht mehr. Qts Rich-Text kennt
# ``letter-spacing`` nicht, deshalb ein echtes Zeichen statt CSS.
_STACK_FULL = "▮ "
_STACK_EMPTY = "▯ "

# Farbnamen aus GGGs Markup UND unsere eigenen für die Satzanzeige. Eine
# Verwechslung ist ausgeschlossen: GGGs Tags sind reine Buchstaben, unsere
# tragen einen Bindestrich.
_SEGMENT_COLORS = {**MARKUP_COLORS, **STACK_COLORS}

# Zusätzliches CSS je Abschnitt. Die Rechtecke stehen für sich und dürfen
# etwas größer sein als der Fließtext daneben.
_SEGMENT_STYLES = dict.fromkeys(
    ("stack-complete", "stack-full", "stack-empty"), "font-size:15px")


def _flavour_font(base: QFont) -> QFont:
    """Kursive Serifenschrift, etwas größer als der übrige Text.

    ``setFamilies`` statt einer Stylesheet-Angabe: Qt-Stylesheets nehmen
    bei ``font-family`` nur den ERSTEN Namen und lassen den Rest fallen —
    eine Ersatzkette gäbe es damit nicht, und auf einem Rechner ohne
    Georgia bliebe die Schrift stumm auf der Standardschrift stehen, ohne
    dass es auffiele.

    Die Größe wird über ``pointSizeF`` skaliert; ist die Schrift in Pixeln
    definiert (kommt bei manchen Themes vor, ``pointSizeF`` liefert dann
    −1), über ``pixelSize``."""
    font = QFont(base)
    font.setFamilies(_SERIF_FAMILIES)
    font.setItalic(True)
    if base.pointSizeF() > 0:
        font.setPointSizeF(base.pointSizeF() * _FLAVOUR_SCALE)
    elif base.pixelSize() > 0:
        font.setPixelSize(round(base.pixelSize() * _FLAVOUR_SCALE))
    return font


class ItemZoomDialog(QDialog):
    def __init__(self, item: Item, pixmap: QPixmap | None,
                parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(item.display_name)
        # Karten brauchen mehr Höhe: Über dem Text steht bei ihnen der
        # Kartenrahmen mit Artwork und Spruchtext (rund 490 px), in 520 px
        # bliebe die Belohnung hinter einem Rollbalken verborgen. Das
        # Artwork ist bei allen Karten gleich groß (~237×170, doppelt also
        # ~474×340), die Höhe ist deshalb verlässlich abschätzbar.
        self.resize(420, 640 if item.frameType == 6 else 520)

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap:
            self.set_icon_pixmap(pixmap)

        colour = RARITY_COLORS.get(item.frameType, "#e8e6e3")
        tags = [tag for tag, present in
               (("Unidentified", not item.identified), ("Corrupted", item.corrupted))
               if present]
        suffix = f"  [{', '.join(tags)}]" if tags else ""
        self._name = QLabel(item.display_name + suffix)
        self._name.setWordWrap(True)
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setStyleSheet(f"font-weight:700; font-size:16px; color:{colour};")

        self._text = QLabel(self._build_html(item))
        self._text.setTextFormat(Qt.TextFormat.RichText)
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._text.setToolTip(self._stack_tooltip(item))

        # Der Spruchtext steht bewusst in einem eigenen Label statt im
        # Textblock: Das Spiel setzt ihn kursiv und abgesetzt ab, und genau
        # diese Trennung geht verloren, sobald alles ein Block ist. Bei
        # Divination Cards ist er der eigentliche Inhalt der Karte, bei
        # Uniques die Hintergrundgeschichte — hat ein Item keinen, bleibt
        # hier gar nichts stehen.
        self._flavour = QLabel(item.flavour_text)
        self._flavour.setWordWrap(True)
        self._flavour.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._flavour.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._flavour.setFont(_flavour_font(self._flavour.font()))
        self._flavour.setStyleSheet(f"color: {_FLAVOUR_COLOR}; padding: 6px 10px;")
        self._flavour.setVisible(bool(item.flavour_text))

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(self._text)
        body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)

        layout = QVBoxLayout(self)
        # Der Spruchtext sitzt ZWISCHEN Bild und Zahlen (Peter,
        # 2026-08-06). Bei einer Karte gehört er mit in den Rahmen — er ist
        # Teil der Karte, nicht eine Bemerkung darunter.
        if item.frameType == 6:
            layout.addWidget(self._build_card_frame())
        else:
            layout.addWidget(self._icon)
            layout.addWidget(self._name)
            layout.addWidget(self._flavour)
        layout.addWidget(scroll, stretch=1)

    def _build_card_frame(self) -> QFrame:
        """Pergament-Rahmen mit Titel-Banner um Artwork, Zierteiler und
        Spruchtext — rein optisch, siehe Modul-Docstring."""
        self._name.setStyleSheet(_CARD_TITLE_STYLE)
        frame = QFrame()
        frame.setObjectName("cardFrame")
        frame.setStyleSheet(_CARD_FRAME_STYLE)
        frame_layout = QVBoxLayout(frame)
        frame_layout.addWidget(self._name)
        frame_layout.addWidget(self._icon)
        if self._flavour.text():
            self._ornament = QLabel(_CARD_ORNAMENT)
            self._ornament.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._ornament.setStyleSheet(_CARD_ORNAMENT_STYLE)
            frame_layout.addWidget(self._ornament)
            frame_layout.addWidget(self._flavour)
        return frame

    def set_icon_pixmap(self, pixmap: QPixmap) -> None:
        """Öffentlich, damit MainWindow das anfängliche (bei Divination
        Cards wertlose generische) Icon nachträglich durch echtes Artwork
        ersetzen kann, sobald der asynchrone Abruf fertig ist. Fester
        Faktor (_ZOOM_FACTOR) auf die Originalgröße, keine Skalierung auf
        die Fensterbreite — siehe Modul-Konstante."""
        self._icon.setPixmap(pixmap.scaled(
            pixmap.width() * _ZOOM_FACTOR, pixmap.height() * _ZOOM_FACTOR,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    @staticmethod
    def _stack_line(item: Item) -> list[tuple[str | None, str]] | None:
        """Der Satz-Fortschritt einer Divination Card als eigene Zeile.

        ``7/5`` → ``1 ▮  +  ▮ ▮ ▯ ▯ ▯`` — ein voller Satz (grün), und vom
        nächsten sind zwei von fünf Karten da. Die Frage, die man an eine
        Karte hat, ist "wie weit bin ich?", und die beantwortet "7/5" erst
        nach Kopfrechnen (Peters Entwurf, 2026-08-06).

        Grün heißt an dieser Stelle immer und nur "vollständig". Damit
        liest sich auch der Fall, in dem der Satz genau aufgeht, richtig:
        ``15/5`` wird zu ``3 ▮  +  ▯ ▯ ▯ ▯ ▯`` — drei fertige Sätze und
        ein noch leerer vierter, statt einer Reihe leerer Kästchen, die
        wie "du hast nichts" aussieht.

        **Nicht an die Properties gekoppelt.** Die Zeile wird aus
        ``stackSize``/``maxStackSize`` gerechnet, nicht aus der
        ``Stack Size``-Property — denn die fehlt genau bei den Karten mit
        Satzgröße 1 (real geprüft: alle 16 solchen Karten haben
        ``properties: []``, alle 960 übrigen eine Property; Peter fand es
        an "Society's Remorse"). Dort stand vorher gar nichts, und "gar
        nichts" ist von einem Fehler nicht zu unterscheiden.

        Bei Satzgröße 1 ist jede Karte für sich ein voller Satz, es gibt
        keinen angefangenen — dann steht dort nur ``16 ▮`` in Grün.

        ``None`` für alles außer Divination Cards: Bei Währung ist
        ``maxStackSize`` keine Satzgröße, sondern Lagerkapazität — real
        bis 50000, und ein voller Stapel heißt nur, dass das Fach voll ist
        (Peter: "die Rechtecke meine ich nur bei den Divination Cards,
        beim Rest macht das wenig Sinn"). Ebenso ``None``, wenn eine der
        beiden Zahlen fehlt.
        """
        per_set = item.maxStackSize or 0
        held = item.stackSize or 0
        if item.frameType != 6 or per_set < 1 or held < 1:
            return None

        complete, in_progress = divmod(held, per_set)
        segments: list[tuple[str | None, str]] = []
        if complete:
            # Die Zahl der vollen Sätze geht bis dreistellig (467 × "The
            # Carrion Crow" sind 116 Sätze) — sie zu zeichnen wäre eine
            # Rechteck-Wand ohne Aussage. Ein einzelnes grünes Rechteck
            # dahinter sagt, wovon die Zahl spricht.
            segments.append((None, f"{complete} "))
            segments.append(("stack-complete", _STACK_FULL.rstrip()))
        if per_set > 1:
            if complete:
                segments.append((None, "  +  "))
            segments.append(("stack-full", _STACK_FULL * in_progress))
            segments.append(("stack-empty", _STACK_EMPTY * (per_set - in_progress)))

        kept = [(tag, text) for tag, text in segments if text]
        # Das schmale Leerzeichen trennt die Rechtecke voneinander; hinter
        # dem letzten hat es nichts zu trennen und verschöbe die zentrierte
        # Zeile um ein halbes Zeichen nach links.
        kept[-1] = (kept[-1][0], kept[-1][1].rstrip())
        return kept

    @staticmethod
    def _stack_tooltip(item: Item) -> str:
        """Die genauen Zahlen, die die Rechtecke ersetzen. 467 Karten und
        116 Sätze lassen sich nicht abzählen — die Auskunft darf deshalb
        nicht ganz verschwinden, nur aus der Zeile."""
        per_set = item.maxStackSize or 0
        held = item.stackSize or 0
        if item.frameType != 6 or per_set < 1 or held < 1:
            return ""
        complete, in_progress = divmod(held, per_set)
        if per_set == 1:
            return f"{held} cards, each one a complete set"
        return (f"{held} cards, {per_set} per set — "
                f"{complete} complete, {in_progress} towards the next")

    @staticmethod
    def _text_lines(item: Item) -> list[list[tuple[str | None, str]]]:
        """Der Textblock als Zeilen aus ``(Farbname, Text)``-Abschnitten.

        EINE Quelle, zwei Darstellungen: ``_build_text`` macht reinen Text
        daraus, ``_build_html`` eingefärbtes HTML. Zwei getrennte Aufbauten
        wären auf Dauer zwei verschiedene Fenster — sobald eine Zeile nur
        in einem der beiden ergänzt wird, fällt es niemandem auf.

        ``None`` als Farbname heißt "normale Textfarbe". Farbig ist nur,
        was GGG selbst eingefärbt hat (die Mod-Texte, siehe
        ``models.markup_segments``); alles andere sind unsere eigenen
        Beschriftungen und bleiben schlicht."""
        lines: list[list[tuple[str | None, str]]] = [
            [(None, item.rarity + (f" · {item.typeLine}" if item.name else ""))]]

        category = item_category(item)
        if category:
            lines.append([(None, f"Class: {category}")])

        requirement_bits = []
        if item.ilvl:
            requirement_bits.append(f"iLvl {item.ilvl}")
        if req_level(item):
            requirement_bits.append(f"Req. Lvl {req_level(item)}")
        for label in ("Str", "Dex", "Int"):
            value = req_attribute(item, label)
            if value:
                requirement_bits.append(f"Req. {label} {value}")
        if requirement_bits:
            lines.append([(None, " · ".join(requirement_bits))])

        if item.socket_string:
            lines.append([(None, f"Sockets: {item.socket_string}")])

        # Die Satz-Zeile ersetzt die Stack-Size-Property, wo es eine gibt,
        # und tritt sonst an deren Stelle — bei Satzgröße 1 liefert GGG
        # keine (siehe _stack_line).
        stack_line = ItemZoomDialog._stack_line(item)
        prop_lines: list[list[tuple[str | None, str]]] = []
        for prop in item.properties:
            if not prop.display_value:
                continue
            if stack_line is not None and prop.name == "Stack Size":
                prop_lines.append(stack_line)
                stack_line = None
                continue
            prop_lines.append([(None, prop.display_text)])
        if stack_line is not None:
            prop_lines.insert(0, stack_line)
        if prop_lines:
            lines.append([])
            lines.extend(prop_lines)

        for raw_mods in (item.implicitMods, item.explicitMods):
            if not raw_mods:
                continue
            lines.append([])
            for raw in raw_mods:
                # Ein Mod-Eintrag kann selbst mehrzeilig sein (Karten mit
                # mehrteiliger Belohnung), und jede Zeile eigene Farben
                # tragen — deshalb erst zerlegen, dann an Umbrüchen teilen.
                current: list[tuple[str | None, str]] = []
                for tag, text in markup_segments(raw):
                    parts = text.split("\n")
                    for index, part in enumerate(parts):
                        if index:
                            lines.append(current)
                            current = []
                        if part:
                            current.append((tag, part))
                lines.append(current)

        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        return lines

    @staticmethod
    def _build_text(item: Item) -> str:
        """Reiner Text — für Tooltips, Tests und alles, was kein HTML mag."""
        return "\n".join("".join(text for _tag, text in line)
                        for line in ItemZoomDialog._text_lines(item))

    @staticmethod
    def _build_html(item: Item) -> str:
        """Derselbe Text zentriert und in GGGs eigenen Farben.

        Die Farbangabe stammt aus dem Markup der Quelle, nicht aus einer
        eigenen Zuordnung nach Schlagworten — bei einer Divination Card
        sagt GGG damit, ob die Belohnung eine Währung, ein Gem oder ein
        Unique ist (``theme.MARKUP_COLORS``). Unbekannte Auszeichnungen
        bleiben in der normalen Textfarbe; eine geratene Farbe wäre
        schlechter als gar keine."""
        rendered = []
        for line in ItemZoomDialog._text_lines(item):
            if not line:
                # Ein LEERES div hat in Qts Rich-Text keine Höhe und fällt
                # ersatzlos weg — die Absätze klebten dadurch aneinander.
                # Ein geschütztes Leerzeichen in kleiner Schrift gibt den
                # Abstand, ohne eine ganze Leerzeile zu kosten.
                rendered.append("<div style='font-size:7px'>&nbsp;</div>")
                continue
            parts = []
            for tag, text in line:
                escaped = html.escape(text)
                style = "; ".join(bit for bit in (
                    f"color:{_SEGMENT_COLORS[tag]}"
                    if tag and _SEGMENT_COLORS.get(tag) else "",
                    _SEGMENT_STYLES.get(tag, "") if tag else "",
                ) if bit)
                parts.append(f"<span style='{style}'>{escaped}</span>" if style else escaped)
            rendered.append(f"<div align='center'>{''.join(parts)}</div>")
        return "".join(rendered)
