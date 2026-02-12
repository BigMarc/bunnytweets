"""Dashboard home page."""

from flask import Blueprint, render_template, current_app

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    state = current_app.config["APP_STATE"]
    accounts = state.config.accounts
    account_data = []

    for acct in accounts:
        name = acct.get("name", "unknown")
        twitter = acct.get("twitter", {})
        status_obj = state.db.get_account_status(name)
        rt_today = state.db.get_retweets_today(name)
        rt_limit = acct.get("retweeting", {}).get("daily_limit", 3)

        account_data.append({
            "name": name,
            "username": twitter.get("username", ""),
            "enabled": acct.get("enabled", False),
            "status": status_obj.status if status_obj else "idle",
            "last_post": status_obj.last_post if status_obj else None,
            "last_retweet": status_obj.last_retweet if status_obj else None,
            "retweets_today": rt_today,
            "retweet_limit": rt_limit,
            "error_message": status_obj.error_message if status_obj else None,
            "posting_enabled": acct.get("posting", {}).get("enabled", False),
            "retweeting_enabled": acct.get("retweeting", {}).get("enabled", False),
        })

    jobs = []
    queue_size = 0
    active_tasks = 0
    if state.engine_running and state.application:
        try:
            jobs = state.application.job_manager.get_jobs_summary()
        except Exception:
            pass
        try:
            queue_size = state.application.queue.queue_size
            active_tasks = state.application.queue.active_tasks
        except Exception:
            pass

    return render_template(
        "dashboard.html",
        accounts=account_data,
        engine_status=state.engine_status,
        engine_running=state.engine_running,
        startup_error=state.startup_error,
        jobs=jobs,
        queue_size=queue_size,
        active_tasks=active_tasks,
        provider=state.config.browser_provider,
    )
