# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT


"""管理画面のルーティング定義モジュール。

このモジュールは、FlaskのBlueprintを利用して、BBSの管理機能に関連する
全てのWebエンドポイント (例: `/admin/dashboard`, `/admin/users`など) を定義します。
"""

from io import StringIO
import json
import os
from datetime import datetime, timedelta
import time
import csv
import logging
from .. import database, util, backup_util, plugin_manager, terminal_handler, extensions
import psutil
from flask import Blueprint, render_template, request, flash, redirect, url_for, session, send_from_directory, g, current_app, Response
from ..decorators import sysop_required
import ipaddress

import shutil
from flask import jsonify
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# 管理画面のブループリント全体をレートリミットの対象外にする
extensions.limiter.exempt(admin_bp)


@admin_bp.route('/links', methods=['GET', 'POST'])
@sysop_required
def link_list():
    """外部リンク一覧の管理ページ。WebターミナルのF7キーで表示されるリンクを管理します。"""
    if request.method == 'POST':
        action = request.form.get('action')
        link_id = request.form.get('id')
        name = request.form.get('name')
        url = request.form.get('url')
        description = request.form.get('description', '')

        if action == 'add':
            if name and url:
                # Keep database function name
                if database.add_bbs_link(name, url, description, source='sysop', submitted_by=session.get('user_id')):
                    util.log_audit_event(
                        action='ADD_BBS_LINK',
                        details={
                            'name': name,
                            'url': url,
                            'description': description
                        }
                    )
                    flash('Link added successfully.', 'success')
                else:
                    flash('Failed to add link. URL might already exist.', 'danger')
            else:
                flash('Name and URL are required.', 'warning')
        elif action == 'delete':
            if link_id:
                link_to_delete = database.bbs_list_manager.get_by_id(link_id)
                # Keep database function name
                if database.delete_bbs_link(link_id):
                    util.log_audit_event(
                        action='DELETE_BBS_LINK',
                        details={
                            'link_id': link_id,
                            'name': link_to_delete.get('name') if link_to_delete else 'N/A',
                            'url': link_to_delete.get('url') if link_to_delete else 'N/A'
                        }
                    )
                    flash('Link deleted successfully.', 'success')
                else:
                    flash('Failed to delete link.', 'danger')
        elif action == 'approve':
            # Keep database function name
            if link_id and database.update_bbs_link_status(link_id, 'approved'):
                util.log_audit_event(
                    action='UPDATE_BBS_LINK_STATUS',
                    details={'link_id': link_id, 'new_status': 'approved'}
                )
                flash('Link approved.', 'success')
            else:
                flash('Failed to approve link.', 'danger')
        elif action == 'reject':
            # Keep database function name
            if link_id and database.update_bbs_link_status(link_id, 'rejected'):
                util.log_audit_event(
                    action='UPDATE_BBS_LINK_STATUS',
                    details={'link_id': link_id, 'new_status': 'rejected'}
                )
                flash('Link rejected.', 'success')
            else:
                flash('Failed to reject link.', 'danger')
        elif action == 'unapprove':
            # Keep database function name
            if link_id and database.update_bbs_link_status(link_id, 'pending'):
                util.log_audit_event(
                    action='UPDATE_BBS_LINK_STATUS',
                    details={'link_id': link_id, 'new_status': 'pending'}
                )
                flash('Link has been returned to pending status.', 'success')
            else:
                flash('Failed to unapprove link.', 'danger')
        elif action == 'requeue':
            # Keep database function name
            if link_id and database.update_bbs_link_status(link_id, 'pending'):
                util.log_audit_event(
                    action='UPDATE_BBS_LINK_STATUS',
                    details={'link_id': link_id, 'new_status': 'pending'}
                )
                flash('Link has been set to pending for re-evaluation.', 'success')
            else:
                flash('Failed to set link to pending.', 'danger')
        return redirect(url_for('admin.link_list'))

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
        flash(f"Error retrieving link list: {e}", 'danger')
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
        'admin.bbs_list.title', session.get('menu_mode', '2'), 'Link Management')
    return render_template(
        'admin/link_list.html', title=title, links=links, pagination=pagination,
        sort_by=sort_by, order=order, next_order=next_order,
        search_params=search_params, search_params_for_per_page=search_params_for_per_page

    )


@admin_bp.route('/links/edit/<int:link_id>', methods=['GET', 'POST'])
@sysop_required
def edit_link(link_id):
    """外部リンクの編集ページ。指定されたIDのリンクの名前、URL、説明を編集します。"""
    link = database.bbs_list_manager.get_by_id(link_id)
    if not link:
        flash('Link not found.', 'danger')
        return redirect(url_for('admin.link_list'))

    if request.method == 'POST':
        name = request.form.get('name')
        url = request.form.get('url')
        description = request.form.get('description', '')

        if name and url:
            # Keep database function name
            if database.update_bbs_link(link_id, name, url, description):
                # --- 監査ログ記録 ---
                util.log_audit_event(
                    action='EDIT_BBS_LINK',
                    details={
                        'link_id': link_id,
                        'name': name,
                        'url': url,
                        'description': description
                    }
                )
                flash('Link updated successfully.', 'success')
                return redirect(url_for('admin.link_list'))
            else:
                flash('Failed to update link.', 'danger')
        else:
            flash('Name and URL are required.', 'warning')
        link.update(name=name, url=url, description=description)

    title = f"Edit Link: {link['name']}"
    return render_template('admin/edit_link.html', title=title, link=link)


BACKUP_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'backups'))
os.makedirs(BACKUP_DIR, exist_ok=True)


def _process_texts_for_mode(node, menu_mode):
    """YAMLから読み込んだ辞書を再帰的に処理し、指定されたメニューモードのテキストを抽出します。"""
    if isinstance(node, dict):
        mode_key = f"mode_{menu_mode}"
        if mode_key in node:
            return node[mode_key]
        else:
            return {key: _process_texts_for_mode(value, menu_mode) for key, value in node.items()}
    return node


@admin_bp.before_request
def load_admin_texts():
    """各リクエストの前に、ユーザーのメニューモードに応じたテキストデータをロードします。"""
    # --- テキストデータのロード ---
    menu_mode = session.get('menu_mode', '3')
    g.texts = _process_texts_for_mode(util.load_master_text_data(), menu_mode)

    # --- ナビゲーション構造の定義 ---
    # 各項目のテキストは g.texts から動的に取得
    nav_texts = g.texts.get('nav', {})
    g.nav_structure = [
        {
            'group_title': nav_texts.get('user_management_group', 'User Management'),
            'nav_items': [
                {'title': nav_texts.get('who_online', "Who's Online"),
                 'endpoint': 'admin.who_online'},
                {'title': nav_texts.get('user_management', 'User Management'),
                 'endpoint': 'admin.user_management'},
            ]
        },
        {
            'group_title': nav_texts.get('content_management_group', 'Content Management'),
            'nav_items': [
                {'title': nav_texts.get('board_management', 'BBS Management'),
                 'endpoint': 'admin.bbs_management'},
                {'title': nav_texts.get('chat_management', 'Chat Management'),
                 'endpoint': 'admin.chat_management'},
                {'title': nav_texts.get('content_management', 'Content Management'),  # Keep this
                 'endpoint': 'admin.content_management'},  # Keep this
                {'title': nav_texts.get('bbs_list_management', 'Link Management'),
                 'endpoint': 'admin.link_list'},
            ]
        },
        {
            'group_title': nav_texts.get('system_management_group', 'System Management'),
            'nav_items': [
                {'title': nav_texts.get('system_settings', 'System Settings'),
                 'endpoint': 'admin.system_settings'},
                {'title': nav_texts.get('plugins', 'Plugin Management'),
                 'endpoint': 'admin.plugin_management'},
                {'title': nav_texts.get('access_log', 'Log Viewer'),
                 'endpoint': 'admin.access_management'},
                {'title': nav_texts.get('data_management', 'Data Management'),
                 'endpoint': 'admin.backup_management'},
            ]
        }
    ]


@admin_bp.route('/')
@sysop_required
def dashboard():
    """管理画面のダッシュボード。統計情報、システムヘルス、アクティビティグラフを表示します。期間指定でグラフデータをJSONで返すことも可能です。"""
    duration = request.args.get('duration', 30, type=int)

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

    # --- Chart Data Generation ---
    if duration > 90:
        # 月単位のラベルを生成
        labels = []
        for i in range(duration // 30):
            month = datetime.now() - timedelta(days=i * 30)
            labels.append(month.strftime('%Y-%m'))
        labels.reverse()
        date_format_str = '%Y-%m'
    elif duration > 28:
        # 週単位のラベルを生成 (YYYY-WW)
        # MySQLのYEARWEEK(date, 1)の挙動に合わせる
        labels = []
        today = datetime.now()
        for i in range(duration):
            d = today - timedelta(days=i)
            # isocalendar() は (year, week, weekday) を返す
            year, week, _ = d.isocalendar()
            # MySQLのYEARWEEK(date, 1)は、週が年にまたがる場合、4日以上がその年にある週を1週目とする。
            # isocalendar()の挙動はこれと一致する。
            # 週番号が1桁の場合は0埋めしてYYYYWW形式にする
            labels.append(f"{year}{week:02d}")
        labels = sorted(list(set(labels)))  # 重複を削除してソート
        date_format_str = '%Y%U'  # YEARWEEK()のモード1は%Y%Uに対応
    else:
        labels = [(datetime.now() - timedelta(days=i)
                   ).strftime('%Y-%m-%d') for i in range(duration - 1, -1, -1)]
        date_format_str = '%Y-%m-%d'

    user_data_raw = database.get_daily_user_registrations(days=duration)
    user_data_map = {str(item['registration_date']) if not isinstance(item['registration_date'], str) else item['registration_date']: item['count']
                     for item in user_data_raw} if user_data_raw else {}
    user_counts = [user_data_map.get(label, 0) for label in labels]
    article_data_raw = database.get_daily_article_posts(days=duration)
    article_data_map = {str(item['post_date']) if not isinstance(item['post_date'], str) else item['post_date']: item['count']
                        for item in article_data_raw} if article_data_raw else {}
    article_counts = [article_data_map.get(label, 0) for label in labels]

    access_data_raw = database.get_access_counts_by_type(days=duration)
    access_data_map = {item['date_period']: item for item in access_data_raw}

    access_counts = {
        'total': [access_data_map.get(label, {}).get('total_access', 0) for label in labels],
        'banned': [access_data_map.get(label, {}).get('ip_banned', 0) for label in labels],
        'proxy': [access_data_map.get(label, {}).get('proxy_blocked', 0) for label in labels],
        'guest': [access_data_map.get(label, {}).get('guest_connect', 0) for label in labels],
        'member': [access_data_map.get(label, {}).get('member_connect', 0) for label in labels],
        'login_failure': [access_data_map.get(label, {}).get('login_failure', 0) for label in labels],
    }

    chart_data = {
        'labels': labels,
        'user_registrations': user_counts,
        'article_posts': article_counts,
        'access_counts': access_counts,
    }

    if 'duration' in request.args:
        return jsonify(chart_data)

    return render_template('admin/dashboard.html', title=g.texts.get('dashboard', {}).get('title', 'Dashboard'),
                           stats=stats, chart_data=chart_data, system_health=system_health)


@admin_bp.route('/who')
@sysop_required
@extensions.limiter.exempt
def who_online():
    """オンラインユーザー一覧。現在接続しているユーザーの一覧表示と強制切断（キック）を行います。"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)

    online_members_raw = terminal_handler.get_webapp_online_members()

    online_list = []
    current_time = time.time()
    for sid, member_data in online_members_raw.items():
        connect_time = member_data.get('connect_time', current_time)
        duration_seconds = current_time - connect_time
        member_data['duration_seconds'] = duration_seconds
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
    """指定されたセッションIDを持つユーザーのWebSocket接続を強制的に切断（キック）します。"""
    from ..factory import socketio

    online_members = terminal_handler.get_webapp_online_members()
    member_to_kick = online_members.get(sid)
    display_name = member_to_kick.get(
        'display_name', f'session {sid}') if member_to_kick else f'session {sid}'

    kicked = terminal_handler.kick_user_session(sid, socketio)

    if kicked:
        flash(f"User '{display_name}' has been kicked.", 'success')
    else:
        flash(
            f"Failed to kick user '{display_name}'. They may have already disconnected.", 'warning')

    return redirect(url_for('admin.who_online'))


@admin_bp.route('/users', methods=['GET'])
@sysop_required
def user_management():
    """ユーザー管理（ユーザー一覧 & アクティビティ）。タブ形式で管理します。"""
    tab = request.args.get('tab', 'list')

    if tab == 'list':
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 15, type=int)
        sort_by = request.args.get('sort_by', 'id')
        order = request.args.get('order', 'asc')
        search_term = request.args.get('q', '')
        next_order = 'desc' if order == 'asc' else 'asc'

        try:
            users, total_items = database.get_all_users(
                page=page, per_page=per_page, sort_by=sort_by, order=order, search_term=search_term)
            total_pages = (total_items + per_page - 1) // per_page
        except Exception as e:
            flash(f"Error retrieving user list: {e}", 'danger')
            users, total_items, total_pages = [], 0, 0

        search_params = {'tab': 'list', 'q': search_term,
                         'sort_by': sort_by, 'order': order, 'per_page': per_page}
        search_params_for_per_page = {
            k: v for k, v in request.args.items() if k != 'per_page'}

        pagination = {'page': page, 'per_page': per_page, 'total_items': total_items,
                      'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages}

        return render_template(
            'admin/user_management.html', tab='list', users=users, pagination=pagination,
            sort_by=sort_by, order=order, next_order=next_order,
            search_params=search_params, search_params_for_per_page=search_params_for_per_page,
            search_term=search_term
        )

    elif tab == 'activity':
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 15, type=int)
        sort_by = request.args.get('sort_by', 'last_login')
        order = request.args.get('order', 'desc')
        next_order = 'desc' if order == 'asc' else 'asc'

        try:
            user_activities, total_items = database.get_user_activity_summary(
                page=page, per_page=per_page, sort_by=sort_by, order=order)
            total_pages = (total_items + per_page - 1) // per_page
        except Exception as e:
            flash(f"Error retrieving user activity: {e}", 'danger')  # noqa
            user_activities, total_items, total_pages = [], 0, 0

        pagination = {'page': page, 'per_page': per_page, 'total_items': total_items,
                      'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages}
        search_params = {'tab': 'activity', 'sort_by': sort_by,
                         'order': order, 'per_page': per_page}
        search_params_for_per_page = {
            k: v for k, v in request.args.items() if k != 'per_page'}

        return render_template(
            'admin/user_management.html', tab='activity', user_activities=user_activities,
            pagination=pagination, sort_by=sort_by, order=order, next_order=next_order,
            search_params=search_params, search_params_for_per_page=search_params_for_per_page
        )

    # Fallback redirect
    return redirect(url_for('admin.user_management', tab='list'))


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@sysop_required
def new_user():
    """新規ユーザー作成（管理者用）。管理者が手動で新しいユーザーアカウントを作成します。"""
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
            # --- 監査ログ記録 ---
            util.log_audit_event(
                action='CREATE_USER',
                details={
                    'new_username': username,
                    'level': level,
                    'email': email,
                    'comment': comment
                }
            )
            flash(
                f"User '{username}' has been created successfully.", 'success')
            return redirect(url_for('admin.user_management'))
        else:
            flash('Failed to create user.', 'danger')

    return render_template('admin/new_user.html', title='Add New User')


@admin_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@sysop_required
def edit_user(user_id):
    """ユーザー情報編集（管理者用）。指定されたユーザーの情報を編集・更新します。"""
    edit_user_texts = g.texts.get('admin_edit_user', {})

    user = database.get_user_by_id(user_id)
    if not user:
        flash(f"User with ID {user_id} not found.", 'danger')
        return redirect(url_for('admin.user_management'))

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

        password_changed = False
        if new_password:
            password_changed = True
            salt, hashed_password = util.hash_password(new_password)
            updates['password'] = hashed_password
            updates['salt'] = salt

        if database.update_record('users', updates, {'id': user_id}):
            # --- 監査ログ記録 ---
            # ログにはハッシュ化されたパスワードやソルトを含めない
            log_details = {
                'target_user_id': user_id,
                'target_username': user['name'],
                'changes': {
                    'level': new_level,
                    'email': new_email,
                    'comment': new_comment,
                }
            }
            if password_changed:
                # パスワードが変更されたことだけ記録
                log_details['changes']['password'] = '********'

            util.log_audit_event(
                action='UPDATE_USER_INFO',
                details=log_details
            )
            flash(
                f"User '{user['name']}' has been updated successfully.", 'success')
        else:
            flash(f"Failed to update user '{user['name']}'.", 'danger')
        return redirect(url_for('admin.user_management'))

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
    """ユーザーのPasskey削除（管理者用）。指定されたユーザーの特定のPasskeyを削除します。"""
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
    """ユーザーの削除（管理者用）。指定されたユーザーアカウントを物理的に削除します。"""
    user_to_delete = database.get_user_by_id(user_id)

    if not user_to_delete:
        flash(f"User with ID {user_id} not found.", 'danger')
        return redirect(url_for('admin.user_management'))

    if user_to_delete['id'] == session.get('user_id'):
        flash("You cannot delete your own account.", 'danger')
        return redirect(url_for('admin.user_management'))

    if user_to_delete['name'].upper() == 'GUEST':
        flash("The GUEST account cannot be deleted.", 'danger')
        return redirect(url_for('admin.user_management'))

    if database.delete_user(user_id):
        # --- 監査ログ記録 ---
        util.log_audit_event(
            action='DELETE_USER',
            details={
                'target_user_id': user_id,
                'target_username': user_to_delete['name']
            }
        )
        flash(
            f"User '{user_to_delete['name']}' has been successfully deleted.", 'success')
    else:
        flash(f"Failed to delete user '{user_to_delete['name']}'.", 'danger')
    return redirect(url_for('admin.user_management'))


@admin_bp.route('/boards/new', methods=['GET', 'POST'])
@sysop_required
def new_board():
    """新規掲示板作成（管理者用）。新しい掲示板を作成し、各種設定を行います。"""
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
            # --- 監査ログ記録 ---
            util.log_audit_event(
                action='CREATE_BOARD',
                details={
                    'shortcut_id': shortcut_id,
                    'name': name,
                    'board_type': board_type,
                    'default_permission': default_permission,
                    'read_level': read_level,
                    'write_level': write_level,
                    'allow_attachments': allow_attachments,
                    'max_threads': max_threads,
                    'max_replies': max_replies,
                })
            flash(f"Board '{name}' has been created successfully.", 'success')
            return redirect(url_for('admin.bbs_management', tab='list'))
        else:
            flash('Failed to create board.', 'danger')

    return render_template('admin/new_board.html', title='Add New Board')


@admin_bp.route('/boards/edit/<int:board_id>', methods=['GET', 'POST'])
@sysop_required
def edit_board(board_id):
    """掲示板設定編集（管理者用）。既存の掲示板の各種設定を編集します。"""
    board = database.get_board_by_id(board_id)
    if not board:
        flash(f"Board with ID {board_id} not found.", 'danger')
        return redirect(url_for('admin.bbs_management', tab='list'))

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
            # --- 監査ログ記録 ---
            log_details = updates.copy()
            log_details['board_id'] = board_id
            log_details['shortcut_id'] = board.get('shortcut_id')
            util.log_audit_event(action='UPDATE_BOARD', details=log_details)

            database.delete_board_permissions_by_board_id(board_id)

            if new_permission_user_ids:
                board_default_permission = updates.get(
                    'default_permission', board.get('default_permission'))
                access_level_to_set = "deny" if board_default_permission == "open" else "allow"

                for user_id_to_add in new_permission_user_ids:
                    database.add_board_permission(
                        board_id, str(user_id_to_add), access_level_to_set)
            flash(f"Board '{name}' has been updated successfully.", 'success')
            return redirect(url_for('admin.bbs_management', tab='list'))
        else:
            flash(f"Failed to update board '{name}'.", 'danger')
            return redirect(url_for('admin.edit_board', board_id=board_id))

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
    """掲示板の完全削除（管理者用）。指定された掲示板と関連データを物理削除します。"""
    board_to_delete = database.get_board_by_id(board_id)

    if not board_to_delete:
        flash(f"Board with ID {board_id} not found.", 'danger')
        return redirect(url_for('admin.bbs_management', tab='list'))

    if database.delete_board_and_related_data(board_id):
        # --- 監査ログ記録 ---
        util.log_audit_event(
            action='DELETE_BOARD',
            details={
                'target_board_id': board_id,
                'target_shortcut_id': board_to_delete.get('shortcut_id'),
                'target_board_name': board_to_delete.get('name')
            })
        flash(
            f"Board '{board_to_delete['name']}' and all related data have been successfully deleted.", 'success')
    else:
        flash(f"Failed to delete board '{board_to_delete['name']}'.", 'danger')

    return redirect(url_for('admin.bbs_management', tab='list'))


@admin_bp.route('/articles/delete/<int:article_id>', methods=['POST'])
@sysop_required
def delete_article(article_id):
    """記事の論理削除/復元（管理者用）。指定された記事の削除フラグをトグルします。"""
    article = database.get_article_by_id(article_id)
    if not article:
        flash(f"Article ID {article_id} not found.", 'danger')
        return redirect(request.referrer or url_for('admin.content_management', tab='articles'))

    was_deleted = article['is_deleted']

    if database.toggle_article_deleted_status(article_id):
        # --- 監査ログ記録 ---
        action_log = 'RESTORE_ARTICLE' if was_deleted else 'DELETE_ARTICLE'
        util.log_audit_event(
            action=action_log,
            details={
                'target_article_id': article_id,
                'target_article_title': article.get('title', '(No Title)'),
                'target_board_id': article.get('board_id')
            }
        )
        if was_deleted:
            flash(f"Article ID {article_id} has been restored.", 'success')
        else:
            flash(
                f"Article ID {article_id} has been marked as deleted.", 'success')
    else:
        flash(
            f"Failed to update status for article ID {article_id}.", 'danger')

    return redirect(request.referrer or url_for('admin.content_management', tab='articles'))


@admin_bp.route('/articles/bulk-action', methods=['POST'])
@sysop_required
def bulk_action_articles():
    """記事の一括操作（管理者用）。選択された複数の記事をまとめて論理削除または復元します。"""
    action = request.form.get('action')
    selected_ids_str = request.form.getlist('selected_articles')

    if not action or not selected_ids_str:
        flash('No action or no articles selected.', 'warning')
        return redirect(request.referrer or url_for('admin.content_management', tab='articles'))

    selected_ids = [int(id_str)
                    for id_str in selected_ids_str if id_str.isdigit()]

    if not selected_ids:
        flash('No valid articles selected.', 'warning')
        return redirect(request.referrer or url_for('admin.content_management', tab='articles'))

    if action == 'delete':
        updated_count = database.bulk_update_articles_deleted_status(
            selected_ids, 1)
        # --- 監査ログ記録 ---
        util.log_audit_event(
            action='BULK_DELETE_ARTICLES',
            details={
                'target_article_ids': selected_ids,
                'count': updated_count
            }
        )
        flash(f"{updated_count} articles have been marked as deleted.", 'success')
    elif action == 'restore':
        updated_count = database.bulk_update_articles_deleted_status(
            selected_ids, 0)
        util.log_audit_event(
            action='BULK_RESTORE_ARTICLES',
            details={
                'target_article_ids': selected_ids,
                'count': updated_count
            })
        flash(f"{updated_count} articles have been restored.", 'success')
    else:
        flash('Invalid action.', 'danger')

    return redirect(request.referrer or url_for('admin.content_management', tab='articles'))


@admin_bp.route('/attachments/quarantine/delete/<path:filename>', methods=['POST'])
@sysop_required
def delete_quarantined_file(filename):
    """隔離ファイルの削除（管理者用）。ウイルススキャンで隔離されたファイルを物理削除します。"""
    quarantine_dir_rel = util.app_config.get('clamav', {}).get(
        'quarantine_directory', 'data/quarantine')
    quarantine_dir_abs = os.path.join(
        current_app.config['PROJECT_ROOT'], quarantine_dir_rel)
    filepath = os.path.join(quarantine_dir_abs, filename)
    log_file_path = os.path.join(quarantine_dir_abs, 'quarantine_log.json')

    try:
        if os.path.exists(filepath) and os.path.isfile(filepath):
            os.remove(filepath)
            # --- 監査ログ記録 ---
            util.log_audit_event(
                action='DELETE_QUARANTINED_FILE',
                details={
                    'filename': filename
                }
            )
    except OSError as e:
        flash(f"Error deleting file '{filename}': {e}", 'danger')
        return redirect(url_for('admin.content_management', tab='attachments'))

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

    return redirect(url_for('admin.content_management', tab='attachments'))


@admin_bp.route('/settings', methods=['GET', 'POST'])
@sysop_required
def system_settings():
    """システム全体設定（管理者用）。機能ごとの最低ユーザーレベルやログインメッセージなどを設定します。"""
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
            # Site Info
            'server_name': request.form.get('server_name', '').strip(),
            'operator_name': request.form.get('operator_name', '').strip(),
            'contact_email': request.form.get('contact_email', '').strip(),
            'contact_x_url': request.form.get('contact_x_url', '').strip(),
            'contact_threads_url': request.form.get('contact_threads_url', '').strip(),
            'contact_bluesky_url': request.form.get('contact_bluesky_url', '').strip(),
            'contact_mastodon_url': request.form.get('contact_mastodon_url', '').strip(),
            'bbs_article_wrap_width': request.form.get('bbs_article_wrap_width', 78, type=int),
            'login_message': request.form.get('login_message', '').strip(),
            'online_signup_enabled': 1 if 'online_signup_enabled' in request.form else 0,
            'telegram_logging_enabled': 1 if 'telegram_logging_enabled' in request.form else 0,
            'plugin_execution_timeout': request.form.get('plugin_execution_timeout', 60, type=int),
            # Log & Backup Settings
            'log_retention_days': request.form.get('log_retention_days', 90, type=int),
            'log_cleanup_cron': request.form.get('log_cleanup_cron', '5 4 * * *').strip(),
            'backup_schedule_enabled': 1 if 'backup_schedule_enabled' in request.form else 0,
            'backup_schedule_cron': request.form.get('backup_schedule_cron', '0 3 * * *').strip(),
            'max_backups': request.form.get('max_backups', 0, type=int),
            # Security Settings
            'max_password_attempts': request.form.get('max_password_attempts', 3, type=int),
            'lockout_time_seconds': request.form.get('lockout_time_seconds', 300, type=int),
            'block_proxies': 1 if 'block_proxies' in request.form else 0,
            'maintenance_mode': 1 if 'maintenance_mode' in request.form else 0,
            'max_concurrent_webapp_clients': request.form.get('max_concurrent_webapp_clients', 4, type=int)
        }

        for key in ['bbs', 'chat', 'mail', 'telegram', 'userpref', 'who', 'hamlet']:
            if not (0 <= settings_to_update[key] <= 5):
                flash(
                    f"Invalid level for {key}. Must be between 0 and 5.", 'danger')
                current_settings = database.read_server_pref() or {}
                return render_template('admin/system_settings.html', title='System Settings', settings=current_settings)
        # --- 監査ログ記録 ---
        util.log_audit_event(
            action='UPDATE_SYSTEM_SETTINGS',
            details=settings_to_update
        )

        if database.update_system_settings(settings_to_update):
            # --- 監査ログ記録 ---
            util.log_audit_event(
                action='UPDATE_SYSTEM_SETTINGS',
                details=settings_to_update
            )
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
    """データ管理（バックアップ・リストア）。バックアップ、リストア、スケジュール設定などを行います。"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)

    if request.method == 'POST':
        if request.form.get('action') == 'save_schedule':
            is_enabled = 'schedule_enabled' in request.form
            cron_string = request.form.get('schedule_cron', '0 3 * * *')
            max_backups = request.form.get('max_backups', 0, type=int)

            if database.update_backup_schedule(is_enabled, cron_string, max_backups):
                # --- 監査ログ記録 ---
                util.log_audit_event(
                    action='UPDATE_BACKUP_SCHEDULE',
                    details={
                        'enabled': is_enabled,
                        'cron_string': cron_string,
                        'max_backups': max_backups
                    }
                )
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
    search_params_for_per_page = {}

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
    """手動バックアップの作成（管理者用）。新しいバックアップファイルを作成します。"""
    try:
        filename = backup_util.create_backup()
        if filename:
            # --- 監査ログ記録 ---
            util.log_audit_event(
                action='CREATE_BACKUP',
                details={
                    'filename': filename
                }
            )
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
    """バックアップファイルのダウンロード。指定されたバックアップファイルをダウンロードさせます。"""
    # --- 監査ログ記録 ---
    util.log_audit_event(
        action='DOWNLOAD_BACKUP',
        details={
            'filename': filename
        }
    )
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)


@admin_bp.route('/backup/delete/<path:filename>', methods=['POST'])
@sysop_required
def delete_backup(filename):
    """バックアップファイルの削除（管理者用）。指定されたバックアップファイルを物理削除します。"""
    try:
        filepath = os.path.join(BACKUP_DIR, filename)
        if not os.path.abspath(filepath).startswith(os.path.abspath(BACKUP_DIR)):
            flash('Invalid file path.', 'danger')
            return redirect(url_for('admin.backup_management'))

        if os.path.exists(filepath) and os.path.isfile(filepath):
            os.remove(filepath)
            # --- 監査ログ記録 ---
            util.log_audit_event(
                action='DELETE_BACKUP',
                details={
                    'filename': filename
                }
            )
            flash(f'Backup file "{filename}" has been deleted.', 'success')
        else:
            flash(f'File "{filename}" not found.', 'warning')
    except Exception as e:
        flash(f'An error occurred while deleting the file: {e}', 'error')

    return redirect(url_for('admin.backup_management'))


@admin_bp.route('/backup/restore/<path:filename>', methods=['POST'])
@sysop_required
def restore_from_backup(filename):
    """バックアップからのリストア（管理者用）。指定されたバックアップファイルからデータを復元します。"""
    try:
        success = backup_util.restore_from_backup(filename)
        if success:
            # --- 監査ログ記録 ---
            util.log_audit_event(

                action='RESTORE_FROM_BACKUP',
                details={
                    'filename': filename
                }
            )
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


@admin_bp.route('/optimize_tables', methods=['POST'])
@sysop_required
def optimize_tables():
    """全てのデータベーステーブルを最適化します。"""
    try:
        result = database.optimize_all_tables()
        if result:
            flash('All database tables have been optimized.', 'success')
            util.log_audit_event(action='OPTIMIZE_TABLES',
                                 details={'status': 'success'})
        else:
            flash(
                'Failed to optimize all database tables. Check the logs for details.', 'danger')
            util.log_audit_event(action='OPTIMIZE_TABLES',
                                 details={'status': 'failed'})
    except Exception as e:
        flash(f'An error occurred during table optimization: {e}', 'danger')
    return redirect(url_for('admin.backup_management'))


@admin_bp.route('/wipe-data', methods=['POST'])
@sysop_required
def wipe_all_data():
    """全データの完全消去（管理者用）。全BBSデータを消去し、システムを初期状態に戻します。"""
    try:
        if session.get('userlevel', 0) < 5:
            flash('You do not have sufficient permissions for this action.', 'danger')
            return redirect(url_for('admin.backup_management'))

        if backup_util.wipe_all_data():

            # --- 監査ログ記録 ---
            util.log_audit_event(
                action='WIPE_ALL_DATA'
            )
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
    """プラグイン管理。インストール済みプラグインの一覧表示と有効/無効の切り替えを行います。"""
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
    search_params_for_per_page = {}

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
    """プラグインの有効/無効切り替え（管理者用）。指定されたプラグインの状態をDB上で切り替えます。"""
    plugin_id = request.form.get('plugin_id')
    action = request.form.get('action')

    if not plugin_id or action not in ['enable', 'disable']:
        flash('Invalid request.', 'danger')
        return redirect(url_for('admin.plugin_management'))

    is_enabled = True if action == 'enable' else False

    if database.upsert_plugin_setting(plugin_id, is_enabled):
        flash(
            f"Plugin '{plugin_id}' has been {action}d. Restart the server to apply changes.", 'success')
        util.log_audit_event(
            action='TOGGLE_PLUGIN_STATUS',
            details={
                'plugin_id': plugin_id,
                'action': action,
                'is_enabled': is_enabled
            }
        )
    else:
        flash(f"Failed to update status for plugin '{plugin_id}'.", 'danger')

    return redirect(url_for('admin.plugin_management'))


@admin_bp.route('/plugins/reload', methods=['POST'])
@sysop_required
def reload_plugins():
    """プラグインを動的に再読み込みします。"""
    plugin_manager.load_plugins()
    flash('Plugins have been reloaded.', 'success')
    util.log_audit_event(
        action='RELOAD_PLUGINS',
        details={
            'message': 'Plugins have been reloaded.'
        }
    )
    return redirect(url_for('admin.plugin_management'))


@admin_bp.route('/plugins/data/<plugin_id>')
@sysop_required
def plugin_data_view(plugin_id):
    """プラグインデータ閲覧（管理者用）。プラグインが保存したデータをJSON形式で表示します。"""
    all_plugins = plugin_manager.get_all_available_plugins()
    plugin_info = next((p for p in all_plugins if p['id'] == plugin_id), None)

    if not plugin_info:
        flash(f"Plugin '{plugin_id}' not found.", 'danger')
        return redirect(url_for('admin.plugin_management'))

    data = database.get_all_plugin_data(plugin_id)

    # JSONデータを整形してテンプレートに渡す
    formatted_data = {}
    for key, value in data.items():
        try:
            # JSON文字列として整形
            formatted_data[key] = json.dumps(
                value, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            formatted_data[key] = str(value)

    return render_template('admin/plugin_data.html', title=f"Data for {plugin_info['name']}", plugin=plugin_info, data=formatted_data)


@admin_bp.route('/plugins/data/<plugin_id>/delete/<key>', methods=['POST'])
@sysop_required
def delete_plugin_data_key(plugin_id, key):
    """プラグインデータの個別削除（管理者用）。指定されたキーのプラグインデータを削除します。"""
    if database.delete_plugin_data(plugin_id, key):
        flash(f"Data for key '{key}' has been deleted.", 'success')
    else:
        flash(f"Failed to delete data for key '{key}'.", 'danger')
    return redirect(url_for('admin.plugin_data_view', plugin_id=plugin_id))


@admin_bp.route('/plugins/data/<plugin_id>/delete_all', methods=['POST'])
@sysop_required
def delete_all_plugin_data(plugin_id):
    """プラグインデータの全件削除（管理者用）。指定されたプラグインの全データを削除します。"""
    if database.delete_all_plugin_data(plugin_id):
        flash(
            f"All data for plugin '{plugin_id}' has been deleted.", 'success')
        util.log_audit_event(
            action='DELETE_ALL_PLUGIN_DATA',
            details={
                'plugin_id': plugin_id
            }
        )
    else:
        flash(f"Failed to delete all data for plugin '{plugin_id}'.", 'danger')
    return redirect(url_for('admin.plugin_data_view', plugin_id=plugin_id))


@admin_bp.route('/broadcast', methods=['POST'])
@sysop_required
def broadcast():
    """メッセージ一斉送信（ブロードキャスト）。オンライン中の全ユーザーに電報を送信します。"""
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
    """サーバーの再起動。サーバープロセスを安全に再起動させます。"""
    flash_message = g.texts.get('system_actions', {}).get(
        'flash_restarting', 'Server is restarting... Please reload the page to reconnect.')
    flash(flash_message, 'warning')

    def do_restart():
        time.sleep(2)  # 2秒待機
        logging.info("SysOp triggered server restart.")
        os._exit(0)

    import threading
    threading.Thread(target=do_restart).start()

    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/chatrooms', methods=['GET', 'POST'])
@sysop_required
def chat_management():
    """チャットルーム管理。Web UIから `chatroom.yaml` の階層構造を管理します。"""
    config_path = os.path.join(
        current_app.config['PROJECT_ROOT'], 'setting', 'chatroom.yaml')

    def find_item_and_parent(items, item_id, parent=None):
        """IDでアイテムを再帰的に探し、アイテムとその親、インデックスを返します。"""
        for i, item in enumerate(items):
            if item.get('id') == item_id:
                return item, parent, i
            if 'items' in item:
                found_item, found_parent, found_index = find_item_and_parent(
                    item['items'], item_id, item)
                if found_item:
                    return found_item, found_parent, found_index
        return None, None, -1

    if request.method == 'POST':
        chat_config = util.load_chat_config()
        action = request.form.get('action')

        try:
            if action == 'add':
                parent_id = request.form.get('parent_id')
                new_id = request.form.get('id').strip()
                new_name = request.form.get('name').strip()
                new_type = request.form.get('type')

                if not new_id or not new_name:
                    flash('ID and Name are required.', 'danger')
                else:
                    new_item = {'id': new_id, 'name': new_name,
                                'type': new_type}
                    if new_type == 'room':
                        new_item['push'] = 'push' in request.form
                        new_item['lock'] = 'lock' in request.form
                    if new_type == 'child':
                        new_item['items'] = []

                    if parent_id == 'root_categories':
                        chat_config.setdefault(
                            'categories', []).append(new_item)
                    elif parent_id == 'root_global':
                        chat_config.setdefault('global', []).append(new_item)
                    else:
                        parent_item, _, _ = find_item_and_parent(
                            chat_config.get('categories', []), parent_id)
                        if parent_item and parent_item.get('type') == 'child':
                            parent_item.setdefault(
                                'items', []).append(new_item)
                        else:
                            flash(
                                f"Parent item '{parent_id}' not found or is not a category.", 'danger')
                    # --- 監査ログ記録 ---
                    util.log_audit_event(
                        action='ADD_CHAT_ITEM',
                        details={
                            'parent_id': parent_id, 'item_id': new_id,
                            'item_name': new_name, 'item_type': new_type
                        }
                    )

            elif action == 'edit':
                item_id = request.form.get('id')
                item, _, _ = find_item_and_parent(
                    chat_config.get('categories', []), item_id)
                if not item:
                    item, _, _ = find_item_and_parent(
                        chat_config.get('global', []), item_id)

                if item:
                    item['name'] = request.form.get(
                        'name', item['name']).strip()
                    item['description'] = request.form.get(
                        'description', item.get('description', '')).strip()
                    if item['type'] == 'room':
                        item['push'] = 'push' in request.form
                        item['lock'] = 'lock' in request.form
                        item['log'] = 'log' in request.form

                    # --- 監査ログ記録 ---
                    util.log_audit_event(
                        action='EDIT_CHAT_ITEM',
                        details={
                            'item_id': item_id,
                            'new_name': item['name'],
                            'new_description': item.get('description'),
                            'new_settings': {'push': item.get('push'), 'lock': item.get('lock'), 'log': item.get('log')} if item['type'] == 'room' else {}
                        }
                    )
                else:
                    flash(f"Item '{item_id}' not found for editing.", 'danger')

            elif action == 'delete':
                item_id = request.form.get('id')
                item, parent, index = find_item_and_parent(
                    chat_config.get('categories', []), item_id)
                target_list = None
                if item:
                    if parent:
                        target_list = parent.get('items')
                    else:
                        target_list = chat_config.get('categories')
                else:
                    item, parent, index = find_item_and_parent(
                        chat_config.get('global', []), item_id)
                    if item:
                        target_list = chat_config.get('global')

                if item and target_list is not None and index != -1:
                    del target_list[index]
                    # --- 監査ログ記録 ---
                    util.log_audit_event(
                        action='DELETE_CHAT_ITEM',
                        details={
                            'item_id': item_id,
                            'item_name': item.get('name'),
                        }
                    )
                else:
                    flash(
                        f"Item '{item_id}' not found for deletion.", 'danger')

            util.save_chat_config(chat_config)
            flash('Chat configuration updated successfully.', 'success')

        except Exception as e:
            flash(f"An error occurred: {e}", 'danger')

        return redirect(url_for('admin.chat_management'))

    # util.load_chat_config() はYAMLファイル全体を辞書として返す
    raw_config = util.load_chat_config()
    # テンプレートが期待する形式に整形する
    chat_config = {
        'categories': raw_config.get('categories', []),
        'global': raw_config.get('global', [])
    }
    return render_template('admin/chat_management.html', title="Chat Room Management", chat_config=chat_config)


@admin_bp.route('/chatrooms/reorder', methods=['POST'])
@sysop_required
def reorder_chat_items():
    """チャットアイテムの並び替えAPI。D&D操作に応じて `chatroom.yaml` を更新します。"""
    data = request.get_json()
    parent_id = data.get('parent_id')
    ordered_ids = data.get('ordered_ids')

    if not parent_id or not ordered_ids:
        return jsonify({'status': 'error', 'message': 'Missing data.'}), 400

    try:
        chat_config = util.load_chat_config()

        target_list = None
        if parent_id == 'root_categories':
            target_list = chat_config.get('categories', [])
        elif parent_id == 'root_global':
            target_list = chat_config.get('global', [])
        else:
            def find_list(items, p_id):
                for item in items:
                    if item.get('id') == p_id:
                        return item.get('items')
                    if 'items' in item:
                        found = find_list(item['items'], p_id)
                        if found is not None:
                            return found
                return None
            target_list = find_list(
                chat_config.get('categories', []), parent_id)

        if target_list is None:
            return jsonify({'status': 'error', 'message': f"Parent '{parent_id}' not found."}), 404

        # Create a map of items by ID for quick lookup
        item_map = {item['id']: item for item in target_list}
        # Reorder the list based on the ordered_ids from the client
        target_list[:] = [item_map[id] for id in ordered_ids if id in item_map]

        util.save_chat_config(chat_config)
        # --- 監査ログ記録 ---
        util.log_audit_event(
            action='REORDER_CHAT_ITEMS',
            details={
                'parent_id': parent_id,
                'ordered_ids': ordered_ids
            }
        )
        return jsonify({'status': 'success'})

    except Exception as e:
        logging.error(f"Error reordering chat items: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/bbs', methods=['GET', 'POST'])
@sysop_required
def bbs_management():
    """BBS管理（掲示板一覧 & メニュー構造）。掲示板とメニュー構造をタブ形式で管理します。"""
    def find_item_and_parent(items, item_id, parent=None):
        """IDでアイテムを再帰的に探し、アイテムとその親、インデックスを返します。"""
        if not isinstance(items, list):
            return None, None, -1
        for i, item in enumerate(items):
            if item.get('id') == item_id:
                return item, parent, i
            if 'items' in item:
                found_item, found_parent, found_index = find_item_and_parent(
                    item['items'], item_id, item)
                if found_item:
                    return found_item, found_parent, found_index
        return None, None, -1

    tab = request.args.get('tab', 'list')

    if request.method == 'POST':
        bbs_config = util.load_bbs_config()
        action = request.form.get('action')

        try:
            if action == 'add':
                parent_id = request.form.get('parent_id')
                new_id = request.form.get('id').strip()
                new_type = request.form.get('type')

                if not new_id:
                    flash('ID is required.', 'danger')
                else:
                    new_item = {'id': new_id, 'type': new_type}

                    if parent_id == 'root_categories':
                        bbs_config.setdefault(
                            'categories', []).append(new_item)
                    else:
                        parent_item, _, _ = find_item_and_parent(
                            bbs_config.get('categories', []), parent_id)
                        if parent_item and parent_item.get('type') == 'child':
                            parent_item.setdefault(
                                'items', []).append(new_item)
                        else:
                            flash(
                                f"Parent item '{parent_id}' not found or is not a category.", 'danger')
                    if new_id:
                        # --- 監査ログ記録 ---
                        util.log_audit_event(
                            action='ADD_BBS_MENU_ITEM',
                            details={
                                'parent_id': parent_id,
                                'item_id': new_id,
                                'item_type': new_type
                            }
                        )
            elif action == 'edit':
                item_id = request.form.get('id')
                item, _, _ = find_item_and_parent(
                    bbs_config.get('categories', []), item_id)

                if item:
                    name = request.form.get('name', '').strip()
                    description = request.form.get('description', '').strip()
                    if name:
                        item['name'] = name
                    elif 'name' in item:
                        del item['name']
                    if description:
                        item['description'] = description
                    elif 'description' in item:
                        del item['description']

                    # --- 監査ログ記録 ---
                    util.log_audit_event(
                        action='EDIT_BBS_MENU_ITEM',
                        details={
                            'item_id': item_id,
                            'new_name': name,
                            'new_description': description,
                        }
                    )
                else:
                    flash(f"Item '{item_id}' not found for editing.", 'danger')

            elif action == 'delete':
                item_id = request.form.get('id')
                item, parent, index = find_item_and_parent(
                    bbs_config.get('categories', []), item_id)
                target_list = None
                if item:
                    if parent:
                        target_list = parent.get('items')
                    else:
                        target_list = bbs_config.get('categories')

                if item and target_list is not None and index != -1:
                    del target_list[index]
                    # --- 監査ログ記録 ---
                    util.log_audit_event(
                        action='DELETE_BBS_MENU_ITEM',
                        details={
                            'item_id': item_id,
                            'parent_id': parent.get('id') if parent else 'root_categories',
                        }
                    )
                else:
                    flash(
                        f"Item '{item_id}' not found for deletion.", 'danger')

            util.save_bbs_config(bbs_config)
            flash('BBS menu configuration updated successfully.', 'success')

        except Exception as e:
            flash(f"An error occurred: {e}", 'danger')

        return redirect(url_for('admin.bbs_management', tab='menu'))

    # --- GET Request Handling ---
    if tab == 'list':
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
            boards_from_db, total_items, total_pages = [], 0, 0

        search_params = {'tab': 'list', 'q': search_term,
                         'sort_by': sort_by, 'order': order, 'per_page': per_page}
        search_params_for_per_page = {
            k: v for k, v in request.args.items() if k != 'per_page'}

        pagination = {'page': page, 'per_page': per_page, 'total_items': total_items,
                      'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages}

        enriched_boards = []
        if boards_from_db:
            operator_ids_to_fetch = {op_id for board in boards_from_db for op_id in json.loads(
                board.get('operators') or '[]')}
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
            'admin/bbs_management.html', title='BBS Management', tab='list',
            boards=enriched_boards, pagination=pagination,
            sort_by=sort_by, order=order, next_order=next_order,
            search_params=search_params, search_params_for_per_page=search_params_for_per_page,
            bbs_config={}
        )

    elif tab == 'menu':
        bbs_config = util.load_bbs_config()
        board_id_map = {}
        board_info_map = {}
        all_boards, _ = database.get_all_boards_for_sysop_list(per_page=9999)
        if all_boards:
            board_id_map = {board['shortcut_id']: board['id']
                            for board in all_boards}
            board_info_map = {board['shortcut_id']
                : board for board in all_boards}

        def enrich_items_with_db_info(items):
            if not isinstance(items, list):
                return
            for item in items:
                if item.get('type') == 'board':
                    shortcut_id = item.get('id')
                    item['db_id'] = board_id_map.get(shortcut_id)
                    # yamlにnameやdescriptionがなければ、DBの情報をフォールバックとして使用
                    if 'name' not in item or not item['name']:
                        item['name'] = board_info_map.get(
                            shortcut_id, {}).get('name', '')
                    if 'description' not in item or not item['description']:
                        item['description'] = board_info_map.get(
                            shortcut_id, {}).get('description', '')
                if 'items' in item and isinstance(item.get('items'), list):
                    enrich_items_with_db_info(item['items'])
        enrich_items_with_db_info(bbs_config.get('categories', []))

        return render_template(
            'admin/bbs_management.html', title="BBS Management", tab='menu',
            bbs_config=bbs_config,

            search_params={},
            search_params_for_per_page={},
            pagination={'total_pages': 0},
            boards=[],
            next_order='asc',
            sort_by='',
            order=''
        )

    # Fallback redirect
    return redirect(url_for('admin.bbs_management', tab='list'))


@admin_bp.route('/boards/export/<int:board_id>')
@sysop_required
def export_board(board_id):
    """指定された掲示板の情報と記事をJSON形式でエクスポートします。"""
    board = database.get_board_by_id(board_id)
    if not board:
        flash(f"Board with ID {board_id} not found.", 'danger')
        return redirect(url_for('admin.bbs_management', tab='list'))

    articles = database.get_articles_by_board_id(
        board_id, include_deleted=True)

    # ユーザーIDからユーザー名へのマッピングを作成
    user_ids = {
        int(art['user_id']) for art in articles if str(art['user_id']).isdigit()
    }
    user_map = database.get_user_names_from_user_ids(list(user_ids))

    # エクスポート用の記事リストを作成
    exported_articles = []
    for article in articles:
        user_id_str = str(article['user_id'])
        username = ''
        if user_id_str.isdigit():
            username = user_map.get(int(user_id_str), '')

        exported_articles.append({
            'article_number': article.get('article_number'),
            'parent_article_id': article.get('parent_article_id'),
            'user_id_original': article.get('user_id'),
            'username_original': username,
            'title': article.get('title'),
            'body': article.get('body'),
            'created_at': article.get('created_at'),
            'is_deleted': article.get('is_deleted'),
            'ip_address': article.get('ip_address'),
            'attachment_filename': article.get('attachment_filename'),
            'attachment_originalname': article.get('attachment_originalname'),
            'attachment_size': article.get('attachment_size')
        })

    export_data = {
        'board_info': dict(board),
        'articles': exported_articles
    }

    response = Response(json.dumps(export_data, indent=2,
                        ensure_ascii=False), mimetype='application/json')
    response.headers["Content-Disposition"] = f"attachment; filename=board_{board['shortcut_id']}_export.json"
    return response


@admin_bp.route('/boards/import', methods=['POST'])
@sysop_required
def import_board():
    """アップロードされたJSONファイルから新しい掲示板をインポートします。"""
    if 'import_file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('admin.bbs_management', tab='list'))

    file = request.files['import_file']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('admin.bbs_management', tab='list'))

    new_shortcut_id = request.form.get('new_shortcut_id', '').strip()
    if not new_shortcut_id:
        flash('New Shortcut ID is required for import.', 'danger')
        return redirect(url_for('admin.bbs_management', tab='list'))

    if database.get_board_by_shortcut_id(new_shortcut_id):
        flash(f'Shortcut ID "{new_shortcut_id}" already exists.', 'danger')
        return redirect(url_for('admin.bbs_management', tab='list'))

    if file and file.filename.endswith('.json'):
        try:
            import_data = json.load(file.stream)
            board_info = import_data.get('board_info', {})
            articles_to_import = import_data.get('articles', [])

            # 新しい掲示板を作成
            new_board_id = database.create_board_entry(
                shortcut_id=new_shortcut_id,
                name=board_info.get('name', 'Imported Board'),
                description=board_info.get('description', ''),
                operators=board_info.get('operators', '[]'),
                default_permission=board_info.get(
                    'default_permission', 'open'),
                kanban_body=board_info.get('kanban_body', ''),
                status=board_info.get('status', 'active'),
                read_level=board_info.get('read_level', 1),
                write_level=board_info.get('write_level', 1),
                board_type=board_info.get('board_type', 'simple'),
                allow_attachments=board_info.get('allow_attachments', 0),
                allowed_extensions=board_info.get('allowed_extensions'),
                max_attachment_size_mb=board_info.get(
                    'max_attachment_size_mb'),
                max_threads=board_info.get('max_threads', 0),
                max_replies=board_info.get('max_replies', 0)
            )

            if not new_board_id:
                raise Exception(
                    "Failed to create a new board in the database.")

            # 記事をインポート
            # 元の記事番号と新しい記事IDのマッピング
            original_article_number_to_new_id = {}

            for article_data in sorted(articles_to_import, key=lambda x: x.get('article_number', 0)):
                # 投稿者IDを解決
                user_id_to_save = '1'  # デフォルトはGUEST
                if article_data.get('username_original'):
                    user = database.get_user_auth_info(
                        article_data['username_original'])
                    if user:
                        user_id_to_save = user['id']

                # 親記事IDを解決
                parent_id_to_save = None
                original_parent_num = article_data.get('parent_article_id')
                if original_parent_num and original_parent_num in original_article_number_to_new_id:
                    parent_id_to_save = original_article_number_to_new_id[original_parent_num]

                new_article_id = database.insert_article(
                    board_id_pk=new_board_id,
                    article_number=article_data.get('article_number'),
                    user_identifier=user_id_to_save,
                    title=article_data.get('title'),
                    body=article_data.get('body'),
                    timestamp=article_data.get('created_at'),
                    ip_address=article_data.get('ip_address'),
                    parent_article_id=parent_id_to_save,
                    attachment_filename=article_data.get(
                        'attachment_filename'),
                    attachment_originalname=article_data.get(
                        'attachment_originalname'),
                    attachment_size=article_data.get('attachment_size')
                )

                original_article_number_to_new_id[article_data.get(
                    'article_number')] = new_article_id

            flash(
                f'Successfully imported board as "{new_shortcut_id}". {len(articles_to_import)} articles were imported.', 'success')
        except Exception as e:
            flash(f'An error occurred during import: {e}', 'danger')
    else:
        flash('Please upload a valid .json file.', 'danger')

    return redirect(url_for('admin.bbs_management', tab='list'))


@admin_bp.route('/access', methods=['GET', 'POST'])
@sysop_required
def access_management():
    """アクセス管理（ログ & IP BAN）。アクセスログ閲覧とIP BANをタブ形式で一元管理します。"""
    from collections import deque
    tab = request.args.get('tab', 'logs')
    ip_to_ban = request.args.get('ip_address', '')

    # エラーログはどのタブでも共通して読み込む
    error_logs = []
    try:
        log_dir = os.path.join(current_app.config['PROJECT_ROOT'], 'logs')
        error_log_path = os.path.join(log_dir, 'grbbs.error.log')
        if os.path.exists(error_log_path):
            with open(error_log_path, 'r', encoding='utf-8') as f:
                # ファイルの末尾5000行のみを読み込む
                error_logs = list(deque(f, 5000))[::-1]
    except Exception as e:
        flash(f"Error reading error log file: {e}", 'danger')

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            ip_address = request.form.get('ip_address', '').strip()
            reason = request.form.get('reason', '').strip()
            if not ip_address:
                flash('IP Address/CIDR is required.', 'danger')
            else:
                try:
                    ipaddress.ip_network(ip_address, strict=False)
                    if database.add_ip_ban(ip_address, reason, session.get('user_id')):
                        flash(f'Successfully banned {ip_address}.', 'success')
                    else:
                        flash(
                            f'Failed to ban {ip_address}. The IP address/CIDR might already exist.', 'danger')
                except ValueError:
                    flash(
                        f'Invalid IP Address or CIDR notation: {ip_address}', 'danger')
        elif action == 'delete':
            ban_id = request.form.get('id')
            if ban_id and database.delete_ip_ban(ban_id):
                flash('IP ban rule has been removed.', 'success')
            else:
                flash('Failed to remove IP ban rule.', 'danger')
            return redirect(url_for('admin.access_management', tab='bans'))
        elif action == 'cleanup_logs':
            try:
                # configから保持日数を取得
                log_retention_days = current_app.config.get('DATABASE', {}).get(
                    'log_retention_days', 90)
                if log_retention_days > 0:
                    deleted_count = database.cleanup_old_access_logs(
                        log_retention_days)
                    flash(
                        f'Successfully cleaned up {deleted_count} old log entries (older than {log_retention_days} days).', 'success')
                else:
                    flash('Log cleanup is disabled (log_retention_days <= 0).', 'info')
            except Exception as e:
                logging.error(f"Manual log cleanup failed: {e}", exc_info=True)
                flash('An error occurred during manual log cleanup.', 'danger')
            return redirect(url_for('admin.access_management', tab='logs'))

    # --- GET Request Handling ---
    if tab == 'logs':
        page = request.args.get('page', 1, type=int)
        search_ip = request.args.get('ip', '')
        search_user = request.args.get('user', '')
        search_display_name = request.args.get('display_name', '')
        search_event = request.args.get('event', '')
        search_message = request.args.get('message', '')
        sort_by = request.args.get('sort_by', 'timestamp')
        order = request.args.get('order', 'desc')
        per_page = request.args.get('per_page', 15, type=int)
        if page < 1:
            page = 1

        try:
            logs, total_items = database.get_access_logs(
                page=page, per_page=per_page, ip_address=search_ip, username=search_user,
                display_name=search_display_name, event_type=search_event,
                message=search_message, sort_by=sort_by, order=order
            )
            total_pages = (total_items + per_page - 1) // per_page
        except Exception as e:
            flash(f"Error retrieving access logs: {e}", 'danger')
            logs, total_items, total_pages = [], 0, 0

        search_params = {
            'tab': 'logs', 'ip': search_ip, 'user': search_user, 'display_name': search_display_name,
            'event': search_event, 'message': search_message, 'sort_by': sort_by, 'order': order,
            'per_page': per_page
        }
        search_params_for_per_page = {k: v for k, v in request.args.items() if k not in [
            'per_page', 'tab']}
        pagination = {
            'page': page, 'per_page': per_page, 'total_items': total_items,
            'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages
        }
        next_order = 'desc' if order == 'asc' else 'asc'

        return render_template(
            'admin/log_viewer.html', title='Access Management', tab='logs',
            logs=logs, error_logs=error_logs, search_params=search_params,
            search_params_for_per_page=search_params_for_per_page, pagination=pagination,
            sort_by=sort_by, order=order, next_order=next_order,
            # Dummy data for bans tab
            bans=[], user_map={}, ip_to_ban=''
        )

    elif tab == 'error':
        # error_logsは既に読み込み済み
        return render_template(
            'admin/log_viewer.html', title='Access Management', tab='error',
            error_logs=error_logs,
            # Dummy data for other tabs
            logs=[], bans=[], user_map={}, ip_to_ban='',
            search_params={}, search_params_for_per_page={},
            pagination={'total_pages': 0}, sort_by='', order='', next_order=''
        )

    elif tab == 'bans':
        try:
            bans = database.get_all_ip_bans()
            user_ids = {ban['added_by'] for ban in bans if ban.get('added_by')}
            user_map = database.get_user_names_from_user_ids(list(user_ids))
        except Exception as e:
            flash(f"Error retrieving IP ban list: {e}", 'danger')
            bans, user_map = [], {}

        return render_template(
            'admin/log_viewer.html', title="Access Management", tab='bans',
            bans=bans, user_map=user_map, ip_to_ban=ip_to_ban,
            error_logs=error_logs,
            logs=[], search_params={}, search_params_for_per_page={},
            pagination={'total_pages': 0}, sort_by='', order='', next_order=''
        )

    elif tab == 'audit':
        page = request.args.get('page', 1, type=int)
        search_user = request.args.get('audit_user', '').strip()
        search_ip = request.args.get('audit_ip', '').strip()
        search_action = request.args.get('audit_action', '').strip()
        search_keyword = request.args.get('audit_keyword', '').strip()
        per_page = request.args.get('per_page', 15, type=int)
        if page < 1:
            page = 1

        audit_logs = []
        try:
            log_dir = os.path.join(current_app.config['PROJECT_ROOT'], 'logs')
            audit_log_path = os.path.join(log_dir, 'audit.log')
            if os.path.exists(audit_log_path):
                with open(audit_log_path, 'r', encoding='utf-8') as f:
                    # ファイルの末尾5000行のみを読み込む
                    for line in deque(f, 5000):
                        # タイムスタンプ部分を除外し、JSON部分のみを抽出
                        try:
                            json_start_index = line.find(' - ')
                            if json_start_index != -1:
                                timestamp_full_str = line[:json_start_index].strip(
                                )
                                timestamp_str = timestamp_full_str.split(',')[
                                    0]
                                json_str = line[json_start_index + 3:].strip()
                                log_data = json.loads(json_str)
                                log_data['timestamp'] = timestamp_str

                                # フィルタリングロジック
                                match = True
                                if search_user and search_user.lower() not in log_data.get('username', '').lower():
                                    match = False
                                if search_ip and search_ip not in log_data.get('ip_address', ''):
                                    match = False
                                if search_action and search_action.lower() not in log_data.get('action', '').lower():
                                    match = False
                                if search_keyword:
                                    details_str = json.dumps(log_data.get(
                                        'details', {}), ensure_ascii=False)
                                    if search_keyword.lower() not in details_str.lower():
                                        match = False

                                if match:
                                    audit_logs.append(log_data)
                        except json.JSONDecodeError:
                            continue  # パースできない行はスキップ
            audit_logs.reverse()  # 新しいログを上にする
        except Exception as e:
            flash(f"Error reading audit log file: {e}", 'danger')

        total_items = len(audit_logs)
        total_pages = (total_items + per_page - 1) // per_page
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paginated_audit_logs = audit_logs[start_index:end_index]

        pagination = {
            'page': page, 'per_page': per_page, 'total_items': total_items,
            'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages
        }
        search_params = {'tab': 'audit', 'per_page': per_page, 'audit_user': search_user,
                         'audit_ip': search_ip, 'audit_action': search_action, 'audit_keyword': search_keyword}
        search_params_for_per_page = {
            k: v for k, v in request.args.items() if k not in ['per_page', 'tab']}

        return render_template('admin/log_viewer.html', title='Access Management', tab='audit',
                               audit_logs=paginated_audit_logs, pagination=pagination,
                               search_params=search_params, search_params_for_per_page=search_params_for_per_page, error_logs=error_logs)

    return redirect(url_for('admin.access_management', tab='logs'))


@admin_bp.route('/bbs_menu/reorder', methods=['POST'])
@sysop_required
def reorder_bbs_items():
    """BBSメニューアイテムの並び替えAPI。D&D操作に応じて `bbs_mode3.yaml` を更新します。"""
    data = request.get_json()
    parent_id = data.get('parent_id')
    ordered_ids = data.get('ordered_ids')

    if not parent_id or not ordered_ids:
        return jsonify({'status': 'error', 'message': 'Missing data.'}), 400

    try:
        bbs_config = util.load_bbs_config()

        all_items_map = {}
        all_lists = []

        def build_map_and_collect_lists(items):
            if not isinstance(items, list):
                return
            all_lists.append(items)
            for item in items:
                all_items_map[item['id']] = item
                if item.get('type') == 'child' and 'items' in item and isinstance(item['items'], list):
                    build_map_and_collect_lists(item['items'])
        build_map_and_collect_lists(bbs_config.get('categories', []))

        target_list = None
        if parent_id == 'root_categories':
            target_list = bbs_config.get('categories', [])
        else:
            parent_item = all_items_map.get(parent_id)
            if parent_item and parent_item.get('type') == 'child':
                target_list = parent_item.setdefault('items', [])

        if target_list is None:
            return jsonify({'status': 'error', 'message': f"Parent '{parent_id}' not found or is not a category."}), 404

        moved_item_ids = set(ordered_ids)
        for lst in all_lists:
            lst[:] = [item for item in lst if item['id'] not in moved_item_ids]

        reordered_items = []
        for item_id in ordered_ids:
            if item_id in all_items_map:
                reordered_items.append(all_items_map[item_id])
            else:
                logging.warning(
                    f"Reordering BBS menu: Item with ID '{item_id}' not found in map.")

        target_list[:] = reordered_items

        util.save_bbs_config(bbs_config)
        # --- 監査ログ記録 ---
        util.log_audit_event(
            action='REORDER_BBS_MENU',
            details={
                'parent_id': parent_id,
                'ordered_ids': ordered_ids
            })
        return jsonify({'status': 'success'})

    except Exception as e:
        logging.error(f"Error reordering BBS menu items: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_bp.route('/content', methods=['GET', 'POST'])
@sysop_required
def content_management():
    """コンテンツ管理（記事 & 添付ファイル）。記事検索と添付ファイル管理をタブ形式で提供します。"""
    tab = request.args.get('tab', 'articles')

    if tab == 'articles':
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
                page=page, per_page=per_page, keyword=keyword, author_id=author_id,
                author_name_guest=author_name_guest, article_id=article_id_search
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

        search_params = {'tab': 'articles', 'q': keyword,
                         'author': author_name, 'per_page': per_page}
        search_params_for_per_page = {k: v for k, v in request.args.items() if k not in [
            'per_page', 'tab']}
        pagination = {'page': page, 'per_page': per_page, 'total_items': total_items,
                      'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages}

        return render_template('admin/content_management.html', title='Content Management', tab='articles',
                               articles=articles, pagination=pagination, search_params=search_params,
                               search_params_for_per_page=search_params_for_per_page,
                               search_keyword=keyword, search_author=author_name,
                               # Dummy data for attachments tab
                               attachments=[], quarantined_files=[], sort_by='', order='', next_order='')

    elif tab == 'attachments':
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
            articles_with_attachments, total_items, total_pages = [], 0, 0

        enriched_attachments = []
        if articles_with_attachments:
            user_ids_to_fetch = {art['user_id'] for art in articles_with_attachments if str(
                art['user_id']).isdigit()}
            id_to_name_map = database.get_user_names_from_user_ids(
                list(user_ids_to_fetch))
            attachment_dir = current_app.config.get('ATTACHMENT_DIR')

            for art in articles_with_attachments:
                mutable_art = dict(art)
                user_id_str = str(mutable_art['user_id'])
                if user_id_str.isdigit():
                    mutable_art['author_display_name'] = id_to_name_map.get(
                        int(user_id_str), f"(ID:{user_id_str})")
                else:
                    mutable_art['author_display_name'] = user_id_str
                filepath = os.path.join(
                    attachment_dir, art['attachment_filename'])
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
            flash(f"Could not read quarantine log: {e}", 'danger')

        search_params = {'tab': 'attachments', 'sort_by': sort_by,
                         'order': order, 'per_page': per_page}
        search_params_for_per_page = {k: v for k, v in request.args.items() if k not in [
            'per_page', 'tab']}
        pagination = {'page': page, 'per_page': per_page, 'total_items': total_items,
                      'total_pages': total_pages, 'has_prev': page > 1, 'has_next': page < total_pages}

        return render_template('admin/content_management.html', title='Content Management', tab='attachments',
                               attachments=enriched_attachments, quarantined_files=quarantined_files,
                               pagination=pagination, sort_by=sort_by, order=order, next_order=next_order,
                               search_params=search_params, search_params_for_per_page=search_params_for_per_page,
                               # Dummy data for articles tab
                               articles=[], search_keyword='', search_author='')
