"""Dashboard home page."""

from datetime import date

from flask import Blueprint, render_template, current_app

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    state = current_app.config["APP_STATE"]
    state.reload_config()
    accounts = state.config.accounts
    account_data = []

    today = date.today().isoformat()

    for acct in accounts:
        name = acct.get("name", "unknown")
        platform = acct.get("platform", "twitter")
        platform_cfg = acct.get(platform, acct.get("twitter", {}))
        status_obj = state.db.get_account_status(name)
        rt_today = state.db.get_retweets_today(name)
        sim_cfg = acct.get("human_simulation", {})

        if platform == "threads":
            rt_limit = acct.get("reposting", {}).get("max_per_day", 5)
            rt_enabled = acct.get("reposting", {}).get("enabled", False)
        else:
            rt_limit = acct.get("retweeting", {}).get("daily_limit", 3)
            rt_enabled = acct.get("retweeting", {}).get("enabled", False)

        # Simulation stats
        sim_sessions_today = 0
        sim_likes_today = 0
        if status_obj and getattr(status_obj, "sim_date", None) == today:
            sim_sessions_today = getattr(status_obj, "sim_sessions_today", 0) or 0
            sim_likes_today = getattr(status_obj, "sim_likes_today", 0) or 0

        account_data.append({
            "name": name,
            "platform": platform,
            "username": platform_cfg.get("username", ""),
            "enabled": acct.get("enabled", False),
            "status": status_obj.status if status_obj else "idle",
            "last_post": status_obj.last_post if status_obj else None,
            "last_retweet": status_obj.last_retweet if status_obj else None,
            "retweets_today": rt_today,
            "retweet_limit": rt_limit,
            "error_message": status_obj.error_message if status_obj else None,
            "posting_enabled": acct.get("posting", {}).get("enabled", False),
            "retweeting_enabled": rt_enabled,
            "sim_enabled": sim_cfg.get("enabled", False),
            "sim_sessions_today": sim_sessions_today,
            "sim_sessions_limit": sim_cfg.get("daily_sessions_limit", 2),
            "sim_likes_today": sim_likes_today,
            "sim_likes_limit": sim_cfg.get("daily_likes_limit", 30),
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
