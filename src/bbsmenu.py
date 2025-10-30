# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""BBSメニューハンドラ。

このモジュールは、BBSのトップメニューから利用可能な様々なコマンドのハンドラ関数を
含んでいます。オンラインユーザーの表示、オンラインサインアップ、新着記事の探索と
いった機能が含まれます。これらの関数は、通常 `command_dispatcher.py` から
呼び出されます。
"""

import textwrap
import logging
import datetime

from . import util, database
from . import bbs_handler
from . import bbs_manager


def who_menu(chan, online_members_dict, current_menu_mode):
    """オンラインメンバーの一覧をクライアントに表示します。"""
    util.send_text_by_key(
        chan, "who_menu.header", current_menu_mode)
    if not online_members_dict:
        util.send_text_by_key(chan, "who_menu.nomembers",
                              current_menu_mode)
        return

    # 最初にオンラインメンバーのログインIDリストを作成
    online_login_ids = [
        member_data.get("username")
        for member_data in online_members_dict.values()
        if member_data.get("username")
    ]

    # ログインIDリストを使って、必要なユーザー情報をDBから一括で取得
    users_data_map = {
        user['name']: user for user in database.get_users_by_names(online_login_ids)
    } if online_login_ids else {}

    for sid, member_data in online_members_dict.items():
        display_name = member_data.get("display_name")
        login_id = member_data.get("username")

        if not display_name or not login_id:
            continue  # 必要なデータがなければスキップ

        display_name_short = util.shorten_text_by_slicing(
            display_name, width=22)

        user_db_data = users_data_map.get(login_id)
        comment = user_db_data.get('comment', '') if user_db_data else ''
        comment_short = util.shorten_text_by_slicing(comment, width=50)

        chan.send(
            f"{display_name_short:<22} {comment_short}\r\n".encode('utf-8'))
    util.send_text_by_key(chan, "who_menu.footer", current_menu_mode)


def handle_online_signup(chan, menu_mode):
    """オンラインサインアップの対話的な処理を管理し、新規ユーザーを登録します。"""
    util.send_text_by_key(
        chan, "online_signup.guidance", menu_mode
    )
    security_config = util.app_config.get('security', {})
    id_min_len = security_config.get('ID_MIN_LENGTH', 3)
    id_max_len = security_config.get('ID_MAX_LENGTH', 20)

    # --- 1. 希望IDの入力と検証 ---
    new_id = ""
    while True:
        util.send_text_by_key(chan, "online_signup.prompt_id",
                              menu_mode, add_newline=False)
        id_input = chan.process_input()
        if id_input is None:
            return  # 切断
        new_id = id_input.strip().upper()
        if not new_id:
            util.send_text_by_key(chan, "online_signup.cancelled", menu_mode)
            return

        # ID長さチェック
        if not (id_min_len <= len(new_id) <= id_max_len):
            util.send_text_by_key(
                chan, "online_signup.error_id_length", menu_mode, min_len=id_min_len, max_len=id_max_len)
            continue

        # ID重複チェック
        if database.get_user_auth_info(new_id):
            util.send_text_by_key(chan, "online_signup.id_exists", menu_mode)
            new_id = ""
            continue
        break

    # --- 2. パスワードの入力と検証 ---
    pw_min_len = security_config.get('PASSWORD_MIN_LENGTH', 8)
    pw_max_len = security_config.get('PASSWORD_MAX_LENGTH', 64)

    new_email = ""
    while True:
        util.send_text_by_key(chan, "online_signup.prompt_email",
                              menu_mode, add_newline=False)
        email_input = chan.process_input()
        if email_input is None:
            return  # 切断
        new_email = email_input.strip()
        if not new_email:
            util.send_text_by_key(chan, "online_signup.cancelled", menu_mode)
            return

        # メールアドレスの簡易検証
        if not util.is_valid_email(new_email):
            util.send_text_by_key(
                chan, "online_signup.error_email_invalid", menu_mode)
            continue
        break

    # --- 4. シスオペへのメッセージ入力 ---
    util.send_text_by_key(
        chan, "online_signup.prompt_message", menu_mode, add_newline=False)
    message_to_sysop = chan.process_input()
    if message_to_sysop is None:
        return  # 切断

    # --- 5. 登録内容の確認 ---
    util.send_text_by_key(chan, "online_signup.confirm_registration_yn",
                          menu_mode, new_id=new_id, new_email=new_email, add_newline=False)
    confirm = chan.process_input()
    if confirm is None or confirm.strip().lower() != "y":
        util.send_text_by_key(chan, "online_signup.cancelled", menu_mode)
        return

    # --- 6. 登録処理 ---
    # パスワード生成と長さチェック
    temp_password = ""
    while True:
        temp_password = util.generate_random_password(length=12)
        if pw_min_len <= len(temp_password) <= pw_max_len:
            break
        logging.warning(f"仮パスワードの長さが制限外( {len(temp_password)} )です。")

    salt_hex, hashed_password = util.hash_password(temp_password)
    comment = util.get_text_by_key(
        "online_signup.default_comment", menu_mode, default_value="Online Signup User")

    # ユーザレベル1、パス認証のみ、メニューモードは2
    if database.register_user(new_id, hashed_password, salt_hex, comment, level=1, menu_mode='2',
                              telegram_restriction=0, email=new_email):
        util.send_text_by_key(
            chan, "online_signup.info_temp_password", menu_mode, temp_password=temp_password)
        util.send_text_by_key(
            chan, "online_signup.registration_success", menu_mode)

        # シスオペにメールで通知
        sysop_user_id = database.get_sysop_user_id()
        if sysop_user_id:
            mail_subject_template = util.get_text_by_key(
                "online_signup.mail_subject", menu_mode, default_value="[System] New User Signup: {new_id}")
            mail_body_template = util.get_text_by_key(
                "online_signup.mail_body", menu_mode, default_value="New user signed up.\nID: {new_id}\nEmail: {new_email}\nMessage:\n{message_to_sysop}")

            mail_subject = mail_subject_template.format(new_id=new_id)
            mail_body = mail_body_template.format(
                new_id=new_id,
                new_email=new_email,
                message_to_sysop=message_to_sysop.strip() if message_to_sysop else "(No message)"
            )

            if not database.send_system_mail(sysop_user_id, mail_subject, mail_body):
                logging.error(
                    f"オンラインサインアップ通知メールの送信に失敗しました (To SysOp ID: {sysop_user_id})")
        else:
            logging.warning(
                "シスオペが見つからないため、オンラインサインアップ通知メールを送信できませんでした。")

    else:
        util.send_text_by_key(
            chan, "online_signup.registration_failed", menu_mode)


def _perform_exploration(chan, login_id, display_name, user_id_pk, user_level, menu_mode, ip_address, exploration_list_str):
    """指定された探索リストに基づいて掲示板を巡回し、未読記事を表示する共通関数。"""
    util.send_text_by_key(
        chan, "explore_new_articles.start_message", menu_mode
    )

    if not exploration_list_str:
        util.send_text_by_key(
            chan, "auto_download.no_exploration_list", menu_mode)
        return

    board_shortcut_ids = [sid.strip()
                          for sid in exploration_list_str.split(',') if sid.strip()]
    if not board_shortcut_ids:
        util.send_text_by_key(
            chan, "auto_download.no_exploration_list", menu_mode)
        return

    # 最終ログイン時刻取得
    user_data_for_n = database.get_user_auth_info(login_id)
    last_login_timestamp_for_n = 0
    if user_data_for_n and 'lastlogin' in user_data_for_n.keys() and user_data_for_n['lastlogin']:
        last_login_timestamp_for_n = user_data_for_n['lastlogin']

    for i, shortcut_id in enumerate(board_shortcut_ids):
        board_info_db = database.get_board_by_shortcut_id(shortcut_id)

        if not board_info_db:
            util.send_text_by_key(
                chan, "auto_download.error_board_not_found", menu_mode, shortcut_id=shortcut_id)
            continue

        potential_new_articles = database.get_new_articles_for_board(
            board_info_db['id'], last_login_timestamp_for_n)
        if not potential_new_articles:
            continue

        util.send_text_by_key(chan, "explore_new_articles.entering_board", menu_mode,
                              shortcut_id=shortcut_id, current_num=i+1, total_num=len(board_shortcut_ids))

        # commandhandlerを直接使用して記事一覧表示
        handler = bbs_handler.CommandHandler(
            chan, login_id, display_name, menu_mode, ip_address)
        handler.current_board = board_info_db

        # 記事一覧の共通ヘッダーを表示
        util.send_text_by_key(chan, "bbs.article_list_header", menu_mode)

        # 記事一覧表示
        # bbs_handler.py 側でのヘッダ表示を抑制するため display_initial_header=False を渡す
        handler.show_article_list(display_initial_header=False,
                                  last_login_timestamp=last_login_timestamp_for_n)

        if not chan.active:
            logging.info(
                f"新アーティクル探索中にユーザ {login_id} が切断されました 掲示板: {shortcut_id}")
            return

        # chanがアクティブでboard_list_resultがNoneの場合、ユーザーが正常にボードを抜けたと判断し次の掲示板へ進む

        if i < len(board_shortcut_ids)-1:
            util.send_text_by_key(
                chan, "explore_new_articles.moving_to_next", menu_mode)

    util.send_text_by_key(
        chan, "explore_new_articles.complete_message", menu_mode)


def _handle_explore_new_articles(chan, login_id: str, display_name: str, user_id_pk: int, user_level: int, menu_mode: str, ip_address: str):
    """新アーティクル探索 ('n' コマンド) のハンドラ。ユーザーの探索リストを使用します。"""
    # ユーザー個人の探索リストを取得
    exploration_list_str = database.get_user_exploration_list(user_id_pk)
    # 個人リストがなければ、サーバーのデフォルトリストにフォールバック
    if not exploration_list_str:
        server_prefs = database.read_server_pref()
        exploration_list_str = server_prefs.get('default_exploration_list', '')

    _perform_exploration(chan, login_id, display_name, user_id_pk,
                         user_level, menu_mode, ip_address, exploration_list_str)


def _handle_full_sig_exploration(chan, login_id: str, display_name: str, user_id_pk: int, user_level: int, menu_mode: str, ip_address: str, default_exploration_list_str: str):
    """全シグ探索 ('x' コマンド) のハンドラ。サーバーのデフォルト探索リストを使用します。"""
    # 引数で渡された共通探索リストを使用
    exploration_list_str = default_exploration_list_str

    if not exploration_list_str:
        util.send_text_by_key(
            chan, "full_sig_exploration.no_default_exploration_list", menu_mode)
        return

    _perform_exploration(chan, login_id, display_name, user_id_pk,
                         user_level, menu_mode, ip_address, exploration_list_str)


def _get_exploration_list_for_user(user_id_pk):
    """ユーザーの探索リストを取得します。個人設定がなければデフォルトリストを使用します。"""
    exploration_list_str = database.get_user_exploration_list(user_id_pk)
    if not exploration_list_str:
        server_prefs = database.read_server_pref()
        exploration_list_str = server_prefs.get('default_exploration_list', '')
    return exploration_list_str


def handle_new_article_headlines(chan, login_id: str, user_id_pk: int, user_level: int, menu_mode: str):
    """新アーティクル見出し表示 ('o' コマンド) のハンドラ。未読記事のタイトルを一覧表示します。"""
    util.send_text_by_key(
        chan, "new_article_headlines.start_message", menu_mode)
    exploration_list_str = _get_exploration_list_for_user(user_id_pk)

    board_shortcut_ids = [sid.strip()
                          for sid in exploration_list_str.split(',') if sid.strip()]
    if not board_shortcut_ids:
        util.send_text_by_key(
            chan, "auto_download.no_exploration_list", menu_mode)
        util.send_text_by_key(
            chan, "new_article_headlines.end_message", menu_mode)
        return

    # 最終ログイン時刻取得（TODO:これも関数化できるなぁ）
    user_data = database.get_user_auth_info(login_id)
    last_login_timestamp = 0
    if user_data and 'lastlogin' in user_data.keys() and user_data['lastlogin']:
        last_login_timestamp = user_data['lastlogin']

    # enumerate を使ってインデックスを取得
    for i, shortcut_id in enumerate(board_shortcut_ids):
        board_info_db = database.get_board_by_shortcut_id(shortcut_id)
        if not board_info_db:
            # 掲示板が見つからないときはスキップ
            logging.debug(f"新アーティクル見出し: 掲示板 {shortcut_id} は見つかりません。")
            continue

        board_id_pk = board_info_db['id']
        # 権限チェック
        permission_manager = bbs_manager.PermissionManager()
        if not permission_manager.can_view_board(board_info_db, user_id_pk, user_level):
            # 権限がないときはスキップ
            logging.debug(
                f"新アーティクル見出し: ユーザー {login_id} は掲示板 {shortcut_id} を閲覧する権限がありません。")
            continue

        # 未読を取得
        new_articles = database.get_new_articles_for_board(
            board_id_pk, last_login_timestamp)
        if not new_articles:
            continue  # 未読がなければスキップ

        # 探索中メッセージ表示 (Nキーの探索と同じ形式のメッセージキーを使用)
        util.send_text_by_key(
            chan, "explore_new_articles.entering_board", menu_mode, shortcut_id=shortcut_id, current_num=i+1, total_num=len(board_shortcut_ids))

        # 記事一覧の共通ヘッダーを表示
        util.send_text_by_key(chan, "bbs.article_list_header", menu_mode)

        # 記事詳細を表示
        for article in new_articles:

            user_id_from_article = article['user_id']
            display_sender_name = ""
            try:
                user_id_int = int(user_id_from_article)
                user_name = database.get_user_name_from_user_id(user_id_int)
                display_sender_name = user_name if user_name else "(Unknown)"
            except (ValueError, TypeError):
                display_sender_name = str(user_id_from_article)

            sender_name_short = util.shorten_text_by_slicing(
                display_sender_name if display_sender_name else "(Unknown)", width=14)

            created_at_str_date = "Unknown date"
            created_at_str_time = "Unknown time"
            try:
                if article['created_at']:
                    dt_obj = datetime.datetime.fromtimestamp(
                        article['created_at'])
                    created_at_str_date = dt_obj.strftime("%y/%m/%d")
                    created_at_str_time = dt_obj.strftime("%H:%M:%S")
            except (OSError, TypeError, ValueError):
                pass

            # 記事番号
            article_number_str = f"{article['article_number']:05d}"
            title_str = article['title'] if article['title'] else "(No Title)"
            # タイトル短縮
            title_short_str = util.shorten_text_by_slicing(
                title_str, width=32)

            # 表示
            util.send_text_by_key(
                chan, "auto_download.article_info_format", menu_mode,
                article_number_str=article_number_str,
                r_date_str=created_at_str_date,
                r_time_str=created_at_str_time,
                sender_name_short=sender_name_short,
                title_short=title_short_str)
        chan.send(b'\r\n')  # 各掲示板の最後に空行を追加

    util.send_text_by_key(
        chan, "new_article_headlines.end_message", menu_mode)


def handle_auto_download(chan, login_id: str, user_id_pk: int, user_level: int, menu_mode: str):
    """自動ダウンロード ('a' コマンド) のハンドラ。未読記事を連続で表示します。"""
    util.send_text_by_key(
        chan, "auto_download.start_message", menu_mode)
    exploration_list_str = _get_exploration_list_for_user(user_id_pk)
    if not exploration_list_str:
        util.send_text_by_key(
            chan, "auto_download.no_exploration_list", menu_mode)
        util.send_text_by_key(
            chan, "auto_download.end_message", menu_mode)
        return

    board_shortcut_ids = [sid.strip()
                          for sid in exploration_list_str.split(',') if sid.strip()]
    if not board_shortcut_ids:
        util.send_text_by_key(
            chan, "auto_download.no_exploration_list", menu_mode)
        util.send_text_by_key(
            chan, "auto_download.end_message", menu_mode)
        return

    # 最終ログイン時刻取得
    user_data = database.get_user_auth_info(login_id)
    last_login_timestamp = 0
    if user_data and 'lastlogin' in user_data.keys() and user_data['lastlogin']:
        last_login_timestamp = user_data['lastlogin']

    # 掲示板巡回
    for i, shortcut_id in enumerate(board_shortcut_ids):
        board_info_db = database.get_board_by_shortcut_id(shortcut_id)
        if not board_info_db:
            logging.debug(f"自動ダウンロード: 掲示板 {shortcut_id} は見つかりません。")
            continue

        board_id_pk = board_info_db['id']
        # 権限チェック
        permission_manager = bbs_manager.PermissionManager()
        if not permission_manager.can_view_board(board_info_db, user_id_pk, user_level):
            logging.debug(
                f"自動ダウンロード: ユーザー {login_id} は掲示板 {shortcut_id} を閲覧する権限がありません。")
            continue

        # 未読を取得
        new_articles = database.get_new_articles_for_board(
            board_id_pk, last_login_timestamp)
        if not new_articles:
            continue  # 未読がなければスキップ

        # 掲示板に入るメッセージ
        util.send_text_by_key(
            chan, "explore_new_articles.entering_board", menu_mode, shortcut_id=shortcut_id, current_num=i+1, total_num=len(board_shortcut_ids))

        # 記事詳細を表示
        for article in new_articles:
            # 1. 共通ヘッダを毎回表示
            util.send_text_by_key(chan, "bbs.article_list_header", menu_mode)

            # 2. 見出し行を表示
            user_id_from_article = article['user_id']
            display_sender_name = ""
            try:
                user_id_int = int(user_id_from_article)
                user_name = database.get_user_name_from_user_id(user_id_int)
                display_sender_name = user_name if user_name else "(Unknown)"
            except (ValueError, TypeError):
                display_sender_name = str(user_id_from_article)

            sender_name_short = util.shorten_text_by_slicing(
                display_sender_name if display_sender_name else "(Unknown)", width=14)

            created_at_str_date = "Unknown date"
            created_at_str_time = "Unknown time"
            try:
                if article['created_at']:
                    dt_obj = datetime.datetime.fromtimestamp(
                        article['created_at'])
                    created_at_str_date = dt_obj.strftime("%y/%m/%d")
                    created_at_str_time = dt_obj.strftime("%H:%M:%S")
            except (OSError, TypeError, ValueError):
                pass

            article_number_str = f"{article['article_number']:05d}"
            title_str = article['title'] if article['title'] else "(No Title)"
            title_short_str = util.shorten_text_by_slicing(
                title_str, width=32)

            util.send_text_by_key(
                chan, "auto_download.article_info_format", menu_mode,
                article_number_str=article_number_str,
                r_date_str=created_at_str_date,
                r_time_str=created_at_str_time,
                sender_name_short=sender_name_short,
                title_short=title_short_str)

            # 3. 空行を追加
            chan.send(b'\r\n')

            # 4. 本文を表示
            body_to_send = article['body'].replace(
                '\r\n', '\n').replace('\n', '\r\n')
            wrapped_body_lines = textwrap.wrap(
                body_to_send, width=78, replace_whitespace=False, drop_whitespace=False)
            for line in wrapped_body_lines:
                chan.send(line.encode('utf-8') + b'\r\n')

            # 5. 記事の表示後に空行を追加
            chan.send(b'\r\n')

    util.send_text_by_key(
        chan, "auto_download.end_message", menu_mode)
