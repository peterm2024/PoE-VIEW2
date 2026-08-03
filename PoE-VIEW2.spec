# -*- mode: python ; coding: utf-8 -*-
"""Build-Rezept für die eigenständige Windows-.exe (siehe RELEASING.md).

Aufruf: pyinstaller PoE-VIEW2.spec
Ergebnis: dist/PoE-VIEW2.exe (Single-File, kein Python nötig).

`collect_all('keyring')` ist nötig, weil keyring seine Backends (hier:
Windows Credential Manager) über einen dynamischen Plugin-Mechanismus
lädt, den PyInstallers statische Analyse allein nicht findet — ohne das
würde die gepackte .exe zur Laufzeit keinen Token speichern können.

Das Icon wird zweifach gebraucht: `icon=` unten brennt es fest in die
.exe (das ist es, was Explorer und Taskleiste anzeigen), der Eintrag in
`datas` legt dieselbe Datei zusätzlich ins Bundle, weil `main.py` sie
zur Laufzeit als Fenster-Icon setzt. Neu erzeugen lässt sie sich mit
`python tools/make_icon.py`.
"""
from PyInstaller.utils.hooks import collect_all

datas = [('assets/PoE-VIEW2.ico', 'assets')]
binaries = []
hiddenimports = ['keyring.backends.Windows']
tmp_ret = collect_all('keyring')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PoE-VIEW2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/PoE-VIEW2.ico',
)
