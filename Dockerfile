# syntax=docker/dockerfile:1

# ステージ1: ビルドステージ
# Alpineベースの公式Pythonイメージを使用
FROM python:3.11-alpine AS builder

# 作業ディレクトリを設定
WORKDIR /app

# Pythonの依存関係をインストール
# requirements.txtを先にコピーして、Dockerのレイヤーキャッシュを有効活用します
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ステージ2: 実行ステージ
FROM python:3.11-alpine

WORKDIR /app

# ビルドステージからインストール済みのライブラリをコピー
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/

# アプリケーションコードと必要なディレクトリをコピー
COPY src/ ./src/
COPY data/ ./data/
COPY logs/ ./logs/
COPY setting/ ./setting/
COPY .sshkey/ ./.sshkey/

# サーバーを起動
CMD ["python", "src/server.py"]

