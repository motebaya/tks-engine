from __future__ import annotations

import random
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta


class DateTimeUtils:
  """
  Utility class for all date/time manipulation, formatting, and
  TikTok-specific schedule time calculations.

  Uses **calendar month** offsets via ``python-dateutil`` for maximum
  date boundary computation (e.g. Feb 17 + 1 month = Mar 17).

  All methods are stateless and exposed as static methods.
  """

  MONTH_NAMES: dict[int, str] = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
  }

  @staticmethod
  def round_to_step(dt: datetime, step: int = 5) -> datetime:
    """
    Round a datetime's minute to the nearest multiple of *step*.

    :param dt: The datetime to round.
    :type dt: datetime
    :param step: Minute granularity (default 5).
    :type step: int
    :return: A new datetime with the minute rounded.
    :rtype: datetime
    """
    minute = dt.minute
    rounded = round(minute / step) * step
    if rounded >= 60:
      return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return dt.replace(minute=rounded, second=0, microsecond=0)

  # Keep the old name as a convenience alias
  round_to_5min = round_to_step

  @staticmethod
  def max_allowed_datetime(
    now: datetime | None = None,
    months: int = 1,
  ) -> datetime:
    """
    Compute the latest allowed schedule datetime using a **calendar
    month** offset (not a fixed day count).

    :param now: Reference time (defaults to ``datetime.now()``).
    :type now: datetime | None
    :param months: Number of calendar months to add.
    :type months: int
    :return: ``now + months`` (calendar).
    :rtype: datetime
    """
    if now is None:
      now = datetime.now()
    return now + relativedelta(months=months)

  @staticmethod
  def is_valid_schedule_time(
    dt: datetime,
    min_offset_minutes: int = 15,
    max_offset_months: int = 1,
  ) -> bool:
    """
    Check if a datetime falls within the valid scheduling window.

    Uses calendar-month arithmetic for the upper bound.

    :param dt: The datetime to validate.
    :type dt: datetime
    :param min_offset_minutes: Minimum future offset in minutes.
    :type min_offset_minutes: int
    :param max_offset_months: Maximum future offset in calendar months.
    :type max_offset_months: int
    :return: True if the time is within the valid scheduling window.
    :rtype: bool
    """
    now = datetime.now()
    min_time = now + timedelta(minutes=min_offset_minutes)
    max_time = now + relativedelta(months=max_offset_months)
    return min_time <= dt <= max_time

  @staticmethod
  def clamp_to_schedule_window(
    dt: datetime,
    min_offset_minutes: int = 15,
    max_offset_months: int = 1,
    step: int = 5,
  ) -> datetime:
    """
    Force a datetime into the valid scheduling range.

    Uses calendar-month arithmetic for the upper bound and rounds to
    the nearest minute step.

    :param dt: The datetime to clamp.
    :type dt: datetime
    :param min_offset_minutes: Minimum future offset in minutes.
    :type min_offset_minutes: int
    :param max_offset_months: Maximum future offset in calendar months.
    :type max_offset_months: int
    :param step: Minute granularity.
    :type step: int
    :return: A clamped and rounded datetime.
    :rtype: datetime
    """
    now = datetime.now()
    min_time = now + timedelta(minutes=min_offset_minutes)
    max_time = now + relativedelta(months=max_offset_months)

    if dt < min_time:
      dt = min_time
    elif dt > max_time:
      dt = max_time

    return DateTimeUtils.round_to_step(dt, step)

  @staticmethod
  def generate_schedule_time(
    base: datetime,
    offset_minutes: int,
    step: int = 5,
  ) -> datetime:
    """
    Create a schedule time by adding an offset to a base datetime.

    The result is rounded to the nearest minute step.

    :param base: The starting datetime.
    :type base: datetime
    :param offset_minutes: Minutes to add.
    :type offset_minutes: int
    :param step: Minute granularity.
    :type step: int
    :return: The computed schedule time, rounded.
    :rtype: datetime
    """
    result = base + timedelta(minutes=offset_minutes)
    return DateTimeUtils.round_to_step(result, step)

  @staticmethod
  def format_for_display(dt: datetime) -> str:
    """
    Format a datetime for human-readable display in GUI and logs.

    :param dt: The datetime to format.
    :type dt: datetime
    :return: Formatted string like ``'2026-02-17 15:30'``.
    :rtype: str
    """
    return dt.strftime("%Y-%m-%d %H:%M")

  @staticmethod
  def format_iso(dt: datetime) -> str:
    """
    Format a datetime as ISO 8601 string for storage.

    :param dt: The datetime to format.
    :type dt: datetime
    :return: ISO formatted string like ``'2026-02-17T15:30:00'``.
    :rtype: str
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S")

  @staticmethod
  def month_name(month: int) -> str:
    """
    Convert a month number (1-12) to its English name.

    Used for TikTok calendar month-title matching.

    :param month: Month number, 1-indexed.
    :type month: int
    :return: Full month name (e.g., ``'January'``).
    :rtype: str
    :raises ValueError: If month is not in range 1-12.
    """
    if month < 1 or month > 12:
      raise ValueError(f"Month must be 1-12, got {month}")
    return DateTimeUtils.MONTH_NAMES[month]

  @staticmethod
  def date_range(
    start: datetime,
    end: datetime,
    step_minutes: int,
  ) -> list[datetime]:
    """
    Generate a list of evenly spaced datetimes between start and end.

    :param start: Start of the range (inclusive).
    :type start: datetime
    :param end: End of the range (inclusive).
    :type end: datetime
    :param step_minutes: Interval between each datetime in minutes.
    :type step_minutes: int
    :return: Ordered list of datetimes.
    :rtype: list[datetime]
    """
    result: list[datetime] = []
    current = start
    step = timedelta(minutes=step_minutes)

    while current <= end:
      result.append(current)
      current += step

    return result

  @staticmethod
  def add_random_offset(
    dt: datetime,
    max_offset_minutes: int,
    step: int = 5,
  ) -> datetime:
    """
    Add a random offset (positive or negative) to a datetime.

    The result is rounded to the nearest minute step.

    :param dt: The base datetime.
    :type dt: datetime
    :param max_offset_minutes: Maximum offset magnitude in minutes.
    :type max_offset_minutes: int
    :param step: Minute granularity.
    :type step: int
    :return: The datetime with random offset applied, rounded.
    :rtype: datetime
    """
    offset = random.randint(-max_offset_minutes, max_offset_minutes)
    result = dt + timedelta(minutes=offset)
    return DateTimeUtils.round_to_step(result, step)

  @staticmethod
  def parse_hour_minute(dt: datetime, step: int = 5) -> tuple[str, str]:
    """
    Extract zero-padded hour and rounded minute strings for the time picker.

    :param dt: The datetime to extract from.
    :type dt: datetime
    :param step: Minute granularity.
    :type step: int
    :return: Tuple of ``(hour_str, minute_str)`` e.g. ``('03', '15')``.
    :rtype: tuple[str, str]
    """
    rounded = DateTimeUtils.round_to_step(dt, step)
    hour_str = str(rounded.hour).zfill(2)
    minute_str = str(rounded.minute).zfill(2)
    return (hour_str, minute_str)

  @staticmethod
  def parse_day_month_year(dt: datetime) -> tuple[int, int, int]:
    """
    Extract day, month, year integers from a datetime.

    :param dt: The datetime to extract from.
    :type dt: datetime
    :return: Tuple of ``(day, month, year)``.
    :rtype: tuple[int, int, int]
    """
    return (dt.day, dt.month, dt.year)
