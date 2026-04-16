"""Application factory — creates and configures the Flask app."""

import os
from flask import Flask, send_from_directory
from app.extensions import db, scheduler
from app.config import config_manager
from app.auth import init_auth
from app.routes import register_blueprints
from app.services.scheduler import init_scheduler


def create_app():
    app = Flask(
        __name__,
        static_folder=None,          # We serve Vue build output manually
        template_folder='templates',  # Jinja2 templates (email only)
    )

    cfg = config_manager.config
    app.secret_key = cfg.get('SECRET_KEY', 'change-me-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = config_manager.get_db_uri()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SCHEDULER_TIMEZONE'] = cfg.get('TIMEZONE', 'Asia/Shanghai')

    # ── Extensions ──
    db.init_app(app)
    init_auth(app)
    register_blueprints(app)

    # ── Database init ──
    with app.app_context():
        db.create_all()

    # ── Scheduler (dev mode only — gunicorn manages it separately) ──
    if os.environ.get('GUNICORN_MANAGED') != '1':
        init_scheduler(app)
        scheduler.start()

    # ── SPA static file serving ──
    _register_spa(app)

    return app


def _register_spa(app):
    """Serve the Vue build output as a single-page application."""
    dist_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'dist')

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_spa(path):
        # Serve static assets from dist/
        full_path = os.path.join(dist_dir, path)
        if path and os.path.isfile(full_path):
            return send_from_directory(dist_dir, path)
        # Fallback to index.html for SPA routing
        return send_from_directory(dist_dir, 'index.html')
