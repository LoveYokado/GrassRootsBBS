# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado) <hogehoge@gmail.com>
# SPDX-License-Identifier: MIT
# # /home/yuki/python/GrassRootsBBS/src/webapp.py

# Gunicorn + gevent で WebSocket を動作させるために必須
# monkey.patch_all() は、他の標準ライブラリ(socket, threadingなど)を
# インポートする前に、可能な限り早く呼び出す必要があります。
from . import bbs_manager, command_dispatcher, database, util, passkey_handler
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_socketio import SocketIO, emit, disconnect
from flask_session import Session
from flask import (Flask, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for, Response)
import redis
from functools import wraps
import time
import threading
import sys
import socket
import secrets
import json
import os
import logging
import datetime
import uuid
import unicodedata
from logging.handlers import RotatingFileHandler
import glob
import collections
import codecs
from gevent import monkey
from webauthn.helpers import base64url_to_bytes
monkey.patch_all()

# --- 標準ライブラリ ---

# --- サードパーティライブラリ ---

# --- プロジェクトルートとパスの設定 ---
# このファイルの絶対パスから、プロジェクトのルートディレクトリを特定します。
_current_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_current_dir)
APP_LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
SESSION_LOG_DIR = os.path.join(APP_LOG_DIR, 'webapp_sessions')

# --- Flaskアプリケーションのセットアップ ---
# Flaskにtemplatesフォルダの場所を教えます（プロジェクトルート直下）。
app = Flask(__name__, template_folder=os.path.join(
    PROJECT_ROOT, 'templates'), static_folder=os.path.join(PROJECT_ROOT, 'static'))

# リバースプロキシ環境下で正しいURLを生成するためにProxyFixミドルウェアを適用
app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)
# セッション管理のために、ランダムな秘密鍵を設定します
app.secret_key = secrets.token_hex(16)
# WebSocketのためのSocketIOラッパー。Gunicornのgeventワーカーと連携するためにasync_modeを指定。
allowed_origins_str = os.getenv(
    'SOCKETIO_ALLOWED_ORIGINS', 'https://localhost')
allowed_origins = allowed_origins_str.split(',') if allowed_origins_str else []

socketio = SocketIO(
    app, cors_allowed_origins=allowed_origins, async_mode='gevent')

# --- アプリケーションモジュールのインポート ---
# app と socketio の初期化後にインポートすることで、循環インポートを避ける


# --- 初期設定 ---
# 既存の設定ファイルを読み込みます
try:
    config_path = os.path.join(PROJECT_ROOT, 'setting', 'config.toml')
    util.load_app_config_from_path(config_path)

    # --- 添付ファイルディレクトリ設定 ---
    webapp_config = util.app_config.get('webapp', {})
    ATTACHMENT_DIR = webapp_config.get(
        'ATTACHMENT_UPLOAD_DIR', 'data/attachments')
    if not os.path.isabs(ATTACHMENT_DIR):
        ATTACHMENT_DIR = os.path.join(PROJECT_ROOT, ATTACHMENT_DIR)

    if not os.path.exists(ATTACHMENT_DIR):
        os.makedirs(ATTACHMENT_DIR)
        logging.info(f"添付ファイル保存ディレクトリを作成しました: {ATTACHMENT_DIR}")

    if not os.path.exists(APP_LOG_DIR):
        os.makedirs(APP_LOG_DIR)
    if not os.path.exists(SESSION_LOG_DIR):
        os.makedirs(SESSION_LOG_DIR)

    # --- ロギング設定 ---
    # 1. アクセスロガーの設定 (grbbs.access)
    access_logger = logging.getLogger('grbbs.access')
    access_logger.setLevel(logging.INFO)
    access_handler = RotatingFileHandler(
        os.path.join(APP_LOG_DIR, 'grbbs.access.log'),
        maxBytes=1024 * 1024 * 5, backupCount=3, encoding='utf-8'
    )
    access_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s'))
    access_logger.addHandler(access_handler)
    access_logger.propagate = False  # ルートロガー（エラーログ）に伝播させない

    # 2. エラーロガー（ルートロガー）の設定
    error_handler = RotatingFileHandler(
        os.path.join(APP_LOG_DIR, 'grbbs.error.log'),
        maxBytes=1024 * 1024 * 5, backupCount=3, encoding='utf-8'
    )
    error_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'))
    logging.getLogger().addHandler(error_handler)
    logging.getLogger().setLevel(logging.INFO)

    # --- MariaDB 接続設定 ---
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'user': os.getenv('DB_USER', 'grbbs_user'),
        'password': os.getenv('DB_PASSWORD', 'password'),
        'database': os.getenv('DB_NAME', 'grbbs'),
        'charset': 'utf8mb4',
        'collation': 'utf8mb4_general_ci',
        'autocommit': False  # 明示的にcommit/rollbackを管理
    }
    # コネクションプールを初期化
    database.init_connection_pool(
        pool_name="grbbs_pool",
        pool_size=5,
        db_config=db_config
    )

    # --- データベース初期化チェック ---
    # アプリケーション起動時にテーブルの存在を確認し、なければ作成する
    if not util.check_database_initialized():
        logging.info("データベースが初期化されていません。初期セットアップを実行します。")
        sysop_id = os.getenv('GRASSROOTSBBS_SYSOP_ID')
        sysop_password = os.getenv('GRASSROOTSBBS_SYSOP_PASSWORD')
        sysop_email = os.getenv('GRASSROOTSBBS_SYSOP_EMAIL')

        if not (sysop_id and sysop_password and sysop_email):
            logging.critical(
                "初回起動には環境変数 GRASSROOTSBBS_SYSOP_ID, GRASSROOTSBBS_SYSOP_PASSWORD, GRASSROOTSBBS_SYSOP_EMAIL が必要です。")
        else:
            try:
                util.initialize_database_and_sysop(
                    sysop_id, sysop_password, sysop_email
                )
                logging.info(f"データベースとシスオペ '{sysop_id}' の初期化が完了しました。")
            except Exception as e:
                logging.exception(
                    f"データベースの初期化中にエラーが発生しました: {e}")

    # --- セッション設定 ---
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
    app.config['SESSION_PERMANENT'] = True  # ブラウザを閉じてもセッションを保持
    app.config['SESSION_USE_SIGNER'] = True  # セッションデータの改ざん防止
    app.config['SESSION_KEY_PREFIX'] = 'grbbs_'

    # セキュリティ設定をFlaskのコンフィグに読み込む
    security_config = util.app_config.get('security', {})
    app.config['MAX_LOGIN_ATTEMPTS'] = security_config.get(
        'MAX_PASSWORD_ATTEMPTS', 3)
    app.config['LOCKOUT_TIME'] = security_config.get(
        'LOCKOUT_TIME_SECONDS', 300)

    sess = Session()
except Exception as e:
    logging.critical(f"設定の読み込みに失敗しました: {e}")
    sys.exit(1)

# --- クライアントごとの状態管理 ---
# {sid: WebTerminalHandler_instance}
client_states = {}

current_webapp_clients = 0
current_webapp_clients_lock = threading.Lock()


# --- 定数 ---
BPS_DELAYS = {
    '300': 10.0 / 300,    # 約 33.3 ms/char (8-N-1を想定し10bit/char)
    '2400': 10.0 / 2400,   # 約 4.17 ms/char
    '4800': 10.0 / 4800,   # 約 2.08 ms/char
    '9600': 10.0 / 9600,   # 約 1.04 ms/char
    'full': 0,
}


def get_webapp_online_members():
    """Web UIでオンラインのメンバーリストを生成する"""
    members = {}
    # 辞書のコピーに対して反復処理を行うことで、反復中の変更によるエラーを回避
    for sid, handler in client_states.copy().items():
        user_session = handler.user_session
        if user_session:
            login_id = user_session.get('username')
            if login_id:
                members[login_id] = {
                    # GUESTの場合はハッシュ付きの表示名、それ以外はログインID
                    "display_name": user_session.get('display_name', login_id),
                    "addr": handler.channel.getpeername(),  # ダミーIPを返す
                    "menu_mode": user_session.get('menu_mode', '?')
                }
    return members


class WebTerminalHandler:
    """Webターミナルセッションの状態とロジックを管理するクラス"""

    def __init__(self, sid, user_session, ip_address):
        self.sid = sid
        self.user_session = user_session
        self.ip_address = ip_address
        self.speed = 'full'
        self.bps_delay = 0
        self.output_queue = collections.deque()
        self.input_queue = collections.deque()
        self.input_event = threading.Event()
        self.stop_worker_event = threading.Event()
        self.is_logging = False
        self.log_buffer = []
        self.mail_notified_this_session = False  # 明示的に初期化
        self.main_thread_active = True
        self.pending_attachment = None

        # SSHの `paramiko.Channel` のように振る舞うアダプタクラス
        class WebChannel:
            def __init__(self, handler_instance, ip_addr):
                self.handler = handler_instance
                self.ip_address = ip_addr
                self.recv_buffer = b''
                self.active = True
                self._timeout = None

            def settimeout(self, timeout):
                """ssh_input.pyから呼び出されるタイムアウト設定"""
                self._timeout = timeout

            def send(self, data):
                # dataはstrかbytes。WebSocketではstrをemitする必要がある。
                if isinstance(data, bytes):
                    text_to_send = data.decode('utf-8', 'ignore')
                else:
                    text_to_send = str(data)

                if self.handler.is_logging:
                    self.handler.log_buffer.append(text_to_send)

                # ワーカースレッドが処理するようにキューに追加する
                self.handler.output_queue.append(text_to_send)

            def recv(self, n):
                """ssh_inputから呼ばれる。クライアントからの入力をバイト列で返す。"""
                while len(self.recv_buffer) < n and self.active:
                    # キューが空なら、新しい入力が来るまで待機
                    if not self.handler.input_queue:
                        # wait()はタイムアウトするとFalseを返す
                        if not self.handler.input_event.wait(timeout=self._timeout):
                            raise socket.timeout("timed out")
                        self.handler.input_event.clear()  # Reset for next wait
                        # 待機後に再度アクティブチェック
                        if not self.active:
                            break

                    # キューからデータを取得して内部バッファに追加
                    try:
                        data_str = self.handler.input_queue.popleft()
                        self.recv_buffer += data_str.encode('utf-8')
                    except IndexError:
                        # 他のスレッドが先にキューを空にした場合など
                        continue

                if not self.active and not self.recv_buffer:
                    return b''  # 接続が閉じてバッファも空なら空バイトを返す

                # 要求されたバイト数を返す
                ret = self.recv_buffer[:n]
                self.recv_buffer = self.recv_buffer[n:]
                return ret

            def getpeername(self):
                # WebTerminalHandlerから渡されたIPアドレスを返す
                return (self.ip_address, 12345)

            def close(self):
                self.active = False
                self.handler.input_event.set()  # Waiting recv() should be unblocked

            def _process_input_internal(self, echo=True):
                """
                クライアントから1行入力を受け取り、文字列として返す内部メソッド。
                エコーバックとマルチバイト文字に対応。
                """
                line_buffer = []  # 文字列のリストとして保持
                decoder = codecs.getincrementaldecoder('utf-8')('ignore')

                try:
                    while self.active:
                        char_byte = self.recv(1)
                        if not char_byte:  # 接続が切れた場合
                            return None

                        # Enterキー (CR or LF)
                        if char_byte in (b'\r', b'\n'):
                            if echo:
                                self.send(b'\r\n')
                            break

                        # Backspace (BS or DEL)
                        elif char_byte in (b'\x08', b'\x7f'):
                            if line_buffer:  # 最後の「文字」を削除
                                deleted_char = line_buffer.pop()
                                if echo:
                                    # unicodedata.east_asian_width を使って文字幅を判定
                                    # 'F' (Fullwidth), 'W' (Wide), 'A' (Ambiguous) は2文字幅とみなす
                                    width = unicodedata.east_asian_width(
                                        deleted_char)
                                    char_width = 2 if width in (
                                        'F', 'W', 'A') else 1
                                    backspaces = b'\x08' * char_width
                                    self.send(
                                        backspaces + (b' ' * char_width) + backspaces)
                        else:
                            # 通常の文字バイトをデコード
                            try:
                                # インクリメンタルデコーダを使い、完全な文字がデコードできた場合のみ処理
                                decoded_char = decoder.decode(char_byte)
                                if decoded_char:
                                    line_buffer.append(decoded_char)
                                    if echo:
                                        # デコードできた文字をUTF-8で送り返す
                                        self.send(decoded_char.encode('utf-8'))
                            except UnicodeDecodeError:
                                # 'ignore' を指定しているので発生しないはずだが、念のため
                                decoder.reset()
                                continue

                except socket.timeout:
                    logging.warning(
                        f"入力待機中にタイムアウトしました (SID: {self.handler.sid})")
                except Exception as e:
                    logging.error(
                        f"process_inputでエラー (SID: {self.handler.sid}): {e}")
                    return None

                # ループを抜けた後、デコーダに残っているかもしれないバイトをフラッシュ
                remaining = decoder.decode(b'', final=True)
                if remaining:
                    line_buffer.append(remaining)

                return "".join(line_buffer)

            def process_input(self):
                """
                クライアントから1行入力を受け取り、文字列として返す。
                エコーバックとバックスペース処理も行う。ssh_input.process_inputの代替。
                """
                return self._process_input_internal(echo=True)

            def hide_process_input(self):
                """
                クライアントから1行入力を受け取るが、エコーバックしない。
                パスワード入力用。ssh_input.hide_process_inputの代替。
                """
                return self._process_input_internal(echo=False)

        self.channel = WebChannel(self, self.ip_address)
        socketio.start_background_task(self._sender_worker)
        socketio.start_background_task(self._bbs_main_loop)

    def _sender_worker(self):
        """出力キューを監視し、クライアントにデータを送信するワーカースレッド"""
        while not self.stop_worker_event.is_set():
            try:
                text = self.output_queue.popleft()
                if self.bps_delay > 0:
                    for char in text:
                        if self.stop_worker_event.is_set():
                            break
                        socketio.emit('server_output', char, to=self.sid)
                        socketio.sleep(self.bps_delay)
                else:
                    socketio.emit('server_output', text, to=self.sid)
            except IndexError:
                socketio.sleep(0.01)  # キューが空なら少し待機

    def stop_worker(self):
        """ワーカースレッドを停止させる"""
        self.main_thread_active = False
        self.channel.close()
        self.stop_worker_event.set()

    def _bbs_main_loop(self):
        """BBSのメインロジックを実行するスレッド"""
        server_pref_dict = {}
        try:
            # サーバ設定読み込み
            pref_list = database.read_server_pref()
            pref_names = ['bbs', 'chat', 'mail', 'telegram',
                          'userpref', 'who', 'default_exploration_list', 'hamlet', 'login_message']
            if pref_list and len(pref_list) >= len(pref_names):
                server_pref_dict = dict(zip(pref_names, pref_list))
            else:
                logging.error(
                    f"サーバ設定読み込みエラーです。デフォルト値を使用します。 (User: {self.user_session.get('username')})")
                server_pref_dict = {'bbs': 2, 'chat': 2, 'mail': 2, 'telegram': 2,
                                    'userpref': 2, 'who': 2, 'hamlet': 2,
                                    'default_exploration_list': '', 'login_message': ''}

            # 最終ログイン時刻を文字列化
            last_login_time = self.user_session.get('lastlogin', 0)
            last_login_str = "なし"
            if last_login_time and last_login_time > 0:
                try:
                    last_login_str = datetime.datetime.fromtimestamp(
                        last_login_time).strftime('%Y-%m-%d %H:%M:%S')
                except (OSError,  TypeError, ValueError):
                    logging.warning(
                        f"最終ログイン時刻の変換に失敗しました。 {last_login_time}")
                    last_login_str = "不明な日時"

            # ウェルカムメッセージとトップメニュー表示
            util.send_text_by_key(self.channel, "login.welcome_message_webapp",
                                  self.user_session.get('menu_mode', '2'),
                                  login_id=self.user_session.get('username'),
                                  last_login_str=last_login_str)
            util.send_top_menu(
                self.channel, self.user_session.get('menu_mode', '2'))

            while self.main_thread_active:
                # プロンプト前の定型処理 (メール/電報通知)
                _, self.mail_notified_this_session = util.prompt_handler(
                    self.channel, self.user_session.get('username'),
                    self.user_session.get(
                        'menu_mode', '2'), self.mail_notified_this_session
                )

                context = {
                    'chan': self.channel,
                    'login_id': self.user_session.get('username'),
                    'display_name': self.user_session.get('display_name'),
                    'user_id': self.user_session.get('user_id'),
                    'userlevel': self.user_session.get('userlevel'),
                    'server_pref_dict': server_pref_dict,
                    'addr': self.channel.getpeername(),
                    'menu_mode': self.user_session.get('menu_mode', '2'),
                    'online_members_func': get_webapp_online_members,
                }

                util.send_text_by_key(
                    self.channel, "prompt.topmenu", context['menu_mode'], add_newline=False)

                command = self.channel.process_input()

                if command is None:  # 切断
                    self.main_thread_active = False
                    break

                # ショートカット処理
                # util.handle_shortcut はショートカットとして処理された場合に True を返す
                if util.handle_shortcut(
                    context['chan'],
                    context['login_id'],
                    context['display_name'],
                    context['menu_mode'],
                    command,  # strip() や lower() をかける前の生コマンドを渡す
                    context['online_members_func']
                ):
                    # ショートカット処理後はトップメニューを再表示してループの先頭へ
                    util.send_top_menu(self.channel, context['menu_mode'])
                    continue

                command = command.strip().lower()
                if not command:
                    util.send_top_menu(self.channel, context['menu_mode'])
                    continue

                result = command_dispatcher.dispatch_command(command, context)

                if result.get('status') == 'logoff':
                    # ログオフメッセージを取得して、クライアントに切断イベントと共に送信
                    logoff_message_text = util.get_text_by_key(
                        "logoff.message", context['menu_mode'])
                    processed_text = logoff_message_text.replace(
                        '\r\n', '\n').replace('\n', '\r\n')
                    self.main_thread_active = False
                    socketio.emit('force_disconnect', {
                                  'message': processed_text}, to=self.sid)
                    break

                if 'new_menu_mode' in result:
                    self.user_session['menu_mode'] = result['new_menu_mode']
                    util.send_top_menu(
                        self.channel, self.user_session['menu_mode'])

        except Exception as e:
            logging.error(
                f"BBSメインループでエラー発生 ({self.user_session.get('username')}): {e}", exc_info=True)
        finally:
            self.stop_worker()
            logging.info(
                f"BBSメインループが終了しました ({self.user_session.get('username')})")

# --- デコレータ ---


def login_required(f):
    """ログインが必要なページへのアクセスのためのデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # ログインしていない場合はログインページにリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


# --- ルーティング（URLと関数の紐付け） ---

@app.route('/manifest.json')
def manifest():
    """PWAのマニフェストファイルを配信する"""
    return send_from_directory(app.static_folder, 'manifest.json')


@app.route('/sw.js')
def service_worker():
    """PWAのService Workerファイルを配信する"""
    response = send_from_directory(app.static_folder, 'sw.js')
    # Service Workerのスクリプトには特定のヘッダーが必要
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@app.route('/')
@login_required
def index():
    """ターミナルページを表示"""
    # url_forはリクエストコンテキスト内で呼び出す必要がある
    fkey_definitions = {
        "f1": {"label": "SETTING", "action": "open_popup"},
        "f2": {"label": "LOGGING", "action": "toggle_logging"},
        "f3": {"label": "LOG VIEW", "action": "open_log_viewer"},
        "f4": {"label": "NoFunction", "action": "none"},  # 予約
        "f5": {"label": "Line Edit", "action": "open_line_editor"},
        "f6": {"label": "M-Line Edit", "action": "open_multiline_editor"},
        "f8": {"label": "ReConnect", "action": "redirect", "value": url_for('login')},
    }
    # limits設定をテンプレートに渡す
    limits_config = util.app_config.get('limits', {})
    attachment_limits = {
        'max_size_mb': limits_config.get('attachment_max_size_mb', 10),
        'allowed_extensions': limits_config.get('allowed_attachment_extensions', 'jpg,jpeg,png,gif,txt')
    }

    return render_template('terminal.html', fkey_definitions=fkey_definitions, attachment_limits=attachment_limits)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """ログインページ"""
    webapp_config = util.app_config.get('webapp', {})
    page_title = webapp_config.get('LOGIN_PAGE_TITLE', 'Login')
    logo_path = webapp_config.get('LOGIN_PAGE_LOGO_PATH')
    message = webapp_config.get('LOGIN_PAGE_MESSAGE', 'Welcome.')

    if request.method == 'POST':
        # ユーザーIDは大文字に統一して扱う
        username = request.form.get('username', '').upper()
        password = request.form.get('password')
        error = None

        # GUESTアカウントはロックアウト対象外
        is_guest = username == 'GUEST'

        if not is_guest:
            # ロックアウト状態かチェック
            if session.get('lockout_expiration', 0) > time.time():
                remaining_time = session.get(
                    'lockout_expiration', 0) - time.time()
                # textdata.yamlからメッセージを取得
                error = util.get_text_by_key(
                    "auth.account_locked_temporary",
                    session.get('menu_mode', '2'),
                    default_value="Account is temporarily locked. Please try again in {remaining_time:.0f} seconds."
                ).format(remaining_time=remaining_time)
                logging.warning(
                    f"ログイン試行失敗: アカウントロック中 {username} (残り{remaining_time:.0f}秒)")
                return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message), 403

        # 既存の認証ロジックを再利用
        user_auth_info = database.get_user_auth_info(username)

        auth_success = False
        if user_auth_info:
            if util.verify_password(user_auth_info['password'], user_auth_info['salt'], password):
                auth_success = True

        if auth_success:
            # --- 認証成功後にマルチログインチェック ---
            if not is_guest:
                for sid, handler in client_states.copy().items():
                    # ユーザー名は既に大文字に統一されている
                    if handler.user_session.get('username') == username:
                        error = util.get_text_by_key(
                            "auth.already_logged_in",
                            session.get('menu_mode', '2'),
                            default_value="This ID is already in use."
                        ).replace('\r\n', '')
                        logging.warning(
                            f"ログイン試行成功後のマルチログイン検出: {username}")
                        return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message), 403
            # --- ここまで ---

            if not is_guest:
                # エラーカウントとロックをリセット
                session['login_attempts'] = 0
                session['lockout_expiration'] = 0

            # 最終ログイン時刻をセッションに保存（DB更新前）
            session['lastlogin'] = user_auth_info['lastlogin'] if 'lastlogin' in user_auth_info.keys(
            ) else 0

            session['user_id'] = user_auth_info['id']
            session['username'] = user_auth_info['name']
            session['userlevel'] = user_auth_info['level']
            session['menu_mode'] = user_auth_info['menu_mode'] if 'menu_mode' in user_auth_info.keys(
            ) else '2'
            logging.info(f"WebUI Login Success: {username}")

            # DBのログイン時刻を更新
            database.update_record(
                'users', {'lastlogin': int(time.time())}, {'id': user_auth_info['id']})

            return redirect(url_for('index'))
        else:
            # 認証失敗
            if not is_guest:
                session['login_attempts'] = session.get(
                    'login_attempts', 0) + 1
                logging.warning(
                    f"ログイン試行失敗: {username} ({session['login_attempts']} 回目)")
                if session['login_attempts'] >= app.config['MAX_LOGIN_ATTEMPTS']:
                    session['lockout_expiration'] = time.time() + \
                        app.config['LOCKOUT_TIME']
                    lockout_minutes = app.config['LOCKOUT_TIME'] / 60
                    error = util.get_text_by_key(
                        "auth.account_locked_permanent",
                        session.get('menu_mode', '2'),
                        default_value="Account has been locked. Please try again in {lockout_minutes:.0f} minutes."
                    ).format(lockout_minutes=lockout_minutes)
                    logging.warning(
                        f"アカウントをロックしました: {username} (試行回数超過)")
                else:
                    error = 'IDまたはパスワードが違います。'
            else:
                error = 'IDまたはパスワードが違います。'

            logging.warning(f"WebUI Login Failed: {username}")
            return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message)

    # GETリクエストの場合はログインフォームを表示
    return render_template('login.html',
                           page_title=page_title,
                           logo_path=logo_path,
                           message=message)


@app.route('/logout')
def logout():
    """ログアウト処理"""
    session.clear()
    return render_template('logout.html')


@app.route('/passkey/register-options', methods=['POST'])
@login_required
def passkey_register_options():
    """Passkey登録のためのオプションを生成して返すAPI"""
    user_id = session.get('user_id')
    username = session.get('username')

    if not user_id or not username:
        return jsonify({"error": "User not logged in"}), 401

    try:
        options_json_str = passkey_handler.generate_registration_options_for_user(
            user_id, username)

        # 検証のためにチャレンジをセッションに保存
        options_dict = json.loads(options_json_str)
        session["passkey_registration_challenge"] = options_dict.get(
            "challenge")

        return Response(options_json_str, mimetype='application/json')
    except Exception as e:
        logging.error(f"Passkey登録オプション生成エラー: {e}", exc_info=True)
        return jsonify({"error": "Failed to generate registration options"}), 500


@app.route('/passkey/verify-registration', methods=['POST'])
@login_required
def passkey_verify_registration():
    """Passkey登録の検証を行い、結果を返すAPI"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "User not logged in"}), 401

    # セッションからチャレンジを取得し、使用後に削除
    challenge_str = session.pop("passkey_registration_challenge", None)
    if not challenge_str:
        return jsonify({"error": "Challenge not found in session"}), 400

    # Base64URLエンコードされたチャレンジをバイト列に戻す
    challenge_bytes = base64url_to_bytes(challenge_str)

    # フロントエンドから送信されたデータを取得
    data = request.get_json()
    if not data or 'credential' not in data or 'nickname' not in data:
        return jsonify({"error": "Invalid request body"}), 400

    credential_json = json.dumps(data['credential'])
    nickname = data['nickname']

    webapp_config = util.app_config.get('webapp', {})
    expected_origin = webapp_config.get('ORIGIN', 'http://localhost:5000')

    success = passkey_handler.verify_registration_for_user(
        user_id=user_id, credential=credential_json, expected_challenge=challenge_bytes, expected_origin=expected_origin, nickname=nickname
    )

    if success:
        return jsonify({"verified": True})
    else:
        return jsonify({"verified": False, "error": "Verification failed on server"}), 400


@app.route('/passkey/auth-options', methods=['POST'])
def passkey_auth_options():
    """Passkey認証のためのオプションを生成して返すAPI"""
    data = request.get_json()
    username = data.get('username', '').upper()
    if not username:
        return jsonify({"error": "Username is required"}), 400

    try:
        options_json_str = passkey_handler.generate_authentication_options_for_user(
            username)
        if not options_json_str:
            return jsonify({"error": "User not found or no passkeys registered"}), 404

        # 検証のためにチャレンジをセッションに保存
        options_dict = json.loads(options_json_str)
        session["passkey_authentication_challenge"] = options_dict.get(
            "challenge")

        return Response(options_json_str, mimetype='application/json')
    except Exception as e:
        logging.error(f"Passkey認証オプション生成エラー: {e}", exc_info=True)
        return jsonify({"error": "Failed to generate authentication options"}), 500


@app.route('/passkey/verify-auth', methods=['POST'])
def passkey_verify_auth():
    """Passkey認証の検証を行い、成功すればログインさせるAPI"""
    challenge_str = session.pop("passkey_authentication_challenge", None)
    if not challenge_str:
        return jsonify({"error": "Challenge not found in session"}), 400

    challenge_bytes = base64url_to_bytes(challenge_str)

    data = request.get_json()
    if not data or 'credential' not in data:
        return jsonify({"error": "Invalid request body"}), 400

    credential_json = json.dumps(data['credential'])
    webapp_config = util.app_config.get('webapp', {})
    expected_origin = webapp_config.get('ORIGIN', 'http://localhost:5000')

    user_data = passkey_handler.verify_authentication_for_user(
        credential=credential_json, expected_challenge=challenge_bytes, expected_origin=expected_origin)

    if user_data:
        session['lastlogin'] = user_data.get('lastlogin', 0)
        session['user_id'] = user_data['id']
        session['username'] = user_data['name']
        session['userlevel'] = user_data['level']
        session['menu_mode'] = user_data.get('menu_mode', '2')
        logging.info(f"WebUI Passkey Login Success: {user_data['name']}")
        database.update_record(
            'users', {'lastlogin': int(time.time())}, {'id': user_data['id']})
        return jsonify({"verified": True})
    else:
        logging.warning("WebUI Passkey Login Failed")
        return jsonify({"verified": False, "error": "Authentication failed"}), 401


@app.route('/attachments/<path:filename>')
@login_required
def download_attachment(filename):
    """保存された添付ファイルをダウンロードさせる"""
    # セキュリティのため、ATTACHMENT_DIRからのみファイルを送信する
    return send_from_directory(ATTACHMENT_DIR, filename, as_attachment=True)

# --- WebSocketイベントハンドラ ---


@socketio.on('connect')
def handle_connect(auth=None):
    """クライアント接続時の処理。auth引数はSocketIOから渡される可能性があるため受け取る。"""
    if 'user_id' not in session:
        return False  # 未認証ユーザーは接続を拒否

    # --- マルチログインチェック ---
    username_to_connect = session.get('username', 'Unknown')
    if username_to_connect.upper() != 'GUEST':
        # client_states を直接チェックして、同じユーザー名が既に存在しないか確認
        for sid, handler in client_states.copy().items():
            if handler.user_session.get('username') == username_to_connect:
                logging.warning(
                    f"WebUIでのマルチログインが試みられました: {username_to_connect} from {request.remote_addr}")
                # クライアントに通知して切断させる
                logoff_message_text = util.get_text_by_key(
                    "auth.already_logged_in", session.get('menu_mode', '2'))
                processed_text = logoff_message_text.replace(
                    '\r\n', '\n').replace('\n', '\r\n')
                emit('force_disconnect', {'message': processed_text})
                return False  # 接続を拒否

    # --- 接続数チェック ---
    global current_webapp_clients
    with current_webapp_clients_lock:
        max_clients = util.app_config.get(
            'webapp', {}).get('MAX_CONCURRENT_WEBAPP_CLIENTS', 0)
        if max_clients > 0 and current_webapp_clients >= max_clients:
            logging.warning(
                f"WebUI connection limit ({max_clients}) reached. Rejecting new connection from {request.remote_addr}")
            return False  # 接続を拒否
        current_webapp_clients += 1

    username = session.get('username', 'Unknown')
    ip_addr = request.remote_addr or 'N/A'
    # GUESTの場合はハッシュ付きの表示名を生成
    display_name = util.get_display_name(username, ip_addr)
    logging.getLogger('grbbs.access').info(
        f"CONNECT - User: {username}, DisplayName: {display_name}, IP: {ip_addr}, SID: {request.sid}")

    sid = request.sid
    # ユーザーセッション情報を辞書としてハンドラに渡す
    user_session_data = {
        'user_id': session.get('user_id'),
        'display_name': display_name,  # 表示名を追加
        'username': session.get('username'),
        'userlevel': session.get('userlevel'),
        'lastlogin': session.get('lastlogin', 0),
        'menu_mode': session.get('menu_mode', '2')
    }
    handler = WebTerminalHandler(sid, user_session_data, ip_addr)
    client_states[sid] = handler

    logging.info(
        f"WebTerminal client connected: {session.get('username')} (sid: {sid}). "
        f"Current clients: {current_webapp_clients}/{max_clients if max_clients > 0 else 'unlimited'}")


@socketio.on('set_speed')
def handle_set_speed(speed_name):
    """クライアントから速度設定を受け取る"""
    sid = request.sid
    if sid in client_states:
        handler = client_states[sid]
        handler.speed = speed_name
        handler.bps_delay = BPS_DELAYS.get(speed_name, 0)
        logging.info(
            f"WebTerminal speed set for {session.get('username')}: {speed_name}")


@socketio.on('disconnect')
def handle_disconnect():
    """クライアント切断時の処理"""
    global current_webapp_clients
    with current_webapp_clients_lock:
        current_webapp_clients = max(0, current_webapp_clients - 1)

    sid = request.sid
    username = session.get('username', 'Unknown')
    # 切断時には client_states から表示名を取得
    display_name = "Unknown"
    if sid in client_states:
        display_name = client_states[sid].user_session.get(
            'display_name', username)
    logging.getLogger('grbbs.access').info(
        f"DISCONNECT - User: {username}, DisplayName: {display_name}, SID: {sid}")

    if sid in client_states:
        client_states[sid].stop_worker()  # これで両方のスレッドが停止する
        del client_states[sid]

    logging.info(
        f"WebTerminal client disconnected: {session.get('username')} (sid: {sid}). "
        f"Current clients: {current_webapp_clients}")


@socketio.on('client_input')
def handle_client_input(data):
    """クライアントからの入力を受け取り、対応するハンドラのキューに入れる"""
    sid = request.sid
    if sid not in client_states:
        return  # 状態がない場合は何もしない

    handler = client_states[sid]
    handler.input_queue.append(data)
    handler.input_event.set()  # BBSメインループに新しい入力があったことを通知


@socketio.on('toggle_logging')
def handle_toggle_logging():
    """ロギングの開始/停止をトグルする"""
    sid = request.sid
    if sid not in client_states:
        return

    handler = client_states[sid]
    if handler.is_logging:
        # --- ロギング停止処理 ---
        handler.is_logging = False
        log_content = "".join(handler.log_buffer)
        handler.log_buffer.clear()

        if not log_content.strip():
            emit('logging_stopped', {'message': 'ログに内容がありません。'})
            return

        # ファイル名生成
        bbs_name = util.app_config.get('server', {}).get('BBS_NAME', 'GR-BBS')
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        display_name_for_log = handler.user_session.get(
            'display_name', handler.user_session.get('username'))
        # ファイル名として安全な文字列に変換
        safe_display_name = display_name_for_log.replace(
            '(', '_').replace(')', '')
        filename = f"{bbs_name}_{safe_display_name}_{timestamp}.log"
        filepath = os.path.join(SESSION_LOG_DIR, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(log_content)

            # クライアントにダウンロード用のURLを通知
            download_url = url_for('download_log', filename=filename)
            emit('log_saved', {'url': download_url, 'filename': filename})
            logging.info(
                f"セッションログを保存しました: {filepath} (User: {handler.user_session.get('username')})")

        except Exception as e:
            logging.error(f"ログファイルの保存に失敗しました: {e}")
            emit('logging_stopped', {'message': 'ログファイルの保存に失敗しました。'})

    else:
        # --- ロギング開始処理 ---
        handler.is_logging = True
        handler.log_buffer.clear()
        emit('logging_started')
        logging.info(
            f"セッションロギングを開始しました (User: {handler.user_session.get('username')})")


@app.route('/download_log/<path:filename>')
@login_required
def download_log(filename):
    """保存されたログファイルをダウンロードさせる"""
    # セキュリティのため、SESSION_LOG_DIRからのみファイルを送信する
    return send_from_directory(SESSION_LOG_DIR, filename, as_attachment=True)


@socketio.on('get_log_files')
def handle_get_log_files():
    """クライアントに保存済みログファイルの一覧を送信する"""
    if 'user_id' not in session:
        return

    sid = request.sid
    if sid not in client_states:
        return

    handler = client_states[sid]
    # ユーザー自身のログファイルのみを対象とする
    display_name_for_log = handler.user_session.get(
        'display_name', handler.user_session.get('username'))
    safe_display_name = display_name_for_log.replace('(', '_').replace(')', '')

    # ユーザー名でファイルを絞り込むためのパターン
    search_pattern = f"*_{safe_display_name}_*.log"

    log_files = []
    try:
        file_paths = glob.glob(os.path.join(SESSION_LOG_DIR, search_pattern))
        for file_path in file_paths:
            try:
                stat = os.stat(file_path)
                log_files.append({
                    'filename': os.path.basename(file_path),
                    'size': stat.st_size,
                    'mtime': stat.st_mtime  # 変更日時 (タイムスタンプ)
                })
            except OSError:
                continue

        log_files.sort(key=lambda x: x['mtime'], reverse=True)
        emit('log_files_list', {'files': log_files}, to=sid)
        logging.info(
            f"Sent log file list to {session.get('username')} (sid: {sid})")

    except Exception as e:
        logging.error(
            f"Error getting log files for {session.get('username')}: {e}")
        emit('error_message', {'message': 'ログファイルの取得に失敗しました。'}, to=sid)


@socketio.on('get_log_content')
def handle_get_log_content(data):
    """指定されたログファイルの内容をクライアントに送信する"""
    if 'user_id' not in session:
        return

    sid = request.sid
    if sid not in client_states:
        return

    filename = data.get('filename')
    if not filename:
        return

    safe_path = os.path.abspath(os.path.join(SESSION_LOG_DIR, filename))
    if not safe_path.startswith(os.path.abspath(SESSION_LOG_DIR)):
        logging.warning(
            f"Potential directory traversal attempt: {filename} from {session.get('username')}")
        return

    try:
        with open(safe_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # ターミナル表示用に改行コードを正規化
        content_for_terminal = content.replace(
            '\r\n', '\n').replace('\n', '\r\n')
        emit('log_content', {'filename': filename,
             'content': content_for_terminal}, to=sid)
    except Exception as e:
        logging.error(f"Error reading log file {filename}: {e}")
        emit('error_message', {'message': 'ログファイルの読み込みに失敗しました。'}, to=sid)


@socketio.on('get_current_log_buffer')
def handle_get_current_log_buffer():
    """クライアントに現在記録中のログバッファ内容を送信する"""
    sid = request.sid
    if sid in client_states:
        handler = client_states[sid]
        if handler.is_logging:
            content = "".join(handler.log_buffer)
            # ターミナル表示用に改行コードを正規化
            content_for_terminal = content.replace(
                '\r\n', '\n').replace('\n', '\r\n')
            # 既存の'log_content'イベントを再利用して送信
            emit('log_content', {'filename': '(ロギング中)',
                 'content': content_for_terminal}, to=sid)
            logging.info(
                f"Sent current log buffer to {session.get('username')} (sid: {sid})")
        else:
            # ロギング中でない場合は、空の内容を返すか、エラーメッセージを返す
            emit('log_content', {'filename': '(ロギング中)',
                 'content': 'ロギングが開始されていません。'}, to=sid)


@socketio.on('upload_attachment')
def handle_upload_attachment(data):
    """クライアントからのファイルアップロードを処理する"""
    sid = request.sid
    if sid not in client_states:
        return

    handler = client_states[sid]
    # 以前の添付情報をクリア
    handler.pending_attachment = None

    if 'user_id' not in handler.user_session:
        emit('attachment_upload_error', {'message': '認証されていません。'})
        return

    filename = data.get('filename')
    file_data = data.get('data')

    if not filename or not file_data:
        emit('attachment_upload_error', {'message': 'ファイル名またはデータがありません。'})
        return

    # --- 設定ファイルから制限を読み込む ---
    limits_config = util.app_config.get('limits', {})

    # ファイルサイズの制限
    max_size_mb = limits_config.get('attachment_max_size_mb', 10)
    max_size_bytes = max_size_mb * 1024 * 1024
    message = ""
    if len(file_data) > max_size_bytes:
        message = f'ファイルサイズが大きすぎます ({max_size_mb}MBまで)。'

    # 許可する拡張子の制限
    if not message:  # ファイルサイズエラーがなければ拡張子をチェック
        allowed_extensions_str = limits_config.get(
            'allowed_attachment_extensions', '')
        allowed_extensions = {ext.strip().lower()
                              for ext in allowed_extensions_str.split(',') if ext.strip()}
        file_ext = os.path.splitext(filename)[1].lstrip('.').lower()
        if allowed_extensions and file_ext not in allowed_extensions:
            message = f'許可されていないファイル形式です。({", ".join(sorted(list(allowed_extensions)))})'

    # エラーがあれば記録して終了
    if message:
        handler.pending_attachment = {'error': message}
        emit('attachment_upload_error', {'message': message})
        return

    # --- 設定ファイルから制限を読み込む ---
    limits_config = util.app_config.get('limits', {})

    # ファイルサイズの制限
    max_size_mb = limits_config.get('attachment_max_size_mb', 10)
    max_size_bytes = max_size_mb * 1024 * 1024
    message = ""
    if len(file_data) > max_size_bytes:
        message = f'ファイルサイズが大きすぎます ({max_size_mb}MBまで)。'

    # 許可する拡張子の制限
    if not message:  # ファイルサイズエラーがなければ拡張子をチェック
        allowed_extensions_str = limits_config.get(
            'allowed_attachment_extensions', '')
        allowed_extensions = {ext.strip().lower()
                              for ext in allowed_extensions_str.split(',') if ext.strip()}
        file_ext = os.path.splitext(filename)[1].lstrip('.').lower()
        if allowed_extensions and file_ext not in allowed_extensions:
            message = f'許可されていないファイル形式です。({", ".join(sorted(list(allowed_extensions)))})'

    # エラーがあれば記録して終了
    if message:
        handler.pending_attachment = {'error': message}
        emit('attachment_upload_error', {'message': message})
        return

    # 安全なファイル名とユニークなファイル名を生成
    _, ext = os.path.splitext(filename)
    unique_filename = f"{uuid.uuid4()}{ext}"
    save_path = os.path.join(ATTACHMENT_DIR, unique_filename)

    try:
        with open(save_path, 'wb') as f:
            f.write(file_data)

        # 成功情報をハンドラに一時保存
        handler.pending_attachment = {
            'unique_filename': unique_filename,
            'original_filename': filename,
            'filepath': save_path,
            'size': len(file_data)
        }

        logging.info(
            f"ファイルがアップロードされました: {filename} -> {unique_filename} (User: {handler.user_session.get('username')})")
        emit('attachment_upload_success', {'original_filename': filename})

    except Exception as e:
        logging.error(f"ファイルアップロード処理中にエラー: {e}", exc_info=True)
        emit('attachment_upload_error', {'message': 'サーバーエラーが発生しました。'})


@socketio.on('clear_pending_attachment')
def handle_clear_pending_attachment():
    """保留中の添付ファイル情報をクリアする"""
    sid = request.sid
    if sid in client_states:
        handler = client_states[sid]
        if handler.pending_attachment:
            logging.info(
                f"保留中の添付ファイルをクリアしました: {handler.pending_attachment.get('original_filename')} (User: {handler.user_session.get('username')})")
            # TODO: もしファイルがDBに保存されなかった場合、ここで物理ファイルを削除するロジックを追加することもできる
            handler.pending_attachment = None


# --- Webサーバーの起動 ---
if __name__ == '__main__':
    # デバッグモードで実行 (開発中に便利)
    # 実際の運用ではGunicornなどのWSGIサーバーを使います
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
