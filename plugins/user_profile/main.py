# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
プロフィール帳プラグイン

定型の質問に答えるだけで、簡単に自己紹介ページを作成・閲覧できる機能を提供します。
"""

# プロフィールの質問テンプレート
PROFILE_TEMPLATE = [
    {"key": "location", "prompt": "出身地/居住地"},
    {"key": "hobby", "prompt": "趣味"},
    {"key": "favorite_music", "prompt": "好きな音楽"},
    {"key": "favorite_food", "prompt": "好きな食べ物"},
    {"key": "recent_ハマり", "prompt": "最近ハマっていること"},
    {"key": "message", "prompt": "ひとことメッセージ"},
]


def _edit_profile(api, context):
    """自分のプロフィールを編集する関数。"""
    user_id = context['user_id']
    profile_key = f"profile:{user_id}"

    # 既存のプロフィールデータを読み込む
    profile_data = api.get_data(profile_key)
    if not isinstance(profile_data, dict):
        profile_data = {}

    api.send("\r\n--- プロフィール編集 ---\r\n")
    api.send("各項目について入力してください。(空欄のままEnterで変更しない)\r\n\r\n")

    for item in PROFILE_TEMPLATE:
        key = item["key"]
        prompt = item["prompt"]
        current_value = profile_data.get(key, "")
        api.send(f"Q. {prompt} (現在: {current_value}): ")
        new_value = api.get_input()

        if new_value:  # 何か入力された場合のみ更新
            profile_data[key] = new_value

    if api.save_data(profile_key, profile_data):
        api.send("\r\nプロフィールを保存しました。\r\n")
    else:
        api.send("\r\nプロフィールの保存に失敗しました。\r\n")


def _view_profile(api, context):
    """指定されたユーザーのプロフィールを閲覧する関数。"""
    api.send("\r\n閲覧したいユーザーのログインIDを入力してください: ")
    username = api.get_input()
    if not username:
        return

    # ユーザー情報を取得して、ユーザーIDを得る
    user_info = api.get_user_info(username)
    if not user_info:
        api.send(f"\r\nユーザー '{username}' は見つかりませんでした。\r\n")
        return

    target_user_id = user_info.get('id')
    profile_key = f"profile:{target_user_id}"
    profile_data = api.get_data(profile_key)

    api.send(b'\x1b[2J\x1b[H')
    api.send(f"--- {user_info.get('name', username)}さんのプロフィール ---\r\n\r\n")

    if not isinstance(profile_data, dict) or not any(profile_data.values()):
        api.send("このユーザーはまだプロフィールを登録していません。\r\n")
    else:
        for item in PROFILE_TEMPLATE:
            key = item["key"]
            prompt = item["prompt"]
            value = profile_data.get(key, "(未設定)")
            api.send(f"◇ {prompt}\r\n")
            api.send(f"   - {value}\r\n\r\n")

    api.send("何かキーを押すと戻ります...")
    api.get_input()


def run(context):
    """プラグインのエントリーポイント。"""
    api = context['api']

    while True:
        api.send(b'\x1b[2J\x1b[H')
        api.send("\r\n--- プロフィール帳 ---\r\n\r\n")
        api.send("[1] プロフィールを閲覧する\r\n")
        api.send("[2] 自分のプロフィールを編集する\r\n")
        api.send("[E] 終了\r\n\r\n")
        api.send("選択してください: ")

        choice = api.get_input()

        if choice is None or choice.lower() == 'e':
            break
        elif choice == '1':
            _view_profile(api, context)
        elif choice == '2':
            _edit_profile(api, context)
        else:
            api.send("無効な選択です。\r\n")
