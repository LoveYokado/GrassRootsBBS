# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
アプリケーションエントリポイント
 
これは、Gunicornや開発サーバーの直接実行時に使用されるアプリケーションの
メインエントリポイントです。アプリケーションファクトリを使用して 
アプリインスタンスを作成します。
"""

from .factory import create_app

app, socketio = create_app()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
