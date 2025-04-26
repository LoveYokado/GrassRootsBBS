import ssh_input
import util
import datetime
import sqlite_tools
import time
import logging
import textwrap


def display_mail_header(chan, mail_data, dbname, is_selected=True):
    """指定されたメールのヘッダ情報（1行）を表示する"""
    if not mail_data:
        return

    mail_id = mail_data['id']
    # 未読マークは削除 (表示形式に合わせて)
    # read_status = " " if mail_data['is_read'] else "*"
    sender_name = sqlite_tools.get_sender_name_from_user_id(
        dbname, mail_data['sender_id'])
    subject = mail_data['subject'] if mail_data['subject'] else "(無題)"
    try:
        sent_dt = datetime.datetime.fromtimestamp(mail_data['sent_at'])
        # フォーマット: YYYY-MM-DD HH:MM
        date_str = sent_dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, OSError, TypeError):
        date_str = "----/--/-- --:--"

    # 表示形式: メールID 送信日時 送信者 件名
    # 例: 1  2025-01-01 20:01 guest ほげほげ
    # 幅調整: ID(3), 日付(16), 送信者(12), 件名(残り)
    display_subject = textwrap.shorten(subject, width=40, placeholder="...")
    # is_selected フラグは将来的に使うかも (例: カーソル表示)
    line = f"{mail_id:<3} {date_str} {sender_name:<12} {display_subject}\r\n"
    chan.send(line)


def display_mail_content(chan, mail_id, dbname):
    """メールの内容を表示し、既読にする。成功/失敗(bool)と既読変更(bool)を返す"""
    try:
        mail_results = sqlite_tools.fetchall_idbase(
            dbname, 'mails', 'id', mail_id)
        if not mail_results:
            chan.send("\r\nエラー: メールが見つかりません。\r\n")
            time.sleep(1)
            return False, False

        mail_data = mail_results[0]

        sender_name = sqlite_tools.get_sender_name_from_user_id(
            dbname, mail_data['sender_id'])
        subject = mail_data['subject'] if mail_data['subject'] else "(無題)"
        body = mail_data['body'] if mail_data['body'] else "(本文なし)"
        try:
            sent_dt = datetime.datetime.fromtimestamp(mail_data['sent_at'])
            date_str = sent_dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError, TypeError):
            date_str = "不明な日時"

        # --- 本文表示 ---
        chan.send("--本文-----------------------------------------\r\n")
        chan.send(f"差出人: {sender_name}\r\n")
        chan.send(f"件名: {subject}\r\n")
        chan.send(f"日時: {date_str}\r\n")
        chan.send("-----------------------------------------------\r\n")
        wrapped_body = textwrap.fill(body, width=78)
        for line in wrapped_body.splitlines():
            chan.send(line + "\r\n")
        chan.send("-----------------------------------------------\r\n")

        # --- メールを既読にする ---
        marked_as_read = False
        if mail_data['is_read'] == 0:  # 未読の場合のみ更新
            try:
                sql = "UPDATE mails SET is_read = 1 WHERE id = ?"
                sqlite_tools.sqlite_execute_query(dbname, sql, (mail_id,))
                marked_as_read = True  # 既読状態が変更された
            except Exception as e:
                logging.error(f"メール既読処理中にDBエラー (ID: {mail_id}): {e}")
                chan.send("\r\n(既読処理中にエラーが発生しました)\r\n")
                # エラーでも処理は続行するが、既読変更フラグは False のまま

        return True, marked_as_read
    except Exception as e:
        logging.error(f"メール本文表示中にDBエラー (ID: {mail_id}): {e}")
        chan.send("\r\n(本文表示中にエラーが発生しました)\r\n")
        time.sleep(1)
        return False, False


def mail(chan, dbname, login_id):
    """
    メールメニュー (パソコン通信風)
    受信メールのタイトルを1行表示し、j/kで移動、Enterで本文表示。
    wで作成、eで終了。
    """
    user_id = sqlite_tools.get_user_id_from_user_name(dbname, login_id)
    if user_id is None:
        chan.send("\r\nエラー: ユーザー情報が見つかりません。\r\n")
        return

    mails = []
    current_index = 0  # 現在表示しているメールのインデックス (リストは新しい順=0が最新)

    def reload_mails():
        """メールリストを再読み込みし、表示を更新する内部関数"""
        nonlocal mails, current_index
        try:
            # 受信トレイを取得 (recipient_deleted = 0 のもの、新しい順)
            # mails テーブルに必要なカラムを取得 (id, sender_id, subject, is_read, sent_at)
            sql = """
                SELECT id, sender_id, subject, is_read, sent_at
                FROM mails
                WHERE recipient_id = ? AND recipient_deleted = 0
                ORDER BY sent_at DESC
            """
            # sqlite_execute_query は Row オブジェクトのリストを返す想定
            fetched_mails = sqlite_tools.sqlite_execute_query(
                dbname, sql, (user_id,), fetch=True)
            mails = fetched_mails if fetched_mails else []

            # インデックスをリセット (最新=0番目)
            current_index = 0
            chan.send("\r\n--- 受信メール ---\r\n")  # 見出し表示
            if not mails:
                chan.send("受信メールはありません。\r\n")
            else:
                # 最初のメールヘッダを表示
                display_mail_header(chan, mails[current_index], dbname)
            return True
        except Exception as e:
            logging.exception(
                f"メール一覧取得中にDBエラー (ユーザーID: {user_id}): {e}")  # スタックトレースも記録
            chan.send("\r\nメール一覧の取得中にエラーが発生しました。\r\n")
            mails = []
            current_index = 0
            return False

    # --- 初期読み込み & 表示 ---
    if not reload_mails():
        return  # 読み込み失敗時は終了

    # --- メインループ ---
    while True:
        # 1文字入力待機 (chan.recv(1) を使用)
        # 注意: この方法はクライアントが特殊なキーシーケンスを送ってきた場合に問題が起きる可能性あり
        data = chan.recv(1)
        if not data:
            logging.warning(f"メールメニュー中に切断されました ({login_id})")
            break

        try:
            # Enter キー (\r または \n) を判定
            if data == b'\r' or data == b'\n':
                char = '\r'
            else:
                # それ以外のキーはASCIIデコードを試みる
                char = data.decode('ascii').lower()
        except UnicodeDecodeError:
            # ASCIIデコードできない文字は無視 (ベルを鳴らす)
            chan.send('\a')
            continue
        except Exception as e:
            logging.error(f"メールメニュー入力処理エラー ({login_id}): {e}")
            continue  # エラーが発生してもループを続ける

        # --- 入力処理 ---
        if char == 'j':  # 次へ (古い方へ、インデックス増)
            if mails and current_index < len(mails) - 1:
                current_index += 1
                display_mail_header(chan, mails[current_index], dbname)
            else:
                chan.send('\a')  # ビープ音 (移動できない)
        elif char == 'k':  # 前へ (新しい方へ、インデックス減)
            if mails and current_index > 0:
                current_index -= 1
                display_mail_header(chan, mails[current_index], dbname)
            else:
                chan.send('\a')  # ビープ音
        elif char == '\r':  # Enter (メールを読む)
            if mails:
                selected_mail_id = mails[current_index]['id']
                # 本文表示 (成功フラグ, 既読変更フラグ を受け取る)
                success, marked_as_read = display_mail_content(
                    chan, selected_mail_id, dbname)

                if success:
                    # 既読状態が変わった場合、メモリ上のリストも更新 (is_read カラムが存在する前提)
                    if marked_as_read and 'is_read' in mails[current_index]:
                        try:
                            # sqlite3.Row は直接変更できない場合があるため、辞書に変換して更新するか、
                            # もしくは再読み込みする方が安全かもしれない。
                            # ここでは簡易的に無視する or 例外処理
                            # mails[current_index]['is_read'] = 1 # これはエラーになる可能性
                            pass  # 既読フラグのメモリ上更新は一旦スキップ
                        except Exception as e:
                            logging.warning(f"メモリ上の既読フラグ更新中にエラー: {e}")

                    # 本文表示後、次のメールへ移動 (リストの範囲内なら)
                    if current_index < len(mails) - 1:
                        current_index += 1
                    # 次のメールヘッダを表示 (リストが空でなければ)
                    if mails:
                        display_mail_header(chan, mails[current_index], dbname)
                    else:  # メールが削除などでなくなった場合
                        chan.send("メールがありません。\r\n")

                else:
                    # 本文表示失敗時も、現在のヘッダを再表示しておく (リストが空でなければ)
                    if mails:
                        display_mail_header(chan, mails[current_index], dbname)
                    else:
                        chan.send("メールがありません。\r\n")
            else:
                chan.send("読むメールがありません。\r\n")
                # プロンプト表示のためにループを続ける
        elif char == 'w':  # メールを書く
            # mail_write を呼び出す前に改行を入れておく
            chan.send("\r\n")
            mail_write(chan, dbname, login_id)
            # 書き終わったらリストを再読み込みして最新を表示
            reload_mails()
        elif char == '?' or char == 'h':  # ヘルプ
            chan.send("\r\n")  # ヘルプ表示前に改行
            util.show_textsfile(chan, "mailmenu.txt")
            # ヘルプ表示後は現在のメールヘッダを再表示 (リストが空でなければ)
            if mails:
                display_mail_header(chan, mails[current_index], dbname)
            else:
                chan.send("受信メールはありません。\r\n")  # メールがない場合
        elif char == 'e':  # 終了
            chan.send("\r\nメールメニューを終了します。\r\n")
            break  # ループを抜ける
        else:
            # その他のキーはベルを鳴らす
            chan.send('\a')

    return  # mail 関数終了


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
        sender_resules = sqlite_tools.fetchall_idbase(
            dbname, 'users', 'name', login_id)
        # 一応念の為
        if not sender_resules:
            chan.send("送信者情報の取得に失敗しました。シスオペに連絡してください\r\n")
            logging.error(f"送信者情報の取得に失敗しました。{login_id}がDBに存在しません。")
            return

        sender_id = sender_resules[0]['id']
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
