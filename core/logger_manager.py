from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable


# Register custom SUCCESS level (between INFO=20 and WARNING=30)
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


class _CallbackHandler(logging.Handler):
  """
  Custom logging handler that invokes a callback on every log record.

  Used to stream log messages to the GUI log panel in real time.

  :param callback: Function receiving (formatted_message, level_number).
  :type callback: Callable[[str, int], None]
  """

  def __init__(self, callback: Callable[[str, int], None]) -> None:
    """
    Initialize CallbackHandler.

    :param callback: Function to invoke on each log record.
    :type callback: Callable[[str, int], None]
    """
    super().__init__()
    self._callback = callback

  def emit(self, record: logging.LogRecord) -> None:
    """
    Emit a log record by invoking the registered callback.

    :param record: The log record to emit.
    :type record: logging.LogRecord
    """
    try:
      msg = self.format(record)
      self._callback(msg, record.levelno)
    except Exception:
      self.handleError(record)


class LoggerManager:
  """
  Centralized logging manager for the TikTok Uploader application.

  Supports console output, optional file logging, a custom SUCCESS level,
  and a callback mechanism for streaming logs to a GUI panel.

  Usage::

      logger = LoggerManager(name="MyApp")
      logger.info("Application started")
      logger.success("Upload complete")

  :param name: Logger name identifier.
  :type name: str
  :param log_file: Optional path to a log file for persistent logging.
  :type log_file: Path | None
  :param level: Minimum logging level.
  :type level: int
  """

  SUCCESS: int = SUCCESS_LEVEL

  def __init__(
    self,
    name: str = "TikTokUploader",
    log_file: Path | None = None,
    level: int = logging.DEBUG,
  ) -> None:
    """
    Initialize LoggerManager.

    :param name: Logger name.
    :type name: str
    :param log_file: Optional path to log file.
    :type log_file: Path | None
    :param level: Minimum logging level.
    :type level: int
    """
    self._logger = logging.getLogger(name)
    self._logger.setLevel(level)
    self._logger.propagate = False
    self._callback_handler: _CallbackHandler | None = None

    # Prevent duplicate handlers on re-initialization
    if not self._logger.handlers:
      self._setup_console_handler()

    if log_file is not None:
      self._setup_file_handler(log_file)

  def _setup_console_handler(self) -> None:
    """
    Configure and attach a console (stdout) handler with colored formatting.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
      fmt="%(asctime)s %(levelname)-8s %(message)s",
      datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    self._logger.addHandler(handler)

  def _setup_file_handler(self, log_file: Path) -> None:
    """
    Configure and attach a file handler.

    :param log_file: Path to the log file.
    :type log_file: Path
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(str(log_file), encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
      fmt="%(asctime)s %(levelname)-8s %(name)s %(message)s",
      datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    self._logger.addHandler(handler)

  def debug(self, msg: str) -> None:
    """
    Log a message at DEBUG level.

    :param msg: The message to log.
    :type msg: str
    """
    self._logger.debug(msg)

  def info(self, msg: str) -> None:
    """
    Log a message at INFO level.

    :param msg: The message to log.
    :type msg: str
    """
    self._logger.info(msg)

  def warning(self, msg: str) -> None:
    """
    Log a message at WARNING level.

    :param msg: The message to log.
    :type msg: str
    """
    self._logger.warning(msg)

  def error(self, msg: str) -> None:
    """
    Log a message at ERROR level.

    :param msg: The message to log.
    :type msg: str
    """
    self._logger.error(msg)

  def success(self, msg: str) -> None:
    """
    Log a message at custom SUCCESS level (25).

    :param msg: The message to log.
    :type msg: str
    """
    self._logger.log(SUCCESS_LEVEL, msg)

  def add_handler(self, handler: logging.Handler) -> None:
    """
    Attach an additional logging handler.

    :param handler: The handler to add.
    :type handler: logging.Handler
    """
    self._logger.addHandler(handler)

  def set_callback(self, callback: Callable[[str, int], None]) -> None:
    """
    Register a callback for GUI log streaming.

    Every log message emitted after registration will invoke the callback
    with the formatted message string and the numeric log level.

    :param callback: Function receiving (message, level).
    :type callback: Callable[[str, int], None]
    """
    # Remove previous callback handler if any
    if self._callback_handler is not None:
      self._logger.removeHandler(self._callback_handler)

    self._callback_handler = _CallbackHandler(callback)
    formatter = logging.Formatter(
      fmt="%(asctime)s %(levelname)-8s %(message)s",
      datefmt="%H:%M:%S",
    )
    self._callback_handler.setFormatter(formatter)
    self._logger.addHandler(self._callback_handler)

  def remove_callback(self) -> None:
    """
    Remove the currently registered GUI callback handler.
    """
    if self._callback_handler is not None:
      self._logger.removeHandler(self._callback_handler)
      self._callback_handler = None
