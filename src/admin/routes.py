from flask import Blueprint, render_template
from ..decorators import sysop_required
from .. import database

# ブループリントを作成
# 'admin' はブループリントの名前
# __name__ はPythonのおまじない
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/')
@sysop_required
def dashboard():
    """管理画面のダッシュボード"""
    return render_template('admin/dashboard.html', title='Admin Dashboard')


@admin_bp.route('/users')
@sysop_required
def user_list():
    """ユーザー一覧ページ"""
    users = database.get_all_users()
    return render_template('admin/user_list.html', title='User Management', users=users)
