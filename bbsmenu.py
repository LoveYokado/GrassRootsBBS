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
    """受信している電報を表示すして、表示後に削除する"""
    results = sqlite_tools.load_and_delete_telegrams(dbname, username)
    if results:
        chan.send("電報が届きました。\r\n")
        for result in results:
            # カラム順序: 0:id, 1:sender_name, 2:recipient_name, 3:message, 4:timestamp
            sender = result[1]
            message = result[3]
            timestamp_val = result[4]
            try:
                dt_str = datetime.datetime.fromtimestamp(
                    timestamp_val).strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, OSError):
                dt_str = "不明な日時"
            # 表示形式を修正
            chan.send(f"[{dt_str}] From:{sender}: {message}\r\n")
    else:
        pass


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

    while True:
        chan.send("Server Preferences: ")
        input_buffer = ssh_input.process_input(chan)

        if input_buffer is None:
            print("sysop_menu:クライアント切断")
            break
        # input_buffer.lower() の呼び出し方を修正
        if input_buffer.lower() == "q":  # () を追加
            break
        if input_buffer == "":
            for s in sendm:
                chan.send(s + '\r')
            continue

        # --- 設定一覧表示 ---
        if input_buffer == "0":
            server_prefs_list = sqlite_tools.read_server_pref(dbname)
            if server_prefs_list:
                pref_names = ['bbs', 'chat', 'mail',
                              'telegram', 'userpref', 'who']
                chan.send('サーバ設定一覧\r\n')
                chan.send('-'*40+"\r\n")
                chan.send('{:<20} {:<20}\r\n'.format('項目名', '値'))
                chan.send('-'*40+"\r\n")
                for i, name in enumerate(pref_names):
                    if i < len(server_prefs_list):
                        chan.send('{:<20} {:<20}\r\n'.format(
                            name, server_prefs_list[i]))
                    else:
                        chan.send('{:<20} {:<20}\r\n'.format(name, '(取得エラー)'))
                # 区切り線のインデントを修正 (ループの外に出す)
                chan.send('-'*40+"\r\n")
            else:
                chan.send("設定がありません(または取得エラー)\r\n")

        # --- 各BBSメニューのユーザレベルごとのパーミッション ---
        elif input_buffer == "1":
            chan.send("各BBSメニューのユーザレベルごとのパーミッションを設定します\r\n")
            chan.send(
                "ユーザレベルを設定する機能を選択してください(bbs,chat,mail,telegram,userpref,who): ")
            # .lower() の呼び出し方を修正し、None チェックを後にする
            menu_input = ssh_input.process_input(chan)
            if menu_input is None:
                break
            menu_to_change = menu_input.lower()  # None でないことを確認してから lower()

            valid_menus = ['bbs', 'chat', 'mail',
                           'telegram', 'userpref', 'who']
            if menu_to_change not in valid_menus:
                chan.send("有効なメニューを選択してください\r\n")
            else:
                user_level = None
                try:
                    chan.send(
                        "0:無効 1:ゲスト 2:一般ユーザ 3:シグオペ 4:サブオペ 5:シスオペ\r\n")
                    chan.send("ユーザレベルを入力してください(0~5): ")
                    level_input = ssh_input.process_input(chan)
                    if level_input is None:
                        break
                    user_level = int(level_input)

                    # レベル範囲チェック (or を使用し、条件を修正)
                    # user_level = int(ssh_input.process_input(chan)) # <-- この行は不要 (二重入力になる)
                    # if user_level < 0 and user_level > 5: # <-- and ではなく or
                    if user_level < 0 or user_level > 5:  # 修正
                        chan.send("ユーザレベルは0~5の範囲で入力してください\r\n")
                        user_level = None
                except ValueError:
                    chan.send("ユーザレベルは0~5の整数で入力してください\r\n")
                    user_level = None

                if user_level is not None:
                    try:
                        sql = f"UPDATE server_pref SET {menu_to_change}=?"
                        sqlite_tools.sqlite_execute_query(
                            dbname, sql, (user_level,))  # タプルで渡す
                        chan.send(
                            f"{menu_to_change}メニューのユーザレベルを{user_level}に変更しました\r\n")
                    except Exception as e:
                        chan.send(f"データベース更新エラー: {e}\r\n")

        # --- ユーザ情報変更メニュー ---
        # !!! ここからインデントを修正 !!!
        elif input_buffer == "2":  # elif を if/elif と同じレベルに修正
            sendm = util.txt_reads("useredit.txt")
            for s in sendm:
                chan.send(s+'\r')
            chan.send("選択してください: ")
            sub_input = ssh_input.process_input(chan)
            if sub_input is None:
                break

            # --- ユーザ一覧表示 ---
            if sub_input == "1":
                # !!! try ブロックに対応する except ブロックを追加 !!!
                try:
                    sql = "SELECT * FROM users ORDER BY id ASC"
                    users = sqlite_tools.sqlite_execute_query(
                        dbname, sql, fetch=True)

                    if users:
                        chan.send(
                            "ID    ユーザ名     レベル 登録日時             最終ログイン         コメント     メール\r\n")
                        chan.send(
                            "------------------------------------------------------------------------------------------\r\n")
                        for user in users:
                            regdt_ts = user['registdate']
                            lastlogin_ts = user['lastlogin']
                            try:
                                regdt_str = datetime.datetime.fromtimestamp(regdt_ts).strftime(
                                    '%Y-%m-%d %H:%M:%S') if regdt_ts else 'N/A'
                            except (ValueError, OSError):
                                regdt_str = 'Invalid Date'
                            try:
                                lastlogin_str = datetime.datetime.fromtimestamp(lastlogin_ts).strftime(
                                    '%Y-%m-%d %H:%M:%S') if lastlogin_ts else 'N/A'
                            except (ValueError, OSError):
                                lastlogin_str = 'Invalid Date'
                            chan.send(
                                f"{user['id']:<5} {user['name']:<12} {str(user['level']):<6} {regdt_str:<20} {lastlogin_str:<20} {user['comment']:<12} {user['mail']:<12}\r\n")
                        chan.send(
                            "------------------------------------------------------------------------------------------\r\n")
                    else:
                        chan.send("ユーザがいません。\r\n")
                except Exception as e:  # !!! except ブロックを追加 !!!
                    chan.send(f"ユーザ一覧表示中にエラーが発生しました: {e}\r\n")
                    print(f"ユーザ一覧表示中にエラーが発生しました: {e}")

            # --- 他のユーザー編集サブメニュー ---
            elif sub_input == "2":
                chan.send("ユーザー追加は未実装です。\r\n")
            elif sub_input == "3":
                chan.send("ユーザー削除は未実装です。\r\n")
            elif sub_input == "4":
                chan.send("ユーザー情報編集は未実装です。\r\n")
            else:
                chan.send("無効な選択です。\r\n")

        # --- 無効なトップレベルコマンドの場合 ---
        else:  # この else は if/elif と同じレベルにあるべき
            chan.send("無効なコマンドです。\r\n")

    # --- ループを抜けた後の処理 ---
    chan.send("シスオペメニューを終了します。\r\n")
