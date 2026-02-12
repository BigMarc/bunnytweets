import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from loguru import logger

from src.dolphin_anty.api_client import DolphinAntyClient


class ProfileManager:
    """Manages Dolphin Anty browser profiles and provides Selenium WebDriver instances."""

    def __init__(self, client: DolphinAntyClient, browser_settings: dict | None = None):
        self.client = client
        self.browser_settings = browser_settings or {}
        self._drivers: dict[str, webdriver.Chrome] = {}

    def start_browser(self, profile_id: str) -> webdriver.Chrome:
        """Start a Dolphin Anty profile and connect Selenium to it."""
        if profile_id in self._drivers:
            logger.debug(f"Driver already exists for profile {profile_id}, reusing")
            return self._drivers[profile_id]

        result = self.client.start_profile(profile_id)
        automation = result.get("automation", {})
        port = automation.get("port")
        ws_endpoint = automation.get("wsEndpoint")

        if not port:
            raise RuntimeError(
                f"No debug port returned for profile {profile_id}. Response: {result}"
            )

        logger.info(
            f"Profile {profile_id} started – debug port={port}, ws={ws_endpoint}"
        )

        options = ChromeOptions()
        options.debugger_address = f"127.0.0.1:{port}"

        implicit_wait = self.browser_settings.get("implicit_wait", 10)
        page_load_timeout = self.browser_settings.get("page_load_timeout", 30)

        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(implicit_wait)
        driver.set_page_load_timeout(page_load_timeout)

        self._drivers[profile_id] = driver
        return driver

    def stop_browser(self, profile_id: str) -> None:
        """Quit the Selenium driver and stop the Dolphin Anty profile."""
        driver = self._drivers.pop(profile_id, None)
        if driver:
            try:
                driver.quit()
            except Exception as exc:
                logger.warning(f"Error quitting driver for {profile_id}: {exc}")

        try:
            self.client.stop_profile(profile_id)
        except Exception as exc:
            logger.warning(f"Error stopping Dolphin profile {profile_id}: {exc}")

    def get_driver(self, profile_id: str) -> webdriver.Chrome | None:
        return self._drivers.get(profile_id)

    def stop_all(self) -> None:
        """Stop all running browser profiles."""
        for pid in list(self._drivers.keys()):
            self.stop_browser(pid)
