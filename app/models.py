"""Database models — all backed by the Pterodactyl MySQL database."""

from datetime import datetime
import bcrypt
from app.extensions import db


# ── Pterodactyl read-only models ──

class PteroUser(db.Model):
    """Model mapping to Pterodactyl panel's `users` table."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(191), nullable=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False)
    username = db.Column(db.String(191), unique=True, nullable=False)
    email = db.Column(db.String(191), unique=True, nullable=False)
    name_first = db.Column(db.String(191), nullable=True)
    name_last = db.Column(db.String(191), nullable=True)
    password = db.Column(db.Text, nullable=False)
    remember_token = db.Column(db.String(191), nullable=True)
    root_admin = db.Column(db.Boolean, nullable=False, default=False)
    language = db.Column(db.String(5), nullable=False, default='en')
    use_totp = db.Column(db.Boolean, nullable=False, default=False)
    totp_secret = db.Column(db.Text, nullable=True)
    totp_authenticated_at = db.Column(db.DateTime, nullable=True)
    gravatar = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    servers = db.relationship('PteroServer', back_populates='owner', lazy='dynamic')

    def check_password(self, plain_password: str) -> bool:
        """Verify a password against the Pterodactyl bcrypt hash."""
        stored = self.password
        if stored.startswith('$2y$'):
            stored = '$2b$' + stored[4:]
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            stored.encode('utf-8'),
        )

    def set_password(self, plain_password: str):
        """Hash and store a password (bcrypt, $2y$ prefix for PHP compat)."""
        hashed = bcrypt.hashpw(
            plain_password.encode('utf-8'),
            bcrypt.gensalt(rounds=10),
        ).decode('utf-8')
        # Pterodactyl / PHP uses $2y$ prefix
        if hashed.startswith('$2b$'):
            hashed = '$2y$' + hashed[4:]
        self.password = hashed

    @property
    def name(self) -> str:
        return f'{self.name_first} {self.name_last}'.strip()

    def __repr__(self):
        return f'<PteroUser {self.username}>'


class PteroServer(db.Model):
    """Read-only model mapping to Pterodactyl panel's `servers` table."""
    __tablename__ = 'servers'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False)
    uuidShort = db.Column(db.String(8), nullable=False)
    node_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(191), nullable=False)
    description = db.Column(db.Text, nullable=False, default='')
    status = db.Column(db.String(191), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    memory = db.Column(db.Integer, nullable=False, default=0)
    swap = db.Column(db.Integer, nullable=False, default=0)
    disk = db.Column(db.Integer, nullable=False, default=0)
    io = db.Column(db.Integer, nullable=False, default=500)
    cpu = db.Column(db.Integer, nullable=False, default=0)
    allocation_id = db.Column(db.Integer, nullable=False)
    nest_id = db.Column(db.Integer, nullable=False)
    egg_id = db.Column(db.Integer, nullable=False)
    database_limit = db.Column(db.Integer, default=0)
    allocation_limit = db.Column(db.Integer, default=0)
    backup_limit = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship('PteroUser', back_populates='servers', lazy='joined')
    meta = db.relationship('ServerMeta', back_populates='server', uselist=False, lazy='joined')

    @property
    def is_suspended(self) -> bool:
        return self.status == 'suspended'

    @property
    def expiration_date(self):
        return self.meta.expiration_date if self.meta else None

    def __repr__(self):
        return f'<PteroServer {self.name}>'


# ── Manager read-write models ──

class ServerMeta(db.Model):
    """Custom meta table storing expiration dates for servers."""
    __tablename__ = 'manager_server_meta'

    server_id = db.Column(db.Integer, db.ForeignKey('servers.id', ondelete='CASCADE'), primary_key=True)
    expiration_date = db.Column(db.Date, nullable=True)

    server = db.relationship('PteroServer', back_populates='meta')

    def __repr__(self):
        return f'<ServerMeta server={self.server_id} expires={self.expiration_date}>'


class ManagerActivityLog(db.Model):
    """Activity log records stored in MySQL."""
    __tablename__ = 'manager_activity_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    actor = db.Column(db.String(100), nullable=False, default='')
    action = db.Column(db.String(100), nullable=False, default='')
    status = db.Column(db.String(50), nullable=False, default='')
    details = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<ManagerActivityLog {self.action} by {self.actor}>'
