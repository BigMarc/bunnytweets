from __future__ import annotations

import time

import requests
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
            existing = self._drivers[profile_id]
            try:
                existing.title  # quick liveness check
                logger.debug(f"Driver already exists for profile {profile_id}, reusing")
                return existing
            except Exception:
                logger.warning(f"Stale driver for profile {profile_id}, replacing")
                try:
                    existing.quit()
                except Exception:
                    pass
                del self._drivers[profile_id]

        # Fast path: if the profile is already running in the browser
        # provider, grab its debug port without restarting / syncing.
        result = None
        if hasattr(self.client, "is_profile_running"):
            try:
                running_info = self.client.is_profile_running(profile_id)
                if running_info and isinstance(running_info, dict) and running_info.get("port"):
                    result = running_info
                    logger.info(
                        f"Profile {profile_id} already running – "
                        f"attaching to port {result['port']}"
                    )
            except Exception:
                pass

        # Normal path: ask the provider to start (or return running port)
        if result is None:
            headless = self.browser_settings.get("headless", False)
            result = self.client.start_profile(profile_id, headless=headless)

        port = result.get("port")
        ws_endpoint = result.get("ws_endpoint")

        if not port:
            raise RuntimeError(
                f"No debug port returned for profile {profile_id}. Response: {result}"
            )

        logger.info(
            f"Profile {profile_id} ready – debug port={port}, ws={ws_endpoint}"
        )

        # Verify the browser is actually responsive on the debug port
        # before attempting Selenium attachment (CDP health check).
        self._wait_for_cdp(port, profile_id)

        # Resolve a ChromeDriver matching the browser's Chrome version.
        # If anything fails after start_profile(), stop the orphaned profile.
        try:
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
        except Exception:
            # Profile is running but Selenium couldn't attach — clean up
            try:
                self.client.stop_profile(profile_id)
            except Exception as stop_exc:
                logger.warning(f"Cleanup: failed to stop profile {profile_id}: {stop_exc}")
            raise

        self._drivers[profile_id] = driver
        return driver

    @staticmethod
    def _wait_for_cdp(port: int, profile_id: str, timeout: int = 30) -> None:
        """Wait until the browser's CDP endpoint responds on *port*.

        Probes ``GET http://127.0.0.1:{port}/json/version`` repeatedly.
        This confirms the browser process is fully started and accepting
        DevTools Protocol connections before Selenium tries to attach.
        """
        url = f"http://127.0.0.1:{port}/json/version"
        deadline = time.monotonic() + timeout
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            try:
                resp = requests.get(url, timeout=3)
                if resp.ok:
                    logger.debug(
                        f"CDP on port {port} responding "
                        f"(profile {profile_id}, attempt {attempt})"
                    )
                    return
            except Exception:
                pass
            time.sleep(2)

        logger.warning(
            f"CDP on port {port} did not respond within {timeout}s "
            f"(profile {profile_id}) — Selenium may fail to attach"
        )

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

    def cleanup_all_profiles(self, profile_ids: list[str]) -> None:
        """Pre-flight cleanup: stop all configured profiles regardless of _drivers state.

        After a crash or SIGKILL, _drivers is empty but GoLogin may still have
        orphaned browser processes running from the previous session.  This method
        sends a stop request for every configured profile ID to ensure a clean slate.
        """
        if not profile_ids:
            return
        logger.info(f"Pre-flight cleanup: stopping {len(profile_ids)} configured profile(s)")
        for pid in profile_ids:
            try:
                self.client.stop_profile(pid)
                logger.debug(f"Pre-flight: stopped profile {pid}")
            except Exception as exc:
                # Expected for profiles that aren't running — not an error
                logger.debug(f"Pre-flight: profile {pid} stop skipped ({exc})")
        # Clear any stale driver references
        self._drivers.clear()

    @staticmethod
    def _wait_for_cdp(port: int, profile_id: str, timeout: int = 30) -> None:
        """Wait until the browser's CDP endpoint responds on *port*.

        Probes ``GET http://127.0.0.1:{port}/json/version`` repeatedly.
        This confirms the browser process is fully started and accepting
        DevTools Protocol connections before Selenium tries to attach.
        """
        url = f"http://127.0.0.1:{port}/json/version"
        deadline = time.monotonic() + timeout
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            try:
                resp = requests.get(url, timeout=3)
                if resp.ok:
                    logger.debug(
                        f"CDP on port {port} responding "
                        f"(profile {profile_id}, attempt {attempt})"
                    )
                    return
            except Exception:
                pass
            time.sleep(2)

        logger.warning(
            f"CDP on port {port} did not respond within {timeout}s "
            f"(profile {profile_id}) — Selenium may fail to attach"
        )
