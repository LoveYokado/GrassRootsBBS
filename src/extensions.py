# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""Flask拡張機能の初期化。

このモジュールは、レートリミット用のFlask-Limiterなど、
アプリケーション全体で使用されるFlask拡張機能を初期化します。
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
)
