FROM python:3.11-slim

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# 依存関係ファイルをコピーし、インストール
# mysqldump と mysql コマンドラインクライアントをインストール
RUN apt-get update && \
    apt-get install -y default-mysql-client && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Pythonの依存関係をインストール
RUN python -m pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードと必要なディレクトリをコピー
# Dockerfileがプロジェクトのルートディレクトリにあることを想定
COPY . /app

# アプリケーションがリッスンするポートを公開
# Gunicornがリッスンするポート
EXPOSE 5000

# Gunicornを使ってWebアプリケーションを起動
# geventワーカーはFlask-SocketIOと互換性がある

CMD ["gunicorn", "-c", "gunicorn.conf.py", "src.webapp:app"]
