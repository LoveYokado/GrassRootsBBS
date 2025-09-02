# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

# ==============================================================================
# WebSocket Event Handlers
#
# This module defines all the SocketIO event handlers for real-time
# communication with the web terminal client. It manages the lifecycle of a
# client connection, from connection and authentication to input processing
# and disconnection.
# ==============================================================================
#
# ==============================================================================
# WebSocketイベントハンドラ
#
# このモジュールは、Webターミナルクライアントとのリアルタイム通信のための
# SocketIOイベントハンドラをすべて定義します。接続と認証から入力処理、
# 切断までのクライアント接続のライフサイクルを管理します。
# ==============================================================================

from flask import request, session, url_for, current_app
from flask_socketio import emit, disconnect
import logging
import os
import glob
import uuid

from . import terminal_handler, util


def init_events(socketio, app):
    """Initializes and registers all SocketIO event handlers."""

    @socketio.on('connect')
    def handle_connect(auth=None):
        """Handles new client connections via WebSocket."""
        if 'user_id' not in session:
            return False

        username_to_connect = session.get('username', 'Unknown')
        if username_to_connect.upper() != 'GUEST':
            sid_to_disconnect = None
            for sid, handler in terminal_handler.client_states.copy().items():
                if handler.user_session.get('username') == username_to_connect:
                    sid_to_disconnect = sid
                    break
            if sid_to_disconnect:
                logoff_message_text = util.get_text_by_key(
                    "auth.logged_in_from_another_location", session.get('menu_mode', '2'))
                processed_text = logoff_message_text.replace(
                    '\r\n', '\n').replace('\n', '\r\n')
                socketio.emit('force_disconnect', {
                              'message': processed_text}, to=sid_to_disconnect)
                disconnect(sid_to_disconnect, silent=True)

        with terminal_handler.current_webapp_clients_lock:
            max_clients_config = app.config.get('WEBAPP', {})
            max_clients = max_clients_config.get(
                'MAX_CONCURRENT_WEBAPP_CLIENTS', 0)
            if max_clients > 0 and terminal_handler.current_webapp_clients >= max_clients:
                return False
            terminal_handler.current_webapp_clients += 1

        username = session.get('username', 'Unknown')
        ip_addr = request.remote_addr or 'N/A'
        display_name = util.get_display_name(username, ip_addr)
        logging.getLogger('grbbs.access').info(
            f"CONNECT - User: {username}, DisplayName: {display_name}, IP: {ip_addr}, SID: {request.sid}")

        sid = request.sid
        user_session_data = {
            'user_id': session.get('user_id'), 'display_name': display_name,
            'username': session.get('username'), 'userlevel': session.get('userlevel'),
            'lastlogin': session.get('lastlogin', 0), 'menu_mode': session.get('menu_mode', '2')
        }
        handler = terminal_handler.WebTerminalHandler(
            sid, user_session_data, ip_addr, socketio)
        terminal_handler.client_states[sid] = handler

    @socketio.on('set_speed')
    def handle_set_speed(speed_name):
        """Receives a speed setting from the client to simulate baud rates."""
        sid = request.sid
        if sid in terminal_handler.client_states:
            handler = terminal_handler.client_states[sid]
            handler.speed = speed_name
            handler.bps_delay = terminal_handler.BPS_DELAYS.get(speed_name, 0)

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handles client disconnections."""
        with terminal_handler.current_webapp_clients_lock:
            terminal_handler.current_webapp_clients = max(
                0, terminal_handler.current_webapp_clients - 1)

        sid = request.sid
        username = session.get('username', 'Unknown')
        display_name = "Unknown"
        if sid in terminal_handler.client_states:
            display_name = terminal_handler.client_states[sid].user_session.get(
                'display_name', username)
        logging.getLogger('grbbs.access').info(
            f"DISCONNECT - User: {username}, DisplayName: {display_name}, SID: {sid}")

        if sid in terminal_handler.client_states:
            terminal_handler.client_states[sid].stop_worker()
            del terminal_handler.client_states[sid]

    @socketio.on('client_input')
    def handle_client_input(data):
        """Receives input from the client and adds it to the corresponding handler's input queue."""
        sid = request.sid
        if sid in terminal_handler.client_states:
            handler = terminal_handler.client_states[sid]
            handler.input_queue.append(data)
            handler.input_event.set()

    @socketio.on('toggle_logging')
    def handle_toggle_logging():
        """Toggles session logging on or off for the client."""
        sid = request.sid
        if sid in terminal_handler.client_states:
            handler = terminal_handler.client_states[sid]
            if handler.is_logging:
                handler.is_logging = False
                log_content = "".join(handler.log_buffer)
                handler.log_buffer.clear()
                if not log_content.strip():
                    emit('logging_stopped', {'message': 'ログに内容がありません。'})
                    return
                bbs_name = util.app_config.get(
                    'server', {}).get('BBS_NAME', 'GR-BBS')
                timestamp = util.datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                display_name_for_log = handler.user_session.get(
                    'display_name', handler.user_session.get('username'))
                safe_display_name = display_name_for_log.replace(
                    '(', '_').replace(')', '')
                filename = f"{bbs_name}_{safe_display_name}_{timestamp}.log"  # noqa
                filepath = os.path.join(
                    current_app.config['SESSION_LOG_DIR'], filename)
                try:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(log_content)
                    download_url = url_for(
                        'web.download_log', filename=filename)
                    emit('log_saved', {
                         'url': download_url, 'filename': filename})
                except Exception as e:
                    emit('logging_stopped', {'message': 'ログファイルの保存に失敗しました。'})
            else:
                handler.is_logging = True
                handler.log_buffer.clear()
                emit('logging_started')

    @socketio.on('get_log_files')
    def handle_get_log_files():
        """Sends a list of the user's saved log files to the client."""
        if 'user_id' not in session:
            return

        sid = request.sid
        if sid not in terminal_handler.client_states:
            return

        handler = terminal_handler.client_states[sid]
        display_name_for_log = handler.user_session.get(
            'display_name', handler.user_session.get('username'))
        safe_display_name = display_name_for_log.replace(
            '(', '_').replace(')', '')
        search_pattern = f"*_{safe_display_name}_*.log"

        log_files = []
        try:
            session_log_dir = current_app.config.get('SESSION_LOG_DIR')
            file_paths = glob.glob(os.path.join(
                session_log_dir, search_pattern))
            for file_path in file_paths:
                try:
                    stat = os.stat(file_path)
                    log_files.append({
                        'filename': os.path.basename(file_path),
                        'size': stat.st_size,
                        'mtime': stat.st_mtime
                    })
                except OSError:
                    continue

            log_files.sort(key=lambda x: x['mtime'], reverse=True)
            emit('log_files_list', {'files': log_files})
            logging.info(
                f"Sent log file list to {session.get('username')} (sid: {sid})")
        except Exception as e:
            logging.error(
                f"Error getting log files for {session.get('username')}: {e}")
            emit('error_message', {'message': 'ログファイルの取得に失敗しました。'})

    @socketio.on('get_log_content')
    def handle_get_log_content(data):
        """Sends the content of a specified log file to the client."""
        if 'user_id' not in session:
            return

        filename = data.get('filename')
        if not filename:
            return

        session_log_dir = current_app.config.get('SESSION_LOG_DIR')
        safe_path = os.path.abspath(os.path.join(session_log_dir, filename))
        if not safe_path.startswith(os.path.abspath(session_log_dir)):
            logging.warning(
                f"Potential directory traversal attempt: {filename} from {session.get('username')}")
            return

        try:
            with open(safe_path, 'r', encoding='utf-8') as f:
                content = f.read()
            content_for_terminal = content.replace(
                '\r\n', '\n').replace('\n', '\r\n')
            emit('log_content', {'filename': filename,
                 'content': content_for_terminal})
        except Exception as e:
            logging.error(f"Error reading log file {filename}: {e}")
            emit('error_message', {'message': 'ログファイルの読み込みに失敗しました。'})

    @socketio.on('get_current_log_buffer')
    def handle_get_current_log_buffer():
        """Sends the current, in-memory log buffer to the client."""
        sid = request.sid
        if sid in terminal_handler.client_states:
            handler = terminal_handler.client_states[sid]
            if handler.is_logging:
                content = "".join(handler.log_buffer)
                content_for_terminal = content.replace(
                    '\r\n', '\n').replace('\n', '\r\n')
                emit('log_content', {'filename': '(ロギング中)',
                     'content': content_for_terminal})
                logging.info(
                    f"Sent current log buffer to {session.get('username')} (sid: {sid})")
            else:
                emit('log_content', {'filename': '(ロギング中)',
                     'content': 'ロギングが開始されていません。'})

    @socketio.on('upload_attachment')
    def handle_upload_attachment(data):
        """Handles file uploads from the client for BBS attachments."""
        sid = request.sid
        if sid not in terminal_handler.client_states:
            return

        handler = terminal_handler.client_states[sid]
        handler.pending_attachment = None

        if 'user_id' not in handler.user_session:
            emit('attachment_upload_error', {'message': '認証されていません。'})
            return

        filename = data.get('filename')
        file_data = data.get('data')

        if not filename or not file_data:
            emit('attachment_upload_error',
                 {'message': 'ファイル名またはデータがありません。'})
            return

        board_config = getattr(handler, 'current_board_for_upload', {}) or {}
        global_limits_config = current_app.config.get('LIMITS', {})

        max_size_mb = board_config.get('max_attachment_size_mb')
        if max_size_mb is None:
            max_size_mb = global_limits_config.get(
                'attachment_max_size_mb', 10)
        max_size_bytes = max_size_mb * 1024 * 1024
        message = ""
        if len(file_data) > max_size_bytes:
            message = f'ファイルサイズが大きすぎます ({max_size_mb}MBまで)。'

        if not message:
            allowed_extensions_str = board_config.get('allowed_extensions')
            if allowed_extensions_str is None:
                allowed_extensions_str = global_limits_config.get(
                    'allowed_attachment_extensions', '')
            allowed_extensions = {ext.strip().lower()
                                  for ext in allowed_extensions_str.split(',') if ext.strip()}
            file_ext = os.path.splitext(filename)[1].lstrip('.').lower()
            if allowed_extensions and file_ext not in allowed_extensions:
                message = f'許可されていないファイル形式です。({", ".join(sorted(list(allowed_extensions)))})'

        if message:
            handler.pending_attachment = {'error': message}
            emit('attachment_upload_error', {'message': message})
            return

        _, ext = os.path.splitext(filename)
        unique_filename = f"{uuid.uuid4()}{ext}"
        attachment_dir = current_app.config.get('ATTACHMENT_DIR')
        save_path = os.path.join(attachment_dir, unique_filename)

        try:
            with open(save_path, 'wb') as f:
                f.write(file_data)

            handler.pending_attachment = {
                'unique_filename': unique_filename,
                'original_filename': filename,
                'filepath': save_path,
                'size': len(file_data)
            }
            logging.info(
                f"ファイルがアップロードされました: {filename} -> {unique_filename} (User: {handler.user_session.get('username')})")
            emit('attachment_upload_success',
                 {'original_filename': filename})
        except Exception as e:
            logging.error(f"ファイルアップロード処理中にエラー: {e}", exc_info=True)
            emit('attachment_upload_error',
                 {'message': 'サーバーエラーが発生しました。'})

    @socketio.on('clear_pending_attachment')
    def handle_clear_pending_attachment():
        """Clears any pending attachment information for the session."""
        sid = request.sid
        if sid in terminal_handler.client_states:
            handler = terminal_handler.client_states[sid]
            if handler.pending_attachment:
                logging.info(
                    f"保留中の添付ファイルをクリアしました: {handler.pending_attachment.get('original_filename')} (User: {handler.user_session.get('username')})")
                handler.pending_attachment = None

    @socketio.on('set_client_mode')
    def handle_set_client_mode(data):
        """
        Receives the client's display mode (mobile or desktop).
        クライアントの表示モード（モバイルかデスクトップか）を受け取ります。
        """
        sid = request.sid
        handler = terminal_handler.client_states.get(sid)
        if handler:
            handler.is_mobile = data.get('is_mobile', False)
            logging.info(
                f"Client mode set for SID {sid}: is_mobile={handler.is_mobile}")

    @socketio.on('multiline_input_submit')
    def handle_multiline_input_submit(data):
        """
        Receives the content from the web multiline editor and puts it into the handler's input queue.
        Webのマルチラインエディタからコンテンツを受け取り、ハンドラの入力キューに入れます。
        """
        sid = request.sid
        handler = terminal_handler.client_states.get(sid)
        if handler:
            content = data.get('content', '')
            handler.input_queue.append(content)
            handler.input_event.set()
