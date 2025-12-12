# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from croniter import croniter

# Flaskアプリケーションの機能を利用するために必要なモジュールをインポート
from .factory import create_app
from . import database, backup_util, plugin_manager

# ロギングの基本設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [Scheduler] %(message)s'
)

# スケジューラープロセス用のFlaskアプリケーションインスタンスを作成
app, _ = create_app()


def log_cleanup_job():
    """スケジュールに従って古いアクセスログを削除するジョブ"""
    settings = database.read_server_pref()
    retention_days = settings.get('log_retention_days', 90)
    if retention_days > 0:
        logging.info(f"ログクリーンアップジョブ開始 (保持期間: {retention_days}日)")
        deleted_count = database.cleanup_old_access_logs(retention_days)
        logging.info(f"ログクリーンアップジョブ完了 ({deleted_count}件削除)")
    else:
        logging.info("ログクリーンアップは無効です (保持期間が0日以下)。")


def backup_job():
    """スケジュールに従ってバックアップを作成し、古いバックアップを削除するジョブ"""
    logging.info("バックアップジョブ開始")
    if backup_util.create_backup():
        backup_util.cleanup_old_backups()
    logging.info("バックアップジョブ完了")


def dispatch_tasks():
    """毎分実行され、DBから最新のスケジュールを読み込み、タスクを実行するか判断する司令塔"""
    with app.app_context():
        try:
            settings = database.read_server_pref()
            now = datetime.now()

            # ログクリーンアップのスケジュールをチェック
            log_cleanup_cron = settings.get('log_cleanup_cron', '5 4 * * *')
            if croniter.match(log_cleanup_cron, now):
                log_cleanup_job()

            # バックアップのスケジュールをチェック
            if settings.get('backup_schedule_enabled', False):
                backup_cron = settings.get('backup_schedule_cron', '0 3 * * *')
                if croniter.match(backup_cron, now):
                    backup_job()
        except Exception as e:
            logging.error(f"タスクディスパッチャーの実行中にエラーが発生しました: {e}", exc_info=True)


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone='Asia/Tokyo')
    scheduler.add_job(dispatch_tasks, 'interval',
                      minutes=1, id='task_dispatcher')
    logging.info("スケジューラーを開始します。1分ごとにタスク実行をチェックします。")
    scheduler.start()
