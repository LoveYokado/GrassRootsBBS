# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# Flaskアプリケーションの機能を利用するために必要なモジュールをインポート
from .factory import create_app
from .database import get_all_users
from .database import read_server_pref, cleanup_old_access_logs

# ロギングの基本設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [Scheduler] %(message)s'
)

# Flaskアプリケーションのインスタンスを作成
# これにより、アプリケーションコンテキスト内でDB操作などが可能になります。
app, _ = create_app()


def show_user_list_job():
    """1分ごとに実行され、ユーザー一覧をログに出力するジョブ"""
    # app.app_context() を使うことで、このブロック内のコードは
    # Flaskアプリケーションがリクエストを処理している時と同じように動作します。


def log_cleanup_job():
    """スケジュールに従って古いアクセスログを削除するジョブ"""
    with app.app_context():
        logging.info("--- ユーザー一覧取得ジョブ開始 ---")
        try:
            # ページネーションなしで全ユーザーを取得
            users, total_items = get_all_users(per_page=9999)
            logging.info(f"現在の総ユーザー数: {total_items}人")
            for user in users:
                logging.info(f"  - ID: {user['id']}, Name: {user['name']}")
            settings = read_server_pref()
            retention_days = settings.get('log_retention_days', 90)
            if retention_days > 0:
                logging.info(f"ログクリーンアップジョブ開始 (保持期間: {retention_days}日)")
                deleted_count = cleanup_old_access_logs(retention_days)
                logging.info(f"ログクリーンアップジョブ完了 ({deleted_count}件削除)")
            else:
                logging.info("ログクリーンアップは無効です (保持期間が0日以下)。")
        except Exception as e:
            logging.error(f"ユーザー一覧の取得中にエラーが発生しました: {e}", exc_info=True)
        logging.info("--- ユーザー一覧取得ジョブ完了 ---")
        logging.error(f"ログクリーンアップジョブの実行中にエラーが発生しました: {e}", exc_info=True)


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone='Asia/Tokyo')
    scheduler.add_job(show_user_list_job, 'interval',
                      minutes=1, id='show_user_list_job')
    logging.info("スケジューラーを開始します。")
    scheduler.start()
    with app.app_context():
        settings = read_server_pref()
        log_cleanup_cron = settings.get('log_cleanup_cron', '5 4 * * *')

        scheduler = BlockingScheduler(timezone='Asia/Tokyo')
        scheduler.add_job(log_cleanup_job, CronTrigger.from_crontab(
            log_cleanup_cron), id='log_cleanup_job')

        logging.info(
            f"スケジューラーを開始します。ログクリーンアップは '{log_cleanup_cron}' のスケジュールで実行されます。")
        scheduler.start()
