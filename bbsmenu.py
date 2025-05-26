import ssh_input
import util
import datetime
import sqlite_tools
import time
import logging

import util


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
    # 電報受信設定を取得
    user_settings = sqlite_tools.get_user_auth_info(dbname, username)
    user_restriction = user_settings['telegram_restriction']
    blacklist_str = user_settings['blacklist']
    user_blacklist_ids = set()
    if blacklist_str:
        try:
            user_blacklist_ids = set(int(uid)
                                     for uid in blacklist_str.split(','))
        except ValueError:
            logging.error(
                f"ユーザ{username}のブラックリスト形式エラー:{blacklist_str}")
            user_blacklist_ids = set()

    results = sqlite_tools.load_and_delete_telegrams(dbname, username)
    if not results:
        return

    filterd_telegrams = []
    for teregram in results:
        sender_name = teregram['sender_name']
        # SenderユーザIDを取得
        sender_id = sqlite_tools.get_user_id_from_user_name(
            dbname, sender_name)

        should_display = True

        # 電報受信制限確認
        if user_restriction == 2:  # 全拒否
            should_display = False
        elif user_restriction == 1:  # ゲスト除外
            if sender_name.upper() == "GUEST":
                should_display = False

        # ブラックリスト確認
        if should_display == 3 and sender_id in user_blacklist_ids:
            should_display = False

        if should_display:
            filterd_telegrams.append(teregram)

    if filterd_telegrams:
        util.send_text_by_key(chan, "telegram.receive_header",
                              current_menu_mode)  # 電報受信メッセージ
        for telegram_to_display in filterd_telegrams:
            sender = telegram_to_display['sender_name']
            message = telegram_to_display['message']
            timestamp_val = telegram_to_display['timestamp']
            try:
                dt_str = datetime.datetime.fromtimestamp(
                    timestamp_val).strftime('%Y-%m-%d %H:%M')  # 秒は省略しても良いかも
            except (ValueError, OSError, TypeError):  # TypeError も考慮
                dt_str = "不明な日時"
            util.send_text_by_key(
                chan, "telegram.receive_message", current_menu_mode, sender=sender, message=message, dt_str=dt_str)  # 受信メッセージ本体
        util.send_text_by_key(
            chan, "telegram.receive_footer", current_menu_mode)


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
