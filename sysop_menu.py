import ssh_input
import util
import sqlite_tools
import logging
import datetime
import os


def sysop_menu(chan, dbname, sysop_login_id, current_menu_mode):
    """シスオペメニュー"""
    while True:
        util.send_text_by_key(chan, "sysop_menu.menu", current_menu_mode)
        util.send_text_by_key(chan, "common_messages.select_prompt",
                              current_menu_mode, add_newline=False)  # プロンプト表示
        input_buffer = ssh_input.process_input(chan)
        if input_buffer is None:
            return  # 接続が切れた場合

        command = input_buffer.lower().strip()
        if command == 'allr':
            # 共通探索リストを読む
            read_default_exploration_list(chan, dbname, current_menu_mode)
        elif command == 'allw':
            # 共通探索リストを書き込む
            write_default_exploration_list(chan, dbname, current_menu_mode)
        elif command == 'usrl':
            # ユーザ一覧表示
            user_list(chan, dbname, current_menu_mode)
        elif command == 'pasu':
            # ユーザ削除
            user_delete(chan, dbname, sysop_login_id, current_menu_mode)
        elif command == 'regs':
            # ユーザ登録
            user_register(chan, dbname, current_menu_mode)
        elif command == 'pasc':
            # ユーザパスワード変更(各ユーザのパスワードが変更できるが、SSH鍵は生成しない)
            pass
        elif command == 'kygn':
            regenerate_user_ssh_key(
                chan, dbname, sysop_login_id, current_menu_mode)

        elif command == 'vset':
            # 設定一覧
            view_settings(chan, dbname, current_menu_mode)
        elif command == 'mnpm':
            # トップメニューパーミッション
            change_top_menu_permission(chan, dbname, current_menu_mode)

        elif command == 'exit':
            # システム強制終了
            system_quit(chan, dbname, current_menu_mode)

        elif command == '':
            return  # 終了

        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode)  # 無効なコマンド


def read_default_exploration_list(chan, dbname, current_menu_mode):
    server_prefs = sqlite_tools.read_server_pref(dbname)
    if server_prefs and len(server_prefs) > 6:
        read_default_exploration_list_str = server_prefs[6]
        if read_default_exploration_list_str:
            items = read_default_exploration_list_str.split(",")
            chan.send("\r\n")
            for item in items:
                item_stripped = item.strip()
                if item_stripped:
                    chan.send(item_stripped.encode('utf-8')+b'\r\n')
            chan.send("\r\n")
    else:
        logging.error("サーバ設定の読み込みに失敗したか、共通探索リストの項目がありません。")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)


def write_default_exploration_list(chan, dbname, current_menu_mode):
    util.send_text_by_key(
        chan, "user_pref_menu.register_exploration_list.header", current_menu_mode)

    exploration_items = []
    item_number = 1
    while True:
        prompt_text = f"{item_number}: "
        chan.send(prompt_text.encode('utf-8'))
        item_input = ssh_input.process_input(chan)

        if item_input is None:  # 接続切れ
            return

        if not item_input.strip():  # 空エンターで終了
            break

        exploration_items.append(item_input.strip())
        item_number += 1

    if not exploration_items:
        return

    util.send_text_by_key(
        chan, "user_pref_menu.register_exploration_list.confirm_yn", current_menu_mode, add_newline=False)
    confirm_choice = ssh_input.process_input(chan)

    if confirm_choice is None:  # 接続切れ
        return

    if confirm_choice.lower().strip() == 'y':
        exploration_list_str = ",".join(exploration_items)
        if sqlite_tools.update_server_default_exploration_list(dbname, exploration_list_str):
            util.send_text_by_key(
                chan, "user_pref_menu.register_exploration_list.success", current_menu_mode)
        else:
            logging.error(f"共通探索リスト更新時にエラーが発生しました。")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)


def user_list(chan, dbname,  current_menu_mode):
    """ユーザ一覧表示"""
    try:
        sql = "SELECT id, name, level, registdate, lastlogin, comment, email FROM users ORDER BY id ASC"
        # sqlite_tools.sqlite_execute_query が辞書を返すように row_factory を使っている前提
        users = sqlite_tools.sqlite_execute_query(
            dbname, sql, fetch=True)
        if users:
            util.send_text_by_key(
                chan, "sysop_menu.user_list.header", current_menu_mode)  # ヘッダ表示
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
                email_str = user['email'] if user['email'] else ''
                chan.send(
                    f"{user['id']:<4} {user['name']:<12} {str(user['level']):<6} {regdt_str:<20} {lastlogin_str:<20} {comment_str:<12} {email_str:<12}\r\n")
            chan.send(
                "------------------------------------------------------------------------------------------\r\n")
        else:
            util.send_text_by_key(
                chan, "sysop_menu.user_list.no_users", current_menu_mode
            )  # ユーザなし
    except Exception as e:  # except を追加
        util.send_text_by_key(
            chan, "sysop_menu.user_list.error", current_menu_mode
        )  # ユーザ表示エラー
        logging.error(f"ユーザ一覧表示中にエラーが発生しました: {e}")  # サーバーログにも


def user_register(chan, dbname, current_menu_mode):
    """ユーザ登録"""
    util.send_text_by_key(
        chan, "sysop_menu.user_register.header", current_menu_mode)  # ヘッダ表示

    while True:
        # ID
        util.send_text_by_key(
            chan, "sysop_menu.user_register.user_id_prompt", current_menu_mode, add_newline=False)  # ID入力
        user_id_input = ssh_input.process_input(chan)
        user_id_input = user_id_input.upper()
        if user_id_input is None:  # 切断チェック
            return
        if not user_id_input.strip():
            return  # キャンセル

        user_id = user_id_input.strip().upper()
        chan.send(f"\"{user_id_input}\"\r\n")

        # ID確認
        util.send_text_by_key(
            chan, "sysop_menu.user_register.confirm_yn", current_menu_mode, add_newline=False)
        confirm_id = ssh_input.process_input(chan)
        if confirm_id is None:  # 切断
            return
        if confirm_id.lower().strip() != 'y':
            continue  # 再入力

        # ユーザID重複チェック
        if sqlite_tools.get_user_auth_info(dbname, user_id_input) is not None:
            util.send_text_by_key(
                chan, "sysop_menu.user_register.user_id_exists", current_menu_mode)
            continue

        # パスワード入力ループ
        while True:
            util.send_text_by_key(
                chan, "sysop_menu.user_register.user_pass_prompt", current_menu_mode, add_newline=False)
            password_input = ssh_input.hide_process_input(chan)
            if password_input is None:  # 切断
                return
            if not password_input:  # 空入力はキャンセルとしてID入力に戻る
                break
            util.send_text_by_key(
                chan, "sysop_menu.user_register.user_pass_confirm_prompt", current_menu_mode, add_newline=False)
            password_confirm_input = ssh_input.hide_process_input(chan)
            if password_confirm_input is None:  # 切断
                return

            if not password_confirm_input:  # 確認入力が空なら不一致扱い
                util.send_text_by_key(
                    chan, "sysop_menu.user_register.user_pass_mismatch", current_menu_mode
                )
                continue  # パスワード入力からやり直し

            if password_input == password_confirm_input:
                break  # パスワード一致、パスワード入力ループを抜ける
            else:
                util.send_text_by_key(
                    chan, "sysop_menu.user_register.user_pass_mismatch", current_menu_mode
                )
                # continue は不要、パスワード入力ループの先頭に戻る

        if not password_input:  # パスワード入力が空でキャンセルされた場合
            continue  # ID入力ループの先頭へ

        # プロフィール
        util.send_text_by_key(
            chan, "sysop_menu.user_register.user_prof_prompt", current_menu_mode, add_newline=False
        )
        prof_input = ssh_input.process_input(chan)
        if prof_input is None:  # 切断
            return
        profile = prof_input.strip()
        chan.send(f"\"{profile}\"\r\n")

        # プロフィール確認
        util.send_text_by_key(
            chan, "sysop_menu.user_register.confirm_yn", current_menu_mode, add_newline=False)
        confirm_prof = ssh_input.process_input(chan)
        if confirm_prof is None:  # 切断
            return
        if confirm_prof.lower().strip() != 'y':
            continue  # 再入力

        # ユーザ登録
        salt_hex, hashed_password = util.hash_password(password_input)
        # まずはレベル0に設定されます。登録後に変更してください。
        if sqlite_tools.register_user(dbname, user_id_input,  hashed_password, salt_hex, profile, level=0):
            util.send_text_by_key(
                chan, "sysop_menu.user_register.user_regist_success", current_menu_mode)
        else:
            # ユーザ登録失敗
            logging.error(f"ユーザ登録中にエラーが発生しました。")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
        continue


def user_delete(chan, dbname, sysop_login_id, current_menu_mode):
    """ユーザ削除"""
    util.send_text_by_key(
        chan, "sysop_menu.user_delete.header", current_menu_mode)  # ユーザ削除ヘッダ

    while True:
        util.send_text_by_key(
            chan, "sysop_menu.user_delete.user_id_prompt", current_menu_mode, add_newline=False)
        user_id_delete_input = ssh_input.process_input(chan)

        if user_id_delete_input is None:  # 切断
            return
        if not user_id_delete_input.strip():
            return  # キャンセル

        # 大文字変換
        user_id_delete_input_normalized = user_id_delete_input.strip().upper()

        # 存在確認
        user_data = sqlite_tools.get_user_auth_info(
            dbname, user_id_delete_input_normalized)
        if user_data is None:
            util.send_text_by_key(
                chan, "sysop_menu.user_delete.user_id_exists", current_menu_mode)
            continue

        actual_user_name_to_delete = user_data['name']
        numeric_user_id_to_delete = user_data['id']

        # シスオペは削除不可
        if actual_user_name_to_delete == sysop_login_id:
            util.send_text_by_key(
                chan, "sysop_menu.user_delete.cannot_delete_sysop", current_menu_mode)
            continue

        # ゲストは削除不可にしようと思ったけど、ゲスト禁止のホストもありますね
        # if actual_user_name_to_delete.upper()=="GUEST":
        #    util.send_text_by_key(
        #        chan, "sysop_menu.user_delete.user_id_exists", current_menu_mode)
        #    continue

        # 最終確認
        chan.send(f"\"{actual_user_name_to_delete}\"\r\n")
        util.send_text_by_key(
            chan, "sysop_menu.user_delete.confirm_yn", current_menu_mode, add_newline=False)
        confirm_choice = ssh_input.process_input(chan)

        if confirm_choice is None:  # 切断
            return
        if confirm_choice.lower().strip() != 'y':
            continue  # 再入力

        # ユーザ削除
        if sqlite_tools.delete_user(dbname, numeric_user_id_to_delete):
            util.send_text_by_key(
                chan, "sysop_menu.user_delete.user_delete_success", current_menu_mode)

           # 公開鍵削除
            if util.remove_user_public_key(actual_user_name_to_delete):
                logging.info(f"ユーザ {actual_user_name_to_delete}公開鍵を削除しました。")
            else:
                logging.info(
                    f"ユーザ {actual_user_name_to_delete}公開鍵が見当たらないか、公開鍵ファイルがありません。")

        else:
            # ユーザ削除失敗
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
        continue


def regenerate_user_ssh_key(chan, dbname, sysop_login_id, current_menu_mode):
    """SSH鍵再生成"""
    util.send_text_by_key(
        chan, "sysop_menu.regenerate_key.header", current_menu_mode)  # SSH鍵再生成ヘッダ
    while True:
        util.send_text_by_key(
            chan, "sysop_menu.regenerate_key.user_id_prompt", current_menu_mode, add_newline=False)
        user_id_input = ssh_input.process_input(chan)

        if user_id_input is None:  # 切断
            return
        if not user_id_input.strip():
            return  # キャンセル

        # 大文字変換
        user_name_to_regenerate = user_id_input.strip().upper()

        # 存在確認
        user_data = sqlite_tools.get_user_auth_info(
            dbname, user_name_to_regenerate)
        if user_data is None:
            util.send_text_by_key(
                chan, "sysop_menu.regenerate_key.user_not_found", current_menu_mode)
            continue

        # GUEST除外
        if user_name_to_regenerate == "GUEST":
            util.send_text_by_key(
                chan, "sysop_menu.regenerate_key.user_not_found", current_menu_mode)
            continue

        # 最終確認
        chan.send(f"\"{user_name_to_regenerate}\"\r\n")
        util.send_text_by_key(
            chan, "sysop_menu.regenerate_key.confirm_yn", current_menu_mode, add_newline=False)
        confirm_choice = ssh_input.process_input(chan)

        if confirm_choice is None:  # 切断
            return
        if confirm_choice.lower().strip() != 'y':
            return

        # SSH鍵再生成
        try:
            private_key_pem = util.regenerate_user_ssh_key(
                user_name_to_regenerate)

            if private_key_pem:
                chan.send(b'\r\n')
                for line in private_key_pem.splitlines():
                    chan.send(line.encode('utf-8')+b'\r\n')
                chan.send(b'\r\n')
                util.send_text_by_key(
                    chan, "sysop_menu.regenerate_key.success", current_menu_mode)
            else:
                util.send_text_by_key(
                    chan, "sysop_menu.regenerate_key.failed", current_menu_mode)

        except Exception as e:
            logging.error(f"SSH鍵再生成エラー({user_name_to_regenerate}): {e}")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
        return


def view_settings(chan, dbname, current_menu_mode):
    """設定一覧表示"""
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


def change_top_menu_permission(chan, dbname, current_menu_mode):
    """トップメニューのアクセス権限変更"""
    util.send_text_by_key(
        chan, "sysop_menu.set_permissions.header", current_menu_mode)  # 設定メニューヘッダ

    valid_menus = ['bbs', 'chat', 'mail',
                   'telegram', 'userpref', 'who']
    menu_to_change = None

    # 変更対象メニューの入力を促し、有効な入力が得られるまでループ
    while menu_to_change is None:
        util.send_text_by_key(
            chan, "sysop_menu.set_permissions.prompt", current_menu_mode, add_newline=False)  # 入力プロンプト
        menu_input = ssh_input.process_input(chan)
        if menu_input is None:  # クライアント切断
            return  # 関数を終了

        menu_to_change_input = menu_input.lower().strip()
        if menu_to_change_input in valid_menus:
            menu_to_change = menu_to_change_input  # 有効なメニューが選択された
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode
            )  # 無効なコマンド
            # ループが継続し、再入力を促す

    user_level = None
    while user_level is None:  # 正しいレベルが入力されるまでループ
        util.send_text_by_key(
            chan, "sysop_menu.set_permissions.user_level_message", current_menu_mode
        )  # ユーザレベル一覧
        util.send_text_by_key(
            chan, "sysop_menu.set_permissions.user_level_prompt", current_menu_mode, add_newline=False)  # プロンプト
        level_input = ssh_input.process_input(chan)
        if level_input is None:  # 切断チェック
            return

        if level_input.lower().strip() == 'q':  # キャンセル機能
            util.send_text_by_key(
                chan, "common_messages.cancel", current_menu_mode
            )
            return

        try:
            level_val = int(level_input)
            if 0 <= level_val <= 5:  # 範囲チェック修正
                user_level = level_val  # 正しい値が入力された
            else:
                util.send_text_by_key(
                    chan, "sysop_menu.set_permissions.user_level_0-5_message", current_menu_mode)  # 範囲外
        except ValueError:
            util.send_text_by_key(
                chan, "sysop_menu.set_permissions.user_level_0-5_message", current_menu_mode)  # 数値変換エラー

    # ここに来るということは、user_level は 0-5 のいずれか
    # データベース更新
    # カラム名は valid_menus でチェック済みなので、直接 f-string で使用
    sql = f"UPDATE server_pref SET {menu_to_change}=?"
    try:
        sqlite_tools.sqlite_execute_query(dbname, sql, (user_level,))
        util.send_text_by_key(
            chan, "sysop_menu.set_permissions.user_level_changed", current_menu_mode, menu_to_change=menu_to_change, user_level=user_level
        )  # ユーザレベル変更メッセージ
    except Exception as e:
        util.send_text_by_key(
            chan, "common_messages.database_update_error", current_menu_mode)  # データベース更新エラー
        logging.error(f"データベース更新エラー: {e}")  # サーバーログ


def system_quit(chan, dbname, current_menu_mode):
    util.send_text_by_key(
        chan, "sysop_menu.system_quit.header", current_menu_mode)
    util.send_text_by_key(chan, "common_messages.confirm_yn",
                          current_menu_mode, add_newline=False)
    continue_choice = ssh_input.process_input(chan)

    if continue_choice is None:  # 接続切れ
        return

    if continue_choice.lower().strip() == 'y':
        util.send_text_by_key(
            chan, "sysop_menu.system_quit.system_down_requested", current_menu_mode
        )
        os.exit(0)
