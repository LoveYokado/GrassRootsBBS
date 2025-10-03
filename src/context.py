# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT


class CommandContext:
    """コマンド実行に必要なコンテキスト情報をカプセル化するクラス。"""

    def __init__(self, chan, user_session, server_pref, online_members_func):
        self.chan = chan
        self._user_session = user_session
        self.server_pref = server_pref
        self.online_members_func = online_members_func

    @property
    def login_id(self) -> str:
        """ログインID（ユーザー名）"""
        return self._user_session.get('username')

    @property
    def display_name(self) -> str:
        """表示名"""
        return self._user_session.get('display_name')

    @property
    def user_id(self) -> int:
        """ユーザーID（主キー）"""
        return self._user_session.get('user_id')

    @property
    def user_level(self) -> int:
        """ユーザーレベル"""
        return self._user_session.get('userlevel')

    @property
    def menu_mode(self) -> str:
        """メニューモード ('1', '2', '3')"""
        return self._user_session.get('menu_mode', '2')

    @menu_mode.setter
    def menu_mode(self, value: str):
        """メニューモードを設定します。"""
        self._user_session['menu_mode'] = value

    @property
    def ip_address(self) -> str:
        """クライアントのIPアドレス"""
        return self.chan.ip_address
