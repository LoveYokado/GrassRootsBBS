import ssh_input
import util
import datetime
import sqlite_tools
import time
import logging
import socket
import textwrap


def mail(chan, dbname, login_id, menu_mode):
    """
    メールメニュー (パソコン通信風)
    受信メールのタイトルを1行表示し、j/kで移動、Enterで本文表示。
    dで削除/復元。sで送受信変更。
    wで作成、eで終了。
    """
    user_id = sqlite_tools.get_user_id_from_user_name(dbname, login_id)
    if user_id is None:
        util.send_text_by_key(
            chan, "common_messages.user_not_found", menu_mode
        )  # ユーザー情報が見つかりません。
        return

    # メールメニュー
    while True:
        # 選択してください([W]送信 [R]受信 [L]一覧形式受信)
        util.send_text_by_key(
            chan, "mail_handler.main_prompt", menu_mode, add_newline=False)
        choice = ssh_input.process_input(chan).lower()
        if choice == 'l':
            view_mode = 'inbox'
            break
        elif choice == 'w':
            mail_write(chan, dbname, login_id, menu_mode)
            return
        elif choice == 'r':
            # 1.初回に新着メールの総数未読数表示
            unread_count_initial = sqlite_tools.get_total_unread_mail_count(
                dbname, user_id)
            total_mail_count_initial = sqlite_tools.get_total_mail_count(
                dbname, user_id)

            if unread_count_initial > 0:
                notification_format = util.get_text_by_key(
                    "mail_handler.new_mail_notification", menu_mode)
                if notification_format:
                    chan.send(notification_format.format(
                              total_mail_count=total_mail_count_initial, unread_mail_count=unread_count_initial
                              ).replace('\n', '\r\n').encode('utf-8')+b'\r\n')
            else:
                util.send_text_by_key(
                    chan, "mail_handler.no_unread_mails_at_start", menu_mode)
                return "back_to_top"

            while True:  # 未読処理ループ
                oldest_unread_mail = sqlite_tools.get_oldest_unread_mail(
                    dbname, user_id)

                if not oldest_unread_mail:
                    util.send_text_by_key(
                        chan, "mail_handler.no_more_unread_mails", menu_mode)
                    break

                # ヘッダ表示
                util.send_text_by_key(
                    chan, "mail_handler.subject_header", menu_mode)

                mail_id_width_for_reader = 5
                util.send_text_by_key(
                    chan, "mail_handler.sender_header", menu_mode)
                display_mail_header(chan, oldest_unread_mail,
                                    dbname, 'inbox', mail_id_width_for_reader)

                # 読み込み選択(y/n)
                util.send_text_by_key(
                    chan, "mail_handler.confirm_read_body_yn", menu_mode, add_newline=False)
                read_choice_input = ssh_input.process_input(chan)
                if read_choice_input is None:
                    return "back_to_top"
                read_choice = read_choice_input.strip().lower()

                if read_choice == 'y':
                    # 本文表示と既読化
                    success, _ = display_mail_content(
                        chan, oldest_unread_mail['id'], dbname, user_id, 'inbox', menu_mode)
                    if not success:
                        util.send_text_by_key(
                            chan, "common_messages.error", menu_mode)
                        break
                    chan.send(b'\r\n')

                    # 削除確認(y/n)
                    util.send_text_by_key(
                        chan, "mail_handler.confirm_delete_after_read_yn", menu_mode, add_newline=False)
                    delete_choice_input = ssh_input.process_input(chan)
                    if delete_choice_input is None:
                        return "back_to_top"
                    delete_choice = delete_choice_input.strip().lower()

                    if delete_choice == 'y':
                        toggled, new_status = sqlite_tools.toggle_mail_delete_status_generic(
                            dbname, oldest_unread_mail['id'], user_id, 'recipient')
                        if toggled and new_status == 1:  # 削除された場合
                            util.send_text_by_key(
                                chan, "mail_handler.mail_deleted_after_read_success", menu_mode)
                        elif not toggled:
                            util.send_text_by_key(
                                chan, "mail_handler.toggle_delete_status_failed", menu_mode)
                elif read_choice == 'n':
                    # 読まなくても既読にする
                    sqlite_tools.mark_mail_as_read(
                        dbname, oldest_unread_mail['id'], user_id)
                else:
                    break  # 未読処理ループを抜ける
            continue  # メインのメールメニュープロンプトに戻る
        elif choice == '':
            return "back_to_top"  # トップメニューに戻ることを示す
        else:
            pass

    if view_mode in ('inbox', 'outbox'):
        mails = []
        current_index = 0  # -1が先頭マーカー lenが末尾マーカー
        mail_count_digits = 5  # メールのID表示桁数、メール数に応じて変動

        def update_current_display():  # clear_screen パラメータを削除
            """現在のcurrent_indexに対応するメールを表示する内部関数"""
            nonlocal mails, current_index, mail_count_digits
            # 画面クリア命令は削除

            if current_index == -1:
                # 先頭マーカーのID部分も mail_count_digits に合わせる
                marker_id_str = "0" * mail_count_digits
                chan.send(f"{marker_id_str} v\r\n")
            elif current_index == len(mails):
                if not mails:  # エラー対策
                    util.send_text_by_key(
                        chan, "mail_handler.no_mails", menu_mode)  # メールがありません。
                else:
                    # 末尾マーカーのID部分も mail_count_digits に合わせる
                    marker_num = len(mails) + 1  # 表示上の番号
                    marker_id_str = f"{marker_num:0{mail_count_digits}d}"
                    chan.send(f"{marker_id_str} ^\r\n")
            elif mails and 0 <= current_index < len(mails):
                display_mail_header(
                    chan, mails[current_index], dbname, view_mode, mail_id_width=mail_count_digits)
            else:
                chan.send("メールがありません。\r\n")

        def reload_mails(keep_index=True):
            """メールリストを再読み込みし、表示を更新する内部関数"""
            nonlocal mails, current_index, mail_count_digits
            current_mail_id = None
            if mails and 0 <= current_index < len(mails):
                current_mail_id = mails[current_index]['id']

            try:
                if view_mode == 'inbox':
                    sql = """
                        SELECT id, sender_id, subject, is_read, sent_at, recipient_deleted
                        FROM mails
                        WHERE recipient_id = ?
                        ORDER BY sent_at ASC
                    """
                else:  # outbox
                    sql = """
                        SELECT id, recipient_id, subject, is_read, sent_at, sender_deleted
                        FROM mails
                        WHERE sender_id = ?
                        ORDER BY sent_at ASC
                    """

                fetched_mails = sqlite_tools.sqlite_execute_query(
                    dbname, sql, (user_id,), fetch=True)
                mails = fetched_mails if fetched_mails else []

                new_index = 0

                if mails:
                    if keep_index and current_mail_id is not None:
                        found = False
                        for i, mail_item in enumerate(mails):
                            if mail_item['id'] == current_mail_id:
                                new_index = i
                                found = True
                                break
                        if not found:
                            new_index = 0  # 該当メールがなければ先頭へ
                    # else:kttp_index=falseならnew_indexは0(先頭)
                current_index = new_index  # mailsが空なら0、あれば0以上len-1以下

                # mail_count_digits を更新
                if mails:
                    mail_count_digits = max(
                        5, len(str(len(mails) + 1)))  # 表示する最大番号の桁数
                else:
                    mail_count_digits = 5

                # reroad_mails直後はマーカー状態にしない
                if view_mode == 'inbox':
                    util.send_text_by_key(
                        chan, "mail_handler.sender_header", menu_mode)  # 送信ヘッダ
                else:  # outbox")
                    util.send_text_by_key(
                        chan, "mail_handler.recipient_header", menu_mode)  # 受信ヘッダ

                if not mails:
                    util.send_text_by_key(
                        chan, "mail_handler.no_mails", menu_mode)  # メールがありません。
                    current_index = 0
                elif 0 <= current_index < len(mails):
                    display_mail_header(
                        chan, mails[current_index], dbname, view_mode, mail_id_width=mail_count_digits)
                return True
            except Exception as e:
                logging.error(
                    f"メール一覧取得中にDBエラー (ユーザーID: {user_id},Mode:{view_mode}): {e}")
                chan.send("\r\nメール一覧の取得中にエラーが発生しました。\r\n")
                mails = []
                current_index = 0
                return False

        def read_selected_mail(advance_cursor_after=True):
            """
            current_indexのメールを読んで必要ならカーソルを進める。有効なメールでない場合は何もしない
            """
            nonlocal current_index
            if not (mails and 0 <= current_index < len(mails)):
                chan.send('\a')  # ビープ音
                # 何もしない
                return
            selected_mail_data = mails[current_index]
            selected_mail_id = selected_mail_data['id']

            is_deleted = False
            try:
                if view_mode == 'inbox' and selected_mail_data['recipient_deleted'] == 1:
                    is_deleted = True
                elif view_mode == 'outbox' and selected_mail_data['sender_deleted'] == 1:
                    is_deleted = True
            except KeyError:
                logging.warning(
                    f"メールデータに削除フラグが見つかりません(MailID: {selected_mail_id})")

            if is_deleted:  # 削除されている場合
                util.send_text_by_key(
                    chan, "mail_handler.mail_deleted", menu_mode)  # メールは削除されています
                if advance_cursor_after:
                    if mails:  # メール空対策
                        current_index += 1
                    update_current_display()
                return

            success, marked_as_read = display_mail_content(
                chan, selected_mail_id, dbname, user_id, view_mode, menu_mode)

            if success:
                reload_mails(keep_index=True)
                if advance_cursor_after:
                    if mails:  # メール空対策
                        current_index += 1
                    update_current_display()  # メールヘッダ表示
                else:

                    next_mail_index_for_header = current_index+1
            else:
                update_current_display()

        # 初期読み込みと表示
        if not reload_mails(keep_index=False):  # 先頭から表示
            return

        # メインループ
        while True:
            key_input = None
            try:
                data = chan.recv(1)
                if not data:
                    logging.info(
                        f"メールメニュー中にクライアントが切断されました。 (ユーザーID: {user_id})")
                    break

                if data == b'\x1b':  # esc - 矢印の可能性
                    chan.settimeout(0.05)
                    try:
                        nextbyte1 = chan.recv(1)
                        if nextbyte1 == b'[':
                            nextbyte2 = chan.recv(1)
                            if nextbyte2 == b'A':
                                key_input = "KEY_UP"
                            elif nextbyte2 == b'B':
                                key_input = "KEY_DOWN"
                            elif nextbyte2 == b'C':
                                key_input = "KEY_RIGHT"
                            elif nextbyte2 == b'D':
                                key_input = "KEY_LEFT"
                            else:
                                key_input = '\x1b'  # 不明なのはesc扱い
                        else:
                            key_input = '\x1b'  # escのあとに[以外が来た場合
                    except socket.timeout:
                        key_input = '\x1b'  # タイムアウトもesc扱い
                    finally:
                        chan.settimeout(None)
                elif data == b'\t':
                    key_input = '\t'  # タブキー
                elif data == b'\r' or data == b'\n':
                    key_input = '\r'  # エンターキー
                else:
                    try:
                        key_input = data.decode('ascii')
                    except UnicodeDecodeError:
                        chan.send('\a')  # デコードできないときはビープ音
                        continue
            except Exception as e:
                logging.error(f"メールメニュー中にソケット受信エラー (ユーザーID: {user_id}): {e}")
                break

            if key_input is None:  # キーが取得できなかった場合
                continue

            # 旧方向へ進む[ctrl+e][k]
            if key_input == '\x05' or key_input == 'k' or key_input == 'K' or key_input == "KEY_UP":
                if not mails:
                    chan.send('\a')  # ビープ音
                    continue
                if current_index > -1:
                    current_index -= 1
                    update_current_display()
                else:
                    chan.send('\a')  # 先頭だよビープ音

            # 旧方向へ読み進む[ctrl+r][h]
            elif key_input == '\x12' or key_input == 'h' or key_input == 'H' or key_input == "KEY_LEFT":
                if not mails:
                    chan.send('\a')  # ビープ音
                    continue
                if current_index > 0:
                    current_index -= 1
                    slected_mail_data = mails[current_index]
                    is_deleted = False
                    try:
                        if view_mode == 'inbox' and slected_mail_data['recipient_deleted']:
                            is_deleted = True
                        elif view_mode == 'outbox' and slected_mail_data['sender_deleted']:
                            is_deleted = True
                    except KeyError:
                        pass

                    if is_deleted:
                        util.send_text_by_key(
                            chan, "common_messages.mail_deleted", menu_mode
                        )  # メールは削除されています。
                        if view_mode == 'inbox':
                            util.send_text_by_key(
                                chan, "mail_handler.sender_header", menu_mode
                            )  # 送信ヘッダ
                        else:  # outbox
                            util.send_text_by_key(
                                chan, "mail_handler.recipient_header", menu_mode
                            )  # 受信ヘッダ
                        update_current_display()
                    else:
                        success, _ = display_mail_content(
                            chan, slected_mail_data['id'], dbname, user_id, view_mode, menu_mode)
                        if success:
                            chan.send('\r\n')
                            if view_mode == 'inbox':
                                util.send_text_by_key(
                                    chan, "mail_handler.sender_header", menu_mode
                                )  # 送信ヘッダ
                            else:
                                util.send_text_by_key(
                                    chan, "mail_handler.recipient_header", menu_mode
                                )  # 受信ヘッダ
                            update_current_display()
                elif current_index == 0:
                    current_index -= 1
                    update_current_display()
                else:
                    chan.send('\a')  # 先頭だよビープ音

            # 現在地を読む(読んでも進まない)[ctrl+d][return]
            elif key_input == '\x04' or key_input == '\r':
                if current_index == -1 or current_index == len(mails):
                    chan.send('\a')  # ビープ音
                elif not mails:
                    util.send_text_by_key(
                        chan, "mail_handler.no_mails", menu_mode
                    )
                else:
                    read_selected_mail(advance_cursor_after=False)

            # 新方向へ読み進む[ctrl+f][l]
            elif key_input == '\x06' or key_input == 'l' or key_input == 'L' or key_input == "KEY_RIGHT" or key_input == "\t":
                if not mails:
                    chan.send('\a')  # ビープ音
                    continue

                # current_indexが-1の時は０に移動
                if current_index == -1:
                    if not mails:  # 先頭マーカの時にメールがなくなったら
                        chan.send('\a')
                        update_current_display()
                        continue
                    current_index = 0

                # current_indexがlen以上、末尾マーカ表示中かそれを超えたら、それ以上進めない
                if current_index >= len(mails):
                    chan.send('\a')
                    continue

                # ここに来るときは0<=current_index<len(mails)が保証される
                selected_mail_data = mails[current_index]
                is_deleted = False
                try:
                    if view_mode == 'inbox' and selected_mail_data['recipient_deleted'] == 1:
                        is_deleted = True
                    elif view_mode == 'outbox' and selected_mail_data['sender_deleted'] == 1:
                        is_deleted = True
                except KeyError:
                    pass  # Falseのまま

                if is_deleted:
                    util.send_text_by_key(
                        chan, "mail_handler.mail_deleted", menu_mode
                    )  # メールは削除されています
                # 削除されていてもカーソルは進める
                else:
                    success, _ = display_mail_content(
                        chan, selected_mail_data['id'], dbname, user_id, view_mode, menu_mode)
                    if success:
                        chan.send('\r\n')

                current_index += 1

                # 次のメールヘッダ準備
                if 0 <= current_index < len(mails):
                    if view_mode == 'inbox':
                        util.send_text_by_key(
                            chan, "mail_handler.sender_header", menu_mode
                        )  # 送信ヘッダ
                    else:  # outbox
                        util.send_text_by_key(
                            chan, "mail_handler.recipient_header", menu_mode
                        )  # 受信ヘッダ
                update_current_display()

            # 新方向へ進む[ctrl+x][j][space]
            elif key_input == '\x18' or key_input == 'j' or key_input == 'J' or key_input == ' ' or key_input == "KEY_DOWN":
                if not mails:
                    chan.send('\a')
                    continue
                if current_index < len(mails):
                    current_index += 1
                    update_current_display()
                else:
                    chan.send('\a')  # 末尾だよビープ音

            # 終了[ctrl+c][esc][e]
            elif key_input == '\x03' or key_input == '\x1b' or key_input == 'e' or key_input == 'E':
                break

            # 削除[*]
            elif key_input == '*':
                if mails and 0 <= current_index < len(mails):
                    selected_mail_id = mails[current_index]['id']

                    mode_for_toggle = None
                    if view_mode == 'inbox':
                        mode_for_toggle = 'recipient'
                    elif view_mode == 'outbox':
                        mode_for_toggle = 'sender'
                    else:
                        logging.error(
                            f"削除トグル動作時の不明なView_mode: {view_mode} (MailID: {selected_mail_id}, UserID: {user_id})")
                        update_current_display()
                        continue

                    toggled, _ = sqlite_tools.toggle_mail_delete_status_generic(
                        dbname, selected_mail_id, user_id, mode_param=mode_for_toggle)
                    if toggled:
                        reload_mails(keep_index=True)
                    else:
                        util.send_text_by_key(
                            chan, "mail_handler.toggle_delete_status_failed", menu_mode
                        )  # 状態変更に失敗しました
                        update_current_display()
                else:
                    chan.send('\a')

            # 書く[w]
            elif key_input == 'w' or key_input == 'W':
                chan.send('\r\n')
                mail_write(chan, dbname, login_id, menu_mode)
                reload_mails(keep_index=False)

            # 送受信切替[s]
            elif key_input == 's' or key_input == 'S':
                view_mode = 'outbox' if view_mode == 'inbox' else 'inbox'
                reload_mails(keep_index=False)

            # 新方向へ読み続ける[r]
            elif key_input == 'r' or key_input == 'R':
                # 現在の位置からのメールをすべて本文込みで一気に表示する
                if not mails:
                    chan.send('\a')  # メールがない場合はビープ
                    continue
                if current_index == len(mails):  # 末尾マーカ一だった場合
                    chan.send('\a')  # 既に末尾なのでビープ
                    continue

                chan.send("\r\n")

                # 表示インデックス決定
                start_processing_idx = current_index
                if start_processing_idx == -1:
                    start_processing_idx = 0

                # 開始インデックスが有効範囲外ORメールがない場合は処理しない
                if not (mails and 0 <= start_processing_idx < len(mails)):
                    if not mails and start_processing_idx == 0:
                        util.send_text_by_key(
                            chan, "mail_handler.no_mail", menu_mode
                        )  # メールはありません
                    else:
                        chan.send('\a')
                    update_current_display()
                    continue

                # 共通ヘッダ表示
                if view_mode == 'inbox':
                    util.send_text_by_key(
                        chan, "mail_handler.sender_header", menu_mode
                    )  # 送信ヘッダ
                else:
                    util.send_text_by_key(
                        chan, "mail_handler.recipient_header", menu_mode
                    )  # 受信ヘッダ

                current_index = start_processing_idx

                # current_indexが有効な場合
                while 0 <= current_index < len(mails):
                    selected_mail_data = mails[current_index]
                    selected_mail_id = selected_mail_data['id']

                    # メールヘッダ表示
                    display_mail_header(
                        chan, selected_mail_data, dbname, view_mode, mail_id_width=mail_count_digits
                    )

                    is_deleted = False
                    try:
                        if view_mode == 'inbox' and selected_mail_data['recipient_deleted'] == 1:
                            is_deleted = True
                        elif view_mode == 'outbox' and selected_mail_data['sender_deleted'] == 1:
                            is_deleted = True
                    except KeyError:
                        logging.warning(
                            f"メールデータに削除フラグが見つかりません(MailID: {selected_mail_id},Rキー処理)")

                    if is_deleted:
                        chan.send("\r\n")
                    else:
                        # メール本文表示
                        success, _ = display_mail_content(
                            chan, selected_mail_id, dbname, view_mode, menu_mode
                        )
                        if success:
                            chan.send('\r\n')
                        else:
                            chan.send('\r\n')
                    current_index += 1  # 次のメールへ

                update_current_display()

            # タイトル一覧[t]
            elif key_input == 't' or key_input == 'T':
                if not mails:
                    chan.send('\a')  # メールがない場合はビープ
                    continue
                if current_index == len(mails):  # 既に末尾マーカー位置
                    chan.send('\a')  # 既に末尾なのでビープ
                    continue

                chan.send("\r\n")  # 現在の表示からの区切り

                # 表示を開始するインデックスを決定
                start_idx_for_display = current_index
                if start_idx_for_display == -1:  # 先頭マーカーなら最初のメールから
                    start_idx_for_display = 0

                if 0 <= start_idx_for_display < len(mails):
                    # スクロール表示する内容のヘッダタイトル
                    if view_mode == 'inbox':
                        util.send_text_by_key(
                            chan, "mail_handler.sender_header", menu_mode
                        )  # 送信ヘッダ
                    else:  # outbox
                        util.send_text_by_key(
                            chan, "mail_handler.recipient_header", menu_mode
                        )  # 受信ヘッダ

                    for i in range(start_idx_for_display, len(mails)):  # 現在位置から最後まで
                        mail_data = mails[i]
                        # format_mail_header_str を使って、カーソルなしのヘッダ文字列を取得
                        header_line = format_mail_header_str(
                            mail_data, dbname, view_mode, mail_id_width=mail_count_digits
                        )
                        chan.send(header_line + "\r\n")

                current_index = len(mails)  # カーソルを末尾マーカーに移動
                update_current_display()  # プロンプト部分を更新 (画面クリアなし)

            # 説明[?]
            elif key_input == '?':
                chan.send('\r\n')
                util.send_text_by_key(
                    # TODO: mail_handler.mail_help を textdata.yaml に追加
                    chan, "mail_handler.mail_help", menu_mode
                )  # メール説明
                update_current_display()

            else:
                chan.send('\a')
                continue
    return "back_to_top"  # 通常終了時もトップメニューに戻る


def format_mail_header_str(mail_data, dbname, view_mode='inbox', mail_id_width=5):
    """指定されたメールのヘッダ情報（1行）を文字列として返す"""
    if not mail_data:
        return ""

    mail_id = mail_data['id']
    try:
        sent_dt = datetime.datetime.fromtimestamp(mail_data['sent_at'])
        date_str = sent_dt.strftime('%y-%m-%d %H:%M:%S')
    except (ValueError, OSError, TypeError):
        date_str = "---/--/-- --:--:--"

    subject = mail_data['subject'] if mail_data['subject'] else "(無題)"

    status_mark_char = " "
    is_mail_deleted_flag = False
    display_subject_final = subject

    try:
        # 削除チェック
        if view_mode == 'inbox' and mail_data['recipient_deleted'] == 1:
            is_mail_deleted_flag = True
        elif view_mode == 'outbox' and mail_data['sender_deleted'] == 1:
            is_mail_deleted_flag = True

        if is_mail_deleted_flag:
            status_mark_char = "*"
            display_subject_final = ""
        else:
            # 受信未読チェック
            if view_mode == 'inbox' and mail_data['is_read'] == 0:
                status_mark_char = "#"
            # 件名短縮
            display_subject_final = textwrap.shorten(
                subject, width=39, placeholder="..."
            )

    except KeyError as e:
        logging.warning(f"メールヘッダ表示中にキーエラー ({mail_id}): {e}")
        display_subject_final = textwrap.shorten(
            subject, width=39, placeholder="..."
        )
    mail_id_str = f"{mail_id:0{mail_id_width}d}"

    # 送信や、宛先表示
    if view_mode == 'inbox':
        sender_name = sqlite_tools.get_user_name_from_user_id(
            dbname, mail_data['sender_id'])
        return f"{mail_id_str}  {date_str}  {sender_name:<7} {status_mark_char}{display_subject_final}"
    else:  # outbox
        recipient_name = sqlite_tools.get_user_name_from_user_id(
            dbname, mail_data['recipient_id'])
        return f"{mail_id_str}  {date_str}  {recipient_name:<7} {status_mark_char}{display_subject_final}"


def display_mail_header(chan, mail_data, dbname, view_mode='inbox', mail_id_width=5):
    """指定されたメールのヘッダ情報（1行）を表示する"""
    header_line = format_mail_header_str(
        mail_data, dbname, view_mode, mail_id_width)
    if header_line:
        chan.send(header_line + "\r\n")


def display_mail_content(chan, mail_id, dbname, recipient_user_id_pk, view_mode='inbox', menu_mode='2'):
    """メールの内容を表示し、既読にする。成功/失敗(bool)と既読変更(bool)を返す"""
    try:
        mail_results = sqlite_tools.fetchall_idbase(
            dbname, 'mails', 'id', mail_id)
        if not mail_results:
            util.send_text_by_key(
                chan, "mail_handler.no_mails", menu_mode
            )  # メールが見つかりません
            return False, False

        mail_data = mail_results[0]

        body = mail_data['body'] if mail_data['body'] else "(本文なし)"

        wrapped_body = textwrap.fill(body, width=78)
        for line in wrapped_body.splitlines():
            chan.send(f"{line}\r\n")

        # 既読にする(inbox only)
        marked_as_read = False
        if view_mode == 'inbox':  # recipient_deleted == 0 のメールのみがここに到達する想定
            # is_read == 0 の条件は mark_mail_as_read 側では不要 (UPDATE文が対象を見つけられないだけ)
            # ここで条件分岐すると、何らかの理由で is_read が予期せぬ値だった場合にスキップされる可能性がある
            if sqlite_tools.mark_mail_as_read(dbname, mail_id, recipient_user_id_pk):
                marked_as_read = True
            # mark_mail_as_read 内でエラーログは出力される
        return True, marked_as_read

    except Exception as e:
        logging.error(f"メール内容表示中にエラー (ID: {mail_id}): {e}")
        return False, False


def mail_write(chan, dbname, login_id, menu_mode='2'):
    """メール送信"""
    recipient_info_list = []  # 複数宛先に対応

    while True:
        util.send_text_by_key(
            chan, "mail_handler.enter_recipient", menu_mode, add_newline=False
        )  # 送り先のIDを入力してください:
        recipient_name_input = ssh_input.process_input(chan)

        if not recipient_name_input:
            if not recipient_info_list:
                return
            else:
                break
        # データベースからユーザが存在するかを確認する。
        try:
            results = sqlite_tools.fetchall_idbase(
                dbname, 'users', 'name', recipient_name_input)
        except Exception as e:
            logging.error(f"宛先ユーザ検索中にDBエラー({recipient_name_input}): {e}")
            util.send_text_by_key(
                chan, "common_messages.db_error", menu_mode
            )  # エラー発生
            return
        if not results:
            chan.send("** 送り先が存在しません **\r\n")
            continue

        # ユーザの存在を確認したらコメントを取得
        userdata = results[0]
        current_recipient_name = userdata['name']
        current_recipient_comment = userdata[
            'comment'] if userdata['comment'] else "(No comment)"

        chan.send(f"\"{current_recipient_comment}\"\r\n")
        util.send_text_by_key(
            chan, "mail_handler.recipient_yn", menu_mode, add_newline=False
        )  # この送り先でよいですか?(Y または N):
        # 送り先の確認
        confirm_add_recipient = ''
        while True:
            ans = ssh_input.process_input(chan).lower()
            if ans in ('y', 'n'):
                confirm_add_recipient = ans
                break
            else:
                util.send_text_by_key(
                    chan, "mail_handler.recipient_yn", menu_mode, add_newline=False
                )  # この送り先でよいですか?(Y または N):
        if confirm_add_recipient == 'y':
            recipient_info_list.append(
                (current_recipient_name, current_recipient_comment)
            )
            util.send_text_by_key(
                chan, "mail_handler.send_another_yn", menu_mode, add_newline=False
            )
            add_more_ans = ssh_input.process_input(chan).lower()
            if add_more_ans == 'y':
                continue
            else:
                break
        else:
            if not recipient_info_list:
                continue
            else:
                break

    # ループを抜けたあとの最終チェック
    if not recipient_info_list:
        return

    # ここから後ろ、データベースに保存する手前までは掲示板でも利用するので、あとで関数化する
    util.send_text_by_key(
        chan, "mail_handler.enter_subject", menu_mode, add_newline=False
    )  # 件名を入力してください:
    subject = ssh_input.process_input(chan)
    if subject is None:
        return
    if not subject:
        subject = "(No subject)"
    # 21文字制限(増やしてもいいかも)
    if len(subject) > 21:
        subject = subject[:21]

    # 本文入力
    util.send_text_by_key(
        chan, "mail_handler.enter_body", menu_mode)
    message_lines = []
    while True:
        line = ssh_input.process_input(chan)
        if line is None:
            return
        if line == '^':
            break
        message_lines.append(line)
    message = '\r\n'.join(message_lines)
    if not message:
        util.send_text_by_key(
            chan, "mail_handler.no_body", menu_mode
        )
        return

    # 送信内容確認
    util.send_text_by_key(
        chan, "mail_handler.confirm_send", menu_mode)  # 送信内容
    util.send_text_by_key(
        chan, "mail_handler.recipient", menu_mode, current_recipient_name=current_recipient_name, current_recipient_comment=current_recipient_comment)  # 宛先
    util.send_text_by_key(
        chan, "mail_handler.subject", menu_mode, subject=subject)  # 件名
    util.send_text_by_key(
        chan, "mail_handler.body", menu_mode, message=message
    )  # 本文

    for line in message.split('\r\n'):
        chan.send(f"{line}\r\n")
    util.send_text_by_key(
        chan, "mail_handler.confirm_send_yn", menu_mode, add_newline=False
    )  # この内容で送信しますか?(y/n):
    # 確認入力 (y/n)
    confirm_input = ''
    while True:
        data = chan.recv(1)
        if not data:
            logging.warning(f"メール送信確認中に切断されました({login_id})")
            return
        try:
            char = data.decode('ascii').lower()
            if char == 'y':
                chan.send('y\r\n')
                confirm_input = 'y'
                break
            elif char == 'n':
                chan.send('n\r\n')
                confirm_input = 'n'
                break
            else:
                pass  # y, n 以外は無視
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logging.error(f"メール送信確認中の入力エラー({login_id}): {e}")
            util.send_text_by_key(
                chan, "common_message.error", menu_mode
            )
            return
    # 'n' が入力された場合はキャンセル
    if confirm_input == 'n':
        util.send_text_by_key(
            chan, "mail_handler.send_cancelled", menu_mode
        )  # メール送信をキャンセルしました。
        return
    # データベースにメールを保存
    try:
        # 送信者のIDを取得
        sender_results = sqlite_tools.fetchall_idbase(
            dbname, 'users', 'name', login_id)
        # 一応念の為
        if not sender_results:
            chan.send("送信者情報の取得に失敗しました。シスオペに連絡してください\r\n")
            util.send_text_by_key(
                chan, "common_message.error", menu_mode
            )
            return

        sender_id = sender_results[0]['id']
        sent_at = int(time.time())

        for rec_name, _ in recipient_info_list:
            recipient_results = sqlite_tools.fetchall_idbase(
                dbname, 'users', 'name', rec_name)
            if not recipient_results:
                logging.error(f"送信に失敗、{rec_name}がDBに存在しません。")
                util.send_text_by_key(
                    chan, "common_message.error", menu_mode)
                continue

            recipient_id = recipient_results[0]['id']

            # mailsテーブルにデータ挿入
            sql = """
                INSERT INTO mails (sender_id, recipient_id, subject, body, sent_at)
                VALUES (?, ?, ?, ?, ?)
                """
            params = (sender_id, recipient_id, subject, message, sent_at)
            sqlite_tools.sqlite_execute_query(dbname, sql, params)

            util.send_text_by_key(
                chan, "mail_handler.send_success", menu_mode
            )  # メールを送信しました

    except Exception as e:
        logging.error(f"メール送信中にDBエラー({login_id} -> ?): {e}")
        util.send_text_by_key(
            chan, "common_message.error", menu_mode
        )
    return
