from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from gui.controller import GUIController
from gui.main_window import MainWindow
from gui.styles import StyleSheet


class Application:
  """
  Main entry point for the TikTok Uploader GUI application.

  Loads ``config.json``, applies the configured primary colour and
  window dimensions, initializes the neumorphic stylesheet, creates
  the main window and controller, and starts the Qt event loop.

  Usage::

      python main.py
  """

  def __init__(self) -> None:
    """
    Initialize the Application instance.
    """
    self._project_root = Path(__file__).parent.resolve()

  def run(self) -> None:
    """
    Launch the GUI application.

    1. Load ``config.json`` (auto-generates defaults if missing).
    2. Apply primary colour override from config.
    3. Create QApplication with global neumorphic stylesheet.
    4. Size the window from config (default + minimum).
    5. Build controller (binds signals, loads initial state).
    6. Enter Qt event loop.
    """
    # Load config
    config_path = self._project_root / "config.json"
    config = ConfigManager(config_path)

    # Apply primary colour from config
    StyleSheet.apply_primary_color(config.primary_color)

    # Create Qt app — Fusion style is required on Windows so that
    # QSS ``background-color: transparent`` on QWidget inherits from
    # the parent paint chain instead of rendering as black.
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(StyleSheet.global_stylesheet())

    # Set global application icon
    icon_path = self._project_root / "assets" / "icon.ico"
    app.setWindowIcon(QIcon(str(icon_path)))

    # Create main window
    window = MainWindow()

    # Apply window dimensions from config
    w, h = config.window_size
    window.resize(w, h)
    mw, mh = config.min_window_size
    window.setMinimumSize(mw, mh)

    # Create controller (binds signals, loads data, starts validation timer)
    GUIController(window, config, self._project_root)

    # Show and run
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
  Application().run()
