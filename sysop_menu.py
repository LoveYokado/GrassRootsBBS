import ssh_input
import util
import datetime
import sqlite_tools
import time
import logging


def sysop_menu(chan, dbname, sysop_login_id, current_menu_mode):
    """シスオペメニュー"""
    while True:
        util.send_text_by_key(chan, "sysop_menu.menu", current_menu_mode)
        util.send_text_by_key(chan, "common_messages.select_prompt",
                              current_menu_mode, add_newline=False)  # プロンプト表示
        input_buffer = ssh_input.process_input(chan)
        if input_buffer is None:
            return  # 接続が切れた場合

        command = input_buffer.lower().strip()
        if command == 'allr':
            # 共通探索リストを読む
            read_default_exploration_list(chan, dbname, current_menu_mode)
        elif command == 'allw':
            # 共通探索リストを書き込む
            write_default_exploration_list(chan, dbname, current_menu_mode)
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", current_menu_mode)  # 無効なコマンド


def read_default_exploration_list(chan, dbname, current_menu_mode):
    server_prefs = sqlite_tools.read_server_pref(dbname)
    if server_prefs and len(server_prefs) > 6:
        read_default_exploration_list_str = server_prefs[6]
        if read_default_exploration_list_str:
            items = read_default_exploration_list_str.split(",")
            chan.send("\r\n")
            for item in items:
                item_stripped = item.strip()
                if item_stripped:
                    chan.send(item_stripped.encode('utf-8')+b'\r\n')
            chan.send("\r\n")
    else:
        logging.error("サーバ設定の読み込みに失敗したか、共通探索リストの項目がありません。")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)


def write_default_exploration_list(chan, dbname, current_menu_mode):
    util.send_text_by_key(
        chan, "user_pref_menu.register_exploration_list.header", current_menu_mode)

    exploration_items = []
    item_number = 1
    while True:
        prompt_text = f"{item_number}: "
        chan.send(prompt_text.encode('utf-8'))
        item_input = ssh_input.process_input(chan)

        if item_input is None:  # 接続切れ
            return

        if not item_input.strip():  # 空エンターで終了
            break

        exploration_items.append(item_input.strip())
        item_number += 1

    if not exploration_items:
        return

    util.send_text_by_key(
        chan, "user_pref_menu.register_exploration_list.confirm_yn", current_menu_mode, add_newline=False)
    confirm_choice = ssh_input.process_input(chan)

    if confirm_choice is None:  # 接続切れ
        return

    if confirm_choice.lower().strip() == 'y':
        exploration_list_str = ",".join(exploration_items)
        if sqlite_tools.update_server_default_exploration_list(dbname, exploration_list_str):
            util.send_text_by_key(
                chan, "user_pref_menu.register_exploration_list.success", current_menu_mode)
        else:
            logging.error(f"共通探索リスト更新時にエラーが発生しました。")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
