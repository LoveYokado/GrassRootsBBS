# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
DB API Test Plugin

このプラグインは、GrbbsApiを通じてプラグインに公開されている
データベース関連の機能 (`save_data`, `get_data`, `get_user_info`など) を
テストするためのシンプルな対話式メニューを提供します。
"""


def run(context):
    """
    プラグインのメインエントリーポイント。
    プラグイン専用のデータベースストレージと対話するためのメニューを表示します。
    """
    api = context['api']
    api.send("--- DB API Test Plugin ---\r\n")

    while True:
        api.send("\r\nSelect an option:\r\n")
        api.send("[1] Save/Update data\r\n")
        api.send("[2] Get data by key\r\n")
        api.send("[3] Get all data for this plugin\r\n")
        api.send("[4] Delete data by key\r\n")
        api.send("[5] Get user info (api.get_user_info)\r\n")
        api.send("[6] Get online users (api.get_online_users)\r\n")
        api.send("[E] Exit\r\n")
        api.send("Your choice: ")
        choice = api.get_input().strip().lower()

        if choice == '1':
            # データの保存/更新
            api.send("Enter key: ")
            key = api.get_input().strip()
            if not key:
                api.send("Key cannot be empty.\r\n")
                continue
            api.send("Enter value (will be stored as a string): ")
            value = api.get_input().strip()
            # この save_data は、このプラグイン専用の領域にデータを保存します。
            # 他のプラグインやBBS本体のデータには影響を与えません。
            if api.save_data(key, value):
                api.send(f"Successfully saved data for key '{key}'.\r\n")
            else:
                api.send(f"Failed to save data for key '{key}'.\r\n")

        elif choice == '2':
            # キーを指定してデータを取得
            api.send("Enter key: ")
            key = api.get_input().strip()
            if not key:
                api.send("Key cannot be empty.\r\n")
                continue
            # この get_data は、このプラグイン専用の領域からデータを取得します。
            value = api.get_data(key)
            if value is not None:
                # データはJSONからデシリアライズされたPythonオブジェクトとして返される
                api.send(f"Value for '{key}': {value}\r\n")
            else:
                api.send(f"No data found for key '{key}'.\r\n")

        elif choice == '3':
            # このプラグインの全データを取得
            # get_all_data も、もちろんこのプラグイン専用のデータのみを返します。
            all_data = api.get_all_data()
            if not all_data:
                api.send("No data stored for this plugin.\r\n")
            else:
                api.send("All data for this plugin:\r\n")
                for key, value in all_data.items():
                    api.send(f"  - {key}: {value}\r\n")

        elif choice == '4':
            # キーを指定してデータを削除
            api.send("Enter key to delete: ")
            key = api.get_input().strip()
            if not key:
                api.send("Key cannot be empty.\r\n")
                continue
            # delete_data も、このプラグイン専用のデータのみを削除対象とします。
            if api.delete_data(key):
                api.send(f"Successfully deleted data for key '{key}'.\r\n")
            else:
                api.send(
                    f"Failed to delete data for key '{key}' (it may not exist).\r\n")

        elif choice == '5':
            # ユーザー情報を取得
            api.send("Enter username: ")
            username = api.get_input().strip()
            if not username:
                api.send("Username cannot be empty.\r\n")
                continue
            # このAPIは読み取り専用で、パスワードなどの機密情報は返しません。
            # ユーザー情報を変更するAPIはプラグインに公開されていません。
            user_info = api.get_user_info(username)
            if user_info:
                api.send(f"--- Info for user '{username}' ---\r\n")
                for key, value in user_info.items():
                    api.send(f"  - {key}: {value}\r\n")
            else:
                api.send(f"User '{username}' not found.\r\n")

        elif choice == '6':
            # オンラインユーザーのリストを取得
            online_users = api.get_online_users()
            if not online_users:
                api.send("No users are currently online.\r\n")
            else:
                api.send(f"--- {len(online_users)} Online Users ---\r\n")
                for user in online_users:
                    api.send(
                        f"  - ID: {user.get('user_id')}, Username: {user.get('username')}, Display Name: {user.get('display_name')}\r\n")

        elif choice == 'e' or choice == '':
            api.send("Exiting DB API Test Plugin.\r\n")
            break

        else:
            api.send("Invalid choice. Please try again.\r\n")
