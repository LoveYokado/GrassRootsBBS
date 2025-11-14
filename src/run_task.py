# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

import logging
import sys

# Dockerのログに時刻やレベルを出力するための基本的な設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    stream=sys.stdout
)

if __name__ == '__main__':
    logging.info("テスト完了")
