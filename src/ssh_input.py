import socket
import logging
import unicodedata

# --- 定数定義 ---
# 制御文字を定数として定義し、可読性を向上
BACKSPACE = b'\x08'
DELETE = b'\x7f'
CR = b'\r'
LF = b'\n'
CRLF = b'\r\n'


def _read_line(chan, show_asterisk=False):
    """
    SSHチャンネルから1行読み込む、堅牢なヘルパー関数。

    - Backspace (\\x08) と Delete (\\x7f) の両方に対応。
    - CRLF, CR, LF の異なる改行コードに対応。
    - ソケットエラーを捕捉し、クライアント切断時に None を返す。
    - チャンネルへの送信はバイト列 (bytes) に統一。
    - UTF-8のマルチバイト文字入力に対応。
    """
    input_buffer = ''
    byte_buffer = b''  # UTF-8文字を一時的に保持するバッファ
    try:
        while True:
            # 1バイトずつデータを受信
            data = chan.recv(1)
            if not data:
                logging.info("クライアントが切断されました (recv returned empty)。")
                return None

            # Backspace または Delete キーが押された場合
            if data == BACKSPACE or data == DELETE:
                if byte_buffer:
                    # マルチバイト文字の入力途中であれば、その入力をキャンセル
                    byte_buffer = b''
                elif input_buffer:
                    # 最後の文字をバッファから削除
                    last_char = input_buffer[-1]
                    input_buffer = input_buffer[:-1]
                    # 削除する文字の表示幅を計算
                    # 'F' (Fullwidth), 'W' (Wide), 'A' (Ambiguous) は2カラムとして扱う
                    width = 2 if unicodedata.east_asian_width(
                        last_char) in ('F', 'W', 'A') else 1

                    # 表示幅の分だけカーソルを戻し、空白で上書きし、さらにカーソルを戻す
                    backspace_sequence = (BACKSPACE + b' ' + BACKSPACE) * width
                    chan.send(backspace_sequence)
            # Enterキー (CR) が押された場合
            elif data == CR:
                # Web端末によってはCRの後にLFが続く場合があるため、
                # 短いタイムアウトで次のバイトを覗き見する。
                chan.settimeout(0.02)  # 20ms
                try:
                    next_data = chan.recv(1)
                    # LFが続いていれば、それは改行の一部なので何もしない。
                    # LFでなければ、それは次の入力。paramikoにはpushbackがないため、
                    # この文字は破棄されるが、実用上問題になることは稀。
                    if next_data != LF:
                        pass
                except socket.timeout:
                    # タイムアウト = CR単独の改行
                    pass
                finally:
                    chan.settimeout(None)
                break  # 行の終わり
            # Enterキー (LF) が押された場合
            elif data == LF:
                break  # 行の終わり
            # その他の表示可能な文字
            else:
                byte_buffer += data
                try:
                    # バッファ全体をUTF-8でデコード試行
                    decoded_char = byte_buffer.decode('utf-8')

                    # デコード成功 => 1文字が完成
                    input_buffer += decoded_char
                    if show_asterisk:
                        chan.send(b'*')
                    else:
                        chan.send(byte_buffer)  # デコードできたバイト列をエコーバック
                    byte_buffer = b''  # バッファをクリア
                except UnicodeDecodeError:
                    # マルチバイト文字の途中。次のバイトを待つ
                    continue

        # 入力完了後、新しい行に移動
        chan.send(CRLF)
        return input_buffer

    except (socket.error, EOFError) as e:
        logging.info(f"ソケット通信中にエラーが発生しました: {e}")
        return None


def process_input(chan):
    """ユーザーからの入力を1行読み込み、エコーバックする。"""
    return _read_line(chan, show_asterisk=False)


def hide_process_input(chan):
    """ユーザーからの入力を1行読み込み、'*'でマスクしてエコーバックする。"""
    return _read_line(chan, show_asterisk=True)
