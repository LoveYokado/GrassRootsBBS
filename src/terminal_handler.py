# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

# ==============================================================================
# Web Terminal Session Handler
#
# This module contains the core logic for managing individual web terminal
# sessions. It includes the WebTerminalHandler class, which orchestrates the
# BBS main loop and I/O for a single client, as well as global state management
# for all connected clients.
# ==============================================================================
#
# ==============================================================================
# Webターミナルセッションハンドラ
#
# このモジュールは、個々のWebターミナルセッションを管理するための中核的な
# ロジックを含んでいます。BBSのメインループと単一クライアントのI/Oを統括する
# WebTerminalHandlerクラスや、接続されている全クライアントのグローバルな
# 状態管理が含まれます。
# ==============================================================================

import logging
import threading
import collections
import socket
import codecs
import unicodedata
import time
import re
import datetime

from . import util, command_dispatcher, database

# --- Global State for Web Terminal Clients / Webターミナルクライアントの状態管理 ---
# {sid: WebTerminalHandler_instance} - Maps SocketIO session IDs to handler instances.
client_states = {}

# Tracks the number of currently connected web terminal clients.
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
    """Generates a list of currently online members for the web UI."""
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
    Forcefully disconnects a user session specified by its SID.
    Intended to be called from the admin panel.
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
    Manages the state and logic for a single web terminal session.
    An instance of this class is created for each connected client.
    It orchestrates the BBS main loop and I/O between the client and the server.
    """

    def __init__(self, sid, user_session, ip_address, socketio):
        self.sid = sid
        self.user_session = user_session
        self.ip_address = ip_address
        self.socketio = socketio
        self.speed = 'full'
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
        self.pending_attachment = None
        self.is_mobile = False
        # クライアントのUIを制御するためのカスタムエスケープシーケンスのパターン
        # これらはBPS遅延の影響を受けずに一括で送信する必要がある
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

    class WebChannel:
        def __init__(self, handler_instance, ip_addr):
            self.handler = handler_instance
            self.ip_address = ip_addr
            self.recv_buffer = b''
            self.active = True
            self._timeout = None

        def settimeout(self, timeout):
            self._timeout = timeout

        def send(self, data):
            if isinstance(data, bytes):
                text_to_send = data.decode('utf-8', 'ignore')
            else:
                text_to_send = str(data)
            if self.handler.is_logging:
                self.handler.log_buffer.append(text_to_send)
            self.handler.output_queue.append(text_to_send)

        def recv(self, n):
            while len(self.recv_buffer) < n and self.active:
                if not self.handler.input_queue:
                    if not self.handler.input_event.wait(timeout=self._timeout):
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
                        if echo:
                            self.send(b'\r\n')
                        break
                    elif char_byte in (b'\x08', b'\x7f'):
                        if line_buffer:
                            deleted_char = line_buffer.pop()
                            if echo:
                                width = unicodedata.east_asian_width(
                                    deleted_char)
                                char_width = 2 if width in (
                                    'F', 'W', 'A') else 1
                                backspaces = b'\x08' * char_width
                                self.send(
                                    backspaces + (b' ' * char_width) + backspaces)
                    else:
                        try:
                            decoded_char = decoder.decode(char_byte)
                            if decoded_char:
                                line_buffer.append(decoded_char)
                                if echo:
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
            remaining = decoder.decode(b'', final=True)
            if remaining:
                line_buffer.append(remaining)
            return "".join(line_buffer)

        def process_input(self):
            return self._process_input_internal(echo=True)

        def hide_process_input(self):
            return self._process_input_internal(echo=False)

        def process_multiline_input(self):
            """
            Triggers the multiline editor on the web client and waits for the result.
            Webクライアントのマルチラインエディタを起動し、結果を待ち受けます。
            """
            # Send a special escape sequence to open the multiline editor
            self.send(b'\x1b[?2034h')
            # Wait for the input to be populated by the socket event handler
            # 5分間のタイムアウト
            if not self.handler.input_event.wait(timeout=300):
                self.send(
                    b'\r\n\x1b[31m[Error] Input timed out.\x1b[0m\r\n')
                return None
            self.handler.input_event.clear()
            # The full text is now in the input queue
            return self.handler.input_queue.popleft()

    def _sender_worker(self):
        while not self.stop_worker_event.is_set():
            try:
                text_to_send = self.output_queue.popleft()

                # テキストを制御シーケンスと通常のテキストに分割
                parts = self.control_sequence_pattern.split(text_to_send)

                for part in parts:
                    if not part:
                        continue

                    # partが制御シーケンスと完全に一致するかチェック
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
                self.socketio.sleep(0.01)  # キューが空の場合は少し待つ

    def stop_worker(self):
        self.main_thread_active = False
        self.channel.close()
        self.stop_worker_event.set()

    def _bbs_main_loop(self):
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
                context = {
                    'chan': self.channel, 'login_id': self.user_session.get('username'),
                    'display_name': self.user_session.get('display_name'), 'user_id': self.user_session.get('user_id'),
                    'userlevel': self.user_session.get('userlevel'), 'server_pref_dict': server_pref_dict,
                    'addr': self.channel.getpeername(), 'menu_mode': self.user_session.get('menu_mode', '2'),
                    'online_members_func': get_webapp_online_members,
                }
                util.send_text_by_key(
                    self.channel, "prompt.topmenu", context['menu_mode'], add_newline=False)
                command = self.channel.process_input()
                if command is None:
                    self.main_thread_active = False
                    break
                if util.handle_shortcut(context['chan'], context['login_id'], context['display_name'], context['menu_mode'], context['user_id'], command, context['online_members_func']):
                    util.send_top_menu(self.channel, context['menu_mode'])
                    continue
                command = command.strip().lower()
                if not command:
                    util.send_top_menu(self.channel, context['menu_mode'])
                    continue
                result = command_dispatcher.dispatch_command(command, context)
                if result.get('status') == 'logoff':
                    logoff_message_text = util.get_text_by_key(
                        "logoff.message", context['menu_mode'])
                    processed_text = logoff_message_text.replace(
                        '\r\n', '\n').replace('\n', '\r\n')
                    self.main_thread_active = False
                    self.socketio.emit('force_disconnect', {
                                       'message': processed_text}, to=self.sid)
                    break
                if 'new_menu_mode' in result:
                    self.user_session['menu_mode'] = result['new_menu_mode']
                    util.send_top_menu(
                        self.channel, self.user_session['menu_mode'])
        except Exception as e:
            logging.error(
                f"BBS main loop error ({self.user_session.get('username')}): {e}", exc_info=True)
        finally:
            self.stop_worker()
            logging.info(
                f"BBS main loop finished ({self.user_session.get('username')})")
