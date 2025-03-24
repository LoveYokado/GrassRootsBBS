import sqlite3


def txt_reads(filename):
    """ ./text/の複数行のテキストファイルを読むだけ。"""
    f = open('text/' + filename, 'r', encoding='UTF-8', newline='\n')
    data = f.readlines()
    f.close()
    return data


def txt_read(filename):
    """./text/の一行のテキストファイルを読むだけ。"""
    f = open('text/' + filename, 'r', encoding='UTF-8', newline='\n')
    data = f.read()
    f.close()
    return data


def make_sysop_and_database(dbname):
    conn = sqlite3.connect(dbname)
    cur = conn.cursor()
    # id,name,password,registdate,level,lastlogin,lastlogout,comment,mail
    cur.execute(
        'CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,name STRING,password TEXT,registdate INTEGER,level INT,lastlogin INTEGER,lastlogout INTEGER,comment STRING,mail STRING)'
    )
    sysopname = input('Input Sysop name: ')
    sysoppass = input('Input Sysop password: ')
    cur.execute("INSERT INTO users(name,password,level) values(?,?,?);", (
                sysopname, sysoppass, 5))

    print(cur.fetchall())

    # 各メニューのユーザレベルごとの有効、ゲストアクセスの設定
    cur.execute(
        'CREATE TABLE server_pref(bbs INTEGER,chat INTEGER,mail INTEGER,telegram INTEGER,userpref INTEGER,who INTEGER,guest BOOLEAN)'
    )
    cur.execute("INSERT INTO server_pref(bbs,chat,mail,telegram,userpref,who,guest) values(0,1,1,1,1,1,true);")
    # データベースへコミット
    conn.commit
    # Query and display the contents of the "users" table
    cur.execute("SELECT * FROM users;")
    users = cur.fetchall()
    for user in users:
        print(user)

    cur.close()
    conn.close()
