import ssh_input
import util
import datetime
import sqlite_tools
import time
import yaml
import logging

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


def telegram_send(chan, dbname, sender_name, online_members, current_menu_mode):
    """
    オンラインのメンバーにのみ電報を送信し、データベースに保存する。
    """
    util.send_text_by_key(chan, "telegram.send_message",
                          current_menu_mode)  # 電報送信メッセージ
    util.send_text_by_key(chan, "telegram.send_prompt",
                          current_menu_mode, add_newline=False)  # 宛先入力
    recipient_name = ssh_input.process_input(chan)

    if not recipient_name:
        util.send_text_by_key(chan, "telegram.no_recipient",
                              current_menu_mode)  # 宛先がオンラインにない
        return

    # ここでオンラインチェック
    if recipient_name not in online_members:
        util.send_text_by_key(chan, "telegram.recipient_not_online",
                              current_menu_mode, recipient_name=recipient_name)
        return

    # 自分自身には送れないようにする(テスト中は無効)
    # if recipient_name == sender_name:
    #    util.send_text_by_key(chan, "telegram.cannot_send_to_self", current_menu_mode)
    #    return

    util.send_text_by_key(chan, "telegram.message_prompt",
                          current_menu_mode, add_newline=False)
    message = ssh_input.process_input(chan)

    if not message:
        util.send_text_by_key(chan, "telegram.no_message", current_menu_mode)
        return

    # メッセージが長すぎる場合の処理（任意）
    if len(message) > 100:
        message = message[:100]
        util.send_text_by_key(
            chan, "telegram.message_truncated", current_menu_mode)

    # 電報をデータベースに保存 (sqlite_tools.save_telegram が必要)
    try:
        current_timestamp = int(time.time())
        # sqlite_tools に save_telegram(dbname, sender, recipient, message, timestamp) 関数を実装する想定
        sqlite_tools.save_telegram(
            dbname, sender_name, recipient_name, message, current_timestamp)
        util.send_text_by_key(chan, "telegram.send_success", current_menu_mode)
        chan.send("電報を送信しました。\r\n")
        # オプション: リアルタイム通知が必要なら、ここで受信側スレッドに通知する仕組みを追加
    except Exception as e:
        # サーバーログ
        logging.warning(
            f"電報保存エラー (送信者: {sender_name}, 宛先: {recipient_name}): {e}")
        util.send_text_by_key(chan, "telegram.send_error", current_menu_mode)


def telegram_recieve(chan, dbname, username, current_menu_mode):
    """受信している電報を表示すして、表示後に削除する"""
    results = sqlite_tools.load_and_delete_telegrams(dbname, username)
    if results:
        util.send_text_by_key(chan, "telegram.receive_header",
                              current_menu_mode)  # 電報受信メッセージ
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
            util.send_text_by_key(
                chan, "telegram.receive_message", current_menu_mode, sender=sender, message=message, dt_str=dt_str)  # 受信メッセージ本体
        util.send_text_by_key(
            chan, "telegram.receive_footer", current_menu_mode)
    else:
        # 電報がない場合は何も表示しない
        pass


# ... (他の関数)


def userpref_menu(chan, dbname, login_id, current_menu_mode):
    """ユーザー設定メニュー"""
    while True:
        util.send_text_by_key(chan, "user_pref_menu.header", current_menu_mode)
        util.send_text_by_key(chan, "common_messages.select_prompt",
                              current_menu_mode, add_newline=False)  # プロンプト表示
        input_buffer = ssh_input.process_input(chan)
        if input_buffer is None:
            return current_menu_mode  # 接続が切れた場合

        command = input_buffer.lower().strip()
        if command == '1':
            # メニューモード変更
            new_mode_after_change = change_menu_mode(
                chan, dbname, login_id, current_menu_mode)
            if new_mode_after_change and new_mode_after_change != current_menu_mode:
                current_menu_mode = new_mode_after_change
                continue
        elif command == '2':
            # パスワード変更
            change_password(chan, dbname, login_id, current_menu_mode)
        elif command == '3':
            # プロフィール変更
            change_profile(chan, dbname, login_id, current_menu_mode)
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
            return current_menu_mode  # メニューから抜ける
        elif command == 'h' or command == '?':
            util.send_text_by_key(
                chan, "user_pref_menu.help", current_menu_mode)  # メニュー再表示
            continue
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode)  # 無効なコマンド


def change_menu_mode(chan, dbname, login_id, current_menu_mode):
    """メニューモード変更"""
    user_id = sqlite_tools.get_user_id_from_user_name(dbname, login_id)
    if user_id is None:
        util.send_text_by_key(
            chan, "common_messages.user_not_found", current_menu_mode)
        return None
    while True:
        util.send_text_by_key(
            chan, "user_pref_menu.mode_selection.header", current_menu_mode)
        util.send_text_by_key(
            chan, "common_messages.select_prompt", current_menu_mode, add_newline=False)
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
                util.send_text_by_key(chan, "user_pref_menu.mode_selection.confirm_changed",
                                      current_menu_mode, mode=new_menu_mode)  # メニューモード変更
                return new_menu_mode
            else:
                util.send_text_by_key(
                    chan, "user_pref_menu.mode_selection.confirm_failed", current_menu_mode)  # メニューモードの変更に失敗
            return None


def show_member_list(chan, dbname, current_menu_mode):
    """会員リストを表示する"""
    util.send_text_by_key(
        chan, "userpref_menu.member_list.search_prompt", current_menu_mode, add_newline=False)
    search_word = ssh_input.process_input(chan)
    member_list = sqlite_tools.get_memberlist(dbname, search_word)
    if member_list:
        for member in member_list:
            chan.send(
                f"{member.get('name', 'N/A')} {member.get('comment', 'N/A')}\r\n")
    else:
        util.send_text_by_key(chan, "userpref_menu.member_list.notfound",
                              current_menu_mode)  # リストが空のとき


def who_menu(chan, dbname, online_members, current_menu_mode):
    """
    オンラインメンバー一覧を表示する
    """
    util.send_text_by_key(
        chan, "who_menu.header", current_menu_mode)
    if not online_members:
        util.send_text_by_key(chan, "who_menu.nomembers",
                              current_menu_mode)
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
    util.send_text_by_key(chan, "who_menu.footer", current_menu_mode)


def change_password(chan, dbname, login_id, current_menu_mode):
    """パスワード変更"""
    security_config = util.app_config.get('security', {})
    pbkdf2_rounds = security_config.get('pbkdf2_rounds', 100000)

    # 今のパスワードを確認
    util.send_text_by_key(chan, "user_pref_menu.change_password.current_password",
                          current_menu_mode, add_newline=False)  # 今のパスワード入力
    current_pass = ssh_input.process_input(chan)
    if current_pass is None:
        return

    user_auth_info = sqlite_tools.get_usser_credentials(dbname, login_id)
    if not user_auth_info:
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
        logging.error(f"パスワード変更施行中にユーザが見つかりません: {login_id}")
        return

    if not util._valify_password(user_auth_info['password'], user_auth_info['salt'], current_pass, pbkdf2_rounds):
        util.send_text_by_key(
            chan, "user_pref_menu.change_password.invalid_password", current_menu_mode)  # 不正パスワード
        return

    # 新しいパスワードを入力
    while True:
        util.send_text_by_key(chan, "user_pref_menu.change_password.new_password",
                              current_menu_mode, add_newline=False)  # 新しいパスワード入力
        new_pass1 = ssh_input.hide_process_input(chan)
        if new_pass1 is None:
            return

        if len(new_pass1) < 8:
            util.send_text_by_key(
                chan, "user_pref_menu.change_password.password_too_short", current_menu_mode)  # パスワードが短いよ
            continue

        util.send_text_by_key(
            chan, "user_pref_menu.change_password.new_password_confirm", add_newline=False)  # 新しいパスワード確認
        new_pass2 = ssh_input.hide_process_input(chan)
        if new_pass2 is None:
            return

        if new_pass1 == new_pass2:
            break
        else:
            util.send_text_by_key(
                chan, "user_pref_menu.change_password.password_mismatch", current_menu_mode)  # パスワードが一致しない

    # パスワードのハッシュ化とDB更新
    new_salt_hex, new_hashed_password = util.hash_password(new_pass1)
    if sqlite_tools.update_user_password_and_salt(dbname, login_id, new_hashed_password, new_salt_hex):
        util.send_text_by_key(
            chan, "user_pref_menu.change_password.password_changed", current_menu_mode)  # パスワード変更完了
    else:
        util.send_text_by_key(chan, "common_messages.error",
                              current_menu_mode)  # パスワード変更エラー
        logging.error(f"パスワード変更エラー({login_id})")

    # SSHキー再生成
    util.send_text_by_key(
        chan, "user_pref_menu.change_password.confirm_regenerate_ssh_key_yn", current_menu_mode, add_newline=False)
    choice = ssh_input.process_input(chan)
    if choice is None:
        return

    if choice.lower() == 'y':
        try:
            private_key_pem = util.regenerate_ssh_key_pair(login_id)
            if private_key_pem:
                chan.send(b'\r\n')
                util.send_text_by_key(
                    chan, "user_pref_menu.change_password.new_private_key_info", current_menu_mode)
                for line in private_key_pem.splitlines():
                    chan.send(line.encode('utf-8') + b'\r\n')
                chan.send(b'\r\n')
                util.send_text_by_key(
                    chan, "user_pref_menu.change_password.ssh_key_updated_success", current_menu_mode)
            else:
                raise Exception("SSHキーの再生成に失敗しました。秘密鍵が取得できませんでした。")
        except Exception as e:
            logging.error(f"SSHキー再生成または表示中にエラー ({login_id}): {e}")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)


def change_profile(chan, dbname, login_id, current_menu_mode):
    """プロフィール変更"""
    user_data = sqlite_tools.get_user_auth_info(dbname, login_id)
    if not user_data:
        util.send_text_by_key(
            chan, "common_messages.user_not_found", current_menu_mode)
        return

    current_comment = user_data.get('comment', '')
    util.send_text_by_key(chan, "user_pref_menu.change_profile.current_profile",
                          current_menu_mode, comment=current_comment)
    util.send_text_by_key(
        chan, "user_pref_menu.change_profile.new_profile", current_menu_mode, add_newline=False)
    new_comment = ssh_input.process_input(chan)

    if new_comment is None:
        return
    if new_comment == '':  # 空入力はキャンセル扱いにするか、空コメントとして許可するか後で考える
        util.send_text_by_key(
            chan, "user_pref_menu.change_profile.cancelled", current_menu_mode)
        return
    try:
        # コメント更新
        if sqlite_tools.update_user_profile(dbname, user_data[id],  new_comment):
            util.send_text_by_key(
                chan, "user_pref_menu.change_profile.profile_updated", current_menu_mode)
        else:
            raise Exception("コメント更新に失敗")

    except Exception as e:
        logging.error(f"コメント更新エラー: {e}")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)


def sysop_menu(chan, dbname, current_menu_mode):
    """シスオペメニュー"""
    util.send_text_by_key(chan, "sysop_menu.header",
                          current_menu_mode)  # メニュー表示
    while True:
        util.send_text_by_key(chan, "common_messages.select_prompt",
                              current_menu_mode, add_newline=False)  # プロンプト表示
        input_buffer = ssh_input.process_input(chan)

        if input_buffer is None:
            logging.info("sysop_menu:クライアント切断")
            break

        command = input_buffer.lower().strip()  # 先に小文字化・空白除去

        if command == "q":
            break
        if command == "":  # 空入力の場合
            util.send_text_by_key(chan, "sysop_menu.header",
                                  current_menu_mode)  # メニュー表示
            continue

        # --- 設定一覧表示 ---
        if command == CMD_SHOW_PREFS:
            server_prefs_list = sqlite_tools.read_server_pref(dbname)
            if server_prefs_list:
                pref_names = ['bbs', 'chat', 'mail',
                              'telegram', 'userpref', 'who']
                util.send_text_by_key(
                    chan, "sysop_menu.view_settings.header", current_menu_mode)    # 設定一覧ヘッダ
                for i, name in enumerate(pref_names):
                    if i < len(server_prefs_list):
                        chan.send('{:<20} {:<20}\r\n'.format(
                            name, server_prefs_list[i]))
                    else:
                        # 通常ここには来ないはず (read_server_pref が固定長リストを返すため)
                        chan.send('{:<20} {:<20}\r\n'.format(name, '(error)'))
                chan.send('-'*36+"\r\n")  # 区切り線はループの外
            else:
                # read_server_pref がデフォルト値を返すようになったので、ここに来る可能性は低い
                util.send_text_by_key(
                    chan, "sysop_menu.view_settings.no_settings_error", current_menu_mode)  # 設定なしかエラー

        # --- 各BBSメニューのユーザレベルごとのパーミッション ---
        elif command == CMD_SET_PERMISSIONS:
            util.send_text_by_key(
                chan, "sysop_menu.set_permissions.header", current_menu_mode)  # 設定メニューヘッダ
            util.send_text_by_key(
                chan, "sysop_menu.set_permissions.prompt", current_menu_mode, add_newline=False)  # 入力プロンプト
            menu_input = ssh_input.process_input(chan)
            if menu_input is None:  # 切断チェック
                break
            menu_to_change = menu_input.lower().strip()  # 小文字化・空白除去

            valid_menus = ['bbs', 'chat', 'mail',
                           'telegram', 'userpref', 'who']
            if menu_to_change not in valid_menus:
                util.send_text_by_key(
                    chan, "common_messages.invalid_command", current_menu_mode
                )
                continue  # メニュー選択からやり直し

            user_level = None
            while user_level is None:  # 正しいレベルが入力されるまでループ
                util.send_text_by_key(
                    chan, "sysop_menu.set_permissions.user_level_message", current_menu_mode
                )  # ユーザレベル一覧
                util.send_text_by_key(
                    chan, "sysop_menu.set_permissions.leveluser_level_prompt", current_menu_mode, add_newline=False)  # プロンプト
                level_input = ssh_input.process_input(chan)
                if level_input is None:  # 切断チェック
                    user_level = -1  # ループを抜けるためのダミー値
                    break  # 外側のループも抜ける準備

                if level_input.lower().strip() == 'q':  # キャンセル機能
                    util.send_text_by_key(
                        chan, "common_messages.cancel", current_menu_mode
                    )
                    user_level = -1  # ループを抜ける
                    break

                try:
                    level_val = int(level_input)
                    if 0 <= level_val <= 5:  # 範囲チェック修正
                        user_level = level_val  # 正しい値が入力された
                    else:
                        util.send_text_by_key(
                            chan, "sysop_menu.set_permissions.user_level_0-1_message", current_menu_mode)
                except ValueError:
                    util.send_text_by_key(
                        chan, "sysop_menu.set_permissions.user_level_0-1_message", current_menu_mode)

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
                    logging.error(f"内部エラー:不正なメニュー項目 '{menu_to_change}'")
                    continue
                try:
                    sqlite_tools.sqlite_execute_query(
                        dbname, sql, (user_level,))  # params はタプルで渡す
                    util.send_text_by_key(
                        chan, "sysop_menu.set_permissions.user_level_changed", current_menu_mode, menu_to_change=menu_to_change, user_level=user_level
                    )  # ユーザレベル変更メッセージ
                except Exception as e:
                    util.send_text_by_key(
                        chan, "common_messages.database_update_error", current_menu_mode)  # データベース更新エラー
                    logging.error(f"データベース更新エラー: {e}")  # サーバーログ

        # --- ユーザ情報変更メニュー ---
        elif command == CMD_USER_EDIT:

            while True:  # サブメニュー用ループ
                util.send_text_by_key(
                    chan, "sysop_menu.user_edit.header", current_menu_mode)  # メニュー表示
                util.send_text_by_key(
                    chan, "common_messages.select_prompt", current_menu_mode, add_newline=False)  # プロンプト
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
                            util.send_text_by_key(
                                chan, "sysop_menu.user_edit.user_list_header", current_menu_mode)  # ヘッダ表示
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
                            util.send_text_by_key(
                                chan, "sysop_menu.user_edit.no_users", current_menu_mode
                            )  # ユーザなし
                    except Exception as e:  # except を追加
                        util.send_text_by_key(
                            chan, "sysop_menu.user_edit.user_list_error", current_menu_mode
                        )  # ユーザ表示エラー
                        logging.error(f"ユーザ一覧表示中にエラーが発生しました: {e}")  # サーバーログにも

                # --- 他のユーザー編集サブメニュー ---
                # インデント修正 & 変数名修正 (sub_input -> sub_command)
                elif sub_command == "2":
                    chan.send("ユーザー情報変更は未実装です。\r\n\r\n")
                elif sub_command == "3":  # インデント修正 & 変数名修正
                    chan.send("ユーザー追加は未実装です。\r\n")
                elif sub_command == "4":  # インデント修正 & 変数名修正
                    chan.send("ユーザー削除は未実装です。\r\n")
                elif sub_command == "":  # 空入力の場合、再度メニュー表示
                    continue
                else:  # インデント修正
                    util.send_text_by_key(
                        chan, "common_messages.invalid_command", current_menu_mode
                    )  # 無効なコマンド

        # --- 無効なトップレベルコマンドの場合 ---
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode
            )  # 無効なコマンド
            # メインメニューを再表示

    # sysop_menu のメインループを抜けた場合 (q が入力された場合)
    util.send_text_by_key(chan, "sysop_menu.exit_sysop_menu",
                          current_menu_mode)  # 終了メッセージ
