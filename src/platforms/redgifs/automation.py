"""Core Selenium helpers for interacting with RedGifs.com.

RedGifs is an upload-only platform for video/image content. Sessions are
pre-authenticated via the anti-detect browser profile — this module does
NOT handle login.

Selector strategy (in priority order):
  1. id attributes (stable)
  2. data-testid / aria-label attributes
  3. CSS class-based structural selectors
  4. XPath text content
  5. Structural selectors (last resort — documented when used)

IMPORTANT: All selectors below are PLACEHOLDERS that must be verified
by inspecting the actual RedGifs upload page (https://www.redgifs.com/upload)
in a browser DevTools session. The fallback chain pattern provides resilience
but actual selector values need manual discovery before first use.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)
from loguru import logger

from src.platforms.base import PlatformAutomation

REDGIFS_BASE = "https://www.redgifs.com"
REDGIFS_UPLOAD_URL = f"{REDGIFS_BASE}/upload"

# Upload processing timeouts (seconds)
_UPLOAD_TIMEOUT_VIDEO = 300  # videos may take 3-5 minutes to process on RedGifs
_UPLOAD_TIMEOUT_IMAGE = 60
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}

# ---------------------------------------------------------------------------
# Selector fallback chains — PLACEHOLDERS.  Must be verified against the
# real RedGifs UI by inspecting https://www.redgifs.com/upload in DevTools.
# Each entry is (By strategy, selector value).
# ---------------------------------------------------------------------------
SELECTORS = {
    # File input on the upload page
    "upload_file_input": [
        (By.CSS_SELECTOR, 'input[type="file"]'),
        (By.CSS_SELECTOR, 'input[accept*="video"]'),
        (By.CSS_SELECTOR, 'input[accept*="image"]'),
        (By.XPATH, '//input[@type="file"]'),
    ],
    # Tag / keyword input field
    "tags_input": [
        (By.CSS_SELECTOR, 'input[placeholder*="tag"]'),
        (By.CSS_SELECTOR, 'input[placeholder*="Tag"]'),
        (By.CSS_SELECTOR, 'input[name="tags"]'),
        (By.CSS_SELECTOR, 'input[aria-label*="tag"]'),
        (By.XPATH, '//input[contains(@placeholder, "tag")]'),
    ],
    # Title / description input (optional on RedGifs)
    "title_input": [
        (By.CSS_SELECTOR, 'input[placeholder*="title"]'),
        (By.CSS_SELECTOR, 'input[placeholder*="Title"]'),
        (By.CSS_SELECTOR, 'input[name="title"]'),
        (By.XPATH, '//input[contains(@placeholder, "itle")]'),
    ],
    # Sound toggle checkbox / button
    "sound_toggle": [
        (By.CSS_SELECTOR, 'input[type="checkbox"][name*="sound"]'),
        (By.XPATH, '//label[contains(text(), "Sound")]'),
        (By.XPATH, '//*[contains(text(), "sound")]//input'),
    ],
    # Submit / publish button
    "submit_button": [
        (By.CSS_SELECTOR, 'button[type="submit"]'),
        (By.XPATH, '//button[contains(text(), "Upload")]'),
        (By.XPATH, '//button[contains(text(), "Publish")]'),
        (By.XPATH, '//button[contains(text(), "Submit")]'),
    ],
    # Upload progress / processing indicator (wait for it to disappear)
    "upload_progress": [
        (By.CSS_SELECTOR, '.upload-progress'),
        (By.CSS_SELECTOR, '[class*="progress"]'),
        (By.CSS_SELECTOR, '[class*="processing"]'),
    ],
    # Indicators that the user is logged in
    "login_indicator": [
        (By.CSS_SELECTOR, 'a[href="/upload"]'),
        (By.CSS_SELECTOR, '[aria-label="Upload"]'),
        (By.CSS_SELECTOR, 'a[href*="/users/"]'),
        (By.XPATH, '//a[contains(text(), "Upload")]'),
    ],
    # Indicators that the user is NOT logged in
    "not_logged_in_indicator": [
        (By.XPATH, '//a[contains(text(), "Log In")]'),
        (By.XPATH, '//a[contains(text(), "Sign Up")]'),
        (By.XPATH, '//button[contains(text(), "Log In")]'),
    ],
    # Cookie / popup dismiss
    "cookie_dismiss": [
        (By.XPATH, '//button[contains(text(), "Accept")]'),
        (By.XPATH, '//button[contains(text(), "I agree")]'),
        (By.XPATH, '//button[contains(text(), "OK")]'),
    ],
    "popup_dismiss": [
        (By.XPATH, '//button[contains(text(), "Close")]'),
        (By.CSS_SELECTOR, '[aria-label="Close"]'),
        (By.XPATH, '//button[contains(text(), "Not now")]'),
    ],
    # Like button on content pages (for human simulation)
    "like_button": [
        (By.CSS_SELECTOR, '[aria-label="Like"]'),
        (By.CSS_SELECTOR, 'button[class*="like"]'),
        (By.XPATH, '//button[contains(@class, "like")]'),
    ],
}


def _find_with_fallback(
    driver, selector_key: str, timeout: float = 10, clickable: bool = False,
):
    """Try each selector in the fallback chain until one succeeds.

    Returns the first matching element.
    Raises NoSuchElementException if none match.
    """
    selectors = SELECTORS.get(selector_key, [])
    condition = (
        EC.element_to_be_clickable if clickable else EC.presence_of_element_located
    )

    for by, value in selectors:
        try:
            el = WebDriverWait(driver, timeout).until(condition((by, value)))
            return el
        except TimeoutException:
            continue

    raise NoSuchElementException(
        f"None of the selectors for '{selector_key}' matched within {timeout}s"
    )


class RedGifsAutomation(PlatformAutomation):
    """Low-level Selenium operations for RedGifs.com."""

    def __init__(self, driver: webdriver.Chrome, delays: dict | None = None):
        self.driver = driver
        self.delays = delays or {}

    # ------------------------------------------------------------------
    # Delay helpers (mirrors ThreadsAutomation API)
    # ------------------------------------------------------------------
    def _action_delay(self) -> None:
        lo = self.delays.get("action_min", 2.0)
        hi = self.delays.get("action_max", 5.0)
        time.sleep(random.uniform(lo, hi))

    def _typing_delay(self) -> None:
        lo = self.delays.get("typing_min", 0.05)
        hi = self.delays.get("typing_max", 0.15)
        time.sleep(random.uniform(lo, hi))

    def _page_delay(self) -> None:
        lo = self.delays.get("page_load_min", 3.0)
        hi = self.delays.get("page_load_max", 7.0)
        time.sleep(random.uniform(lo, hi))

    def _human_type(self, element, text: str) -> None:
        """Type text character-by-character with random delays."""
        for ch in text:
            element.send_keys(ch)
            self._typing_delay()
            # Occasional longer pause to mimic thinking
            if random.random() < 0.05:
                time.sleep(random.uniform(0.3, 0.8))

    def _move_and_click(self, element) -> None:
        """Move mouse to element then click — more human-like than .click()."""
        try:
            ActionChains(self.driver).move_to_element(element).pause(
                random.uniform(0.1, 0.4)
            ).click().perform()
        except Exception:
            element.click()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def navigate_to(self, url: str) -> None:
        logger.debug(f"Navigating to {url}")
        self.driver.get(url)
        self._page_delay()

    def navigate_to_home(self) -> None:
        self.navigate_to(REDGIFS_BASE)

    def navigate_to_profile(self, username: str) -> None:
        clean = username.lstrip("@")
        self.navigate_to(f"{REDGIFS_BASE}/users/{clean}")

    def get_current_url(self) -> str:
        return self.driver.current_url

    # ------------------------------------------------------------------
    # Popup / cookie dismissal
    # ------------------------------------------------------------------
    def dismiss_popups(self) -> None:
        """Try to close cookie banners, notification prompts, etc."""
        for key in ("cookie_dismiss", "popup_dismiss"):
            for by, value in SELECTORS.get(key, []):
                try:
                    btn = WebDriverWait(self.driver, 2).until(
                        EC.element_to_be_clickable((by, value))
                    )
                    btn.click()
                    logger.debug(f"Dismissed popup via {key}: {value}")
                    time.sleep(0.5)
                except (TimeoutException, ElementClickInterceptedException):
                    continue

    # ------------------------------------------------------------------
    # Login check
    # ------------------------------------------------------------------
    def is_logged_in(self) -> bool:
        """Check whether the browser is authenticated on RedGifs."""
        self.navigate_to(REDGIFS_BASE)
        self.dismiss_popups()

        # Positive check — look for upload link / profile indicators
        for by, value in SELECTORS["login_indicator"]:
            try:
                WebDriverWait(self.driver, 8).until(
                    EC.presence_of_element_located((by, value))
                )
                logger.info("Already logged in to RedGifs")
                return True
            except TimeoutException:
                continue

        # Negative check — look for login page indicators
        for by, value in SELECTORS["not_logged_in_indicator"]:
            try:
                self.driver.find_element(by, value)
                logger.warning("Not logged in to RedGifs — login page detected")
                return False
            except NoSuchElementException:
                continue

        logger.warning("Could not determine RedGifs login state")
        return False

    # ------------------------------------------------------------------
    # Upload content (replaces compose_tweet for RedGifs)
    # ------------------------------------------------------------------
    def upload_content(
        self,
        media_file: Path,
        tags: list[str] | None = None,
        title: str = "",
        sound_on: bool = True,
    ) -> str | None:
        """Upload a file to RedGifs.

        Returns the resulting URL if available, else None.
        This replaces compose_tweet — RedGifs is upload-only rather than
        microblog-style.
        """
        self.navigate_to(REDGIFS_UPLOAD_URL)
        self._action_delay()
        self.dismiss_popups()

        try:
            # Step 1: Find the file input and upload
            file_input = _find_with_fallback(
                self.driver, "upload_file_input", timeout=15
            )
            abs_path = str(media_file.resolve())
            logger.debug(f"Uploading to RedGifs: {abs_path}")
            file_input.send_keys(abs_path)
            self._action_delay()

            # Step 2: Wait for upload / processing
            has_video = media_file.suffix.lower() in _VIDEO_EXTENSIONS
            process_timeout = (
                _UPLOAD_TIMEOUT_VIDEO if has_video else _UPLOAD_TIMEOUT_IMAGE
            )
            self._wait_for_upload_processing(process_timeout)

            # Step 3: Enter tags
            if tags:
                self._enter_tags(tags)

            # Step 4: Optionally set title
            if title:
                self._enter_title(title)

            # Step 5: Optionally toggle sound off
            if not sound_on:
                self._toggle_sound_off()

            self._action_delay()

            # Step 6: Submit
            submit_btn = _find_with_fallback(
                self.driver, "submit_button", timeout=15, clickable=True
            )
            self._move_and_click(submit_btn)
            logger.info("RedGifs upload submitted")
            self._page_delay()

            # Step 7: Extract the resulting URL
            # After submission, RedGifs typically redirects to the new content page
            time.sleep(5)
            result_url = self.get_current_url()
            if REDGIFS_BASE in result_url and result_url != REDGIFS_UPLOAD_URL:
                logger.info(f"RedGifs upload URL: {result_url}")
                return result_url

            return None

        except (TimeoutException, NoSuchElementException) as exc:
            logger.error(f"Failed to upload to RedGifs: {exc}")
            return None
        except ElementClickInterceptedException as exc:
            logger.error(f"Could not click submit button on RedGifs: {exc}")
            return None

    # ------------------------------------------------------------------
    # Upload helpers
    # ------------------------------------------------------------------
    def _wait_for_upload_processing(self, timeout: int) -> None:
        """Wait for the upload progress indicator to disappear."""
        for by, value in SELECTORS.get("upload_progress", []):
            try:
                # Wait for progress indicator to APPEAR
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((by, value))
                )
                # Now wait for it to DISAPPEAR
                WebDriverWait(self.driver, timeout).until_not(
                    EC.presence_of_element_located((by, value))
                )
                logger.debug("Upload processing complete")
                return
            except TimeoutException:
                continue

        # Fallback: wait a fixed amount if no progress indicator was found
        fallback = timeout // 3
        logger.debug(
            f"No progress indicator found, waiting {fallback}s as fallback"
        )
        time.sleep(fallback)

    def _enter_tags(self, tags: list[str]) -> None:
        """Enter tags into the tag input field."""
        try:
            tag_input = _find_with_fallback(
                self.driver, "tags_input", timeout=10
            )
            tag_input.click()
            self._action_delay()

            for tag in tags:
                clean_tag = tag.strip().strip("#")
                if clean_tag:
                    self._human_type(tag_input, clean_tag)
                    # Tags are typically confirmed with Enter or comma
                    tag_input.send_keys(Keys.ENTER)
                    self._action_delay()

            logger.debug(f"Entered {len(tags)} tags")
        except NoSuchElementException:
            logger.warning("Could not find tag input on RedGifs upload page")

    def _enter_title(self, title: str) -> None:
        """Enter a title into the title field."""
        try:
            title_input = _find_with_fallback(
                self.driver, "title_input", timeout=8
            )
            title_input.click()
            self._human_type(title_input, title)
            logger.debug(f"Entered title: {title[:50]}...")
        except NoSuchElementException:
            logger.warning("Could not find title input on RedGifs upload page")

    def _toggle_sound_off(self) -> None:
        """Toggle the sound option off."""
        try:
            toggle = _find_with_fallback(
                self.driver, "sound_toggle", timeout=5, clickable=True
            )
            self._move_and_click(toggle)
            logger.debug("Toggled sound off")
        except NoSuchElementException:
            logger.debug("Sound toggle not found — may default to on")

    # ------------------------------------------------------------------
    # Human-like browsing actions (for human simulator)
    # ------------------------------------------------------------------
    def scroll_feed(self, scroll_count: int = 1) -> int:
        """Scroll the current page with human-like varied amounts."""
        total = 0
        for _ in range(scroll_count):
            pixels = random.randint(300, 900)
            # Occasional upward scroll for realism
            if random.random() < 0.1:
                pixels = -random.randint(100, 300)
            self.driver.execute_script(f"window.scrollBy(0, {pixels});")
            total += abs(pixels)
            time.sleep(random.uniform(1.5, 4.0))
        return total

    def like_post_on_page(self) -> bool:
        """Like a random visible content item on the current page."""
        try:
            like_buttons = self.driver.find_elements(*SELECTORS["like_button"][0])
            if not like_buttons:
                for by, value in SELECTORS["like_button"][1:]:
                    like_buttons = self.driver.find_elements(by, value)
                    if like_buttons:
                        break
            if not like_buttons:
                return False

            btn = random.choice(like_buttons)
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", btn
            )
            time.sleep(random.uniform(0.5, 1.5))
            self._move_and_click(btn)
            logger.debug("Liked a post on RedGifs")
            self._action_delay()
            return True
        except (
            NoSuchElementException,
            ElementClickInterceptedException,
            StaleElementReferenceException,
        ) as exc:
            logger.debug(f"Could not like post on RedGifs: {exc}")
            return False

    def navigate_explore(self) -> None:
        """Navigate to the RedGifs browse / discover page."""
        self.navigate_to(f"{REDGIFS_BASE}/browse")
