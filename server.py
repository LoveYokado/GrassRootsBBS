import socket
import threading
import paramiko
import sqlite3
import os

import ssh_input

# Paramikoのホストキーを読み込む
host_key = paramiko.RSAKey(filename='test_rsa.key')

bind_host = "0.0.0.0"
bind_port = 50000
dbname = "bbs.db"


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
        conn = sqlite3.connect(dbname)
        cur = conn.cursor()
        sql = 'SELECT * FROM users WHERE name=?'
        data = ("{}".format(login_id),)
        cur.execute(sql, data)
        results = cur.fetchall()
        if results:
            userdata = list(results[0])
            print(userdata[2])
        else:
            userdata = "notid"  # 該当がない場合
            print("該当なし")

        conn.close()
        print(userdata)
        passwordauth = False
        passwordmisscount = 0
        if userdata == "notid":  # 該当IDがない場合は認証できないループへ
            for i in range(3):
                chan.send("PASSWORD: ")
                login_pass = ssh_input.hide_process_input(chan)
                print("攻撃発生:login {}:{}".format(login_id, login_pass))
            chan.send("3回パスワードを間違えました。切断します。")
            transport.close()

        while not passwordauth:  # 該当IDのパスワードを検証
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
                print(f"攻撃が発生している可能性があります: {addr}")

        chan.send("""
--------------------------------\r\n
 Welcome BicliModel BBS Program\r\n
--------------------------------\r\n\n""")

        while True:
            chan.send("Menu(A,B,C,F,H,M,Q,T,U,W H=Help Q=QUit) >> ")
            input_buffer = ssh_input.process_input(chan)

            if input_buffer == "H" or input_buffer == "h":
                chan.send("""
+++++ BBS Menu ++++++++++++++++++++++\r\n
[B] 掲示板     | [A] 未読をすべて読む\r\n
[C] チャット   | [H] ヘルプ\r\n
[F] ファイル   | [T] 電報\r\n
[M] メール     | [W] WHO\r\n
               | [Q] 切断\r\n
+++++++++++++++++++++++++++++++++++++\r\n
"""
                          )

#            if len(input_buffer) == 0:
#                print("クライアントが入力を終了しました。")
#                break
            if input_buffer == "Q" or input_buffer == "q":
                chan.send("また遊びに来てくださいね!\r\n")
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


def make_user_database():
    dbname = 'bbs.db'
    conn = sqlite3.connect(dbname)
    cur = conn.cursor()
    cur.execute(
        'CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,name STRING,password TEXT,registdate DATE,level INT,lastlogin DATETIME,comment STRING,mail STRING)'
    )
    sysopname = input('Input Sysop name: ')
    sysoppass = input('Input Sysop password: ')
    cur.execute("INSERT INTO users(name,password,level) values(?,?,?);", (
                sysopname, sysoppass, 5))

    print(cur.fetchall())
    # データベースへコミット
    conn.commit()

    # Query and display the contents of the "users" table
    cur.execute("SELECT * FROM users;")
    users = cur.fetchall()
    for user in users:
        print(user)

    cur.close()
    conn.close()


if not os.path.isfile('bbs.db'):
    make_user_database()

if __name__ == "__main__":
    main()
