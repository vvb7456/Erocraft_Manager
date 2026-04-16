"""Automated scheduler tasks — suspend, delete, and email reminders."""

import time
from datetime import timedelta
from flask import current_app
from app.extensions import db, scheduler
from app.models import PteroServer, ServerMeta
from app.config import config_manager
from app.utils import get_today, log_activity
from app.services import pterodactyl as ptero
from app.services import email as email_service


def init_scheduler(app):
    """Initialise APScheduler and register cron jobs based on config."""
    with app.app_context():
        scheduler.init_app(app)
        _sync_jobs()


def reload_jobs():
    """Re-register cron jobs from current config (hot-reload)."""
    tz = config_manager.get('TIMEZONE', 'Asia/Shanghai')
    if scheduler.app:
        scheduler.app.config['SCHEDULER_TIMEZONE'] = tz
    _sync_jobs()


def _sync_jobs():
    """Add or remove scheduler jobs to match current automation config."""
    cfg = config_manager.config
    run_hour = cfg['AUTOMATION_RUN_HOUR']
    run_minute = cfg['AUTOMATION_RUN_MINUTE']
    email_hour = cfg['AUTOMATION_EMAIL_RUN_HOUR']
    email_minute = cfg['AUTOMATION_EMAIL_RUN_MINUTE']
    tz = cfg.get('TIMEZONE', 'Asia/Shanghai')

    _sync_one_job(
        'auto_suspend_task', _suspend_task, cfg.get('AUTOMATION_SUSPEND_ENABLED'),
        hour=run_hour, minute=run_minute, tz=tz,
    )
    _sync_one_job(
        'auto_delete_task', _delete_task, cfg.get('AUTOMATION_DELETE_ENABLED'),
        hour=run_hour, minute=run_minute, tz=tz,
    )
    _sync_one_job(
        'auto_expiry_reminder_task', _reminder_task, cfg.get('AUTOMATION_EMAIL_ENABLED'),
        hour=email_hour, minute=email_minute, tz=tz, args=['expiry'],
    )
    _sync_one_job(
        'auto_pre_delete_reminder_task', _reminder_task, cfg.get('AUTOMATION_EMAIL_ENABLED'),
        hour=email_hour, minute=email_minute, tz=tz, args=['pre_delete'],
    )


def _sync_one_job(job_id: str, func, enabled: bool, *, hour: int, minute: int, tz: str = 'Asia/Shanghai', args=None):
    """Add or replace a job if enabled, otherwise remove it if it exists."""
    if enabled:
        scheduler.add_job(
            id=job_id, func=func,
            trigger='cron', hour=hour, minute=minute, timezone=tz,
            args=args, replace_existing=True,
        )
    else:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass


# ── Helpers ──

def _servers_by_expiration(target_date):
    """Return PteroServer list whose expiration_date matches target_date."""
    return (
        PteroServer.query
        .join(ServerMeta)
        .filter(ServerMeta.expiration_date == target_date)
        .all()
    )


# ── Tasks ──

def _suspend_task():
    app = scheduler.app
    with app.app_context():
        log_activity('系统', 'automated_suspend_task', '信息', '开始执行自动冻结任务。')
        count = 0
        try:
            yesterday = get_today() - timedelta(days=1)
            servers = (
                PteroServer.query
                .join(ServerMeta)
                .filter(
                    ServerMeta.expiration_date == yesterday,
                    PteroServer.status.is_(None),
                )
                .all()
            )
            if not servers:
                log_activity('系统', 'automated_suspend_task', '信息', '任务完成，没有需要冻结的服务器。')
                return

            for srv in servers:
                if ptero.suspend_server(srv.id):
                    db.session.expire(srv)
                    count += 1
                else:
                    app.logger.error(f"[自动化] 冻结服务器 {srv.id} 失败")

            log_activity('系统', 'automated_suspend_task', '成功', f'任务完成，成功冻结了 {count} 台服务器。')
        except Exception as e:
            log_activity('系统', 'automated_suspend_task', '失败', f'执行冻结任务时发生意外错误: {e}')
            app.logger.error(f"[自动化] 冻结任务出错: {e}", exc_info=True)


def _delete_task():
    app = scheduler.app
    with app.app_context():
        log_activity('系统', 'automated_delete_task', '信息', '开始执行自动删除任务。')
        count = 0
        try:
            threshold = get_today() - timedelta(days=config_manager.get('AUTOMATION_DELETE_DAYS', 14))
            servers = (
                PteroServer.query
                .join(ServerMeta)
                .filter(ServerMeta.expiration_date <= threshold)
                .all()
            )
            if not servers:
                log_activity('系统', 'automated_delete_task', '信息', '任务完成，没有需要删除的服务器。')
                return

            for srv in servers:
                if ptero.delete_server_from_panel(srv.id):
                    count += 1
                else:
                    app.logger.error(f"[自动化] 删除服务器 {srv.id} 失败")
            db.session.expire_all()

            log_activity('系统', 'automated_delete_task', '成功', f'任务完成，成功删除了 {count} 台服务器。')
        except Exception as e:
            log_activity('系统', 'automated_delete_task', '失败', f'执行删除任务时发生意外错误: {e}')
            app.logger.error(f"[自动化] 删除任务出错: {e}", exc_info=True)


def _reminder_task(reminder_type: str):
    app = scheduler.app
    with app.app_context():
        if reminder_type == 'expiry':
            task_name, friendly = 'automated_expiry_reminder', '到期提醒'
            target_date = get_today() + timedelta(days=1)
            tpl = email_service.load_template('reminder')
        elif reminder_type == 'pre_delete':
            task_name, friendly = 'automated_pre_delete_reminder', '删除前提醒'
            delete_days = config_manager.get('AUTOMATION_DELETE_DAYS', 14)
            target_date = get_today() - timedelta(days=delete_days - 1)
            tpl = email_service.load_template('pre_delete')
        else:
            app.logger.error(f"未知提醒类型: {reminder_type}")
            return

        log_activity('系统', task_name, '信息', f'开始执行{friendly}任务。')
        sent_count = 0
        try:
            servers = _servers_by_expiration(target_date)
            if not servers:
                log_activity('系统', task_name, '信息', f'任务完成，没有需要发送{friendly}的服务器。')
                return

            panel_name = config_manager.get('BRAND_NAME', 'Ptero Manager')
            panel_url = config_manager.get('PTERO_PANEL_URL')

            if reminder_type == 'expiry':
                owners: dict[int, list] = {}
                for s in servers:
                    owners.setdefault(s.owner_id, []).append(s)

                for owner_id, owner_servers in owners.items():
                    owner = owner_servers[0].owner
                    if not owner or not owner.email:
                        continue
                    server_list_str = '\n'.join(
                        f"- {s.name} (ID: {s.id})" for s in owner_servers
                    )
                    ctx = {
                        '{{username}}': owner.username,
                        '{{expiration_date}}': target_date.strftime('%Y-%m-%d'),
                        '{{server_count}}': str(len(owner_servers)),
                        '{{server_list}}': server_list_str,
                        '{{panel_name}}': panel_name,
                    }
                    subj, body = email_service.render_template_body(tpl, ctx)
                    ok, _ = email_service.send_email(
                        owner.email, subj, body,
                        f"您好, {owner.username}!",
                        '登录面板处理', panel_url,
                    )
                    if ok:
                        sent_count += 1
                    time.sleep(email_service.get_email_delay())

            elif reminder_type == 'pre_delete':
                deletion_date_str = (get_today() + timedelta(days=1)).strftime('%Y-%m-%d')
                for srv in servers:
                    owner = srv.owner
                    if not owner or not owner.email:
                        continue
                    ctx = {
                        '{{username}}': owner.username,
                        '{{server_name}}': srv.name,
                        '{{server_id}}': str(srv.id),
                        '{{deletion_date}}': deletion_date_str,
                        '{{panel_name}}': panel_name,
                    }
                    subj, body = email_service.render_template_body(tpl, ctx)
                    ok, _ = email_service.send_email(
                        owner.email, subj, body,
                        f"您好, {owner.username}!",
                        '登录面板处理', panel_url,
                    )
                    if ok:
                        sent_count += 1
                    time.sleep(email_service.get_email_delay())

            log_activity('系统', task_name, '成功', f'任务完成，成功发送了 {sent_count} 封{friendly}邮件。')
        except Exception as e:
            log_activity('系统', task_name, '失败', f'执行{friendly}任务时发生意外错误: {e}')
            app.logger.error(f"[自动化] {friendly}任务出错: {e}", exc_info=True)
