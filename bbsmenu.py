import ssh_input
import util
import sqlite_tools
import textwrap
import logging
import datetime

import util
import bbs_handler


def bbs_menu(chan):
    """BBSメニュー"""
    rtinput = ''
    while rtinput != 'e':
        rtinput = ssh_input.realtime_input(chan)
        chan.send(rtinput)

    return


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


def handle_online_signup(chan, dbname, menu_mode):
    """オンラインサインアップ処理"""
    util.send_text_by_key(
        chan, "online_signup.guidance", menu_mode
    )
    security_config = util.app_config.get('security', {})
    id_min_len = security_config.get('ID_MIN_LENGTH', 3)
    id_max_len = security_config.get('ID_MAX_LENGTH', 20)

    new_id = ""
    while True:
        util.send_text_by_key(chan, "online_signup.prompt_id",
                              menu_mode, add_newline=False)
        id_input = ssh_input.process_input(chan)
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
        if sqlite_tools.get_user_auth_info(dbname, new_id):
            util.send_text_by_key(chan, "online_signup.id_exists", menu_mode)
            new_id = ""
            continue
        break

    pw_min_len = security_config.get('PASSWORD_MIN_LENGTH', 8)
    pw_max_len = security_config.get('PASSWORD_MAX_LENGTH', 64)

    new_email = ""
    while True:
        util.send_text_by_key(chan, "online_signup.prompt_email",
                              menu_mode, add_newline=False)
        email_input = ssh_input.process_input(chan)
        if email_input is None:
            return  # 切断
        new_email = email_input.strip()
        if not new_email:
            util.send_text_by_key(chan, "online_signup.cancelled", menu_mode)
            return

        # メールアドレスの簡易検証
        if not util._is_valid_email_for_signup(new_email):
            util.send_text_by_key(
                chan, "online_signup.error_email_invalid", menu_mode)
            continue
        break

    util.send_text_by_key(chan, "online_signup.confirm_registration_yn",
                          menu_mode, new_id=new_id, new_email=new_email, add_newline=False)
    confirm = ssh_input.process_input(chan)
    if confirm is None or confirm.strip().lower() != "y":
        util.send_text_by_key(chan, "online_signup.cancelled", menu_mode)
        return

    # パスワード生成と長さチェック
    temp_password = ""
    while True:
        temp_password = util.generate_random_password(length=12)  # 仮パス作成
        if pw_min_len <= len(temp_password) <= pw_max_len:
            break
        logging.warning(f"仮パスワードの長さが制限外( {len(temp_password)} )です。")

    salt_hex, hashed_password = util.hash_password(temp_password)
    comment = "Online Signup User"  # 仮コメ

    # ユーザレベル1、パス認証のみ、メニューモードは2
    if sqlite_tools.register_user(dbname, new_id, hashed_password, salt_hex,
                                  comment, level=1, auth_method='password_only', menu_mode='2', telegram_restriction=0):
        util.send_text_by_key(
            chan, "online_signup.info_temp_password", menu_mode, temp_password=temp_password)
        util.send_text_by_key(
            chan, "online_signup.registration_success", menu_mode)

        # 一応SSH鍵生成
        try:
            private_key_pem = util.generate_and_regenerate_ssh_key(new_id)
            if private_key_pem:
                logging.info(f"オンラインサインアップユーザ '{new_id}' にSSH鍵を生成しました。")
            else:
                logging.error(f"オンラインサインアップユーザ '{new_id}' のSSH鍵の生成に失敗しました。")
        except Exception as e_key:
            logging.error(f"オンラインサインアップユーザ '{new_id}' のSSH鍵生成時エラー: {e_key}")

    else:
        util.send_text_by_key(
            chan, "online_signup.registration_failed", menu_mode)


def _handle_auto_download(chan, dbname: str, login_id: str, user_id_pk: int, user_level: int, menu_mode: str):
    """自動ダウンロード"""
    util.send_text_by_key(chan, "auto_download.start_message", menu_mode)

    # 探索リスト取得
    exploration_list_str = sqlite_tools.get_user_exploration_list(
        dbname, user_id_pk)
    if not exploration_list_str:
        server_prefs = sqlite_tools.read_server_pref(dbname)
        if server_prefs and len(server_prefs) > 6:
            exploration_list_str = server_prefs[6]

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
    user_data = sqlite_tools.get_user_auth_info(dbname, login_id)
    last_login_timestamp = 0
    if user_data and 'lastlogin' in user_data and user_data['lastlogin']:
        last_login_timestamp = user_data['lastlogin']

    # 掲示板データ処理
    permission_manager = bbs_handler.PermissionManager(dbname)
    article_manager = bbs_handler.ArticleManager(dbname)
    found_new_articles_total = False  # 初期値を設定

    for shortcut_id in board_shortcut_ids:
        board_info_db = sqlite_tools.get_board_by_shortcut_id(
            dbname, shortcut_id)

        if not board_info_db:
            util.send_text_by_key(
                chan, "auto_download.error_board_not_found", menu_mode, shortcut_id=shortcut_id)
            continue

        board_name = board_info_db['name'] if 'name' in board_info_db else shortcut_id
        board_id_pk = board_info_db['id']

        if not permission_manager.can_view_board(board_info_db, user_id_pk, user_level):
            util.send_text_by_key(
                chan, "auto_download.error_permission_denied", menu_mode, board_name=board_name)
            continue

        articles = sqlite_tools.get_new_articles_for_board(
            dbname, board_id_pk, last_login_timestamp)

        if articles:
            found_new_articles_total = True
            # ショートカットID表示
            util.send_text_by_key(
                chan, "auto_download.board_header_format", menu_mode, shortcut_id=shortcut_id)

            for article in articles:
                sender_name = sqlite_tools.get_user_name_from_user_id(
                    dbname, article['user_id'])
                sender_name_short = textwrap.shorten(
                    sender_name if sender_name else "(Unknown)", width=7, placeholder="..")

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
                # タイトル短縮
                title_short_str = textwrap.shorten(
                    title_str, width=43, placeholder="...")

                # 記事情報ヘッダ表示
                # ヘッダ表示
                util.send_text_by_key(
                    chan, "auto_download.article_list_header", menu_mode)
                util.send_text_by_key(chan, "auto_download.article_info_format", menu_mode,
                                      article_number_str=article_number_str,
                                      r_date_str=created_at_str_date,
                                      r_time_str=created_at_str_time,
                                      sender_name_short=sender_name_short,
                                      title_short=title_short_str,)

                # 記事本文表示
                util.send_text_by_key(
                    chan, "auto_download.article_body_prefix", menu_mode)
                body_to_send = article['body'].replace(
                    '\r\n', '\n').replace('\n', '\r\n')
                wrapped_body_lines = textwrap.wrap(
                    body_to_send, width=78, replace_whitespace=False, drop_whitespace=False)
                for line in wrapped_body_lines:
                    chan.send(line.encode('utf-8') + b'\r\n')

                chan.send(b'\r\n')
        else:
            util.send_text_by_key(
                chan, "auto_download.board_header_format", menu_mode, shortcut_id=shortcut_id)
            util.send_text_by_key(
                chan, "auto_download.no_new_articles_in_board", menu_mode)

    if not found_new_articles_total:
        util.send_text_by_key(
            chan, "auto_download.no_new_articles_total", menu_mode)

    util.send_text_by_key(chan, "auto_download.complete_message", menu_mode)


def _handle_explore_new_articles(chan, dbname: str, login_id: str, user_id_pk: int, user_level: int, menu_mode: str):
    """新アーティクル探索"""
    util.send_text_by_key(
        chan, "explore_new_articles.start_message", menu_mode
    )

    # 探索リスト取得
    exploration_list_str = sqlite_tools.get_user_exploration_list(
        dbname, user_id_pk)
    if not exploration_list_str:
        server_prefs = sqlite_tools.read_server_pref(dbname)
        if server_prefs and len(server_prefs) > 6:
            exploration_list_str = server_prefs[6]

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

    for i, shortcut_id in enumerate(board_shortcut_ids):
        board_info_db = sqlite_tools.get_board_by_shortcut_id(
            dbname, shortcut_id)

        if not board_info_db:
            util.send_text_by_key(
                chan, "auto_download.error_board_not_found", menu_mode, shortcut_id=shortcut_id)
            continue

        util.send_text_by_key(chan, "explore_new_articles.entering_board", menu_mode,
                              shortcut_id=shortcut_id, current_num=i+1, total_num=len(board_shortcut_ids))

        # commandhandlerを直接使用して記事一覧表示
        handler = bbs_handler.CommandHandler(chan, dbname, login_id, menu_mode)
        handler.current_board = board_info_db

        # ショートカットID表示 (新アーティクル見出しと同様の形式)
        logging.info(f"ショートカットID: {shortcut_id}")
        util.send_text_by_key(
            chan, "new_article_headlines.board_id_header_format", menu_mode, shortcut_id=shortcut_id)

        chan.send(
            # デバッグ用表示
            f"DEBUG: Shortcut ID should be displayed for {shortcut_id}\r\n".encode())

        # 記事一覧表示
        board_list_result = handler.show_article_list()

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
