# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
管理画面 (Admin Panel) のルーティング定義

このモジュールは、Flask Blueprint を使用して、BBSの管理機能に関する
全てのWebルート（例: /admin/dashboard, /admin/users）を定義します。
"""

import json
import os
from datetime import datetime, timedelta
import time
import logging
from .. import database, util, backup_util, plugin_manager, terminal_handler
import psutil
from flask import Blueprint, render_template, request, flash, redirect, url_for, session, send_from_directory, g, current_app
from ..decorators import sysop_required

import toml
import shutil

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/bbs_list', methods=['GET', 'POST'])
@sysop_required
def bbs_list():
    """
    BBSリンクの管理ページ。リンクの追加、削除、承認状態の変更を処理します。
    """
    if request.method == 'POST':
        action = request.form.get('action')
        link_id = request.form.get('id')
        name = request.form.get('name')
        url = request.form.get('url')
        description = request.form.get('description', '')

        if action == 'add':
            if name and url:
                if database.add_bbs_link(name, url, description, source='sysop', submitted_by=session.get('user_id')):
                    flash('BBS link added successfully.', 'success')
                else:
                    flash('Failed to add BBS link. URL might already exist.', 'danger')
            else:
                flash('Name and URL are required.', 'warning')
        elif action == 'delete':
            if link_id:
                if database.delete_bbs_link(link_id):
                    flash('BBS link deleted successfully.', 'success')
                else:
                    flash('Failed to delete BBS link.', 'danger')
        elif action == 'approve':
            if link_id and database.update_bbs_link_status(link_id, 'approved'):
                flash('BBS link approved.', 'success')
            else:
                flash('Failed to approve BBS link.', 'danger')
        elif action == 'reject':
            if link_id and database.update_bbs_link_status(link_id, 'rejected'):
                flash('BBS link rejected.', 'success')
            else:
                flash('Failed to reject BBS link.', 'danger')
        elif action == 'unapprove':
            if link_id and database.update_bbs_link_status(link_id, 'pending'):
                flash('BBS link has been returned to pending status.', 'success')
            else:
                flash('Failed to unapprove BBS link.', 'danger')
        elif action == 'requeue':
            if link_id and database.update_bbs_link_status(link_id, 'pending'):
                flash('BBS link has been set to pending for re-evaluation.', 'success')
            else:
                flash('Failed to set link to pending.', 'danger')
        return redirect(url_for('admin.bbs_list'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    sort_by = request.args.get('sort_by', 'status')
    order = request.args.get('order', 'asc')
    next_order = 'desc' if order == 'asc' else 'asc'

    try:
        links, total_items = database.get_all_bbs_links_for_admin(
            page=page, per_page=per_page, sort_by=sort_by, order=order)
        total_pages = (total_items + per_page - 1) // per_page
    except Exception as e:
        flash(f"Error retrieving BBS link list: {e}", 'danger')
        links = []
        total_items = 0
        total_pages = 0

    search_params = {
        'sort_by': sort_by,
        'order': order,
        'per_page': per_page
    }
    search_params_for_per_page = {k: v for k,
                                  v in request.args.items() if k != 'per_page'}

    pagination = {
        'page': page, 'per_page': per_page, 'total_items': total_items,
        'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages
    }

    title = util.get_text_by_key(
        'admin.bbs_list.title', session.get('menu_mode', '2'), 'BBS List Management')
    return render_template(
        'admin/bbs_list.html', title=title, links=links, pagination=pagination,
        sort_by=sort_by, order=order, next_order=next_order,
        search_params=search_params, search_params_for_per_page=search_params_for_per_page
    )


@admin_bp.route('/bbs_list/edit/<int:link_id>', methods=['GET', 'POST'])
@sysop_required
def edit_bbs_link(link_id):
    """
    BBSリンクの編集ページ。
    """
    link = database.bbs_list_manager.get_by_id(link_id)
    if not link:
        flash('BBS link not found.', 'danger')
        return redirect(url_for('admin.bbs_list'))

    if request.method == 'POST':
        name = request.form.get('name')
        url = request.form.get('url')
        description = request.form.get('description', '')

        if name and url:
            if database.update_bbs_link(link_id, name, url, description):
                flash('BBS link updated successfully.', 'success')
                return redirect(url_for('admin.bbs_list'))
            else:
                flash('Failed to update BBS link.', 'danger')
        else:
            flash('Name and URL are required.', 'warning')
        link.update(name=name, url=url, description=description)

    title = f"Edit BBS Link: {link['name']}"
    return render_template('admin/edit_bbs_link.html', title=title, link=link)


BACKUP_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'backups'))
os.makedirs(BACKUP_DIR, exist_ok=True)


def _process_texts_for_mode(node, menu_mode):
    """
    YAMLから読み込んだ辞書を再帰的に処理し、指定されたmenu_modeのテキストだけを抽出します。
    これにより、テンプレート側では g.texts.dashboard.title のようにシンプルにアクセスできます。

    Recursively processes a dictionary loaded from YAML to extract text for the specified menu_mode.
    """
    if isinstance(node, dict):
        # 'mode1', 'mode2', 'mode3' のようなキーを持つ末端の辞書かチェック
        mode_key = f"mode_{menu_mode}"
        if mode_key in node:
            return node[mode_key]
        else:
            return {key: _process_texts_for_mode(value, menu_mode) for key, value in node.items()}
    return node


@admin_bp.before_request
def load_admin_texts():
    """
    各リクエストの前に、ユーザーの言語設定に応じてテキストデータをロードします。
    """
    menu_mode = session.get('menu_mode', '3')
    g.texts = _process_texts_for_mode(util.load_master_text_data(), menu_mode)


@admin_bp.route('/')
@sysop_required
def dashboard():
    """
    管理画面のメインページ。システムの統計情報やアクティビティを表示します。
    """
    online_count = len(terminal_handler.get_webapp_online_members())

    stats = {
        'total_users': database.get_total_user_count(),
        'total_boards': database.get_total_board_count(),
        'total_articles': database.get_total_article_count(),
        'online_users': online_count
    }

    disk_info = shutil.disk_usage('/')
    memory_info = psutil.virtual_memory()
    system_health = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'memory_percent': memory_info.percent,
        'memory_used_gb': f"{memory_info.used / (1024**3):.1f}",
        'memory_total_gb': f"{memory_info.total / (1024**3):.1f}",
        'disk_percent': (disk_info.used / disk_info.total) * 100,
        'disk_used_gb': f"{disk_info.used / (1024**3):.1f}",
        'disk_total_gb': f"{disk_info.total / (1024**3):.1f}",
    }

    labels = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
              for i in range(6, -1, -1)]

    user_data_raw = database.get_daily_user_registrations(days=7)
    user_data_map = {item['registration_date'].strftime(
        '%Y-%m-%d'): item['count'] for item in user_data_raw} if user_data_raw else {}
    user_counts = [user_data_map.get(label, 0) for label in labels]

    article_data_raw = database.get_daily_article_posts(days=7)
    article_data_map = {item['post_date'].strftime(
        '%Y-%m-%d'): item['count'] for item in article_data_raw} if article_data_raw else {}
    article_counts = [article_data_map.get(label, 0) for label in labels]

    chart_data = {
        'labels': labels,
        'user_registrations': user_counts,
        'article_posts': article_counts,
    }

    return render_template('admin/dashboard.html',
                           title=g.texts.get('dashboard', {}).get(
                               'title', 'Dashboard'),
                           stats=stats,
                           chart_data=json.dumps(chart_data),
                           system_health=system_health)


@admin_bp.route('/who')
@sysop_required
def who_online():
    """
    現在オンラインのユーザー一覧ページ。セッションの強制切断も可能です。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)

    online_members_raw = terminal_handler.get_webapp_online_members()

    online_list = []
    current_time = time.time()
    for sid, member_data in online_members_raw.items():
        connect_time = member_data.get('connect_time', current_time)
        duration_seconds = current_time - connect_time
        member_data['duration_seconds'] = duration_seconds
        # 人間が読みやすい形式に変換
        minutes, seconds = divmod(duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        member_data['duration_str'] = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
        online_list.append(member_data)

    sort_by = request.args.get('sort_by', 'connect_time')
    order = request.args.get('order', 'asc')
    reverse = (order == 'desc')

    def sort_key(item):
        key = item.get(sort_by)
        return str(key).lower() if isinstance(key, str) else key if key is not None else 0

    online_list.sort(key=sort_key, reverse=reverse)

    next_order = 'desc' if order == 'asc' else 'asc'

    total_items = len(online_list)
    total_pages = (total_items + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated_list = online_list[start:end]

    search_params = {
        'sort_by': sort_by,
        'order': order,
        'per_page': per_page
    }
    search_params_for_per_page = {k: v for k,
                                  v in request.args.items() if k != 'per_page'}

    pagination = {
        'page': page,
        'per_page': per_page,
        'total_items': total_items,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages
    }

    return render_template(
        'admin/who_online.html',
        title=g.texts.get('who_online', {}).get('title', "Who's Online"),
        online_list=paginated_list,
        pagination=pagination,
        sort_by=sort_by,
        order=order, next_order=next_order,
        search_params=search_params,
        search_params_for_per_page=search_params_for_per_page
    )


@admin_bp.route('/who/kick/<sid>', methods=['POST'])
@sysop_required
def kick_user(sid):
    """
    指定されたセッションIDを持つユーザーの接続を強制的に切断します。
    """
    from ..factory import socketio

    online_members = terminal_handler.get_webapp_online_members()
    member_to_kick = online_members.get(sid)
    display_name = member_to_kick.get(
        'display_name', f'session {sid}') if member_to_kick else f'session {sid}'

    kicked = False
    if sid in terminal_handler.client_states:
        socketio.disconnect(sid)
        kicked = True

    if kicked:
        flash(f"User '{display_name}' has been kicked.", 'success')
    else:
        flash(
            f"Failed to kick user '{display_name}'. They may have already disconnected.", 'warning')

    return redirect(url_for('admin.who_online'))


@admin_bp.route('/users')
@sysop_required
def user_list():
    """
    登録ユーザーの一覧ページ。検索、ソート機能付き。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    sort_by = request.args.get('sort_by', 'id')
    order = request.args.get('order', 'asc')
    search_term = request.args.get('q', '')

    next_order = 'desc' if order == 'asc' else 'asc'

    try:
        users, total_items = database.get_all_users(
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            order=order,
            search_term=search_term
        )
        total_pages = (total_items + per_page - 1) // per_page
    except Exception as e:
        flash(f"Error retrieving user list: {e}", 'danger')
        users = []
        total_items = 0
        total_pages = 0

    search_params = {
        'q': search_term,
        'sort_by': sort_by,
        'order': order,
        'per_page': per_page
    }
    search_params_for_per_page = {k: v for k,
                                  v in request.args.items() if k != 'per_page'}

    pagination = {
        'page': page,
        'per_page': per_page,
        'total_items': total_items,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages
    }

    return render_template(
        'admin/user_list.html', title='User Management', users=users, pagination=pagination,
        sort_by=sort_by, order=order, next_order=next_order, search_params=search_params,
        search_params_for_per_page=search_params_for_per_page)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@sysop_required
def new_user():
    """
    新規ユーザー作成ページ。
    """
    if request.method == 'POST':
        username = request.form.get('name', '').strip().upper()
        password = request.form.get('password')
        level = request.form.get('level', 1, type=int)
        email = request.form.get('email', '').strip()
        comment = request.form.get('comment', '').strip()

        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('admin/new_user.html', title='Add New User')

        if database.get_user_auth_info(username):
            flash(f"Username '{username}' already exists.", 'danger')
            return render_template('admin/new_user.html', title='Add New User')

        if not (0 <= level <= 5):
            flash('Level must be between 0 and 5.', 'danger')
            return render_template('admin/new_user.html', title='Add New User')

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
    """
    既存ユーザーの編集ページ。
    """
    edit_user_texts = g.texts.get('admin_edit_user', {})

    user = database.get_user_by_id(user_id)
    if not user:
        flash(f"User with ID {user_id} not found.", 'danger')
        return redirect(url_for('admin.user_list'))

    if request.method == 'POST':
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

    passkeys = database.get_passkeys_by_user(user_id)

    return render_template(
        'admin/edit_user.html',
        title=edit_user_texts.get('title', 'Edit User'),
        user=user,
        passkeys=passkeys
    )


@admin_bp.route('/users/edit/<int:user_id>/delete_passkey/<int:passkey_id>', methods=['POST'])
@sysop_required
def delete_user_passkey(user_id, passkey_id):
    """
    指定されたユーザーのPasskeyを削除します。
    """
    if database.delete_passkey_by_id_and_user_id(passkey_id, user_id):
        flash(g.texts.get('admin_edit_user', {}).get(
            'flash_passkey_deleted', "Passkey has been deleted."), 'success')
    else:
        flash(g.texts.get('admin_edit_user', {}).get(
            'flash_passkey_delete_failed', "Failed to delete Passkey."), 'danger')
    return redirect(url_for('admin.edit_user', user_id=user_id))


@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@sysop_required
def delete_user(user_id):
    """指定されたユーザーをデータベースから削除します。"""
    user_to_delete = database.get_user_by_id(user_id)

    if not user_to_delete:
        flash(f"User with ID {user_id} not found.", 'danger')
        return redirect(url_for('admin.user_list'))

    if user_to_delete['id'] == session.get('user_id'):
        flash("You cannot delete your own account.", 'danger')
        return redirect(url_for('admin.user_list'))

    if user_to_delete['name'].upper() == 'GUEST':
        flash("The GUEST account cannot be deleted.", 'danger')
        return redirect(url_for('admin.user_list'))

    if database.delete_user(user_id):
        flash(
            f"User '{user_to_delete['name']}' has been successfully deleted.", 'success')
    else:
        flash(f"Failed to delete user '{user_to_delete['name']}'.", 'danger')

    return redirect(url_for('admin.user_list'))


@admin_bp.route('/boards')
@sysop_required
def board_list():
    """
    登録掲示板の一覧ページ。検索、ソート機能付き。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    sort_by = request.args.get('sort_by', 'shortcut_id')
    order = request.args.get('order', 'asc')
    search_term = request.args.get('q', '')

    next_order = 'desc' if order == 'asc' else 'asc'

    try:
        boards_from_db, total_items = database.get_all_boards_for_sysop_list(
            page=page, per_page=per_page, sort_by=sort_by, order=order, search_term=search_term)
        total_pages = (total_items + per_page - 1) // per_page
    except Exception as e:
        flash(f"Error retrieving board list: {e}", 'danger')
        boards_from_db = []
        total_items = 0
        total_pages = 0

    search_params = {
        'q': search_term,
        'sort_by': sort_by,
        'order': order,
        'per_page': per_page
    }
    search_params_for_per_page = {k: v for k,
                                  v in request.args.items() if k != 'per_page'}

    pagination = {
        'page': page, 'per_page': per_page, 'total_items': total_items,
        'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages
    }

    enriched_boards = []

    if boards_from_db:
        operator_ids_to_fetch = set()
        for board in boards_from_db:
            try:
                operator_ids = json.loads(board.get('operators') or '[]')
                if operator_ids:
                    operator_ids_to_fetch.update(operator_ids)
            except (json.JSONDecodeError, TypeError):
                continue

        id_to_name_map = database.get_user_names_from_user_ids(
            list(operator_ids_to_fetch))

        for board in boards_from_db:
            mutable_board = dict(board)
            try:
                operator_ids = json.loads(
                    mutable_board.get('operators') or '[]')
                operator_names = [id_to_name_map.get(
                    op_id, f"(ID:{op_id})") for op_id in operator_ids]
                mutable_board['operator_names_str'] = ", ".join(
                    operator_names) if operator_names else 'N/A'
            except (json.JSONDecodeError, TypeError):
                mutable_board['operator_names_str'] = '(Error)'
            enriched_boards.append(mutable_board)

    if sort_by == 'operators':
        enriched_boards.sort(key=lambda x: x.get(
            'operator_names_str', ''), reverse=(order == 'desc'))

    return render_template(
        'admin/board_list.html', title='Board Management', boards=enriched_boards, pagination=pagination,
        sort_by=sort_by, order=order, next_order=next_order, search_params=search_params,
        search_params_for_per_page=search_params_for_per_page)


@admin_bp.route('/boards/new', methods=['GET', 'POST'])
@sysop_required
def new_board():
    """
    新規掲示板作成ページ。
    """
    if request.method == 'POST':
        shortcut_id = request.form.get('shortcut_id', '').strip()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        board_type = request.form.get('board_type', 'simple')
        default_permission = request.form.get('default_permission', 'open')
        read_level = request.form.get('read_level', 1, type=int)
        write_level = request.form.get('write_level', 1, type=int)
        allow_attachments = 1 if 'allow_attachments' in request.form else 0
        allowed_extensions = request.form.get(
            'allowed_extensions', '').strip() or None
        max_size_mb = request.form.get('max_attachment_size_mb')
        max_attachment_size_mb = int(
            max_size_mb) if max_size_mb and max_size_mb.isdigit() else None
        max_threads = request.form.get('max_threads', 99999, type=int)
        max_replies = request.form.get('max_replies', 999, type=int)

        if not shortcut_id or not name:
            flash('Shortcut ID and Board Name are required.', 'danger')
            return render_template('admin/new_board.html', title='Add New Board')

        if database.get_board_by_shortcut_id(shortcut_id):
            flash(f"Shortcut ID '{shortcut_id}' already exists.", 'danger')
            return render_template('admin/new_board.html', title='Add New Board')

        if not (1 <= max_threads <= 99999):
            flash('Max Threads must be between 1 and 99999.', 'danger')
            return render_template('admin/new_board.html', title='Add New Board')

        if board_type == 'thread':
            if not (1 <= max_replies <= 999):
                flash(
                    'Max Replies must be between 1 and 999 for thread boards.', 'danger')
                return render_template('admin/new_board.html', title='Add New Board')
        else:
            max_replies = 0  # simple board has no replies

        sysop_user_id = session.get('user_id')
        operators_json = json.dumps([sysop_user_id]) if sysop_user_id else '[]'

        if database.create_board_entry(shortcut_id, name, description, operators_json, default_permission, "", "active", read_level, write_level, board_type, allow_attachments, allowed_extensions, max_attachment_size_mb, max_threads, max_replies):
            flash(f"Board '{name}' has been created successfully.", 'success')
            return redirect(url_for('admin.board_list'))
        else:
            flash('Failed to create board.', 'danger')

    return render_template('admin/new_board.html', title='Add New Board')


@admin_bp.route('/boards/edit/<int:board_id>', methods=['GET', 'POST'])
@sysop_required
def edit_board(board_id):
    """
    既存の掲示板の編集ページ。
    """
    board = database.get_board_by_id(board_id)
    if not board:
        flash(f"Board with ID {board_id} not found.", 'danger')
        return redirect(url_for('admin.board_list'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        kanban_body = request.form.get('kanban_body', '').strip()
        default_permission = request.form.get('default_permission', 'open')
        read_level = request.form.get('read_level', 1, type=int)
        write_level = request.form.get('write_level', 1, type=int)
        allow_attachments = 1 if 'allow_attachments' in request.form else 0
        allowed_extensions = request.form.get(
            'allowed_extensions', '').strip() or None
        max_size_mb_str = request.form.get('max_attachment_size_mb')
        max_attachment_size_mb = int(
            max_size_mb_str) if max_size_mb_str and max_size_mb_str.isdigit() else None
        operators_str = request.form.get('operators', '').strip()
        max_threads = request.form.get('max_threads', 99999, type=int)
        max_replies = request.form.get('max_replies', 999, type=int)

        new_operator_ids = []
        if operators_str:
            operator_names = [name.strip().upper()
                              for name in operators_str.split(',') if name.strip()]
            all_users, _ = database.get_all_users(
                per_page=9999)  # Get all users
            user_map = {user['name'].upper(): user['id']
                        for user in all_users} if all_users else {}

            invalid_names = []
            for op_name in operator_names:
                if op_name in user_map:
                    new_operator_ids.append(user_map[op_name])
                else:
                    invalid_names.append(op_name)

            if invalid_names:
                flash(
                    f"The following operator names were not found: {', '.join(invalid_names)}", 'danger')
                return render_template('admin/edit_board.html', title='Edit Board', board=board)

        permission_users_str = request.form.get('permission_users', '').strip()
        new_permission_user_ids = []
        if permission_users_str:
            permission_user_names = [perm_user_name.strip().upper()
                                     for perm_user_name in permission_users_str.split(',') if perm_user_name.strip()]
            # user_map is already available from operator processing
            invalid_perm_names = []
            for perm_user_name in permission_user_names:
                if perm_user_name in user_map:
                    new_permission_user_ids.append(user_map[perm_user_name])
                else:
                    invalid_perm_names.append(perm_user_name)
            if invalid_perm_names:
                flash(
                    f"The following B/W list user names were not found: {', '.join(invalid_perm_names)}", 'danger')
                return render_template('admin/edit_board.html', title='Edit Board', board=board)

        if not name:
            flash('Board Name is required.', 'danger')
            return render_template('admin/edit_board.html', title='Edit Board', board=board)

        updates = {
            'name': name, 'description': description, 'kanban_body': kanban_body,
            'default_permission': default_permission, 'read_level': read_level, 'write_level': write_level,
            'allow_attachments': allow_attachments, 'allowed_extensions': allowed_extensions,
            'max_attachment_size_mb': max_attachment_size_mb,
            'operators': json.dumps(new_operator_ids),
            'max_threads': max_threads,
            'max_replies': max_replies if board.get('board_type') == 'thread' else 0
        }

        if database.update_record('boards', updates, {'id': board_id}):
            database.delete_board_permissions_by_board_id(board_id)

            if new_permission_user_ids:
                board_default_permission = updates.get(
                    'default_permission', board.get('default_permission'))
                access_level_to_set = "deny" if board_default_permission == "open" else "allow"

                for user_id_to_add in new_permission_user_ids:
                    database.add_board_permission(
                        board_id, str(user_id_to_add), access_level_to_set)
            flash(f"Board '{name}' has been updated successfully.", 'success')
        else:
            flash(f"Failed to update board '{name}'.", 'danger')

        return redirect(url_for('admin.board_list'))

    current_operator_ids_json = board.get('operators', '[]')
    try:
        current_operator_ids = json.loads(current_operator_ids_json)
        if current_operator_ids:
            id_to_name_map = database.get_user_names_from_user_ids(
                current_operator_ids)
            operator_names = [id_to_name_map.get(
                op_id, f"ID:{op_id}") for op_id in current_operator_ids]
            board['operators_str'] = ", ".join(operator_names)
    except (json.JSONDecodeError, TypeError):
        board['operators_str'] = ""

    current_permissions = database.get_board_permissions(board_id)
    board['permission_users_str'] = ""
    if current_permissions:
        user_ids_in_list = [perm['user_id'] for perm in current_permissions]
        user_ids_in_list_int = [
            int(uid) for uid in user_ids_in_list if str(uid).isdigit()]
        id_to_name_map = database.get_user_names_from_user_ids(
            user_ids_in_list_int)
        user_names = [id_to_name_map.get(
            int(uid), f"ID:{uid}") for uid in user_ids_in_list]
        board['permission_users_str'] = ", ".join(user_names)

    return render_template('admin/edit_board.html', title='Edit Board', board=board)


@admin_bp.route('/boards/delete/<int:board_id>', methods=['POST'])
@sysop_required
def delete_board(board_id):
    """
    指定された掲示板と関連する全データを物理削除します。
    """
    board_to_delete = database.get_board_by_id(board_id)

    if not board_to_delete:
        flash(f"Board with ID {board_id} not found.", 'danger')
        return redirect(url_for('admin.board_list'))

    if database.delete_board_and_related_data(board_id):
        flash(
            f"Board '{board_to_delete['name']}' and all related data have been successfully deleted.", 'success')
    else:
        flash(f"Failed to delete board '{board_to_delete['name']}'.", 'danger')

    return redirect(url_for('admin.board_list'))


@admin_bp.route('/articles', methods=['GET'])
@sysop_required
def article_search():
    """
    全掲示板を横断して記事を検索するページ。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    keyword = request.args.get('q', '')
    author_name = request.args.get('author', '')

    articles = []
    total_items = 0
    total_pages = 0
    article_id_search = None

    if keyword or author_name:
        author_id = None
        author_name_guest = None
        if author_name:
            user = database.get_user_auth_info(author_name)
            if user:
                author_id = user['id']
            else:
                author_name_guest = author_name

        if keyword and keyword.lower().startswith('id:'):
            try:
                article_id_search = int(keyword.split(':')[1])
            except (ValueError, IndexError):
                article_id_search = None

        articles_from_db, total_items = database.search_all_articles(
            page=page,
            per_page=per_page,
            keyword=keyword,
            author_id=author_id,
            author_name_guest=author_name_guest,
            article_id=article_id_search
        )

        total_pages = (total_items + per_page - 1) // per_page

        if articles_from_db:
            user_ids_to_fetch = {
                art['user_id'] for art in articles_from_db if str(art['user_id']).isdigit()}
            id_to_name_map = database.get_user_names_from_user_ids(
                list(user_ids_to_fetch))

            for art in articles_from_db:
                mutable_art = dict(art)
                user_id_str = str(mutable_art['user_id'])
                if user_id_str.isdigit():
                    mutable_art['author_display_name'] = id_to_name_map.get(
                        int(user_id_str), f"(ID:{user_id_str})")
                else:
                    mutable_art['author_display_name'] = user_id_str
                articles.append(mutable_art)

    search_params = {
        'q': keyword,
        'author': author_name,
        'per_page': per_page
    }
    search_params_for_per_page = {k: v for k,
                                  v in request.args.items() if k != 'per_page'}

    pagination = {
        'page': page, 'per_page': per_page, 'total_items': total_items,
        'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages
    }

    return render_template('admin/article_search.html',
                           title='Article Management',
                           articles=articles,
                           pagination=pagination,
                           search_params=search_params,
                           search_params_for_per_page=search_params_for_per_page,
                           search_keyword=keyword,
                           search_author=author_name)


@admin_bp.route('/articles/delete/<int:article_id>', methods=['POST'])
@sysop_required
def delete_article(article_id):
    """
    指定された記事の削除フラグをトグルします（論理削除/復元）。
    """
    article = database.get_article_by_id(article_id)
    if not article:
        flash(f"Article ID {article_id} not found.", 'danger')
        return redirect(request.referrer or url_for('admin.article_search'))

    was_deleted = article['is_deleted']

    if database.toggle_article_deleted_status(article_id):
        if was_deleted:
            flash(f"Article ID {article_id} has been restored.", 'success')
        else:
            flash(
                f"Article ID {article_id} has been marked as deleted.", 'success')
    else:
        flash(
            f"Failed to update status for article ID {article_id}.", 'danger')

    return redirect(request.referrer or url_for('admin.article_search'))


@admin_bp.route('/articles/bulk-action', methods=['POST'])
@sysop_required
def bulk_action_articles():
    """
    選択された複数の記事に対して、一括で論理削除または復元を実行します。
    """
    action = request.form.get('action')
    selected_ids_str = request.form.getlist('selected_articles')

    if not action or not selected_ids_str:
        flash('No action or no articles selected.', 'warning')
        return redirect(request.referrer or url_for('admin.article_search'))

    selected_ids = [int(id_str)
                    for id_str in selected_ids_str if id_str.isdigit()]

    if not selected_ids:
        flash('No valid articles selected.', 'warning')
        return redirect(request.referrer or url_for('admin.article_search'))

    if action == 'delete':
        updated_count = database.bulk_update_articles_deleted_status(
            selected_ids, 1)
        flash(f"{updated_count} articles have been marked as deleted.", 'success')
    elif action == 'restore':
        updated_count = database.bulk_update_articles_deleted_status(
            selected_ids, 0)
        flash(f"{updated_count} articles have been restored.", 'success')
    else:
        flash('Invalid action.', 'danger')

    return redirect(request.referrer or url_for('admin.article_search'))


@admin_bp.route('/attachments')
@sysop_required
def attachment_list():
    """
    アップロードされた全添付ファイルの一覧と、隔離されたファイルを表示します。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    sort_by = request.args.get('sort_by', 'created_at')
    order = request.args.get('order', 'desc')

    next_order = 'desc' if order == 'asc' else 'asc'

    try:
        articles_with_attachments, total_items = database.get_all_articles_with_attachments(
            page=page, per_page=per_page, sort_by=sort_by, order=order)
        total_pages = (total_items + per_page - 1) // per_page
    except Exception as e:
        flash(f"Error retrieving attachment list: {e}", 'danger')
        articles_with_attachments = []
        total_items = 0
        total_pages = 0

    enriched_attachments = []
    if articles_with_attachments:
        user_ids_to_fetch = {art['user_id'] for art in articles_with_attachments if str(
            art['user_id']).isdigit()}
        id_to_name_map = database.get_user_names_from_user_ids(
            list(user_ids_to_fetch))

        attachment_dir = util.app_config.get('WEBAPP', {}).get(
            'ATTACHMENT_UPLOAD_DIR', 'data/attachments')

        for art in articles_with_attachments:
            mutable_art = dict(art)
            user_id_str = str(mutable_art['user_id'])
            if user_id_str.isdigit():
                mutable_art['author_display_name'] = id_to_name_map.get(
                    int(user_id_str), f"(ID:{user_id_str})")
            else:
                mutable_art['author_display_name'] = user_id_str

            filepath = os.path.join(attachment_dir, art['attachment_filename'])
            is_safe, scan_message = util.scan_file_with_clamav(filepath)
            mutable_art['scan_status'] = 'safe' if is_safe else 'infected'
            mutable_art['scan_message'] = scan_message

            enriched_attachments.append(mutable_art)

    quarantined_files = []
    quarantine_dir_rel = util.app_config.get('clamav', {}).get(
        'quarantine_directory', 'data/quarantine')
    quarantine_dir_abs = os.path.join(
        current_app.config['PROJECT_ROOT'], quarantine_dir_rel)
    log_file_path = os.path.join(quarantine_dir_abs, 'quarantine_log.json')
    try:
        if os.path.exists(log_file_path):
            with open(log_file_path, 'r', encoding='utf-8') as f:
                quarantined_files = json.load(f)
            if isinstance(quarantined_files, list):
                quarantined_files.sort(key=lambda x: x.get(
                    'timestamp', 0), reverse=True)
    except (json.JSONDecodeError, IOError) as e:
        flash(f"Could not read quarantine log: {e}", 'danger')  # noqa

    search_params = {'sort_by': sort_by, 'order': order, 'per_page': per_page}
    search_params_for_per_page = {k: v for k,
                                  v in request.args.items() if k != 'per_page'}

    pagination = {'page': page, 'per_page': per_page, 'total_items': total_items,
                  'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages}

    return render_template('admin/attachment_list.html', title='Attachment Management', attachments=enriched_attachments, quarantined_files=quarantined_files,
                           pagination=pagination, sort_by=sort_by, order=order, next_order=next_order,
                           search_params=search_params, search_params_for_per_page=search_params_for_per_page)


@admin_bp.route('/attachments/quarantine/delete/<path:filename>', methods=['POST'])
@sysop_required
def delete_quarantined_file(filename):
    """Deletes a specific file from the quarantine directory and its log entry."""
    quarantine_dir_rel = util.app_config.get('clamav', {}).get(
        'quarantine_directory', 'data/quarantine')
    quarantine_dir_abs = os.path.join(
        current_app.config['PROJECT_ROOT'], quarantine_dir_rel)
    filepath = os.path.join(quarantine_dir_abs, filename)
    log_file_path = os.path.join(quarantine_dir_abs, 'quarantine_log.json')

    try:
        if os.path.exists(filepath) and os.path.isfile(filepath):
            os.remove(filepath)
    except OSError as e:
        flash(f"Error deleting file '{filename}': {e}", 'danger')
        return redirect(url_for('admin.attachment_list'))

    try:
        if os.path.exists(log_file_path):
            with open(log_file_path, 'r+', encoding='utf-8') as f:
                logs = json.load(f)
                updated_logs = [log for log in logs if log.get(
                    'unique_filename') != filename]
                f.seek(0)
                f.truncate()
                json.dump(updated_logs, f, indent=4)
            flash(
                f"Quarantined file '{filename}' and its log entry have been deleted.", 'success')
    except (IOError, json.JSONDecodeError) as e:
        flash(
            f"File was deleted, but failed to update quarantine log: {e}", 'danger')

    return redirect(url_for('admin.attachment_list'))


@admin_bp.route('/settings', methods=['GET', 'POST'])
@sysop_required
def system_settings():
    """
    システム全体の設定ページ。各機能の最低アクセスレベルなどを変更します。
    """

    if request.method == 'POST':
        settings_to_update = {
            'bbs': request.form.get('bbs', type=int),
            'chat': request.form.get('chat', type=int),
            'mail': request.form.get('mail', type=int),
            'telegram': request.form.get('telegram', type=int),
            'userpref': request.form.get('userpref', type=int),
            'who': request.form.get('who', type=int),
            'hamlet': request.form.get('hamlet', type=int),
            'default_exploration_list': request.form.get('default_exploration_list', '').strip(),
            'login_message': request.form.get('login_message', '').strip(),
            'online_signup_enabled': 1 if 'online_signup_enabled' in request.form else 0
        }

        for key in ['bbs', 'chat', 'mail', 'telegram', 'userpref', 'who', 'hamlet']:
            if not (0 <= settings_to_update[key] <= 5):
                flash(
                    f"Invalid level for {key}. Must be between 0 and 5.", 'danger')
                current_settings = database.read_server_pref() or {}
                return render_template('admin/system_settings.html', title='System Settings', settings=current_settings)

        if database.update_record('server_pref', settings_to_update, {'id': 1}):
            flash('System settings have been updated successfully.', 'success')
        else:
            flash('Failed to update system settings.', 'danger')
        return redirect(url_for('admin.system_settings'))

    all_boards, _ = database.get_all_boards_for_sysop_list(per_page=9999)
    all_board_ids = [board['shortcut_id']
                     for board in all_boards] if all_boards else []

    current_settings = database.read_server_pref() or {}
    return render_template('admin/system_settings.html', title='System Settings', settings=current_settings, all_board_ids=all_board_ids)


@admin_bp.route('/backup', methods=['GET', 'POST'])
@sysop_required
def backup_management():
    """
    バックアップ管理ページ。手動バックアップや自動バックアップ設定を行います。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)

    if request.method == 'POST':
        if request.form.get('action') == 'save_schedule':
            is_enabled = 'schedule_enabled' in request.form
            cron_string = request.form.get('schedule_cron', '0 3 * * *')

            if database.update_backup_schedule(is_enabled, cron_string):
                flash('Backup schedule updated successfully.', 'success')
            else:
                flash('Failed to update backup schedule.', 'danger')
            return redirect(url_for('admin.backup_management'))

    schedule_settings = database.read_server_pref()

    backups = []
    try:
        for filename in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if filename.endswith('.tar.gz'):
                filepath = os.path.join(BACKUP_DIR, filename)
                try:
                    stat = os.stat(filepath)
                    backups.append({
                        'filename': filename,
                        'size': util.format_file_size(stat.st_size),
                        'created_at': datetime.fromtimestamp(stat.st_mtime)
                    })
                except OSError:
                    continue
    except Exception as e:
        flash(f'Error retrieving backup list: {e}', 'danger')

    total_items = len(backups)
    total_pages = (total_items + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated_backups = backups[start:end]

    search_params = {
        'per_page': per_page
    }
    search_params_for_per_page = {}  # No other params to pass

    pagination = {
        'page': page,
        'per_page': per_page,
        'total_items': total_items,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages
    }

    return render_template('admin/backup.html', title="Backup Management", backups=paginated_backups,
                           pagination=pagination, search_params=search_params,
                           search_params_for_per_page=search_params_for_per_page, schedule_settings=schedule_settings)


@admin_bp.route('/backup/create', methods=['POST'])
@sysop_required
def create_backup_route():
    """
    手動で新しいバックアップを作成します。
    """
    try:
        filename = backup_util.create_backup()
        if filename:
            flash(f'Backup file "{filename}" created successfully.', 'success')
        else:
            flash('Backup creation failed. Please check the logs for details.', 'error')
    except Exception as e:
        flash(
            f'An unexpected error occurred during backup creation: {e}', 'error')

    return redirect(url_for('admin.backup_management'))


@admin_bp.route('/backup/download/<path:filename>')
@sysop_required
def download_backup(filename):
    """
    指定されたバックアップファイルをダウンロードさせます。
    """
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)


@admin_bp.route('/backup/delete/<path:filename>', methods=['POST'])
@sysop_required
def delete_backup(filename):
    """
    指定されたバックアップファイルをサーバーから物理削除します。
    """
    try:
        filepath = os.path.join(BACKUP_DIR, filename)
        if not os.path.abspath(filepath).startswith(os.path.abspath(BACKUP_DIR)):
            flash('Invalid file path.', 'danger')
            return redirect(url_for('admin.backup_management'))

        if os.path.exists(filepath) and os.path.isfile(filepath):
            os.remove(filepath)
            flash(f'Backup file "{filename}" has been deleted.', 'success')
        else:
            flash(f'File "{filename}" not found.', 'warning')
    except Exception as e:
        flash(f'An error occurred while deleting the file: {e}', 'error')

    return redirect(url_for('admin.backup_management'))


@admin_bp.route('/backup/restore/<path:filename>', methods=['POST'])
@sysop_required
def restore_from_backup(filename):
    """
    指定されたバックアップファイルからデータをリストアし、サーバーを再起動します。
    """
    try:
        success = backup_util.restore_from_backup(filename)
        if success:
            flash(
                f'Restore from backup "{filename}" has started. The server will restart automatically upon completion.', 'success')

            def restart_server():
                import time
                time.sleep(3)  # flashメッセージがブラウザに届くのを待つ
                os._exit(0)
            import threading
            threading.Thread(target=restart_server).start()
        else:
            flash(
                f'Failed to restore from backup "{filename}". Please check the logs for details.', 'error')
    except Exception as e:
        flash(
            f'An unexpected error occurred during the restore process: {e}', 'error')
    return redirect(url_for('admin.backup_management'))


@admin_bp.route('/wipe-data', methods=['POST'])
@sysop_required
def wipe_all_data():
    """
    データベース内の全BBS関連データを消去し、初期状態に戻します。
    """
    try:
        if session.get('userlevel', 0) < 5:
            flash('You do not have sufficient permissions for this action.', 'danger')
            return redirect(url_for('admin.backup_management'))

        if backup_util.wipe_all_data():
            flash(
                'All data has been wiped. The system will now restart to apply initial settings.', 'success')

            def restart_server():
                import time
                time.sleep(3)
                os._exit(0)
            import threading
            threading.Thread(target=restart_server).start()
        else:
            flash('Failed to wipe data. Please check the logs.', 'error')
    except Exception as e:
        flash(
            f'An unexpected error occurred during the data wipe process: {e}', 'error')
    return redirect(url_for('admin.backup_management'))


@admin_bp.route('/plugins')
@sysop_required
def plugin_management():
    """
    インストールされているプラグインの一覧と、有効/無効状態を表示します。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)

    all_plugins = plugin_manager.get_all_available_plugins()

    total_items = len(all_plugins)
    total_pages = (total_items + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated_plugins = all_plugins[start:end]

    search_params = {
        'per_page': per_page
    }
    search_params_for_per_page = {}  # No other params to pass

    pagination = {
        'page': page,
        'per_page': per_page,
        'total_items': total_items,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages
    }

    return render_template('admin/plugin_list.html', title='Plugin Management', plugins=paginated_plugins, pagination=pagination, search_params=search_params, search_params_for_per_page=search_params_for_per_page)


@admin_bp.route('/plugins/toggle', methods=['POST'])
@sysop_required
def toggle_plugin_status():
    """
    指定されたプラグインの有効/無効状態を切り替えます。変更の適用には再起動が必要です。
    """
    plugin_id = request.form.get('plugin_id')
    action = request.form.get('action')

    if not plugin_id or action not in ['enable', 'disable']:
        flash('Invalid request.', 'danger')
        return redirect(url_for('admin.plugin_management'))

    is_enabled = True if action == 'enable' else False

    if database.upsert_plugin_setting(plugin_id, is_enabled):
        flash(
            f"Plugin '{plugin_id}' has been {action}d. Restart the server to apply changes.", 'success')
    else:
        flash(f"Failed to update status for plugin '{plugin_id}'.", 'danger')

    return redirect(url_for('admin.plugin_management'))


@admin_bp.route('/config-editor', methods=['GET', 'POST'])
@sysop_required
def config_editor():
    """
    設定ファイル `config.toml` をWeb UIから直接編集・保存します。
    """
    config_path = os.path.join(
        backup_util.PROJECT_ROOT, 'setting', 'config.toml')

    if request.method == 'POST':
        new_content = request.form.get('config_content', '')

        try:
            parsed_config = toml.loads(new_content)
        except toml.TomlDecodeError as e:
            flash(f"Invalid TOML format. Changes not saved: {e}", 'danger')
            return render_template('admin/config_editor.html', title=g.texts.get('config_editor', {}).get('title', 'Configuration Editor'), config_content=new_content)

        try:
            backup_path = config_path + '.bak'
            if os.path.exists(config_path):
                shutil.copy2(config_path, backup_path)

            if util.save_app_config(parsed_config, config_path):
                flash(
                    'Configuration file saved successfully. A restart is often required for changes to take effect.', 'success')
            return redirect(url_for('admin.config_editor'))
        except Exception as e:
            flash(f"Error saving configuration file: {e}", 'danger')
            return render_template('admin/config_editor.html', title=g.texts.get('config_editor', {}).get('title', 'Configuration Editor'), config_content=new_content)

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
    except Exception as e:
        config_content = f"# Error reading config file: {e}"
        flash(f'Error reading configuration file: {e}', 'danger')

    return render_template('admin/config_editor.html', title=g.texts.get('config_editor', {}).get('title', 'Configuration Editor'), config_content=config_content)


@admin_bp.route('/broadcast', methods=['POST'])
@sysop_required
def broadcast():
    """
    オンライン中の全ユーザーにメッセージを一斉送信（ブロードキャスト）します。
    """
    message = request.form.get('message', '').strip()

    if not message:
        flash(g.texts.get('broadcast', {}).get(
            'flash_empty', 'Message cannot be empty.'), 'warning')
        return redirect(url_for('admin.dashboard'))

    online_members = terminal_handler.get_webapp_online_members()

    if not online_members:
        flash(g.texts.get('broadcast', {}).get(
            'flash_no_users', 'No users are currently online.'), 'info')
        return redirect(url_for('admin.dashboard'))

    sender_name = session.get('username', 'SYSOP')
    count = 0
    for sid, member_data in online_members.items():
        recipient_name = member_data.get('username')
        if recipient_name:
            database.save_telegram(
                sender_name, recipient_name, message, int(time.time()))
            count += 1

    if count > 0:
        success_message = g.texts.get('broadcast', {}).get(
            'flash_success', 'Broadcast message sent to {count} online users.').format(count=count)
        flash(success_message, 'success')
    else:
        flash(g.texts.get('broadcast', {}).get(
            'flash_no_users', 'No users are currently online.'), 'info')

    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/restart', methods=['POST'])
@sysop_required
def restart_server():
    """
    サーバープロセスを再起動します。
    """
    flash_message = g.texts.get('system_actions', {}).get(
        'flash_restarting', 'Server is restarting... Please reload the page to reconnect.')
    flash(flash_message, 'warning')

    def do_restart():
        time.sleep(2)  # 2秒待機
        logging.info("SysOp triggered server restart.")
        os._exit(0)  # Gunicornワーカーを終了させる。Dockerがコンテナを再起動する。

    import threading
    threading.Thread(target=do_restart).start()

    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/access-log')
@sysop_required
def access_log_viewer():
    """
    アクセスログ閲覧ページ。IP、ユーザー名、イベントタイプでフィルタリング可能。
    """
    page = request.args.get('page', 1, type=int)
    search_ip = request.args.get('ip', '')
    search_user = request.args.get('user', '')
    search_event = request.args.get('event', '')
    sort_by = request.args.get('sort_by', 'timestamp')
    order = request.args.get('order', 'desc')
    per_page = request.args.get('per_page', 15, type=int)
    if page < 1:
        page = 1

    # --- Error Log Reading ---
    error_logs = []
    try:
        log_dir = os.path.join(current_app.config['PROJECT_ROOT'], 'logs')
        error_log_path = os.path.join(log_dir, 'grbbs.error.log')
        if os.path.exists(error_log_path):
            with open(error_log_path, 'r', encoding='utf-8') as f:
                # Read lines and reverse to show newest first
                error_logs = f.readlines()[::-1]
    except Exception as e:
        flash(f"Error reading error log file: {e}", 'danger')
    # --- End Error Log Reading ---

    try:
        logs, total_items = database.get_access_logs(
            page=page,
            per_page=per_page,
            ip_address=search_ip,
            username=search_user,
            event_type=search_event,
            sort_by=sort_by,
            order=order
        )
        total_pages = (total_items + per_page - 1) // per_page
    except Exception as e:
        flash(f"Error retrieving access logs: {e}", 'danger')
        logs = []
        total_items = 0
        total_pages = 0

    search_params = {
        'ip': search_ip,
        'user': search_user,
        'event': search_event,
        'sort_by': sort_by,
        'order': order,
        'per_page': per_page
    }

    search_params_for_per_page = search_params.copy()
    search_params_for_per_page.pop('per_page', None)

    pagination = {
        'page': page,
        'per_page': per_page,
        'total_items': total_items,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages
    }

    next_order = 'desc' if order == 'asc' else 'asc'

    return render_template('admin/log_viewer.html', title=g.texts.get('access_log', {}).get('title', 'Access Log Viewer'), logs=logs, error_logs=error_logs, search_params=search_params, search_params_for_per_page=search_params_for_per_page, pagination=pagination,
                           sort_by=sort_by, order=order, next_order=next_order)
