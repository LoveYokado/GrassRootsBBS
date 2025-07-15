# /home/yuki/python/GrassRootsBBS/src/webapp.py

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, disconnect
import os
import secrets
import logging
import sys
from functools import wraps
import datetime
import threading
import socket
import collections
import unicodedata
# このファイルは 'src' ディレクトリ内にあるため、他の 'src' 内のモジュールは直接インポートできます。
import util
import sqlite_tools
import bbs_manager
import command_dispatcher
import ssh_input

# --- プロジェクトルートとパスの設定 ---
# このファイルの絶対パスから、プロジェクトのルートディレクトリを特定します。
_current_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_current_dir)

# --- Flaskアプリケーションのセットアップ ---
# Flaskにtemplatesフォルダの場所を教えます（プロジェクトルート直下）。
app = Flask(__name__, template_folder=os.path.join(
    PROJECT_ROOT, 'templates'), static_folder=os.path.join(PROJECT_ROOT, 'static'))
# セッション管理のために、ランダムな秘密鍵を設定します
app.secret_key = secrets.token_hex(16)
# WebSocketのためのSocketIOラッパー
socketio = SocketIO(app)

# --- 初期設定 ---
# 既存の設定ファイルを読み込みます
try:
    config_path = os.path.join(PROJECT_ROOT, 'setting', 'config.toml')
    util.load_app_config_from_path(config_path)
    db_path_relative = util.app_config.get('paths', {}).get('db_name')
    if not db_path_relative:
        raise ValueError("データベース名が設定ファイルに見つかりません。")
    DB_NAME = os.path.join(PROJECT_ROOT, db_path_relative)
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


class WebTerminalHandler:
    """Webターミナルセッションの状態とロジックを管理するクラス"""

    def __init__(self, sid, db_name, user_session):
        self.sid = sid
        self.db_name = db_name
        self.user_session = user_session
        self.speed = 'full'
        self.bps_delay = 0
        self.output_queue = collections.deque()
        self.input_queue = collections.deque()
        self.input_event = threading.Event()
        self.stop_worker_event = threading.Event()
        self.main_thread_active = True

        # SSHの `paramiko.Channel` のように振る舞うアダプタクラス
        class WebChannel:
            def __init__(self, handler_instance):
                self.handler = handler_instance
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
                # sessionからIPを取得するのは難しいのでダミーを返す
                return ('127.0.0.1', 12345)

            def close(self):
                self.active = False
                self.handler.input_event.set()  # Waiting recv() should be unblocked

        self.channel = WebChannel(self)
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
        try:
            # ウェルカムメッセージとトップメニュー表示
            util.send_text_by_key(self.channel, "login.welcome_message_webapp",
                                  self.user_session.get('menu_mode', '2'))
            util.send_text_by_key(self.channel, "top_menu.menu",
                                  self.user_session.get('menu_mode', '2'))

            # server.pyのprocess_command_loopを模倣
            while self.main_thread_active:
                context = {
                    'chan': self.channel,
                    'dbname': self.db_name,
                    'login_id': self.user_session.get('username'),
                    'display_name': self.user_session.get('username'),
                    'user_id': self.user_session.get('user_id'),
                    'userlevel': self.user_session.get('userlevel'),
                    'server_pref_dict': {},  # TODO: 必要に応じてDBから読み込む
                    'addr': self.channel.getpeername(),
                    'menu_mode': self.user_session.get('menu_mode', '2'),
                    'online_members_func': lambda: {},  # TODO: WebとSSHで共有する仕組みが必要
                }

                util.send_text_by_key(
                    self.channel, "prompt.topmenu", context['menu_mode'], add_newline=False)

                command = ssh_input.process_input(self.channel)

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
    return render_template('terminal.html')


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

        # 既存の認証ロジックを再利用
        user_auth_info = sqlite_tools.get_user_auth_info(DB_NAME, username)

        if user_auth_info:
            pbkdf2_rounds = util.app_config.get(
                'security', {}).get('PBKDF2_ROUNDS', 100000)
            if util.verify_password(user_auth_info['password'], user_auth_info['salt'], password, pbkdf2_rounds):
                # 認証成功
                session['user_id'] = user_auth_info['id']
                session['username'] = user_auth_info['name']
                session['userlevel'] = user_auth_info['level']
                logging.info(f"WebUI Login Success: {username}")
                return redirect(url_for('index'))

        # 認証失敗
        error = 'IDまたはパスワードが違います。'
        logging.warning(f"WebUI Login Failed: {username}")
        return render_template('login.html',
                               error=error,
                               page_title=page_title,
                               logo_path=logo_path,
                               message=message)

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

    sid = request.sid
    # ユーザーセッション情報を辞書としてハンドラに渡す
    user_session_data = {
        'user_id': session.get('user_id'),
        'username': session.get('username'),
        'userlevel': session.get('userlevel'),
        'menu_mode': '2'  # WebUIのメニューモードは '2' に固定
    }
    handler = WebTerminalHandler(sid, DB_NAME, user_session_data)
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


# --- Webサーバーの起動 ---
if __name__ == '__main__':
    # デバッグモードで実行 (開発中に便利)
    # 実際の運用ではGunicornなどのWSGIサーバーを使います
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
