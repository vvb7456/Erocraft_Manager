"""审计统一为成功或失败，保留历史记录中已知的独立步骤结果。"""

import json

from alembic import op
import sqlalchemy as sa

revision = "20261015_audit_results"
down_revision = "20261014_notification_center"
branch_labels = None
depends_on = None


def _result(action, outcome, target, *, error=None, children=None, facts=None):
    result = {"action": action, "phase": "execution", "outcome": outcome, "target": target}
    if error:
        result["error"] = error if isinstance(error, dict) else {"code": "dependency.failed", "detail": str(error)}
    if children:
        result["children"] = children
    if facts:
        result["facts"] = facts
    return result


def _normalize_operation(result):
    if result.get("outcome") == "unknown":
        result["outcome"] = "failed"
    for child in result.get("children", []):
        _normalize_operation(child)


def _normalize(key, status, params):
    result = params.get("operation")
    if isinstance(result, dict):
        _normalize_operation(result)
        return key, result["outcome"], params

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
        # The old handler always removed the local row, even after remote errors.
        key, outcome = "llm.revoke.local", "success"
    return key, outcome, params


def upgrade() -> None:
    connection = op.get_bind()
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
            key, status, params = _normalize(row["detail_key"] or "", row["status"], params)
            updates.append({"id": row["id"], "key": key, "status": status, "params": json.dumps(params, ensure_ascii=False)})
        connection.execute(sa.text("UPDATE manager_activity_logs SET detail_key=:key, status=:status, detail_params=:params WHERE id=:id"), updates)
        last_id = rows[-1]["id"]


def downgrade() -> None:
    # The old schema accepts both values; discarded status aliases cannot be recovered.
    pass
