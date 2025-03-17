import sqlite3

dbname = 'test.db'
conn = sqlite3.connect(dbname)
cur = conn.cursor()

# "name"にユーザ名を入れる
cur.execute('INSERT INTO persons(name) values("Taro")')
cur.execute('INSERT INTO persons(name) values("Hanako")')
cur.execute('INSERT INTO persons(name) values("Hiroki")')

conn.commit()

cur.close()
conn.close()
