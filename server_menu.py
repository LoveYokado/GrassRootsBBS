
import ssh_input
import util
import sqlite_tools
import logging
import datetime

CMD_SHOW_PREFS = "0"
CMD_SET_PERMISSIONS = "1"
CMD_USER_EDIT = "2"


def server_menu(chan, dbname, current_menu_mode):
    """シスオペメニュー"""
    util.send_text_by_key(chan, "server_menu.header",
                          current_menu_mode)  # メニュー表示
    while True:
        util.send_text_by_key(chan, "common_messages.select_prompt",
                              current_menu_mode, add_newline=False)  # プロンプト表示
        input_buffer = ssh_input.process_input(chan)

        if input_buffer is None:
            logging.info("server_menu:クライアント切断")
            break

        command = input_buffer.lower().strip()  # 先に小文字化・空白除去

        if command == "q":
            break
        if command == "":  # 空入力の場合
            util.send_text_by_key(chan, "server_menu.header",
                                  current_menu_mode)  # メニュー表示
            continue

        # --- 設定一覧表示 ---
        if command == CMD_SHOW_PREFS:
            server_prefs_list = sqlite_tools.read_server_pref(dbname)
            if server_prefs_list:
                pref_names = ['bbs', 'chat', 'mail',
                              'telegram', 'userpref', 'who']
                util.send_text_by_key(
                    chan, "server_menu.view_settings.header", current_menu_mode)    # 設定一覧ヘッダ
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
                    chan, "server_menu.view_settings.no_settings_error", current_menu_mode)  # 設定なしかエラー

        # --- 各BBSメニューのユーザレベルごとのパーミッション ---
        elif command == CMD_SET_PERMISSIONS:
            util.send_text_by_key(
                chan, "server_menu.set_permissions.header", current_menu_mode)  # 設定メニューヘッダ
            util.send_text_by_key(
                chan, "server_menu.set_permissions.prompt", current_menu_mode, add_newline=False)  # 入力プロンプト
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
                    chan, "server_menu.set_permissions.user_level_message", current_menu_mode
                )  # ユーザレベル一覧
                util.send_text_by_key(
                    chan, "server_menu.set_permissions.leveluser_level_prompt", current_menu_mode, add_newline=False)  # プロンプト
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
                            chan, "server_menu.set_permissions.user_level_0-1_message", current_menu_mode)
                except ValueError:
                    util.send_text_by_key(
                        chan, "server_menu.set_permissions.user_level_0-1_message", current_menu_mode)

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
                        chan, "server_menu.set_permissions.user_level_changed", current_menu_mode, menu_to_change=menu_to_change, user_level=user_level
                    )  # ユーザレベル変更メッセージ
                except Exception as e:
                    util.send_text_by_key(
                        chan, "common_messages.database_update_error", current_menu_mode)  # データベース更新エラー
                    logging.error(f"データベース更新エラー: {e}")  # サーバーログ

        # --- ユーザ情報変更メニュー ---
        elif command == CMD_USER_EDIT:

            while True:  # サブメニュー用ループ
                util.send_text_by_key(
                    chan, "server_menu.user_edit.header", current_menu_mode)  # メニュー表示
                util.send_text_by_key(
                    chan, "common_messages.select_prompt", current_menu_mode, add_newline=False)  # プロンプト
                sub_input = ssh_input.process_input(chan)
                if sub_input is None:
                    # クライアント切断の場合、server_menu を抜ける
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
                                chan, "server_menu.user_edit.user_list_header", current_menu_mode)  # ヘッダ表示
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
                                chan, "server_menu.user_edit.no_users", current_menu_mode
                            )  # ユーザなし
                    except Exception as e:  # except を追加
                        util.send_text_by_key(
                            chan, "server_menu.user_edit.user_list_error", current_menu_mode
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

    # server_menu のメインループを抜けた場合 (q が入力された場合)
    util.send_text_by_key(chan, "server_menu.exit_server_menu",
                          current_menu_mode)  # 終了メッセージ
