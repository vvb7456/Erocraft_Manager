"""Register all API blueprints."""

from app.routes.auth import bp as auth_bp
from app.routes.dashboard import bp as dashboard_bp
from app.routes.servers import bp as servers_bp
from app.routes.users import bp as users_bp
from app.routes.logs import bp as logs_bp
from app.routes.settings import bp as settings_bp
from app.routes.automation import bp as automation_bp
from app.routes.email_templates import bp as email_templates_bp
from app.routes.resources import bp as resources_bp


def register_blueprints(app):
    prefix = '/api'
    app.register_blueprint(auth_bp, url_prefix=prefix)
    app.register_blueprint(dashboard_bp, url_prefix=prefix)
    app.register_blueprint(servers_bp, url_prefix=prefix)
    app.register_blueprint(users_bp, url_prefix=prefix)
    app.register_blueprint(logs_bp, url_prefix=prefix)
    app.register_blueprint(settings_bp, url_prefix=prefix)
    app.register_blueprint(automation_bp, url_prefix=prefix)
    app.register_blueprint(email_templates_bp, url_prefix=prefix)
    app.register_blueprint(resources_bp, url_prefix=prefix)
