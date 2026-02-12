import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class ConfigLoader:
    """Loads and merges settings.yaml, accounts.yaml, and environment variables."""

    def __init__(
        self,
        settings_path: str = "config/settings.yaml",
        accounts_path: str = "config/accounts.yaml",
    ):
        load_dotenv()
        self.base_dir = Path(__file__).resolve().parent.parent.parent
        settings_p = Path(settings_path)
        accounts_p = Path(accounts_path)
        self.settings = self._load_yaml(
            settings_p if settings_p.is_absolute() else self.base_dir / settings_path
        )
        self.accounts_cfg = self._load_yaml(
            accounts_p if accounts_p.is_absolute() else self.base_dir / accounts_path
        )
        self._apply_env_overrides()

    # ------------------------------------------------------------------
    @staticmethod
    def _load_yaml(path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {path}. "
                f"Copy the .example file and fill in your details."
            )
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _apply_env_overrides(self) -> None:
        """Override settings with environment variables when present."""
        token = os.getenv("DOLPHIN_ANTY_TOKEN")
        if token:
            self.settings.setdefault("dolphin_anty", {})["api_token"] = token

        creds = os.getenv("GOOGLE_CREDENTIALS_FILE")
        if creds:
            self.settings.setdefault("google_drive", {})["credentials_file"] = creds

        host = os.getenv("DOLPHIN_ANTY_HOST")
        if host:
            self.settings.setdefault("dolphin_anty", {})["host"] = host

        port = os.getenv("DOLPHIN_ANTY_PORT")
        if port:
            self.settings.setdefault("dolphin_anty", {})["port"] = int(port)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    @property
    def accounts(self) -> list[dict[str, Any]]:
        return self.accounts_cfg.get("accounts", [])

    @property
    def enabled_accounts(self) -> list[dict[str, Any]]:
        return [a for a in self.accounts if a.get("enabled", False)]

    @property
    def timezone(self) -> str:
        return self.settings.get("timezone", "America/New_York")

    @property
    def dolphin_anty(self) -> dict:
        return self.settings.get("dolphin_anty", {})

    @property
    def google_drive(self) -> dict:
        return self.settings.get("google_drive", {})

    @property
    def browser(self) -> dict:
        return self.settings.get("browser", {})

    @property
    def delays(self) -> dict:
        return self.settings.get("delays", {})

    @property
    def error_handling(self) -> dict:
        return self.settings.get("error_handling", {})

    @property
    def logging(self) -> dict:
        return self.settings.get("logging", {})

    @property
    def database_path(self) -> str:
        return self.settings.get("database", {}).get(
            "path", "data/database/automation.db"
        )

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to the project root."""
        return self.base_dir / relative
