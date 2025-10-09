# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""プラグインメニューハンドラ。

このモジュールは、プラグインシステムのユーザーインターフェースを提供します。
ロードされたプラグインのリストをユーザーに表示し、選択を受け付け、
`plugin_manager` を呼び出して選択されたプラグインを実行します。
"""

import textwrap


def handle_plugin_menu(context, app):
    """プラグインメニューを表示し、ユーザーの選択に応じてプラグインを実行します。"""
    # 循環インポートを避けるため、関数内でインポートする
    from . import plugin_manager, util

    chan = context.chan

    chan.send(b'\x1b[?2032h')
    try:
        while chan.active:
            plugins = plugin_manager.get_loaded_plugins()
            menu_mode = context.menu_mode

            chan.send(b'\r\n')
            util.send_text_by_key(chan, "plugin_menu.header", menu_mode)

            if not plugins:
                util.send_text_by_key(
                    chan, "plugin_menu.no_plugins", menu_mode)
                chan.process_input()  # ユーザーがEnterを押すのを待つ
                break

            for i, plugin in enumerate(plugins):
                description = textwrap.fill(
                    plugin['description'], width=70, initial_indent='    ', subsequent_indent='    ')
                chan.send(f"[{i+1}] {plugin['name']}\r\n".encode('utf-8'))
                chan.send(f"{description}\r\n".encode('utf-8'))

            util.prompt_handler(chan, context.login_id, menu_mode)

            util.send_text_by_key(
                chan, "plugin_menu.select_prompt", menu_mode, add_newline=False)
            choice = chan.process_input()

            if choice is None or choice.strip() == '':
                break

            try:
                choice_index = int(choice) - 1
                if 0 <= choice_index < len(plugins):
                    plugin_to_run = plugins[choice_index]
                    chan.send(b'\r\n')
                    # run_plugin に app オブジェクトを渡す
                    plugin_manager.run_plugin(
                        app, plugin_to_run['id'], context)
                    util.send_text_by_key(
                        chan, "plugin_menu.returning_to_menu", menu_mode)
                else:
                    util.send_text_by_key(
                        chan, "plugin_menu.invalid_selection", menu_mode)
            except ValueError:
                util.send_text_by_key(
                    chan, "plugin_menu.invalid_selection", menu_mode)

    finally:
        # メニューを抜ける際にモバイル用ボタンを非表示にする
        chan.send(b'\x1b[?2032l')
