"""User-facing API routes — accessible to all authenticated users."""

from flask import Blueprint, session, jsonify
from app.models import PteroUser

bp = Blueprint('user_api', __name__)


@bp.route('/me')
def user_me():
    """Return current user's basic info."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    user = PteroUser.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({
        'id': user.id,
        'username': user.username,
        'email': user.email,
    })
