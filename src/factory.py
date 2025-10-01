# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""アプリケーションファクトリ

このモジュールは、Flaskアプリケーションインスタンスの作成と設定を行う 
`create_app()` ファクトリ関数を提供します。
"""
import json

import datetime
import ipaddress
import logging
import os
import secrets
from logging.handlers import RotatingFileHandler

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from flask import request, abort
from markupsafe import escape, Markup
from flask_session import Session
from flask_socketio import SocketIO
from werkzeug.middleware.proxy_fix import ProxyFix

from . import util, database, plugin_manager, backup_util, errors, extensions
from .routes import web_bp
from .events import init_events
from .admin.routes import admin_bp

socketio = SocketIO()


def create_app():
    """
    Flaskアプリケーションインスタンスを作成し、各種設定を初期化します。 

    このファクトリ関数は、アプリケーションの全体的な設定（設定ファイル読み込み、
    ロギング、ディレクトリ作成）、Blueprintの登録、エラーハンドリング、
    拡張機能（レートリミット、セッション管理など）の初期化を担当します。 
    """
    # --- パス設定 ---
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(_current_dir)
    APP_LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
    SESSION_LOG_DIR = os.path.join(APP_LOG_DIR, 'webapp_sessions')

    app = Flask(__name__, static_folder='../static',
                template_folder='../templates')

    # --- 設定ファイルの読み込み ---
    config_path = os.path.join(PROJECT_ROOT, 'setting', 'config.toml')
    util.load_app_config_from_path(config_path)
    uppercase_config = {key.upper(): value for key,
                        value in util.app_config.items()}
    app.config.from_mapping(uppercase_config)
    app.config['PROJECT_ROOT'] = PROJECT_ROOT

    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.secret_key = secrets.token_hex(16)

    # --- ディレクトリの作成 ---
    ATTACHMENT_DIR = app.config.get('WEBAPP', {}).get(
        'ATTACHMENT_UPLOAD_DIR', 'data/attachments')
    if not os.path.isabs(ATTACHMENT_DIR):
        ATTACHMENT_DIR = os.path.join(PROJECT_ROOT, ATTACHMENT_DIR)
    os.makedirs(ATTACHMENT_DIR, exist_ok=True)
    os.makedirs(APP_LOG_DIR, exist_ok=True)
    QUARANTINE_DIR = app.config.get('CLAMAV', {}).get(
        'QUARANTINE_DIRECTORY', 'data/quarantine')
    if not os.path.isabs(QUARANTINE_DIR):
        QUARANTINE_DIR = os.path.join(PROJECT_ROOT, QUARANTINE_DIR)
    os.makedirs(QUARANTINE_DIR, exist_ok=True)
    os.makedirs(SESSION_LOG_DIR, exist_ok=True)
    app.config['ATTACHMENT_DIR'] = ATTACHMENT_DIR
    app.config['SESSION_LOG_DIR'] = SESSION_LOG_DIR

    # --- ロギング設定 ---
    access_logger = logging.getLogger('grbbs.access')
    access_logger.setLevel(logging.INFO)
    access_handler = RotatingFileHandler(
        os.path.join(APP_LOG_DIR, 'grbbs.access.log'),
        maxBytes=1024 * 1024 * 5, backupCount=3, encoding='utf-8'
    )
    access_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s'))
    access_logger.addHandler(access_handler)
    access_logger.propagate = False

    error_handler = RotatingFileHandler(
        os.path.join(APP_LOG_DIR, 'grbbs.error.log'),
        maxBytes=1024 * 1024 * 5, backupCount=3, encoding='utf-8'
    )
    error_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'))
    logging.getLogger().addHandler(error_handler)
    logging.getLogger().setLevel(logging.INFO)

    database.init_app(app)

    # --- 拡張機能の初期化 ---
    app.config.setdefault('RATELIMIT_STORAGE_URI', os.getenv(
        'REDIS_URL', 'redis://localhost:6379/0').replace('/0', '/1'))
    ratelimit_config = app.config.get('RATELIMIT', {})
    default_limits_str = ratelimit_config.get(
        'default_limits', '200 per day;50 per hour')
    app.config.setdefault('RATELIMIT_DEFAULT', default_limits_str)
    extensions.limiter.init_app(app)

    # --- プラグインの読み込み ---
    plugin_manager.load_plugins()

    # --- セッション設定 (Redis) ---
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
    app.config['SESSION_PERMANENT'] = True
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_KEY_PREFIX'] = 'grbbs_'
    Session(app)

    # --- セキュリティ設定 ---
    app.config['MAX_LOGIN_ATTEMPTS'] = app.config.get(
        'SECURITY', {}).get('MAX_PASSWORD_ATTEMPTS', 3)
    app.config['LOCKOUT_TIME_SECONDS'] = app.config.get(
        'SECURITY', {}).get('LOCKOUT_TIME_SECONDS', 300)

    # --- 管理画面のURLプレフィックスを設定 ---
    admin_config = app.config.get('ADMIN', {})
    admin_prefix = admin_config.get('url_prefix', '/admin')

    # --- Blueprintの登録 ---
    app.register_blueprint(web_bp)
    app.register_blueprint(admin_bp, url_prefix=admin_prefix)

    errors.register_error_handlers(app)

    # --- テンプレートコンテキストとフィルタ ---
    @app.context_processor
    def inject_util():
        """テンプレート内で `util` モジュールの関数を使えるようにします。"""
        return dict(util=util)

    @app.template_filter('timestamp_to_datetime')
    def timestamp_to_datetime_filter(ts):
        try:
            return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError):
            return "Invalid Date"

    @app.template_filter('nl2br')
    def nl2br_filter(s):
        """文字列内の改行をHTMLの`<br>`タグに変換します（XSS対策済み）。"""
        if not s:
            return ""
        # First, escape the string to prevent XSS, then replace newlines.
        s_escaped = escape(s)
        return Markup(s_escaped.replace('\n', '<br>\n'))

    # --- リクエストフック ---
    @app.before_request
    def restrict_admin_access_by_ip():
        """
        リクエスト毎に、管理画面 (`/admin`) へのアクセスをIPアドレスで制限します。 

        `config.toml` の `[admin]` セクションで `ip_restriction_enabled` が `True` の場合にのみ有効です。 
        """
        if request.path.startswith(admin_prefix):
            if not admin_config.get('ip_restriction_enabled', False):
                return
            allowed_ips_str = admin_config.get(
                'ALLOWED_IPS', ['127.0.0.1', '::1'])
            remote_ip_str = request.remote_addr
            if not remote_ip_str:
                abort(403)
            try:
                remote_ip = ipaddress.ip_address(remote_ip_str)
                is_allowed = any(remote_ip in ipaddress.ip_network(
                    allowed, strict=False) for allowed in allowed_ips_str)
                if not is_allowed:
                    abort(403)
            except ValueError:
                abort(403)

    @app.after_request
    def add_security_headers(response):
        """
        全てのリクエストのレスポンスにセキュリティ関連のHTTPヘッダーを追加します。 

        Content-Security-Policy (CSP) などを含み、XSSなどの攻撃に対する防御を強化します。 
        """
        csp = (
            "default-src 'self';"
            "script-src 'self' 'unsafe-inline' https://cdn.socket.io https://cdn.jsdelivr.net https://code.jquery.com https://stackpath.bootstrapcdn.com https://fonts.googleapis.com;"
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com https://cdnjs.cloudflare.com https://stackpath.bootstrapcdn.com;"
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com;"
            "img-src 'self' data:;"
            "connect-src 'self' wss: ws: https://cdn.jsdelivr.net https://cdn.socket.io;"
            "frame-ancestors 'none';"
            "form-action 'self';"
            "base-uri 'self';"
        )
        response.headers['Content-Security-Policy'] = csp
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        return response

    # --- SocketIOの初期化 ---
    allowed_origins_str = os.getenv('SOCKETIO_ALLOWED_ORIGINS', app.config.get(
        'WEBAPP', {}).get('ORIGIN', 'http://localhost:5000'))
    allowed_origins = allowed_origins_str.split(
        ',') if allowed_origins_str else []
    socketio.init_app(app, async_mode='gevent',
                      cors_allowed_origins=allowed_origins)
    init_events(socketio, app)

    # --- スケジュールジョブ (バックアップ) ---
    def scheduled_backup_job():
        """
        `apscheduler`によって定期的に実行されるバックアップジョブです。 

        バックアップ作成後、古いバックアップファイルのクリーンアップも行います。 
        """
        with app.app_context():
            logging.info("Starting scheduled backup job...")
            filename = backup_util.create_backup()
            if filename:
                logging.info(
                    f"Scheduled backup created successfully: {filename}")
                backup_util.cleanup_old_backups()
            else:
                logging.error("Scheduled backup creation failed.")

    schedule_settings = database.read_server_pref()
    if schedule_settings.get('backup_schedule_enabled'):
        scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Tokyo')
        try:
            cron_schedule = schedule_settings.get(
                'backup_schedule_cron', '0 3 * * *')
            scheduler.add_job(
                scheduled_backup_job,
                trigger=CronTrigger.from_crontab(cron_schedule),
                id='scheduled_backup_job',
                name='Daily Backup and Cleanup',
                replace_existing=True
            )
            scheduler.start()
            logging.info(
                f"Backup scheduler enabled. Schedule: '{cron_schedule}'")
        except Exception as e:
            logging.error(f"Failed to initialize scheduler: {e}")
    else:
        logging.info("Automatic backup schedule is disabled.")

    return app, socketio
