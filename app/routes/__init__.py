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
from app.routes.user import bp as user_bp
from app.routes.user_servers import bp as user_servers_bp
from app.routes.user_files import bp as user_files_bp


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
    app.register_blueprint(user_bp, url_prefix=f'{prefix}/user')
    app.register_blueprint(user_servers_bp, url_prefix=f'{prefix}/user')
    app.register_blueprint(user_files_bp, url_prefix=f'{prefix}/user')
