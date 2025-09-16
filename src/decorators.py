# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

# ==============================================================================
# Custom Decorators
#
# This module defines custom decorators for use with Flask routes.
# Decorators wrap view functions to add pre-processing logic, such as
# checking user permissions before allowing access to a page.
# ==============================================================================
#
# ==============================================================================
# カスタムデコレータ
#
# このモジュールは、Flaskのルートで使用するカスタムデコレータを定義します。
# デコレータはビュー関数をラップし、ページへのアクセスを許可する前に
# ユーザー権限をチェックするなどの前処理ロジックを追加します。
# ==============================================================================

from functools import wraps
from flask import session, redirect, url_for, flash


def sysop_required(f):
    """
    ユーザーがSysOp (user_level == 5) であることを確認するデコレータ。
    未ログインの場合はログインページへ、権限がない場合はトップページへリダイレクトします。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:  # ログインしているかチェック
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('web.login'))
        if session.get('userlevel') != 5:  # SysOpのレベル(5)かチェック
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('index'))  # ターミナル画面へ
        return f(*args, **kwargs)
    return decorated_function
