from __future__ import annotations

from urllib.parse import urlparse

import requests
from loguru import logger


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
        self.headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if api_token:
            self.headers["Authorization"] = f"Bearer {api_token}"
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
        self.headers["Authorization"] = f"Bearer {token}"
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
        Body: {"profileId": "<id>", "sync": true}
        Response: {"status": "success", "wsUrl": "ws://127.0.0.1:<port>/devtools/browser/<id>"}

        Returns a normalised dict::

            {"port": int, "ws_endpoint": str}

        so that ProfileManager can connect Selenium identically for both
        GoLogin and Dolphin Anty.
        """
        logger.info(f"Starting GoLogin profile {profile_id} (headless={headless})")
        json_data: dict = {"profileId": profile_id, "sync": True}

        url = f"{self.base_url}/browser/start-profile"
        logger.debug(f"POST {url} body={json_data}")
        resp = requests.post(url, headers=self.headers, json=json_data, timeout=120)
        if not resp.ok:
            logger.error(f"POST start-profile failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "success":
            raise RuntimeError(f"Failed to start GoLogin profile {profile_id}: {data}")

        ws_url = data.get("wsUrl", "")
        if not ws_url:
            raise RuntimeError(
                f"No wsUrl in GoLogin start-profile response for {profile_id}: {data}"
            )

        # Parse "ws://127.0.0.1:22739/devtools/browser/abc-123"
        parsed = urlparse(ws_url)
        port = parsed.port
        ws_endpoint = parsed.path  # e.g. "/devtools/browser/abc-123"

        if not port:
            raise RuntimeError(
                f"Could not extract debug port from wsUrl '{ws_url}' for profile {profile_id}"
            )

        return {"port": port, "ws_endpoint": ws_endpoint}

    def stop_profile(self, profile_id: str) -> dict:
        """Stop a running browser profile.

        Endpoint: POST http://localhost:36912/browser/stop-profile
        Body: {"profileId": "<id>"}
        """
        logger.info(f"Stopping GoLogin profile {profile_id}")
        url = f"{self.base_url}/browser/stop-profile"
        logger.debug(f"POST {url}")
        resp = requests.post(
            url,
            headers=self.headers,
            json={"profileId": profile_id},
            timeout=30,
        )
        if not resp.ok:
            logger.error(f"POST stop-profile failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Remote API – profile listing
    # ------------------------------------------------------------------
    def list_profiles(self, page: int = 1, limit: int = 50) -> dict:
        """List browser profiles via the GoLogin remote API.

        Endpoint: GET https://api.gologin.com/browser/v2
        Paginated (30 profiles per page).
        """
        url = f"{self.REMOTE_API_BASE}/browser/v2"
        logger.debug(f"GET {url} page={page}")
        resp = requests.get(
            url,
            headers=self.headers,
            params={"page": page},
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
        resp = requests.get(url, headers=self.headers, timeout=30)
        if not resp.ok:
            logger.error(
                f"GET /browser/{profile_id} failed ({resp.status_code}): {resp.text}"
            )
        resp.raise_for_status()
        return resp.json()
