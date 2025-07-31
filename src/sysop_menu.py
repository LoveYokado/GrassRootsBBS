import logging
import datetime
import os
import secrets

from . import util, sqlite_tools, database


def sysop_menu(chan, sysop_login_id, sysop_display_name, current_menu_mode):
    """シスオペメニュー"""
    # コマンドと対応する関数のディスパッチテーブル
    command_dispatch = {
        'allr': read_default_exploration_list,
        'allw': write_default_exploration_list,
        'usrl': user_list,
        'mkbd': make_board,
        'lsbd': list_boards,
        'dlbd': delete_board,
        'bdlv': change_board_settings,
        'delu': user_delete,
        'regs': user_register,
        'pasc': change_user_password_by_sysop,
        'chgu': change_user_level,
        'vset': view_settings,
        'mnpm': change_top_menu_permission,
        'lgmg': change_login_message,  # ログインメッセージ
        'exit': system_quit,
        '': lambda *args: "back_to_top",  # 空入力でメニュー終了
    }

    mail_notified_flag = False  # シスオペメニュー内での通知状態を管理
    while True:
        util.send_text_by_key(chan, "sysop_menu.menu", current_menu_mode)
        # プロンプト前の定型処理。通知フラグを渡して、更新されたフラグを受け取る
        _, mail_notified_flag = util.prompt_handler(
            chan, sysop_login_id, current_menu_mode, mail_notified_flag)
        util.send_text_by_key(chan, "common_messages.select_prompt",
                              current_menu_mode, add_newline=False)  # プロンプト表示
        input_buffer = chan.process_input()
        if input_buffer is None:
            return None  # 接続が切れた場合

        command = input_buffer.lower().strip()
        # ディスパッチテーブルからコマンドに対応する関数を取得
        handler = command_dispatch.get(command)
        if handler:
            result = handler(chan, sysop_login_id, current_menu_mode)
            if result == "back_to_top":
                return "back_to_top"  # メニュー終了
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode)  # 無効なコマンド


def read_default_exploration_list(chan, _sysop_login_id, current_menu_mode):
    """共通探索リストを読む"""
    server_prefs = database.read_server_pref()
    if not server_prefs or len(server_prefs) <= 6:
        logging.error("サーバ設定の読み込みに失敗したか、共通探索リストの項目がありません。")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
        return None

    default_exploration_list_str = server_prefs[6]
    util.display_exploration_list(chan, default_exploration_list_str)
    return None


def write_default_exploration_list(chan, _sysop_login_id, current_menu_mode):
    """共通探索リストを書き込む"""
    def save_func(exploration_list_str):
        return database.update_record(
            'server_pref',
            {'default_exploration_list': exploration_list_str},
            {'id': 1}
        )
    util.prompt_and_save_exploration_list(chan, current_menu_mode, save_func)
    return None


def change_login_message(chan, _sysop_login_id, current_menu_mode):
    """ログインメッセージ変更"""
    util.send_text_by_key(
        chan, "sysop_menu.change_login_message.header", current_menu_mode)

    # 現在のログインメッセージを表示
    server_prefs = database.read_server_pref()
    if server_prefs and len(server_prefs) > 8:
        current_login_message = server_prefs[8]
        util.send_text_by_key(chan, "sysop_menu.change_login_message.current", current_menu_mode,
                              message=current_login_message if current_login_message else "(設定されていません)")
    else:
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
        logging.error("サーバー設定の読み込みに失敗しました (ログインメッセージ変更)")
        return None

    # 新しいログインメッセージの入力を促す
    util.send_text_by_key(
        chan, "sysop_menu.change_login_message.prompt", current_menu_mode, add_newline=False)
    new_login_message = chan.process_input()
    if new_login_message is None:
        return None

    # 確認
    util.send_text_by_key(chan, "common_messages.confirm_yn",
                          current_menu_mode, add_newline=False)
    final_confirm = chan.process_input()

    if final_confirm is None or final_confirm.strip().lower() != 'y':
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)
        return None

    # DBを更新
    try:
        # MariaDB用の関数を呼び出す。server_prefテーブルは1行しかなく、id=1と仮定
        database.update_record(
            'server_pref', {'login_message': new_login_message}, {'id': 1})
        util.send_text_by_key(
            chan, "sysop_menu.change_login_message.success", current_menu_mode)
        logging.info(f"ログインメッセージを更新しました: {new_login_message[:50]}...")

    except Exception as e:
        util.send_text_by_key(
            chan, "common_messages.database_update_error", current_menu_mode)
        logging.error(f"ログインメッセージ更新中に予期せぬエラー: {e}")

    return None


def user_list(chan, _sysop_login_id, current_menu_mode):
    """ユーザ一覧表示"""
    try:
        users = database.get_all_users()
        if users:
            util.send_text_by_key(
                chan, "sysop_menu.user_list.header", current_menu_mode)
            chan.send(
                "------------------------------------------------------------------------------------------\r\n")
            for user in users:
                regdt_str = util.format_timestamp(user['registdate'])
                lastlogin_str = util.format_timestamp(user['lastlogin'])

                comment_str = user['comment'] if user['comment'] else ''
                email_str = user['email'] if user['email'] else ''
                chan.send(
                    f"{user['id']:<4} {user['name']:<12} {str(user['level']):<6} {regdt_str:<20} {lastlogin_str:<20} {comment_str:<12} {email_str:<12}\r\n")
            chan.send(
                "------------------------------------------------------------------------------------------\r\n")
        else:
            util.send_text_by_key(
                chan, "sysop_menu.user_list.no_users", current_menu_mode)
    except Exception as e:
        util.send_text_by_key(
            chan, "sysop_menu.user_list.error", current_menu_mode)
        logging.error(f"ユーザ一覧表示中にエラーが発生しました: {e}")
    return None


def user_register(chan, _sysop_login_id, current_menu_mode):
    """ユーザ登録"""
    util.send_text_by_key(
        chan, "sysop_menu.user_register.header", current_menu_mode)
    while True:
        util.send_text_by_key(
            chan, "sysop_menu.user_register.user_id_prompt", current_menu_mode, add_newline=False)
        user_id_input = chan.process_input()
        user_id_input = user_id_input.upper() if user_id_input else ''
        if user_id_input is None:
            return None
        if not user_id_input.strip():
            return None

        user_id = user_id_input.strip().upper()
        chan.send(f"\"{user_id_input}\"\r\n")
        util.send_text_by_key(
            chan, "sysop_menu.user_register.confirm_yn", current_menu_mode, add_newline=False)
        confirm_id = chan.process_input()
        if confirm_id is None:
            return None
        if confirm_id.lower().strip() != 'y':
            continue

        if database.get_user_auth_info(user_id_input) is not None:
            util.send_text_by_key(
                chan, "sysop_menu.user_register.user_id_exists", current_menu_mode)
            continue

        while True:
            util.send_text_by_key(
                chan, "sysop_menu.user_register.user_pass_prompt", current_menu_mode, add_newline=False)
            password_input = chan.hide_process_input()
            if password_input is None:
                return None
            if not password_input:
                break

            util.send_text_by_key(
                chan, "sysop_menu.user_register.user_pass_confirm_prompt", current_menu_mode, add_newline=False)
            password_confirm_input = chan.hide_process_input()
            if password_confirm_input is None:
                return None

            if not password_confirm_input:
                util.send_text_by_key(
                    chan, "sysop_menu.user_register.user_pass_mismatch", current_menu_mode)
                continue

            if password_input == password_confirm_input:
                break
            else:
                util.send_text_by_key(
                    chan, "sysop_menu.user_register.user_pass_mismatch", current_menu_mode)

        if not password_input:
            continue

        util.send_text_by_key(
            chan, "sysop_menu.user_register.user_prof_prompt", current_menu_mode, add_newline=False)
        prof_input = chan.process_input()
        if prof_input is None:
            return None
        profile = prof_input.strip()
        chan.send(f"\"{profile}\"\r\n")

        util.send_text_by_key(
            chan, "sysop_menu.user_register.confirm_yn", current_menu_mode, add_newline=False)
        confirm_prof = chan.process_input()
        if confirm_prof is None:
            return None
        if confirm_prof.lower().strip() != 'y':
            continue

        salt_hex, hashed_password = util.hash_password(password_input)
        if database.register_user(user_id_input, hashed_password, salt_hex, profile, level=0):
            util.send_text_by_key(
                chan, "sysop_menu.user_register.user_regist_success", current_menu_mode)
        else:
            logging.error(f"ユーザ登録中にエラーが発生しました。")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
        return None


def _get_target_user(chan, prompt_key, current_menu_mode):
    """
    ユーザー名の入力を促し、検証済みのユーザー情報を返すヘルパー関数。
    見つからない場合やキャンセルの場合は None を返す。
    """
    util.send_text_by_key(
        chan, prompt_key, current_menu_mode, add_newline=False)
    user_input = chan.process_input()
    if user_input is None or not user_input.strip():
        return None  # 切断またはキャンセル

    target_user_name = user_input.strip().upper()
    user_data = database.get_user_auth_info(target_user_name)

    if not user_data:
        util.send_text_by_key(
            chan, "sysop_menu.change_user_level.user_not_found",  # 既存のキーを流用
            current_menu_mode,
            user_id=target_user_name
        )
        return None
    return user_data


def user_delete(chan, sysop_login_id, current_menu_mode):
    """ユーザ削除"""
    util.send_text_by_key(
        chan, "sysop_menu.user_delete.header", current_menu_mode)

    user_data = _get_target_user(
        chan, "sysop_menu.user_delete.user_id_prompt", current_menu_mode)
    if not user_data:
        return None  # ユーザーが見つからないかキャンセル

    user_name_to_delete = user_data['name']
    user_id_to_delete = user_data['id']

    if user_name_to_delete.upper() == sysop_login_id.upper():
        util.send_text_by_key(
            chan, "sysop_menu.user_delete.cannot_delete_sysop", current_menu_mode)
        return None

    util.send_text_by_key(chan, "sysop_menu.user_delete.confirm_yn", current_menu_mode,
                          add_newline=False, user_name=user_name_to_delete)
    confirm_choice = chan.process_input()
    if confirm_choice is None or confirm_choice.lower().strip() != 'y':
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)
        return None

    if database.delete_user(user_id_to_delete):
        util.send_text_by_key(
            chan, "sysop_menu.user_delete.user_delete_success", current_menu_mode, user_name=user_name_to_delete)
    else:
        util.send_text_by_key(
            chan, "common_messages.error", current_menu_mode)
    return None


def view_settings(chan, _sysop_login_id, current_menu_mode):
    """設定一覧表示"""
    server_prefs_list = database.read_server_pref()
    if server_prefs_list:
        # sqlite_tools.read_server_pref が返すリストの順序と一致させる必要がある
        all_pref_names = ['bbs', 'chat', 'mail', 'telegram',
                          'userpref', 'who', 'default_exploration_list', 'hamlet']
        server_prefs_dict = dict(zip(all_pref_names, server_prefs_list))

        # vset で表示する項目
        display_pref_names = ['bbs', 'chat', 'mail',
                              'telegram', 'userpref', 'who', 'hamlet']

        util.send_text_by_key(
            chan, "sysop_menu.view_settings.header", current_menu_mode)
        for name in display_pref_names:
            value = server_prefs_dict.get(name, '(error)')
            line = '{:<20} {:<20}\r\n'.format(str(name), str(value))
            chan.send(line.encode('utf-8'))

        chan.send(('-' * 41 + "\r\n").encode('utf-8'))
    else:
        util.send_text_by_key(
            chan, "sysop_menu.view_settings.no_settings_error", current_menu_mode)
    return None


def change_top_menu_permission(chan, _sysop_login_id, current_menu_mode):
    """トップメニューのアクセス権限変更"""
    util.send_text_by_key(
        chan, "sysop_menu.set_permissions.header", current_menu_mode)
    valid_menus = ['bbs', 'chat', 'mail',
                   'telegram', 'userpref', 'who', 'hamlet']
    menu_to_change = None

    while menu_to_change is None:
        util.send_text_by_key(
            chan, "sysop_menu.set_permissions.prompt", current_menu_mode, add_newline=False)
        menu_input = chan.process_input()
        if menu_input is None:
            return None

        menu_to_change_input = menu_input.lower().strip()
        if menu_to_change_input in valid_menus:
            menu_to_change = menu_to_change_input
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode)

    user_level = None
    while user_level is None:
        util.send_text_by_key(
            chan, "sysop_menu.set_permissions.user_level_message", current_menu_mode)
        util.send_text_by_key(
            chan, "sysop_menu.set_permissions.user_level_prompt", current_menu_mode, add_newline=False)
        level_input = chan.process_input()
        if level_input is None:
            return None

        if level_input.lower().strip() == 'q':
            util.send_text_by_key(
                chan, "common_messages.cancel", current_menu_mode)
            return None

        try:
            level_val = int(level_input)
            if 0 <= level_val <= 5:
                user_level = level_val
            else:
                util.send_text_by_key(
                    chan, "sysop_menu.set_permissions.user_level_0-5_message", current_menu_mode)
        except ValueError:
            util.send_text_by_key(
                chan, "sysop_menu.set_permissions.user_level_0-5_message", current_menu_mode)

    try:
        # MariaDB用の関数を呼び出す。server_prefテーブルは1行しかなく、id=1と仮定
        database.update_record(
            'server_pref', {menu_to_change: user_level}, {'id': 1})
        util.send_text_by_key(chan, "sysop_menu.set_permissions.user_level_changed", current_menu_mode,
                              menu_to_change=menu_to_change, user_level=user_level)
    except Exception as e:
        util.send_text_by_key(
            chan, "common_messages.database_update_error", current_menu_mode)
        logging.error(f"トップメニュー権限のデータベース更新エラー: {e}")
    return None


def change_user_level(chan, sysop_login_id, current_menu_mode):
    """ユーザレベルの変更"""
    util.send_text_by_key(
        chan, "sysop_menu.change_user_level.header", current_menu_mode)

    user_data = _get_target_user(
        chan, "sysop_menu.change_user_level.user_name_prompt", current_menu_mode)
    if not user_data:
        return None  # ユーザーが見つからないかキャンセル

    user_id_to_change = user_data['id']
    user_name_to_change = user_data['name']
    current_level = user_data['level']

    # GUESTユーザーのレベル変更を禁止
    if user_name_to_change.upper() == 'GUEST':
        util.send_text_by_key(
            chan, "sysop_menu.change_user_level.cannot_change_guest", current_menu_mode)
        return None

    util.send_text_by_key(chan, "sysop_menu.change_user_level.current_level_info", current_menu_mode,
                          name=user_name_to_change, user_id=user_id_to_change, level=current_level)
    util.send_text_by_key(
        chan, "sysop_menu.change_user_level.new_level_prompt", current_menu_mode, add_newline=False)
    new_level_input = chan.process_input()
    if new_level_input is None:
        return None
    new_level = new_level_input.strip()
    if not new_level:
        return None

    try:
        new_level = int(new_level_input)
        if not (0 <= new_level <= 5):
            util.send_text_by_key(
                chan, "sysop_menu.change_user_level.invalid_level_range", current_menu_mode)
            return None
    except ValueError:
        util.send_text_by_key(
            chan, "sysop_menu.change_user_level.invalid_level_range", current_menu_mode)
        return None

    if new_level == current_level:
        util.send_text_by_key(
            chan, "sysop_menu.change_user_level.no_change_level_same", current_menu_mode)
        return None

    util.send_text_by_key(chan, "sysop_menu.change_user_level.confirm_yn", current_menu_mode,
                          name=user_name_to_change, old_level=current_level, new_level=new_level, add_newline=False)
    confirm_input = chan.process_input()
    if confirm_input is None:
        return None
    confirm_input = confirm_input.lower().strip()

    if confirm_input == 'y':
        if database.update_record('users', {'level': new_level}, {'id': user_id_to_change}):
            util.send_text_by_key(
                chan, "sysop_menu.change_user_level.success", current_menu_mode)
    return None


def change_user_password_by_sysop(chan, sysop_login_id, current_menu_mode):
    """ シスオペによるユーザーパスワード再発行 """
    util.send_text_by_key(
        chan, "sysop_menu.change_user_password.header", current_menu_mode)

    user_data = _get_target_user(
        chan, "sysop_menu.change_user_password.user_id_prompt", current_menu_mode)
    if not user_data:
        return None  # ユーザーが見つからないかキャンセル

    user_id_to_change = user_data['id']
    user_name_to_change = user_data['name']

    if user_name_to_change.upper() == sysop_login_id.upper():
        util.send_text_by_key(chan, "sysop_menu.change_user_password.cannot_change_sysop",
                              current_menu_mode)
        return None

    # ランダムな12文字のパスワードを生成
    new_password = secrets.token_urlsafe(9)  # 12文字のランダムな文字列（URLセーフ）

    util.send_text_by_key(chan, "sysop_menu.change_user_password.confirm_yn",
                          current_menu_mode, name=user_name_to_change, new_password=new_password, add_newline=False)
    confirm_input = chan.process_input()
    if confirm_input is None:
        return None

    confirm_input = confirm_input.lower().strip()
    if confirm_input == 'y':
        # パスワードをハッシュ化して更新
        salt_hex, hashed_password = util.hash_password(new_password)
        if database.update_record('users', {'password': hashed_password, 'salt': salt_hex}, {'id': user_id_to_change}):
            util.send_text_by_key(chan, "sysop_menu.change_user_password.success",
                                  current_menu_mode, name=user_name_to_change, new_password=new_password)
        else:
            util.send_text_by_key(
                chan, "common_messages.database_update_error", current_menu_mode)
            logging.error(f"パスワード更新エラー (ユーザー: {user_name_to_change})")
    else:
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)
    return None


def system_quit(chan, _sysop_login_id, current_menu_mode):
    """システム強制終了"""
    util.send_text_by_key(
        chan, "sysop_menu.system_quit.header", current_menu_mode)
    util.send_text_by_key(chan, "common_messages.confirm_yn",
                          current_menu_mode, add_newline=False)
    continue_choice = chan.process_input()
    if continue_choice is None:
        return None

    if continue_choice.lower().strip() == 'y':
        util.send_text_by_key(
            chan, "sysop_menu.system_quit.system_down_requested", current_menu_mode)
        os._exit(0)  # 注意: os._exit は即時終了。os.exit から変更
    return None


def make_board(chan, sysop_login_id, current_menu_mode):
    """掲示板作成"""
    util.send_text_by_key(
        chan, "sysop_menu.make_board.header_direct", current_menu_mode)
    shortcut_id = ""
    while not shortcut_id:
        util.send_text_by_key(
            chan, "sysop_menu.make_board.shortcut_id_prompt", current_menu_mode, add_newline=False)
        shortcut_id_input = chan.process_input()
        if shortcut_id_input is None:
            return None
        shortcut_id = shortcut_id_input.strip()
        if not shortcut_id:
            return None
        if database.get_board_by_shortcut_id(shortcut_id):
            util.send_text_by_key(chan, "sysop_menu.make_board.shortcut_id_exists",
                                  current_menu_mode, shortcut_id=shortcut_id)
            shortcut_id = ""

    board_name = ""
    while not board_name:
        util.send_text_by_key(
            chan, "sysop_menu.make_board.name_prompt", current_menu_mode, add_newline=False)
        name_input = chan.process_input()
        if name_input is None:
            return None
        board_name = name_input.strip()
        if not board_name:
            util.send_text_by_key(
                chan, "sysop_menu.make_board.name_required", current_menu_mode)

    util.send_text_by_key(
        chan, "sysop_menu.make_board.description_prompt", current_menu_mode, add_newline=False)
    desc_input = chan.process_input()
    if desc_input is None:
        return None
    description = desc_input.strip()

    board_type = ""
    balid_types = ["simple", "thread"]
    while board_type not in balid_types:
        util.send_text_by_key(chan, "sysop_menu.make_board.board_type_prompt", current_menu_mode,
                              types=", ".join(balid_types), add_newline=False)
        type_input = chan.process_input()
        if type_input is None:
            return None
        board_type = type_input.strip().lower()
        if not board_type:
            board_type = "simple"
        if board_type not in balid_types:
            util.send_text_by_key(chan, "sysop_menu.make_board.invalid_board_type", current_menu_mode,
                                  types=", ".join(balid_types))

    default_permission = ""
    valid_permissions = ["open", "close", "readonly"]
    while default_permission not in valid_permissions:
        util.send_text_by_key(chan, "sysop_menu.make_board.default_permission_prompt", current_menu_mode,
                              permissions=", ".join(valid_permissions), add_newline=False)
        permission_input = chan.process_input()
        if permission_input is None:
            return None
        default_permission = permission_input.strip().lower()
        if default_permission not in valid_permissions:
            util.send_text_by_key(chan, "sysop_menu.make_board.invalid_permission", current_menu_mode,
                                  permission=", ".join(valid_permissions))

    read_level = 1
    while True:
        chan.send("閲覧レベル (1-5, デフォルト:1): ".encode('utf-8'))
        level_input = chan.process_input()
        if level_input is None:
            return None
        if not level_input.strip():
            break
        try:
            level = int(level_input)
            if 1 <= level <= 5:
                read_level = level
                break
        except ValueError:
            pass

    write_level = 1
    while True:
        chan.send("書込レベル (1-5, デフォルト:1): ".encode('utf-8'))
        level_input = chan.process_input()
        if level_input is None:
            return None
        if not level_input.strip():
            break
        try:
            level = int(level_input)
            if 1 <= level <= 5:
                write_level = level
                break
        except ValueError:
            pass

    operators_json = f'["{sysop_login_id}"]'
    kanban_body = ""
    status = "active"

    util.send_text_by_key(chan, "sysop_menu.make_board.confirm_create_yn", current_menu_mode,
                          shortcut_id=shortcut_id, board_name=board_name, permission=default_permission,
                          operator=sysop_login_id, add_newline=False)
    confirm_create = chan.process_input()
    if confirm_create is None or confirm_create.lower().strip() != 'y':
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)
        return None

    if database.create_board_entry(shortcut_id, board_name, description, operators_json, default_permission, kanban_body, status, read_level, write_level, board_type):
        util.send_text_by_key(chan, "sysop_menu.make_board.success_direct",
                              current_menu_mode, shortcut_id=shortcut_id)
        util.send_text_by_key(
            chan, "sysop_menu.make_board.advise_bbs_yaml", current_menu_mode)
    else:
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
        logging.error(f"掲示板作成失敗:{shortcut_id}")
    return None


def delete_board(chan, _sysop_login_id, current_menu_mode):
    """掲示板削除"""
    util.send_text_by_key(
        chan, "sysop_menu.delete_board.header", current_menu_mode)
    while True:
        util.send_text_by_key(
            chan, "sysop_menu.delete_board.delete_board_prompt", current_menu_mode, add_newline=False)
        board_id_input = chan.process_input()
        if board_id_input is None:
            return None
        if not board_id_input.strip():
            return None

        shortcut_id_to_delete = board_id_input.strip()
        board_db_entry = database.get_board_by_shortcut_id(
            shortcut_id_to_delete)
        if not board_db_entry:
            util.send_text_by_key(
                chan, "sysop_menu.delete_board.board_not_found", current_menu_mode)
            continue

        board_name_to_display = board_db_entry['name'] if board_db_entry and 'name' in board_db_entry.keys(
        ) else shortcut_id_to_delete
        chan.send(
            f"\"{board_name_to_display}\" (ID: {shortcut_id_to_delete})\r\n")
        util.send_text_by_key(chan, "sysop_menu.delete_board.confirm_yn", current_menu_mode,
                              board_name=board_name_to_display, add_newline=False)
        confirm_choice = chan.process_input()
        if confirm_choice is None:
            return None

        if confirm_choice.lower().strip() == 'y':
            if database.delete_board_entry(shortcut_id_to_delete):
                util.send_text_by_key(
                    chan, "sysop_menu.delete_board.advise_bbs_yaml_delete", current_menu_mode)
                return None
            else:
                util.send_text_by_key(
                    chan, "common_messages.error", current_menu_mode)
                logging.error(
                    f"掲示板の削除に失敗しました(board_id: {shortcut_id_to_delete})")
                continue
        else:
            util.send_text_by_key(
                chan, "common_messages.cancel", current_menu_mode)
            return None


def list_boards(chan, _sysop_login_id, current_menu_mode):
    """DBに登録されている掲示板一覧を表示"""
    boards = database.get_all_boards_for_sysop_list()
    if not boards:
        util.send_text_by_key(
            chan, "sysop_menu.list_boards.no_boards", current_menu_mode)
        return None

    util.send_text_by_key(
        chan, "sysop_menu.list_boards.header_title", current_menu_mode)
    header_line = f"{'ID':<15} {'Name':<18} {'Perm':<8} {'R/W':<5} {'Status':<8} {'LastPost':<16} {'Ops'}\r\n"
    separator_line = "-" * 83 + "\r\n"
    chan.send(header_line.encode('utf-8'))
    chan.send(separator_line.encode('utf-8'))

    board_list_details = ""
    for board in boards:
        shortcut_id_str = board['shortcut_id']
        name_str = board['name']
        name_str = (name_str[:15] + "...") if len(name_str) > 16 else name_str
        operators_str = board['operators']
        default_permission_str = board['default_permission']
        status_str = board['status']
        read_level_str = str(board['read_level']
                             ) if 'read_level' in board.keys() else ''
        write_level_str = str(board['write_level']
                              ) if 'write_level' in board.keys() else ''

        last_posted_ts = board['last_posted_at']
        last_posted_str = "N/A"
        if last_posted_ts and last_posted_ts > 0:
            try:
                last_posted_str = datetime.datetime.fromtimestamp(
                    last_posted_ts).strftime('%Y-%m-%d %H:%M')
            except (ValueError, OSError, TypeError):
                last_posted_str = 'Invalid Date'
        board_list_details += f"{shortcut_id_str:<15} {name_str:<18} {default_permission_str:<8} {read_level_str}/{write_level_str:<3} {status_str:<8} {last_posted_str:<16} {operators_str}\r\n"
    chan.send(board_list_details.encode('utf-8'))
    chan.send(separator_line.encode('utf-8'))
    return None


def change_board_settings(chan, _sysop_login_id, current_menu_mode):
    """掲示板の設定（R/Wレベルなど）を変更する"""
    util.send_text_by_key(
        chan, "sysop_menu.change_board.header", current_menu_mode)

    # 掲示板IDの入力
    util.send_text_by_key(
        chan, "sysop_menu.change_board.shortcut_id_prompt", current_menu_mode, add_newline=False)
    shortcut_id_input = chan.process_input()
    if not shortcut_id_input or not shortcut_id_input.strip():
        return None
    shortcut_id = shortcut_id_input.strip()

    # 掲示板情報の取得
    board_info = database.get_board_by_shortcut_id(shortcut_id)
    if not board_info:
        util.send_text_by_key(
            chan, "sysop_menu.delete_board.board_not_found", current_menu_mode, shortcut_id=shortcut_id)
        return None

    board_id_pk = board_info['id']
    current_read_level = board_info['read_level'] if 'read_level' in board_info.keys(
    ) else 1
    current_write_level = board_info['write_level'] if 'write_level' in board_info.keys(
    ) else 1

    # 現在の設定を表示
    util.send_text_by_key(chan, "sysop_menu.change_board.current_settings", current_menu_mode,
                          shortcut_id=shortcut_id,
                          read_level=current_read_level,
                          write_level=current_write_level)

    # 新しい閲覧レベルの入力
    new_read_level = current_read_level
    chan.send(
        f"新しい閲覧レベル (1-5, 現在:{current_read_level}, 空入力で変更なし): ".encode('utf-8'))
    level_input = chan.process_input()
    if level_input is None:
        return None
    if level_input.strip():
        try:
            level = int(level_input)
            if 1 <= level <= 5:
                new_read_level = level
            else:
                util.send_text_by_key(
                    chan, "sysop_menu.change_user_level.invalid_level_range", current_menu_mode)
                return None
        except ValueError:
            util.send_text_by_key(
                chan, "sysop_menu.change_user_level.invalid_level_range", current_menu_mode)
            return None

    # 新しい書き込みレベルの入力
    new_write_level = current_write_level
    chan.send(
        f"新しい書込レベル (1-5, 現在:{current_write_level}, 空入力で変更なし): ".encode('utf-8'))
    level_input = chan.process_input()
    if level_input is None:
        return None
    if level_input.strip():
        try:
            level = int(level_input)
            if 1 <= level <= 5:
                new_write_level = level
            else:
                util.send_text_by_key(
                    chan, "sysop_menu.change_user_level.invalid_level_range", current_menu_mode)
                return None
        except ValueError:
            util.send_text_by_key(
                chan, "sysop_menu.change_user_level.invalid_level_range", current_menu_mode)
            return None

    # 変更内容の確認
    if new_read_level == current_read_level and new_write_level == current_write_level:
        util.send_text_by_key(
            chan, "sysop_menu.change_board.no_changes", current_menu_mode)
        return None

    util.send_text_by_key(chan, "sysop_menu.change_board.confirm_yn", current_menu_mode,
                          shortcut_id=shortcut_id,
                          old_read=current_read_level, new_read=new_read_level,
                          old_write=current_write_level, new_write=new_write_level,
                          add_newline=False)
    confirm = chan.process_input()
    if confirm is None or confirm.strip().lower() != 'y':
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)
        return None

    # DB更新
    if database.update_record('boards', {'read_level': new_read_level, 'write_level': new_write_level}, {'id': board_id_pk}):
        util.send_text_by_key(
            chan, "sysop_menu.change_board.success", current_menu_mode, shortcut_id=shortcut_id)
    else:
        util.send_text_by_key(
            chan, "common_messages.database_update_error", current_menu_mode)

    return None
