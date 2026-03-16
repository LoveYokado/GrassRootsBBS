# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""Webアプリケーションのルート定義。

このモジュールは、ログイン、ログアウト、メインのターミナルページといった、
アプリケーションの標準的なWebルートを定義します。FlaskのBlueprintを
使用して、これらのルートをコアロジックから分離し、整理しています。
"""

from flask import (
    Blueprint, render_template, request, session, redirect, url_for,
    send_from_directory, jsonify, Response, current_app, flash
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
    """Base64URLでエンコードされた文字列をバイト列にデコードします。"""
    s_bytes = s.encode('utf-8')
    rem = len(s_bytes) % 4
    if rem > 0:
        s_bytes += b'=' * (4 - rem)
    return base64.urlsafe_b64decode(s_bytes)


def login_required(f):
    """ログイン必須を強制するデコレータ。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('web.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def check_maintenance(f):
    """メンテナンスモードをチェックするデコレータ。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        server_prefs = database.read_server_pref()
        if server_prefs.get('maintenance_mode'):
            # メンテナンスモードが有効
            user_level = session.get('userlevel', 0)
            if user_level < 5:
                # 管理者でなければメンテナンスページへ
                return render_template('maintenance.html')
        # メンテナンスモードが無効、または管理者であれば通常通り処理
        return f(*args, **kwargs)
    return decorated_function


@web_bp.route('/manifest.json')
def manifest():
    """PWA (Progressive Web App) のマニフェストファイルを配信します。"""
    return send_from_directory(current_app.static_folder, 'manifest.json')


@web_bp.route('/sw.js')
def service_worker():
    """PWAのService Workerファイルを配信します。"""
    response = send_from_directory(current_app.static_folder, 'sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@web_bp.route('/vapid-public-key', methods=['GET'])
@login_required
def vapid_public_key():
    """VAPID公開鍵をクライアントに提供します。"""
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
            return jsonify({'public_key': vapid_public_key_for_js})
        except Exception as e:
            logging.error(
                f"VAPID public key processing failed: {e}", exc_info=True)
            return jsonify({'error': 'Failed to process VAPID public key'}), 500
    return jsonify({'error': 'VAPID public key not found'}), 404


@web_bp.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    """プッシュ通知の購読情報を保存します。"""
    subscription_info = request.get_json()
    if not subscription_info:
        return jsonify({'error': 'Subscription information is missing'}), 400

    user_id = session.get('user_id')
    subscription_json = json.dumps(subscription_info)

    database.save_push_subscription(user_id, subscription_json)
    logging.info(f"User {user_id} subscribed to push notifications.")

    # 購読成功時にテスト通知を送信
    try:
        title = util.get_text_by_key(
            'push_notifications.test_subscribe.title', session.get('menu_mode', '2'), 'GR-BBS')
        body = util.get_text_by_key(
            'push_notifications.test_subscribe.body', session.get('menu_mode', '2'), 'Push notifications enabled!')
        test_payload = json.dumps({"title": title, "body": body})
        util.send_push_notification(subscription_json, test_payload)
    except Exception as e:
        logging.error(f"テストプッシュ通知の送信に失敗しました: {e}", exc_info=True)

    return jsonify({'success': True}), 201


@web_bp.route('/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    """プッシュ通知の購読情報を削除します。"""
    data = request.get_json()
    endpoint = data.get('endpoint')
    if not endpoint:
        return jsonify({'error': 'Endpoint is missing'}), 400

    user_id = session.get('user_id')
    database.delete_push_subscription(user_id, endpoint)
    logging.info(
        f"User {user_id} unsubscribed from push notifications.")
    return jsonify({'success': True}), 200


@web_bp.route('/')
@login_required
@check_maintenance
def index():
    """メインのターミナルページを描画します。"""
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

    return render_template('terminal.html', fkey_definitions=fkey_definitions, attachment_limits=attachment_limits, vapid_public_key=vapid_public_key_for_js, mobile_button_layouts=mobile_button_layouts, menu_mode=menu_mode, textData=textData_for_js, user_level=session.get('userlevel', 0))


@web_bp.route('/login', methods=['GET', 'POST'])
@extensions.limiter.limit("10 per minute")
def login():
    """ログインページの表示と認証処理をハンドリングします。"""
    # ブラウザの言語設定からロケールを取得 (ja or en)
    locale = 'ja' if request.accept_languages.best_match(['ja']) else 'en'

    site_info = database.read_server_pref() or {}
    webapp_config = current_app.config.get('WEBAPP', {})
    # config.tomlからサイト名を取得し、なければデフォルト値を設定
    page_title = site_info.get('server_name', 'GR-BBS')
    message = util.get_text_by_key('login_page.message', locale, 'Welcome.')

    logo_path = webapp_config.get('LOGIN_PAGE_LOGO_PATH')

    if request.method == 'POST':
        server_prefs = database.read_server_pref()
        if server_prefs.get('maintenance_mode'):
            # メンテナンスモード中は管理者(level 5)のみログイン試行を許可
            username_to_check = request.form.get('username', '').upper()
            user_to_check = database.get_user_auth_info(username_to_check)
            if not user_to_check or user_to_check.get('level', 0) < 5:
                return render_template('maintenance.html')

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
            server_prefs = database.read_server_pref()
            error = util.get_text_by_key("auth.account_locked_temporary", server_prefs.get('menu_mode', session.get('menu_mode', locale)),
                                         default_value="Account is temporarily locked. Please try again in {remaining_time:.0f} seconds.").format(remaining_time=remaining_time)
            return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message), 403

        user_auth_info = database.get_user_auth_info(username)
        auth_success = False
        if user_auth_info and util.verify_password(user_auth_info['password'], user_auth_info['salt'], password):
            auth_success = True

        if auth_success:
            from .terminal_handler import client_states
            if not is_guest:
                for sid, handler in client_states.copy().items():
                    server_prefs = database.read_server_pref()
                    if handler.user_session.get('username') == username and server_prefs.get('menu_mode', handler.user_session.get('menu_mode', '2')):
                        error = util.get_text_by_key("auth.already_logged_in", handler.user_session.get(  # noqa
                            'menu_mode', '2')).replace('\r\n', '')
                        database.log_access_event(ip_address=util.get_client_ip(),
                                                  event_type='LOGIN_FAILURE', username=username, message='Multi-login detected.')
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
            # User-Agentを見てモバイル判定
            user_agent = request.user_agent.string.lower()
            is_mobile = 'mobi' in user_agent or 'android' in user_agent or 'iphone' in user_agent
            if is_mobile:
                session['menu_mode'] = '4'
            else:
                session['menu_mode'] = user_auth_info.get('menu_mode', '2')
            logging.info(f"WebUI Login Success: {username}")
            database.log_access_event(ip_address=util.get_client_ip(),
                                      event_type='LOGIN_SUCCESS',
                                      user_id=user_auth_info['id'], username=user_auth_info['name'], display_name=user_auth_info['name'], message='Password authentication successful.')
            database.update_record('users', {'lastlogin': int(time.time())}, {
                                   'id': user_auth_info['id']})
            return redirect(url_for('web.index'))
        else:
            if not is_guest:
                server_prefs = database.read_server_pref()
                session['login_attempts'] = session.get(
                    'login_attempts', 0) + 1
                if session['login_attempts'] >= server_prefs.get('max_password_attempts', 3):
                    session['lockout_expiration'] = time.time(
                    ) + server_prefs.get('lockout_time_seconds', 300)
                    lockout_minutes = current_app.config['LOCKOUT_TIME_SECONDS'] / 60
                    error = util.get_text_by_key("auth.account_locked_permanent", locale).format(
                        lockout_minutes=lockout_minutes)
                    database.log_access_event(ip_address=util.get_client_ip(),
                                              event_type='ACCOUNT_LOCKED', username=username,
                                              message=f"Account locked for user '{username}' due to too many failed attempts.")
                else:
                    error = util.get_text_by_key(
                        'login_page.invalid_credentials', locale, 'Invalid ID or password.')
            else:
                error = util.get_text_by_key(
                    'login_page.invalid_credentials', locale, 'Invalid ID or password.')
            database.log_access_event(ip_address=util.get_client_ip(),
                                      event_type='LOGIN_FAILURE',
                                      username=username, message=f"Invalid password for user '{username}'.")
            logging.warning(f"WebUI Login Failed: {username}")
            return render_template('login.html', error=error, page_title=page_title, logo_path=logo_path, message=message, lang=locale)

    # Passkey認証フローのためにリダイレクトされてきた場合の処理
    passkey_username = session.pop('passkey_login_username', None)

    # --- Proxy/VPN/Torチェック ---
    server_prefs = database.read_server_pref()
    if server_prefs.get('block_proxies', False):
        remote_ip_str = util.get_client_ip()
        if remote_ip_str:
            is_proxy, reason = util.is_proxy_connection(remote_ip_str)
            if is_proxy:
                logging.warning(
                    f"Proxy/VPN/Torからのアクセスをブロックしました。IP: {remote_ip_str}, Reason: {reason}")
                database.log_access_event(
                    ip_address=remote_ip_str, event_type='PROXY_BLOCKED',
                    username=username, display_name=username,
                    message=f"Blocked proxy/hosting access ({reason})."
                )
    return render_template('login.html', page_title=page_title, logo_path=logo_path, message=message,
                           passkey_username_for_js=passkey_username, lang=locale)


@web_bp.route('/logout')
def logout():
    """ログアウト処理を行い、ユーザーセッションをクリアします。"""
    # ログアウト前にロケールを取得
    locale = 'ja' if request.accept_languages.best_match(['ja']) else 'en'
    session.clear()
    return render_template('logout.html', lang=locale)


@web_bp.route('/privacy')
def privacy_policy():
    """プライバシーポリシーページを表示します。"""
    site_info = database.read_server_pref() or {}
    locale = 'ja' if request.accept_languages.best_match(['ja']) else 'en'
    return render_template('privacy_policy.html', lang=locale, site_info=site_info)


@web_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    """お問い合わせフォームの表示と、メッセージの送信処理を行います。"""
    site_info = database.read_server_pref() or {}
    locale = 'ja' if request.accept_languages.best_match(['ja']) else 'en'
    text_data = {
        'all_fields_required': util.get_text_by_key('contact_page.all_fields_required', locale, 'All fields are required.'),
        'send_failed_admin': util.get_text_by_key('contact_page.send_failed_admin', locale, 'Failed to send message. Please contact the administrator.'),
        'mail_body_template': util.get_text_by_key('contact_page.mail_body_template', locale),
        'send_success': util.get_text_by_key('contact_page.send_success', locale, 'Thank you for your inquiry. Your message has been sent successfully.'),
        'send_failed_retry': util.get_text_by_key('contact_page.send_failed_retry', locale, 'Failed to send message. Please try again later.'),
    }

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')

        if not all([name, email, subject, message]):
            flash(text_data['all_fields_required'], 'danger')
            return redirect(url_for('web.contact'))

        # シスオペのユーザーIDを取得
        sysop_user_id = database.get_sysop_user_id()
        if not sysop_user_id:
            logging.error("お問い合わせメールの送信先（シスオペ）が見つかりません。")
            flash(text_data['send_failed_admin'], 'danger')
            return redirect(url_for('web.contact'))

        # メールの件名と本文を作成
        mail_subject = f"[Contact Form] {subject}"
        ip_address = util.get_client_ip()
        mail_body = text_data['mail_body_template'].format(
            name=name,
            email=email,
            ip_address=ip_address,
            message=message
        )

        # システムメールとして送信
        if database.send_system_mail(sysop_user_id, mail_subject, mail_body):
            # flashの代わりに、テンプレートに直接メッセージを渡す
            return render_template('contact.html', success_message=text_data['send_success'], lang=locale, site_info=site_info)
        else:
            flash(text_data['send_failed_retry'], 'danger')
            return redirect(url_for('web.contact'))

    user_email = ''
    if 'user_id' in session:
        user_data = database.get_user_by_id(session.get('user_id'))
        if user_data:
            user_email = user_data.get('email', '')
    return render_template('contact.html', user_email=user_email, lang=locale, site_info=site_info)


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
    """Passkey登録情報を検証し、DBに保存するAPIエンドポイント。"""
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
    """Passkey認証情報を検証し、ユーザーをログインさせるAPIエンドポイント。"""
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
        # User-Agentを見てモバイル判定
        user_agent = request.user_agent.string.lower()
        is_mobile = 'mobi' in user_agent or 'android' in user_agent or 'iphone' in user_agent
        if is_mobile:
            session['menu_mode'] = '4'
        else:
            session['menu_mode'] = user_data.get('menu_mode', '2')
        database.log_access_event(ip_address=util.get_client_ip(),
                                  event_type='LOGIN_SUCCESS',
                                  user_id=user_data['id'], username=user_data['name'], display_name=user_data['name'], message='Passkey authentication successful.')
        database.update_record('users', {'lastlogin': int(time.time())}, {
                               'id': user_data['id']})
        return jsonify({"verified": True})
    else:
        return jsonify({"verified": False, "error": "Authentication failed"}), 401


@web_bp.route('/attachments/<path:filename>')
@login_required
def download_attachment(filename):
    """添付ファイルまたはサムネイルを配信します。"""
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
    """保存されたセッションログファイルをダウンロードさせます。"""
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
    """プラグイン専用の静的ファイル(CSS, 画像など)を配信します。"""
    # パストラバーサル攻撃を防ぐための基本的な検証
    if '..' in plugin_id or '/' in plugin_id or '\\' in plugin_id:
        return "Invalid plugin ID", 400
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400

    plugin_static_dir = os.path.join(
        current_app.config['PLUGINS_DIR'], plugin_id, 'static')
    return send_from_directory(plugin_static_dir, filename)
