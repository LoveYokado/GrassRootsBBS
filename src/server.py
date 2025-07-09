# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado) <hogehoge@gmail.com>
# SPDX-License-Identifier: MIT

import mail_handler
import sqlite_tools
import bbsmenu
import util
import ssh_input
import threading
import paramiko
import hashlib
import socket
import os
import time
import logging
import datetime

import user_pref_menu
import util
import sysop_menu
import hierarchical_menu
import chat_handler
import bbs_handler
import manual_menu_handler
import hamlet_game

CONFIG_FILE_PATH = "setting/config.toml"

online_members_lock = threading.Lock()  # ロックオブジェクト作成
# オンラインメンバーの構造を set から辞書に変更
# {login_id: {"addr": (ip, port), "display_name": "...", "menu_mode": "..."}}
online_members = {}

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
        paths_config = util.app_config.get('paths', {})

        webapp_user = webapp_config.get('WEBAPP_USER')
        webapp_password = webapp_config.get('WEBAPP_PASSWORD')
        db_name = paths_config.get('db_name')
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
                if util.verify_password(stored_hash, salt_hex, password, pbkdf2_rounds):
                    logging.info(f"パスワード認証成功: ユーザ名'{username}'")
                    return paramiko.AUTH_SUCCESSFUL
                logging.warning(f"パスワード認証失敗(不一致): ユーザ名'{username}'")
            else:
                logging.warning(
                    f"WEBアプリからの接続パスワード認証失敗: ユーザ名'{username}'はパスワード認証が許可されていないか、存在しません。")
            return paramiko.AUTH_FAILED

        logging.warning(
            f"パスワード認証失敗(フォールスルー): ユーザ名'{username}', is_web_app:{self.is_web_app_connection}")
        return paramiko.AUTH_FAILED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):

        # ターミナルタイプをログに出力(debug用)
        logging.debug(
            f"PTY request: term='{term}', width={width}, height={height}, modes={modes}")

        return True  # PTY リクエストを許可

    def check_channel_shell_request(self, channel):

        return True  # シェルリクエストを許可

    def check_auth_publickey(self, username, key):
        if self.is_web_app_connection:
            # webアプリでは公開鍵認証を許可しない
            return paramiko.AUTH_FAILED

        paths_config = util.app_config.get('paths', {})
        db_name = paths_config.get('db_name')
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
        authorized_keys_path = paths_config.get('authorized_keys')
        if not authorized_keys_path:
            logging.error("authorized_keys のパスが設定されていません。")
            return paramiko.AUTH_FAILED

        try:
            with open(authorized_keys_path, 'r', encoding='utf-8') as f:  # Specify encoding
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):  # 空行＋コメントスキップ
                        continue
                    parts = line.strip().split()
                    if len(parts) < 2:
                        continue

                    file_key_type = parts[0]
                    file_key_string = parts[1]

                    # Compare the client's key with the key from the file
                    if key.get_name() == file_key_type and key.get_base64() == file_key_string:
                        # Key matches. Now check if the username in the comment matches.
                        key_comment_user = None
                        if len(parts) > 2:  # Check if there's a comment part
                            # Clean up the comment part for comparison
                            comment_part = " ".join(parts[2:])
                            key_comment_user = comment_part.split('#')[
                                0].strip()

                        if username == key_comment_user or username == "keyuser":  # "keyuser" is a special case
                            logging.info(
                                f"公開鍵認証成功: ユーザ名'{username}' (鍵タイプ: {key.get_name()})")
                            return paramiko.AUTH_SUCCESSFUL
        except FileNotFoundError:  # Corrected exception type for file not found
            logging.error(f"公開鍵ファイル '{authorized_keys_path}' が見つかりません。")
        except Exception as e:
            # Add exc_info
            logging.error(f"公開鍵読み込みまたは比較中に予期せぬエラー: {e}", exc_info=True)
        logging.warning(f"公開鍵認証失敗: ユーザ名'{username}'")
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):

        if self.is_web_app_connection:
            # Webアプリ接続時はパスワード認証のみ
            return 'password'

        server_config = util.app_config.get('server', {})
        paths_config = util.app_config.get('paths', {})
        db_name = paths_config.get('db_name')
        if not db_name:
            logging.error("DB名が設定されていません")
            return ''

        # 通常接続時はDBからユーザの認証設定を取
        user_auth_info = sqlite_tools.get_user_auth_info(db_name, username)
        # logging.debug(f"get_allowed_auths: username='{username}', user_auth_info type: {type(user_auth_info)}, content: {user_auth_info}")

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
        if login_id in online_members.keys():
            del online_members[login_id]
            logging.info(
                f"ユーザ {login_id} がログオフしました。オンライン: {len(online_members.keys())}人")
            removed_from_list = True
        else:
            logging.warning(
                f"ログオフ処理中にオンラインリストから {login_id} を削除しようとしましたが、見つかりません。")

    # ログアウト時刻記録
    time_recorded = False
    # ゲスト(user_id=2)の場合、ログアウト時刻は記録しない
    if user_id is not None and user_id != 2:
        try:
            logout_time = int(time.time())
            # sqlite_tools.update_idbase の第3引数は許可カラムリスト
            sqlite_tools.update_idbase(
                dbname, 'users', ['lastlogout'], user_id, 'lastlogout', logout_time)
            logging.info(f"ユーザ {login_id} (ID:{user_id}) のログアウト時刻を記録しました。")
            time_recorded = True
        except Exception as e:
            logging.error(f"ログアウト時刻記録エラー ({login_id}): {e}")
    else:
        # ゲストの場合は時刻記録をスキップするので、成功とみなす
        time_recorded = True
        logging.warning(
            f"ログオフ処理中に user_id が不明なため、ログアウト時刻を記録できませんでした({login_id})")

    logged_off_successfully = removed_from_list and time_recorded

    return logged_off_successfully


def get_online_members_list():
    """オンラインメンバーのリストのコピーを返す"""
    with online_members_lock:
        # 辞書全体を返すように変更。呼び出し元で必要な情報を取り出す。
        return online_members.copy()


def process_command_loop(chan, dbname, login_id, display_name, user_id, userlevel, server_pref_dict, addr, initial_menu_mode):  # addr, display_name を追加
    """
    メインのコマンド処理ループを実行する。

    Args:
        chan: Paramikoチャンネルオブジェクト
        dbname: データベース名
        login_id: ログインID
        display_name: 表示名 (GUEST(hash)など)
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
        if util.handle_shortcut(chan, dbname, login_id, display_name, current_loop_menu_mode, command, get_online_members_list):
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

        # 新アーティクル自動ダウンロード
        elif command == "a" and userlevel >= server_pref_dict.get("bbs", 1):
            bbsmenu.handle_auto_download(
                chan, dbname, login_id, user_id, userlevel, current_loop_menu_mode
            )
            # 表示後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # シスオペメニュー
        elif command == "s" and userlevel >= 5:
            # シスオペメニュー(menu_mode)
            # sysop_menu から戻ってきたらトップメニューを表示するため、結果を受け取る
            sysop_menu_result = sysop_menu.sysop_menu(chan, dbname, login_id, display_name,
                                                      current_loop_menu_mode)

        # サーバ設定メニュー
        elif command == "v" and userlevel >= 5:
            # サーバ設定メニュー(menu_mode)
            pass

        # オンラインメンバー一覧表示
        elif command == "w" and userlevel >= server_pref_dict.get("who", 1):
            online_members_dict = get_online_members_list()
            bbsmenu.who_menu(chan, dbname, online_members_dict,
                             current_loop_menu_mode)
            # who_menu 表示後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # 電報送信
        elif command in ("#", "!") and userlevel >= server_pref_dict.get("telegram", 1):
            online_members_dict = get_online_members_list()
            util.telegram_send(chan, dbname, display_name,
                               list(online_members_dict.keys()), current_loop_menu_mode)
            # telegram_send 後はトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # ユーザー環境設定
        elif command == "u" and userlevel >= server_pref_dict.get("userpref", 1):
            previous_menu_mode_before_userpref = current_loop_menu_mode
            # userpref_menu は変更後のメニューモード('1','2','3')または"back_to_top"、Noneを返す
            user_pref_result = user_pref_menu.userpref_menu(
                chan, dbname, login_id, display_name, current_loop_menu_mode)

            # After returning from user_pref_menu, reload user data to get the latest lastlogin
            # This is important because user_pref_menu might update lastlogin or menu_mode
            reloaded_user_data = sqlite_tools.get_user_auth_info(
                dbname, login_id)
            # reloaded_user_data を使って何かをする必要があればここに記述
            # 現状は、次に CommandHandler がインスタンス化される際に最新情報が使われることを期待

            if user_pref_result in ('1', '2', '3'):  # 有効なメニューモード文字列が返ってきた場合
                current_loop_menu_mode = user_pref_result  # current_loop_menu_mode を更新
                if current_loop_menu_mode != previous_menu_mode_before_userpref:
                    # メニューモードが実際に変更された場合、新しいモードでトップメニューを表示
                    util.send_text_by_key(
                        chan, "top_menu.menu", current_loop_menu_mode)

        # メール送信
        elif command == "m" and userlevel >= server_pref_dict.get("mail", 1):
            mail_handler_result = mail_handler.mail(
                chan, dbname, login_id, current_loop_menu_mode)
        # 掲示板
        elif command == "b" and userlevel >= server_pref_dict.get("bbs", 1):
            while True:  # 掲示板メニュー内をループ
                bbs_handler_result = None  # ループごとにリセット
                if current_loop_menu_mode in ('2', '3'):
                    paths_config = util.app_config.get('paths', {})
                    bbs_config_path = paths_config.get('bbs_mode3_yaml')
                    selected_item = hierarchical_menu.handle_hierarchical_menu(
                        chan, bbs_config_path, current_loop_menu_mode, menu_type="BBS",
                        dbname=dbname, enrich_boards=True)

                    if selected_item and selected_item.get("type") == "board":
                        item_id = selected_item.get("id")
                        bbs_handler_result = bbs_handler.handle_bbs_menu(
                            chan, dbname, login_id, display_name, current_loop_menu_mode, item_id, addr[0])
                    else:
                        # 階層メニューを抜けた場合
                        break
                else:  # mode1
                    paths_config = util.app_config.get('paths', {})
                    selected_board_id = manual_menu_handler.process_manual_menu(
                        chan, dbname, login_id, current_loop_menu_mode, menu_config_path=paths_config.get(
                            'bbs_mode1_yaml'),
                        initial_menu_id="main_bbs_menu", menu_type="bbs")

                    if selected_board_id and selected_board_id not in ("exit_bbs_menu", "back_to_top", None):
                        bbs_handler_result = bbs_handler.handle_bbs_menu(chan, dbname, login_id, display_name,
                                                                         current_loop_menu_mode, selected_board_id, addr[0])
                    else:
                        # 手書きメニューを抜けた場合
                        if selected_board_id in ("exit_bbs_menu", "back_to_top"):
                            logging.info(
                                f"手書きメニューが終了、またはトップに戻りました: {selected_board_id}")
                        elif selected_board_id is None:
                            logging.info(f"手書きメニュー処理中に切断されました。")
                        break

                # 掲示板から戻ってきたときの処理
                if bbs_handler_result == "back_one_level":
                    # 1階層戻る = ボード選択メニューを再表示
                    continue
                else:
                    # 切断(None)またはその他の理由で掲示板メニューを抜ける
                    break
            # 掲示板メニューから抜けたときにトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # チャット
        elif command == "c" and userlevel >= server_pref_dict.get("chat", 1):
            while True:  # チャットメニュー内をループ
                chat_handler_result = None  # ループごとにリセット
                paths_config = util.app_config.get('paths', {})
                chat_config_path = paths_config.get('chatroom_yaml')
                selected_item = hierarchical_menu.handle_hierarchical_menu(
                    chan, chat_config_path, current_loop_menu_mode, menu_type="CHAT"
                )
                if selected_item:
                    # selected_item の type や id に応じた処理
                    terminal_item_type = selected_item.get("type")
                    item_id = selected_item.get("id")
                    item_name = selected_item.get("name", "未定義の項目")

                    if terminal_item_type == "room":  # チャットでは "room"
                        util.send_text_by_key(
                            chan, "chat.entering_room", current_loop_menu_mode, room_name=item_name, room_id=item_id)
                        chat_handler.set_online_members_function_for_chat(
                            get_online_members_list)  # 関数を渡す
                        chat_handler_result = chat_handler.handle_chat_room(  # 結果を受け取る
                            chan, dbname, login_id, display_name, current_loop_menu_mode, item_id, item_name)
                    else:
                        # 汎用メニューで選択されたが、チャット機能では解釈できないtypeの場合
                        util.send_text_by_key(
                            chan, "common_messages.error", current_loop_menu_mode)
                        logging.warning(
                            f"項目「{item_name}」(ID: {item_id}, Type: {terminal_item_type}) が選択されましたが、この機能では処理できません。")
                        break  # ループを抜ける
                else:
                    # 階層メニューを抜けた場合
                    break

                if chat_handler_result == "back_one_level":
                    continue
                else:
                    break
            # チャットメニューから抜けたときにトップメニューを再表示
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)
        # オンラインサインアップ(config.toml の online_signup 設定で有効/無効を切り替え)
        elif command == "l":
            online_signup_enabled = util.app_config.get(  # serverセクションのキーを大文字に
                'server', {}).get('ONLINE_SIGNUP', False)
            if online_signup_enabled and userlevel == 1:
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

        # ハムレットゲーム
        elif command == "z" and userlevel >= server_pref_dict.get("hamlet", 1):
            hamlet_game.run_game_vs_ai(chan, current_loop_menu_mode)
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        else:
            util.send_text_by_key(chan, "top_menu.help_h",
                                  current_loop_menu_mode)
            # 不明なコマンドの後もトップメニューを表示（ヘルプ表示と同じ扱い）
            util.send_text_by_key(chan, "top_menu.menu",
                                  current_loop_menu_mode)

        # 各ハンドラから "back_to_top" が返ってきた場合にトップメニューを表示
        if mail_handler_result == "back_to_top" or user_pref_result == "back_to_top" or sysop_menu_result == "back_to_top":
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
    paths_config = util.app_config.get('paths', {})
    db_name_from_config = paths_config.get('db_name')
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
        # WebApp接続時のウェルカムメッセージ (AAなど) をID/Pass入力の前に表示
        util.send_text_by_key(
            chan, "login.welcome_message_webapp", menu_mode=auth_menu_mode)
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

        # 認証方法のチェック (Webアプリからの対話認証)
        auth_method = userdata['auth_method'] if 'auth_method' in userdata.keys(
        ) else 'password_only'
        # 'key_only' のユーザーはWebアプリからログインできないようにする
        if auth_method not in ('password_only', 'both', 'webapp_only'):
            logging.warning(
                f"認証失敗: ユーザー '{login_id}' はWebアプリからのパスワード認証が許可されていません (auth_method: {auth_method}) ({addr})")
            util.send_text_by_key(
                chan, "auth.method_not_allowed", menu_mode=auth_menu_mode)
            return None, None, None

        if userdata['level'] == 0:
            logging.warning(f"認証失敗: レベル0のID '{login_id}' ({addr})")
            util.send_text_by_key(
                chan, "auth.account_disabled", menu_mode=auth_menu_mode)  # ID停止通知
            return None, None, None

        password_attempts = 0
        while password_attempts < max_attempts:
            util.send_text_by_key(
                chan, "auth.password_prompt", menu_mode=auth_menu_mode, add_newline=False)  # パスワード入力プロンプト
            login_pass = ssh_input.hide_process_input(chan)
            if login_pass is None:
                logging.info(f"パスワード入力中に切断されました ({login_id}, {addr})")
                return None, None, None

            if util.verify_password(stored_hash, salt_hex, login_pass, pbkdf2_rounds):
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


def handle_client(client, addr, host_keys, is_web_app=True):
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
        for key in host_keys:
            transport.add_server_key(key)
        server = Server(is_web_app_connection=is_web_app)
        try:
            transport.start_server(server=server)
        except paramiko.SSHException as e:
            logging.error(f"SSHネゴシエーションに失敗({addr}): {e}")
            return
        except Exception as e:  # This is the generic error that needs more info
            # Add exc_info=True
            logging.error(f'サーバ起動中の予期せぬエラー ({addr}): {e}', exc_info=True)
            return

        chan = transport.accept(30)
        if chan is None:
            logging.error(f'*** チャンネルを取得できませんでした。({addr})')
            return

        if is_web_app:
            # webアプリの場合paramiko認証が成功してればOK
            # Server.check_auth_password で設定に書かれたID/PASSWORDのSSH認証が行われている前提
            db_name_from_config = util.app_config.get(
                'paths', {}).get('db_name')
            max_attempts_from_config = util.app_config.get(
                # これはserverセクションでOK
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
                    'paths', {}).get('db_name')
                if not db_name_from_config:
                    logging.error("DB名が設定されていません")
                    return

                # 動的ゲストIDに対応するための修正
                id_to_lookup = login_id
                if login_id.upper().startswith('GUEST('):
                    id_to_lookup = 'GUEST'
                    logging.info(
                        f"動的ゲストID '{login_id}' を検出。DB検索用に 'GUEST' を使用します。")

                # SSHユーザ名でDBからユーザ情報を取得
                results = sqlite_tools.fetchall_idbase(
                    db_name_from_config, 'users', 'name', id_to_lookup)
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
                'paths', {}).get('db_name')
            if not db_name_from_config:
                logging.error("DB名が設定されていません")
                return

            # ログイン時刻記録
            login_time = int(time.time())
            # sqlite_tools.update_idbase の第3引数は許可カラムリスト
            sqlite_tools.update_idbase(
                db_name_from_config, 'users', ['lastlogin'], user_id, 'lastlogin', login_time)

            # 表示名を生成
            display_name = util.get_display_name(login_id, addr[0])
            initial_user_menu_mode = userdata['menu_mode'] if 'menu_mode' in userdata.keys(
            ) else '1'

            # オンラインメンバーに追加
            with online_members_lock:
                online_members[login_id] = {
                    "display_name": display_name, "addr": addr, "menu_mode": initial_user_menu_mode}
            logging.info(
                f"ユーザ {login_id}({display_name}) がログインしました。オンライン: {len(online_members)}人")
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

            # 接続方法に応じたログイン後メッセージを表示
            if is_web_app:
                # WebApp経由の場合 (対話認証後)
                util.send_text_by_key(
                    chan, "login.login_message_webapp", initial_user_menu_mode, login_id=login_id, last_login_str=last_login_str)
            else:
                # 通常のSSH接続の場合 (公開鍵認証など)
                util.send_text_by_key(
                    chan, "login.welcome_message_ssh", initial_user_menu_mode, login_id=login_id, last_login_str=last_login_str)

            # ログイン直後のトップメニュー表示
            util.send_text_by_key(
                chan, "top_menu.menu", initial_user_menu_mode)

            # サーバ設定読み込み
            pref_list = sqlite_tools.read_server_pref(db_name_from_config)
            pref_names = ['bbs', 'chat', 'mail', 'telegram',
                          'userpref', 'who', 'default_exploration_list', 'hamlet']
            if pref_list and len(pref_list) >= len(pref_names):
                server_pref_dict = dict(zip(pref_names, pref_list))
            else:
                # sqlite_tools.read_server_pref がデフォルト値を返すようになったため、
                logging.error("サーバ設定読み込みエラーです。デフォルト値を使用します。")
                # 最新のデフォルト値に更新
                default_prefs = {'bbs': 2, 'chat': 2, 'mail': 2,
                                 'telegram': 2, 'userpref': 2, 'who': 2, 'hamlet': 2, 'default_exploration_list': ''}
                server_pref_dict = default_prefs
            userlevel = userdata['level'] if userdata and 'level' in userdata.keys(
            ) else 0

            normal_logoff = process_command_loop(
                chan, db_name_from_config, login_id, display_name, user_id, userlevel, server_pref_dict, addr, initial_user_menu_mode)

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
            _decrement_connections(
                current_webapp_clients_lock, 'current_webapp_clients', 'MAX_CONCURRENT_WEBAPP_CLIENTS', 'Webapp')
        else:
            _decrement_connections(
                current_normal_ssh_clients_lock, 'current_normal_ssh_clients', 'MAX_CONCURRENT_NORMAL_SSH_CLIENTS', '通常SSH')

        # 正常ログオフでない場合、かつログイン成功していた場合のみ後処理を試みる
        if logged_in and not normal_logoff and login_id:
            logging.warning(
                f"予期せぬ切断またはエラーのため、追加のログオフ処理を実行します。: {login_id}")

            # オンラインメンバーから削除 (login_id が None でないことを確認)
            if login_id:
                removed_from_list_finally = False
                with online_members_lock:
                    if login_id in online_members.keys():
                        del online_members[login_id]
                        removed_from_list_finally = True
                        logging.info(
                            f"オンラインリストから {login_id} を削除しました (finally)。オンライン: {len(online_members.keys())}人")

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


def _check_and_increment_connections(lock, counter_name, max_clients_key, client_type_str, addr, log_level=logging.INFO):
    """
    接続上限をチェックし、問題なければカウンタをインクリメントする。

    Args:
        lock (threading.Lock): 使用するロックオブジェクト。
        counter_name (str): グローバルなカウンタ変数名。
        max_clients_key (str): config.toml内の最大接続数設定キー。
        client_type_str (str): ログ出力用のクライアント種別名。
        addr (tuple): クライアントアドレス。
        log_level (int): インクリメント時のログレベル。

    Returns:
        bool: 接続が許可された場合はTrue、拒否された場合はFalse。
    """
    with lock:
        current_clients = globals()[counter_name]
        max_clients = util.app_config.get('server', {}).get(max_clients_key, 0)

        if max_clients > 0 and current_clients >= max_clients:
            logging.info(
                f"{client_type_str}接続上限({max_clients})に達しました。新規接続を拒否します({addr})")
            return False

        globals()[counter_name] += 1
        new_count = globals()[counter_name]
        logging.log(
            log_level, f"{client_type_str}接続カウンタインクリメント: {new_count}/{max_clients}")
        return True


def _decrement_connections(lock, counter_name, max_clients_key, client_type_str, log_level=logging.INFO):
    """
    接続カウンタをデクリメントする。

    Args:
        lock (threading.Lock): 使用するロックオブジェクト。
        counter_name (str): グローバルなカウンタ変数名。
        max_clients_key (str): config.toml内の最大接続数設定キー。
        client_type_str (str): ログ出力用のクライアント種別名。
        log_level (int): デクリメント時のログレベル。
    """
    with lock:
        # max(0, ...) でカウンタが負にならないようにする
        globals()[counter_name] = max(0, globals()[counter_name] - 1)
        new_count = globals()[counter_name]
        max_clients = util.app_config.get('server', {}).get(max_clients_key, 0)
        logging.log(
            log_level, f"{client_type_str}接続カウンタデクリメント: {new_count}/{max_clients}")


def wait_for_connections(sock, host_keys, is_web_app_server):
    """
    指定されたソケットでクライアントからの接続を待ち受け、新しい接続があるたびにhandle_clientを呼び出す。
    """
    while True:
        try:
            client, addr = sock.accept()

            # 接続上限チェックとカウンタインクリメント
            if is_web_app_server:
                allowed = _check_and_increment_connections(
                    current_webapp_clients_lock, 'current_webapp_clients', 'MAX_CONCURRENT_WEBAPP_CLIENTS', 'Webapp', addr, log_level=logging.DEBUG)
            else:
                allowed = _check_and_increment_connections(
                    current_normal_ssh_clients_lock, 'current_normal_ssh_clients', 'MAX_CONCURRENT_NORMAL_SSH_CLIENTS', '通常SSH', addr)

            if not allowed:
                client.close()
                continue

            # スレッド開始
            client_thread = threading.Thread(
                target=handle_client, args=(client, addr, host_keys, is_web_app_server), daemon=True)
            client_thread.start()
        except socket.timeout:
            logging.info(
                f"接続待ち受け中にタイムアウトしました(is_web_app_server={is_web_app_server})。")
            continue
        except Exception as e:
            logging.error(
                f"接続待ち受け中に予期せぬエラーが発生しました(is_web_app_server={is_web_app_server}): {e}", exc_info=True)
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

    # --- 環境変数からシスオペ情報を取得 ---
    # Docker環境での初回起動時に使用される
    sysop_id_from_env = os.getenv('GRASSROOTSBBS_SYSOP_ID')
    if sysop_id_from_env:
        sysop_id_from_env = sysop_id_from_env.strip()
        if '#' in sysop_id_from_env:
            sysop_id_from_env = sysop_id_from_env.split('#')[0].strip()
    sysop_password_from_env = os.getenv('GRASSROOTSBBS_SYSOP_PASSWORD')
    if sysop_password_from_env:
        sysop_password_from_env = sysop_password_from_env.strip()
        if '#' in sysop_password_from_env:
            sysop_password_from_env = sysop_password_from_env.split('#')[
                0].strip()
    sysop_email_from_env = os.getenv('GRASSROOTSBBS_SYSOP_EMAIL')
    if sysop_email_from_env:
        sysop_email_from_env = sysop_email_from_env.strip()
        if '#' in sysop_email_from_env:
            sysop_email_from_env = sysop_email_from_env.split('#')[0].strip()

    # --- ログ設定 ---
    # util.load_app_config_from_path の後で実行
    paths_config = util.app_config.get('paths', {})
    log_dir = paths_config.get('log_dir', 'logs')  # デフォルト値
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 既存のハンドラをクリア
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(
                log_dir, "server.log"), 'a', 'utf-8'),
            logging.StreamHandler()
        ]
    )

    server_config = util.app_config.get('server', {})
    webapp_config = util.app_config.get('webapp', {})

    db_name_from_config = paths_config.get('db_name')
    bind_host_from_config = server_config.get('BIND_HOST', '0.0.0.0')
    host_key_dir_from_config = paths_config.get('host_key_dir')
    webapp_bind_port_from_config = webapp_config.get('WEBAPP_BIND_PORT')
    normal_bind_port_from_config = server_config.get('NORMAL_BIND_PORT_START')
    NORMAL_SSH_PORT_COUNT_from_config = server_config.get(
        'NORMAL_SSH_PORT_COUNT', 1)

    if not db_name_from_config:
        logging.critical("DB名が設定ファイルにありません")
        print("DB名が設定ファイルにありません")
        return

    if not host_key_dir_from_config:
        logging.critical("ホストキーのディレクトリ(paths.host_key_dir)が設定ファイルにありません。")
        return

    # データベース初期化チェック
    if not os.path.isfile(db_name_from_config):
        logging.info(f"データベースファイル '{db_name_from_config}' が見つかりません。初期化を実行します。")
        if not (sysop_id_from_env and sysop_password_from_env and sysop_email_from_env):
            logging.critical(
                "初回起動には環境変数 GRASSROOTSBBS_SYSOP_ID, GRASSROOTSBBS_SYSOP_PASSWORD, GRASSROOTSBBS_SYSOP_EMAIL が必要です。")
            return

        try:
            # 注: util.make_sysop_and_database がIDとパスワードを引数に取るように改修する必要があります。
            util.make_sysop_and_database(
                db_name_from_config, sysop_id_from_env, sysop_password_from_env, sysop_email_from_env)
            logging.info(f"データベースとシスオペ '{sysop_id_from_env}' の初期化が完了しました。")
        except Exception as e:
            logging.exception(
                f"データベースの初期化中にエラーが発生しました。util.pyが引数に対応しているか確認してください。: {e}")
            return
    else:
        logging.info(f"データベースファイル '{db_name_from_config}' を使用します。")

    # ホストキーの準備
    host_keys = []
    try:
        if not os.path.exists(host_key_dir_from_config):
            os.makedirs(host_key_dir_from_config, mode=0o700)
            logging.info(f"ホストキーディレクトリ '{host_key_dir_from_config}' を作成しました。")

        # ディレクトリ内の秘密鍵ファイルを確認
        key_files_exist = any(
            os.path.isfile(os.path.join(host_key_dir_from_config, f)
                           ) and not f.endswith('.pub')
            for f in os.listdir(host_key_dir_from_config)
        )

        if not key_files_exist:
            logging.info(f"ホストキーが見つかりません。新しいRSAキーを生成します。")
            # RSAキー生成
            rsa_key_path = os.path.join(host_key_dir_from_config, 'id_rsa')
            rsa_key = paramiko.RSAKey.generate(4096)
            rsa_key.write_private_key_file(rsa_key_path)
            logging.info(f"新しいRSAホストキーを '{rsa_key_path}' に保存しました。")

        # ディレクトリ内のすべての秘密鍵を読み込む
        for filename in sorted(os.listdir(host_key_dir_from_config)):
            if filename.endswith('.pub'):
                continue
            # authorized_keys はユーザーの公開鍵を格納するファイルであり、ホストキーではないためスキップ
            if filename == os.path.basename(paths_config.get('authorized_keys')):
                continue
            filepath = os.path.join(host_key_dir_from_config, filename)
            if not os.path.isfile(filepath):
                continue
            try:
                key = paramiko.RSAKey(filename=filepath)
                host_keys.append(key)
                logging.info(f"ホストキー '{filepath}' を読み込みました。")
            except (paramiko.SSHException, ValueError) as e:
                logging.warning(f"ホストキー '{filepath}' の読み込みに失敗しました: {e}")

        if not host_keys:
            logging.critical("読み込めるホストキーがありません。サーバを起動できません。")
            return

    except Exception as e:
        logging.exception(f"ホストキーの準備中にエラーが発生しました: {e}")
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
                target=wait_for_connections, args=(webapp_sock, host_keys, True), daemon=True)
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
                            target=wait_for_connections, args=(normal_sock_instance, host_keys, False), daemon=True)
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
