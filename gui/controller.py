from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
  QFileDialog, QHBoxLayout, QLabel, QTableWidgetItem, QWidget,
)

from core.browser_manager import BrowserManager
from core.config_manager import ConfigManager
from core.cookie_manager import CookieManager
from core.dom_handler import DOMHandler, RateLimitError
from core.logger_manager import LoggerManager
from core.schedule_rule_engine import ScheduleRuleEngine
from core.scheduler import Scheduler, ScheduleConfig, UploadTask
from core.uploader import Uploader, UploadResult
from gui.components import AddAccountDialog
from gui.main_window import MainWindow
from utils.datetime_utils import DateTimeUtils
from utils.file_scanner import FileScanner, VideoFile
from utils.validators import Validators


class UploadWorker(QThread):
  """
  Background worker thread for running the async upload pipeline.

  Runs an asyncio event loop inside a QThread to keep the GUI responsive
  while Playwright operations execute sequentially.

  Signals:
      progress_update(int, int, int, int): current, total, success, failed
      log_message(str, int): message, level
      upload_complete(bool, str): success, filename
      finished_all(): all uploads done
      error_occurred(str): fatal error message
  """

  progress_update = pyqtSignal(int, int, int, int)
  log_message = pyqtSignal(str, int)
  upload_complete = pyqtSignal(bool, str)
  finished_all = pyqtSignal()
  error_occurred = pyqtSignal(str)
  rate_limited = pyqtSignal(str)

  def __init__(
    self,
    cookie_manager: CookieManager,
    username: str,
    tasks: list[UploadTask],
    headless: bool,
    retry_enabled: bool,
    logger: LoggerManager,
    rule_engine: ScheduleRuleEngine,
    storage_dir: Path | None = None,
    process_limit: int = 0,
  ) -> None:
    """
    Initialize UploadWorker.

    :param cookie_manager: CookieManager for loading cookies.
    :type cookie_manager: CookieManager
    :param username: Account username.
    :type username: str
    :param tasks: List of upload tasks to execute.
    :type tasks: list[UploadTask]
    :param headless: Whether to run browser headless.
    :type headless: bool
    :param retry_enabled: Whether to retry failed uploads.
    :type retry_enabled: bool
    :param logger: Logger instance.
    :type logger: LoggerManager
    :param rule_engine: Schedule rule engine for final validation.
    :type rule_engine: ScheduleRuleEngine
    :param storage_dir: Directory for copyright.json storage.
    :type storage_dir: Path | None
    :param process_limit: Max videos to process (0 = no limit).
    :type process_limit: int
    """
    super().__init__()
    self._cookie_manager = cookie_manager
    self._username = username
    self._tasks = tasks
    self._headless = headless
    self._retry_enabled = retry_enabled
    self._logger = logger
    self._rules = rule_engine
    self._storage_dir = storage_dir
    self._process_limit = process_limit
    self._stop_flag = False
    self._pause_flag = False
    self._results: list[UploadResult] = []

  def run(self) -> None:
    """
    Thread entry point.
    """
    try:
      asyncio.run(self._execute())
    except Exception as e:
      self.error_occurred.emit(str(e))

  async def _execute(self) -> None:
    """
    Async upload pipeline.

    Re-validates every schedule timestamp via the rule engine before
    sending it to Playwright (backend hard validation).
    """
    browser_manager = BrowserManager(
      cookie_manager=self._cookie_manager,
      logger=self._logger,
      headless=self._headless,
    )

    total = len(self._tasks)
    success_count = 0
    failed_count = 0

    try:
      await browser_manager.launch(self._username)

      for i, task in enumerate(self._tasks):
        self._logger.info(
          f"Processing: {i+1} of {len(self._tasks)}"
        )
        if self._stop_flag:
          self._logger.info("Upload stopped by user")
          break

        # Check process limit
        processed = success_count + failed_count
        if self._process_limit > 0 and processed >= self._process_limit:
          self._logger.info(
            f"Process limit reached ({self._process_limit}) — stopping"
          )
          break

        while self._pause_flag:
          await asyncio.sleep(0.5)
          if self._stop_flag:
            break
        if self._stop_flag:
          break

        # Hard-validate schedule time before uploading
        if task.schedule_time is not None:
          valid, reason = self._rules.validate(task.schedule_time)
          if not valid:
            self._logger.warning(
              f"Skipping {task.file_path.name}: {reason}"
            )
            result = UploadResult(
              success=False,
              file_path=task.file_path,
              message="Schedule validation failed",
              timestamp=datetime.now(),
              error=reason,
            )
            self._results.append(result)
            failed_count += 1
            self.progress_update.emit(i + 1, total, success_count, failed_count)
            self.upload_complete.emit(False, task.file_path.name)
            continue

        page = browser_manager.get_page()
        datetime_utils = DateTimeUtils()
        dom_handler = DOMHandler(page, self._logger, datetime_utils)
        uploader = Uploader(dom_handler, self._logger, self._storage_dir)

        if self._retry_enabled:
          result = await uploader.retry_upload(
            task=task,
            max_retries=3,
            navigate_callback=browser_manager.new_upload_page,
          )
        else:
          result = await uploader.upload_video(task)

        self._results.append(result)

        if result.success:
          success_count += 1
        else:
          failed_count += 1

        self.progress_update.emit(i + 1, total, success_count, failed_count)
        self.upload_complete.emit(result.success, task.file_path.name)

        if i < total - 1 and not self._stop_flag:
          await browser_manager.new_upload_page()
          await asyncio.sleep(3)
        
        print("-" * 20)

    except RateLimitError as e:
      self._stop_flag = True
      toast_msg = str(e)
      self._logger.error(
        f"Account rate limit reached: {toast_msg}"
      )
      self.rate_limited.emit(toast_msg)
    except Exception as e:
      self.error_occurred.emit(str(e))
    finally:
      await browser_manager.close()
      self.finished_all.emit()

  def request_stop(self) -> None:
    """Signal the worker to stop after the current upload."""
    self._stop_flag = True

  def toggle_pause(self) -> None:
    """Toggle the pause state."""
    self._pause_flag = not self._pause_flag

  @property
  def is_paused(self) -> bool:
    """Whether the worker is paused."""
    return self._pause_flag

  @property
  def results(self) -> list[UploadResult]:
    """Accumulated upload results."""
    return self._results


class GUIController:
  """
  Mediator between the MainWindow GUI and core application modules.

  Handles user interactions, live date/time validation, dynamic time-
  option filtering via :class:`ScheduleRuleEngine`, async task
  dispatching, and storage I/O.

  :param window: The main application window.
  :type window: MainWindow
  :param config: Application configuration.
  :type config: ConfigManager
  :param project_root: Root directory of the project.
  :type project_root: Path
  """

  SCHEDULES_DIR: str = "schedules"
  PUBLISHES_DIR: str = "publishes"
  TARGET_PATH_FILE: str = "target-path.json"

  # How often to re-validate (ms) for long-running sessions
  VALIDATION_TIMER_INTERVAL: int = 60_000  # 1 minute

  def __init__(
    self,
    window: MainWindow,
    config: ConfigManager,
    project_root: Path,
  ) -> None:
    """
    Initialize GUIController.

    :param window: The main application window.
    :type window: MainWindow
    :param config: Application configuration.
    :type config: ConfigManager
    :param project_root: Root directory of the project.
    :type project_root: Path
    """
    self._window = window
    self._config = config
    self._root = project_root
    self._storage_dir = self._root / config.storage_dir
    self._schedules_dir = self._storage_dir / self.SCHEDULES_DIR
    self._publishes_dir = self._storage_dir / self.PUBLISHES_DIR
    self._cookies_dir = self._root / config.cookies_dir

    self._logger = LoggerManager(
      name="TikTokGUI",
      level=config.effective_log_level,
    )
    self._cookie_manager = CookieManager(self._cookies_dir, self._logger)
    self._scanner = FileScanner(self._logger)
    self._rules = ScheduleRuleEngine(config)
    self._scheduler = Scheduler(self._rules, self._logger)

    self._videos: list[VideoFile] = []
    self._tasks: list[UploadTask] = []
    self._worker: UploadWorker | None = None

    # Cached data for filter/sort refresh
    self._cached_data_uploads: list[dict] = []
    self._cached_username: str = ""
    self._sort_column: int | None = None
    self._sort_ascending: bool = True
    # Row index → VideoFile mapping (accounts for sorting/filtering)
    self._row_video_map: dict[int, VideoFile] = {}

    # Apply headless default from config
    self._window.headless_check.setChecked(config.headless_default)

    # Register logger callback for GUI streaming
    self._logger.set_callback(self._on_log_message)

    # Surface config warnings in GUI
    for w in config.warnings:
      self._logger.warning(f"[config] {w}")

    # Connect signals
    self._connect_signals()

    # Migrate legacy scheduled.json to per-user files (one-time)
    self._migrate_legacy_scheduled()

    # Initial data load
    self._load_accounts()
    self._load_saved_folder()

    # Initialize time defaults (now + 15 min) and filter dropdowns
    self._initialize_time_defaults()

    # Run initial validation
    self._validate_date_range()
    self._validate_time_selection()

    # Periodic re-validation timer (handles long-running sessions)
    self._validation_timer = QTimer()
    self._validation_timer.timeout.connect(self._validate_date_range)
    self._validation_timer.timeout.connect(self._update_time_options)
    self._validation_timer.timeout.connect(self._validate_time_selection)
    self._validation_timer.start(self.VALIDATION_TIMER_INTERVAL)

  # ================================================================
  # SIGNAL CONNECTIONS
  # ================================================================

  def _connect_signals(self) -> None:
    """Connect all widget signals to handler methods."""
    w = self._window

    w.account_dropdown.currentTextChanged.connect(self._on_account_selected)
    w.add_account_btn.clicked.connect(self._on_add_account_clicked)
    w.browse_button.clicked.connect(self._on_browse_clicked)
    w.scan_button.clicked.connect(self._on_scan_clicked)
    w.generate_btn.clicked.connect(self._on_generate_schedule)
    w.start_btn.clicked.connect(self._on_start_upload)
    w.stop_btn.clicked.connect(self._on_stop_clicked)
    w.pause_btn.clicked.connect(self._on_pause_resume)
    w.export_btn.clicked.connect(self._on_export_report)

    # Live date range validation on change
    w.start_date.dateChanged.connect(lambda _: self._validate_date_range())
    w.end_date.dateChanged.connect(lambda _: self._validate_date_range())

    # Dynamic time option filtering on date change
    w.start_date.dateChanged.connect(lambda _: self._update_time_options())
    w.time_start_hour.currentTextChanged.connect(
      lambda _: self._update_start_minutes()
    )

    # Live time validation on any time selection change
    w.time_start_hour.currentTextChanged.connect(
      lambda _: self._validate_time_selection()
    )
    w.time_start_minute.currentTextChanged.connect(
      lambda _: self._validate_time_selection()
    )

    # Sync checkboxes when limit changes
    w.limit_spin.valueChanged.connect(self._on_limit_changed)

    # Live caption preview update
    w.caption_input.textChanged.connect(self._update_caption_preview)
    w.hashtags_input.textChanged.connect(self._update_caption_preview)

    # Table filter checkboxes
    w.filter_scheduled_check.stateChanged.connect(
      lambda _: self._on_filter_changed()
    )
    w.filter_published_check.stateChanged.connect(
      lambda _: self._on_filter_changed()
    )

    # Column header click for sorting
    w.video_table.horizontalHeader().sectionClicked.connect(
      self._on_header_clicked
    )

  # ================================================================
  # DATE RANGE VALIDATION (live, on-change)
  # ================================================================

  def _validate_date_range(self) -> None:
    """
    Validate the currently selected date range against the rule engine.

    If invalid, shows the inline warning and disables primary actions.
    """
    w = self._window
    start_qdate = w.start_date.date()
    end_qdate = w.end_date.date()

    start_dt = datetime(
      start_qdate.year(), start_qdate.month(), start_qdate.day(),
    )
    end_dt = datetime(
      end_qdate.year(), end_qdate.month(), end_qdate.day(),
      23, 59,
    )

    valid, reason = self._rules.validate_date_range(start_dt, end_dt)

    if valid:
      w.clear_schedule_warning()
      w.set_actions_enabled(True)
      # Also re-check time selection (may still be invalid for today)
      self._validate_time_selection()
    else:
      w.show_schedule_warning(reason)
      w.set_actions_enabled(False)

  # ================================================================
  # DYNAMIC TIME OPTION FILTERING
  # ================================================================

  def _update_time_options(self) -> None:
    """
    Regenerate hour options for the start-time dropdown based on the
    selected start date.

    If the date is today, only hours >= the current hour are shown.
    For future dates the full 00-23 range is available.
    """
    w = self._window
    qdate = w.start_date.date()
    now = datetime.now()

    # Save current selection
    current_hour = w.time_start_hour.currentText()

    if qdate.toPyDate() == now.date():
      hours = [f"{h:02d}" for h in range(now.hour, 24)]
    elif qdate.toPyDate() < now.date():
      hours = []
    else:
      hours = [f"{h:02d}" for h in range(24)]

    w.time_start_hour.blockSignals(True)
    w.time_start_hour.clear()
    w.time_start_hour.addItems(hours)
    w.time_start_hour.blockSignals(False)

    # Restore selection if still valid
    idx = w.time_start_hour.findText(current_hour)
    if idx >= 0:
      w.time_start_hour.setCurrentIndex(idx)
    elif w.time_start_hour.count() > 0:
      w.time_start_hour.setCurrentIndex(0)

    self._update_start_minutes()

  def _update_start_minutes(self) -> None:
    """
    Regenerate minute options for the start-time dropdown based on the
    selected date and hour.

    If the date is today AND the selected hour equals the current hour,
    only minutes >= the current minute (rounded up to the next 5-min
    step) are shown.  Otherwise the full 00-55 range is available.
    """
    w = self._window
    qdate = w.start_date.date()
    now = datetime.now()

    hour_text = w.time_start_hour.currentText()
    if not hour_text:
      return
    selected_hour = int(hour_text)

    current_minute = w.time_start_minute.currentText()

    step = 5
    all_minutes = [f"{m:02d}" for m in range(0, 60, step)]

    if qdate.toPyDate() == now.date() and selected_hour == now.hour:
      # Round current minute up to next 5-min step
      cur_m = now.minute
      remainder = cur_m % step
      if remainder != 0:
        cur_m += step - remainder
      if cur_m >= 60:
        # All minutes in this hour are past; list will be empty
        # (caller should bump to next hour via _update_time_options)
        minutes = []
      else:
        minutes = [f"{m:02d}" for m in range(cur_m, 60, step)]
    else:
      minutes = all_minutes

    w.time_start_minute.blockSignals(True)
    w.time_start_minute.clear()
    w.time_start_minute.addItems(minutes)
    w.time_start_minute.blockSignals(False)

    idx = w.time_start_minute.findText(current_minute)
    if idx >= 0:
      w.time_start_minute.setCurrentIndex(idx)
    elif w.time_start_minute.count() > 0:
      w.time_start_minute.setCurrentIndex(0)

    # Re-validate time after minute options change
    self._validate_time_selection()

  def _initialize_time_defaults(self) -> None:
    """
    Set start-time defaults to now + 15 minutes, rounded up to the
    next 5-minute increment, then filter the dropdowns.

    For example, if the current time is 12:35, the default becomes
    12:50 (35+15=50).  If it is 12:48, it becomes 13:05 (48+15=63,
    rounded up to next 5-min → 13:05).

    Called once during init to ensure the initial state reflects the
    current time rather than stale hardcoded values.
    """
    w = self._window
    now = datetime.now()

    # Add 15 minutes, then round UP to the next 5-minute step
    step = 5
    total_minutes = now.hour * 60 + now.minute + 15
    remainder = total_minutes % step
    if remainder != 0:
      total_minutes += step - remainder
    cur_h = (total_minutes // 60) % 24
    cur_m = total_minutes % 60

    # Filter hour dropdown (removes past hours for today)
    self._update_time_options()

    # Select the rounded hour
    w.time_start_hour.blockSignals(True)
    hour_str = f"{cur_h:02d}"
    idx = w.time_start_hour.findText(hour_str)
    if idx >= 0:
      w.time_start_hour.setCurrentIndex(idx)
    elif w.time_start_hour.count() > 0:
      w.time_start_hour.setCurrentIndex(0)
    w.time_start_hour.blockSignals(False)

    # Filter minute dropdown (removes past minutes for current hour)
    self._update_start_minutes()

    # Select the rounded minute
    w.time_start_minute.blockSignals(True)
    minute_str = f"{cur_m:02d}"
    idx = w.time_start_minute.findText(minute_str)
    if idx >= 0:
      w.time_start_minute.setCurrentIndex(idx)
    elif w.time_start_minute.count() > 0:
      w.time_start_minute.setCurrentIndex(0)
    w.time_start_minute.blockSignals(False)

  def _validate_time_selection(self) -> None:
    """
    Check whether the currently selected start time is at least 15
    minutes in the future.  If not, show a red warning below the
    time row and disable primary actions.

    Only applies when the start date is today; future dates are
    always valid at any hour/minute.
    """
    w = self._window
    qdate = w.start_date.date()
    now = datetime.now()

    # Only validate against current time when start date is today
    if qdate.toPyDate() != now.date():
      w.clear_time_warning()
      return

    hour_text = w.time_start_hour.currentText()
    minute_text = w.time_start_minute.currentText()
    if not hour_text or not minute_text:
      w.clear_time_warning()
      return

    selected_dt = datetime(
      qdate.year(), qdate.month(), qdate.day(),
      int(hour_text), int(minute_text),
    )

    valid, reason = self._rules.validate(selected_dt, now)
    if not valid:
      min_dt = self._rules.min_allowed_datetime(now)
      w.show_time_warning(
        f"Start time must be at least 15 min from now "
        f"(earliest: {min_dt.strftime('%H:%M')})"
      )
      w.set_actions_enabled(False)
    else:
      w.clear_time_warning()
      # Only re-enable if the date range is also valid
      start_dt = datetime(qdate.year(), qdate.month(), qdate.day())
      end_qdate = w.end_date.date()
      end_dt = datetime(
        end_qdate.year(), end_qdate.month(), end_qdate.day(), 23, 59,
      )
      date_valid, _ = self._rules.validate_date_range(start_dt, end_dt, now)
      if date_valid:
        w.set_actions_enabled(True)

  # ================================================================
  # ACCOUNT
  # ================================================================

  def _load_accounts(self) -> None:
    """Scan cookies directory and populate dropdown."""
    accounts = self._cookie_manager.list_accounts()
    self._window.account_dropdown.clear()
    if accounts:
      self._window.account_dropdown.addItems(accounts)
    else:
      self._logger.warning("No cookie files found in /cookies directory")

  def _on_account_selected(self, username: str) -> None:
    """Handle account dropdown change."""
    if username:
      self._logger.info(f"Selected account: @{username}")

  def _on_add_account_clicked(self) -> None:
    """Open the Add Account dialog and handle save."""
    dialog = AddAccountDialog(self._window)
    dialog.save_btn.clicked.connect(
      lambda: self._save_new_account(dialog)
    )
    dialog.exec()

  def _save_new_account(self, dialog: AddAccountDialog) -> None:
    """
    Validate and save a new account cookie from the dialog.

    Checks:
    1. Username is not empty and contains no invalid characters.
    2. Cookie text is valid JSON and is a non-empty list.
    3. Each cookie entry has the required fields (name, value, domain, path).
    4. File does not already exist (prevents accidental overwrite).

    On success, saves to ``cookies/@<username>-cookie.json``, refreshes
    the account dropdown, and closes the dialog.
    """
    dialog.clear_error()

    username = dialog.get_username()
    cookie_text = dialog.get_cookie_text()

    # ---- Validate username ----
    if not username:
      dialog.show_error("Username is required.")
      return

    # Strip leading @ if user typed it
    if username.startswith("@"):
      username = username[1:]

    if not username:
      dialog.show_error("Username is required.")
      return

    # Basic character validation (alphanumeric, dots, underscores)
    if not re.match(r'^[\w.]+$', username):
      dialog.show_error(
        "Username contains invalid characters. "
        "Only letters, numbers, dots, and underscores are allowed."
      )
      return

    # ---- Validate cookie JSON ----
    if not cookie_text:
      dialog.show_error("Cookie JSON is required.")
      return

    try:
      cookie_data = json.loads(cookie_text)
    except json.JSONDecodeError as e:
      dialog.show_error(f"Invalid JSON: {e}")
      return

    if not isinstance(cookie_data, list):
      dialog.show_error("Cookie JSON must be a JSON array [ ... ].")
      return

    if len(cookie_data) == 0:
      dialog.show_error("Cookie array is empty.")
      return

    # Validate each cookie entry has required fields
    required_fields = ["name", "value", "domain", "path"]
    for idx, entry in enumerate(cookie_data):
      if not isinstance(entry, dict):
        dialog.show_error(f"Cookie #{idx} is not a JSON object.")
        return
      for field in required_fields:
        val = entry.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
          dialog.show_error(
            f'Cookie #{idx} is missing required field "{field}".'
          )
          return

    # ---- Check file conflict ----
    cookie_path = self._cookies_dir / f"@{username}-cookie.json"
    if cookie_path.exists():
      dialog.show_error(
        f"Account @{username} already exists. "
        f"Delete the existing cookie file first to replace it."
      )
      return

    # ---- Save ----
    try:
      self._cookies_dir.mkdir(parents=True, exist_ok=True)
      with open(cookie_path, "w", encoding="utf-8") as f:
        json.dump(cookie_data, f, indent=2, ensure_ascii=False)
    except OSError as e:
      dialog.show_error(f"Failed to save file: {e}")
      return

    self._logger.success(f"Account @{username} added successfully")
    dialog.accept()

    # Refresh dropdown and select the new account
    self._load_accounts()
    idx = self._window.account_dropdown.findText(username)
    if idx >= 0:
      self._window.account_dropdown.setCurrentIndex(idx)

  # ================================================================
  # FOLDER
  # ================================================================

  def _load_saved_folder(self) -> None:
    """Load previously saved target folders from target-path.json into dropdown."""
    target_file = self._storage_dir / self.TARGET_PATH_FILE
    if target_file.exists():
      try:
        with open(target_file, "r", encoding="utf-8") as f:
          data = json.load(f)
        folders = data.get("video_folder", [])
        # Backward compat: old format was a single string
        if isinstance(folders, str):
          folders = [folders] if folders else []
        self._window.folder_dropdown.clear()
        if folders:
          self._window.folder_dropdown.addItems(folders)
      except (json.JSONDecodeError, OSError):
        pass

  def _save_folder_path(self, folder: str) -> None:
    """Append folder to the saved list in target-path.json (no duplicates)."""
    target_file = self._storage_dir / self.TARGET_PATH_FILE
    folders: list[str] = []
    if target_file.exists():
      try:
        with open(target_file, "r", encoding="utf-8") as f:
          data = json.load(f)
        folders = data.get("video_folder", [])
        if isinstance(folders, str):
          folders = [folders] if folders else []
      except (json.JSONDecodeError, OSError):
        pass
    if folder not in folders:
      folders.append(folder)
    try:
      self._storage_dir.mkdir(parents=True, exist_ok=True)
      with open(target_file, "w", encoding="utf-8") as f:
        json.dump({"video_folder": folders}, f, indent=2)
    except OSError as e:
      self._logger.error(f"Failed to save folder path: {e}")

  def _update_caption_preview(self) -> None:
    """Update the caption preview label to show what will be sent."""
    w = self._window
    if self._videos:
      video_id = self._normalize_video_id(self._videos[0].path)
    else:
      video_id = "<videoid>"

    user_caption = w.caption_input.toPlainText().strip()
    hashtags_raw = w.hashtags_input.toPlainText().strip()

    parts = [f"Cre: {video_id}"]
    if user_caption:
      parts.append(user_caption)
    if hashtags_raw:
      tags = []
      for token in hashtags_raw.split():
        tags.append(token if token.startswith("#") else f"#{token}")
      parts.append(" ".join(tags))

    preview = " | ".join(parts)
    w.caption_preview.setText(f"Preview: {preview}")

  def _on_limit_changed(self, value: int) -> None:
    """Sync table checkboxes, clear stale schedule times, and update label.

    Skips rows whose status is 'Scheduled', 'Published', or 'Failed'.
    """
    table = self._window.video_table
    checked = 0
    available_idx = 0
    for row in range(table.rowCount()):
      item = table.item(row, 0)
      if item is None:
        continue

      # Skip unavailable rows (col 4 hidden item stores status text)
      status_item = table.item(row, 4)
      if status_item and status_item.text() in (
        "Scheduled", "Published", "Failed",
      ):
        continue

      if available_idx < value:
        item.setCheckState(Qt.CheckState.Checked)
        checked += 1
      else:
        item.setCheckState(Qt.CheckState.Unchecked)
        # Clear schedule time for unchecked rows
        time_item = table.item(row, 3)
        if time_item and time_item.text():
          time_item.setText("")
      available_idx += 1
    self._window.video_selected_label.setText(f"Selected: {checked}")

  def _on_browse_clicked(self) -> None:
    """Open folder dialog, add to dropdown, and save."""
    folder = QFileDialog.getExistingDirectory(self._window, "Select Video Folder")
    if folder:
      dropdown = self._window.folder_dropdown
      idx = dropdown.findText(folder)
      if idx < 0:
        dropdown.addItem(folder)
        idx = dropdown.count() - 1
      dropdown.setCurrentIndex(idx)
      self._save_folder_path(folder)
      self._logger.info(f"Selected folder: {folder}")

  def _on_scan_clicked(self) -> None:
    """Scan target folder for .mp4 files."""
    folder = self._window.folder_dropdown.currentText()
    if not folder:
      self._logger.warning("No folder selected")
      return

    path = Validators.sanitize_path(folder)
    if not Validators.validate_directory(path):
      self._logger.error(f"Invalid directory: {path}")
      return

    self._videos = self._scanner.scan(path)

    # Build set of already-scheduled basenames
    self._scheduled_basenames: set[str] = set()
    self._published_video_ids: set[str] = set()
    self._published_entries: dict[str, str] = {}   # video_id -> iso_date
    username = self._window.account_dropdown.currentText()
    existing: list[dict] = []
    if username:
      scheduled_data = self._load_scheduled(username)
      existing = self._get_user_uploads(scheduled_data)
      from utils.file_scanner import FileScanner
      self._scheduled_basenames = FileScanner.get_scheduled_basenames(existing)

      # 3.1 FIX: migrate past-due entries BEFORE populating table
      to_publish: list[dict] = []
      for upload in existing:
        if upload.get("status") == "success":
          ts = upload.get("timestamp")
          if ts and datetime.fromtimestamp(ts) < datetime.now():
            to_publish.append(upload)
      if to_publish:
        self._migrate_to_published(username, to_publish)
        # Rebuild sets after migration
        scheduled_data = self._load_scheduled(username)
        existing = self._get_user_uploads(scheduled_data)
        self._scheduled_basenames = FileScanner.get_scheduled_basenames(
          existing
        )

      # Build published entries dict (video_id -> iso_date)
      pub_data = self._load_published(username)
      for entry in pub_data.get("published", []):
        if "|" in entry:
          video_id, date_str = entry.split("|", 1)
        else:
          video_id, date_str = entry, ""
        if video_id:
          self._published_video_ids.add(video_id)
          self._published_entries[video_id] = date_str

    def _is_unavailable(filename: str) -> bool:
      """Check if a file is scheduled or already published."""
      if filename in self._scheduled_basenames:
        return True
      stem = Path(filename).stem
      for vid in self._published_video_ids:
        if stem.startswith(vid):
          return True
      return False

    self._is_unavailable = _is_unavailable

    total_all = len(self._videos)
    total_available = sum(
      1 for v in self._videos
      if not self._is_unavailable(v.filename)
    )

    self._window.file_count_label.setText(f"Files found: {total_all}")
    self._window.video_total_label.setText(f"Total: {total_available}")

    # Update limit spin max to available (non-scheduled) videos
    limit_max = max(1, total_available)
    self._window.limit_spin.setMaximum(limit_max)
    self._window.limit_spin.setValue(limit_max)

    self._populate_video_table(existing, username)
    self._update_caption_preview()

  def lookup_scheduled(self, filename: str, uploads: list) -> dict | None:
    """Look up scheduled date based on basename file."""
    for upload in uploads:
      if upload.get("file") == filename and upload.get("status") == "success":
        ts = upload.get("timestamp")
        if ts:
          return {
            "date": datetime.fromtimestamp(ts).strftime("%d %B %Y %H:%M%p"),
            "passed": datetime.fromtimestamp(ts) < datetime.now(),
            "timestamp": ts,
          }
    return None

  def _populate_video_table(
    self, data_uploads: list[dict] | None = None, username: str = "",
  ) -> None:
    """Fill the video table with filtered, sorted data.

    Supports filter checkboxes for scheduled/published visibility,
    column sorting, centered content, and coloured status badges.
    """
    if data_uploads is None:
      data_uploads = []
    # Cache for filter/sort refresh
    self._cached_data_uploads = data_uploads
    self._cached_username = username
    self._refresh_video_table()

  # ----------------------------------------------------------------
  # TABLE FILTER / SORT / BADGE HELPERS
  # ----------------------------------------------------------------

  def _refresh_video_table(self) -> None:
    """Rebuild the table from cached data applying filters and sort."""
    data_uploads = self._cached_data_uploads
    table = self._window.video_table
    w = self._window
    limit = w.limit_spin.value()

    show_scheduled = w.filter_scheduled_check.isChecked()
    show_published = w.filter_published_check.isChecked()

    scheduled_names = getattr(self, "_scheduled_basenames", set())
    published_entries: dict[str, str] = getattr(
      self, "_published_entries", {}
    )

    # Build row data: (video, status, dt_display, sort_ts, size_bytes)
    rows: list[tuple] = []
    for video in self._videos:
      is_scheduled = video.filename in scheduled_names

      # Check published (only if not scheduled)
      is_published = False
      pub_date_iso = ""
      if not is_scheduled:
        stem = Path(video.filename).stem
        for vid, dstr in published_entries.items():
          if stem.startswith(vid):
            is_published = True
            pub_date_iso = dstr
            break

      # Determine status and display datetime
      if is_scheduled:
        sched = self.lookup_scheduled(video.filename, data_uploads)
        dt_str = sched["date"] if sched else ""
        sort_ts = sched.get("timestamp", 0) if sched else 0
        status = "Scheduled"
      elif is_published:
        status = "Published"
        sort_ts = 0.0
        if pub_date_iso:
          try:
            dt_obj = datetime.fromisoformat(pub_date_iso)
            dt_str = dt_obj.strftime("%d %B %Y %H:%M%p")
            sort_ts = dt_obj.timestamp()
          except (ValueError, OSError):
            dt_str = pub_date_iso
        else:
          dt_str = ""
      else:
        status = "Ready"
        dt_str = ""
        sort_ts = 0.0

      # Apply visibility filters
      if status == "Scheduled" and not show_scheduled:
        continue
      if status == "Published" and not show_published:
        continue

      rows.append((video, status, dt_str, sort_ts, video.size_bytes))

    # Apply column sorting
    if self._sort_column is not None:
      if self._sort_column == 1:        # Filename
        rows.sort(
          key=lambda r: r[0].filename.lower(),
          reverse=not self._sort_ascending,
        )
      elif self._sort_column == 2:      # Size
        rows.sort(key=lambda r: r[4], reverse=not self._sort_ascending)
      elif self._sort_column == 3:      # Date Time
        rows.sort(key=lambda r: r[3], reverse=not self._sort_ascending)

    # ---- populate table rows ----
    table.setRowCount(len(rows))
    self._row_video_map.clear()
    available_idx = 0

    for row_idx, (video, status, dt_str, _ts, _sz) in enumerate(rows):
      self._row_video_map[row_idx] = video
      is_unavailable = status in ("Scheduled", "Published")

      # Col 0: checkbox
      check_item = QTableWidgetItem()
      check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
      if is_unavailable:
        check_item.setCheckState(Qt.CheckState.Unchecked)
        check_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
      else:
        if available_idx < limit:
          check_item.setCheckState(Qt.CheckState.Checked)
        else:
          check_item.setCheckState(Qt.CheckState.Unchecked)
        check_item.setFlags(
          Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
        )
        available_idx += 1
      table.setItem(row_idx, 0, check_item)

      # Col 1: Filename
      fn_item = QTableWidgetItem(video.filename)
      fn_item.setFlags(fn_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
      fn_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
      table.setItem(row_idx, 1, fn_item)

      # Col 2: Size
      size_item = QTableWidgetItem(video.size_human)
      size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
      size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
      table.setItem(row_idx, 2, size_item)

      # Col 3: Date Time
      dt_item = QTableWidgetItem(dt_str)
      dt_item.setFlags(dt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
      dt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
      table.setItem(row_idx, 3, dt_item)

      # Col 4: Status (item for data access + cell widget for badge)
      status_item = QTableWidgetItem(status)
      status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
      status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
      table.setItem(row_idx, 4, status_item)
      table.setCellWidget(row_idx, 4, self._create_status_badge(status))

    selected_count = min(limit, available_idx)
    w.video_selected_label.setText(f"Selected: {selected_count}")

  @staticmethod
  def _create_status_badge(status: str) -> QWidget:
    """Return a centred, colour-coded badge widget for the status column."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(4, 2, 4, 2)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    label = QLabel(status)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    if status == "Scheduled":
      label.setStyleSheet(
        "background-color: #B8860B; color: #FFFFFF; "
        "border-radius: 6px; padding: 2px 10px; "
        "font-size: 11px; font-weight: 600;"
      )
    elif status == "Published":
      label.setStyleSheet(
        "background-color: #1B5E20; color: #FFFFFF; "
        "border-radius: 6px; padding: 2px 10px; "
        "font-size: 11px; font-weight: 600;"
      )
    elif status == "Failed":
      label.setStyleSheet(
        "background-color: #B71C1C; color: #FFFFFF; "
        "border-radius: 6px; padding: 2px 10px; "
        "font-size: 11px; font-weight: 600;"
      )
    else:  # Ready
      label.setStyleSheet(
        "background-color: #FFFFFF; color: #000000; "
        "border-radius: 6px; padding: 2px 10px; "
        "font-size: 11px; font-weight: 600;"
      )

    layout.addWidget(label)
    return container

  def _on_filter_changed(self) -> None:
    """Re-populate table when filter checkboxes change."""
    if self._videos:
      self._refresh_video_table()

  def _on_header_clicked(self, logical_index: int) -> None:
    """Handle column header click for sorting."""
    if logical_index not in (1, 2, 3):
      return  # Only sort Filename, Size, Date Time columns
    if self._sort_column == logical_index:
      self._sort_ascending = not self._sort_ascending
    else:
      self._sort_column = logical_index
      self._sort_ascending = True
    if self._videos:
      self._refresh_video_table()

  # ================================================================
  # LOG CALLBACK
  # ================================================================

  def _on_log_message(self, message: str, level: int) -> None:
    """Forward logger output to GUI log panel."""
    self._window.append_log(message, level)

  # ================================================================
  # SCHEDULE GENERATION
  # ================================================================

  def _on_generate_schedule(self) -> None:
    """Generate schedule slots and assign to selected videos."""
    # Re-validate before proceeding
    self._validate_date_range()
    self._validate_time_selection()
    w = self._window
    if w.schedule_warning.isVisible():
      self._logger.warning("Cannot generate schedule -- date range invalid")
      return
    if w.time_warning.isVisible():
      self._logger.warning("Cannot generate schedule -- start time invalid")
      return

    if not self._videos:
      self._logger.warning("No videos to schedule. Scan a folder first.")
      return

    start_qdate = w.start_date.date()
    end_qdate = w.end_date.date()

    ts_h = int(w.time_start_hour.currentText() or "9")
    ts_m = int(w.time_start_minute.currentText() or "0")
    te_h = int(w.time_end_hour.currentText() or "23")
    te_m = int(w.time_end_minute.currentText() or "55")

    start_dt = datetime(
      start_qdate.year(), start_qdate.month(), start_qdate.day(),
      ts_h, ts_m,
    )
    end_dt = datetime(
      end_qdate.year(), end_qdate.month(), end_qdate.day(),
      te_h, te_m,
    )

    config = ScheduleConfig(
      start_date=start_dt,
      end_date=end_dt,
      interval_minutes=w.interval_spin.value(),
      time_window_start=(ts_h, ts_m),
      time_window_end=(te_h, te_m),
    )

    try:
      slots = self._scheduler.generate_slots(config)
    except Exception as e:
      self._logger.error(f"Schedule generation failed: {e}")
      return

    selected_videos = self._get_selected_videos()
    if not selected_videos:
      self._logger.warning("No videos selected")
      return

    # Enforce count limit
    limit = w.limit_spin.value()
    selected_videos = selected_videos[:limit]
    slots = slots[:limit]

    video_paths = [v.path for v in selected_videos]

    # Build per-video captions:
    #   default = "Cre: <videoid>"  (filename without _X64 suffix etc.)
    #   + user custom caption on next line (if provided)
    #   + hashtags appended
    user_caption = w.caption_input.toPlainText().strip()
    hashtags_raw = w.hashtags_input.toPlainText().strip()
    captions = [
      self._build_caption(v.path, user_caption, hashtags_raw)
      for v in selected_videos
    ]

    self._tasks = self._scheduler.assign_videos(video_paths, slots, captions)
    self._update_table_schedule()
    w.start_btn.setEnabled(len(self._tasks) > 0)
    self._logger.info(f"Schedule generated: {len(self._tasks)} upload(s)")

  @staticmethod
  def _normalize_video_id(file_path: Path) -> str:
    """
    Extract a clean video ID from a filename.

    Splits the stem by ``_`` and takes the first segment only.

    Example: ``videoid_x264.mp4`` -> ``videoid``
    Example: ``abc_def_X64.mp4`` -> ``abc``

    :param file_path: Path to the video file.
    :type file_path: Path
    :return: Normalized video ID string.
    :rtype: str
    """
    stem = file_path.stem
    # Split by underscore and take only the first part as the video ID
    if "_" in stem:
      return stem.split("_")[0]
    return stem

  @staticmethod
  def _build_caption(
    file_path: Path,
    user_caption: str,
    hashtags_raw: str,
  ) -> str:
    """
    Build the final caption for a video.

    Format::

        Cre: <videoid>
        <user custom caption>     (if provided)
        #tag1 #tag2               (if provided)

    :param file_path: Path to the video file.
    :type file_path: Path
    :param user_caption: Custom caption from the UI field.
    :type user_caption: str
    :param hashtags_raw: Space-separated hashtags from the UI field.
    :type hashtags_raw: str
    :return: Assembled caption string.
    :rtype: str
    """
    video_id = GUIController._normalize_video_id(file_path)
    parts = [f"Cre: {video_id}"]

    if user_caption:
      parts.append(user_caption)

    if hashtags_raw:
      # Ensure each tag starts with #
      tags = []
      for token in hashtags_raw.split():
        tag = token if token.startswith("#") else f"#{token}"
        tags.append(tag)
      if tags:
        parts.append(" ".join(tags))

    return "\n".join(parts)

  def _get_selected_videos(self) -> list[VideoFile]:
    """Get videos checked in the table, excluding already-scheduled."""
    selected: list[VideoFile] = []
    table = self._window.video_table
    for row in range(table.rowCount()):
      # Skip already-scheduled or published rows
      status_item = table.item(row, 4)
      if status_item and status_item.text() in (
        "Scheduled", "Published", "Failed",
      ):
        continue

      item = table.item(row, 0)
      if item and item.checkState() == Qt.CheckState.Checked:
        video = self._row_video_map.get(row)
        if video:
          selected.append(video)
    return selected

  def _update_table_schedule(self) -> None:
    """Write schedule times into the table."""
    table = self._window.video_table
    for task in self._tasks:
      for row in range(table.rowCount()):
        fn_item = table.item(row, 1)
        if fn_item and fn_item.text() == task.file_path.name:
          time_str = ""
          if task.schedule_time:
            time_str = DateTimeUtils.format_for_display(task.schedule_time)
          time_item = QTableWidgetItem(time_str)
          time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
          time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
          table.setItem(row, 3, time_item)
          break

  # ================================================================
  # UPLOAD
  # ================================================================

  def _on_start_upload(self) -> None:
    """Launch upload worker thread."""
    if not self._tasks:
      self._logger.warning("No tasks to upload. Generate a schedule first.")
      return

    username = self._window.account_dropdown.currentText()
    if not username:
      self._logger.error("No account selected")
      return

    headless = self._window.headless_check.isChecked()
    retry = self._window.retry_check.isChecked()

    self._window.set_upload_running(True)
    self._window.update_progress(0, len(self._tasks), 0, 0)

    self._worker = UploadWorker(
      cookie_manager=self._cookie_manager,
      username=username,
      tasks=self._tasks,
      headless=headless,
      retry_enabled=retry,
      logger=self._logger,
      rule_engine=self._rules,
      storage_dir=self._storage_dir,
      process_limit=self._window.limit_spin.value(),
    )

    self._worker.progress_update.connect(self._on_progress_update)
    self._worker.upload_complete.connect(self._on_upload_complete)
    self._worker.finished_all.connect(self._on_finished)
    self._worker.error_occurred.connect(self._on_worker_error)
    self._worker.rate_limited.connect(self._on_rate_limited)

    self._worker.start()
    self._logger.info("Upload started")

  def _on_stop_clicked(self) -> None:
    """Signal worker to stop."""
    if self._worker:
      self._worker.request_stop()
      self._logger.warning("Stop requested -- finishing current upload")

  def _on_pause_resume(self) -> None:
    """Toggle pause/resume."""
    if self._worker:
      self._worker.toggle_pause()
      if self._worker.is_paused:
        self._window.pause_btn.setText(" Resume")
        self._logger.info("Upload paused")
      else:
        self._window.pause_btn.setText(" Pause")
        self._logger.info("Upload resumed")

  def _on_progress_update(
    self, current: int, total: int, success: int, failed: int,
  ) -> None:
    """Update progress bar and counters."""
    self._window.update_progress(current, total, success, failed)

  def _on_upload_complete(self, success: bool, filename: str) -> None:
    """Store result and flag table row on each upload completion."""
    if self._worker:
      username = self._window.account_dropdown.currentText()
      scheduled_data = self._load_scheduled(username)
      results = self._worker.results
      if results:
        last_result = results[-1]
        for task in self._tasks:
          if task.file_path.name == filename:
            self._append_upload_record(
              scheduled_data, task, last_result
            )
            self._save_scheduled(username, scheduled_data)
            break

    # Immediately flag the row status in the video table
    table = self._window.video_table
    for row in range(table.rowCount()):
      fn_item = table.item(row, 1)
      if fn_item and fn_item.text() == filename:
        status_text = "Scheduled" if success else "Failed"
        status_item = QTableWidgetItem(status_text)
        status_item.setFlags(
          status_item.flags() & ~Qt.ItemFlag.ItemIsEditable
        )
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, 4, status_item)
        table.setCellWidget(
          row, 4, self._create_status_badge(status_text)
        )

        if success:
          # Disable checkbox so it can't be re-selected
          check_item = table.item(row, 0)
          if check_item:
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
          # Track in scheduled basenames
          scheduled_names = getattr(self, "_scheduled_basenames", set())
          scheduled_names.add(filename)
          self._scheduled_basenames = scheduled_names
        break

  def _on_finished(self) -> None:
    """Handle worker completion."""
    self._window.set_upload_running(False)
    self._window.pause_btn.setText(" Pause")
    self._logger.success("All uploads finished")

  def _on_worker_error(self, error: str) -> None:
    """Handle fatal worker error."""
    self._window.set_upload_running(False)
    self._logger.error(f"Worker error: {error}")

  def _on_rate_limited(self, toast_message: str) -> None:
    """
    Handle account rate limit detection.

    Stops all uploads, resets the UI, and shows a prominent warning
    in the schedule warning label and log panel.

    :param toast_message: The Toast text from TikTok.
    :type toast_message: str
    """
    self._window.set_upload_running(False)
    self._window.show_schedule_warning(
      f"Account rate limited: {toast_message}"
    )
    self._window.set_actions_enabled(False)
    self._logger.error(
      f"RATE LIMIT — All uploads stopped. TikTok message: {toast_message}"
    )

  # ================================================================
  # EXPORT REPORT
  # ================================================================

  def _on_export_report(self) -> None:
    """Export upload results to a text file."""
    if not self._worker or not self._worker.results:
      self._logger.warning("No results to export")
      return

    file_path, _ = QFileDialog.getSaveFileName(
      self._window, "Export Report", "upload_report.txt",
      "Text Files (*.txt);;All Files (*)",
    )

    if file_path:
      try:
        with open(file_path, "w", encoding="utf-8") as f:
          f.write("TikTok Upload Report\n")
          f.write(f"Generated: {datetime.now().isoformat()}\n")
          f.write("=" * 50 + "\n\n")
          for r in self._worker.results:
            status = "SUCCESS" if r.success else "FAILED"
            f.write(f"[{status}] {r.file_path.name}\n")
            f.write(f"  Message: {r.message}\n")
            f.write(f"  Time: {DateTimeUtils.format_for_display(r.timestamp)}\n")
            if r.error:
              f.write(f"  Error: {r.error}\n")
            f.write("\n")
        self._logger.success(f"Report exported to {file_path}")
      except OSError as e:
        self._logger.error(f"Failed to export report: {e}")

  # ================================================================
  # LEGACY MIGRATION
  # ================================================================

  def _migrate_legacy_scheduled(self) -> None:
    """
    One-time migration from ``storage/scheduled.json`` to per-user
    files at ``storage/schedules/@<username>.json``.

    Reads the old file, splits by username key, writes each user's
    data into a separate file, then renames the old file to
    ``scheduled.json.migrated`` so it is not processed again.
    """
    legacy_path = self._storage_dir / "scheduled.json"
    if not legacy_path.exists():
      return

    try:
      with open(legacy_path, "r", encoding="utf-8") as f:
        legacy_data = json.load(f)
    except (json.JSONDecodeError, OSError):
      return

    if not isinstance(legacy_data, dict) or not legacy_data:
      return

    self._logger.info("Migrating scheduled.json to per-user files...")
    self._schedules_dir.mkdir(parents=True, exist_ok=True)

    for username, user_data in legacy_data.items():
      if not isinstance(user_data, dict):
        continue
      user_path = self._user_schedule_path(username)
      # Merge if per-user file already exists
      if user_path.exists():
        try:
          with open(user_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
          existing_uploads = existing.get("uploads", [])
          new_uploads = user_data.get("uploads", [])
          existing["uploads"] = existing_uploads + new_uploads
          user_data = existing
        except (json.JSONDecodeError, OSError):
          pass
      try:
        with open(user_path, "w", encoding="utf-8") as f:
          json.dump(user_data, f, indent=2, ensure_ascii=False)
        self._logger.info(f"  Migrated @{username}")
      except OSError as e:
        self._logger.error(f"  Failed to migrate @{username}: {e}")

    # Rename old file so migration doesn't run again
    try:
      legacy_path.rename(legacy_path.with_suffix(".json.migrated"))
      self._logger.success("Migration complete — old file renamed to scheduled.json.migrated")
    except OSError:
      pass

  # ================================================================
  # STORAGE I/O  (per-user schedule files)
  # ================================================================

  def _user_schedule_path(self, username: str) -> Path:
    """
    Build the path for a user's schedule file.

    :param username: Account username (without '@').
    :type username: str
    :return: ``storage/schedules/@<username>.json``
    :rtype: Path
    """
    return self._schedules_dir / f"@{username}.json"

  def _load_scheduled(self, username: str) -> dict:
    """
    Load the schedule data for a single user.

    :param username: Account username.
    :type username: str
    :return: Dict with ``{"uploads": [...]}`` or empty dict.
    :rtype: dict
    """
    path = self._user_schedule_path(username)
    if not path.exists():
      return {"uploads": []}
    try:
      with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
      if not isinstance(data, dict):
        return {"uploads": []}
      return data
    except (json.JSONDecodeError, OSError):
      return {"uploads": []}

  def _save_scheduled(self, username: str, data: dict) -> None:
    """
    Save the schedule data for a single user atomically.

    :param username: Account username.
    :type username: str
    :param data: Schedule data dict to persist.
    :type data: dict
    """
    path = self._user_schedule_path(username)
    temp = path.with_suffix(".tmp")
    try:
      self._schedules_dir.mkdir(parents=True, exist_ok=True)
      with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
      temp.replace(path)
    except OSError as e:
      self._logger.error(f"Failed to save schedule for @{username}: {e}")

  def _user_publish_path(self, username: str) -> Path:
    """Build the path for a user's publishes file.

    :param username: Account username (without '@').
    :type username: str
    :return: ``storage/publishes/@<username>.json``
    :rtype: Path
    """
    return self._publishes_dir / f"@{username}.json"

  def _load_published(self, username: str) -> dict:
    """Load the published data for a single user.

    :param username: Account username.
    :type username: str
    :return: Dict with ``{"published": [...]}`` or empty dict.
    :rtype: dict
    """
    path = self._user_publish_path(username)
    if not path.exists():
      return {"published": []}
    try:
      with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
      if not isinstance(data, dict):
        return {"published": []}
      return data
    except (json.JSONDecodeError, OSError):
      return {"published": []}

  def _save_published(self, username: str, data: dict) -> None:
    """Save the published data for a single user atomically.

    :param username: Account username.
    :type username: str
    :param data: Published data dict to persist.
    :type data: dict
    """
    path = self._user_publish_path(username)
    temp = path.with_suffix(".tmp")
    try:
      self._publishes_dir.mkdir(parents=True, exist_ok=True)
      with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
      temp.replace(path)
    except OSError as e:
      self._logger.error(f"Failed to save publishes for @{username}: {e}")

  def _migrate_to_published(
    self, username: str, entries: list[dict],
  ) -> None:
    """Move past-due scheduled entries to ``storage/publishes/``.

    Each entry is stored as ``<videoid>|<dateISO>`` and removed from
    the user's schedule file.

    :param username: Account username.
    :type username: str
    :param entries: Upload records to migrate.
    :type entries: list[dict]
    """
    # Build published entries
    pub_data = self._load_published(username)
    existing_set = set(pub_data.get("published", []))

    for entry in entries:
      filename = entry.get("file", "")
      schedule_time = entry.get("schedule_time", "")
      video_id = self._normalize_video_id(Path(filename))
      pub_entry = f"{video_id}|{schedule_time}"
      existing_set.add(pub_entry)

    pub_data["published"] = sorted(existing_set)
    self._save_published(username, pub_data)

    # Remove migrated entries from schedules
    sched_data = self._load_scheduled(username)
    migrated_files = {e.get("file") for e in entries}
    sched_data["uploads"] = [
      u for u in sched_data.get("uploads", [])
      if u.get("file") not in migrated_files
    ]
    self._save_scheduled(username, sched_data)

    self._logger.info(
      f"Migrated {len(entries)} published entry/entries for @{username}"
    )

  def _get_user_uploads(self, data: dict) -> list[dict]:
    """Extract uploads list from a user's schedule data."""
    return data.get("uploads", [])

  def _append_upload_record(
    self, data: dict,
    task: UploadTask, result: UploadResult,
  ) -> None:
    """Append an upload record to a user's schedule data."""
    if "uploads" not in data:
      data["uploads"] = []
    record = {
      "file": task.file_path.name,
      "caption": task.caption,
      "schedule_time": (
        DateTimeUtils.format_iso(task.schedule_time)
        if task.schedule_time else None
      ),
      "status": "success" if result.success else "failed",
      "timestamp": int(task.schedule_time.timestamp()),
      "video_id": None,
      "cm": result.cm,
      "qc": result.qc,
    }
    data["uploads"].append(record)
