"""System Diagnoser web routes — live health dashboard and JSON API."""

from flask import Blueprint, render_template, jsonify, current_app

bp = Blueprint("diagnose", __name__)


def _get_diagnoser():
    """Build a SystemDiagnoser from the current AppState.

    IMPORTANT: We always pass ``app=None`` here because the diagnoser's
    browser liveness checks (``driver.title``) would crash if called from
    Flask's thread — Selenium/Playwright drivers are bound to the main
    thread.  Browser health is checked by the main loop instead.
    """
    from src.core.diagnoser import SystemDiagnoser

    state = current_app.config["APP_STATE"]
    return SystemDiagnoser(app=None, config=state.config, db=state.db)


@bp.route("/")
def index():
    diag = _get_diagnoser()
    report = diag.run_full_diagnosis()
    return render_template("diagnose.html", report=report)


@bp.route("/api/run")
def api_run():
    """JSON endpoint — run full diagnosis and return structured data."""
    diag = _get_diagnoser()
    report = diag.run_full_diagnosis()
    return jsonify(report.to_dict())
