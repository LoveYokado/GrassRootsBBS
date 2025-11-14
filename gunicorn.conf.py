# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

# Gunicorn config file

# サーバーソケットの設定
bind = "0.0.0.0:5000"

# ワーカープロセス
workers = 1
worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"

# 開発用にリロードを有効にする
reload = False

# ロギング設定
# Gunicornのログは標準出力/エラー出力に設定。アプリケーションログは別途設定。
accesslog = "-"
errorlog = "-"
loglevel = "info"

# プロセスの名前
proc_name = "grassrootsbbs"
