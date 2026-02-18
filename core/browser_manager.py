from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import (
  Browser,
  BrowserContext,
  Page,
  Playwright,
  async_playwright,
)

from core.cookie_manager import CookieManager
from core.logger_manager import LoggerManager


class AuthenticationError(Exception):
  """
  Raised when TikTok session authentication fails.
  """


class BrowserManager:
  """
  Manages the full Playwright browser lifecycle for TikTok Studio.

  Handles launching Chromium, creating browser contexts, injecting cookies,
  navigating to the upload page, verifying login status, and teardown.

  :param cookie_manager: CookieManager instance for loading cookies.
  :type cookie_manager: CookieManager
  :param logger: Logger instance for status messages.
  :type logger: LoggerManager
  :param headless: Whether to run the browser without a visible window.
  :type headless: bool
  """

  UPLOAD_URL: str = "https://www.tiktok.com/tiktokstudio/upload?from=webapp"
  LOGIN_URL_FRAGMENT: str = "login"
  FILE_INPUT_SELECTOR: str = "input[type='file']"

  DEFAULT_VIEWPORT: dict[str, int] = {"width": 1920, "height": 1080}
  DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
  )

  DEFAULT_TIMEOUT: int = 30000     # 30 seconds (locator actions)
  NAVIGATION_TIMEOUT: int = 60000  # 60 seconds
  LOGIN_CHECK_TIMEOUT: int = 10000  # 10 seconds

  def __init__(
    self,
    cookie_manager: CookieManager,
    logger: LoggerManager,
    headless: bool = True,
  ) -> None:
    """
    Initialize BrowserManager.

    :param cookie_manager: CookieManager instance for loading cookies.
    :type cookie_manager: CookieManager
    :param logger: Logger instance.
    :type logger: LoggerManager
    :param headless: Run browser without visible window.
    :type headless: bool
    """
    self._cookie_manager = cookie_manager
    self._logger = logger
    self._headless = headless

    self._playwright: Playwright | None = None
    self._browser: Browser | None = None
    self._context: BrowserContext | None = None
    self._page: Page | None = None
    self._current_username: str | None = None

  async def launch(self, username: str) -> None:
    """
    Launch browser, create context, inject cookies, and navigate to upload page.

    :param username: TikTok account username to load cookies for.
    :type username: str
    :raises AuthenticationError: If login verification fails after navigation.
    """
    self._logger.info(f"Launching browser for @{username}")
    self._current_username = username

    # Start Playwright
    self._playwright = await async_playwright().start()

    # Launch Chromium
    self._browser = await self._playwright.chromium.launch(
      headless=self._headless,
      args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
      ],
    )

    # Create context with realistic settings
    self._context = await self._configure_context()

    # Load and inject cookies
    cookies = self._cookie_manager.load_cookie(username)
    await self._inject_cookies(cookies)

    # Create page and navigate
    self._page = await self._context.new_page()
    await self.navigate_to_upload()

    # Verify login
    if not await self.is_logged_in():
      await self.close()
      raise AuthenticationError(
        f"Authentication failed for @{username}. "
        "Cookie may be expired or invalid."
      )

    self._logger.success(f"Browser ready for @{username}")

  def get_page(self) -> Page:
    """
    Return the current active Playwright Page.

    :return: The active page object.
    :rtype: Page
    :raises RuntimeError: If the browser has not been launched.
    """
    if self._page is None:
      raise RuntimeError("Browser not launched. Call launch() first.")
    return self._page

  async def is_logged_in(self) -> bool:
    """
    Check if the TikTok session is valid after navigation.

    Verifies that:
    1. The URL still contains 'tiktokstudio/upload' (no login redirect).
    2. The file input element is present on the page.

    :return: True if the session is authenticated.
    :rtype: bool
    """
    if self._page is None:
      return False

    return await self._verify_login()

  async def navigate_to_upload(self) -> None:
    """
    Navigate the active page to the TikTok Studio upload URL.

    :raises RuntimeError: If no page is available.
    """
    if self._page is None:
      raise RuntimeError("No active page. Call launch() first.")

    self._logger.info(f"Navigating to {self.UPLOAD_URL}")
    await self._page.goto(
      self.UPLOAD_URL,
      wait_until="domcontentloaded",
      timeout=self.NAVIGATION_TIMEOUT,
    )

    # Allow page JS to settle — do NOT use networkidle because TikTok
    # keeps persistent WebSocket connections open indefinitely, which
    # causes networkidle to hang until timeout.
    await asyncio.sleep(3)
    self._logger.debug("Page loaded successfully")

  async def close(self) -> None:
    """
    Close the browser, context, and Playwright instance gracefully.

    Safe to call multiple times.
    """
    self._logger.info("Closing browser")

    try:
      if self._page is not None:
        await self._page.close()
        self._page = None
    except Exception as e:
      self._logger.debug(f"Error closing page: {e}")

    try:
      if self._context is not None:
        await self._context.close()
        self._context = None
    except Exception as e:
      self._logger.debug(f"Error closing context: {e}")

    try:
      if self._browser is not None:
        await self._browser.close()
        self._browser = None
    except Exception as e:
      self._logger.debug(f"Error closing browser: {e}")

    try:
      if self._playwright is not None:
        await self._playwright.stop()
        self._playwright = None
    except Exception as e:
      self._logger.debug(f"Error stopping playwright: {e}")

    self._current_username = None
    self._logger.debug("Browser closed")

  async def restart(self, username: str) -> None:
    """
    Close the current browser session and re-launch with a fresh context.

    :param username: TikTok account username to use for the new session.
    :type username: str
    """
    self._logger.info(f"Restarting browser for @{username}")
    await self.close()
    await self.launch(username)

  async def new_upload_page(self) -> None:
    """
    Navigate to a fresh upload page for the next video.

    Closes the current page and creates a new one, then navigates
    to the upload URL. Used between consecutive uploads.
    """
    if self._context is None:
      raise RuntimeError("No active context. Call launch() first.")

    if self._page is not None:
      try:
        await self._page.close()
      except Exception:
        pass

    self._page = await self._context.new_page()
    await self.navigate_to_upload()

  async def _inject_cookies(self, cookies: list[dict[str, Any]]) -> None:
    """
    Add cookies to the browser context.

    :param cookies: List of Playwright-compatible cookie dictionaries.
    :type cookies: list[dict[str, Any]]
    """
    if self._context is None:
      raise RuntimeError("No active context")

    await self._context.add_cookies(cookies)
    self._logger.debug(f"Injected {len(cookies)} cookie(s)")

  async def _verify_login(self) -> bool:
    """
    Verify that the current page state indicates a valid login session.

    Checks URL for login redirects and probes for the file upload input.

    :return: True if login is verified.
    :rtype: bool
    """
    if self._page is None:
      return False

    current_url = self._page.url.lower()

    # Check for login redirect
    if self.LOGIN_URL_FRAGMENT in current_url and "upload" not in current_url:
      self._logger.error("Redirected to login page -- session invalid")
      return False

    # Check for file input element
    try:
      file_input = self._page.locator(self.FILE_INPUT_SELECTOR)
      await file_input.wait_for(
        state="attached",
        timeout=self.LOGIN_CHECK_TIMEOUT,
      )
      self._logger.debug("Login verified -- file input found")
      return True
    except Exception:
      self._logger.error("File input not found -- login may have failed")
      return False

  async def _configure_context(self) -> BrowserContext:
    """
    Create a browser context with realistic viewport, user-agent, and locale.

    :return: Configured BrowserContext.
    :rtype: BrowserContext
    """
    if self._browser is None:
      raise RuntimeError("Browser not launched")

    context = await self._browser.new_context(
      viewport=self.DEFAULT_VIEWPORT,
      user_agent=self.DEFAULT_USER_AGENT,
      locale="en-US",
    )

    # Set default timeouts on the context so every locator and
    # navigation call inherits them (matches old working code).
    context.set_default_timeout(self.DEFAULT_TIMEOUT)
    context.set_default_navigation_timeout(self.NAVIGATION_TIMEOUT)

    return context
