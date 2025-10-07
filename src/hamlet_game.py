
# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""ハムレットゲーム（四目並べ）。

このモジュールは、プロジェクトの元となったBBSソフトウェア「BIG-Model」に
付属していたゲームへのオマージュとして、「ハムレットゲーム」と名付けられた
「コネクトフォー」風のゲームを実装します。
1人プレイ用に、単純なヒューリスティックベースのAIを搭載しています。
"""

import numpy as np
import random
import time

from . import util

# --- Constants / 定数 ---
ROWS = 6
COLS = 7  # 一般的な四目並べに合わせて7列に変更
CONNECT_N = 4  # 4目並べ

# プレイヤー識別子
PLAYER_HUMAN = 1
PLAYER_AI = 2
EMPTY = 0

# 各プレイヤーの表示シンボル
SYMBOL_HUMAN = "O"
SYMBOL_AI = "X"
SYMBOL_EMPTY = " "


def create_board():
    """空のゲーム盤 (6x7のNumpy配列) を作成します。"""
    return np.zeros((ROWS, COLS), dtype=int)  # 6x7の盤面を作成


def drop_piece(board, col, player):
    """指定された列にプレイヤーの駒を落とします。"""
    for r in range(ROWS - 1, -1, -1):
        if board[r, col] == EMPTY:
            board[r, col] = player
            return True
    return False


def is_valid_location(board, col):
    """指定された列に駒を置けるか（盤の範囲内で、一番上が空いているか）をチェックします。"""
    return 0 <= col < COLS and board[0, col] == EMPTY  # 盤の範囲内で、一番上が空いているか


def check_win(board, player):
    """指定されたプレイヤーが勝利条件を満たしたか（CONNECT_N個連続）をチェックします。"""
    # 横方向のチェック
    for r in range(ROWS):
        for c in range(COLS - CONNECT_N + 1):
            if all(board[r, c+i] == player for i in range(CONNECT_N)):
                return True

    # 縦方向のチェック
    for c in range(COLS):
        for r in range(ROWS - CONNECT_N + 1):
            if all(board[r+i, c] == player for i in range(CONNECT_N)):
                return True

    # 右下がりの斜め方向のチェック
    for r in range(ROWS - CONNECT_N + 1):
        for c in range(COLS - CONNECT_N + 1):
            if all(board[r+i, c+i] == player for i in range(CONNECT_N)):
                return True

    # 右上がりの斜め方向のチェック
    for r in range(CONNECT_N - 1, ROWS):
        for c in range(COLS - CONNECT_N + 1):
            if all(board[r-i, c+i] == player for i in range(CONNECT_N)):
                return True

    return False


def get_valid_locations(board):
    """駒を置ける全ての有効な列のリストを返します。"""
    valid_cols = []
    for col in range(COLS):
        if is_valid_location(board, col):
            valid_cols.append(col)
    return valid_cols


def evaluate_position(board, player):
    """現在の盤面を指定されたプレイヤーにとってどれだけ有利かを評価するヒューリスティック関数。"""
    score = 0
    # 横方向の評価
    for r in range(ROWS):
        for c in range(COLS - CONNECT_N + 1):
            window = board[r, c:c+CONNECT_N]
            if np.count_nonzero(window == player) == CONNECT_N - 1 and np.count_nonzero(window == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(window == player) == CONNECT_N - 2 and np.count_nonzero(window == EMPTY) == 2:
                score += 2

    # 縦方向の評価
    for c in range(COLS):
        for r in range(ROWS - CONNECT_N + 1):
            window = board[r:r+CONNECT_N, c]
            if np.count_nonzero(window == player) == CONNECT_N - 1 and np.count_nonzero(window == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(window == player) == CONNECT_N - 2 and np.count_nonzero(window == EMPTY) == 2:
                score += 2
    # 右下がりの斜め方向の評価
    for r in range(ROWS - CONNECT_N + 1):
        for c in range(COLS - CONNECT_N + 1):
            window = [board[r+i, c+i] for i in range(CONNECT_N)]
            if np.count_nonzero(np.array(window) == player) == CONNECT_N - 1 and np.count_nonzero(np.array(window) == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(np.array(window) == player) == CONNECT_N - 2 and np.count_nonzero(np.array(window) == EMPTY) == 2:
                score += 2
    # 右上がりの斜め方向の評価
    for r in range(CONNECT_N - 1, ROWS):
        for c in range(COLS - CONNECT_N + 1):
            window = [board[r-i, c+i] for i in range(CONNECT_N)]
            if np.count_nonzero(np.array(window) == player) == CONNECT_N - 1 and np.count_nonzero(np.array(window) == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(np.array(window) == player) == CONNECT_N - 2 and np.count_nonzero(np.array(window) == EMPTY) == 2:
                score += 2

    # 中央列は戦略的に重要なので、少し評価を高くする
    center_col = COLS // 2
    if board[0, center_col] == EMPTY:
        score += 3

    return score


def ai_choose_column_heuristic(board):
    """AIがヒューリスティックに基づいて最適な列を選択する戦略。"""
    valid_cols = get_valid_locations(board)
    if not valid_cols:
        return -1

    best_col = random.choice(valid_cols)
    best_score = -10000

    # 1. AIが勝利できる手を探す
    for col in valid_cols:
        temp_board = board.copy()
        drop_piece(temp_board, col, PLAYER_AI)
        if check_win(temp_board, PLAYER_AI):
            return col

    # 2. 相手（人間）の勝利を阻止する手を探す
    for col in valid_cols:
        temp_board = board.copy()
        drop_piece(temp_board, col, PLAYER_HUMAN)
        if check_win(temp_board, PLAYER_HUMAN):
            return col

    # 3. 上記以外の場合は、ヒューリスティック評価に基づいて最善手を選ぶ
    for col in valid_cols:
        temp_board = board.copy()
        if drop_piece(temp_board, col, PLAYER_AI):
            score = evaluate_position(temp_board, PLAYER_AI)

            if score > best_score:
                best_score = score
                best_col = col
            elif score == best_score:
                # 同じスコアの場合は、ランダム性を持たせて手を多様化する
                if random.random() > 0.5:
                    best_col = col

    return best_col


def is_board_full(board):
    """ゲーム盤が全て埋まっているかチェックします。"""
    return np.all(board != EMPTY)


def print_board(chan, board):
    """ゲーム盤をテキスト形式でクライアントに送信します。"""
    # 列番号の表示
    col_numbers = "|" + "|".join([str(i+1) for i in range(COLS)]) + "|\r\n"
    chan.send(col_numbers.encode('utf-8'))

    # 区切り線
    chan.send(b"-" * (COLS * 2 + 1) + b"\r\n")

    # 盤面の中身を表示 (上から下へ)
    for r in range(ROWS):
        row_str = "|"
        for c in range(COLS):
            piece = board[r, c]
            if piece == EMPTY:
                row_str += SYMBOL_EMPTY + "|"
            elif piece == PLAYER_HUMAN:
                row_str += SYMBOL_HUMAN + "|"
            else:
                row_str += SYMBOL_AI + "|"
        chan.send((row_str + "\r\n").encode('utf-8'))


def get_player_symbol(player_id):
    """プレイヤーIDから表示シンボル ('O' or 'X') を取得します。"""
    return SYMBOL_HUMAN if player_id == PLAYER_HUMAN else SYMBOL_AI


def run_game_vs_ai(chan, menu_mode):
    """人間 対 AI のゲームを実行するメインループ。"""
    board = create_board()
    game_over = False
    turn = 0

    # ゲームタイトルとルールの表示
    util.send_text_by_key(chan, "hamlet_game.title", menu_mode)
    util.send_text_by_key(chan, "hamlet_game.rules",
                          menu_mode, rows=ROWS, cols=COLS, connect_n=CONNECT_N)
    util.send_text_by_key(chan, "hamlet_game.player_info",
                          menu_mode, symbol_human=SYMBOL_HUMAN, symbol_ai=SYMBOL_AI)

    # 先攻・後攻の選択
    while True:
        util.send_text_by_key(
            chan, "hamlet_game.prompt_first_move", menu_mode, add_newline=False)
        first_choice_input = chan.process_input()
        if first_choice_input is None:
            return  # 切断
        first_choice = first_choice_input.strip().upper()

        if first_choice == 'Y':
            current_player = PLAYER_HUMAN
            util.send_text_by_key(chan, "hamlet_game.you_are_first", menu_mode)
            break
        elif first_choice == 'N':
            current_player = PLAYER_AI
            util.send_text_by_key(chan, "hamlet_game.ai_is_first", menu_mode)
            turn = 1
            break
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", menu_mode)

    while not game_over:
        print_board(chan, board)

        player_prompt_symbol = get_player_symbol(current_player)

        if current_player == PLAYER_HUMAN:
            col_choice = -1
            while True:
                util.send_text_by_key(chan, "hamlet_game.prompt_your_turn",
                                      menu_mode, symbol=player_prompt_symbol, add_newline=False)
                input_str = chan.process_input()
                if input_str is None:
                    return  # 切断

                choice = input_str.strip().lower()

                # 中断コマンドの処理
                if choice == 'a':
                    util.send_text_by_key(
                        chan, "hamlet_game.abort_prompt", menu_mode, add_newline=False)
                    confirm_abort = chan.process_input()
                    if confirm_abort and confirm_abort.strip().lower() == 'y':
                        util.send_text_by_key(
                            chan, "hamlet_game.game_aborted", menu_mode)
                        return
                    else:
                        print_board(chan, board)
                        continue

                if choice.isdigit():
                    col_choice = int(choice) - 1
                    break
                else:
                    util.send_text_by_key(
                        chan, "common_messages.invalid_input", menu_mode)

            if is_valid_location(board, col_choice):
                drop_piece(board, col_choice, current_player)
            else:
                util.send_text_by_key(
                    chan, "hamlet_game.invalid_column", menu_mode)
                continue
        else:  # AIのターン
            util.send_text_by_key(
                chan, "hamlet_game.ai_thinking", menu_mode, symbol=player_prompt_symbol)
            time.sleep(1)
            ai_col = ai_choose_column_heuristic(board)  # ヒューリスティックAIを使用

            if ai_col != -1:
                util.send_text_by_key(
                    chan, "hamlet_game.ai_move", menu_mode, col=ai_col + 1)
                drop_piece(board, ai_col, current_player)
            else:
                pass

        # ゲーム終了条件のチェック
        if check_win(board, current_player):
            print_board(chan, board)
            winner_name = get_player_name(current_player, menu_mode)
            winner_symbol = get_player_symbol(current_player)
            util.send_text_by_key(chan, "hamlet_game.win_message",
                                  menu_mode, winner=winner_name, symbol=winner_symbol)
            game_over = True
        elif is_board_full(board):
            print_board(chan, board)
            # ルール: 盤面が埋まった場合は後攻の勝ち
            if current_player == PLAYER_HUMAN:
                winner_name = get_player_name(PLAYER_AI, menu_mode)
                winner_symbol = get_player_symbol(PLAYER_AI)
                util.send_text_by_key(chan, "hamlet_game.draw_win_message",
                                      menu_mode, winner=winner_name, symbol=winner_symbol)
            else:
                winner_name = get_player_name(PLAYER_HUMAN, menu_mode)
                winner_symbol = get_player_symbol(PLAYER_HUMAN)
                util.send_text_by_key(chan, "hamlet_game.draw_win_message",
                                      menu_mode, winner=winner_name, symbol=winner_symbol)
            game_over = True
        else:
            # 次のプレイヤーへ交代
            turn += 1
            current_player = PLAYER_AI if current_player == PLAYER_HUMAN else PLAYER_HUMAN


def get_player_name(player_id, menu_mode):
    """プレイヤーIDからローカライズされたプレイヤー名を取得します。"""
    if player_id == PLAYER_HUMAN:
        return util.get_text_by_key("hamlet_game.player_name_human", menu_mode)
    else:
        return util.get_text_by_key("hamlet_game.player_name_ai", menu_mode)
