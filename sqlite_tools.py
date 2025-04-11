import sqlite3


def sqlite_execute_query(dbname, sql, params=None, fetch=False):
    """汎用的なSQLiteクエリ実行関数"""
    try:
        conn = sqlite3.connect(dbname)
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
            conn.close()
        return None


def update_idbase(dbname, table, ALLOWED_COLUMNS, id, col, data):
    """ ユーザデータベースをIDで検索して更新 """
    if col not in ALLOWED_COLUMNS:
        raise ValueError(f"無許可カラムが指定されています:{col}")
    sql = f'UPDATE {table} SET {col} = ? WHERE id=?'
    sqlite_execute_query(dbname, sql, (data, id))


def fetchall_idbase(dbname, table, key, keyword):
    """ ユーザデータベースからIDで検索 """
    sql = f'SELECT * FROM {table} WHERE {key}=?'
    results = sqlite_execute_query(dbname, sql, (keyword,), fetch=True)
    return results if results else "notdata"


def read_server_pref(dbname):
    """サーバープレフを読み込む"""
    conn = sqlite3.connect(dbname)
    cur = conn.cursor()
    cur.execute('SELECT * FROM server_pref')
    results = cur.fetchall()
    conn.close()
    if results:
        return list(results[0])
    else:
        retresults = "notdata"  # 該当がない場合
        print("該当なし")


def save_telegram(dbname, sender_name, recipient_name, message, current_timestamp):
    """電報をデータベースに保存"""
    conn = sqlite3.connect(dbname)
    cur = conn.cursor()
    cur.execute("INSERT INTO telegram(sender_name, recipient_name, message, timestamp) VALUES(?,?,?,?)",
                (sender_name, recipient_name, message, current_timestamp))
    conn.commit()
    conn.close()


def load_telegram(dbname, username):
    """usernameに対応する電報をデータベースから取得し、取得後に取得分を削除、電報がなければNoneを返す"""
    conn = sqlite3.connect(dbname)
    cur = conn.cursor()
    cur.execute("SELECT * FROM telegram WHERE sender_name=?", (username,))
    results = cur.fetchall()
    if results:
        cur.execute("DELETE FROM telegram WHERE sender_name=?", (username,))
        conn.commit()
        return results
    else:
        return None
    conn.close()
