# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
Webアプリケーションルート
 
このモジュールは、ログイン、ログアウト、メインのターミナルページなど、
アプリケーションの標準的なWebルートをすべて定義します。FlaskのBlueprintを
使用してこれらのルートを整理し、コアアプリロジックから分離しています。
"""

from flask import (
    Blueprint, render_template, request, session, redirect, url_for,
    send_from_directory, jsonify, Response, current_app
)
from functools import wraps
import base64
import json
import os
from cryptography.hazmat.primitives import serialization
import time
import logging

from . import util, database, passkey_handler, extensions

web_bp = Blueprint('web', __name__)


def base64url_to_bytes(s: str) -> bytes:
    """Base64URLでエンコードされた文字列をバイトに変換します。必要に応じてパディングを追加します。"""
    s_bytes = s.encode('utf-8')
    rem = len(s_bytes) % 4
    if rem > 0:
        s_bytes += b'=' * (4 - rem)
    return base64.urlsafe_b64decode(s_bytes)


def login_required(f):
    """ユーザーがページにアクセスする前にログインしていることを確認するデコレータ。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('web.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@web_bp.route('/manifest.json')
def manifest():
    """PWAマニフェストファイルを配信します。"""
    return send_from_directory(current_app.static_folder, 'manifest.json')


@web_bp.route('/sw.js')
def service_worker():
    """PWAサービスワーカーファイルを配信します。"""
    response = send_from_directory(current_app.static_folder, 'sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@web_bp.route('/')
@login_required
def index():
    """ログイン済みユーザー向けのメインのターミナルページを描画します。"""
    menu_mode = session.get('menu_mode', '2')
    fkey_definitions = {
        "f1": {"label": "SETTING", "action": "open_popup"},
        "f2": {"label": "LOGGING", "action": "toggle_logging"},
        "f3": {"label": "LOG VIEW", "action": "open_log_viewer"},
        "f4": {"label": "NoFunction", "action": "none"},
        "f5": {"label": "Line Edit", "action": "open_line_editor"},
        "f6": {"label": "M-Line Edit", "action": "open_multiline_editor"},
        "f7": {"label": "BBS LIST", "action": "open_bbs_list"},
        "f8": {"label": "ReConnect", "action": "redirect", "value": url_for('web.login')},
    }
    limits_config = current_app.config.get('LIMITS', {})
    attachment_limits = {
        'max_size_mb': limits_config.get('attachment_max_size_mb', 10),
        'allowed_extensions': limits_config.get('allowed_attachment_extensions', 'jpg,jpeg,png,gif,txt')
    }
    push_config = current_app.config.get('PUSH', {})
    vapid_public_key_for_js = ''
    public_key_path = '/app/public_key.pem'
    if os.path.exists(public_key_path):
        try:
            with open(public_key_path, "rb") as key_file:
                public_key = serialization.load_pem_public_key(key_file.read())
            uncompressed_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.X962,
                format=serialization.PublicFormat.UncompressedPoint
            )
            vapid_public_key_for_js = base64.urlsafe_b64encode(
                uncompressed_bytes).rstrip(b'=').decode('utf-8')
        except Exception as e:
            logging.error(
                f"VAPID public key processing failed: {e}", exc_info=True)

    all_text_data = util.load_master_text_data()
    mobile_button_layouts = all_text_data.get("mobile_button_layouts", {})

    def _process_texts_for_mode(node, mode):
        if isinstance(node, dict):
            mode_key = f"mode_{mode}"
            if mode_key in node:
                return node[mode_key]
            else:
                return {key: _process_texts_for_mode(value, mode) for key, value in node.items()}
        return node

    textData_for_js = {
        "terminal_ui": _process_texts_for_mode(all_text_data.get("terminal_ui", {}), menu_mode),
        "user_pref_menu": _process_texts_for_mode(all_text_data.get("user_pref_menu", {}), menu_mode),
        "passkey_management": _process_texts_for_mode(all_text_data.get("user_pref_menu", {}).get("passkey_management", {}), menu_mode)
    }

    return render_template('terminal.html', fkey_definitions=fkey_definitions, attachment_limits=attachment_limits, vapid_public_key=vapid_public_key_for_js, mobile_button_layouts=mobile_button_layouts, menu_mode=menu_mode, textData=textData_for_js)


@web_bp.route('/login', methods=['GET', 'POST'])
@extensions.limiter.limit("10 per minute")
def login():
    """ユーザーのログイン処理（パスワード認証およびPasskey認証）をハンドリングします。"""
    webapp_config = current_app.config.get('WEBAPP', {})
    page_title = webapp_config.get('LOGIN_PAGE_TITLE', 'Login')
    logo_path = webapp_config.get('LOGIN_PAGE_LOGO_PATH')
    message = webapp_config.get('LOGIN_PAGE_MESSAGE', 'Welcome.')

    if request.method == 'POST':
        username = request.form.get('username', '').upper()
        password = request.form.get('password')
        error = None
        is_guest = username == 'GUEST'
        use_passkey = not password  # パスワードが空ならPasskey認証とみなす

        # Passkey認証フローを開始するためのリダイレクト
        if use_passkey and not is_guest:
            # JavaScriptでPasskeyフローをトリガーするために、ユーザー名をセッションに一時保存してリダイレクト
            session['passkey_login_username'] = username
            # ログインページにリダイレクトし、クライアント側でJSを実行させる
            return redirect(url_for('web.login'))

        if not is_guest and session.get('lockout_expiration', 0) > time.time():
            remaining_time = session.get('lockout_expiration', 0) - time.time()
            error = util.get_text_by_key("auth.account_locked_temporary", session.get(
                'menu_mode', '2')).format(remaining_time=remaining_time)
            return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message), 403

        user_auth_info = database.get_user_auth_info(username)
        auth_success = False
        if user_auth_info and util.verify_password(user_auth_info['password'], user_auth_info['salt'], password):
            auth_success = True

        if auth_success:
            from .terminal_handler import client_states
            if not is_guest:
                for sid, handler in client_states.copy().items():
                    if handler.user_session.get('username') == username:
                        error = util.get_text_by_key("auth.already_logged_in", handler.user_session.get(
                            'menu_mode', '2')).replace('\r\n', '')
                        database.log_access_event(
                            ip_address=request.remote_addr, event_type='LOGIN_FAILURE', username=username, message='Multi-login detected.')
                        return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message), 403

            if not is_guest:
                # セッション固定化攻撃対策: ログイン成功時にセッションを再生成
                session.clear()
                session.permanent = True

                session['login_attempts'] = 0
                session['lockout_expiration'] = 0

            session['lastlogin'] = user_auth_info.get('lastlogin', 0)
            session['user_id'] = user_auth_info['id']
            session['username'] = user_auth_info['name']
            session['userlevel'] = user_auth_info['level']
            session['menu_mode'] = user_auth_info.get('menu_mode', '2')
            logging.info(f"WebUI Login Success: {username}")
            database.log_access_event(ip_address=request.remote_addr, event_type='LOGIN_SUCCESS',
                                      user_id=user_auth_info['id'], username=user_auth_info['name'], display_name=user_auth_info['name'], message='Password authentication successful.')
            database.update_record('users', {'lastlogin': int(time.time())}, {
                                   'id': user_auth_info['id']})
            return redirect(url_for('web.index'))
        else:
            if not is_guest:
                session['login_attempts'] = session.get(
                    'login_attempts', 0) + 1
                if session['login_attempts'] >= current_app.config['MAX_LOGIN_ATTEMPTS']:
                    session['lockout_expiration'] = time.time(
                    ) + current_app.config['LOCKOUT_TIME_SECONDS']
                    lockout_minutes = current_app.config['LOCKOUT_TIME_SECONDS'] / 60
                    error = util.get_text_by_key("auth.account_locked_permanent", session.get(
                        'menu_mode', '2')).format(lockout_minutes=lockout_minutes)
                    database.log_access_event(ip_address=request.remote_addr, event_type='ACCOUNT_LOCKED', username=username,
                                              message=f"Account locked for user '{username}' due to too many failed attempts.")
                else:
                    error = 'IDまたはパスワードが違います。'
            else:
                error = 'IDまたはパスワードが違います。'
            database.log_access_event(ip_address=request.remote_addr, event_type='LOGIN_FAILURE',
                                      username=username, message=f"Invalid password for user '{username}'.")
            logging.warning(f"WebUI Login Failed: {username}")
            return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message)

    # Passkey認証フローのためにリダイレクトされてきた場合の処理
    passkey_username = session.pop('passkey_login_username', None)

    return render_template('login.html', page_title=page_title, logo_path=logo_path,
                           message=message, passkey_username_for_js=passkey_username)


@web_bp.route('/logout')
def logout():
    """ユーザーをログアウトさせ、セッションをクリアします。"""
    menu_mode = session.get('menu_mode', '2')
    session.clear()
    return render_template('logout.html', menu_mode=menu_mode)


@web_bp.route('/passkey/register-options', methods=['POST'])
@login_required
@extensions.limiter.limit("20 per minute")
def passkey_register_options():
    """Passkey登録用のオプションを生成するAPIエンドポイント。"""
    user_id = session.get('user_id')
    username = session.get('username')
    options_json_str = passkey_handler.generate_registration_options_for_user(
        user_id, username)
    options_dict = json.loads(options_json_str)
    session["passkey_registration_challenge"] = options_dict.get("challenge")
    return Response(options_json_str, mimetype='application/json')


@web_bp.route('/passkey/verify-registration', methods=['POST'])
@login_required
@extensions.limiter.limit("10 per minute")
def passkey_verify_registration():
    """Passkey登録レスポンスを検証するAPIエンドポイント。"""
    user_id = session.get('user_id')
    challenge_str = session.pop("passkey_registration_challenge", None)
    challenge_bytes = base64url_to_bytes(challenge_str)
    data = request.get_json()
    credential_json = json.dumps(data['credential'])
    nickname = data['nickname']
    success = passkey_handler.verify_registration_for_user(
        user_id, credential_json, challenge_bytes, request.url_root.rstrip('/'), nickname)
    if success:
        return jsonify({"verified": True})
    else:
        return jsonify({"verified": False, "error": "Verification failed on server"}), 400


@web_bp.route('/passkey/login-options', methods=['POST'])
@extensions.limiter.limit("20 per minute")
def passkey_login_options():
    """Passkey認証用のオプションを生成するAPIエンドポイント。"""
    username = request.get_json().get('username', '').upper()
    options_json_str = passkey_handler.generate_authentication_options_for_user(
        username)
    if not options_json_str:
        return jsonify({"error": "User not found or no passkeys registered for that user."}), 400
    options_dict = json.loads(options_json_str)
    session["passkey_login_challenge"] = options_dict.get("challenge")
    return Response(options_json_str, mimetype='application/json')


@web_bp.route('/passkey/verify-login', methods=['POST'])
@extensions.limiter.limit("10 per minute")
def passkey_verify_login():
    """Passkey認証レスポンスを検証し、ユーザーをログインさせるAPIエンドポイント。"""
    challenge_str = session.pop("passkey_login_challenge", None)
    challenge_bytes = base64url_to_bytes(challenge_str)
    credential_json = json.dumps(request.get_json())
    user_data = passkey_handler.verify_authentication_for_user(
        credential_json, challenge_bytes, request.url_root.rstrip('/'))
    if user_data:
        # セッション固定化攻撃対策: ログイン成功時にセッションを再生成
        session.clear()
        session.permanent = True

        session['lastlogin'] = user_data.get('lastlogin', 0)
        session['user_id'] = user_data['id']
        session['username'] = user_data['name']
        session['userlevel'] = user_data['level']
        session['menu_mode'] = user_data.get('menu_mode', '2')
        database.log_access_event(ip_address=request.remote_addr, event_type='LOGIN_SUCCESS',
                                  user_id=user_data['id'], username=user_data['name'], display_name=user_data['name'], message='Passkey authentication successful.')
        database.update_record('users', {'lastlogin': int(time.time())}, {
                               'id': user_data['id']})
        return jsonify({"verified": True})
    else:
        return jsonify({"verified": False, "error": "Authentication failed"}), 401


@web_bp.route('/attachments/<path:filename>')
@login_required
def download_attachment(filename):
    """アップロード済みの添付ファイルまたはそのサムネイルを配信します。"""
    is_thumbnail = filename.startswith('thumbnails/')
    actual_filename = filename.replace(
        'thumbnails/', '') if is_thumbnail else filename

    # データベースからファイル名に一致する記事情報を取得
    article = database.get_article_by_attachment_filename(actual_filename)

    if not is_thumbnail and article and article.get('attachment_originalname'):
        # 元のファイルをダウンロードする場合、元のファイル名を使用
        download_name = article['attachment_originalname']
        as_attachment = True
    else:
        # サムネイル表示またはDBに情報がない場合は、そのまま表示
        download_name = None
        as_attachment = False

    attachment_dir = current_app.config.get('ATTACHMENT_DIR')
    return send_from_directory(attachment_dir, filename, as_attachment=as_attachment, download_name=download_name)


@web_bp.route('/download_log/<path:filename>')
@login_required
def download_log(filename):
    """保存されたセッションログファイルをダウンロード用に配信します。"""
    session_log_dir = current_app.config.get('SESSION_LOG_DIR')
    return send_from_directory(session_log_dir, filename, as_attachment=True)


@web_bp.route('/plugins/<plugin_id>/js/<path:filename>')
@login_required
def serve_plugin_js(plugin_id, filename):
    """プラグイン専用のJavaScriptファイルを配信します。"""
    # パストラバーサル攻撃を防ぐための基本的な検証
    if '..' in plugin_id or '/' in plugin_id or '\\' in plugin_id:
        return "Invalid plugin ID", 400
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400

    plugin_js_dir = os.path.join(
        current_app.config['PLUGINS_DIR'], plugin_id, 'js')
    return send_from_directory(plugin_js_dir, filename)


@web_bp.route('/plugins/<plugin_id>/static/<path:filename>')
@login_required
def serve_plugin_static(plugin_id, filename):
    """プラグイン専用の静的ファイル(CSS,画像など)を配信します。"""
    # パストラバーサル攻撃を防ぐための基本的な検証
    if '..' in plugin_id or '/' in plugin_id or '\\' in plugin_id:
        return "Invalid plugin ID", 400
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400

    plugin_static_dir = os.path.join(
        current_app.config['PLUGINS_DIR'], plugin_id, 'static')
    return send_from_directory(plugin_static_dir, filename)
