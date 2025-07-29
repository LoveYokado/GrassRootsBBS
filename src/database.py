# /home/yuki/python/GrassRootsBBS/src/database.py
import mysql.connector
from mysql.connector import pooling
import logging
import json

# グローバルなコネクションプール。アプリケーション起動時に初期化される。
connection_pool = None


def init_connection_pool(pool_name, pool_size, db_config):
    """アプリケーション起動時にコネクションプールを初期化する"""
    global connection_pool
    try:
        connection_pool = pooling.MySQLConnectionPool(
            pool_name=pool_name,
            pool_size=pool_size,
            **db_config
        )
        logging.info(f"データベースコネクションプール '{pool_name}' が正常に初期化されました。")
    except mysql.connector.Error as err:
        logging.critical(f"コネクションプールの初期化に失敗しました: {err}")
        raise


def get_connection():
    """プールからデータベース接続を取得する"""
    if not connection_pool:
        raise RuntimeError("コネクションプールが初期化されていません。")
    try:
        return connection_pool.get_connection()
    except mysql.connector.Error as err:
        logging.error(f"データベース接続の取得に失敗しました: {err}")
        raise


def execute_query(query, params=None, fetch=None):
    """
    クエリを実行し、結果を取得する汎用関数
    :param query: SQLクエリ文字列
    :param params: クエリにバインドするパラメータのタプル
    :param fetch: 'one', 'all', or None
    :return: 結果 or None
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        # dictionary=True で結果を辞書形式で受け取る
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params or ())

        if fetch == 'one':
            return cursor.fetchone()
        elif fetch == 'all':
            return cursor.fetchall()
        else:  # INSERT, UPDATE, DELETE の場合
            conn.commit()
            return cursor.lastrowid  # AUTO_INCREMENT の値などを返す
    except mysql.connector.Error as err:
        logging.error(f"クエリ実行エラー: {err}\nQuery: {query}\nParams: {params}")
        if conn:
            conn.rollback()
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_user_auth_info(username):
    """ユーザー名から認証情報を取得する"""
    query = "SELECT id, name, password, salt, level, lastlogin, menu_mode, email, comment, telegram_restriction, blacklist, exploration_list, read_progress FROM users WHERE name = %s"
    return execute_query(query, (username,), fetch='one')


def get_user_by_id(user_id):
    """ユーザーIDからユーザー情報を取得する"""
    query = "SELECT id, name, password, salt, level, lastlogin, menu_mode, email, comment, telegram_restriction, blacklist, exploration_list, read_progress FROM users WHERE id = %s"
    return execute_query(query, (user_id,), fetch='one')


def get_user_id_from_user_name(username):
    """ユーザ名からユーザIDを取得する"""
    query = "SELECT id FROM users WHERE name = %s"
    result = execute_query(query, (username,), fetch='one')
    return result['id'] if result else None


def get_user_name_from_user_id(user_id):
    """ユーザIDからユーザ名を取得する"""
    query = "SELECT name FROM users WHERE id = %s"
    result = execute_query(query, (user_id,), fetch='one')
    return result['name'] if result else "(不明)"


def get_user_names_from_user_ids(user_ids):
    """複数のユーザーIDからユーザー名の辞書を取得する"""
    if not user_ids:
        return {}
    valid_user_ids = [int(uid)
                      for uid in user_ids if str(uid).strip().isdigit()]
    if not valid_user_ids:
        return {}

    placeholders = ','.join(['%s'] * len(valid_user_ids))
    query = f"SELECT id, name FROM users WHERE id IN ({placeholders})"
    results = execute_query(query, tuple(valid_user_ids), fetch='all')
    return {row['id']: row['name'] for row in results} if results else {}


def update_record(table, set_data, where_data):
    """
    汎用的なレコード更新関数
    :param table: テーブル名
    :param set_data: 更新するカラムと値の辞書 (e.g., {'col1': 'val1', 'col2': 123})
    :param where_data: WHERE句の条件となる辞書 (e.g., {'id': 1})
    """
    if not set_data or not where_data:
        logging.error("update_record: set_data or where_data is empty.")
        return

    set_clause = ', '.join([f"`{k}` = %s" for k in set_data.keys()])
    where_clause = ' AND '.join([f"`{k}` = %s" for k in where_data.keys()])

    query = f"UPDATE `{table}` SET {set_clause} WHERE {where_clause}"

    params = tuple(set_data.values()) + tuple(where_data.values())
    execute_query(query, params)


def read_server_pref():
    """サーバー設定を読み込む"""
    query = "SELECT bbs, chat, mail, telegram, userpref, who, default_exploration_list, hamlet, login_message FROM server_pref LIMIT 1"
    result = execute_query(query, fetch='one')
    return list(result.values()) if result else []


def get_board_by_shortcut_id(shortcut_id):
    """指定されたショートカットIDの掲示板情報をDBから取得"""
    query = "SELECT * FROM boards WHERE shortcut_id = %s"
    return execute_query(query, (shortcut_id,), fetch='one')


def get_all_boards():
    query = "SELECT id, shortcut_id, operators, default_permission, board_type FROM boards"
    return execute_query(query, fetch='all')


def get_next_article_number(board_id_pk):
    query = "SELECT COALESCE(MAX(article_number), 0) + 1 AS next_num FROM articles WHERE board_id = %s"
    result = execute_query(query, (board_id_pk,), fetch='one')
    return result['next_num'] if result else 1


def save_telegram(sender_name, recipient_name, message, current_timestamp):
    """電報をデータベースに保存"""
    query = "INSERT INTO telegram(sender_name, recipient_name, message, timestamp) VALUES(%s, %s, %s, %s)"
    execute_query(
        query, (sender_name, recipient_name, message, current_timestamp))


def load_and_delete_telegrams(recipient_name):
    """指定された受信者の電報を取得し、取得した電報を削除する。"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Select
        query_select = "SELECT id, sender_name, recipient_name, message, timestamp FROM telegram WHERE recipient_name = %s ORDER BY timestamp ASC"
        cursor.execute(query_select, (recipient_name,))
        results = cursor.fetchall()

        if not results:
            return None

        # 2. Delete
        telegram_ids = [row['id'] for row in results]
        placeholders = ','.join(['%s'] * len(telegram_ids))
        query_delete = f"DELETE FROM telegram WHERE id IN ({placeholders})"
        cursor.execute(query_delete, tuple(telegram_ids))

        conn.commit()
        return results

    except mysql.connector.Error as err:
        logging.error(f"電報の読み込み/削除中にエラー: {err}")
        if conn:
            conn.rollback()
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def update_board_operators(board_id_pk, operator_user_ids_json_string):
    """掲示板のオペレーターリストを更新する"""
    query = "UPDATE boards SET operators = %s WHERE id = %s"
    params = (
        operator_user_ids_json_string if operator_user_ids_json_string is not None else '[]', board_id_pk)
    execute_query(query, params)
    logging.info(
        f"掲示板ID {board_id_pk} のオペレーターリストを更新しました: {operator_user_ids_json_string}")
    return True  # Assuming success if no exception


def update_board_kanban(board_id_pk, new_kanban_body):
    """掲示板の看板を更新する"""
    query = "UPDATE boards SET kanban_body = %s WHERE id = %s"
    execute_query(query, (new_kanban_body, board_id_pk))
    logging.info(f"掲示板ID {board_id_pk} の看板本文を更新しました")
    return True  # Assuming success if no exception


def get_board_permissions(board_id_pk):
    """指定された掲示板IDのパーミッションリストを全て取得する"""
    query = "SELECT user_id, access_level FROM board_user_permissions WHERE board_id = %s"
    return execute_query(query, (board_id_pk,), fetch='all')


def delete_board_permissions_by_board_id(board_id_pk):
    """指定された掲示板IDのパーミッションを全て削除する"""
    query = "DELETE FROM board_user_permissions WHERE board_id = %s"
    return execute_query(query, (board_id_pk,)) is not None


def add_board_permission(board_id_pk, user_id_pk_str, access_level):
    """board_user_permissions テーブルに新しい権限エントリを追加する"""
    query = "INSERT INTO board_user_permissions (board_id, user_id, access_level) VALUES (%s, %s, %s)"
    return execute_query(query, (board_id_pk, user_id_pk_str, access_level)) is not None


def get_user_permission_for_board(board_id_pk, user_id_pk_str):
    """指定された掲示板とユーザのアクセスレベルを取得"""
    query = "SELECT access_level FROM board_user_permissions WHERE board_id = %s AND user_id = %s"
    result = execute_query(query, (board_id_pk, user_id_pk_str), fetch='one')
    return result['access_level'] if result else None


def get_total_unread_mail_count(user_id_pk):
    """指定されたユーザの未読かつ未削除の受信メール総数を取得"""
    query = "SELECT COUNT(*) AS count FROM mails WHERE recipient_id = %s AND is_read = 0 AND recipient_deleted = 0"
    result = execute_query(query, (user_id_pk,), fetch='one')
    return result['count'] if result else 0


def get_total_mail_count(user_id_pk):
    """指定されたユーザの未削除の受信メール総数を取得"""
    query = "SELECT COUNT(*) AS count FROM mails WHERE recipient_id = %s AND recipient_deleted = 0"
    result = execute_query(query, (user_id_pk,), fetch='one')
    return result['count'] if result else 0


def mark_mail_as_read(mail_id, recipient_user_id_pk):
    """指定されたメールを指定された受信者に対して既読にする"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        query = "UPDATE mails SET is_read = 1 WHERE id = %s AND recipient_id = %s"
        cursor.execute(query, (mail_id, recipient_user_id_pk))
        updated_rows = cursor.rowcount
        conn.commit()

        if updated_rows > 0:
            logging.info(
                f"メールID {mail_id} をユーザID {recipient_user_id_pk} に対して既読にマークしました ({updated_rows}行更新)。")
            return True
        else:
            logging.debug(
                f"メールID {mail_id} (ユーザID: {recipient_user_id_pk}) は既に既読、または存在しません。既読化処理はスキップされました。")
            return False
    except mysql.connector.Error as err:
        logging.error(
            f"メール既読化中にDBエラー (MailID: {mail_id}, UserID: {recipient_user_id_pk}): {err}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_oldest_unread_mail(recipient_user_id_pk):
    """指定されたユーザの一番古い未読、かつ未削除の受信メールを1件取得"""
    query = """
        SELECT id, sender_id, subject, body, is_read, sent_at, recipient_deleted, sender_ip_address
        FROM mails
        WHERE recipient_id = %s AND is_read = 0 AND recipient_deleted = 0
        ORDER BY sent_at ASC
        LIMIT 1
    """
    return execute_query(query, (recipient_user_id_pk,), fetch='one')


def get_new_articles_for_board(board_id_pk, last_login_timestamp):
    """
    指定された掲示板の、指定時刻以降の未削除記事を取得する。
    last_login_timestamp が 0 または None の場合は、全ての未削除記事を取得する。
    スレッド形式の掲示板では、親記事のみを取得する。
    """
    params = [board_id_pk]
    query = """
    SELECT a.id, a.article_number, a.user_id, a.parent_article_id, a.title, a.body, a.created_at
    FROM articles AS a
    WHERE a.board_id = %s AND a.is_deleted = 0 AND a.parent_article_id IS NULL
    """
    if last_login_timestamp and last_login_timestamp > 0:
        query += " AND a.created_at > %s"
        params.append(last_login_timestamp)
    query += " ORDER BY a.created_at ASC"
    return execute_query(query, tuple(params), fetch='all')


def update_board_levels(board_id_pk, read_level, write_level):
    """掲示板の閲覧・書き込みレベルを更新する"""
    query = "UPDATE boards SET read_level = %s, write_level = %s WHERE id = %s"
    try:
        execute_query(query, (read_level, write_level, board_id_pk))
        logging.info(
            f"掲示板ID {board_id_pk} のレベルを R:{read_level}, W:{write_level} に更新しました。")
        return True
    except Exception as e:
        logging.error(f"掲示板レベル更新中にDBエラー (BoardID: {board_id_pk}): {e}")
        return False


def get_thread_root_articles_with_reply_count(board_id_pk, include_deleted=False):
    """
    指定された掲示板の親記事（スレッドルート）と、それぞれの返信数を取得する。
    """
    deleted_cond = "" if include_deleted else "AND is_deleted = 0"

    query = f"""
        SELECT
            p.id, p.article_number, p.user_id, p.title, p.body, p.created_at, p.is_deleted, p.ip_address,
            (SELECT COUNT(*) FROM articles AS r WHERE r.parent_article_id = p.id {deleted_cond}) AS reply_count
        FROM articles AS p
        WHERE p.board_id = %s AND p.parent_article_id IS NULL {deleted_cond}
        ORDER BY p.created_at ASC, p.article_number ASC
    """
    return execute_query(query, (board_id_pk,), fetch='all')


def get_replies_for_article(parent_article_id, include_deleted=False):
    """指定された親記事への返信をすべて取得する"""
    where_clauses = ["parent_article_id = %s"]
    params = [parent_article_id]
    if not include_deleted:
        where_clauses.append("is_deleted = 0")

    query = f"SELECT id, article_number, user_id, title, body, created_at, is_deleted, ip_address FROM articles WHERE {' AND '.join(where_clauses)} ORDER BY created_at ASC, article_number ASC"
    return execute_query(query, tuple(params), fetch='all')


def get_sysop_user_id():
    """シスオペ(level=5)のユーザーIDを取得する。"""
    query = "SELECT id FROM users WHERE level = 5 ORDER BY id ASC LIMIT 1"
    result = execute_query(query, fetch='one')
    if result:
        return result['id']
    logging.warning("シスオペ(level=5)が見つかりませんでした。")
    return None


def send_system_mail(recipient_id, subject, body):
    """システムから指定されたユーザーへメールを送信する。"""
    import time
    sender_id = get_sysop_user_id()
    if sender_id is None:
        logging.error("システムメールの送信に失敗しました。送信者(シスオペ)が見つかりません。")
        return False

    sent_at = int(time.time())
    query = "INSERT INTO mails (sender_id, recipient_id, subject, body, sent_at, sender_ip_address) VALUES (%s, %s, %s, %s, %s, %s)"
    params = (sender_id, recipient_id, subject, body, sent_at, None)

    if execute_query(query, params) is not None:
        logging.info(
            f"システムメールを送信しました (To: UserID {recipient_id}, Subject: {subject})")
        return True
    else:
        logging.error(
            f"システムメールのDB保存に失敗しました (To: UserID {recipient_id})")
        return False


def get_user_exploration_list(user_id):
    """ユーザの探索リストを取得"""
    query = "SELECT exploration_list FROM users WHERE id = %s"
    result = execute_query(query, (user_id,), fetch='one')
    return result['exploration_list'] if result and result['exploration_list'] else ""


def update_user_read_progress(user_id, read_progress_dict):
    """ユーザの掲示板読み込み進捗を更新"""
    read_progress_json = json.dumps(read_progress_dict)
    update_record(
        'users', {'read_progress': read_progress_json}, {'id': user_id})


def get_user_read_progress(user_id):
    """ユーザの掲示板読み込み進捗を取得"""
    query = "SELECT read_progress FROM users WHERE id = %s"
    result = execute_query(query, (user_id,), fetch='one')
    if result and result.get('read_progress'):
        try:
            return json.loads(result['read_progress'])
        except (json.JSONDecodeError, TypeError):
            logging.warning(
                f"ユーザーID {user_id} の read_progress のJSONデコードに失敗しました。")
            return {}
    return {}


def update_board_last_posted_at(board_id_pk, timestamp=None):
    """boardsテーブルのlast_posted_atを更新"""
    import time
    if timestamp is None:
        timestamp = int(time.time())
    update_record('boards', {'last_posted_at': timestamp}, {'id': board_id_pk})


def toggle_mail_delete_status_generic(mail_id, user_id, mode_param):
    """メールの削除フラグをトグルする汎用関数"""
    # This function is complex due to needing a SELECT then UPDATE.
    # It's better to handle this with a transaction in the function itself
    # rather than relying on the generic execute_query for both steps.
    # The implementation from the previous turn is a good example.
    # For now, this is a placeholder as it requires a more complex transaction logic
    # that is not yet implemented in the new `execute_query`.
    # A proper implementation would require passing a connection object.
    logging.warning(
        "toggle_mail_delete_status_generic is not fully implemented for MariaDB yet.")
    return False, 0


def get_memberlist(search_word=None):
    """メンバーリストを取得する。"""
    query = "SELECT name, comment FROM users"
    params = []
    if search_word:
        query += " WHERE name LIKE %s OR comment LIKE %s"
        params = [f"%{search_word}%", f"%{search_word}%"]
    return execute_query(query, tuple(params), fetch='all')


def register_user(username, hashed_password, salt, comment, level=0, menu_mode='1', telegram_restriction=0, email=''):
    """新しいユーザーをデータベースに登録する"""
    query = """
        INSERT INTO users (
            name, password, salt, registdate, level, lastlogin, lastlogout,
            comment, email, menu_mode, telegram_restriction, blacklist,
            exploration_list, read_progress
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    import time
    params = (
        username, hashed_password, salt, int(time.time()), level, 0, 0,
        comment, email, menu_mode, telegram_restriction, '', '{}'
    )
    return execute_query(query, params) is not None


def delete_user(user_id):
    """ユーザーを削除する"""
    query = "DELETE FROM users WHERE id = %s"
    return execute_query(query, (user_id,)) is not None


def create_board_entry(shortcut_id, name, description, operators, default_permission, kanban_body, status, read_level=1, write_level=1, board_type="simple"):
    """新しい掲示板エントリをboardsテーブルに挿入"""
    query = """
    INSERT INTO boards(shortcut_id, name, description, operators, default_permission, kanban_body, status, last_posted_at, read_level, write_level, board_type)
    VALUES(%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
    """
    params = (shortcut_id, name, description, operators,
              default_permission, kanban_body, status, read_level, write_level, board_type)
    return execute_query(query, params) is not None


def delete_board_entry(shortcut_id):
    """掲示板エントリを削除"""
    query = "DELETE FROM boards WHERE shortcut_id = %s"
    return execute_query(query, (shortcut_id,)) is not None


def insert_article(board_id_pk, article_number, user_identifier, title, body, timestamp, ip_address=None, parent_article_id=None):
    """記事を挿入し、IDを返す"""
    query = """
        INSERT INTO articles (board_id, article_number, user_id, parent_article_id, title, body, created_at, ip_address)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (board_id_pk, article_number, user_identifier,
              parent_article_id, title, body, timestamp, ip_address)
    return execute_query(query, params)


def get_articles_by_board_id(board_id_pk, order_by="created_at ASC, article_number ASC", include_deleted=False):
    """
    指定された掲示板IDの記事リストを取得する。
    """
    where_clauses = ["board_id = %s"]
    params = [board_id_pk]

    if not include_deleted:
        where_clauses.append("is_deleted = 0")

    query = f"SELECT id, article_number, user_id, parent_article_id, title, body, created_at, is_deleted, ip_address FROM articles WHERE {' AND '.join(where_clauses)} ORDER BY {order_by}"
    return execute_query(query, tuple(params), fetch='all')
