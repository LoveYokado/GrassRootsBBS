# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

# ==============================================================================
# Plugin Menu Handler
#
# This module provides the user interface for the plugin system. It displays
# a list of loaded plugins to the user, accepts their selection, and then
# calls the `plugin_manager` to execute the chosen plugin.
# ==============================================================================
#
# ==============================================================================
# プラグインメニューハンドラ
#
# このモジュールは、プラグインシステムのユーザーインターフェースを提供します。
# ロードされたプラグインのリストをユーザーに表示し、選択を受け付け、
# `plugin_manager` を呼び出して選択されたプラグインを実行します。
# ==============================================================================

import textwrap


def handle_plugin_menu(chan, context):
    """
    Displays the plugin menu and executes a plugin based on user selection.
    It also controls the visibility of mobile-specific buttons.
    プラグインメニューを表示し、ユーザーの選択に応じてプラグインを実行します。
    モバイル用のボタン表示/非表示も制御します。
    """
    # 循環インポートを避けるため、関数内でインポートする
    from . import plugin_manager, util

    # モバイル用のプラグインメニューボタンを表示
    chan.send(b'\x1b[?2032h')
    try:
        while chan.active:
            plugins = plugin_manager.get_loaded_plugins()
            # Get current menu mode from context
            menu_mode = context.get('menu_mode', '2')

            # Display menu header
            chan.send(b'\r\n')  # Add a newline for better readability
            util.send_text_by_key(chan, "plugin_menu.header", menu_mode)

            if not plugins:
                util.send_text_by_key(
                    chan, "plugin_menu.no_plugins", menu_mode)
                chan.process_input()  # ユーザーがEnterを押すのを待つ
                break

            # List all loaded plugins
            for i, plugin in enumerate(plugins):
                description = textwrap.fill(
                    plugin['description'], width=70, initial_indent='    ', subsequent_indent='    ')
                chan.send(f"[{i+1}] {plugin['name']}\r\n".encode('utf-8'))
                chan.send(f"{description}\r\n".encode('utf-8'))

            # Check for new mail/telegrams for consistency with other menus
            util.prompt_handler(chan, context.get('login_id'), menu_mode)

            util.send_text_by_key(  # Display prompt
                chan, "plugin_menu.select_prompt", menu_mode, add_newline=False)
            choice = chan.process_input()

            # Eではなく空エンターで終了するように変更
            if choice is None or choice.strip() == '':
                break

            try:
                choice_index = int(choice) - 1
                if 0 <= choice_index < len(plugins):
                    # Execute the selected plugin
                    plugin_to_run = plugins[choice_index]
                    chan.send(b'\r\n')
                    plugin_manager.run_plugin(plugin_to_run['id'], context)
                    util.send_text_by_key(
                        chan, "plugin_menu.returning_to_menu", menu_mode)
                else:
                    util.send_text_by_key(
                        chan, "plugin_menu.invalid_selection", menu_mode)
            except ValueError:
                util.send_text_by_key(
                    chan, "plugin_menu.invalid_selection", menu_mode)

    finally:
        # Ensure mobile buttons are hidden when exiting the menu
        chan.send(b'\x1b[?2032l')
