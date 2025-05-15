import ssh_input
import util
import datetime
import sqlite_tools
import time
import yaml

CMD_SHOW_PREFS = "0"
CMD_SET_PERMISSIONS = "1"
CMD_USER_EDIT = "2"


def bbs_menu(chan):
    """BBSメニュー"""
    rtinput = ''
    while rtinput != 'e':
        rtinput = ssh_input.realtime_input(chan)
        chan.send(rtinput)

    return


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
        chan.send("--- 電報が届いています ---\r\n")  # 見出しを追加
        for result in results:
            sender = result['sender_name']
            message = result['message']
            timestamp_val = result['timestamp']
            try:
                dt_str = datetime.datetime.fromtimestamp(
                    timestamp_val).strftime('%Y-%m-%d %H:%M')  # 秒は省略しても良いかも
            except (ValueError, OSError, TypeError):  # TypeError も考慮
                dt_str = "不明な日時"
            # 表示形式を修正
            chan.send(f"[{dt_str}] From:{sender}: {message}\r\n")
        chan.send("--- 電報ここまで ---\r\n")  # 終了を示す
    else:
        # 電報がない場合は何も表示しない
        pass


# ... (他の関数)


def userpref_menu(chan, dbname, login_id, current_menu_mode):
    """ユーザー設定メニュー"""
    util.send_text_by_key(chan, "user_pref_menu.header",
                          current_menu_mode)  # メニュー表示

    while True:
        util.show_textfile(chan, "userpref/prompt",
                           current_menu_mode)  # プロンプト表示
        input_buffer = ssh_input.process_input(chan)
        if input_buffer is None:
            break  # 接続が切れた場合

        command = input_buffer.lower().strip()
        if command == '1':
            new_mode_after_change = change_menu_mode(
                chan, dbname, login_id, current_menu_mode)
            if new_mode_after_change and new_mode_after_change != current_menu_mode:
                current_menu_mode = new_mode_after_change
                util.show_textsfile(chan, "MENU/USER_", current_menu_mode)
                continue
        elif command == '2':
            # パスワード変更
            change_password(chan, dbname, login_id)
        elif command == '3':
            # プロフィール変更
            change_profile(chan, dbname, login_id)
        elif command == '4':
            # 会員リスト表示
            show_member_list(chan, dbname, current_menu_mode)
        elif command == '5':
            # 最終ログイン日時仮設定 (未実装)
            chan.send("最終ログイン日時仮設定は未実装です。\r\n")
        elif command == '6':
            # 探索リスト登録 (未実装)
            chan.send("探索リスト登録は未実装です。\r\n")
        elif command == '7':
            # 探索リスト読み出し (未実装)
            chan.send("探索リスト読み出しは未実装です。\r\n")
        elif command == '8':
            # 元探索リスト読み出し (未実装)
            chan.send("元探索リスト読み出しは未実装です。\r\n")
        elif command == '9':
            # 電報受信制限 (未実装)
            chan.send("電報受信制限は未実装です。\r\n")
        elif command == 'e' or command == '':
            break  # メニューから抜ける
        elif command == 'h' or command == '?':
            util.send_text_by_key(
                chan, "user_pref_menu.header", current_menu_mode)  # メニュー再表示
        else:
            chan.send("無効なコマンドです。\r\n")


def change_menu_mode(chan, dbname, login_id, current_menu_mode):
    """メニューモード変更"""
    user_id = sqlite_tools.get_user_id_from_user_name(dbname, login_id)
    if user_id is None:
        chan.send("ユーザー情報が見つかりません。\r\n")
        return None
    while True:
        util.show_textsfile(
            chan, "userpref/menu_mode_select", current_menu_mode)
        choice = ssh_input.process_input(chan)
        if choice is None:
            return None  # 切断

        choice = choice.upper().strip()
        new_menu_mode = None
        if choice == '1':
            new_menu_mode = '1'
        elif choice == '2':
            new_menu_mode = '2'
        elif choice == '3':
            new_menu_mode = '3'
        elif choice == 'e' or choice == '':
            return None
        else:
            continue

        if new_menu_mode:
            if sqlite_tools.update_user_menu_mode(dbname, user_id, new_menu_mode):
                chan.send(f"メニューモードを {new_menu_mode} に変更しました。\r\n")
                return new_menu_mode
            else:
                chan.send("メニューモードの変更に失敗しました。\r\n")
            return None


def show_member_list(chan, dbname, current_menu_mode):
    """会員リストを表示する"""
    util.show_textfile(
        chan, "userpref/search_input", current_menu_mode)
    search_word = ssh_input.process_input(chan)
    member_list = sqlite_tools.get_memberlist(dbname, search_word)
    if member_list:
        for member in member_list:
            chan.send(
                f"{member.get('name', 'N/A')} {member.get('comment', 'N/A')}\r\n")
    else:
        chan.send("会員リストは空です。\r\n")


def who_menu(chan, dbname, online_members, current_menu_mode):
    """
    オンラインメンバー一覧を表示する
    """
    chan.send("オンラインメンバー一覧\r\n")
    chan.send("NAME            COMMENT\r\n")
    chan.send(
        "-------------------------------------------------------------------\r\n")
    if not online_members:
        chan.send("現在オンラインのメンバーはいません。\r\n")  # メッセージ修正
        return

    for member_name in online_members:
        # fetchall_idbase はリストを返す。ユーザー名は UNIQUE なので結果は 0 or 1 件
        results = sqlite_tools.fetchall_idbase(
            dbname, 'users', 'name', member_name)
        if results:  # 結果が存在する場合
            userdata = results[0]
            comment = userdata['comment'] if userdata['comment'] else "(コメントなし)"
            chan.send(f"{member_name:<15} {comment} \r\n")
        else:
            # 基本的に online_members にいるユーザーは DB に存在するはずだが念のため
            chan.send(f"{member_name:<15} {'(ユーザー情報取得エラー)'}\r\n")
            print(f"警告: オンラインメンバー '{member_name}' の情報がDBに見つかりません。")
    chan.send(
        "-------------------------------------------------------------------\r\n")


def sysop_menu(chan, dbname, current_menu_mode):
    """シスオペメニュー"""
    util.show_textsfile(chan, "serverprefmenu", current_menu_mode)
    while True:
        chan.send("Server Preferences: ")
        input_buffer = ssh_input.process_input(chan)

        if input_buffer is None:
            print("sysop_menu:クライアント切断")
            break

        command = input_buffer.lower().strip()  # 先に小文字化・空白除去

        if command == "q":
            break
        if command == "":  # 空入力の場合
            util.show_textsfile(chan, "serverprefmenu", current_menu_mode)
            continue

        # --- 設定一覧表示 ---
        if command == CMD_SHOW_PREFS:
            server_prefs_list = sqlite_tools.read_server_pref(dbname)
            if server_prefs_list:
                pref_names = ['bbs', 'chat', 'mail',
                              'telegram', 'userpref', 'who']
                chan.send('サーバ設定一覧\r\n')
                chan.send('-'*40+"\r\n")
                chan.send('{:<20} {:<20}\r\n'.format(
                    '項目名', '値 (レベル)'))  # ヘッダー修正
                chan.send('-'*40+"\r\n")
                for i, name in enumerate(pref_names):
                    if i < len(server_prefs_list):
                        chan.send('{:<20} {:<20}\r\n'.format(
                            name, server_prefs_list[i]))
                    else:
                        # 通常ここには来ないはず (read_server_pref が固定長リストを返すため)
                        chan.send('{:<20} {:<20}\r\n'.format(name, '(取得エラー)'))
                chan.send('-'*40+"\r\n")  # 区切り線はループの外
            else:
                # read_server_pref がデフォルト値を返すようになったので、ここに来る可能性は低い
                chan.send("設定がありません(または取得エラー)\r\n")

        # --- 各BBSメニューのユーザレベルごとのパーミッション ---
        elif command == CMD_SET_PERMISSIONS:
            chan.send("各BBSメニューのユーザレベルごとのパーミッションを設定します\r\n")
            chan.send(
                "ユーザレベルを設定する機能を選択してください(bbs,chat,mail,telegram,userpref,who): ")

            menu_input = ssh_input.process_input(chan)
            if menu_input is None:  # 切断チェック
                break
            menu_to_change = menu_input.lower().strip()  # 小文字化・空白除去

            valid_menus = ['bbs', 'chat', 'mail',
                           'telegram', 'userpref', 'who']
            if menu_to_change not in valid_menus:
                chan.send("有効なメニューを選択してください\r\n")
                continue  # メニュー選択からやり直し

            user_level = None
            while user_level is None:  # 正しいレベルが入力されるまでループ
                chan.send(
                    "0:無効 1:ゲスト 2:一般ユーザ 3:シグオペ 4:サブオペ 5:シスオペ\r\n")
                chan.send("ユーザレベルを入力してください(0~5): ")
                level_input = ssh_input.process_input(chan)
                if level_input is None:  # 切断チェック
                    user_level = -1  # ループを抜けるためのダミー値
                    break  # 外側のループも抜ける準備

                if level_input.lower().strip() == 'q':  # キャンセル機能
                    chan.send("レベル設定をキャンセルしました。\r\n")
                    user_level = -1  # ループを抜ける
                    break

                try:
                    level_val = int(level_input)
                    if 0 <= level_val <= 5:  # 範囲チェック修正
                        user_level = level_val  # 正しい値が入力された
                    else:
                        chan.send("ユーザレベルは0~5の範囲で入力してください\r\n")
                except ValueError:
                    chan.send("ユーザレベルは0~5の整数で入力してください\r\n")

            if user_level == -1:  # 切断またはキャンセル
                if menu_input is None:  # 切断の場合
                    break  # メインループも抜ける
                else:  # キャンセルの場合
                    continue  # メインループの最初に戻る

            # データベース更新
            if user_level is not None:  # 念のため確認
                if menu_to_change == 'bbs':
                    sql = "UPDATE server_pref SET bbs=?"
                elif menu_to_change == 'chat':
                    sql = "UPDATE server_pref SET chat=?"
                elif menu_to_change == 'mail':
                    sql = "UPDATE server_pref SET mail=?"
                elif menu_to_change == 'telegram':
                    sql = "UPDATE server_pref SET telegram=?"
                elif menu_to_change == 'userpref':
                    sql = "UPDATE server_pref SET userpref=?"
                elif menu_to_change == 'who':
                    sql = "UPDATE server_pref SET who=?"
                else:
                    chan.send(f"内部エラー:不正なメニュー項目 '{menu_to_change}' \r\n")
                    continue
                try:
                    sqlite_tools.sqlite_execute_query(
                        dbname, sql, (user_level,))  # params はタプルで渡す
                    chan.send(
                        f"{menu_to_change}メニューのユーザレベルを{user_level}に変更しました\r\n")
                except Exception as e:
                    chan.send(f"データベース更新エラー: {e}\r\n")
                    print(f"データベース更新エラー: {e}")  # サーバーログ

        # --- ユーザ情報変更メニュー ---
        elif command == CMD_USER_EDIT:
            util.show_textsfile(chan, "useredit", current_menu_mode)
            while True:  # サブメニュー用ループ
                chan.send("ユーザ編集メニュー: ")
                sub_input = ssh_input.process_input(chan)
                if sub_input is None:
                    # クライアント切断の場合、sysop_menu を抜ける
                    return

                sub_command = sub_input.lower().strip()

                if sub_command == "q":  # サブメニューを抜ける
                    break  # while ループを抜ける

                # --- ユーザ一覧表示 ---
                elif sub_command == "1":
                    try:
                        sql = "SELECT id, name, level, registdate, lastlogin, comment, mail FROM users ORDER BY id ASC"
                        # sqlite_tools.sqlite_execute_query が辞書を返すように row_factory を使っている前提
                        users = sqlite_tools.sqlite_execute_query(
                            dbname, sql, fetch=True)
                        if users:
                            chan.send(
                                "ID   NAME         LEVEL  REGIST DATE          LAST LOGIN           COMMENT      MAIL\r\n")
                            chan.send(
                                "------------------------------------------------------------------------------------------\r\n")
                            for user in users:
                                regdt_ts = user['registdate']
                                lastlogin_ts = user['lastlogin']
                                try:
                                    regdt_str = datetime.datetime.fromtimestamp(regdt_ts).strftime(
                                        '%Y-%m-%d %H:%M') if regdt_ts else 'N/A'  # 秒は省略しても良いかも
                                except (ValueError, OSError, TypeError):
                                    regdt_str = 'Invalid Date'
                                try:
                                    lastlogin_str = datetime.datetime.fromtimestamp(lastlogin_ts).strftime(
                                        '%Y-%m-%d %H:%M') if lastlogin_ts else 'N/A'
                                except (ValueError, OSError, TypeError):
                                    lastlogin_str = 'Invalid Date'

                                # 各フィールドの桁数を調整し、None の場合の処理を追加
                                comment_str = user['comment'] if user['comment'] else ''
                                mail_str = user['mail'] if user['mail'] else ''
                                chan.send(
                                    f"{user['id']:<4} {user['name']:<12} {str(user['level']):<6} {regdt_str:<20} {lastlogin_str:<20} {comment_str:<12} {mail_str:<12}\r\n")
                            chan.send(
                                "------------------------------------------------------------------------------------------\r\n")
                        else:
                            chan.send("ユーザがいません。\r\n")
                    except Exception as e:  # except を追加
                        chan.send(f"ユーザ一覧表示中にエラーが発生しました: {e}\r\n")
                        print(f"ユーザ一覧表示中にエラーが発生しました: {e}")  # サーバーログにも

                # --- 他のユーザー編集サブメニュー ---
                # インデント修正 & 変数名修正 (sub_input -> sub_command)
                elif sub_command == "2":
                    chan.send("ユーザー情報変更は未実装です。\r\n\r\n")
                elif sub_command == "3":  # インデント修正 & 変数名修正
                    chan.send("ユーザー追加は未実装です。\r\n")
                elif sub_command == "4":  # インデント修正 & 変数名修正
                    chan.send("ユーザー削除は未実装です。\r\n")
                elif sub_command == "":  # 空入力の場合、再度メニュー表示
                    util.show_textsfile(chan, "useredit", current_menu_mode)
                else:  # インデント修正
                    chan.send("無効な選択です。\r\n")

        # --- 無効なトップレベルコマンドの場合 ---
        else:
            chan.send("無効なコマンドです。\r\n")
            # メインメニューを再表示
            util.show_textsfile(chan, "serverprefmenu", current_menu_mode)

    # sysop_menu のメインループを抜けた場合 (q が入力された場合)
    chan.send("シスオペメニューを終了します。\r\n")
