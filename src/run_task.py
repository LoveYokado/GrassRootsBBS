# SPDX-FileCopyrightText: 2025-2026 LoveYokado
# SPDX-License-Identifier: GPL-2.0-or-later

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
