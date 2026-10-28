"""从生产订单归因版本升级客服、通知、审计和统一支付。"""

import json

from alembic import op
import sqlalchemy as sa

# 保留开发库已执行的终点编号；生产从此处的父版本直接升级。
revision = "20261022_payment_gateway"
down_revision = "20260902_order_attr"
branch_labels = None
depends_on = None


OBSOLETE_SETTINGS_SQL = sa.text("""
    DELETE FROM manager_system_settings
    WHERE `key` REGEXP '^(ALIPAY_DIRECT_|HUPIJIAO_|WECHAT_PAY_)'
       OR `key` IN (
           'BILLING_REFUND_STUCK_HOURS', 'BILLING_USER_PENDING_ORDER_MAX',
           'LLM_DEFAULT_MODELS', 'NEWAPI_POOL_USER_ID', 'NEWAPI_POOL_USER_ACCESS_TOKEN',
           'NOTIFY_BILLING_ENABLED', 'NOTIFY_CERTIFICATE_ENABLED', 'NOTIFY_MIN_SEVERITY',
           'NOTIFY_MONITORING_ENABLED', 'NOTIFY_RESOLVED', 'NOTIFY_SUPPORT_ENABLED',
           'NOTIFY_SYSTEM_ENABLED', 'WECOM_RECIPIENTS'
       )
""")


def upgrade() -> None:
    op.create_table(
        "manager_support_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("last_message_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("user_read_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("admin_read_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "manager_support_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.BigInteger(), sa.ForeignKey("manager_support_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("image_type", sa.String(32)),
        sa.Column("image_path", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "sender_id", "client_id", name="uq_support_message_retry"),
    )
    op.create_index("ix_support_messages_conversation", "manager_support_messages", ["conversation_id", "id"])

    op.create_table(
        "manager_notification_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("gateway_key", sa.String(64), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime()),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("last_error", sa.String(500)),
        sa.Column("message_id", sa.String(255)),
        sa.Column("channel", sa.String(16), nullable=False, server_default="wecom"),
    )
    op.create_index("uq_notification_dedup", "manager_notification_deliveries", ["dedup_key"], unique=True)
    op.create_index("ix_notification_due", "manager_notification_deliveries", ["status", "available_at"])
    op.create_index("ix_notification_topic", "manager_notification_deliveries", ["topic", "created_at"])
    op.create_index("ix_notification_recipient", "manager_notification_deliveries", ["recipient", "last_attempt_at"])
    op.create_table(
        "manager_notification_issues",
        sa.Column("key", sa.String(190), primary_key=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime()),
        sa.Column("muted_until", sa.DateTime()),
        sa.Column("resolved_at", sa.DateTime()),
    )
    op.execute("""
        ALTER TABLE manager_host_alerts
          ADD COLUMN acknowledged_at DATETIME NULL,
          ADD COLUMN muted_until DATETIME NULL
    """)
    op.alter_column("manager_host_alert_rules", "enabled", existing_type=sa.Boolean(), nullable=True)
    op.add_column("manager_cert_deployments", sa.Column("unhealthy_since", sa.DateTime()))
    op.execute("UPDATE manager_cert_deployments SET unhealthy_since = COALESCE(last_check_at, created_at) WHERE status <> 'synced'")

    op.create_table(
        "manager_miniprogram_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("appid", sa.String(32), nullable=False),
        sa.Column("openid", sa.String(128, collation="utf8mb4_bin"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("appid", "openid", name="uq_mini_wechat_identity"),
        sa.UniqueConstraint("appid", "user_id", name="uq_mini_user_identity"),
    )
    op.create_table(
        "manager_miniprogram_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("appid", sa.String(32), nullable=False),
        sa.Column("openid", sa.String(128, collation="utf8mb4_bin"), nullable=False),
        sa.Column("binding_id", sa.BigInteger(), sa.ForeignKey("manager_miniprogram_bindings.id", ondelete="CASCADE")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_manager_miniprogram_sessions_binding_id", "manager_miniprogram_sessions", ["binding_id"])
    op.create_index("ix_manager_miniprogram_sessions_expires_at", "manager_miniprogram_sessions", ["expires_at"])

    op.execute(sa.text("""
        ALTER TABLE manager_billing_orders
          ALTER COLUMN channel SET DEFAULT '',
          DROP INDEX uk_billing_orders_active_user,
          DROP COLUMN active_user_lock,
          ADD COLUMN active_user_lock INT GENERATED ALWAYS AS (
            CASE WHEN status = 'pending' THEN user_id END
          ) VIRTUAL,
          ADD UNIQUE KEY uk_billing_orders_active_user (active_user_lock),
          ADD COLUMN close_reason VARCHAR(16) NULL
    """))
    op.create_table(
        "manager_billing_payments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("manager_billing_orders.id"), nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), sa.ForeignKey("manager_billing_invoices.id"), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False, unique=True),
        sa.Column("request_body", sa.JSON(), nullable=False),
        sa.Column("gateway_id", sa.String(64), unique=True),
        sa.Column("checkout_url", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("method", sa.String(32)),
        sa.Column("close_requested", sa.Boolean(), nullable=False),
        sa.Column("channel_refunding", sa.Boolean(), nullable=False),
        sa.Column("transaction_id", sa.String(64)),
        sa.Column("paid_at", sa.DateTime()),
        sa.Column("delivery_confirmed_at", sa.DateTime()),
        sa.Column("last_error", sa.String(500)),
        sa.Column("synced_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_manager_billing_payments_order_id", "manager_billing_payments", ["order_id"])
    op.execute("""
        ALTER TABLE manager_billing_invoice_transactions
          ADD COLUMN payment_id BIGINT NULL,
          ADD CONSTRAINT uq_billing_transaction_payment UNIQUE (payment_id),
          ADD FOREIGN KEY (payment_id) REFERENCES manager_billing_payments (id)
    """)
    # 旧退款恢复字段仅留作历史存档，新退款不再写入。
    op.execute("""
        ALTER TABLE manager_billing_refunds
          ADD COLUMN payment_id BIGINT NULL,
          ADD KEY ix_manager_billing_refunds_payment_id (payment_id),
          ADD FOREIGN KEY (payment_id) REFERENCES manager_billing_payments (id),
          ADD COLUMN request_id VARCHAR(100) NULL,
          ADD CONSTRAINT uq_billing_refund_request UNIQUE (request_id),
          ADD COLUMN automatic BOOL NOT NULL DEFAULT FALSE,
          MODIFY COLUMN transaction_id BIGINT NULL,
          MODIFY COLUMN status VARCHAR(32) NOT NULL,
          MODIFY COLUMN previous_order_status VARCHAR(32) NULL DEFAULT NULL
    """)
    op.execute("""
        ALTER TABLE manager_billing_payment_events
          ADD COLUMN gateway_event_id VARCHAR(64) NULL,
          ADD CONSTRAINT uq_billing_gateway_event UNIQUE (gateway_event_id)
    """)
    # 先复制仍在使用的旧通知验签资料；密文不依赖配置键名。
    for new_key, old_key in (
        ("LEGACY_ALIPAY_APPID", "ALIPAY_DIRECT_APPID"),
        ("LEGACY_ALIPAY_PUBLIC_KEY", "ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY"),
    ):
        op.execute(sa.text("""
            INSERT INTO manager_system_settings (`key`, category, value_type, value_text, value_encrypted, version)
            SELECT :new_key, category, value_type, value_text, value_encrypted, version
            FROM manager_system_settings WHERE `key` = :old_key
        """).bindparams(new_key=new_key, old_key=old_key))
    op.execute(OBSOLETE_SETTINGS_SQL)
    _migrate_audit_logs(op.get_bind())


def _result(action, outcome, target, *, error=None, children=None, facts=None):
    result = {"action": action, "phase": "execution", "outcome": outcome, "target": target}
    if error:
        result["error"] = error if isinstance(error, dict) else {"code": "dependency.failed", "detail": str(error)}
    if children:
        result["children"] = children
    if facts:
        result["facts"] = facts
    return result


def _normalize_audit(key, status, params):
    params = params.copy()
    outcome = "success" if status in {"success", "ok", "info"} else "failed"
    target = {key: params[key] for key in ("server_id", "host_id", "node_id", "certificate_id", "deployment_id", "order_id") if params.get(key) is not None}
    if key in {"login.email_not_verified", "billing.referral.template_missing", "install_notify.no_email"}:
        outcome = "failed"
    elif key in {"monitoring.alert.fired", "monitoring.alert.resolved", "host.probe.failed"}:
        outcome = "success"
    elif key in {"automated_suspend_finished", "automated_delete_finished", "automated_trial_expire_finished"} or key.startswith("batch_"):
        outcome = "failed" if params.get("failed") else "success"
    elif key == "install_notify.run":
        outcome = "failed" if params.get("scanned", 0) > params.get("sent", 0) + params.get("skipped", 0) else "success"
    elif key == "billing.order.force_applied":
        outcome = "success" if params.get("result") in {"applied", "retry_scheduled"} else "failed"
    elif key == "billing.order.refund_reconciled":
        outcome = "failed" if params.get("outcome") in {"failed", "exhausted"} else "success"
    elif key in {"cert.create", "cert.acme.register", "cert.patch"}:
        outcome = "success"
        scan = params.get("source_scan")
        if isinstance(scan, dict):
            child = _result("certificate.scan", "success", target, facts={"valid": bool(scan.get("ok"))}, error=scan.get("error"))
            child["phase"] = "observation"
            params["operation"] = _result("certificate.update" if key == "cert.patch" else "certificate.create", outcome, target, children=[child])
    elif key == "admin_server.owner.update" and status in {"partial", "warning"}:
        outcome = "success"
        params["operation"] = _result("server.owner.update", outcome, target, children=[_result("wings.owner.deauthorize", "failed", target)])
    elif key == "node.wings_config.update":
        outcome = "failed" if params.get("wings_error") or (params.get("wings_pushed") and params.get("wings_applied") is False) else outcome
        params["operation"] = _result("wings.configuration.update", outcome, target, error=params.get("wings_error"), children=[_result("wings.configuration.save", "success", target)])
    elif key == "node.daemon_token.reset":
        outcome = "success" if params.get("new_token_id") else "failed"
        restart = params.get("auto_restart") or {}
        children = []
        if restart.get("attempted"):
            children.append(_result("wings.restart_and_verify", "success" if restart.get("restarted") and restart.get("self_check") else "failed", target, error=restart.get("error") or restart.get("self_check_error")))
        params["operation"] = _result("wings.token.rotate", outcome, target, error=params.get("wings_error"), children=children)
    elif key == "tunnel.uninstall.ok":
        outcome = "success"
        if "agent_ok" in params:
            params["operation"] = _result("tunnel.uninstall", outcome, target, children=[_result("tunnel.node_cleanup", "success" if params["agent_ok"] else "failed", target, error=params.get("agent_error"))])
    elif key in {"llm.revoke", "llm.admin.revoke"}:
        # 旧实现即使远端撤销失败，也会删除本地记录。
        key, outcome = "llm.revoke.local", "success"
    return key, outcome, params


def _migrate_audit_logs(connection) -> None:
    last_id = 0
    while True:
        rows = connection.execute(sa.text(
            "SELECT id, detail_key, status, detail_params FROM manager_activity_logs WHERE id > :id ORDER BY id LIMIT 500"
        ), {"id": last_id}).mappings().all()
        if not rows:
            break
        updates = []
        for row in rows:
            params = json.loads(row["detail_params"] or "{}")
            key, status, normalized = _normalize_audit(row["detail_key"] or "", row["status"], params)
            if key != row["detail_key"] or status != row["status"] or normalized != params:
                updates.append({"id": row["id"], "key": key, "status": status, "params": json.dumps(normalized, ensure_ascii=False)})
        if updates:
            connection.execute(sa.text("UPDATE manager_activity_logs SET detail_key=:key, status=:status, detail_params=:params WHERE id=:id"), updates)
        last_id = rows[-1]["id"]


def downgrade() -> None:
    raise RuntimeError("本迁移包含支付及退款记录，请从备份恢复，不能删除财务数据回退。")
