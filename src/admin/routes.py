from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from ..decorators import sysop_required
from .. import database, util

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
    # クエリパラメータからソート順と検索語を取得
    sort_by = request.args.get('sort_by', 'id')
    order = request.args.get('order', 'asc')
    search_term = request.args.get('q', '')

    # 次のソート順を計算
    next_order = 'desc' if order == 'asc' else 'asc'

    users = database.get_all_users(
        sort_by=sort_by, order=order, search_term=search_term)
    return render_template(
        'admin/user_list.html', title='User Management', users=users,
        sort_by=sort_by, order=order, next_order=next_order, search_term=search_term)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@sysop_required
def new_user():
    """新規ユーザー作成ページ"""
    if request.method == 'POST':
        username = request.form.get('name', '').strip().upper()
        password = request.form.get('password')
        level = request.form.get('level', 1, type=int)
        email = request.form.get('email', '').strip()
        comment = request.form.get('comment', '').strip()

        # バリデーション
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('admin/new_user.html', title='Add New User')

        if database.get_user_auth_info(username):
            flash(f"Username '{username}' already exists.", 'danger')
            return render_template('admin/new_user.html', title='Add New User')

        if not (0 <= level <= 5):
            flash('Level must be between 0 and 5.', 'danger')
            return render_template('admin/new_user.html', title='Add New User')

        # ユーザー登録
        salt, hashed_password = util.hash_password(password)
        if database.register_user(username, hashed_password, salt, comment, level, email=email):
            flash(
                f"User '{username}' has been created successfully.", 'success')
            return redirect(url_for('admin.user_list'))
        else:
            flash('Failed to create user.', 'danger')

    return render_template('admin/new_user.html', title='Add New User')


@admin_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@sysop_required
def edit_user(user_id):
    """ユーザー編集ページ"""
    user = database.get_user_by_id(user_id)
    if not user:
        flash(f"User with ID {user_id} not found.", 'danger')
        return redirect(url_for('admin.user_list'))

    if request.method == 'POST':
        # フォームからデータを取得
        new_level = request.form.get('level', type=int)
        new_email = request.form.get('email')
        new_comment = request.form.get('comment')
        new_password = request.form.get('password')

        updates = {
            'level': new_level,
            'email': new_email,
            'comment': new_comment
        }

        if new_password:
            salt, hashed_password = util.hash_password(new_password)
            updates['password'] = hashed_password
            updates['salt'] = salt

        database.update_record('users', updates, {'id': user_id})
        flash(
            f"User '{user['name']}' has been updated successfully.", 'success')
        return redirect(url_for('admin.user_list'))

    return render_template('admin/edit_user.html', title='Edit User', user=user)


@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@sysop_required
def delete_user(user_id):
    """ユーザーを削除する"""
    user_to_delete = database.get_user_by_id(user_id)

    if not user_to_delete:
        flash(f"User with ID {user_id} not found.", 'danger')
        return redirect(url_for('admin.user_list'))

    # 自分自身は削除できない
    if user_to_delete['id'] == session.get('user_id'):
        flash("You cannot delete your own account.", 'danger')
        return redirect(url_for('admin.user_list'))

    # GUESTユーザーは削除できない
    if user_to_delete['name'].upper() == 'GUEST':
        flash("The GUEST account cannot be deleted.", 'danger')
        return redirect(url_for('admin.user_list'))

    if database.delete_user(user_id):
        flash(
            f"User '{user_to_delete['name']}' has been successfully deleted.", 'success')
    else:
        flash(f"Failed to delete user '{user_to_delete['name']}'.", 'danger')

    return redirect(url_for('admin.user_list'))
