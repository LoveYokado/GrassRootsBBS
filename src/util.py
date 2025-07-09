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
import textwrap

import sqlite_tools
import ssh_input
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
        is_match = (stored_password_hash == provided_hash)
        return is_match

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
    paths_config = app_config.get('paths', {})
    full_path = paths_config.get('text_data_yaml', 'setting/textdata.yaml')
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            _master_text_data_cache = data  # キャッシュ作りまーす
            return _master_text_data_cache
    except FileNotFoundError:
        logging.error(f"テキストデータファイル '{full_path}' が見つかりません。")
        _master_text_data_cache = {}
        return _master_text_data_cache
    except Exception as e:
        logging.error(f"テキストデータファイル '{full_path}' の読み込みエラー: {e}")
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

            if text_value is None:
                return ""  # YAMLで値が空の場合、Noneが返るので空文字列に変換

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
    pbkdf2_rounds_val = app_config.get('security', {}).get('PBKDF2_ROUNDS')
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


def make_sysop_and_database(dbname, sysop_id, sysop_password, sysop_email):
    """データベースと初期テーブル、Sysop/Guestユーザーを作成する"""
    conn = None  # finally で確実に close するため
    cur = None  # finally で確実に close するため
    try:
        conn = sqlite3.connect(dbname)
        cur = conn.cursor()

        # --- users テーブル作成 ---
        # id,name,password,registdate,level,lastlogin,lastlogout,comment,mail
        logging.info("Creating 'users' table...")
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
                exploration_list TEXT DEFAULT '',
                read_progress TEXT DEFAULT '{}'
            )'''
        )

        # Sysop 情報入力
        sysopname = sysop_id
        sysoppass = sysop_password
        registdate = int(time.time())

        sysop_salt, sysop_hashed_pass = hash_password(sysoppass)

        # シスオペ登録 (saltとハッシュ化パスワード保存)
        logging.info(f"Registering Sysop '{sysopname}'...")
        cur.execute(
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, email,auth_method) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sysopname, sysop_hashed_pass, sysop_salt, 5, registdate, 0, 0,
             'Sysop', sysop_email, 'both')
        )

        # --- SysopのSSH鍵を生成し、秘密鍵をファイルに保存 ---
        try:
            paths_config = app_config.get('paths', {})
            key_dir = paths_config.get('host_key_dir')
            if key_dir:
                # generate_and_regenerate_ssh_key は公開鍵を authorized_keys に追加し、秘密鍵(PEM文字列)を返す
                private_key_pem = generate_and_regenerate_ssh_key(sysopname)
                if private_key_pem:
                    private_key_path = os.path.join(key_dir, sysopname)
                    with open(private_key_path, 'w') as f:
                        f.write(private_key_pem)
                    os.chmod(private_key_path, 0o600)
                    logging.info(
                        f"Sysop's private key has been saved to: {private_key_path}")
                else:
                    logging.error("Failed to generate SSH key for Sysop.")
            else:
                logging.warning(
                    "paths.host_key_dir is not configured. Skipping Sysop's private key generation.")
        except Exception as e:
            logging.error(
                f"An error occurred while generating Sysop's SSH key: {e}", exc_info=True)

        # ゲスト登録 (saltとハッシュ化パスワード保存)
        guest_salt, guest_hashed_pass = hash_password('GUEST')
        logging.info("Registering 'GUEST' user...")
        cur.execute(
            "INSERT INTO users(name, password, salt, level, registdate, lastlogin, lastlogout, comment, email, auth_method) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("GUEST", guest_hashed_pass, guest_salt, 1, registdate, 0, 0,
             'Guest', 'guest@example.com', 'webapp_only')   # 登録日も設定、ゲストはWebAPPのみ
        )

        # --- server_pref テーブル作成 ---
        logging.info("Creating 'server_pref' table...")
        cur.execute(
            '''CREATE TABLE server_pref(
                bbs INTEGER DEFAULT 0,
                chat INTEGER DEFAULT 1,
                mail INTEGER DEFAULT 1,
                telegram INTEGER DEFAULT 1,
                userpref INTEGER DEFAULT 1,
                who INTEGER DEFAULT 1,
                default_exploration_list TEXT DEFAULT '',
                hamlet INTEGER DEFAULT 1
            )'''
        )
        # 初期設定を挿入 (プレースホルダーを使用)
        cur.execute(
            "INSERT INTO server_pref(bbs, chat, mail, telegram, userpref, who, default_exploration_list, hamlet) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (2, 2, 2, 2, 2, 2, "", 2)
        )

        # メールボックステーブル作成

        logging.info("Creating 'mails' table...")
        cur.execute(
            '''CREATE TABLE mails(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                sender_display_name TEXT,
                sender_ip_address TEXT,
                recipient_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                sent_at INTEGER NOT NULL,
                sender_deleted INTEGER DEFAULT 0,
                recipient_deleted INTEGER DEFAULT 0
            )'''
        )

        # --- telegram テーブル作成 (id カラムあり) ---
        logging.info("Creating 'telegram' table...")
        cur.execute(
            '''CREATE TABLE telegram(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_name TEXT NOT NULL,
                recipient_name TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            )'''
        )

        # --- BBS関連テーブル作成 ---
        logging.info("Creating BBS related tables...")
        sqlite_tools.create_bbs_tables_if_not_exist(cur)

        # データベースへコミット
        conn.commit()
        logging.info("Database and initial tables created successfully.")

        # 作成されたテーブルの内容を表示 (確認用)
        logging.debug("\n--- Users Table Contents ---")
        cur.execute("SELECT * FROM users;")
        users = cur.fetchall()
        for user in users:
            logging.debug(user)

        logging.debug("\n--- Server Pref Table Contents ---")
        cur.execute("SELECT * FROM server_pref;")
        serverprefs = cur.fetchall()
        for server_pref in serverprefs:
            logging.debug(server_pref)

    except sqlite3.Error as e:
        logging.critical(f"データベースの初期化に失敗しました: {e}", exc_info=True)
        if conn:
            conn.rollback()  # エラー時はロールバック

    finally:
        # カーソルと接続を確実に閉じる
        if cur:
            cur.close()
        if conn:
            conn.close()
        logging.info("Database connection closed after initialization.")


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
        logging.error(
            "設定が読み込まれていません。SSH鍵ペアを生成できません。(util.generate_and_regenerate_ssh_key)")
        return None
    try:
        paths_config = app_config.get('paths', {})
        authorized_keys_path = paths_config.get('authorized_keys')

        if not authorized_keys_path:
            logging.error(
                "authorized_keys のパスが設定されていません。(util.generate_and_regenerate_ssh_key)")
            return None

        key_dir_val = os.path.dirname(authorized_keys_path)

        # 秘密鍵を生成 (Ed25519Key.generate() は古いparamikoにないため、より互換性の高いRSAKeyを使用)
        logging.info("Generating a new RSA 4096-bit key pair...")
        key = paramiko.RSAKey.generate(4096)
        from io import StringIO
        private_key_io = StringIO()
        key.write_private_key(private_key_io)
        private_key_str = private_key_io.getvalue()
        private_key_io.close()

        # 公開鍵を生成してauthorized_keys.pubに追加
        public_key_line = f"{key.get_name()} {key.get_base64()} {username}"

        if not os.path.exists(key_dir_val):  # ディレクトリがなければ作成
            os.makedirs(key_dir_val, mode=0o700)
            logging.info(f"SSHキーディレクトリ '{key_dir_val}' を作成しました。")

        auth_key_path = authorized_keys_path
        # authorized_keys.pubに追記
        with open(auth_key_path, 'a', encoding='utf-8') as f:
            f.write(public_key_line+'\n')
        logging.info(f"SSH鍵を生成しました。{username} の公開鍵を {auth_key_path} に追加しました。")

        return private_key_str
    except Exception as e:
        logging.error(f"SSH鍵生成エラー: {e}")
        return None


def regenerate_user_ssh_key(username):
    """
    指定されたユーザの公開鍵をauthorized_keys.pubから削除し、
    新しいキーペアを生成して公開鍵を追記。
    """
    if not app_config:
        logging.error("設定が読み込めないので鍵が作れません。(util.regenerate_user_ssh_key)")
        return None
    try:
        paths_config = app_config.get('paths', {})
        authorized_keys_path = paths_config.get('authorized_keys')

        if not authorized_keys_path:
            logging.error(
                "authorized_keys のパスが設定されていません。(util.regenerate_user_ssh_key)")
            return None

        auth_key_path = authorized_keys_path
        key_dir_val = os.path.dirname(authorized_keys_path)

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


def remove_user_public_key(username):
    """
    指定されたユーザの公開鍵をファイルから削除する。
    """
    if not app_config:
        logging.error("設定が読み込めないので公開鍵が削除できません。(util.remove_user_public_key)")
        return None
    try:
        paths_config = app_config.get('paths', {})
        authorized_keys_path = paths_config.get('authorized_keys')

        if not authorized_keys_path:
            logging.error(
                "authorized_keys のパスが設定されていません。(util.remove_user_public_key)")
            return False

        auth_key_path = authorized_keys_path
        # key_dir_val = os.path.dirname(authorized_keys_path) # Not needed for removal

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
    # This function is used by util.handle_shortcut and bbs_handler.BoardManager.load_boards_from_config
    # The filename argument should be the full path from config.toml
    filepath = filename  # filename is now expected to be a full path from config.toml
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


def handle_shortcut(chan, dbname: str, login_id: str, display_name: str, menu_mode: str, shortcut_input: str, online_members_func: callable):
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
                chan, dbname, login_id, display_name, menu_mode, shortcut_id_to_search, chan.getpeername()[0])
            return True
        if target_type == "bbs":
            send_text_by_key(chan, "shortcut.not_found", menu_mode,
                             shortcut_id=raw_shortcut_id_with_prefix)
            return True

    # チャット検索
    if target_type == "chat" or target_type is None:
        paths_config = app_config.get('paths', {})
        chatroom_config_path = paths_config.get('chatroom_yaml')
        chatroom_config = load_yaml_file_for_shortcut(chatroom_config_path)
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
                    chan, dbname, login_id, display_name, menu_mode, shortcut_id_to_search, item_name
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


def telegram_send(chan, dbname, display_name, online_members_ids, current_menu_mode):
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
    if recipient_name not in online_members_ids:
        send_text_by_key(chan, "telegram.recipient_not_online",
                         current_menu_mode, recipient_name=recipient_name)
        return

    # 自分自身には送れないようにする(テスト中は無効)
    # if recipient_name == sender_name:
    #    util.send_text_by_key(chan, "telegram.cannot_send_to_self", current_menu_mode)
    #    return

    limits_config = app_config.get('limits', {})
    telegram_max_len = limits_config.get('telegram_message_max_length', 100)

    send_text_by_key(chan, "telegram.message_prompt",
                     current_menu_mode, max_len=telegram_max_len, add_newline=False)
    message = ssh_input.process_input(chan)

    if not message:
        send_text_by_key(chan, "telegram.no_message", current_menu_mode)
        return

    # メッセージが長すぎる場合の処理
    if len(message) > telegram_max_len:
        message = message[:telegram_max_len]
        send_text_by_key(
            chan, "telegram.message_truncated", current_menu_mode, max_len=telegram_max_len)

    try:
        current_timestamp = int(time.time())
        # sqlite_tools に save_telegram(dbname, sender, recipient, message, timestamp) 関数を実装する想定
        # 送信者名は表示名(display_name)を保存
        sqlite_tools.save_telegram(
            dbname, display_name, recipient_name, message, current_timestamp)
        send_text_by_key(chan, "telegram.send_success", current_menu_mode)
    except Exception as e:
        logging.warning(
            f"電報保存エラー (送信者: {display_name}, 宛先: {recipient_name}): {e}")
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
        # ヘッダーとカラム見出しを textdata.yaml から表示
        send_text_by_key(chan, "telegram.receive_header", current_menu_mode)
        send_text_by_key(chan, "telegram.receive_headings", current_menu_mode)

        for i, telegram_to_display in enumerate(filterd_telegrams):
            num_str = f"{i+1:05d}"
            sender = telegram_to_display['sender_name']
            message = telegram_to_display['message']
            timestamp_val = telegram_to_display['timestamp']
            try:
                dt_obj = datetime.datetime.fromtimestamp(timestamp_val)
                r_date_str = dt_obj.strftime('%y/%m/%d')
                r_time_str = dt_obj.strftime('%H:%M:%S')
            except (ValueError, OSError, TypeError):  # TypeError も考慮
                r_date_str = "----/--/--"
                r_time_str = "--:--:--"

            # 掲示板のフォーマットに合わせる
            # 投稿者名: 14文字, 本文: 32文字
            sender_short = shorten_text_by_slicing(sender, width=14)
            message_short = shorten_text_by_slicing(message, width=32)

            # 掲示板の表示フォーマットと完全に一致させる
            line = f"{num_str}  {r_date_str} {r_time_str} {sender_short:<14}   {message_short}\r\n"
            chan.send(line.encode('utf-8'))

        # フッターを textdata.yaml から表示
        send_text_by_key(chan, "telegram.receive_footer", current_menu_mode)


def is_valid_email(email: str) -> bool:
    """メールアドレスの簡易検証"""
    if not email:
        return False
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if re.match(pattern, email):
        return True
    return False


def generate_random_password(length=12):
    """ランダムパスワード生成"""
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password


def display_exploration_list(chan, list_str: str):
    """カンマ区切りの探索リスト文字列を整形して表示する共通関数"""
    if not list_str:
        # リストが空の場合は何も表示しない（メッセージは呼び出し元で制御）
        return
    items = list_str.split(",")
    chan.send(b"\r\n")
    for item in items:
        item_stripped = item.strip()
        if item_stripped:
            chan.send(item_stripped.encode('utf-8') + b'\r\n')
    chan.send(b"\r\n")


def prompt_and_save_exploration_list(chan, menu_mode: str, save_callback: callable):
    """探索リストの入力を促し、指定されたコールバック関数で保存する共通関数"""
    send_text_by_key(
        chan, "user_pref_menu.register_exploration_list.header", menu_mode)

    exploration_items = []
    item_number = 1
    while True:
        prompt_text = f"{item_number}: "
        chan.send(prompt_text.encode('utf-8'))
        item_input = ssh_input.process_input(chan)

        if item_input is None:
            return False  # 切断

        if not item_input.strip():
            break

        cleaned_item_input = item_input.strip().lstrip(':').lstrip(';')
        exploration_items.append(cleaned_item_input)
        item_number += 1

    if not exploration_items:
        return True  # 何も入力されずに終了した場合

    send_text_by_key(
        chan, "user_pref_menu.register_exploration_list.confirm_yn", menu_mode, add_newline=False)
    confirm_choice = ssh_input.process_input(chan)

    if confirm_choice is None or confirm_choice.lower().strip() != 'y':
        return True  # キャンセルまたは切断

    exploration_list_str = ",".join(exploration_items)
    if save_callback(exploration_list_str):
        send_text_by_key(
            chan, "user_pref_menu.register_exploration_list.success", menu_mode)
    else:
        logging.error("探索リスト保存時にエラーが発生しました。")
        send_text_by_key(
            chan, "common_messages.error", menu_mode)
    return True


def format_timestamp(timestamp, default_str='N/A', date_format='%Y-%m-%d %H:%M'):
    """タイムスタンプを安全にフォーマットする"""
    if not timestamp or timestamp <= 0:
        return default_str
    try:
        return datetime.datetime.fromtimestamp(timestamp).strftime(date_format)
    except (ValueError, OSError, TypeError):
        logging.warning(f"Invalid timestamp for formatting: {timestamp}")
        return 'Invalid Date'


def generate_guest_hash(ip_address: str) -> str:
    """IPアドレスからゲスト用の短縮ハッシュを生成する"""
    # app_configがロードされていることを前提とする
    security_config = app_config.get('security', {})
    salt = security_config.get('GUEST_ID_SALT')
    if not salt:
        logging.error("security.GUEST_ID_SALT が設定されていません。ゲストIDを生成できません。")
        return "error"

    # IPとソルトを結合してハッシュ化
    hash_input = f"{ip_address}-{salt}".encode('utf-8')
    full_hash = hashlib.sha256(hash_input).hexdigest()

    # ハッシュの先頭7文字を使用
    return full_hash[:7]


def get_display_name(login_id: str, ip_address: str) -> str:
    """ユーザーの表示名を取得する。ゲストの場合は動的IDを生成する。"""
    if login_id.upper() == 'GUEST':
        guest_hash = generate_guest_hash(ip_address)
        return f"GUEST({guest_hash})"
    return login_id


def shorten_text_by_slicing(text, width, placeholder="..."):
    """
    テキストを指定された幅に単純なスライスで短縮する。
    textwrap.shortenと異なり、長い単語でも先頭部分を残す。
    """
    if len(text) <= width:
        return text

    placeholder_len = len(placeholder)
    if width <= placeholder_len:
        # 幅がプレースホルダ自体より短いか等しい場合、プレースホルダを切り詰めて返す
        return placeholder[:width]

    truncated_len = width - placeholder_len
    return text[:truncated_len] + placeholder
