import socket
import threading
import paramiko
import os
import time
import logging

import ssh_input
import util
import bbsmenu
import sqlite_tools

# Paramikoのホストキーを読み込む
host_key = paramiko.RSAKey(filename='test_rsa.key')
# USER_COLUMNS = ['name', 'password', 'registdate',
#                'level', 'lastlogin', 'lastlogout', 'comment', 'mail']
bind_host = "0.0.0.0"
bind_port = 50000
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

#    def check_auth_password(self, username, password):
#        if (username == 'user') and (password == 'pass'):
#            return paramiko.AUTH_SUCCESSFUL
#        return paramiko.AUTH_FAILED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True  # PTY リクエストを許可

    def check_channel_shell_request(self, channel):
        return True  # シェルリクエストを許可

# ログオフ処理


def logoff_user(chan, dbname, login_id, user_id):
    """ユーザの正常なログオフ処理を行う"""
    global online_members_lock
    logged_off_successfully = False  # ログオフフラグ

    # ログオフメッセージ表示
    try:
        sendm = util.txt_reads("logoff_message.txt")
        for s in sendm:
            chan.send(s+'\r')
    except FileNotFoundError:
        logging.warning(
            f"ログオフメッセージファイル'logoff_message.txt'が見つかりません ({login_id})")
        chan.send("ログオフします。\y\n")
    except Exception as e:
        logging.error(f"ログオフメッセージ読込中にエラーが発生しました ({login_id}): {e}")

    # オンラインメンバーから削除
    removed_from_list = False
    with online_members_lock:
        if login_id in online_members:
            online_members.remove(login_id)
            logging.info(
                f"ユーザ{login_id}がログオフしました。オンライン: {len(online_members)}人")
            removed_from_list = True
        else:
            logging.worning(
                f"ログオフ処理中にオンラインリストから {login_id}を削除しようとしましたが、見つかりません。")

    # ログアウト時刻記録
    time_recorded = False
    if user_id is not None:
        try:
            logout_time = int(time.time())
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

 # ヘルプ表示関数


def show_help(chan):
    """ヘルプメニューを表示する"""
    try:
        sendm = util.txt_reads("bbsmenu.txt")
        for s in sendm:
            chan.send(s + '\r')
    except FileNotFoundError:
        logging.warning("ヘルプファイル 'bbsmenu.txt' が見つかりません。")
        chan.send("ヘルプファイルが見つかりません。\r\n")
    except Exception as e:
        logging.error(f"ヘルプ表示エラー: {e}")
        chan.send("ヘルプ表示中にエラーが発生しました。\r\n")

# オンラインメンバー取得関数


def get_online_members_list():
    """オンラインメンバーのリストのコピーを返す"""
    with online_members_lock:
        return list(online_members)


def handle_client(client, addr, host_key):
    global online_members
    login_id = None
    user_id = None
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
        except paramiko.SSHException:
            logging.error("SSHネゴシエーションに失敗({addr}): {e}")
            return
        except Exeception as e:
            logging.error(f'サーバ起動中の予期せぬエラー ({addr}): {e}')
            return

        chan = transport.accept(30)
        if chan is None:
            logging.error(f'*** チャンネルを取得できませんでした。({addr})')
            return

        # ログインプロセス開始(後で切り出し)
        chan.send("** Connect **\r\n\n")
        chan.send("ID: ")

        # ID入力がなければ切断
        login_id_input = ssh_input.process_input(chan)
        if login_id_input is None:
            return

        # あとでfetchall_idbase は row_factory を使って辞書を返すように sqlite_tools を修正
        results = sqlite_tools.fetchall_idbase(
            DBNAME, 'users', 'name', login_id)

        if not results:
            logging.warning(f"認証施行: 存在しないID '{login_id_input}' ({addr})")
            # 存在しないIDでもパスワード入力を要求(タイミング攻撃対策)
            for i in range(MAX_PASSWORD_ATTEMPTS):
                chan.send("PASSWORD: ")
                if login_pass_attempt is None:
                    return
                chan.send("IDまたはパスワードが違います。\y\n")
                logging.warning(
                    f"認証失敗 (存在しないID): '{login_id_input}',試行 {i+1}/{MAX_PASSWORD_ATTEMPTS} ({addr})")
                return

        userdata = results[0]
        login_id = userdata['name']
        user_id = userdata['id']

        if userdata['level'] == 0:
            logging.warning(f"認証失敗: レベル0のID '{login_id}' ({addr})")
            chan.send("このIDは現在利用できません。\r\n")
            return
        password_attempts = 0
        while password_attempts < MAX_PASSWORD_ATTEMPTS:
            chan.send("PASSWORD: ")
            login_pass = ssh_input.hide_process_input(chan)
            if login_pass is None:
                return  # 切断

            if login_pass == userdata['password']:
                logging.info(f"認証成功: '{login_id}' ({addr})")
                logged_in = True  # ログイン成功
                break
            else:
                password_attempts += 1
                logging.warning(
                    f"認証失敗:　ID '{login_id}' のパスワード間違い ({password_attempts}/ MAX_PASSWORD_ATTEMPTS) ({addr})")
                chan.send("IDまたはパスワードが違います。\y\n")

        if not logged_in:
            chan.send(f"{MAX_PASSWORD_ATTEMPTS}回以上パスワードを間違えました。切断します。\y\n")
            return

        # ログイン後処理
        try:
            # ログイン時刻記録
            login_time = int(time.time())
            sqlite_tools.update_idbase(
                DBNAME, 'users', ['lastlogin'], user_id, 'lastlogin', login_time)

            # オンラインメンバーに追加
            with online_members_lock:
                online_members.add(login_id)
            logging.info(
                f"ユーザ{login_id}がログインしました。オンライン: {len(online_members)}人")

            # ウェルカムメッセージ
            try:
                sendm = util.txt_reads("welcome_message.txt")
                for s in sendm:
                    chan.send(s+'\r')
            except FileNotFoundError:
                logging.warning(
                    f"ウェルカムメッセージファイル'welcome_message.txt'が見つかりません。")
            except Exception as e:
                logging.error(f"ウェルカムメッセージ処理エラー: {e}")

            # サーバ設定読み込み
            pref_list = sqlite_tools.read_server_pref(DBNAME)
            pref_names = ["bbs_lv", "chat_lv", "mail_lv",
                          "telegram_lv", "userpref_lv", "who_lv"]
            if pref_list and len(pref_list) == len(pref_names):
                server_pref = dict(zip(pref_names, pref_list))
            else:
                logging.error("サーバ設定読み込みエラーです。デフォルト値を使用します。")
                # デフォルト値を設定
                server_pref_dict = dict(zip(pref_names, [0, 1, 1, 1, 1, 1]))
            userlevel = userdata['level']

        # 本ループ開始 後で関数に切り出す
        while True:
            # 定期実行
            util.prompt_handler(chan, DBNAME, login_id)

            # プロンプト表示
            try:
                sendm = util.txt_read("top_prompt.txt")
                chan.send(sendm)
            except FileNotFoundError:
                logging.warning(
                    "プロンプトファイル'top_prompt.txt'が見つかりません。")
            except Exception as e:
                logging.error(f"プロンプト処理エラー: {e}")
                chan.send("> ")

            input_buffer = ssh_input.process_input(chan)

            if input_buffer is None:  # クライアント切断
                logging.info(f"ユーザ{login_id}が切断しました。({addr})")
                break

            command = input_buffer.lower().strip()
            if not command:
                continue

            # サーバ設定を読み込み　後で辞書を使うように変更する
            # ヘルプメニュー表示
            if command in ('h', '?'):
                show_help(chan)

            # シスオペメニュー
            elif command == "s" and userlevel == 5:
                bbsmenu.sysop_menu(chan, DBNAME)

            # オンラインメンバー一覧表示
            elif command == "w" and userlevel >= server_pref_dict.get("who_lv"):
                online_list = get_online_members_list()
                bbsmenu.who_menu(chan, DBNAME, online_list)

            # 電報送信
            elif command in ("t", "!") and userlevel >= server_pref_dict.get("telegram_lv", 1):
                online_list = get_online_members_list()
                bbsmenu.telegram_send(chan, DBNAME, login_id, online_list)

            # メール送信
            elif command == "m" and userlevel >= server_pref_dict.get("mail_lv", 1):
                # bbsmenu.mail_send(chan, DBNAME, login_id)
                chan.send("メールはまだ未実装です。\r\n")

            # チャット
            elif command == "c" and userlevel >= server_pref_dict.get("chat_lv", 1):
                # bbsmenu.chat(chan, DBNAME, login_id)
                chan.send("チャットはまだ未実装です。\r\n")
                bbsmenu.mail_recieve(chan, DBNAME, login_id)

            # 切断処理 (暫定)
            if command == "e":
                normal_logoff = logoff_user(chan, DBNAME, login_id, user_id)
                break

            else:
                chan.send("無効なコマンドです。 (h:ヘルプ)\r\n")

    except Exception as e:
        print(f"例外が発生しました: {e}")
    finally:
        with online_members_lock:  # ロック取得
            try:
                online_members.remove(login_id)  # login_idが定義されているか注意
            except (ValueError, NameError):
                pass  # すでに無いかログイン前に切断された場合
        transport.close()
        print(f"接続を閉じました: {addr}")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_host, bind_port))
    sock.listen(5)

    print(f"SSHサーバーが {bind_host}:{bind_port} で待機中...")

    while True:
        client, addr = sock.accept()
        client_thread = threading.Thread(
            target=handle_client, args=(client, addr, host_key))
        client_thread.start()


# 初起動の場合はデータベース作成とsysop登録を実行
if not os.path.isfile(DBNAME):
    util.make_sysop_and_database(DBNAME)

if __name__ == "__main__":
    main()
