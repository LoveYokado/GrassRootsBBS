# -*- coding: utf-8 -*-

import time
import random

# プラグインのメタデータ
PLUGIN_NAME = "サイコロゲーム"
PLUGIN_DESCRIPTION = "シンプルなサイコロゲームです。大きな目を出した方が勝ち！"


def run(context):
    """プラグインのメイン実行関数"""
    chan = context['chan']
    login_id = context['login_id']
    menu_mode = context.get('menu_mode', '2')

    chan.send(b"\r\n--- サイコロゲームへようこそ！ ---\r\n")
    chan.send(b"Enterキーを押してサイコロを振ってください...\r\n")
    chan.process_input()

    player_roll = random.randint(1, 6)
    chan.send(f"あなたの出目: {player_roll}\r\n".encode('utf-8'))

    time.sleep(1)

    chan.send(b"コンピュータがサイコロを振ります...\r\n")
    time.sleep(1)
    computer_roll = random.randint(1, 6)
    chan.send(f"コンピュータの出目: {computer_roll}\r\n\r\n".encode('utf-8'))

    if player_roll > computer_roll:
        chan.send(b"** あなたの勝ちです！ **\r\n")
    elif player_roll < computer_roll:
        chan.send(b"** コンピュータの勝ちです... **\r\n")
    else:
        chan.send(b"** 引き分けです！ **\r\n")

    chan.send(b"\r\nゲームを終了します。Enterキーを押してください。")
    chan.process_input()
