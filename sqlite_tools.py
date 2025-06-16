import sqlite3
import logging
import time
import json


def get_user_id_from_user_name(dbname, username):
    """ユーザ名からユーザIDを取得する"""
    try:
        results = fetchall_idbase(
            dbname, 'users', 'name', username)
        if results:
            return results[0]['id']
        else:
            logging.warning(f"ユーザID取得失敗: ユーザ名 '{username}' が見つかりません。")
            return None
    except Exception as e:
        logging.error(f"ユーザID取得中にDBエラー ({username}): {e}")
        return None


def get_user_name_from_user_id(dbname, user_id):
    """ユーザIDからユーザ名を取得する"""
    try:
        results = fetchall_idbase(
            dbname, 'users', 'id', user_id)
        if results:
            return results[0]['name']
        else:
            # 送信者が削除された場合など
            return "(不明)"  # 短く変更
    except Exception as e:
        logging.error(f"ユーザ名取得中にDBエラー (ID: {user_id}): {e}")
        return "(エラー)"


def get_user_level_from_user_id(dbname, user_id):
    """ユーザIDからユーザレベルを取得する"""
    try:
        results = fetchall_idbase(  # fetchall_idbase はリストを返すので results[0] を使う
            dbname, 'users', 'id', user_id)
        if results:
            return results[0]['level']
        else:
            logging.warning(f"ユーザレベル取得失敗: ユーザID '{user_id}'が見つかりません。")
            # 送信者が削除された場合など
            return 0
    except Exception as e:
        logging.error(f"ユーザレベル取得中にDBエラー (ID: {user_id}): {e}")
        return 0


def get_user_auth_info(dbname, username):
    """
    ユーザ名から認証情報を含むユーザデータ取得。
    見つからない場合はNoneを返す。
    """
    try:
        results = fetchall_idbase(dbname, 'users', 'name', username)
        return results[0] if results else None
    except Exception as e:
        logging.error(f"認証情報取得中にエラー ({username}): {e}")
        return None


def toggle_mail_delete_status_generic(dbname, mail_id, user_id, mode_param):
    """
    メールの削除フラグをトグルする汎用関数。

    Args:
        dbname (str): データベース名
        mail_id (int): メールID
        user_id (int): ユーザーID
        mode_param (str): 'sender' または 'recipient'

    Returns:
        tuple: (成功/失敗(bool), 新しいステータス(int))
        失敗時は (False, 0) を返す。
    """

    conn = None
    mode = str(mode_param).strip()

    try:
        conn = sqlite3.connect(dbname)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # modeによってSQLを構築
        if mode == 'sender':
            sql_select = "SELECT sender_deleted FROM mails WHERE id=? AND sender_id=?"
            sql_update = "UPDATE mails SET sender_deleted=? WHERE id=? AND sender_id=?"
            current_status_colmn = 'sender_deleted'
        elif mode == 'recipient':
            sql_select = "SELECT recipient_deleted FROM mails WHERE id=? AND recipient_id=?"
            sql_update = "UPDATE mails SET recipient_deleted=? WHERE id=? AND recipient_id=?"
            current_status_colmn = 'recipient_deleted'
        else:
            logging.error(
                f"無効なモードが指定されました: original='{mode_param}',stripped='{mode}' ")
            return False, 0

        # 現在の状態を取得
        cur.execute(sql_select, (mail_id, user_id))
        result = cur.fetchone()

        if result is None:
            logging.warning(
                f"メール削除トグルに失敗({mode})しました。メールなしか権限なしです)(MailID: {mail_id}, UserID: {user_id})")
            return False, 0

        current_status = result[current_status_colmn]
        new_status = 1-current_status  # ステータス反転

        cur.execute(sql_update, (new_status, mail_id, user_id))
        conn.commit()

        logging.info(
            f"メール(ID:{mail_id})の{current_status_colmn}を{new_status}に変更しました(User:{user_id},Mode:{mode})")
        return True, new_status
    except sqlite3.Error as e:
        logging.error(
            f"メール削除トグル処理{mode}中にDBエラー (MailID: {mail_id}, UserID: {user_id}): {e}")
        if conn:
            conn.rollback()  # DBエラーの場合ロールバック
    except Exception as e:
        logging.error(
            f"メール削除トグル処理{mode}中に予期せぬエラー (MailID: {mail_id}, UserID: {user_id}): {e}")
    finally:
        if conn:
            conn.close()
    return False, 0


def sqlite_execute_query(dbname, sql, params=None, fetch=False):
    """汎用的なSQLiteクエリ実行関数"""
    conn = None  # finally で確実に close するため
    try:
        conn = sqlite3.connect(dbname)
        # Row ファクトリを設定して辞書ライクなアクセスを可能にする (任意だが推奨)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params or ())
        if fetch:
            results = cur.fetchall()
            return results
        else:
            conn.commit()
            return True
    except sqlite3.Error as e:
        logging.error(f"SQLiteエラー: {e} (SQL: {sql[:100]})")
        if conn:
            conn.rollback()  # 書き込みエラーの場合ロールバック
        return False
    finally:
        if conn:
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
                kanban_title TEXT DEFAULT '',
                kanban_body TEXT DEFAULT '',
                last_posted_at INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived', 'hidden'))
            )
        ''')
    logging.info("boards テーブルを作成または確認しました。")

    # articles テーブル
    cur.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                article_number INTEGER NOT NULL,
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
    sql = 'SELECT bbs, chat, mail, telegram, userpref, who, default_exploration_list FROM server_pref'
    # server_pref は通常1行しかないので fetchone() でも良いかも
    results = sqlite_execute_query(dbname, sql, fetch=True)
    if results:
        # results はリストのリスト [(val1, val2, ...)] なので results[0] を返す
        return list(results[0])
    else:
        # テーブルが存在しないか空の場合(念の為)
        logging.warning("警告: server_pref テーブルが見つからないか、空です。")
        # デフォルト値を返すか、None を返すなどエラー処理を明確にする
        return [0, 1, 1, 1, 1, 1, ""]  # 例: デフォルト値を返す


def save_telegram(dbname, sender_name, recipient_name, message, current_timestamp):
    """電報をデータベースに保存 (sqlite_execute_query を使用)"""
    sql = "INSERT INTO telegram(sender_name, recipient_name, message, timestamp) VALUES(?,?,?,?)"
    sqlite_execute_query(
        dbname, sql, (sender_name, recipient_name, message, current_timestamp))


def load_and_delete_telegrams(dbname, recipient_name):
    """
    指定された受信者の電報を取得し、取得した電報を削除する。
    電報がなければ None を返す。
    """
    # 1. 受信者宛の電報を取得 (id も含める)
    # カラム順: id, sender_name, recipient_name, message, timestamp
    sql_select = "SELECT id, sender_name, recipient_name, message, timestamp FROM telegram WHERE recipient_name=? ORDER BY timestamp ASC"
    results = sqlite_execute_query(
        dbname, sql_select, (recipient_name,), fetch=True)

    if not results:
        return None  # 電報がない場合は None を返す

    # 2. 取得した電報の ID リストを作成
    telegram_ids = [row[0] for row in results]

    # 3. 取得した電報を ID で削除
    if telegram_ids:  # IDリストが空でないことを確認
        # プレースホルダーを ID の数だけ作成: (?, ?, ...)
        placeholders = ', '.join('?' * len(telegram_ids))
        sql_delete = f"DELETE FROM telegram WHERE id IN ({placeholders})"
        # params は ID のタプル
        sqlite_execute_query(dbname, sql_delete, tuple(telegram_ids))
    else:
        # 通常ここには来ないはずだが、念のためログ
        logging.warning(f"警告: 電報データは取得できましたが、IDリストが空です。受信者: {recipient_name}")

    # 取得した電報データを返す (id を含んだまま)
    return results


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

    try:
        # update_idbase を使う場合 (usersテーブルの許可カラムリストに 'menu_mode' を追加する必要あり)
        # ALLOWED_COLUMNS_USERS = ['lastlogout', 'lastlogin', 'password', 'salt', 'comment', 'mail', 'level', 'auth_method', 'menu_mode']
        # update_idbase(dbname, 'users', ALLOWED_COLUMNS_USERS, user_id, 'menu_mode', new_mode)

        # sqlite_execute_query を直接使う場合
        sql = "UPDATE users SET menu_mode = ? WHERE id = ?"
        sqlite_execute_query(dbname, sql, (new_mode, user_id))
        logging.info(f"ユーザーID {user_id} のメニューモードを {new_mode} に更新しました。")
        return True
    except Exception as e:
        logging.error(
            f"メニューモード更新中にエラー (UserID: {user_id}, Mode: {new_mode}): {e}")
        return False


def update_user_password_and_salt(dbname, login_id, new_hashed_password, new_salt_hex):
    """ユーザのパスハッシュとソルトの更新"""
    try:
        user_id = get_user_id_from_user_name(dbname, login_id)
        if user_id is None:
            logging.error(f"パスワード更新失敗、ユーザが見つかりません: {login_id}")
            return False
        # usersテーブルの更新
        sql = "UPDATE users SET password = ?, salt = ? WHERE id = ?"
        sqlite_execute_query(
            dbname, sql, (new_hashed_password, new_salt_hex, user_id))
        logging.info(f"ユーザ '{login_id}' (ID: {user_id}) のパスワードとソルトを更新しました。")
        return True
    except Exception as e:
        logging.error(f"パスワードとソルトの更新中にDBエラー (ユーザ: {login_id}): {e}")
        return False


def update_user_profile_comment(dbname, user_id, new_comment):
    """ユーザーのプロフィールコメントを更新"""
    try:
        # usersテーブルの更新
        sql = "UPDATE users SET comment = ? WHERE id = ?"
        sqlite_execute_query(dbname, sql, (new_comment, user_id))
        logging.info(f"ユーザID {user_id} のプロフィールコメントを更新しました。")
        return True
    except Exception as e:
        logging.error(f"プロフィールコメント更新中にDBエラー (UserID: {user_id}): {e}")
        return False


def update_user_telegram_restriction(dbname, user_id, restriction_level):
    """ユーザの電報受信制限を更新"""
    try:
        sql = "UPDATE users SET telegram_restriction=? WHERE id=?"
        sqlite_execute_query(dbname, sql, (restriction_level, user_id))
        logging.info(f"ユーザID {user_id} の電報受信制限を{restriction_level}に変更しました。")
        return True
    except Exception as e:
        logging.error(f"電報受信制限更新中にDBエラー (UserID: {user_id}): {e}")
        return False


def update_user_blacklist(dbname, user_id, blacklist_str):
    """ユーザのブラックリストを更新"""
    try:
        sql = "UPDATE users SET blacklist=? WHERE id=?"
        sqlite_execute_query(dbname, sql, (blacklist_str, user_id))
        logging.info(f"ユーザID {user_id} のブラックリストを更新しました。")
        return True
    except Exception as e:
        logging.error(f"ブラックリスト更新中にDBエラー (UserID: {user_id}): {e}")
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
        sql = "UPDATE server_pref SET default_exploration_list=?"
        sqlite_execute_query(dbname, sql, (exploration_list_str,))
        logging.info(f"サーバーのデフォルト探索リストを更新しました: {exploration_list_str[:50]}...")
        return True
    except Exception as e:
        logging.error(f"サーバーのデフォルト探索リスト更新中にDBエラー: {e}")
        return False


def register_user(dbname, username, hashed_password, salt, comment, level=0,
                  auth_method='password_only', menu_mode='1', telegram_restriction=0):
    """新しいユーザーをデータベースに登録する"""
    registdate = int(time.time())
    # Ensure consistent mail format, can be changed later by user or sysop
    email_addr = f'{username.lower()}@example.com'
    # Default values for other fields
    lastlogin = 0
    lastlogout = 0
    blacklist = ''
    exploration_list = ''

    sql_insert_user = """
        INSERT INTO users (
            name, password, salt, registdate, level, lastlogin, lastlogout,
            comment, email, auth_method, menu_mode, telegram_restriction,
            blacklist, exploration_list
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        username, hashed_password, salt, registdate, level, lastlogin, lastlogout,
        comment, email_addr, auth_method, menu_mode, telegram_restriction,
        blacklist, exploration_list
    )

    if sqlite_execute_query(dbname, sql_insert_user, params):
        logging.info(f"新規ユーザー '{username}' を登録しました。")
        return True
    else:
        # The error is already logged by sqlite_execute_query.
        logging.error(
            f"ユーザー登録失敗: SQL実行エラーが発生しました (ユーザー: {username})。詳細は先行ログを確認してください。")
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
    sql = "UPDATE users SET level=? WHERE id=?"
    try:
        success = sqlite_execute_query(dbname, sql, (new_level, user_id))
        return success
    except Exception as e:
        logging.error(f"レベル更新中にDBエラー (UserID: {user_id}): {e}")
        return False


def get_board_by_shortcut_id(dbname, shortcut_id):
    """指定されたショートカットIDの掲示板情報をDBから取得"""
    sql = "SELECT id, shortcut_id, name, description, operators, default_permission, kanban_title, kanban_body, last_posted_at, status FROM boards WHERE shortcut_id = ?"
    results = sqlite_execute_query(dbname, sql, (shortcut_id,), fetch=True)
    return results[0] if results else None


def create_board_entry(dbname, shortcut_id, name, description, operators, default_permission, kanban_title, kanban_body, status):
    """新しい掲示板エントリをboardsテーブルに挿入"""
    sql = """
    INSERT INTO boards(shortcut_id, name, description, operators, default_permission, kanban_title, kanban_body, status, last_posted_at)
    VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0)
    """
    params = (shortcut_id, name, description, operators,
              default_permission, kanban_title, kanban_body, status)
    return sqlite_execute_query(dbname, sql, params)


def delete_board_entry(dbname, shortcut_id):
    """指定されたショートカットIDの掲示板エントリをboardsテーブルから削除"""
    # 注意: この関数は boards テーブルのレコードのみを削除します。
    #       関連する articles や board_user_permissions のレコードは別途削除処理が必要です。
    #       CASCADE DELETE を設定していればDB側で自動削除されますが、現状のスキーマでは設定されていません。
    #       ひとまず、boards テーブルからの削除のみとします。
    sql = "DELETE FROM boards WHERE shortcut_id=?"
    return sqlite_execute_query(dbname, sql, (shortcut_id,))


def get_all_boards(dbname):
    sql = "SELECT id, shortcut_id, operators, default_permission, category_id, display_order FROM boards WHERE category_id=?"
    return sqlite_execute_query(dbname, sql, (current_menu_mode,), fetch=True)


def get_next_article_number(dbname, board_id_pk):
    sql = "SELECT COALESCE(MAX(article_number), 0) + 1 FROM articles WHERE board_id=?"
    results = sqlite_execute_query(
        dbname, sql, (board_id_pk,), fetch=True)
    if results and results[0] is not None:
        return results[0][0]
    return 1  # エラー、または記事がないなら1から


def update_board_last_posted_at(dbname, board_id_pk, timestamp=None):
    # boardsテーブルのlast_posted_atを更新
    if timestamp is None:
        timestamp = int(time.time())
    sql = "UPDATE boards SET last_posted_at=? WHERE id=?"
    return sqlite_execute_query(dbname, sql, (timestamp, board_id_pk))


def insert_article(dbname, board_id_pk, article_number, user_id_pk, title, body, timestamp, ip_address=None):
    """
    articlesテーブルに新しい記事を挿入し、挿入された記事のIDを返す。
    失敗した場合はNoneを返す。
    """
    sql = """
        INSERT INTO articles (board_id, article_number, user_id, title, body, created_at, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    params = (board_id_pk, article_number, user_id_pk,
              title, body, timestamp, ip_address)
    conn = None
    try:
        conn = sqlite3.connect(dbname)
        cur = conn.cursor()
        cur.execute(sql, params)
        article_id = cur.lastrowid
        conn.commit()
        return article_id
    except sqlite3.Error as e:
        logging.error(f"記事挿入中にSQLiteエラー: {e} (SQL: {sql}, Params: {params})")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()


def get_articles_by_board_id(dbname, board_id_pk, order_by="article_number ASC", include_deleted=False):
    """
    指定された掲示板IDの記事リストを取得する。
    include_deleted=True の場合、削除済み記事も含む。
    """
    sql = f"SELECT id, article_number, user_id, title, body, created_at, is_deleted FROM articles WHERE board_id = ?"
    params = [board_id_pk]

    if not include_deleted:
        sql += " AND is_deleted = 0"

    sql += f" ORDER BY {order_by}"
    results = sqlite_execute_query(dbname, sql, tuple(params), fetch=True)
    return results if results else []


def get_article_by_board_and_number(dbname, board_id_pk, article_number, include_deleted=False):
    """指定された掲示板IDと記事番号の記事を取得する"""
    # is_deleted が 0 (または FALSE) の記事のみ取得
    sql = "SELECT id, article_number, user_id, title, body, created_at, ip_address FROM articles WHERE board_id = ? AND article_number = ? AND is_deleted = 0"
    # sqlite_execute_query は fetchone=True で単一の sqlite3.Row オブジェクトを返す想定
    # もし sqlite_execute_query が fetchone をサポートしていない場合は、fetch=True で取得し、結果リストの最初の要素を使う
    # ここでは fetchone があると仮定
    # result = sqlite_execute_query(dbname, sql, (board_id_pk, article_number), fetchone=True)
    sql = "SELECT id, article_number, user_id, title, body, created_at, ip_address, is_deleted FROM articles WHERE board_id = ? AND article_number = ?"
    params = [board_id_pk, article_number]
    if not include_deleted:
        sql += " AND is_deleted = 0"
    results = sqlite_execute_query(
        dbname, sql, (board_id_pk, article_number), fetch=True)
    result = results[0] if results else None
    return result


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


def update_board_kanban(dbname, board_id_pk, new_kanban_title, new_kanban_body):
    """掲示板の看板タイトルと本文更新"""
    sql = "UPDATE boards SET kanban_title=?,kanban_body=? WHERE id=?"
    try:
        params = sqlite_execute_query(
            dbname, sql, (new_kanban_title, new_kanban_body, board_id_pk))
        if params:
            logging.info(f"掲示板ID {board_id_pk} の看板タイトルと本文を更新しました")
            return True
        else:
            logging.error(
                f"掲示板ID {board_id_pk} の看板タイトルと本文更新中にDBエラー")
        return params
    except Exception as e:
        logging.error(f"掲示板ID {board_id_pk} の看板タイトルと本文更新中にDBエラー: {e}")
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
    sql = "SELECT COUNT(*) FROM mails WHERE recipient_id=? AND is_read=0 AND recipient_deleted=0"
    results = sqlite_execute_query(dbname, sql, (user_id_pk,), fetch=True)
    return results[0][0] if results and results[0] else 0


def get_total_mail_count(dbname, user_id_pk):
    """指定されたユーザの未削除の受信メール総数を取得"""
    sql = "SELECT COUNT(*) FROM mails WHERE recipient_id=? AND recipient_deleted=0"
    results = sqlite_execute_query(dbname, sql, (user_id_pk,), fetch=True)
    return results[0][0] if results and results[0] else 0


def mark_mail_as_read(dbname, mail_id, recipient_user_id_pk):
    """指定されたメールを指定された受信者に対して既読にする"""
    sql = "UPDATE mails SET is_read = 1 WHERE id = ? AND recipient_id = ?"
    conn = None
    try:
        conn = sqlite3.connect(dbname)
        conn.row_factory = sqlite3.Row  # 他の関数と一貫性を持たせる
        cur = conn.cursor()
        cur.execute(sql, (mail_id, recipient_user_id_pk))
        updated_rows = cur.rowcount  # 更新された行数を取得
        conn.commit()

        if updated_rows > 0:
            logging.info(
                f"メールID {mail_id} をユーザID {recipient_user_id_pk} に対して既読にマークしました ({updated_rows}行更新)。")
            return True
        else:
            # 対象のメールが見つからない、または既に既読の場合
            logging.debug(  # ログレベルをdebugに変更
                f"メールID {mail_id} (ユーザID: {recipient_user_id_pk}) は既に既読、または存在しません。既読化処理はスキップされました。")
            return False
    except sqlite3.Error as e:  # より具体的な例外をキャッチ
        logging.error(
            f"メール既読化中にDBエラー (MailID: {mail_id}, UserID: {recipient_user_id_pk}): {e}")
        if conn:
            conn.rollback()  # エラー時はロールバック
        return False
    finally:
        if conn:
            conn.close()


def get_oldest_unread_mail(dbname, recipient_user_id_pk):
    """指定されたユーザの一番古い未読、かつ未削除の受信メールを1件取得"""
    sql = """
        SELECT id, sender_id,subject,body,is_read,sent_at,recipient_deleted
        FROM mails
        WHERE recipient_id=? AND is_read=0 AND recipient_deleted=0
        ORDER BY sent_at ASC
        LIMIT 1
    """
    results = sqlite_execute_query(
        dbname, sql, (recipient_user_id_pk,), fetch=True)
    return results[0] if results else None
