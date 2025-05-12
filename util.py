import sqlite3
import time
import hashlib
import os  # os.path を使うためにインポート
import bbsmenu
import sqlite_tools
import logging


def show_textsfile(chan, filename):
    """テキストファイルを表示する"""
    try:
        sendm = txt_reads(filename)
        for s in sendm:
            chan.send(s + '\r')
    except FileNotFoundError:
        logging.warning(f"テキストファイル '{filename}' が見つかりません。")
    except Exception as e:
        logging.error(f"テキストファイル表示エラー: {e}")


def show_textfile(chan, filename):
    try:
        sendm = txt_read(filename)
        chan.send(sendm)
    except FileNotFoundError:
        logging.warning(
            f"テキストファイル '{filename}' が見つかりません。")
    except Exception as e:
        logging.error(f"テキストファイル表示エラー: {e}")


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
                mail TEXT,
                auth_method TEXT DEFAULT'passsword_only' NOT NULL CHECK(auth_method IN ('key_only','password_only','webapp_only','both'))
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
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, mail,auth_method) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sysopname, sysop_hashed_pass, sysop_salt, 5, registdate, 0, 0,
             'Sysop', f'{sysopname}@example.com', 'both')  # メールアドレスも動的に、認証は両方
        )
        print("Sysop registered.")

        # ゲスト登録 (saltとハッシュ化パスワード保存)
        guest_salt, guest_hashed_pass = hash_password('GUEST')
        print("Registering Guest...")
        cur.execute(
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, mail, auth_method) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("GUEST", guest_hashed_pass, guest_salt, 1, registdate, 0, 0,
             'Guest', 'guest@example.com', 'webapp_only')  # 登録日も設定、ゲストはWebAPPのみ
        )
        print("Guest registered.")

        # テスト用SSH鍵認証専用ユーザー登録 (keyuser)
        key_user_name = "keyuser"
        key_user_dummy_pass = ""  # 鍵認証ユーザーはパスワードを使わない想定
        key_user_salt, key_user_hashed_pass = hash_password(
            key_user_dummy_pass)
        print(f"Registering SSH Key User: {key_user_name}...")
        cur.execute(
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, mail, auth_method) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key_user_name, key_user_hashed_pass, key_user_salt, 2, registdate, 0, 0,
             # keyuserは鍵のみ
             'SSH Key User', f'{key_user_name}@example.com', 'key_only')
        )
        print(f"SSH Key TestUser '{key_user_name}' registered.")

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

        # メールボックステーブル作成

        print("Creating mails table...")
        cur.execute(
            '''CREATE TABLE mails(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                sent_at INTEGER NOT NULL,
                sender_deleted INTEGER DEFAULT 0,
                recipient_deleted INTEGER DEFAULT 0
            )'''
        )
        print("mail table created and initialized.")

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
        print("Telegram table created and initialized.")

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
