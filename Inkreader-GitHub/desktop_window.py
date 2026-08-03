from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow

from config import APP_ID, APP_NAME, BASE_DIR, PORT
from web_server import start_server


class DesktopPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if os.getenv("INKREAD_DEBUG"):
            print(f"[web:{line}] {message}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1540, 960)
        self.setMinimumSize(1080, 680)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            max(0, (screen.width() - self.width()) // 2),
            max(0, (screen.height() - self.height()) // 2),
        )
        icon = BASE_DIR / "assets" / "app.ico"
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
        self.web = QWebEngineView()
        self.web.setPage(DesktopPage(self.web))
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        settings = self.web.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.web.setUrl(QUrl(f"http://127.0.0.1:{PORT}"))
        self.setCentralWidget(self.web)
        self.setStyleSheet("QMainWindow { background: #efe8d8; }")


def _wait_for_server() -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/api/health", timeout=0.5
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.15)
    raise RuntimeError("本地服务启动超时")


def run_desktop() -> int:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    _wait_for_server()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("InkRead")
    app.setApplicationDisplayName(APP_NAME)
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor("#efe8d8"))
    app.setPalette(palette)
    window = MainWindow()
    window.show()
    return app.exec()
