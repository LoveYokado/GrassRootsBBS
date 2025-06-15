import ssh_input
import util
import datetime
import sqlite_tools
import time
import logging

import util


def bbs_menu(chan):
    """BBSメニュー"""
    rtinput = ''
    while rtinput != 'e':
        rtinput = ssh_input.realtime_input(chan)
        chan.send(rtinput)

    return


def who_menu(chan, dbname, online_members, current_menu_mode):
    """
    オンラインメンバー一覧を表示する
    """
    util.send_text_by_key(
        chan, "who_menu.header", current_menu_mode)
    if not online_members:
        util.send_text_by_key(chan, "who_menu.nomembers",
                              current_menu_mode)
        return

    for member_name in online_members:
        # fetchall_idbase はリストを返す。ユーザー名は UNIQUE なので結果は 0 or 1 件
        results = sqlite_tools.fetchall_idbase(
            dbname, 'users', 'name', member_name)
        if results:  # 結果が存在する場合
            userdata = results[0]
            comment = userdata['comment'] if userdata['comment'] else "(コメントなし)"
            chan.send(f"{member_name:<15} {comment} \r\n")
        else:
            # 基本的に online_members にいるユーザーは DB に存在するはずだが念のため
            chan.send(f"{member_name:<15} {'(ユーザー情報取得エラー)'}\r\n")
            print(f"警告: オンラインメンバー '{member_name}' の情報がDBに見つかりません。")
    util.send_text_by_key(chan, "who_menu.footer", current_menu_mode)
