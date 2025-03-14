import sqlite3
from datetime import datetime


def quit(dbname, userid):
    """ログオフ処理、最終ログイン日時を記録するためにユーザIDが必須です。"""

    # 日時を取得してISO8601に変換
    dtime = datetime.now()
    dtime_str = dtime.strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(dbname)
    sql = 'UPDATE users SET lastlogin = ? WHERE id=?'
    data = (dtime_str, userid)
    conn.execute(sql, data)
    conn.commit()
    conn.close()
