from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.dom_handler import DOMHandler, RateLimitError
from core.logger_manager import LoggerManager
from core.scheduler import UploadTask
from utils.datetime_utils import DateTimeUtils


class UploadError(Exception):
  """
  Raised when a video upload operation fails.
  """


@dataclass
class UploadResult:
  """
  Result of a single upload attempt.

  :param success: Whether the upload succeeded.
  :type success: bool
  :param file_path: Path of the uploaded file.
  :type file_path: Path
  :param message: Human-readable status message.
  :type message: str
  :param timestamp: When the upload completed.
  :type timestamp: datetime
  :param error: Error details if the upload failed.
  :type error: str | None
  """

  success: bool
  file_path: Path
  message: str
  timestamp: datetime
  error: str | None = None
  copyright_music: bool = False
  quality_content: str = ""

  def to_dict(self) -> dict:
    """
    Serialize this result to a dictionary for JSON storage.

    :return: Dictionary representation.
    :rtype: dict
    """
    return {
      "file": str(self.file_path),
      "message": self.message,
      "status": "success" if self.success else "failed",
      "timestamp": DateTimeUtils.format_iso(self.timestamp),
      "error": self.error,
      "copyright_music": self.copyright_music,
      "quality_content": self.quality_content,
    }


class Uploader:
  """
  Orchestrates the full upload pipeline for a single video.

  Manages the sequence: file upload -> caption entry -> schedule
  configuration -> visibility selection -> post submission. Includes
  retry logic with exponential backoff.

  :param dom_handler: DOMHandler instance for page interactions.
  :type dom_handler: DOMHandler
  :param logger: Logger instance for status messages.
  :type logger: LoggerManager
  """

  def __init__(
    self,
    dom_handler: DOMHandler,
    logger: LoggerManager,
    storage_dir: Path | None = None,
  ) -> None:
    """
    Initialize Uploader.

    :param dom_handler: DOMHandler instance for page interactions.
    :type dom_handler: DOMHandler
    :param logger: Logger instance.
    :type logger: LoggerManager
    :param storage_dir: Directory for copyright.json and schedule files.
    :type storage_dir: Path | None
    """
    self._dom_handler = dom_handler
    self._logger = logger
    self._storage_dir = storage_dir

  async def upload_video(self, task: UploadTask) -> UploadResult:
    """
    Execute the full upload pipeline for a single video.

    Pipeline steps:
    1. Upload file via hidden input
    2. Wait for upload completion
    3. Set caption text
    4. Enable scheduling and set time/date (if scheduled)
    5. Set visibility mode
    6. Click post button
    7. Wait for submission confirmation

    :param task: Upload task with file, caption, schedule, and visibility.
    :type task: UploadTask
    :return: Structured result of the upload attempt.
    :rtype: UploadResult
    """
    filename = task.file_path.name
    self._logger.info(f"Starting upload for {filename}")

    try:
      # Dismiss any blocking popups before starting
      await self._dom_handler.dismiss_all_popups()

      # Step 1: Upload file
      await self._dom_handler.upload_file(task.file_path)

      # Step 2: Wait for upload to complete
      upload_ok = await self._dom_handler.wait_upload_complete(timeout=120)
      if not upload_ok:
        return UploadResult(
          success=False,
          file_path=task.file_path,
          message="Upload timed out",
          timestamp=datetime.now(),
          error="File upload did not complete within 120 seconds",
        )

      # Dismiss popups that may have appeared during upload
      await self._dom_handler.dismiss_all_popups()

      # Step 3: Set caption
      if task.caption:
        await self._dom_handler.set_caption(task.caption)

      # Step 4: Schedule (if specified)
      if task.schedule_time is not None:
        await self._dom_handler.enable_schedule()

        hour, minute = DateTimeUtils.parse_hour_minute(task.schedule_time)
        await self._dom_handler.set_time(hour, minute)

        day, month, year = DateTimeUtils.parse_day_month_year(task.schedule_time)
        await self._dom_handler.set_date(day, month, year)

      # Step 5: Set visibility
      await self._dom_handler.set_visibility(task.visibility)

      # Step 5b: Check music copyright
      copyright_result = await self._dom_handler.check_music_copyright()
      has_copyright = copyright_result.get("has_copyright", False)
      copyright_msg = copyright_result.get("message", "")

      # Step 5c: Wait for content quality check to finish
      quality_result = await self._dom_handler.check_content_quality()
      quality_state = quality_result.get("state", "")
      quality_msg = quality_result.get("message", "")

      # If music has copyright, save to copyright.json and abort
      if has_copyright:
        self._logger.error(
          f"Music copyright detected for {filename}: {copyright_msg}"
        )
        self._save_copyright_record(
          filename=filename,
          music_message=copyright_msg,
          quality_message=quality_msg,
        )
        return UploadResult(
          success=False,
          file_path=task.file_path,
          message="Music copyright detected — upload aborted",
          timestamp=datetime.now(),
          error=copyright_msg,
          copyright_music=True,
          quality_content=quality_msg,
        )

      # Step 6: Click post
      await self._dom_handler.click_post()

      # Handle copyright check confirmation modal (if it appears)
      await asyncio.sleep(1)
      await self._dom_handler.handle_copyright_modal()

      # Step 7: Wait for confirmation
      post_ok = await self._dom_handler.wait_post_complete(timeout=60)
      if not post_ok:
        return UploadResult(
          success=False,
          file_path=task.file_path,
          message="Post confirmation timed out",
          timestamp=datetime.now(),
          error="Post button clicked but confirmation not received",
        )

      # Success
      schedule_info = ""
      if task.schedule_time:
        schedule_info = f" (scheduled: {DateTimeUtils.format_for_display(task.schedule_time)})"

      self._logger.success(f"Upload complete: {filename}{schedule_info}")

      return UploadResult(
        success=True,
        file_path=task.file_path,
        message=f"Upload successful{schedule_info}",
        timestamp=datetime.now(),
        copyright_music=False,
        quality_content=quality_msg,
      )

    except RateLimitError:
      # Let rate limit propagate — the worker must stop all uploads
      raise

    except Exception as e:
      error_msg = str(e)
      self._logger.error(f"Upload failed for {filename}: {error_msg}")

      return UploadResult(
        success=False,
        file_path=task.file_path,
        message="Upload failed",
        timestamp=datetime.now(),
        error=error_msg,
      )

  def _save_copyright_record(
    self,
    filename: str,
    music_message: str,
    quality_message: str,
  ) -> None:
    """
    Append a copyright failure record to ``storage/copyright.json``.

    :param filename: Name of the video file (e.g. ``sample.mp4``).
    :type filename: str
    :param music_message: Copyright check message from TikTok.
    :type music_message: str
    :param quality_message: Content quality check message.
    :type quality_message: str
    """
    if self._storage_dir is None:
      self._logger.warning(
        "No storage_dir configured — skipping copyright.json write"
      )
      return

    copyright_path = self._storage_dir / "copyright.json"

    # Load existing data
    data: dict = {}
    if copyright_path.exists():
      try:
        with open(copyright_path, "r", encoding="utf-8") as f:
          data = json.load(f)
      except (json.JSONDecodeError, OSError):
        data = {}

    # Add / overwrite entry for this file
    data[filename] = {
      "date_failed": DateTimeUtils.format_iso(datetime.now()),
      "music_message": music_message,
      "quality_message": quality_message,
    }

    # Write back
    try:
      self._storage_dir.mkdir(parents=True, exist_ok=True)
      temp = copyright_path.with_suffix(".tmp")
      with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
      temp.replace(copyright_path)
      self._logger.info(f"Copyright record saved for {filename}")
    except OSError as e:
      self._logger.error(f"Failed to save copyright.json: {e}")

  async def retry_upload(
    self,
    task: UploadTask,
    max_retries: int = 3,
    navigate_callback=None,
  ) -> UploadResult:
    """
    Wrap upload_video with retry logic and exponential backoff.

    On failure, waits progressively longer between attempts and
    optionally calls a navigation callback to refresh the upload page
    before retrying.

    :param task: Upload task to retry.
    :type task: UploadTask
    :param max_retries: Maximum number of attempts.
    :type max_retries: int
    :param navigate_callback: Async callable to navigate to a fresh upload
        page between retries (e.g., ``browser_manager.new_upload_page``).
    :type navigate_callback: Callable[[], Awaitable[None]] | None
    :return: Result from the last attempt.
    :rtype: UploadResult
    """
    result: UploadResult | None = None

    for attempt in range(1, max_retries + 1):
      self._logger.info(
        f"Upload attempt {attempt}/{max_retries} for {task.file_path.name}"
      )

      result = await self.upload_video(task)

      if result.success:
        return result

      self._logger.warning(
        f"Attempt {attempt} failed: {result.error}"
      )

      if attempt < max_retries:
        backoff = 5 * attempt
        self._logger.info(f"Retrying in {backoff}s...")
        await asyncio.sleep(backoff)

        # Refresh the page for a clean upload form
        if navigate_callback is not None:
          try:
            await navigate_callback()
          except Exception as e:
            self._logger.error(f"Navigation callback failed: {e}")

    # Return last failed result
    return result  # type: ignore[return-value]
