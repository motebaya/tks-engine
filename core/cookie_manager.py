from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.logger_manager import LoggerManager


class CookieError(Exception):
  """
  Raised when cookie loading, parsing, or validation fails.
  """


class CookieManager:
  """
  Manages TikTok cookie files for Playwright browser context injection.

  Loads exported cookie JSON files from the cookies directory, normalizes
  sameSite values and expiration timestamps into Playwright-compatible
  format, validates required fields, and supports multiple accounts.

  Cookie filename convention::

      @usernameTiktok-cookie.json

  Usage::

      cm = CookieManager(Path("cookies"), logger)
      accounts = cm.list_accounts()
      cookies = cm.load_cookie(accounts[0])

  :param cookies_dir: Path to the directory containing cookie JSON files.
  :type cookies_dir: Path
  :param logger: Logger instance for status messages.
  :type logger: LoggerManager
  """

  COOKIE_PATTERN: str = r"^@(.+)-cookie\.json$"

  SAME_SITE_MAP: dict[str, str] = {
    "strict": "Strict",
    "lax": "Lax",
    "none": "None",
    "no_restriction": "None",
    "unspecified": "Lax",
  }

  SAME_SITE_NUMERIC: dict[int, str] = {
    0: "None",
    1: "Lax",
    2: "Strict",
  }

  REQUIRED_FIELDS: list[str] = ["name", "value", "domain", "path"]

  def __init__(self, cookies_dir: Path, logger: LoggerManager) -> None:
    """
    Initialize CookieManager.

    :param cookies_dir: Path to the cookies directory.
    :type cookies_dir: Path
    :param logger: Logger instance.
    :type logger: LoggerManager
    """
    self._cookies_dir = cookies_dir
    self._logger = logger

    if not self._cookies_dir.exists():
      self._cookies_dir.mkdir(parents=True, exist_ok=True)
      self._logger.warning(f"Created cookies directory: {self._cookies_dir}")

  def list_accounts(self) -> list[str]:
    """
    Scan the cookies directory for cookie files and extract usernames.

    Searches for files matching the pattern ``@<username>-cookie.json``.

    :return: List of extracted usernames (without '@' prefix).
    :rtype: list[str]
    """
    accounts: list[str] = []

    for file_path in self._cookies_dir.iterdir():
      if file_path.is_file():
        username = self._extract_username(file_path.name)
        if username is not None:
          accounts.append(username)

    accounts.sort()
    self._logger.info(f"Found {len(accounts)} account(s): {accounts}")
    return accounts

  def load_cookie(self, username: str) -> list[dict[str, Any]]:
    """
    Load and normalize the cookie file for a given username.

    :param username: The account username (without '@' prefix).
    :type username: str
    :return: List of Playwright-compatible cookie dictionaries.
    :rtype: list[dict[str, Any]]
    :raises CookieError: If the file cannot be loaded or parsed.
    """
    cookie_path = self._build_cookie_path(username)

    if not cookie_path.exists():
      raise CookieError(f"Cookie file not found: {cookie_path}")

    self._logger.info(f"Loading cookies for @{username}")

    try:
      with open(cookie_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
      raise CookieError(f"Failed to read cookie file: {e}")

    if not isinstance(raw, list):
      raise CookieError("Cookie file must contain a JSON array of cookie objects")

    normalized = self.normalize_cookie(raw)

    if not self.validate_cookie(normalized):
      raise CookieError("Cookie validation failed after normalization")

    self._logger.success(f"Loaded {len(normalized)} cookie(s) for @{username}")
    return normalized

  def validate_cookie(self, cookies: list[dict[str, Any]]) -> bool:
    """
    Validate that all cookies contain the required fields with non-empty values.

    Required fields: name, value, domain, path.

    :param cookies: List of cookie dictionaries to validate.
    :type cookies: list[dict[str, Any]]
    :return: True if all cookies are valid.
    :rtype: bool
    """
    if not cookies:
      self._logger.error("Cookie list is empty")
      return False

    for idx, cookie in enumerate(cookies):
      for field in self.REQUIRED_FIELDS:
        val = cookie.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
          self._logger.error(
            f"Cookie #{idx} missing required field '{field}'"
          )
          return False

    return True

  def normalize_cookie(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalize a list of raw cookie exports into Playwright-compatible format.

    Handles sameSite conversion, expires normalization, field defaults,
    and type casting. Skips entries missing name or domain.

    :param raw: Raw cookie list from JSON export.
    :type raw: list[dict[str, Any]]
    :return: Normalized cookie list ready for ``context.add_cookies()``.
    :rtype: list[dict[str, Any]]
    """
    fixed: list[dict[str, Any]] = []

    for cookie in raw:
      if not isinstance(cookie, dict):
        continue

      name = cookie.get("name")
      value = cookie.get("value")

      # Must have a non-empty string name
      if not isinstance(name, str) or not name:
        continue

      # Value can be cast to string
      if value is None:
        continue
      if not isinstance(value, str):
        value = str(value)

      domain = cookie.get("domain")
      path = cookie.get("path") or "/"

      # Must have a domain
      if not isinstance(domain, str) or not domain:
        continue

      # Path must start with /
      if not isinstance(path, str) or not path.startswith("/"):
        path = "/"

      cookie_out: dict[str, Any] = {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path,
        "secure": bool(cookie.get("secure", False)),
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "sameSite": self._normalize_same_site(cookie.get("sameSite")),
      }

      # Handle expires / expirationDate
      expires = self._normalize_expires(cookie.get("expirationDate"))
      is_session = bool(cookie.get("session", False))

      if not is_session and expires is not None:
        cookie_out["expires"] = expires

      fixed.append(cookie_out)

    return fixed

  def _normalize_same_site(
    self,
    value: str | int | float | None,
  ) -> str:
    """
    Map variant sameSite values to Playwright-accepted strings.

    Playwright only accepts: "Strict", "Lax", "None" (case-sensitive).
    TikTok/Chrome exports may use null, "no_restriction", lowercase,
    numeric codes, or other non-standard values.

    :param value: Raw sameSite value from cookie export.
    :type value: str | int | float | None
    :return: One of "Strict", "Lax", or "None".
    :rtype: str
    """
    if value is None:
      return "Lax"

    if isinstance(value, (int, float)):
      return self.SAME_SITE_NUMERIC.get(int(value), "Lax")

    if isinstance(value, str):
      normalized = value.strip().lower()
      return self.SAME_SITE_MAP.get(normalized, "Lax")

    return "Lax"

  def _normalize_expires(
    self,
    expiration_date: int | float | None,
  ) -> int | None:
    """
    Convert expirationDate to Playwright-compatible expires (epoch seconds).

    Handles float values, millisecond timestamps, and invalid types.

    :param expiration_date: Raw expiration value from cookie export.
    :type expiration_date: int | float | None
    :return: Integer epoch seconds, or None if not applicable.
    :rtype: int | None
    """
    if expiration_date is None:
      return None

    try:
      exp = float(expiration_date)
    except (TypeError, ValueError):
      return None

    # If value looks like milliseconds, convert to seconds
    if exp > 10_000_000_000:
      exp = exp / 1000.0

    return int(exp)

  def _extract_username(self, filename: str) -> str | None:
    """
    Parse the username from a cookie filename.

    Expected format: ``@<username>-cookie.json``

    :param filename: The cookie file name.
    :type filename: str
    :return: Extracted username, or None if the filename doesn't match.
    :rtype: str | None
    """
    match = re.match(self.COOKIE_PATTERN, filename, re.IGNORECASE)
    if match:
      return match.group(1)
    return None

  def _build_cookie_path(self, username: str) -> Path:
    """
    Construct the full file path for a given username's cookie file.

    :param username: The account username (without '@' prefix).
    :type username: str
    :return: Full path to the cookie JSON file.
    :rtype: Path
    """
    filename = f"@{username}-cookie.json"
    return self._cookies_dir / filename
