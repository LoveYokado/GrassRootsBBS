# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""Webターミナルセッションハンドラモジュール。

このモジュールは、個々のWebターミナルセッションを管理するための中核ロジックを提供します。
WebTerminalHandlerクラスは各クライアントのセッション状態を管理し、BBSのメインループとI/Oを統括します。
また、接続されている全クライアントのグローバルな状態も管理します。
"""

import logging
import threading
import collections
import socket
import codecs
import unicodedata
import time
import re
import datetime

from . import util, command_dispatcher, database, context as ctx

# --- Global State for Web Terminal Clients / Webターミナルクライアントの状態管理 ---

# {sid: WebTerminalHandler_instance}
# 接続中の全クライアントのハンドラインスタンスを保持するグローバル辞書。
client_states = {}

# 現在接続しているWebターミナルクライアントの数を追跡します。
current_webapp_clients = 0
current_webapp_clients_lock = threading.Lock()


# --- Constants for Simulated Baud Rates / 擬似BPSレート用定数 ---
BPS_DELAYS = {
    '300': 10.0 / 300,
    '2400': 10.0 / 2400,
    '4800': 10.0 / 4800,
    '9600': 10.0 / 9600,
    'full': 0,
}


def get_webapp_online_members():
    """
    現在オンラインのWebターミナルユーザーのリストを取得します。

    `client_states` グローバル辞書を走査し、アクティブなセッションの情報を
    辞書として返します。

    Returns: オンラインユーザーの情報を格納した辞書。キーはセッションID。
    """
    members = {}
    for sid, handler in client_states.copy().items():
        user_session = handler.user_session
        if user_session:
            login_id = user_session.get('username')
            if login_id:
                members[sid] = {
                    "sid": sid,
                    "user_id": user_session.get('user_id'),
                    "username": login_id,
                    "display_name": user_session.get('display_name', login_id),
                    "addr": handler.channel.getpeername(),
                    "menu_mode": user_session.get('menu_mode', '?'),
                    "connect_time": handler.connect_time
                }
    return members


def kick_user_session(sid, socketio):
    """
    指定されたセッションIDのユーザーを強制的に切断します。
    主に管理画面からのキック操作で使用されます。

    Args:
        sid (str): 切断するユーザーのセッションID。
        socketio (SocketIO): SocketIOインスタンス。
    """
    if sid in client_states:
        logoff_message_text = util.get_text_by_key(
            "auth.kicked_by_sysop",
            client_states[sid].user_session.get('menu_mode', '2')
        )
        processed_text = logoff_message_text.replace(
            '\r\n', '\n').replace('\n', '\r\n')
        socketio.emit('force_disconnect', {'message': processed_text}, to=sid)
        socketio.close_room(sid)
        logging.info(f"SysOp kicked user with SID: {sid}")
        return True
    return False


class WebTerminalHandler:
    """
    単一のWebターミナルセッションの状態とロジックを管理するクラス。

    接続されたクライアントごとにインスタンスが生成されます。BBSのメインループを
    バックグラウンドタスクとして実行し、クライアントとのI/Oを仲介します。

    Attributes:
        sid (str): SocketIOのセッションID。
        user_session (dict): ユーザーのセッション情報。
    """

    def __init__(self, app, sid, user_session, ip_address, socketio):
        self.sid = sid
        self.user_session = user_session
        self.ip_address = ip_address
        self.socketio = socketio
        self.speed = 'full'
        self.app = app  # Flaskアプリケーションインスタンスを保持
        self.bps_delay = 0
        self.output_queue = collections.deque()
        self.input_queue = collections.deque()
        self.input_event = threading.Event()
        self.stop_worker_event = threading.Event()
        self.is_logging = False
        self.connect_time = time.time()
        self.log_buffer = []
        self.mail_notified_this_session = False
        self.main_thread_active = True
        self.pending_upload = None  # プラグインからのファイルアップロード結果を一時的に保持
        self.pending_upload_settings = None  # プラグインからのファイルアップロード設定を一時的に保持
        self.pending_attachment = None  # 掲示板投稿時の添付ファイル情報を一時的に保持
        self.is_mobile = self.user_session.get('menu_mode') == '4'

        # クライアントのUIを制御するためのカスタムエスケープシーケンスのパターン。
        # これらのシーケンスはBPS遅延の影響を受けずに一括で送信する必要があります。
        self.control_sequence_pattern = re.compile(
            r'('
            r'\x1b\]GRBBS;[^\x07]*\x07'  # OSC: LINE_EDITなど
            r'|\x1b_GRBBS_DOWNLOAD;[^\x1b]*\x1b\\'  # APC: ファイルダウンロード
            r'|\x1b\[\?\d+[hl]'  # DEC Private Mode: UIボタンの表示/非表示
            r')'
        )
        self.channel = self.WebChannel(self, self.ip_address)
        self.socketio.start_background_task(self._sender_worker)
        self.socketio.start_background_task(self._bbs_main_loop)

        @self.socketio.on('get_bbs_list')
        def handle_get_bbs_list():
            """クライアントのBBSリストポップアップ(F7キー)からのデータ要求を処理します。"""
            if not self.user_session.get('user_id'):
                return  # 未認証の場合は何もしない

            try:
                links = database.get_bbs_links()
                self.socketio.emit('bbs_list_data', {'links': links})
            except Exception as e:
                logging.error(f"BBSリストの取得中にエラーが発生しました: {e}", exc_info=True)
                self.socketio.emit('bbs_list_data', {
                                   'links': [], 'error': 'Could not retrieve BBS list.'})

        @self.socketio.on('submit_bbs_link')
        def handle_submit_bbs_link(data):
            """クライアントのBBSリストポップアップからの新規リンク申請を処理し、DBに保存します。"""
            user_id = self.user_session.get('user_id')
            if not user_id:
                return

            name = data.get('name')
            url = data.get('url')
            description = data.get('description', '')

            if not name or not url:
                self.socketio.emit('bbs_link_submission_result', {
                                   'success': False, 'message': 'Name and URL are required.'})
                return

            if database.add_bbs_link(name, url, description, source='user', submitted_by=user_id):
                self.socketio.emit(
                    'bbs_link_submission_result', {'success': True})
            else:
                self.socketio.emit('bbs_link_submission_result', {
                                   'success': False, 'message': 'Failed to submit link. URL might already exist.'})

    class WebChannel:
        """
        WebTerminalHandlerとBBSコアロジック間の通信を仲介する内部クラス。

        従来のソケット通信を模倣したインターフェース (`send`, `recv`など) を提供し、
        BBSの既存ロジックをWebSocket上で再利用可能にします。
        """

        def __init__(self, handler_instance, ip_addr):
            self.handler = handler_instance
            self.ip_address = ip_addr
            self.recv_buffer = b''
            self.active = True
            self._timeout = None

        def settimeout(self, timeout):
            self._timeout = timeout

        def send(self, data):
            if isinstance(data, bytes):  # バイト列の場合はUTF-8でデコード
                text_to_send = data.decode('utf-8', 'ignore')
            else:
                text_to_send = str(data)
            if self.handler.is_logging:
                self.handler.log_buffer.append(text_to_send)
            self.handler.output_queue.append(text_to_send)

        def recv(self, n):
            while len(self.recv_buffer) < n and self.active:
                if not self.handler.input_queue:
                    if not self.handler.input_event.wait(timeout=None):
                        raise socket.timeout("timed out")
                    self.handler.input_event.clear()
                    if not self.active:
                        break
                try:
                    data_str = self.handler.input_queue.popleft()
                    self.recv_buffer += data_str.encode('utf-8')
                except IndexError:
                    continue
            if not self.active and not self.recv_buffer:
                return b''
            ret = self.recv_buffer[:n]
            self.recv_buffer = self.recv_buffer[n:]
            return ret

        def getpeername(self):
            return (self.ip_address, 12345)

        def close(self):
            self.active = False
            self.handler.input_event.set()

        def _process_input_internal(self, echo=True):
            line_buffer = []
            decoder = codecs.getincrementaldecoder('utf-8')('ignore')
            try:
                while self.active:
                    char_byte = self.recv(1)
                    if not char_byte:
                        return None
                    if char_byte in (b'\r', b'\n'):
                        if echo:  # エコーバックが有効なら改行を送信
                            self.send(b'\r\n')
                        break
                    elif char_byte in (b'\x08', b'\x7f'):  # バックスペース処理
                        if line_buffer:
                            deleted_char = line_buffer.pop()
                            if echo:  # エコーバックが有効なら文字を削除
                                width = unicodedata.east_asian_width(
                                    deleted_char)
                                char_width = 2 if width in (
                                    'F', 'W', 'A') else 1
                                backspaces = b'\x08' * char_width
                                self.send(
                                    backspaces + (b' ' * char_width) + backspaces)
                    else:
                        try:  # UTF-8としてデコードを試みる
                            decoded_char = decoder.decode(char_byte)
                            if decoded_char:
                                line_buffer.append(decoded_char)
                                if echo:  # エコーバックが有効なら文字を送信
                                    self.send(decoded_char.encode('utf-8'))
                        except UnicodeDecodeError:
                            decoder.reset()
                            continue
            except socket.timeout:
                logging.info(
                    f"Input timeout (normal operation) (SID: {self.handler.sid})")
            except Exception as e:
                logging.error(
                    f"Error in process_input (SID: {self.handler.sid}): {e}")
                return None
            remaining = decoder.decode(b'', final=True)  # バッファに残っている文字をデコード
            if remaining:
                line_buffer.append(remaining)
            return "".join(line_buffer)

        def process_input(self):
            """
            クライアントからの入力を一行受け取ります (エコーバックあり)。

            Returns:
                str: ユーザーが入力した文字列。
            """
            return self._process_input_internal(echo=True)

        def hide_process_input(self):
            return self._process_input_internal(echo=False)

        def process_multiline_input(self):
            """
            Webクライアントのマルチラインエディタを起動し、その入力を待ち受けます。

            サーバーから特殊シーケンスを送信してエディタを開き、クライアントは
            `multiline_input_submit` イベントで結果を返します。
            """
            self.send(b'\x1b[?2034h')  # マルチラインエディタを開くシーケンスを送信
            # 5分間のタイムアウトを設定
            if not self.handler.input_event.wait(timeout=300):
                self.send(
                    b'\r\n\x1b[31m[Error] Input timed out.\x1b[0m\r\n')
                return None
            self.handler.input_event.clear()
            # 全文が入力キューに入っている
            return self.handler.input_queue.popleft()

    def stop_worker(self):
        self.main_thread_active = False
        self.channel.close()
        self.stop_worker_event.set()

    def _bbs_main_loop(self):
        """
        BBSのメインループ。

        ユーザー認証後のメインメニュー表示とコマンド処理を担当するバックグラウンドタスクです。
        """
        server_pref_dict = {}
        try:
            server_pref_dict = database.read_server_pref()
            if not server_pref_dict:
                logging.error(
                    f"Server config read error. Using defaults. (User: {self.user_session.get('username')})")
                server_pref_dict = {}

            last_login_time = self.user_session.get('lastlogin', 0)
            last_login_str = "なし"
            if last_login_time and last_login_time > 0:
                try:
                    last_login_str = datetime.datetime.fromtimestamp(
                        last_login_time).strftime('%Y-%m-%d %H:%M:%S')
                except (OSError, TypeError, ValueError):
                    last_login_str = "不明な日時"

            util.send_text_by_key(self.channel, "login.welcome_message_webapp", self.user_session.get(
                'menu_mode', '2'), login_id=self.user_session.get('username'), last_login_str=last_login_str)
            util.send_top_menu(
                self.channel, self.user_session.get('menu_mode', '2'))

            while self.main_thread_active:
                server_pref_dict, _ = util.prompt_handler(self.channel, self.user_session.get(
                    'username'), self.user_session.get('menu_mode', '2'))

                context = ctx.CommandContext(
                    self.channel, self.user_session, server_pref_dict, get_webapp_online_members, self.app)

                util.send_text_by_key(
                    self.channel, "prompt.topmenu", context.menu_mode, add_newline=False)
                command = self.channel.process_input()
                if command is None:
                    self.main_thread_active = False
                    break  # 接続が切れたらループを抜ける
                # contextオブジェクトを直接渡すように修正
                if util.handle_shortcut(context, command):
                    util.send_top_menu(self.channel, context.menu_mode)
                    continue
                command = command.strip().lower()
                # 空のコマンドでもショートカット処理を通す（;のみの入力など）
                if not command and not util.handle_shortcut(context, command):
                    util.send_top_menu(self.channel, context.menu_mode)
                    continue
                result = command_dispatcher.dispatch_command(
                    command, context, self.app)
                if result.get('status') == 'logoff':
                    logoff_message_text = util.get_text_by_key(  # ログオフメッセージを取得
                        "logoff.message", context.menu_mode)
                    processed_text = logoff_message_text.replace(
                        '\r\n', '\n').replace('\n', '\r\n')
                    self.main_thread_active = False
                    self.socketio.emit('force_disconnect', {
                                       'message': processed_text}, to=self.sid)
                    break
                if 'new_menu_mode' in result:  # メニューモードが変更された場合
                    context.menu_mode = result['new_menu_mode']
                    util.send_top_menu(
                        self.channel, self.user_session['menu_mode'])
        except Exception as e:
            logging.error(
                f"BBS main loop error ({self.user_session.get('username')}): {e}", exc_info=True)
        finally:
            self.stop_worker()
            logging.info(
                f"BBS main loop finished ({self.user_session.get('username')})")

    def _sender_worker(self):
        """
        出力キューからテキストを送信するバックグラウンドタスク。

        キューからテキストを取り出し、クライアントに送信します。
        BPSレートをシミュレートするための遅延処理もここで行います。
        """
        while not self.stop_worker_event.is_set():
            try:
                text_to_send = self.output_queue.popleft()

                # テキストを制御シーケンスと通常のテキストに分割します。
                parts = self.control_sequence_pattern.split(text_to_send)

                for part in parts:
                    if not part:
                        continue

                    # partが制御シーケンスと完全に一致するかチェックします。
                    if self.control_sequence_pattern.fullmatch(part):
                        # 制御シーケンスは遅延なしで即時送信
                        self.socketio.emit('server_output', part, to=self.sid)
                    else:
                        # 通常のテキストはBPS設定に従って送信
                        if self.bps_delay > 0:
                            for char in part:
                                if self.stop_worker_event.is_set():
                                    break
                                self.socketio.emit(
                                    'server_output', char, to=self.sid)
                                self.socketio.sleep(self.bps_delay)
                        else:
                            self.socketio.emit(
                                'server_output', part, to=self.sid)
            except IndexError:
                self.socketio.sleep(0.01)  # キューが空の場合は少し待機します。
