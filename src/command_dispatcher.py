# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""コマンドディスパッチャーモジュール。

このモジュールは、トップメニューで入力されたユーザーコマンドの中央ルーターとして機能します。
コマンド文字列（例: 'b', 'c', '?'）を対応するハンドラ関数にマッピングし、実行前に
権限チェックを行います。
"""

from . import util
from . import bbsmenu
from . import user_pref_menu
from . import mail_handler
from . import chat_handler
from . import bbs_handler
from . import hamlet_game
import base64

# --- Command Handlers / 各コマンドに対応するハンドラ関数 ---
# 各コマンドに対応するハンドラ関数


def handle_help_h(context):
    """`h` コマンドを処理し、ヘルプ（コマンド一覧）を表示します。"""
    util.send_text_by_key(
        context.chan, "top_menu.help_h", context.menu_mode)
    return {'status': 'continue'}


def handle_help_q(context):
    """`?` コマンドを処理し、ヘルプ（コマンド一覧と説明）を表示します。"""
    util.send_text_by_key(
        context.chan, "top_menu.help_q", context.menu_mode)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_explore_new_articles(context):
    """`n` コマンドを処理し、ユーザーの探索リストに基づいて新着記事を巡回します。"""
    bbsmenu._handle_explore_new_articles(
        context.chan, context.login_id, context.display_name, context.user_id,
        context.user_level, context.menu_mode, context.ip_address
    )
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_full_sig_exploration(context):
    """`x` コマンドを処理し、サーバーのデフォルト探索リストに基づいて全掲示板を巡回します。"""
    default_exploration_list = context.server_pref.get(
        "default_exploration_list", "")
    bbsmenu._handle_full_sig_exploration(
        context.chan, context.login_id, context.display_name, context.user_id,
        context.user_level, context.menu_mode, context.ip_address, default_exploration_list
    )
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_new_article_headlines(context):
    """`o` コマンドを処理し、探索リスト内の掲示板にある新着記事の見出しを一覧表示します。"""
    bbsmenu.handle_new_article_headlines(
        context.chan, context.login_id, context.user_id, context.user_level, context.menu_mode
    )
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_auto_download(context):
    """`a` コマンドを処理し、探索リスト内の新着記事を連続で表示します。"""
    bbsmenu.handle_auto_download(
        context.chan, context.login_id, context.user_id, context.user_level, context.menu_mode
    )
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_open_admin_ui(context):
    """`s` コマンドを処理し、Web管理画面を開くようにクライアントに指示します。"""
    from . import terminal_handler
    if isinstance(context.chan, terminal_handler.WebTerminalHandler.WebChannel):
        admin_prefix = context.app.config.get(
            'ADMIN', {}).get('url_prefix', '/admin')
        origin = context.app.config.get('WEBAPP', {}).get('ORIGIN', '')
        admin_url = f"{origin}{admin_prefix}"

        # カスタムシーケンスでURLを送信（クライアント側で即時open）
        url_b64 = base64.b64encode(admin_url.encode('utf-8')).decode('utf-8')
        context.chan.send(
            f'\x1b]GRBBS;OPEN_ADMIN;{url_b64}\x07'.encode('utf-8'))
    else:
        # Webクライアント以外（SSHなど）の場合は、URLを表示する(保険のため)
        admin_prefix = context.app.config.get(
            'ADMIN', {}).get('url_prefix', '/admin')
        context.chan.send(
            f"\r\nWeb Admin URL: {context.app.config.get('WEBAPP', {}).get('ORIGIN', '')}{admin_prefix}\r\n".encode('utf-8'))
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_bbs(context):
    """`b` コマンドを処理し、電子掲示板メニューを開始します。"""
    context.chan.send(b'\x1b[?2031l')
    bbs_handler.handle_bbs_menu(
        context.chan, context.login_id, context.display_name, context.menu_mode,
        shortcut_id=None, ip_address=context.ip_address
    )
    # 掲示板メニューから抜けたときにトップメニューを再表示
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_chat(context):
    """`c` コマンドを処理し、チャットルームメニューを開始します。"""
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
    """`w` コマンドを処理し、現在オンラインのメンバー一覧を表示します。"""
    online_members_dict = context.online_members_func()
    bbsmenu.who_menu(context.chan, online_members_dict,
                     context.menu_mode)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_telegram(context):
    """`#` または `!` コマンドを処理し、オンラインユーザーへの電報送信機能を開始します。"""
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
                       online_user_logins, context.menu_mode, context.app, is_mobile=is_mobile)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_user_pref_menu(context):
    """`u` コマンドを処理し、パスワードやプロファイルなどのユーザー環境設定メニューを表示します。"""
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
    """`m` コマンドを処理し、内部メール機能を開始します。"""
    context.chan.send(b'\x1b[?2031l')
    result = mail_handler.mail(
        context.chan, context.login_id, context.menu_mode, context.ip_address)
    if result == "back_to_top":
        util.send_top_menu(context.chan, context.menu_mode)
    # mail_handler.mail は内部でループし、終了時に "back_to_top" または None を返す
    # どちらの場合もメインループは継続させる
    return {'status': 'continue'}


def handle_online_signup(context):
    """`l` コマンドを処理し、ゲストユーザー向けのオンラインサインアップ機能を開始します。"""
    context.chan.send(b'\x1b[?2031l')
    bbsmenu.handle_online_signup(context.chan, context.menu_mode)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_logoff(context):
    """`e` コマンドを処理し、ログオフシーケンスを開始して接続を切断します。"""
    return {'status': 'logoff'}


def handle_hamlet_game(context):
    """`z` コマンドを処理し、四目並べ風の「ハムレットゲーム」を開始します。"""
    context.chan.send(b'\x1b[?2031l')
    hamlet_game.run_game_vs_ai(context.chan, context.menu_mode)
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


def handle_plugin_menu(context, app):
    """`p` コマンドを処理し、利用可能なプラグインの一覧メニューを表示します。"""
    # トップメニューのボタンを非表示にする
    context.chan.send(b'\x1b[?2031l')
    # 循環インポートを避けるため、ここでインポートする
    from . import plugin_menu_handler
    plugin_menu_handler.handle_plugin_menu(context, app)
    # プラグインメニューから戻ってきたら、トップメニューを再表示
    util.send_top_menu(context.chan, context.menu_mode)
    return {'status': 'continue'}


# --- コマンドディスパッチテーブル ---
# コマンド文字列を、対応するハンドラ関数と権限レベルにマッピングします。
#
# - 'handler': 実行される関数。
# - 'level': コマンド実行に必要な固定のユーザーレベル。
# - 'level_key': `server_pref`テーブルから要求レベルを動的に取得するためのキー。
# - 'guest_only': Trueの場合、GUESTユーザーのみが利用可能なコマンド。
COMMAND_DISPATCH_TABLE = {
    'h': {'handler': handle_help_h, 'level': 0},
    '?': {'handler': handle_help_q, 'level': 0},
    'n': {'handler': handle_explore_new_articles, 'level_key': 'bbs'},
    'a': {'handler': handle_auto_download, 'level_key': 'bbs'},
    'x': {'handler': handle_full_sig_exploration, 'level_key': 'bbs'},
    'o': {'handler': handle_new_article_headlines, 'level_key': 'bbs'},
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
    's': {'handler': handle_open_admin_ui, 'level': 5},
    'z': {'handler': handle_hamlet_game, 'level_key': 'hamlet'},
}


def dispatch_command(command, context, app):
    """コマンドをディスパッチテーブルに基づいて処理し、権限チェックを実行します。

    Args:
        command (str): ユーザーが入力したコマンド文字列。
        context (CommandContext): 現在の実行コンテキスト。
        app (Flask): Flaskアプリケーションインスタンス。
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

    # --- 権限レベルの決定 ---
    # まず、デフォルトの要求レベルを0に設定
    required_level = 0
    if 'level' in command_info:
        # 固定のレベルが指定されている場合
        required_level = command_info['level']
    elif 'level_key' in command_info:
        # server_prefから動的にレベルを取得する場合
        required_level = int(server_pref_dict.get(
            command_info['level_key'], 2))

    # --- 権限チェック ---
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
    # プラグインメニューハンドラには app を渡す必要がある
    if handler == handle_plugin_menu:
        return handler(context, app)
    return handler(context)
