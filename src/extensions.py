# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# default_limitsはアプリケーション起動時に factory.py で設定される
limiter = Limiter(
    key_func=get_remote_address,
)
