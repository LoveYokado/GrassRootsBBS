# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""ユーザー設定メニューハンドラ。

このモジュールは、ユーザー設定メニューのUIとロジックを提供します。
ユーザーは、パスワード、プロフィール、メニューモードの変更や、Passkey、
探索リストなどの高度な機能の管理といった、自身のアカウント設定を管理できます。
"""

import datetime
import logging

from . import util, database


def userpref_menu(chan, login_id, display_name, current_menu_mode):
    """ユーザー設定メニューを表示し、コマンドをディスパッチします。"""
    user_data = database.get_user_auth_info(login_id)
    if not user_data:
        util.send_text_by_key(
            chan, "common_messages.user_not_found", current_menu_mode)
        logging.error(f"ユーザー設定メニュー表示時にユーザーが見つかりません: {login_id}")
        return None

    # --- Command Dispatch Table ---
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
        '12': manage_passkeys,
        '': lambda *args, **kwargs: "back_to_top",   # 空入力もメニュー終了
        'h': display_help,
        '?': display_help,
    }

    # Show mobile-specific buttons
    chan.send(b'\x1b[?2028h')
    try:
        while True:
            util.send_text_by_key(
                chan, "user_pref_menu.header", current_menu_mode)
            util.prompt_handler(chan, login_id, current_menu_mode)
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
                result = handler(chan, login_id,
                                 current_menu_mode, user_data)
                # メニューモード変更や終了の場合、結果を返す
                if result in ('1', '2', '3', 'back_to_top', None):
                    return result
            else:
                util.send_text_by_key(
                    chan, "common_messages.invalid_command", current_menu_mode)  # 無効なコマンド
    finally:
        # メニューを抜ける際に必ずボタンを非表示にする
        chan.send(b'\x1b[?2028l')


def display_help(chan, login_id, current_menu_mode, user_data):
    """ユーザー設定メニューのヘルプメッセージを表示します。"""
    util.send_text_by_key(chan, "user_pref_menu.help", current_menu_mode)
    return None


def change_menu_mode(chan, login_id, current_menu_mode, user_data):
    """ユーザーのメニュー表示モードを変更します。"""
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
            if database.update_record('users', {'menu_mode': new_menu_mode}, {'id': user_id}):
                util.send_text_by_key(chan, "user_pref_menu.mode_selection.confirm_changed",
                                      current_menu_mode, mode=new_menu_mode)
                return new_menu_mode
            else:
                util.send_text_by_key(
                    chan, "common_messages.db_update_error", current_menu_mode)
            return "back_to_top"


def show_member_list(chan, login_id, current_menu_mode, user_data):
    """検索可能な全登録メンバーのリストを表示します。"""
    util.send_text_by_key(
        chan, "user_pref_menu.member_list.search_prompt", current_menu_mode, add_newline=False)
    search_word = chan.process_input()
    member_list = database.get_memberlist(search_word)  # noqa
    if member_list:
        # ヘッダーを追加して見やすくする
        header = f"{'NAME':<20} {'COMMENT'}\r\n"
        separator = f"{'-'*20} {'-'*50}\r\n"
        chan.send(b'\r\n' + header.encode('utf-8') + separator.encode('utf-8'))
        for member in member_list:
            name = member.get('name', 'N/A')
            comment = member.get('comment', '')
            name_short = util.shorten_text_by_slicing(name, 18)
            comment_short = util.shorten_text_by_slicing(comment, 50)
            chan.send(f"{name_short:<20} {comment_short}\r\n".encode('utf-8'))
        chan.send(separator.encode('utf-8'))
    else:
        util.send_text_by_key(
            chan, "user_pref_menu.member_list.notfound", current_menu_mode)
    return None


def change_password(chan, login_id, current_menu_mode, user_data):
    """ユーザーのパスワード変更処理をハンドリングします。"""
    security_config = util.app_config.get('security', {})

    util.send_text_by_key(chan, "user_pref_menu.change_password.current_password",
                          current_menu_mode, add_newline=False)
    current_pass = chan.hide_process_input()
    chan.send(b'\r\n')
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
        chan.send(b'\r\n')
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
        chan.send(b'\r\n')
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
    if database.update_record('users', {'password': new_hashed_password, 'salt': new_salt_hex}, {'id': user_data['id']}):
        util.send_text_by_key(
            chan, "user_pref_menu.change_password.password_changed", current_menu_mode)
    else:
        util.send_text_by_key(chan, "common_messages.db_update_error",
                              current_menu_mode)
        logging.error(f"パスワード変更エラー({login_id})")
    return None


def change_profile(chan, login_id, current_menu_mode, user_data):
    """ユーザーのプロフィールコメントを変更します。"""
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

    if database.update_record('users', {'comment': new_comment}, {'id': user_data['id']}):
        util.send_text_by_key(
            chan, "user_pref_menu.change_profile.profile_updated", current_menu_mode)
    else:
        logging.error(f"コメント更新エラー: {login_id}")
        util.send_text_by_key(
            chan, "common_messages.db_update_error", current_menu_mode)
    return None


def list_passkeys(chan, login_id, current_menu_mode, user_data):
    """ユーザーアカウントに登録されている全てのPasskeyを一覧表示します。"""
    user_id_pk = user_data.get('id')
    passkeys = database.get_passkeys_by_user(user_id_pk)

    util.send_text_by_key(
        chan, "user_pref_menu.passkey_management.list_header", current_menu_mode)

    if not passkeys:
        util.send_text_by_key(
            chan, "user_pref_menu.passkey_management.no_passkeys", current_menu_mode)
    else:
        for key in passkeys:
            created_at_str = util.format_timestamp(
                key.get('created_at'), default_str='不明')
            last_used_at_str = util.format_timestamp(
                key.get('last_used_at'), default_str='未使用')
            nickname = key.get('nickname', '(ニックネームなし)')

            util.send_text_by_key(
                chan, "user_pref_menu.passkey_management.list_item_format", current_menu_mode,
                nickname=nickname, created_at=created_at_str, last_used_at=last_used_at_str)
    chan.send(b'\r\n')
    return None


def delete_passkey(chan, login_id, current_menu_mode, user_data):
    """登録済みPasskeyの削除処理をハンドリングします。"""
    user_id_pk = user_data.get('id')
    passkeys = database.get_passkeys_by_user(user_id_pk)

    if not passkeys:
        util.send_text_by_key(
            chan, "user_pref_menu.passkey_management.no_passkeys", current_menu_mode)
        return

    # 削除対象のPasskeyを一覧表示
    chan.send("--- 削除するPasskeyを選択してください ---\r\n".encode('utf-8'))
    for i, key in enumerate(passkeys):
        nickname = key.get('nickname', '(ニックネームなし)')
        created_at_str = util.format_timestamp(
            key.get('created_at'), default_str='不明')
        chan.send(
            f"[{i+1}] {nickname} (登録日: {created_at_str})\r\n".encode('utf-8'))

    util.send_text_by_key(
        chan, "user_pref_menu.passkey_management.delete_prompt", current_menu_mode, add_newline=False)
    choice_input = chan.process_input()

    if choice_input is None or not choice_input.strip():
        util.send_text_by_key(
            chan, "common_messages.cancel", current_menu_mode)
        return

    try:
        choice_index = int(choice_input) - 1
        if not (0 <= choice_index < len(passkeys)):
            raise ValueError

        key_to_delete = passkeys[choice_index]
        passkey_id_to_delete = key_to_delete['id']
        nickname_to_delete = key_to_delete.get('nickname', '(ニックネームなし)')

        util.send_text_by_key(
            chan, "user_pref_menu.passkey_management.delete_confirm_yn", current_menu_mode, nickname=nickname_to_delete, add_newline=False)
        confirm = chan.process_input()
        if confirm is None or confirm.strip().lower() != 'y':
            util.send_text_by_key(
                chan, "common_messages.cancel", current_menu_mode)
            return

        if database.delete_passkey_by_id_and_user_id(passkey_id_to_delete, user_id_pk):
            util.send_text_by_key(
                chan, "user_pref_menu.passkey_management.delete_success", current_menu_mode)
        else:
            util.send_text_by_key(
                chan, "common_messages.db_update_error", current_menu_mode)

    except ValueError:
        util.send_text_by_key(
            chan, "user_pref_menu.passkey_management.invalid_selection", current_menu_mode)


def manage_passkeys(chan, login_id, current_menu_mode, user_data):
    """Passkey管理のサブメニューを表示します。"""
    while True:
        util.send_text_by_key(
            chan, "user_pref_menu.passkey_management.header", current_menu_mode)
        util.send_text_by_key(
            chan, "common_messages.select_prompt", current_menu_mode, add_newline=False)
        choice = chan.process_input()
        if choice is None:
            return None  # disconnect

        choice = choice.strip().lower()

        if choice == '1':
            chan.send(b'\x1b[?2027h')
            util.send_text_by_key(
                chan, "user_pref_menu.passkey_management.start_registration_prompt", current_menu_mode)
            # ユーザーがブラウザでの操作を終えてEnterを押すのを待つ
            chan.process_input()
            continue  # メニューを再表示
        elif choice == '2':
            delete_passkey(chan, login_id, current_menu_mode, user_data)
            continue  # メニューを再表示
        elif choice == '3':
            list_passkeys(chan, login_id, current_menu_mode, user_data)
            continue  # メニューを再表示
        elif choice == 'e' or choice == '':
            return None
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode)


def set_lastlogin_datetime(chan, login_id, current_menu_mode, user_data):
    """ユーザーの最終ログイン日時を手動で設定します。これは新着記事の判定に影響します。"""
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

        if database.update_record('users', {'lastlogin': new_timestamp}, {'id': user_id}):
            util.send_text_by_key(
                chan, "user_pref_menu.set_lastlogin.updated", current_menu_mode)
        else:
            logging.error(f"最終ログイン日時更新エラー: {login_id}")
            util.send_text_by_key(
                chan, "common_messages.db_update_error", current_menu_mode)
        return None


def set_telegram_restriction(chan, login_id, current_menu_mode, user_data):
    """ユーザーの電報受信設定を行います。"""
    user_id = user_data.get('id')
    restriction_options = {
        '1': {'level': 0, 'key': "user_pref_menu.telegram_restriction.recieve_all"},
        '2': {'level': 1, 'key': "user_pref_menu.telegram_restriction.members_only"},
        '3': {'level': 2, 'key': "user_pref_menu.telegram_restriction.reject_all"},
        '4': {'level': 3, 'key': "user_pref_menu.telegram_restriction.reject_black_list"},
    }

    util.send_text_by_key(
        chan, "user_pref_menu.telegram_restriction.prompt", current_menu_mode, add_newline=False)
    choice = chan.process_input()

    if choice is None or choice not in restriction_options:
        return None  # キャンセルまたは無効な入力

    selected_option = restriction_options[choice]
    new_restriction_level = selected_option['level']
    new_restriction_label_text = util.get_text_by_key(
        selected_option['key'], current_menu_mode)

    if database.update_record('users', {'telegram_restriction': new_restriction_level}, {'id': user_id}):
        chan.send((new_restriction_label_text + "\r\n").encode('utf-8'))
    else:
        logging.error(f"電報受信制限更新時にエラーが発生しました。{login_id}")
        util.send_text_by_key(
            chan, "common_messages.db_update_error", current_menu_mode)
    return None


def edit_blacklist(chan, login_id, current_menu_mode, user_data):
    """ユーザーが個人の電報ブラックリストを編集できるようにします。"""
    user_id = user_data.get('id')
    current_blacklist_str = user_data.get('blacklist', '')

    util.send_text_by_key(
        chan, "user_pref_menu.blacklist_edit.header", current_menu_mode)
    util.send_text_by_key(
        chan, "user_pref_menu.blacklist_edit.current_blacklist_header", current_menu_mode)

    if current_blacklist_str:
        current_user_id_strs = [uid_str.strip(
        ) for uid_str in current_blacklist_str.split(',') if uid_str.strip().isdigit()]  # noqa
        display_login_ids = []

        if current_user_id_strs:
            # dbnameは不要になった
            id_to_name_map = database.get_user_names_from_user_ids(
                current_user_id_strs)
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
            target_login_id_upper = target_login_id_str.upper()
            target_user_id_from_db = database.get_user_id_from_user_name(
                target_login_id_upper)

            if target_user_id_from_db is None:
                util.send_text_by_key(chan, "user_pref_menu.blacklist_edit.user_id_not_found",
                                      current_menu_mode, user_id=target_login_id_upper)
                return None

            validated_user_ids_for_db.append(str(target_user_id_from_db))

    if validated_user_ids_for_db:
        unique_sorted_user_ids = sorted(
            list(set(map(int, validated_user_ids_for_db))))
        final_blacklist_db_str = ",".join(map(str, unique_sorted_user_ids))
    else:
        final_blacklist_db_str = ""

    if database.update_record('users', {'blacklist': final_blacklist_db_str}, {'id': user_id}):
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.update_success", current_menu_mode)
    else:
        logging.error(f"ブラックリスト更新時にエラーが発生しました。{login_id}")
        util.send_text_by_key(
            chan, "common_messages.db_update_error", current_menu_mode)
    return None


def register_exploration_list(chan, login_id, current_menu_mode, user_data):
    """ユーザーのカスタム探索リストを登録します。"""
    user_id = user_data.get('id')

    def save_func(exploration_list_str): return database.set_user_exploration_list(
        user_id, exploration_list_str)
    util.prompt_and_save_exploration_list(
        chan, current_menu_mode, save_func)
    return None


def read_exploration_list(chan, login_id, current_menu_mode, user_data):
    """ユーザーのカスタム探索リストを表示します。"""
    user_id = user_data.get('id')
    exploration_list_str = database.get_user_exploration_list(user_id)
    util.display_exploration_list(chan, exploration_list_str)
    return None


def read_server_default_exploration_list(chan, login_id, current_menu_mode, user_data):
    """サーバーのデフォルト探索リストを表示します。"""
    server_prefs = database.read_server_pref()
    if not server_prefs or len(server_prefs) <= 6:
        logging.error("サーバ設定の読み込みに失敗したか、共通探索リストの項目がありません。")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
        return None

    default_exploration_list_str = server_prefs.get(
        'default_exploration_list', '')
    util.display_exploration_list(chan, default_exploration_list_str)
    return None


def change_email_address(chan, login_id, current_menu_mode, user_data):
    """ユーザーの登録メールアドレス変更をハンドリングします。"""
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
    if database.update_record('users', {'email': new_email}, {'id': user_id}):
        util.send_text_by_key(
            chan, "user_pref_menu.change_email.updated", current_menu_mode)
        logging.info(f"ユーザID {user_id} のメールアドレスを {new_email} に更新しました。")
    else:
        util.send_text_by_key(
            chan, "common_messages.db_update_error", current_menu_mode)
    return None
