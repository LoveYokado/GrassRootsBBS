import sqlite3
import logging
import time
import json

from . import database


def get_user_id_from_user_name(dbname, username):
    """ユーザ名からユーザIDを取得する"""
    try:
        # 呼び出し先をMariaDB用の関数に変更
        # dbnameは使わないが、呼び出し元の互換性のために引数は残す
        return database.get_user_id_from_user_name(username)
    except Exception as e:
        logging.error(f"ユーザID取得中に予期せぬエラー ({username}): {e}")
        return None


def get_user_name_from_user_id(dbname, user_id):
    """ユーザIDからユーザ名を取得する"""
    try:
        # 呼び出し先をMariaDB用の関数に変更
        # dbnameは使わないが、呼び出し元の互換性のために引数は残す
        return database.get_user_name_from_user_id(user_id)
    except Exception as e:
        logging.error(f"ユーザ名取得中に予期せぬエラー (ID: {user_id}): {e}")
        return "(不明)"


def get_user_level_from_user_id(dbname, user_id):
    """ユーザIDからユーザレベルを取得する"""
    try:
        # 呼び出し先をMariaDB用の関数に変更
        # dbnameは使わないが、呼び出し元の互換性のために引数は残す
        return database.get_user_level_from_user_id(user_id)
    except Exception as e:
        logging.error(f"ユーザレベル取得中に予期せぬエラー (ID: {user_id}): {e}")
        return 0


def get_user_auth_info(dbname, username):
    """
    ユーザ名から認証情報を含むユーザデータ取得。
    見つからない場合はNoneを返す。
    """
    try:
        # 呼び出し先をMariaDB用の関数に変更
        # dbnameは使わないが、呼び出し元の互換性のために引数は残す
        return database.get_user_auth_info(username)
    except Exception as e:
        # databaseモジュール内でエラーログは出力される想定だが、念のためここでもログを残す
        logging.error(f"認証情報取得中に予期せぬエラー ({username}): {e}")
        return None


def toggle_mail_delete_status_generic(dbname, mail_id, user_id, mode_param):
    """メールの削除フラグをトグルする汎用関数。"""
    try:
        return database.toggle_mail_delete_status_generic(mail_id, user_id, mode_param)
    except Exception as e:
        logging.error(f"メール削除トグル処理中に予期せぬエラー: {e}")
        return False, 0


def sqlite_execute_query(dbname, sql, params=None, fetch=False, conn=None):
    """汎用的なSQLiteクエリ実行関数。connが渡された場合はその接続を使い、コミットやクローズは行わない。"""
    close_conn_locally = False
    if conn is None:
        conn = sqlite3.connect(dbname)
        close_conn_locally = True

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params or ())
        if fetch:
            results = cur.fetchall()
            return results
        else:
            if close_conn_locally:  # ローカルで接続した場合のみコミット
                conn.commit()
            return True
    except sqlite3.Error as e:
        logging.error(f"SQLiteエラー: {e} (SQL: {sql[:100]})")
        if close_conn_locally and conn:  # ローカルで接続した場合のみロールバック
            conn.rollback()
        return False
    finally:
        if close_conn_locally and conn:  # ローカルで接続した場合のみクローズ
            conn.close()


def update_idbase(dbname, table, ALLOWED_COLUMNS, id_val, col, data):  # id は組み込み関数名なので id_val に変更
    """ ユーザデータベースをIDで検索して更新 """
    if col not in ALLOWED_COLUMNS:
        raise ValueError(
            f"許可されていないカラムが指定されました: {col}. 許可されているカラム: {ALLOWED_COLUMNS}")
    sql = f'UPDATE {table} SET {col} = ? WHERE id=?'
    # params はタプルで渡す
    sqlite_execute_query(dbname, sql, (data, id_val))


def fetchall_idbase(dbname, table, key, keyword):
    """ ユーザデータベースから指定キーで検索 """
    ALLOWED_TABLES = ['users', 'mails', 'boards']
    ALLOWED_KEYS = ['id', 'name', 'sender_id', 'recipient_id', 'shortcut_id']
    if table not in ALLOWED_TABLES:
        raise ValueError(
            f"許可されていないテーブルです: {table}.許可されているテーブル: {ALLOWED_TABLES}")
    if key not in ALLOWED_KEYS:
        raise ValueError(f"許可されていない検索キーです: {key}")
    sql = f'SELECT * FROM {table} WHERE {key}=?'
    results = sqlite_execute_query(dbname, sql, (keyword,), fetch=True)
    # logging.debug(f"fetchall_idbase: SQL results: {results}")
    return results if results else []


def create_bbs_tables_if_not_exist(cur):
    """掲示板機能に必要なテーブルを作成する"""
    # boards テーブル
    cur.execute('''
            CREATE TABLE IF NOT EXISTS boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shortcut_id TEXT UNIQUE NOT NULL,
                operators JSON NOT NULL,
                default_permission TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                kanban_body TEXT DEFAULT '',
                last_posted_at INTEGER DEFAULT 0,
                board_type TEXT NOT NULL DEFAULT 'simple' CHECK(board_type IN ('simple', 'thread')),
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived', 'hidden')),
                read_level INTEGER NOT NULL DEFAULT 1,
                write_level INTEGER NOT NULL DEFAULT 1
            )
        ''')
    logging.info("boards テーブルを作成または確認しました。")

    # articles テーブル
    cur.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                article_number INTEGER,
                parent_article_id INTEGER,
                user_id TEXT NOT NULL,
                title TEXT,
                body TEXT NOT NULL,
                ip_address TEXT,
                is_deleted BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (board_id) REFERENCES boards(id),
                UNIQUE (board_id, article_number)
            )
        ''')
    logging.info("articles テーブルを作成または確認しました。")

    # board_user_permissions テーブル
    cur.execute('''
            CREATE TABLE IF NOT EXISTS board_user_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                access_level TEXT NOT NULL, -- "allow" or "deny"
                FOREIGN KEY (board_id) REFERENCES boards(id),
                UNIQUE (board_id, user_id)
            )
        ''')
    logging.info("board_user_permissions テーブルを作成または確認しました。")


def read_server_pref(dbname):
    """サーバー設定を読み込む"""
    try:
        # 呼び出し先をMariaDB用の関数に変更
        # dbnameは使わないが、呼び出し元の互換性のために引数は残す
        return database.read_server_pref()
    except Exception as e:
        logging.error(f"サーバー設定の読み込み中に予期せぬエラー: {e}")
        # フォールバックとしてデフォルト値を返す
        return [2, 2, 2, 2, 2, 2, "", 2, ""]


def save_telegram(dbname, sender_name, recipient_name, message, current_timestamp):
    """電報をデータベースに保存 (sqlite_execute_query を使用)"""
    try:
        database.save_telegram(
            sender_name, recipient_name, message, current_timestamp)
    except Exception as e:
        logging.error(f"電報の保存中に予期せぬエラー: {e}")


def load_and_delete_telegrams(dbname, recipient_name):
    """指定された受信者の電報を取得し、取得した電報を削除する。"""
    try:
        return database.load_and_delete_telegrams(recipient_name)
    except Exception as e:
        logging.error(f"電報の読み込み/削除中に予期せぬエラー: {e}")
        return None


def get_memberlist(dbname, search_word=None):
    """
    メンバーリストを取得する。検索ワードがなければ全表示
    """
    try:
        conn = sqlite3.connect(dbname)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        sql = "SELECT name, comment FROM users"
        if search_word:
            sql += " WHERE name LIKE ? OR comment LIKE ?"
            cur.execute(sql, (f"%{search_word}%", f"%{search_word}%"))
        else:
            cur.execute(sql)
        results = cur.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except sqlite3.Error as e:
        logging.error(f"会員リスト取得エラー: {e}")
        return None


def update_user_menu_mode(dbname, user_id, new_mode):
    """ユーザーのメニューモードを更新する"""
    ALLOWED_MODES = ['1', '2', '3']
    if new_mode not in ALLOWED_MODES:
        logging.warning(f"無効なメニューモードが指定されました: {new_mode}")
        return False

    sql = "UPDATE users SET menu_mode = ? WHERE id = ?"
    success = sqlite_execute_query(dbname, sql, (new_mode, user_id))
    if success:
        logging.info(f"ユーザーID {user_id} のメニューモードを {new_mode} に更新しました。")
    # エラーログは sqlite_execute_query 内で出力される
    return success


def update_user_password_and_salt(dbname, login_id, new_hashed_password, new_salt_hex):
    """ユーザのパスハッシュとソルトの更新"""
    try:
        # MariaDB用の関数を呼び出す
        user_id = database.get_user_id_from_user_name(login_id)
        if user_id is None:
            logging.error(f"パスワード更新失敗、ユーザが見つかりません: {login_id}")
            return False
        database.update_record(
            'users',
            {'password': new_hashed_password, 'salt': new_salt_hex},
            {'id': user_id}
        )
        logging.info(f"ユーザ '{login_id}' (ID: {user_id}) のパスワードとソルトを更新しました。")
        return True
    except Exception as e:
        logging.error(f"パスワードとソルトの更新中に予期せぬエラー (ユーザ: {login_id}): {e}")
        return False


def update_user_password(dbname, user_id, new_hashed_password, new_salt_hex):
    """ユーザIDを使ってパスワードとソルトを更新する"""
    try:
        database.update_record(
            'users', {'password': new_hashed_password, 'salt': new_salt_hex}, {'id': user_id})
        logging.info(f"ユーザID '{user_id}' のパスワードとソルトを更新しました。")
        return True
    except Exception as e:
        logging.error(
            f"パスワードとソルトの更新中に予期せぬエラー (UserID: {user_id}): {e}")
        return False


def update_user_profile_comment(dbname, user_id, new_comment):
    """ユーザーのプロフィールコメントを更新"""
    return update_user_field(dbname, user_id, 'comment', new_comment)


def update_user_telegram_restriction(dbname, user_id, restriction_level):
    """ユーザの電報受信制限を更新"""
    return update_user_field(dbname, user_id, 'telegram_restriction', restriction_level)


def update_user_blacklist(dbname, user_id, blacklist_str):
    """ユーザのブラックリストを更新"""
    try:
        # 呼び出し先をMariaDB用の汎用更新関数に変更
        # dbnameは使わないが、呼び出し元の互換性のために引数は残す
        database.update_record(
            'users', {'blacklist': blacklist_str}, {'id': user_id})
        logging.info(f"ユーザID {user_id} のブラックリストを更新しました。")
        return True
    except Exception as e:
        logging.error(f"ブラックリスト更新中に予期せぬエラー (UserID: {user_id}): {e}")
        return False


def get_user_names_from_user_ids(dbname, user_ids):
    """
    複数のユーザーIDのリストから、ユーザーIDとユーザー名のマッピング辞書を取得する。
    存在しないIDは結果に含まれない。
    """
    if not user_ids:
        return {}

    # user_ids リスト内の非数値や空文字列を除外
    valid_user_ids = [int(uid)
                      for uid in user_ids if str(uid).strip().isdigit()]
    if not valid_user_ids:
        return {}

    placeholders = ','.join('?' * len(valid_user_ids))
    sql = f"SELECT id, name FROM users WHERE id IN ({placeholders})"

    results = sqlite_execute_query(
        dbname, sql, tuple(valid_user_ids), fetch=True)

    id_to_name_map = {}
    if results:
        for row in results:
            id_to_name_map[row['id']] = row['name']
    return id_to_name_map


def get_user_exploration_list(dbname, user_id):
    """ユーザの探索リストを取得"""
    try:
        sql = "SELECT exploration_list FROM users WHERE id=?"
        results = sqlite_execute_query(dbname, sql, (user_id,), fetch=True)
        if results and results[0] and results[0]['exploration_list'] is not None:
            return results[0]['exploration_list']
        return ""
    except Exception as e:
        logging.error(f"探索リスト取得中にDBエラー (UserID: {user_id}): {e}")
        return ""


def set_user_exploration_list(dbname, user_id, exploration_list_str):
    """ユーザ探索リストを更新"""
    try:
        sql = "UPDATE users SET exploration_list=? WHERE id=?"
        sqlite_execute_query(dbname, sql, (exploration_list_str, user_id))
        logging.info(f"ユーザID {user_id} の探索リストを更新しました。")
        return True
    except Exception as e:
        logging.error(
            f"探索リスト更新中にDBエラー (UserID: {user_id},List:{exploration_list_str[:50]}...): {e}")
        return False


def update_server_default_exploration_list(dbname, exploration_list_str):
    """サーバーのデフォルト探索リストを更新"""
    try:
        # MariaDB用の関数を呼び出す。server_prefテーブルは1行しかなく、id=1と仮定
        database.update_record(
            'server_pref',
            {'default_exploration_list': exploration_list_str},
            {'id': 1}
        )
        logging.info(f"サーバーのデフォルト探索リストを更新しました: {exploration_list_str[:50]}...")
        return True
    except Exception as e:
        logging.error(f"サーバーのデフォルト探索リスト更新中に予期せぬエラー: {e}")
        return False


def get_user_read_progress(dbname, user_id):
    """
    ユーザの掲示板読み込み進捗を取得
    JSONのパースを辞書として返す
    """
    try:
        sql = "SELECT read_progress FROM users WHERE id=?"
        results = sqlite_execute_query(dbname, sql, (user_id,), fetch=True)
        if results and results[0] and results[0]['read_progress'] is not None:
            return json.loads(results[0]['read_progress'])
        return {}
    except Exception as e:
        logging.error(f"掲示板読み込み進捗取得中にDBエラー (UserID: {user_id}): {e}")
        return {}


def update_user_read_progress(dbname, user_id, read_progress_dict):
    """
    ユーザの掲示板読み込み進捗を更新
    辞書をjsonに変換して保存する
    """
    try:
        read_progress_json = json.dumps(read_progress_dict)
        sql = "UPDATE users SET read_progress=? WHERE id=?"
        sqlite_execute_query(dbname, sql, (read_progress_json, user_id))
        logging.info(f"ユーザID {user_id} の掲示板読み込み進捗を更新しました。")
        return True
    except Exception as e:
        logging.error(f"掲示板読み込み進捗更新中にDBエラー (UserID: {user_id}): {e}")
        return False


def register_user(dbname, username, hashed_password, salt, comment, level=0,
                  menu_mode='1', telegram_restriction=0):
    """新しいユーザーをデータベースに登録する"""
    try:
        email_addr = f'{username.lower()}@example.com'
        return database.register_user(
            username=username,
            hashed_password=hashed_password,
            salt=salt,
            comment=comment,
            level=level,
            menu_mode=menu_mode,
            telegram_restriction=telegram_restriction,
            email=email_addr
        )
    except Exception as e:
        logging.error(f"ユーザー登録中に予期せぬエラー: {e}")
        return False


def delete_user(dbname, user_id_to_delete):
    """ユーザーを削除する。シスオペや場合によってはゲストのフィルタリングはすでに行われている必要があります。"""
    sql = "DELETE FROM users WHERE id=?"
    try:
        if sqlite_execute_query(dbname, sql, (user_id_to_delete,)):
            logging.info(f"ユーザーID {user_id_to_delete} を削除しました。")
            return True
        else:
            logging.error(f"ユーザID {user_id_to_delete} の削除中にDBエラー")
            return False
    except Exception as e:
        logging.error(f"ユーザID {user_id_to_delete} の削除中にDBエラー: {e}")
        return False


def update_user_email(dbname, user_id, new_email):
    """ユーザーのメールアドレスを更新"""
    try:
        sql = "UPDATE users SET email=? WHERE id=?"
        if sqlite_execute_query(dbname, sql, (new_email, user_id)):
            logging.info(f"ユーザID {user_id} のメールアドレスを更新しました。")
            return True
        return False
    except Exception as e:
        logging.error(f"メールアドレス更新中にDBエラー (UserID: {user_id}): {e}")
        return False


def update_user_level(dbname, user_id, new_level):
    """ユーザーのレベルを更新"""
    try:
        database.update_record('users', {'level': new_level}, {'id': user_id})
        logging.info(f"ユーザーID {user_id} のレベルを {new_level} に更新しました。")
        return True
    except Exception as e:
        logging.error(f"レベル更新中に予期せぬエラー (UserID: {user_id}): {e}")
        return False


def get_board_by_shortcut_id(dbname, shortcut_id):
    """指定されたショートカットIDの掲示板情報をDBから取得"""
    sql = "SELECT id, shortcut_id, name, description, operators, default_permission, kanban_body, last_posted_at, status, read_level, write_level, board_type FROM boards WHERE shortcut_id = ?"
    results = sqlite_execute_query(dbname, sql, (shortcut_id,), fetch=True)
    return results[0] if results else None


def create_board_entry(dbname, shortcut_id, name, description, operators, default_permission, kanban_body, status, read_level=1, write_level=1, board_type="simple"):
    """新しい掲示板エントリをboardsテーブルに挿入"""
    sql = """
    INSERT INTO boards(shortcut_id, name, description, operators, default_permission, kanban_body, status, last_posted_at, read_level, write_level,board_type)
    VALUES(?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
    """
    params = (shortcut_id, name, description, operators,
              default_permission, kanban_body, status, read_level, write_level, board_type)
    return sqlite_execute_query(dbname, sql, params)


def delete_board_entry(dbname, shortcut_id):
    """指定されたショートカットIDの掲示板エントリをboardsテーブルから削除"""
    # 注意: この関数は boards テーブルのレコードのみを削除します。
    #       関連する articles や board_user_permissions のレコードは別途削除処理が必要です。
    #       CASCADE DELETE を設定していればDB側で自動削除されますが、現状のスキーマでは設定されていません。
    #       ひとまず、boards テーブルからの削除のみとします。
    sql = "DELETE FROM boards WHERE shortcut_id=?"
    return sqlite_execute_query(dbname, sql, (shortcut_id,))


def get_next_article_number(dbname, board_id_pk, conn=None):
    sql = "SELECT COALESCE(MAX(article_number), 0) + 1 FROM articles WHERE board_id=?"
    results = sqlite_execute_query(
        dbname, sql, (board_id_pk,), fetch=True, conn=conn)
    if results and results[0] is not None:
        return results[0][0]
    return 1  # エラー、または記事がないなら1から


def update_board_last_posted_at(dbname, board_id_pk, timestamp=None, conn=None):
    # boardsテーブルのlast_posted_atを更新
    if timestamp is None:
        timestamp = int(time.time())
    sql = "UPDATE boards SET last_posted_at=? WHERE id=?"
    return sqlite_execute_query(dbname, sql, (timestamp, board_id_pk), conn=conn)


def insert_article(dbname, board_id_pk, article_number, user_id_pk, title, body, timestamp, ip_address=None, parent_article_id=None, conn=None):
    """
    articlesテーブルに新しい記事を挿入し、挿入された記事のIDを返す。
    失敗した場合はNoneを返す。
    """
    # この関数はconnを受け取るが、lastrowidを取得するためにsqlite_execute_queryは使わない
    sql = """
        INSERT INTO articles (board_id, article_number, user_id, parent_article_id, title, body, created_at, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (board_id_pk, article_number, user_id_pk, parent_article_id,
              title, body, timestamp, ip_address)

    close_conn_locally = False
    if conn is None:
        conn = sqlite3.connect(dbname)
        close_conn_locally = True

    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        article_id = cur.lastrowid
        if close_conn_locally:
            conn.commit()
        return article_id
    except sqlite3.Error as e:
        logging.error(f"記事挿入中にSQLiteエラー: {e} (SQL: {sql}, Params: {params})")
        if close_conn_locally and conn:
            conn.rollback()
        return None
    finally:
        if close_conn_locally and conn:
            conn.close()


def get_articles_by_board_id(dbname, board_id_pk, order_by="article_number ASC", include_deleted=False):
    """
    指定された掲示板IDの記事リストを取得する。
    include_deleted=True の場合、削除済み記事も含む。
    """
    sql = f"SELECT id, article_number, user_id, title, body, created_at, is_deleted, ip_address FROM articles WHERE board_id = ?"
    params = [board_id_pk]

    if not include_deleted:
        sql += " AND is_deleted = 0"

    sql += f" ORDER BY {order_by}"
    results = sqlite_execute_query(dbname, sql, tuple(params), fetch=True)
    return results if results else []


def get_article_by_board_and_number(dbname, board_id_pk, article_number, include_deleted=False):
    """指定された掲示板IDと記事番号の記事を取得する"""
    # is_deleted が 0 (または FALSE) の記事のみ取得
    sql = "SELECT id, article_number, user_id, parent_article_id, title, body, created_at, ip_address, is_deleted FROM articles WHERE board_id = ? AND article_number = ?"
    params = [board_id_pk, article_number]
    if not include_deleted:
        sql += " AND is_deleted = 0"
    results = sqlite_execute_query(
        dbname, sql, (board_id_pk, article_number), fetch=True)
    result = results[0] if results else None
    return result


def get_article_by_id(dbname, article_id_pk, include_deleted=False):
    """指定された記事ID(主キー)の記事を取得する"""
    sql = "SELECT id, article_number, user_id, parent_article_id, title, body, created_at, ip_address, is_deleted FROM articles WHERE id = ?"
    params = [article_id_pk]
    if not include_deleted:
        sql += " AND is_deleted = 0"
    results = sqlite_execute_query(dbname, sql, tuple(params), fetch=True)
    return results[0] if results else None


def toggle_article_deleted_status(dbname, article_id):
    """記事の is_deleted フラグをトグルする"""
    conn = None
    try:
        conn = sqlite3.connect(dbname)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 現在の is_deleted の値を取得
        cur.execute("SELECT is_deleted FROM articles WHERE id = ?",
                    (article_id,))
        result = cur.fetchone()

        if result is None:
            logging.warning(f"記事削除フラグのトグル失敗: 記事ID '{article_id}' が見つかりません。")
            return False

        new_status = 1 - result['is_deleted']  # 0なら1に、1なら0に
        cur.execute("UPDATE articles SET is_deleted = ? WHERE id = ?",
                    (new_status, article_id))
        conn.commit()
        logging.info(f"記事ID {article_id} の is_deleted を {new_status} に変更しました。")
        return True
    except sqlite3.Error as e:
        logging.error(f"記事削除フラグのトグル中にDBエラー (記事ID: {article_id}): {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def update_board_operators(dbname, board_id_pk, operator_user_ids_json_string):
    """
    指定された掲示板のオペレーターリストを更新する。

    Args:
        dbname (str): データベースファイル名。
        board_id_pk (int): 更新対象の掲示板の主キー(id)。
        operator_user_ids_json_string (str): オペレーターのユーザーIDリストをJSON文字列化したもの。
                                            例: '[1, 2, 3]' や '[]'

    Returns:
        bool: 更新に成功した場合はTrue、失敗した場合はFalse。
    """
    sql = "UPDATE boards SET operators=? WHERE id=?"
    try:
        params = (
            operator_user_ids_json_string if operator_user_ids_json_string is not None else '[]', board_id_pk)
        sqlite_execute_query(dbname, sql, params, fetch=False)
        logging.info(
            f"掲示板ID {board_id_pk} のオペレーターリストを更新しました: {operator_user_ids_json_string}")
        return True
    except Exception as e:
        logging.error(f"掲示板ID {board_id_pk} のオペレーターリスト更新中にDBエラー: {e}")
        return False


def update_board_kanban(dbname, board_id_pk, new_kanban_body):
    """掲示板の看板更新"""
    sql = "UPDATE boards SET kanban_body=? WHERE id=?"
    try:
        success = sqlite_execute_query(
            dbname, sql, (new_kanban_body, board_id_pk))
        if success:
            logging.info(f"掲示板ID {board_id_pk} の看板本文を更新しました")
            return True
        else:
            logging.error(
                f"掲示板ID {board_id_pk} の看板本文更新中にDBエラー（sqlite_execute_queryがFalseを返しました）")
        return success
    except Exception as e:
        logging.error(f"掲示板ID {board_id_pk} の看板本文更新中に例外が発生: {e}")
        return False


def get_board_permissions(dbname, board_id_pk):
    """指定された掲示板IDのパーミッションリスト（user_idとaccess_level）を全て取得する"""
    sql = "SELECT user_id, access_level FROM board_user_permissions WHERE board_id = ?"
    results = sqlite_execute_query(dbname, sql, (board_id_pk,), fetch=True)
    return results if results else []  # sqlite_execute_query は sqlite3.Row のリストを返す


def delete_board_permissions_by_board_id(dbname, board_id_pk):
    """指定された掲示板IDのパーミッションを全て削除する"""
    sql = "DELETE FROM board_user_permissions WHERE board_id = ?"
    return sqlite_execute_query(dbname, sql, (board_id_pk,))


def add_board_permission(dbname, board_id_pk, user_id_pk_str, access_level):
    """board_user_permissions テーブルに新しい権限エントリを追加する"""
    sql = "INSERT INTO board_user_permissions (board_id, user_id,access_level) VALUES (?, ?, ?)"
    return sqlite_execute_query(dbname, sql, (board_id_pk, user_id_pk_str, access_level))


def get_user_permission_for_board(dbname, board_id_pk, user_id_pk_str):
    """指定された掲示板とユーザのアクセスレベルを取得"""
    sql = "SELECT access_level FROM board_user_permissions WHERE board_id=? AND user_id=?"
    result = sqlite_execute_query(
        dbname, sql, (board_id_pk, user_id_pk_str), fetch=True)
    return result[0]['access_level']if result else None


def get_total_unread_mail_count(dbname, user_id_pk):
    """指定されたユーザの未読かつ未削除の受信メール総数を取得"""
    try:
        return database.get_total_unread_mail_count(user_id_pk)
    except Exception as e:
        logging.error(f"未読メール数取得中に予期せぬエラー: {e}")
        return 0


def get_total_mail_count(dbname, user_id_pk):
    """指定されたユーザの未削除の受信メール総数を取得"""
    try:
        return database.get_total_mail_count(user_id_pk)
    except Exception as e:
        logging.error(f"総メール数取得中に予期せぬエラー: {e}")
        return 0


def mark_mail_as_read(dbname, mail_id, recipient_user_id_pk):
    """指定されたメールを指定された受信者に対して既読にする"""
    try:
        return database.mark_mail_as_read(mail_id, recipient_user_id_pk)
    except Exception as e:
        logging.error(f"メール既読化処理中に予期せぬエラー: {e}")
        return False


def get_oldest_unread_mail(dbname, recipient_user_id_pk):
    """指定されたユーザの一番古い未読、かつ未削除の受信メールを1件取得"""
    sql = """
        SELECT
            m.id, m.sender_id, m.subject, m.body, m.is_read, m.sent_at, m.recipient_deleted, m.sender_ip_address,
            u.name AS sender_name
        FROM mails AS m
        LEFT JOIN users AS u ON m.sender_id = u.id
        WHERE m.recipient_id=? AND m.is_read=0 AND m.recipient_deleted=0
        ORDER BY sent_at ASC
        LIMIT 1
    """
    results = sqlite_execute_query(
        dbname, sql, (recipient_user_id_pk,), fetch=True)
    return results[0] if results else None


def get_mails_for_view(dbname, user_id_pk, view_mode):
    """
    指定されたユーザーのメール一覧を、表示に必要な情報をJOINして取得する。
    view_mode: 'inbox' または 'outbox'
    """
    if view_mode == 'inbox':
        # 受信箱: 送信者の名前をJOINで取得
        sql = """
            SELECT
                m.id, m.sender_id, m.subject, m.is_read, m.sent_at, m.recipient_deleted, m.sender_ip_address,
                u.name AS sender_name
            FROM mails AS m
            LEFT JOIN users AS u ON m.sender_id = u.id
            WHERE m.recipient_id = ?
            ORDER BY m.sent_at ASC
        """
    else:  # outbox
        # 送信箱: 宛先の名前をJOINで取得
        sql = """
            SELECT
                m.id, m.recipient_id, m.subject, m.is_read, m.sent_at, m.sender_deleted,
                u.name AS recipient_name
            FROM mails AS m
            LEFT JOIN users AS u ON m.recipient_id = u.id
            WHERE m.sender_id = ?
            ORDER BY m.sent_at ASC
        """
    return sqlite_execute_query(dbname, sql, (user_id_pk,), fetch=True)


def get_new_articles_for_board(dbname, board_id_pk, last_login_timestamp):
    """
    指定された掲示板の、指定時刻以降の未削除記事を取得する。
    last_login_timestamp が 0 または None の場合は、全ての未削除記事を取得する。
    スレッド形式の掲示板では、親記事のみを取得する。
    """
    params = [board_id_pk]
    sql = """
    SELECT a.id, a.article_number, a.user_id, a.parent_article_id, a.title, a.body, a.created_at
    FROM articles AS a
    WHERE a.board_id = ? AND a.is_deleted = 0 AND a.parent_article_id IS NULL
    """
    if last_login_timestamp and last_login_timestamp > 0:
        sql += " AND a.created_at > ?"
        params.append(last_login_timestamp)
    sql += " ORDER BY a.created_at ASC"
    return sqlite_execute_query(dbname, sql, tuple(params), fetch=True)


def get_all_boards(dbname):
    """DBに登録されている掲示板の基本情報をすべて取得する"""
    try:
        return database.get_all_boards()
    except Exception as e:
        logging.error(f"全掲示板情報取得中に予期せぬエラー: {e}")
        return []


def update_board_levels(dbname, board_id_pk, read_level, write_level):
    """掲示板の閲覧・書き込みレベルを更新する"""
    sql = "UPDATE boards SET read_level = ?, write_level = ? WHERE id = ?"
    try:
        success = sqlite_execute_query(
            dbname, sql, (read_level, write_level, board_id_pk))
        if success:
            logging.info(
                f"掲示板ID {board_id_pk} のレベルを R:{read_level}, W:{write_level} に更新しました。")
        return success
    except Exception as e:
        logging.error(f"掲示板レベル更新中にDBエラー (BoardID: {board_id_pk}): {e}")
        return False


def get_thread_root_articles_with_reply_count(dbname, board_id_pk, include_deleted=False):
    """
    指定された掲示板の親記事（スレッドルート）と、それぞれの返信数を取得する。
    """
    # is_deleted の条件をサブクエリとメインクエリの両方に入れる
    deleted_cond = "" if include_deleted else "AND is_deleted = 0"

    sql = f"""
        SELECT
            p.id,
            p.article_number,
            p.user_id,
            p.title,
            p.body,
            p.created_at,
            p.is_deleted,
            p.ip_address,
            (SELECT COUNT(*) FROM articles AS r WHERE r.parent_article_id = p.id {deleted_cond}) AS reply_count
        FROM
            articles AS p
        WHERE
            p.board_id = ?
            AND p.parent_article_id IS NULL
            {deleted_cond}
        ORDER BY
            p.created_at ASC, p.article_number ASC
    """
    params = (board_id_pk,)
    results = sqlite_execute_query(dbname, sql, params, fetch=True)
    return results if results else []


def get_replies_for_article(dbname, parent_article_id, include_deleted=False):
    """指定された親記事への返信をすべて取得する"""
    sql = "SELECT id,article_number,user_id,title,body,created_at,is_deleted,ip_address FROM articles WHERE parent_article_id=?"
    params = [parent_article_id]
    if not include_deleted:
        sql += " AND is_deleted=0"
    sql += " ORDER BY created_at ASC,article_number ASC"
    results = sqlite_execute_query(dbname, sql, tuple(params), fetch=True)
    return results if results else []


def get_sysop_user_id(dbname):
    """シスオペ(level=5)のユーザーIDを取得する。複数いる場合は最初の1人を返す。"""
    sql = "SELECT id FROM users WHERE level = 5 ORDER BY id ASC LIMIT 1"
    results = sqlite_execute_query(dbname, sql, fetch=True)
    if results:
        return results[0]['id']
    logging.warning("シスオペ(level=5)が見つかりませんでした。")
    return None


def send_system_mail(dbname, recipient_id, subject, body):
    """
    システムから指定されたユーザーへメールを送信する。
    送信者はシスオペ(level=5)とする。
    """
    sender_id = get_sysop_user_id(dbname)
    if sender_id is None:
        logging.error("システムメールの送信に失敗しました。送信者(シスオペ)が見つかりません。")
        return False

    sent_at = int(time.time())
    sql = "INSERT INTO mails (sender_id, recipient_id, subject, body, sent_at, sender_ip_address) VALUES (?, ?, ?, ?, ?, ?)"
    params = (sender_id, recipient_id, subject, body,
              sent_at, None)  # システムメールなのでIPはNone
    if sqlite_execute_query(dbname, sql, params):
        logging.info(
            f"システムメールを送信しました (To: UserID {recipient_id}, Subject: {subject})")
        return True
    else:
        logging.error(
            f"システムメールのDB保存に失敗しました (To: UserID {recipient_id})")
        return False
