# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
画像ポップアップテストプラグイン。

このプラグインは、`api.show_image_popup`メソッドを使用して、
画像加工オプション付きでポップアップを表示する機能のデモンストレーションです。
"""


def run(context):
    """Plugin entry point."""
    api = context['api']

    api.send("\r\n--- 16bit Picture Viewer ---\r\n")

    # ファイルアップロードを要求
    uploaded_file = api.upload_file(
        prompt="レトロ風に加工したい画像ファイルを選択してください (5MBまで):",
        allowed_extensions=['png', 'jpg', 'jpeg', 'gif', 'bmp'],
        max_size_mb=5
    )

    if uploaded_file:
        api.send(
            f"\r\nファイル '{uploaded_file['original_filename']}' をアップロードしました。\r\n")
        api.send("画像を加工して表示します...\r\n")

        # アップロードされた画像を加工して表示
        api.show_image_popup(
            image_path=uploaded_file['filepath'],
            title=f"{uploaded_file['original_filename']} (レトロ風加工)",
            resize=(320, 200),
            reduce_colors=16)
    else:
        api.send("\r\nファイルのアップロードがキャンセルされたか、エラーが発生しました。\r\n")

    api.send(
        "\r\n\r\n(ポップアップを閉じた後、Enterキーを押すとメニューに戻ります...)\r\n")
    # ポップアップが閉じられるのを待つ
    api.get_input()
