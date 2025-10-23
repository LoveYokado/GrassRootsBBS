# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
シスオペ呼び出しプラグイン

シスオペに緊急のメッセージをプッシュ通知で送信します。
"""


def run(context):
    """プラグインのエントリーポイント。"""
    api = context['api']
    display_name = context.get(
        'display_name', context.get('login_id', 'Unknown'))

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
