from __future__ import annotations

import threading
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
        # GoLogin's local API is single-threaded — serialize all requests
        # to avoid timeouts caused by concurrent calls queuing up.
        self._api_lock = threading.Lock()
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
    def _post_local(self, url: str, json_data: dict, timeout=30) -> requests.Response:
        """Send a POST to GoLogin's local API, serialized through the lock.

        GoLogin's local HTTP server is single-threaded — concurrent requests
        queue up and cause timeouts.  This method ensures only one request
        is in-flight at a time.
        """
        with self._api_lock:
            return self._session.post(
                url, headers=self._post_headers, json=json_data,
                timeout=timeout if isinstance(timeout, tuple) else (10, timeout),
            )

    def start_profile(self, profile_id: str, headless: bool = False) -> dict:
        """Start a browser profile and wait for its debug port.

        Uses ``sync=True`` so GoLogin blocks until the browser is fully
        ready and returns the ``wsUrl`` in a single response — no polling.

        Returns a normalised dict ``{"port": int, "ws_endpoint": str}``
        so ProfileManager can connect via CDP.
        """
        logger.info(f"Starting GoLogin profile {profile_id} (headless={headless})")
        url = f"{self.base_url}/browser/start-profile"
        json_data: dict = {"profileId": profile_id, "sync": True}

        resp = self._post_local(url, json_data, timeout=120)
        if not resp.ok:
            logger.error(f"POST start-profile failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
        data = resp.json()

        ws_url = data.get("wsUrl", "")
        if not ws_url:
            raise RuntimeError(
                f"GoLogin start-profile returned no wsUrl for {profile_id}. "
                f"Response: {data}"
            )

        result = self._parse_ws_url(ws_url)
        logger.info(f"Profile {profile_id} ready (port={result.get('port')})")
        return result

    def start_all_profiles(self, profile_ids: list[str]) -> dict[str, dict]:
        """Start multiple profiles sequentially via ``sync=True`` calls.

        Each call blocks until the profile is ready — no polling phase
        needed.  GoLogin's local API is single-threaded, so there is no
        benefit to fire-and-forget anyway.

        Returns ``{profile_id: {"port": int, "ws_endpoint": str}}`` for
        profiles that started successfully.  Failed profiles are logged
        and omitted from the result.
        """
        results: dict[str, dict] = {}
        logger.info(f"Starting {len(profile_ids)} GoLogin profiles (sync=true)...")
        for pid in profile_ids:
            try:
                result = self.start_profile(pid)
                results[pid] = result
            except Exception as exc:
                logger.error(f"Failed to start profile {pid}: {exc}")
        logger.info(
            f"Profile startup complete: {len(results)}/{len(profile_ids)} ready"
        )
        return results

    def _parse_ws_url(self, ws_url: str) -> dict:
        """Extract port and ws_endpoint from a GoLogin wsUrl string."""
        parsed = urlparse(ws_url)
        return {"port": parsed.port, "ws_endpoint": parsed.path}

    def stop_profile(self, profile_id: str) -> dict:
        """Stop a running browser profile.

        Endpoint: POST http://localhost:36912/browser/stop-profile
        Body: {"profileId": "<id>"}
        Response: 204 No Content (empty body on success).
        """
        logger.info(f"Stopping GoLogin profile {profile_id}")
        url = f"{self.base_url}/browser/stop-profile"
        resp = self._post_local(url, {"profileId": profile_id})
        if not resp.ok:
            logger.error(f"POST stop-profile failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
        # stop-profile returns 204 No Content on success
        if resp.status_code == 204 or not resp.content:
            return {"status": "success"}
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
