import ssh_input
import util
import datetime
import sqlite_tools
import time
import logging
import textwrap
import sqlite3


def display_mail_header(chan, mail_data, dbname, view_mode='inbox'):
    """指定されたメールのヘッダ情報（1行）を表示する"""
    if not mail_data:
        return

    mail_id = mail_data['id']
    try:
        sent_dt = datetime.datetime.fromtimestamp(mail_data['sent_at'])
        date_str = sent_dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, OSError, TypeError):
        date_str = "---/--/-- --:--"

    subject = mail_data['subject'] if mail_data['subject'] else "(無題)"

    deleted_mark = ""
    display_subject = subject
    try:
        if view_mode == 'inbox' and mail_data['recipient_deleted'] == 1:
            deleted_mark = "*"
        elif view_mode == 'outbox' and mail_data['sender_deleted'] == 1:
            deleted_mark = "*"
        if deleted_mark:
            display_subject = "(削除済み)"
        else:
            display_subject = textwrap.shorten(
                subject, width=40, placeholder="...")
    except KeyError as e:
        logging.warning(f"メールヘッダ表示中にキーエラー ({mail_id}): {e}")
        display_subject = textwrap.shorten(
            subject, width=40, placeholder="..."
        )

    # 送信や、宛先表示
    if view_mode == 'inbox':
        sender_name = sqlite_tools.get_user_name_from_user_id(
            dbname, mail_data['sender_id'])
        line = f"{mail_id:<3} {date_str} {sender_name:<12} {deleted_mark} {display_subject}\r\n"
    else:  # outbox
        recipient_name = sqlite_tools.get_user_name_from_user_id(
            dbname, mail_data['recipient_id'])
        line = f"{mail_id:<3} {date_str} To: {recipient_name:<9} {deleted_mark}  {display_subject}\r\n"
    chan.send(line)


def display_mail_content(chan, mail_id, dbname, view_mode='inbox'):
    """メールの内容を表示し、既読にする。成功/失敗(bool)と既読変更(bool)を返す"""
    try:
        mail_results = sqlite_tools.fetchall_idbase(
            dbname, 'mails', 'id', mail_id)
        if not mail_results:
            chan.send("\r\nエラー: メールが見つかりません。\r\n")
            time.sleep(1)
            return False, False

        mail_data = mail_results[0]

        subject = mail_data['subject'] if mail_data['subject'] else "(無題)"
        body = mail_data['body'] if mail_data['body'] else "(本文なし)"
        try:
            sent_dt = datetime.datetime.fromtimestamp(mail_data['sent_at'])
            date_str = sent_dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError, TypeError):
            date_str = "不明な日時"

        # 本文
        if view_mode == 'inbox':
            sender_name = sqlite_tools.get_user_name_from_user_id(
                dbname, mail_data['sender_id'])
            chan.send(f"送信者: {sender_name}\r\n")
        else:  # outbox
            recipient_name = sqlite_tools.get_user_name_from_user_id(
                dbname, mail_data['recipient_id'])
        chan.send(f"日時: {date_str}\r\n")
        wrapped_body = textwrap.fill(body, width=78)
        for line in wrapped_body.splitlines():
            chan.send(f"{line}\r\n")

        # 既読にする(inbox only)
        marked_as_read = False
        if view_mode == 'inbox' and 'is_read' in mail_data and mail_data['is_read'] == 0:
            try:
                sql = "UPDATE mails SET is_read = 1 WHERE id = ?"
                sqlite_tools.sqlite_execute_query(dbname, sql, (mail_id,))
                marked_as_read = True
            except Exception as e:
                logging.error(f"メール既読処理中にDBエラー (ID: {mail_id}): {e}")
                chan.send("\r\n(既読処理中にエラーが発生しました)\r\n")
        return True, marked_as_read

    except Exception as e:
        logging.error(f"メール内容表示中にエラー (ID: {mail_id}): {e}")
        chan.send("\r\nメール内容の表示中にエラーが発生しました。\r\n")
        time.sleep(1)
        return False, False


def mail(chan, dbname, login_id):
    """
    メールメニュー (パソコン通信風)
    受信メールのタイトルを1行表示し、j/kで移動、Enterで本文表示。
    dで削除/復元。sで送受信変更。
    wで作成、eで終了。
    """
    user_id = sqlite_tools.get_user_id_from_user_name(dbname, login_id)
    if user_id is None:
        chan.send("\r\nエラー: ユーザー情報が見つかりません。\r\n")
        return

    mails = []
    current_index = 0  # 現在表示しているメールのインデックス (リストは新しい順=0が最新)
    view_mode = 'inbox'

    def reload_mails(keep_index=True):
        """メールリストを再読み込みし、表示を更新する内部関数"""
        nonlocal mails, current_index
        current_mail_id = mails[current_index]['id'] if mails and 0 <= current_index < len(
            mails) else None

        try:
            if view_mode == 'inbox':
                sql = """
                    SELECT id, sender_id, subject, is_read, sent_at, recipient_deleted
                    FROM mails
                    WHERE recipient_id = ?
                    ORDER BY sent_at DESC
                """
                chan.send(f"\r\n--- 受信メール ---\r\n")
            else:  # outbox
                sql = """
                    SELECT id, recipient_id, subject, is_read, sent_at, sender_deleted
                    FROM mails
                    WHERE sender_id = ?
                    ORDER BY sent_at DESC
                """
                chan.send(f"\r\n--- 送信メール ---\r\n")

            fetched_mails = sqlite_tools.sqlite_execute_query(
                dbname, sql, (user_id,), fetch=True)
            mails = fetched_mails if fetched_mails else []

            new_index = 0
            if keep_index and current_mail_id is not None:
                found = False
                for i, mail_item in enumerate(mails):
                    if mail_item['id'] == current_mail_id:
                        new_index = i
                        found = True
                        break
            current_index = new_index

            if not mails:
                chan.send("メールはありません。\r\n")
            else:
                # インデックスチェック
                if current_index >= len(mails):
                    current_index = len(mails)-1
                if current_index < 0:
                    current_index = 0
                display_mail_header(
                    chan, mails[current_index], dbname, view_mode)
                return True

        except Exception as e:
            logging.error(
                f"メール一覧取得中にDBエラー (ユーザーID: {user_id},Mode:`view_mode`): {e}")
            chan.send("\r\nメール一覧の取得中にエラーが発生しました。\r\n")
            mails = []
            current_index = 0
            return False

    # 初期読み込みと表示
    if not reload_mails():
        return

    # メインループ
    while True:
        data = chan.recv(1)
        try:
            if data == b'\r' or data == b'\n':
                char = '\r'
            else:
                char = data.decode('ascii').lower()
        except UnicodeDecodeError:
            chan.send('\a')
            continue
        except Exception as e:
            logging.error(f"メールメニュー中にエラー (ユーザーID: {user_id}): {e}")
            continue

        # 入力判定
        if char == 'j':  # 次へ (古い方へ、インデックス増)
            if mails and current_index < len(mails) - 1:
                current_index += 1
                display_mail_header(
                    chan, mails[current_index], dbname, view_mode)
            else:
                chan.send('\a')  # ビープ音 (移動できない)
        elif char == 'k':  # 前へ (新しい方へ、インデックス減)
            if mails and current_index > 0:
                current_index -= 1
                display_mail_header(
                    chan, mails[current_index], dbname, view_mode)
            else:
                chan.send('\a')  # ビープ音
        elif char == '\r':  # Enter (メールを読む)
            if mails:
                selected_mail_data = mails[current_index]
                selected_mail_id = mails[current_index]['id']

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
                    chan.send("メールは削除されています\r\n\r\n")
                    if current_index < len(mails) - 1:
                        current_index += 1
                    # 次のメールヘッダを表示
                    if mails:
                        display_mail_header(
                            chan, mails[current_index], dbname, view_mode)
                    else:
                        chan.send("メールがありません。\r\n")
                else:

                    # 本文表示 (成功フラグ, 既読変更フラグ を受け取る)
                    success, marked_as_read = display_mail_content(
                        chan, selected_mail_id, dbname, view_mode)

                    if success:
                        if current_index < len(mails) - 1:
                            current_index += 1
                        # 次のメールヘッダを表示 (リストが空でなければ)
                        if mails:
                            display_mail_header(
                                chan, mails[current_index], dbname, view_mode)
                        else:
                            chan.send("メールがありません。\r\n")

                    else:
                        # 本文表示失敗時も、現在のヘッダを再表示しておく
                        if mails:
                            display_mail_header(
                                chan, mails[current_index], dbname, view_mode)
                        else:
                            chan.send("メールがありません。\r\n")
            else:
                chan.send("読むメールがありません。\r\n")

        elif char == 'd':  # メール削除トグル
            if mails:
                selected_mail_id = mails[current_index]['id']
                toggled = False
                new_status = 0
                if view_mode == 'inbox':
                    toggled, new_status = sqlite_tools.toggle_mail_delete_status_generic(
                        dbname, selected_mail_id, user_id, mode='recipient')
                else:  # outbox
                    toggled, new_status = sqlite_tools.toggle_mail_delete_status_generic(
                        dbname, selected_mail_id, user_id, mode='sender')
                if toggled:
                    reload_mails(keep_index=True)
                else:
                    chan.send("メールの状態変更が失敗しました。\r\n")
                    if mails:
                        display_mail_header(
                            chan, mails[current_index], dbname, view_mode)
                    else:
                        chan.send("メールがありません。\r\n")
            else:
                chan.send("対象のメールがありません。\r\n")
        elif char == 's':  # 受信/送信切り替え
            view_mode = 'outbox' if view_mode == 'inbox' else 'inbox'
            reload_mails(keep_index=False)  # モード切替時はインデックスをリセット
        elif char == 'w':  # メール作成
            chan.send("\r\n")
            mail_write(chan, dbname, login_id)
            reload_mails(keep_index=False)  # メール作成後はインデックスをリセット
        elif char == '?' or char == 'h':  # ヘルプ
            chan.send("\r\n")
            util.show_textsfile(chan, "mailmenu.txt")
            if mails:
                display_mail_header(
                    chan, mails[current_index], dbname, view_mode)
            else:
                chan.send("メールがありません。\r\n")
        elif char == 'e':  # 終了
            chan.send("\r\nメールメニューを終了します。\r\n")
            break  # ループを抜ける

        else:
            chan.send('\a')
    return


def mail_write(chan, dbname, login_id):
    """メール送信"""
    chan.send("送信先のIDを入力してください: ")
    recipient_name = ssh_input.process_input(chan)

    if not recipient_name:
        chan.send("\r\n宛先が入力されていません。\r\n")
        return
    # データベースからユーザが存在するかを確認する。
    try:
        results = sqlite_tools.fetchall_idbase(
            dbname, 'users', 'name', recipient_name)
    except Exception as e:
        logging.error(f"宛先ユーザ検索中にDBエラー({recipient_name}): {e}")
        chan.send(f"何かがおかしいです。シスオペに連絡してください\r\n")
        return
    if not results:
        chan.send(f"宛先'{recipient_name}'は存在しません\r\n")
        return
    # ユーザの存在を確認したらコメントを取得
    userdata = results[0]
    recipient_comment = userdata['comment'] if userdata['comment'] else "(コメントなし)"
    chan.send(f"宛先: {recipient_name} ({recipient_comment})\r\n")
    chan.send("この宛先でよろしいですか?(y/n): ")

    rtinput = ''
    while True:
        data = chan.recv(1)
        if not data:
            logging.warning("メール宛先中に切断されました({login_id})")
            return
        try:
            char = data.decode('ascii').lower()
            if char == 'y':
                chan.send("y\r\n")
                rtinput = 'y'
                break
            elif char == 'n':
                chan.send("n\r\n")
                rtinput = 'n'
                break
            else:
                pass
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logging.error(f"メール宛先入力中にエラー({login_id}): {e}")
            return

    if rtinput == 'n':
        chan.send("メール送信をキャンセルしました。\r\n")
        return
    # ここから後ろ、データベースに保存する手前までは掲示板でも利用するので、あとで関数化する
    chan.send("件名を入力してください: ")
    subject = ssh_input.process_input(chan)
    if subject is None:
        return
    if not subject:
        subject = "(無題)"

    chan.send("本文を入力してください('.'のみの行で終了): \r\n")
    message_lines = []
    while True:
        line = ssh_input.process_input(chan)
        if line is None:
            return
        if line == '.':
            break
        message_lines.append(line)
    message = '\r\n'.join(message_lines)
    if not message:
        chan.send("本文が入力されていません。終了します。\r\n")
        return

    # 送信内容確認
    chan.send("\r\n-- 送信内容 --\r\n")
    chan.send(f"宛先: {recipient_name} ({recipient_comment})\r\n")
    chan.send(f"件名: {subject}\r\n")
    chan.send("本文:\r\n")

    for line in message.split('\r\n'):
        chan.send(f"{line}\r\n")
    chan.send("-- ここまで --\r\n")
    chan.send("この内容で送信しますか?(y/n): ")
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
            chan.send("\r\n入力処理中にエラーが発生しました。\r\n")
            return
    # 'n' が入力された場合はキャンセル
    if confirm_input == 'n':
        chan.send("メール送信をキャンセルしました。\r\n")
        return
    # データベースにメールを保存
    try:
        # 送信者のIDを取得
        sender_results = sqlite_tools.fetchall_idbase(
            dbname, 'users', 'name', login_id)
        # 一応念の為
        if not sender_results:
            chan.send("送信者情報の取得に失敗しました。シスオペに連絡してください\r\n")
            logging.error(f"送信者情報の取得に失敗しました。{login_id}がDBに存在しません。")
            return

        sender_id = sender_results[0]['id']
        recipient_id = userdata['id']
        sent_at = int(time.time())

        # mailsテーブルにデータ挿入
        sql = """
        INSERT INTO mails (sender_id, recipient_id, subject, body, sent_at)
        VALUES (?, ?, ?, ?, ?)
        """
        params = (sender_id, recipient_id, subject, message, sent_at)
        sqlite_tools.sqlite_execute_query(dbname, sql, params)

        chan.send("\r\nメールを送信しました\r\n")

    except Exception as e:
        logging.error(f"メール送信中にDBエラー({login_id} -> {recipient_name}): {e}")
        chan.send("\r\nメール送信中にエラーが発生しました。シスオペに連絡してください\r\n")
    return
