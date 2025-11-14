# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

import logging
import time
from apscheduler.schedulers.blocking import BlockingScheduler

# ロギングの基本設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [Scheduler] %(message)s'
)


def simple_test_job():
    """10秒ごとに実行されるシンプルなテストジョブ"""
    logging.info("スケジューラーからのテスト実行")


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone='Asia/Tokyo')
    scheduler.add_job(simple_test_job, 'interval',
                      seconds=10, id='simple_test_job')
    logging.info("スケジューラーを開始します。")
    scheduler.start()
