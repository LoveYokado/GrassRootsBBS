import sqlite3
import time
import hashlib
import os  # os.path を使うためにインポート
import bbsmenu
import sqlite_tools


def txt_reads(filename):
    """ ./text/ の複数行のテキストファイルを読むだけ。"""
    # ファイルパスを安全に結合
    filepath = os.path.join('text', filename)
    try:
        # with 文を使ってファイルを確実に閉じる
        with open(filepath, 'r', encoding='UTF-8', newline='\n') as f:
            data = f.readlines()
        return data
    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません - {filepath}")
        return []  # 空のリストを返すなど、エラー処理を追加


def txt_read(filename):
    """./text/ の一行のテキストファイルを読むだけ。"""
    # ファイルパスを安全に結合
    filepath = os.path.join('text', filename)
    try:
        # with 文を使ってファイルを確実に閉じる
        with open(filepath, 'r', encoding='UTF-8', newline='\n') as f:
            data = f.read()
        return data
    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません - {filepath}")
        return ""  # 空文字列を返すなど、エラー処理を追加


def hash_password(password):
    """ハッシュ化したパスワードを返す"""
    salt = os.urandom(16)
    hashed_password = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        100000  # ストレッチング回数
    )
    return salt.hex(), hashed_password.hex()


def make_sysop_and_database(dbname):
    """データベースと初期テーブル、Sysop/Guestユーザーを作成する"""
    conn = None  # finally で確実に close するため
    cur = None  # finally で確実に close するため
    try:
        conn = sqlite3.connect(dbname)
        cur = conn.cursor()

        # --- users テーブル作成 ---
        print("Creating users table...")
        # id,name,password,registdate,level,lastlogin,lastlogout,comment,mail
        cur.execute(
            '''CREATE TABLE users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                salt TEXT NOT NULL,
                registdate INTEGER,
                level INTEGER DEFAULT 1,
                lastlogin INTEGER,
                lastlogout INTEGER,
                comment TEXT,
                mail TEXT
            )'''
        )
        print("users table created.")

        # Sysop 情報入力
        while True:
            sysopname = input('Input Sysop name: ')
            if sysopname:  # 空入力を防ぐ
                break
            print("Sysop名は必須です。")
        while True:
            sysoppass = input('Input Sysop password: ')
            if sysoppass:  # 空入力を防ぐ
                break
            print("Sysopパスワードは必須です。")

        registdate = int(time.time())

        sysop_salt, sysop_hashed_pass = hash_password(sysoppass)

        # シスオペ登録 (saltとハッシュ化パスワード保存)
        print("Registering Sysop...")
        cur.execute(
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, mail) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sysopname, sysop_hashed_pass, sysop_salt, 5, registdate, 0, 0,
             'Sysop', f'{sysopname}@example.com')  # メールアドレスも動的に
        )
        print("Sysop registered.")

        # ゲスト登録 (saltとハッシュ化パスワード保存)
        guest_salt, guest_hashed_pass = hash_password('GUEST')
        print("Registering Guest...")
        cur.execute(
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, mail) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("GUEST", guest_hashed_pass, guest_salt, 1, registdate, 0, 0,
             'Guest', 'guest@example.com')  # 登録日も設定
        )
        print("Guest registered.")

        # --- server_pref テーブル作成 ---
        print("Creating server_pref table...")
        cur.execute(
            '''CREATE TABLE server_pref(
                bbs INTEGER DEFAULT 0,
                chat INTEGER DEFAULT 1,
                mail INTEGER DEFAULT 1,
                telegram INTEGER DEFAULT 1,
                userpref INTEGER DEFAULT 1,
                who INTEGER DEFAULT 1
            )'''
        )
        # 初期設定を挿入 (プレースホルダーを使用)
        cur.execute(
            "INSERT INTO server_pref(bbs, chat, mail, telegram, userpref, who) VALUES(?, ?, ?, ?, ?, ?)",
            (0, 1, 1, 1, 1, 1)
        )
        print("server_pref table created and initialized.")

        # --- telegram テーブル作成 (id カラムあり) ---
        print("Creating telegram table...")
        cur.execute(
            '''CREATE TABLE telegram(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_name TEXT NOT NULL,
                recipient_name TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            )'''
        )
        print("telegram table created.")

        # データベースへコミット
        conn.commit()
        print("Database and tables created successfully.")

        # 作成されたテーブルの内容を表示 (確認用)
        print("\n--- Users Table Contents ---")
        cur.execute("SELECT * FROM users;")
        users = cur.fetchall()
        for user in users:
            print(user)

        print("\n--- Server Pref Table Contents ---")
        cur.execute("SELECT * FROM server_pref;")
        serverprefs = cur.fetchall()
        for server_pref in serverprefs:
            print(server_pref)

    except sqlite3.Error as e:
        print(f"データベースエラーが発生しました: {e}")
        if conn:
            conn.rollback()  # エラー時はロールバック

    finally:
        # カーソルと接続を確実に閉じる
        if cur:
            cur.close()
        if conn:
            conn.close()
        print("Database connection closed.")


def prompt_handler(chan, dbname, login_id):
    """ 定型実行のまとめ """
    bbsmenu.telegram_recieve(chan, dbname, login_id)
    server_prefs = sqlite_tools.read_server_pref(dbname)
    return server_prefs
