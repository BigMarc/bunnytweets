#!/usr/bin/env python3
"""Import accounts from a CSV file into config/accounts.yaml.

Usage:
    python scripts/import_accounts.py                            # reads config/accounts_template.csv
    python scripts/import_accounts.py path/to/my_accounts.csv    # reads a custom CSV
    python scripts/import_accounts.py --append my_accounts.csv   # append to existing accounts.yaml
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).resolve().parent.parent
ACCOUNTS_YAML = BASE_DIR / "config" / "accounts.yaml"
DEFAULT_CSV = BASE_DIR / "config" / "accounts_template.csv"

# ── Defaults applied when a CSV cell is empty ───────────────────────────
DEFAULTS = {
    "platform": "twitter",
    "content_rating": "sfw",
    "enabled": "true",
    "drive_check_interval": "15",
    "posting_enabled": "true",
    "posting_times": "09:00,15:00,20:00",
    "default_text": "",
    "title_categories": "Global",
    "retweet_enabled": "true",
    "retweet_daily_limit": "3",
    "retweet_targets": "",
    "retweet_time_windows": "09:00-12:00,14:00-17:00,19:00-22:00",
    "retweet_strategy": "latest",
    "sim_enabled": "true",
    "sim_duration_min": "30",
    "sim_duration_max": "60",
    "sim_daily_sessions": "2",
    "sim_daily_likes": "30",
    "sim_time_windows": "08:00-12:00,18:00-23:00",
    "reply_enabled": "false",
    "reply_daily_limit": "10",
    "reply_time_windows": "",
}

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


# ── Parsing helpers ─────────────────────────────────────────────────────

def _bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "yes")


def _int(val: str, fallback: int = 0) -> int:
    try:
        return int(val.strip())
    except (ValueError, AttributeError):
        return fallback


def _parse_times(raw: str) -> list[dict]:
    """'09:00,15:00,20:00' -> [{'time': '09:00'}, ...]"""
    if not raw.strip():
        return []
    return [{"time": t.strip()} for t in raw.split(",") if t.strip()]


def _parse_time_windows(raw: str) -> list[dict]:
    """'09:00-12:00,14:00-17:00' -> [{'start': '09:00', 'end': '12:00'}, ...]"""
    if not raw.strip():
        return []
    windows = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if "-" not in chunk:
            continue
        parts = chunk.split("-", 1)
        if len(parts) == 2:
            windows.append({"start": parts[0].strip(), "end": parts[1].strip()})
    return windows


def _parse_targets(raw: str) -> list[dict]:
    """'@user1:1,@user2:2' -> [{'username': '@user1', 'priority': 1}, ...]"""
    if not raw.strip():
        return []
    targets = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            user, pri = chunk.rsplit(":", 1)
            targets.append({"username": user.strip(), "priority": _int(pri, 1)})
        else:
            targets.append({"username": chunk, "priority": len(targets) + 1})
    return targets


def _parse_targets_simple(raw: str) -> list[str]:
    """'@user1,@user2' -> ['@user1', '@user2']  (for Threads reposting)"""
    if not raw.strip():
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _csv_list(raw: str) -> list[str]:
    """'Global,ALT' -> ['Global', 'ALT']"""
    if not raw.strip():
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


# ── Build account dict from one CSV row ─────────────────────────────────

def _get(row: dict, key: str) -> str:
    """Get a value from the row, falling back to DEFAULTS."""
    val = row.get(key, "")
    if val is None:
        val = ""
    val = val.strip()
    if not val:
        val = DEFAULTS.get(key, "")
    return val


def build_account(row: dict, row_num: int) -> dict | None:
    """Convert one CSV row into an accounts.yaml account dict."""
    name = row.get("name", "").strip()
    username = row.get("username", "").strip()
    profile_id = row.get("profile_id", "").strip()

    # Validation
    errors = []
    if not name:
        errors.append("name")
    if not username:
        errors.append("username")
    if not profile_id:
        errors.append("profile_id")
    if errors:
        print(f"  [ERROR] Row {row_num}: missing required field(s): {', '.join(errors)} — skipping")
        return None

    platform = _get(row, "platform")
    if platform not in ("twitter", "threads"):
        print(f"  [WARN] Row {row_num} ({name}): unknown platform '{platform}', defaulting to 'twitter'")
        platform = "twitter"

    content_rating = _get(row, "content_rating")
    if content_rating not in ("sfw", "nsfw"):
        content_rating = "sfw"

    acct: dict = {
        "name": name,
        "platform": platform,
        "content_rating": content_rating,
        "enabled": _bool(_get(row, "enabled")),
    }

    # Platform credentials
    acct[platform] = {
        "username": username,
        "profile_id": profile_id,
    }

    # Google Drive
    drive_folder = row.get("drive_folder_id", "").strip()
    if drive_folder:
        acct["google_drive"] = {
            "folder_id": drive_folder,
            "check_interval_minutes": _int(_get(row, "drive_check_interval"), 15),
            "file_types": ["jpg", "png", "gif", "webp", "mp4", "mov", "txt"],
        }

    # Posting
    acct["posting"] = {
        "enabled": _bool(_get(row, "posting_enabled")),
        "schedule": _parse_times(_get(row, "posting_times")),
        "default_text": _get(row, "default_text"),
        "title_categories": _csv_list(_get(row, "title_categories")),
    }

    # Retweeting / Reposting
    if platform == "threads":
        targets_raw = _get(row, "retweet_targets")
        acct["reposting"] = {
            "enabled": _bool(_get(row, "retweet_enabled")),
            "max_per_day": _int(_get(row, "retweet_daily_limit"), 5),
            "targets": _parse_targets_simple(targets_raw),
            "time_windows": _parse_time_windows(_get(row, "retweet_time_windows")),
        }
    else:
        acct["retweeting"] = {
            "enabled": _bool(_get(row, "retweet_enabled")),
            "daily_limit": _int(_get(row, "retweet_daily_limit"), 3),
            "target_profiles": _parse_targets(_get(row, "retweet_targets")),
            "time_windows": _parse_time_windows(_get(row, "retweet_time_windows")),
            "strategy": _get(row, "retweet_strategy"),
        }

    # Human simulation
    acct["human_simulation"] = {
        "enabled": _bool(_get(row, "sim_enabled")),
        "session_duration_min": _int(_get(row, "sim_duration_min"), 30),
        "session_duration_max": _int(_get(row, "sim_duration_max"), 60),
        "daily_sessions_limit": _int(_get(row, "sim_daily_sessions"), 2),
        "daily_likes_limit": _int(_get(row, "sim_daily_likes"), 30),
        "time_windows": _parse_time_windows(_get(row, "sim_time_windows")),
    }

    # Reply to replies
    reply_windows = _get(row, "reply_time_windows")
    acct["reply_to_replies"] = {
        "enabled": _bool(_get(row, "reply_enabled")),
        "daily_limit": _int(_get(row, "reply_daily_limit"), 10),
        "time_windows": _parse_time_windows(reply_windows),
    }

    return acct


# ── Main ────────────────────────────────────────────────────────────────

def import_csv(csv_path: Path, append: bool = False) -> None:
    if not csv_path.exists():
        print(f"  [ERROR] CSV file not found: {csv_path}")
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    if not rows:
        print("  [ERROR] CSV file is empty (no data rows)")
        sys.exit(1)

    # Build accounts
    accounts: list[dict] = []
    seen_names: set[str] = set()
    for i, row in enumerate(rows, start=2):  # row 1 is header
        acct = build_account(row, i)
        if acct is None:
            continue
        if acct["name"] in seen_names:
            print(f"  [WARN] Row {i}: duplicate name '{acct['name']}' — skipping")
            continue
        seen_names.add(acct["name"])
        accounts.append(acct)

    if not accounts:
        print("  [ERROR] No valid accounts found in CSV")
        sys.exit(1)

    # Merge with existing if --append
    if append and ACCOUNTS_YAML.exists():
        with open(ACCOUNTS_YAML, encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}
        existing_accounts = existing.get("accounts", [])
        existing_names = {a["name"] for a in existing_accounts}
        added = 0
        for acct in accounts:
            if acct["name"] in existing_names:
                print(f"  [SKIP] '{acct['name']}' already exists in accounts.yaml")
            else:
                existing_accounts.append(acct)
                added += 1
        data = {"accounts": existing_accounts}
        print(f"\n  Appended {added} new account(s) ({len(accounts) - added} skipped as duplicates)")
    else:
        data = {"accounts": accounts}
        # Back up existing file
        if ACCOUNTS_YAML.exists():
            backup = ACCOUNTS_YAML.with_suffix(".yaml.bak")
            shutil.copy2(ACCOUNTS_YAML, backup)
            print(f"  Backed up existing accounts.yaml to {backup.name}")

    # Write
    with open(ACCOUNTS_YAML, "w", encoding="utf-8") as fh:
        fh.write("# BunnyTweets - Account Configuration\n")
        fh.write("# Auto-generated by import_accounts.py from CSV\n\n")
        yaml.dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"  Wrote {len(data['accounts'])} account(s) to {ACCOUNTS_YAML.relative_to(BASE_DIR)}")


def main():
    parser = argparse.ArgumentParser(
        description="Import accounts from CSV into config/accounts.yaml"
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=str(DEFAULT_CSV),
        help="Path to CSV file (default: config/accounts_template.csv)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing accounts.yaml instead of overwriting",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.is_absolute():
        csv_path = BASE_DIR / csv_path

    print(f"\n  Importing accounts from: {csv_path}")
    print(f"  Mode: {'append' if args.append else 'overwrite'}\n")

    import_csv(csv_path, append=args.append)
    print()


if __name__ == "__main__":
    main()
