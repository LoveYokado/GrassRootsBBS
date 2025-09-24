import flask
import os

"""
スタンドアロンツール実行用サーバー
このスクリプトは、AAカメラのような単体で動作するツールをブラウザで試すための簡易的なWebサーバーです。
メインのBBSアプリケーションとは独立して動作します。
"""

app = flask.Flask(__name__, template_folder='templates')


@app.route('/')
def index():
    """ツールのメインページを配信します。"""
    return flask.render_template('aa_camera.html')


if __name__ == '__main__':
    print("ツールサーバーを起動しています...")
    print("ブラウザで http://127.0.0.1:5002 を開いてください。")
    # メインアプリとの衝突を避けるため、異なるポートを使用します
    app.run(host='0.0.0.0', port=5002, debug=True)
