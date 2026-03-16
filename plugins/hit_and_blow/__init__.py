# -*- coding: utf-8 -*-

import random


def generate_secret_number():
    """重複しない4桁の数字を生成する"""
    digits = list('0123456789')
    random.shuffle(digits)
    return "".join(digits[:4])


def validate_input(guess):
    """ユーザー入力が4桁のユニークな数字か検証する"""
    if not guess.isdigit() or len(guess) != 4:
        return False, "4桁の数字を入力してください。"
    if len(set(guess)) != 4:
        return False, "数字は重複しないように入力してください。"
    return True, ""


def check_guess(secret, guess):
    """推測を評価し、ヒットとブローの数を返す"""
    hits = 0
    blows = 0
    for i, digit in enumerate(guess):
        if digit == secret[i]:
            hits += 1
        elif digit in secret:
            blows += 1
    return hits, blows


def run(context):
    """プラグインのメイン実行関数"""
    api = context['api']

    api.send("\r\n--- ヒットアンドブロー ---\r\n")
    api.send("コンピュータが4桁のユニークな数字を決定しました。\r\n")
    api.send("重複しない4桁の数字を推測してください (例: 1234)。\r\n")

    secret_number = generate_secret_number()
    attempts = 0

    while True:
        attempts += 1
        prompt = f"\r\n[{attempts}回目] あなたの推測 ('q'でギブアップ): "
        api.send(prompt)
        guess = api.get_input()

        if guess is None or guess.lower() == 'q':
            api.send(
                f"\r\nギブアップですね。正解は {secret_number} でした。\r\n")

            break

        is_valid, message = validate_input(guess)
        if not is_valid:
            api.send(f"\r\n{message}\r\n")
            attempts -= 1  # 不正な入力はカウントしない
            continue

        hits, blows = check_guess(secret_number, guess)

        if hits == 4:
            api.send(f"\r\n** 正解！ ** {attempts}回で当てました！\r\n")
            break
        else:
            result_message = f" -> {hits} Hit, {blows} Blow\r\n"
            api.send(result_message)

    api.send("\r\nゲームを終了します。Enterキーを押してください。")
    api.get_input()
