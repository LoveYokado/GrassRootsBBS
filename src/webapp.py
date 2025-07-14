# /home/yuki/python/GrassRootsBBS/webapp.py

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit
import os
import secrets
import logging
import sys
from functools import wraps
import datetime
import threading
import collections
import unicodedata
# このファイルは 'src' ディレクトリ内にあるため、他の 'src' 内のモジュールは直接インポートできます。
import util
import sqlite_tools
import bbs_manager
import command_dispatcher

# --- プロジェクトルートとパスの設定 ---
# このファイルの絶対パスから、プロジェクトのルートディレクトリを特定します。
_current_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_current_dir)

# --- Flaskアプリケーションのセットアップ ---
# Flaskにtemplatesフォルダの場所を教えます（プロジェクトルート直下）。
app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, 'templates'))
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
        self.input_buffer = ""
        self.command_history = collections.deque(maxlen=50)
        self.history_index = -1
        self.speed = 'full'
        self.bps_delay = 0
        self.output_queue = collections.deque()
        self.stop_worker_event = threading.Event()

        # SSHの `paramiko.Channel` のように振る舞うアダプタクラス
        class WebChannel:
            def __init__(self, handler_instance):
                self.handler = handler_instance

            def send(self, data):
                # dataはstrかbytes。WebSocketではstrをemitする必要がある。
                if isinstance(data, bytes):
                    text_to_send = data.decode('utf-8', 'ignore')
                else:
                    text_to_send = str(data)

                # ワーカースレッドが処理するようにキューに追加する
                self.handler.output_queue.append(text_to_send)

            def getpeername(self):
                # sessionからIPを取得するのは難しいのでダミーを返す
                return ('127.0.0.1', 12345)

        self.channel = WebChannel(self)
        socketio.start_background_task(self._sender_worker)

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
                socketio.sleep(0.01)  # キューが空なら待機

    def stop_worker(self):
        """ワーカースレッドを停止させる"""
        self.stop_worker_event.set()

    def show_prompt(self):
        """現在の状態に応じたプロンプトを表示する"""
        username = self.user_session.get('username', 'user')
        prompt = f"\r\n{username}> "
        self.output_queue.append(prompt)

    def handle_command(self, command):
        """入力されたコマンドを処理する"""
        # 空のコマンドは履歴に追加しない
        if command:
            # 履歴の先頭が同じコマンドでなければ追加
            if not self.command_history or self.command_history[0] != command:
                self.command_history.appendleft(command)
        self.history_index = -1  # コマンド実行後は履歴インデックスをリセット

        # command_dispatcher に渡すためのコンテキストを作成
        context = {
            'chan': self.channel,
            'dbname': self.db_name,
            'login_id': self.user_session.get('username'),
            # Webでは表示名はログインIDと同じ
            'display_name': self.user_session.get('username'),
            'user_id': self.user_session.get('user_id'),
            'userlevel': self.user_session.get('userlevel'),
            'server_pref_dict': {},  # TODO: 必要に応じてDBから読み込む
            'addr': self.channel.getpeername(),
            'menu_mode': self.user_session.get('menu_mode', '2'),
            'online_members_func': lambda: {},  # TODO: WebとSSHで共有する仕組みが必要
        }

        result = command_dispatcher.dispatch_command(command, context)

        if result.get('status') == 'logoff':
            util.send_text_by_key(
                self.channel, "logoff.message", context['menu_mode'])
            socketio.disconnect(self.sid)
            return

        # コマンド処理後にプロンプトを再表示
        self.show_prompt()

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
        return render_template('login.html', error=error)

    # GETリクエストの場合はログインフォームを表示
    return render_template('login.html')


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
        f"WebTerminal client connected: {session.get('username')} (sid: {sid})")

    # ウェルカムメッセージとトップメニュー表示
    util.send_text_by_key(handler.channel, "login.welcome_message_webapp",
                          handler.user_session.get('menu_mode', '2'))
    util.send_text_by_key(handler.channel, "top_menu.menu",
                          handler.user_session.get('menu_mode', '2'))
    handler.show_prompt()


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
    sid = request.sid
    if sid in client_states:
        client_states[sid].stop_worker()
        del client_states[sid]
    logging.info(
        f"WebTerminal client disconnected: {session.get('username')} (sid: {sid})")


@socketio.on('client_input')
def handle_client_input(data):
    """クライアントからの入力を受け取り、処理する"""
    sid = request.sid
    if sid not in client_states:
        return  # 状態がない場合は何もしない

    handler = client_states[sid]
    username = handler.user_session.get('username', 'user')
    prompt = f"{username}> "

    # --- エスケープシーケンス処理 (矢印キーなど) ---
    if data == '\x1b[A':  # 上矢印
        if handler.history_index < len(handler.command_history) - 1:
            handler.history_index += 1
            new_buffer = handler.command_history[handler.history_index]
            handler.input_buffer = new_buffer
            # 行をクリアして新しいバッファの内容を表示
            handler.output_queue.append(f'\r{prompt}\x1b[K{new_buffer}')
        return
    elif data == '\x1b[B':  # 下矢印
        if handler.history_index > 0:
            handler.history_index -= 1
            new_buffer = handler.command_history[handler.history_index]
            handler.input_buffer = new_buffer
            handler.output_queue.append(f'\r{prompt}\x1b[K{new_buffer}')
        elif handler.history_index <= 0:  # 履歴の末尾または履歴がない場合
            handler.history_index = -1
            handler.input_buffer = ""
            handler.output_queue.append(f'\r{prompt}\x1b[K')
        return

    # --- 通常のキー入力処理 ---
    elif data == '\r' or data == '\n':  # Enterキー
        command = handler.input_buffer
        handler.output_queue.append('\r\n')  # 改行をエコー

        # ハンドラにコマンドを渡して処理
        handler.handle_command(command)

        handler.input_buffer = ""  # バッファをクリア

    elif data == '\x7f' or data == '\x08':  # Backspace or Delete
        if handler.input_buffer:
            last_char = handler.input_buffer[-1]
            handler.input_buffer = handler.input_buffer[:-1]
            width = 2 if unicodedata.east_asian_width(
                last_char) in ('F', 'W', 'A') else 1
            backspace_sequence = ('\b \b') * width
            handler.output_queue.append(backspace_sequence)

    else:  # 通常の文字
        # 制御文字は無視 (エスケープシーケンスは上で処理済み)
        if not data.startswith('\x1b') and not unicodedata.category(data[0]).startswith('C'):
            handler.input_buffer += data
            handler.output_queue.append(data)  # 入力された文字をエコー


# --- HTMLテンプレートの準備 ---
# Flaskにtemplatesフォルダの場所を教えたので、その場所にファイルを作成します。
templates_dir = os.path.join(PROJECT_ROOT, 'templates')
if not os.path.exists(templates_dir):
    os.makedirs(templates_dir)

login_html_path = os.path.join(templates_dir, 'login.html')
if not os.path.exists(login_html_path):
    with open(login_html_path, 'w', encoding='utf-8') as f:
        f.write("""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>ログイン</title>
</head>
<body>
    <h2>ログイン</h2>
    {% if error %}
        <p style="color: red;">{{ error }}</p>
    {% endif %}
    <form method="post">
        <label for="username">ID:</label><br>
        <input type="text" id="username" name="username" required><br><br>
        <label for="password">パスワード:</label><br>
        <input type="password" id="password" name="password" required><br><br>
        <button type="submit">ログイン</button>
    </form>
</body>
</html>
""")

# --- Webサーバーの起動 ---
if __name__ == '__main__':
    # デバッグモードで実行 (開発中に便利)
    # 実際の運用ではGunicornなどのWSGIサーバーを使います
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
