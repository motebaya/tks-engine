from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


class ConfigManager:
  """
  Centralized configuration manager for the TikTok Uploader application.

  Loads ``config.json`` at startup, validates every key against safe
  defaults, and exposes typed accessors for all runtime parameters.
  If the file is missing it is auto-generated with defaults.  If
  individual values are invalid they fall back silently and a warning
  is recorded for the caller to surface.

  :param config_path: Absolute path to ``config.json``.
  :type config_path: Path
  """

  DEFAULTS: dict[str, Any] = {
    "windowSize": {"width": 1200, "height": 800},
    "minWindowSize": {"width": 900, "height": 600},
    "theme": "neumorphism_dark",
    "primaryColor": "#1E66FF",
    "logLevel": "INFO",
    "enableVerbose": False,
    "headlessDefault": True,
    "scheduleRules": {
      "minOffsetMinutes": 15,
      "maxOffsetMonths": 1,
      "minuteStep": 5,
    },
    "paths": {
      "storageDir": "storage",
      "cookiesDir": "cookies",
    },
  }

  VALID_LOG_LEVELS: list[str] = [
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL",
  ]

  def __init__(self, config_path: Path) -> None:
    """
    Initialize ConfigManager.

    :param config_path: Path to the config JSON file.
    :type config_path: Path
    """
    self._path = config_path
    self._data: dict[str, Any] = {}
    self._warnings: list[str] = []
    self._load()

  # ------------------------------------------------------------------
  # Loading / generation
  # ------------------------------------------------------------------

  def _load(self) -> None:
    """
    Load config from disk.  Auto-generate with defaults when missing.
    """
    if not self._path.exists():
      self._warnings.append(
        f"config.json not found at {self._path} -- generating defaults"
      )
      self._data = dict(self.DEFAULTS)
      self._save()
      return

    try:
      with open(self._path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
      self._warnings.append(f"Failed to parse config.json: {exc}")
      self._data = dict(self.DEFAULTS)
      return

    if not isinstance(raw, dict):
      self._warnings.append("config.json root is not an object -- using defaults")
      self._data = dict(self.DEFAULTS)
      return

    self._data = self._merge(self.DEFAULTS, raw)

  def _save(self) -> None:
    """
    Persist current config data back to ``config.json``.
    """
    try:
      self._path.parent.mkdir(parents=True, exist_ok=True)
      with open(self._path, "w", encoding="utf-8") as fh:
        json.dump(self._data, fh, indent=2, ensure_ascii=False)
    except OSError as exc:
      self._warnings.append(f"Failed to write config.json: {exc}")

  def _merge(
    self,
    defaults: dict[str, Any],
    overrides: dict[str, Any],
  ) -> dict[str, Any]:
    """
    Recursively merge *overrides* into *defaults*, keeping defaults
    for any missing or wrongly-typed keys.

    :param defaults: Default config structure.
    :type defaults: dict[str, Any]
    :param overrides: User-supplied overrides.
    :type overrides: dict[str, Any]
    :return: Merged dictionary.
    :rtype: dict[str, Any]
    """
    merged: dict[str, Any] = {}
    for key, default_val in defaults.items():
      user_val = overrides.get(key)
      if user_val is None:
        merged[key] = default_val
        continue
      if isinstance(default_val, dict):
        if isinstance(user_val, dict):
          merged[key] = self._merge(default_val, user_val)
        else:
          self._warnings.append(
            f"config key '{key}' expected object, got {type(user_val).__name__} -- using default"
          )
          merged[key] = default_val
      else:
        if type(user_val) is type(default_val):
          merged[key] = user_val
        else:
          # Allow int/float coercion for numeric fields
          if isinstance(default_val, (int, float)) and isinstance(user_val, (int, float)):
            merged[key] = type(default_val)(user_val)
          else:
            self._warnings.append(
              f"config key '{key}' expected {type(default_val).__name__}, "
              f"got {type(user_val).__name__} -- using default"
            )
            merged[key] = default_val
    return merged

  # ------------------------------------------------------------------
  # Public accessors
  # ------------------------------------------------------------------

  @property
  def warnings(self) -> list[str]:
    """
    Warnings accumulated during load / validation.

    :rtype: list[str]
    """
    return list(self._warnings)

  @property
  def window_size(self) -> tuple[int, int]:
    """
    Default launch window size ``(width, height)``.

    :rtype: tuple[int, int]
    """
    ws = self._data.get("windowSize", self.DEFAULTS["windowSize"])
    return (int(ws.get("width", 1200)), int(ws.get("height", 800)))

  @property
  def min_window_size(self) -> tuple[int, int]:
    """
    Minimum window size ``(width, height)``.

    :rtype: tuple[int, int]
    """
    ms = self._data.get("minWindowSize", self.DEFAULTS["minWindowSize"])
    return (int(ms.get("width", 900)), int(ms.get("height", 600)))

  @property
  def theme(self) -> str:
    """
    Active theme identifier.

    :rtype: str
    """
    return str(self._data.get("theme", self.DEFAULTS["theme"]))

  @property
  def primary_color(self) -> str:
    """
    Primary action colour (hex string, e.g. ``#1E66FF``).

    :rtype: str
    """
    return str(self._data.get("primaryColor", self.DEFAULTS["primaryColor"]))

  @property
  def log_level(self) -> int:
    """
    Logging level as a ``logging`` constant.

    :rtype: int
    """
    name = str(self._data.get("logLevel", "INFO")).upper()
    if name not in self.VALID_LOG_LEVELS:
      name = "INFO"
    return getattr(logging, name, logging.INFO)

  @property
  def log_level_name(self) -> str:
    """
    Logging level as a human-readable string.

    :rtype: str
    """
    name = str(self._data.get("logLevel", "INFO")).upper()
    if name not in self.VALID_LOG_LEVELS:
      return "INFO"
    return name

  @property
  def enable_verbose(self) -> bool:
    """
    Whether verbose (DEBUG-level) logging is enabled.

    When ``True``, the effective log level is forced to ``DEBUG``
    regardless of ``logLevel``.  When ``False``, ``logLevel`` is
    used as-is (default ``INFO``).

    :rtype: bool
    """
    return bool(self._data.get("enableVerbose", False))

  @property
  def effective_log_level(self) -> int:
    """
    Effective logging level considering ``enableVerbose``.

    Returns ``logging.DEBUG`` if verbose is enabled, otherwise
    falls back to :attr:`log_level`.

    :rtype: int
    """
    if self.enable_verbose:
      return logging.DEBUG
    return self.log_level

  @property
  def headless_default(self) -> bool:
    """
    Whether the browser should default to headless mode.

    :rtype: bool
    """
    return bool(self._data.get("headlessDefault", True))

  # -- schedule rules --

  @property
  def min_offset_minutes(self) -> int:
    """
    Minimum future offset for scheduling (minutes).

    :rtype: int
    """
    rules = self._data.get("scheduleRules", {})
    return int(rules.get("minOffsetMinutes", 15))

  @property
  def max_offset_months(self) -> int:
    """
    Maximum future offset for scheduling (calendar months).

    :rtype: int
    """
    rules = self._data.get("scheduleRules", {})
    return int(rules.get("maxOffsetMonths", 1))

  @property
  def minute_step(self) -> int:
    """
    Minute granularity for the scheduler (must be a divisor of 60).

    :rtype: int
    """
    rules = self._data.get("scheduleRules", {})
    return int(rules.get("minuteStep", 5))

  # -- paths --

  @property
  def storage_dir(self) -> str:
    """
    Relative path to the storage directory.

    :rtype: str
    """
    paths = self._data.get("paths", {})
    return str(paths.get("storageDir", "storage"))

  @property
  def cookies_dir(self) -> str:
    """
    Relative path to the cookies directory.

    :rtype: str
    """
    paths = self._data.get("paths", {})
    return str(paths.get("cookiesDir", "cookies"))
