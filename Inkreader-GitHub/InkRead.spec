# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs

root = Path(SPECPATH)
translation_binaries = (
    collect_dynamic_libs("ctranslate2")
    + collect_dynamic_libs("sentencepiece")
)

a = Analysis(
    ["app.py"],
    pathex=[str(root)],
    binaries=translation_binaries,
    datas=[
        (str(root / "dist"), "dist"),
        (str(root / "assets"), "assets"),
    ],
    hiddenimports=[
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebChannel",
        "fitz",
        "ctranslate2",
        "ctranslate2._ext",
        "sentencepiece",
        "sentencepiece._sentencepiece",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "torchaudio",
        "transformers",
        "tokenizers",
        "huggingface_hub",
        "hf_xet",
        "cv2",
        "PIL",
        "fontTools",
        "numpy",
        "scipy",
        "pandas",
        "matplotlib",
        "openpyxl",
        "sqlalchemy",
        "pygame",
        "psutil",
        "sklearn",
        "tensorflow",
        "notebook",
        "IPython",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InkRead",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "assets" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="InkRead",
)
