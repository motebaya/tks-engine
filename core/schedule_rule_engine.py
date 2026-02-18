from __future__ import annotations

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from core.config_manager import ConfigManager


class ScheduleRuleEngine:
  """
  Single authoritative source for all TikTok scheduling constraints.

  Referenced by both GUI (for dynamic option filtering) and CLI/backend
  (for hard validation before Playwright submission).  All time
  calculations use **calendar month** offsets (Feb 17 -> Mar 17),
  not fixed day counts.

  :param config: Application configuration manager.
  :type config: ConfigManager
  """

  def __init__(self, config: ConfigManager) -> None:
    """
    Initialize ScheduleRuleEngine from config.

    :param config: ConfigManager providing rule parameters.
    :type config: ConfigManager
    """
    self._min_offset_minutes: int = config.min_offset_minutes
    self._max_offset_months: int = config.max_offset_months
    self._minute_step: int = config.minute_step

  # ------------------------------------------------------------------
  # Properties
  # ------------------------------------------------------------------

  @property
  def min_offset_minutes(self) -> int:
    """
    Minimum future offset in minutes.

    :rtype: int
    """
    return self._min_offset_minutes

  @property
  def max_offset_months(self) -> int:
    """
    Maximum future offset in calendar months.

    :rtype: int
    """
    return self._max_offset_months

  @property
  def minute_step(self) -> int:
    """
    Allowed minute granularity (step size).

    :rtype: int
    """
    return self._minute_step

  # ------------------------------------------------------------------
  # Boundary calculations
  # ------------------------------------------------------------------

  def min_allowed_datetime(self, now: datetime | None = None) -> datetime:
    """
    Earliest allowed schedule timestamp.

    :param now: Reference time (defaults to ``datetime.now()``).
    :type now: datetime | None
    :return: ``now + min_offset_minutes``, rounded up to the next
             valid minute step.
    :rtype: datetime
    """
    if now is None:
      now = datetime.now()
    raw = now + timedelta(minutes=self._min_offset_minutes)
    return self.round_minute_up(raw)

  def max_allowed_datetime(self, now: datetime | None = None) -> datetime:
    """
    Latest allowed schedule timestamp.

    Uses a **calendar month** offset (``relativedelta``), not a fixed
    day count.  E.g. Feb 17 + 1 month = Mar 17.

    :param now: Reference time (defaults to ``datetime.now()``).
    :type now: datetime | None
    :return: ``now + max_offset_months`` (calendar months).
    :rtype: datetime
    """
    if now is None:
      now = datetime.now()
    return now + relativedelta(months=self._max_offset_months)

  # ------------------------------------------------------------------
  # Validation
  # ------------------------------------------------------------------

  def validate(
    self,
    dt: datetime,
    now: datetime | None = None,
  ) -> tuple[bool, str]:
    """
    Hard-validate a schedule timestamp against all rules.

    Checks:
    1. ``dt >= min_allowed_datetime``
    2. ``dt <= max_allowed_datetime``
    3. ``dt.minute`` is a multiple of ``minute_step``

    This method is the **single source of truth** for time validation.
    It is called:
    - In the GUI live validation (``GUIController._validate_time_selection``)
      whenever the user changes the start-time dropdowns.
    - Pre-generation (``GUIController._on_generate_schedule``) before
      building the schedule.
    - Pre-upload (``UploadWorker._execute``) immediately before each
      Playwright submission.

    :param dt: Candidate schedule timestamp.
    :type dt: datetime
    :param now: Reference time (defaults to ``datetime.now()``).
    :type now: datetime | None
    :return: ``(is_valid, reason)`` tuple.
    :rtype: tuple[bool, str]
    """
    if now is None:
      now = datetime.now()

    min_dt = self.min_allowed_datetime(now)
    max_dt = self.max_allowed_datetime(now)

    if dt < min_dt:
      return (
        False,
        f"Too early: must be at least {self._min_offset_minutes} min "
        f"in the future (earliest: {min_dt.strftime('%Y-%m-%d %H:%M')})",
      )

    if dt > max_dt:
      return (
        False,
        f"Too late: must be within {self._max_offset_months} month(s) "
        f"(latest: {max_dt.strftime('%Y-%m-%d %H:%M')})",
      )

    if dt.minute % self._minute_step != 0:
      return (
        False,
        f"Minute must be a multiple of {self._minute_step} "
        f"(got {dt.minute:02d})",
      )

    return (True, "Valid")

  def validate_date_range(
    self,
    start: datetime,
    end: datetime,
    now: datetime | None = None,
  ) -> tuple[bool, str]:
    """
    Validate that a full date range falls within the allowed window.

    Compares **calendar dates** (not exact timestamps) for the
    start/end boundaries, because the GUI date pickers select whole
    days.  Individual upload timestamps are still hard-validated via
    :meth:`validate` before submission.

    :param start: Range start.
    :type start: datetime
    :param end: Range end.
    :type end: datetime
    :param now: Reference time.
    :type now: datetime | None
    :return: ``(is_valid, reason)`` tuple.
    :rtype: tuple[bool, str]
    """
    if now is None:
      now = datetime.now()

    min_dt = self.min_allowed_datetime(now)
    max_dt = self.max_allowed_datetime(now)

    if start > end:
      return (False, "Start date must be before end date")

    if end.date() < min_dt.date():
      return (
        False,
        f"Entire range is in the past or too soon "
        f"(earliest allowed: {min_dt.strftime('%Y-%m-%d')})",
      )

    if start.date() > max_dt.date():
      return (
        False,
        f"Start date exceeds maximum allowed "
        f"({max_dt.strftime('%Y-%m-%d')}). "
        f"Scheduling is limited to {self._max_offset_months} month(s) from now.",
      )

    if end.date() > max_dt.date():
      return (
        False,
        f"End date {end.strftime('%Y-%m-%d')} exceeds the maximum "
        f"allowed date {max_dt.strftime('%Y-%m-%d')}. "
        f"Scheduling is limited to {self._max_offset_months} month(s) from now.",
      )

    return (True, "Valid")

  # ------------------------------------------------------------------
  # Minute step helpers
  # ------------------------------------------------------------------

  def round_minute_up(self, dt: datetime) -> datetime:
    """
    Round a datetime's minute **up** to the next valid step boundary.

    :param dt: Input datetime.
    :type dt: datetime
    :return: Rounded datetime (seconds/microseconds zeroed).
    :rtype: datetime
    """
    m = dt.minute
    remainder = m % self._minute_step
    if remainder == 0:
      return dt.replace(second=0, microsecond=0)
    rounded = m + (self._minute_step - remainder)
    if rounded >= 60:
      return (dt.replace(minute=0, second=0, microsecond=0)
              + timedelta(hours=1))
    return dt.replace(minute=rounded, second=0, microsecond=0)

  def round_minute_nearest(self, dt: datetime) -> datetime:
    """
    Round a datetime's minute to the **nearest** valid step boundary.

    :param dt: Input datetime.
    :type dt: datetime
    :return: Rounded datetime.
    :rtype: datetime
    """
    m = dt.minute
    rounded = round(m / self._minute_step) * self._minute_step
    if rounded >= 60:
      return (dt.replace(minute=0, second=0, microsecond=0)
              + timedelta(hours=1))
    return dt.replace(minute=rounded, second=0, microsecond=0)

  # ------------------------------------------------------------------
  # GUI option generation
  # ------------------------------------------------------------------

  def allowed_hours(self) -> list[str]:
    """
    Full list of zero-padded hour strings (``00`` .. ``23``).

    :return: 24-element list.
    :rtype: list[str]
    """
    return [f"{h:02d}" for h in range(24)]

  def allowed_minutes(self) -> list[str]:
    """
    Full list of zero-padded minute strings at the configured step.

    :return: List like ``['00','05','10', ... ,'55']``.
    :rtype: list[str]
    """
    return [f"{m:02d}" for m in range(0, 60, self._minute_step)]

  def filtered_hours_for_date(
    self,
    selected_date: datetime,
    now: datetime | None = None,
  ) -> list[str]:
    """
    Return hours valid for the given *selected_date*.

    If *selected_date* is today, hours earlier than the minimum
    allowed hour are excluded.  For future dates the full range is
    returned.

    :param selected_date: The date the user picked in the calendar.
    :type selected_date: datetime
    :param now: Reference time.
    :type now: datetime | None
    :return: Filtered list of zero-padded hour strings.
    :rtype: list[str]
    """
    if now is None:
      now = datetime.now()

    min_dt = self.min_allowed_datetime(now)

    if selected_date.date() == now.date():
      min_hour = min_dt.hour
      return [f"{h:02d}" for h in range(min_hour, 24)]

    if selected_date.date() < now.date():
      return []

    return self.allowed_hours()

  def filtered_minutes_for_hour(
    self,
    selected_date: datetime,
    selected_hour: int,
    now: datetime | None = None,
  ) -> list[str]:
    """
    Return minutes valid for the given *selected_date* and *selected_hour*.

    If the date+hour corresponds to the same hour as the minimum
    allowed time, earlier minutes are excluded.

    :param selected_date: The date the user picked.
    :type selected_date: datetime
    :param selected_hour: The hour the user picked (0-23).
    :type selected_hour: int
    :param now: Reference time.
    :type now: datetime | None
    :return: Filtered list of zero-padded minute strings.
    :rtype: list[str]
    """
    if now is None:
      now = datetime.now()

    min_dt = self.min_allowed_datetime(now)
    all_minutes = self.allowed_minutes()

    if selected_date.date() == now.date() and selected_hour == min_dt.hour:
      return [m for m in all_minutes if int(m) >= min_dt.minute]

    if selected_date.date() == now.date() and selected_hour < min_dt.hour:
      return []

    return all_minutes
