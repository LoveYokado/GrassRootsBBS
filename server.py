import socket
import threading
import paramiko
import hashlib
import os
import time
import logging

import ssh_input
import util
import bbsmenu
import sqlite_tools
import mail_handler
import socket

HOST_KEY_PATH = 'test_rsa.key'
BIND_HOST = "0.0.0.0"
BIND_PORT = 50000
DBNAME = "bbs.db"
MAX_PASSWORD_ATTEMPTS = 3

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

online_members_lock = threading.Lock()  # ロックオブジェクト作成
online_members = set()


class Server(paramiko.ServerInterface):
    def __init__(self):
        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    # WEBアプリのSSHクライアントからの接続用なので、内部のみで完結するため、このままにしておくｗｗｗ
    def check_auth_password(self, username, password):
        if (username == 'user') and (password == 'pass'):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True  # PTY リクエストを許可

    def check_channel_shell_request(self, channel):

        return True  # シェルリクエストを許可


def logoff_user(chan, dbname, login_id, user_id):
    """ユーザの正常なログオフ処理を行う"""
    global online_members_lock, online_members
    logged_off_successfully = False  # ログオフフラグ

    # ログオフメッセージ表示
    util.show_textsfile(chan, "logoff_message.txt")

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


def process_command_loop(chan, dbname, login_id, user_id, userlevel, server_pref_dict, addr):  # addr を追加
    """
    メインのコマンド処理ループを実行する。

    Args:
        chan: Paramikoチャンネルオブジェクト
        dbname: データベース名
        login_id: ログインID
        user_id: ユーザーID
        userlevel: ユーザーレベル
        server_pref_dict: サーバー設定辞書
        addr: クライアントアドレス (ログ用)

    Returns:
        bool: 正常にログオフした場合はTrue、それ以外はFalse
    """
    normal_logoff = False  # ループ内でログオフ状態を管理
    while True:
        # 定期実行
        util.prompt_handler(chan, dbname, login_id)

        # プロンプト表示
        util.show_textfile(chan, "top_prompt.txt")
        input_buffer = ssh_input.process_input(chan)

        if input_buffer is None:  # クライアント切断
            # ログに addr を追加
            logging.info(f"ユーザ {login_id} が切断しました。({addr})")
            normal_logoff = False  # 異常終了
            break  # ループを抜ける

        command = input_buffer.lower().strip()

        # ヘルプメニュー表示 BIGMODELはヘルプがHと?で別
        if command in ('h'):
            util.show_textsfile(chan, "MENU/MENU.2")
        elif command in ('?'):
            util.show_textsfile(chan, "MENU/MENU_.1")

        # シスオペメニュー
        elif command == "s" and userlevel >= 5:
            bbsmenu.sysop_menu(chan, dbname)

        # オンラインメンバー一覧表示
        elif command == "w" and userlevel >= server_pref_dict.get("who", 1):
            online_list = get_online_members_list()
            bbsmenu.who_menu(chan, dbname, online_list)

        # 電報送信
        elif command in ("t", "!") and userlevel >= server_pref_dict.get("telegram", 1):
            online_list = get_online_members_list()
            bbsmenu.telegram_send(chan, dbname, login_id, online_list)

        # メール送信
        elif command == "m" and userlevel >= server_pref_dict.get("mail", 1):
            mail_handler.mail(chan, dbname, login_id)

        # 掲示板(テスト実装)
        elif command == "b" and userlevel >= server_pref_dict.get("bbs", 1):
            bbsmenu.bbs_menu(chan)

        # チャット
        elif command == "c" and userlevel >= server_pref_dict.get("chat", 1):
            # bbsmenu.chat(chan, dbname, login_id)
            chan.send("チャットはまだ未実装です。\r\n")
            # bbsmenu.mail_recieve(chan, dbname, login_id) # 不要なら削除

        # 切断処理
        elif command == "e":
            normal_logoff = logoff_user(
                chan, dbname, login_id, user_id)
            break  # ループを抜ける

        else:
            util.show_textsfile(chan, "MENU/MENU.2")
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
    try:
        chan.send("** Connect **\r\n\n")
        chan.send("ID: ")

        login_id_input = ssh_input.process_input(chan)
        # --- 修正点1: return を if ブロック内に移動 ---
        if login_id_input is None:
            logging.info(f"ID入力中に切断されました ({addr})")
            return None, None, None  # 切断された場合のみ None を返す

        # --- 修正点3: DBNAME -> dbname に修正 ---
        results = sqlite_tools.fetchall_idbase(
            dbname, 'users', 'name', login_id_input)

        # --- 修正点4: IDが存在しない場合の処理を明確化 ---
        if not results:  # IDが存在しない場合
            logging.warning(f"認証施行: 存在しないID '{login_id_input}' ({addr})")
            password_attempts = 0  # ループ外で使うため初期化
            for i in range(max_password_attempts):
                password_attempts = i + 1  # 試行回数を記録
                chan.send("PASSWORD: ")
                login_pass_attempt = ssh_input.hide_process_input(chan)
                if login_pass_attempt is None:  # 切断された場合
                    logging.info(f"パスワード入力中に切断されました (存在しないID) ({addr})")
                    return None, None, None
                # ダミーのハッシュ計算 (時間はかかるが結果は使わない)
                try:
                    dummy_salt = os.urandom(16)
                    hashlib.pbkdf2_hmac('sha256', login_pass_attempt.encode(
                        'utf-8'), dummy_salt, 100000)
                except Exception:
                    pass  # エラーは無視
                chan.send("IDまたはパスワードが違います。\r\n")
                logging.warning(
                    f"認証失敗 (存在しないID): '{login_id_input}',試行 {password_attempts}/{max_password_attempts} ({addr})")
            # ループが正常に終わった場合（試行回数超過）
            chan.send(f"{max_password_attempts}回以上間違えました。切断します。\r\n")
            return None, None, None  # IDが存在しない場合はここで終了

        # --- ID が存在する場合の処理 (else は不要、上の if で return するため) ---
        userdata = results[0]
        login_id = userdata['name']
        user_id = userdata['id']
        stored_hash = userdata['password']
        salt_hex = userdata['salt']

        if userdata['level'] == 0:
            logging.warning(f"認証失敗: レベル0のID '{login_id}' ({addr})")
            chan.send("このIDは現在利用できません。\r\n")
            return None, None, None

        def verify_password(stored_password_hash, salt_hex, provided_password):
            """入力されたパスワードが保存されたハッシュと一致するか検証"""
            try:
                salt = bytes.fromhex(salt_hex)
                provided_hash = hashlib.pbkdf2_hmac(
                    'sha256',
                    provided_password.encode('utf-8'),
                    salt,
                    100000
                ).hex()

                match = (stored_password_hash == provided_hash)
                return match
            except Exception as e:  # その他の予期せぬエラー
                logging.error(f"パスワード検証中にエラーが発生しました (ユーザー: {login_id}): {e}")
                return False  # 検証失敗

        password_attempts = 0
        while password_attempts < max_password_attempts:
            chan.send("PASSWORD: ")
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
                    f"認証失敗: ID '{login_id}' のパスワード間違い ({password_attempts}/{max_password_attempts}) ({addr})")
                chan.send("IDまたはパスワードが違います。\r\n")

        # パスワード試行回数超過
        chan.send(f"{max_password_attempts}回以上パスワードを間違えました。切断します。\r\n")
        return None, None, None

    except Exception as e:
        logging.error(f"認証プロセス中に予期せぬエラーが発生しました ({addr}): {e}")
        try:
            if chan and chan.active:
                chan.send("\r\n認証中にエラーが発生しました。切断します。\r\n")
        except Exception as chan_e:
            logging.error(f"認証エラー時のメッセージ送信に失敗 ({addr}): {chan_e}")
        return None, None, None


def handle_client(client, addr, host_key):
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
        transport.add_server_key(host_key)
        server = Server()
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

        # ログインプロセス呼び出し
        login_id, user_id, userdata = authenticate_user(
            chan, addr, DBNAME, MAX_PASSWORD_ATTEMPTS)

        # 認証失敗または切断の場合
        if login_id is None:
            return
        # 認証成功の場合のみlogged_inをTrueにする
        logged_in = True

        # ログイン後処理
        try:
            # ログイン時刻記録
            login_time = int(time.time())
            # sqlite_tools.update_idbase の第3引数は許可カラムリスト
            sqlite_tools.update_idbase(
                DBNAME, 'users', ['lastlogin'], user_id, 'lastlogin', login_time)

            # オンラインメンバーに追加
            with online_members_lock:
                online_members.add(login_id)
            logging.info(
                f"ユーザ {login_id} がログインしました。オンライン: {len(online_members)}人")

            # ウェルカムメッセージ
            util.show_textsfile(chan, "MENU/OPENNING.2")

            # サーバ設定読み込み
            pref_list = sqlite_tools.read_server_pref(DBNAME)
            pref_names = ['bbs', 'chat', 'mail',
                          'telegram', 'userpref', 'who']
            if pref_list and len(pref_list) == len(pref_names):
                server_pref_dict = dict(zip(pref_names, pref_list))
            else:
                logging.error("サーバ設定読み込みエラーです。デフォルト値を使用します。")
                default_prefs = {'bbs': 0, 'chat': 1, 'mail': 1,
                                 'telegram': 1, 'userpref': 1, 'who': 1}
                server_pref_dict = default_prefs
            userlevel = userdata['level']

            normal_logoff = process_command_loop(chan, DBNAME, login_id, user_id,
                                                 userlevel, server_pref_dict, addr)

        except Exception as e:
            logging.exception(
                f"クライアント処理中に予期せぬエラーが発生しました({login_id},{addr}): {e}")
            try:
                if chan and chan.active:
                    chan.send("\r\n予期せぬエラーが発生したため、切断します。\r\n")
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

        # 正常ログオフでない場合、かつログイン成功していた場合のみ後処理を試みる
        if logged_in and not normal_logoff:
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
            if user_id is not None:
                try:
                    logout_time = int(time.time())
                    # sqlite_tools.update_idbase の第3引数は許可カラムリスト
                    sqlite_tools.update_idbase(
                        DBNAME, 'users', ['lastlogout'], user_id, 'lastlogout', logout_time)
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


def main():
    # データベース初期化チェック
    if not os.path.isfile(DBNAME):
        logging.info(f"データベースファイル '{DBNAME}'が見つかりません。初期化を実行します。")
        try:
            util.make_sysop_and_database(DBNAME)
            logging.info("データベースの初期化が完了しました。")
        except Exception as e:
            logging.exception(f"データベースの初期化中にエラーが発生しました。: {e}")
            return
    else:
        logging.info(f"データベースファイル '{DBNAME}'を使用します。")

    # ホストキー読み込み
    host_key = None
    try:
        host_key = paramiko.RSAKey(filename=HOST_KEY_PATH)
        logging.info(f"ホストキー '{HOST_KEY_PATH}'を読み込みました。")
    except Exception as e:
        logging.exception(f"ホストキー '{HOST_KEY_PATH}'が見つからないか、読み込めません。")
        print(f"エラー: ホストキー '{HOST_KEY_PATH}' が見つからないか、読み込めません。")
        print("SSHサーバーを起動できません。")
        print("RSAキーを生成してください (例: ssh-keygen -t rsa -f test_rsa.key)")
        return

    # ソケット設定とリスニング
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((BIND_HOST, BIND_PORT))
        sock.listen(5)
        logging.info(f"SSHサーバが {BIND_HOST}:{BIND_PORT} で待機中...")
    except Exception as e:
        logging.exception(
            f"{BIND_HOST}:{BIND_PORT} でのバインドまたはリッスンに失敗しました: {e}")
        if sock:
            sock.close()
        return

    # クライアント接続待機ループ
    try:
        while True:
            client, addr = sock.accept()
            client_thread = threading.Thread(
                target=handle_client, args=(client, addr, host_key), daemon=True)
            client_thread.start()
    except KeyboardInterrupt:
        logging.info("Ctrl+Cを検出しました。サーバをシャットダウンします。")
    except Exception as e:
        logging.exception("メインループで予期せぬエラーが発生しました。")
    finally:
        logging.info("ソケットを閉じています...")
        if sock:
            sock.close()
        logging.info("サーバが停止しました。")


if __name__ == "__main__":
    main()
