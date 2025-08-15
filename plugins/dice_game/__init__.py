# -*- coding: utf-8 -*-

import time
import random


def run(context):
    """プラグインのメイン実行関数"""
    chan = context['chan']
    login_id = context['login_id']
    menu_mode = context.get('menu_mode', '2')

    chan.send("\r\n--- サイコロゲームへようこそ！ ---\r\n".encode('utf-8'))
    chan.send("Enterキーを押してサイコロを振ってください...\r\n".encode('utf-8'))
    chan.process_input()

    player_roll = random.randint(1, 6)
    chan.send(f"あなたの出目: {player_roll}\r\n".encode('utf-8'))

    time.sleep(1)

    chan.send("コンピュータがサイコロを振ります...\r\n".encode('utf-8'))
    time.sleep(1)
    computer_roll = random.randint(1, 6)
    chan.send(f"コンピュータの出目: {computer_roll}\r\n\r\n".encode('utf-8'))

    if player_roll > computer_roll:
        chan.send("** あなたの勝ちです！ **\r\n".encode('utf-8'))
    elif player_roll < computer_roll:
        chan.send("** コンピュータの勝ちです... **\r\n".encode('utf-8'))
    else:
        chan.send("** 引き分けです！ **\r\n".encode('utf-8'))

    chan.send("\r\nゲームを終了します。Enterキーを押してください。".encode('utf-8'))
    chan.process_input()
