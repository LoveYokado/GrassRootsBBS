import base64
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""GR-BBS プラグインAPI。
 
このモジュールは、プラグインに提供される安全なAPIクラスを定義します。
これは「ファサード」または「ブリッジ」として機能し、ホストアプリケーションの
機能を、制限された安全な形でプラグインに公開します。
"""


class GrbbsApi:
    """
    プラグインに提供される安全なAPIクラス。

    これは「ファサード」または「ブリッジ」として機能し、ホストアプリケーションの機能を、
    制限された安全な形でプラグインに公開します。
    """

    def __init__(self, app, channel, plugin_id, online_members_func):
        """GrbbsApiのコンストラクタ。"""
        self._chan = channel
        self._plugin_id = plugin_id
        self._app = app
        self._online_members_func = online_members_func  # オンラインメンバーリスト取得用の関数

    def send(self, message):
        """クライアントにメッセージを送信します。

        Args:
            message (str or bytes): 送信する文字列またはバイトデータ。
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
            str: ユーザーが入力した文字列。
        """
        if echo:
            return self._chan.process_input()
        else:
            return self.hide_input()

    def hide_input(self):
        """エコーバックなしでクライアントからの入力を一行受け取ります（パスワード入力などに使用）。"""
        return self._chan.hide_process_input()

    def save_data(self, key, value):
        """このプラグイン専用のデータをキーバリュー形式で保存または更新します。

        値はJSONとしてシリアライズ可能なオブジェクトである必要があります。

        Args:
            key (str): データのキー。
            value: 保存する値。

        Returns:
            bool: 成功した場合はTrue、失敗した場合はFalse。
        """
        from . import database
        return database.save_plugin_data(self._plugin_id, key, value)

    def get_data(self, key):
        """指定されたキーに対応する、このプラグイン専用のデータを取得します。

        Args:
            key (str): 取得するデータのキー。

        Returns:
            any: 対応するデータ。存在しない場合はNone。
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
        """このプラグインが保存した全てのデータを辞書として取得します。"""
        from . import database
        return database.get_all_plugin_data(self._plugin_id)

    def get_user_info(self, username):
        """
        指定されたユーザー名の公開情報を取得します。
        パスワードやメールアドレスなどの機密情報は含まれません。

        Args:
            username (str): 情報を取得したいユーザーのログインID。

        Returns:
            dict or None: ユーザー情報の辞書。ユーザーが存在しない場合はNone。
                          辞書には 'id', 'name', 'level', 'comment', 'registdate', 'lastlogin' が含まれます。
        """
        from . import database
        # ユーザー名はAPI側で大文字に変換する
        return database.get_public_user_info(username.upper())

    def get_online_users(self):
        """現在オンラインのユーザーのリストを取得します。

        IPアドレスなどの機密情報は含まれません。

        Returns:
            list[dict]: オンラインユーザー情報のリスト（辞書の配列）。
                        各辞書には 'user_id', 'username', 'display_name' が含まれます。
        """
        if not self._online_members_func:
            return []

        online_members_raw = self._online_members_func()
        safe_online_list = []
        for sid, member_data in online_members_raw.items():
            safe_data = {
                'user_id': member_data.get('user_id'),
                'username': member_data.get('username'),
                'display_name': member_data.get('display_name'),
            }
            safe_online_list.append(safe_data)
        return safe_online_list

    def show_image_popup(self, image_path, title="Image"):
        """
        指定されたパスの画像をポップアップウィンドウで表示するようクライアントに指示します。

        この関数はポップアップが閉じられるまでブロックします。

        Args:
            image_path (str): プラグインの 'static' ディレクトリからの相対パス。
            title (str, optional): ポップアップウィンドウのタイトル。
        """
        from flask import url_for

        # プラグインはリクエストコンテキスト外で実行されるため、
        # url_for を使うにはアプリケーションコンテキストを明示的に作成する必要がある
        with self._app.app_context():
            if image_path.startswith('/'):
                # パスが / から始まる場合は、アプリケーションルートからの絶対パスとして扱う
                image_url = image_path
            else:
                # それ以外の場合は、プラグインの静的ファイルとして扱う
                image_url = url_for('web.serve_plugin_static',
                                    plugin_id=self._plugin_id, filename=image_path)

        title_b64 = base64.b64encode(title.encode('utf-8')).decode('utf-8')
        url_b64 = base64.b64encode(image_url.encode('utf-8')).decode('utf-8')

        sequence = f"\x1b]GRBBS;SHOW_IMAGE_POPUP;{title_b64};{url_b64}\x07"
        self.send(sequence)
