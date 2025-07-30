import datetime
import re
import logging

from . import util, sqlite_tools


def userpref_menu(chan, dbname, login_id, display_name, current_menu_mode):
    """ユーザー設定メニュー"""
    # 最初にユーザー情報を一括で取得
    user_data = sqlite_tools.get_user_auth_info(dbname, login_id)
    if not user_data:
        util.send_text_by_key(
            chan, "common_messages.user_not_found", current_menu_mode)
        logging.error(f"ユーザー設定メニュー表示時にユーザーが見つかりません: {login_id}")
        return None

    # コマンドと対応する関数のディスパッチテーブル
    command_dispatch = {
        '1': change_menu_mode,
        '2': change_password,
        '3': change_profile,
        '4': show_member_list,  # bbsmenu.who_menu を呼び出すように変更しても良い
        '5': set_lastlogin_datetime,
        '6': register_exploration_list,
        '7': read_exploration_list,
        '8': read_server_default_exploration_list,
        '9': set_telegram_restriction,
        '10': edit_blacklist,
        '11': change_email_address,
        'e': lambda *args, **kwargs: "back_to_top",  # メニュー終了
        '': lambda *args, **kwargs: "back_to_top",   # 空入力もメニュー終了
        'h': display_help,
        '?': display_help,
    }

    while True:
        util.send_text_by_key(chan, "user_pref_menu.header", current_menu_mode)
        util.prompt_handler(chan, dbname, login_id, current_menu_mode)
        util.send_text_by_key(chan, "common_messages.select_prompt",
                              current_menu_mode, add_newline=False)  # プロンプト表示
        input_buffer = chan.process_input()
        if input_buffer is None:
            return None  # 接続が切れた場合

        command = input_buffer.lower().strip()
        # ディスパッチテーブルからコマンドに対応する関数を取得
        handler = command_dispatch.get(command)
        if handler:
            # 各ハンドラに user_data を渡す
            result = handler(chan, dbname, login_id,
                             current_menu_mode, user_data)
            # メニューモード変更や終了の場合、結果を返す
            if result in ('1', '2', '3', 'back_to_top', None):
                return result
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode)  # 無効なコマンド


def display_help(chan, dbname, login_id, current_menu_mode, user_data):
    """ヘルプメッセージを表示"""
    util.send_text_by_key(chan, "user_pref_menu.help", current_menu_mode)
    return None


# 以下の関数は変更なし（必要に応じてリファクタリング可能）
def change_menu_mode(chan, dbname, login_id, current_menu_mode, user_data):
    """メニューモード変更"""
    user_id = user_data['id']
    while True:
        util.send_text_by_key(
            chan, "user_pref_menu.mode_selection.header", current_menu_mode)
        util.send_text_by_key(
            chan, "common_messages.select_prompt", current_menu_mode, add_newline=False)
        choice = chan.process_input()
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
            return "back_to_top"
        else:
            continue

        if new_menu_mode:
            if sqlite_tools.update_user_menu_mode(dbname, user_id, new_menu_mode):
                util.send_text_by_key(chan, "user_pref_menu.mode_selection.confirm_changed",
                                      current_menu_mode, mode=new_menu_mode)
                return new_menu_mode
            else:
                util.send_text_by_key(
                    chan, "user_pref_menu.mode_selection.confirm_failed", current_menu_mode)
            return "back_to_top"


def show_member_list(chan, dbname, login_id, current_menu_mode, user_data):
    """会員リストを表示する"""
    util.send_text_by_key(
        chan, "user_pref_menu.member_list.search_prompt", current_menu_mode, add_newline=False)
    search_word = chan.process_input()
    member_list = sqlite_tools.get_memberlist(dbname, search_word)
    if member_list:
        for member in member_list:
            chan.send(
                f"{member.get('name', 'N/A')} {member.get('comment', 'N/A')}\r\n")
    else:
        util.send_text_by_key(chan, "user_pref_menu.member_list.notfound",
                              current_menu_mode)
    return None


def change_password(chan, dbname, login_id, current_menu_mode, user_data):
    """パスワード変更"""
    security_config = util.app_config.get('security', {})

    util.send_text_by_key(chan, "user_pref_menu.change_password.current_password",
                          current_menu_mode, add_newline=False)
    current_pass = chan.hide_process_input()
    if current_pass is None or not current_pass:
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)
        return None

    if not util.verify_password(user_data['password'], user_data['salt'], current_pass):
        util.send_text_by_key(
            chan, "user_pref_menu.change_password.invalid_password", current_menu_mode)
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)
        return None

    while True:
        util.send_text_by_key(chan, "user_pref_menu.change_password.new_password",
                              current_menu_mode, add_newline=False)
        new_pass1 = chan.hide_process_input()
        if new_pass1 is None:
            util.send_text_by_key(
                chan, "common_messages.cancel", current_menu_mode)
            return None

        pw_min_len = security_config.get('PASSWORD_MIN_LENGTH', 8)
        pw_max_len = security_config.get('PASSWORD_MAX_LENGTH', 64)
        if not (pw_min_len <= len(new_pass1) <= pw_max_len):
            util.send_text_by_key(
                chan, "user_pref_menu.change_password.error_password_length", current_menu_mode, min_len=pw_min_len, max_len=pw_max_len)
            continue

        util.send_text_by_key(
            chan, "user_pref_menu.change_password.new_password_confirm", current_menu_mode, add_newline=False)
        new_pass2 = chan.hide_process_input()
        if new_pass2 is None:
            util.send_text_by_key(
                chan, "common_messages.cancel", current_menu_mode)
            return None

        if new_pass1 == new_pass2:
            break
        else:
            util.send_text_by_key(
                chan, "user_pref_menu.change_password.password_mismatch", current_menu_mode)

    new_salt_hex, new_hashed_password = util.hash_password(new_pass1)
    if sqlite_tools.update_user_password_and_salt(dbname, login_id, new_hashed_password, new_salt_hex):
        util.send_text_by_key(
            chan, "user_pref_menu.change_password.password_changed", current_menu_mode)
    else:
        util.send_text_by_key(chan, "common_messages.error",
                              current_menu_mode)
        logging.error(f"パスワード変更エラー({login_id})")
    return None


def change_profile(chan, dbname, login_id, current_menu_mode, user_data):
    """プロフィール変更"""
    current_comment = user_data.get('comment', '')
    util.send_text_by_key(chan, "user_pref_menu.change_profile.current_profile",
                          current_menu_mode, comment=current_comment)
    util.send_text_by_key(
        chan, "user_pref_menu.change_profile.new_profile", current_menu_mode, add_newline=False)
    new_comment = chan.process_input()

    if new_comment is None:
        return None
    if new_comment == '':
        util.send_text_by_key(
            chan, "user_pref_menu.change_profile.cancelled", current_menu_mode)
        return None
    try:
        if sqlite_tools.update_user_profile_comment(dbname, user_data['id'], new_comment):
            util.send_text_by_key(
                chan, "user_pref_menu.change_profile.profile_updated", current_menu_mode)
        else:
            raise Exception("コメント更新に失敗")
    except Exception as e:
        logging.error(f"コメント更新エラー: {e}")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
    return None


def set_lastlogin_datetime(chan, dbname, login_id, current_menu_mode, user_data):
    """最終ログイン日時を手動で設定"""
    user_id = user_data.get('id')
    current_lastlogin_ts = user_data['lastlogin']

    current_lastlogin_str = "None"
    if current_lastlogin_ts and current_lastlogin_ts > 0:
        try:
            current_lastlogin_str = datetime.datetime.fromtimestamp(
                current_lastlogin_ts).strftime('%Y-%m-%d %H:%M:%S')
        except (OSError, TypeError, ValueError):
            current_lastlogin_str = "Unknown datetime"
    util.send_text_by_key(
        chan, "user_pref_menu.set_lastlogin.current_lastlogin", current_menu_mode, lastlogin=current_lastlogin_str)

    while True:
        util.send_text_by_key(
            chan, "user_pref_menu.set_lastlogin.newe_datetime", current_menu_mode, add_newline=False)
        datetime_str_input = chan.process_input()

        if datetime_str_input is None:
            return None
        if not datetime_str_input:
            util.send_text_by_key(
                chan, "user_pref_menu.set_lastlogin.cancelled", current_menu_mode)
            return None

        new_datetime_obj = None
        datetime_formats_to_try = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%y-%m-%d %H:%M:%S',
            '%y-%m-%d %H:%M',
        ]

        for fmt in datetime_formats_to_try:
            try:
                new_datetime_obj = datetime.datetime.strptime(
                    datetime_str_input, fmt)
                break
            except ValueError:
                continue
        if new_datetime_obj is None:
            util.send_text_by_key(
                chan, "user_pref_menu.set_lastlogin.invalid_format", current_menu_mode)
            continue

        new_timestamp = int(new_datetime_obj.timestamp())

        try:
            sqlite_tools.update_idbase(
                dbname, 'users', ['lastlogin'], user_id, 'lastlogin', new_timestamp)
            util.send_text_by_key(
                chan, "user_pref_menu.set_lastlogin.updated", current_menu_mode)
            return None
        except Exception as e:
            logging.error(f"最終ログイン日時更新エラー: {e}")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
            return None


def set_telegram_restriction(chan, dbname, login_id, current_menu_mode, user_data):
    """電報受信制限設定"""
    user_id = user_data.get('id')

    while True:
        util.send_text_by_key(
            chan, "user_pref_menu.telegram_restriction.prompt", current_menu_mode, add_newline=False)
        choice = chan.process_input()
        new_restriction_level = -1
        new_restridtion_lebel_text = ""
        if choice == '1':
            new_restriction_level = 0
            new_restridtion_lebel_text = util.get_text_by_key(
                "user_pref_menu.telegram_restriction.recieve_all", current_menu_mode)
        elif choice == '2':
            new_restriction_level = 1
            new_restridtion_lebel_text = util.get_text_by_key(
                "user_pref_menu.telegram_restriction.members_only", current_menu_mode)
        elif choice == '3':
            new_restriction_level = 2
            new_restridtion_lebel_text = util.get_text_by_key(
                "user_pref_menu.telegram_restriction.reject_all", current_menu_mode)
        elif choice == '4':
            new_restriction_level = 3
            new_restridtion_lebel_text = util.get_text_by_key(
                "user_pref_menu.telegram_restriction.reject_black_list", current_menu_mode)
        else:
            return None

        if sqlite_tools.update_user_telegram_restriction(dbname, user_id, new_restriction_level):
            chan.send(new_restridtion_lebel_text + "\r\n")
            return None
        else:
            logging.error(f"電報受信制限更新時にエラーが発生しました。{login_id}")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
            return None


def edit_blacklist(chan, dbname, login_id, current_menu_mode, user_data):
    """ブラックリスト編集"""
    user_id = user_data.get('id')
    current_blacklist_str = user_data.get('blacklist', '')

    util.send_text_by_key(
        chan, "user_pref_menu.blacklist_edit.header", current_menu_mode)
    util.send_text_by_key(
        chan, "user_pref_menu.blacklist_edit.current_blacklist_header", current_menu_mode)

    if current_blacklist_str:
        current_user_id_strs = [uid_str.strip(
        ) for uid_str in current_blacklist_str.split(',') if uid_str.strip().isdigit()]
        display_login_ids = []

        if current_user_id_strs:
            id_to_name_map = sqlite_tools.get_user_names_from_user_ids(
                dbname, current_user_id_strs)
            for uid_str in current_user_id_strs:
                user_id_int = int(uid_str)
                login_name = id_to_name_map.get(user_id_int)
                display_login_ids.append(
                    login_name if login_name else f"(ID:{uid_str} 不明)")

        if display_login_ids:
            util.send_text_by_key(
                chan, "user_pref_menu.blacklist_edit.current_list_display", current_menu_mode, blacklist_users=", ".join(display_login_ids))
        else:
            util.send_text_by_key(
                chan, "user_pref_menu.blacklist_edit.no_blacklist", current_menu_mode)
    else:
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.no_blacklist", current_menu_mode)

    util.send_text_by_key(chan, "user_pref_menu.blacklist_edit.confirm_change_prompt",
                          current_menu_mode, add_newline=False)
    Confirm_choice = chan.process_input()

    if Confirm_choice is None or Confirm_choice.lower() != "y":
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.cancelled", current_menu_mode)
        return None

    util.send_text_by_key(chan, "user_pref_menu.blacklist_edit.new_list_prompt",
                          current_menu_mode, add_newline=False)
    new_blacklist_login_ids_input_str = chan.process_input()

    if new_blacklist_login_ids_input_str is None:
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.cancelled", current_menu_mode)
        return None

    new_blacklist_login_ids_input_str = new_blacklist_login_ids_input_str.strip()
    validated_user_ids_for_db = []

    if not new_blacklist_login_ids_input_str:
        pass
    else:
        input_login_ids = [name.strip(
        ) for name in new_blacklist_login_ids_input_str.split(',') if name.strip()]

        if not input_login_ids and new_blacklist_login_ids_input_str:
            util.send_text_by_key(
                chan, "user_pref_menu.blacklist_edit.invalid_id_format", current_menu_mode)
            return None

        for target_login_id_str in input_login_ids:
            if not target_login_id_str:
                continue

            if target_login_id_str == login_id:
                continue

            target_user_id_from_db = sqlite_tools.get_user_id_from_user_name(
                dbname, target_login_id_str)

            if target_user_id_from_db is None:
                util.send_text_by_key(chan, "user_pref_menu.blacklist_edit.user_id_not_found",
                                      current_menu_mode, user_id=target_login_id_str)
                return None

            validated_user_ids_for_db.append(str(target_user_id_from_db))

    if validated_user_ids_for_db:
        unique_sorted_user_ids = sorted(
            list(set(map(int, validated_user_ids_for_db))))
        final_blacklist_db_str = ",".join(map(str, unique_sorted_user_ids))
    else:
        final_blacklist_db_str = ""

    if sqlite_tools.update_user_blacklist(dbname, user_id, final_blacklist_db_str):
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.update_success", current_menu_mode)
    else:
        logging.error(f"ブラックリスト更新時にエラーが発生しました。{login_id}")
        util.send_text_by_key(
            chan, "common_messages.error", current_menu_mode)
    return None


def register_exploration_list(chan, dbname, login_id, current_menu_mode, user_data):
    """探索リスト登録"""
    user_id = user_data.get('id')

    # util.pyの共通関数を呼び出す。保存処理はラムダ式で渡す。
    def save_func(exploration_list_str): return sqlite_tools.set_user_exploration_list(
        dbname, user_id, exploration_list_str)
    util.prompt_and_save_exploration_list(
        chan, current_menu_mode, save_func)
    return None


def read_exploration_list(chan, dbname, login_id, current_menu_mode, user_data):
    """探索リスト読み出し"""
    user_id = user_data.get('id')
    exploration_list_str = sqlite_tools.get_user_exploration_list(
        dbname, user_id)
    util.display_exploration_list(chan, exploration_list_str)
    return None


def read_server_default_exploration_list(chan, dbname, login_id, current_menu_mode, user_data):
    """元探索リスト読み出し"""
    server_prefs = sqlite_tools.read_server_pref(dbname)
    if not server_prefs or len(server_prefs) <= 6:
        logging.error("サーバ設定の読み込みに失敗したか、共通探索リストの項目がありません。")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
        return None

    default_exploration_list_str = server_prefs[6]
    util.display_exploration_list(chan, default_exploration_list_str)
    return None


def change_email_address(chan, dbname, login_id, current_menu_mode, user_data):
    """メールアドレス変更"""
    user_id = user_data.get('id')
    email_from_db = user_data.get('email')
    current_email = email_from_db if email_from_db is not None else ''

    util.send_text_by_key(chan, "user_pref_menu.change_email.current_email",
                          current_menu_mode, email=current_email)
    util.send_text_by_key(
        chan, "user_pref_menu.change_email.new_email_prompt", current_menu_mode, add_newline=False)
    new_email_input = chan.process_input()

    if new_email_input is None:
        return None

    new_email = new_email_input.strip()

    if not new_email:
        return None

    if not util.is_valid_email(new_email):
        util.send_text_by_key(
            chan, "user_pref_menu.change_email.invalid_format", current_menu_mode)
        return None
    if sqlite_tools.update_user_email(dbname, user_id, new_email):
        util.send_text_by_key(
            chan, "user_pref_menu.change_email.updated", current_menu_mode)
        logging.info(f"ユーザID {user_id} のメールアドレスを {new_email} に更新しました。")
    else:
        util.send_text_by_key(
            chan, "common_messages.db_update_error", current_menu_mode)
    return None
