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

    def __init__(self, channel):
        self._chan = channel

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
