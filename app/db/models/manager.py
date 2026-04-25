"""Manager-owned tables stored in the Panel database."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.pterodactyl import PteroServer


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ServerMeta(Base):
    __tablename__ = "manager_server_meta"

    server_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("servers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    server: Mapped["PteroServer"] = relationship("PteroServer", back_populates="meta")


class ManagerHost(Base):
    """Unified host registry — see ``docs/HOST_MANAGEMENT_DESIGN.md`` §4.1.

    Each row represents a managed host the manager talks to via Erocraft Agent
    HTTPS pull. ``kind`` identifies the host's role:

    * ``wings_node`` — a Pterodactyl wings node (``pterodactyl_node_id`` set)
    * ``nginx_proxy`` / ``nas`` / ``generic_linux`` — generic agent-managed
      host without a corresponding panel.nodes row

    The encrypted ``agent_token_enc`` is Fernet-sealed with
    ``MANAGER_SECRET_KEY``; plaintext only ever lives in memory during create
    or rotation. ``extra_metadata`` is a free-form JSON sidecar (e.g. mirror
    of generic_host's ``cert_install_targets`` summary for UI rendering).
    """

    __tablename__ = "manager_hosts"
    __table_args__ = (
        UniqueConstraint("pterodactyl_node_id", name="uk_pterodactyl_node"),
        Index("idx_kind", "kind"),
        Index("idx_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_url: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    pterodactyl_node_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    # ``metadata`` is reserved by SQLAlchemy declarative on Base. Use a
    # different attribute name; the on-disk column matches the design doc
    # via the explicit name argument.
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "extra_metadata", JSON, nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    inbound_reachable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class HostAlertSettings(Base):
    """Per-host channel/cooldown overrides. NULL fields = inherit defaults."""

    __tablename__ = "manager_host_alert_settings"

    host_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("manager_hosts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    email_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    email_recipients: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    min_severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notify_resolve: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cooldown_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class HostAlertRule(Base):
    """Per-host per-alert-type rule override. UNIQUE(host_id, alert_type)."""

    __tablename__ = "manager_host_alert_rules"
    __table_args__ = (
        UniqueConstraint("host_id", "alert_type", name="uk_host_type"),
        Index("idx_host_alert_host", "host_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("manager_hosts.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    warning_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    sustain_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class ManagerCertificate(Base):
    """Certificate registry row owned by Manager.

    Manager does not issue certificates in the current phase. ``source_path``
    points at the local acme.sh install directory that contains
    ``fullchain.pem`` and ``privkey.pem``.
    """

    __tablename__ = "manager_certificates"
    __table_args__ = (
        Index("idx_manager_cert_enabled", "enabled"),
        Index("idx_manager_cert_source_path", "source_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    domains: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_not_before: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_not_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_threshold_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class ManagerCertDeployment(Base):
    """Binding between a certificate and an agent-managed host target."""

    __tablename__ = "manager_cert_deployments"
    __table_args__ = (
        UniqueConstraint(
            "certificate_id",
            "host_id",
            "target_name",
            name="uk_manager_cert_deployment_target",
        ),
        Index("idx_manager_cert_deploy_cert", "certificate_id"),
        Index("idx_manager_cert_deploy_host", "host_id"),
        Index("idx_manager_cert_deploy_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    certificate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("manager_certificates.id", ondelete="CASCADE"),
        nullable=False,
    )
    host_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("manager_hosts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Empty string means "the host's default target". For wings_node hosts that
    # is the api.ssl.cert/key pair in /etc/pterodactyl/config.yml.
    target_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    deployed_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deployed_not_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_check_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_deploy_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_deploy_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_deploy_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class ManagerActivityLog(Base):
    __tablename__ = "manager_activity_logs"
    __table_args__ = (
        Index("idx_timestamp", "timestamp"),
        Index("idx_actor", "actor"),
        Index("idx_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    detail_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail_params: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemSetting(Base):
    __tablename__ = "manager_system_settings"
    __table_args__ = (Index("idx_category", "category"),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="runtime")
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="string")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=_utc_now,
        onupdate=_utc_now,
    )


class ManagerPasswordReset(Base):
    __tablename__ = "manager_password_resets"
    __table_args__ = (Index("idx_pw_reset_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ManagerEmailChange(Base):
    __tablename__ = "manager_email_changes"
    __table_args__ = (Index("idx_email_change_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    new_email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ManagerPendingRegistration(Base):
    __tablename__ = "manager_pending_registrations"
    __table_args__ = (
        Index("idx_pr_email", "email"),
        Index("idx_pr_username", "username"),
        Index("uq_pr_lookup_hash", "lookup_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(191), nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ManagerEmailTemplate(Base):
    __tablename__ = "manager_email_templates"

    template_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=_utc_now,
        onupdate=_utc_now,
    )
