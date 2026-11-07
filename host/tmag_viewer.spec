# -*- mode: python ; coding: utf-8 -*-
"""Unbuilt packaging template; see README before building or distributing.

Reference: https://pyinstaller.org/en/stable/spec-files.html
Qt and pyqtgraph dependencies use PyInstaller's standard hooks.
"""
from pathlib import Path

host_dir = Path(SPECPATH).resolve()
a = Analysis(
    [str(host_dir / 'run.py')],
    pathex=[str(host_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[
        'serial.tools.list_ports',
        'serial.tools.list_ports_windows',
        'serial.serialwin32',
        'serial.win32',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TMAGViewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='TMAGViewer',
)
