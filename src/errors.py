# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""カスタムエラーハンドラ。

このモジュールは、404 (Not Found) や 500 (Internal Server Error) といった
一般的なHTTPエラーに対するカスタムエラーページを定義します。これにより、
デフォルトのエラーページよりもユーザーフレンドリーな体験を提供します。
"""

from flask import render_template, request, session
import logging


def register_error_handlers(app):
    """Flaskアプリケーションにカスタムエラーハンドラを登録します。"""

    @app.errorhandler(429)
    def ratelimit_handler(e):
        logging.warning(
            f"Rate limit exceeded for {request.remote_addr} on {request.path}. Limit: {e.description}")
        context = {'username': session.get('username')}
        return render_template('errors/429.html', error=e, context=context), 429

    @app.errorhandler(403)
    def forbidden_error(error):
        context = {'username': session.get('username')}
        return render_template('errors/403.html', context=context), 403

    @app.errorhandler(404)
    def not_found_error(error):
        context = {'username': session.get('username')}
        return render_template('errors/404.html', context=context), 404

    @app.errorhandler(500)
    def internal_error(error):
        logging.error(f"500 Internal Server Error: {error}", exc_info=True)
        context = {'username': session.get('username')}
        return render_template('errors/500.html', context=context), 500
