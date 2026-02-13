"""Account management routes."""

import re
from flask import (
    Blueprint, render_template, request, flash, redirect, url_for,
    current_app, jsonify,
)

bp = Blueprint("accounts", __name__)


def _get_form_context(state, acct=None):
    """Build extra context for the account form (categories, CTAs)."""
    categories = state.db.get_all_categories()
    all_cats = [{"id": c.id, "name": c.name} for c in categories]

    selected = []
    if acct:
        selected = acct.get("posting", {}).get("title_categories", [])

    cta_texts = []
    if acct and acct.get("name"):
        ctas = state.db.get_cta_texts(acct["name"])
        cta_texts = [{"id": c.id, "text": c.text} for c in ctas]

    reply_templates = []
    if acct and acct.get("name"):
        tpls = state.db.get_reply_templates(acct["name"])
        reply_templates = [{"id": t.id, "text": t.text} for t in tpls]

    return {
        "all_categories": all_cats,
        "selected_categories": selected,
        "cta_texts": cta_texts,
        "reply_templates": reply_templates,
    }


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
    ctx = _get_form_context(state)
    return render_template("account_form.html", account=None, provider=provider, edit=False, **ctx)


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

    # Auto-add new account's twitter username to global retweet pool
    username = acct.get("twitter", {}).get("username", "")
    if username:
        state.db.add_global_target(username)

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
    ctx = _get_form_context(state, acct)
    return render_template("account_form.html", account=acct, provider=provider, edit=True, **ctx)


@bp.route("/<name>/edit", methods=["POST"])
def edit_save(name):
    state = current_app.config["APP_STATE"]
    data = _get_accounts_data(state)

    idx = _find_account_index(data["accounts"], name)
    if idx is None:
        flash(f"Account '{name}' not found.", "danger")
        return redirect(url_for("accounts.index"))

    # Track old username so we can update the global target pool
    old_username = data["accounts"][idx].get("twitter", {}).get("username", "")

    acct = _parse_account_form(request.form)
    data["accounts"][idx] = acct
    state.save_accounts(data)

    # Update global target pool if username changed
    new_username = acct.get("twitter", {}).get("username", "")
    if old_username and new_username and old_username != new_username:
        state.db.update_global_target(old_username, new_username)
    elif new_username and not old_username:
        state.db.add_global_target(new_username)

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


@bp.route("/<name>/cta/add", methods=["POST"])
def add_cta(name):
    state = current_app.config["APP_STATE"]
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"success": False, "message": "CTA text is required"})

    cta = state.db.add_cta_text(name, text)
    return jsonify({"success": True, "id": cta.id, "message": "CTA text added"})


@bp.route("/<name>/cta/<int:cta_id>/delete", methods=["POST"])
def delete_cta(name, cta_id):
    state = current_app.config["APP_STATE"]
    ok = state.db.delete_cta_text(cta_id)
    if ok:
        return jsonify({"success": True, "message": "CTA text deleted"})
    return jsonify({"success": False, "message": "CTA text not found"})


@bp.route("/<name>/reply-template/add", methods=["POST"])
def add_reply_template(name):
    state = current_app.config["APP_STATE"]
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"success": False, "message": "Template text is required"})

    tpl = state.db.add_reply_template(name, text)
    return jsonify({"success": True, "id": tpl.id, "message": "Reply template added"})


@bp.route("/<name>/reply-template/<int:tpl_id>/delete", methods=["POST"])
def delete_reply_template(name, tpl_id):
    state = current_app.config["APP_STATE"]
    ok = state.db.delete_reply_template(tpl_id)
    if ok:
        return jsonify({"success": True, "message": "Reply template deleted"})
    return jsonify({"success": False, "message": "Reply template not found"})


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

    # Title categories (multi-select checkboxes — always include Global)
    selected_cats = form.getlist("title_category")
    # Deduplicate and ensure Global is always present
    cat_set = set(selected_cats) | {"Global"}
    acct["posting"]["title_categories"] = sorted(cat_set)

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

    # Human simulation
    sim_enabled = "human_simulation.enabled" in form
    acct["human_simulation"] = {"enabled": sim_enabled}
    if sim_enabled:
        acct["human_simulation"]["session_duration_min"] = _to_int(
            form.get("human_simulation.session_duration_min", "30"), 30
        )
        acct["human_simulation"]["session_duration_max"] = _to_int(
            form.get("human_simulation.session_duration_max", "60"), 60
        )
        acct["human_simulation"]["daily_sessions_limit"] = _to_int(
            form.get("human_simulation.daily_sessions_limit", "2"), 2
        )
        acct["human_simulation"]["daily_likes_limit"] = _to_int(
            form.get("human_simulation.daily_likes_limit", "30"), 30
        )

        # Simulation time windows
        sim_windows = []
        i = 0
        while True:
            start = form.get(f"sim_window_{i}_start", "").strip()
            end = form.get(f"sim_window_{i}_end", "").strip()
            if not start or not end:
                break
            sim_windows.append({"start": start, "end": end})
            i += 1
        acct["human_simulation"]["time_windows"] = sim_windows or [
            {"start": "08:00", "end": "12:00"},
            {"start": "18:00", "end": "23:00"},
        ]

    # Reply to replies
    reply_enabled = "reply_to_replies.enabled" in form
    acct["reply_to_replies"] = {"enabled": reply_enabled}
    if reply_enabled:
        acct["reply_to_replies"]["daily_limit"] = _to_int(
            form.get("reply_to_replies.daily_limit", "10"), 10
        )

        # Reply time windows
        reply_windows = []
        i = 0
        while True:
            start = form.get(f"reply_window_{i}_start", "").strip()
            end = form.get(f"reply_window_{i}_end", "").strip()
            if not start or not end:
                break
            reply_windows.append({"start": start, "end": end})
            i += 1
        acct["reply_to_replies"]["time_windows"] = reply_windows or [
            {"start": "09:00", "end": "22:00"},
        ]

    return acct


def _to_int(val, default):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default
