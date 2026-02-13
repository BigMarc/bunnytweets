"""Core Selenium helpers for interacting with Threads.net.

Threads uses Instagram login credentials. Sessions are pre-authenticated
via the anti-detect browser profile — this module does NOT handle login.

Selector strategy (in priority order):
  1. role / aria-label attributes (stable across deploys)
  2. data-testid attributes (if present)
  3. XPath text content
  4. Structural selectors (last resort — documented when used)

All class names (x1i10hfl, xdj266r, …) are hashed CSS-modules and MUST
NOT be used — they change on every Threads deploy.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
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

THREADS_BASE = "https://www.threads.net"

# Timeouts (seconds) for waiting on media upload processing
_UPLOAD_TIMEOUT_IMAGE = 30
_UPLOAD_TIMEOUT_VIDEO = 180  # videos can take 1-3 minutes
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}

# ---------------------------------------------------------------------------
# Selector fallback chains — update HERE when Threads changes its UI.
# Each entry is (By strategy, selector value).
# ---------------------------------------------------------------------------
SELECTORS = {
    "compose_button": [
        (By.CSS_SELECTOR, '[aria-label="Create"]'),
        (By.CSS_SELECTOR, '[aria-label="New thread"]'),
        (By.XPATH, '//div[contains(text(), "Start a thread")]'),
        (By.XPATH, '//*[contains(text(), "What\'s new?")]'),
    ],
    "compose_textbox": [
        (By.CSS_SELECTOR, '[role="dialog"] [role="textbox"]'),
        (By.CSS_SELECTOR, '[role="dialog"] div[contenteditable="true"]'),
        (By.CSS_SELECTOR, '[role="textbox"]'),
        (By.CSS_SELECTOR, 'div[contenteditable="true"]'),
    ],
    "post_button": [
        (By.XPATH, '//div[@role="button"][.//text()="Post"]'),
        (By.XPATH, '//div[text()="Post"]'),
        (By.XPATH, '//span[text()="Post"]'),
    ],
    "media_input": [
        (By.CSS_SELECTOR, '[role="dialog"] input[type="file"]'),
        (By.CSS_SELECTOR, 'input[type="file"][accept*="image"]'),
        (By.CSS_SELECTOR, 'input[type="file"]'),
    ],
    "like_button": [
        (By.CSS_SELECTOR, '[aria-label="Like"]'),
        (By.CSS_SELECTOR, 'svg[aria-label="Like"]'),
    ],
    "reply_button": [
        (By.CSS_SELECTOR, '[aria-label="Reply"]'),
        (By.CSS_SELECTOR, 'svg[aria-label="Reply"]'),
    ],
    "repost_button": [
        (By.CSS_SELECTOR, '[aria-label="Repost"]'),
        (By.CSS_SELECTOR, 'svg[aria-label="Repost"]'),
    ],
    "repost_menu_repost": [
        (By.XPATH, '//span[text()="Repost"]'),
        (By.XPATH, '//div[text()="Repost"]'),
    ],
    "repost_menu_quote": [
        (By.XPATH, '//span[text()="Quote"]'),
        (By.XPATH, '//div[text()="Quote"]'),
    ],
    "login_indicator": [
        (By.CSS_SELECTOR, '[aria-label="Create"]'),
        (By.CSS_SELECTOR, '[aria-label="New thread"]'),
        (By.CSS_SELECTOR, '[aria-label="Profile"]'),
    ],
    "not_logged_in_indicator": [
        (By.XPATH, '//span[contains(text(), "Log in")]'),
        (By.XPATH, '//span[contains(text(), "Continue with Instagram")]'),
        (By.CSS_SELECTOR, 'input[name="username"]'),
    ],
    "cookie_dismiss": [
        (By.XPATH, '//button[contains(text(), "Allow")]'),
        (By.XPATH, '//button[contains(text(), "Decline")]'),
        (By.XPATH, '//button[contains(text(), "Accept")]'),
    ],
    "popup_dismiss": [
        (By.XPATH, '//button[contains(text(), "Not now")]'),
        (By.XPATH, '//button[contains(text(), "Not Now")]'),
        (By.CSS_SELECTOR, '[aria-label="Close"]'),
    ],
    "add_to_thread": [
        (By.XPATH, '//div[@role="button"][contains(text(), "Add to thread")]'),
        (By.XPATH, '//*[text()="Add to thread"]'),
        (By.CSS_SELECTOR, '[aria-label="Add to thread"]'),
    ],
    "activity_tab": [
        (By.CSS_SELECTOR, '[aria-label="Activity"]'),
        (By.CSS_SELECTOR, 'a[href="/activity"]'),
    ],
}


def _find_with_fallback(driver, selector_key: str, timeout: float = 10,
                        clickable: bool = False):
    """Try each selector in the fallback chain until one succeeds.

    Returns the first matching element.
    Raises NoSuchElementException if none match.
    """
    selectors = SELECTORS.get(selector_key, [])
    condition = EC.element_to_be_clickable if clickable else EC.presence_of_element_located

    for by, value in selectors:
        try:
            el = WebDriverWait(driver, timeout).until(condition((by, value)))
            return el
        except TimeoutException:
            continue

    raise NoSuchElementException(
        f"None of the selectors for '{selector_key}' matched within {timeout}s"
    )


class ThreadsAutomation(PlatformAutomation):
    """Low-level Selenium operations for Threads.net."""

    def __init__(self, driver: webdriver.Chrome, delays: dict | None = None):
        self.driver = driver
        self.delays = delays or {}

    # ------------------------------------------------------------------
    # Delay helpers (mirrors TwitterAutomation API)
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
        self.navigate_to(THREADS_BASE)

    def navigate_to_profile(self, username: str) -> None:
        clean = username.lstrip("@")
        self.navigate_to(f"{THREADS_BASE}/@{clean}")

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
        """Check whether the browser is authenticated on Threads."""
        self.navigate_to(THREADS_BASE)
        self.dismiss_popups()

        # Positive check — look for compose / profile buttons
        for by, value in SELECTORS["login_indicator"]:
            try:
                WebDriverWait(self.driver, 8).until(
                    EC.presence_of_element_located((by, value))
                )
                logger.info("Already logged in to Threads")
                return True
            except TimeoutException:
                continue

        # Negative check — look for login page indicators
        for by, value in SELECTORS["not_logged_in_indicator"]:
            try:
                self.driver.find_element(by, value)
                logger.warning("Not logged in to Threads — login page detected")
                return False
            except NoSuchElementException:
                continue

        logger.warning("Could not determine Threads login state")
        return False

    # ------------------------------------------------------------------
    # Compose (new post)
    # ------------------------------------------------------------------
    def compose_tweet(self, text: str = "", media_files: list[Path] | None = None) -> bool:
        """Create a new Threads post. Named compose_tweet for API parity with Twitter.

        Returns True on success.
        """
        self.navigate_to_home()
        self._action_delay()

        try:
            # Open compose dialog
            compose_btn = _find_with_fallback(
                self.driver, "compose_button", timeout=10, clickable=True
            )
            self._move_and_click(compose_btn)
            self._action_delay()

            # Find the textbox inside the dialog
            textbox = _find_with_fallback(
                self.driver, "compose_textbox", timeout=10
            )
            textbox.click()
            self._action_delay()

            # Type text (500-char limit on Threads)
            if text:
                trimmed = text[:500]
                if len(text) > 500:
                    logger.warning(
                        f"Text truncated from {len(text)} to 500 characters for Threads"
                    )
                self._human_type(textbox, trimmed)
                self._action_delay()

            # Upload media if provided
            if media_files:
                try:
                    file_input = _find_with_fallback(
                        self.driver, "media_input", timeout=8
                    )
                    has_video = any(
                        mf.suffix.lower() in _VIDEO_EXTENSIONS for mf in media_files
                    )
                    upload_timeout = _UPLOAD_TIMEOUT_VIDEO if has_video else _UPLOAD_TIMEOUT_IMAGE
                    for mf in media_files:
                        abs_path = str(mf.resolve())
                        logger.debug(f"Uploading media: {abs_path}")
                        file_input.send_keys(abs_path)
                        self._action_delay()
                        # Wait for upload to process
                        time.sleep(3 if not has_video else 5)
                except NoSuchElementException:
                    logger.warning("Could not find media upload input — posting without media")

            self._action_delay()

            # Click Post — use a longer timeout for video uploads since the
            # Post button stays disabled until the upload finishes processing.
            has_video = media_files and any(
                mf.suffix.lower() in _VIDEO_EXTENSIONS for mf in media_files
            )
            post_btn_timeout = _UPLOAD_TIMEOUT_VIDEO if has_video else 10
            try:
                post_btn = _find_with_fallback(
                    self.driver, "post_button", timeout=post_btn_timeout, clickable=True
                )
            except NoSuchElementException:
                logger.error(
                    f"Post button not clickable after {post_btn_timeout}s "
                    "— media upload may have failed"
                )
                return False
            self._move_and_click(post_btn)
            logger.info("Threads post published successfully")
            self._page_delay()
            return True

        except (TimeoutException, NoSuchElementException) as exc:
            logger.error(f"Failed to compose Threads post: {exc}")
            return False
        except ElementClickInterceptedException as exc:
            logger.error(f"Could not click post button on Threads: {exc}")
            return False

    # ------------------------------------------------------------------
    # Repost
    # ------------------------------------------------------------------
    def retweet(self, post_url: str) -> bool:
        """Repost a Threads post. Named retweet for API parity."""
        self.navigate_to(post_url)
        self._action_delay()

        try:
            repost_btn = _find_with_fallback(
                self.driver, "repost_button", timeout=10, clickable=True
            )
            self._move_and_click(repost_btn)
            self._action_delay()

            # Click "Repost" in the menu
            confirm = _find_with_fallback(
                self.driver, "repost_menu_repost", timeout=8, clickable=True
            )
            self._move_and_click(confirm)
            logger.info(f"Reposted on Threads: {post_url}")
            self._action_delay()
            return True

        except (TimeoutException, NoSuchElementException) as exc:
            logger.error(f"Failed to repost {post_url}: {exc}")
            return False

    def quote_post(self, post_url: str, text: str) -> bool:
        """Quote-post on Threads."""
        self.navigate_to(post_url)
        self._action_delay()

        try:
            repost_btn = _find_with_fallback(
                self.driver, "repost_button", timeout=10, clickable=True
            )
            self._move_and_click(repost_btn)
            self._action_delay()

            quote_btn = _find_with_fallback(
                self.driver, "repost_menu_quote", timeout=8, clickable=True
            )
            self._move_and_click(quote_btn)
            self._action_delay()

            textbox = _find_with_fallback(self.driver, "compose_textbox", timeout=10)
            textbox.click()
            self._human_type(textbox, text[:500])
            self._action_delay()

            post_btn = _find_with_fallback(
                self.driver, "post_button", timeout=10, clickable=True
            )
            self._move_and_click(post_btn)
            logger.info(f"Quote-posted on Threads: {post_url}")
            self._page_delay()
            return True

        except (TimeoutException, NoSuchElementException) as exc:
            logger.error(f"Failed to quote-post {post_url}: {exc}")
            return False

    # ------------------------------------------------------------------
    # Reply
    # ------------------------------------------------------------------
    def reply_to_tweet(self, post_url: str, text: str) -> bool:
        """Reply to a Threads post. Named reply_to_tweet for API parity."""
        self.navigate_to(post_url)
        self._action_delay()

        try:
            reply_btn = _find_with_fallback(
                self.driver, "reply_button", timeout=10, clickable=True
            )
            self._move_and_click(reply_btn)
            self._action_delay()

            textbox = _find_with_fallback(self.driver, "compose_textbox", timeout=10)
            textbox.click()
            self._action_delay()

            self._human_type(textbox, text[:500])
            self._action_delay()

            post_btn = _find_with_fallback(
                self.driver, "post_button", timeout=10, clickable=True
            )
            self._move_and_click(post_btn)
            logger.info(f"Replied on Threads: {post_url}")
            self._page_delay()
            return True

        except (TimeoutException, NoSuchElementException) as exc:
            logger.error(f"Failed to reply to {post_url}: {exc}")
            return False

    # ------------------------------------------------------------------
    # Fetching posts from a profile
    # ------------------------------------------------------------------
    def get_latest_tweet_urls(self, username: str, limit: int = 10) -> list[str]:
        """Scrape latest post URLs from a Threads profile. Named for API parity."""
        clean = username.lstrip("@")
        self.navigate_to_profile(clean)
        self._page_delay()

        post_urls: list[str] = []
        try:
            # Wait for any posts to load
            WebDriverWait(self.driver, 12).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, f'a[href*="/@{clean}/post/"]')
                )
            )
            links = self.driver.find_elements(
                By.CSS_SELECTOR, f'a[href*="/@{clean}/post/"]'
            )
            seen = set()
            for link in links:
                href = link.get_attribute("href")
                if href and "/post/" in href and href not in seen:
                    seen.add(href)
                    post_urls.append(href)
                    if len(post_urls) >= limit:
                        break
        except TimeoutException:
            logger.warning(f"Could not load posts for @{clean} on Threads")

        logger.debug(f"Found {len(post_urls)} Threads posts for @{clean}")
        return post_urls

    def get_tweet_id_from_url(self, url: str) -> str:
        """Extract the post ID from a Threads URL."""
        # Format: https://www.threads.net/@username/post/ABC123xyz
        parts = url.rstrip("/").split("/")
        for i, part in enumerate(parts):
            if part == "post" and i + 1 < len(parts):
                return parts[i + 1]
        return ""

    # ------------------------------------------------------------------
    # Human-like browsing actions
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

    def like_tweet_on_page(self) -> bool:
        """Like a random visible post on the current page."""
        try:
            like_buttons = self.driver.find_elements(*SELECTORS["like_button"][0])
            if not like_buttons:
                # Fallback selector
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
            logger.debug("Liked a post on Threads")
            self._action_delay()
            return True
        except (NoSuchElementException, ElementClickInterceptedException,
                StaleElementReferenceException) as exc:
            logger.debug(f"Could not like post on Threads: {exc}")
            return False

    def navigate_explore(self) -> None:
        self.navigate_to(f"{THREADS_BASE}/search")

    def navigate_notifications(self) -> None:
        self.navigate_to(f"{THREADS_BASE}/activity")

    def get_notification_replies(self, limit: int = 15) -> list[dict]:
        """Scrape mentions/replies from the Activity tab."""
        self.navigate_notifications()
        self._page_delay()

        mentions: list[dict] = []
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'a[href*="/post/"]')
                )
            )
            links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/post/"]')
            seen = set()
            for link in links[:limit * 2]:
                href = link.get_attribute("href")
                if href and "/post/" in href and href not in seen:
                    seen.add(href)
                    post_id = self.get_tweet_id_from_url(href)
                    if post_id:
                        mentions.append({"url": href, "tweet_id": post_id})
                        if len(mentions) >= limit:
                            break
        except TimeoutException:
            logger.debug("No activity items found on Threads")

        logger.debug(f"Found {len(mentions)} activity items on Threads")
        return mentions
