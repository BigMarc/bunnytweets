from __future__ import annotations

import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger


def _retry_session() -> requests.Session:
    """Create a requests Session with automatic retry on transient errors."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class GoLoginClient:
    """Client for the GoLogin Local REST API (default port 36912).

    GoLogin's desktop app exposes a local HTTP API for starting/stopping
    browser profiles. Authentication uses a static Bearer token obtained
    from the GoLogin dashboard (Settings > API).

    Local API docs: https://documenter.getpostman.com/view/21126834/Uz5GnvaL
    """

    REMOTE_API_BASE = "https://api.gologin.com"

    def __init__(self, host: str = "localhost", port: int = 36912, api_token: str = ""):
        self.base_url = f"http://{host}:{port}"
        self.api_token = api_token
        self._session = _retry_session()
        # POST headers for local API (start/stop profile) — needs Content-Type
        self._post_headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        # GET headers for remote API (list/get profiles) — no Content-Type
        self._get_headers: dict[str, str] = {}
        if api_token:
            self._post_headers["Authorization"] = f"Bearer {api_token}"
            self._get_headers["Authorization"] = f"Bearer {api_token}"
        self._authenticated = False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def authenticate(self, token: str | None = None) -> bool:
        """Configure the Bearer token for GoLogin API requests.

        Unlike Dolphin Anty, GoLogin does not require a login-with-token
        handshake. The API token from the dashboard is used directly as
        a Bearer token in every request.
        """
        token = token or self.api_token
        if not token:
            logger.warning(
                "No GoLogin API token provided – skipping authentication. "
                "Set 'api_token' in settings.yaml or the GOLOGIN_TOKEN env var."
            )
            return False

        self.api_token = token
        self._post_headers["Authorization"] = f"Bearer {token}"
        self._get_headers["Authorization"] = f"Bearer {token}"
        self._authenticated = True
        logger.info("GoLogin API configured with bearer token")
        return True

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    # ------------------------------------------------------------------
    # Local API – profile lifecycle
    # ------------------------------------------------------------------
    def start_profile(self, profile_id: str, headless: bool = False) -> dict:
        """Start a browser profile via GoLogin desktop app.

        Endpoint: POST http://localhost:36912/browser/start-profile
        Body: {"profileId": "<id>", "sync": false}
        Response: {"status": "success", "wsUrl": "ws://127.0.0.1:<port>/devtools/browser/<id>"}

        Returns a normalised dict::

            {"port": int, "ws_endpoint": str}

        so that ProfileManager can connect Selenium identically for both
        GoLogin and Dolphin Anty.

        Uses a fire-and-forget approach: sends ``sync=False`` to trigger the
        profile launch (returns immediately), then polls until GoLogin
        reports the debug port via ``wsUrl``.  This avoids blocking HTTP
        calls that deadlock when multiple profiles start concurrently.
        """
        logger.info(f"Starting GoLogin profile {profile_id} (headless={headless})")
        url = f"{self.base_url}/browser/start-profile"

        # Phase 1: Fire-and-forget — tell GoLogin to start the profile.
        # sync=False returns immediately; the profile opens in the background.
        json_data: dict = {"profileId": profile_id, "sync": False}
        try:
            resp = self._session.post(
                url, headers=self._post_headers, json=json_data,
                timeout=(10, 30),
            )
            if not resp.ok:
                logger.error(
                    f"POST start-profile failed ({resp.status_code}): {resp.text}"
                )
            resp.raise_for_status()
            data = resp.json()

            # If GoLogin already had this profile running, we may get
            # the wsUrl immediately — no need to poll.
            if data.get("status") == "success":
                ws_url = data.get("wsUrl", "")
                if ws_url:
                    result = self._parse_ws_url(ws_url)
                    if result.get("port"):
                        logger.info(
                            f"Profile {profile_id} was already running "
                            f"(port={result['port']})"
                        )
                        return result

        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as exc:
            # GoLogin may be busy — the start command may still have been
            # accepted.  Fall through to polling.
            logger.warning(
                f"GoLogin start-profile request for {profile_id} "
                f"timed out: {exc}. Will poll for readiness..."
            )

        # Phase 2: Poll until the profile is ready and wsUrl is available.
        max_polls = 12
        poll_interval = 8  # seconds between polls
        initial_delay = 5  # seconds before first poll

        logger.info(
            f"Waiting for profile {profile_id} to become ready "
            f"(polling every {poll_interval}s, up to ~{initial_delay + max_polls * poll_interval}s)..."
        )
        time.sleep(initial_delay)

        for poll in range(1, max_polls + 1):
            result = self.is_profile_running(profile_id)
            if result and result.get("port"):
                logger.info(
                    f"Profile {profile_id} ready after ~"
                    f"{initial_delay + poll * poll_interval}s "
                    f"(poll {poll}/{max_polls}, port={result['port']})"
                )
                return result

            logger.debug(
                f"Profile {profile_id} not ready yet "
                f"(poll {poll}/{max_polls})"
            )
            if poll < max_polls:
                time.sleep(poll_interval)

        raise RuntimeError(
            f"GoLogin profile {profile_id} did not become ready after "
            f"~{initial_delay + max_polls * poll_interval}s of polling"
        )

    def _parse_ws_url(self, ws_url: str) -> dict:
        """Extract port and ws_endpoint from a GoLogin wsUrl string."""
        parsed = urlparse(ws_url)
        return {"port": parsed.port, "ws_endpoint": parsed.path}

    def is_profile_running(self, profile_id: str) -> dict | None:
        """Check whether a profile is already running in GoLogin.

        Calls ``start-profile`` with ``sync=false`` which returns
        immediately for running profiles.  Returns a normalised
        ``{"port": int, "ws_endpoint": str}`` dict if running, else None.
        """
        try:
            url = f"{self.base_url}/browser/start-profile"
            resp = self._session.post(
                url,
                headers=self._post_headers,
                json={"profileId": profile_id, "sync": False},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                ws_url = data.get("wsUrl", "")
                if data.get("status") == "success" and ws_url:
                    return self._parse_ws_url(ws_url)
        except Exception:
            pass
        return None

    def stop_profile(self, profile_id: str) -> dict:
        """Stop a running browser profile.

        Endpoint: POST http://localhost:36912/browser/stop-profile
        Body: {"profileId": "<id>"}
        """
        logger.info(f"Stopping GoLogin profile {profile_id}")
        url = f"{self.base_url}/browser/stop-profile"
        logger.debug(f"POST {url}")
        resp = self._session.post(
            url,
            headers=self._post_headers,
            json={"profileId": profile_id},
            timeout=30,
        )
        if not resp.ok:
            logger.error(f"POST stop-profile failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
        # GoLogin may return an empty body on success
        try:
            return resp.json()
        except Exception:
            return {"status": "success"}

    # ------------------------------------------------------------------
    # Remote API – profile listing
    # ------------------------------------------------------------------
    def list_profiles(self) -> dict:
        """List browser profiles via the GoLogin remote API.

        Endpoint: GET https://api.gologin.com/browser/v2
        """
        url = f"{self.REMOTE_API_BASE}/browser/v2"
        logger.debug(f"GET {url}")
        resp = self._session.get(
            url,
            headers=self._get_headers,
            timeout=30,
        )
        if not resp.ok:
            logger.error(f"GET /browser/v2 failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
        return resp.json()

    def get_profile(self, profile_id: str) -> dict:
        """Retrieve detailed information about a specific profile.

        Endpoint: GET https://api.gologin.com/browser/{id}
        """
        url = f"{self.REMOTE_API_BASE}/browser/{profile_id}"
        logger.debug(f"GET {url}")
        resp = self._session.get(url, headers=self._get_headers, timeout=30)
        if not resp.ok:
            logger.error(
                f"GET /browser/{profile_id} failed ({resp.status_code}): {resp.text}"
            )
        resp.raise_for_status()
        return resp.json()
