from __future__ import annotations

import asyncio
import re
import random
from pathlib import Path

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeout

from core.logger_manager import LoggerManager
from utils.datetime_utils import DateTimeUtils


class SelectorError(Exception):
  """
  Raised when a required DOM element cannot be found or interacted with.
  """


class RateLimitError(Exception):
  """
  Raised when TikTok displays a Toast indicating the account has
  reached its upload/scheduling rate limit.

  The ``message`` attribute contains the Toast text content.
  """


class _Selectors:
  """
  Centralized DOM selectors for the TikTok Studio upload page.

  All values are derived from the DOM.js reference file.
  """

  FILE_INPUT = "input[type='file']"
  UPLOAD_STATUS = 'span[class*="TUXText"]'
  CAPTION_EDITOR = "div[contenteditable='true']"
  SCHEDULE_TOGGLE_TAG = "span"
  SCHEDULE_TOGGLE_TEXT = "Schedule"
  TIME_INPUT = "input[class='TUXTextInputCore-input']"
  TIMEPICKER_LIST = 'div[class="tiktok-timepicker-option-list"]'
  CALENDAR_WRAPPER = ".calendar-wrapper"
  MONTH_TITLE = ".month-title"
  CALENDAR_ARROW = ".arrow"
  DAY_SPAN = 'span[class*="day"]'
  VISIBILITY_CONTAINER = 'div[class*="view-auth-container"]'
  VISIBILITY_OPTION = 'div[class*="select-option"]'
  POST_BUTTON = 'button[data-e2e="post_video_button"]'
  POST_NOW_BUTTON = "//button[.//div[text()='Post now']]"
  POST_CONFIRMATION = (
    "//div[contains(text(), 'Your video has been uploaded') or "
    "contains(text(), 'Video published')]"
  )

  # Popup / overlay selectors (from old working code)
  COOKIE_BANNER = "#tiktok-cookie-banner"
  COOKIE_BANNER_BUTTON = "div.button-wrapper"
  SPLIT_WINDOW = "//button[./div[text()='Not now']]"
  CONTENT_CHECK_MODAL = ".TUXModal.common-modal"
  CONTENT_CHECK_CLOSE = ".common-modal-close, .common-modal-close-icon"
  CONTENT_CHECK_CANCEL = (
    "button.Button__root--type-neutral, button:has-text('Cancel')"
  )
  COPYRIGHT_MODAL = ".TUXModal.common-modal-confirm-modal"
  COPYRIGHT_POST_NOW = "button.TUXButton--primary"


class DOMHandler:
  """
  Translates all TikTok Studio DOM interactions into Playwright Python calls.

  Encapsulates every UI operation: file upload, caption entry, schedule
  configuration (time picker, calendar navigation), visibility selection,
  and post submission. All selectors and interaction sequences are derived
  from the DOM.js reference file.

  :param page: Active Playwright page for the TikTok Studio upload form.
  :type page: Page
  :param logger: Logger instance for status and debug messages.
  :type logger: LoggerManager
  :param datetime_utils: DateTimeUtils instance for time calculations.
  :type datetime_utils: DateTimeUtils
  """

  VISIBILITY_MAP: dict[str, str] = {
    "private": "Only you",
    "public": "Everyone",
    "friends": "Friends",
  }

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

  MAX_CALENDAR_NAVIGATION: int = 12
  DEFAULT_TYPING_DELAY: int = 50
  UPLOAD_POLL_INTERVAL: int = 2000
  CONTENT_CHECK_POLL_INTERVAL: int = 3  # seconds
  CONTENT_CHECK_TIMEOUT: int = 900      # 15 minutes max

  def __init__(
    self,
    page: Page,
    logger: LoggerManager,
    datetime_utils: DateTimeUtils,
  ) -> None:
    """
    Initialize DOMHandler.

    :param page: Active Playwright page.
    :type page: Page
    :param logger: Logger instance.
    :type logger: LoggerManager
    :param datetime_utils: DateTimeUtils instance for time calculations.
    :type datetime_utils: DateTimeUtils
    """
    self._page = page
    self._logger = logger
    self._datetime_utils = datetime_utils

  async def upload_file(self, file_path: Path) -> None:
    """
    Set a video file on the hidden file input element.

    Locates ``input[type='file']`` and uses Playwright's
    ``set_input_files`` to attach the file without clicking.

    :param file_path: Path to the video file to upload.
    :type file_path: Path
    :raises SelectorError: If the file input element is not found.
    """
    self._logger.info(f"Uploading file: {file_path.name}")

    file_input = await self._wait_for_selector(
      _Selectors.FILE_INPUT,
      timeout=15000,
      state="attached",
    )

    await file_input.set_input_files(str(file_path))

    # Wait for TikTok to start processing the file (matches old code)
    await asyncio.sleep(2)
    self._logger.debug("File attached to input element")

  async def wait_upload_complete(self, timeout: int = 120) -> bool:
    """
    Wait for the file upload to complete by polling for the "Uploaded" status.

    Polls ``span[class*="TUXText"]`` elements until one starts with
    "Uploaded", indicating the file has been processed by TikTok.

    :param timeout: Maximum wait time in seconds.
    :type timeout: int
    :return: True if upload completed, False if timed out.
    :rtype: bool
    """
    self._logger.info("Waiting for upload to complete...")
    elapsed = 0
    interval = self.UPLOAD_POLL_INTERVAL / 1000

    while elapsed < timeout:
      try:
        result = await self._page.evaluate("""
          () => {
            const spans = [...document.querySelectorAll('span[class*="TUXText"]')];
            const uploaded = spans.filter(s => s.textContent.startsWith("Uploaded"));
            return uploaded.length > 0;
          }
        """)

        if result:
          self._logger.success("File upload complete")
          return True

      except Exception as e:
        self._logger.debug(f"Upload status check error: {e}")

      await asyncio.sleep(interval)
      elapsed += interval

    self._logger.error(f"Upload timed out after {timeout}s")
    return False

  async def set_caption(self, text: str) -> None:
    """
    Set the video caption/description text.

    Locates the contenteditable div, clears any existing text by
    selecting all and deleting, then types each line separately with
    Shift+Enter between lines to create real line breaks in TikTok's
    rich-text editor.

    :param text: Caption text to enter (use ``\\n`` for line breaks).
    :type text: str
    :raises SelectorError: If the caption editor is not found.
    """
    self._logger.info("Setting caption")

    editor = self._page.locator(_Selectors.CAPTION_EDITOR).first
    await editor.wait_for(state="visible", timeout=10000)

    # Click to focus
    await editor.click()
    await asyncio.sleep(0.3)

    # Select all existing text and delete
    await self._page.keyboard.press("Control+A")
    await asyncio.sleep(0.1)
    await self._page.keyboard.press("Backspace")
    await asyncio.sleep(0.2)

    # Type line by line, pressing Shift+Enter between lines
    # to create real line breaks in the contenteditable div
    lines = text.split("\n")
    for i, line in enumerate(lines):
      if line:
        await self._page.keyboard.type(
          line,
          delay=self.DEFAULT_TYPING_DELAY,
        )
      # Insert line break between lines (not after the last one)
      if i < len(lines) - 1:
        await self._page.keyboard.press("Shift+Enter")
        await asyncio.sleep(0.1)

    self._logger.debug(f"Caption set: {text[:50]}...")

  async def enable_schedule(self) -> None:
    """
    Click the "Schedule" toggle to enable scheduling mode.

    Finds a ``<span>`` element with exact text content "Schedule"
    and clicks it.

    :raises SelectorError: If the Schedule toggle is not found.
    """
    self._logger.info("Enabling schedule mode")

    await self._click_by_text(
      _Selectors.SCHEDULE_TOGGLE_TAG,
      _Selectors.SCHEDULE_TOGGLE_TEXT,
    )

    await asyncio.sleep(0.5)
    self._logger.debug("Schedule mode enabled")

  async def set_time(self, hour: str, minute: str) -> None:
    """
    Set the schedule time using the TikTok time picker.

    Opens the time picker by clicking the time input field, waits
    for hour and minute option lists to appear, then clicks the
    matching hour and minute values.

    :param hour: Zero-padded hour string (e.g., '03', '15').
    :type hour: str
    :param minute: Zero-padded minute string, multiple of 5 (e.g., '00', '30').
    :type minute: str
    :raises SelectorError: If time picker elements are not found.
    """
    self._logger.info(f"Setting time to {hour}:{minute}")

    # Click time input (first TUXTextInputCore-input)
    time_input = self._page.locator(_Selectors.TIME_INPUT).nth(0)
    await time_input.wait_for(state="visible", timeout=10000)
    await time_input.click()
    await asyncio.sleep(0.5)

    # Wait for timepicker lists to appear
    timepicker_lists = self._page.locator(_Selectors.TIMEPICKER_LIST)
    await timepicker_lists.first.wait_for(state="visible", timeout=5000)

    # Select hour from first list
    hour_list = timepicker_lists.nth(0)
    await self._click_option_in_list(hour_list, hour)
    await asyncio.sleep(0.3)

    # Select minute from second list
    minute_list = timepicker_lists.nth(1)
    rounded_minute = self._round_minute(int(minute))
    await self._click_option_in_list(minute_list, rounded_minute)
    await asyncio.sleep(0.3)

    self._logger.debug(f"Time set to {hour}:{rounded_minute}")

  async def set_date(self, day: int, month: int, year: int) -> None:
    """
    Set the schedule date using the TikTok calendar picker.

    Opens the calendar by clicking the date input, navigates forward
    through months until the target month is visible, then clicks the
    target day.

    :param day: Day of the month (1-31).
    :type day: int
    :param month: Month number (1-12).
    :type month: int
    :param year: Year (e.g., 2026).
    :type year: int
    :raises SelectorError: If calendar elements are not found.
    :raises SelectorError: If month navigation exceeds maximum attempts.
    """
    target_month = self.MONTH_NAMES.get(month, "")
    self._logger.info(f"Setting date to {target_month} {day}, {year}")

    # Click date input (second TUXTextInputCore-input)
    date_input = self._page.locator(_Selectors.TIME_INPUT).nth(1)
    await date_input.wait_for(state="visible", timeout=10000)
    await date_input.click()
    await asyncio.sleep(0.5)

    # Wait for calendar to appear
    calendar = self._page.locator(_Selectors.CALENDAR_WRAPPER)
    await calendar.wait_for(state="visible", timeout=5000)

    # Navigate calendar to the target month
    await self._navigate_calendar_to_month(target_month)

    # Click target day
    await self._click_calendar_day(day)

    self._logger.debug(f"Date set to {target_month} {day}, {year}")

  async def set_visibility(self, mode: str) -> None:
    """
    Set the video visibility mode.

    Opens the visibility dropdown by clicking the button inside
    the view-auth-container, then selects the matching option.

    :param mode: Visibility mode - one of 'private', 'public', 'friends'.
    :type mode: str
    :raises ValueError: If mode is not a valid visibility option.
    :raises SelectorError: If visibility elements are not found.
    """
    if mode not in self.VISIBILITY_MAP:
      raise ValueError(
        f"Invalid visibility mode '{mode}'. "
        f"Must be one of: {list(self.VISIBILITY_MAP.keys())}"
      )

    target_text = self.VISIBILITY_MAP[mode]
    self._logger.info(f"Setting visibility to '{mode}' ({target_text})")

    # Click visibility dropdown button
    container = self._page.locator(_Selectors.VISIBILITY_CONTAINER)
    await container.wait_for(state="visible", timeout=10000)
    button = container.locator("button")
    await button.click()
    await asyncio.sleep(0.5)

    # Select the matching option
    options = self._page.locator(_Selectors.VISIBILITY_OPTION)
    count = await options.count()

    for i in range(count):
      option = options.nth(i)
      text = await option.text_content()
      if text and text.strip().startswith(target_text):
        await option.click()
        self._logger.debug(f"Visibility set to '{mode}'")
        return

    raise SelectorError(f"Visibility option '{target_text}' not found")

  # ----------------------------------------------------------------
  # Copyright & content quality checks
  # ----------------------------------------------------------------

  async def check_music_copyright(self) -> dict:
    """
    Read the music copyright status from the TikTok upload page.

    Looks for ``div[class*="status-success"]`` and reads the inner
    ``<span>`` text.  A value of ``"No issues found."`` means no
    copyright problem.

    :return: ``{"has_copyright": bool, "message": str}``
    :rtype: dict
    """
    self._logger.info("Checking music copyright...")

    try:
      result = await self._page.evaluate("""
        () => {
          const el = document.querySelector('div[class*="status-success"]');
          if (el) {
            const span = el.querySelector('span');
            return span ? span.textContent.trim() : null;
          }
          return null;
        }
      """)

      if result is None:
        self._logger.warning("Music copyright status element not found")
        return {"has_copyright": False, "message": "Status element not found"}

      no_issue = result.lower().startswith("no issues")
      if no_issue:
        self._logger.success(f"Music copyright: {result}")
      else:
        self._logger.warning(f"Music copyright issue: {result}")

      return {"has_copyright": not no_issue, "message": result}

    except Exception as e:
      self._logger.debug(f"Error checking music copyright: {e}")
      return {"has_copyright": False, "message": f"Check error: {e}"}

  async def check_content_quality(self) -> dict:
    """
    Poll the content quality check until it resolves.

    The TikTok upload page cycles through states:
    ``status-ready`` -> ``status-checking`` -> final state.

    Final states are: ``status-success``, ``status-warn``,
    ``status-error``, ``status-limit``, ``status-not-eligible``.

    Polls every :attr:`CONTENT_CHECK_POLL_INTERVAL` seconds until a
    final state is reached or :attr:`CONTENT_CHECK_TIMEOUT` expires.

    :return: ``{"state": str, "message": str}``
    :rtype: dict
    """
    self._logger.info("Waiting for content quality check to complete...")

    _JS_GET_STATUS = """
      () => {
        const el = document.querySelector(
          'div[class*="status-result"][data-show="true"]'
        );
        if (!el) return null;
        if (/try\s+again\s+tomorrow/si.test(el.textContent)) {
          return "status-limit"
        }
        const classes = Array.from(el.classList);
        const statusClass = classes.filter(
          c => c.startsWith('status') && !c.endsWith('result')
        )[0];
        return statusClass || null;
      }
    """

    _JS_GET_MODAL_WARNING = """
      () => {
        const modal_warning = document.querySelector('div[class*="common-modal-close-icon"]')
        if (modal_warning) {
          modal_warning.click()
          return true
        }
        return false
      }
    """

    status_map = {
      "status-ready": {
        "state": "ready",
        "message": "We'll check your content for For You Feed eligibility.",
      },
      "status-checking": {
        "state": "checking",
        "message": "Checking in progress.",
      },
      "status-success": {
        "state": "success",
        "message": (
          "No issues detected. However, your video may still be "
          "removed later if it violates Community Guidelines."
        ),
      },
      "status-warn": {
        "state": "warning",
        "message": (
          "Content may be restricted. You can still post, but "
          "modifying it to follow guidelines may improve visibility."
        ),
      },
      "status-error": {
        "state": "error",
        "message": "Something went wrong. Please try again later.",
      },
      "status-limit": {
        "state": "limitReached",
        "message": (
          "You've reached your check limit for today. "
          "Please try again tomorrow."
        ),
      },
      "status-not-eligible": {
        "state": "notEligible",
        "message": (
          "This feature isn't available for government, politician, "
          "or political party accounts."
        ),
      },
    }

    pending_states = {"status-ready", "status-checking"}
    elapsed = 0

    while elapsed < self.CONTENT_CHECK_TIMEOUT:
      try:
        status_key = await self._page.evaluate(_JS_GET_STATUS)
      except Exception as e:
        self._logger.debug(f"Content check poll error: {e}")
        await asyncio.sleep(self.CONTENT_CHECK_POLL_INTERVAL)
        elapsed += self.CONTENT_CHECK_POLL_INTERVAL
        continue

      if status_key is None:
        # Element not present yet — keep waiting
        await asyncio.sleep(self.CONTENT_CHECK_POLL_INTERVAL)
        elapsed += self.CONTENT_CHECK_POLL_INTERVAL
        continue

      if status_key not in pending_states:
        # Reached a final state
        info = status_map.get(status_key, {
          "state": status_key,
          "message": f"Unknown status: {status_key}",
        })
        self._logger.info(
          f"Content quality check: {info['state']} — {info['message']}"
        )

        # need wait few seconds to check modal warning appeared or nah
        if status_key == "status-warn": 
          self._logger.info("Waiting for modal warning appeared/not...")
          await asyncio.sleep(3)
          modal = await self._page.evaluate(_JS_GET_MODAL_WARNING)
          if modal:
            self._logger.info("Modal warning appeared, and success closed...")
          else:
            self._logger.warning("Modal warning not appeared, continue...")
        return info

      # Still checking — keep polling
      self._logger.debug(f"Content check state: {status_key}")
      await asyncio.sleep(self.CONTENT_CHECK_POLL_INTERVAL)
      elapsed += self.CONTENT_CHECK_POLL_INTERVAL

    self._logger.warning("Content quality check timed out")
    return {"state": "timeout", "message": "Content check timed out"}

  async def click_post(self) -> None:
    """
    Click the post/schedule submission button.

    Locates ``button[data-e2e="post_video_button"]`` and clicks it.

    :raises SelectorError: If the post button is not found.
    """
    self._logger.info("Clicking post button")

    post_button = await self._wait_for_selector(
      _Selectors.POST_BUTTON,
      timeout=10000,
    )

    await post_button.click()
    self._logger.debug("Post button clicked")


  # ----------------------------------------------------------------
  # Popup / overlay dismissal (ported from old working code)
  # ----------------------------------------------------------------

  async def dismiss_all_popups(self) -> None:
    """
    Dismiss all potential blocking popups and overlays.

    Called before file upload and after upload completes (before
    caption entry) to clear any modals that TikTok may have shown.
    """
    await self._dismiss_cookie_banner()
    await self._dismiss_content_check_modal()
    await self._dismiss_joyride_overlay()
    await self._dismiss_split_window()

  async def _dismiss_cookie_banner(self) -> None:
    """Dismiss the cookie consent banner if present."""
    try:
      banner = self._page.locator(_Selectors.COOKIE_BANNER)
      if await banner.count() > 0:
        button = banner.locator(_Selectors.COOKIE_BANNER_BUTTON)
        await button.click(timeout=5000)
        await asyncio.sleep(0.5)
        self._logger.debug("Cookie banner dismissed")
    except PlaywrightTimeout:
      pass

  async def _dismiss_joyride_overlay(self) -> None:
    """Dismiss the joyride tutorial overlay if present."""
    try:
      overlay = self._page.locator(".react-joyride__overlay")
      if await overlay.count() > 0:
        await overlay.click(timeout=3000)
        await asyncio.sleep(0.5)
        self._logger.debug("Joyride overlay dismissed")
    except PlaywrightTimeout:
      pass

    try:
      close_btn = self._page.locator("button[aria-label='Close']")
      if await close_btn.count() > 0:
        await close_btn.first.click(timeout=3000)
        await asyncio.sleep(0.5)
    except PlaywrightTimeout:
      pass

    try:
      skip_btn = self._page.locator("button:has-text('Skip')")
      if await skip_btn.count() > 0:
        await skip_btn.first.click(timeout=3000)
        await asyncio.sleep(0.5)
    except PlaywrightTimeout:
      pass

  async def _dismiss_split_window(self) -> None:
    """Dismiss the 'Not now' split window popup if present."""
    try:
      not_now = self._page.locator(_Selectors.SPLIT_WINDOW)
      if await not_now.count() > 0:
        await not_now.click(timeout=5000)
        await asyncio.sleep(0.5)
        self._logger.debug("Split window dismissed")
    except PlaywrightTimeout:
      pass

  async def _dismiss_content_check_modal(self) -> None:
    """Dismiss the 'Turn on automatic content checks?' modal if present."""
    try:
      modal = self._page.locator(_Selectors.CONTENT_CHECK_MODAL)
      if await modal.count() > 0:
        close_btn = modal.locator(_Selectors.CONTENT_CHECK_CLOSE).first
        if await close_btn.count() > 0:
          self._logger.debug("Dismissing content check modal (close)")
          await close_btn.click(timeout=3000)
          await asyncio.sleep(0.5)
          return

        cancel_btn = modal.locator(_Selectors.CONTENT_CHECK_CANCEL).first
        if await cancel_btn.count() > 0:
          self._logger.debug("Dismissing content check modal (cancel)")
          await cancel_btn.click(timeout=3000)
          await asyncio.sleep(0.5)
    except PlaywrightTimeout:
      pass
    except Exception as e:
      self._logger.debug(f"Error dismissing content check modal: {e}")

  async def handle_copyright_modal(self) -> None:
    """
    Handle the 'Continue to post?' copyright confirmation modal.

    After clicking post, TikTok may show a copyright check modal.
    If present, click the 'Post now' primary button to proceed.
    """
    try:
      modal = self._page.locator(_Selectors.COPYRIGHT_MODAL)
      if await modal.count() > 0:
        post_now_btn = modal.locator(_Selectors.COPYRIGHT_POST_NOW)
        if await post_now_btn.count() > 0:
          self._logger.info("Copyright modal detected — clicking 'Post now'")
          await post_now_btn.click()
          await asyncio.sleep(1)
    except PlaywrightTimeout:
      pass
    except Exception as e:
      self._logger.debug(f"Error handling copyright modal: {e}")

  async def wait_post_complete(self, timeout: int = 60) -> bool:
    """
    Wait for post submission confirmation.

    Polls for multiple success signals in a loop:
    1. Toast error detection (rate limit / account restriction).
    2. URL redirected to ``/content`` (most reliable after post).
    3. The upload confirmation text ("Your video has been uploaded").
    4. The post button disappearing from the page.

    :param timeout: Maximum wait time in seconds.
    :type timeout: int
    :return: True if post completed successfully, False on timeout.
    :rtype: bool
    :raises RateLimitError: If a Toast-content element is detected,
        indicating the account has reached its rate limit.
    """
    self._logger.info("Waiting for post confirmation...")
    poll_interval = 2
    elapsed = 0

    while elapsed < timeout:
      # Check 0: Toast error (rate limit / restriction)
      try:
        toast_text = await self._page.evaluate("""
          () => {
            const el = document.querySelector('div[class*="Toast-content"]');
            return el ? el.textContent.trim() : null;
          }
        """)
        if toast_text and not re.match('video\s+published',toast_text, re.IGNORECASE):
          self._logger.error(f"Rate limit Toast detected: {toast_text}")
          raise RateLimitError(toast_text)
      except RateLimitError:
        raise
      except Exception:
        pass

      # Check 1: URL redirected to /content (most reliable)
      current_url = self._page.url.rstrip("/")
      if current_url.endswith("/content"):
        self._logger.success("Post submitted successfully (redirected to /content)")
        return True

      # Check 2: confirmation text appeared
      try:
        confirm = self._page.locator(_Selectors.POST_CONFIRMATION)
        if await confirm.count() > 0:
          self._logger.success("Post submitted successfully")
          return True
      except Exception:
        pass

      # Check 3: post button disappeared
      try:
        post_btn = self._page.locator(_Selectors.POST_BUTTON)
        if await post_btn.count() == 0 or not await post_btn.is_visible():
          self._logger.success("Post submitted successfully (button hidden)")
          return True
      except Exception:
        pass

      await asyncio.sleep(poll_interval)
      elapsed += poll_interval

    self._logger.error(f"Post confirmation timed out after {timeout}s")
    return False

  async def _wait_for_selector(
    self,
    selector: str,
    timeout: int = 10000,
    state: str = "visible",
  ) -> Locator:
    """
    Wait for a DOM element to reach the specified state.

    :param selector: CSS selector string.
    :type selector: str
    :param timeout: Maximum wait time in milliseconds.
    :type timeout: int
    :param state: Expected state ('visible', 'attached', 'hidden').
    :type state: str
    :return: The located element.
    :rtype: Locator
    :raises SelectorError: If the element is not found within the timeout.
    """
    try:
      locator = self._page.locator(selector)
      await locator.first.wait_for(state=state, timeout=timeout)
      return locator.first
    except Exception as e:
      raise SelectorError(
        f"Element not found: '{selector}' (state={state}, "
        f"timeout={timeout}ms): {e}"
      )

  async def _click_by_text(self, tag: str, text: str) -> None:
    """
    Find an element by tag name and exact text content, then click it.

    Uses JavaScript evaluation to filter elements by textContent.

    :param tag: HTML tag name (e.g., 'span', 'div').
    :type tag: str
    :param text: Exact text content to match.
    :type text: str
    :raises SelectorError: If no matching element is found.
    """
    clicked = await self._page.evaluate(
      """
      ([tag, text]) => {
        const elements = [...document.querySelectorAll(tag)];
        const target = elements.filter(el => el.textContent.trim() === text)[0];
        if (target) {
          target.click();
          return true;
        }
        return false;
      }
      """,
      [tag, text],
    )

    if not clicked:
      raise SelectorError(
        f"Element <{tag}> with text '{text}' not found"
      )

  async def _navigate_calendar_to_month(self, target_month: str) -> None:
    """
    Click the right arrow in the calendar until the target month is displayed.

    Reads the ``.month-title`` text and compares to the target month name.
    Stops when matched or after MAX_CALENDAR_NAVIGATION iterations.

    :param target_month: Full month name (e.g., 'February').
    :type target_month: str
    :raises SelectorError: If navigation exceeds maximum iterations.
    """
    calendar = self._page.locator(_Selectors.CALENDAR_WRAPPER)

    for attempt in range(self.MAX_CALENDAR_NAVIGATION):
      month_title = calendar.locator(_Selectors.MONTH_TITLE)
      current_text = await month_title.text_content()

      if current_text and current_text.strip() == target_month:
        self._logger.debug(f"Calendar showing {target_month}")
        return

      # Click right arrow to go to next month
      arrows = calendar.locator(_Selectors.CALENDAR_ARROW)
      right_arrow = arrows.nth(1)
      await right_arrow.click()
      await asyncio.sleep(1)

    raise SelectorError(
      f"Could not navigate calendar to {target_month} "
      f"after {self.MAX_CALENDAR_NAVIGATION} attempts"
    )

  async def _click_calendar_day(self, day: int) -> None:
    """
    Click a specific day number in the visible calendar month.

    Filters ``span[class*="day"]`` elements by text content matching
    the target day number.

    :param day: Day of the month to click (1-31).
    :type day: int
    :raises SelectorError: If the target day is not found.
    """
    calendar = self._page.locator(_Selectors.CALENDAR_WRAPPER)

    clicked = await self._page.evaluate(
      """
      (day) => {
        const calendar = document.querySelector('.calendar-wrapper');
        if (!calendar) return false;
        const days = [...calendar.querySelectorAll('span[class*="day"]')];
        const target = days.filter(s => s.textContent.trim() === String(day))[0];
        if (target) {
          target.click();
          return true;
        }
        return false;
      }
      """,
      day,
    )

    if not clicked:
      raise SelectorError(f"Calendar day {day} not found")

  async def _click_option_in_list(
    self,
    list_locator: Locator,
    target_text: str,
  ) -> None:
    """
    Click an option within a timepicker list by matching text content.

    Iterates through div children of the list, finds the one whose
    text matches, and clicks its inner span.

    :param list_locator: Locator for the timepicker option list container.
    :type list_locator: Locator
    :param target_text: Text to match (e.g., '03', '30').
    :type target_text: str
    :raises SelectorError: If the target option is not found.
    """
    divs = list_locator.locator("div")
    count = await divs.count()

    for i in range(count):
      div = divs.nth(i)
      text = await div.text_content()
      if text and text.strip() == target_text:
        span = div.locator("span")
        if await span.count() > 0:
          await span.first.click()
        else:
          await div.click()
        return

    raise SelectorError(
      f"Option '{target_text}' not found in timepicker list"
    )

  def _round_minute(self, minute: int) -> str:
    """
    Round a minute value to the nearest multiple of 5 and zero-pad.

    TikTok's time picker only accepts multiples of 5 (00, 05, ..., 55).
    Mirrors the DOM.js logic: ``Math.round(parseInt(m) / 5) * 5``.

    :param minute: Minute value (0-59).
    :type minute: int
    :return: Zero-padded string of the rounded minute.
    :rtype: str
    """
    rounded = round(minute / 5) * 5
    rounded = max(0, min(55, rounded))
    return str(rounded).zfill(2)

  async def _humanized_delay(
    self,
    min_ms: int = 300,
    max_ms: int = 800,
  ) -> None:
    """
    Sleep for a random duration to simulate human interaction timing.

    :param min_ms: Minimum delay in milliseconds.
    :type min_ms: int
    :param max_ms: Maximum delay in milliseconds.
    :type max_ms: int
    """
    delay = random.randint(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)
