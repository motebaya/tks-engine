from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from core.logger_manager import LoggerManager
from core.schedule_rule_engine import ScheduleRuleEngine
from utils.datetime_utils import DateTimeUtils


class ScheduleError(Exception):
  """
  Raised when schedule generation or validation fails.
  """


@dataclass
class ScheduleConfig:
  """
  Configuration for schedule slot generation.

  :param start_date: First available date for scheduling.
  :type start_date: datetime
  :param end_date: Last available date for scheduling.
  :type end_date: datetime
  :param interval_minutes: Minutes between consecutive uploads.
  :type interval_minutes: int
  :param daily_limit: Maximum uploads per day.
  :type daily_limit: int
  :param time_window_start: Earliest time of day as (hour, minute).
  :type time_window_start: tuple[int, int]
  :param time_window_end: Latest time of day as (hour, minute).
  :type time_window_end: tuple[int, int]
  :param randomize: Whether to add random offset to each slot.
  :type randomize: bool
  :param randomize_range_minutes: Maximum random offset magnitude in minutes.
  :type randomize_range_minutes: int
  """

  start_date: datetime
  end_date: datetime
  interval_minutes: int = 60
  daily_limit: int = 5
  time_window_start: tuple[int, int] = (9, 0)
  time_window_end: tuple[int, int] = (21, 0)
  randomize: bool = False
  randomize_range_minutes: int = 10


@dataclass
class UploadTask:
  """
  Represents a single upload job with all required parameters.

  :param file_path: Path to the video file.
  :type file_path: Path
  :param caption: Video caption/description text.
  :type caption: str
  :param schedule_time: When to schedule the post (None = post immediately).
  :type schedule_time: datetime | None
  :param visibility: Video visibility mode ('private', 'public', 'friends').
  :type visibility: str
  """

  file_path: Path
  caption: str
  schedule_time: datetime | None = None
  visibility: str = "public"


class Scheduler:
  """
  Generates scheduling time slots for video uploads, enforces TikTok
  scheduling rules via :class:`ScheduleRuleEngine`, detects conflicts,
  and assigns videos to time slots.

  All boundary calculations (minimum offset, maximum calendar-month
  offset, minute step) are delegated to the rule engine so that GUI
  and backend share a single source of truth.

  :param rule_engine: Centralized schedule rule engine.
  :type rule_engine: ScheduleRuleEngine
  :param logger: Logger instance for status messages.
  :type logger: LoggerManager
  """

  def __init__(
    self,
    rule_engine: ScheduleRuleEngine,
    logger: LoggerManager,
  ) -> None:
    """
    Initialize Scheduler.

    :param rule_engine: Centralized schedule rule engine.
    :type rule_engine: ScheduleRuleEngine
    :param logger: Logger instance.
    :type logger: LoggerManager
    """
    self._rules = rule_engine
    self._logger = logger

  def generate_slots(self, config: ScheduleConfig) -> list[datetime]:
    """
    Generate time slots based on the provided configuration.

    Clamps the date range to the rule engine's valid scheduling window,
    respects time windows, rounds minutes to the configured step, and
    optionally applies random offsets.  All valid slots within the
    time window are returned; the caller is responsible for slicing
    down to the desired count (e.g. ``slots[:limit]``).

    :param config: Schedule generation configuration.
    :type config: ScheduleConfig
    :return: Ordered list of valid schedule datetimes.
    :rtype: list[datetime]
    :raises ScheduleError: If no valid slots can be generated.
    """
    now = datetime.now()
    min_time = self._rules.min_allowed_datetime(now)
    max_time = self._rules.max_allowed_datetime(now)
    step = self._rules.minute_step

    # Clamp start/end to valid window
    start = max(config.start_date, min_time)
    end = min(config.end_date, max_time)

    if start >= end:
      raise ScheduleError(
        "No valid scheduling window: start >= end after clamping"
      )

    self._logger.info(
      f"Generating slots from {DateTimeUtils.format_for_display(start)} "
      f"to {DateTimeUtils.format_for_display(end)}"
    )

    slots: list[datetime] = []
    current = start
    start_date = start.date()

    # Config window applies only to the first day (today)
    cfg_start_h, cfg_start_m = config.time_window_start
    cfg_end_h, cfg_end_m = config.time_window_end

    while current <= end:
      # Determine effective window for the current day:
      #   - First day (today): use config time window
      #   - Future days: full day 00:00 – 23:55
      if current.date() == start_date:
        eff_start_h, eff_start_m = cfg_start_h, cfg_start_m
        eff_end_h, eff_end_m = cfg_end_h, cfg_end_m
      else:
        eff_start_h, eff_start_m = 0, 0
        eff_end_h, eff_end_m = 23, 55

      eff_start_total = eff_start_h * 60 + eff_start_m
      eff_end_total = eff_end_h * 60 + eff_end_m

      # Enforce time window
      current_time = current.hour * 60 + current.minute

      if current_time < eff_start_total:
        current = current.replace(
          hour=eff_start_h,
          minute=eff_start_m,
          second=0,
          microsecond=0,
        )
        continue

      if current_time > eff_end_total:
        # Roll to next day at midnight; the loop will compute
        # the effective window for that day on the next iteration
        next_day = current.replace(
          hour=0, minute=0, second=0, microsecond=0,
        ) + timedelta(days=1)
        current = next_day
        continue

      # Round to configured minute step
      slot = DateTimeUtils.round_to_step(current, step)

      # Apply randomization
      if config.randomize:
        slot = DateTimeUtils.add_random_offset(
          slot,
          config.randomize_range_minutes,
          step,
        )

      # Hard-validate via rule engine after rounding/randomization
      valid, _ = self._rules.validate(slot, now)
      if valid:
        slot_time = slot.hour * 60 + slot.minute
        if eff_start_total <= slot_time <= eff_end_total:
          slots.append(slot)

      current += timedelta(minutes=config.interval_minutes)

    self._logger.info(f"Generated {len(slots)} schedule slot(s)")
    return slots

  def assign_videos(
    self,
    videos: list[Path],
    slots: list[datetime],
    captions: list[str] | None = None,
  ) -> list[UploadTask]:
    """
    Pair video files with time slots to create upload tasks.

    If captions are not provided, the video filename (without extension)
    is used as the caption.

    :param videos: List of video file paths.
    :type videos: list[Path]
    :param slots: List of schedule datetimes.
    :type slots: list[datetime]
    :param captions: Optional list of captions (one per video).
    :type captions: list[str] | None
    :return: List of UploadTask objects.
    :rtype: list[UploadTask]
    """
    tasks: list[UploadTask] = []
    pair_count = min(len(videos), len(slots))

    for i in range(pair_count):
      caption = ""
      if captions and i < len(captions):
        caption = captions[i]
      else:
        caption = videos[i].stem

      task = UploadTask(
        file_path=videos[i],
        caption=caption,
        schedule_time=slots[i],
      )
      tasks.append(task)

    self._logger.info(
      f"Assigned {len(tasks)} video(s) to schedule slots "
      f"({len(videos)} videos, {len(slots)} slots available)"
    )

    if len(videos) > len(slots):
      skipped = len(videos) - len(slots)
      self._logger.warning(f"{skipped} video(s) skipped -- not enough slots")

    return tasks

  def detect_conflicts(
    self,
    slots: list[datetime],
    existing: list[dict],
  ) -> list[datetime]:
    """
    Check new slots against already-scheduled uploads for time conflicts.

    A conflict is detected when a new slot is within *minute_step*
    minutes of an existing scheduled upload time.

    :param slots: New schedule slots to check.
    :type slots: list[datetime]
    :param existing: List of existing upload records with ``'schedule_time'`` keys.
    :type existing: list[dict]
    :return: List of conflicting slot datetimes.
    :rtype: list[datetime]
    """
    conflicts: list[datetime] = []
    existing_times: list[datetime] = []

    for record in existing:
      time_str = record.get("schedule_time", "")
      if time_str:
        try:
          existing_times.append(datetime.fromisoformat(time_str))
        except ValueError:
          continue

    for slot in slots:
      for existing_time in existing_times:
        diff = abs((slot - existing_time).total_seconds())
        if diff < self._rules.minute_step * 60:
          conflicts.append(slot)
          break

    if conflicts:
      self._logger.warning(
        f"Detected {len(conflicts)} scheduling conflict(s)"
      )

    return conflicts

  def validate_slot(self, slot: datetime) -> bool:
    """
    Validate a single time slot against the rule engine.

    :param slot: The datetime to validate.
    :type slot: datetime
    :return: True if the slot is within the valid scheduling window.
    :rtype: bool
    """
    valid, _ = self._rules.validate(slot)
    return valid
