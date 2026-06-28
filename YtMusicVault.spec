# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for YtMusicVault — single .exe build."""

import sys
from pathlib import Path

a = Analysis(
    ['main.py'],
    pathex=[str(Path(__file__).parent)],
    binaries=[],
    datas=[
        ('ytmusicvault', 'ytmusicvault'),
    ],
    hiddenimports=[
        'ytmusicapi',
        'ytmusicapi.auth',
        'ytmusicapi.auth.oauth',
        'ytmusicapi.parsers',
        'yt_dlp',
        'mutagen',
        'mutagen.mp4',
        'mutagen.id3',
        'requests',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'scipy',
        'notebook',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='YtMusicVault',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True for debugging, False for release
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here: 'resources/icon.ico'
)
