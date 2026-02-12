"""Account management routes."""

import re
from flask import (
    Blueprint, render_template, request, flash, redirect, url_for,
    current_app, jsonify,
)

bp = Blueprint("accounts", __name__)


def _get_accounts_data(state):
    """Load raw accounts dict from config."""
    return {"accounts": list(state.config.accounts)}


@bp.route("/")
def index():
    state = current_app.config["APP_STATE"]
    accounts = state.config.accounts
    account_info = []
    for acct in accounts:
        name = acct.get("name", "unknown")
        status_obj = state.db.get_account_status(name)
        account_info.append({
            **acct,
            "status": status_obj.status if status_obj else "idle",
        })
    return render_template("accounts.html", accounts=account_info)


@bp.route("/add", methods=["GET"])
def add_form():
    state = current_app.config["APP_STATE"]
    provider = state.config.browser_provider
    return render_template("account_form.html", account=None, provider=provider, edit=False)


@bp.route("/add", methods=["POST"])
def add_save():
    state = current_app.config["APP_STATE"]
    acct = _parse_account_form(request.form)

    if not acct["name"]:
        flash("Account name is required.", "danger")
        return redirect(url_for("accounts.add_form"))

    data = _get_accounts_data(state)
    data["accounts"].append(acct)
    state.save_accounts(data)

    flash(f"Account '{acct['name']}' added!", "success")
    return redirect(url_for("accounts.index"))


@bp.route("/<name>/edit", methods=["GET"])
def edit_form(name):
    state = current_app.config["APP_STATE"]
    provider = state.config.browser_provider
    acct = _find_account(state, name)
    if not acct:
        flash(f"Account '{name}' not found.", "danger")
        return redirect(url_for("accounts.index"))
    return render_template("account_form.html", account=acct, provider=provider, edit=True)


@bp.route("/<name>/edit", methods=["POST"])
def edit_save(name):
    state = current_app.config["APP_STATE"]
    data = _get_accounts_data(state)

    idx = _find_account_index(data["accounts"], name)
    if idx is None:
        flash(f"Account '{name}' not found.", "danger")
        return redirect(url_for("accounts.index"))

    acct = _parse_account_form(request.form)
    acct["name"] = name  # Name is read-only on edit
    data["accounts"][idx] = acct
    state.save_accounts(data)

    flash(f"Account '{name}' updated!", "success")
    return redirect(url_for("accounts.index"))


@bp.route("/<name>/delete", methods=["POST"])
def delete(name):
    state = current_app.config["APP_STATE"]
    data = _get_accounts_data(state)

    idx = _find_account_index(data["accounts"], name)
    if idx is None:
        flash(f"Account '{name}' not found.", "danger")
        return redirect(url_for("accounts.index"))

    data["accounts"].pop(idx)
    state.save_accounts(data)

    flash(f"Account '{name}' deleted.", "success")
    return redirect(url_for("accounts.index"))


@bp.route("/<name>/toggle", methods=["POST"])
def toggle(name):
    state = current_app.config["APP_STATE"]
    data = _get_accounts_data(state)

    idx = _find_account_index(data["accounts"], name)
    if idx is None:
        return jsonify({"success": False, "message": f"Account '{name}' not found"})

    current = data["accounts"][idx].get("enabled", True)
    data["accounts"][idx]["enabled"] = not current
    state.save_accounts(data)

    new_state = "enabled" if not current else "disabled"
    return jsonify({"success": True, "enabled": not current, "message": f"Account {new_state}"})


def _find_account(state, name):
    for acct in state.config.accounts:
        if acct.get("name") == name:
            return acct
    return None


def _find_account_index(accounts, name):
    for i, acct in enumerate(accounts):
        if acct.get("name") == name:
            return i
    return None


def _parse_account_form(form):
    """Parse the account form into the YAML-compatible dict structure."""
    acct = {
        "name": form.get("name", "").strip(),
        "enabled": "enabled" in form,
        "twitter": {
            "username": form.get("twitter.username", "").strip(),
            "profile_id": form.get("twitter.profile_id", "").strip(),
        },
    }

    # Google Drive
    folder_id = form.get("google_drive.folder_id", "").strip()
    if folder_id:
        acct["google_drive"] = {
            "folder_id": folder_id,
            "check_interval_minutes": _to_int(
                form.get("google_drive.check_interval_minutes", "15"), 15
            ),
            "file_types": ["jpg", "png", "gif", "webp", "mp4", "mov", "txt"],
        }

    # Posting
    posting_enabled = "posting.enabled" in form
    acct["posting"] = {"enabled": posting_enabled}
    if posting_enabled:
        times_raw = form.get("posting.schedule", "")
        schedule = []
        for t in times_raw.split(","):
            t = t.strip()
            if re.match(r"^\d{1,2}:\d{2}$", t):
                schedule.append({"time": t})
        acct["posting"]["schedule"] = schedule or [{"time": "09:00"}, {"time": "15:00"}, {"time": "20:00"}]
        acct["posting"]["default_text"] = form.get("posting.default_text", "")

    # Retweeting
    rt_enabled = "retweeting.enabled" in form
    acct["retweeting"] = {"enabled": rt_enabled}
    if rt_enabled:
        acct["retweeting"]["daily_limit"] = _to_int(
            form.get("retweeting.daily_limit", "3"), 3
        )
        acct["retweeting"]["strategy"] = form.get("retweeting.strategy", "latest")

        # Target profiles (dynamic rows)
        targets = []
        i = 0
        while True:
            username = form.get(f"target_{i}_username", "").strip()
            if not username:
                break
            if not username.startswith("@"):
                username = "@" + username
            priority = _to_int(form.get(f"target_{i}_priority", str(i + 1)), i + 1)
            targets.append({"username": username, "priority": priority})
            i += 1
        if targets:
            acct["retweeting"]["target_profiles"] = targets

        # Time windows (dynamic rows)
        windows = []
        i = 0
        while True:
            start = form.get(f"window_{i}_start", "").strip()
            end = form.get(f"window_{i}_end", "").strip()
            if not start or not end:
                break
            windows.append({"start": start, "end": end})
            i += 1
        acct["retweeting"]["time_windows"] = windows or [
            {"start": "09:00", "end": "12:00"},
            {"start": "14:00", "end": "17:00"},
            {"start": "19:00", "end": "22:00"},
        ]

    return acct


def _to_int(val, default):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default
