import codecs
import socket
import logging


def realtime_input(chan):
    """実装実験、リアルタイム文字入力を実装する"""
    input_buffer = ''
    while True:
        data = chan.recv(1)  # 1バイトずつデータを受信
        # ascii以外は無視
        try:
            char = data.decode('ascii')
        except UnicodeDecodeError:
            continue
        if char.isprintable() and ord(char) < 128:
            input_buffer += char
            return (char)


def _read_line_robust(chan, show_asterisk=False):
    """
    SSHチャンネルから1行読み込むヘルパー関数。
    CRLF, CR, LFの改行に対応し、Web-based terminalからの入力を安定させる。
    """
    input_buffer = ''
    while True:
        data = chan.recv(1)
        if not data:
            logging.info("クライアントが切断されました。")
            return None  # Connection closed

        try:
            char = data.decode('ascii')
        except UnicodeDecodeError:
            continue  # Ignore non-ascii characters

        if char == '\x08':  # Backspace
            if input_buffer:
                input_buffer = input_buffer[:-1]
                chan.send('\x08 \x08')
        elif char == '\r':
            # CRを検出。LFが続くかチェックし、続くなら読み飛ばす。
            chan.settimeout(0.02)  # 20msの短いタイムアウト
            try:
                next_data = chan.recv(1)
                if next_data != b'\n':
                    # LFでなかった場合、この文字は次の入力の一部かもしれない。
                    # paramikoにはpushbackがないため、このケースは無視する。
                    # ほとんどのクライアントはCRLFかLFを送るので、実用上問題になりにくい。
                    pass
            except socket.timeout:
                # タイムアウトした = LFは来なかった
                pass
            finally:
                chan.settimeout(None)
            break  # CRを検出したらループを抜ける
        elif char == '\n':
            # LFのみを検出した場合もループを抜ける
            break
        else:
            if char.isprintable():
                input_buffer += char
                if show_asterisk:
                    chan.send('*')
                else:
                    chan.send(char)

    chan.send('\r\n')
    return input_buffer


def process_input(chan):
    """インクリメンタルデコーダを使用して入力を処理する関数"""
    return _read_line_robust(chan, show_asterisk=False)


def hide_process_input(chan):
    """非表示で("*"を表示する)エコーする関数"""
    return _read_line_robust(chan, show_asterisk=True)
