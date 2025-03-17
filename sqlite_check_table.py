import sqlite3
dbname = 'test.db'
conn = sqlite3.connect(dbname)
cur = conn.cursor()

# terminalで実行するSQL分と同じようにexecute()に書く
cur.execute('SELECT * FROM persons')

# 中身をすべて取得するfetchall()を使ってprintする
print(cur.fetchall())

cur.close()
conn.close()
