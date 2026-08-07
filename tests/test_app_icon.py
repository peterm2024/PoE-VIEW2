"""Tests für die mitgelieferte Icondatei (Peter, 2026-08-03: eigene
Grafik in vier Detailgraden, gebaut von ``tools/make_icon.py``).

Die .ico wird als fertige Datei versioniert, nicht beim Build erzeugt —
diese Tests sind deshalb die einzige Stelle, an der auffiele, wenn sie
verlorenginge oder beim Regenerieren kaputt ginge.
"""

import struct

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage

from poe_view import config

EXPECTED_SIZES = [16, 24, 32, 48, 64, 128, 256]


def test_the_icon_file_ships_with_the_project() -> None:
    assert config.APP_ICON.is_file(), f"fehlt: {config.APP_ICON}"


def test_the_icon_contains_every_expected_size(qapp) -> None:
    """Mehrstufig ist der ganze Zweck: ohne die kleinen Stufen würde
    Windows die große Fassung selbst auf 16 px herunterrechnen und der
    Runenring würde unkenntlich."""
    icon = QIcon(str(config.APP_ICON))
    sizes = sorted(s.width() for s in icon.availableSizes())
    assert sizes == EXPECTED_SIZES


def test_the_icon_directory_is_structurally_intact() -> None:
    """Prüft den ICO-Container selbst statt über Qt: Kopf, Anzahl und
    dass die Bilddaten lückenlos bis genau ans Dateiende reichen. Ein
    Fehler im selbstgeschriebenen Generator (``tools/make_icon.py``)
    zeigt sich hier, auch wenn Qt beim Lesen darüber hinwegsähe."""
    raw = config.APP_ICON.read_bytes()
    reserved, image_type, count = struct.unpack("<HHH", raw[:6])
    assert (reserved, image_type) == (0, 1)  # 1 = Icon (2 wäre ein Cursor)
    assert count == len(EXPECTED_SIZES)

    offset = 6 + 16 * count  # direkt hinter dem Verzeichnis
    for index in range(count):
        entry = raw[6 + index * 16:22 + index * 16]
        width, height, _colors, _res, planes, bpp, length, start = struct.unpack(
            "<BBBBHHII", entry)
        assert (width or 256) == EXPECTED_SIZES[index]
        assert (height or 256) == EXPECTED_SIZES[index]  # 0 steht für 256
        assert (planes, bpp) == (1, 32)
        assert start == offset, "Bilddaten müssen lückenlos aufeinander folgen"
        offset += length
    assert offset == len(raw), "hinter dem letzten Bild darf nichts übrig sein"


def test_the_web_png_ships_and_is_a_single_readable_image(qapp) -> None:
    """Die .png ist die Fassung für README und Hilfe-Fenster — beide
    kommen mit einer mehrstufigen .ico nicht zurecht. Sie wird wie die
    .ico als fertige Datei versioniert, hier fiele ihr Verlust auf."""
    assert config.APP_ICON_PNG.is_file(), f"fehlt: {config.APP_ICON_PNG}"
    image = QImage(str(config.APP_ICON_PNG))
    assert not image.isNull()
    assert (image.width(), image.height()) == (128, 128)


def test_the_web_png_stays_small_enough_for_a_readme(qapp) -> None:
    """Die Quellgrafiken in ``assets/icon/`` sind 0,4 bis 3 MB groß —
    eine davon direkt einzubinden wäre der naheliegende Fehler. Beim
    Regenerieren darf die Größenordnung nicht zurückrutschen."""
    assert config.APP_ICON_PNG.stat().st_size < 100_000


def _row_alpha_profile(image) -> list[int]:
    return [sum(image.pixelColor(x, y).alpha() for x in range(image.width()))
            for y in range(image.height())]


def test_the_small_sizes_are_not_upside_down(qapp) -> None:
    """DIB-Einträge speichern ihre Zeilen von unten nach oben — ein
    vergessenes Umdrehen im Generator ist der klassische Fehler und
    fiele sonst erst am fertigen Windows-Icon auf.

    Geprüft wird die 16-px-Stufe (eine der handgeschriebenen
    DIB-Einträge) gegen ihre eigene Vorlage: sie muss dem Original
    ähnlicher sein als dessen vertikaler Spiegelung.
    """
    source = QImage(str(config.PROJECT_ROOT / "assets" / "icon" / "PoEVIEW_16.png"))
    assert not source.isNull(), "Vorlage fehlt"
    expected = source.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)

    embedded = _row_alpha_profile(QIcon(str(config.APP_ICON)).pixmap(16, 16).toImage())
    upright = _row_alpha_profile(expected)
    flipped = upright[::-1]
    assert upright != flipped, "Vorlage ist senkrecht symmetrisch — Test taugt nicht"

    def distance(a: list[int], b: list[int]) -> int:
        return sum(abs(x - y) for x, y in zip(a, b))

    assert distance(embedded, upright) < distance(embedded, flipped)
