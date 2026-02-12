"""Engine control and manual trigger endpoints."""

from flask import Blueprint, jsonify, current_app

bp = Blueprint("actions", __name__)


@bp.route("/engine/start", methods=["POST"])
def start_engine():
    state = current_app.config["APP_STATE"]
    success, message = state.start_engine()
    return jsonify({"success": success, "message": message})


@bp.route("/engine/stop", methods=["POST"])
def stop_engine():
    state = current_app.config["APP_STATE"]
    success, message = state.stop_engine()
    return jsonify({"success": success, "message": message})


@bp.route("/account/<name>/post", methods=["POST"])
def trigger_post(name):
    state = current_app.config["APP_STATE"]

    if not state.engine_running or not state.application:
        return jsonify({
            "success": False,
            "message": "Engine is not running. Start the engine first.",
        })

    app = state.application
    poster = app._posters.get(name)
    if not poster:
        return jsonify({
            "success": False,
            "message": f"No poster found for account '{name}'. "
                       "Account may not be set up or posting is disabled.",
        })

    try:
        from src.scheduler.queue_handler import Task
        task = Task(
            account_name=name,
            task_type="post",
            callback=poster.run_posting_cycle,
        )
        app.queue.submit(task)
        return jsonify({
            "success": True,
            "message": f"Post task queued for '{name}'",
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@bp.route("/account/<name>/retweet", methods=["POST"])
def trigger_retweet(name):
    state = current_app.config["APP_STATE"]

    if not state.engine_running or not state.application:
        return jsonify({
            "success": False,
            "message": "Engine is not running. Start the engine first.",
        })

    app = state.application
    retweeter = app._retweeters.get(name)
    if not retweeter:
        return jsonify({
            "success": False,
            "message": f"No retweeter found for account '{name}'. "
                       "Account may not be set up or retweeting is disabled.",
        })

    try:
        from src.scheduler.queue_handler import Task
        task = Task(
            account_name=name,
            task_type="retweet",
            callback=retweeter.run_retweet_cycle,
        )
        app.queue.submit(task)
        return jsonify({
            "success": True,
            "message": f"Retweet task queued for '{name}'",
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
