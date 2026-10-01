"""Minimal Qt bootstrap; login runs asynchronously after the window is created."""
import sys
from PySide6.QtWidgets import QApplication
from .ui.main_window import MainWindow
from . import __version__


class YtMusicVaultApp:
    def __init__(self, auto_restore=True):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("YtMusicVault")
        self._app.setApplicationVersion(__version__)
        self._app.setOrganizationName("YtMusicVault")
        self._window = MainWindow(auto_restore=auto_restore)

    def run(self):
        self._window.show()
        return self._app.exec()
