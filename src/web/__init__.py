"""BunnyTweets Web Dashboard - Flask app factory."""

from __future__ import annotations

import os
import secrets

from flask import Flask
from flask_wtf.csrf import CSRFProtect

from src.web.state import AppState

csrf = CSRFProtect()


def create_app(config, db) -> Flask:
    """Create and configure the Flask application.

    Args:
        config: A ConfigLoader instance (lightweight, no browser deps).
        db: A Database instance.
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

    # CSRF protection
    csrf.init_app(app)

    # Initialize shared state
    state = AppState(config=config, db=db)
    app.config["APP_STATE"] = state

    # Register blueprints
    from src.web.routes import register_blueprints
    register_blueprints(app)

    return app
