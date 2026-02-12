"""Interactive CLI setup wizard for BunnyTweets.

Guides users through configuring settings.yaml and accounts.yaml
step by step. Works even when config files don't exist yet.

Usage:
    python main.py --setup          Full setup (provider, token, accounts)
    python main.py --add-account    Add a new account to existing config
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml


BASE_DIR = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = BASE_DIR / "config" / "settings.yaml"
ACCOUNTS_PATH = BASE_DIR / "config" / "accounts.yaml"
SETTINGS_EXAMPLE = BASE_DIR / "config" / "settings.yaml.example"
ACCOUNTS_EXAMPLE = BASE_DIR / "config" / "accounts.yaml.example"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _input(prompt: str, default: str = "") -> str:
    """Prompt with optional default shown in brackets."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\n  Setup cancelled.")
        sys.exit(0)
    return value or default


def _confirm(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        value = input(f"  {prompt} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n\n  Setup cancelled.")
        sys.exit(0)
    if not value:
        return default
    return value in ("y", "yes")


def _choose(prompt: str, options: list[tuple[str, str]], default: int = 1) -> str:
    """Let user pick from numbered options. Returns the value (second element)."""
    print(f"\n  {prompt}")
    for i, (label, _value) in enumerate(options, 1):
        marker = " (default)" if i == default else ""
        print(f"    [{i}] {label}{marker}")
    try:
        raw = input(f"  Choice [{default}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\n  Setup cancelled.")
        sys.exit(0)
    if not raw:
        return options[default - 1][1]
    try:
        idx = int(raw)
        if 1 <= idx <= len(options):
            return options[idx - 1][1]
    except ValueError:
        pass
    print(f"  Invalid choice, using default: {options[default - 1][0]}")
    return options[default - 1][1]


def _load_yaml(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _write_yaml_with_header(path: Path, data: dict, header: str) -> None:
    """Write YAML with a comment header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = header + "\n" + yaml.dump(data, default_flow_style=False, sort_keys=False)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _mask_token(token: str) -> str:
    if len(token) <= 8:
        return "****"
    return token[:4] + "..." + token[-4:]


# ------------------------------------------------------------------
# Account wizard
# ------------------------------------------------------------------
def _collect_account(provider_name: str) -> dict:
    """Interactively collect one account's configuration."""
    print("\n  --- New Account ---")
    name = _input("Account name (e.g. MyMainAccount)")
    while not name:
        print("  Account name cannot be empty.")
        name = _input("Account name")

    username = _input("Twitter username (e.g. @myhandle)")
    while not username:
        print("  Username cannot be empty.")
        username = _input("Twitter username")
    if not username.startswith("@"):
        username = "@" + username

    profile_id = _input(f"Browser profile ID (from {provider_name})")
    while not profile_id:
        print("  Profile ID cannot be empty.")
        profile_id = _input(f"Browser profile ID (from {provider_name})")

    # Google Drive
    folder_id = _input("Google Drive folder ID (leave empty to skip)")

    # Posting
    posting_enabled = _confirm("Enable posting?", default=True)
    schedule = []
    if posting_enabled:
        times_raw = _input("Posting times (comma-separated HH:MM)", "09:00, 15:00, 20:00")
        for t in times_raw.split(","):
            t = t.strip()
            if re.match(r"^\d{1,2}:\d{2}$", t):
                schedule.append({"time": t})

    # Retweeting
    rt_enabled = _confirm("Enable retweeting?", default=True)
    daily_limit = 3
    target_profiles = []
    time_windows = [
        {"start": "09:00", "end": "12:00"},
        {"start": "14:00", "end": "17:00"},
        {"start": "19:00", "end": "22:00"},
    ]
    if rt_enabled:
        limit_raw = _input("Daily retweet limit", "3")
        try:
            daily_limit = int(limit_raw)
        except ValueError:
            daily_limit = 3

        targets_raw = _input("Retweet target usernames (comma-separated @handles, or empty)")
        if targets_raw:
            for i, handle in enumerate(targets_raw.split(","), 1):
                handle = handle.strip()
                if handle and not handle.startswith("@"):
                    handle = "@" + handle
                if handle:
                    target_profiles.append({"username": handle, "priority": i})

    # Build account dict
    acct: dict[str, Any] = {
        "name": name,
        "enabled": True,
        "twitter": {
            "username": username,
            "profile_id": profile_id,
        },
    }

    if folder_id:
        acct["google_drive"] = {
            "folder_id": folder_id,
            "check_interval_minutes": 15,
            "file_types": ["jpg", "png", "gif", "webp", "mp4", "mov", "txt"],
        }

    if posting_enabled:
        acct["posting"] = {
            "enabled": True,
            "schedule": schedule or [{"time": "09:00"}, {"time": "15:00"}, {"time": "20:00"}],
            "default_text": "",
        }
    else:
        acct["posting"] = {"enabled": False}

    rt_section: dict[str, Any] = {"enabled": rt_enabled}
    if rt_enabled:
        rt_section["daily_limit"] = daily_limit
        if target_profiles:
            rt_section["target_profiles"] = target_profiles
        rt_section["time_windows"] = time_windows
        rt_section["strategy"] = "latest"
    acct["retweeting"] = rt_section

    return acct


# ------------------------------------------------------------------
# Full setup
# ------------------------------------------------------------------
def run_setup() -> None:
    """Full interactive setup: provider, API token, timezone, accounts."""
    print()
    print("=" * 60)
    print("  BunnyTweets -- Interactive Setup")
    print("=" * 60)

    # Check if config files already exist
    if SETTINGS_PATH.exists():
        if not _confirm(
            "settings.yaml already exists. Overwrite?", default=False
        ):
            print("  Keeping existing settings.yaml.")
            settings = _load_yaml(SETTINGS_PATH)
        else:
            settings = {}
    else:
        settings = {}

    # Step 1: Browser provider
    provider = _choose(
        "Which anti-detect browser do you use?",
        [("GoLogin", "gologin"), ("Dolphin Anty", "dolphin_anty")],
        default=1,
    )
    provider_label = "GoLogin" if provider == "gologin" else "Dolphin Anty"
    settings["browser_provider"] = provider

    # Step 2: API token
    print(f"\n  -- {provider_label} Configuration --")
    if provider == "gologin":
        print("  Get your API token from GoLogin dashboard > Settings > API")
        token = _input("GoLogin API token")
        host = _input("GoLogin host", "localhost")
        port_raw = _input("GoLogin port", "36912")
        try:
            port = int(port_raw)
        except ValueError:
            port = 36912
        settings["gologin"] = {"host": host, "port": port, "api_token": token}
        # Keep dolphin_anty defaults for easy switching later
        settings.setdefault("dolphin_anty", {"host": "localhost", "port": 3001, "api_token": ""})
    else:
        print("  Get your API token from Dolphin Anty settings")
        token = _input("Dolphin Anty API token")
        host = _input("Dolphin Anty host", "localhost")
        port_raw = _input("Dolphin Anty port", "3001")
        try:
            port = int(port_raw)
        except ValueError:
            port = 3001
        settings["dolphin_anty"] = {"host": host, "port": port, "api_token": token}
        settings.setdefault("gologin", {"host": "localhost", "port": 36912, "api_token": ""})

    if token:
        print(f"  Token saved: {_mask_token(token)}")

    # Step 3: Timezone
    tz = _input("\n  Timezone (IANA format)", "America/New_York")
    settings["timezone"] = tz

    # Preserve defaults for other sections
    settings.setdefault("google_drive", {
        "credentials_file": "config/credentials/google_credentials.json",
        "download_dir": "data/downloads",
    })
    settings.setdefault("browser", {
        "implicit_wait": 10,
        "page_load_timeout": 30,
        "headless": False,
    })
    settings.setdefault("delays", {
        "action_min": 2.0,
        "action_max": 5.0,
        "typing_min": 0.05,
        "typing_max": 0.15,
        "page_load_min": 3.0,
        "page_load_max": 7.0,
    })
    settings.setdefault("error_handling", {
        "max_retries": 3,
        "retry_backoff": 5,
        "pause_duration_minutes": 60,
    })
    settings.setdefault("logging", {
        "level": "INFO",
        "retention_days": 30,
        "per_account_logs": True,
    })
    settings.setdefault("database", {
        "path": "data/database/automation.db",
    })

    # Write settings
    _write_yaml_with_header(
        SETTINGS_PATH,
        settings,
        "# Twitter Multi-Account Automation - Global Settings\n"
        "# Generated by: python main.py --setup\n",
    )
    print(f"\n  Settings saved to {SETTINGS_PATH.relative_to(BASE_DIR)}")

    # Step 4: Accounts
    print("\n  -- Account Setup --")
    accounts: list[dict] = []

    while True:
        acct = _collect_account(provider_label)
        accounts.append(acct)
        print(f"\n  Account '{acct['name']}' added.")
        if not _confirm("Add another account?", default=False):
            break

    accounts_data = {"accounts": accounts}
    _write_yaml_with_header(
        ACCOUNTS_PATH,
        accounts_data,
        "# Twitter Multi-Account Automation - Account Configuration\n"
        "# Generated by: python main.py --setup\n",
    )
    print(f"  Accounts saved to {ACCOUNTS_PATH.relative_to(BASE_DIR)}")

    # Summary
    print()
    print("=" * 60)
    print("  Setup Complete!")
    print("=" * 60)
    print(f"  Browser provider: {provider_label}")
    print(f"  Timezone:         {tz}")
    print(f"  Accounts:         {len(accounts)}")
    for a in accounts:
        print(f"    - {a['name']} ({a['twitter']['username']})")
    print()
    print("  Next steps:")
    print("    1. python main.py --test     Verify connections")
    print("    2. python main.py            Start automation")
    print("=" * 60)
    print()


# ------------------------------------------------------------------
# Add account
# ------------------------------------------------------------------
def run_add_account() -> None:
    """Add a new account to an existing accounts.yaml."""
    print()
    print("=" * 60)
    print("  BunnyTweets -- Add Account")
    print("=" * 60)

    # Load existing settings to know the provider
    settings = _load_yaml(SETTINGS_PATH)
    provider = settings.get("browser_provider", "gologin")
    provider_label = "GoLogin" if provider == "gologin" else "Dolphin Anty"
    print(f"  Browser provider: {provider_label}")

    # Load existing accounts
    accounts_data = _load_yaml(ACCOUNTS_PATH)
    accounts = accounts_data.get("accounts", [])
    existing_names = {a.get("name", "").lower() for a in accounts}

    if accounts:
        print(f"  Existing accounts: {len(accounts)}")
        for a in accounts:
            status = "enabled" if a.get("enabled", True) else "disabled"
            print(f"    - {a.get('name')} ({status})")

    acct = _collect_account(provider_label)

    # Check for duplicate name
    if acct["name"].lower() in existing_names:
        if not _confirm(
            f"Account '{acct['name']}' already exists. Add anyway?", default=False
        ):
            print("  Cancelled.")
            return

    accounts.append(acct)
    accounts_data["accounts"] = accounts

    _write_yaml_with_header(
        ACCOUNTS_PATH,
        accounts_data,
        "# Twitter Multi-Account Automation - Account Configuration\n",
    )

    print(f"\n  Account '{acct['name']}' added successfully!")
    print(f"  Total accounts: {len(accounts)}")
    print(f"  Saved to {ACCOUNTS_PATH.relative_to(BASE_DIR)}")
    print()
