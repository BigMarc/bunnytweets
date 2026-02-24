"""Interactive CLI setup wizard for BunnyTweets.

Guides users through configuring settings.yaml and accounts.yaml
step by step. Works even when config files don't exist yet.

Usage:
    python main.py --setup          Full setup (provider, token, accounts)
    python main.py --add-account    Add a new account to existing config
"""

from __future__ import annotations

import json
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
CREDENTIALS_DIR = BASE_DIR / "config" / "credentials"
CREDENTIALS_PATH = CREDENTIALS_DIR / "google_credentials.json"


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

    # Google Drive (optional – only needed if you post media from Drive)
    print("\n  Google Drive integration is optional.")
    print("  Skip this if you don't plan to post media from a Drive folder.")
    folder_id = _input("Google Drive folder ID (press Enter to skip)")

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
# Google Drive credentials
# ------------------------------------------------------------------
def _setup_google_credentials() -> None:
    """Guide user through setting up Google Drive service-account credentials."""
    print("  To get Google Drive credentials:")
    print("    1. Go to https://console.cloud.google.com/")
    print("    2. Create a project (or select an existing one)")
    print("    3. Enable the Google Drive API")
    print("    4. Go to Credentials > Create Credentials > Service Account")
    print("    5. Give it a name, click Create and Continue, then Done")
    print("    6. Click on the service account > Keys tab > Add Key > Create new key > JSON")
    print("    7. Download the JSON file")
    print("    8. Share your Google Drive folder(s) with the service account email\n")

    print("  You can either:")
    print("    [1] Paste the JSON content directly")
    print("    [2] Provide the path to your downloaded JSON file\n")

    choice = _choose(
        "How would you like to provide the credentials?",
        [("Paste JSON content", "paste"), ("Path to JSON file", "path")],
        default=1,
    )

    creds_data = None

    if choice == "paste":
        print("\n  Paste your credentials JSON below (then press Enter twice):")
        lines = []
        try:
            while True:
                line = input()
                if not line and lines and not lines[-1]:
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return

        raw = "\n".join(lines).strip()
        try:
            creds_data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  Invalid JSON: {e}")
            print("  Skipping credentials setup. Add the file manually later.")
            return

    elif choice == "path":
        file_path = _input("Path to your credentials JSON file")
        if not file_path:
            print("  No path provided. Skipping.")
            return
        src_path = Path(file_path).expanduser().resolve()
        if not src_path.exists():
            print(f"  File not found: {src_path}")
            print("  Skipping credentials setup. Add the file manually later.")
            return
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                creds_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Could not read file: {e}")
            print("  Skipping credentials setup.")
            return

    if creds_data:
        if creds_data.get("type") != "service_account":
            print("\n  WARNING: This does not look like a Service Account JSON file.")
            print("  BunnyTweets expects a Service Account key (with \"type\": \"service_account\").")
            print("  If you downloaded an OAuth client ID JSON, that will NOT work.")
            print("  See the instructions above to create the correct credentials.")
            if not _confirm("Save anyway?", default=False):
                print("  Skipping credentials setup.")
                return
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
            json.dump(creds_data, f, indent=2)
        print(f"\n  Credentials saved to {CREDENTIALS_PATH.relative_to(BASE_DIR)}")
    else:
        print("  No credentials data. Skipping.")


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
        print("\n  The next two settings are for GoLogin's local desktop app.")
        print("  Just press Enter to keep the defaults -- they work out of the box.")
        host = _input("GoLogin host (GoLogin desktop runs locally)", "localhost")
        port_raw = _input("GoLogin port (GoLogin desktop default)", "36912")
        try:
            port = int(port_raw)
        except ValueError:
            port = 36912
        settings["gologin"] = {"host": host, "port": port, "api_token": token}
        settings.setdefault("dolphin_anty", {"host": "localhost", "port": 3001, "api_token": ""})
    else:
        print("  Get your API token from Dolphin Anty settings")
        token = _input("Dolphin Anty API token")
        print("\n  The next two settings are for Dolphin Anty's local app.")
        print("  Just press Enter to keep the defaults -- they work out of the box.")
        host = _input("Dolphin Anty host (runs locally)", "localhost")
        port_raw = _input("Dolphin Anty port (Dolphin Anty default)", "3001")
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

    # Step 4: Google Drive credentials (optional)
    print("\n  -- Google Drive Integration (Optional) --")
    print("  Google Drive lets you post media by uploading files to a Drive folder.")
    print("  You need a Google Cloud Service Account credentials JSON file for this.")
    print("  If you don't have one yet, you can skip this and set it up later.\n")

    if _confirm("Set up Google Drive credentials now?", default=False):
        _setup_google_credentials()
    else:
        print("  Skipping Google Drive setup. You can add it later via the web dashboard.")

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

    # Step 5: Accounts
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
    gdrive_status = "configured" if CREDENTIALS_PATH.exists() else "not configured"
    print(f"  Google Drive:     {gdrive_status}")
    print()
    print("  Next steps:")
    print("    1. python main.py --test     Verify connections")
    print("    2. python main.py --web      Open the web dashboard")
    print("    3. python main.py            Start automation (CLI)")
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
