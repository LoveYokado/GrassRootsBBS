import socket
import threading
import paramiko
import os
import time

import ssh_input
import util
import bbsmenu
import sqlite_tools

# Paramikoのホストキーを読み込む
host_key = paramiko.RSAKey(filename='test_rsa.key')
USER_COLUMNS = ['name', 'password', 'registdate',
                'level', 'lastlogin', 'lastlogout', 'comment', 'mail']
bind_host = "0.0.0.0"
bind_port = 50000
DBNAME = "bbs.db"
online_members_lock = threading.Lock()  # ロックオブジェクト作成
online_menbers = []


class Server(paramiko.ServerInterface):
    def __init__(self):
        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        if (username == 'user') and (password == 'pass'):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True  # PTY リクエストを許可

    def check_channel_shell_request(self, channel):
        return True  # シェルリクエストを許可


def handle_client(client, addr, host_key):
    """メインの関数"""
    server_prefs = sqlite_tools.read_server_pref(DBNAME)
    print(f"接続を受け付けました: {addr}")
    try:
        transport = paramiko.Transport(client)
        transport.add_server_key(host_key)
        server = Server()
        try:
            transport.start_server(server=server)
        except paramiko.SSHException:
            print("SSHネゴシエーションに失敗しました。")
            return

        chan = transport.accept(30)
        if chan is None:
            print('*** チャンネルを取得できませんでした。')
            return

        # ログインプロセス開始
        chan.send("** Connect **\r\n\n")
        chan.send("ID: ")

        login_id = ssh_input.process_input(chan)
        # ログインIDを元にユーザ情報を取得
        # [0]:id,[1]:name,[2]:password,[3]:registdate,[4]level,[5]:lastlogin,[6]:lastlogout,[7]:comment,[8]:mail
        results = sqlite_tools.fetchall_idbase(
            DBNAME, 'users', 'name', login_id)
        userdata = results[0]
        passwordauth = False
        passwordmisscount = 0
        # 該当IDがない、もしくはレベルが0場合は認証できないループへ
        if results == "notdata" or userdata[4] == 0:
            for i in range(3):
                chan.send("PASSWORD: ")
                login_pass = ssh_input.hide_process_input(chan)
                print("攻撃の可能性: login {}:{}".format(login_id, login_pass))
            chan.send("3回パスワードを間違えました。切断します。")
            transport.close()

        while not passwordauth:  # 該当IDのパスワードを検証
            chan.send("PASSWORD: ")
            login_pass = ssh_input.hide_process_input(chan)
            if login_pass == userdata[2]:
                break
            else:
                passwordmisscount += 1
            if passwordmisscount > 2:
                chan.send("3回パスワードを間違えました。切断します。")
                transport.close()
                print(f"攻撃の可能性: {addr}")

        # IDからレベルを取得
        userlevel = int(results[0][4])

        # ログイン時刻記録
        date = time.time()
        sqlite_tools.update_idbase(
            DBNAME, 'users', USER_COLUMNS, userdata[0], 'lastlogin', date)

        # オンラインメンバーに追加
        with online_members_lock:  # ロック取得
            online_menbers.append(login_id)

        # ウェルカムメッセージを送信
        sendm = util.txt_reads("welcome_message.txt")
        for s in sendm:
            chan.send(s+'\r')

        # 本ループ開始
        while True:
            server_prefs = util.prompt_handler(chan, DBNAME, login_id)

            # プロンプト表示
            sendm = util.txt_read("top_prompt.txt")
            chan.send(sendm)
            input_buffer = ssh_input.process_input(chan)

            # サーバ設定を読み込み
            bbs_lv, chat_lv, mail_lv, telegram_lv, userpref_lv, who_lv = sqlite_tools.read_server_pref(
                DBNAME)
            # ヘルプメニュー表示
            if input_buffer == "H" or input_buffer == "h":
                sendm = util.txt_reads("bbsmenu.txt")
                for s in sendm:
                    chan.send(s + '\r')

            # シスオペメニュー表示
            if (input_buffer == "S" or input_buffer == "s") and userlevel == 5:
                bbsmenu.sysop_menu(chan, DBNAME)

            # オンラインメンバー一覧表示
            if (input_buffer == "W" or input_buffer == "w") and userlevel >= who_lv:
                bbsmenu.who_menu(chan, DBNAME, online_menbers)

            # 電報送信
            if (input_buffer == "T" or input_buffer == "t" or input_buffer == "!") and userlevel >= telegram_lv:
                bbsmenu.telegram_send(chan, DBNAME, login_id, online_menbers)

            # メール送信
            if (input_buffer == "M" or input_buffer == "m") and userlevel >= mail_lv:
                bbsmenu.mail_send(chan, DBNAME, login_id, online_menbers)

            # メール受信
            if (input_buffer == "N" or input_buffer == "n") and userlevel >= mail_lv:
                bbsmenu.mail_recieve(chan, DBNAME, login_id)

            # 切断処理 (暫定)
            if input_buffer == "E" or input_buffer == "e":
                sendm = util.txt_reads("logoff_message.txt")
                for s in sendm:
                    chan.send(s + '\r')
                # オンラインメンバーから削除
                with online_members_lock:  # ロック取得
                    try:
                        online_menbers.remove(login_id)
                    except ValueError:
                        # すでにリストにない場合のエラー防止
                        print(
                            f"警告: オンラインリストから {login_id}を削除しようとしましたが、見つかりません。")
                # ログアウト時刻記録
                date = time.time()
                sqlite_tools.update_idbase(
                    DBNAME, 'users', USER_COLUMNS, userdata[0], 'lastlogout', date)
                break

    except Exception as e:
        print(f"例外が発生しました: {e}")
    finally:
        with online_members_lock:  # ロック取得
            try:
                online_menbers.remove(login_id)  # login_idが定義されているか注意
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
