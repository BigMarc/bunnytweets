"""Settings editor routes."""

from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app

bp = Blueprint("settings", __name__)


def _get_nested(d, key, default=""):
    """Get a nested dict value using dot notation: 'delays.action_min'."""
    keys = key.split(".")
    val = d
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, default)
        else:
            return default
    return val if val is not None else default


def _set_nested(d, key, value):
    """Set a nested dict value using dot notation."""
    keys = key.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


@bp.route("/", methods=["GET"])
def index():
    state = current_app.config["APP_STATE"]
    settings = state.config.settings
    return render_template(
        "settings.html",
        settings=settings,
        engine_running=state.engine_running,
    )


@bp.route("/", methods=["POST"])
def save():
    state = current_app.config["APP_STATE"]
    old = state.config.settings.copy()
    new_settings = {}

    # General
    new_settings["browser_provider"] = request.form.get("browser_provider", "gologin")
    new_settings["timezone"] = request.form.get("timezone", "America/New_York")

    # GoLogin
    gl_token = request.form.get("gologin.api_token", "")
    new_settings["gologin"] = {
        "host": request.form.get("gologin.host", "localhost"),
        "port": _to_int(request.form.get("gologin.port", "36912"), 36912),
        "api_token": gl_token if gl_token else _get_nested(old, "gologin.api_token", ""),
    }

    # Dolphin Anty
    da_token = request.form.get("dolphin_anty.api_token", "")
    new_settings["dolphin_anty"] = {
        "host": request.form.get("dolphin_anty.host", "localhost"),
        "port": _to_int(request.form.get("dolphin_anty.port", "3001"), 3001),
        "api_token": da_token if da_token else _get_nested(old, "dolphin_anty.api_token", ""),
    }

    # Google Drive
    new_settings["google_drive"] = {
        "credentials_file": request.form.get(
            "google_drive.credentials_file",
            "config/credentials/google_credentials.json",
        ),
        "download_dir": request.form.get("google_drive.download_dir", "data/downloads"),
    }

    # Browser
    new_settings["browser"] = {
        "implicit_wait": _to_int(request.form.get("browser.implicit_wait", "10"), 10),
        "page_load_timeout": _to_int(request.form.get("browser.page_load_timeout", "30"), 30),
        "headless": "browser.headless" in request.form,
    }

    # Delays
    new_settings["delays"] = {
        "action_min": _to_float(request.form.get("delays.action_min", "2.0"), 2.0),
        "action_max": _to_float(request.form.get("delays.action_max", "5.0"), 5.0),
        "typing_min": _to_float(request.form.get("delays.typing_min", "0.05"), 0.05),
        "typing_max": _to_float(request.form.get("delays.typing_max", "0.15"), 0.15),
        "page_load_min": _to_float(request.form.get("delays.page_load_min", "3.0"), 3.0),
        "page_load_max": _to_float(request.form.get("delays.page_load_max", "7.0"), 7.0),
    }

    # Error Handling
    new_settings["error_handling"] = {
        "max_retries": _to_int(request.form.get("error_handling.max_retries", "3"), 3),
        "retry_backoff": _to_int(request.form.get("error_handling.retry_backoff", "5"), 5),
        "pause_duration_minutes": _to_int(
            request.form.get("error_handling.pause_duration_minutes", "60"), 60
        ),
    }

    # Logging
    new_settings["logging"] = {
        "level": request.form.get("logging.level", "INFO"),
        "retention_days": _to_int(request.form.get("logging.retention_days", "30"), 30),
        "per_account_logs": "logging.per_account_logs" in request.form,
        "quiet": "logging.quiet" in request.form,
    }

    # Database
    new_settings["database"] = {
        "path": request.form.get("database.path", "data/database/automation.db"),
    }

    state.save_settings(new_settings)
    flash("Settings saved successfully!", "success")

    if state.engine_running:
        flash("Engine is running. Restart it to apply changes.", "warning")

    return redirect(url_for("settings.index"))


def _to_int(val, default):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _to_float(val, default):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
