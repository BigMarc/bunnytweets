from __future__ import annotations

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
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class DolphinAntyClient:
    """Client for the Dolphin Anty Local API (http://localhost:3001/v1.0).

    The local API requires an authentication step before any profile operations.
    Call ``authenticate()`` (or pass ``api_token`` to the constructor) to perform
    ``POST /v1.0/auth/login-with-token`` which is mandatory per the Dolphin Anty
    docs – without it every subsequent request returns 401.
    """

    def __init__(self, host: str = "localhost", port: int = 3001, api_token: str = ""):
        self.base_url = f"http://{host}:{port}/v1.0"
        self.api_token = api_token
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        self._authenticated = False
        self._session = _retry_session()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def authenticate(self, token: str | None = None) -> bool:
        """Authenticate with the Dolphin Anty local API.

        Must be called before starting/stopping profiles. Uses
        ``POST /v1.0/auth/login-with-token`` as required by the docs.
        """
        token = token or self.api_token
        if not token:
            logger.warning(
                "No Dolphin Anty API token provided – skipping authentication. "
                "Set 'api_token' in settings.yaml or the DOLPHIN_ANTY_TOKEN env var."
            )
            return False

        url = f"{self.base_url}/auth/login-with-token"
        logger.debug(f"POST {url}")
        resp = self._session.post(
            url,
            headers={"Content-Type": "application/json"},
            json={"token": token},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success", False):
            logger.error(f"Dolphin Anty authentication failed: {data}")
            return False

        # The response may contain a session token for subsequent requests
        bearer = data.get("data", {}).get("token") or data.get("token")
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"

        self._authenticated = True
        logger.info("Dolphin Anty local API authenticated successfully")
        return True

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None, timeout: int = 30) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug(f"GET {url} params={params}")
        resp = self._session.get(url, headers=self.headers, params=params, timeout=timeout)
        if not resp.ok:
            logger.error(f"GET {path} failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_data: dict | None = None, timeout: int = 30) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug(f"POST {url} body={json_data}")
        resp = self._session.post(url, headers=self.headers, json=json_data, timeout=timeout)
        if not resp.ok:
            logger.error(f"POST {path} failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Profile operations
    # ------------------------------------------------------------------
    def list_profiles(self, page: int = 1, limit: int = 50) -> dict:
        """List browser profiles."""
        return self._get("/browser_profiles", params={"page": page, "limit": limit})

    def start_profile(self, profile_id: str, headless: bool = False) -> dict:
        """Start a browser profile with DevTools Protocol enabled.

        Endpoint: POST /browser_profiles/{profile_id}/start
        Body: {"automation": true[, "headless": true]}

        Returns a normalised dict::

            {"port": int, "ws_endpoint": str}

        so that ProfileManager can connect Selenium identically for both
        Dolphin Anty and GoLogin.
        """
        logger.info(f"Starting Dolphin Anty profile {profile_id} (headless={headless})")
        json_data: dict = {"automation": True}
        if headless:
            json_data["headless"] = True

        data = self._post(f"/browser_profiles/{profile_id}/start", json_data=json_data, timeout=120)

        if not data.get("success", False):
            raise RuntimeError(f"Failed to start profile {profile_id}: {data}")

        automation = data.get("automation", {})
        return {
            "port": automation.get("port"),
            "ws_endpoint": automation.get("wsEndpoint"),
        }

    def stop_profile(self, profile_id: str) -> dict:
        """Stop a running browser profile.

        Endpoint: GET /browser_profiles/{profile_id}/stop
        """
        logger.info(f"Stopping Dolphin Anty profile {profile_id}")
        return self._get(f"/browser_profiles/{profile_id}/stop")

    def get_profile(self, profile_id: str) -> dict:
        """Get details for a single profile."""
        return self._get(f"/browser_profiles/{profile_id}")

    def is_profile_running(self, profile_id: str) -> bool:
        """Check whether a profile's browser is currently running."""
        try:
            data = self.get_profile(profile_id)
            return data.get("data", {}).get("running", False)
        except Exception:
            return False
