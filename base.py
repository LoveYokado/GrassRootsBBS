import socket
import threading
import paramiko
import codecs

# Paramikoのホストキーを読み込む
host_key = paramiko.RSAKey(filename='test_rsa.key')

bind_host = "0.0.0.0"
bind_port = 50000

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

        chan.send("こんにちは！\r\n")
        chan.send("hodo the world\r\n")

        decoder = codecs.getincrementaldecoder('utf-8')()
        input_buffer = ''
        while True:
            chan.send("Please input something >> ")
            input_buffer = ''
            # インクリメンタルデコーダ用のバッファ
            byte_buffer = b''
            while True:
                data = chan.recv(1024)
                if not data:
                    print("クライアントが切断されました。")
                    return
                byte_buffer += data

                # デコード可能な部分を受け取る
                decoded_text = decoder.decode(data)
                for char in decoded_text:
                    if char in ('\r', '\n'):
                        break
                    input_buffer += char
                    chan.send(char)  # エコー
                else:
                    # 改行が見つからなかった場合、続けて受信
                    continue
                # 改行が見つかった場合、ループを抜ける
                break

            chan.send('\r\n')  # 改行を送信
            if len(input_buffer) == 0:
                print("クライアントが入力を終了しました。")
                break
            response = f"{input_buffer}が入力されちゃったー。\r\n"
            chan.send(response)

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
        client_thread = threading.Thread(target=handle_client, args=(client, addr, host_key))
        client_thread.start()

if __name__ == "__main__":
    main()