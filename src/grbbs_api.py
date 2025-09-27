# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
GR-BBS プラグインAPI

このモジュールは、プラグインに提供される安全なAPIクラスを定義します。
これは「ファサード」または「ブリッジ」として機能し、ホストアプリケーションの
機能を、制限された安全な形でプラグインに公開します。
"""


class GrbbsApi:

    def __init__(self, channel, plugin_id, online_members_func):
        self._chan = channel
        self._plugin_id = plugin_id
        # 循環インポートを避けるため、メソッド内で database モジュールをインポート
        self._online_members_func = online_members_func

    def send(self, message):
        """クライアントにメッセージを送信します。

        :param message: 送信する文字列またはバイト列。
        """
        if isinstance(message, str):
            self._chan.send(message.encode('utf-8'))
        elif isinstance(message, bytes):
            self._chan.send(message)

    def get_input(self, echo=True):
        """クライアントからの入力を一行受け取ります。

        :param echo: 入力内容をエコーバックするかどうか。デフォルトはTrue。
        :return: ユーザーが入力した文字列。
        """
        if echo:
            return self._chan.process_input()
        else:
            return self.hide_input()

    def hide_input(self):
        """エコーバックなしでクライアントからの入力を一行受け取ります（パスワード入力用）。"""
        return self._chan.hide_process_input()

    def save_data(self, key, value):
        """
        このプラグイン専用のデータをキーと値のペアで保存します。
        値はJSONとしてシリアライズ可能なオブジェクトである必要があります。

        :param key: データのキー（文字列）。
        :param value: 保存する値。
        :return: 成功した場合はTrue、失敗した場合はFalse。
        """
        from . import database
        return database.save_plugin_data(self._plugin_id, key, value)

    def get_data(self, key):
        """指定されたキーに対応する、このプラグイン専用のデータを取得します。"""
        from . import database
        return database.get_plugin_data(self._plugin_id, key)

    def delete_data(self, key):
        """指定されたキーのデータを削除します。"""
        from . import database
        return database.delete_plugin_data(self._plugin_id, key)

    def get_all_data(self):
        """
        このプラグインが保存した全てのデータを辞書として取得します。
        キーが辞書のキー、値が辞書の値となります。
        """
        from . import database
        return database.get_all_plugin_data(self._plugin_id)

    def get_user_info(self, username):
        """
        指定されたユーザー名の公開情報を取得します。
        パスワードやメールアドレスなどの機密情報は含まれません。

        :param username: 情報を取得したいユーザー名。
        :return: ユーザー情報の辞書。ユーザーが存在しない場合はNone。
                 辞書には 'id', 'name', 'level', 'comment', 'registdate', 'lastlogin' が含まれる可能性があります。
        """
        from . import database
        # ユーザー名はAPI側で大文字に変換する
        return database.get_public_user_info(username.upper())

    def get_online_users(self):
        """
        現在オンラインのユーザーのリストを取得します。
        IPアドレスなどの機密情報は含まれません。

        :return: オンラインユーザー情報のリスト（辞書型）。
                 各辞書には 'user_id', 'username', 'display_name' が含まれる可能性があります。
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
