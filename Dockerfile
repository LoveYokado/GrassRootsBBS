FROM python:3.11-slim

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# 依存関係ファイルをコピーし、インストール
# これにより、依存関係が変更されない限り、このレイヤーはキャッシュされる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir flask-session

# アプリケーションのコードと必要なディレクトリをコピー
# Dockerfileがプロジェクトのルートディレクトリにあることを想定
COPY . /app

# アプリケーションがリッスンするポートを公開
# config.toml の設定 (デフォルト: 50000 for webapp, 50001 for normal SSH)
EXPOSE 50000
EXPOSE 50001

# アプリケーションの起動コマンド (srcディレクトリ内のserver.pyを指定)
CMD ["python", "src/server.py"]