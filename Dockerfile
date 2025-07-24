FROM python:3.11-slim

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# 依存関係ファイルをコピーし、インストール
# これにより、依存関係が変更されない限り、このレイヤーはキャッシュされる
COPY requirements.txt .
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
