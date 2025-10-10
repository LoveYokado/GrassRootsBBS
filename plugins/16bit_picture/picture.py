# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""

画像アップロード・加工テストプラグイン。

このプラグインは、`api.upload_file`と`api.show_image_popup`メソッドを使用して、
ユーザーがアップロードした画像をレトロPC風に加工して表示する機能のデモンストレーションです。
"""


def run(context):
    """プラグインのエントリーポイント。"""
    api = context['api']

    api.send("\r\n--- 16bit Picture Viewer ---\r\n")
    api.send("レトロ風に加工したい画像ファイルをアップロードします。\r\n\r\n")

    # ファイルアップロードを要求
    uploaded_file = api.upload_file(
        prompt="レトロ風に加工したい画像ファイルを選択してください (5MBまで):",
        allowed_extensions=['png', 'jpg', 'jpeg', 'gif', 'bmp'],
        max_size_mb=5
    )

    if uploaded_file:
        api.send(
            f"\r\n'{uploaded_file['original_filename']}' をアップロードしました。画像を加工して表示します...\r\n")

        # アップロードされた画像を加工して表示
        # 160x100に縮小 -> 640x400にピクセルを保ったまま拡大 -> 16色に減色
        api.show_image_popup(
            image_path=uploaded_file['filepath'],
            title=f"{uploaded_file['original_filename']} (レトロ風加工)",
            resize=(160, 100),
            enlarge_to=(640, 400),
            reduce_colors=16
        )
    else:
        api.send("\r\nファイルのアップロードがキャンセルされたか、エラーが発生しました。\r\n")

    api.send(
        "\r\n\r\n(ポップアップを閉じた後、Enterキーを押すとメニューに戻ります...)\r\n")
    # ポップアップが閉じられるのを待つ
    api.get_input()
