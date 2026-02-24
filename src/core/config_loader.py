from __future__ import annotations

import os
import shutil
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

        resolved_settings = settings_p if settings_p.is_absolute() else self.base_dir / settings_path
        # Auto-copy settings.yaml.example on first run if settings.yaml is missing
        if not resolved_settings.exists():
            example = resolved_settings.with_suffix(".yaml.example")
            if not example.exists():
                example = resolved_settings.parent / (resolved_settings.stem + ".yaml.example")
            if example.exists():
                resolved_settings.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(example, resolved_settings)

        self.settings = self._load_yaml(resolved_settings)
        self.accounts_cfg = self._load_yaml(
            accounts_p if accounts_p.is_absolute() else self.base_dir / accounts_path,
            create_empty=True,
        )
        self._apply_env_overrides()

    # ------------------------------------------------------------------
    @staticmethod
    def _load_yaml(path: Path, *, create_empty: bool = False) -> dict:
        if not path.exists():
            if create_empty:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("accounts: []\n", encoding="utf-8")
                return {"accounts": []}
            raise FileNotFoundError(
                f"Configuration file not found: {path}. "
                f"Copy the .example file and fill in your details."
            )
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:
            raise ValueError(
                f"Failed to parse {path}: {exc}"
            ) from exc

    def _apply_env_overrides(self) -> None:
        """Override settings with environment variables when present."""
        # Browser provider
        provider = os.getenv("BROWSER_PROVIDER")
        if provider:
            self.settings["browser_provider"] = provider

        # Dolphin Anty overrides
        token = os.getenv("DOLPHIN_ANTY_TOKEN")
        if token:
            self.settings.setdefault("dolphin_anty", {})["api_token"] = token

        host = os.getenv("DOLPHIN_ANTY_HOST")
        if host:
            self.settings.setdefault("dolphin_anty", {})["host"] = host

        port = os.getenv("DOLPHIN_ANTY_PORT")
        if port:
            try:
                self.settings.setdefault("dolphin_anty", {})["port"] = int(port)
            except ValueError:
                pass  # ignore non-numeric port env var

        # GoLogin overrides
        gl_token = os.getenv("GOLOGIN_TOKEN")
        if gl_token:
            self.settings.setdefault("gologin", {})["api_token"] = gl_token

        gl_host = os.getenv("GOLOGIN_HOST")
        if gl_host:
            self.settings.setdefault("gologin", {})["host"] = gl_host

        gl_port = os.getenv("GOLOGIN_PORT")
        if gl_port:
            try:
                self.settings.setdefault("gologin", {})["port"] = int(gl_port)
            except ValueError:
                pass  # ignore non-numeric port env var

        # Google Drive
        creds = os.getenv("GOOGLE_CREDENTIALS_FILE")
        if creds:
            self.settings.setdefault("google_drive", {})["credentials_file"] = creds

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
    def browser_provider(self) -> str:
        """Return the configured browser provider: 'gologin' (default) or 'dolphin_anty'."""
        return self.settings.get("browser_provider", "gologin")

    @property
    def gologin(self) -> dict:
        return self.settings.get("gologin", {})

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
    def discord(self) -> dict:
        return self.settings.get("discord", {})

    @property
    def database_path(self) -> str:
        return self.settings.get("database", {}).get(
            "path", "data/database/automation.db"
        )

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to the project root."""
        return self.base_dir / relative
