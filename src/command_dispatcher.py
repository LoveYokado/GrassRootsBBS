# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado) <hogehoge@gmail.com>
# SPDX-License-Identifier: MIT

from . import util
from . import bbsmenu
from . import user_pref_menu
from . import sysop_menu
from . import mail_handler
from . import hierarchical_menu
from . import chat_handler
from . import bbs_handler
from . import manual_menu_handler
from . import hamlet_game

# --- Command Handlers ---


def _get_online_members_list(context):
    """コンテキストからオンラインメンバーリスト取得関数を呼び出す"""
    # server.py の get_online_members_list を呼び出すためのラッパー
    return context['online_members_func']()


def handle_help_h(context):
    """'h' ヘルプコマンドを処理する"""
    util.send_text_by_key(
        context['chan'], "top_menu.help_h", context['menu_mode'])
    return {'status': 'continue'}


def handle_help_q(context):
    """'?' ヘルプコマンドを処理する"""
    util.send_text_by_key(
        context['chan'], "top_menu.help_q", context['menu_mode'])
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_explore_new_articles(context):
    """'n' 新アーティクル探索コマンドを処理する"""
    bbsmenu._handle_explore_new_articles(
        context['chan'], context['login_id'], context['display_name'], context['user_id'],
        context['userlevel'], context['menu_mode'], context['addr'][0]
    )
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_full_sig_exploration(context):
    """'x' 全シグ探索コマンドを処理する"""
    default_exploration_list = context['server_pref_dict'].get(
        "default_exploration_list", "")
    bbsmenu._handle_full_sig_exploration(
        context['chan'], context['login_id'], context['display_name'], context['user_id'],
        context['userlevel'], context['menu_mode'], context['addr'][0], default_exploration_list
    )
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_new_article_headlines(context):
    """'o' 新アーティクル見出しコマンドを処理する"""
    bbsmenu.handle_new_article_headlines(
        context['chan'], context['login_id'], context['user_id'], context['userlevel'], context['menu_mode']
    )
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_auto_download(context):
    """'a' 自動ダウンロードコマンドを処理する"""
    bbsmenu.handle_auto_download(
        context['chan'], context['login_id'], context['user_id'], context['userlevel'], context['menu_mode']
    )
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_sysop_menu(context):
    """'s' シスオペメニューコマンドを処理する"""
    result = sysop_menu.sysop_menu(
        context['chan'], context['login_id'], context['display_name'], context['menu_mode'])
    if result == "back_to_top":
        util.send_text_by_key(
            context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_bbs(context):
    """'b' 掲示板コマンドを処理する"""
    # bbs_handler.handle_bbs_menu に処理を移譲する。
    # shortcut_id=None で呼び出すと、階層メニューが表示される。
    # bbs_handler側でモバイルボタンの表示/非表示を制御する。
    bbs_handler.handle_bbs_menu(
        context['chan'], context['login_id'], context['display_name'],
        context['menu_mode'], shortcut_id=None, ip_address=context['addr'][0]
    )
    # 掲示板メニューから抜けたときにトップメニューを再表示
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_chat(context):
    """'c' チャットコマンドを処理する"""
    # 新しく作成したチャットメニューハンドラを呼び出す
    chat_handler.handle_chat_menu(
        context['chan'], context['login_id'], context['display_name'],
        context['menu_mode'], lambda: _get_online_members_list(context)
    )
    # チャットメニューから抜けたときにトップメニューを再表示
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_who_menu(context):
    """'w' オンラインメンバー一覧コマンドを処理する"""
    online_members_dict = _get_online_members_list(context)
    bbsmenu.who_menu(context['chan'], online_members_dict,
                     context['menu_mode'])
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_telegram(context):
    """'#' or '!' 電報コマンドを処理する"""
    online_members_dict = _get_online_members_list(context)
    util.telegram_send(context['chan'], context['display_name'], list(
        online_members_dict.keys()), context['menu_mode'])
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_user_pref_menu(context):
    """'u' ユーザー環境設定コマンドを処理する"""
    result = user_pref_menu.userpref_menu(
        context['chan'], context['login_id'], context['display_name'], context['menu_mode'])

    if result in ('1', '2', '3'):
        # メニューモードが変更された場合、コンテキストを更新してループを継続
        return {'status': 'continue', 'new_menu_mode': result}
    elif result == "back_to_top":
        # トップメニューに戻るだけの場合
        util.send_text_by_key(
            context['chan'], "top_menu.menu", context['menu_mode'])
        return {'status': 'continue'}
    else:  # None (切断)
        return {'status': 'break'}


def handle_mail(context):
    """'m' メールコマンドを処理する"""
    result = mail_handler.mail(
        context['chan'], context['login_id'], context['menu_mode'])
    if result == "back_to_top":
        util.send_text_by_key(
            context['chan'], "top_menu.menu", context['menu_mode'])
    # mail_handler.mail は内部でループし、終了時に "back_to_top" または None を返す
    # どちらの場合もメインループは継続させる
    return {'status': 'continue'}


def handle_online_signup(context):
    """'l' オンラインサインアップコマンドを処理する"""
    bbsmenu.handle_online_signup(context['chan'], context['menu_mode'])
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}


def handle_logoff(context):
    """'e' ログオフコマンドを処理する"""
    return {'status': 'logoff'}


def handle_hamlet_game(context):
    """'z' ハムレットゲームコマンドを処理する"""
    hamlet_game.run_game_vs_ai(context['chan'], context['menu_mode'])
    util.send_text_by_key(
        context['chan'], "top_menu.menu", context['menu_mode'])
    return {'status': 'continue'}

# --- Dispatch Table ---


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
    'e': {'handler': handle_logoff, 'level': 0},
    'z': {'handler': handle_hamlet_game, 'level_key': 'hamlet'},
}


def dispatch_command(command, context):
    """
    コマンドをディスパッチテーブルに基づいて処理する。
    権限チェックもここで行う。
    """
    command_info = COMMAND_DISPATCH_TABLE.get(command)
    if not command_info:
        # 不明なコマンドはヘルプを表示
        util.send_text_by_key(
            context['chan'], "top_menu.help_h", context['menu_mode'])
        util.send_text_by_key(
            context['chan'], "top_menu.menu", context['menu_mode'])
        return {'status': 'continue'}

    user_level = context['userlevel']
    server_pref_dict = context['server_pref_dict']

    # --- 権限チェック ---
    required_level = 0
    if 'level' in command_info:
        required_level = command_info['level']
    elif 'level_key' in command_info:
        required_level = server_pref_dict.get(command_info['level_key'], 2)

    if command_info.get('guest_only', False):
        online_signup_enabled = util.app_config.get(
            'webapp', {}).get('ONLINE_SIGNUP', False)
        if not online_signup_enabled or user_level != 1:
            util.send_text_by_key(
                context['chan'], "common_messages.invalid_command", context['menu_mode'])
            return {'status': 'continue'}
    elif user_level < required_level:
        util.send_text_by_key(
            context['chan'], "common_messages.permission_denied", context['menu_mode'])
        return {'status': 'continue'}

    # --- ハンドラ実行 ---
    handler = command_info['handler']
    return handler(context)
