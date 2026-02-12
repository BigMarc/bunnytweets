import time

import requests
from loguru import logger


class DolphinAntyClient:
    """Client for the Dolphin Anty Local API (http://localhost:3001/v1.0)."""

    def __init__(self, host: str = "localhost", port: int = 3001, api_token: str = ""):
        self.base_url = f"http://{host}:{port}/v1.0"
        self.headers = {}
        if api_token:
            self.headers["Authorization"] = f"Bearer {api_token}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug(f"GET {url}")
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
    def list_profiles(self, page: int = 1, limit: int = 50) -> dict:
        """List browser profiles."""
        return self._get("/browser_profiles", params={"page": page, "limit": limit})

    def start_profile(self, profile_id: str) -> dict:
        """Start a browser profile and return connection details.

        Returns dict with keys like:
          - automation.port  (debug port)
          - automation.wsEndpoint
        """
        logger.info(f"Starting Dolphin Anty profile {profile_id}")
        data = self._get(f"/browser_profiles/{profile_id}/start?automation=1")
        if not data.get("success", True):
            raise RuntimeError(f"Failed to start profile {profile_id}: {data}")
        return data

    def stop_profile(self, profile_id: str) -> dict:
        """Stop a running browser profile."""
        logger.info(f"Stopping Dolphin Anty profile {profile_id}")
        return self._get(f"/browser_profiles/{profile_id}/stop")

    def get_profile(self, profile_id: str) -> dict:
        """Get details for a single profile."""
        return self._get(f"/browser_profiles/{profile_id}")

    def is_profile_running(self, profile_id: str) -> bool:
        """Check whether a profile's browser is currently running."""
        try:
            data = self.get_profile(profile_id)
            # The 'running' field or check via start endpoint
            return data.get("data", {}).get("running", False)
        except Exception:
            return False
