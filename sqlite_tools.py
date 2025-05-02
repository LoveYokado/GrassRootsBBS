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


def toggle_mail_delete_status_generic(dbname, mail_id, user_id, mode):
    """
    メールの削除フラグをトグルする汎用関数。

    Args:
        dbname (str): データベース名
        mail_id (int): メールID
        user_id (int): ユーザーID
        mode (str): 'sender' または 'recipient'

    Returns:
        tuple: (成功/失敗(bool), 新しいステータス(int))
               失敗時は (False, 0) を返す。
    """
    if mode == 'sender':
        user_id_colmn = 'sender_id'
        delete_flag_colmn = 'sender_deleted'
    elif mode == 'recipient':
        user_id_colmn = 'recipient_id'
        delete_flag_colmn = 'recipient_deleted'
    else:
        logging.error(f"無効なモードが指定されました: {mode}")
        return False, 0

    conn = None
    try:
        conn = sqlite3.connect(dbname)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 現在の状態を取得
        sql_select = f"SELECT {delete_flag_colmn} FROM mails WHERE id=? AND {user_id_colmn}=?"
        cur.execute(sql_select, (mail_id, user_id))
        result = cur.fetchone()

        if result is None:
            logging.warning(
                f"メール削除トグルに失敗({mode})しました。メールなしか権限なしです)(MailID: {mail_id}, UserID: {user_id})")
            return False, 0

        current_status = result[delete_flag_colmn]
        new_status = 1-current_status  # ステータス反転

        # ステータスを更新
        sql_update = f"UPDATE mails SET {delete_flag_colmn}=? WHERE id=? AND {user_id_colmn}=?"
        cur.execute(sql_update, (new_status, mail_id, user_id))
        conn.commit()

        logging.info(
            f"メール(ID:{mail_id})の{delete_flag_colmn}を{new_status}に変更しました(User:{user_id},Mode:{mode})")
        return True, new_status
    except sqlite3.Error as e:
        logging.error(
            f"メール削除トグル処理{mode}中にDBエラー (MailID: {mail_id}, UserID: {user_id}): {e}")
    except Exception as e:
        logging.error(
            f"メール削除トグル処理{mode}中に予期せぬエラー (MailID: {mail_id}, UserID: {user_id}): {e}")
    finally:
        if conn:
            conn.rollback()
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
            conn.close()
            return results
        else:
            conn.commit()
            conn.close()
            return None
    except sqlite3.Error as e:
        print(f"SQLiteエラー: {e}")
        if conn:
            conn.rollback()  # 書き込みエラーの場合ロールバック
            conn.close()
        return None


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
    ALLOWED_KEYS = ['id', 'name', ...]
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
        print("警告: server_pref テーブルが見つからないか、空です。")
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
        print(f"警告: 電報データは取得できましたが、IDリストが空です。受信者: {recipient_name}")

    # 取得した電報データを返す (id を含んだまま)
    return results
