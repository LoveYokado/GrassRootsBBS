# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
コマンドディスパッチャ
 
このモジュールは、トップメニューで入力されたユーザーコマンドの
中央ルーターとして機能します。コマンド文字列 (例: 'b', 'c', '?') を 
対応するハンドラ関数にマッピングし、実行前に権限チェックを行います。
"""

from . import util
from . import bbsmenu
from . import user_pref_menu
from . import sysop_menu
from . import mail_handler
from . import hierarchical_menu
from . import chat_handler
from . import bbs_handler
from . import manual_menu_handler
from . import plugin_manager
from . import hamlet_game

# --- Command Handlers / 各コマンドに対応するハンドラ関数 ---


def handle_help_h(context):
    """`h` ヘルプコマンドを処理し、コマンド一覧を表示します。"""
    util.send_text_by_key(
        context.chan, "top_menu.help_h", context.menu_mode)
    return {'status': 'continue'}


def handle_help_q(context):
    """`?` ヘルプコマンドを処理し、コマンド説明を表示します。"""
    util.send_text_by_key(
        context.chan, "top_menu.help_q", context.menu_mode)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_explore_new_articles(context):
    """`n` コマンドを処理し、新着記事の探索を開始します。"""
    bbsmenu._handle_explore_new_articles(
        context.chan, context.login_id, context.display_name, context.user_id,
        context.user_level, context.menu_mode, context.ip_address
    )
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_full_sig_exploration(context):
    """`x` コマンドを処理し、全シグ (掲示板) の探索を開始します。"""
    default_exploration_list = context.server_pref.get(
        "default_exploration_list", "")
    bbsmenu._handle_full_sig_exploration(
        context.chan, context.login_id, context.display_name, context.user_id,
        context.user_level, context.menu_mode, context.ip_address, default_exploration_list
    )
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_new_article_headlines(context):
    """`o` コマンドを処理し、新着記事の見出し一覧を表示します。"""
    bbsmenu.handle_new_article_headlines(
        context.chan, context.login_id, context.user_id, context.user_level, context.menu_mode
    )
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_auto_download(context):
    """`a` コマンドを処理し、新着記事の自動ダウンロードを開始します。"""
    bbsmenu.handle_auto_download(
        context.chan, context.login_id, context.user_id, context.user_level, context.menu_mode
    )
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_sysop_menu(context):
    """`s` コマンドを処理し、シスオペメニューを表示します。"""
    context.chan.send(b'\x1b[?2031l')
    result = sysop_menu.sysop_menu(
        context.chan, context.login_id, context.display_name, context.menu_mode)
    if result == "back_to_top":
        util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_bbs(context):
    """`b` コマンドを処理し、電子掲示板機能を開始します。"""
    context.chan.send(b'\x1b[?2031l')
    bbs_handler.handle_bbs_menu(
        context.chan, context.login_id, context.display_name, context.menu_mode,
        shortcut_id=None, ip_address=context.ip_address
    )
    # 掲示板メニューから抜けたときにトップメニューを再表示
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_chat(context):
    """`c` コマンドを処理し、チャット機能を開始します。"""
    context.chan.send(b'\x1b[?2031l')
    # 新しく作成したチャットメニューハンドラを呼び出す
    chat_handler.handle_chat_menu(
        context.chan, context.login_id, context.display_name, context.menu_mode,
        context.user_id, context.online_members_func
    )
    # チャットメニューから抜けたときにトップメニューを再表示
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_who_menu(context):
    """`w` コマンドを処理し、オンラインメンバーの一覧を表示します。"""
    online_members_dict = context.online_members_func()
    bbsmenu.who_menu(context.chan, online_members_dict,
                     context.menu_mode)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_telegram(context):
    """`#` または `!` コマンドを処理し、電報送信機能を開始します。"""
    online_members_dict = context.online_members_func()
    # オンラインメンバーの辞書から、SIDではなくログインIDのリストを抽出する
    online_user_logins = [
        member_data.get('username') for member_data in online_members_dict.values() if member_data.get('username')
    ]
    from . import terminal_handler
    is_mobile = (
        isinstance(context.chan, terminal_handler.WebTerminalHandler.WebChannel) and
        getattr(context.chan.handler, 'is_mobile', False)
    )
    util.telegram_send(context.chan, context.display_name,
                       online_user_logins, context.menu_mode, is_mobile=is_mobile)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_user_pref_menu(context):
    """`u` コマンドを処理し、ユーザー環境設定メニューを表示します。"""
    context.chan.send(b'\x1b[?2031l')
    result = user_pref_menu.userpref_menu(
        context.chan, context.login_id, context.display_name, context.menu_mode)

    if result in ('1', '2', '3'):
        # メニューモードが変更された場合、コンテキストを更新してループを継続
        return {'status': 'continue', 'new_menu_mode': result}
    elif result == "back_to_top":
        # トップメニューに戻るだけの場合
        util.send_top_menu(context.chan, context.menu_mode)
        return {'status': 'continue'}
    else:  # None (切断)
        return {'status': 'break'}


def handle_mail(context):
    """`m` コマンドを処理し、メールボックス機能を開始します。"""
    context.chan.send(b'\x1b[?2031l')
    result = mail_handler.mail(
        context.chan, context.login_id, context.menu_mode, context.ip_address)
    if result == "back_to_top":
        util.send_top_menu(context.chan, context.menu_mode)
    # mail_handler.mail は内部でループし、終了時に "back_to_top" または None を返す
    # どちらの場合もメインループは継続させる
    return {'status': 'continue'}


def handle_online_signup(context):
    """'l' コマンドを処理し、オンラインサインアップ機能を開始します。"""
    context.chan.send(b'\x1b[?2031l')
    bbsmenu.handle_online_signup(context.chan, context.menu_mode)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_logoff(context):
    """'e' コマンドを処理し、ログオフシーケンスを開始します。"""
    return {'status': 'logoff'}


def handle_hamlet_game(context):
    """'z' コマンドを処理し、ハムレットゲームを開始します。"""
    context.chan.send(b'\x1b[?2031l')
    hamlet_game.run_game_vs_ai(context.chan, context.menu_mode)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_plugin_menu(context):
    """`p` コマンドを処理し、プラグインメニューを表示します。"""
    # トップメニューのボタンを非表示にする
    context.chan.send(b'\x1b[?2031l')
    # 循環インポートを避けるため、ここでインポートする
    from . import plugin_menu_handler
    plugin_menu_handler.handle_plugin_menu(context)
    # プラグインメニューから戻ってきたら、トップメニューを再表示
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


# --- Dispatch Table / ディスパッチテーブル ---
# Maps command strings to their handler functions and required permission levels.
# 'level': Specifies a fixed required user level.
# 'level_key': Specifies a key to look up the required level from server_pref.
# 'guest_only': If True, the command is only available to GUEST users.
#
# コマンド文字列を、対応するハンドラ関数と必要な権限レベルにマッピングします。
# 'level': 固定の要求ユーザーレベルを指定します。
# 'level_key': server_prefから要求レベルを検索するためのキーを指定します。
# 'guest_only': Trueの場合、GUESTユーザーのみが利用可能なコマンドです。
COMMAND_DISPATCH_TABLE = {
    'h': {'handler': handle_help_h, 'level': 0},
    '?': {'handler': handle_help_q, 'level': 0},
    'n': {'handler': handle_explore_new_articles, 'level_key': 'bbs'},
    'x': {'handler': handle_full_sig_exploration, 'level_key': 'bbs'},
    'o': {'handler': handle_new_article_headlines, 'level_key': 'bbs'},
    'a': {'handler': handle_auto_download, 'level_key': 'bbs'},
    's': {'handler': handle_sysop_menu, 'level': 5},
    'w': {'handler': handle_who_menu, 'level_key': 'who'},
    '#': {'handler': handle_telegram, 'level_key': 'telegram'},
    '!': {'handler': handle_telegram, 'level_key': 'telegram'},
    'u': {'handler': handle_user_pref_menu, 'level_key': 'userpref'},
    'm': {'handler': handle_mail, 'level_key': 'mail'},
    'b': {'handler': handle_bbs, 'level_key': 'bbs'},
    'c': {'handler': handle_chat, 'level_key': 'chat'},
    'l': {'handler': handle_online_signup, 'level': 1, 'guest_only': True},
    'p': {'handler': handle_plugin_menu, 'level': 2},
    'e': {'handler': handle_logoff, 'level': 0},
    'z': {'handler': handle_hamlet_game, 'level_key': 'hamlet'},
}


def dispatch_command(command, context):
    """
    コマンドをディスパッチテーブルに基づいて処理し、実行前に権限チェックも行います。
    """
    command_info = COMMAND_DISPATCH_TABLE.get(command)
    if not command_info:
        # 不明なコマンドはヘルプを表示
        util.send_text_by_key(
            context.chan, "top_menu.help_h", context.menu_mode)
        util.send_top_menu(context.chan, context.menu_mode)
        return {'status': 'continue'}

    user_level = context.user_level
    server_pref_dict = context.server_pref

    # --- 権限チェック ---
    # まず、デフォルトの要求レベルを0に設定
    required_level = 0
    if 'level' in command_info:
        # 固定のレベルが指定されている場合
        required_level = command_info['level']
    elif 'level_key' in command_info:
        # server_prefから動的にレベルを取得する場合
        required_level = int(server_pref_dict.get(
            command_info['level_key'], 2))

    if command_info.get('guest_only', False):
        # GUEST専用コマンドの場合の特別チェック
        online_signup_enabled = server_pref_dict.get(
            'online_signup_enabled', False)
        if not online_signup_enabled or user_level != 1:
            util.send_text_by_key(
                context.chan, "common_messages.invalid_command", context.menu_mode)
            return {'status': 'continue'}
    elif user_level < required_level:
        util.send_text_by_key(
            context.chan, "common_messages.permission_denied", context.menu_mode)
        return {'status': 'continue'}

    # --- ハンドラ実行 ---
    handler = command_info['handler']
    return handler(context)
