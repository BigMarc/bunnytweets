"""Core Selenium helpers for interacting with Twitter/X."""

import random
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
)
from loguru import logger


TWITTER_BASE = "https://x.com"


class TwitterAutomation:
    """Low-level Selenium operations for Twitter/X."""

    def __init__(self, driver: webdriver.Chrome, delays: dict | None = None):
        self.driver = driver
        self.delays = delays or {}

    # ------------------------------------------------------------------
    # Delay helpers
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

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def navigate_to(self, url: str) -> None:
        logger.debug(f"Navigating to {url}")
        self.driver.get(url)
        self._page_delay()

    def navigate_home(self) -> None:
        self.navigate_to(f"{TWITTER_BASE}/home")

    # ------------------------------------------------------------------
    # Login (only needed if session is not already active)
    # ------------------------------------------------------------------
    def is_logged_in(self) -> bool:
        """Check whether the browser is already logged in to Twitter."""
        self.navigate_to(f"{TWITTER_BASE}/home")
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"],'
                                      'a[href="/compose/post"],'
                                      'div[data-testid="tweetTextarea_0"],'
                                      'div[data-testid="SideNav_NewTweet_Button"]')
                )
            )
            logger.info("Already logged in to Twitter")
            return True
        except TimeoutException:
            return False

    def login(self, username: str, password: str) -> bool:
        """Log in to Twitter. Returns True on success."""
        self.navigate_to(f"{TWITTER_BASE}/i/flow/login")
        self._page_delay()

        try:
            # Enter username
            user_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="text"]'))
            )
            self._human_type(user_input, username)
            self._action_delay()
            user_input.send_keys(Keys.ENTER)
            self._page_delay()

            # Enter password
            pass_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'input[name="password"]')
                )
            )
            self._human_type(pass_input, password)
            self._action_delay()
            pass_input.send_keys(Keys.ENTER)
            self._page_delay()

            # Verify login
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'a[data-testid="SideNav_NewTweet_Button"],'
                                      'div[data-testid="tweetTextarea_0"]')
                )
            )
            logger.info(f"Successfully logged in as {username}")
            return True

        except TimeoutException:
            logger.error(f"Login failed for {username} – timeout waiting for elements")
            return False

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------
    def compose_tweet(self, text: str = "", media_files: list[Path] | None = None) -> bool:
        """Open the compose dialog, fill in text and media, and send."""
        self.navigate_home()
        self._action_delay()

        try:
            # Click on tweet compose area
            textarea = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]')
                )
            )
            textarea.click()
            self._action_delay()

            # Type tweet text
            if text:
                self._human_type(textarea, text)
                self._action_delay()

            # Upload media files
            if media_files:
                file_input = self.driver.find_element(
                    By.CSS_SELECTOR, 'input[data-testid="fileInput"]'
                )
                for mf in media_files:
                    abs_path = str(mf.resolve())
                    logger.debug(f"Uploading media: {abs_path}")
                    file_input.send_keys(abs_path)
                    self._action_delay()
                    # Wait for upload to process
                    time.sleep(3)

            # Wait for the tweet button to become active
            self._action_delay()

            # Click tweet/post button
            tweet_btn = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'button[data-testid="tweetButton"]')
                )
            )
            tweet_btn.click()
            logger.info("Tweet posted successfully")
            self._page_delay()
            return True

        except (TimeoutException, NoSuchElementException) as exc:
            logger.error(f"Failed to compose tweet: {exc}")
            return False
        except ElementClickInterceptedException as exc:
            logger.error(f"Could not click tweet button: {exc}")
            return False

    # ------------------------------------------------------------------
    # Retweeting
    # ------------------------------------------------------------------
    def retweet(self, tweet_url: str) -> bool:
        """Navigate to a tweet and retweet it."""
        self.navigate_to(tweet_url)
        self._action_delay()

        try:
            retweet_btn = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'button[data-testid="retweet"]')
                )
            )
            retweet_btn.click()
            self._action_delay()

            confirm_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'div[data-testid="retweetConfirm"]')
                )
            )
            confirm_btn.click()
            logger.info(f"Retweeted: {tweet_url}")
            self._action_delay()
            return True

        except TimeoutException:
            # Might already be retweeted – check for unretweet button
            try:
                self.driver.find_element(
                    By.CSS_SELECTOR, 'button[data-testid="unretweet"]'
                )
                logger.info(f"Tweet already retweeted: {tweet_url}")
                return True
            except NoSuchElementException:
                logger.error(f"Failed to retweet {tweet_url} – button not found")
                return False

    # ------------------------------------------------------------------
    # Fetching tweets from a profile
    # ------------------------------------------------------------------
    def get_latest_tweet_urls(self, username: str, limit: int = 10) -> list[str]:
        """Scrape the latest tweet URLs from a user's profile page."""
        clean_name = username.lstrip("@")
        self.navigate_to(f"{TWITTER_BASE}/{clean_name}")
        self._page_delay()

        tweet_urls: list[str] = []
        try:
            # Wait for tweets to load
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'article[data-testid="tweet"]')
                )
            )

            articles = self.driver.find_elements(
                By.CSS_SELECTOR, 'article[data-testid="tweet"]'
            )

            for article in articles[:limit]:
                try:
                    # Find the timestamp link which contains the tweet URL
                    time_link = article.find_element(
                        By.CSS_SELECTOR, "a time"
                    ).find_element(By.XPATH, "..")
                    href = time_link.get_attribute("href")
                    if href and "/status/" in href:
                        tweet_urls.append(href)
                except NoSuchElementException:
                    continue

        except TimeoutException:
            logger.warning(f"Could not load tweets for {username}")

        logger.debug(f"Found {len(tweet_urls)} tweets for {username}")
        return tweet_urls

    def get_tweet_id_from_url(self, url: str) -> str:
        """Extract the tweet/status ID from a URL."""
        # URL pattern: https://x.com/user/status/1234567890
        parts = url.rstrip("/").split("/")
        for i, part in enumerate(parts):
            if part == "status" and i + 1 < len(parts):
                return parts[i + 1]
        return ""
