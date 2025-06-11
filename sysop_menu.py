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

        elif command == 'mkbd':
            # 掲示板作成
            make_board(chan, dbname, sysop_login_id, current_menu_mode)

        elif command == 'lsbd':
            list_boards(chan, dbname, current_menu_mode)

        elif command == 'dlbd':
            # 掲示板削除
            delete_board(chan, dbname, current_menu_mode)

        elif command == 'pasu':
            # ユーザ削除
            user_delete(chan, dbname, sysop_login_id, current_menu_mode)
        elif command == 'regs':
            # ユーザ登録
            user_register(chan, dbname, current_menu_mode)
        elif command == 'pasc':
            # ユーザパスワード変更(各ユーザのパスワードが変更できるが、SSH鍵は生成しない)
            pass
        elif command == 'chgu':
            # ユーザ権限変更
            change_user_level(chan, dbname, sysop_login_id, current_menu_mode)

        elif command == 'kygn':
            # SSH鍵再生成
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
            return "back_to_top"  # 終了

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
        if sqlite_tools.register_user(dbname, user_id_input,  hashed_password, salt_hex, profile, level=0, auth_method='both'):
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


def change_user_level(chan, dbname, sysop_login_id, current_menu_mode):
    """ユーザレベルの変更"""
    util.send_text_by_key(
        chan, "sysop_menu.change_user_level.header", current_menu_mode)  # ユーザレベル変更ヘッダ
    util.send_text_by_key(
        chan, "sysop_menu.change_user_level.user_name_prompt", current_menu_mode, add_newline=False
    )
    target_user_input = ssh_input.process_input(chan)
    if target_user_input is None:  # 切断
        return
    target_user = target_user_input.strip()
    if not target_user_input:

        return
    user_data = sqlite_tools.get_user_auth_info(dbname, target_user_input)
    if not user_data:
        util.send_text_by_key(
            chan, "sysop_menu.change_user_level.user_not_found", current_menu_mode, user_id=target_user_input)
        return

    user_id_to_change = user_data['id']
    user_name_to_change = user_data['name']
    current_level = user_data['level']

    util.send_text_by_key(chan, "sysop_menu.change_user_level.current_level_info", current_menu_mode,
                          name=user_name_to_change, user_id=user_id_to_change, level=current_level)

    util.send_text_by_key(
        chan, "sysop_menu.change_user_level.new_level_prompt", current_menu_mode, add_newline=False)
    new_level_input = ssh_input.process_input(chan)
    if new_level_input is None:  # 切断
        return
    new_level = new_level_input.strip()

    if not new_level_input:
        return

    try:
        new_level = int(new_level_input)
        if not (0 <= new_level <= 5):  # レベル範囲チェック
            util.send_text_by_key(
                chan, "sysop_menu.change_user_level.invalid_level_range", current_menu_mode)
            return
    except ValueError:
        util.send_text_by_key(
            chan, "sysop_menu.change_user_level.invalid_level_range", current_menu_mode)
        return

    if new_level == current_level:
        util.send_text_by_key(
            chan, "sysop_menu.change_user_level.no_change_level_same", current_menu_mode)
        return

    util.send_text_by_key(chan, "sysop_menu.change_user_level.confirm_yn", current_menu_mode,
                          name=user_name_to_change, old_level=current_level, new_level=new_level, add_newline=False)
    confirm_input = ssh_input.process_input(chan)
    if confirm_input is None:  # 切断
        return
    confirm_input = confirm_input.lower().strip()

    if confirm_input == 'y':
        if sqlite_tools.update_user_level(dbname, user_id_to_change, new_level):
            util.send_text_by_key(
                chan, "sysop_menu.change_user_level.success", current_menu_mode)


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


def make_board(chan, dbname, sysop_login_id, current_menu_mode):
    """掲示板作成(bbs.ymlの内容とも関連するので、忘れないように)"""

    util.send_text_by_key(
        chan, "sysop_menu.make_board.header_direct", current_menu_mode)
    shortcut_id = ""

    while not shortcut_id:
        util.send_text_by_key(
            chan, "sysop_menu.make_board.shortcut_id_prompt", current_menu_mode, add_newline=False
        )
        shortcut_id_input = ssh_input.process_input(chan)
        if shortcut_id_input is None:
            return  # 切断
        shortcut_id = shortcut_id_input.strip()
        if not shortcut_id:
            return  # キャンセル
        if sqlite_tools.get_board_by_shortcut_id(dbname, shortcut_id):
            util.send_text_by_key(
                chan, "sysop_menu.make_board.shortcut_id_exists", current_menu_mode, shortcut_id=shortcut_id)
            shortcut_id = ""  # 再入力
    board_name = ""
    while not board_name:
        # 掲示板名入力
        util.send_text_by_key(
            chan, "sysop_menu.make_board.name_prompt", current_menu_mode, add_newline=False
        )
        name_input = ssh_input.process_input(chan)
        if name_input is None:
            return  # 切断
        board_name = name_input.strip()
        if not board_name:
            # textdata.yaml に追加が必要
            util.send_text_by_key(
                chan, "sysop_menu.make_board.name_required", current_menu_mode)

    description = ""
    util.send_text_by_key(
        # textdata.yaml に追加が必要
        chan, "sysop_menu.make_board.description_prompt", current_menu_mode, add_newline=False
    )
    desc_input = ssh_input.process_input(chan)
    if desc_input is None:
        return  # 切断
    description = desc_input.strip()  # 空でもOK

    default_permission = ""
    valid_permissions = ["open", "close", "readonly"]
    while default_permission not in valid_permissions:
        util.send_text_by_key(
            chan, "sysop_menu.make_board.default_permission_prompt", current_menu_mode, permissions=", ".join(valid_permissions), add_newline=False
        )
        permission_input = ssh_input.process_input(chan)
        if permission_input is None:
            return  # 切断
        default_permission = permission_input.strip().lower()
        if default_permission not in valid_permissions:
            util.send_text_by_key(
                chan, "sysop_menu.make_board.invalid_permission", current_menu_mode, permission=", ".join(valid_permissions))

    operators_json = f'["{sysop_login_id}"]'
    category_id = None
    display_order = 0
    # 初期設定
    kanban_title = ""
    kanban_body = ""
    status = "active"

    util.send_text_by_key(chan, "sysop_menu.make_board.confirm_create_yn", current_menu_mode, shortcut_id=shortcut_id,
                          board_name=board_name, permission=default_permission, operator=sysop_login_id, add_newline=False)
    confirm_create = ssh_input.process_input(chan)
    if confirm_create is None or confirm_create.lower().strip() != 'y':
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)  # キャンセルメッセージ
        return

    if sqlite_tools.create_board_entry(dbname, shortcut_id, board_name, description, operators_json, default_permission, kanban_title, kanban_body, status):
        util.send_text_by_key(chan, "sysop_menu.make_board.success_direct",
                              current_menu_mode, shortcut_id=shortcut_id)
        util.send_text_by_key(
            chan, "sysop_menu.make_board.advise_bbs_yml", current_menu_mode)
    else:
        util.send_text_by_key(
            chan, "common_messages.error", current_menu_mode)
        logging.error(f"掲示板作成失敗:{shortcut_id}")


def delete_board(chan, dbname, current_menu_mode):
    """掲示板削除(boardsテーブルからレコード削除)"""
    util.send_text_by_key(
        chan, "sysop_menu.delete_board.header", current_menu_mode)
    while True:
        util.send_text_by_key(
            chan, "sysop_menu.delete_board.delete_board_prompt", current_menu_mode, add_newline=False)
        board_id_input = ssh_input.process_input(chan)

        if board_id_input is None:  # 切断
            return
        if not board_id_input.strip():
            return  # キャンセル

        shortcut_id_to_delete = board_id_input.strip()
        # DBにエントリがあるか確認 (オペレーター情報などを取得するため)
        board_db_entry = sqlite_tools.get_board_by_shortcut_id(
            dbname, shortcut_id_to_delete)

        # bbs.yml から名前と説明を取得 (表示用)
        bbs_config = util.load_yaml_file_for_shortcut("bbs.yml")
        board_info_yml, board_name_yml = util.find_item_in_yaml(
            bbs_config, shortcut_id_to_delete, current_menu_mode, "board")

        if not board_db_entry:  # DBにエントリがなければエラー
            util.send_text_by_key(
                chan, "sysop_menu.delete_board.board_not_found", current_menu_mode)
            continue

        # DBから名前を取得して表示
        board_name_to_display = board_db_entry.get('name', shortcut_id_to_delete) if isinstance(
            board_db_entry, dict) else shortcut_id_to_delete

        chan.send(
            f"\"{board_name_to_display}\" (ID: {shortcut_id_to_delete})\r\n")

        util.send_text_by_key(chan, "sysop_menu.delete_board.confirm_yn",
                              current_menu_mode, board_name=board_name_to_display, add_newline=False)
        confirm_choice = ssh_input.process_input(chan)

        if confirm_choice is None:  # 切断
            return

        if confirm_choice.lower().strip() == 'y':
            # データベースから掲示板を削除 (関連記事やパーミッションも削除するかは別途検討)
            # 関連する articles や board_user_permissions の削除も将来的には必要
            if sqlite_tools.delete_board_entry(dbname, shortcut_id_to_delete):
                util.send_text_by_key(
                    chan, "sysop_menu.delete_board.advise_bbs_yml_delete", current_menu_mode)
                break  # 削除成功で終了
            else:
                util.send_text_by_key(
                    chan, "common_messages.error", current_menu_mode)
                logging.error(
                    f"掲示板の削除に失敗しました(board_id: {shortcut_id_to_delete})")
                continue  # 削除失敗で繰り返し
        else:
            util.send_text_by_key(
                chan, "common_messages.cancel", current_menu_mode)
            break


def list_boards(chan, dbname, current_menu_mode):
    """DBに登録されている掲示板一覧を表示"""
    # sqlite_tools.get_all_boards は存在しないため、直接クエリを実行
    sql = "SELECT shortcut_id, name, operators, default_permission, kanban_title, status, last_posted_at FROM boards ORDER BY shortcut_id"
    boards = sqlite_tools.sqlite_execute_query(dbname, sql, fetch=True)

    if not boards:
        util.send_text_by_key(
            chan, "sysop_menu.list_boards.no_boards", current_menu_mode)
        return
    else:
        # ヘッダーを textdata.yaml から取得する例 (キーは仮)
        util.send_text_by_key(
            chan, "sysop_menu.list_boards.header_title", current_menu_mode)
        # テーブルヘッダー
        header_line = f"{'ID':<12} {'Name':<20} {'Ops':<15} {'Perm':<10} {'Status':<8} {'Kanban':<15} {'LastPost':<15}\r\n"
        separator_line = "-" * (12 + 20 + 15 + 10 + 8 +
                                15 + 15 + 6*2) + "\r\n"  # Adjust length
        chan.send(header_line.encode('utf-8'))
        chan.send(separator_line.encode('utf-8'))

        board_list_details = ""
        for board in boards:
            shortcut_id_str = board['shortcut_id'] if 'shortcut_id' in board.keys(
            ) else 'N/A'
            name_str = board['name'] if 'name' in board.keys() else 'N/A'
            if len(name_str) > 18:
                name_str = name_str[:17] + "..."
            operators_str = board['operators'] if 'operators' in board.keys(
            ) else '[]'
            if len(operators_str) > 13:
                operators_str = operators_str[:12] + "..."
            default_permission_str = board['default_permission'] if 'default_permission' in board.keys(
            ) else 'N/A'
            status_str = board['status'] if 'status' in board.keys() else 'N/A'
            kanban_title_str = board['kanban_title'] if 'kanban_title' in board.keys(
            ) else ''
            if len(kanban_title_str) > 13:  # 表示桁数調整
                kanban_title_str = kanban_title_str[:12] + "..."

            last_posted_ts = board['last_posted_at'] if 'last_posted_at' in board.keys(
            ) else 0
            last_posted_str = "N/A"
            if last_posted_ts and last_posted_ts > 0:
                try:
                    last_posted_str = datetime.datetime.fromtimestamp(
                        last_posted_ts).strftime('%Y-%m-%d %H:%M')
                except (ValueError, OSError, TypeError):
                    last_posted_str = 'Invalid Date'
            board_list_details += f"{shortcut_id_str:<12} {name_str:<20} {operators_str:<15} {default_permission_str:<10} {status_str:<8} {kanban_title_str:<15} {last_posted_str:<15}\r\n"
        chan.send(board_list_details.encode('utf-8'))
        chan.send(separator_line.encode('utf-8'))  # フッターの区切り線
