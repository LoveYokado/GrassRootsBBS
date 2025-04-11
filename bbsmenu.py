import ssh_input
import util
import sqlite3
import datetime
import sqlite_tools
import time


def telegram_send(chan, dbname, sender_name, online_members):
    """
    オンラインのメンバーにのみ電報を送信し、データベースに保存する。
    """
    chan.send("電報を送信します (オンラインメンバーのみ)\r\n")
    chan.send("宛先ID: ")
    recipient_name = ssh_input.process_input(chan)

    if not recipient_name:
        chan.send("宛先が入力されていません。\r\n")
        return

    # ここでオンラインチェック
    if recipient_name not in online_members:
        chan.send(f"ID '{recipient_name}' は現在オンラインではありません。\r\n")
        return

    # 自分自身には送れないようにする(テスト中は無効)
    # if recipient_name == sender_name:
    #    chan.send("自分自身に電報を送ることはできません。\r\n")
    #    return

    chan.send("電報メッセージ (最大100文字): ")
    message = ssh_input.process_input(chan)

    if not message:
        chan.send("メッセージが入力されていません。\r\n")
        return

    # メッセージが長すぎる場合の処理（任意）
    if len(message) > 100:
        message = message[:100]
        chan.send("メッセージが長すぎるため、100文字に切り詰めました。\r\n")

    # 電報をデータベースに保存 (sqlite_tools.save_telegram が必要)
    try:
        current_timestamp = int(time.time())
        # sqlite_tools に save_telegram(dbname, sender, recipient, message, timestamp) 関数を実装する想定
        sqlite_tools.save_telegram(
            dbname, sender_name, recipient_name, message, current_timestamp)
        chan.send("電報を送信しました。\r\n")
        # オプション: リアルタイム通知が必要なら、ここで受信側スレッドに通知する仕組みを追加
    except Exception as e:
        # サーバーログ
        print(f"電報保存エラー (送信者: {sender_name}, 宛先: {recipient_name}): {e}")
        chan.send("電報の送信中にエラーが発生しました。\r\n")


def telegram_recieve(chan, dbname, username):
    """受信している電報を表示する"""
    results = sqlite_tools.load_telegram(dbname, username)
    if results:
        for result in results:
            chan.send(
                f"{result[1]}[{str(datetime.datetime.fromtimestamp(result[4]))}]: {result[3]}\r\n")


def who_menu(chan, dbname, onlinemenbers):
    """
    単純にオンラインメンバー一覧を表示するだけ
    """
    chan.send("オンラインメンバー一覧\r\n")
    chan.send("NAME            COMMENT\r\n")
    chan.send(
        "-------------------------------------------------------------------\r\n")
    for menber in onlinemenbers:
        results = sqlite_tools.fetchall_idbase(dbname, 'users', 'name', menber)
        if results != "notdata":
            comment = results[0][7]
            chan.send(f"{menber:<15} {comment} \r\n")
        else:
            chan.send(f"{menber:<15} {'no data'}\r\n")


def sysop_menu(chan, dbname):
    """シスオペメニュー"""
    sendm = util.txt_reads("serverprefmenu.txt")
    for s in sendm:
        chan.send(s + '\r')
        print(s)
    chan.send("Server Preferences: ")
    input_buffer = ssh_input.process_input(chan)
    while input_buffer != "Q" and input_buffer != "q":
        if input_buffer == "":
            for s in sendm:
                chan.send(s + '\r')
                print(s)

        # 設定一覧表示
        if input_buffer == "0":
            conn = sqlite3.connect(dbname)
            cur = conn.cursor()
            cur.execute("SELECT * FROM server_pref;")
            server_prefs = cur.fetchall()
            conn.close()
            if server_prefs:
                chan.send('サーバ設定一覧\r\n')
                chan.send('-'*40+"\r\n")
                chan.send('{:<20} {:<20}\r\n'.format('項目名', '値'))
                chan.send('-'*40+"\r\n")

                for server_pref in server_prefs:
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'bbs', server_pref[0]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'chat', server_pref[1]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'mail', server_pref[2]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'telegram', server_pref[3]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'userpref', server_pref[4]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'who', server_pref[5]))
                    chan.send('-'*40+"\r\n")
            else:
                chan.send("設定がありません\r\n")

        # 各BBSメニューのユーザレベルごとのパーミッション
        if input_buffer == "1":
            chan.send("各BBSメニューのユーザレベルごとのパーミッションを設定します\r\n")
            chan.send(
                "ユーザレベルを設定する機能を選択してください(bbs,chat,mail,telegram,userpref,who): ")
            input_buffer = ssh_input.process_input(chan).lower()
            valid_menus = ['bbs', 'chat', 'mail',
                           'telegram', 'userpref', 'who']
            if input_buffer not in valid_menus:
                chan.send("有効なメニューを選択してください\r\n")
            else:
                try:
                    chan.send("0:無効 1:ゲスト 2:一般ユーザ 3:シグオペ 4:サブオペ 5:シスオペ\r\n")
                    chan.send("ユーザレベルを入力してください(0~5): ")
                    user_level = int(ssh_input.process_input(chan))
                    if user_level < 0 and user_level > 5:
                        chan.send("ユーザレベルは0~5の範囲で入力してください\r\n")
                        chan.send(
                            "0:無効 1:ゲスト 2:一般ユーザ 3:シグオペ 4:サブオペ 5:シスオペ\r\n")
                except ValueError:
                    chan.send("ユーザレベルは0~5の整数で入力してください\r\n")
                try:
                    conn = sqlite3.connect(dbname)
                    cur = conn.cursor()
                    sql = f"UPDATE server_pref SET {input_buffer}=?"
                    cur.execute(sql, (user_level,))
                    conn.commit()
                    chan.send(
                        f"{input_buffer}メニューのユーザレベルを{user_level}に変更しました\r\n")
                except sqlite3.Error as e:
                    chan.send(f"データベースエラー: {e}\r\n")
                finally:
                    if conn:
                        conn.close()

        # ユーザ情報変更メニュー
        if input_buffer == "2":
            sendm = util.txt_reads("useredit.txt")
            for s in sendm:
                chan.send(s + '\r')
                print(s)
            chan.send("選択してください: ")
            input_buffer = ssh_input.process_input(chan)
            # ユーザ一覧表示
            if input_buffer == "1":
                conn = sqlite3.connect(dbname)
                cur = conn.cursor()
                cursol = cur.execute("SELECT * FROM users")
                users = cursol.fetchall()
                chan.send(
                    "ID    ユーザ名     レベル 登録日時             最終ログイン         コメント     メール\r\n")
                for user in users:
                    regdt = str(datetime.datetime.fromtimestamp(
                        user[3]).strftime('%Y-%m-%d %H:%M:%S'))
                    lastlogin = str(datetime.datetime.fromtimestamp(
                        user[5]).strftime('%Y-%m-%d %H:%M:%S'))
                    chan.send(
                        f"{user[0]:<5} {user[1]:<12} {str(user[4]):<6} {regdt:<20} {lastlogin:<20} {user[7]:<12} {user[8]:<12}\r\n")
                conn.close()

        chan.send("Server Preferences: ")
        input_buffer = ssh_input.process_input(chan)
