import sqlite3

dbname = 'test.db'
conn = sqlite3.connect(dbname)

# sqliteを操作するカーソルオブジェクト作成
cur = conn.cursor()

# personsというテーブルを作成
# 大文字はSQL文。小文字でも良い。
cur.execute(
    'CREATE TABLE persons(id INTEGER PRIMARY KEY AUTOINCREMENT,name STRING)'
)

# データベースへコミット。これで反映される。
conn.commit()
conn.close()
