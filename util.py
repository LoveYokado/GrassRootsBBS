import logging
import toml
import socket
import paramiko
import os  # os.path を使うためにインポート
import hashlib
import time
import sqlite3
import yaml

import bbsmenu
import sqlite_tools

# テキストデータのキャッシュ用グローバル変数
_master_text_data_cache = None

# 設定辞書(グローバル)
app_config = {}

# SSH_KEY_DIR = '.sshkey'
# AUTH_KEYS_FILE = os.path.join(SSH_KEY_DIR, 'authorized_keys.pub')
# PBKDF2_ROUNDS = 100000  # パスワードハッシュのストレチッング数


def load_app_config_from_path(config_file_path):
    """
    指定されたパスから設定を読み込んで設定辞書を初期化
    """
    global app_config
    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            app_config = toml.load(f)
            logging.info(f"設定ファイルを読み込みました: {config_file_path}")
            _validate_config_or_log_warnings()
    except FileNotFoundError:
        logging.error(f"設定ファイル '{config_file_path}' が見つかりません。")
        raise
    except toml.TomlDecodeError as e:
        logging.error(f"設定ファイル '{config_file_path}' の読み込みエラー: {e}")
        raise


def _validate_config_or_log_warnings():
    """
    設定ファイルの基本的な検証
    """
    required_sections = {"ssh", "security", "server", "webapp"}
    for section in required_sections:

        if section not in app_config:
            logging.warning(f"設定ファイルに必須セクション '{section}' がありません。")


def load_master_text_data():
    """全体のテキストデータを読み込んでキャッシュする。"""
    global _master_text_data_cache
    if _master_text_data_cache is not None:
        return _master_text_data_cache

    # テキストデータを読み込む
    master_text_data_filename = "textdata.yaml"
    file_path = os.path.join('text', master_text_data_filename)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            _master_text_data_cache = data  # キャッシュ作りまーす
            return _master_text_data_cache
    except FileNotFoundError:
        logging.error(f"テキストデータファイル '{file_path}' が見つかりません。")
        _master_text_data_cache = {}
        return _master_text_data_cache
    except Exception as e:
        logging.error(f"テキストデータファイル '{file_path}' の読み込みエラー: {e}")
        _master_text_data_cache = {}
        return _master_text_data_cache


def get_text_by_key(key_string, menu_mode, default_value=""):
    """
    指定モードのテキストデータを取得する。
    例：get_text_by_key("user_pref_menu.header","1")
    """
    master_data = load_master_text_data()
    keys = key_string.split('.')
    current_level_data = master_data
    try:
        # 要素の取り出し
        for key_part in keys:
            if not isinstance(current_level_data, dict):
                logging.warning(
                    f"キー {key_string} のパス {key_part}が辞書ではありません。")
                return default_value
            current_level_data = current_level_data[key_part]

        if isinstance(current_level_data, dict):
            mode_specific_key = f"mode_{menu_mode}"
            text_value = current_level_data[mode_specific_key]

            if isinstance(text_value, list):
                return "\r\n".join(text_value)  # 複数行の場合
            return str(text_value)  # 単行の場合

        else:
            # キーの終端が辞書ではなかった場合
            logging.warning(
                f"キー {key_string}の終端が予期した形式ではありません。(mode_{menu_mode}を持つ辞書にしてください)")
            return default_value
    except (KeyError, TypeError):
        logging.warning(
            f"キー {key_string} (mode{menu_mode}) に対応するテキストデータが見つかりません。")
        return default_value


def send_text_by_key(chan, key_string, menu_mode, default_value="", add_newline=True, **kwargs):
    """指定されたキーのテキストをチャンネルに送信する
    キーワード引数でプレイスホルダを置換可能"""
    text_to_send = get_text_by_key(key_string, menu_mode, default_value)
    if text_to_send:
        try:
            if kwargs:
                text_to_send = text_to_send.format(**kwargs)

            # SSHチャンネル向けに改行コードを正規化 (\r\n または \n を \r\n に統一)
            processed_text = text_to_send.replace(
                '\r\n', '\n').replace('\n', '\r\n')

            # 末尾の改行を追加するかどうか制御
            if add_newline:
                if not processed_text.endswith('\r\n'):
                    chan.send(processed_text + '\r\n')
                else:
                    chan.send(processed_text)  # 既に改行で終わっている場合はそのまま送信

            else:
                chan.send(processed_text)  # 末尾に改行を追加しない

        except KeyError as e:
            logging.warning(
                f"キー {key_string}のテキストフォーマット中にエラー：未定義のプレイスホルダ {e}")
            # フォーマットエラーの場合も、改行処理と送信は試みる (text_to_send はフォーマット前のもの)
            processed_text_on_error = text_to_send.replace(
                '\r\n', '\n').replace('\n', '\r\n')
            if add_newline:
                if not processed_text_on_error.endswith('\r\n'):
                    chan.send(processed_text_on_error + '\r\n')
                else:
                    chan.send(processed_text_on_error)
            else:
                chan.send(processed_text_on_error)
        except Exception as e:
            logging.error(
                f"テキスト送信中にエラー(キー: {key_string})： {e}")
            processed_text_on_error = text_to_send.replace(
                '\r\n', '\n').replace('\n', '\r\n')
            if add_newline:
                if not processed_text_on_error.endswith('\r\n'):
                    chan.send(processed_text_on_error + '\r\n')
                else:
                    chan.send(processed_text_on_error)
            else:
                chan.send(processed_text_on_error)
    elif not default_value:
        logging.warning(
            f"キー {key_string} (mode{menu_mode}) に対応するテキストデータがないのでスキップします。")


def hash_password(password):
    """ハッシュ化したパスワードを返す"""
    pbkdf2_rounds_val = app_config.get('security', {}).get('pbkdf2_rounds')
    if pbkdf2_rounds_val is None:
        logging.warning("security.pbkdf2_rounds が設定されていません。デフォルト値を使用します。")
        pbkdf2_rounds_val = 100000

    salt = os.urandom(16)
    hashed_password = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        pbkdf2_rounds_val
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
                auth_method TEXT DEFAULT 'password_only' NOT NULL CHECK(auth_method IN ('key_only','password_only','webapp_only','both')),
                menu_mode TEXT DEFAULT '1' NOT NULL CHECK(menu_mode IN ('1','2','3'))
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

        # シスオペのSSH鍵を作成
        sysop_private_key = generate_ssh_keypair(sysopname)

        print("Sysop registered.")
        print(sysop_private_key)
        print("秘密鍵は今回のみの表示です。大切に保管してください。")
        # ゲスト登録 (saltとハッシュ化パスワード保存)
        guest_salt, guest_hashed_pass = hash_password('GUEST')
        print("Registering Guest...")
        cur.execute(
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, mail, auth_method) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("GUEST", guest_hashed_pass, guest_salt, 1, registdate, 0, 0,
             'Guest', 'guest@example.com', 'webapp_only')  # 登録日も設定、ゲストはWebAPPのみ
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


def prompt_handler(chan, dbname, login_id, menu_mode='2'):
    """ 定型実行のまとめ """
    bbsmenu.telegram_recieve(chan, dbname, login_id)
    server_prefs = sqlite_tools.read_server_pref(dbname)
    return server_prefs


def generate_ssh_keypair(username):
    """
    SSH鍵を生成する。公開鍵はauthorized_keys.pubに追加し、秘密鍵は文字列として返す
    """
    if not app_config:
        logging.error("設定が読み込まれていません。SSH鍵ペアを生成できません。")
        return None
    try:
        ssh_config = app_config.get("ssh", {})
        key_dir_val = ssh_config.get('key_dir')
        auth_keys_filename_val = ssh_config.get('auth_keys_filename')

        if not key_dir_val or not auth_keys_filename_val:
            logging.error(
                "SSH設定(key_dir or auth_key_filename)がconfig.tomlに設定されていません。")
            return None

        # 秘密鍵を生成
        key = paramiko.RSAKey.generate(2048)
        from io import StringIO
        private_key_io = StringIO()
        key.write_private_key(private_key_io)
        private_key_str = private_key_io.getvalue()
        private_key_io.close()

        # 公開鍵を生成してauthorized_keys.pubに追加
        public_key_line = f"ssh-rsa {key.get_base64()} {username}@{socket.gethostname()}"

        # .sshkeyディレクトリがなければ作成
        if not os.path.exists(key_dir_val):
            os.makedirs(key_dir_val, mode=0o700)
            logging.info(f"SSHキーディレクトリ '{key_dir_val}' を作成しました。")

        auth_key_path = os.path.join(key_dir_val, auth_keys_filename_val)
        # authorized_keys.pubがなければ作成
        if not os.path.exists(auth_key_path):
            with open(auth_key_path, 'w', encoding='utf-8') as f:
                f.write(public_key_line+'\n')
        else:  # あれば追記
            with open(auth_key_path, 'a', encoding='utf-8') as f:
                f.write(public_key_line+'\n')
        logging.info(f"SSH鍵を生成しました。{username} の公開鍵を {auth_key_path} に追加しました。")

        return private_key_str
    except Exception as e:
        logging.error(f"SSH鍵生成エラー: {e}")
        return None


# ここからしたはデバッグ後に削除する

def show_textsfile(chan, filename, menu_mode='2'):
    """テキストファイルを表示する"""
    try:
        sendm = txt_reads(filename+'.'+menu_mode)
        for s in sendm:
            chan.send(s + '\r')
    except FileNotFoundError:
        logging.warning(f"テキストファイル '{filename+'.'+menu_mode}' が見つかりません。")
    except Exception as e:
        logging.error(f"テキストファイル表示エラー: {e}")


def show_textfile(chan, filename, menu_mode='2'):
    try:
        sendm = txt_read(filename+'.'+menu_mode)
        chan.send(sendm)
    except FileNotFoundError:
        logging.warning(
            f"テキストファイル '{filename+'.'+menu_mode}' が見つかりません。")
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
        logging.warning(f"エラー: ファイルが見つかりません - {filepath}")
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
        logging.warning(f"エラー: ファイルが見つかりません - {filepath}")
        return ""  # 空文字列を返すなど、エラー処理を追加
