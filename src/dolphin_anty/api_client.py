import requests
from loguru import logger


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
        resp = requests.post(
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
    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug(f"GET {url} params={params}")
        resp = requests.get(url, headers=self.headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_data: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug(f"POST {url}")
        resp = requests.post(url, headers=self.headers, json=json_data, timeout=30)
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

        Endpoint: GET /browser_profiles/{profile_id}/start?automation=1[&headless=1]

        Returns dict with:
          - success: bool
          - automation.port  (Chrome debug port)
          - automation.wsEndpoint
        """
        logger.info(f"Starting Dolphin Anty profile {profile_id} (headless={headless})")
        params: dict[str, int] = {"automation": 1}
        if headless:
            params["headless"] = 1

        data = self._get(f"/browser_profiles/{profile_id}/start", params=params)

        if not data.get("success", False):
            raise RuntimeError(f"Failed to start profile {profile_id}: {data}")
        return data

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
