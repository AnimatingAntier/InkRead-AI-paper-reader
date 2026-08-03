from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "砚读 InkRead"
APP_ID = "InkRead.Desktop.1"
PORT = int(os.getenv("INKREAD_PORT", "3217"))


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            return Path(bundle_dir).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = app_base_dir()
DIST_DIR = BASE_DIR / "dist"
if getattr(sys, "frozen", False):
    _default_data = Path(os.getenv("LOCALAPPDATA", str(BASE_DIR))) / "InkRead"
else:
    _default_data = BASE_DIR / "data"
DATA_DIR = Path(os.getenv("INKREAD_DATA_DIR", str(_default_data)))
DOCUMENT_DIR = DATA_DIR / "documents"
SETTINGS_FILE = DATA_DIR / "settings.json"
MANIFEST_FILE = DATA_DIR / "library.json"

for directory in (DATA_DIR, DOCUMENT_DIR):
    directory.mkdir(parents=True, exist_ok=True)
