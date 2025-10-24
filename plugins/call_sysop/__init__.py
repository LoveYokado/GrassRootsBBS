# -*- coding: utf-8 -*-
import time
# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
シスオペ呼び出しプラグイン

シスオペに緊急のメッセージをプッシュ通知で送信します。
"""
PLUGIN_STATE_KEY = 'call_sysop_enabled'


def _handle_user_call(api, display_name):
    """一般ユーザー向けの呼び出し処理。"""
    # テキストをプラグイン内に直接定義
    title_text = "--- シスオペ呼び出し ---"
    prompt_text = "シスオペに送信するメッセージを入力してください (Enterのみでキャンセル):\r\n> "
    cancelled_text = "\r\nキャンセルしました。\r\n"
    success_text = "\r\nシスオペを呼び出しました。\r\n"
    not_found_text = "\r\nエラー: シスオペが見つかりませんでした。\r\n"
    failed_text = "\r\nエラー: シスオペへの通知に失敗しました。(プッシュ通知が未登録の可能性があります)\r\n"
    push_title = "シスオペ呼び出し"
    push_body_format = "{sender}さんからメッセージ: {message}"

    api.send(f"\r\n{title_text}\r\n")
    api.send(prompt_text)

    message = api.get_input()
    if not message or not message.strip():
        api.send(cancelled_text)
        return

    sysop_user_id = api.get_sysop_user_id()
    if not sysop_user_id:
        api.send(not_found_text)
        return

    body = push_body_format.format(sender=display_name, message=message)

    if api.send_push_notification(sysop_user_id, push_title, body, url="/admin/who"):
        api.send(success_text)
    else:
        api.send(failed_text)

    api.send("何かキーを押すと戻ります...")
    api.get_input()


def _handle_sysop_menu(api):
    """シスオペ向けの管理メニュー処理。"""
    while True:
        api.send(b'\x1b[2J\x1b[H')  # 画面クリア
        is_enabled = api.get_data(PLUGIN_STATE_KEY)
        if is_enabled is None:
            is_enabled = True  # デフォルトは有効

        status_text = "有効" if is_enabled else "無効"
        toggle_action_text = "無効にする" if is_enabled else "有効にする"

        api.send("--- シスオペ呼び出し管理 ---\r\n\r\n")
        api.send(f"現在の状態: {status_text}\r\n\r\n")
        api.send(f"[1] 呼び出しを{toggle_action_text}\r\n")
        api.send("[E] 終了\r\n\r\n")
        api.send("選択してください: ")

        choice = api.get_input()
        if not choice or choice.lower() == 'e':
            break

        if choice == '1':
            new_state = not is_enabled
            if api.save_data(PLUGIN_STATE_KEY, new_state):
                new_status_text = "有効" if new_state else "無効"
                api.send(f"\r\n呼び出し機能を「{new_status_text}」にしました。\r\n")
            else:
                api.send("\r\n状態の保存に失敗しました。\r\n")
            time.sleep(2)
        else:
            api.send("\r\n無効な選択です。\r\n")
            time.sleep(1)


def run(context):
    """プラグインのエントリーポイント。"""
    api = context['api']
    user_level = context.get('user_level', 0)
    display_name = context.get(
        'display_name', context.get('login_id', 'Unknown'))

    # シスオペの場合、管理メニューを表示
    if user_level >= 5:
        _handle_sysop_menu(api)
        return

    # 一般ユーザーの場合、機能が有効かチェック
    is_enabled = api.get_data(PLUGIN_STATE_KEY)
    if is_enabled is None:
        is_enabled = True  # データがなければデフォルトで有効

    if not is_enabled:
        api.send("\r\n--- シスオペ呼び出し ---\r\n")
        api.send("現在、シスオペ呼び出しは停止されています。\r\n")
        api.send("何かキーを押すと戻ります...")
        api.get_input()
        return

    # 機能が有効なら、通常の呼び出し処理を実行
    _handle_user_call(api, display_name)
