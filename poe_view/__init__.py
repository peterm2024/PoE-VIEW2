"""PoE-VIEW2 — Path of Exile Account-/Stash-Viewer (Python-Edition).

Schichten (Abhängigkeiten zeigen nur nach unten, siehe docs/ARCHITEKTUR.md §3):
  ui/       PySide6-Oberfläche
  services/ Worker-Thread, Icon-Cache, Token-Speicher
  api/      reines Python: OAuth, HTTP-Client, Rate-Limiter, Datenmodelle
"""

__version__ = "0.5.0"
