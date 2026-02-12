"""Tests for ConfigLoader."""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.core.config_loader import ConfigLoader


@pytest.fixture
def config_dir(tmp_path):
    settings = {
        "timezone": "America/New_York",
        "browser_provider": "gologin",
        "gologin": {"host": "localhost", "port": 36912},
        "dolphin_anty": {"host": "localhost", "port": 3001},
        "database": {"path": "data/database/test.db"},
        "logging": {"level": "DEBUG"},
        "delays": {"action_min": 1, "action_max": 2},
    }
    accounts = {
        "accounts": [
            {
                "name": "TestAcct",
                "enabled": True,
                "twitter": {
                    "username": "@test",
                    "profile_id": "p123",
                },
                "google_drive": {"folder_id": "f1"},
                "posting": {"enabled": True, "schedule": [{"time": "09:00"}]},
                "retweeting": {"enabled": True, "daily_limit": 3},
            },
            {
                "name": "Disabled",
                "enabled": False,
                "twitter": {"username": "@off", "profile_id": "p0"},
            },
        ]
    }
    (tmp_path / "settings.yaml").write_text(yaml.dump(settings))
    (tmp_path / "accounts.yaml").write_text(yaml.dump(accounts))
    return tmp_path


def test_load_settings(config_dir):
    cfg = ConfigLoader(
        settings_path=str(config_dir / "settings.yaml"),
        accounts_path=str(config_dir / "accounts.yaml"),
    )
    assert cfg.timezone == "America/New_York"
    assert cfg.dolphin_anty["port"] == 3001
    assert cfg.gologin["port"] == 36912
    assert cfg.browser_provider == "gologin"


def test_enabled_accounts(config_dir):
    cfg = ConfigLoader(
        settings_path=str(config_dir / "settings.yaml"),
        accounts_path=str(config_dir / "accounts.yaml"),
    )
    assert len(cfg.accounts) == 2
    assert len(cfg.enabled_accounts) == 1
    assert cfg.enabled_accounts[0]["name"] == "TestAcct"
    assert cfg.enabled_accounts[0]["twitter"]["profile_id"] == "p123"


def test_browser_provider_default(tmp_path):
    """When browser_provider is omitted, default to 'gologin'."""
    settings = {"timezone": "UTC"}
    accounts = {"accounts": []}
    (tmp_path / "settings.yaml").write_text(yaml.dump(settings))
    (tmp_path / "accounts.yaml").write_text(yaml.dump(accounts))
    cfg = ConfigLoader(
        settings_path=str(tmp_path / "settings.yaml"),
        accounts_path=str(tmp_path / "accounts.yaml"),
    )
    assert cfg.browser_provider == "gologin"


def test_missing_config_raises():
    with pytest.raises(FileNotFoundError):
        ConfigLoader(settings_path="/nonexistent/settings.yaml")
