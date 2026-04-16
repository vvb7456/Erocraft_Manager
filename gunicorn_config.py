"""Gunicorn configuration for production deployment."""

import os

# Tell Flask not to start the scheduler itself — gunicorn manages it.
os.environ['GUNICORN_MANAGED'] = '1'

_app = None

def when_ready(server):
    """Start APScheduler in the master process once gunicorn is ready."""
    global _app
    from app import create_app
    from app.extensions import scheduler
    from app.services.scheduler import init_scheduler

    _app = create_app()
    with _app.app_context():
        init_scheduler(_app)
        if not scheduler.running:
            scheduler.start()
            server.log.info("APScheduler started in master process.")


def post_fork(server, worker):
    """Pause scheduler in forked workers to prevent duplicate task execution."""
    from app.extensions import scheduler
    if scheduler.running:
        scheduler.pause()


# ── Server settings ──

bind = "0.0.0.0:5001"
workers = 3
worker_class = "gevent"
timeout = 120
preload_app = True
daemon = True
pidfile = "ptero_manager.pid"

# ── Logging ──

loglevel = "info"

logconfig_dict = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'generic': {
            'format': '%(asctime)s [%(process)d] [%(levelname)s] %(message)s',
            'datefmt': '[%Y-%m-%d %H:%M:%S %z]',
            'class': 'logging.Formatter',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'generic',
            'stream': 'ext://sys.stdout',
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'generic',
            'filename': os.path.join(os.path.dirname(__file__), 'logs', 'error.log'),
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'encoding': 'utf-8',
        },
        'access_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'generic',
            'filename': os.path.join(os.path.dirname(__file__), 'logs', 'access.log'),
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'encoding': 'utf-8',
        },
    },
    'loggers': {
        'gunicorn.error': {
            'handlers': ['console', 'error_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'gunicorn.access': {
            'handlers': ['access_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console', 'error_file'],
    },
}
