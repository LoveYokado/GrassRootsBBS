# Gunicorn config file

# サーバーソケット
bind = "0.0.0.0:5000"

# ワーカープロセス
workers = 1
worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"

# 開発用にリロードを有効にする
reload = True

# ロギング
# Gunicornのログは標準出力/エラー出力に出すのがシンプルで一般的です。
# アプリケーションのログは webapp.py 側で設定します。
accesslog = "-"
errorlog = "-"
loglevel = "info"

# プロセスの名前
proc_name = "grassrootsbbs"
