"""Authentication middleware — before_request hook."""

from flask import session, request, jsonify


def init_auth(app):
    """Register the before_request auth check on *app*."""

    @app.before_request
    def check_auth():
        # Public paths that never require authentication
        if request.path.startswith('/static/'):
            return None

        # Auth API endpoints are public
        if request.path in ('/api/login', '/api/me', '/api/version', '/api/logout'):
            return None

        if not session.get('admin_user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized'}), 401
            # For non-API requests (SPA fallback), let them through — the Vue
            # router will handle redirect to login.
            return None
