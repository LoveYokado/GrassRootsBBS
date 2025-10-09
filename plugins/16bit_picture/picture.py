# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
16bit Picture Plugin

This plugin demonstrates how to display an image in the terminal
using the Sixel graphics format via the `api.send_sixel` method.
"""


def run(context):
    """Plugin entry point."""
    api = context['api']

    api.send("\r\n--- 16bit Picture Viewer ---\r\n")
    api.send("Image popup will be displayed.\r\n\r\n")

    # 'static/gr-bbs.png' is relative to this plugin's directory.
    api.show_image_popup('/static/images/logo.png', title="GR-BBS Logo")

    api.send(
        "\r\n\r\n(Press Enter after closing the popup to return to the menu...)\r\n")
    # ポップアップが閉じられるのを待つ
    api.get_input()
