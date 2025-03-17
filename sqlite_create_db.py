import sqlite3

# test.dbに接続、なければ作成
dbname = 'test.db'
conn = sqlite3.connect(dbname)

# test.dbを閉じる
conn.close()
