"""Typed ORM models that map to Pterodactyl tables."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import bcrypt
from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.manager import ServerMeta


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def parse_json_str_list(raw: str | None, *, strip_empty: bool = False) -> list[str] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        if strip_empty:
            return [str(item) for item in parsed if str(item).strip()]
        return [str(item) for item in parsed]
    return None


def parse_egg_docker_images(raw: str | None, *, accept_list: bool = False) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return {str(k): str(v) for k, v in parsed.items() if isinstance(v, str)}
    if accept_list and isinstance(parsed, list):
        return {str(v): str(v) for v in parsed if v}
    return {}


mount_server = Table(
    "mount_server",
    Base.metadata,
    Column(
        "server_id",
        mysql.INTEGER(unsigned=True),
        ForeignKey(
            "servers.id",
            name="mount_server_server_id_foreign",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    ),
    Column(
        "mount_id",
        mysql.INTEGER(unsigned=True),
        ForeignKey(
            "mounts.id",
            name="mount_server_mount_id_foreign",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    ),
    UniqueConstraint(
        "server_id", "mount_id", name="mount_server_server_id_mount_id_unique"
    ),
)

mount_node = Table(
    "mount_node",
    Base.metadata,
    Column(
        "node_id",
        mysql.INTEGER(unsigned=True),
        ForeignKey(
            "nodes.id",
            name="mount_node_node_id_foreign",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    ),
    Column(
        "mount_id",
        mysql.INTEGER(unsigned=True),
        ForeignKey(
            "mounts.id",
            name="mount_node_mount_id_foreign",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    ),
    UniqueConstraint(
        "node_id", "mount_id", name="mount_node_node_id_mount_id_unique"
    ),
)


class PteroUser(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("uuid", name="users_uuid_unique"),
        UniqueConstraint("email", name="users_email_unique"),
        UniqueConstraint("username", name="users_username_unique"),
        Index("users_external_id_index", "external_id"),
    )

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    external_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    uuid: Mapped[str] = mapped_column(mysql.CHAR(36), nullable=False)
    username: Mapped[str] = mapped_column(String(191), nullable=False)
    email: Mapped[str] = mapped_column(String(191), nullable=False)
    name_first: Mapped[str | None] = mapped_column(String(191), nullable=True)
    name_last: Mapped[str | None] = mapped_column(String(191), nullable=True)
    password: Mapped[str] = mapped_column(Text, nullable=False)
    remember_token: Mapped[str | None] = mapped_column(String(191), nullable=True)
    language: Mapped[str] = mapped_column(mysql.CHAR(5), nullable=False, default="zh")
    root_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Permanent per-user flag (20260619_trial migration). Set to True the
    # first time this user owns a server via ANY path (paid order apply,
    # admin manual create, import) and never reset — even if the server is
    # later deleted. Drives the trial-plan eligibility rule ("trial plans
    # only for users who have never owned a server, once"), which cannot
    # rely on order history because most servers are admin-created from
    # off-platform sales and leave no order row.
    has_owned_server: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    use_totp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_authenticated_at: Mapped[datetime | None] = mapped_column(
        mysql.TIMESTAMP(), nullable=True
    )
    gravatar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)

    servers: Mapped[list["PteroServer"]] = relationship(
        "PteroServer",
        back_populates="owner",
        lazy="selectin",
    )

    def check_password(self, plain_password: str) -> bool:
        stored = self.password
        # 历史用户密码可能带 PHP 风格的 $2y$ 前缀，需兼容归一化为 $2b$ 后再校验。
        if stored.startswith("$2y$"):
            stored = "$2b$" + stored[4:]
        return bcrypt.checkpw(plain_password.encode("utf-8"), stored.encode("utf-8"))

    @staticmethod
    def hash_password_sync(plain_password: str) -> str:
        """Compute a standard ``$2b$`` bcrypt hash (CPU-bound)."""
        return bcrypt.hashpw(
            plain_password.encode("utf-8"),
            bcrypt.gensalt(rounds=10),
        ).decode("utf-8")

    def set_password(self, plain_password: str) -> None:
        self.password = self.hash_password_sync(plain_password)

    @property
    def name(self) -> str:
        return f"{self.name_first or ''} {self.name_last or ''}".strip()


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("short", name="locations_short_unique"),
    )

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    short: Mapped[str] = mapped_column(String(191), nullable=False)
    long: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)


class PanelNode(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint("uuid", name="nodes_uuid_unique"),
        UniqueConstraint("daemon_token_id", name="nodes_daemon_token_id_unique"),
    )

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    uuid: Mapped[str] = mapped_column(mysql.CHAR(36), nullable=False)
    public: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True), nullable=False, default=1
    )
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("locations.id", name="nodes_location_id_foreign"),
        nullable=False,
    )
    fqdn: Mapped[str] = mapped_column(String(191), nullable=False)
    scheme: Mapped[str] = mapped_column(String(191), nullable=False, default="https")
    behind_proxy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    memory: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    memory_overallocate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disk: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    disk_overallocate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upload_size: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=100
    )
    daemon_token_id: Mapped[str] = mapped_column(mysql.CHAR(16), nullable=False)
    daemon_token: Mapped[str] = mapped_column(Text, nullable=False)
    daemon_listen: Mapped[int] = mapped_column(
        "daemonListen", mysql.SMALLINT(unsigned=True), nullable=False, default=8080
    )
    daemon_sftp: Mapped[int] = mapped_column(
        "daemonSFTP", mysql.SMALLINT(unsigned=True), nullable=False, default=2022
    )
    daemon_base: Mapped[str] = mapped_column("daemonBase", String(191), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)

    location: Mapped[Location] = relationship("Location")
    servers: Mapped[list["PteroServer"]] = relationship("PteroServer", back_populates="node")
    mounts: Mapped[list["Mount"]] = relationship("Mount", secondary=mount_node)


class Nest(Base):
    __tablename__ = "nests"
    __table_args__ = (
        UniqueConstraint("uuid", name="services_uuid_unique"),
    )

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    uuid: Mapped[str] = mapped_column(mysql.CHAR(36), nullable=False)
    author: Mapped[str] = mapped_column(mysql.CHAR(191), nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)


class Egg(Base):
    __tablename__ = "eggs"
    __table_args__ = (
        UniqueConstraint("uuid", name="service_options_uuid_unique"),
    )

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    uuid: Mapped[str] = mapped_column(mysql.CHAR(36), nullable=False)
    nest_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("nests.id", name="service_options_nest_id_foreign", ondelete="CASCADE"),
        nullable=False,
    )
    author: Mapped[str] = mapped_column(String(191), nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    features: Mapped[str | None] = mapped_column(
        mysql.LONGTEXT(charset="utf8mb4", collation="utf8mb4_bin"), nullable=True
    )
    docker_images: Mapped[str | None] = mapped_column(
        mysql.LONGTEXT(charset="utf8mb4", collation="utf8mb4_bin"), nullable=True
    )
    file_denylist: Mapped[str | None] = mapped_column(
        mysql.LONGTEXT(charset="utf8mb4", collation="utf8mb4_bin"), nullable=True
    )
    update_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_files: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_startup: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_stop: Mapped[str | None] = mapped_column(String(191), nullable=True)
    config_from: Mapped[int | None] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("eggs.id", name="eggs_config_from_foreign", ondelete="SET NULL"),
        nullable=True,
    )
    startup: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_container: Mapped[str] = mapped_column(String(191), nullable=False, default="alpine:3.4")
    copy_script_from: Mapped[int | None] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("eggs.id", name="eggs_copy_script_from_foreign", ondelete="SET NULL"),
        nullable=True,
    )
    script_entry: Mapped[str] = mapped_column(String(191), nullable=False, default="ash")
    script_is_privileged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    script_install: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    force_outgoing_ip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    @property
    def docker_image(self) -> str:
        return next(
            (value for value in parse_egg_docker_images(self.docker_images).values() if value),
            "",
        )

    def resolve_config_files(self, parent: Egg | None = None) -> str | None:
        if self.config_files is not None or self.config_from is None:
            return self.config_files
        return parent.config_files if parent is not None else None

    def resolve_config_startup(self, parent: Egg | None = None) -> str | None:
        if self.config_startup is not None or self.config_from is None:
            return self.config_startup
        return parent.config_startup if parent is not None else None

    def resolve_config_logs(self, parent: Egg | None = None) -> str | None:
        if self.config_logs is not None or self.config_from is None:
            return self.config_logs
        return parent.config_logs if parent is not None else None

    def resolve_config_stop(self, parent: Egg | None = None) -> str | None:
        if self.config_stop is not None or self.config_from is None:
            return self.config_stop
        return parent.config_stop if parent is not None else None

    def resolve_features(self, parent: Egg | None = None) -> list[str] | None:
        if self.features is not None or self.config_from is None:
            return parse_json_str_list(self.features)
        return parse_json_str_list(parent.features) if parent is not None else None

    def resolve_file_denylist(self, parent: Egg | None = None) -> list[str] | None:
        # Matches Egg.php:getInheritFileDenylistAttribute — unconditionally takes
        # parent's file_denylist whenever config_from is set, ignoring child value.
        if self.config_from is None:
            return parse_json_str_list(self.file_denylist)
        return parse_json_str_list(parent.file_denylist) if parent is not None else None

    def resolve_script_install(self, parent: Egg | None = None) -> str | None:
        if self.script_install is not None or self.copy_script_from is None:
            return self.script_install
        return parent.script_install if parent is not None else None

    def resolve_script_entry(self, parent: Egg | None = None) -> str:
        # Matches Egg.php:getCopyScriptEntryAttribute — unconditionally takes
        # parent's script_entry whenever copy_script_from is set.
        if self.copy_script_from is None:
            return self.script_entry
        return parent.script_entry if parent is not None else self.script_entry

    def resolve_script_container(self, parent: Egg | None = None) -> str:
        # Matches Egg.php:getCopyScriptContainerAttribute — unconditionally takes
        # parent's script_container whenever copy_script_from is set.
        if self.copy_script_from is None:
            return self.script_container
        return parent.script_container if parent is not None else self.script_container


class EggVariable(Base):
    __tablename__ = "egg_variables"

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    egg_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("eggs.id", name="service_variables_egg_id_foreign", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    env_variable: Mapped[str] = mapped_column(String(191), nullable=False)
    default_value: Mapped[str] = mapped_column(Text, nullable=False)
    user_viewable: Mapped[int] = mapped_column(mysql.TINYINT(unsigned=True), nullable=False)
    user_editable: Mapped[int] = mapped_column(mysql.TINYINT(unsigned=True), nullable=False)
    rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)


class ServerVariable(Base):
    __tablename__ = "server_variables"

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    # 实库历史 schema 允许 NULL，业务查询均按 server_id 过滤，保持 Mapped[int] 兼容现有调用方类型注解
    server_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("servers.id", name="server_variables_server_id_foreign", ondelete="CASCADE"),
        nullable=True,
    )
    variable_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey(
            "egg_variables.id",
            name="server_variables_variable_id_foreign",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    variable_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)


class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (
        UniqueConstraint(
            "node_id", "ip", "port", name="allocations_node_id_ip_port_unique"
        ),
    )

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    node_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("nodes.id", name="allocations_node_id_foreign", ondelete="CASCADE"),
        nullable=False,
    )
    ip: Mapped[str] = mapped_column(String(191), nullable=False)
    ip_alias: Mapped[str | None] = mapped_column(Text, nullable=True)
    port: Mapped[int] = mapped_column(mysql.MEDIUMINT(unsigned=True), nullable=False)
    server_id: Mapped[int | None] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey(
            "servers.id",
            name="allocations_server_id_foreign",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(String(191), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)

    # Pterodactyl schema links allocations to servers in two different ways:
    # `allocations.server_id` means an allocation belongs to a server, while
    # `servers.allocation_id` points to the primary allocation for that server.
    # The two FKs form a cycle (Allocation.server_id <-> PteroServer.allocation_id),
    # so we mark this side `post_update=True` to break the unit-of-work
    # dependency cycle and let SQLAlchemy issue a separate UPDATE for the FK.
    server: Mapped[PteroServer | None] = relationship(
        "PteroServer",
        foreign_keys=[server_id],
        lazy="joined",
        post_update=True,
    )
    node: Mapped[PanelNode] = relationship("PanelNode")


class PteroServer(Base):
    __tablename__ = "servers"
    __table_args__ = (
        UniqueConstraint("uuid", name="servers_uuid_unique"),
        UniqueConstraint("uuidShort", name="servers_uuidshort_unique"),
        UniqueConstraint("allocation_id", name="servers_allocation_id_unique"),
        UniqueConstraint("external_id", name="servers_external_id_unique"),
    )

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    external_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    uuid: Mapped[str] = mapped_column(mysql.CHAR(36), nullable=False)
    uuid_short: Mapped[str] = mapped_column("uuidShort", mysql.CHAR(8), nullable=False)
    node_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("nodes.id", name="servers_node_id_foreign"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str | None] = mapped_column(String(191), nullable=True)
    skip_scripts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("users.id", name="servers_owner_id_foreign"),
        nullable=False,
    )
    memory: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=0
    )
    swap: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disk: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=0
    )
    io: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=500
    )
    cpu: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=0
    )
    threads: Mapped[str | None] = mapped_column(String(191), nullable=True)
    oom_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allocation_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("allocations.id", name="servers_allocation_id_foreign"),
        nullable=False,
    )
    nest_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("nests.id", name="servers_nest_id_foreign"),
        nullable=False,
    )
    egg_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("eggs.id", name="servers_egg_id_foreign"),
        nullable=False,
    )
    startup: Mapped[str] = mapped_column(Text, nullable=False)
    image: Mapped[str] = mapped_column(String(191), nullable=False)
    allocation_limit: Mapped[int | None] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=True
    )
    database_limit: Mapped[int | None] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=True, default=0
    )
    backup_limit: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=0
    )
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    installed_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)

    owner: Mapped[PteroUser] = relationship("PteroUser", back_populates="servers", lazy="joined")
    node: Mapped[PanelNode] = relationship("PanelNode", back_populates="servers", lazy="joined")
    allocation: Mapped[Allocation] = relationship(
        "Allocation",
        foreign_keys=[allocation_id],
        lazy="joined",
    )
    meta: Mapped[ServerMeta | None] = relationship(
        "ServerMeta",
        back_populates="server",
        uselist=False,
        lazy="selectin",
    )
    egg: Mapped[Egg] = relationship("Egg", lazy="joined")
    mounts: Mapped[list["Mount"]] = relationship("Mount", secondary=mount_server)

    @property
    def is_suspended(self) -> bool:
        return self.status == "suspended"

    @property
    def expiration_date(self):
        return self.meta.expiration_date if self.meta else None


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("activity_logs_actor_type_actor_id_index", "actor_type", "actor_id"),
        Index("activity_logs_event_index", "event"),
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    batch: Mapped[str | None] = mapped_column(mysql.CHAR(36), nullable=True)
    event: Mapped[str] = mapped_column(String(191), nullable=False)
    ip: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_type: Mapped[str | None] = mapped_column(String(191), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), nullable=True
    )
    api_key_id: Mapped[int | None] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=True
    )
    properties: Mapped[str] = mapped_column(
        mysql.LONGTEXT(charset="utf8mb4", collation="utf8mb4_bin"),
        nullable=False,
        default="{}",
    )
    timestamp: Mapped[datetime] = mapped_column(
        mysql.TIMESTAMP(), nullable=False, default=_utc_now
    )

    subjects: Mapped[list["ActivityLogSubject"]] = relationship(
        "ActivityLogSubject",
        back_populates="activity_log",
        cascade="all, delete-orphan",
    )


class ActivityLogSubject(Base):
    __tablename__ = "activity_log_subjects"
    __table_args__ = (
        Index(
            "activity_log_subjects_subject_type_subject_id_index",
            "subject_type",
            "subject_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    activity_log_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "activity_logs.id",
            name="activity_log_subjects_activity_log_id_foreign",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(191), nullable=False)
    subject_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)

    activity_log: Mapped[ActivityLog] = relationship("ActivityLog", back_populates="subjects")


class Backup(Base):
    """``backups`` row — a per-server backup archive stored on the node."""

    __tablename__ = "backups"
    __table_args__ = (
        UniqueConstraint("uuid", name="backups_uuid_unique"),
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    server_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("servers.id", name="backups_server_id_foreign", ondelete="CASCADE"),
        nullable=False,
    )
    uuid: Mapped[str] = mapped_column(mysql.CHAR(36), nullable=False)
    upload_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    ignored_files: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    disk: Mapped[str] = mapped_column(String(191), nullable=False, default="wings")
    checksum: Mapped[str | None] = mapped_column(String(191), nullable=True)
    bytes: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), nullable=False, default=0
    )
    completed_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)


class UserSshKey(Base):
    __tablename__ = "user_ssh_keys"

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("users.id", name="user_ssh_keys_user_id_foreign", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(191), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)


class Subuser(Base):
    __tablename__ = "subusers"

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("users.id", name="subusers_user_id_foreign", ondelete="CASCADE"),
        nullable=False,
    )
    server_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey("servers.id", name="subusers_server_id_foreign", ondelete="CASCADE"),
        nullable=False,
    )
    permissions: Mapped[str | None] = mapped_column(
        mysql.LONGTEXT(charset="utf8mb4", collation="utf8mb4_bin"), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)

    @property
    def permission_list(self) -> list[str]:
        return parse_json_str_list(self.permissions) or []


class ServerTransfer(Base):
    __tablename__ = "server_transfers"

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    server_id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        ForeignKey(
            "servers.id",
            name="server_transfers_server_id_foreign",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    successful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    old_node: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    new_node: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    old_allocation: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False
    )
    new_allocation: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False
    )
    old_additional_allocations: Mapped[str | None] = mapped_column(
        mysql.LONGTEXT(charset="utf8mb4", collation="utf8mb4_bin"), nullable=True
    )
    new_additional_allocations: Mapped[str | None] = mapped_column(
        mysql.LONGTEXT(charset="utf8mb4", collation="utf8mb4_bin"), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(mysql.TIMESTAMP(), nullable=True)


class Mount(Base):
    __tablename__ = "mounts"
    __table_args__ = (
        UniqueConstraint("id", name="mounts_id_unique"),
        UniqueConstraint("uuid", name="mounts_uuid_unique"),
        UniqueConstraint("name", name="mounts_name_unique"),
    )

    id: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), primary_key=True, autoincrement=True
    )
    uuid: Mapped[str] = mapped_column(mysql.CHAR(36), nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(191), nullable=False)
    target: Mapped[str] = mapped_column(String(191), nullable=False)
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_mountable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
