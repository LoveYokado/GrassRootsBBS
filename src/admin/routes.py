from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from ..decorators import sysop_required
import json
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


@admin_bp.route('/boards')
@sysop_required
def board_list():
    """掲示板一覧ページ"""
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
    """新規掲示板作成ページ"""
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

        # バリデーション
        if not shortcut_id or not name:
            flash('Shortcut ID and Board Name are required.', 'danger')
            return render_template('admin/new_board.html', title='Add New Board')

        if database.get_board_by_shortcut_id(shortcut_id):
            flash(f"Shortcut ID '{shortcut_id}' already exists.", 'danger')
            return render_template('admin/new_board.html', title='Add New Board')

        # シスオペをオペレーターとして自動設定
        sysop_user_id = session.get('user_id')
        operators_json = json.dumps([sysop_user_id]) if sysop_user_id else '[]'

        if database.create_board_entry(shortcut_id, name, description, operators_json, default_permission, "", "active", read_level, write_level, board_type, allow_attachments, allowed_extensions, max_attachment_size_mb):
            flash(f"Board '{name}' has been created successfully.", 'success')
            return redirect(url_for('admin.board_list'))
        else:
            flash('Failed to create board.', 'danger')

    return render_template('admin/new_board.html', title='Add New Board')


@admin_bp.route('/boards/edit/<int:board_id>', methods=['GET', 'POST'])
@sysop_required
def edit_board(board_id):
    """掲示板編集ページ"""
    board = database.get_board_by_id(board_id)
    if not board:
        flash(f"Board with ID {board_id} not found.", 'danger')
        return redirect(url_for('admin.board_list'))

    if request.method == 'POST':
        # フォームからデータを取得
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
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

        # バリデーション
        if not name:
            flash('Board Name is required.', 'danger')
            return render_template('admin/edit_board.html', title='Edit Board', board=board)

        updates = {
            'name': name, 'description': description, 'board_type': board_type,
            'default_permission': default_permission, 'read_level': read_level, 'write_level': write_level,
            'allow_attachments': allow_attachments, 'allowed_extensions': allowed_extensions,
            'max_attachment_size_mb': max_attachment_size_mb
        }

        if database.update_record('boards', updates, {'id': board_id}):
            flash(f"Board '{name}' has been updated successfully.", 'success')
        else:
            flash(f"Failed to update board '{name}'.", 'danger')

        return redirect(url_for('admin.board_list'))

    return render_template('admin/edit_board.html', title='Edit Board', board=board)


@admin_bp.route('/boards/delete/<int:board_id>', methods=['POST'])
@sysop_required
def delete_board(board_id):
    """掲示板を削除する"""
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
    """記事検索ページ"""
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
    """記事を削除する（論理削除）"""
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
    """記事の一括操作（削除/復元）"""
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
