# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

# ==============================================================================
# Application Factory
#
# This module contains the create_app function, which is responsible for
# creating and configuring the Flask application instance. This includes
# loading configuration, initializing extensions like SocketIO and the database,
# and registering blueprints.
# ==============================================================================
#
# ==============================================================================
# アプリケーションファクトリ
#
# このモジュールは、Flaskアプリケーションインスタンスの作成と設定を担当する
# create_app 関数を含んでいます。設定の読み込み、SocketIOやデータベースなどの
# 拡張機能の初期化、ブループリントの登録などを行います。
# ==============================================================================

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
from flask_session import Session
from flask_socketio import SocketIO
from werkzeug.middleware.proxy_fix import ProxyFix

from . import util, database, plugin_manager, backup_util, errors, extensions
from .routes import web_bp
from .events import init_events
from .admin.routes import admin_bp

socketio = SocketIO()


def create_app():
    """Create and configure an instance of the Flask application."""
    # --- Path and Directory Setup ---
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(_current_dir)
    APP_LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
    SESSION_LOG_DIR = os.path.join(APP_LOG_DIR, 'webapp_sessions')

    app = Flask(__name__, static_folder='../static',
                template_folder='../templates')

    # --- Configuration Loading ---
    config_path = os.path.join(PROJECT_ROOT, 'setting', 'config.toml')
    util.load_app_config_from_path(config_path)
    uppercase_config = {key.upper(): value for key,
                        value in util.app_config.items()}
    app.config.from_mapping(uppercase_config)
    app.config['PROJECT_ROOT'] = PROJECT_ROOT

    # --- Middleware and Basic Configuration ---
    # Apply ProxyFix to correctly handle headers from a reverse proxy (e.g., Nginx).
    # This is crucial for getting the correct client IP address, protocol (http/https), etc.
    # リバースプロキシ（例: Nginx）からのヘッダーを正しく処理するためにProxyFixを適用します。
    # これにより、正しいクライアントIPアドレスやプロトコル（http/https）などを取得できます。
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.secret_key = secrets.token_hex(16)

    # --- Directory Setup ---
    ATTACHMENT_DIR = app.config.get('WEBAPP', {}).get(
        'ATTACHMENT_UPLOAD_DIR', 'data/attachments')
    if not os.path.isabs(ATTACHMENT_DIR):
        ATTACHMENT_DIR = os.path.join(PROJECT_ROOT, ATTACHMENT_DIR)
    os.makedirs(ATTACHMENT_DIR, exist_ok=True)
    os.makedirs(APP_LOG_DIR, exist_ok=True)
    os.makedirs(SESSION_LOG_DIR, exist_ok=True)
    app.config['ATTACHMENT_DIR'] = ATTACHMENT_DIR
    app.config['SESSION_LOG_DIR'] = SESSION_LOG_DIR

    # --- Logging Configuration ---
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

    # --- Database Initialization (encapsulated in database.init_app) ---
    # データベース初期化（database.init_appにカプセル化）
    database.init_app(app)

    # --- Initialize Other Extensions ---
    # Use a different Redis DB for rate limiting to avoid key collisions with session data.
    app.config.setdefault('RATELIMIT_STORAGE_URI', os.getenv(
        'REDIS_URL', 'redis://localhost:6379/0').replace('/0', '/1'))
    extensions.limiter.init_app(app)

    plugin_manager.load_plugins()

    # --- Session Configuration ---
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
    app.config['SESSION_PERMANENT'] = True
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_KEY_PREFIX'] = 'grbbs_'
    Session(app)

    # --- Security Config ---
    app.config['MAX_LOGIN_ATTEMPTS'] = app.config.get(
        'SECURITY', {}).get('MAX_PASSWORD_ATTEMPTS', 3)
    app.config['LOCKOUT_TIME_SECONDS'] = app.config.get(
        'SECURITY', {}).get('LOCKOUT_TIME_SECONDS', 300)

    # --- Register Blueprints ---
    app.register_blueprint(web_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # --- Register Error Handlers ---
    errors.register_error_handlers(app)

    # --- Register Context Processors and Template Filters ---
    @app.context_processor
    def inject_util():
        return dict(util=util)

    @app.template_filter('timestamp_to_datetime')
    def timestamp_to_datetime_filter(ts):
        if not ts or not isinstance(ts, (int, float)) or ts <= 0:
            return "N/A"
        try:
            return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError):
            return "Invalid Date"

    # --- Register Request Hooks ---
    @app.before_request
    def restrict_admin_access_by_ip():
        if request.path.startswith('/admin'):
            admin_config = app.config.get('ADMIN', {})
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

    # --- Initialize SocketIO ---
    allowed_origins_str = os.getenv('SOCKETIO_ALLOWED_ORIGINS', app.config.get(
        'WEBAPP', {}).get('ORIGIN', 'http://localhost:5000'))
    allowed_origins = allowed_origins_str.split(
        ',') if allowed_origins_str else []
    socketio.init_app(app, async_mode='gevent',
                      cors_allowed_origins=allowed_origins)
    init_events(socketio, app)

    # --- Initialize Scheduler ---
    def scheduled_backup_job():
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
