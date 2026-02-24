"""JSON API endpoints for live status polling."""

from flask import Blueprint, jsonify, current_app

bp = Blueprint("api", __name__)


@bp.route("/status")
def status():
    state = current_app.config["APP_STATE"]
    accounts = state.config.accounts
    account_data = []

    for acct in accounts:
        name = acct.get("name", "unknown")
        twitter = acct.get("twitter", {})
        status_obj = state.db.get_account_status(name)
        rt_today = state.db.get_retweets_today(name)
        rt_limit = acct.get("retweeting", {}).get("daily_limit", 3)

        last_post = None
        last_retweet = None
        if status_obj:
            if status_obj.last_post:
                last_post = status_obj.last_post.isoformat()
            if status_obj.last_retweet:
                last_retweet = status_obj.last_retweet.isoformat()

        account_data.append({
            "name": name,
            "username": twitter.get("username", ""),
            "enabled": acct.get("enabled", False),
            "status": status_obj.status if status_obj else "idle",
            "last_post": last_post,
            "last_retweet": last_retweet,
            "retweets_today": rt_today,
            "retweet_limit": rt_limit,
            "error_message": status_obj.error_message if status_obj else None,
        })

    queue_info = {"size": 0, "active": 0}
    jobs_count = 0
    if state.application:
        try:
            queue_info["size"] = state.application.queue.queue_size
            queue_info["active"] = state.application.queue.active_tasks
        except Exception:
            pass
        try:
            jobs_count = len(state.application.job_manager.get_jobs_summary())
        except Exception:
            pass

    return jsonify({
        "engine_status": state.engine_status,
        "engine_running": state.engine_running,
        "startup_error": state.startup_error,
        "accounts": account_data,
        "queue": queue_info,
        "jobs_count": jobs_count,
    })


@bp.route("/engine")
def engine():
    state = current_app.config["APP_STATE"]
    return jsonify({
        "status": state.engine_status,
        "error": state.startup_error,
    })


@bp.route("/jobs")
def jobs():
    state = current_app.config["APP_STATE"]
    if not state.application:
        return jsonify([])
    try:
        raw = state.application.job_manager.get_jobs_summary()
        result = []
        for j in raw:
            result.append({
                "id": j.get("id", ""),
                "next_run": str(j.get("next_run", "")),
            })
        return jsonify(result)
    except Exception:
        return jsonify([])


@bp.route("/analytics")
def analytics():
    state = current_app.config["APP_STATE"]
    days = 30
    try:
        daily = state.db.get_daily_activity(days)
        sf = state.db.get_success_failure_counts(days)
        per_account = state.db.get_per_account_stats(days)
        rotation = state.db.get_file_use_distribution()
    except Exception:
        daily, sf, per_account, rotation = [], {}, [], []
    return jsonify({
        "daily_activity": daily,
        "success_failure": sf,
        "per_account": per_account,
        "rotation": rotation,
    })


@bp.route("/queue")
def queue():
    state = current_app.config["APP_STATE"]
    if not state.application:
        return jsonify({"size": 0, "active": 0})
    try:
        return jsonify({
            "size": state.application.queue.queue_size,
            "active": state.application.queue.active_tasks,
        })
    except Exception:
        return jsonify({"size": 0, "active": 0})
