# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""メールハンドラ。

このモジュールは、内部メールシステムのユーザーインターフェースとロジックを提供します。
`MailViewer` クラスによる対話的なメール一覧表示（受信箱/送信箱、閲覧、削除）や、
宛先・件名・本文を対話的に入力してメールを送信する機能を含みます。
モバイルクライアント向けに、マルチラインエディタや確認ボタンの表示にも対応しています。
"""

import datetime
import time
import logging
import socket
import textwrap
import base64
import json

from . import util
from . import database, terminal_handler


def format_mail_header_str(mail_data, view_mode, mail_id_width=5):  # noqa
    """指定されたメールデータのヘッダ情報（1行）を、整形された文字列として返します。

    Args:
        mail_data (dict): メール一件分のデータ。
        view_mode (str): 'inbox' または 'outbox'。
        mail_id_width (int): メールIDを表示する際の桁数。

    Returns:
        str: 整形されたメールヘッダ文字列。
    """
    if not mail_data:
        return ""

    # --- カラム幅の定義 ---
    # 送信者/受信者: 21文字, 件名: 31文字
    # ターミナルの横幅(約80文字)に合わせて調整します。
    SENDER_RCPT_WIDTH = 14
    SUBJECT_WIDTH = 38

    mail_id = mail_data['id']
    date_str = util.format_timestamp(
        mail_data.get('sent_at'), date_format='%y-%m-%d %H:%M:%S', default_str="---/--/-- --:--:--")

    subject = mail_data['subject'] if mail_data['subject'] else "(無題)"
    mail_id_str = f"{mail_id:0{mail_id_width}d}"

    # --- 状態マークと最終的な件名を決定 ---
    status_mark_char = " "
    display_subject_final = ""
    is_mail_deleted_flag = False

    try:
        if view_mode == 'inbox' and mail_data['recipient_deleted'] == 1:
            is_mail_deleted_flag = True
        elif view_mode == 'outbox' and mail_data['sender_deleted'] == 1:
            is_mail_deleted_flag = True

        if is_mail_deleted_flag:
            status_mark_char = "*"
            display_subject_final = ""  # 削除済みメールには件名を表示しない
        else:
            if view_mode == 'inbox' and mail_data['is_read'] == 0:
                status_mark_char = "#"
            display_subject_final = subject
    except KeyError as e:
        logging.warning(f"メールヘッダ表示中にキーエラー ({mail_id}): {e}")
        display_subject_final = subject

    # --- 送信者名/受信者名を決定 ---
    display_name = ""
    if view_mode == 'inbox':
        sender_name_raw = mail_data.get('sender_name')
        if sender_name_raw and sender_name_raw.upper() == 'GUEST' and mail_data.get('sender_ip_address'):
            display_name = util.get_display_name(
                'GUEST', mail_data['sender_ip_address'])
        else:
            display_name = sender_name_raw if sender_name_raw else "(不明)"
    else:  # 送信箱の場合
        recipient_name = mail_data.get('recipient_name')
        display_name = recipient_name if recipient_name else "(不明)"

    # カラム幅に合わせて名前を短縮
    display_name_final = util.shorten_text_by_slicing(
        display_name, width=SENDER_RCPT_WIDTH)

    # 名前と状態マークの間はスペース1つ
    return f"{mail_id_str}  {date_str}  {display_name_final:<{SENDER_RCPT_WIDTH}} {status_mark_char}{display_subject_final}"


class MailViewer:
    """
    メール一覧の表示と、その中での対話的な操作を管理するクラス。

    ユーザーが 'l' コマンドで一覧表示を選択した際にインスタンス化されます。
    受信箱と送信箱の表示切り替え、カーソル移動、メールの閲覧・削除などを行います。
    """

    def __init__(self, chan, login_id, menu_mode, user_id):
        self.chan = chan
        self.login_id = login_id
        self.menu_mode = menu_mode
        self.user_id = user_id

        # --- インスタンスの状態管理 ---
        self.view_mode = 'inbox'  # 'inbox' (受信箱) または 'outbox' (送信箱)
        self.mails = []
        self.current_index = 0
        self.mail_count_digits = 5

        # --- キー入力とメソッドのディスパッチテーブル ---
        self.key_dispatch = {
            '\x05': self._move_cursor_up, 'k': self._move_cursor_up, 'K': self._move_cursor_up, "KEY_UP": self._move_cursor_up,
            '\x18': self._move_cursor_down, 'j': self._move_cursor_down, 'J': self._move_cursor_down, ' ': self._move_cursor_down, "KEY_DOWN": self._move_cursor_down,
            '\x04': self._read_selected_mail_and_stay, '\r': self._read_selected_mail_and_stay,
            '\x12': self._read_and_move_up, 'h': self._read_and_move_up, 'H': self._read_and_move_up, "KEY_LEFT": self._read_and_move_up,
            '\x06': self._read_and_move_down, 'l': self._read_and_move_down, 'L': self._read_and_move_down, "KEY_RIGHT": self._read_and_move_down, '\t': self._read_and_move_down,
            '*': self._toggle_delete,
            'w': self._write_mail, 'W': self._write_mail,
            's': self._switch_view_mode, 'S': self._switch_view_mode,
            'r': self._read_all_from_current, 'R': self._read_all_from_current,
            't': self._display_title_list, 'T': self._display_title_list,
            '?': self._display_help,
        }

    def _display_mail_header_line(self, mail_data):
        """指定されたメールデータ一件のヘッダ情報（1行）を整形して表示します。"""
        header_line = format_mail_header_str(
            mail_data, self.view_mode, self.mail_count_digits)
        if header_line:
            self.chan.send(header_line.encode('utf-8') + b"\r\n")

    def _display_current_header(self):
        """現在のカーソル位置 (`current_index`) に対応するメールヘッダまたはマーカーを表示します。"""
        if self.current_index == -1:
            marker_id_str = "0" * self.mail_count_digits
            self.chan.send(f"{marker_id_str} v\r\n".encode('utf-8'))
        elif self.current_index == len(self.mails):
            if not self.mails:
                util.send_text_by_key(
                    self.chan, "mail_handler.no_mails", self.menu_mode)
            else:
                marker_num = len(self.mails) + 1
                marker_id_str = f"{marker_num:0{self.mail_count_digits}d}"
                self.chan.send(f"{marker_id_str} ^\r\n".encode('utf-8'))
        elif self.mails and 0 <= self.current_index < len(self.mails):
            self._display_mail_header_line(self.mails[self.current_index])
        else:
            self.chan.send("メールがありません。\r\n".encode('utf-8'))

    def _reload_mails(self, keep_index=True):
        """データベースからメールリストを再読み込みし、表示を更新します。"""
        current_mail_id = None
        if self.mails and 0 <= self.current_index < len(self.mails):
            current_mail_id = self.mails[self.current_index]['id']

        try:
            fetched_mails = database.get_mails_for_view(
                self.user_id, self.view_mode)
            self.mails = fetched_mails if fetched_mails else []

            new_index = 0
            if self.mails:
                if keep_index and current_mail_id is not None:
                    found_index = next((i for i, mail in enumerate(
                        self.mails) if mail['id'] == current_mail_id), -1)
                    if found_index != -1:
                        new_index = found_index
                else:
                    # keep_index=False の場合、未読メールにフォーカス
                    if self.view_mode == 'inbox':
                        # 最初の未読メールを探す
                        first_unread_index = next((i for i, mail in enumerate(self.mails)
                                                   if mail['is_read'] == 0 and mail['recipient_deleted'] == 0), -1)
                        if first_unread_index != -1:
                            new_index = first_unread_index
                        else:
                            # 未読がなければ最終メールにフォーカス
                            new_index = len(self.mails) - 1
                    else:  # 送信箱の場合
                        new_index = len(self.mails) - 1
                self.mail_count_digits = max(5, len(str(len(self.mails) + 1)))
            else:
                self.mail_count_digits = 5

            self.current_index = new_index if new_index >= 0 else 0
            return True
        except Exception as e:
            logging.error(
                f"メール一覧取得中にDBエラー (ユーザーID: {self.user_id}, Mode:{self.view_mode}): {e}")
            self.chan.send("\r\nメール一覧の取得中にエラーが発生しました。\r\n".encode('utf-8'))
            self.mails = []
            self.current_index = 0
            return False

    def _get_key_input(self):
        """チャンネルから1キー入力を取得し、特殊キーを解釈して統一された文字列として返します。"""
        try:
            data = self.chan.recv(1)
            if not data:
                logging.info(  # ログ
                    f"メールメニュー中にクライアントが切断されました。 (ユーザーID: {self.user_id})")
                return None

            if data == b'\x1b':  # ESC - 矢印キーの可能性
                self.chan.settimeout(0.05)
                try:
                    nextbyte1 = self.chan.recv(1)
                    if nextbyte1 == b'[':
                        nextbyte2 = self.chan.recv(1)
                        if nextbyte2 == b'A':
                            return "KEY_UP"
                        if nextbyte2 == b'B':
                            return "KEY_DOWN"
                        if nextbyte2 == b'C':
                            return "KEY_RIGHT"
                        if nextbyte2 == b'D':
                            return "KEY_LEFT"
                    return data.decode('ascii')  # ESC単体
                except socket.timeout:  # タイムアウト
                    return data.decode('ascii')  # ESC単体
                finally:
                    self.chan.settimeout(None)
            else:
                return data.decode('ascii')
        except (socket.error, UnicodeDecodeError, EOFError) as e:
            logging.error(f"メールメニュー中にソケット受信エラー (ユーザーID: {self.user_id}): {e}")
            return None

    def run(self):
        """メールビューアのメインループを開始し、ユーザーからのキー入力を処理します。"""
        # モバイル用の操作ボタンを表示
        self.chan.send(b'\x1b[?2024h')

        total_mail_count = database.get_total_mail_count(self.user_id)  # noqa
        unread_mail_count = database.get_total_unread_mail_count(self.user_id)
        util.send_text_by_key(
            self.chan, "mail_handler.article_list_count", self.menu_mode,
            total_count=total_mail_count, unread_count=unread_mail_count
        )

        if not self._reload_mails(keep_index=False):
            self.chan.send(b'\x1b[?2024l')  # エラー時も非表示にする
            return "back_to_top"  # トップメニューに戻る

        # ヘッダ表示
        if self.view_mode == 'inbox':
            util.send_text_by_key(
                self.chan, "mail_handler.sender_header", self.menu_mode)
        else:
            util.send_text_by_key(
                self.chan, "mail_handler.recipient_header", self.menu_mode)
        self._display_current_header()

        try:
            while True:
                key_input = self._get_key_input()
                if key_input is None:
                    return None  # 切断
                # Ctrl+C, ESC, e, E
                if key_input in ('e', 'E', '\x03', '\x1b'):  # Ctrl+C, ESC, e, E
                    break

                handler = self.key_dispatch.get(key_input)
                if handler:
                    handler()
                else:
                    self.chan.send(b'\a')
        finally:
            # ループを抜けるときに必ずパネルを非表示にする
            self.chan.send(b'\x1b[?2024l')

        return "back_to_top"

    def _move_cursor_up(self):
        """カーソルを一つ上に移動し、移動先のヘッダを表示します。"""
        if not self.mails:
            self.chan.send(b'\a')
            return
        if self.current_index > -1:
            self.current_index -= 1
            self._display_current_header()
        else:
            self.chan.send(b'\a')

    def _move_cursor_down(self):
        """カーソルを一つ下に移動し、移動先のヘッダを表示します。"""
        if not self.mails:
            self.chan.send(b'\a')
            return
        if self.current_index < len(self.mails):
            self.current_index += 1
            self._display_current_header()
        else:
            self.chan.send(b'\a')

    def _read_selected_mail(self, advance_cursor_after=False):
        """現在カーソルがあるメールを読み込み、必要に応じてカーソルを進めます。"""
        if not (self.mails and 0 <= self.current_index < len(self.mails)):
            self.chan.send(b'\a')
            return

        selected_mail_data = self.mails[self.current_index]

        is_deleted = False
        try:
            if self.view_mode == 'inbox' and selected_mail_data['recipient_deleted'] == 1:
                is_deleted = True
            elif self.view_mode == 'outbox' and selected_mail_data['sender_deleted'] == 1:
                is_deleted = True
        except KeyError:
            logging.warning(
                f"メールデータに削除フラグが見つかりません(MailID: {selected_mail_id})")

        if is_deleted:
            util.send_text_by_key(
                self.chan, "mail_handler.mail_deleted", self.menu_mode)
        else:
            # 本文表示
            success, _ = display_mail_content(
                self.chan, selected_mail_data, self.user_id, self.view_mode, self.menu_mode)
            if not success:
                util.send_text_by_key(
                    self.chan, "common_messages.error", self.menu_mode)

        # メールリストを再読み込み（既読状態の更新などを反映）
        self._reload_mails(keep_index=True)

        if advance_cursor_after:
            if self.mails:
                self.current_index += 1

        # ヘッダ表示
        if self.view_mode == 'inbox':
            util.send_text_by_key(
                self.chan, "mail_handler.sender_header", self.menu_mode)
        else:
            util.send_text_by_key(
                self.chan, "mail_handler.recipient_header", self.menu_mode)
        self._display_current_header()

    def _read_selected_mail_and_stay(self):
        """選択されているメールを読み込みます（カーソル位置は変更しない）。"""
        self._read_selected_mail(advance_cursor_after=False)

    def _read_and_move_down(self):
        """選択されているメールを読み込み、カーソルを一つ下に進めます。"""
        self._read_selected_mail(advance_cursor_after=True)

    def _read_and_move_up(self):
        """カーソルを一つ上に移動し、その位置のメールを読み込みます（読み戻り）。"""
        if not self.mails:
            self.chan.send(b'\a')
            return
        if self.current_index > 0:
            self.current_index -= 1
            self._read_selected_mail(advance_cursor_after=False)
        else:
            self.chan.send(b'\a')

    def _toggle_delete(self):
        """選択されているメールの削除状態（論理削除）を切り替えます。"""
        if not (self.mails and 0 <= self.current_index < len(self.mails)):
            self.chan.send(b'\a')
            return

        selected_mail_id = self.mails[self.current_index]['id']
        mode_for_toggle = 'recipient' if self.view_mode == 'inbox' else 'sender'

        toggled, _ = database.toggle_mail_delete_status_generic(
            selected_mail_id, self.user_id, mode_param=mode_for_toggle)

        if toggled:
            self._reload_mails(keep_index=True)
            self._display_current_header()
        else:
            util.send_text_by_key(
                self.chan, "mail_handler.toggle_delete_status_failed", self.menu_mode)
            self._display_current_header()

    def _switch_view_mode(self):
        """受信箱 (inbox) と送信箱 (outbox) の表示を切り替えます。"""
        self.view_mode = 'outbox' if self.view_mode == 'inbox' else 'inbox'
        self._reload_mails(keep_index=False)
        # ヘッダ表示
        if self.view_mode == 'inbox':
            util.send_text_by_key(
                self.chan, "mail_handler.sender_header", self.menu_mode)
        else:
            util.send_text_by_key(
                self.chan, "mail_handler.recipient_header", self.menu_mode)
        self._display_current_header()

    def _write_mail(self):
        """メール作成画面を呼び出し、完了後に一覧をリロードします。"""
        self.chan.send(b'\r\n')
        mail_write(self.chan, self.login_id, self.menu_mode)
        self._reload_mails(keep_index=False)
        # ヘッダ表示
        if self.view_mode == 'inbox':
            util.send_text_by_key(
                self.chan, "mail_handler.sender_header", self.menu_mode)
        else:
            util.send_text_by_key(
                self.chan, "mail_handler.recipient_header", self.menu_mode)
        self._display_current_header()

    def _read_all_from_current(self):
        """現在カーソルがある位置から、リストの最後までメールを連続で表示します。"""
        if not self.mails or self.current_index == len(self.mails):
            self.chan.send(b'\a')
            return

        start_idx = self.current_index if self.current_index != -1 else 0
        self.chan.send(b'\r\n')

        if self.view_mode == 'inbox':
            util.send_text_by_key(
                self.chan, "mail_handler.sender_header", self.menu_mode)
        else:
            util.send_text_by_key(
                self.chan, "mail_handler.recipient_header", self.menu_mode)

        for i in range(start_idx, len(self.mails)):
            self.current_index = i
            self._display_mail_header_line(self.mails[i])
            self._read_selected_mail(advance_cursor_after=False)  # 本文表示
            self.chan.send(b'\r\n')

        self.current_index = len(self.mails)
        self._display_current_header()

    def _display_title_list(self):
        """現在カーソルがある位置から、リストの最後までメールのヘッダのみを一覧表示します。"""
        if not self.mails or self.current_index == len(self.mails):
            self.chan.send(b'\a')
            return

        start_idx = self.current_index if self.current_index != -1 else 0
        self.chan.send(b'\r\n')

        if self.view_mode == 'inbox':
            util.send_text_by_key(
                self.chan, "mail_handler.sender_header", self.menu_mode)
        else:
            util.send_text_by_key(
                self.chan, "mail_handler.recipient_header", self.menu_mode)

        for i in range(start_idx, len(self.mails)):
            self._display_mail_header_line(self.mails[i])

        self.current_index = len(self.mails)
        self._display_current_header()

    def _display_help(self):
        """メールビューアの操作ヘルプを表示します。"""
        self.chan.send(b'\r\n')
        util.send_text_by_key(
            self.chan, "mail_handler.mail_help", self.menu_mode)
        # ヘルプ表示後に現在の行を再表示
        if self.view_mode == 'inbox':
            util.send_text_by_key(
                self.chan, "mail_handler.sender_header", self.menu_mode)
        else:
            util.send_text_by_key(
                self.chan, "mail_handler.recipient_header", self.menu_mode)
        self._display_current_header()


def mail(chan, login_id, menu_mode, ip_address):
    """メール機能のメインエントリーポイント。書き込み、受信、一覧表示のメニューを提供します。"""
    user_id = database.get_user_id_from_user_name(login_id)
    if user_id is None:
        util.send_text_by_key(
            chan, "common_messages.user_not_found", menu_mode
        )  # ユーザー情報が見つかりません。
        return "back_to_top"

    # モバイル用の操作ボタンを表示
    chan.send(b'\x1b[?2029h')
    try:
        # メールメニュー
        while True:
            # 選択してください([W]送信 [R]受信 [L]一覧形式受信)
            util.send_text_by_key(
                chan, "mail_handler.main_prompt", menu_mode, add_newline=False)
            choice_input = chan.process_input()
            if choice_input is None:
                return None  # 切断
            choice = choice_input.lower().strip()

            if choice == 'l':
                chan.send(b'\x1b[?2029l')  # メインのメールボタンを非表示
                viewer = MailViewer(chan, login_id, menu_mode, user_id)
                result = viewer.run()
                chan.send(b'\x1b[?2029h')  # メインのメールボタンを再表示
                if result == "back_to_top":
                    continue
                else:
                    return result  # 切断など
            elif choice == 'w':
                chan.send(b'\x1b[?2029l')  # メインのメールボタンを非表示
                mail_write(chan, login_id, menu_mode, ip_address)
                chan.send(b'\x1b[?2029h')  # メインのメールボタンを再表示
                continue
            elif choice == 'r':
                # 1.初回に新着メールの総数未読数表示
                unread_count_initial = database.get_total_unread_mail_count(
                    user_id)
                total_mail_count_initial = database.get_total_mail_count(
                    user_id)

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
                    oldest_unread_mail = database.get_oldest_unread_mail(
                        user_id)

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
                                        'inbox', mail_id_width_for_reader)

                    # 読み込み選択(y/n)
                    util.send_text_by_key(
                        chan, "mail_handler.confirm_read_body_yn", menu_mode, add_newline=False)
                    read_choice_input = chan.process_input()
                    if read_choice_input is None:
                        return "back_to_top"
                    read_choice = read_choice_input.strip().lower()

                    if read_choice == 'y':
                        # 本文表示と既読化
                        success, _ = display_mail_content(
                            chan, oldest_unread_mail, user_id, 'inbox', menu_mode)
                        if not success:
                            util.send_text_by_key(
                                chan, "common_messages.error", menu_mode)
                            break
                        chan.send(b'\r\n')

                        # 削除確認(y/n)
                        util.send_text_by_key(
                            chan, "mail_handler.confirm_delete_after_read_yn", menu_mode, add_newline=False)
                        delete_choice_input = chan.process_input()
                        if delete_choice_input is None:
                            return "back_to_top"
                        delete_choice = delete_choice_input.strip().lower()

                        if delete_choice == 'y':
                            toggled, new_status = database.toggle_mail_delete_status_generic(
                                oldest_unread_mail['id'], user_id, 'recipient')
                            if toggled and new_status == 1:  # 削除された場合
                                util.send_text_by_key(
                                    chan, "mail_handler.mail_deleted_after_read_success", menu_mode)
                            elif not toggled:
                                util.send_text_by_key(
                                    chan, "mail_handler.toggle_delete_status_failed", menu_mode)
                    elif read_choice == 'n':
                        database.mark_mail_as_read(
                            oldest_unread_mail['id'], user_id)
                    else:
                        break
                continue  # メインのメールメニュープロンプトに戻る
            elif choice == '' or choice == 'e':
                return "back_to_top"
            else:
                util.send_text_by_key(
                    chan, "common_messages.invalid_command", menu_mode)
    finally:
        # メニューを抜けたら必ずボタンを非表示にする
        chan.send(b'\x1b[?2029l')


def display_mail_header(chan, mail_data, view_mode='inbox', mail_id_width=5):
    """指定されたメールデータ一件のヘッダ情報（1行）を整形して表示します。"""
    header_line = format_mail_header_str(mail_data, view_mode, mail_id_width)
    if header_line:
        chan.send((header_line + "\r\n").encode('utf-8'))


def display_mail_content(chan, mail_data, recipient_user_id_pk, view_mode='inbox', menu_mode='2'):
    try:
        if not mail_data:
            util.send_text_by_key(
                chan, "mail_handler.no_mails", menu_mode
            )  # メールが見つかりません
            return False, False

        mail_id = mail_data['id']
        body = mail_data['body'] if mail_data['body'] else "(本文なし)"

        # ユーザーが入力した改行を維持しつつ、長い行を折り返す
        for line in body.splitlines():
            wrapped_lines = textwrap.wrap(
                line,
                width=78,
                replace_whitespace=False,  # 元の空白文字を保持
                drop_whitespace=False      # 行頭・行末の空白を保持
            )
            if not wrapped_lines:  # 元の行が空行だった場合
                chan.send(b'\r\n')
            else:
                for wrapped_line in wrapped_lines:
                    chan.send(wrapped_line.encode('utf-8') + b'\r\n')

        marked_as_read = False
        if view_mode == 'inbox':
            if database.mark_mail_as_read(mail_id, recipient_user_id_pk):
                marked_as_read = True
        return True, marked_as_read

    except Exception as e:
        logging.error(f"メール内容表示中にエラー (ID: {mail_data.get('id', 'N/A')}): {e}")
        return False, False


def _get_recipients(chan, menu_mode):
    """宛先をユーザーから対話的に取得し、検証してリストとして返します。"""
    recipient_info_list = []  # 複数宛先に対応
    is_mobile_web_client = (isinstance(chan, terminal_handler.WebTerminalHandler.WebChannel) and getattr(
        chan.handler, 'is_mobile', False))

    def get_confirm_input(prompt_key):
        """Yes/No確認プロンプトを表示し、ユーザーの入力を取得するヘルパー関数。"""
        confirm_input_raw = None
        if is_mobile_web_client:
            yes_label = util.get_text_by_key(
                "common_messages.yes_button", menu_mode, default_value="Yes")
            no_label = util.get_text_by_key(
                "common_messages.no_button", menu_mode, default_value="No")
            yes_label_b64 = base64.b64encode(
                yes_label.encode('utf-8')).decode('utf-8')
            no_label_b64 = base64.b64encode(
                no_label.encode('utf-8')).decode('utf-8')
            chan.send(
                f'\x1b]GRBBS;CONFIRM_BUTTONS;{yes_label_b64};{no_label_b64}\x07'.encode('utf-8'))
            chan.send(b'\x1b[?2035h')
        try:
            util.send_text_by_key(
                chan, prompt_key, menu_mode, add_newline=False)
            confirm_input_raw = chan.process_input()
        finally:
            if is_mobile_web_client:
                chan.send(b'\x1b[?2035l')
        return confirm_input_raw

    while True:
        recipient_name_input = None
        if is_mobile_web_client:
            all_users = database.get_memberlist()
            if not all_users:
                util.send_text_by_key(
                    chan, "mail_handler.no_users_to_select", menu_mode, default_value="送信可能なユーザーがいません。")
                return []
            prompt_text = util.get_text_by_key(
                "mail_handler.select_recipient_prompt_popup", menu_mode, default_value="宛先を選択してください")
            prompt_b64 = base64.b64encode(
                prompt_text.encode('utf-8')).decode('utf-8')
            user_list_json = json.dumps(all_users)
            user_list_b64 = base64.b64encode(
                user_list_json.encode('utf-8')).decode('utf-8')
            chan.send(
                f'\x1b]GRBBS;USER_SELECT;{prompt_b64};{user_list_b64}\x07'.encode('utf-8'))
            recipient_name_input = chan.process_input()
            if recipient_name_input:
                prompt_display_text = util.get_text_by_key(
                    "mail_handler.enter_recipient", menu_mode)
                chan.send(
                    f"{prompt_display_text}{recipient_name_input}\r\n".encode('utf-8'))
        else:
            util.send_text_by_key(
                chan, "mail_handler.enter_recipient", menu_mode, add_newline=False)
            recipient_name_input = chan.process_input()

        if not recipient_name_input:
            return recipient_info_list if recipient_info_list else []

        recipient_name_upper = recipient_name_input.upper()
        userdata = database.get_user_auth_info(recipient_name_upper)

        if not userdata:
            util.send_text_by_key(chan, "mail_handler.recipient_not_found",
                                  menu_mode, recipient_name=recipient_name_upper)
            continue

        current_recipient_name = userdata['name']
        current_recipient_comment = userdata.get(
            'comment', '') or "(No comment)"
        chan.send(f"\"{current_recipient_comment}\"\r\n".encode('utf-8'))

        ans = get_confirm_input("mail_handler.recipient_yn")
        if ans is None:
            return None

        if ans.lower().strip() == 'y':
            recipient_info_list.append(
                (current_recipient_name, current_recipient_comment))

            add_more_ans = get_confirm_input("mail_handler.send_another_yn")
            if add_more_ans is None:
                return None

            if add_more_ans.lower().strip() == 'y':  # yが入力された場合
                continue
            else:
                return recipient_info_list
        else:
            continue


def _get_subject(chan, menu_mode):
    """件名をユーザーから対話的に取得し、最大長を超えた場合は切り詰めます。"""
    limits_config = util.app_config.get('limits', {})
    mail_subject_max_len = limits_config.get('mail_subject_max_length', 100)

    is_mobile_web_client = (
        isinstance(chan, terminal_handler.WebTerminalHandler.WebChannel) and
        getattr(chan.handler, 'is_mobile', False)
    )

    if is_mobile_web_client:
        prompt_text_template = util.get_text_by_key(
            "mail_handler.enter_subject", menu_mode)
        prompt_text = prompt_text_template.format(max_len=mail_subject_max_len)
        prompt_b64 = base64.b64encode(
            prompt_text.encode('utf-8')).decode('utf-8')
        initial_value_b64 = base64.b64encode(
            b'').decode('utf-8')  # 初期値は空にする
        chan.send(
            f'\x1b]GRBBS;LINE_EDIT;{prompt_b64};{initial_value_b64}\x07'.encode('utf-8'))
        subject_raw = chan.process_input()
        if subject_raw is not None:
            chan.send(f"{prompt_text}{subject_raw}\r\n".encode('utf-8'))
        subject = subject_raw
    else:
        util.send_text_by_key(chan, "mail_handler.enter_subject",
                              menu_mode, add_newline=False, max_len=mail_subject_max_len)
        subject = chan.process_input()

    if subject is None:
        return None

    subject = subject.strip()
    if not subject:
        subject = util.get_text_by_key(
            "mail_handler.no_subject", menu_mode, default_value="(No Subject)")

    if len(subject) > mail_subject_max_len:
        subject = subject[:mail_subject_max_len]
        util.send_text_by_key(
            chan, "mail_handler.subject_truncated", menu_mode, max_len=mail_subject_max_len)
    return subject


def _get_body(chan, menu_mode):
    """本文をユーザーから対話的に取得し、最大長を超えた場合は切り詰めます。"""
    limits_config = util.app_config.get('limits', {})
    mail_body_max_len = limits_config.get('mail_body_max_length', 4096)
    util.send_text_by_key(
        chan, "mail_handler.enter_body", menu_mode, max_len=mail_body_max_len)

    is_mobile_web_client = (
        isinstance(chan, terminal_handler.WebTerminalHandler.WebChannel) and
        getattr(chan.handler, 'is_mobile', False)
    )

    message = ""
    if is_mobile_web_client:
        # モバイルWebクライアントの場合はマルチラインエディタを呼び出す
        body = chan.process_multiline_input()
        if body is None:
            return None  # タイムアウトまたはエラーの場合
        # 入力された内容をターミナルにエコーバック
        chan.send(body.replace('\n', '\r\n').encode('utf-8') + b'\r\n')
        message = body
    else:
        # --- 従来のインラインエディタを使用する場合 ---
        message_lines = []
        while True:
            line = chan.process_input()
            if line is None:
                return None  # 切断
            if line == '^':
                break
            message_lines.append(line)
        message = '\r\n'.join(message_lines)

    if len(message) > mail_body_max_len:
        message = message[:mail_body_max_len]
        util.send_text_by_key(
            chan, "mail_handler.body_truncated", menu_mode, max_len=mail_body_max_len)
    return message


def _save_mails_to_db(sender_id, recipient_info_list, subject, body, ip_address=None):
    """複数の宛先に対して、それぞれメールをデータベースに保存します。"""
    try:
        sent_at = int(time.time())
        for rec_name, _ in recipient_info_list:
            recipient_data = database.get_user_auth_info(rec_name)
            if not recipient_data:
                logging.error(f"送信に失敗、{rec_name}がDBに存在しません。")
                continue
            recipient_id = recipient_data['id']
            query = "INSERT INTO mails (sender_id, recipient_id, subject, body, sent_at, sender_ip_address) VALUES (%s, %s, %s, %s, %s, %s)"
            params = (sender_id, recipient_id, subject,
                      body, sent_at, ip_address)
            database.execute_query(query, params)
        return True
    except Exception as e:
        logging.error(f"メールDB保存中にエラー: {e}")
        return False


def _confirm_and_send(chan, login_id, menu_mode, recipient_info_list, subject, body, ip_address=None):
    """送信内容の最終確認画面を表示し、ユーザーの同意を得てからDBに保存します。"""
    from markupsafe import escape
    util.send_text_by_key(
        chan, "mail_handler.confirm_send", menu_mode)

    # 宛先表示
    for name, comment in recipient_info_list:
        util.send_text_by_key(chan, "mail_handler.recipient", menu_mode,
                              current_recipient_name=name, current_recipient_comment=comment)  # noqa

    util.send_text_by_key(chan, "mail_handler.subject",
                          menu_mode, subject=subject)
    util.send_text_by_key(chan, "mail_handler.body", menu_mode)
    # XSS対策: ユーザーが入力した本文をエスケープしてから表示
    for line in str(escape(body)).splitlines():
        chan.send(f"{line}\r\n".encode('utf-8'))

    is_mobile_web_client = (
        isinstance(chan, terminal_handler.WebTerminalHandler.WebChannel) and
        getattr(chan.handler, 'is_mobile', False)
    )

    confirm_input_raw = None
    if is_mobile_web_client:
        # ローカライズされたボタンラベルを取得
        yes_label = util.get_text_by_key(
            "common_messages.yes_button", menu_mode, default_value="Yes")
        no_label = util.get_text_by_key(
            "common_messages.no_button", menu_mode, default_value="No")
        # Base64エンコード
        yes_label_b64 = base64.b64encode(
            yes_label.encode('utf-8')).decode('utf-8')
        no_label_b64 = base64.b64encode(
            no_label.encode('utf-8')).decode('utf-8')
        # ラベルを設定してボタンを表示するコマンドを送信
        chan.send(
            f'\x1b]GRBBS;CONFIRM_BUTTONS;{yes_label_b64};{no_label_b64}\x07'.encode('utf-8'))
        chan.send(b'\x1b[?2035h')

    try:
        util.send_text_by_key(
            chan, "mail_handler.confirm_send_yn", menu_mode, add_newline=False)
        confirm_input_raw = chan.process_input()
    finally:
        if is_mobile_web_client:
            chan.send(b'\x1b[?2035l')

    if confirm_input_raw is None:
        logging.warning(f"メール送信確認中に切断されました({login_id})")
        return
    confirm_input = confirm_input_raw.strip().lower()

    if confirm_input != 'y':
        util.send_text_by_key(chan, "mail_handler.send_cancelled", menu_mode)
        return
    sender_id = database.get_user_id_from_user_name(login_id)
    if sender_id is None:
        util.send_text_by_key(chan, "common_messages.error", menu_mode)
        logging.error(f"メール送信時に送信者IDが取得できませんでした: {login_id}")
        return

    if _save_mails_to_db(sender_id, recipient_info_list, subject, body, ip_address=ip_address):
        util.send_text_by_key(chan, "mail_handler.send_success", menu_mode)
    else:
        util.send_text_by_key(chan, "common_messages.db_error", menu_mode)


def mail_write(chan, login_id, menu_mode='2', ip_address=None):
    """メール作成のメインハンドラ。宛先、件名、本文の入力を順に受け付け、送信します。"""
    recipient_info_list = _get_recipients(chan, menu_mode)
    if not recipient_info_list:  # キャンセルまたは切断
        return

    subject = _get_subject(chan, menu_mode)
    if subject is None:  # 切断
        return

    body = _get_body(chan, menu_mode)
    if body is None:  # 切断
        return
    if not body.strip():
        util.send_text_by_key(chan, "mail_handler.no_body", menu_mode)
        return

    _confirm_and_send(chan, login_id, menu_mode,
                      recipient_info_list, subject, body, ip_address=ip_address)
