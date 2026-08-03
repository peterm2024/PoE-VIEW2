"""Baut aus den Quell-PNGs in ``assets/icon/`` die mehrstufige
Windows-Icondatei ``assets/PoE-VIEW2.ico``.

Aufruf: python tools/make_icon.py

Warum ein eigener Generator statt eines Bildbearbeitungspakets: Qt kann
zwar ``.ico`` schreiben (``QImageWriter``), aber immer nur EIN Bild pro
Datei — eine mehrstufige Icondatei ist damit nicht zu bauen. Der
ICO-Container ist andererseits so simpel (ein Kopf, ein Verzeichnis, die
Bilddaten), dass ihn diese Datei selbst schreibt. Damit kommt der Build
ohne zusätzliche Abhängigkeit aus: PySide6 liegt ohnehin vor und
erledigt Laden, Skalieren und PNG-Kodierung.

Warum überhaupt mehrere Stufen: Peter hat die Grafik bewusst in vier
Detailgraden gezeichnet (2026-08-03). Würde man nur die große Fassung
einbetten, skaliert Windows sie selbst auf 16 px herunter und der
Runenring zerfällt zu Matsch. Die Zuordnung in ``LAYOUT`` bildet Peters
Absicht ab: je kleiner die Zielgröße, desto reduzierter die Vorlage.

Die Quelldateien sind nicht exakt quadratisch (z. B. 490x504), deshalb
wird jede Vorlage seitenverhältnis-treu eingepasst und mittig auf eine
transparente quadratische Fläche gelegt — Verzerren wäre bei einem
Zahnrad sofort sichtbar.

``assets/icon/PoEVIEW_full.png`` taucht in ``LAYOUT`` bewusst nicht auf:
sie ist die größte Fassung und liegt als Archiv daneben, gebaut wird aus
den vier abgestuften Vorlagen. Nicht versehentlich „aufräumen".
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "assets" / "icon"
OUT_FILE = ROOT / "assets" / "PoE-VIEW2.ico"

# Zielgröße in Pixeln -> Vorlage. Mehrfachnennungen sind Absicht: für 24
# reicht die reduzierteste Fassung, 64 profitiert noch von der mittleren.
LAYOUT: dict[int, str] = {
    16: "PoEVIEW_16.png",    # nur Zahnrad + Auge
    24: "PoEVIEW_16.png",
    32: "PoEVIEW_32.png",    # runde Fassung mit Runenkranz
    48: "PoEVIEW_48.png",    # abgerundetes Quadrat, mittlerer Detailgrad
    64: "PoEVIEW_48.png",
    128: "PoEVIEW_256.png",  # volle Detailtiefe
    256: "PoEVIEW_256.png",
}

# Ab dieser Kantenlänge wird PNG-komprimiert eingebettet statt als
# unkomprimiertes DIB. Grund: 256x256 als DIB wären allein 256 KB, als
# PNG ein Bruchteil davon. Unterhalb davon bleibt es bei DIB, weil das
# die historisch überall unterstützte Form ist und die paar KB nicht
# weh tun — PNG-in-ICO versteht zwar jedes Windows ab Vista, aber es
# gibt keinen Grund, die Kompatibilität ohne Gegenwert einzutauschen.
PNG_FROM = 64


def square_scaled(source: QImage, size: int) -> QImage:
    """Seitenverhältnis-treu auf ``size`` einpassen und mittig auf eine
    transparente quadratische Fläche legen."""
    scaled = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    canvas = QImage(size, size, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawImage((size - scaled.width()) // 2,
                      (size - scaled.height()) // 2, scaled)
    painter.end()
    return canvas


def as_png(image: QImage) -> bytes:
    # QBuffer OHNE Argument: ein `QBuffer(QByteArray())` bekäme einen
    # temporären Puffer untergeschoben, den Python sofort wieder freigibt
    # — das quittiert Qt mit einem Absturz statt einer Fehlermeldung.
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def as_dib(image: QImage) -> bytes:
    """Klassische ICO-Bilddaten: BITMAPINFOHEADER, danach die Pixel von
    UNTEN nach oben, danach die AND-Maske.

    Zwei Eigenheiten des Formats, die man leicht übersieht: ``biHeight``
    trägt die DOPPELTE Bildhöhe (Farb- und Maskenteil zusammengezählt),
    und die AND-Maske muss vorhanden sein, obwohl 32-Bit-Icons ihre
    Transparenz längst aus dem Alphakanal beziehen — sie bleibt hier
    deshalb komplett auf null.
    """
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    # Format_ARGB32 liegt im Speicher als B,G,R,A vor — genau die
    # Bytefolge, die das DIB erwartet, also kein Umsortieren nötig.
    bits = image.constBits()
    stride = image.bytesPerLine()
    rows = [bytes(bits[y * stride:y * stride + width * 4]) for y in range(height)]

    header = struct.pack("<IiiHHIIiiII",
                         40,             # biSize
                         width,          # biWidth
                         height * 2,     # biHeight (Farbe + Maske)
                         1,              # biPlanes
                         32,             # biBitCount
                         0,              # biCompression = BI_RGB
                         0,              # biSizeImage
                         0, 0,           # Auflösung, irrelevant
                         0, 0)           # Palette, keine
    mask_stride = ((width + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * height)
    return header + b"".join(reversed(rows)) + mask


def build() -> None:
    entries: list[tuple[int, bytes]] = []
    for size in sorted(LAYOUT):
        source_path = SRC_DIR / LAYOUT[size]
        source = QImage(str(source_path))
        if source.isNull():
            raise SystemExit(f"Quelldatei nicht lesbar: {source_path}")
        image = square_scaled(source, size)
        data = as_png(image) if size >= PNG_FROM else as_dib(image)
        entries.append((size, data))
        print(f"  {size:>3} px  aus {LAYOUT[size]:<16} "
              f"{'PNG' if size >= PNG_FROM else 'DIB'}  {len(data):>7} Bytes")

    # ICONDIR, danach je Bild ein 16 Byte langer ICONDIRENTRY, danach die
    # Bilddaten am Stück.
    offset = 6 + 16 * len(entries)
    directory = struct.pack("<HHH", 0, 1, len(entries))
    for size, data in entries:
        directory += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,  # 0 steht im Format für 256
            size if size < 256 else 0,
            0,        # keine Palette
            0,        # reserviert
            1,        # Ebenen
            32,       # Bit pro Pixel
            len(data),
            offset)
        offset += len(data)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_bytes(directory + b"".join(data for _, data in entries))
    print(f"\n{OUT_FILE.relative_to(ROOT)}: {len(entries)} Stufen, "
          f"{OUT_FILE.stat().st_size} Bytes")


if __name__ == "__main__":
    QApplication(sys.argv)  # QImage/QPainter brauchen eine laufende App
    build()
