import logging
import toml
import os
import hashlib
import time
import yaml
import datetime
import re
import secrets
import string
import textwrap
import json
import base64
from pywebpush import webpush, WebPushException
from cryptography.hazmat.primitives import serialization

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


def verify_password(stored_password_hash, salt_hex, provided_password):
    """
    パスワードと保存されたハッシュの検証
    """
    try:
        salt = bytes.fromhex(salt_hex)
        # 設定ファイルから PBKDF2 のラウンド数を取得
        security_config = app_config.get('security', {})
        pbkdf2_rounds = security_config.get('PBKDF2_ROUNDS', 100000)
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
    required_sections = {"security", "webapp"}
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
            f"キー {key_string} (mode_{menu_mode}) に対応するテキストデータが見つかりません。")
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


def send_top_menu(chan, menu_mode):
    """トップメニューのUIとテキストを表示する"""
    # モバイル用のトップメニューボタンを表示
    chan.send(b'\x1b[?2031h')
    # トップメニューのテキストを表示
    send_text_by_key(chan, "top_menu.menu", menu_mode)


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


def check_database_initialized():
    """
    MariaDBのテーブルが存在するか確認する。
    'users'テーブルの存在をチェックすることで判断する。
    """
    from . import database
    try:
        # 'users'テーブルの存在を確認するクエリ
        query = "SHOW TABLES LIKE 'users'"
        result = database.execute_query(query, fetch='one')
        return result is not None
    except Exception as e:
        logging.error(f"データベース初期化チェック中にエラー: {e}")
        return False


def initialize_database_and_sysop(sysop_id, sysop_password, sysop_email):
    """MariaDBのテーブルを作成し、初期ユーザーを登録する"""
    from . import database
    try:
        # テーブル作成クエリ
        create_queries = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(255) UNIQUE NOT NULL,
                password TEXT NOT NULL,
                salt TEXT NOT NULL,
                registdate INT,
                level INT DEFAULT 1,
                lastlogin INT,
                lastlogout INT,
                comment TEXT,
                email VARCHAR(255),
                menu_mode VARCHAR(1) DEFAULT '1' NOT NULL,
                telegram_restriction INT DEFAULT 0 NOT NULL,
                blacklist TEXT,
                exploration_list TEXT,
                read_progress JSON
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS server_pref (
                id INT PRIMARY KEY AUTO_INCREMENT,
                bbs INT DEFAULT 2,
                chat INT DEFAULT 2,
                mail INT DEFAULT 2,
                telegram INT DEFAULT 2,
                userpref INT DEFAULT 2,
                who INT DEFAULT 2,
                default_exploration_list TEXT,
                hamlet INT DEFAULT 2,
                login_message TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS mails (
                id INT PRIMARY KEY AUTO_INCREMENT,
                sender_id INT NOT NULL,
                sender_display_name TEXT,
                sender_ip_address VARCHAR(45),
                recipient_id INT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                sent_at INT NOT NULL,
                sender_deleted BOOLEAN DEFAULT 0,
                recipient_deleted BOOLEAN DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS telegram (
                id INT PRIMARY KEY AUTO_INCREMENT,
                sender_name TEXT NOT NULL,
                recipient_name TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp INT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS boards (
                id INT PRIMARY KEY AUTO_INCREMENT,
                shortcut_id VARCHAR(255) UNIQUE NOT NULL,
                operators JSON,
                default_permission VARCHAR(10) NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                kanban_body TEXT,
                last_posted_at INT DEFAULT 0,
                board_type VARCHAR(10) NOT NULL DEFAULT 'simple',
                status VARCHAR(10) NOT NULL DEFAULT 'active',
                read_level INT NOT NULL DEFAULT 1,
                write_level INT NOT NULL DEFAULT 1,
                allow_attachments BOOLEAN DEFAULT 0 NOT NULL,
                allowed_extensions TEXT DEFAULT NULL,
                max_attachment_size_mb INT DEFAULT NULL,
                max_threads INT DEFAULT 0,
                max_replies INT DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INT PRIMARY KEY AUTO_INCREMENT,
                board_id INT NOT NULL,
                article_number INT,
                parent_article_id INT,
                user_id TEXT NOT NULL,
                title TEXT,
                body TEXT NOT NULL,
                ip_address VARCHAR(45),
                is_deleted BOOLEAN DEFAULT 0,
                created_at INT,
                attachment_filename TEXT,
                attachment_originalname TEXT,
                attachment_size INT DEFAULT NULL,
                FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
                UNIQUE (board_id, article_number)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS passkeys (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                credential_id VARBINARY(255) UNIQUE NOT NULL,
                public_key VARBINARY(255) NOT NULL,
                sign_count INT UNSIGNED NOT NULL DEFAULT 0,
                transports JSON,
                created_at INT,
                last_used_at INT,
                nickname VARCHAR(255),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS board_user_permissions (
                id INT PRIMARY KEY AUTO_INCREMENT,
                board_id INT NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                access_level VARCHAR(10) NOT NULL,
                FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
                UNIQUE (board_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                subscription_info TEXT NOT NULL,
                created_at INT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS activitypub_actors (
                id INT PRIMARY KEY AUTO_INCREMENT,
                actor_type VARCHAR(50) NOT NULL,
                actor_identifier VARCHAR(255) NOT NULL,
                private_key_pem TEXT,
                public_key_pem TEXT,
                created_at INT,
                UNIQUE KEY (actor_type, actor_identifier)
            )
            """
        ]
        for query in create_queries:
            database.execute_query(query)

        logging.info("All tables created or already exist.")

        # 初期データ挿入
        # server_pref
        if not database.execute_query("SELECT * FROM server_pref", fetch='one'):
            database.execute_query(
                "INSERT INTO server_pref (id, login_message) VALUES (%s, %s)",
                (1, 'GR-BBSへようこそ！')
            )
            logging.info("Initialized server_pref with default values.")

        # Sysopユーザー
        if not database.get_user_auth_info(sysop_id):
            salt, hashed_password = hash_password(sysop_password)
            database.register_user(
                username=sysop_id,
                hashed_password=hashed_password,
                salt=salt,
                comment='Sysop',
                level=5,
                email=sysop_email
            )
            logging.info(f"Sysop user '{sysop_id}' created.")

        # Guestユーザー
        if not database.get_user_auth_info('GUEST'):
            salt, hashed_password = hash_password('GUEST')
            database.register_user(
                username='GUEST',
                hashed_password=hashed_password,
                salt=salt,
                comment='Guest',
                level=1,
                email='guest@example.com'
            )
            logging.info("Guest user created.")

        return True
    except Exception as e:
        logging.critical(f"データベースの初期化中に致命的なエラー: {e}", exc_info=True)
        return False


def prompt_handler(chan, login_id, menu_mode='2', mail_notified_flag=False):
    """ 定型実行のまとめ """
    from . import database
    # dbname引数は互換性のために残すが、使用しない
    updated_mail_notified_flag = check_new_mail(
        chan, login_id, menu_mode, mail_notified_flag)
    telegram_recieve(chan, login_id, menu_mode)
    server_prefs = database.read_server_pref()
    return server_prefs, updated_mail_notified_flag


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
            if isinstance(item_global_data, dict) and item_global_data.get("id") == target_id and item_global_data.get("type") == expected_type:
                item_name = item_global_data.get(
                    "name", item_global_data.get("id"))
                return item_global_data, item_name
    return None, None


def handle_shortcut(chan, login_id: str, display_name: str, menu_mode: str, user_id: int, shortcut_input: str, online_members_func: callable):
    """ショートカットを処理する。ショートカットとして処理が完了したらtrueを返す"""
    from . import database
    # ショートカットではない
    if not shortcut_input.startswith(';'):
        return False

    # ゲストはショートカット機能を使えないようにする
    if login_id.upper().startswith('GUEST'):
        send_text_by_key(chan, "common_messages.permission_denied", menu_mode)
        # ショートカットとして処理したが、権限なしで終了したことを示す
        return True

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
        board_info = database.get_board_by_shortcut_id(shortcut_id_to_search)
        if board_info:
            import bbs_handler
            send_text_by_key(chan, "shortcut.jumping_to_bbs",
                             menu_mode, board_name=board_info["name"])
            bbs_handler.handle_bbs_menu(
                chan, login_id, display_name, menu_mode, shortcut_id_to_search, chan.getpeername()[0])
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
                from . import chat_handler
                send_text_by_key(chan, "shortcut.jumping_to_chat",
                                 menu_mode, room_name=item_name)
                chat_handler.set_online_members_function_for_chat(
                    online_members_func)
                chat_handler.handle_chat_room(
                    chan, login_id, display_name, menu_mode, user_id, shortcut_id_to_search, item_name)
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


def check_new_mail(chan, username, current_menu_mode, notified_in_session):
    """新着メールがないか確認し、あれば通知する。"""
    from . import database
    user_id = database.get_user_id_from_user_name(username)
    if user_id is None:
        return notified_in_session  # ユーザーが見つからない場合は元の状態を返す

    try:
        unread_count = database.get_total_unread_mail_count(user_id)

        # 未読メールが0件なら、通知フラグをリセット(False)して終了
        if unread_count == 0:
            return False

        # --- ここから下は unread_count > 0 が確定 ---

        # 既に通知済みなら、何もしないでフラグを維持(True)
        if notified_in_session:
            return True

        # まだ通知していない場合、通知処理を行う
        total_mail_count = database.get_total_mail_count(user_id)
        notification_message_format = get_text_by_key(
            "mail_handler.new_mail_notification", current_menu_mode
        )
        if notification_message_format:
            message_payload = notification_message_format.format(
                total_mail_count=total_mail_count, unread_mail_count=unread_count)
            chan.send(b"\033[s\r\n\r" + message_payload.replace('\n',
                      '\r\n').encode('utf-8') + b"\r\n\033[u")
            return True  # 通知したのでフラグをオン(True)にする
        else:
            logging.warning(
                f"新着メール通知のキー 'mail_handler.new_mail_notification' (mode: {current_menu_mode}) が見つかりません。")

    except Exception as e:
        logging.error(f"新着メールチェック中にエラー (ユーザー: {username}): {e}")

    # 通知しなかった場合やエラーの場合は、元のフラグ状態を維持
    return notified_in_session


def telegram_send(chan, display_name, online_members_ids, current_menu_mode):
    """
    オンラインのメンバーにのみ電報を送信し、データベースに保存する。
    """
    from . import database
    send_text_by_key(chan, "telegram.send_message",
                     current_menu_mode)  # 電報送信メッセージ
    send_text_by_key(chan, "telegram.send_prompt",
                     current_menu_mode, add_newline=False)  # 宛先入力
    recipient_name_input = chan.process_input()

    if not recipient_name_input:
        send_text_by_key(chan, "telegram.no_recipient",
                         current_menu_mode)  # 宛先がオンラインにない
        return

    recipient_name = recipient_name_input.strip().upper()
    # ここでオンラインチェック
    if recipient_name not in [uid.upper() for uid in online_members_ids]:
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
    message = chan.process_input()

    if not message:
        send_text_by_key(chan, "telegram.no_message", current_menu_mode)
        return

    original_visible_len = len(strip_ansi(message))
    message = truncate_ansi_string(message, telegram_max_len)
    if original_visible_len > telegram_max_len:
        send_text_by_key(
            chan, "telegram.message_truncated", current_menu_mode, max_len=telegram_max_len)

    try:
        current_timestamp = int(time.time())
        # 送信者名は表示名(display_name)を保存
        database.save_telegram(
            display_name, recipient_name, message, current_timestamp)
        send_text_by_key(chan, "telegram.send_success", current_menu_mode)
    except Exception as e:
        logging.warning(
            f"電報保存エラー (送信者: {display_name}, 宛先: {recipient_name}): {e}")
        send_text_by_key(chan, "telegram.send_error", current_menu_mode)


def strip_ansi(text):
    """文字列からANSIエスケープシーケンスを削除する"""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def truncate_ansi_string(text, max_width):
    """
    ANSIエスケープシーケンスを考慮して文字列を指定された表示幅に切り詰める。
    """
    ansi_escape_pattern = re.compile(r'(\x1b\[[0-9;]*m)')

    visible_length = 0
    result_parts = []
    truncated = False

    for part in ansi_escape_pattern.split(text):
        if not part:
            continue

        if ansi_escape_pattern.match(part):
            result_parts.append(part)
        else:
            remaining_width = max_width - visible_length
            if len(part) > remaining_width:
                result_parts.append(part[:remaining_width])
                truncated = True
                break
            else:
                result_parts.append(part)
                visible_length += len(part)

    final_str = "".join(result_parts)
    if truncated and not final_str.endswith('\x1b[0m'):
        final_str += '\x1b[0m'
    return final_str


def telegram_recieve(chan, username, current_menu_mode):
    """受信している電報を表示すして、表示後に削除する"""
    from . import database
    # 電報受信設定を取得
    user_settings = database.get_user_auth_info(username)
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

    results = database.load_and_delete_telegrams(username)
    if not results:
        return

    filterd_telegrams = []
    for teregram in results:
        sender_name = teregram['sender_name']
        # SenderユーザIDを取得
        sender_id = database.get_user_id_from_user_name(sender_name)

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
            sender_short = truncate_ansi_string(sender, 14)
            message_short = truncate_ansi_string(message, 32)

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
        item_input = chan.process_input()

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
    confirm_choice = chan.process_input()

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


def format_file_size(size_in_bytes):
    """ファイルサイズを人間が読みやすい形式にフォーマットする"""
    if not isinstance(size_in_bytes, (int, float)) or size_in_bytes < 0:
        return "0 B"
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    size_in_kb = size_in_bytes / 1024
    if size_in_kb < 1024:
        return f"{size_in_kb:.1f} KB"
    size_in_mb = size_in_kb / 1024
    return f"{size_in_mb:.1f} MB"


def send_push_notification(subscription_info_json, payload_json):
    """
    単一の購読情報に対してプッシュ通知を送信する。
    """
    push_config = app_config.get('push', {})
    # VAPID_PRIVATE_KEY はファイルから直接読み込む
    private_key_path = '/app/private_key.pem'
    claims_email = push_config.get('VAPID_CLAIMS_EMAIL')

    if not os.path.exists(private_key_path) or not claims_email:
        logging.error(
            "VAPID秘密鍵ファイルが見つからないか、連絡先メールアドレスが設定されていません。プッシュ通知は送信されません。")
        return False

    try:
        # PEM形式の秘密鍵ファイルを読み込み、ライブラリが期待する
        # URL-safe Base64エンコードされたDER形式の文字列に変換する
        with open(private_key_path, "rb") as key_file:
            private_key_obj = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
            )
        private_key_der = private_key_obj.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        vapid_private_key_b64 = base64.urlsafe_b64encode(
            private_key_der).rstrip(b'=').decode('utf-8')

        subscription_info = json.loads(subscription_info_json)
        webpush(
            subscription_info=subscription_info,
            data=payload_json,
            vapid_private_key=vapid_private_key_b64,
            vapid_claims={'sub': claims_email}
        )
        return True
    except WebPushException as ex:
        logging.warning(f"Web push failed: {ex}")
        if ex.response:
            logging.warning(
                f"Response: {ex.response.status_code} {ex.response.text}")
        return False
    except Exception as e:
        logging.error(f"プッシュ通知送信中に予期せぬエラー: {e}", exc_info=True)
        return False
