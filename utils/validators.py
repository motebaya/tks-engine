from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.schedule_rule_engine import ScheduleRuleEngine


class Validators:
  """
  Static validation methods for file paths, schedule parameters,
  cookie data, captions, and configuration values.

  Schedule-time validation delegates to :class:`ScheduleRuleEngine`
  so that a single source of truth governs all scheduling constraints
  across both GUI and backend.
  """

  VALID_EXTENSIONS: list[str] = [".mp4"]
  VALID_VISIBILITY_MODES: list[str] = ["private", "public", "friends"]
  MAX_CAPTION_LENGTH: int = 2200

  @staticmethod
  def validate_video_path(path: Path) -> bool:
    """
    Validate that a path points to a valid uploadable video file.

    Checks: exists, is a file, has .mp4 extension, non-zero size.

    :param path: Path to validate.
    :type path: Path
    :return: True if the path is a valid video file.
    :rtype: bool
    """
    if not path.exists():
      return False
    if not path.is_file():
      return False
    if path.suffix.lower() not in Validators.VALID_EXTENSIONS:
      return False
    if path.stat().st_size == 0:
      return False
    return True

  @staticmethod
  def validate_directory(path: Path) -> bool:
    """
    Validate that a path points to an existing, readable directory.

    :param path: Path to validate.
    :type path: Path
    :return: True if the directory is valid and accessible.
    :rtype: bool
    """
    if not path.exists():
      return False
    if not path.is_dir():
      return False
    try:
      list(path.iterdir())
      return True
    except PermissionError:
      return False

  @staticmethod
  def validate_schedule_time(
    dt: datetime,
    rule_engine: ScheduleRuleEngine,
  ) -> tuple[bool, str]:
    """
    Validate a datetime against the centralized scheduling rules.

    Delegates entirely to :meth:`ScheduleRuleEngine.validate`.

    :param dt: The datetime to validate.
    :type dt: datetime
    :param rule_engine: The authoritative rule engine instance.
    :type rule_engine: ScheduleRuleEngine
    :return: Tuple of ``(is_valid, reason_string)``.
    :rtype: tuple[bool, str]
    """
    return rule_engine.validate(dt)

  @staticmethod
  def validate_date_range(
    start: datetime,
    end: datetime,
    rule_engine: ScheduleRuleEngine,
  ) -> tuple[bool, str]:
    """
    Validate a full date range against scheduling rules.

    :param start: Range start.
    :type start: datetime
    :param end: Range end.
    :type end: datetime
    :param rule_engine: The authoritative rule engine instance.
    :type rule_engine: ScheduleRuleEngine
    :return: Tuple of ``(is_valid, reason_string)``.
    :rtype: tuple[bool, str]
    """
    return rule_engine.validate_date_range(start, end)

  @staticmethod
  def validate_cookie_data(cookies: list[dict[str, Any]]) -> tuple[bool, str]:
    """
    Validate that a list of cookie dicts contains required fields.

    Required fields per cookie: name, value, domain, path.

    :param cookies: List of cookie dictionaries.
    :type cookies: list[dict[str, Any]]
    :return: Tuple of ``(is_valid, reason_string)``.
    :rtype: tuple[bool, str]
    """
    if not cookies:
      return (False, "Cookie list is empty")

    required_fields = ["name", "value", "domain", "path"]
    for idx, cookie in enumerate(cookies):
      if not isinstance(cookie, dict):
        return (False, f"Cookie at index {idx} is not a dictionary")
      for field in required_fields:
        val = cookie.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
          return (False, f"Cookie at index {idx} missing required field: {field}")

    return (True, "Valid")

  @staticmethod
  def validate_caption(text: str) -> tuple[bool, str]:
    """
    Validate a video caption string.

    Checks length limits against TikTok's maximum.

    :param text: Caption text to validate.
    :type text: str
    :return: Tuple of ``(is_valid, reason_string)``.
    :rtype: tuple[bool, str]
    """
    if not isinstance(text, str):
      return (False, "Caption must be a string")
    if len(text) > Validators.MAX_CAPTION_LENGTH:
      return (False, f"Caption exceeds maximum length of {Validators.MAX_CAPTION_LENGTH} characters")
    return (True, "Valid")

  @staticmethod
  def validate_visibility(mode: str) -> bool:
    """
    Check that a visibility mode is one of the accepted values.

    Accepted: ``"private"``, ``"public"``, ``"friends"``.

    :param mode: Visibility mode string.
    :type mode: str
    :return: True if the mode is valid.
    :rtype: bool
    """
    return mode.lower() in Validators.VALID_VISIBILITY_MODES

  @staticmethod
  def sanitize_path(path: str) -> Path:
    """
    Resolve and normalize a file path to prevent traversal attacks.

    :param path: Raw path string from user input.
    :type path: str
    :return: Cleaned, resolved Path object.
    :rtype: Path
    """
    return Path(path).resolve()
