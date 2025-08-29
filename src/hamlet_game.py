
# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

# ==============================================================================
# Hamlet Game (Connect Four)
#
# This module implements a "Connect Four" style game, named "Hamlet Game"
# in homage to the game included with the "BIG-Model" BBS software, which
# served as the inspiration for this project.
#
# It features a simple heuristic-based AI for single-player mode.
# ==============================================================================
#
# ==============================================================================
# ハムレットゲーム（四目並べ）
#
# このモジュールは、プロジェクトの元となったBBSソフトウェア「BIG-Model」に
# 付属していたゲームへのオマージュとして、「ハムレットゲーム」と名付けられた
# 「コネクトフォー」風のゲームを実装します。
#
# 1人プレイ用に、単純なヒューリスティックベースのAIを搭載しています。
# ==============================================================================

import numpy as np
import random
import time

from . import util

# --- Constants / 定数 ---
ROWS = 6
COLS = 6
CONNECT_N = 4  # N目並べのN

# Player identifiers / プレイヤー識別子
PLAYER_HUMAN = 1
PLAYER_AI = 2
EMPTY = 0

# Display symbols for each player / 各プレイヤーの表示シンボル
SYMBOL_HUMAN = "O"
SYMBOL_AI = "X"
SYMBOL_EMPTY = " "


def create_board():
    """空のゲーム盤 (6x6のNumpy配列) を作成します。"""
    return np.zeros((ROWS, COLS), dtype=int)


def drop_piece(board, col, player):
    """
    指定された列にプレイヤーの駒を落とす。
    成功した場合はTrue、列が満杯の場合はFalseを返す。
    """
    for r in range(ROWS - 1, -1, -1):  # 下の行から上に探索
        if board[r, col] == EMPTY:
            board[r, col] = player
            return True
    return False  # 列が満杯


def is_valid_location(board, col):
    """指定された列に駒を置けるか (盤の範囲内で、一番上が空いているか) をチェックします。"""
    return 0 <= col < COLS and board[0, col] == EMPTY  # 盤の範囲内で、一番上が空いているか


def check_win(board, player):
    """
    指定されたプレイヤーが connect_n 個連続で並べたかどうかをチェックする。
    縦、横、斜め（両方向）をチェックする。
    """
    # Check horizontal locations for a win / 横方向のチェック
    for r in range(ROWS):
        for c in range(COLS - CONNECT_N + 1):
            if all(board[r, c+i] == player for i in range(CONNECT_N)):
                return True

    # Check vertical locations for a win / 縦方向のチェック
    for c in range(COLS):
        for r in range(ROWS - CONNECT_N + 1):
            if all(board[r+i, c] == player for i in range(CONNECT_N)):
                return True

    # Check positively sloped diagonals / 正斜め方向 (右下がり) のチェック
    for r in range(ROWS - CONNECT_N + 1):
        for c in range(COLS - CONNECT_N + 1):
            if all(board[r+i, c+i] == player for i in range(CONNECT_N)):
                return True

    # Check negatively sloped diagonals / 逆斜め方向 (右上がり) のチェック
    for r in range(CONNECT_N - 1, ROWS):
        for c in range(COLS - CONNECT_N + 1):
            if all(board[r-i, c+i] == player for i in range(CONNECT_N)):
                return True

    return False


def get_valid_locations(board):
    """駒を置けるすべての有効な列のリストを返します。"""
    valid_cols = []
    for col in range(COLS):
        if is_valid_location(board, col):
            valid_cols.append(col)
    return valid_cols


def evaluate_position(board, player):
    """
    現在の盤面を指定されたプレイヤーにとってどれだけ有利かを評価する。
    ここでは、単純にリーチに近い形（3連+空き1マスなど）の数を数える。
    """
    score = 0
    # Horizontal evaluation / 横方向の評価
    for r in range(ROWS):
        for c in range(COLS - CONNECT_N + 1):
            window = board[r, c:c+CONNECT_N]
            if np.count_nonzero(window == player) == CONNECT_N - 1 and np.count_nonzero(window == EMPTY) == 1:
                score += 5  # 3連+空き1マス
            elif np.count_nonzero(window == player) == CONNECT_N - 2 and np.count_nonzero(window == EMPTY) == 2:
                score += 2  # 2連+空き2マス

    # Vertical evaluation / 縦方向の評価
    for c in range(COLS):
        for r in range(ROWS - CONNECT_N + 1):
            window = board[r:r+CONNECT_N, c]
            if np.count_nonzero(window == player) == CONNECT_N - 1 and np.count_nonzero(window == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(window == player) == CONNECT_N - 2 and np.count_nonzero(window == EMPTY) == 2:
                score += 2
    # Positively sloped diagonal evaluation / 正斜め方向の評価
    for r in range(ROWS - CONNECT_N + 1):
        for c in range(COLS - CONNECT_N + 1):
            window = [board[r+i, c+i] for i in range(CONNECT_N)]
            if np.count_nonzero(np.array(window) == player) == CONNECT_N - 1 and np.count_nonzero(np.array(window) == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(np.array(window) == player) == CONNECT_N - 2 and np.count_nonzero(np.array(window) == EMPTY) == 2:
                score += 2
    # Negatively sloped diagonal evaluation / 逆斜め方向の評価
    for r in range(CONNECT_N - 1, ROWS):
        for c in range(COLS - CONNECT_N + 1):
            window = [board[r-i, c+i] for i in range(CONNECT_N)]
            if np.count_nonzero(np.array(window) == player) == CONNECT_N - 1 and np.count_nonzero(np.array(window) == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(np.array(window) == player) == CONNECT_N - 2 and np.count_nonzero(np.array(window) == EMPTY) == 2:
                score += 2

    # Center column bias (central columns are generally more valuable)
    # 中央列の評価（中央に近いほど有利なため、簡単なバイアスを追加）
    center_col = COLS // 2
    if board[0, center_col] == EMPTY:
        score += 3

    return score


def ai_choose_column_heuristic(board):
    """
    AIがヒューリスティックに基づいて最適な列を選ぶ戦略。
    """
    valid_cols = get_valid_locations(board)
    if not valid_cols:
        return -1  # 有効な列がない場合

    best_col = random.choice(valid_cols)  # デフォルトはランダム
    best_score = -10000  # Initialize with a very low score

    # --- 1. Check for winning moves (AI) ---
    for col in valid_cols:
        temp_board = board.copy()  # 盤面を一時的にコピー
        drop_piece(temp_board, col, PLAYER_AI)
        if check_win(temp_board, PLAYER_AI):
            return col  # 勝利できるなら迷わずその列を選ぶ

    # --- 2. Block opponent's winning moves (Human) ---
    for col in valid_cols:
        temp_board = board.copy()
        drop_piece(temp_board, col, PLAYER_HUMAN)  # 相手がそこに置いたらどうなるか
        if check_win(temp_board, PLAYER_HUMAN):
            return col  # 相手の勝利をブロックできるならその列を選ぶ

    # --- 3. Evaluate other moves based on score ---
    for col in valid_cols:
        temp_board = board.copy()
        if drop_piece(temp_board, col, PLAYER_AI):
            score = evaluate_position(temp_board, PLAYER_AI)

            if score > best_score:
                best_score = score
                best_col = col
            elif score == best_score:
                # 同じスコアの場合はランダムに選ぶことで多様性を出す
                if random.random() > 0.5:
                    best_col = col

    return best_col


def is_board_full(board):
    """ゲーム盤がすべて埋まっているかチェックします。"""
    return np.all(board != EMPTY)


def print_board(chan, board):
    """ゲーム盤をテキスト形式でクライアントに送信します。"""
    # Column numbers / 列番号の表示
    col_numbers = "|" + "|".join([str(i+1) for i in range(COLS)]) + "|\r\n"
    chan.send(col_numbers.encode('utf-8'))

    # Separator line / 区切り線
    chan.send(b"-" * (COLS * 2 + 1) + b"\r\n")

    # Board content (from top to bottom) / 盤面の中身を表示 (上から下へ)
    for r in range(ROWS):
        row_str = "|"
        for c in range(COLS):
            piece = board[r, c]
            if piece == EMPTY:
                row_str += SYMBOL_EMPTY + "|"
            elif piece == PLAYER_HUMAN:
                row_str += SYMBOL_HUMAN + "|"
            else:  # PLAYER_AI
                row_str += SYMBOL_AI + "|"
        chan.send((row_str + "\r\n").encode('utf-8'))


def get_player_symbol(player_id):
    """プレイヤーIDから表示シンボル ('O' or 'X') を取得します。"""
    return SYMBOL_HUMAN if player_id == PLAYER_HUMAN else SYMBOL_AI


def run_game_vs_ai(chan, menu_mode):
    """人間 対 AI のゲームを実行するメインループ。"""
    board = create_board()
    game_over = False
    turn = 0  # 0 for the first player, 1 for the second

    # --- Display game title and rules ---
    util.send_text_by_key(chan, "hamlet_game.title", menu_mode)
    util.send_text_by_key(chan, "hamlet_game.rules",
                          menu_mode, rows=ROWS, cols=COLS, connect_n=CONNECT_N)
    util.send_text_by_key(chan, "hamlet_game.player_info",
                          menu_mode, symbol_human=SYMBOL_HUMAN, symbol_ai=SYMBOL_AI)

    # --- Ask who goes first ---
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
            turn = 1  # AIが先攻なので、ターンを1にする
            break
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", menu_mode)

    while not game_over:
        print_board(chan, board)

        # Get the symbol for the current player
        player_prompt_symbol = get_player_symbol(current_player)

        if current_player == PLAYER_HUMAN:
            col_choice = -1
            while True:  # Loop until valid input is received
                util.send_text_by_key(chan, "hamlet_game.prompt_your_turn",
                                      menu_mode, symbol=player_prompt_symbol, add_newline=False)
                input_str = chan.process_input()
                if input_str is None:
                    return  # 切断

                choice = input_str.strip().lower()

                # Handle abort command
                if choice == 'a':
                    util.send_text_by_key(
                        chan, "hamlet_game.abort_prompt", menu_mode, add_newline=False)
                    confirm_abort = chan.process_input()
                    if confirm_abort and confirm_abort.strip().lower() == 'y':
                        util.send_text_by_key(
                            chan, "hamlet_game.game_aborted", menu_mode)
                        return  # ゲーム関数を終了
                    else:
                        # 中断をキャンセルした場合、盤面を再表示して入力を促す
                        print_board(chan, board)
                        continue  # 入力ループを継続

                if choice.isdigit():
                    col_choice = int(choice) - 1
                    break  # 入力ループを抜ける
                else:
                    util.send_text_by_key(
                        chan, "common_messages.invalid_input", menu_mode)

            if is_valid_location(board, col_choice):
                drop_piece(board, col_choice, current_player)
            else:
                util.send_text_by_key(
                    chan, "hamlet_game.invalid_column", menu_mode)
                continue  # ターンを消費しない
        else:  # AI's turn
            util.send_text_by_key(
                chan, "hamlet_game.ai_thinking", menu_mode, symbol=player_prompt_symbol)
            time.sleep(1)  # 少し待機してAIが考えているように見せる
            ai_col = ai_choose_column_heuristic(board)  # ヒューリスティックAIを使用

            if ai_col != -1:
                util.send_text_by_key(
                    chan, "hamlet_game.ai_move", menu_mode, col=ai_col + 1)
                drop_piece(board, ai_col, current_player)
            else:
                # このケースは通常、盤面が埋まった場合にのみ発生する
                pass

        # --- Check for game end conditions ---
        if check_win(board, current_player):
            print_board(chan, board)
            winner_name = get_player_name(current_player, menu_mode)
            winner_symbol = get_player_symbol(current_player)
            util.send_text_by_key(chan, "hamlet_game.win_message",
                                  menu_mode, winner=winner_name, symbol=winner_symbol)
            game_over = True
        elif is_board_full(board):
            print_board(chan, board)
            # Rule: If the board is full, the second player wins.
            # 先攻が current_player だった場合、その次のプレイヤーが後攻
            if current_player == PLAYER_HUMAN:  # 人間が最後に手番を打ったが、盤面が埋まった。AIが後攻。
                winner_name = get_player_name(PLAYER_AI, menu_mode)
                winner_symbol = get_player_symbol(PLAYER_AI)
                util.send_text_by_key(chan, "hamlet_game.draw_win_message",
                                      menu_mode, winner=winner_name, symbol=winner_symbol)
            else:  # AIが最後に手番を打ったが、盤面が埋まった。人間が後攻。
                winner_name = get_player_name(PLAYER_HUMAN, menu_mode)
                winner_symbol = get_player_symbol(PLAYER_HUMAN)
                util.send_text_by_key(chan, "hamlet_game.draw_win_message",
                                      menu_mode, winner=winner_name, symbol=winner_symbol)
            game_over = True
        else:
            # Switch to the next player
            turn += 1
            current_player = PLAYER_AI if current_player == PLAYER_HUMAN else PLAYER_HUMAN


def get_player_name(player_id, menu_mode):
    """プレイヤーIDからローカライズされたプレイヤー名を取得します。"""
    if player_id == PLAYER_HUMAN:
        return util.get_text_by_key("hamlet_game.player_name_human", menu_mode)
    else:
        return util.get_text_by_key("hamlet_game.player_name_ai", menu_mode)
