from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from loguru import logger

from src.dolphin_anty.chromedriver_resolver import resolve_chromedriver


class ProfileManager:
    """Manages anti-detect browser profiles and provides Selenium WebDriver instances.

    Works with any browser provider client (GoLogin or Dolphin Anty) that
    implements the following interface:

        - ``start_profile(profile_id, headless) -> {"port": int, "ws_endpoint": str}``
        - ``stop_profile(profile_id) -> dict``

    Workflow:
      1. Provider client authenticates (provider-specific).
      2. ``start_profile()`` – starts a browser profile, returns debug port.
      3. Connect Selenium to ``127.0.0.1:{port}`` via Chrome debugger address.
      4. ``stop_profile()`` – stops the browser profile.
    """

    def __init__(self, client, browser_settings: dict | None = None):
        self.client = client
        self.browser_settings = browser_settings or {}
        self._drivers: dict[str, webdriver.Chrome] = {}

    def start_browser(self, profile_id: str) -> webdriver.Chrome:
        """Start a browser profile and connect Selenium to it.

        The profile is started via the provider's local API which returns a
        Chrome DevTools debug port. Selenium then attaches to that port.
        """
        if profile_id in self._drivers:
            logger.debug(f"Driver already exists for profile {profile_id}, reusing")
            return self._drivers[profile_id]

        headless = self.browser_settings.get("headless", False)
        result = self.client.start_profile(profile_id, headless=headless)

        port = result.get("port")
        ws_endpoint = result.get("ws_endpoint")

        if not port:
            raise RuntimeError(
                f"No debug port returned for profile {profile_id}. Response: {result}"
            )

        logger.info(
            f"Profile {profile_id} started – debug port={port}, ws={ws_endpoint}"
        )

        # Resolve a ChromeDriver matching the browser's Chrome version
        chromedriver_path, chrome_major = resolve_chromedriver(port)

        options = ChromeOptions()
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")

        if chrome_major:
            options.browser_version = chrome_major

        service_kwargs: dict = {}
        if chromedriver_path:
            service_kwargs["executable_path"] = chromedriver_path
            logger.debug(f"Using resolved ChromeDriver: {chromedriver_path}")
        service = ChromeService(**service_kwargs)

        implicit_wait = self.browser_settings.get("implicit_wait", 10)
        page_load_timeout = self.browser_settings.get("page_load_timeout", 30)

        driver = webdriver.Chrome(options=options, service=service)
        driver.implicitly_wait(implicit_wait)
        driver.set_page_load_timeout(page_load_timeout)

        self._drivers[profile_id] = driver
        return driver

    def stop_browser(self, profile_id: str) -> None:
        """Disconnect Selenium and stop the browser profile.

        We call ``driver.quit()`` to release the Selenium session, then
        use the provider's stop endpoint to close the browser process.
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
            logger.warning(f"Error stopping profile {profile_id}: {exc}")

    def get_driver(self, profile_id: str) -> webdriver.Chrome | None:
        return self._drivers.get(profile_id)

    def stop_all(self) -> None:
        """Stop all running browser profiles."""
        for pid in list(self._drivers.keys()):
            self.stop_browser(pid)
