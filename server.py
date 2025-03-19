import socket
import threading
import paramiko
import os
import time

import ssh_input
import util
from sqlite_tools import *

# Paramikoのホストキーを読み込む
host_key = paramiko.RSAKey(filename='test_rsa.key')
USER_COLUMNS = ['name', 'password', 'registdate',
                'level', 'lastlogin', 'lastlogout', 'comment', 'mail']
bind_host = "0.0.0.0"
bind_port = 50000
DBNAME = "bbs.db"


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
        results = sqlite_fetchall_idbasee(DBNAME, 'users', 'name', login_id)
        print(results[0])
        passwordauth = False
        passwordmisscount = 0
        if results == "notdata":  # 該当IDがない場合は認証できないループへ
            for i in range(3):
                chan.send("PASSWORD: ")
                login_pass = ssh_input.hide_process_input(chan)
                print("攻撃の可能性: login {}:{}".format(login_id, login_pass))
            chan.send("3回パスワードを間違えました。切断します。")
            transport.close()

        while not passwordauth:  # 該当IDのパスワードを検証
            userdata = results[0]
            chan.send("PASSWORD: ")
            login_pass = ssh_input.hide_process_input(chan)
            print("login {}:{}".format(login_id, login_pass))

            if login_pass == userdata[2]:
                break
            else:
                passwordmisscount += 1
            if passwordmisscount > 2:
                chan.send("3回パスワードを間違えました。切断します。")
                transport.close()
                print("攻撃の可能性: {}", format(addr))

        # ログイン時刻記録
        date = time.time()
        sqlite_update_idbase(
            DBNAME, 'users', USER_COLUMNS, userdata[0], 'lastlogin', date)
        # ウェルカムメッセージを送信
        sendm = util.txt_reads("welcome_message.txt")
        for s in sendm:
            chan.send(s+'\r')

        # 本ループ開始
        while True:
            sendm = util.txt_read("top_prompt.txt")
            # プロンプト表示
            chan.send(sendm)
            input_buffer = ssh_input.process_input(chan)

            # ヘルプメニュー表示
            if input_buffer == "H" or input_buffer == "h":
                sendm = util.txt_reads("bbsmenu.txt")
                for s in sendm:
                    chan.send(s + '\r')
                    print(s)

            # 切断処理 (暫定)
            if input_buffer == "E" or input_buffer == "e":
                sendm = util.txt_reads("logoff_message.txt")
                for s in sendm:
                    chan.send(s + '\r')
                    print(s)
                date = time.time()
                sqlite_update_idbase(
                    DBNAME, 'users', USER_COLUMNS, userdata[0], 'lastlogout', date)
                break

    except Exception as e:
        print(f"例外が発生しました: {e}")
    finally:
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
