# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado) <hogehoge@gmail.com>
# SPDX-License-Identifier: MIT

import threading
import paramiko
import socket
import os
import time
import logging
import datetime

from . import sqlite_tools, util, ssh_input, command_dispatcher

CONFIG_FILE_PATH = "setting/config.toml"

online_members_lock = threading.Lock()  # ロックオブジェクト作成
# オンラインメンバーの構造を set から辞書に変更
# {login_id: {"addr": (ip, port), "display_name": "...", "menu_mode": "..."}}
online_members = {}

# ssh
current_normal_ssh_clients = 0
current_normal_ssh_clients_lock = threading.Lock()


class Server(paramiko.ServerInterface):
    def __init__(self):
        """
        ServerInterface の初期化
        """

        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):  # パスワード認証
        """
        パスワード認証を処理する。
        通常接続時はDBのユーザー情報と照合。
        """
        security_config = util.app_config.get('security', {})
        paths_config = util.app_config.get('paths', {})

        db_name = paths_config.get('db_name')
        pbkdf2_rounds = security_config.get('PBKDF2_ROUNDS', 100000)

        if not db_name:
            logging.error("DB名が設定されていません")
            return paramiko.AUTH_FAILED

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
                f"パスワード認証失敗: ユーザ名'{username}'はパスワード認証が許可されていないか、存在しません。")
        return paramiko.AUTH_FAILED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):

        # ターミナルタイプをログに出力(debug用)
        logging.debug(
            f"PTY request: term='{term}', width={width}, height={height}, modes={modes}")

        return True  # PTY リクエストを許可

    def check_channel_shell_request(self, channel):

        return True  # シェルリクエストを許可

    def check_auth_publickey(self, username, key):
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


def logoff_user(chan, dbname, login_id, display_name, user_id, menu_mode):
    """ユーザの正常なログオフ処理を行う"""
    global online_members_lock, online_members
    logged_off_successfully = False  # ログオフフラグ

    # ログオフメッセージ表示
    util.send_text_by_key(chan, "logoff.message", menu_mode)

    # 接続ログファイルへの記録
    try:
        connection_logger = logging.getLogger('connection_log')
        ip_address = chan.getpeername(
        )[0] if chan.active and chan.getpeername() else "N/A"
        connection_logger.info(
            f"LOGOFF - ID: {login_id}, DisplayName: {display_name}, IP: {ip_address}")
    except Exception as e:
        logging.error(f"ログオフ時の接続ログ記録に失敗 ({login_id}): {e}")

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
    current_menu_mode = initial_menu_mode
    normal_logoff = False
    mail_notified_this_session = False  # 新着メール通知をセッションで1回に制限するフラグ

    while True:
        # プロンプト前の定型処理。通知フラグを渡して、更新されたフラグを受け取る
        _, mail_notified_this_session = util.prompt_handler(
            chan, dbname, login_id, current_menu_mode, mail_notified_this_session
        )
        util.send_text_by_key(chan, "prompt.topmenu",
                              current_menu_mode, add_newline=False)
        input_buffer = ssh_input.process_input(chan)

        if input_buffer is None:
            logging.info(f"ユーザ {login_id} が切断しました。({addr})")
            normal_logoff = False
            break

        command = input_buffer.lower().strip()

        if command == "":
            util.send_text_by_key(chan, "top_menu.menu", current_menu_mode)
            continue

        if util.handle_shortcut(chan, dbname, login_id, display_name, current_menu_mode, command, get_online_members_list):
            continue

        context = {
            'chan': chan,
            'dbname': dbname,
            'login_id': login_id,
            'display_name': display_name,
            'user_id': user_id,
            'userlevel': userlevel,
            'server_pref_dict': server_pref_dict,
            'addr': addr,
            'menu_mode': current_menu_mode,
            'online_members_func': get_online_members_list,
        }

        result = command_dispatcher.dispatch_command(command, context)

        if result['status'] == 'continue':
            if 'new_menu_mode' in result:
                current_menu_mode = result['new_menu_mode']
                util.send_text_by_key(
                    chan, "top_menu.menu", current_menu_mode)
            continue
        elif result['status'] == 'logoff':
            normal_logoff = logoff_user(
                chan, dbname, login_id, display_name, user_id, current_menu_mode)
            break  # ループを抜ける
        elif result['status'] == 'break':
            normal_logoff = False  # 異常終了
            break

    return normal_logoff  # ログオフ状態を返す


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
        server = Server()
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

        # 通常接続の場合(鍵認証 or パスワード認証)
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
                user_level_val = userdata.get('level', 0)
                initial_user_menu_mode = userdata.get('menu_mode', '1')

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
                    # ユーザー情報がないため、メニューモードはデフォルト値'1'を直接使用
                    util.send_text_by_key(
                        chan, "auth.account_disabled", "1")
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

            # マルチログインチェック
            with online_members_lock:
                # GUEST以外のユーザーで、既にログインしているかチェック
                if login_id.upper() != 'GUEST' and login_id in online_members:
                    logging.warning(
                        f"マルチログインが試みられました: {login_id} from {addr}")
                    util.send_text_by_key(
                        chan, "auth.already_logged_in", initial_user_menu_mode)
                    return  # 接続を終了

            # オンラインメンバーに追加
            with online_members_lock:
                online_members[login_id] = {
                    "display_name": display_name, "addr": addr, "menu_mode": initial_user_menu_mode}
            # 接続ログファイルへの記録
            connection_logger = logging.getLogger('connection_log')
            connection_logger.info(
                f"LOGIN - ID: {login_id}, DisplayName: {display_name}, IP: {addr[0]}")

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

            # 通常のSSH接続の場合 (公開鍵認証など)
            util.send_text_by_key(
                chan, "login.welcome_message_ssh", initial_user_menu_mode, login_id=login_id, last_login_str=last_login_str)

            # サーバ設定読み込み
            pref_list = sqlite_tools.read_server_pref(db_name_from_config)
            pref_names = ['bbs', 'chat', 'mail', 'telegram',
                          'userpref', 'who', 'default_exploration_list', 'hamlet', 'login_message']
            if pref_list and len(pref_list) >= len(pref_names):
                server_pref_dict = dict(zip(pref_names, pref_list))
            else:
                # sqlite_tools.read_server_pref がデフォルト値を返すようになったため、
                logging.error("サーバ設定読み込みエラーです。デフォルト値を使用します。")
                # 最新のデフォルト値に更新
                default_prefs = {'bbs': 2, 'chat': 2, 'mail': 2, 'telegram': 2,
                                 'userpref': 2, 'who': 2, 'hamlet': 2,
                                 'default_exploration_list': '', 'login_message': ''}
                server_pref_dict = default_prefs

            # 「今日の一言」表示
            if server_pref_dict and 'login_message' in server_pref_dict and server_pref_dict['login_message']:
                util.send_text_by_key(chan, "login.daily_message", initial_user_menu_mode,
                                      message=server_pref_dict['login_message'])

            # ログイン直後のトップメニュー表示
            util.send_text_by_key(
                chan, "top_menu.menu", initial_user_menu_mode)

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
        _decrement_connections(
            current_normal_ssh_clients_lock, 'current_normal_ssh_clients', 'MAX_CONCURRENT_NORMAL_SSH_CLIENTS', '通常SSH')

        # 正常ログオフでない場合、かつログイン成功していた場合のみ後処理を試みる
        if logged_in and not normal_logoff and login_id:
            logging.warning(
                f"予期せぬ切断またはエラーのため、追加のログオフ処理を実行します。: {login_id}")

            # 接続ログファイルへの記録 (異常切断)
            connection_logger = logging.getLogger('connection_log')
            display_name_for_log = util.get_display_name(
                login_id, addr[0])
            connection_logger.info(
                f"DISCONNECT - ID: {login_id}, DisplayName: {display_name_for_log}, IP: {addr[0]}")
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


def wait_for_connections(sock, host_keys):
    """
    指定されたソケットでクライアントからの接続を待ち受け、新しい接続があるたびにhandle_clientを呼び出す。
    """
    while True:
        try:
            client, addr = sock.accept()

            # 接続上限チェックとカウンタインクリメント
            allowed = _check_and_increment_connections(
                current_normal_ssh_clients_lock, 'current_normal_ssh_clients', 'MAX_CONCURRENT_NORMAL_SSH_CLIENTS', '通常SSH', addr)

            if not allowed:
                client.close()
                continue

            # スレッド開始
            client_thread = threading.Thread(
                target=handle_client, args=(client, addr, host_keys), daemon=True)
            client_thread.start()
        except socket.timeout:
            logging.info(
                f"接続待ち受け中にタイムアウトしました。")
            continue
        except Exception as e:
            logging.error(
                f"接続待ち受け中に予期せぬエラーが発生しました: {e}", exc_info=True)
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

    # 接続ログ用のロガーをセットアップ
    connection_logger = logging.getLogger('connection_log')
    connection_logger.setLevel(logging.INFO)
    # ログが親ロガー(root)に伝播しないようにする
    connection_logger.propagate = False
    # ハンドラが既に追加されているかチェック (複数回mainが呼ばれる可能性を考慮)
    if not connection_logger.handlers:
        conn_log_path = os.path.join(log_dir, "connection.log")
        conn_handler = logging.FileHandler(conn_log_path, 'a', 'utf-8')
        # フォーマットは時刻とメッセージのみ
        conn_formatter = logging.Formatter('%(asctime)s - %(message)s')
        conn_handler.setFormatter(conn_formatter)
        connection_logger.addHandler(conn_handler)

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
                            target=wait_for_connections, args=(normal_sock_instance, host_keys), daemon=True)
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
