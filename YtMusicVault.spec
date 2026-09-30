# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for YtMusicVault — single .exe build."""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

a = Analysis(
    ['main.py'],
    # SPECPATH is provided by PyInstaller, regardless of the caller's cwd.
    pathex=[SPECPATH],
    binaries=[],
    datas=[
        ('GUIDE.md', '.'),
    ] + collect_data_files('ytmusicapi') + copy_metadata('ytmusicapi')
      + collect_data_files('dukpy', includes=['jsruntime/*'])
      + collect_data_files('publicsuffixlist', includes=['public_suffix_list.dat']),
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
        'socks',
        'pypac',
        'dukpy',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
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

# Qt on Windows imports the OS ICU API (unversioned symbols). A third-party
# icuuc.dll found on PATH, e.g. Poppler's ICU 78, is ABI-incompatible. Do not
# shadow the Windows system library in the extracted application directory.
if sys.platform == 'win32':
    a.binaries = [entry for entry in a.binaries
                  if Path(entry[0]).name.lower() != 'icuuc.dll']

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
    upx=False,
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
