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
    # v2 billing: which plan this server is currently bound to. Written by
    # ``_effect_new_purchase`` (and Phase B ``_effect_upgrade``); never written
    # by manual server creation. Renew reads this to look up price + period.
    # See ``docs/BILLING_DESIGN.md`` §3.3.2.
    plan_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Set once when the "server installed" notification email has been sent
    # for this server (or the row was backfilled on first deploy of the
    # feature). Stays set across reinstalls so they don't re-trigger the
    # email — only first-install completion notifies. NULL means "first
    # install pending or notification not yet attempted".
    install_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    server: Mapped["PteroServer"] = relationship("PteroServer", back_populates="meta")


class ManagerHost(Base):
    """Unified host registry — see ``docs/HOST_MANAGEMENT_DESIGN.md`` §4.1.

    Each row represents a managed host the manager talks to via Erocraft Agent
    HTTPS pull. ``kind`` identifies the host's role:

    * ``wings_node`` — a Pterodactyl wings node (``pterodactyl_node_id`` set)
    * ``generic_linux`` / ``synology_dsm`` — generic agent-managed
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
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
        Index("idx_category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
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
        Index("idx_pr_inviter", "inviter_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(191), nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    # Captured at /register time when the URL or form carried a valid
    # invite code. ``invite_code`` stores the literal 8-char string so we
    # can write a referral row at verify-time even if the inviter rotated
    # / disabled their code in between (rare). ``inviter_user_id`` is the
    # resolved user.id snapshot taken at /register; if NULL, no referral
    # is recorded on verify.
    inviter_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invite_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserInviteCode(Base):
    """One invite code per user — lazy-generated on first dashboard view.

    The same code is reused forever; ``disabled_at`` lets admins kill a
    code without removing it (so audit history stays intact). See
    ``docs/REFERRAL_AND_COUPON_DESIGN.md`` §4.1.
    """

    __tablename__ = "manager_user_invite_codes"
    __table_args__ = (
        UniqueConstraint("code", name="uk_invite_code"),
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class UserReferral(Base):
    """Inviter→invitee binding + reward-grant audit row.

    Lifecycle: ``registered`` (created on /register/verify) → ``rewarded``
    (set when ``referral_rewards.try_grant_for_order`` writes the two
    coupons + ``qualifying_order_id``) → ``revoked`` (admin only). The
    UNIQUE on ``invitee_user_id`` makes each new account belong to at
    most one inviter forever.
    """

    __tablename__ = "manager_user_referrals"
    __table_args__ = (
        UniqueConstraint("invitee_user_id", name="uk_referral_invitee"),
        Index("idx_referral_inviter_status", "inviter_user_id", "status"),
        Index("idx_referral_qualifying_order", "qualifying_order_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inviter_user_id: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    invitee_user_id: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    invite_code: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="registered")
    qualifying_order_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    inviter_coupon_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    invitee_coupon_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utc_now, onupdate=_utc_now
    )


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



# ---------------------------------------------------------------------------
# Cloudflare Tunnel — see docs/CLOUDFLARE_TUNNEL_DESIGN.md
# ---------------------------------------------------------------------------


class ManagerHostTunnel(Base):
    """Per-host Cloudflare Tunnel binding (1:1 with manager_hosts).

    Holds the CF account credentials, the chosen zone, and the cloudflared
    install state for one wings host. The CF tunnel UUID + secret are NULL
    until the install flow successfully creates the tunnel.

    The CF API token + tunnel secret are Fernet-encrypted at rest (same
    scheme used elsewhere — :func:`app.core.security.encrypt_value`).
    """

    __tablename__ = "manager_host_tunnels"
    __table_args__ = (
        UniqueConstraint("host_id", name="uk_host_tunnel_host"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("manager_hosts.id", ondelete="CASCADE"),
        nullable=False,
    )
    cf_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cf_api_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    cf_zone_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cf_zone_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cf_tunnel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cf_tunnel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cf_tunnel_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloudflared_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # NOTE: there is intentionally no ``cloudflared_status`` column.
    # Whether cloudflared is actually running is an agent-live signal,
    # not a DB cache. The DB only records what we have told CF
    # (cf_tunnel_id, cf_tunnel_secret_enc, cf_config_version, last_synced_at).
    # See docs/CF_TUNNEL_PSEUDOCODE.md.
    cf_config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class ManagerServerTunnel(Base):
    """Per-server tunnel hostname (1:1 with panel.servers).

    ``server_id`` references panel.servers.id but is **not** a FK (cross-schema
    Pterodactyl table; consistency maintained at application layer via
    pre-delete hooks in :mod:`app.services.server_lifecycle`).

    ``cf_dns_record_id`` is the CF DNS record id we created so we can delete
    it later. ``upstream_port`` is a snapshot of the server's primary
    allocation port at the time tunnel was enabled (refreshed on port change
    via :func:`tunnel_manager.dispatcher.on_server_port_changed`).
    """

    __tablename__ = "manager_server_tunnels"
    __table_args__ = (
        UniqueConstraint("server_id", name="uk_server_tunnel_server"),
        UniqueConstraint("hostname", name="uk_server_tunnel_hostname"),
        Index("ix_server_tunnel_status", "status"),
        Index("ix_server_tunnel_host_tunnel", "host_tunnel_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, nullable=False)
    host_tunnel_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("manager_host_tunnels.id", ondelete="CASCADE"),
        nullable=False,
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    custom_subdomain: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upstream_port: Mapped[int] = mapped_column(Integer, nullable=False)
    upstream_scheme: Mapped[str] = mapped_column(
        String(8), nullable=False, default="http",
    )
    cf_dns_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Lifecycle: only "active" (steady) or "failed" (push_remote_ingress
    # failure). enable/change always set this synchronously; there is no
    # provisioning intermediate state.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now, onupdate=_utc_now,
    )


class ManagerOrphanResource(Base):
    """CF-side resources that have no matching DB row.

    Populated by the reconciler (``app/jobs/tasks/tunnel_reconcile.py``) when
    it sees a CF tunnel or DNS record that doesn't correspond to any manager
    DB row — e.g. due to a half-completed install, an out-of-band Dashboard
    deletion, or a host that was physically destroyed without going through
    the uninstall flow.

    Admins review the list and either delete the CF resource (cleanup) or
    mark it ignored.
    """

    __tablename__ = "manager_orphan_resources"
    __table_args__ = (
        UniqueConstraint(
            "resource_type", "cf_resource_id", name="uk_orphan_resource",
        ),
        Index("ix_orphan_type", "resource_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cf_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cf_zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cf_resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cf_resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utc_now,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
