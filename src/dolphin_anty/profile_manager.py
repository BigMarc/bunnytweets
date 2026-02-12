from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from loguru import logger

from src.dolphin_anty.api_client import DolphinAntyClient


class ProfileManager:
    """Manages Dolphin Anty browser profiles and provides Selenium WebDriver instances.

    Workflow per the Dolphin Anty docs:
      1. ``DolphinAntyClient.authenticate()`` – POST /auth/login-with-token
      2. ``start_profile()`` – POST /browser_profiles/{id}/start
         body: {"automation": true}, returns ``{ automation: { port, wsEndpoint } }``
      3. Connect Selenium to ``127.0.0.1:{port}`` via Chrome debugger address
      4. ``stop_profile()`` – GET /browser_profiles/{id}/stop
    """

    def __init__(self, client: DolphinAntyClient, browser_settings: dict | None = None):
        self.client = client
        self.browser_settings = browser_settings or {}
        self._drivers: dict[str, webdriver.Chrome] = {}

    def start_browser(self, profile_id: str) -> webdriver.Chrome:
        """Start a Dolphin Anty profile and connect Selenium to it.

        The profile is started via the local API which returns a Chrome
        DevTools debug port. Selenium then attaches to that port.
        """
        if profile_id in self._drivers:
            logger.debug(f"Driver already exists for profile {profile_id}, reusing")
            return self._drivers[profile_id]

        headless = self.browser_settings.get("headless", False)
        result = self.client.start_profile(profile_id, headless=headless)

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

        # Connect Selenium via the Chrome DevTools debug port
        options = ChromeOptions()
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")

        implicit_wait = self.browser_settings.get("implicit_wait", 10)
        page_load_timeout = self.browser_settings.get("page_load_timeout", 30)

        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(implicit_wait)
        driver.set_page_load_timeout(page_load_timeout)

        self._drivers[profile_id] = driver
        return driver

    def stop_browser(self, profile_id: str) -> None:
        """Disconnect Selenium and stop the Dolphin Anty profile.

        Important: we only call ``driver.quit()`` to release the Selenium
        session; the actual browser process is stopped by the Dolphin Anty
        ``/stop`` endpoint.
        """
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
