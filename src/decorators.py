from functools import wraps
from flask import session, redirect, url_for, flash


def sysop_required(f):
    """
    ユーザーがSysOp (user_level == 9) であることを確認するデコレータ。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))  # webapp.pyのlogin関数にリダイレクト
        if session.get('userlevel') != 5:  # SysOpのレベルは5です
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('index'))  # ターミナル画面へ
        return f(*args, **kwargs)
    return decorated_function
