# Gunicorn config file

# サーバーソケット
bind = "0.0.0.0:5000"

# ワーカープロセス
workers = 1
worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"

# ロギング
# Dockerで実行する場合、ログは標準出力/エラー出力に出すのが一般的
accesslog = "-"
errorlog = "-"
loglevel = "info"

# プロセスの名前
proc_name = "grassrootsbbs"
