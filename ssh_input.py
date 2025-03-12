import codecs


def process_input(chan):
    """インクリメンタルデコーダを使用して入力を処理する関数"""
    decoder = codecs.getincrementaldecoder('utf-8')()
    input_buffer = ''

    # インクリメンタルデコーダ用のバッファ
    byte_buffer = b''
    while True:
        data = chan.recv(1024)
        if not data:
            print("クライアントが切断されました。")
            return None

        byte_buffer += data

        # デコード可能な部分を受け取る
        decoded_text = decoder.decode(data)
        for char in decoded_text:
            if char == '\x08':  # バックスペースの処理
                if input_buffer:
                    # バックスペースが来た場合、最後の文字を削除
                    input_buffer = input_buffer[:-1]
                    chan.send('\x08 \x08')  # バックスペースと空白で消去
            elif char in ('\r', '\n'):
                break
            else:
                input_buffer += char
                chan.send(char)  # エコー
        else:
            # 改行が見つからなかった場合、続けて受信
            continue

        # 改行が見つかった場合、ループを抜ける
        break

    chan.send('\r\n')  # 改行を送信
    return input_buffer


def hide_process_input(chan):
    """非表示で("*"を表示する)エコーする関数"""
    input_buffer = ''

    while True:
        data = chan.recv(1)  # 1文字ずつ受信
        if not data:
            print("クライアントが切断されました。")
            return None

        char = data.decode('ascii')  # ASCII文字としてデコード

        if char == '\x08':  # バックスペースの処理
            if input_buffer:
                input_buffer = input_buffer[:-1]
                chan.send('\x08 \x08')  # バックスペースと空白で消去
        elif char in ('\r', '\n'):
            break
        else:
            input_buffer += char
            chan.send('*')  # '*' を送信

    chan.send('\r\n')
    return input_buffer
