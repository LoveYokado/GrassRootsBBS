import sqlite3
import time


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
    try:
        # id,name,password,registdate,level,lastlogin,lastlogout,comment,mail
        cur.execute(
            'CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,name STRING,password TEXT,registdate INTEGER,level INT,lastlogin INTEGER,lastlogout INTEGER,comment STRING,mail STRING)'
        )
        sysopname = input('Input Sysop name: ')
        sysoppass = input('Input Sysop password: ')
        registdate = int(time.time())

        # シスオペ登録
        cur.execute("INSERT INTO users(name,password,level,registdate,lastlogin,lastlogout,comment,mail) values(?,?,?,?,?,?,?,?);",
                    (sysopname, sysoppass, 5, registdate, 0, 0, 'Sysop', 'sysop@sysop.com'),)

        # ゲスト登録
        cur.execute(
            "INSERT INTO users(name,password,level,registdate,lastlogin,lastlogout,comment,mail) values(?,?,?,?,?,?,?,?);",
            ("GUEST", "GUEST", 1, 1, 0, 0, 'Guest', 'guest@guest.com'),)
        cur.execute("SELECT * FROM users;")
        users = cur.fetchall()
        for user in users:
            print(user)

        # 各メニューのユーザレベルごとの有効、ゲストアクセスの設定
        cur.execute(
            'CREATE TABLE server_pref(bbs INTEGER,chat INTEGER,mail INTEGER,telegram INTEGER,userpref INTEGER,who INTEGER)'
        )
        cur.execute(
            "INSERT INTO server_pref(bbs,chat,mail,telegram,userpref,who) values(0,1,1,1,1,1);")
        # データベースへコミット
        conn.commit()
        # Query and display the contents of the "users" table
        cur.execute("SELECT * FROM server_pref;")
        serverprefs = cur.fetchall()
        for server_pref in serverprefs:
            print(server_pref)
    except sqlite3.Error as e:
        print(f"データベースエラー: {e}")
        conn.rollback()

    finally:
        cur.close()
        conn.close()
