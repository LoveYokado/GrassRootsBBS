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
    api.send("加工された画像がポップアップで表示されます。\r\n\r\n")

    # このプラグインの 'static' ディレクトリにある 'gr-bbs.png' を使用します。
    # 160x100に縮小 -> 640x400にピクセルを保ったまま拡大 -> 16色に減色、という加工を指示します。
    api.show_image_popup(
        image_path='gr-bbs.png',
        title="GR-BBS Logo (レトロ風加工)",
        resize=(160, 100),
        enlarge_to=(640, 400),
        reduce_colors=16)

    api.send(
        "\r\n\r\n(ポップアップを閉じた後、Enterキーを押すとメニューに戻ります...)\r\n")
    # ポップアップが閉じられるのを待つ
    api.get_input()
