import base64
# -*- coding: utf-8 -*-
import io
import json
import os
from PIL import Image

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""GR-BBS プラグインAPIモジュール。

プラグインがホストアプリケーションの機能と安全に対話するためのAPIを提供します。
このモジュールは、プラグインに対して公開される`GrbbsApi`クラスを定義しており、
BBS本体の内部実装を隠蔽し、安定したインターフェースのみを公開するファサードパターンとして機能します。
"""


class GrbbsApi:
    """
    プラグインに提供されるAPIのエントリーポイントとなるクラス。

    プラグインは、このクラスのインスタンスを介して、メッセージの送受信、データの永続化、
    ユーザー情報の取得、画像ポップアップの表示、ファイルアップロードなど、
    ホストアプリケーションが提供する機能にアクセスします。
    """

    def __init__(self, app, channel, plugin_id, online_members_func):
        """GrbbsApiのコンストラクタ。

        Args:
            app (Flask): Flaskアプリケーションインスタンス。
            channel (WebChannel): クライアントとの通信チャネル。
            plugin_id (str): このAPIインスタンスを使用するプラグインのID。
            online_members_func (callable): オンラインメンバーのリストを取得する関数。
        """
        self._chan = channel
        self._plugin_id = plugin_id
        self._app = app
        self._online_members_func = online_members_func  # オンラインメンバーリスト取得用の関数

    def send(self, message):
        """クライアントにメッセージを送信します。

        Args:
            message (str | bytes): 送信する文字列またはバイトデータ。
        """
        if isinstance(message, str):
            self._chan.send(message.encode('utf-8'))
        elif isinstance(message, bytes):
            self._chan.send(message)

    def get_input(self, echo=True):
        """クライアントからの入力を一行受け取ります。

        Args:
            echo (bool): 入力内容をクライアントにエコーバックするかどうか。

        Returns:
            str | None: ユーザーが入力した文字列。接続が切れた場合はNone。
        """
        if echo:
            return self._chan.process_input()
        else:
            return self.hide_input()

    def hide_input(self):
        """エコーバックなしでクライアントからの入力を一行受け取ります。

        パスワード入力など、入力内容を画面に表示したくない場合に使用します。

        Returns:
            str | None: ユーザーが入力した文字列。接続が切れた場合はNone。
        """
        return self._chan.hide_process_input()

    def save_data(self, key, value):
        """プラグイン専用のデータをキーバリュー形式で保存または更新します。

        Args:
            key (str): データのキー。
            value: 保存する値。

        Returns:
            bool: 成功した場合はTrue、失敗した場合はFalse。
        """
        from . import database
        return database.save_plugin_data(self._plugin_id, key, value)

    def get_data(self, key):
        """プラグイン専用のデータをキーで取得します。

        Args:
            key (str): 取得するデータのキー。

        Returns:
            any: キーに対応するデータ。存在しない場合はNone。
        """
        from . import database
        return database.get_plugin_data(self._plugin_id, key)

    def delete_data(self, key):
        """指定されたキーのデータを削除します。

        Args:
            key (str): 削除するデータのキー。

        Returns:
            bool: 成功した場合はTrue、失敗した場合はFalse。
        """
        from . import database
        return database.delete_plugin_data(self._plugin_id, key)

    def get_all_data(self):
        """このプラグインが保存した全てのデータを辞書として取得します。

        Returns:
            dict: {'key1': value1, 'key2': value2, ...} 形式の辞書。
        """
        from . import database
        return database.get_all_plugin_data(self._plugin_id)

    def get_user_info(self, username):
        """
        指定されたユーザー名の公開情報を取得します。
        パスワードやメールアドレスなどの機密情報は含まれません。

        Args:
            username (str): 情報を取得したいユーザーのログインID。

        Returns:
            dict | None: ユーザー情報の辞書。ユーザーが存在しない場合はNone。
                          辞書には 'id', 'name', 'level', 'comment', 'registdate', 'lastlogin' が含まれます。
        """
        from . import database
        # ユーザー名はAPI側で大文字に変換する
        return database.get_public_user_info(username.upper())

    def get_online_users(self):
        """現在オンラインのユーザーのリストを取得します。

        IPアドレスなどの機密情報は含まれません。

        Returns:
            list[dict]: オンラインユーザー情報のリスト。
                        各辞書には 'user_id', 'username', 'display_name' が含まれます。
        """
        if not self._online_members_func:
            return []

        online_members_raw = self._online_members_func()
        safe_online_list = []
        for _, member_data in online_members_raw.items():
            safe_data = {
                'user_id': member_data.get('user_id'),
                'username': member_data.get('username'),
                'display_name': member_data.get('display_name'),
            }
            safe_online_list.append(safe_data)
        return safe_online_list

    def get_sysop_user_id(self):
        """
        システムオペレーター（SysOp）のユーザーIDを取得します。

        Returns:
            int | None: シスオペのユーザーID。見つからない場合はNone。
        """
        from . import database
        return database.get_sysop_user_id()

    def send_push_notification(self, user_id, title, body, url=None):
        """
        指定されたユーザーにプッシュ通知を送信します。

        Args:
            user_id (int): 通知を送信するユーザーのID。
            title (str): 通知のタイトル。
            body (str): 通知の本文。
            url (str, optional): 通知クリック時に開くURL。

        Returns:
            bool: 少なくとも1つの通知が正常に送信された場合はTrue、
                  購読情報がない、または全ての送信に失敗した場合はFalse。
        """
        from . import database, util

        subscriptions = database.get_push_subscriptions_by_user_id(user_id)
        if not subscriptions:
            return False

        payload_data = {"title": title, "body": body}
        if url:
            payload_data["data"] = {"url": url}

        payload_json = json.dumps(payload_data)

        success_count = 0
        for sub in subscriptions:
            if util.send_push_notification(sub['subscription_info'], payload_json):
                success_count += 1

        return success_count > 0

    def show_image_popup(self, image_path, title="Image", resize=None, reduce_colors=None, enlarge_to=None, enlarge_filter="nearest"):
        """
        画像ポップアップをクライアントに表示するよう指示します。

        オプションでリサイズ、拡大、減色といった画像加工を行えます。
        加工された画像はData URIとしてクライアントに送信されます。

        Args:
            image_path (str): 表示する画像のパス。
                - 絶対パスの場合: アップロードされたファイルのフルパスなど。
                - 相対パスの場合: このプラグインの 'static' ディレクトリからの相対パス (例: 'my_image.jpg')。
            title (str, optional): ポップアップウィンドウのタイトル。
            resize (tuple, optional): (width, height) のタプルで画像を縮小。例: (320, 200)。
            reduce_colors (int, optional): 指定された色数に減色します。例: 16。256色以下に有効です。
            enlarge_to (tuple, optional): `resize`後に再度拡大する際の解像度。ジャギーな効果を出すのに使用。例: (640, 480)。
            enlarge_filter (str, optional): 拡大時の補間フィルタ。'nearest'でピクセル調になります。デフォルトは 'nearest'。
        """
        from flask import url_for
        from .plugin_manager import PLUGINS_DIR

        image_data_uri = None
        needs_processing = resize is not None or reduce_colors is not None or enlarge_to is not None

        # プレビュー（絶対パス）または画像加工が要求された場合は、ファイルを読み込みData URIを生成する
        if os.path.isabs(image_path) or needs_processing:
            try:
                # --- 画像加工処理 ---
                # image_pathが絶対パス（アップロードされたファイルなど）か、プラグインの相対パスかを判断
                full_path = image_path if os.path.isabs(
                    image_path) else os.path.join(
                        PLUGINS_DIR, self._plugin_id, 'static', image_path)

                if not os.path.exists(full_path):
                    self.send(
                        f"\r\n[API Error] Image not found: {full_path}\r\n")
                    return

                with Image.open(full_path) as img:
                    processed_img = img.convert("RGBA")  # 透過情報を保持するためにRGBAに変換
                    if resize:
                        processed_img = processed_img.resize(
                            resize, Image.Resampling.LANCZOS)
                    if enlarge_to:
                        filter_map = {
                            'nearest': Image.Resampling.NEAREST,
                            'box': Image.Resampling.BOX,
                        }
                        resample_algo = filter_map.get(
                            enlarge_filter.lower(), Image.Resampling.NEAREST)
                        processed_img = processed_img.resize(
                            enlarge_to, resample=resample_algo)
                    if reduce_colors:
                        processed_img = processed_img.quantize(
                            colors=reduce_colors)
                    buffer = io.BytesIO()
                    processed_img.save(buffer, format="PNG")
                    encoded_string = base64.b64encode(
                        buffer.getvalue()).decode("utf-8")
                    image_data_uri = f"data:image/png;base64,{encoded_string}"

            except Exception as e:
                self.send(f"\r\n[API Error] Image processing failed: {e}\r\n")
                return
        else:
            # 加工が不要で、かつ相対パスまたは外部リンクの場合
            try:
                with self._app.app_context():  # URL生成にはアプリケーションコンテキストが必要
                    if image_path.startswith('http'):
                        image_data_uri = image_path  # 外部リンク
                    else:
                        # プラグインのstaticディレクトリからの相対パス
                        image_data_uri = url_for('web.serve_plugin_static',
                                                 plugin_id=self._plugin_id, filename=image_path)
            except Exception as e:
                self.send(f"\r\n[API Error] URL generation failed: {e}\r\n")
                return

        if image_data_uri is None:
            self.send(f"\r\n[API Error] Could not generate image URI.\r\n")
            return

        title_b64 = base64.b64encode(title.encode('utf-8')).decode('utf-8')
        uri_b64 = base64.b64encode(
            image_data_uri.encode('utf-8')).decode('utf-8')

        sequence = f"\x1b]GRBBS;SHOW_IMAGE_POPUP;{title_b64};{uri_b64}\x07"
        self.send(sequence)

    def upload_file(self, prompt="ファイルを選択してください", allowed_extensions=None, max_size_mb=10, preferred_filename=None):
        """
        クライアントにファイルアップロードを要求し、アップロードされたファイル情報を返します。

        この関数は、ユーザーがファイルを選択するかキャンセルするまでブロックします。

        Args:
            prompt (str, optional): ファイル選択ダイアログの前に表示するメッセージ。
            allowed_extensions (list[str], optional): 許可する拡張子のリスト。例: ['jpg', 'png']。
                                                      Noneの場合は制限なし。
            max_size_mb (int, optional): 最大ファイルサイズ (MB)。
            preferred_filename (str, optional): 保存時の推奨ファイル名（拡張子なし）。指定されなければUUIDが使われます。

        Returns:
            dict | None: アップロード成功時にファイルの情報を格納した辞書を返します。
                         {'unique_filename': str, 'original_filename': str, 'filepath': str, 'size': int}
                         ユーザーがキャンセルした場合やエラーが発生した場合はNoneを返します。
        """
        from . import terminal_handler

        # API呼び出し時に、ハンドラにアップロード設定をセット
        if hasattr(self._chan, 'handler') and isinstance(self._chan.handler, terminal_handler.WebTerminalHandler):
            self._chan.handler.pending_upload_settings = {
                'allowed_extensions': allowed_extensions,
                'max_size_mb': max_size_mb,
                'plugin_id': self._plugin_id,  # どのプラグインからの要求か記録
                'preferred_filename': preferred_filename,
            }

        # クライアントにアップロードUIの表示を指示
        self.send(prompt)
        self.send(b'\x1b]GRBBS;UPLOAD_FILE\x07')

        # クライアントからのファイル選択/キャンセルを待つ
        try:
            # process_input() はEnterキーを待ってしまうため、
            # イベントがセットされるのを直接待つように変更
            if not self._chan.handler.input_event.wait(timeout=300.0):
                raise TimeoutError("File upload timed out.")
        except Exception:
            # タイムアウトなど
            return None
        finally:
            self._chan.settimeout(None)

        # ハンドラにセットされたアップロード結果を取得
        self._chan.handler.input_event.clear()  # 次の入力のためにイベントをクリア
        if hasattr(self._chan, 'handler') and isinstance(self._chan.handler, terminal_handler.WebTerminalHandler):
            upload_result = self._chan.handler.pending_upload
            self._chan.handler.pending_upload = None  # 結果を取得したらクリア
            self._chan.handler.pending_upload_settings = None
            if upload_result and 'error' not in upload_result:
                return upload_result
            elif upload_result and 'error' in upload_result:
                self.send(f"\r\n[API Error] {upload_result['error']}\r\n")

        return None

    def delete_static_file(self, filename):
        """
        このプラグインの 'static' ディレクトリから指定されたファイルを削除します。

        ディレクトリトラバーサルを防ぐため、ファイル名に '..' や '/' が含まれている場合は
        処理を中断します。

        Args:
            filename (str): 削除するファイル名。

        Returns:
            bool: 削除に成功した場合はTrue、失敗した場合はFalse。
        """
        from .plugin_manager import PLUGINS_DIR
        if '..' in filename or '/' in filename or '\\' in filename:
            self.send(
                f"\r\n[API Error] Invalid characters in filename: {filename}\r\n")
            return False

        file_path = os.path.join(
            PLUGINS_DIR, self._plugin_id, 'static', filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
