# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""WebSocketイベントハンドラ。

このモジュールは、Webターミナルクライアントとのリアルタイム通信を担う
SocketIOイベントハンドラを定義します。クライアント接続のライフサイクル
(接続、認証、入力処理、切断) を管理します。
"""

from flask import request, session, url_for, current_app
from flask_socketio import emit, disconnect
import logging
import os
import glob
import uuid
import json
import shutil
import ipaddress
from werkzeug.utils import secure_filename
from . import database

from . import terminal_handler, util


def init_events(socketio, app):
    """全てのSocketIOイベントハンドラを初期化し、登録します。"""

    @socketio.on('connect')
    def handle_connect(auth=None):
        """新しいクライアントのWebSocket接続を処理し、セッションを初期化します。"""
        # --- Proxy/VPN/Torチェック ---
        security_config = current_app.config.get('SECURITY', {})
        if security_config.get('block_proxies', False):
            remote_ip_str = util.get_client_ip()
            if remote_ip_str:
                is_proxy, reason = util.is_proxy_connection(remote_ip_str)
                if is_proxy:
                    logging.warning(
                        f"Proxy/VPN/TorからのWebSocket接続をブロックしました。IP: {remote_ip_str}, Reason: {reason}")
                    database.log_access_event(
                        ip_address=remote_ip_str, event_type='PROXY_BLOCKED',
                        username=session.get('username'), display_name=session.get('display_name'),
                        message=f"Blocked proxy/hosting WebSocket connection ({reason})."
                    )
                    return False  # 接続を拒否

        # --- IP BANチェック ---
        # HTTPリクエストだけでなく、WebSocket接続時にもBANチェックを行う
        try:
            banned_ips = database.get_all_ip_bans()
            if banned_ips:
                remote_ip_str = util.get_client_ip()
                if remote_ip_str:
                    remote_ip = ipaddress.ip_address(remote_ip_str)
                    if any(remote_ip in ipaddress.ip_network(ban['ip_address'], strict=False) for ban in banned_ips):
                        logging.warning(
                            f"Banned IP {remote_ip_str} tried to connect via WebSocket.")
                        return False  # 接続を拒否
        except Exception as e:
            logging.error(f"WebSocket接続時のIP BANチェック中にエラー: {e}")
            return False  # 安全のためエラー時も接続を拒否

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
            server_prefs = database.read_server_pref()
            max_clients = server_prefs.get(
                'max_concurrent_webapp_clients', 4)
            if max_clients > 0 and terminal_handler.current_webapp_clients >= max_clients:
                return False
            terminal_handler.current_webapp_clients += 1

        username = session.get('username', 'Unknown')
        ip_addr = util.get_client_ip()
        display_name = util.get_display_name(username, ip_addr)
        logging.getLogger('grbbs.access').info(
            f"CONNECT - User: {username}, DisplayName: {display_name}, IP: {ip_addr}, SID: {request.sid}")
        database.log_access_event(ip_address=ip_addr, event_type='CONNECT',
                                  username=username, display_name=display_name, message=f"SID: {request.sid}")

        sid = request.sid
        user_session_data = {
            'user_id': session.get('user_id'), 'display_name': display_name,
            'username': session.get('username'), 'userlevel': session.get('userlevel'),
            'lastlogin': session.get('lastlogin', 0), 'menu_mode': session.get('menu_mode', '2')
        }
        handler = terminal_handler.WebTerminalHandler(
            app, sid, user_session_data, ip_addr, socketio)
        terminal_handler.client_states[sid] = handler

    @socketio.on('set_speed')
    def handle_set_speed(speed_name):
        """クライアントからBPSレート設定を受け取り、通信速度をシミュレートします。"""
        sid = request.sid
        if sid in terminal_handler.client_states:
            handler = terminal_handler.client_states[sid]
            handler.speed = speed_name
            handler.bps_delay = terminal_handler.BPS_DELAYS.get(speed_name, 0)

    @socketio.on('disconnect')
    def handle_disconnect():
        """クライアントの切断イベントを処理し、関連リソースをクリーンアップします。"""
        with terminal_handler.current_webapp_clients_lock:
            terminal_handler.current_webapp_clients = max(
                0, terminal_handler.current_webapp_clients - 1)

        sid = request.sid
        handler = terminal_handler.client_states.get(sid)

        username = handler.user_session.get(
            'username', 'Unknown') if handler else 'Unknown'
        display_name = "Unknown"
        if handler:
            display_name = handler.user_session.get(
                'display_name', username)
        ip_addr = util.get_client_ip()
        database.log_access_event(ip_address=ip_addr, event_type='DISCONNECT',
                                  username=username, display_name=display_name, message=f"SID: {sid}")

        if sid in terminal_handler.client_states:
            terminal_handler.client_states[sid].stop_worker()
            del terminal_handler.client_states[sid]

    @socketio.on('client_input')
    def handle_client_input(data):
        """クライアントからのキーボード入力を受け取り、入力キューに追加します。"""
        sid = request.sid
        if sid in terminal_handler.client_states:
            handler = terminal_handler.client_states[sid]
            handler.input_queue.append(data)
            handler.input_event.set()

    @socketio.on('toggle_logging')
    def handle_toggle_logging():
        """クライアントのセッションログ記録の開始/停止を切り替えます。"""
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
                # ファイル名を無害化
                safe_display_name = secure_filename(display_name_for_log)
                filename = f"{bbs_name}_{safe_display_name}_{timestamp}.log"
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
        """ユーザーが保存したログファイルの一覧を取得し、クライアントに送信します。"""
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
        """指定されたログファイルの内容を読み込み、クライアントに送信します。"""
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
        """現在メモリ上にあるログバッファの内容をクライアントに送信します。"""
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
        """クライアントからのファイルアップロードを処理し、添付ファイルとして準備します。"""
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

        # ファイル名を無害化してから拡張子チェックを行う
        safe_original_filename = secure_filename(filename)

        if not message:
            allowed_extensions_str = board_config.get('allowed_extensions')
            if allowed_extensions_str is None:
                allowed_extensions_str = global_limits_config.get(
                    'allowed_attachment_extensions', '')
            allowed_extensions = {ext.strip().lower()
                                  for ext in allowed_extensions_str.split(',') if ext.strip()}
            file_ext = os.path.splitext(safe_original_filename)[
                1].lstrip('.').lower()
            if allowed_extensions and file_ext not in allowed_extensions:
                message = f'許可されていないファイル形式です。({", ".join(sorted(list(allowed_extensions)))})'

        if message:
            handler.pending_attachment = {'error': message}
            emit('attachment_upload_error', {'message': message})
            return

        _, ext = os.path.splitext(safe_original_filename)
        unique_filename = f"{uuid.uuid4()}{ext}"
        attachment_dir = current_app.config.get('ATTACHMENT_DIR')
        save_path = os.path.join(attachment_dir, unique_filename)

        try:
            with open(save_path, 'wb') as f:
                f.write(file_data)

            # --- ClamAVによるウイルススキャン ---
            is_safe, scan_message = util.scan_file_with_clamav(save_path)
            if not is_safe:
                logging.warning(
                    f"ウイルス検出: {filename} (User: {handler.user_session.get('username')}). Reason: {scan_message}")
                # --- 隔離処理 ---
                quarantine_dir_rel = util.app_config.get('clamav', {}).get(
                    'quarantine_directory', 'data/quarantine')
                quarantine_dir_abs = os.path.join(
                    current_app.config['PROJECT_ROOT'], quarantine_dir_rel)
                try:
                    log_entry = {
                        'timestamp': int(util.time.time()),
                        'unique_filename': unique_filename,
                        'original_filename': safe_original_filename,
                        'size': len(file_data),
                        'user_id': handler.user_session.get('user_id'),
                        'username': handler.user_session.get('username'),
                        'board_shortcut_id': board_config.get('shortcut_id', 'N/A'),
                        'board_name': board_config.get('name', 'N/A'),
                        'scan_result': scan_message,
                    }
                    log_file_path = os.path.join(
                        quarantine_dir_abs, 'quarantine_log.json')
                    logs = []
                    if os.path.exists(log_file_path):
                        try:
                            with open(log_file_path, 'r', encoding='utf-8') as f:
                                logs = json.load(f)
                                if not isinstance(logs, list):
                                    logs = []
                        except (json.JSONDecodeError, IOError):
                            logs = []
                    logs.append(log_entry)
                    with open(log_file_path, 'w', encoding='utf-8') as f:
                        json.dump(logs, f, indent=4)

                    # ファイルを隔離ディレクトリに移動
                    shutil.move(save_path, os.path.join(
                        quarantine_dir_abs, unique_filename))
                    logging.info(
                        f"ファイルを隔離しました: {unique_filename} -> {quarantine_dir_abs}")
                except OSError as e:
                    logging.error(f"ウイルス検出後のファイル隔離に失敗: {e}")

                # エラーメッセージをクライアントに送信
                error_msg = f"ウイルスが検出されたため、アップロードは拒否されました。({scan_message})"
                handler.pending_attachment = {'error': error_msg}
                emit('attachment_upload_error', {'message': error_msg})
                return

            # --- サムネイル生成 ---
            is_image = safe_original_filename.lower().endswith(
                ('.png', '.jpg', '.jpeg', '.gif', '.bmp'))
            if is_image:
                thumbnail_dir_rel = util.app_config.get('WEBAPP', {}).get(
                    'THUMBNAIL_DIR', 'data/attachments/thumbnails')
                thumbnail_dir_abs = os.path.join(
                    current_app.config['PROJECT_ROOT'], thumbnail_dir_rel)
                thumbnail_path = os.path.join(
                    thumbnail_dir_abs, unique_filename)
                util.create_thumbnail(save_path, thumbnail_path)

            handler.pending_attachment = {
                'unique_filename': unique_filename,
                'original_filename': safe_original_filename,
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

    @socketio.on('upload_file_from_plugin')
    def handle_upload_file_from_plugin(data):
        """プラグインAPI経由でのファイルアップロードを処理します。"""
        sid = request.sid
        if sid not in terminal_handler.client_states:
            return

        handler = terminal_handler.client_states[sid]
        handler.pending_upload = None  # 古い情報をクリア

        if 'user_id' not in handler.user_session:
            emit('upload_error_from_plugin', {'message': '認証されていません。'})
            return

        filename = data.get('filename')
        file_data = data.get('data')

        if not filename or file_data is None:
            # ファイル選択がキャンセルされた場合も、APIの待機を解除する
            handler.pending_upload = {'error': 'ファイルが選択されませんでした。'}
            handler.input_event.set()
            return

        # ハンドラに保存された設定を取得
        upload_settings = handler.pending_upload_settings or {}
        max_size_mb = upload_settings.get('max_size_mb', 10)
        allowed_extensions = upload_settings.get('allowed_extensions')

        # ファイルサイズチェック
        max_size_bytes = max_size_mb * 1024 * 1024
        if len(file_data) > max_size_bytes:
            msg = f'ファイルサイズが大きすぎます ({max_size_mb}MBまで)。'
            handler.pending_upload = {'error': msg}
            emit('upload_error_from_plugin', {'message': msg})
            handler.input_event.set()  # APIの待機を解除
            return

        # 拡張子チェック
        safe_original_filename = secure_filename(filename)
        if allowed_extensions:
            file_ext = os.path.splitext(safe_original_filename)[
                1].lstrip('.').lower()
            if file_ext not in [ext.lower() for ext in allowed_extensions]:
                msg = f'許可されていないファイル形式です。({", ".join(allowed_extensions)})'
                handler.pending_upload = {'error': msg}
                handler.input_event.set()  # APIの待機を解除
                return

        # ファイルを保存
        # プラグイン側で指定されたファイル名を使用する。指定がなければUUIDを生成。
        preferred_filename = upload_settings.get('preferred_filename')
        if preferred_filename:
            # 拡張子を元ファイルから拝借し、ファイル名を無害化
            _, ext = os.path.splitext(safe_original_filename)
            unique_filename = secure_filename(f"{preferred_filename}{ext}")
        else:
            _, ext = os.path.splitext(safe_original_filename)
            unique_filename = f"{uuid.uuid4()}{ext}"

        # どのプラグインからのアップロードかを取得
        requesting_plugin_id = upload_settings.get('plugin_id')
        if not requesting_plugin_id:
            handler.pending_upload = {'error': 'プラグインIDが特定できませんでした。'}
            handler.input_event.set()
            return

        # プラグインごとにディレクトリを分ける
        # アップロード先を、各プラグインの 'static' ディレクトリに変更
        plugin_upload_dir = os.path.join(
            current_app.config['PROJECT_ROOT'], 'plugins', requesting_plugin_id, 'static')
        os.makedirs(plugin_upload_dir, exist_ok=True)
        save_path = os.path.join(plugin_upload_dir, unique_filename)

        with open(save_path, 'wb') as f:
            f.write(file_data)

        # 成功情報をハンドラにセット
        handler.pending_upload = {
            'unique_filename': unique_filename,
            'original_filename': safe_original_filename,
            'filepath': save_path,
            'size': len(file_data)
        }
        handler.input_event.set()  # APIの待機を解除

    @socketio.on('clear_pending_attachment')
    def handle_clear_pending_attachment():
        """セッションで保留中の添付ファイル情報をクリアします。"""
        sid = request.sid
        if sid in terminal_handler.client_states:
            handler = terminal_handler.client_states[sid]
            if handler.pending_attachment:
                logging.info(
                    f"保留中の添付ファイルをクリアしました: {handler.pending_attachment.get('original_filename')} (User: {handler.user_session.get('username')})")
                handler.pending_attachment = None

    @socketio.on('multiline_input_submit')
    def handle_multiline_input_submit(data):
        """Webのマルチラインエディタから送信された内容を受け取り、入力キューに入れます。"""
        sid = request.sid
        handler = terminal_handler.client_states.get(sid)
        if handler:
            content = data.get('content', '')
            handler.input_queue.append(content)
            handler.input_event.set()
