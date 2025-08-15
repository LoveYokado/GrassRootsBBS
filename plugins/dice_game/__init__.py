# -*- coding: utf-8 -*-

import time
import random


def run(context):
    """プラグインのメイン実行関数"""
    api = context['api']
    # コンテキストから表示名を取得。なければログインIDをフォールバックとして使用
    display_name = context.get('display_name', context.get('login_id', 'ゲスト'))

    api.send(f"\r\n--- {display_name}さん、サイコロゲームへようこそ！ ---\r\n")
    api.send("Enterキーを押してサイコロを振ってください...\r\n")
    api.get_input()

    player_roll = random.randint(1, 6)
    api.send(f"あなたの出目: {player_roll}\r\n")

    time.sleep(1)

    api.send("コンピュータがサイコロを振ります...\r\n")
    time.sleep(1)
    computer_roll = random.randint(1, 6)
    api.send(f"コンピュータの出目: {computer_roll}\r\n\r\n")

    if player_roll > computer_roll:
        api.send("** あなたの勝ちです！ **\r\n")
    elif player_roll < computer_roll:
        api.send("** コンピュータの勝ちです... **\r\n")
    else:
        api.send("** 引き分けです！ **\r\n")

    api.send("\r\nゲームを終了します。Enterキーを押してください。")
    api.get_input()
