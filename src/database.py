# /home/yuki/python/GrassRootsBBS/src/database.py
import mysql.connector
from mysql.connector import pooling
import logging
import json

import time  # For timestamp in some functions

# グローバルインスタンスの宣言 (後で初期化される)
db_manager = None
users = None
boards = None
articles = None
mails = None
telegrams = None
server_prefs = None
plugins = None
access_logs = None
board_permissions = None
push_subscriptions = None
passkeys = None
initializer = None


class DBManager:
    """
    データベース接続とクエリ実行を管理するクラス。
    コネクションプールを保持し、他のマネージャークラスに共有される。
    """
    _pool = None

    def __init__(self):
        # コンストラクタが複数回呼ばれた場合にプールを再初期化しないようにする
        # ただし、明示的にinit_poolを呼ぶことで再初期化は可能
        if DBManager._pool is not None:
            logging.warning(
                "DBManager already initialized. Skipping re-initialization.")

    def init_pool(self, pool_name, pool_size, db_config):
        """アプリケーション起動時にコネクションプールを初期化する"""
        if DBManager._pool is not None:
            logging.warning(
                "Connection pool already initialized. Skipping re-initialization.")
            return

        try:
            DBManager._pool = pooling.MySQLConnectionPool(
                pool_name=pool_name,
                pool_size=pool_size,
                **db_config
            )
            logging.info(f"データベースコネクションプール '{pool_name}' が正常に初期化されました。")
        except mysql.connector.Error as err:
            logging.critical(f"コネクションプールの初期化に失敗しました: {err}")
            raise

    def get_connection(self):
        """プールからデータベース接続を取得する"""
        if DBManager._pool is None:
            raise RuntimeError("コネクションプールが初期化されていません。")
        try:
            return DBManager._pool.get_connection()
        except mysql.connector.Error as err:
            logging.error(f"データベース接続の取得に失敗しました: {err}")
            raise

    def execute_query(self, query, params=None, fetch=None):
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
            conn = self.get_connection()
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

    def update_record(self, table, set_data, where_data):
        """
        汎用的なレコード更新関数
        :param table: テーブル名
        :param set_data: 更新するカラムと値の辞書 (e.g., {'col1': 'val1', 'col2': 123})
        :param where_data: WHERE句の条件となる辞書 (e.g., {'id': 1})
        """
        if not set_data or not where_data:
            logging.error("update_record: set_data or where_data is empty.")
            return False

        set_clause = ', '.join([f"`{k}` = %s" for k in set_data.keys()])
        where_clause = ' AND '.join([f"`{k}` = %s" for k in where_data.keys()])

        query = f"UPDATE `{table}` SET {set_clause} WHERE {where_clause}"

        params = tuple(set_data.values()) + tuple(where_data.values())
        return self.execute_query(query, params) is not None


class UserManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def get_auth_info(self, username):
        query = "SELECT id, name, password, salt, level, lastlogin, menu_mode, email, comment, telegram_restriction, blacklist, exploration_list, read_progress FROM users WHERE name = %s"
        return self._db.execute_query(query, (username,), fetch='one')

    def get_by_id(self, user_id):
        query = "SELECT id, name, password, salt, level, lastlogin, menu_mode, email, comment, telegram_restriction, blacklist, exploration_list, read_progress FROM users WHERE id = %s"
        return self._db.execute_query(query, (user_id,), fetch='one')

    def get_id_from_name(self, username):
        query = "SELECT id FROM users WHERE name = %s"
        result = self._db.execute_query(query, (username,), fetch='one')
        return result['id'] if result else None

    def get_name_from_id(self, user_id):
        query = "SELECT name FROM users WHERE id = %s"
        result = self._db.execute_query(query, (user_id,), fetch='one')
        return result['name'] if result else "(不明)"

    def get_names_from_ids(self, user_ids):
        if not user_ids:
            return {}
        valid_user_ids = [int(uid)
                          for uid in user_ids if str(uid).strip().isdigit()]
        if not valid_user_ids:
            return {}

        placeholders = ','.join(['%s'] * len(valid_user_ids))
        query = f"SELECT id, name FROM users WHERE id IN ({placeholders})"
        results = self._db.execute_query(
            query, tuple(valid_user_ids), fetch='all')
        return {row['id']: row['name'] for row in results} if results else {}

    def get_total_count(self):
        query = "SELECT COUNT(*) as count FROM users"
        result = self._db.execute_query(query, fetch='one')
        return result['count'] if result else 0

    def get_daily_registrations(self, days=7):
        query = """
            SELECT
                DATE(FROM_UNIXTIME(registdate)) as registration_date,
                COUNT(*) as count
            FROM users
            WHERE registdate >= UNIX_TIMESTAMP(CURDATE() - INTERVAL %s DAY)
            GROUP BY registration_date
            ORDER BY registration_date ASC
        """
        return self._db.execute_query(query, (days - 1,), fetch='all')

    def register(self, username, hashed_password, salt, comment, level=0, menu_mode='2', telegram_restriction=0, email=''):
        query = """
            INSERT INTO users (
                name, password, salt, registdate, level, lastlogin, lastlogout,
                comment, email, menu_mode, telegram_restriction, blacklist,
                exploration_list, read_progress
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        username_upper = username.upper()
        params = (
            username_upper, hashed_password, salt, int(
                time.time()), level, 0, 0,
            comment, email, menu_mode, telegram_restriction, '', '', '{}'
        )
        return self._db.execute_query(query, params) is not None

    def delete(self, user_id):
        query = "DELETE FROM users WHERE id = %s"
        return self._db.execute_query(query, (user_id,)) is not None

    def get_exploration_list(self, user_id):
        query = "SELECT exploration_list FROM users WHERE id = %s"
        result = self._db.execute_query(query, (user_id,), fetch='one')
        return result['exploration_list'] if result and result['exploration_list'] else ""

    def set_exploration_list(self, user_id, exploration_list_str):
        try:
            self._db.update_record(
                'users', {'exploration_list': exploration_list_str}, {'id': user_id})
            logging.info(f"ユーザID {user_id} の探索リストを更新しました。")
            return True
        except Exception as e:
            logging.error(
                f"探索リスト更新中にDBエラー (UserID: {user_id}, List: {exploration_list_str[:50]}...): {e}")
            return False

    def update_read_progress(self, user_id, read_progress_dict):
        read_progress_json = json.dumps(read_progress_dict)
        self._db.update_record(
            'users', {'read_progress': read_progress_json}, {'id': user_id})

    def get_read_progress(self, user_id):
        query = "SELECT read_progress FROM users WHERE id = %s"
        result = self._db.execute_query(query, (user_id,), fetch='one')
        if result and result.get('read_progress'):
            try:
                return json.loads(result['read_progress'])
            except (json.JSONDecodeError, TypeError):
                logging.warning(
                    f"ユーザーID {user_id} の read_progress のJSONデコードに失敗しました。")
                return {}
        return {}

    def get_memberlist(self, search_word=None):
        query = "SELECT name, comment FROM users"
        params = []
        if search_word:
            query += " WHERE name LIKE %s OR comment LIKE %s"
            params = [f"%{search_word}%", f"%{search_word}%"]
        return self._db.execute_query(query, tuple(params), fetch='all')

    def get_all(self, sort_by='id', order='asc', search_term=None):
        allowed_columns = ['id', 'name', 'level',
                           'email', 'registdate', 'lastlogin']
        if sort_by not in allowed_columns:
            sort_by = 'id'

        if order.lower() not in ['asc', 'desc']:
            order = 'asc'

        params = []
        where_clauses = []

        if search_term:
            where_clauses.append("(name LIKE %s OR email LIKE %s)")
            search_pattern = f"%{search_term}%"
            params.extend([search_pattern, search_pattern])

        query = "SELECT id, name, level, registdate, lastlogin, comment, email FROM users"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += f" ORDER BY {sort_by} {order}"
        return self._db.execute_query(query, tuple(params), fetch='all')

    def get_sysop_user_id(self):
        query = "SELECT id FROM users WHERE level = 5 ORDER BY id ASC LIMIT 1"
        result = self._db.execute_query(query, fetch='one')
        if result:
            return result['id']
        logging.warning("シスオペ(level=5)が見つかりませんでした。")
        return None


class BoardManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def get_by_shortcut_id(self, shortcut_id):
        query = "SELECT * FROM boards WHERE shortcut_id = %s"
        return self._db.execute_query(query, (shortcut_id,), fetch='one')

    def get_by_id(self, board_id_pk):
        query = "SELECT * FROM boards WHERE id = %s"
        return self._db.execute_query(query, (board_id_pk,), fetch='one')

    def get_all(self):
        query = "SELECT id, shortcut_id, operators, default_permission, board_type FROM boards"
        return self._db.execute_query(query, fetch='all')

    def get_total_count(self):
        query = "SELECT COUNT(*) as count FROM boards"
        result = self._db.execute_query(query, fetch='one')
        return result['count'] if result else 0

    def create_entry(self, shortcut_id, name, description, operators, default_permission, kanban_body, status, read_level=1, write_level=1, board_type="simple", allow_attachments=0, allowed_extensions=None, max_attachment_size_mb=None, max_threads=0, max_replies=0):
        query = """
        INSERT INTO boards (shortcut_id, name, description, operators, default_permission, kanban_body, status, last_posted_at, read_level, write_level, board_type, allow_attachments, allowed_extensions, max_attachment_size_mb, max_threads, max_replies)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (shortcut_id, name, description, operators, default_permission,
                  kanban_body, status, read_level, write_level, board_type, allow_attachments, allowed_extensions, max_attachment_size_mb, max_threads, max_replies)
        return self._db.execute_query(query, params) is not None

    def delete_entry(self, shortcut_id):
        query = "DELETE FROM boards WHERE shortcut_id = %s"
        return self._db.execute_query(query, (shortcut_id,)) is not None

    def delete_and_related_data(self, board_id_pk):
        conn = self._db.get_connection()
        cursor = None
        try:
            cursor = conn.cursor()

            cursor.execute(
                "DELETE FROM articles WHERE board_id = %s", (board_id_pk,))
            logging.info(
                f"{cursor.rowcount} articles deleted for board_id {board_id_pk}.")

            cursor.execute(
                "DELETE FROM board_user_permissions WHERE board_id = %s", (board_id_pk,))
            logging.info(
                f"{cursor.rowcount} permissions deleted for board_id {board_id_pk}.")

            cursor.execute("DELETE FROM boards WHERE id = %s", (board_id_pk,))
            logging.info(
                f"{cursor.rowcount} board entry deleted for board_id {board_id_pk}.")

            conn.commit()
            logging.info(
                f"Board ID {board_id_pk} and all related data have been successfully deleted.")
            return True
        except mysql.connector.Error as err:
            logging.error(
                f"掲示板削除中にDBエラー (BoardID: {board_id_pk}): {err}", exc_info=True)
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def update_operators(self, board_id_pk, operator_user_ids_json_string):
        query = "UPDATE boards SET operators = %s WHERE id = %s"
        params = (
            operator_user_ids_json_string if operator_user_ids_json_string is not None else '[]', board_id_pk)
        self._db.execute_query(query, params)
        logging.info(
            f"掲示板ID {board_id_pk} のオペレーターリストを更新しました: {operator_user_ids_json_string}")
        return True

    def update_kanban(self, board_id_pk, new_kanban_body):
        query = "UPDATE boards SET kanban_body = %s WHERE id = %s"
        self._db.execute_query(query, (new_kanban_body, board_id_pk))
        logging.info(f"掲示板ID {board_id_pk} の看板本文を更新しました")
        return True

    def update_levels(self, board_id_pk, read_level, write_level):
        query = "UPDATE boards SET read_level = %s, write_level = %s WHERE id = %s"
        try:
            self._db.execute_query(
                query, (read_level, write_level, board_id_pk))
            logging.info(
                f"掲示板ID {board_id_pk} のレベルを R:{read_level}, W:{write_level} に更新しました。")
            return True
        except Exception as e:
            logging.error(f"掲示板レベル更新中にDBエラー (BoardID: {board_id_pk}): {e}")
            return False

    def update_last_posted_at(self, board_id_pk, timestamp=None):
        if timestamp is None:
            timestamp = int(time.time())
        self._db.update_record(
            'boards', {'last_posted_at': timestamp}, {'id': board_id_pk})

    def get_all_for_sysop_list(self, sort_by='shortcut_id', order='asc', search_term=None):
        allowed_columns = [
            'shortcut_id', 'name', 'board_type', 'status', 'last_posted_at',
            'read_level', 'write_level', 'default_permission', 'allow_attachments', 'post_count'
        ]
        if sort_by not in allowed_columns:
            sort_by = 'shortcut_id'

        if order.lower() not in ['asc', 'desc']:
            order = 'asc'

        params = []
        where_clauses = []

        if search_term:
            where_clauses.append("(b.shortcut_id LIKE %s OR b.name LIKE %s)")
            search_pattern = f"%{search_term}%"
            params.extend([search_pattern, search_pattern])

        query = """
            SELECT
                b.id, b.shortcut_id, b.name, b.operators, b.default_permission, b.status,
                b.last_posted_at, b.read_level, b.write_level, b.board_type,
                b.allow_attachments, b.allowed_extensions, b.max_attachment_size_mb,
                (
                    SELECT COUNT(*)
                    FROM articles a
                    WHERE a.board_id = b.id
                    AND (b.board_type != 'thread' OR a.parent_article_id IS NULL)
                ) AS post_count
            FROM boards b
        """
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += f" ORDER BY {sort_by} {order}"
        return self._db.execute_query(query, tuple(params), fetch='all')


class ArticleManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def get_by_board_id(self, board_id_pk, order_by="created_at ASC, article_number ASC", include_deleted=False):
        where_clauses = ["board_id = %s"]
        params = [board_id_pk]

        if not include_deleted:
            where_clauses.append("is_deleted = 0")

        query = f"SELECT id, article_number, user_id, parent_article_id, title, body, created_at, is_deleted, ip_address FROM articles WHERE {' AND '.join(where_clauses)} ORDER BY {order_by}"
        return self._db.execute_query(query, tuple(params), fetch='all')

    def get_by_board_and_number(self, board_id, article_number, include_deleted=False):
        where_clauses = ["board_id = %s", "article_number = %s"]
        params = [board_id, article_number]

        if not include_deleted:
            where_clauses.append("is_deleted = 0")

        query = f"SELECT id, article_number, user_id, parent_article_id, title, body, created_at, is_deleted, ip_address, attachment_filename, attachment_originalname, attachment_size FROM articles WHERE {' AND '.join(where_clauses)}"
        return self._db.execute_query(query, tuple(params), fetch='one')

    def get_new_for_board(self, board_id_pk, last_login_timestamp):
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
        return self._db.execute_query(query, tuple(params), fetch='all')

    def get_next_number(self, board_id_pk):
        query = "SELECT COALESCE(MAX(article_number), 0) + 1 AS next_num FROM articles WHERE board_id = %s"
        result = self._db.execute_query(query, (board_id_pk,), fetch='one')
        return result['next_num'] if result else 1

    def insert(self, board_id_pk, article_number, user_identifier, title, body, timestamp, ip_address=None, parent_article_id=None, attachment_filename=None, attachment_originalname=None, attachment_size=None):
        query = """
            INSERT INTO articles (board_id, article_number, user_id, parent_article_id, title, body, created_at, ip_address, attachment_filename, attachment_originalname, attachment_size)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (board_id_pk, article_number, user_identifier,
                  parent_article_id, title, body, timestamp, ip_address,
                  attachment_filename, attachment_originalname, attachment_size)
        return self._db.execute_query(query, params)

    def get_by_id(self, article_id):
        query = "SELECT * FROM articles WHERE id = %s"
        return self._db.execute_query(query, (article_id,), fetch='one')

    def get_by_attachment_filename(self, filename):
        query = "SELECT * FROM articles WHERE attachment_filename = %s"
        return self._db.execute_query(query, (filename,), fetch='one')

    def toggle_deleted_status(self, article_id):
        conn = self._db.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)

            query_select = "SELECT is_deleted FROM articles WHERE id = %s"
            cursor.execute(query_select, (article_id,))
            result = cursor.fetchone()

            if result is None:
                logging.warning(
                    f"記事削除フラグのトグル失敗: 記事ID '{article_id}' が見つかりません。")
                return False

            current_status = result['is_deleted']
            new_status = 1 - current_status

            query_update = "UPDATE articles SET is_deleted = %s WHERE id = %s"
            cursor.execute(query_update, (new_status, article_id))
            conn.commit()

            logging.info(
                f"記事ID {article_id} の is_deleted を {new_status} に変更しました。")
            return True

        except mysql.connector.Error as err:
            logging.error(
                f"記事削除フラグのトグル中にDBエラー (記事ID: {article_id}): {err}")
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def bulk_update_deleted_status(self, article_ids, new_status):
        if not article_ids or new_status not in [0, 1]:
            return 0

        placeholders = ','.join(['%s'] * len(article_ids))
        query = f"UPDATE articles SET is_deleted = %s WHERE id IN ({placeholders})"

        params = [new_status] + article_ids

        conn = self._db.get_connection()
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            updated_rows = cursor.rowcount
            conn.commit()
            logging.info(f"{updated_rows}件の記事の削除ステータスを {new_status} に更新しました。")
            return updated_rows
        except mysql.connector.Error as err:
            logging.error(f"記事の一括削除ステータス更新中にDBエラー: {err}")
            if conn:
                conn.rollback()
            return 0
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_thread_root_articles_with_reply_count(self, board_id_pk, include_deleted=False):
        deleted_cond = "" if include_deleted else "AND is_deleted = 0"

        query = f"""
            SELECT
                p.id, p.article_number, p.user_id, p.title, p.body, p.created_at, p.is_deleted, p.ip_address,
                (SELECT COUNT(*) FROM articles AS r WHERE r.parent_article_id = p.id {deleted_cond}) AS reply_count
            FROM articles AS p
            WHERE p.board_id = %s AND p.parent_article_id IS NULL {deleted_cond}
            ORDER BY p.created_at ASC, p.article_number ASC
        """
        return self._db.execute_query(query, (board_id_pk,), fetch='all')

    def get_replies_for_article(self, parent_article_id, include_deleted=False):
        where_clauses = ["parent_article_id = %s"]
        params = [parent_article_id]
        if not include_deleted:
            where_clauses.append("is_deleted = 0")

        query = f"SELECT id, article_number, user_id, title, body, created_at, is_deleted, ip_address FROM articles WHERE {' AND '.join(where_clauses)} ORDER BY created_at ASC, article_number ASC"
        return self._db.execute_query(query, tuple(params), fetch='all')

    def get_daily_posts(self, days=7):
        query = """
            SELECT DATE(FROM_UNIXTIME(created_at)) as post_date, COUNT(*) as count
            FROM articles WHERE created_at >= UNIX_TIMESTAMP(CURDATE() - INTERVAL %s DAY)
            GROUP BY post_date ORDER BY post_date ASC
        """
        return self._db.execute_query(query, (days - 1,), fetch='all')

    def search_all(self, keyword=None, author_id=None, author_name_guest=None, sort_by='created_at', order='desc'):
        allowed_columns = ['created_at', 'board_name', 'title']
        if sort_by not in allowed_columns:
            sort_by = 'created_at'
        if order.lower() not in ['asc', 'desc']:
            order = 'desc'

        params = []
        where_clauses = []

        if keyword:
            where_clauses.append("(a.title LIKE %s OR a.body LIKE %s)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        if author_id is not None:
            where_clauses.append("a.user_id = %s")
            params.append(str(author_id))
        elif author_name_guest:
            where_clauses.append("a.user_id = %s")
            params.append(author_name_guest)

        query = """
            SELECT
                a.id, a.board_id, a.article_number, a.user_id, a.title, a.body, a.created_at, a.is_deleted,
                b.name as board_name, b.shortcut_id as board_shortcut_id
            FROM articles a
            JOIN boards b ON a.board_id = b.id
        """
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        sort_column_map = {'created_at': 'a.created_at',
                           'board_name': 'b.name', 'title': 'a.title'}
        db_sort_by = sort_column_map.get(sort_by, 'a.created_at')

        query += f" ORDER BY {db_sort_by} {order}"
        query += " LIMIT 100"

        return self._db.execute_query(query, tuple(params), fetch='all')

    def get_total_count(self):
        query = "SELECT COUNT(*) as count FROM articles"
        result = self._db.execute_query(query, fetch='one')
        return result['count'] if result else 0

    def get_thread_count(self, board_id_pk):
        query = "SELECT COUNT(*) AS count FROM articles WHERE board_id = %s AND parent_article_id IS NULL AND is_deleted = 0"
        result = self._db.execute_query(query, (board_id_pk,), fetch='one')
        return result['count'] if result else 0

    def get_reply_count(self, parent_article_id_pk):
        query = "SELECT COUNT(*) AS count FROM articles WHERE parent_article_id = %s AND is_deleted = 0"
        result = self._db.execute_query(
            query, (parent_article_id_pk,), fetch='one')
        return result['count'] if result else 0


class MailManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def get_total_unread_count(self, user_id_pk):
        query = "SELECT COUNT(*) AS count FROM mails WHERE recipient_id = %s AND is_read = 0 AND recipient_deleted = 0"
        result = self._db.execute_query(query, (user_id_pk,), fetch='one')
        return result['count'] if result else 0

    def get_total_count(self, user_id_pk):
        query = "SELECT COUNT(*) AS count FROM mails WHERE recipient_id = %s AND recipient_deleted = 0"
        result = self._db.execute_query(query, (user_id_pk,), fetch='one')
        return result['count'] if result else 0

    def mark_as_read(self, mail_id, recipient_user_id_pk):
        conn = self._db.get_connection()
        cursor = None
        try:
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

    def get_oldest_unread(self, recipient_user_id_pk):
        query = """
            SELECT
                m.id, m.sender_id, m.subject, m.body, m.is_read, m.sent_at, m.recipient_deleted, m.sender_ip_address,
                u.name AS sender_name
            FROM mails AS m
            LEFT JOIN users AS u ON m.sender_id = u.id
            WHERE m.recipient_id = %s AND m.is_read = 0 AND m.recipient_deleted = 0
            ORDER BY sent_at ASC
            LIMIT 1
        """
        return self._db.execute_query(query, (recipient_user_id_pk,), fetch='one')

    def get_for_view(self, user_id_pk, view_mode):
        if view_mode == 'inbox':
            query = """
                SELECT
                    m.id, m.sender_id, m.subject, m.is_read, m.sent_at, m.recipient_deleted, m.sender_ip_address,
                    u.name AS sender_name
                FROM mails AS m
                LEFT JOIN users AS u ON m.sender_id = u.id
                WHERE m.recipient_id = %s
                ORDER BY m.sent_at ASC
            """
        else:
            query = """
                SELECT
                    m.id, m.recipient_id, m.subject, m.is_read, m.sent_at, m.sender_deleted,
                    u.name AS recipient_name
                FROM mails AS m
                LEFT JOIN users AS u ON m.recipient_id = u.id
                WHERE m.sender_id = %s
                ORDER BY m.sent_at ASC
            """
        return self._db.execute_query(query, (user_id_pk,), fetch='all')

    def toggle_delete_status_generic(self, mail_id, user_id, mode_param):
        conn = self._db.get_connection()
        cursor = None
        mode = str(mode_param).strip()

        if mode not in ['sender', 'recipient']:
            logging.error(f"無効なモードが指定されました: {mode}")
            return False, 0

        id_column = 'sender_id' if mode == 'sender' else 'recipient_id'
        deleted_column = 'sender_deleted' if mode == 'sender' else 'recipient_deleted'

        try:
            cursor = conn.cursor(dictionary=True)

            query_select = f"SELECT {deleted_column} FROM mails WHERE id = %s AND {id_column} = %s"
            cursor.execute(query_select, (mail_id, user_id))
            result = cursor.fetchone()

            if result is None:
                logging.warning(
                    f"メール削除トグルに失敗({mode})。メールなしか権限なし (MailID: {mail_id}, UserID: {user_id})")
                return False, 0

            current_status = result[deleted_column]
            new_status = 1 - current_status

            query_update = f"UPDATE mails SET {deleted_column} = %s WHERE id = %s AND {id_column} = %s"
            cursor.execute(query_update, (new_status, mail_id, user_id))
            conn.commit()

            logging.info(
                f"メール(ID:{mail_id})の{deleted_column}を{new_status}に変更しました(User:{user_id},Mode:{mode})")
            return True, new_status

        except mysql.connector.Error as err:
            logging.error(
                f"メール削除トグル処理({mode})中にDBエラー (MailID: {mail_id}, UserID: {user_id}): {err}")
            if conn:
                conn.rollback()
            return False, 0
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def send_system_mail(self, recipient_id, subject, body):
        # usersインスタンスがグローバルに利用可能であることを前提とする
        sender_id = users.get_sysop_user_id()
        if sender_id is None:
            logging.error("システムメールの送信に失敗しました。送信者(シスオペ)が見つかりません。")
            return False

        sent_at = int(time.time())
        query = "INSERT INTO mails (sender_id, recipient_id, subject, body, sent_at, sender_ip_address) VALUES (%s, %s, %s, %s, %s, %s)"
        params = (sender_id, recipient_id, subject, body, sent_at, None)

        if self._db.execute_query(query, params) is not None:
            logging.info(
                f"システムメールを送信しました (To: UserID {recipient_id}, Subject: {subject})")
            return True
        else:
            logging.error(
                f"システムメールのDB保存に失敗しました (To: UserID {recipient_id})")
            return False


class TelegramManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def save(self, sender_name, recipient_name, message, current_timestamp):
        query = "INSERT INTO telegram(sender_name, recipient_name, message, timestamp) VALUES(%s, %s, %s, %s)"
        self._db.execute_query(
            query, (sender_name, recipient_name, message, current_timestamp))

    def load_and_delete(self, recipient_name):
        conn = self._db.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)

            query_select = "SELECT id, sender_name, recipient_name, message, timestamp FROM telegram WHERE recipient_name = %s ORDER BY timestamp ASC"
            cursor.execute(query_select, (recipient_name,))
            results = cursor.fetchall()

            if not results:
                return None

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


class ServerPrefManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def read(self):
        query = "SELECT * FROM server_pref LIMIT 1"
        result = self._db.execute_query(query, fetch='one')
        return result if result else {}

    def update_backup_schedule(self, enabled: bool, cron_string: str):
        update_data = {
            'backup_schedule_enabled': enabled,
            'backup_schedule_cron': cron_string
        }
        return self._db.update_record('server_pref', update_data, {'id': 1})

    def update_online_signup_status(self, enabled: bool):
        """オンラインサインアップの有効/無効を更新する"""
        return self._db.update_record('server_pref', {'online_signup_enabled': enabled}, {'id': 1})


class PluginManagerDB:  # Renamed to avoid conflict with plugin_manager.py
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def get_all_settings(self):
        query = "SELECT plugin_id, is_enabled FROM plugins"
        results = self._db.execute_query(query, fetch='all')
        return {row['plugin_id']: bool(row['is_enabled']) for row in results} if results else {}

    def upsert_setting(self, plugin_id: str, is_enabled: bool):
        current_time = int(time.time())
        query = """
            INSERT INTO plugins (plugin_id, is_enabled, created_at, updated_at)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE is_enabled = VALUES(is_enabled), updated_at = VALUES(updated_at)
        """
        params = (plugin_id, is_enabled, current_time, current_time)
        return self._db.execute_query(query, params) is not None


class AccessLogManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def log_event(self, ip_address, event_type, user_id=None, username=None, message=None):
        query = """
            INSERT INTO access_logs (timestamp, ip_address, user_id, username, event_type, message)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (int(time.time()), ip_address, user_id,
                  username, event_type, message)
        self._db.execute_query(query, params)

    def get_logs(self, limit=200, ip_address=None, username=None, event_type=None, sort_by='timestamp', order='desc'):
        query = """
            SELECT id, timestamp, ip_address, user_id, username, event_type, message
            FROM access_logs
        """
        where_clauses = []
        params = []

        if ip_address:
            where_clauses.append("ip_address LIKE %s")
            params.append(f"%{ip_address}%")

        if username:
            where_clauses.append("username LIKE %s")
            params.append(f"%{username}%")

        if event_type:
            where_clauses.append("event_type = %s")
            params.append(event_type)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        allowed_sort_columns = ['timestamp',
                                'ip_address', 'username', 'event_type']
        if sort_by not in allowed_sort_columns:
            sort_by = 'timestamp'

        if order.lower() not in ['asc', 'desc']:
            order = 'desc'

        query += f" ORDER BY {sort_by} {order} LIMIT %s"
        params.append(limit)

        return self._db.execute_query(query, tuple(params), fetch='all')


class BoardPermissionManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def get_permissions(self, board_id_pk):
        query = "SELECT user_id, access_level FROM board_user_permissions WHERE board_id = %s"
        return self._db.execute_query(query, (board_id_pk,), fetch='all')

    def delete_by_board_id(self, board_id_pk):
        query = "DELETE FROM board_user_permissions WHERE board_id = %s"
        return self._db.execute_query(query, (board_id_pk,)) is not None

    def add(self, board_id_pk, user_id_pk_str, access_level):
        query = "INSERT INTO board_user_permissions (board_id, user_id, access_level) VALUES (%s, %s, %s)"
        return self._db.execute_query(query, (board_id_pk, user_id_pk_str, access_level)) is not None

    def get_user_permission(self, board_id_pk, user_id_pk_str):
        query = "SELECT access_level FROM board_user_permissions WHERE board_id = %s AND user_id = %s"
        result = self._db.execute_query(
            query, (board_id_pk, user_id_pk_str), fetch='one')
        return result['access_level'] if result else None


class PushSubscriptionManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def get_all(self, exclude_user_id=None):
        query = "SELECT user_id, subscription_info FROM push_subscriptions"
        params = ()
        if exclude_user_id is not None:
            query += " WHERE user_id != %s"
            params = (exclude_user_id,)
        return self._db.execute_query(query, params, fetch='all')

    def save(self, user_id, subscription_info_json):
        try:
            query = "INSERT INTO push_subscriptions (user_id, subscription_info, created_at) VALUES (%s, %s, %s)"
            params = (user_id, subscription_info_json, int(time.time()))

            last_row_id = self._db.execute_query(query, params)
            if last_row_id is not None:
                logging.info(f"Push subscription saved for user_id: {user_id}")
                return True
            else:
                logging.error(
                    f"Failed to save push subscription for user {user_id} (execute_query returned None).")
                return False
        except Exception as e:
            logging.error(
                f"Failed to save push subscription for user {user_id}: {e}", exc_info=True)
            return False

    def delete(self, user_id, endpoint_to_delete):
        conn = self._db.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "SELECT id, subscription_info FROM push_subscriptions WHERE user_id = %s", (user_id,))
            subscriptions = cursor.fetchall()

            for sub in subscriptions:
                subscription_info = json.loads(sub['subscription_info'])
                if subscription_info.get('endpoint') == endpoint_to_delete:
                    # マッチするendpointが見つかったら、そのIDで削除
                    cursor.execute(
                        "DELETE FROM push_subscriptions WHERE id = %s", (sub['id'],))
                    conn.commit()
                    logging.info(
                        f"Push subscription deleted for user_id: {user_id} (endpoint: {endpoint_to_delete})")
                    return True

            logging.warning(
                f"No matching push subscription found to delete for user_id: {user_id} (endpoint: {endpoint_to_delete})")
            return False
        except Exception as e:
            logging.error(
                f"Failed to delete push subscription for user {user_id}: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


class PasskeyManager:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def save(self, user_id, credential_id, public_key, sign_count, transports, nickname):
        query = """
            INSERT INTO passkeys (user_id, credential_id, public_key, sign_count, transports, created_at, nickname)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = (user_id, credential_id, public_key, sign_count, json.dumps(
            transports), int(time.time()), nickname)
        return self._db.execute_query(query, params) is not None

    def get_by_user(self, user_id):
        query = "SELECT * FROM passkeys WHERE user_id = %s"
        return self._db.execute_query(query, (user_id,), fetch='all')

    def get_by_credential_id(self, credential_id):
        query = "SELECT * FROM passkeys WHERE credential_id = %s"
        return self._db.execute_query(query, (credential_id,), fetch='one')

    def update_sign_count(self, credential_id, new_sign_count):
        query = "UPDATE passkeys SET sign_count = %s, last_used_at = %s WHERE credential_id = %s"
        params = (new_sign_count, int(time.time()), credential_id)
        return self._db.execute_query(query, params) is not None

    def delete_by_id_and_user_id(self, passkey_id: int, user_id: int) -> bool:
        query = "DELETE FROM passkeys WHERE id = %s AND user_id = %s"
        conn = self._db.get_connection()
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(query, (passkey_id, user_id))
            conn.commit()
            return cursor.rowcount > 0
        except mysql.connector.Error as err:
            logging.error(
                f"Passkey削除中にDBエラー (passkey_id: {passkey_id}, user_id: {user_id}): {err}")
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


class DatabaseInitializer:
    def __init__(self, db_manager_instance):
        self._db = db_manager_instance

    def check_initialized(self):
        try:
            query = "SHOW TABLES LIKE 'users'"
            result = self._db.execute_query(query, fetch='one')
            return result is not None
        except Exception as e:
            logging.error(f"データベース初期化チェック中にエラー: {e}")
            return False

    def initialize_and_sysop(self, sysop_id, sysop_password, sysop_email):
        # utilモジュールはdatabase.pyの外部にあるため、ここでインポートする
        from . import util

        try:
            # テーブル作成クエリ
            create_queries = [
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    name VARCHAR(255) UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    registdate INT,
                    level INT DEFAULT 1,
                    lastlogin INT,
                    lastlogout INT,
                    comment TEXT,
                    email VARCHAR(255),
                    menu_mode VARCHAR(1) DEFAULT '1' NOT NULL,
                    telegram_restriction INT DEFAULT 0 NOT NULL,
                    blacklist TEXT,
                    exploration_list TEXT,
                    read_progress JSON
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS server_pref (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    bbs INT DEFAULT 2,
                    chat INT DEFAULT 2,
                    mail INT DEFAULT 2,
                    telegram INT DEFAULT 2,
                    userpref INT DEFAULT 2,
                    who INT DEFAULT 2,
                    default_exploration_list TEXT,
                    hamlet INT DEFAULT 2,
                    login_message TEXT,
                    backup_schedule_enabled BOOLEAN DEFAULT 0,
                    backup_schedule_cron VARCHAR(255) DEFAULT '0 3 * * *'
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS mails (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    sender_id INT NOT NULL,
                    sender_display_name TEXT,
                    sender_ip_address VARCHAR(45),
                    recipient_id INT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    is_read BOOLEAN DEFAULT 0,
                    sent_at INT NOT NULL,
                    sender_deleted BOOLEAN DEFAULT 0,
                    recipient_deleted BOOLEAN DEFAULT 0
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS telegram (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    sender_name TEXT NOT NULL,
                    recipient_name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp INT NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS boards (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    shortcut_id VARCHAR(255) UNIQUE NOT NULL,
                    operators JSON,
                    default_permission VARCHAR(10) NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    kanban_body TEXT,
                    last_posted_at INT DEFAULT 0,
                    board_type VARCHAR(10) NOT NULL DEFAULT 'simple',
                    status VARCHAR(10) NOT NULL DEFAULT 'active',
                    read_level INT NOT NULL DEFAULT 1,
                    write_level INT NOT NULL DEFAULT 1,
                    allow_attachments BOOLEAN DEFAULT 0 NOT NULL,
                    allowed_extensions TEXT DEFAULT NULL,
                    max_attachment_size_mb INT DEFAULT NULL,
                    max_threads INT DEFAULT 0,
                    max_replies INT DEFAULT 0
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS articles (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    board_id INT NOT NULL,
                    article_number INT,
                    parent_article_id INT,
                    user_id TEXT NOT NULL,
                    title TEXT,
                    body TEXT NOT NULL,
                    ip_address VARCHAR(45),
                    is_deleted BOOLEAN DEFAULT 0,
                    created_at INT,
                    attachment_filename TEXT,
                    attachment_originalname TEXT,
                    attachment_size INT DEFAULT NULL,
                    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
                    UNIQUE (board_id, article_number)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS passkeys (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    credential_id VARBINARY(255) UNIQUE NOT NULL,
                    public_key VARBINARY(255) NOT NULL,
                    sign_count INT UNSIGNED NOT NULL DEFAULT 0,
                    transports JSON,
                    created_at INT,
                    last_used_at INT,
                    nickname VARCHAR(255),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS board_user_permissions (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    board_id INT NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    access_level VARCHAR(10) NOT NULL,
                    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
                    UNIQUE (board_id, user_id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    subscription_info TEXT NOT NULL,
                    created_at INT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS activitypub_actors (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    actor_type VARCHAR(50) NOT NULL,
                    actor_identifier VARCHAR(255) NOT NULL,
                    private_key_pem TEXT,
                    public_key_pem TEXT,
                    created_at INT,
                    UNIQUE KEY (actor_type, actor_identifier)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS plugins (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    plugin_id VARCHAR(255) UNIQUE NOT NULL,
                    is_enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_at INT,
                    updated_at INT
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS access_logs (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    timestamp INT NOT NULL,
                    ip_address VARCHAR(45),
                    user_id INT,
                    username VARCHAR(255),
                    event_type VARCHAR(50) NOT NULL,
                    message VARCHAR(255),
                    INDEX (timestamp),
                    INDEX (ip_address),
                    INDEX (user_id)
                )
                """
            ]
            for query in create_queries:
                self._db.execute_query(query)

            logging.info("All tables created or already exist.")

            # 初期データ挿入
            # server_pref
            if not self._db.execute_query("SELECT * FROM server_pref", fetch='one'):
                self._db.execute_query(
                    "INSERT INTO server_pref (id, login_message) VALUES (%s, %s)",
                    (1, 'GR-BBSへようこそ！')
                )
                logging.info("Initialized server_pref with default values.")

            # Sysopユーザー
            # usersマネージャーのメソッドを使用
            if not users.get_auth_info(sysop_id):
                salt, hashed_password = util.hash_password(sysop_password)
                users.register(
                    username=sysop_id,
                    hashed_password=hashed_password,
                    salt=salt,
                    comment='Sysop',
                    level=5,
                    email=sysop_email
                )
                logging.info(f"Sysop user '{sysop_id}' created.")

            # Guestユーザー
            if not users.get_auth_info('GUEST'):
                salt, hashed_password = util.hash_password('GUEST')
                users.register(
                    username='GUEST',
                    hashed_password=hashed_password,
                    salt=salt,
                    comment='Guest',
                    level=1,
                    email='guest@example.com'
                )
                logging.info("Guest user created.")

            return True
        except Exception as e:
            logging.critical(f"データベースの初期化中に致命的なエラー: {e}", exc_info=True)
            return False

    def apply_migrations(self):
        """
        アプリケーション起動時にデータベーススキーマの変更を適用する。
        """
        conn = self._db.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)

            # --- pluginsテーブルの存在チェックと作成 ---
            cursor.execute("SHOW TABLES LIKE 'plugins'")
            if not cursor.fetchone():
                # util.pyの定義と合わせる
                create_query = """
                CREATE TABLE plugins (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    plugin_id VARCHAR(255) UNIQUE NOT NULL,
                    is_enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_at INT,
                    updated_at INT
                )
                """
                cursor.execute(create_query)
                logging.info("データベースマイグレーション: 'plugins'テーブルを作成しました。")

            # server_prefテーブルのカラムをチェック
            cursor.execute("DESCRIBE server_pref")
            columns = [row['Field'].lower() for row in cursor.fetchall()]

            # backup_schedule_enabled カラムが存在しない場合に追加
            if 'backup_schedule_enabled' not in columns:
                cursor.execute(
                    "ALTER TABLE server_pref ADD COLUMN backup_schedule_enabled BOOLEAN DEFAULT 0")
                logging.info(
                    "データベースマイグレーション: 'server_pref'テーブルに'backup_schedule_enabled'カラムを追加しました。")

            # backup_schedule_cron カラムが存在しない場合に追加
            if 'backup_schedule_cron' not in columns:
                cursor.execute(
                    "ALTER TABLE server_pref ADD COLUMN backup_schedule_cron VARCHAR(255) DEFAULT '0 3 * * *'")
                logging.info(
                    "データベースマイグレーション: 'server_pref'テーブルに'backup_schedule_cron'カラムを追加しました。")

            # online_signup_enabled カラムが存在しない場合に追加
            if 'online_signup_enabled' not in columns:
                cursor.execute(
                    "ALTER TABLE server_pref ADD COLUMN online_signup_enabled BOOLEAN NOT NULL DEFAULT 0")
                logging.info(
                    "データベースマイグレーション: 'server_pref'テーブルに'online_signup_enabled'カラムを追加しました。")

            # --- access_logsテーブルの存在チェックと作成 ---
            cursor.execute("SHOW TABLES LIKE 'access_logs'")
            if not cursor.fetchone():
                create_query = """
                CREATE TABLE access_logs (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    timestamp INT NOT NULL,
                    ip_address VARCHAR(45),
                    user_id INT,
                    username VARCHAR(255),
                    event_type VARCHAR(50) NOT NULL,
                    message VARCHAR(255),
                    INDEX (timestamp),
                    INDEX (ip_address),
                    INDEX (user_id)
                )
                """
                cursor.execute(create_query)
                logging.info("データベースマイグレーション: 'access_logs'テーブルを作成しました。")

        except Exception as e:
            logging.error(f"Database migration failed: {e}", exc_info=True)
        finally:
            if conn:
                conn.close()


# マネージャークラスのインスタンス化
# これらのインスタンスは、他のモジュールから database.users.get_auth_info() のようにアクセスされる
db_manager = DBManager()
users = UserManager(db_manager)
boards = BoardManager(db_manager)
articles = ArticleManager(db_manager)
mails = MailManager(db_manager)
telegrams = TelegramManager(db_manager)
server_prefs = ServerPrefManager(db_manager)
# Renamed to avoid conflict with plugin_manager.py
plugins = PluginManagerDB(db_manager)
access_logs = AccessLogManager(db_manager)
board_permissions = BoardPermissionManager(db_manager)
push_subscriptions = PushSubscriptionManager(db_manager)
passkeys = PasskeyManager(db_manager)
initializer = DatabaseInitializer(db_manager)

# 既存のトップレベル関数を新しいマネージャーメソッドにマッピング
# これにより、他のファイルからの呼び出しを変更せずに互換性を維持する


def init_connection_pool(pool_name, pool_size, db_config):
    db_manager.init_pool(pool_name, pool_size, db_config)


def get_connection():
    return db_manager.get_connection()


def execute_query(query, params=None, fetch=None):
    return db_manager.execute_query(query, params, fetch)


def update_record(table, set_data, where_data):
    return db_manager.update_record(table, set_data, where_data)


def get_user_auth_info(username):
    return users.get_auth_info(username)


def get_user_by_id(user_id):
    return users.get_by_id(user_id)


def get_user_id_from_user_name(username):
    return users.get_id_from_name(username)


def get_user_name_from_user_id(user_id):
    return users.get_name_from_id(user_id)


def get_user_names_from_user_ids(user_ids):
    return users.get_names_from_ids(user_ids)


def get_total_user_count():
    return users.get_total_count()


def get_daily_user_registrations(days=7):
    return users.get_daily_registrations(days)


def register_user(username, hashed_password, salt, comment, level=0, menu_mode='2', telegram_restriction=0, email=''):
    return users.register(username, hashed_password, salt, comment, level, menu_mode, telegram_restriction, email)


def delete_user(user_id):
    return users.delete(user_id)


def get_memberlist(search_word=None):
    return users.get_memberlist(search_word)


def get_all_users(sort_by='id', order='asc', search_term=None):
    return users.get_all(sort_by, order, search_term)


def get_sysop_user_id():
    return users.get_sysop_user_id()


def read_server_pref():
    return server_prefs.read()


def update_backup_schedule(enabled: bool, cron_string: str):
    return server_prefs.update_backup_schedule(enabled, cron_string)


def update_online_signup_status(enabled: bool):
    """オンラインサインアップの有効/無効をDBで更新する"""
    return server_prefs.update_online_signup_status(enabled)


def get_board_by_shortcut_id(shortcut_id):
    return boards.get_by_shortcut_id(shortcut_id)


def get_board_by_id(board_id_pk):
    return boards.get_by_id(board_id_pk)


def get_all_boards():
    return boards.get_all()


def get_total_board_count():
    return boards.get_total_count()


def create_board_entry(shortcut_id, name, description, operators, default_permission, kanban_body, status, read_level=1, write_level=1, board_type="simple", allow_attachments=0, allowed_extensions=None, max_attachment_size_mb=None, max_threads=0, max_replies=0):
    return boards.create_entry(shortcut_id, name, description, operators, default_permission, kanban_body, status, read_level, write_level, board_type, allow_attachments, allowed_extensions, max_attachment_size_mb, max_threads, max_replies)


def delete_board_entry(shortcut_id):
    return boards.delete_entry(shortcut_id)


def delete_board_and_related_data(board_id_pk):
    return boards.delete_and_related_data(board_id_pk)


def update_board_operators(board_id_pk, operator_user_ids_json_string):
    return boards.update_operators(board_id_pk, operator_user_ids_json_string)


def update_board_kanban(board_id_pk, new_kanban_body):
    return boards.update_kanban(board_id_pk, new_kanban_body)


def update_board_levels(board_id_pk, read_level, write_level):
    return boards.update_levels(board_id_pk, read_level, write_level)


def update_board_last_posted_at(board_id_pk, timestamp=None):
    return boards.update_last_posted_at(board_id_pk, timestamp)


def get_all_boards_for_sysop_list(sort_by='shortcut_id', order='asc', search_term=None):
    return boards.get_all_for_sysop_list(sort_by, order, search_term)


def get_articles_by_board_id(board_id_pk, order_by="created_at ASC, article_number ASC", include_deleted=False):
    return articles.get_by_board_id(board_id_pk, order_by, include_deleted)


def get_article_by_board_and_number(board_id, article_number, include_deleted=False):
    return articles.get_by_board_and_number(board_id, article_number, include_deleted)


def get_new_articles_for_board(board_id_pk, last_login_timestamp):
    return articles.get_new_for_board(board_id_pk, last_login_timestamp)


def get_next_article_number(board_id_pk):
    return articles.get_next_number(board_id_pk)


def insert_article(board_id_pk, article_number, user_identifier, title, body, timestamp, ip_address=None, parent_article_id=None, attachment_filename=None, attachment_originalname=None, attachment_size=None):
    return articles.insert(board_id_pk, article_number, user_identifier, title, body, timestamp, ip_address, parent_article_id, attachment_filename, attachment_originalname, attachment_size)


def get_article_by_id(article_id):
    return articles.get_by_id(article_id)


def get_article_by_attachment_filename(filename):
    return articles.get_by_attachment_filename(filename)


def toggle_article_deleted_status(article_id):
    return articles.toggle_deleted_status(article_id)


def bulk_update_articles_deleted_status(article_ids, new_status):
    return articles.bulk_update_deleted_status(article_ids, new_status)


def get_thread_root_articles_with_reply_count(board_id_pk, include_deleted=False):
    return articles.get_thread_root_articles_with_reply_count(board_id_pk, include_deleted)


def get_replies_for_article(parent_article_id, include_deleted=False):
    return articles.get_replies_for_article(parent_article_id, include_deleted)


def get_daily_article_posts(days=7):
    return articles.get_daily_posts(days)


def search_all_articles(keyword=None, author_id=None, author_name_guest=None, sort_by='created_at', order='desc'):
    return articles.search_all(keyword, author_id, author_name_guest, sort_by, order)


def get_total_article_count():
    return articles.get_total_count()


def get_total_unread_mail_count(user_id_pk):
    return mails.get_total_unread_count(user_id_pk)


def get_total_mail_count(user_id_pk):
    return mails.get_total_count(user_id_pk)


def mark_mail_as_read(mail_id, recipient_user_id_pk):
    return mails.mark_as_read(mail_id, recipient_user_id_pk)


def get_oldest_unread_mail(recipient_user_id_pk):
    return mails.get_oldest_unread(recipient_user_id_pk)


def get_mails_for_view(user_id_pk, view_mode):
    return mails.get_for_view(user_id_pk, view_mode)


def toggle_mail_delete_status_generic(mail_id, user_id, mode_param):
    return mails.toggle_delete_status_generic(mail_id, user_id, mode_param)


def send_system_mail(recipient_id, subject, body):
    return mails.send_system_mail(recipient_id, subject, body)


def save_telegram(sender_name, recipient_name, message, current_timestamp):
    return telegrams.save(sender_name, recipient_name, message, current_timestamp)


def load_and_delete_telegrams(recipient_name):
    return telegrams.load_and_delete(recipient_name)


def get_all_plugin_settings():
    return plugins.get_all_settings()


def upsert_plugin_setting(plugin_id: str, is_enabled: bool):
    return plugins.upsert_setting(plugin_id, is_enabled)


def log_access_event(ip_address, event_type, user_id=None, username=None, message=None):
    return access_logs.log_event(ip_address, event_type, user_id, username, message)


def get_access_logs(limit=200, ip_address=None, username=None, event_type=None, sort_by='timestamp', order='desc'):
    return access_logs.get_logs(limit, ip_address, username, event_type, sort_by, order)


def get_board_permissions(board_id_pk):
    return board_permissions.get_permissions(board_id_pk)


def delete_board_permissions_by_board_id(board_id_pk):
    return board_permissions.delete_by_board_id(board_id_pk)


def add_board_permission(board_id_pk, user_id_pk_str, access_level):
    return board_permissions.add(board_id_pk, user_id_pk_str, access_level)


def get_user_permission_for_board(board_id_pk, user_id_pk_str):
    return board_permissions.get_user_permission(board_id_pk, user_id_pk_str)


def get_all_subscriptions(exclude_user_id=None):
    return push_subscriptions.get_all(exclude_user_id)


def save_push_subscription(user_id, subscription_info_json):
    return push_subscriptions.save(user_id, subscription_info_json)


def delete_push_subscription(user_id, endpoint_to_delete):
    return push_subscriptions.delete(user_id, endpoint_to_delete)


def save_passkey(user_id, credential_id, public_key, sign_count, transports, nickname):
    return passkeys.save(user_id, credential_id, public_key, sign_count, transports, nickname)


def get_passkeys_by_user(user_id):
    return passkeys.get_by_user(user_id)


def get_passkey_by_credential_id(credential_id):
    return passkeys.get_by_credential_id(credential_id)


def update_passkey_sign_count(credential_id, new_sign_count):
    return passkeys.update_sign_count(credential_id, new_sign_count)


def delete_passkey_by_id_and_user_id(passkey_id: int, user_id: int) -> bool:
    return passkeys.delete_by_id_and_user_id(passkey_id, user_id)


def check_database_initialized():
    return initializer.check_initialized()


def initialize_database_and_sysop(sysop_id, sysop_password, sysop_email):
    return initializer.initialize_and_sysop(sysop_id, sysop_password, sysop_email)


def apply_migrations():
    return initializer.apply_migrations()
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


def get_total_user_count():
    """登録ユーザーの総数を取得する"""
    query = "SELECT COUNT(*) as count FROM users"
    result = execute_query(query, fetch='one')
    return result['count'] if result else 0


def get_total_board_count():
    """掲示板の総数を取得する"""
    query = "SELECT COUNT(*) as count FROM boards"
    result = execute_query(query, fetch='one')
    return result['count'] if result else 0


def get_total_article_count():
    """記事の総数を取得する"""
    query = "SELECT COUNT(*) as count FROM articles"
    result = execute_query(query, fetch='one')
    return result['count'] if result else 0


def get_daily_user_registrations(days=7):
    """過去N日間の日毎のユーザー登録数を取得する"""
    query = """
        SELECT
            DATE(FROM_UNIXTIME(registdate)) as registration_date,
            COUNT(*) as count
        FROM users
        WHERE registdate >= UNIX_TIMESTAMP(CURDATE() - INTERVAL %s DAY)
        GROUP BY registration_date
        ORDER BY registration_date ASC
    """
    return execute_query(query, (days - 1,), fetch='all')


def get_daily_article_posts(days=7):
    """過去N日間の日毎の記事投稿数を取得する"""
    query = """
        SELECT DATE(FROM_UNIXTIME(created_at)) as post_date, COUNT(*) as count
        FROM articles WHERE created_at >= UNIX_TIMESTAMP(CURDATE() - INTERVAL %s DAY)
        GROUP BY post_date ORDER BY post_date ASC
    """
    return execute_query(query, (days - 1,), fetch='all')


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
    return execute_query(query, params) is not None


def read_server_pref():
    """サーバー設定を読み込む"""
    query = "SELECT * FROM server_pref LIMIT 1"
    result = execute_query(query, fetch='one')
    return result if result else {}


def get_board_by_shortcut_id(shortcut_id):
    """指定されたショートカットIDの掲示板情報をDBから取得"""
    query = "SELECT * FROM boards WHERE shortcut_id = %s"
    return execute_query(query, (shortcut_id,), fetch='one')


def get_board_by_id(board_id_pk):
    """指定された主キーIDの掲示板情報をDBから取得"""
    query = "SELECT * FROM boards WHERE id = %s"
    return execute_query(query, (board_id_pk,), fetch='one')


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
        SELECT
            m.id, m.sender_id, m.subject, m.body, m.is_read, m.sent_at, m.recipient_deleted, m.sender_ip_address,
            u.name AS sender_name
        FROM mails AS m
        LEFT JOIN users AS u ON m.sender_id = u.id
        WHERE m.recipient_id = %s AND m.is_read = 0 AND m.recipient_deleted = 0
        ORDER BY sent_at ASC
        LIMIT 1
    """
    return execute_query(query, (recipient_user_id_pk,), fetch='one')


def get_mails_for_view(user_id_pk, view_mode):
    """
    指定されたユーザーのメール一覧を、表示に必要な情報をJOINして取得する。
    view_mode: 'inbox' または 'outbox'
    """
    if view_mode == 'inbox':
        # 受信箱: 送信者の名前をJOINで取得
        query = """
            SELECT
                m.id, m.sender_id, m.subject, m.is_read, m.sent_at, m.recipient_deleted, m.sender_ip_address,
                u.name AS sender_name
            FROM mails AS m
            LEFT JOIN users AS u ON m.sender_id = u.id
            WHERE m.recipient_id = %s
            ORDER BY m.sent_at ASC
        """
    else:  # outbox
        # 送信箱: 宛先の名前をJOINで取得
        query = """
            SELECT
                m.id, m.recipient_id, m.subject, m.is_read, m.sent_at, m.sender_deleted,
                u.name AS recipient_name
            FROM mails AS m
            LEFT JOIN users AS u ON m.recipient_id = u.id
            WHERE m.sender_id = %s
            ORDER BY m.sent_at ASC
        """
    return execute_query(query, (user_id_pk,), fetch='all')


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


def set_user_exploration_list(user_id, exploration_list_str):
    """ユーザ探索リストを更新"""
    try:
        update_record(
            'users', {'exploration_list': exploration_list_str}, {'id': user_id})
        logging.info(f"ユーザID {user_id} の探索リストを更新しました。")
        return True
    except Exception as e:
        # ログにリストの先頭部分を含める
        logging.error(
            f"探索リスト更新中にDBエラー (UserID: {user_id}, List: {exploration_list_str[:50]}...): {e}")
        return False


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
    conn = None
    cursor = None
    mode = str(mode_param).strip()

    if mode not in ['sender', 'recipient']:
        logging.error(f"無効なモードが指定されました: {mode}")
        return False, 0

    id_column = 'sender_id' if mode == 'sender' else 'recipient_id'
    deleted_column = 'sender_deleted' if mode == 'sender' else 'recipient_deleted'

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. 現在の状態を取得
        query_select = f"SELECT {deleted_column} FROM mails WHERE id = %s AND {id_column} = %s"
        cursor.execute(query_select, (mail_id, user_id))
        result = cursor.fetchone()

        if result is None:
            logging.warning(
                f"メール削除トグルに失敗({mode})。メールなしか権限なし (MailID: {mail_id}, UserID: {user_id})")
            return False, 0

        current_status = result[deleted_column]
        new_status = 1 - current_status  # 0 -> 1, 1 -> 0

        # 2. 更新
        query_update = f"UPDATE mails SET {deleted_column} = %s WHERE id = %s AND {id_column} = %s"
        cursor.execute(query_update, (new_status, mail_id, user_id))
        conn.commit()

        logging.info(
            f"メール(ID:{mail_id})の{deleted_column}を{new_status}に変更しました(User:{user_id},Mode:{mode})")
        return True, new_status

    except mysql.connector.Error as err:
        logging.error(
            f"メール削除トグル処理({mode})中にDBエラー (MailID: {mail_id}, UserID: {user_id}): {err}")
        if conn:
            conn.rollback()
        return False, 0
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_memberlist(search_word=None):
    """メンバーリストを取得する。"""
    query = "SELECT name, comment FROM users"
    params = []
    if search_word:
        query += " WHERE name LIKE %s OR comment LIKE %s"
        params = [f"%{search_word}%", f"%{search_word}%"]
    return execute_query(query, tuple(params), fetch='all')


def register_user(username, hashed_password, salt, comment, level=0, menu_mode='2', telegram_restriction=0, email=''):
    """新しいユーザーをデータベースに登録する"""
    query = """
        INSERT INTO users (
            name, password, salt, registdate, level, lastlogin, lastlogout,
            comment, email, menu_mode, telegram_restriction, blacklist,
            exploration_list, read_progress
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    import time

    username_upper = username.upper()
    params = (
        username_upper, hashed_password, salt, int(time.time()), level, 0, 0,
        comment, email, menu_mode, telegram_restriction, '', '', '{}'
    )
    return execute_query(query, params) is not None


def delete_user(user_id):
    """ユーザーを削除する"""
    query = "DELETE FROM users WHERE id = %s"
    return execute_query(query, (user_id,)) is not None


def create_board_entry(shortcut_id, name, description, operators, default_permission, kanban_body, status, read_level=1, write_level=1, board_type="simple", allow_attachments=0, allowed_extensions=None, max_attachment_size_mb=None, max_threads=0, max_replies=0):
    """新しい掲示板エントリをboardsテーブルに挿入"""
    query = """
    INSERT INTO boards (shortcut_id, name, description, operators, default_permission, kanban_body, status, last_posted_at, read_level, write_level, board_type, allow_attachments, allowed_extensions, max_attachment_size_mb, max_threads, max_replies)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (shortcut_id, name, description, operators, default_permission,
              kanban_body, status, read_level, write_level, board_type, allow_attachments, allowed_extensions, max_attachment_size_mb, max_threads, max_replies)
    return execute_query(query, params) is not None


def delete_board_entry(shortcut_id):
    """掲示板エントリを削除"""
    query = "DELETE FROM boards WHERE shortcut_id = %s"
    return execute_query(query, (shortcut_id,)) is not None


def delete_board_and_related_data(board_id_pk):
    """
    指定された掲示板と、それに関連する全ての記事、権限設定をトランザクション内で削除する。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # 1. 関連する記事を削除
        cursor.execute(
            "DELETE FROM articles WHERE board_id = %s", (board_id_pk,))
        logging.info(
            f"{cursor.rowcount} articles deleted for board_id {board_id_pk}.")

        # 2. 関連する権限設定を削除
        cursor.execute(
            "DELETE FROM board_user_permissions WHERE board_id = %s", (board_id_pk,))
        logging.info(
            f"{cursor.rowcount} permissions deleted for board_id {board_id_pk}.")

        # 3. 掲示板本体を削除
        cursor.execute("DELETE FROM boards WHERE id = %s", (board_id_pk,))
        logging.info(
            f"{cursor.rowcount} board entry deleted for board_id {board_id_pk}.")

        conn.commit()
        logging.info(
            f"Board ID {board_id_pk} and all related data have been successfully deleted.")
        return True
    except mysql.connector.Error as err:
        logging.error(
            f"掲示板削除中にDBエラー (BoardID: {board_id_pk}): {err}", exc_info=True)
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def insert_article(board_id_pk, article_number, user_identifier, title, body, timestamp, ip_address=None, parent_article_id=None, attachment_filename=None, attachment_originalname=None, attachment_size=None):
    """記事を挿入し、IDを返す"""
    query = """
        INSERT INTO articles (board_id, article_number, user_id, parent_article_id, title, body, created_at, ip_address, attachment_filename, attachment_originalname, attachment_size)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (board_id_pk, article_number, user_identifier,
              parent_article_id, title, body, timestamp, ip_address,
              attachment_filename, attachment_originalname, attachment_size)
    return execute_query(query, params)


def get_article_by_id(article_id):
    """記事ID(主キー)から記事情報を取得する"""
    query = "SELECT * FROM articles WHERE id = %s"
    return execute_query(query, (article_id,), fetch='one')


def get_article_by_attachment_filename(filename):
    """添付ファイル名から記事情報を取得する"""
    query = "SELECT * FROM articles WHERE attachment_filename = %s"
    return execute_query(query, (filename,), fetch='one')


def apply_migrations():
    """
    アプリケーション起動時にデータベーススキーマの変更を適用する。
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # --- pluginsテーブルの存在チェックと作成 ---
        cursor.execute("SHOW TABLES LIKE 'plugins'")
        if not cursor.fetchone():
            # util.pyの定義と合わせる
            create_query = """
            CREATE TABLE plugins (
                id INT PRIMARY KEY AUTO_INCREMENT,
                plugin_id VARCHAR(255) UNIQUE NOT NULL,
                is_enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at INT,
                updated_at INT
            )
            """
            cursor.execute(create_query)
            logging.info("データベースマイグレーション: 'plugins'テーブルを作成しました。")

        # server_prefテーブルのカラムをチェック
        cursor.execute("DESCRIBE server_pref")
        columns = [row['Field'].lower() for row in cursor.fetchall()]

        # backup_schedule_enabled カラムが存在しない場合に追加
        if 'backup_schedule_enabled' not in columns:
            cursor.execute(
                "ALTER TABLE server_pref ADD COLUMN backup_schedule_enabled BOOLEAN DEFAULT 0")
            logging.info(
                "データベースマイグレーション: 'server_pref'テーブルに'backup_schedule_enabled'カラムを追加しました。")

        # backup_schedule_cron カラムが存在しない場合に追加
        if 'backup_schedule_cron' not in columns:
            cursor.execute(
                "ALTER TABLE server_pref ADD COLUMN backup_schedule_cron VARCHAR(255) DEFAULT '0 3 * * *'")
            logging.info(
                "データベースマイグレーション: 'server_pref'テーブルに'backup_schedule_cron'カラムを追加しました。")

        # online_signup_enabled カラムが存在しない場合に追加
        if 'online_signup_enabled' not in columns:
            cursor.execute(
                "ALTER TABLE server_pref ADD COLUMN online_signup_enabled BOOLEAN NOT NULL DEFAULT 0")
            logging.info(
                "データベースマイグレーション: 'server_pref'テーブルに'online_signup_enabled'カラムを追加しました。")

        # --- access_logsテーブルの存在チェックと作成 ---
        cursor.execute("SHOW TABLES LIKE 'access_logs'")
        if not cursor.fetchone():
            create_query = """
            CREATE TABLE access_logs (
                id INT PRIMARY KEY AUTO_INCREMENT,
                timestamp INT NOT NULL,
                ip_address VARCHAR(45),
                user_id INT,
                username VARCHAR(255),
                event_type VARCHAR(50) NOT NULL,
                message VARCHAR(255),
                INDEX (timestamp),
                INDEX (ip_address),
                INDEX (user_id)
            )
            """
            cursor.execute(create_query)
            logging.info("データベースマイグレーション: 'access_logs'テーブルを作成しました。")

    except Exception as e:
        logging.error(f"Database migration failed: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


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


def get_article_by_board_and_number(board_id, article_number, include_deleted=False):
    """指定された掲示板IDと記事番号の記事を取得する"""
    where_clauses = ["board_id = %s", "article_number = %s"]
    params = [board_id, article_number]

    if not include_deleted:
        where_clauses.append("is_deleted = 0")

    # 添付ファイル情報も取得するよう修正
    query = f"SELECT id, article_number, user_id, parent_article_id, title, body, created_at, is_deleted, ip_address, attachment_filename, attachment_originalname, attachment_size FROM articles WHERE {' AND '.join(where_clauses)}"

    return execute_query(query, tuple(params), fetch='one')


def toggle_article_deleted_status(article_id):
    """記事の is_deleted フラグをトグルする"""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. 現在の状態を取得
        query_select = "SELECT is_deleted FROM articles WHERE id = %s"
        cursor.execute(query_select, (article_id,))
        result = cursor.fetchone()

        if result is None:
            logging.warning(
                f"記事削除フラグのトグル失敗: 記事ID '{article_id}' が見つかりません。")
            return False

        current_status = result['is_deleted']
        new_status = 1 - current_status  # 0 -> 1, 1 -> 0

        # 2. 更新
        query_update = "UPDATE articles SET is_deleted = %s WHERE id = %s"
        cursor.execute(query_update, (new_status, article_id))
        conn.commit()

        logging.info(
            f"記事ID {article_id} の is_deleted を {new_status} に変更しました。")
        return True

    except mysql.connector.Error as err:
        logging.error(
            f"記事削除フラグのトグル中にDBエラー (記事ID: {article_id}): {err}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def bulk_update_articles_deleted_status(article_ids, new_status):
    """
    複数の記事の is_deleted フラグを一括で更新する。
    :param article_ids: 更新対象の記事IDのリスト
    :param new_status: 新しいステータス (0 or 1)
    """
    if not article_ids or new_status not in [0, 1]:
        return 0

    placeholders = ','.join(['%s'] * len(article_ids))
    query = f"UPDATE articles SET is_deleted = %s WHERE id IN ({placeholders})"

    params = [new_status] + article_ids

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        updated_rows = cursor.rowcount
        conn.commit()
        logging.info(f"{updated_rows}件の記事の削除ステータスを {new_status} に更新しました。")
        return updated_rows
    except mysql.connector.Error as err:
        logging.error(f"記事の一括削除ステータス更新中にDBエラー: {err}")
        if conn:
            conn.rollback()
        return 0
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_all_subscriptions(exclude_user_id=None):
    """
    すべての有効なプッシュ通知購読情報を取得する。
    特定のユーザーIDを除外することも可能。
    """
    query = "SELECT user_id, subscription_info FROM push_subscriptions"
    params = ()
    if exclude_user_id is not None:
        query += " WHERE user_id != %s"
        params = (exclude_user_id,)
    return execute_query(query, params, fetch='all')


def save_push_subscription(user_id, subscription_info_json):
    """
    ユーザーのプッシュ通知購読情報を保存する。
    """
    import time
    try:
        # 同じendpointを持つ購読情報が既に存在するかどうかをチェックするロジックは、
        # ユーザーが複数のデバイスで購読できるようにするため、一旦省略します。
        # 必要であれば、endpointをUNIQUEキーにするか、INSERT前にSELECTで確認します。
        query = "INSERT INTO push_subscriptions (user_id, subscription_info, created_at) VALUES (%s, %s, %s)"
        params = (user_id, subscription_info_json, int(time.time()))

        last_row_id = execute_query(query, params)
        if last_row_id is not None:
            logging.info(f"Push subscription saved for user_id: {user_id}")
            return True
        else:
            logging.error(
                f"Failed to save push subscription for user {user_id} (execute_query returned None).")
            return False
    except Exception as e:
        logging.error(
            f"Failed to save push subscription for user {user_id}: {e}", exc_info=True)
        return False


def delete_push_subscription(user_id, endpoint_to_delete):
    """
    ユーザーの特定のプッシュ通知購読情報を、endpointを元に削除する。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # ユーザーのすべての購読情報を取得
        cursor.execute(
            "SELECT id, subscription_info FROM push_subscriptions WHERE user_id = %s", (user_id,))
        subscriptions = cursor.fetchall()

        for sub in subscriptions:
            subscription_info = json.loads(sub['subscription_info'])
            if subscription_info.get('endpoint') == endpoint_to_delete:
                # マッチするendpointが見つかったら、そのIDで削除
                cursor.execute(
                    "DELETE FROM push_subscriptions WHERE id = %s", (sub['id'],))
                conn.commit()
                logging.info(
                    f"Push subscription deleted for user_id: {user_id} (endpoint: {endpoint_to_delete})")
                return True

        logging.warning(
            f"No matching push subscription found to delete for user_id: {user_id} (endpoint: {endpoint_to_delete})")
        return False
    except Exception as e:
        logging.error(
            f"Failed to delete push subscription for user {user_id}: {e}", exc_info=True)
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_all_users(sort_by='id', order='asc', search_term=None):
    """
    すべてのユーザー情報を取得する。ソート順と検索語を指定可能。
    :param sort_by: ソートするカラム名
    :param order: 'asc' または 'desc'
    :param search_term: 検索キーワード
    """
    # SQLインジェクションを防ぐため、許可するカラム名をホワイトリストで管理
    allowed_columns = ['id', 'name', 'level',
                       'email', 'registdate', 'lastlogin']
    if sort_by not in allowed_columns:
        sort_by = 'id'  # デフォルト値

    # 'asc' または 'desc' 以外は 'asc' にする
    if order.lower() not in ['asc', 'desc']:
        order = 'asc'

    params = []
    where_clauses = []

    if search_term:
        where_clauses.append("(name LIKE %s OR email LIKE %s)")
        search_pattern = f"%{search_term}%"
        params.extend([search_pattern, search_pattern])

    # f-string is safe here because we've whitelisted the column names and order direction.
    query = "SELECT id, name, level, registdate, lastlogin, comment, email FROM users"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += f" ORDER BY {sort_by} {order}"
    return execute_query(query, tuple(params), fetch='all')


def get_all_boards_for_sysop_list(sort_by='shortcut_id', order='asc', search_term=None):  # noqa
    """
    シスオペメニューの掲示板一覧表示用に、掲示板の情報を取得する。ソートと検索に対応。
    :param sort_by: ソートするカラム名
    :param order: 'asc' または 'desc'
    :param search_term: 検索キーワード
    """
    # SQLインジェクションを防ぐため、許可するカラム名をホワイトリストで管理
    allowed_columns = [
        'shortcut_id', 'name', 'board_type', 'status', 'last_posted_at',
        'read_level', 'write_level', 'default_permission', 'allow_attachments', 'post_count'
    ]
    if sort_by not in allowed_columns:
        sort_by = 'shortcut_id'

    if order.lower() not in ['asc', 'desc']:
        order = 'asc'

    params = []
    where_clauses = []

    if search_term:
        where_clauses.append("(b.shortcut_id LIKE %s OR b.name LIKE %s)")
        search_pattern = f"%{search_term}%"
        params.extend([search_pattern, search_pattern])

    query = """
        SELECT
            b.id, b.shortcut_id, b.name, b.operators, b.default_permission, b.status,
            b.last_posted_at, b.read_level, b.write_level, b.board_type,
            b.allow_attachments, b.allowed_extensions, b.max_attachment_size_mb,
            (
                SELECT COUNT(*)
                FROM articles a
                WHERE a.board_id = b.id
                AND (b.board_type != 'thread' OR a.parent_article_id IS NULL)
            ) AS post_count
        FROM boards b
    """
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += f" ORDER BY {sort_by} {order}"
    return execute_query(query, tuple(params), fetch='all')


def search_all_articles(keyword=None, author_id=None, author_name_guest=None, sort_by='created_at', order='desc'):
    """
    全ての掲示板を横断して記事を検索する。
    :param keyword: タイトルと本文から検索するキーワード
    :param author_id: 登録ユーザーのID
    :param author_name_guest: GUESTなどの非登録ユーザー名
    :param sort_by: ソートするカラム名
    :param order: 'asc' または 'desc'
    """
    allowed_columns = ['created_at', 'board_name', 'title']
    if sort_by not in allowed_columns:
        sort_by = 'created_at'
    if order.lower() not in ['asc', 'desc']:
        order = 'desc'

    params = []
    where_clauses = []

    if keyword:
        where_clauses.append("(a.title LIKE %s OR a.body LIKE %s)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    if author_id is not None:
        where_clauses.append("a.user_id = %s")
        params.append(str(author_id))
    elif author_name_guest:
        where_clauses.append("a.user_id = %s")
        params.append(author_name_guest)

    query = """
        SELECT
            a.id, a.board_id, a.article_number, a.user_id, a.title, a.body, a.created_at, a.is_deleted,
            b.name as board_name, b.shortcut_id as board_shortcut_id
        FROM articles a
        JOIN boards b ON a.board_id = b.id
    """
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    sort_column_map = {'created_at': 'a.created_at',
                       'board_name': 'b.name', 'title': 'a.title'}
    db_sort_by = sort_column_map.get(sort_by, 'a.created_at')

    query += f" ORDER BY {db_sort_by} {order}"
    query += " LIMIT 100"  # 念のため、最大100件に制限

    return execute_query(query, tuple(params), fetch='all')


def save_passkey(user_id, credential_id, public_key, sign_count, transports, nickname):
    """新しいPasskeyをデータベースに保存する"""
    import time
    query = """
        INSERT INTO passkeys (user_id, credential_id, public_key, sign_count, transports, created_at, nickname)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    params = (user_id, credential_id, public_key, sign_count, json.dumps(
        transports), int(time.time()), nickname)
    return execute_query(query, params) is not None


def get_passkeys_by_user(user_id):
    """指定されたユーザーのすべてのPasskeyを取得する"""
    query = "SELECT * FROM passkeys WHERE user_id = %s"
    return execute_query(query, (user_id,), fetch='all')


def get_passkey_by_credential_id(credential_id):
    """Credential IDでPasskeyを取得する"""
    query = "SELECT * FROM passkeys WHERE credential_id = %s"
    return execute_query(query, (credential_id,), fetch='one')


def update_passkey_sign_count(credential_id, new_sign_count):
    """Passkeyの署名カウントと最終使用日時を更新する"""
    import time
    query = "UPDATE passkeys SET sign_count = %s, last_used_at = %s WHERE credential_id = %s"
    params = (new_sign_count, int(time.time()), credential_id)
    return execute_query(query, params) is not None


def delete_passkey_by_id_and_user_id(passkey_id: int, user_id: int) -> bool:
    """指定されたユーザーIDに属する特定のPasskeyをIDで削除する"""
    query = "DELETE FROM passkeys WHERE id = %s AND user_id = %s"
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query, (passkey_id, user_id))
        conn.commit()
        return cursor.rowcount > 0
    except mysql.connector.Error as err:
        logging.error(
            f"Passkey削除中にDBエラー (passkey_id: {passkey_id}, user_id: {user_id}): {err}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    result = execute_query(query, fetch='one')
    return result if result else {}


def update_backup_schedule(enabled: bool, cron_string: str):
    """バックアップスケジュール設定を更新する"""
    update_data = {
        'backup_schedule_enabled': enabled,
        'backup_schedule_cron': cron_string
    }
    # server_prefは常にID=1のレコードを更新する
    return update_record('server_pref', update_data, {'id': 1}) is not None


def get_all_plugin_settings():
    """すべてのプラグイン設定をDBから取得する"""
    query = "SELECT plugin_id, is_enabled FROM plugins"
    results = execute_query(query, fetch='all')
    # { 'plugin_id': True, ... } の形式の辞書で返す
    return {row['plugin_id']: bool(row['is_enabled']) for row in results} if results else {}


def upsert_plugin_setting(plugin_id: str, is_enabled: bool):
    """プラグイン設定を挿入または更新する (UPSERT)"""
    import time
    query = """
        INSERT INTO plugins (plugin_id, is_enabled, created_at, updated_at)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE is_enabled = VALUES(is_enabled), updated_at = VALUES(updated_at)
    """
    current_time = int(time.time())
    params = (plugin_id, is_enabled, current_time, current_time)
    return execute_query(query, params) is not None


def log_access_event(ip_address, event_type, user_id=None, username=None, message=None):
    """アクセスイベントをデータベースに記録する"""
    import time
    query = """
        INSERT INTO access_logs (timestamp, ip_address, user_id, username, event_type, message)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    params = (int(time.time()), ip_address, user_id,
              username, event_type, message)
    # ログ記録はfire-and-forget。execute_queryがエラーをログに出力してくれる。
    execute_query(query, params)


def get_access_logs(limit=200, ip_address=None, username=None, event_type=None, sort_by='timestamp', order='desc'):
    """最近のアクセスログをデータベースから取得する。フィルタリングとソート機能付き。"""
    query = """
        SELECT id, timestamp, ip_address, user_id, username, event_type, message
        FROM access_logs
    """
    where_clauses = []
    params = []

    if ip_address:
        where_clauses.append("ip_address LIKE %s")
        params.append(f"%{ip_address}%")

    if username:
        where_clauses.append("username LIKE %s")
        params.append(f"%{username}%")

    if event_type:
        where_clauses.append("event_type = %s")
        params.append(event_type)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    # SQLインジェクションを防ぐため、ソートカラムをホワイトリストで検証
    allowed_sort_columns = ['timestamp',
                            'ip_address', 'username', 'event_type']
    if sort_by not in allowed_sort_columns:
        sort_by = 'timestamp'  # デフォルト値

    # 'asc' または 'desc' 以外は 'desc' にする
    if order.lower() not in ['asc', 'desc']:
        order = 'desc'

    query += f" ORDER BY {sort_by} {order} LIMIT %s"
    params.append(limit)

    return execute_query(query, tuple(params), fetch='all')
