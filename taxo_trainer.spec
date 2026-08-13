# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for taxo-trainer directory-based desktop executable bundle."""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Identify root path (SPECPATH is provided by PyInstaller when building)
try:
    ROOT_DIR = Path(SPECPATH)
except NameError:
    ROOT_DIR = Path.cwd()

# Define bundled assets and resource paths
added_files = [
    (str(ROOT_DIR / "assets"), "assets"),
    (str(ROOT_DIR / "src" / "data"), "data"),
]

hidden_imports = [
    "nicegui",
    "webview",
    "platformdirs",
    "taxo_trainer",
    "taxo_trainer.app",
    "taxo_trainer.db",
    "taxo_trainer.resources",
    "taxo_trainer.engine",
    "taxo_trainer.ui",
    "taxo_trainer.ingestion",
]

hidden_imports.extend(collect_submodules("nicegui"))
hidden_imports.extend(collect_submodules("webview"))

a = Analysis(
    [str(ROOT_DIR / "main.py")],
    pathex=[str(ROOT_DIR / "src")],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="taxo-trainer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT_DIR / "assets" / "guides" / "initial_dataset_setup" / "step1_header.png")
    if (ROOT_DIR / "assets" / "guides" / "initial_dataset_setup" / "step1_header.png").exists()
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="taxo-trainer",
)
