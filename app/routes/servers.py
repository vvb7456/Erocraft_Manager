"""Server routes — CRUD, renew, suspend, batch operations."""

import time
from datetime import date, timedelta
from flask import Blueprint, request, jsonify, session
from app.extensions import db
from app.models import PteroServer, ServerMeta, PteroUser
from app.config import config_manager
from app.utils import get_today, log_activity
from app.services import pterodactyl as ptero
from app.services import email as email_svc
from sqlalchemy import or_, asc, desc

bp = Blueprint('servers', __name__)


# ── Helpers ──

def _classify_server(expiration_date, today):
    days_left = None
    status_label = 'permanent'
    if expiration_date is not None:
        days_left = (expiration_date - today).days
        if days_left < 0:
            status_label = 'expired'
        elif days_left <= 7:
            status_label = 'expiring_soon'
        else:
            status_label = 'normal'
    return days_left, status_label


def _get_or_create_meta(server_id):
    """Get or create a ServerMeta record for the given server."""
    meta = ServerMeta.query.get(server_id)
    if not meta:
        meta = ServerMeta(server_id=server_id)
        db.session.add(meta)
    return meta


def _filtered_servers(args):
    """Build a filtered/sorted PteroServer query from request args."""
    query = PteroServer.query.outerjoin(ServerMeta).join(PteroUser)
    filter_status = args.get('filter_status', 'all')
    sort_by = args.get('sort_by', 'expiration_date')
    sort_order = args.get('sort_order', 'asc')
    search = args.get('search_term', '').strip()

    if search:
        query = query.filter(or_(
            PteroServer.name.ilike(f'%{search}%'),
            PteroUser.username.ilike(f'%{search}%'),
        ))

    today = get_today()
    if filter_status == 'normal':
        query = query.filter(ServerMeta.expiration_date >= today)
    elif filter_status == 'expiring_soon':
        query = query.filter(ServerMeta.expiration_date.between(today, today + timedelta(days=7)))
    elif filter_status == 'expired':
        query = query.filter(ServerMeta.expiration_date < today)
    elif filter_status == 'permanent':
        query = query.filter(or_(ServerMeta.expiration_date.is_(None), ServerMeta.server_id.is_(None)))
    elif filter_status == 'suspended':
        query = query.filter(PteroServer.status == 'suspended')

    sort_map = {
        'id': PteroServer.id,
        'ptero_server_id': PteroServer.id,
        'name': PteroServer.name,
        'server_name': PteroServer.name,
        'owner_username': PteroUser.username,
        'expiration_date': ServerMeta.expiration_date,
    }
    col = sort_map.get(sort_by, PteroServer.id)

    if sort_by == 'expiration_date':
        # MySQL/MariaDB doesn't support NULLS LAST; use IS NULL trick
        if sort_order == 'asc':
            query = query.order_by(col.is_(None), col.asc())
        else:
            query = query.order_by(col.isnot(None), col.desc())
    else:
        query = query.order_by(desc(col) if sort_order == 'desc' else asc(col))

    return query.all()


# ── List ──

@bp.route('/servers')
def list_servers():
    servers = _filtered_servers(request.args)
    today = get_today()
    panel_url = config_manager.get('PTERO_PANEL_URL', '').rstrip('/')
    result = []
    for s in servers:
        exp_date = s.expiration_date  # via meta relationship
        days_left, status_label = _classify_server(exp_date, today)
        result.append({
            'pteroId': s.id,
            'uuid': s.uuid,
            'name': s.name,
            'ownerId': s.owner_id,
            'ownerUsername': s.owner.username if s.owner else '未知',
            'expirationDate': exp_date.isoformat() if exp_date else None,
            'daysLeft': days_left,
            'statusLabel': status_label,
            'isSuspended': s.is_suspended,
            'panelUrl': f"{panel_url}/server/{s.uuid}" if s.uuid else None,
        })
    return jsonify({'servers': result, 'panelUrl': panel_url})


# ── Renew ──

@bp.route('/servers/<int:ptero_id>/renew', methods=['POST'])
def renew(ptero_id):
    server = PteroServer.query.get(ptero_id)
    if not server:
        return jsonify({'error': '服务器不存在'}), 404

    data = request.get_json(silent=True) or {}
    target_date_str = data.get('date')
    if not target_date_str:
        return jsonify({'error': '缺少必填字段: date (YYYY-MM-DD)'}), 400

    try:
        new_date = date.fromisoformat(target_date_str)
    except (ValueError, TypeError):
        return jsonify({'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400

    actor = session.get('admin_username', '未知管理员')
    was_suspended = server.is_suspended

    meta = _get_or_create_meta(ptero_id)
    meta.expiration_date = new_date
    db.session.commit()
    ptero.update_server_description(ptero_id, new_date)
    log_activity(actor, 'set_expiry', '成功',
                 f"服务器 '{server.name}' (ID: {ptero_id}) 到期时间设为 {new_date.strftime('%Y-%m-%d')}。")

    if was_suspended and ptero.unsuspend_server(ptero_id):
        db.session.expire(server)
        log_activity(actor, 'unsuspend', '信息',
                     f"服务器 '{server.name}' (ID: {ptero_id}) 续期后自动解冻。")

    return jsonify({'message': f"已续期至 {new_date.strftime('%Y-%m-%d')}", 'expirationDate': new_date.isoformat()})


# ── Suspend / Unsuspend ──

@bp.route('/servers/<int:ptero_id>/suspend', methods=['POST'])
def toggle_suspend(ptero_id):
    server = PteroServer.query.get(ptero_id)
    if not server:
        return jsonify({'error': '服务器不存在'}), 404

    actor = session.get('admin_username', '未知管理员')
    is_suspended = server.is_suspended
    action = 'unsuspend' if is_suspended else 'suspend'
    action_text = '解冻' if is_suspended else '冻结'
    ok = ptero.unsuspend_server(ptero_id) if is_suspended else ptero.suspend_server(ptero_id)

    if ok:
        db.session.expire(server)
        log_activity(actor, action, '成功', f"成功{action_text}服务器 '{server.name}' (ID: {ptero_id})。")
        return jsonify({'message': f"服务器已{action_text}", 'isSuspended': not is_suspended})

    log_activity(actor, action, '失败', f"{action_text}服务器 '{server.name}' (ID: {ptero_id}) 失败。")
    return jsonify({'error': f'{action_text}失败'}), 500


# ── Delete ──

@bp.route('/servers/<int:ptero_id>', methods=['DELETE'])
def delete(ptero_id):
    server = PteroServer.query.get(ptero_id)
    server_name = server.name if server else f"ID {ptero_id}"
    actor = session.get('admin_username', '未知管理员')

    if ptero.delete_server_from_panel(ptero_id):
        db.session.expire_all()
        log_activity(actor, 'delete_server', '成功', f"成功删除服务器 '{server_name}' (ID: {ptero_id})。")
        return jsonify({'message': f"服务器 '{server_name}' 已删除"})

    log_activity(actor, 'delete_server', '失败', f"删除服务器 '{server_name}' (ID: {ptero_id}) 失败。")
    return jsonify({'error': '删除失败'}), 500


# ── Set Date (edit) ──

@bp.route('/servers/<int:ptero_id>', methods=['PUT'])
def update_server(ptero_id):
    server = PteroServer.query.get(ptero_id)
    if not server:
        return jsonify({'error': '服务器不存在'}), 404

    data = request.get_json(silent=True) or {}
    actor = session.get('admin_username', '未知管理员')

    new_date_str = data.get('expirationDate')
    if new_date_str:
        from datetime import date as date_cls
        try:
            parts = new_date_str.split('-')
            new_date = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            return jsonify({'error': '日期格式无效'}), 400

        meta = _get_or_create_meta(ptero_id)
        meta.expiration_date = new_date
        db.session.commit()
        ptero.update_server_description(ptero_id, new_date)
        log_activity(actor, 'set_expiry', '成功',
                     f"服务器 '{server.name}' (ID: {ptero_id}) 日期设为 {new_date.strftime('%Y-%m-%d')}。")
        return jsonify({'message': f"到期日期已更新为 {new_date.strftime('%Y-%m-%d')}"})

    return jsonify({'error': '无有效更新内容'}), 400


# ── Create ──

@bp.route('/servers', methods=['POST'])
def create():
    data = request.get_json(silent=True) or {}
    actor = session.get('admin_username', '未知管理员')
    cfg = config_manager.config

    required = ['user_id', 'server_name', 'egg_id', 'startup_command', 'node_id', 'allocation_id', 'expiration_days']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'缺少必填字段: {field}'}), 400

    try:
        server_data = ptero.create_server(
            user_id=int(data['user_id']),
            server_name=data['server_name'].strip(),
            expiration_days=int(data['expiration_days']),
            node_id=int(data['node_id']),
            allocation_id=int(data['allocation_id']),
            egg_id=int(data['egg_id']),
            docker_image=data.get('docker_image', cfg.get('DOCKER_IMAGE', '')).strip(),
            startup_command=data['startup_command'].strip(),
            environment=data.get('environment', {}),
            cpu=int(data.get('cpu', cfg.get('DEFAULT_CPU', 100))),
            memory=int(data.get('memory', cfg.get('DEFAULT_MEMORY', 1024))),
            disk=int(data.get('disk', cfg.get('DEFAULT_DISK', 5120))),
            databases=int(data.get('databases', cfg.get('DEFAULT_DATABASES', 0))),
            backups=int(data.get('backups', cfg.get('DEFAULT_BACKUPS', 0))),
            allocations=int(data.get('allocations', cfg.get('DEFAULT_ALLOCATIONS', 1))),
        )
    except (ValueError, TypeError):
        return jsonify({'error': '参数类型无效'}), 400

    if server_data:
        log_activity(actor, 'create_server', '成功',
                     f"创建服务器 '{data['server_name']}' (用户ID: {data['user_id']})。")
        return jsonify({'message': f"服务器 '{data['server_name']}' 创建成功", 'server': server_data}), 201

    log_activity(actor, 'create_server', '失败', f"创建服务器 '{data['server_name']}' 失败。")
    return jsonify({'error': '创建服务器失败'}), 500


# ── Batch ──

@bp.route('/servers/batch', methods=['POST'])
def batch():
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    server_ids = data.get('serverIds', [])
    if not action or not server_ids:
        return jsonify({'error': '未选择操作或服务器'}), 400

    actor = session.get('admin_username', '未知管理员')
    success, errors = 0, 0

    if action in ('suspend', 'unsuspend'):
        action_text = '冻结' if action == 'suspend' else '解冻'
        log_activity(actor, f'batch_{action}', '信息', f"批量{action_text}，目标: {len(server_ids)} 台。")
        fn = ptero.suspend_server if action == 'suspend' else ptero.unsuspend_server
        for sid in server_ids:
            if fn(sid):
                success += 1
            else:
                errors += 1
        db.session.expire_all()
        log_activity(actor, f'batch_{action}', '成功', f"批量{action_text}完成。成功: {success}, 失败: {errors}。")

    elif action == 'renew':
        days = data.get('days')
        if not days or not isinstance(days, int) or days <= 0:
            return jsonify({'error': '续期天数无效'}), 400
        log_activity(actor, 'batch_renew', '信息', f"批量续期 {days} 天，目标: {len(server_ids)} 台。")
        today = get_today()
        servers = PteroServer.query.filter(PteroServer.id.in_(server_ids)).all()
        for srv in servers:
            was_suspended = srv.is_suspended
            exp_date = srv.expiration_date
            base = today if (exp_date and exp_date < today) else (exp_date or today)
            new_date = base + timedelta(days=days)
            meta = _get_or_create_meta(srv.id)
            meta.expiration_date = new_date
            ptero.update_server_description(srv.id, new_date)
            success += 1
            if was_suspended and ptero.unsuspend_server(srv.id):
                db.session.expire(srv)
        db.session.commit()
        log_activity(actor, 'batch_renew', '成功', f"批量续期完成。成功: {success}, 失败: {errors}。")

    elif action == 'delete':
        log_activity(actor, 'batch_delete', '信息', f"批量删除，目标: {len(server_ids)} 台。")
        for sid in server_ids:
            if ptero.delete_server_from_panel(sid):
                success += 1
            else:
                errors += 1
        db.session.expire_all()
        log_activity(actor, 'batch_delete', '成功', f"批量删除完成。成功: {success}, 失败: {errors}。")

    elif action == 'email':
        log_activity(actor, 'batch_email', '信息', f"批量发送邮件，目标: {len(server_ids)} 台。")
        tpl = email_svc.load_template('bulk')
        servers = PteroServer.query.filter(PteroServer.id.in_(server_ids)).all()
        panel_name = config_manager.get('BRAND_NAME', 'Ptero Manager')
        panel_url = config_manager.get('PTERO_PANEL_URL', '')

        for srv in servers:
            owner = srv.owner
            if not owner or not owner.email:
                errors += 1
                continue
            exp_date = srv.expiration_date
            ctx = {
                '{{panel_name}}': panel_name,
                '{{username}}': owner.username,
                '{{email}}': owner.email,
                '{{server_name}}': srv.name,
                '{{server_id}}': str(srv.id),
                '{{expiration_date}}': exp_date.strftime('%Y-%m-%d') if exp_date else '永久',
            }
            subj, body = email_svc.render_template_body(tpl, ctx)
            ok, _ = email_svc.send_email(
                owner.email, subj, body,
                f"您好, {owner.username}!",
                '登录面板查看', panel_url,
            )
            if ok:
                success += 1
            else:
                errors += 1
            time.sleep(email_svc.get_email_delay())
        log_activity(actor, 'batch_email', '成功', f"批量邮件完成。成功: {success}, 失败: {errors}。")

    else:
        return jsonify({'error': f'未知操作: {action}'}), 400

    return jsonify({'message': f'操作完成：成功 {success}，失败 {errors}', 'success': success, 'failed': errors})
