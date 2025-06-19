# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado) <hogehoge@gmail.com>
# SPDX-License-Identifier: MIT

import mail_handler
import sqlite_tools
import bbsmenu
import util
import ssh_input
import socket
import threading
import paramiko
import hashlib
import os
import time
import logging
import base64
import datetime

import user_pref_menu
import util
import sysop_menu
import hierarchical_menu
import chat_handler
import bbs_handler
import manual_menu_handler


CONFIG_FILE_PATH = "setting/config.toml"

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

online_members_lock = threading.Lock()  # ロックオブジェクト作成
online_members = set()

# 同時接続数とロック周り
# webapp
current_webapp_clients = 0
current_webapp_clients_lock = threading.Lock()

# ssh
current_normal_ssh_clients = 0
current_normal_ssh_clients_lock = threading.Lock()


class Server(paramiko.ServerInterface):
    def __init__(self, is_web_app_connection=False):
        """
        ServerInterface の初期化

        :param is_web_app_connection: bool
            WEBアプリケーション経由で接続されたSSHクライアントか否か
        """

        self.event = threading.Event()
        self.is_web_app_connection = is_web_app_connection

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    # WEBアプリのSSHクライアントからの接続用なので、内部のみで完結するため、このままにしておくｗｗｗ
    def check_auth_password(self, username, password):  # パスワード認証
        """
        パスワード認証を処理する。
        通常接続時はDBのユーザー情報と照合。
        """
        webapp_config = util.app_config.get('webapp', {})
        server_config = util.app_config.get('server', {})
        security_config = util.app_config.get('security', {})

        webapp_user = webapp_config.get('WEBAPP_USER')
        webapp_password = webapp_config.get('WEBAPP_PASSWORD')
        db_name = server_config.get('DBNAME')
        pbkdf2_rounds = security_config.get('PBKDF2_ROUNDS', 100000)

        if not db_name:
            logging.error("DB名が設定されていません")
            return paramiko.AUTH_FAILED

        if self.is_web_app_connection and username == webapp_user and password == webapp_password:
            logging.info("WEBアプリからの接続を許可")
            return paramiko.AUTH_SUCCESSFUL

        if not self.is_web_app_connection:
            user_auth_info = sqlite_tools.get_user_auth_info(db_name, username)
            if user_auth_info and user_auth_info['auth_method'] in ('password_only', 'both'):
                stored_hash = user_auth_info['password']
                salt_hex = user_auth_info['salt']
                try:
                    salt = bytes.fromhex(salt_hex)
                    provided_hash = hashlib.pbkdf2_hmac(
                        'sha256',
                        password.encode('utf-8'),
                        salt,
                        pbkdf2_rounds
                    ).hex()
                    if stored_hash == provided_hash:
                        logging.info(f"パスワード認証成功: ユーザ名'{username}'")
                        return paramiko.AUTH_SUCCESSFUL
                except Exception as e:
                    logging.error(f"通常接続パスワード検証中にエラー: ユーザ名'{username}': {e}")
                logging.warning(f"通常接続パスワード認証失敗(不一致): ユーザ名'{username}'")
            else:
                logging.warning(
                    f"WEBアプリからの接続パスワード認証失敗: ユーザ名'{username}'はパスワード認証が許可されていないか、存在しません。")
            return paramiko.AUTH_FAILED

        logging.warning(
            f"パスワード認証失敗(フォールスルー): ユーザ名'{username}', is_web_app:{self.is_web_app_connection}")
        return paramiko.AUTH_FAILED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):

        # ターミナルタイプをログに出力(debug用)
        logging.info(
            f"PTY request: term='{term}', width={width}, height={height}, modes={modes}")

        return True  # PTY リクエストを許可

    def check_channel_shell_request(self, channel):

        return True  # シェルリクエストを許可

    def check_auth_publickey(self, username, key):
        if self.is_web_app_connection:
            # webアプリでは公開鍵認証を許可しない
            return paramiko.AUTH_FAILED

        server_config = util.app_config.get('server', {})
        ssh_config = util.app_config.get('ssh', {})
        db_name = server_config.get('DBNAME')
        if not db_name:
            logging.error("DB名が設定されていません")
            return paramiko.AUTH_FAILED

        # 通常接続時の公開鍵認証
        user_auth_info = sqlite_tools.get_user_auth_info(db_name, username)
        if not user_auth_info or user_auth_info['auth_method'] not in ('key_only', 'both'):
            logging.warning(
                f"公開鍵認証失敗: ユーザ名'{username}'は公開鍵認証が許可されていないか、存在しません。")
            return paramiko.AUTH_FAILED

        logging.info(f"公開鍵認証開始: ユーザ名'{username}' (鍵認証許可ユーザ)")
        key_dir = ssh_config.get('KEY_DIR', '.sshkey')
        auth_keys_filename = ssh_config.get(
            'AUTH_KEYS_FILENAME', 'authorized_keys.pub')
        authorized_keys_path = os.path.join(key_dir, auth_keys_filename)

        try:
            with open(authorized_keys_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):  # 空行＋コメントスキップ
                        continue
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        key_type = parts[0]
                        key_string = parts[1]
                        key_comment_user = None
                        if len(parts) > 2:
                            key_comment_user = parts[2].split('@')[0]
                        auth_key = paramiko.RSAKey(
                            data=base64.b64decode(key_string.encode('ascii')))

                        # 鍵と公開鍵ファイルのコメントユーザ名がSSH接続ユーザ名と一致
                        if key == auth_key and (username == key_comment_user or username == "keyuser"):
                            logging.info(
                                f"公開鍵認証成功: ユーザ名'{username}' (鍵タイプ: {key_type})")
                            return paramiko.AUTH_SUCCESSFUL
        except FileExistsError:
            logging.error(f"公開鍵ファイル '{authorized_keys_path}' が見つかりません。")
        except Exception as e:
            logging.error(f"公開鍵読み込みまたは比較中にエラー: {e}")
        logging.warning(f"公開鍵認証失敗: ユーザ名'{username}'")
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):

        if self.is_web_app_connection:
            # Webアプリ接続時はパスワード認証のみ
            return 'password'

        server_config = util.app_config.get('server', {})
        db_name = server_config.get('DBNAME')
        if not db_name:
            logging.error("DB名が設定されていません")
            return ''

        # 通常接続時はDBからユーザの認証設定を取
        user_auth_info = sqlite_tools.get_user_auth_info(db_name, username)
        logging.debug(
            # デバッグログ追加
            f"get_allowed_auths: username='{username}', user_auth_info type: {type(user_auth_info)}, content: {user_auth_info}")

        if user_auth_info:
            auth_method = user_auth_info['auth_method']
            if auth_method == 'key_only':
                return 'publickey'
            elif auth_method == 'password_only':
                return 'password'
            elif auth_method == 'both':
                return 'publickey,password'
        logging.warning(f"ユーザ名'{username}'の認証タイプ不明、またはユーザ不在。")
        return ''


def logoff_user(chan, dbname, login_id, user_id, menu_mode):
    """ユーザの正常なログオフ処理を行う"""
    global online_members_lock, online_members
    logged_off_successfully = False  # ログオフフラグ

    # ログオフメッセージ表示
    util.send_text_by_key(chan, "logoff.message", menu_mode)

    # オンラインメンバーから削除
    removed_from_list = False
    with online_members_lock:
        if login_id in online_members:
            online_members.remove(login_id)
            logging.info(
                f"ユーザ {login_id} がログオフしました。オンライン: {len(online_members)}人")
            removed_from_list = True
        else:
            logging.warning(
                f"ログオフ処理中にオンラインリストから {login_id} を削除しようとしましたが、見つかりません。")

    # ログアウト時刻記録
    time_recorded = False
    if user_id is not None:
        try:
            logout_time = int(time.time())
            # sqlite_tools.update_idbase の第3引数は許可カラムリスト
            sqlite_tools.update_idbase(
                dbname, 'users', ['lastlogout'], user_id, 'lastlogout', logout_time)
            logging.info(f"ユーザ {login_id} のログアウト時刻を記録しました。")
            time_recorded = True
        except Exception as e:
            logging.error(f"ログアウト時刻記録エラー ({login_id}): {e}")
    else:
        logging.warning(
            f"ログオフ処理中に user_id が不明なため、ログアウト時刻を記録できませんでした({login_id})")

    logged_off_successfully = removed_from_list and time_recorded

    return logged_off_successfully


def get_online_members_list():
    """オンラインメンバーのリストのコピーを返す"""
    with online_members_lock:
        return list(online_members)


def process_command_loop(chan, dbname, login_id, user_id, userlevel, server_pref_dict, addr, initial_menu_mode):  # addr を追加
    """
    メインのコマンド処理ループを実行する。

    Args:
        chan: Paramikoチャンネルオブジェクト
        dbname: データベース名
        login_id: ログインID
        user_id: ユーザーID
        userlevel: ユーザーレベル
        server_pref_dict: サーバー設定辞書
        initial_menu_mode: 初期メニューモード
        addr: クライアントアドレス (ログ用)

    Returns:
        bool: 正常にログオフした場合はTrue、それ以外はFalse
    """
    current_loop_menu_mode = initial_menu_mode
    normal_logoff = False  # ループ内でログオフ状態を管理
    while True:
        # 定期実行
        util.prompt_handler(chan, dbname, login_id, current_loop_menu_mode)

        # プロンプト表示
        util.send_text_by_key(chan, "prompt.topmenu",
                              current_loop_menu_mode, add_newline=False)
        input_buffer = ssh_input.process_input(chan)

        if input_buffer is None:  # クライアント切断
            logging.info(f"ユーザ {login_id} が切断しました。({addr})")
            normal_logoff = False  # 異常終了
            break  # ループを抜ける

        command = input_buffer.lower().strip()

        # bbs_handler_result をループの先頭で初期化
        bbs_handler_result = None
        chat_handler_result = None
        mail_handler_result = None
        user_pref_result = None  # user_pref_menu の結果用
        sysop_menu_result = None  # sysop_menu の結果用
        # 空エンターの場合はトップメニューを再表示
        if command == "":
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)
            continue

        # ショートカット処理
        if util.handle_shortcut(chan, dbname, login_id, current_loop_menu_mode, command, get_online_members_list):
            continue

        # ヘルプメニュー表示 ヘルプがHと?で別にもできる
        if command in ('h'):
            # ヘルプメニュー表示(menu_mode)
            util.send_text_by_key(chan, "top_menu.help_h",
                                  current_loop_menu_mode)
        elif command in ('?'):
            util.send_text_by_key(chan, "top_menu.help_q",
                                  current_loop_menu_mode)
            # ヘルプ表示後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # 自動ダウンロード
        # BBS閲覧権限があれば使用可能
        elif command == "a" and userlevel >= server_pref_dict.get("bbs", 1):
            bbsmenu._handle_auto_download(
                chan, dbname, login_id, user_id, userlevel, current_loop_menu_mode)
            # 表示後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # 新アーティクル探索
        elif command == "n" and userlevel >= server_pref_dict.get("bbs", 1):
            bbsmenu._handle_explore_new_articles(
                chan, dbname, login_id, user_id, userlevel, current_loop_menu_mode
            )
            # 表示後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # 全シグ探索 (X) - BBS閲覧権限があれば使用可能
        elif command == "x" and userlevel >= server_pref_dict.get("bbs", 1):
            default_exploration_list = server_pref_dict.get(
                "default_exploration_list", "")
            bbsmenu._handle_full_sig_exploration(
                chan, dbname, login_id, user_id, userlevel, current_loop_menu_mode, default_exploration_list
            )
            # 表示後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        elif command == "o" and userlevel >= server_pref_dict.get("bbs", 1):

            bbsmenu.handle_new_article_headlines(
                chan, dbname, login_id, user_id, userlevel, current_loop_menu_mode
            )
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # シスオペメニュー
        elif command == "s" and userlevel >= 5:
            # シスオペメニュー(menu_mode)
            # sysop_menu から戻ってきたらトップメニューを表示するため、結果を受け取る
            sysop_menu_result = sysop_menu.sysop_menu(chan, dbname, login_id,
                                                      current_loop_menu_mode)

        # サーバ設定メニュー
        elif command == "v" and userlevel >= 5:
            # サーバ設定メニュー(menu_mode)
            pass

        # オンラインメンバー一覧表示
        elif command == "w" and userlevel >= server_pref_dict.get("who", 1):
            online_list = get_online_members_list()
            bbsmenu.who_menu(chan, dbname, online_list, current_loop_menu_mode)
            # who_menu 表示後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # 電報送信
        elif command in ("t", "!") and userlevel >= server_pref_dict.get("telegram", 1):
            online_list = get_online_members_list()
            util.telegram_send(chan, dbname, login_id,
                               online_list, current_loop_menu_mode)
            # telegram_send 後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # 　ユーザ環境設定(ゲスト以上すべて)
        elif command in ("u") and userlevel >= 1:
            previous_menu_mode_before_userpref = current_loop_menu_mode
            # userpref_menu は変更後のメニューモード('1','2','3')または"back_to_top"、Noneを返す
            user_pref_result = user_pref_menu.userpref_menu(  # 結果を user_pref_result に代入
                chan, dbname, login_id, current_loop_menu_mode)

            if user_pref_result in ('1', '2', '3'):  # 有効なメニューモード文字列が返ってきた場合
                current_loop_menu_mode = user_pref_result  # current_loop_menu_mode を更新
                if current_loop_menu_mode != previous_menu_mode_before_userpref:
                    # メニューモードが実際に変更された場合、新しいモードでトップメニューを表示
                    util.send_text_by_key(
                        chan, "top_menu.menu", current_loop_menu_mode)

        # メール送信
        elif command == "m" and userlevel >= server_pref_dict.get("mail", 1):
            mail_handler.mail(chan, dbname, login_id, current_loop_menu_mode)
            mail_handler_result = mail_handler.mail(
                chan, dbname, login_id, current_loop_menu_mode)
        # 掲示板
        elif command == "b" and userlevel >= server_pref_dict.get("bbs", 1):
            if current_loop_menu_mode in ('2', '3'):
                bbs_config_path = "setting/bbs_mode3.yaml"
                selected_item = hierarchical_menu.handle_hierarchical_menu(
                    chan, bbs_config_path, current_loop_menu_mode, menu_type="BBS",
                    dbname=dbname, enrich_boards=True)
                if selected_item and selected_item.get("type") == "board":
                    item_id = selected_item.get("id")
                    # bbs_handler.handle_bbs_menuを呼ぶ
                    bbs_handler_result = bbs_handler.handle_bbs_menu(  # 結果を受け取る
                        chan, dbname, login_id, current_loop_menu_mode, item_id)
                elif selected_item:  # 念の為boardタイプ以外が選択されたとき
                    util.send_text_by_key(
                        chan, "common_messages.error", current_loop_menu_mode)
                    logging.warning(
                        f"階層メニュー(mode3):項目「{selected_item.get('name')}」(ID: {selected_item.get('id')}, Type: {selected_item.get('type')}) が選択されましたが、boardタイプではありません。")
            else:  # mode1またはmode2の場合は手書きメニュー
                selected_board_id = manual_menu_handler.process_manual_menu(
                    chan, dbname, login_id, current_loop_menu_mode, menu_config_path="setting/bbs_mode1.yaml",
                    initial_menu_id="main_bbs_menu", menu_type="bbs")

                if selected_board_id and selected_board_id not in ("exit_bbs_menu", "back_to_top", None):
                    # Noneチェック追加
                    bbs_handler_result = bbs_handler.handle_bbs_menu(  # 結果を受け取る
                        chan, dbname, login_id, current_loop_menu_mode, selected_board_id)
                elif selected_board_id in ("exit_bbs_menu", "back_to_top"):
                    logging.info(
                        f"手書きメニューが終了、またはトップに戻りました: {selected_board_id}")
                    # 手書きメニューから戻ってきた場合もトップメニューを表示
                    util.send_text_by_key(
                        chan, "top_menu.menu", current_loop_menu_mode)
                elif selected_board_id is None:
                    logging.info(f"手書きメニュー処理中に切断されました。")
        # チャット
        elif command == "c" and userlevel >= server_pref_dict.get("chat", 1):
            chat_config_path = "setting/chatroom.yaml"
            selected_item = hierarchical_menu.handle_hierarchical_menu(
                chan, chat_config_path, current_loop_menu_mode, menu_type="CHAT"
            )
            if selected_item:
                # selected_item の type や id に応じた処理
                terminal_item_type = selected_item.get("type")
                item_id = selected_item.get("id")
                item_name = selected_item.get("name", "未定義の項目")

                if terminal_item_type == "room":  # チャットでは "room"
                    chan.send(
                        f"チャットルーム「{item_name}」(ID: {item_id}) に入室します。\r\n")
                    chat_handler.set_online_members_function_for_chat(
                        get_online_members_list)
                    chat_handler_result = chat_handler.handle_chat_room(  # 結果を受け取る
                        chan, dbname, login_id, current_loop_menu_mode, item_id, item_name)
                else:
                    # 汎用メニューで選択されたが、チャット機能では解釈できないtypeの場合
                    util.send_text_by_key(
                        chan, "common_messages.error",
                        current_loop_menu_mode
                    )
                    logging.warning(
                        f"項目「{item_name}」(ID: {item_id}, Type: {terminal_item_type}) が選択されましたが、この機能では処理できません。\r\n")
        # オンラインサインアップ(config.toml の online_signup 設定で有効/無効を切り替え)
        elif command == "l":
            online_signup_enabled = util.app_config.get(  # serverセクションのキーを大文字に
                'server', {}).get('ONLINE_SIGNUP', False)
            if online_signup_enabled:
                bbsmenu.handle_online_signup(
                    chan, dbname, current_loop_menu_mode)
                util.send_text_by_key(
                    chan, "top_menu.menu", current_loop_menu_mode)
            else:
                util.send_text_by_key(
                    chan, "common_messages.invalid_command", current_loop_menu_mode)
        # 切断処理
        elif command == "e":
            normal_logoff = logoff_user(
                chan, dbname, login_id, user_id, current_loop_menu_mode)
            break  # ループを抜ける

        else:
            util.send_text_by_key(chan, "top_menu.help_h",
                                  current_loop_menu_mode)
            # 不明なコマンドの後もトップメニューを表示（ヘルプ表示と同じ扱い）
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # 各ハンドラから "back_to_top" が返ってきた場合にトップメニューを表示
        if bbs_handler_result == "back_to_top" or chat_handler_result == "back_to_top" or \
           mail_handler_result == "back_to_top" or user_pref_result == "back_to_top" or sysop_menu_result == "back_to_top":
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)
        # コマンドループ終了 (while True)

    return normal_logoff  # ログオフ状態を返す


def authenticate_user(chan, addr, dbname, max_password_attempts):
    """
    ユーザー認証プロセスを実行する。(パスワードハッシュ対応)

    Args:
        chan: Paramikoチャンネルオブジェクト
        addr: クライアントアドレス
        dbname: データベース名
        max_password_attempts: 最大パスワード試行回数

    Returns:
        tuple: 認証成功時は (login_id, user_id, userdata)、失敗時は (None, None, None)
    """
    server_config = util.app_config.get('server', {})
    security_config = util.app_config.get('security', {})
    db_name_from_config = server_config.get('DBNAME')
    auth_menu_mode = server_config.get('DEFAULT_AUTH_MENU_MODE', '1')
    if auth_menu_mode not in ('1', '2', '3'):
        logging.warning("default_auth_menu_mode 設定値不正")
        auth_menu_mode = '1'

    max_attempts = server_config.get('MAX_PASSWORD_ATTEMPTS', 3)
    pbkdf2_rounds = security_config.get('PBKDF2_ROUNDS', 100000)
    if not db_name_from_config:
        logging.error("DB名が設定ファイルにありません(authenticate_user)")
        if chan and chan.active:
            # サーバ設定エラー。シスオペに連絡してください
            util.send_text_by_key(
                chan, "common_messages.db_error", menu_mode=auth_menu_mode)
        return None, None, None

    try:
        util.send_text_by_key(chan, "auth.connect_message",
                              menu_mode=auth_menu_mode)  # 接続メッセージ
        util.send_text_by_key(chan, "auth.id_prompt", menu_mode=auth_menu_mode,
                              add_newline=False)  # ID入力プロンプト

        login_id_input = ssh_input.process_input(chan)
        if login_id_input is None:
            logging.info(f"ID入力中に切断されました ({addr})")
            return None, None, None  # 切断された場合のみ None を返す

        results = sqlite_tools.fetchall_idbase(
            db_name_from_config, 'users', 'name', login_id_input)

        if not results:  # IDが存在しない場合
            logging.warning(f"認証施行: 存在しないID '{login_id_input}' ({addr})")
            password_attempts = 0  # ループ外で使うため初期化
            for i in range(max_attempts):
                password_attempts = i + 1  # 試行回数を記録
                util.send_text_by_key(
                    chan, "auth.password_prompt", menu_mode=auth_menu_mode, add_newline=False)  # パスワード入力プロンプト
                login_pass_attempt = ssh_input.hide_process_input(chan)
                if login_pass_attempt is None:  # 切断された場合
                    logging.info(f"パスワード入力中に切断されました (存在しないID) ({addr})")
                    return None, None, None
                # ダミーのハッシュ計算 (時間はかかるが結果は使わない)
                try:
                    dummy_salt = os.urandom(16)
                    hashlib.pbkdf2_hmac('sha256', login_pass_attempt.encode(
                        'utf-8'), dummy_salt, pbkdf2_rounds)
                except Exception:
                    pass  # エラーは無視
                util.send_text_by_key(
                    chan, "auth.invalid_credentials", menu_mode=auth_menu_mode)  # 認証失敗メッセージ
                logging.warning(
                    f"認証失敗 (存在しないID): '{login_id_input}',試行 {password_attempts}/{max_attempts} ({addr})")
            # ループが正常に終わった場合（試行回数超過）
            util.send_text_by_key(
                chan, "auth.too_many_attempts", menu_mode=auth_menu_mode, max_attempts=max_attempts)
            return None, None, None  # IDが存在しない場合はここで終了

        # ID が存在する場合の処理 (else は不要、上の if で return するため)
        userdata = results[0]
        login_id = userdata['name']
        user_id = userdata['id']
        stored_hash = userdata['password']
        salt_hex = userdata['salt']

        if userdata['level'] == 0:
            logging.warning(f"認証失敗: レベル0のID '{login_id}' ({addr})")
            util.send_text_by_key(
                chan, "auth.account_disabled", menu_mode=auth_menu_mode)  # ID停止通知
            return None, None, None

        def verify_password(stored_password_hash, salt_hex, provided_password):
            """入力されたパスワードが保存されたハッシュと一致するか検証"""
            try:
                salt = bytes.fromhex(salt_hex)
                provided_hash = hashlib.pbkdf2_hmac(
                    'sha256',
                    provided_password.encode('utf-8'),
                    salt,
                    pbkdf2_rounds
                ).hex()

                match = (stored_password_hash == provided_hash)
                return match
            except Exception as e:  # その他の予期せぬエラー
                logging.error(f"パスワード検証中にエラーが発生しました (ユーザー: {login_id}): {e}")
                return False  # 検証失敗

        password_attempts = 0
        while password_attempts < max_attempts:
            util.send_text_by_key(
                chan, "auth.password_prompt", menu_mode=auth_menu_mode, add_newline=False)  # パスワード入力プロンプト
            login_pass = ssh_input.hide_process_input(chan)
            if login_pass is None:
                logging.info(f"パスワード入力中に切断されました ({login_id}, {addr})")
                return None, None, None

            if verify_password(stored_hash, salt_hex, login_pass):
                # 認証成功
                logging.info(f"認証成功: '{login_id}' ({addr})")
                return login_id, user_id, userdata
            else:
                # 認証失敗
                password_attempts += 1
                logging.warning(
                    f"認証失敗: ID '{login_id}' のパスワード間違い ({password_attempts}/{max_attempts}) ({addr})")
                util.send_text_by_key(
                    chan, "auth.invalid_credentials", menu_mode=auth_menu_mode)

        # パスワード試行回数超過
        util.send_text_by_key(
            chan, "auth.too_many_attempts", menu_mode=auth_menu_mode, max_attempts=max_attempts
        )
        return None, None, None

    except Exception as e:
        logging.error(f"認証プロセス中に予期せぬエラーが発生しました ({addr}): {e}")
        try:
            if chan and chan.active:
                util.send_text_by_key(
                    chan, "auth.auth_error", menu_mode=auth_menu_mode)  # 認証中にエラー
        except Exception as chan_e:
            logging.error(f"認証エラー時のメッセージ送信に失敗 ({addr}): {chan_e}")
        return None, None, None


def handle_client(client, addr, host_key, is_web_app=True):
    login_id = None
    user_id = None
    userdata = None
    transport = None
    chan = None
    logged_in = False
    normal_logoff = False

    logging.info(f"接続を受け付けました: {addr}")
    try:
        transport = paramiko.Transport(client)
        # serverクラスのインスタンスを作成、Webアプリ接続かどうかを判別
        transport.add_server_key(host_key)
        server = Server(is_web_app_connection=is_web_app)
        try:
            transport.start_server(server=server)
        except paramiko.SSHException as e:
            logging.error(f"SSHネゴシエーションに失敗({addr}): {e}")
            return
        except Exception as e:
            logging.error(f'サーバ起動中の予期せぬエラー ({addr}): {e}')
            return

        chan = transport.accept(30)
        if chan is None:
            logging.error(f'*** チャンネルを取得できませんでした。({addr})')
            return

        if is_web_app:
            # webアプリの場合paramiko認証が成功してればOK
            # Server.check_auth_password で設定に書かれたID/PASSWORDのSSH認証が行われている前提
            db_name_from_config = util.app_config.get(
                'server', {}).get('DBNAME')
            max_attempts_from_config = util.app_config.get(
                'server', {}).get('MAX_PASSWORD_ATTEMPTS', 3)
            if not db_name_from_config:
                logging.error("DB名が設定されていません(webapp)")
                return
            if transport.is_authenticated():
                # SSH認証は成功。次にBBSアプリケーションレベルの認証を行う。
                logging.info(f"WEBアプリからのSSH接続認証成功。BBS認証に進みます。 ({addr})")
                login_id, user_id, userdata = authenticate_user(
                    chan, addr, db_name_from_config, max_attempts_from_config)
            else:
                logging.error(
                    f"WEBアプリ接続でparamiko認証に失敗しました。(is_authenticated is False ({addr})")
                return
        else:
            # 通常接続の場合(鍵認証)
            if transport.is_authenticated():
                login_id = transport.get_username()
                logging.info(f"SSH接続認証成功。 ユーザ名: {login_id} ({addr})")
                db_name_from_config = util.app_config.get(
                    'server', {}).get('DBNAME')
                if not db_name_from_config:
                    logging.error("DB名が設定されていません")
                    return
                # SSHユーザ名でDBからユーザ情報を取得
                results = sqlite_tools.fetchall_idbase(
                    db_name_from_config, 'users', 'name', login_id)
                if results:
                    userdata = results[0]
                    user_id = userdata['id']
                    user_level_val = userdata['level'] if 'level' in userdata.keys(
                    ) else 0

                    if user_level_val == 0:
                        logging.warning(f"認証失敗: レベル0のID '{login_id}' ({addr})")
                        if chan.active:
                            util.send_text_by_key(
                                chan, "auth.account_disabled", initial_user_menu_mode)
                        return
                    logging.info(
                        f"SSH認証ユーザー情報取得成功: {login_id},UserID:{user_id},Level:{user_level_val}")
                else:
                    logging.warning(
                        f"SSH鍵認証ユーザ '{login_id}'はDBに登録されていません ({addr})")
                    if chan.active:
                        util.send_text_by_key(
                            chan, "auth.account_disabled", initial_user_menu_mode)
                    return
            else:
                logging.warning(f"通常接続でparamiko認証に失敗しました。 ({addr})")
                return

        # 認証失敗
        if login_id is None:
            logging.info(f"認証プロセスが完了しませんでした ({addr})")  # ログレベルをINFOに変更
            return

        logged_in = True

        # ログイン後処理
        try:
            db_name_from_config = util.app_config.get(
                'server', {}).get('DBNAME')
            if not db_name_from_config:
                logging.error("DB名が設定されていません")
                return

            # ログイン時刻記録
            login_time = int(time.time())
            # sqlite_tools.update_idbase の第3引数は許可カラムリスト
            sqlite_tools.update_idbase(
                db_name_from_config, 'users', ['lastlogin'], user_id, 'lastlogin', login_time)

            # オンラインメンバーに追加
            with online_members_lock:
                online_members.add(login_id)
            logging.info(
                f"ユーザ {login_id} がログインしました。オンライン: {len(online_members)}人")
            initial_user_menu_mode = userdata['menu_mode'] if 'menu_mode' in userdata.keys(
            ) else '1'
            # 最終ログイン時刻を文字列化
            last_login_time = userdata['lastlogin'] if userdata and 'lastlogin' in userdata.keys(
            ) else 0
            last_login_str = "なし"
            if last_login_time and last_login_time > 0:
                try:
                    last_login_str = datetime.datetime.fromtimestamp(
                        last_login_time).strftime('%Y-%m-%d %H:%M:%S')
                except (OSError,  TypeError, ValueError):
                    logging.warning(
                        f"最終ログイン時刻の変換に失敗しました。 {last_login_time}")
                    last_login_str = "不明な日時"

            # ウェルカムメッセージ
            util.send_text_by_key(
                chan, "login.welcome_message", initial_user_menu_mode, login_id=login_id, last_login_str=last_login_str)

            # ログイン直後のトップメニュー表示
            util.send_text_by_key(
                chan, "top_menu.menu", initial_user_menu_mode)

            # サーバ設定読み込み
            pref_list = sqlite_tools.read_server_pref(db_name_from_config)
            # default_exploration_list を追加
            pref_names = ['bbs', 'chat', 'mail', 'telegram',
                          'userpref', 'who', 'default_exploration_list']
            if pref_list and len(pref_list) == len(pref_names):
                server_pref_dict = dict(zip(pref_names, pref_list))
            else:
                # sqlite_tools.read_server_pref がデフォルト値を返すようになったため、
                logging.error("サーバ設定読み込みエラーです。デフォルト値を使用します。")
                default_prefs = {'bbs': 0, 'chat': 1, 'mail': 1,
                                 'telegram': 1, 'userpref': 1, 'who': 1}
                server_pref_dict = default_prefs
            userlevel = userdata['level'] if userdata and 'level' in userdata.keys(
            ) else 0

            normal_logoff = process_command_loop(
                chan, db_name_from_config, login_id, user_id, userlevel, server_pref_dict, addr, initial_user_menu_mode)

        except Exception as e:
            logging.exception(
                f"クライアント処理中に予期せぬエラーが発生しました({login_id},{addr}): {e}")
            try:
                if chan and chan.active:
                    # 予期せぬエラーが発生したため、切断します。
                    util.send_text_by_key(
                        chan, "common_messages.unexpected_error", initial_user_menu_mode)
            except:
                pass

    except Exception as e:
        # transport初期化やaccept周りでの予期せぬエラー
        logging.exception(f"ハンドル処理の早い段階でエラーが発生しました ({addr}): {e}")
    finally:
        # 切断処理
        logging.info(
            # normal_logoff が正しく反映されるはず
            f"接続終了処理開始: {addr} (ログインID:{login_id}, 正常ログオフ:{normal_logoff})")

        # 接続数カウンタデクリメント
        if is_web_app:
            with current_webapp_clients_lock:
                global current_webapp_clients
                current_webapp_clients = max(0, current_webapp_clients-1)
                _max_webapp_clients = util.app_config.get(
                    'server', {}).get('MAX_CONCURRENT_WEBAPP_CLIENTS', 0)
                logging.info(
                    f"Webapp接続カウンタデクリメント: {current_webapp_clients}/{_max_webapp_clients}")
        else:
            with current_normal_ssh_clients_lock:
                global current_normal_ssh_clients
                current_normal_ssh_clients = max(
                    0, current_normal_ssh_clients-1)
                _max_normal_clients = util.app_config.get('server', {}).get(
                    'MAX_CONCURRENT_NORMAL_SSH_CLIENTS', 0)
                logging.info(
                    f"通常SSH接続カウンタデクリメント: {current_normal_ssh_clients}/{_max_normal_clients}")

        # 正常ログオフでない場合、かつログイン成功していた場合のみ後処理を試みる
        if logged_in and not normal_logoff and login_id:
            logging.warning(
                f"予期せぬ切断またはエラーのため、追加のログオフ処理を実行します。: {login_id}")

            # オンラインメンバーから削除 (login_id が None でないことを確認)
            if login_id:
                removed_from_list_finally = False
                with online_members_lock:
                    if login_id in online_members:
                        online_members.remove(login_id)
                        removed_from_list_finally = True
                        logging.info(
                            f"オンラインリストから {login_id} を削除しました (finally)。オンライン: {len(online_members)}人")

            # ログアウト時刻記録 (user_id が None でないことを確認)
            if user_id is not None and db_name_from_config:
                try:
                    logout_time = int(time.time())
                    # sqlite_tools.update_idbase の第3引数は許可カラムリスト
                    sqlite_tools.update_idbase(
                        db_name_from_config, 'users', ['lastlogout'], user_id, 'lastlogout', logout_time)
                    logging.info(
                        f"予期せぬ切断のため、ユーザー {login_id} のログアウト時刻を記録しました (finally)。")
                except Exception as e:
                    logging.error(
                        f"予期せぬ切断時のログアウト時刻記録エラー ({login_id}): {e} (finally)")
            # else: # user_id が None の場合のログは不要

        # トランスポートを閉じる
        if transport:
            try:
                transport.close()
            except Exception as e:
                logging.error(f"Transportクローズ中にエラー ({addr}): {e}")
        logging.info(f"接続を閉じました: {addr}")


def wait_for_connections(sock, host_key, is_web_app_server):
    """
    指定されたソケットでクライアントからの接続を待ち受け、新しい接続があるたびにhandle_clientを呼び出す。
    """
    while True:
        try:
            client, addr = sock.accept()

            # 接続上限チェック
            if is_web_app_server:
                with current_webapp_clients_lock:
                    global current_webapp_clients
                    _max_webapp_clients = util.app_config.get(
                        'server', {}).get('MAX_CONCURRENT_WEBAPP_CLIENTS', 0)
                    if _max_webapp_clients > 0 and current_webapp_clients >= _max_webapp_clients:
                        logging.info(
                            f"Webapp接続上限({_max_webapp_clients})に達しました。新規接続を拒否します({addr})")
                        client.close()
                        continue
                    current_webapp_clients += 1
                    # ログ出力のために再度設定値を取得するか、頻繁に使うなら変数で渡す
                    logging.debug(
                        f"Webapp接続カウンタインクリメント: {current_webapp_clients}/{_max_webapp_clients}")
            else:
                with current_normal_ssh_clients_lock:
                    global current_normal_ssh_clients
                    _max_normal_clients = util.app_config.get('server', {}).get(
                        'MAX_CONCURRENT_NORMAL_SSH_CLIENTS', 0)
                    if _max_normal_clients > 0 and current_normal_ssh_clients >= _max_normal_clients:
                        logging.info(
                            f"通常SSH接続上限({_max_normal_clients})に達しました。新規接続を拒否します({addr})")
                        client.close()
                        continue
                    current_normal_ssh_clients += 1
                    # ログ出力のために再度設定値を取得
                    logging.info(
                        f"通常SSH接続カウンタインクリメント: {current_normal_ssh_clients}/{_max_normal_clients}")

            # スレッド開始
            client_thread = threading.Thread(
                target=handle_client, args=(client, addr, host_key, is_web_app_server), daemon=True)
            client_thread.start()
        except socket.timeout:
            logging.info(
                f"接続待ち受け中にタイムアウトしました(is_web_app_server={is_web_app_server})。")
            continue
        except Exception as e:
            logging.error(
                f"接続待ち受け中に予期せぬエラーが発生しました(is_web_app_server={is_web_app_server}): {e}")
            break


def main():
    # 設定読み込み
    try:
        util.load_app_config_from_path(CONFIG_FILE_PATH)
    except Exception as e:
        logging.critical(
            f"設定ファイル '{CONFIG_FILE_PATH}' の読み込みに失敗: {e}。サーバを起動できません。")
        print(f"設定ファイル '{CONFIG_FILE_PATH}' の読み込みに失敗: {e}。サーバを起動できません。")
        return
    server_config = util.app_config.get('server', {})
    webapp_config = util.app_config.get('webapp', {})

    db_name_from_config = server_config.get('DBNAME')
    bind_host_from_config = server_config.get('BIND_HOST', '0.0.0.0')
    webapp_key_path_from_config = webapp_config.get(
        'WEBAPP_KEY_PATH', '.sshkey/webapp_rsa.key')
    webapp_bind_port_from_config = webapp_config.get('WEBAPP_BIND_PORT')
    normal_bind_port_from_config = server_config.get('NORMAL_BIND_PORT_START')
    NORMAL_SSH_PORT_COUNT_from_config = server_config.get(
        'NORMAL_SSH_PORT_COUNT', 1)

    if not db_name_from_config:
        logging.critical("DB名が設定ファイルにありません")
        print("DB名が設定ファイルにありません")
        return
    # データベース初期化チェック
    if not os.path.isfile(db_name_from_config):
        logging.info(
            f"データベースファイル '{db_name_from_config}'が見つかりません。初期化を実行します。")
        try:
            util.make_sysop_and_database(db_name_from_config)
            logging.info("データベースの初期化が完了しました。")
        except Exception as e:
            logging.exception(f"データベースの初期化中にエラーが発生しました。: {e}")
            return
    else:
        logging.info(f"データベースファイル '{db_name_from_config}'を使用します。")

    # ホストキー読み込み
    host_key = None
    try:
        host_key = paramiko.RSAKey(filename=webapp_key_path_from_config)
        logging.info(f"ホストキー '{webapp_key_path_from_config}'を読み込みました。")
    except Exception as e:
        logging.exception(
            f"ホストキー '{webapp_key_path_from_config}'が見つからないか、読み込めません。")
        print(f"エラー: ホストキー '{webapp_key_path_from_config}' が見つからないか、読み込めません。")
        print("SSHサーバーを起動できません。")
        print("RSAキーを生成してください (例: ssh-keygen -t rsa -f test_rsa.key)")
        return

    listening_sockets = []  # 起動したソケット用リスト
    threads = []  # 起動したスレッド用リスト

    # WEBアプリ用ソケット準備とスレッド作成
    if webapp_bind_port_from_config is not None:
        try:
            webapp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            webapp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            webapp_sock.bind(
                (bind_host_from_config, int(webapp_bind_port_from_config)))
            webapp_sock.listen(5)
            logging.info(
                f"WEBアプリ用SSHサーバが{bind_host_from_config}:{webapp_bind_port_from_config}で待機中...")
            listening_sockets.append(webapp_sock)

            web_app_thread = threading.Thread(
                target=wait_for_connections, args=(webapp_sock, host_key, True), daemon=True)
            web_app_thread.start()
            threads.append(web_app_thread)
        except Exception as e:
            logging.exception(
                f"WEBアプリ用ポート{bind_host_from_config}:{webapp_bind_port_from_config}での起動に失敗: {e}")
            # WEBアプリ用がコケたら通常用も起動しないで終了
    else:
        logging.info("WEBアプリのポートが設定されていないため、通常用SSHサーバのみを起動します。")

    # 通常接続用ソケットの準備とスレッド起動
    if normal_bind_port_from_config is not None:
        try:
            num_ports = int(NORMAL_SSH_PORT_COUNT_from_config)
            if num_ports <= 0:
                logging.warning(f"SSHサーバポート数が0以下になっています。")
            else:

                for i in range(int(num_ports)):
                    normal_port = normal_bind_port_from_config+i
                    normal_sock_instance = None
                    try:
                        normal_sock_instance = socket.socket(
                            socket.AF_INET, socket.SOCK_STREAM)
                        normal_sock_instance.setsockopt(
                            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        normal_sock_instance.bind(
                            (bind_host_from_config, int(normal_port)))
                        normal_sock_instance.listen(10)  # ちょっと多めに
                        logging.info(
                            f"通常用SSHサーバが{bind_host_from_config}:{normal_port}で待機中...")
                        listening_sockets.append(normal_sock_instance)

                        normal_thread = threading.Thread(
                            target=wait_for_connections, args=(normal_sock_instance, host_key, False), daemon=True)
                        normal_thread.start()
                        threads.append(normal_thread)
                    except Exception as e:
                        logging.exception(
                            f"通常ポート{bind_host_from_config}:{normal_port}での起動に失敗: {e}")
                        # 失敗したポートがあっても他のポートは頑張って起動する
                        if normal_sock_instance:
                            normal_sock_instance.close()
                            if normal_sock_instance in listening_sockets:
                                listening_sockets.remove(normal_sock_instance)
                        continue
        except Exception as e:
            logging.exception(
                f"通常ポート{bind_host_from_config}:{normal_bind_port_from_config}での起動に失敗: {e}")
    else:
        logging.info("通常接続用ポートが設定されていないので、通常接続用SSHサーバは起動しません。")

    if not any(t.is_alive() for t in threads if t is not None):
        logging.info("接続を受け付けるスレッドがないのでサーバを終了します。")
        for s in listening_sockets:
            if s:
                s.close()
        return

    # webアプリ接続用スレッドスタート
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Ctrl+Cを検出しました。サーバをシャットダウンします。")
    except Exception as e:
        logging.exception("メイン待機ループで予期せぬエラーが発生しました。")
    finally:
        logging.info("すべてのソケットを閉じています...")
        for sock_item in listening_sockets:
            try:
                sock_item.close()
            except Exception as e_sock_close:
                logging.exception(f"ソケットのクローズ中にエラー発生: {e_sock_close}")
        logging.info("サーバが停止しました。")


if __name__ == "__main__":
    main()
