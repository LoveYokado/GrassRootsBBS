import logging
import toml
import paramiko
import os
import hashlib
import time
import sqlite3
import yaml
import datetime
import re
import secrets
import string

import sqlite_tools
import ssh_input
SETTING_DIR = "setting"
# テキストデータのキャッシュ用グローバル変数
_master_text_data_cache = None


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


def verify_password(stored_password_hash, salt_hex, provided_password, pbkdf2_rounds):
    """
    パスワードと保存されたハッシュの検証
    """
    try:
        salt = bytes.fromhex(salt_hex)
        provided_hash = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'),
                                            salt, pbkdf2_rounds).hex()
        return stored_password_hash == provided_hash
    except Exception as e:
        logging.error(f"パスワード検証中エラー: {e}")
        return False


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
                name TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password TEXT NOT NULL,
                salt TEXT NOT NULL,
                registdate INTEGER,
                level INTEGER DEFAULT 1,
                lastlogin INTEGER,
                lastlogout INTEGER,
                comment TEXT,
                email TEXT,
                auth_method TEXT DEFAULT 'password_only' NOT NULL CHECK(auth_method IN ('key_only','password_only','webapp_only','both')),
                menu_mode TEXT DEFAULT '1' NOT NULL CHECK(menu_mode IN ('1','2','3')),
                telegram_restriction INTEGER DEFAULT 0 NOT NULL CHECK(telegram_restriction IN (0, 1, 2, 3)),
                blacklist TEXT DEFAULT '',
                exploration_list TEXT DEFAULT ''
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
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, email,auth_method) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sysopname, sysop_hashed_pass, sysop_salt, 5, registdate, 0, 0,
             # メールアドレスも動的に、認証は両方
             'Sysop', f'{sysopname.lower()}@example.com', 'both')
        )

        # シスオペのSSH鍵を作成
        sysop_private_key_pem = generate_and_regenerate_ssh_key(sysopname)
        if sysop_private_key_pem:
            print("Sysop registered.")
            print(sysop_private_key_pem)
            print("秘密鍵は今回のみの表示です。大切に保管してください。")
        else:
            print("シスオペのSSH鍵の作成に失敗しました。")
        # ゲスト登録 (saltとハッシュ化パスワード保存)
        guest_salt, guest_hashed_pass = hash_password('GUEST')
        print("Registering Guest...")
        cur.execute(
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, email, auth_method) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("GUEST", guest_hashed_pass, guest_salt, 1, registdate, 0, 0,
             'Guest', 'guest@example.com', 'webapp_only')   # 登録日も設定、ゲストはWebAPPのみ
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
                who INTEGER DEFAULT 1,
                default_exploration_list TEXT DEFAULT ''
            )'''
        )
        # 初期設定を挿入 (プレースホルダーを使用)
        cur.execute(
            "INSERT INTO server_pref(bbs, chat, mail, telegram, userpref, who, default_exploration_list) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (0, 1, 1, 1, 1, 1, "")
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

        # --- BBS関連テーブル作成 ---
        print("Creating BBS tables...")
        sqlite_tools.create_bbs_tables_if_not_exist(cur)

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
    check_new_mail(chan, dbname, login_id, menu_mode)
    telegram_recieve(chan, dbname, login_id, menu_mode)
    server_prefs = sqlite_tools.read_server_pref(dbname)
    return server_prefs


def generate_and_regenerate_ssh_key(username):
    """
    新しいSSHキーペアを生成し、公開鍵をauthorized_keys.pubに追加する。
    秘密鍵(PEM形式文字列)を返す。
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
        public_key_line = f"{key.get_name()} {key.get_base64()} {username}"

        # .sshkeyディレクトリがなければ作成
        if not os.path.exists(key_dir_val):
            os.makedirs(key_dir_val, mode=0o700)
            logging.info(f"SSHキーディレクトリ '{key_dir_val}' を作成しました。")

        auth_key_path = os.path.join(key_dir_val, auth_keys_filename_val)
        # authorized_keys.pubに追記
        with open(auth_key_path, 'a', encoding='utf-8') as f:
            f.write(public_key_line+'\n')
        logging.info(f"SSH鍵を生成しました。{username} の公開鍵を {auth_key_path} に追加しました。")

        return private_key_str
    except Exception as e:
        logging.error(f"SSH鍵生成エラー: {e}")
        return None


# ここからしたはデバッグ後に削除する
def regenerate_user_ssh_key(username):
    """
    指定されたユーザの公開鍵をauthorized_keys.pubから削除し、
    新しいキーペアを生成して公開鍵を追記。
    """
    if not app_config:
        logging.error("設定が読み込めないので鍵が作れません。")
        return None
    try:
        ssh_config = app_config.get("ssh", {})
        key_dir_val = ssh_config.get('key_dir')
        auth_keys_filename_val = ssh_config.get('auth_keys_filename')

        if not key_dir_val or not auth_keys_filename_val:
            logging.error(
                "SSH設定(key_dir or auth_keys_filename)がconfig.tomlに設定されていません。")
            return None

        auth_key_path = os.path.join(key_dir_val, auth_keys_filename_val)

        # 古い公開鍵を削除
        if os.path.exists(auth_key_path):
            temp_auth_key_path = auth_key_path + ".tmp"
            found_and_removed = False
            with open(auth_key_path, 'r', encoding='utf-8') as infile, \
                    open(temp_auth_key_path, 'w', encoding='utf-8') as outfile:
                for line in infile:
                    stripped_line = line.strip()
                    if not stripped_line or stripped_line.startswith('#'):
                        outfile.write(line)
                        continue

                    parts = stripped_line.split()
                    # 公開鍵のコメント部分がユーザー名と一致するか確認
                    key_comment_user = None
                    if len(parts) > 2:
                        key_comment_user = parts[2].split('@')[0]  # @以降は無視

                    if key_comment_user == username:
                        logging.info(
                            f"ユーザー '{username}' の古いSSH公開鍵を削除します: {stripped_line}")
                        found_and_removed = True
                    else:
                        outfile.write(line)  # 他のユーザーの鍵は保持

            os.replace(temp_auth_key_path, auth_key_path)  # 一時ファイルを元のファイルに置き換え
            if not found_and_removed:
                logging.warning(
                    f"ユーザー '{username}' のSSH公開鍵は見つかりませんでした。削除処理はスキップされました。")
        else:
            logging.warning(f"authorized_keysファイル '{auth_key_path}' が存在しません。")

        # 新しいキーペアを生成し、公開鍵を追記
        new_private_key_pem = generate_and_regenerate_ssh_key(username)
        if new_private_key_pem:
            logging.info(f"ユーザー '{username}' の新しいSSH鍵ペアを生成し、公開鍵を登録しました。")
            return new_private_key_pem
        else:
            logging.error(f"ユーザー '{username}' の新しいSSH鍵ペアの生成に失敗しました。")
            return None

    except Exception as e:
        logging.error(f"SSH鍵の再生成中にエラーが発生しました (ユーザー: {username}): {e}")
        return None


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


def remove_user_public_key(username):
    """
    指定されたユーザの公開鍵をファイルから削除する。
    """
    if not app_config:
        logging.error("設定が読み込めないので公開鍵が削除できません。")
        return None
    try:
        ssh_config = app_config.get("ssh", {})
        key_dir_val = ssh_config.get('key_dir')
        auth_keys_filename_val = ssh_config.get('auth_keys_filename')

        if not key_dir_val or not auth_keys_filename_val:
            logging.error(
                "SSH設定(key_dir or auth_key_filename)がconfig.tomlに設定されていません。")
            return False

        auth_key_path = os.path.join(key_dir_val, auth_keys_filename_val)

        if not os.path.exists(auth_key_path):
            logging.info(f"公開鍵ファイル'{auth_key_path}'が見つかりません。公開鍵の削除はスキップしました。")
            return False

        temp_auth_key_path = auth_key_path + ".tmp"
        found_and_removed = False
        with open(auth_key_path, 'r', encoding='utf-8') as infile, \
                open(temp_auth_key_path, 'w', encoding='utf-8') as outfile:
            for line in infile:
                stripped_line = line.strip()
                if not stripped_line or stripped_line.startswith('#'):
                    outfile.write(line)
                    continue

                parts = stripped_line.split()
                key_comment_user = None
                if len(parts) > 2:
                    key_comment_user = parts[2].split('@')[0]

                if key_comment_user == username:
                    logging.info(
                        f"ユーザ'{username}'の公開鍵を削除しましす: {stripped_line}")
                    found_and_removed = True
                else:
                    outfile.write(line)
        os.replace(temp_auth_key_path, auth_key_path)
        return found_and_removed  # 削除結果を返す
    except Exception as e:
        logging.error(f"公開鍵の削除エラー: {e}")
        return False


def load_yaml_file_for_shortcut(filename: str):
    """設定からYAMLをロードしてショートカット情報を取得する"""
    filepath = os.path.join(SETTING_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"設定ファイル '{filepath}' が見つかりません。")
        return None
    except Exception as e:
        logging.error(f"設定ファイル '{filepath}' の読み込みエラー: {e}")
        return None


def _search_items_recursive(items_list, target_id, menu_mode, expected_type):
    """アイテムリストを再帰的に探索するヘルパー関数"""
    if not items_list:
        return None, None

    for item_data in items_list:
        if not isinstance(item_data, dict):
            continue

        current_item_id = item_data.get("id")
        current_item_type = item_data.get("type")

        if current_item_id == target_id and current_item_type == expected_type:
            item_name = item_data.get("name", current_item_id)
            return item_data, item_name

        # 'items'があれば再帰的に探索
        if item_data.get("type") == "child" and "items" in item_data and isinstance(item_data["items"], list):
            found_item, found_item_name = _search_items_recursive(
                item_data["items"], target_id, menu_mode, expected_type)
            if found_item:
                return found_item, found_item_name
    return None, None


def find_item_in_yaml(config_data, target_id, menu_mode, expected_type):
    """YAMLから指定されたIDのアイテムを再帰的に検索、期待されるタイプならアイテムと名前を返す"""
    if not config_data:
        return None, None

    # categoriesリスト探索
    if "categories" in config_data and isinstance(config_data["categories"], list):
        for category_data in config_data["categories"]:
            item, name = _search_items_recursive(category_data.get(
                "items", []), target_id, menu_mode, expected_type)
            if item:
                return item, name
    # globalリスト探索(トップレベルのアイテム)
    if "global" in config_data and isinstance(config_data["global"], list):
        # globalアイテムは直接的な子要素として探索
        for item_global_data in config_data["global"]:
            if isinstance(item_global_data, dict) and\
                    item_global_data.get("id") == target_id and\
                    item_global_data.get("type") == expected_type:
                item_name = item_global_data.get(
                    "name", item_global_data.get("id"))
                return item_global_data, item_name
    return None, None


def handle_shortcut(chan, dbname: str, login_id: str, menu_mode: str, shortcut_input: str, online_members_func: callable):
    """ショートカットを処理する。ショートカットとして処理が完了したらtrueを返す"""
    # ショートカットではない
    if not shortcut_input.startswith(';'):
        return False

    raw_shortcut_id_with_prefix = shortcut_input[1:]
    if not raw_shortcut_id_with_prefix:
        return True  # 空のショートカットは無視

    target_type = None  # chat or bbs
    shortcut_id_to_search = raw_shortcut_id_with_prefix

    if raw_shortcut_id_with_prefix.startswith('c:'):
        target_type = "chat"
        shortcut_id_to_search = raw_shortcut_id_with_prefix[2:]

    if raw_shortcut_id_with_prefix.startswith('b:'):
        target_type = "bbs"
        shortcut_id_to_search = raw_shortcut_id_with_prefix[2:]
    # プレフィクスがないときはまずBBS,つぎにチャットの順で探す

    if not shortcut_id_to_search:
        send_text_by_key(chan, "shortcut.not_found", menu_mode,
                         shortcut_id=raw_shortcut_id_with_prefix)
        return True

    # BBS検索
    if target_type == "bbs" or target_type is None:
        board_info = sqlite_tools.get_board_by_shortcut_id(
            dbname, shortcut_id_to_search)
        if board_info:
            import bbs_handler
            send_text_by_key(chan, "shortcut.jumping_to_bbs",
                             menu_mode, board_name=board_info["name"])
            bbs_handler.handle_bbs_menu(
                chan, dbname, login_id, menu_mode, shortcut_id_to_search)
            return True
        if target_type == "bbs":
            send_text_by_key(chan, "shortcut.not_found", menu_mode,
                             shortcut_id=raw_shortcut_id_with_prefix)
            return True

    # チャット検索
    if target_type == "chat" or target_type is None:
        chatroom_config = load_yaml_file_for_shortcut("chatroom.yml")
        if chatroom_config:
            target_item, item_name = find_item_in_yaml(
                chatroom_config, shortcut_id_to_search, menu_mode, "room")
            if target_item:
                import chat_handler
                send_text_by_key(chan, "shortcut.jumping_to_chat",
                                 menu_mode, room_name=item_name)
                chat_handler.set_online_members_function_for_chat(
                    online_members_func)
                chat_handler.handle_chat_room(
                    chan, dbname, login_id, menu_mode, shortcut_id_to_search, item_name
                )
                return True
            if target_type == "chat":
                send_text_by_key(chan, "shortcut.not_found", menu_mode,
                                 shortcut_id=raw_shortcut_id_with_prefix)
                return True

        # プレフィクス無しでどちらにもみつからなかった場合
        if target_type is None:
            send_text_by_key(chan, "shortcut.not_found", menu_mode,
                             shortcut_id=raw_shortcut_id_with_prefix)
            return True

    return True


def check_new_mail(chan, dbname, username, current_menu_mode):
    """新着メールがないか確認し、あれば通知する"""
    user_id = sqlite_tools.get_user_id_from_user_name(dbname, username)
    if user_id is None:
        return

    try:
        unread_count = sqlite_tools.get_total_unread_mail_count(
            dbname, user_id)
        total_mail_count = sqlite_tools.get_total_mail_count(dbname, user_id)

        if unread_count > 0:  # 未読メールがある場合のみ通知
            notification_message_format = get_text_by_key(
                "mail_handler.new_mail_notification", current_menu_mode
            )
            if notification_message_format:  # キーが存在する場合のみ
                message_payload = notification_message_format.format(
                    total_mail_count=total_mail_count, unread_mail_count=unread_count)
                # ユーザーの入力を邪魔しないように通知 (カーソル位置保存・復元)
                chan.send(b"\033[s\r\n\r" + message_payload.replace('\n',
                          '\r\n').encode('utf-8') + b"\r\n\033[u")
            else:
                logging.warning(
                    f"新着メール通知のキー 'mail_handler.new_mail_notification' (mode: {current_menu_mode}) が見つかりません。")

    except Exception as e:
        logging.error(f"新着メールチェック中にエラー (ユーザー: {username}): {e}")


def telegram_send(chan, dbname, sender_name, online_members, current_menu_mode):
    """
    オンラインのメンバーにのみ電報を送信し、データベースに保存する。
    """
    send_text_by_key(chan, "telegram.send_message",
                     current_menu_mode)  # 電報送信メッセージ
    send_text_by_key(chan, "telegram.send_prompt",
                     current_menu_mode, add_newline=False)  # 宛先入力
    recipient_name = ssh_input.process_input(chan)

    if not recipient_name:
        send_text_by_key(chan, "telegram.no_recipient",
                         current_menu_mode)  # 宛先がオンラインにない
        return

    # ここでオンラインチェック
    if recipient_name not in online_members:
        send_text_by_key(chan, "telegram.recipient_not_online",
                         current_menu_mode, recipient_name=recipient_name)
        return

    # 自分自身には送れないようにする(テスト中は無効)
    # if recipient_name == sender_name:
    #    util.send_text_by_key(chan, "telegram.cannot_send_to_self", current_menu_mode)
    #    return

    send_text_by_key(chan, "telegram.message_prompt",
                     current_menu_mode, add_newline=False)
    message = ssh_input.process_input(chan)

    if not message:
        send_text_by_key(chan, "telegram.no_message", current_menu_mode)
        return

    # メッセージが長すぎる場合の処理
    if len(message) > 100:
        message = message[:100]
        send_text_by_key(
            chan, "telegram.message_truncated", current_menu_mode)

    try:
        current_timestamp = int(time.time())
        # sqlite_tools に save_telegram(dbname, sender, recipient, message, timestamp) 関数を実装する想定
        sqlite_tools.save_telegram(
            dbname, sender_name, recipient_name, message, current_timestamp)
        send_text_by_key(chan, "telegram.send_success", current_menu_mode)
    except Exception as e:
        logging.warning(
            f"電報保存エラー (送信者: {sender_name}, 宛先: {recipient_name}): {e}")
        send_text_by_key(chan, "telegram.send_error", current_menu_mode)


def telegram_recieve(chan, dbname, username, current_menu_mode):
    """受信している電報を表示すして、表示後に削除する"""
    # 電報受信設定を取得
    user_settings = sqlite_tools.get_user_auth_info(dbname, username)
    user_restriction = user_settings['telegram_restriction']
    blacklist_str = user_settings['blacklist']
    user_blacklist_ids = set()
    if blacklist_str:
        try:
            user_blacklist_ids = set(int(uid)
                                     for uid in blacklist_str.split(','))
        except ValueError:
            logging.error(
                f"ユーザ{username}のブラックリスト形式エラー:{blacklist_str}")
            user_blacklist_ids = set()

    results = sqlite_tools.load_and_delete_telegrams(dbname, username)
    if not results:
        return

    filterd_telegrams = []
    for teregram in results:
        sender_name = teregram['sender_name']
        # SenderユーザIDを取得
        sender_id = sqlite_tools.get_user_id_from_user_name(
            dbname, sender_name)

        should_display = True

        # 電報受信制限確認
        if user_restriction == 2:  # 全拒否
            should_display = False
        elif user_restriction == 1:  # ゲスト除外
            if sender_name.upper() == "GUEST":
                should_display = False

        # ブラックリスト確認
        if should_display == 3 and sender_id in user_blacklist_ids:
            should_display = False

        if should_display:
            filterd_telegrams.append(teregram)

    if filterd_telegrams:
        send_text_by_key(chan, "telegram.receive_header",
                         current_menu_mode)  # 電報受信メッセージ
        for telegram_to_display in filterd_telegrams:
            sender = telegram_to_display['sender_name']
            message = telegram_to_display['message']
            timestamp_val = telegram_to_display['timestamp']
            try:
                dt_str = datetime.datetime.fromtimestamp(
                    timestamp_val).strftime('%Y-%m-%d %H:%M')  # 秒は省略しても良いかも
            except (ValueError, OSError, TypeError):  # TypeError も考慮
                dt_str = "不明な日時"
            send_text_by_key(
                chan, "telegram.receive_message", current_menu_mode, sender=sender, message=message, dt_str=dt_str)  # 受信メッセージ本体
        send_text_by_key(
            chan, "telegram.receive_footer", current_menu_mode)


def _is_valid_email_for_signup(email: str) -> bool:
    """メールアドレスの簡易検証"""
    if not email:
        return False
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if re.match(pattern, email):
        return True
    return False


def _generate_random_password(length=12):
    """ランダムパスワード生成"""
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password


def handle_online_signup(chan, dbname, menu_mode):
    """オンラインサインアップ処理"""
    send_text_by_key(
        chan, "online_signup.guieance", menu_mode
    )

    new_id = ""
    while True:
        send_text_by_key(chan, "online_signup.prompt_id",
                         menu_mode, add_newline=False)
        id_input = ssh_input.process_input(chan)
        if id_input is None:
            return  # 切断
        new_id = id_input.strip().upper()
        if not new_id:
            send_text_by_key(chan, "online_signup.cancelled", menu_mode)
            return

        # ID重複チェック
        if sqlite_tools.get_user_auth_info(dbname, new_id):
            send_text_by_key(chan, "online_signup.id_exists", menu_mode)
            new_id = ""
            continue
        break

    new_email = ""
    while True:
        send_text_by_key(chan, "online_signup.prompt_email",
                         menu_mode, add_newline=False)
        email_input = ssh_input.process_input(chan)
        if email_input is None:
            return  # 切断
        new_email = email_input.strip()
        if not new_email:
            send_text_by_key(chan, "online_signup.cancelled", menu_mode)
            return

        # メールアドレスの簡易検証
        if not _is_valid_email_for_signup(new_email):
            send_text_by_key(
                chan, "online_signup.error_email_invalid", menu_mode)
            continue
        break

    send_text_by_key(chan, "online_signup.confirm_registration_yn",
                     menu_mode, new_id=new_id, new_email=new_email, add_newline=False)
    confirm = ssh_input.process_input(chan)
    if confirm is None or confirm.strip().lower() != "y":
        send_text_by_key(chan, "online_signup.cancelled", menu_mode)
        return

    temp_password = _generate_random_password()
    salt_hex, hashed_password = hash_password(temp_password)
    comment = "Online Signup User"  # 仮コメ

    # ユーザレベル1、パス認証のみ、メニューモードは2
    if sqlite_tools.register_user(dbname, new_id, hashed_password, salt_hex,
                                  comment, level=1, auth_method='password_only', menu_mode='2', telegram_restriction=0):
        send_text_by_key(
            chan, "online_signup.info_temp_password", menu_mode, temp_password=temp_password)
        send_text_by_key(
            chan, "online_signup.registration_success", menu_mode)

        # 一応SSH鍵生成
        try:
            private_key_pem = generate_and_regenerate_ssh_key(new_id)
            if private_key_pem:
                logging.info(f"オンラインサインアップユーザ '{new_id}' にSSH鍵を生成しました。")
            else:
                logging.error(f"オンラインサインアップユーザ '{new_id}' のSSH鍵の生成に失敗しました。")
        except Exception as e_key:
            logging.error(f"オンラインサインアップユーザ '{new_id}' のSSH鍵生成時エラー: {e_key}")

    else:
        send_text_by_key(chan, "online_signup.registration_failed", menu_mode)
