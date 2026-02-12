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

    if state.engine_status == "starting":
        return jsonify({
            "success": False,
            "message": "Engine is still starting up. Wait for accounts to finish loading.",
        })

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
                       "Google Drive may not be configured for this account.",
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

    if state.engine_status == "starting":
        return jsonify({
            "success": False,
            "message": "Engine is still starting up. Wait for accounts to finish loading.",
        })

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
                       "Retweeting may not be enabled for this account.",
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


@bp.route("/account/<name>/simulate", methods=["POST"])
def trigger_simulation(name):
    state = current_app.config["APP_STATE"]

    if state.engine_status == "starting":
        return jsonify({
            "success": False,
            "message": "Engine is still starting up. Wait for accounts to finish loading.",
        })

    if not state.engine_running or not state.application:
        return jsonify({
            "success": False,
            "message": "Engine is not running. Start the engine first.",
        })

    app = state.application
    simulator = app._simulators.get(name)
    if not simulator:
        return jsonify({
            "success": False,
            "message": f"No simulator found for account '{name}'.",
        })

    try:
        from src.scheduler.queue_handler import Task
        task = Task(
            account_name=name,
            task_type="simulation",
            callback=simulator.run_session,
        )
        app.queue.submit(task)
        return jsonify({
            "success": True,
            "message": f"Human simulation session queued for '{name}' (30-60 min)",
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
