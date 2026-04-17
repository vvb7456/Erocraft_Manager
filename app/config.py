"""Configuration management — dual-layer .env defaults + settings.json overrides."""

import os
import json
from dotenv import load_dotenv


class ConfigManager:
    SETTINGS_FILE = 'settings.json'

    # Keys that must be cast to int when loaded from settings.json
    INT_KEYS = frozenset({
        'DEFAULT_NEST_ID', 'DEFAULT_EGG_ID', 'DEFAULT_NODE_ID',
        'DEFAULT_CPU', 'DEFAULT_MEMORY', 'DEFAULT_DISK',
        'DEFAULT_DATABASES', 'DEFAULT_BACKUPS', 'DEFAULT_ALLOCATIONS',
        'SMTP_PORT', 'EMAIL_SEND_DELAY',
        'AUTOMATION_RUN_HOUR', 'AUTOMATION_RUN_MINUTE', 'AUTOMATION_DELETE_DAYS',
        'AUTOMATION_EMAIL_RUN_HOUR', 'AUTOMATION_EMAIL_RUN_MINUTE',
        'DB_PORT',
    })

    # Keys that must be cast to bool
    BOOL_KEYS = frozenset({
        'SMTP_USE_SSL',
        'AUTOMATION_SUSPEND_ENABLED', 'AUTOMATION_DELETE_ENABLED', 'AUTOMATION_EMAIL_ENABLED',
    })

    # Whitelist of keys that may be saved via the settings API
    SETTINGS_WHITELIST = frozenset({
        'PTERO_PANEL_URL', 'PTERO_API_KEY',
        'DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME',
        'SMTP_HOST', 'SMTP_PORT', 'SMTP_USE_SSL', 'SMTP_PASSWORD', 'SENDER_EMAIL', 'EMAIL_SEND_DELAY',
        'UI_SYSTEM_NAME', 'UI_BANNER_URL', 'UI_ICP_RECORD',
        'BRAND_NAME',
        'DEFAULT_NEST_ID', 'DEFAULT_EGG_ID', 'DEFAULT_NODE_ID', 'DOCKER_IMAGE',
        'DEFAULT_CPU', 'DEFAULT_MEMORY', 'DEFAULT_DISK',
        'DEFAULT_DATABASES', 'DEFAULT_BACKUPS', 'DEFAULT_ALLOCATIONS',
        'SERVER_NAME_PREFIX',
        'PANEL_APP_KEY',
    })

    AUTOMATION_WHITELIST = frozenset({
        'AUTOMATION_RUN_HOUR', 'AUTOMATION_RUN_MINUTE',
        'AUTOMATION_DELETE_DAYS', 'AUTOMATION_EMAIL_RUN_HOUR', 'AUTOMATION_EMAIL_RUN_MINUTE',
        'AUTOMATION_SUSPEND_ENABLED', 'AUTOMATION_DELETE_ENABLED', 'AUTOMATION_EMAIL_ENABLED',
        'TIMEZONE',
    })

    def __init__(self):
        self.config: dict = {}
        self.load_config()

    # ── Load ──

    def load_config(self):
        load_dotenv()
        self.config = self._defaults_from_env()
        self._overlay_settings_json()

    def _defaults_from_env(self) -> dict:
        """Read defaults from environment / .env file."""
        _bool = lambda v: str(v).lower() in ('true', '1', 't')
        _int = lambda v, d: int(v) if v else d
        env = os.getenv
        return {
            'SECRET_KEY': env('SECRET_KEY', 'a_default_secret_key_for_dev'),
            'DB_HOST': env('DB_HOST', '127.0.0.1'),
            'DB_PORT': _int(env('DB_PORT'), 3306),
            'DB_USER': env('DB_USER', ''),
            'DB_PASSWORD': env('DB_PASSWORD', ''),
            'DB_NAME': env('DB_NAME', 'panel'),
            'PTERO_PANEL_URL': env('PTERO_PANEL_URL', ''),
            'PTERO_API_KEY': env('PTERO_API_KEY', ''),
            'DEFAULT_NEST_ID': _int(env('DEFAULT_NEST_ID'), 1),
            'DEFAULT_EGG_ID': _int(env('DEFAULT_EGG_ID'), 1),
            'DEFAULT_NODE_ID': _int(env('DEFAULT_NODE_ID'), 1),
            'DOCKER_IMAGE': env('DOCKER_IMAGE', 'ghcr.io/pterodactyl/yolks:java_17'),
            'DEFAULT_CPU': _int(env('DEFAULT_CPU'), 100),
            'DEFAULT_MEMORY': _int(env('DEFAULT_MEMORY'), 1024),
            'DEFAULT_DISK': _int(env('DEFAULT_DISK'), 5120),
            'DEFAULT_DATABASES': _int(env('DEFAULT_DATABASES'), 0),
            'DEFAULT_BACKUPS': _int(env('DEFAULT_BACKUPS'), 0),
            'DEFAULT_ALLOCATIONS': _int(env('DEFAULT_ALLOCATIONS'), 1),
            'SERVER_NAME_PREFIX': env('SERVER_NAME_PREFIX', ''),
            'SMTP_HOST': env('SMTP_HOST', ''),
            'SMTP_PORT': _int(env('SMTP_PORT'), 587),
            'SMTP_USE_SSL': _bool(env('SMTP_USE_SSL', 'true')),
            'SMTP_PASSWORD': env('SMTP_PASSWORD', ''),
            'SENDER_EMAIL': env('SENDER_EMAIL', ''),
            'EMAIL_SEND_DELAY': _int(env('EMAIL_SEND_DELAY'), 2),
            'AUTOMATION_SUSPEND_ENABLED': _bool(env('AUTOMATION_SUSPEND_ENABLED', 'false')),
            'AUTOMATION_DELETE_ENABLED': _bool(env('AUTOMATION_DELETE_ENABLED', 'false')),
            'AUTOMATION_EMAIL_ENABLED': _bool(env('AUTOMATION_EMAIL_ENABLED', 'false')),
            'AUTOMATION_RUN_HOUR': _int(env('AUTOMATION_RUN_HOUR'), 2),
            'AUTOMATION_RUN_MINUTE': _int(env('AUTOMATION_RUN_MINUTE'), 0),
            'AUTOMATION_DELETE_DAYS': _int(env('AUTOMATION_DELETE_DAYS'), 14),
            'AUTOMATION_EMAIL_RUN_HOUR': _int(env('AUTOMATION_EMAIL_RUN_HOUR'), 10),
            'AUTOMATION_EMAIL_RUN_MINUTE': _int(env('AUTOMATION_EMAIL_RUN_MINUTE'), 0),
            'UI_SYSTEM_NAME': env('UI_SYSTEM_NAME', 'Pterodactyl 管理面板'),
            'UI_BANNER_URL': env('UI_BANNER_URL', ''),
            'UI_ICP_RECORD': env('UI_ICP_RECORD', ''),
            'BRAND_NAME': env('BRAND_NAME', 'Ptero Manager'),
            'TIMEZONE': env('TIMEZONE', 'Asia/Shanghai'),
        }

    def _overlay_settings_json(self):
        """Merge settings.json on top of env defaults."""
        try:
            with open(self.SETTINGS_FILE, 'r', encoding='utf-8') as f:
                overrides = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        for key in self.INT_KEYS:
            if key in overrides and overrides[key] not in (None, ''):
                overrides[key] = int(overrides[key])

        for key in self.BOOL_KEYS:
            if key in overrides:
                overrides[key] = str(overrides[key]).lower() in ('true', '1', 't')

        self.config.update(overrides)

    # ── Save ──

    def save_config(self, new_settings: dict):
        """Merge *new_settings* into settings.json and reload."""
        try:
            with open(self.SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        data.update(new_settings)

        with open(self.SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        self.load_config()

    # ── Accessors ──

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def get_db_uri(self) -> str:
        """Build SQLAlchemy DB URI from individual fields."""
        host = self.get('DB_HOST', '127.0.0.1')
        port = self.get('DB_PORT', 3306)
        user = self.get('DB_USER', '')
        password = self.get('DB_PASSWORD', '')
        name = self.get('DB_NAME', 'panel')
        from urllib.parse import quote_plus
        return f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}"


config_manager = ConfigManager()
