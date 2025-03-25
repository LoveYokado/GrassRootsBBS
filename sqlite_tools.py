import sqlite3


def sqlite_update_idbase(dbname, table, ALLOWED_COLUMNS, id, col, data):
    if col not in ALLOWED_COLUMNS:
        raise ValueError(f"無許可カラムが指定されています:{col}")
    """sqliteをアップデートします。"""
    conn = sqlite3.connect(dbname)
    sql = f'UPDATE {table} SET {col} = ? WHERE id=?'
    conn.execute(sql, (data, id))
    conn.commit()
    conn.close()


def sqlite_fetchall_idbase(dbname, table, key, keyword):
    conn = sqlite3.connect(dbname)
    cur = conn.cursor()
    sql = f'SELECT * FROM {table} WHERE {key}=?'
    cur.execute(sql, (keyword,))
    results = cur.fetchall()
    if results:
        retresults = list(results)
    else:
        retresults = "notdata"  # 該当がない場合
        print("該当なし")
    conn.close()
    return retresults
