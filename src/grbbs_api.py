# -*- coding: utf-8 -*-

class GrbbsApi:
    """
    プラグインに提供する安全なAPI。
    ホストプログラムの機能を制限付きで公開する「窓口」の役割を担う。
    """

    def __init__(self, channel):
        self._chan = channel

    def send(self, message):
        """クライアントにメッセージを送信する"""
        if isinstance(message, str):
            self._chan.send(message.encode('utf-8'))
        elif isinstance(message, bytes):
            self._chan.send(message)

    def get_input(self, echo=True):
        """クライアントからの入力を一行受け取る"""
        if echo:
            return self._chan.process_input()
        else:
            return self.hide_input()

    def hide_input(self):
        """エコーバックなしでクライアントからの入力を一行受け取る"""
        return self._chan.hide_process_input()
