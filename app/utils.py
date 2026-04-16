"""Shared utility functions."""

from datetime import datetime
import pytz
from flask import current_app
from app.extensions import db
from app.models import ManagerActivityLog
from app.config import config_manager


def get_today():
    """Return today's date in the configured local timezone."""
    tz = pytz.timezone(config_manager.get('TIMEZONE', 'Asia/Shanghai'))
    return datetime.now(tz).date()


def log_activity(actor: str, action: str, status: str, details: str = ''):
    """Insert an activity log record."""
    try:
        entry = ManagerActivityLog(actor=actor[:100], action=action[:100], status=status[:50], details=details)
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to log activity: {e}", exc_info=True)
