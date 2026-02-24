"""Core Selenium helpers for interacting with RedGifs.com.

RedGifs is an upload-only platform for video/image content. Sessions are
pre-authenticated via the anti-detect browser profile — this module does
NOT handle login.

The upload flow at https://www.redgifs.com/create is a **6-step wizard**:
  Step 1: Select file (video or image) — hidden file input behind buttons
  Step 2: Video editor — trim slider, sound toggle, "Next"
  Step 3: Audience preference — radio buttons, "Next"
  Step 4: Tag selection — click tag buttons (3-10 required), "Next"
  Step 5: Niche selection — checkboxes or "Skip"
  Step 6: Description (disabled for non-verified), "Make Private", "Publish"

Selectors were captured from the real RedGifs DOM on 2026-02-15.
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

REDGIFS_BASE = "https://www.redgifs.com"
REDGIFS_CREATE_URL = f"{REDGIFS_BASE}/create"

# Upload processing timeouts (seconds)
_UPLOAD_TIMEOUT_VIDEO = 300  # videos may take 3-5 minutes to process
_UPLOAD_TIMEOUT_IMAGE = 60
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}

_VALID_AUDIENCES = ("straight", "gay", "lesbian", "trans", "bisexual", "animated")

# ---------------------------------------------------------------------------
# Selector fallback chains — derived from real RedGifs DOM (2026-02-15).
# Each entry is a list of (By strategy, selector value) tuples tried in order.
# ---------------------------------------------------------------------------
SELECTORS = {
    # Step 1: Upload page buttons
    "select_video_button": [
        (By.CSS_SELECTOR, 'button[aria-label="select a video"]'),
        (By.XPATH, '//button[.//span[text()="Select a Video"]]'),
    ],
    "select_image_button": [
        (By.CSS_SELECTOR, 'button[aria-label="select images(s)"]'),
        (By.XPATH, '//button[.//span[text()="Select Image(s)"]]'),
    ],
    "hidden_file_input": [
        (By.CSS_SELECTOR, 'input[type="file"]'),
        (By.XPATH, '//input[@type="file"]'),
    ],

    # Step 2: Video editor
    "sound_toggle": [
        (By.CSS_SELECTOR, 'input.ToggleButton-Input[type="checkbox"]'),
        (By.XPATH, '//p[text()="Enable Sound"]/following::input[@type="checkbox"][1]'),
    ],
    "next_button_primary_full": [
        (By.CSS_SELECTOR, "button.Button_primary.Button_fullWidth"),
        (By.XPATH, '//button[contains(@class,"Button_primary") and contains(@class,"Button_fullWidth")]'),
    ],

    # Step 3: Audience preference — radio inputs are selected dynamically
    # via input[id="{value}"] where value ∈ _VALID_AUDIENCES
    "next_step_button": [
        (By.CSS_SELECTOR, 'button[aria-label="next step"]'),
        (By.XPATH, '//button[@aria-label="next step"]'),
    ],

    # Step 4: Tag selection
    "tag_search_input": [
        (By.CSS_SELECTOR, 'input[placeholder="Type to search for tags..."]'),
        (By.CSS_SELECTOR, "div.TagSelector-SearchBar input[type='text']"),
    ],
    # Individual tag buttons are matched dynamically:
    #   button[aria-label="Select {Tag Name} tag"]

    # Step 5: Niche selection
    "niche_skip_button": [
        (By.CSS_SELECTOR, "div.UploadNicheStep-Bottom button.Button_secondary"),
        (By.XPATH, '//div[contains(@class,"UploadNicheStep-Bottom")]//button[.//div[text()="Skip"]]'),
    ],
    "niche_next_button": [
        (By.CSS_SELECTOR, "div.UploadNicheStep-Bottom button.Button_primary"),
        (By.XPATH, '//div[contains(@class,"UploadNicheStep-Bottom")]//button[.//div[text()="Next"]]'),
    ],

    # Step 6: Publish
    "publish_button": [
        (By.CSS_SELECTOR, 'button[aria-label="publish"]'),
        (By.XPATH, '//button[@aria-label="publish"]'),
    ],
    "make_private_toggle": [
        (By.CSS_SELECTOR, "div.UploadFifthStep-Option input.ToggleButton-Input"),
        (By.XPATH, '//p[text()="Make Private"]/following::input[@type="checkbox"][1]'),
    ],

    # Login indicators
    "login_indicator": [
        (By.CSS_SELECTOR, 'a[href="/create"]'),
        (By.CSS_SELECTOR, '[aria-label="Upload"]'),
        (By.CSS_SELECTOR, 'a[href*="/users/"]'),
        (By.XPATH, '//a[contains(text(), "Upload")]'),
    ],
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
    # Upload content — 6-step wizard at /create
    # ------------------------------------------------------------------
    def upload_content(
        self,
        media_file: Path,
        tags: list[str] | None = None,
        title: str = "",
        sound_on: bool = True,
        audience_preference: str = "straight",
    ) -> str | None:
        """Upload a file to RedGifs via the 6-step create wizard.

        Steps:
          1. Navigate to /create and inject the file into the hidden input
          2. Handle sound toggle in the video editor, click Next
          3. Select audience preference, click Next
          4. Select tags by clicking tag buttons, click Next
          5. Skip niche selection
          6. Click Publish

        Returns the resulting content URL if available, else None.
        """
        if audience_preference not in _VALID_AUDIENCES:
            audience_preference = "straight"

        self.navigate_to(REDGIFS_CREATE_URL)
        self._action_delay()
        self.dismiss_popups()

        is_video = media_file.suffix.lower() in _VIDEO_EXTENSIONS

        try:
            # === Step 1: Upload the file ===
            abs_path = str(media_file.resolve())
            logger.info(f"[RedGifs] Uploading file: {media_file.name}")
            self._inject_file(abs_path, is_video)

            # === Step 2: Video editor — sound toggle + Next ===
            if is_video:
                self._handle_video_editor(sound_on)
            else:
                # For images, the editor step may be skipped or have a
                # simpler layout.  Wait for whichever step appears next.
                self._wait_for_any_next_button(timeout=30)
                self._click_visible_next_button()

            # === Step 3: Audience preference ===
            self._select_audience(audience_preference)

            # === Step 4: Tag selection ===
            self._select_tags(tags or [])

            # === Step 5: Niche selection — skip ===
            self._handle_niche_step()

            # === Step 6: Publish ===
            result_url = self._publish()
            return result_url

        except (TimeoutException, NoSuchElementException) as exc:
            logger.error(f"[RedGifs] Upload failed: {exc}")
            return None
        except ElementClickInterceptedException as exc:
            logger.error(f"[RedGifs] Click intercepted during upload: {exc}")
            return None

    # ------------------------------------------------------------------
    # Step 1 helpers — file injection
    # ------------------------------------------------------------------
    def _inject_file(self, abs_path: str, is_video: bool) -> None:
        """Find the hidden file input and send the file path.

        RedGifs hides the <input type="file"> behind styled buttons.
        Selenium can send_keys to hidden inputs if we find them in the DOM.
        If the input isn't present yet, we click the upload button to
        trigger its creation, then find and populate it.
        """
        # Try to find a hidden file input already in the DOM
        file_input = self._try_find_file_input(timeout=3)

        if not file_input:
            # Click the appropriate upload button to trigger the file input
            btn_key = "select_video_button" if is_video else "select_image_button"
            try:
                upload_btn = _find_with_fallback(
                    self.driver, btn_key, timeout=10, clickable=True
                )
                # Use JavaScript click to avoid intercepted-click issues
                self.driver.execute_script("arguments[0].click();", upload_btn)
                time.sleep(1)
            except NoSuchElementException:
                logger.warning(
                    f"[RedGifs] Could not find {btn_key}, trying generic file input"
                )

            # Now the file input should exist
            file_input = self._try_find_file_input(timeout=5)

        if not file_input:
            # Last resort: use JS to find any file input in the DOM
            file_input = self.driver.execute_script(
                "var el = document.querySelector('input[type=\"file\"]');"
                "if (el) { el.style.display = 'block'; el.style.opacity = '1'; }"
                "return el;"
            )

        if not file_input:
            raise NoSuchElementException(
                "[RedGifs] Could not find file input element on /create"
            )

        file_input.send_keys(abs_path)
        logger.debug(f"[RedGifs] File injected: {abs_path}")

        # Wait for the file to be accepted and the wizard to advance
        timeout = _UPLOAD_TIMEOUT_VIDEO if abs_path.lower().endswith(
            tuple(_VIDEO_EXTENSIONS)
        ) else _UPLOAD_TIMEOUT_IMAGE
        self._wait_for_wizard_advance(timeout)

    def _try_find_file_input(self, timeout: float = 3):
        """Attempt to find an <input type='file'> on the page."""
        for by, value in SELECTORS["hidden_file_input"]:
            try:
                el = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
                return el
            except TimeoutException:
                continue
        return None

    def _wait_for_wizard_advance(self, timeout: int) -> None:
        """Wait for the wizard to advance past the file-upload step.

        After file injection, RedGifs processes the upload and shows
        either the video editor (step 2) or advances further.  We wait
        for a "Next" button or the audience preference step to appear.
        """
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: (
                    self._element_present("next_button_primary_full")
                    or self._element_present("next_step_button")
                )
            )
            logger.debug("[RedGifs] Wizard advanced past file upload")
        except TimeoutException:
            logger.warning(
                f"[RedGifs] Wizard did not advance within {timeout}s — "
                "attempting to continue anyway"
            )

    def _element_present(self, selector_key: str) -> bool:
        """Check if any selector in the fallback chain matches (no wait)."""
        for by, value in SELECTORS.get(selector_key, []):
            try:
                self.driver.find_element(by, value)
                return True
            except NoSuchElementException:
                continue
        return False

    # ------------------------------------------------------------------
    # Step 2 helpers — video editor
    # ------------------------------------------------------------------
    def _handle_video_editor(self, sound_on: bool) -> None:
        """Handle the video editor step: optional sound toggle + Next."""
        # Wait for the "Next" button in the video editor to become available
        try:
            _find_with_fallback(
                self.driver, "next_button_primary_full",
                timeout=_UPLOAD_TIMEOUT_VIDEO, clickable=True,
            )
        except NoSuchElementException:
            logger.warning("[RedGifs] Video editor Next button not found")
            return

        # Handle sound toggle
        if not sound_on:
            self._toggle_sound_off()

        self._action_delay()

        # Click "Next" to move to step 3
        self._click_next_primary_full()

    def _toggle_sound_off(self) -> None:
        """Uncheck the Enable Sound toggle if it's currently checked."""
        try:
            toggle = _find_with_fallback(
                self.driver, "sound_toggle", timeout=5
            )
            is_checked = toggle.get_attribute("checked") is not None
            if is_checked:
                # Click the parent wrapper to toggle (direct input click
                # may not work with custom toggle components)
                wrapper = toggle.find_element(
                    By.XPATH, "./ancestor::div[contains(@class,'ToggleButton')]"
                )
                self._move_and_click(wrapper)
                logger.debug("[RedGifs] Sound toggled OFF")
                self._action_delay()
        except NoSuchElementException:
            logger.debug("[RedGifs] Sound toggle not found — may default to on")

    def _click_next_primary_full(self) -> None:
        """Click the full-width primary Next button (video editor step)."""
        btn = _find_with_fallback(
            self.driver, "next_button_primary_full", timeout=10, clickable=True
        )
        self._move_and_click(btn)
        self._action_delay()

    # ------------------------------------------------------------------
    # Step 3 helpers — audience preference
    # ------------------------------------------------------------------
    def _select_audience(self, preference: str) -> None:
        """Select an audience radio button and click Next."""
        # Wait for the audience step to appear
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "ul.GifPreferenceList")
                )
            )
        except TimeoutException:
            logger.warning("[RedGifs] Audience preference list not found — skipping")
            # Try to find and click whatever Next button is visible
            self._click_any_next_button()
            return

        # Click the radio button for the chosen audience
        try:
            radio = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, f'input[type="radio"][id="{preference}"]')
                )
            )
            # Click the label (parent) for better hit area
            label = radio.find_element(By.XPATH, "./ancestor::label")
            self._move_and_click(label)
            logger.debug(f"[RedGifs] Selected audience: {preference}")
        except (TimeoutException, NoSuchElementException):
            logger.warning(
                f"[RedGifs] Could not select audience '{preference}' — "
                "defaulting to whatever is pre-selected"
            )

        self._action_delay()

        # Click "Next" (aria-label="next step")
        self._click_next_step_button()

    def _click_next_step_button(self) -> None:
        """Click the 'next step' button (audience / tags steps)."""
        btn = _find_with_fallback(
            self.driver, "next_step_button", timeout=10, clickable=True
        )
        self._move_and_click(btn)
        self._action_delay()

    def _click_any_next_button(self) -> None:
        """Click whichever Next button is currently visible."""
        for key in ("next_step_button", "next_button_primary_full",
                     "niche_next_button"):
            try:
                btn = _find_with_fallback(
                    self.driver, key, timeout=3, clickable=True
                )
                self._move_and_click(btn)
                self._action_delay()
                return
            except NoSuchElementException:
                continue
        logger.warning("[RedGifs] No Next button found to click")

    # ------------------------------------------------------------------
    # Step 4 helpers — tag selection
    # ------------------------------------------------------------------
    def _select_tags(self, tags: list[str]) -> None:
        """Select tags by clicking the corresponding tag buttons.

        RedGifs requires 3-10 tags.  Each tag button has
        aria-label="Select {Tag Name} tag".  If a tag isn't visible in
        the initial list, we type it into the search input to filter.
        """
        # Wait for the tag selector to appear
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.TagSelector")
                )
            )
        except TimeoutException:
            logger.warning("[RedGifs] Tag selector not found — skipping tags")
            self._click_any_next_button()
            return

        selected_count = 0

        for tag in tags[:10]:  # RedGifs max 10 tags
            tag_clean = tag.strip()
            if not tag_clean:
                continue

            clicked = self._try_click_tag(tag_clean)
            if clicked:
                selected_count += 1
            else:
                # Tag not visible — try searching for it
                clicked = self._search_and_click_tag(tag_clean)
                if clicked:
                    selected_count += 1

            if selected_count > 0:
                time.sleep(random.uniform(0.5, 1.5))

        if selected_count < 3:
            logger.warning(
                f"[RedGifs] Only {selected_count} tags selected "
                f"(minimum 3 required) — Next button may be disabled"
            )

        self._action_delay()

        # Click "Next" — may need to wait for it to become enabled
        try:
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'button[aria-label="next step"]')
                )
            )
            self._click_next_step_button()
        except TimeoutException:
            logger.warning(
                "[RedGifs] Next button not clickable after tag selection "
                f"({selected_count} tags selected, need >= 3)"
            )
            # Force-click anyway
            self._click_any_next_button()

    def _try_click_tag(self, tag_name: str) -> bool:
        """Try to click a tag button by its aria-label."""
        selector = f'button[aria-label="Select {tag_name} tag"]'
        try:
            btn = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", btn
            )
            time.sleep(0.3)
            self._move_and_click(btn)
            logger.debug(f"[RedGifs] Selected tag: {tag_name}")
            return True
        except (TimeoutException, NoSuchElementException):
            return False
        except ElementClickInterceptedException:
            # Try JS click as fallback
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                self.driver.execute_script("arguments[0].click();", btn)
                logger.debug(f"[RedGifs] Selected tag (JS click): {tag_name}")
                return True
            except NoSuchElementException:
                return False

    def _search_and_click_tag(self, tag_name: str) -> bool:
        """Type the tag name into the search input, then click the result."""
        try:
            search_input = _find_with_fallback(
                self.driver, "tag_search_input", timeout=5
            )
            # Clear previous search
            search_input.clear()
            self._human_type(search_input, tag_name)
            time.sleep(1.5)  # Wait for search results to filter

            # Try to click the tag button in the filtered results
            clicked = self._try_click_tag(tag_name)

            # Clear the search input for the next tag
            search_input.clear()
            time.sleep(0.5)

            return clicked
        except NoSuchElementException:
            logger.debug(f"[RedGifs] Could not search for tag: {tag_name}")
            return False

    # ------------------------------------------------------------------
    # Step 5 helpers — niche selection
    # ------------------------------------------------------------------
    def _handle_niche_step(self) -> None:
        """Handle the niche selection step — skip for now."""
        # Wait for the niche step to appear
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.UploadNicheStep")
                )
            )
        except TimeoutException:
            # Niche step might be skipped by the platform
            logger.debug("[RedGifs] Niche step not found — may have been skipped")
            return

        self._action_delay()

        # Click "Skip" or "Next" — prefer Next if available, Skip as fallback
        for key in ("niche_next_button", "niche_skip_button"):
            try:
                btn = _find_with_fallback(
                    self.driver, key, timeout=5, clickable=True
                )
                self._move_and_click(btn)
                logger.debug(f"[RedGifs] Niche step: clicked {key}")
                self._action_delay()
                return
            except NoSuchElementException:
                continue

        logger.warning("[RedGifs] Could not find Skip or Next on niche step")

    # ------------------------------------------------------------------
    # Step 6 helpers — publish
    # ------------------------------------------------------------------
    def _publish(self) -> str | None:
        """Click Publish and wait for the result URL."""
        # Wait for the publish step to appear
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.UploadFifthStep")
                )
            )
        except TimeoutException:
            logger.debug("[RedGifs] Publish step container not found — trying anyway")

        self._action_delay()

        # Click Publish
        publish_btn = _find_with_fallback(
            self.driver, "publish_button", timeout=15, clickable=True
        )
        self._move_and_click(publish_btn)
        logger.info("[RedGifs] Clicked Publish")

        # Wait for redirect to the content page
        self._page_delay()
        time.sleep(5)

        # Check if we've been redirected to a content page
        result_url = self.get_current_url()
        if (
            REDGIFS_BASE in result_url
            and result_url != REDGIFS_CREATE_URL
            and "/create" not in result_url
        ):
            logger.info(f"[RedGifs] Upload successful: {result_url}")
            return result_url

        # Sometimes the URL doesn't change immediately.  Wait a bit more
        # and check for a success indicator or URL change.
        for _ in range(6):
            time.sleep(5)
            result_url = self.get_current_url()
            if (
                REDGIFS_BASE in result_url
                and "/create" not in result_url
            ):
                logger.info(f"[RedGifs] Upload successful (delayed): {result_url}")
                return result_url

        logger.warning("[RedGifs] Could not confirm upload success — URL unchanged")
        return None

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _wait_for_any_next_button(self, timeout: float = 15) -> None:
        """Wait for any variant of the Next button to appear."""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: (
                    self._element_present("next_button_primary_full")
                    or self._element_present("next_step_button")
                )
            )
        except TimeoutException:
            logger.debug("[RedGifs] No Next button appeared within timeout")

    def _click_visible_next_button(self) -> None:
        """Click whichever Next button is currently visible."""
        for key in ("next_button_primary_full", "next_step_button"):
            try:
                btn = _find_with_fallback(
                    self.driver, key, timeout=3, clickable=True
                )
                self._move_and_click(btn)
                self._action_delay()
                return
            except NoSuchElementException:
                continue
        logger.warning("[RedGifs] No visible Next button found")

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
