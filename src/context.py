# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""コマンド実行コンテキストモジュール。"""


class CommandContext:
    """コマンド実行に必要なコンテキスト情報をカプセル化するクラス。

    各コマンドハンドラに渡され、ユーザーセッション、サーバー設定、
    クライアントとの通信チャンネルなどへの統一されたアクセスを提供します。
    """

    def __init__(self, chan, user_session, server_pref, online_members_func, app):
        """CommandContextのコンストラクタ。"""
        self.chan = chan
        self._user_session = user_session
        self.server_pref = server_pref
        self.online_members_func = online_members_func
        self.app = app

    @property
    def login_id(self) -> str:
        """ログインID (ユーザー名) を返します。"""
        return self._user_session.get('username')

    @property
    def display_name(self) -> str:
        """表示名を返します。GUESTの場合はIPアドレスから生成された名前になります。"""
        return self._user_session.get('display_name')

    @property
    def user_id(self) -> int:
        """データベース上のユーザーID (主キー) を返します。"""
        return self._user_session.get('user_id')

    @property
    def user_level(self) -> int:
        """ユーザーの権限レベルを返します。"""
        return self._user_session.get('userlevel')

    @property
    def menu_mode(self) -> str:
        """現在のメニュー表示モード ('1', '2', '3', '4') を返します。"""
        return self._user_session.get('menu_mode', '2')

    @menu_mode.setter
    def menu_mode(self, value: str):
        """メニュー表示モードをセッションに設定します。"""
        self._user_session['menu_mode'] = value

    @property
    def ip_address(self) -> str:
        """クライアントのIPアドレスを返します。"""
        return self.chan.ip_address
