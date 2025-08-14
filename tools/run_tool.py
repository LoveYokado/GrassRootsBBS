import flask
import os

# このスクリプトは、スタンドアロンのツールを実演するための簡単なサーバーです。
# これはメインのGrassRootsBBSアプリケーションの一部ではありません。

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
