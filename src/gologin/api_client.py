from __future__ import annotations

import threading
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

        Returns a normalised dict ``{"port": int, "ws_endpoint": str}``
        so ProfileManager can connect Selenium.

        All GoLogin local API calls go through ``_post_local`` which
        serializes them to avoid overloading the single-threaded server.
        """
        logger.info(f"Starting GoLogin profile {profile_id} (headless={headless})")
        url = f"{self.base_url}/browser/start-profile"
        json_data: dict = {"profileId": profile_id, "sync": False}

        # Step 1 — send the start command (serialized).
        try:
            resp = self._post_local(url, json_data)
            if not resp.ok:
                logger.error(
                    f"POST start-profile failed ({resp.status_code}): {resp.text}"
                )
            resp.raise_for_status()
            data = resp.json()

            # Profile may already be running — check for wsUrl.
            if data.get("status") == "success":
                ws_url = data.get("wsUrl", "")
                if ws_url:
                    result = self._parse_ws_url(ws_url)
                    if result.get("port"):
                        logger.info(
                            f"Profile {profile_id} already running "
                            f"(port={result['port']})"
                        )
                        return result
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as exc:
            logger.warning(
                f"Start command for {profile_id} timed out: {exc}. "
                f"Profile may still be starting..."
            )

        # Step 2 — poll until wsUrl is available (serialized per call).
        max_polls = 15
        poll_interval = 5  # seconds
        initial_delay = 3

        logger.info(
            f"Polling for profile {profile_id} readiness "
            f"(every {poll_interval}s, up to ~{initial_delay + max_polls * poll_interval}s)..."
        )
        time.sleep(initial_delay)

        for poll in range(1, max_polls + 1):
            result = self.is_profile_running(profile_id)
            if result and result.get("port"):
                logger.info(
                    f"Profile {profile_id} ready "
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

    def start_all_profiles(self, profile_ids: list[str]) -> dict[str, dict]:
        """Start multiple profiles efficiently via serialized API calls.

        Phase 1 — fire ``sync=False`` start commands one by one (each ~2-5s).
                   All profiles begin opening in GoLogin simultaneously.
        Phase 2 — poll each profile one by one for its debug port.
                   Most profiles are already ready by the time we poll.

        Returns ``{profile_id: {"port": int, "ws_endpoint": str}}`` for
        profiles that started successfully.  Failed profiles are logged
        and omitted from the result.
        """
        url = f"{self.base_url}/browser/start-profile"
        results: dict[str, dict] = {}
        pending: list[str] = []

        # Phase 1 — fire start commands, one at a time.
        logger.info(f"Phase 1: Sending start commands for {len(profile_ids)} profiles...")
        for pid in profile_ids:
            json_data = {"profileId": pid, "sync": False}
            try:
                resp = self._post_local(url, json_data)
                if resp.ok:
                    data = resp.json()
                    ws_url = data.get("wsUrl", "")
                    if data.get("status") == "success" and ws_url:
                        result = self._parse_ws_url(ws_url)
                        if result.get("port"):
                            results[pid] = result
                            logger.info(
                                f"  {pid[:12]}... already running "
                                f"(port={result['port']})"
                            )
                            continue
                    pending.append(pid)
                    logger.info(f"  {pid[:12]}... start command sent")
                else:
                    pending.append(pid)
                    logger.warning(
                        f"  {pid[:12]}... start returned {resp.status_code}"
                    )
            except Exception as exc:
                pending.append(pid)
                logger.warning(f"  {pid[:12]}... start failed: {exc}")

        if not pending:
            return results

        # Phase 2 — poll pending profiles for readiness.
        logger.info(
            f"Phase 2: Waiting for {len(pending)} profiles to become ready..."
        )
        max_rounds = 15
        poll_interval = 5  # seconds

        time.sleep(5)  # initial grace period

        for round_num in range(1, max_rounds + 1):
            still_pending = []
            for pid in pending:
                info = self.is_profile_running(pid)
                if info and info.get("port"):
                    results[pid] = info
                    logger.info(
                        f"  {pid[:12]}... ready "
                        f"(round {round_num}/{max_rounds}, "
                        f"port={info['port']})"
                    )
                else:
                    still_pending.append(pid)

            pending = still_pending
            if not pending:
                break

            logger.debug(
                f"  {len(pending)} profiles still pending "
                f"(round {round_num}/{max_rounds})"
            )
            if round_num < max_rounds:
                time.sleep(poll_interval)

        for pid in pending:
            logger.error(
                f"  {pid[:12]}... did NOT become ready after "
                f"{max_rounds * poll_interval}s"
            )

        logger.info(
            f"Profile startup complete: {len(results)} ready, "
            f"{len(pending)} failed"
        )
        return results

    def _parse_ws_url(self, ws_url: str) -> dict:
        """Extract port and ws_endpoint from a GoLogin wsUrl string."""
        parsed = urlparse(ws_url)
        return {"port": parsed.port, "ws_endpoint": parsed.path}

    def is_profile_running(self, profile_id: str) -> dict | None:
        """Check whether a profile is already running in GoLogin.

        Calls ``start-profile`` with ``sync=false`` (serialized through
        the API lock).  Returns a normalised ``{"port": int, "ws_endpoint": str}``
        dict if running, else ``None``.
        """
        try:
            url = f"{self.base_url}/browser/start-profile"
            resp = self._post_local(
                url,
                {"profileId": profile_id, "sync": False},
                timeout=15,
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
        resp = self._post_local(url, {"profileId": profile_id})
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
