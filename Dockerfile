FROM python:3.11-slim

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# 依存関係ファイルをコピーし、インストール
# mysqldump と mysql コマンドラインクライアントをインストール
RUN apt-get update && \
    apt-get install -y default-mysql-client supervisor build-essential libffi-dev libssl-dev libgl1 && \
    rm -rf /var/lib/apt/lists/*

# Pythonの依存関係をインストール
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
# supervisordの設定ファイルをコピーする
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# アプリケーションのコードと必要なディレクトリをコピー
# Dockerfileがプロジェクトのルートディレクトリにあることを想定
COPY . /app

# アプリケーションがリッスンするポートを公開
# Gunicornがリッスンするポート
EXPOSE 5000

# Gunicornを使ってWebアプリケーションを起動
# geventワーカーはFlask-SocketIOと互換性がある

# supervisordを起動
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]