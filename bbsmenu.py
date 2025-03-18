import sqlite3
import time

ALLOWED_COLUMNS = ['name', 'password', 'registdate',
                   'level', 'lastlogin', 'lastlogout', 'comment', 'mail']


def userupdate(dbname, userid, col, data):
    if col not in ALLOWED_COLUMNS:
        raise ValueError(f"無許可カラムが指定されています:{col}")
    """ユーザのデータをアップデートします。"""
    conn = sqlite3.connect(dbname)
    sql = f'UPDATE users SET {col} = ? WHERE id=?'
    conn.execute(sql, (data, userid))
    conn.commit()
    conn.close()
