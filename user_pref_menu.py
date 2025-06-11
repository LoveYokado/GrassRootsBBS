import ssh_input
import util
import datetime
import sqlite_tools
import re
import logging


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
            # 最終ログイン日時仮設定
            set_lastlogin_datetime(chan, dbname, login_id, current_menu_mode)
        elif command == '6':
            # 探索リスト登録
            register_exploration_list(
                chan, dbname, login_id, current_menu_mode)
        elif command == '7':
            # 探索リスト読み出し
            read_exploration_list(chan, dbname, login_id, current_menu_mode)
        elif command == '8':
            # 元探索リスト読み出し (未実装)
            read_server_default_exploration_list(
                chan, dbname, login_id, current_menu_mode)
        elif command == '9':
            # 電報受信制限
            set_telegram_restriction(chan, dbname, login_id, current_menu_mode)
        elif command == '10':
            # ブラックリスト編集
            edit_blacklist(chan, dbname, login_id, current_menu_mode)
        elif command == '11':
            # メールアドレス変更
            change_email_address(chan, dbname, login_id, current_menu_mode)
        elif command == 'e' or command == '':
            return "back_to_top"  # メニューから抜ける
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
            return "back_to_top"
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
            return "back_to_top"


def show_member_list(chan, dbname, current_menu_mode):
    """会員リストを表示する"""
    util.send_text_by_key(
        chan, "user_pref_menu.member_list.search_prompt", current_menu_mode, add_newline=False)
    search_word = ssh_input.process_input(chan)
    member_list = sqlite_tools.get_memberlist(dbname, search_word)
    if member_list:
        for member in member_list:
            chan.send(
                f"{member.get('name', 'N/A')} {member.get('comment', 'N/A')}\r\n")
    else:
        util.send_text_by_key(chan, "userpref_menu.member_list.notfound",
                              current_menu_mode)  # リストが空のとき


def change_password(chan, dbname, login_id, current_menu_mode):
    """パスワード変更"""
    security_config = util.app_config.get('security', {})
    pbkdf2_rounds = security_config.get('pbkdf2_rounds', 100000)

    # 今のパスワードを確認
    util.send_text_by_key(chan, "user_pref_menu.change_password.current_password",
                          current_menu_mode, add_newline=False)  # 今のパスワード入力
    current_pass = ssh_input.hide_process_input(chan)
    if current_pass is None:
        return

    user_auth_info = sqlite_tools.get_user_auth_info(dbname, login_id)
    if not user_auth_info:
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
        logging.error(f"パスワード変更施行中にユーザが見つかりません: {login_id}")
        return

    if not util.verify_password(user_auth_info['password'], user_auth_info['salt'], current_pass, pbkdf2_rounds):
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
            chan, "user_pref_menu.change_password.new_password_confirm", current_menu_mode, add_newline=False)  # 新しいパスワード確認
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
            private_key_pem = util.regenerate_user_ssh_key(login_id)
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

    current_comment = user_data['comment'] if user_data['comment'] is not None else ''
    util.send_text_by_key(chan, "user_pref_menu.change_profile.current_profile",
                          current_menu_mode, comment=current_comment)
    util.send_text_by_key(
        chan, "user_pref_menu.change_profile.new_profile", current_menu_mode, add_newline=False)
    new_comment = ssh_input.process_input(chan)

    if new_comment is None:
        return
    if new_comment == '':  # 空入力はキャンセル扱いにするか、空コメントとして許可するか後で考える。どうだっけ?
        util.send_text_by_key(
            chan, "user_pref_menu.change_profile.cancelled", current_menu_mode)
        return
    try:
        # コメント更新
        if sqlite_tools.update_user_profile_comment(dbname, user_data['id'],  new_comment):
            util.send_text_by_key(
                chan, "user_pref_menu.change_profile.profile_updated", current_menu_mode)
        else:
            raise Exception("コメント更新に失敗")

    except Exception as e:
        logging.error(f"コメント更新エラー: {e}")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)


def set_lastlogin_datetime(chan, dbname, login_id, current_menu_mode):
    """最終ログイン日時を手動で設定"""
    user_data = sqlite_tools.get_user_auth_info(dbname, login_id)

    user_id = user_data['id']
    current_lastlogin_ts = user_data['lastlogin']

    current_lastlogin_str = "None"
    if current_lastlogin_ts and current_lastlogin_ts > 0:
        try:
            current_lastlogin_str = datetime.datetime.fromtimestamp(
                current_lastlogin_ts).strftime('%Y-%m-%d %H:%M:%S')
        except (OSError, TypeError, ValueError):
            current_lastlogin_str = "Unknown datetime"
    util.send_text_by_key(
        chan, "user_pref_menu.set_lastlogin.current_lastlogin", current_menu_mode, lastlogin=current_lastlogin_str)  # 最終ログイン日時

    while True:
        util.send_text_by_key(
            chan, "user_pref_menu.set_lastlogin.newe_datetime", current_menu_mode, add_newline=False)  # 新しい日時
        datetime_str_input = ssh_input.process_input(chan)

        if datetime_str_input is None:
            return
        if not datetime_str_input:
            util.send_text_by_key(
                chan, "user_pref_menu.set_lastlogin.cancelled", current_menu_mode
            )  # キャンセル
            return

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
                chan, "user_pref_menu.set_lastlogin.invalid_format", current_menu_mode
            )  # 日時のフォーマットが不正
            continue

        new_timestamp = int(new_datetime_obj.timestamp())

        try:
            sqlite_tools.update_idbase(
                dbname, 'users', ['lastlogin'], user_id, 'lastlogin', new_timestamp)
            util.send_text_by_key(
                chan, "user_pref_menu.set_lastlogin.updated", current_menu_mode
            )  # 最終ログイン日時更新
            return
        except Exception as e:
            logging.error(f"最終ログイン日時更新エラー: {e}")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
            return


def set_telegram_restriction(chan, dbname, login_id, current_menu_mode):
    """電報受信制限設定"""
    user_data = sqlite_tools.get_user_auth_info(dbname, login_id)
    if not user_data:
        logging.error(f"電報受信制限設定時にユーザが存在しませんでした。{login_id}")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)
        return

    user_id = user_data['id']

    while True:
        util.send_text_by_key(
            chan, "user_pref_menu.telegram_restriction.prompt", current_menu_mode, add_newline=False)
        choice = ssh_input.process_input(chan)
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
            return

        if sqlite_tools.update_user_telegram_restriction(dbname, user_id, new_restriction_level):
            chan.send(new_restridtion_lebel_text+"\r\n")  # 制限レベル表示
            return
        else:
            logging.error(f"電報受信制限更新時にエラーが発生しました。{login_id}")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
            return


def edit_blacklist(chan, dbname, login_id, current_menu_mode):
    """ブラックリスト編集"""
    user_data = sqlite_tools.get_user_auth_info(dbname, login_id)

    user_id = user_data['id']
    current_blacklist_str = user_data['blacklist']

    util.send_text_by_key(
        chan, "user_pref_menu.blacklist_edit.header", current_menu_mode)
    util.send_text_by_key(
        chan, "user_pref_menu.blacklist_edit.current_blacklist_header", current_menu_mode)  # 現在のブラックリスト

    if current_blacklist_str:
        current_user_id_strs = [uid_str.strip(
        ) for uid_str in current_blacklist_str.split(',') if uid_str.strip().isdigit()]
        display_login_ids = []

        if current_user_id_strs:
            # 複数のIDから一度に名前を取得
            id_to_name_map = sqlite_tools.get_user_names_from_user_ids(
                dbname, current_user_id_strs)
            for uid_str in current_user_id_strs:
                # 取得したマップからユーザー名を参照
                user_id_int = int(uid_str)  # マップのキーは整数型
                login_name = id_to_name_map.get(user_id_int)
                display_login_ids.append(
                    login_name if login_name else f"(ID:{uid_str} 不明)")

        if display_login_ids:
            util.send_text_by_key(
                chan, "user_pref_menu.blacklist_edit.current_list_display", current_menu_mode, blacklist_users=", ".join(display_login_ids))
        else:
            # ID文字列はあるが、有効なユーザー名に変換できなかった場合
            util.send_text_by_key(
                chan, "user_pref_menu.blacklist_edit.no_blacklist", current_menu_mode)
    else:
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.no_blacklist", current_menu_mode)  # ブラックリスト無し

    util.send_text_by_key(chan, "user_pref_menu.blacklist_edit.confirm_change_prompt",
                          current_menu_mode, add_newline=False)  # 変更するかの確認
    Confirm_choice = ssh_input.process_input(chan)

    if Confirm_choice is None or Confirm_choice.lower() != "y":
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.cancelled", current_menu_mode)  # キャンセル
        return

    util.send_text_by_key(chan, "user_pref_menu.blacklist_edit.new_list_prompt",
                          current_menu_mode, add_newline=False)  # 新しいブラックリスト",)
    new_blacklist_login_ids_input_str = ssh_input.process_input(chan)

    if new_blacklist_login_ids_input_str is None:
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.cancelled", current_menu_mode)  # キャンセル
        return

    new_blacklist_login_ids_input_str = new_blacklist_login_ids_input_str.strip()
    validated_user_ids_for_db = []

    if not new_blacklist_login_ids_input_str:  # 空入力はブラックリストをクリア
        pass  # validated_user_ids_for_db は空のまま
    else:
        input_login_ids = [name.strip(
        ) for name in new_blacklist_login_ids_input_str.split(',') if name.strip()]

        # 何か入力はあるが、パースしたら空になった場合 (例: ",,,")
        if not input_login_ids and new_blacklist_login_ids_input_str:
            util.send_text_by_key(
                # 適切なエラーメッセージキーに変更
                chan, "user_pref_menu.blacklist_edit.invalid_id_format", current_menu_mode)
            return

        for target_login_id_str in input_login_ids:
            if not target_login_id_str:  # カンマが連続した場合など
                continue

            # 自分自身をブラックリストには追加できない
            if target_login_id_str == login_id:
                # logging.info(f"ユーザー {login_id} が自身をブラックリストに追加しようとしました。")
                # メッセージを出しても良いが、今回は単に無視する
                continue

            # 入力された login_id から user_id を取得
            target_user_id_from_db = sqlite_tools.get_user_id_from_user_name(
                dbname, target_login_id_str)

            if target_user_id_from_db is None:
                util.send_text_by_key(chan, "user_pref_menu.blacklist_edit.user_id_not_found",
                                      current_menu_mode, user_id=target_login_id_str)  # user_id を login_id に変更
                return

            validated_user_ids_for_db.append(str(target_user_id_from_db))
    # 重複を除いてソートして保存
    # validated_user_ids_for_db には文字列型の user_id が入っている
    if validated_user_ids_for_db:
        # 数値としてソートするために一度intに変換
        unique_sorted_user_ids = sorted(
            list(set(map(int, validated_user_ids_for_db))))
        final_blacklist_db_str = ",".join(map(str, unique_sorted_user_ids))
    else:
        final_blacklist_db_str = ""

    if sqlite_tools.update_user_blacklist(dbname, user_id, final_blacklist_db_str):
        util.send_text_by_key(
            chan, "user_pref_menu.blacklist_edit.update_success", current_menu_mode)  # 成功
    else:
        logging.error(f"ブラックリスト更新時にエラーが発生しました。{login_id}")
        util.send_text_by_key(
            chan, "common_messages.error", current_menu_mode)


def register_exploration_list(chan, dbname, login_id, current_menu_mode):
    """探索リスト登録"""
    user_id = sqlite_tools.get_user_id_from_user_name(dbname, login_id)
    if user_id is None:
        util.send_text_by_key(
            chan, "common_messages.user_not_found", current_menu_mode)
        return

    util.send_text_by_key(
        chan, "user_pref_menu.register_exploration_list.header", current_menu_mode)  # 探索リスト登録ヘッダ

    exploration_items = []
    item_number = 1
    while True:
        # 番号を表示して待つ
        prompt_text = f"{item_number}: "
        chan.send(prompt_text.encode('utf-8'))
        item_input = ssh_input.process_input(chan)

        if item_input is None:
            return

        # からエンターで終了
        if not item_input.strip():
            break

        exploration_items.append(item_input.strip())
        item_number += 1

    if not exploration_items:  # 何も入力されなかった場合
        return

    # 保存確認
    util.send_text_by_key(
        chan, "user_pref_menu.register_exploration_list.confirm_yn", current_menu_mode, add_newline=False)
    confirm_choice = ssh_input.process_input(chan)

    if confirm_choice is None:
        return

    if confirm_choice.lower().strip() == 'y':
        exploration_list_str = ",".join(exploration_items)
        if sqlite_tools.set_user_exploration_list(dbname, user_id, exploration_list_str):
            util.send_text_by_key(
                chan, "user_pref_menu.register_exploration_list.success", current_menu_mode)  # 成功
        else:
            logging.error(f"探索リスト登録時にエラーが発生しました。{login_id}")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)


def read_exploration_list(chan, dbname, login_id, current_menu_mode):
    """探索リスト読み出し"""
    user_id = sqlite_tools.get_user_id_from_user_name(dbname, login_id)
    if user_id is None:
        return

    exploration_list_str = sqlite_tools.get_user_exploration_list(
        dbname, user_id)

    if exploration_list_str:
        items = exploration_list_str.split(",")
        chan.send("\r\n")
        for item in items:
            item_stripped = item.strip()
            if item_stripped:
                chan.send(item_stripped.encode('utf-8') + b'\r\n')
        chan.send("\r\n")

    else:
        pass


def read_server_default_exploration_list(chan, dbname, login_id, current_menu_mode):
    """元探索リスト読み出し"""
    server_prefs = sqlite_tools.read_server_pref(dbname)
    if server_prefs and len(server_prefs) > 6:
        default_exploration_list_str = server_prefs[6]
        if default_exploration_list_str:
            items = default_exploration_list_str.split(",")
            chan.send("\r\n")
            for item in items:
                item_stripped = item.strip()
                if item_stripped:
                    chan.send(item_stripped.encode('utf-8')+b'\r\n')
            chan.send("\r\n")
    else:
        logging.error("サーバ設定の読み込みに失敗したか、共通探索リストの項目がありません。")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)


def _is_valid_email(email: str) -> bool:
    """メールアドレスの検証(RFC5322)"""
    if not email:
        return False
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if re.match(pattern, email):
        return True
    return False


def change_email_address(chan, dbname, login_id, current_menu_mode):
    """メールアドレス変更"""
    user_data = sqlite_tools.get_user_auth_info(dbname, login_id)
    if not user_data:
        util.send_text_by_key(
            chan, "common_messages.user_not_found", current_menu_mode)
        return

    user_id = user_data['id']
    email_from_db = user_data['email']
    current_email = email_from_db if email_from_db is not None else ''

    util.send_text_by_key(chan, "user_pref_menu.change_email.current_email",
                          current_menu_mode, email=current_email)
    util.send_text_by_key(
        chan, "user_pref_menu.change_email.new_email_prompt", current_menu_mode, add_newline=False)
    new_email_input = ssh_input.process_input(chan)

    if new_email_input is None:
        return

    new_email = new_email_input.strip()

    if not new_email:
        return

    if not _is_valid_email(new_email):
        util.send_text_by_key(
            chan, "user_pref_menu.change_email.invalid_format", current_menu_mode)
        return
    if sqlite_tools.update_user_email(dbname, user_id, new_email):
        util.send_text_by_key(
            chan, "user_pref_menu.change_email.updated", current_menu_mode)
        logging.info(f"ユーザID {user_id} のメールアドレスを {new_email} に更新しました。")
    else:
        util.send_text_by_key(
            chan, "common_messages.db_update_error", current_menu_mode)
