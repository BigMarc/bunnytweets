"""Register all route blueprints with the Flask app."""


def register_blueprints(app):
    from src.web.routes.dashboard import bp as dashboard_bp
    from src.web.routes.settings import bp as settings_bp
    from src.web.routes.accounts import bp as accounts_bp
    from src.web.routes.generator import bp as generator_bp
    from src.web.routes.logs import bp as logs_bp
    from src.web.routes.actions import bp as actions_bp
    from src.web.routes.api import bp as api_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(accounts_bp, url_prefix="/accounts")
    app.register_blueprint(generator_bp, url_prefix="/generator")
    app.register_blueprint(logs_bp, url_prefix="/logs")
    app.register_blueprint(actions_bp, url_prefix="/api/actions")
    app.register_blueprint(api_bp, url_prefix="/api")
