import sqlite3
import logging


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
            return None
    except sqlite3.Error as e:
        logging.error(f"SQLiteエラー: {e}")
        if conn:
            conn.rollback()  # 書き込みエラーの場合ロールバック
        return None
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
    ALLOWED_TABLES = ['users', 'mails']
    ALLOWED_KEYS = ['id', 'name', 'sender_id', 'recipient_id']
    if table not in ALLOWED_TABLES:
        raise ValueError(f"許可されていないテーブルです: {table}")
    if key not in ALLOWED_KEYS:
        raise ValueError(f"許可されていない検索キーです: {key}")
    sql = f'SELECT * FROM {table} WHERE {key}=?'
    results = sqlite_execute_query(dbname, sql, (keyword,), fetch=True)
    return results if results else []


def read_server_pref(dbname):
    """サーバープレフを読み込む (sqlite_execute_query を使用)"""
    sql = 'SELECT * FROM server_pref'
    # server_pref は通常1行しかないので fetchone() でも良いかもしれない
    results = sqlite_execute_query(dbname, sql, fetch=True)
    if results:
        # results はリストのリスト [(val1, val2, ...)] なので results[0] を返す
        return list(results[0])
    else:
        # テーブルが存在しないか空の場合
        logging.warning("警告: server_pref テーブルが見つからないか、空です。")
        # デフォルト値を返すか、None を返すなどエラー処理を明確にする
        return [0, 1, 1, 1, 1, 1]  # 例: デフォルト値を返す


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
        logging.error(f"無効なメニューモードが指定されました: {new_mode}")
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
