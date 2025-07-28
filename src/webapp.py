# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado) <hogehoge@gmail.com>
# SPDX-License-Identifier: MIT
# # /home/yuki/python/GrassRootsBBS/src/webapp.py

# Gunicorn + gevent で WebSocket を動作させるために必須
# monkey.patch_all() は、他の標準ライブラリ(socket, threadingなど)を
# インポートする前に、可能な限り早く呼び出す必要があります。
from . import bbs_manager, command_dispatcher, sqlite_tools, util
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_socketio import SocketIO, emit, disconnect
from flask_session import Session
from flask import (Flask, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
import redis
from functools import wraps
import time
import threading
import sys
import socket
import secrets
import os
import logging
import datetime
from logging.handlers import RotatingFileHandler
import collections
import codecs
from gevent import monkey
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
    db_path_relative = util.app_config.get('paths', {}).get('db_name')
    if not db_path_relative:
        raise ValueError("データベース名が設定ファイルに見つかりません。")
    DB_NAME = os.path.join(PROJECT_ROOT, db_path_relative)
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
    error_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'))
    logging.getLogger().addHandler(error_handler)
    logging.getLogger().setLevel(logging.INFO)

    # --- データベース初期化チェック ---
    if not os.path.isfile(DB_NAME):
        logging.info(f"データベースファイル '{DB_NAME}' が見つかりません。初期化を実行します。")
        # 環境変数からシスオペ情報を取得
        sysop_id_from_env = os.getenv('GRASSROOTSBBS_SYSOP_ID')
        sysop_password_from_env = os.getenv('GRASSROOTSBBS_SYSOP_PASSWORD')
        sysop_email_from_env = os.getenv('GRASSROOTSBBS_SYSOP_EMAIL')

        if not (sysop_id_from_env and sysop_password_from_env and sysop_email_from_env):
            logging.critical(
                "初回起動には環境変数 GRASSROOTSBBS_SYSOP_ID, GRASSROOTSBBS_SYSOP_PASSWORD, GRASSROOTSBBS_SYSOP_EMAIL が必要です。")
            # Webアプリの場合、ここで終了するとコンテナが再起動ループに陥る可能性があるためエラーログに留める
        else:
            try:
                util.make_sysop_and_database(
                    DB_NAME, sysop_id_from_env, sysop_password_from_env, sysop_email_from_env)
                logging.info(f"データベースとシスオペ '{sysop_id_from_env}' の初期化が完了しました。")
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

    def __init__(self, sid, db_name, user_session, ip_address):
        self.sid = sid
        self.db_name = db_name
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
                            if line_buffer:
                                line_buffer.pop()  # 最後の「文字」を削除
                                if echo:
                                    # xterm.jsは文字幅を考慮してカーソルを戻してくれる
                                    self.send(b'\x08 \x08')
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
            pref_list = sqlite_tools.read_server_pref(self.db_name)
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
            util.send_text_by_key(self.channel, "top_menu.menu",
                                  self.user_session.get('menu_mode', '2'))

            while self.main_thread_active:
                # プロンプト前の定型処理 (メール/電報通知)
                _, self.mail_notified_this_session = util.prompt_handler(
                    self.channel, self.db_name, self.user_session.get(
                        'username'),
                    self.user_session.get(
                        'menu_mode', '2'), self.mail_notified_this_session
                )

                context = {
                    'chan': self.channel,
                    'dbname': self.db_name,
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

                command = command.strip().lower()
                if not command:
                    util.send_text_by_key(
                        self.channel, "top_menu.menu", context['menu_mode'])
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
                    util.send_text_by_key(
                        self.channel, "top_menu.menu", self.user_session['menu_mode'])

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

@app.route('/')
@login_required
def index():
    """ターミナルページを表示"""
    # url_forはリクエストコンテキスト内で呼び出す必要がある
    fkey_definitions = {
        "f1": {"label": "SETTING", "action": "open_popup"},
        "f2": {"label": "LOGGING", "action": "toggle_logging"},
        "f3": {"label": "NoFunction", "action": "none"},  # フルスクリーン機能は設定メニューに移動
        "f4": {"label": "NoFunction", "action": "none"},  # 予約
        "f5": {"label": "Line Edit", "action": "open_line_editor"},
        "f6": {"label": "M-Line Edit", "action": "open_multiline_editor"},
        "f8": {"label": "ReConnect", "action": "redirect", "value": url_for('login')},
    }
    return render_template('terminal.html', fkey_definitions=fkey_definitions)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """ログインページ"""
    webapp_config = util.app_config.get('webapp', {})
    page_title = webapp_config.get('LOGIN_PAGE_TITLE', 'Login')
    logo_path = webapp_config.get('LOGIN_PAGE_LOGO_PATH')
    message = webapp_config.get('LOGIN_PAGE_MESSAGE', 'Welcome.')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        error = None

        # GUESTアカウントはロックアウト対象外
        is_guest = username.upper() == 'GUEST'

        if not is_guest:
            # ロックアウト状態かチェック
            if session.get('lockout_expiration', 0) > time.time():
                remaining_time = session.get(
                    'lockout_expiration', 0) - time.time()
                error = f"アカウントは一時的にロックされています。{remaining_time:.0f}秒後に再試行してください。"
                logging.warning(
                    f"ログイン試行失敗: アカウントロック中 {username} (残り{remaining_time:.0f}秒)")
                return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message)

        # 既存の認証ロジックを再利用
        user_auth_info = sqlite_tools.get_user_auth_info(DB_NAME, username)

        auth_success = False
        if user_auth_info:
            pbkdf2_rounds = util.app_config.get(
                'security', {}).get('PBKDF2_ROUNDS', 100000)
            if util.verify_password(user_auth_info['password'], user_auth_info['salt'], password, pbkdf2_rounds):
                auth_success = True

        if auth_success:
            # 認証成功
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
            sqlite_tools.update_idbase(DB_NAME, 'users', [
                                       'lastlogin'], user_auth_info['id'], 'lastlogin', int(time.time()))

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
                    error = f"アカウントはロックされました。{app.config['LOCKOUT_TIME']/60:.0f}分後に再試行してください。"
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
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('userlevel', None)
    return redirect(url_for('login'))


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
                logging.warning(f"WebUIでのマルチログインが試みられました: {username_to_connect} from {request.remote_addr}")
                # クライアントに通知して切断させる
                logoff_message_text = util.get_text_by_key("auth.already_logged_in", session.get('menu_mode', '2'))
                processed_text = logoff_message_text.replace('\r\n', '\n').replace('\n', '\r\n')
                emit('force_disconnect', {'message': processed_text})
                return False # 接続を拒否

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
    logging.getLogger('grbbs.access').info(f"CONNECT - User: {username}, DisplayName: {display_name}, IP: {ip_addr}, SID: {request.sid}")

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
    handler = WebTerminalHandler(sid, DB_NAME, user_session_data, ip_addr)
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
        display_name = client_states[sid].user_session.get('display_name', username)
    logging.getLogger('grbbs.access').info(f"DISCONNECT - User: {username}, DisplayName: {display_name}, SID: {sid}")

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
        display_name_for_log = handler.user_session.get('display_name', handler.user_session.get('username'))
        # ファイル名として安全な文字列に変換
        safe_display_name = display_name_for_log.replace('(', '_').replace(')', '')
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


# --- Webサーバーの起動 ---
if __name__ == '__main__':
    # デバッグモードで実行 (開発中に便利)
    # 実際の運用ではGunicornなどのWSGIサーバーを使います
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
