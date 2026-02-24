"""Resolve a ChromeDriver binary matching the Chrome version on a running debug port.

The Chrome instance is already running (started by GoLogin or Dolphin Anty).
We query its version via the Chrome DevTools Protocol, then ensure the
correct ChromeDriver is available before Selenium tries to create a session.
"""

from __future__ import annotations

import re

import requests
from loguru import logger

# Module-level cache: chrome_major -> (chromedriver_path, chrome_major)
_resolve_cache: dict[str, tuple[str | None, str | None]] = {}


def get_chrome_version_from_cdp(port: int, timeout: float = 5.0) -> str | None:
    """Query a running Chrome's /json/version endpoint.

    Returns the full version string (e.g. ``'142.0.7444.175'``),
    or ``None`` on failure.
    """
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # "Browser" field looks like "Chrome/142.0.7444.175" or "Orbita/142.0.7444.175"
        browser_str = data.get("Browser", "")
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", browser_str)
        if match:
            return match.group(1)
        logger.warning(f"Could not parse version from CDP Browser field: {browser_str!r}")
        return None
    except Exception as exc:
        logger.warning(f"Failed to query Chrome version via CDP on port {port}: {exc}")
        return None


def resolve_chromedriver(port: int) -> tuple[str | None, str | None]:
    """Detect Chrome version on *port* and return a matching ChromeDriver.

    Returns ``(chromedriver_path, chrome_major_version)`` where either value
    may be ``None``:

    * Both set — use ``Service(executable_path=path)``
    * Only major version — set ``options.browser_version = major`` so
      Selenium Manager downloads the right driver automatically
    * Both ``None`` — detection failed; fall back to system ChromeDriver
    """
    full_version = get_chrome_version_from_cdp(port)
    if not full_version:
        return None, None

    major = full_version.split(".")[0]
    logger.info(f"Detected Chrome {full_version} (major {major}) on port {port}")

    # Return cached result if we already resolved this major version
    if major in _resolve_cache:
        cached = _resolve_cache[major]
        logger.debug(f"Using cached ChromeDriver for Chrome {major}")
        return cached

    chromedriver_path = _try_webdriver_manager(full_version, major)
    if chromedriver_path:
        _resolve_cache[major] = (chromedriver_path, major)
        return chromedriver_path, major

    # Fallback: let Selenium Manager handle it via browser_version
    _resolve_cache[major] = (None, major)
    return None, major


def _try_webdriver_manager(full_version: str, major: str) -> str | None:
    """Download ChromeDriver via webdriver-manager (if installed).

    Returns the executable path, or ``None`` if the library is missing
    or the download fails.
    """
    try:
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        logger.debug("webdriver-manager not installed, skipping")
        return None

    # Try exact version first, then major-only
    for version_str in (full_version, major):
        try:
            path = ChromeDriverManager(driver_version=version_str).install()
            logger.debug(f"webdriver-manager resolved ChromeDriver at: {path}")
            return path
        except Exception as exc:
            logger.debug(f"webdriver-manager failed for version {version_str}: {exc}")

    return None
