# ==============================================================================
# Admin Panel Routes
#
# This file defines all the web routes for the GrassRootsBBS administration
# panel. It uses a Flask Blueprint to organize these routes into a distinct
# group, which is then registered with the main Flask application.
# ==============================================================================
#
# ==============================================================================
# 管理画面ルート定義
#
# このファイルは、GrassRootsBBS管理画面の全てのWebルートを定義します。
# Flaskのブループリント機能を使用してこれらのルートをグループ化し、
# メインのFlaskアプリケーションに登録します。
# ==============================================================================

from flask import Blueprint, render_template, request, flash, redirect, url_for, session, send_from_directory, g
from ..decorators import sysop_required
import json
import os
from datetime import datetime, timedelta
import time
import logging
from .. import database, util, backup_util, plugin_manager
import psutil
import toml
import shutil

# --- Blueprint Definition / ブループリントの定義 ---
# 'admin' という名前のブループリントを作成します。これにより、管理画面のルートをモジュール化できます。
# All routes defined in this file will be prefixed with /admin.
# このファイルで定義される全てのルートは /admin プレフィックスが付きます。
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# --- Backup Directory Configuration / バックアップディレクトリ設定 ---
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
        mode_key = f"mode_{menu_mode}"  # e.g., 'mode_1', 'mode_2'
        if mode_key in node:
            return node[mode_key]
        else:
            # 末端でなければ、さらに下の階層を処理
            return {key: _process_texts_for_mode(value, menu_mode) for key, value in node.items()}
    return node


@admin_bp.before_request
def load_admin_texts():
    """
    管理画面への各リクエストの前に、ユーザーの言語設定に応じたテキストをロードします。
    ロードされたテキストは、リクエスト中のみ有効なグローバル変数 `g.texts` に格納されます。

    Before each request to the admin panel, load texts corresponding to the user's language setting.
    The loaded texts are stored in `g.texts`, a global variable available only during the request.
    """
    menu_mode = session.get('menu_mode', '3')  # デフォルトは英語モード
    # adminセクションのテキストをロードし、指定されたmenu_modeのテキストを抽出
    g.texts = _process_texts_for_mode(
        util.load_master_text_data().get('admin', {}), menu_mode)


@admin_bp.route('/')
@sysop_required
def dashboard():
    """管理画面のダッシュボードを表示します。"""
    # 循環参照を避けるため、関数内でインポートします
    from .. import webapp
    # オンラインメンバーの数を取得
    online_count = len(webapp.get_webapp_online_members())

    # 統計情報を取得
    stats = {
        'total_users': database.get_total_user_count(),
        'total_boards': database.get_total_board_count(),
        'total_articles': database.get_total_article_count(),
        'online_users': online_count
    }

    # --- System Health ---
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

    # --- グラフ用データの準備 ---
    # 過去7日間の日付ラベルを生成
    labels = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
              for i in range(6, -1, -1)]

    # ユーザー登録数のデータを取得・整形
    user_data_raw = database.get_daily_user_registrations(days=7)
    user_data_map = {item['registration_date'].strftime(
        '%Y-%m-%d'): item['count'] for item in user_data_raw} if user_data_raw else {}
    user_counts = [user_data_map.get(label, 0) for label in labels]

    # 記事投稿数のデータを取得・整形
    article_data_raw = database.get_daily_article_posts(days=7)
    article_data_map = {item['post_date'].strftime(
        '%Y-%m-%d'): item['count'] for item in article_data_raw} if article_data_raw else {}
    article_counts = [article_data_map.get(label, 0) for label in labels]

    chart_data = {
        'labels': labels,
        'user_registrations': user_counts,
        'article_posts': article_counts,
    }
    # --- ここまで ---

    return render_template('admin/dashboard.html',
                           title=g.texts.get('dashboard', {}).get(
                               'title', 'Dashboard'),
                           stats=stats,
                           chart_data=json.dumps(chart_data),
                           system_health=system_health)


@admin_bp.route('/who')
@sysop_required
def who_online():
    """オンラインユーザーの詳細一覧ページを表示します。"""
    # 循環参照を避けるため、関数内でwebappをインポートします
    from .. import webapp
    online_members_raw = webapp.get_webapp_online_members()

    # データを整形し、接続時間を計算
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

    # ソート処理
    sort_by = request.args.get('sort_by', 'connect_time')
    order = request.args.get('order', 'asc')
    reverse = (order == 'desc')

    # ソートキーを安全に処理
    def sort_key(item):
        key = item.get(sort_by)
        return str(key).lower() if isinstance(key, str) else key if key is not None else 0

    online_list.sort(key=sort_key, reverse=reverse)

    next_order = 'desc' if order == 'asc' else 'asc'

    return render_template(
        'admin/who_online.html',
        title=g.texts.get('who_online', {}).get('title', "Who's Online"),
        online_list=online_list,
        sort_by=sort_by,
        order=order,
        next_order=next_order
    )


@admin_bp.route('/who/kick/<sid>', methods=['POST'])
@sysop_required
def kick_user(sid):
    """指定されたSIDのユーザーセッションを強制的に切断します。"""
    # webappモジュールからキック関数を呼び出す
    from .. import webapp

    online_members = webapp.get_webapp_online_members()
    member_to_kick = online_members.get(sid)
    display_name = member_to_kick.get(
        'display_name', f'session {sid}') if member_to_kick else f'session {sid}'

    if webapp.kick_user_session(sid):
        flash(f"User '{display_name}' has been kicked.", 'success')
    else:
        flash(
            f"Failed to kick user '{display_name}'. They may have already disconnected.", 'warning')

    return redirect(url_for('admin.who_online'))


@admin_bp.route('/users')
@sysop_required
def user_list():
    """ユーザー一覧ページを表示します。"""
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
    """新規ユーザー作成ページを表示し、作成処理を行います。"""
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
    """ユーザー編集ページを表示し、更新処理を行います。"""
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
    """指定されたユーザーをデータベースから削除します。"""
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


@admin_bp.route('/boards')
@sysop_required
def board_list():
    """掲示板一覧ページを表示します。"""
    # クエリパラメータからソート順と検索語を取得
    sort_by = request.args.get('sort_by', 'shortcut_id')
    order = request.args.get('order', 'asc')
    search_term = request.args.get('q', '')

    # 次のソート順を計算
    next_order = 'desc' if order == 'asc' else 'asc'

    boards_from_db = database.get_all_boards_for_sysop_list(
        sort_by=sort_by, order=order, search_term=search_term)

    enriched_boards = []

    if boards_from_db:
        # オペレーターIDをすべて集めて、一度のクエリで名前を取得する準備
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
            # オペレーター名を取得して文字列に変換
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

    # 'operators' はDBで直接ソートできないため、ここでPython側でソートする
    if sort_by == 'operators':
        enriched_boards.sort(key=lambda x: x.get(
            'operator_names_str', ''), reverse=(order == 'desc'))

    return render_template(
        'admin/board_list.html', title='Board Management', boards=enriched_boards,
        sort_by=sort_by, order=order, next_order=next_order, search_term=search_term)


@admin_bp.route('/boards/new', methods=['GET', 'POST'])
@sysop_required
def new_board():
    """新規掲示板作成ページを表示し、作成処理を行います。"""
    if request.method == 'POST':
        # フォームからデータを取得
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

        # バリデーション
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

        # シスオペをオペレーターとして自動設定
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
    """掲示板編集ページを表示し、更新処理を行います。"""
    board = database.get_board_by_id(board_id)
    if not board:
        flash(f"Board with ID {board_id} not found.", 'danger')
        return redirect(url_for('admin.board_list'))

    if request.method == 'POST':
        # フォームからデータを取得
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        kanban_body = request.form.get('kanban_body', '').strip()
        board_type = request.form.get('board_type', 'simple')
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

        # オペレーター文字列をIDのリストに変換
        new_operator_ids = []
        if operators_str:
            operator_names = [name.strip().upper()
                              for name in operators_str.split(',') if name.strip()]
            all_users = database.get_all_users()
            user_map = {user['name'].upper(): user['id'] for user in all_users}

            invalid_names = []
            for name in operator_names:
                if name in user_map:
                    new_operator_ids.append(user_map[name])
                else:
                    invalid_names.append(name)

            if invalid_names:
                flash(
                    f"The following operator names were not found: {', '.join(invalid_names)}", 'danger')
                return render_template('admin/edit_board.html', title='Edit Board', board=board)

        # B/Wリストの処理
        permission_users_str = request.form.get('permission_users', '').strip()
        new_permission_user_ids = []
        if permission_users_str:
            permission_user_names = [name.strip().upper()
                                     for name in permission_users_str.split(',') if name.strip()]
            # user_map is already available from operator processing
            invalid_perm_names = []
            for name in permission_user_names:
                if name in user_map:
                    new_permission_user_ids.append(user_map[name])
                else:
                    invalid_perm_names.append(name)
            if invalid_perm_names:
                flash(
                    f"The following B/W list user names were not found: {', '.join(invalid_perm_names)}", 'danger')
                return render_template('admin/edit_board.html', title='Edit Board', board=board)

        # バリデーション
        if not name:
            flash('Board Name is required.', 'danger')
            return render_template('admin/edit_board.html', title='Edit Board', board=board)

        updates = {
            'name': name, 'description': description, 'kanban_body': kanban_body, 'board_type': board_type,
            'default_permission': default_permission, 'read_level': read_level, 'write_level': write_level,
            'allow_attachments': allow_attachments, 'allowed_extensions': allowed_extensions,
            'max_attachment_size_mb': max_attachment_size_mb,
            'operators': json.dumps(new_operator_ids),
            'max_threads': max_threads,
            'max_replies': max_replies if board_type == 'thread' else 0
        }

        if database.update_record('boards', updates, {'id': board_id}):
            # B/Wリストの更新処理
            # 1. 既存のパーミッションを削除
            database.delete_board_permissions_by_board_id(board_id)

            # 2. 新しいパーミッションを追加
            if new_permission_user_ids:
                # default_permission はフォームから送信された新しい値を使う
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

    # 現在のオペレーターIDリストをユーザー名のカンマ区切り文字列に変換してテンプレートに渡す
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

    # B/Wリストのユーザー名を取得
    current_permissions = database.get_board_permissions(board_id)
    board['permission_users_str'] = ""
    if current_permissions:
        user_ids_in_list = [perm['user_id'] for perm in current_permissions]
        # get_user_names_from_user_ids expects a list of ints
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
    """指定された掲示板と関連するすべての記事を削除します。"""
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
    """記事検索ページを表示し、検索結果を返します。"""
    keyword = request.args.get('q', '')
    author_name = request.args.get('author', '')

    articles = []
    if keyword or author_name:
        author_id = None
        author_name_guest = None
        if author_name:
            user = database.get_user_auth_info(author_name)
            if user:
                author_id = user['id']
            else:
                author_name_guest = author_name

        articles_from_db = database.search_all_articles(
            keyword=keyword,
            author_id=author_id,
            author_name_guest=author_name_guest
        )

        if articles_from_db:
            user_ids_to_fetch = {art['user_id'] for art in articles_from_db if str(
                art['user_id']).isdigit()}
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

    return render_template('admin/article_search.html',
                           title='Article Management',
                           articles=articles,
                           search_keyword=keyword,
                           search_author=author_name)


@admin_bp.route('/articles/delete/<int:article_id>', methods=['POST'])
@sysop_required
def delete_article(article_id):
    """記事の削除フラグをトグルします（論理削除/復元）。"""
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
    """選択された複数の記事を一括で論理削除または復元します。"""
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


@admin_bp.route('/settings', methods=['GET', 'POST'])
@sysop_required
def system_settings():
    """システム全体のアクセスレベルなどの設定ページを表示し、更新処理を行います。"""
    pref_names = ['bbs', 'chat', 'mail', 'telegram', 'userpref',
                  'who', 'default_exploration_list', 'hamlet', 'login_message']

    if request.method == 'POST':
        # フォームからデータを取得
        settings_to_update = {
            'bbs': request.form.get('bbs', type=int),
            'chat': request.form.get('chat', type=int),
            'mail': request.form.get('mail', type=int),
            'telegram': request.form.get('telegram', type=int),
            'userpref': request.form.get('userpref', type=int),
            'who': request.form.get('who', type=int),
            'hamlet': request.form.get('hamlet', type=int),
            'default_exploration_list': request.form.get('default_exploration_list', '').strip(),
            'login_message': request.form.get('login_message', '').strip()
        }

        # バリデーション (レベルが0-5の範囲にあるか)
        for key in ['bbs', 'chat', 'mail', 'telegram', 'userpref', 'who', 'hamlet']:
            if not (0 <= settings_to_update[key] <= 5):
                flash(
                    f"Invalid level for {key}. Must be between 0 and 5.", 'danger')
                pref_list = database.read_server_pref()
                current_settings = dict(
                    zip(pref_names, pref_list)) if pref_list else {}
                return render_template('admin/system_settings.html', title='System Settings', settings=current_settings)

        if database.update_record('server_pref', settings_to_update, {'id': 1}):
            flash('System settings have been updated successfully.', 'success')
        else:
            flash('Failed to update system settings.', 'danger')
        return redirect(url_for('admin.system_settings'))

    pref_list = database.read_server_pref()
    current_settings = dict(zip(pref_names, pref_list)) if pref_list else {}
    return render_template('admin/system_settings.html', title='System Settings', settings=current_settings)


@admin_bp.route('/backup', methods=['GET', 'POST'])
@sysop_required
def backup_management():
    """バックアップの管理ページを表示し、スケジュールの保存も処理します。"""
    if request.method == 'POST':
        # スケジュール保存リクエストを処理
        if request.form.get('action') == 'save_schedule':
            # チェックボックスがONならTrue、なければFalse
            is_enabled = 'schedule_enabled' in request.form
            cron_string = request.form.get('schedule_cron', '0 3 * * *')

            if database.update_backup_schedule(is_enabled, cron_string):
                flash('Backup schedule updated successfully.', 'success')
            else:
                flash('Failed to update backup schedule.', 'danger')
            return redirect(url_for('admin.backup_management'))

    # GETリクエスト、または他のPOSTアクションの場合
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
        flash(f'Error retrieving backup list: {e}', 'error')

    return render_template('admin/backup.html', title="Backup Management", backups=backups, schedule_settings=schedule_settings)


@admin_bp.route('/backup/create', methods=['POST'])
@sysop_required
def create_backup_route():
    """手動で新しいバックアップを作成するルートです。"""
    try:
        # バックアップ作成処理を呼び出す
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
    """指定されたバックアップファイルをダウンロードさせます。"""
    # send_from_directory はディレクトリトラバーサル攻撃から保護してくれます
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)


@admin_bp.route('/backup/delete/<path:filename>', methods=['POST'])
@sysop_required
def delete_backup(filename):
    """指定されたバックアップファイルをサーバーから削除します。"""
    try:
        filepath = os.path.join(BACKUP_DIR, filename)
        # パストラバーサル攻撃のチェック
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
    """指定されたバックアップファイルからデータをリストアし、サーバーを再起動します。"""
    try:
        # リストア処理を呼び出す
        success = backup_util.restore_from_backup(filename)
        if success:
            flash(
                f'Restore from backup "{filename}" has started. The server will restart automatically upon completion.', 'success')
            # Gunicornに再起動を促すために、現在のプロセスを終了させる

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
    """すべてのBBSデータを削除し、データベースを再初期化してサーバーを再起動します。"""
    try:
        # 重要な操作なので、セッションのユーザーが本当にシスオペか再確認
        if session.get('userlevel', 0) < 5:
            flash('You do not have sufficient permissions for this action.', 'danger')
            return redirect(url_for('admin.backup_management'))

        # データ削除処理を呼び出す
        if backup_util.wipe_all_data():
            flash(
                'All data has been wiped. The system will now restart to apply initial settings.', 'success')
            # Gunicornに再起動を促す

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
    """インストールされているプラグインの一覧と状態を表示します。"""
    all_plugins = plugin_manager.get_all_available_plugins()
    return render_template('admin/plugin_list.html', title='Plugin Management', plugins=all_plugins)


@admin_bp.route('/plugins/toggle', methods=['POST'])
@sysop_required
def toggle_plugin_status():
    """指定されたプラグインの有効/無効状態をデータベースに保存します。"""
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
    """config.tomlファイルをWeb UIから直接編集・保存する機能を提供します。"""
    config_path = os.path.join(
        backup_util.PROJECT_ROOT, 'setting', 'config.toml')

    if request.method == 'POST':
        new_content = request.form.get('config_content', '')

        # TOML形式として正しいか検証
        try:
            parsed_config = toml.loads(new_content)
        except toml.TomlDecodeError as e:
            flash(f"Invalid TOML format. Changes not saved: {e}", 'danger')
            return render_template('admin/config_editor.html', title=g.texts.get('config_editor', {}).get('title', 'Configuration Editor'), config_content=new_content)

        # ファイルに保存
        try:
            # バックアップを作成
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
    """オンライン中の全ユーザーに電報機能を使ってメッセージを一斉送信します。"""
    message = request.form.get('message', '').strip()

    if not message:
        flash(g.texts.get('broadcast', {}).get(
            'flash_empty', 'Message cannot be empty.'), 'warning')
        return redirect(url_for('admin.dashboard'))

    # 循環参照を避けるため、関数内でインポート
    from .. import webapp
    online_members = webapp.get_webapp_online_members()

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
    """Gunicornワーカープロセスを終了させ、Dockerによる再起動を促します。"""
    flash_message = g.texts.get('system_actions', {}).get(
        'flash_restarting', 'Server is restarting... Please reload the page to reconnect.')
    flash(flash_message, 'warning')

    # レスポンスをクライアントに送信する時間を確保するために、
    # 別のスレッドで少し待ってから終了処理を行う。
    def do_restart():
        time.sleep(2)  # 2秒待機
        logging.info("SysOp triggered server restart.")
        os._exit(0)  # Gunicornワーカーを終了させる。Dockerがコンテナを再起動する。

    import threading
    threading.Thread(target=do_restart).start()

    # flashメッセージを表示させるために、一度ダッシュボードにリダイレクトする
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/access-log')
@sysop_required
def access_log_viewer():
    """データベースに記録されたアクセスログを検索・表示します。"""
    # 検索フォームからのパラメータを取得
    search_ip = request.args.get('ip', '')
    search_user = request.args.get('user', '')
    search_event = request.args.get('event', '')
    # ソート用のパラメータを取得
    sort_by = request.args.get('sort_by', 'timestamp')  # デフォルトはtimestamp
    order = request.args.get('order', 'desc')  # デフォルトは降順

    try:
        logs = database.get_access_logs(
            limit=200,
            ip_address=search_ip,
            username=search_user,
            event_type=search_event,
            sort_by=sort_by,
            order=order
        )
    except Exception as e:
        flash(f"Error retrieving access logs: {e}", 'danger')
        logs = []

    # 検索条件をテンプレートに渡して、フォームに値を再表示する
    search_params = {
        'ip': search_ip,
        'user': search_user,
        'event': search_event
    }

    # 次のソート順を計算
    next_order = 'desc' if order == 'asc' else 'asc'

    return render_template('admin/log_viewer.html', title=g.texts.get('access_log', {}).get('title', 'Access Log Viewer'), logs=logs, search_params=search_params,
                           sort_by=sort_by, order=order, next_order=next_order)
