# /home/yuki/python/GrassRootsBBS/webapp.py

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit
import os
import secrets
import logging
import sys
from functools import wraps
import datetime
import unicodedata
# このファイルは 'src' ディレクトリ内にあるため、他の 'src' 内のモジュールは直接インポートできます。
import util
import sqlite_tools
import bbs_manager

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
# {sid: {"input_buffer": "..."}}
client_states = {}

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
def handle_connect():
    """クライアント接続時の処理"""
    if 'user_id' not in session:
        return False  # 未認証ユーザーは接続を拒否

    sid = request.sid
    client_states[sid] = {"input_buffer": ""}

    logging.info(
        f"WebTerminal client connected: {session.get('username')} (sid: {sid})")
    # 接続時にウェルカムメッセージを送信
    emit('server_output', 'Welcome to GR-BBS Web Terminal!\r\n')
    emit('server_output', f"{session.get('username')}> ")


@socketio.on('disconnect')
def handle_disconnect():
    """クライアント切断時の処理"""
    sid = request.sid
    if sid in client_states:
        del client_states[sid]
    logging.info(
        f"WebTerminal client disconnected: {session.get('username')} (sid: {sid})")


@socketio.on('client_input')
def handle_client_input(data):
    """クライアントからの入力を受け取り、処理する"""
    sid = request.sid
    if sid not in client_states:
        return  # 状態がない場合は何もしない

    state = client_states[sid]
    input_buffer = state.get("input_buffer", "")

    if data == '\r' or data == '\n':  # Enterキー
        command = input_buffer
        emit('server_output', '\r\n')  # 改行をエコー

        # (将来のコマンド処理ロジック)
        emit('server_output', f"Command received: {command}\r\n")

        emit('server_output', f"{session.get('username')}> ")
        state["input_buffer"] = ""  # バッファをクリア

    elif data == '\x7f' or data == '\x08':  # Backspace or Delete
        if input_buffer:
            last_char = input_buffer[-1]
            input_buffer = input_buffer[:-1]
            width = 2 if unicodedata.east_asian_width(
                last_char) in ('F', 'W', 'A') else 1
            backspace_sequence = ('\b \b') * width
            emit('server_output', backspace_sequence)
            state["input_buffer"] = input_buffer
    else:  # 通常の文字
        if not unicodedata.category(data[0]).startswith('C'):
            input_buffer += data
            emit('server_output', data)  # 入力された文字をエコー
            state["input_buffer"] = input_buffer


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
