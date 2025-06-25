import numpy as np
import random
import time
import logging

import ssh_input
import util

# 定数
ROWS = 6
COLS = 6
CONNECT_N = 4  # N目並べのN
PLAYER_HUMAN = 1  # 人間プレイヤー
PLAYER_AI = 2    # AIプレイヤー
EMPTY = 0        # 空きマス

# プレイヤーの表示シンボル
# 画像のプロンプトに合わせて、人間を〇 (O)、AIをXとする
SYMBOL_HUMAN = "O"
SYMBOL_AI = "X"
SYMBOL_EMPTY = " "


def create_board():
    """空のゲーム盤を作成する"""
    return np.zeros((ROWS, COLS), dtype=int)


def drop_piece(board, col, player):
    """
    指定された列にプレイヤーの駒を落とす。
    成功した場合はTrue、列が満杯の場合はFalseを返す。
    """
    for r in range(ROWS - 1, -1, -1):  # 下から上に探索
        if board[r, col] == EMPTY:
            board[r, col] = player
            return True
    return False  # 列が満杯


def is_valid_location(board, col):
    """指定された列に駒を置けるかどうかをチェックする"""
    return 0 <= col < COLS and board[0, col] == EMPTY  # 盤の範囲内で、一番上が空いているか


def check_win(board, player):
    """
    指定されたプレイヤーが connect_n 個連続で並べたかどうかをチェックする。
    縦、横、斜め（両方向）をチェックする。
    """
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

    # 正斜め方向 (下から右へ) のチェック
    for r in range(ROWS - CONNECT_N + 1):
        for c in range(COLS - CONNECT_N + 1):
            if all(board[r+i, c+i] == player for i in range(CONNECT_N)):
                return True

    # 逆斜め方向 (上から右へ) のチェック
    for r in range(CONNECT_N - 1, ROWS):
        for c in range(COLS - CONNECT_N + 1):
            if all(board[r-i, c+i] == player for i in range(CONNECT_N)):
                return True

    return False


def get_valid_locations(board):
    """駒を置けるすべての有効な列のリストを返す"""
    valid_cols = []
    for col in range(COLS):
        if is_valid_location(board, col):
            valid_cols.append(col)
    return valid_cols


def evaluate_position(board, player):
    """
    現在の盤面を指定されたプレイヤーにとってどれだけ有利かを評価する。
    ここでは、単純に3連以上の数を数える。
    """
    score = 0
    # 横方向の評価
    for r in range(ROWS):
        for c in range(COLS - CONNECT_N + 1):
            window = board[r, c:c+CONNECT_N]
            if np.count_nonzero(window == player) == CONNECT_N - 1 and np.count_nonzero(window == EMPTY) == 1:
                score += 5  # 3連+空き1マス
            elif np.count_nonzero(window == player) == CONNECT_N - 2 and np.count_nonzero(window == EMPTY) == 2:
                score += 2  # 2連+空き2マス
    # 縦方向の評価 (上は塞がれていることが多いので、下方向への3連を重視)
    for c in range(COLS):
        for r in range(ROWS - CONNECT_N + 1):
            window = board[r:r+CONNECT_N, c]
            if np.count_nonzero(window == player) == CONNECT_N - 1 and np.count_nonzero(window == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(window == player) == CONNECT_N - 2 and np.count_nonzero(window == EMPTY) == 2:
                score += 2
    # 斜め方向の評価 (正斜め)
    for r in range(ROWS - CONNECT_N + 1):
        for c in range(COLS - CONNECT_N + 1):
            window = [board[r+i, c+i] for i in range(CONNECT_N)]
            if np.count_nonzero(np.array(window) == player) == CONNECT_N - 1 and np.count_nonzero(np.array(window) == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(np.array(window) == player) == CONNECT_N - 2 and np.count_nonzero(np.array(window) == EMPTY) == 2:
                score += 2
    # 斜め方向の評価 (逆斜め)
    for r in range(CONNECT_N - 1, ROWS):
        for c in range(COLS - CONNECT_N + 1):
            window = [board[r-i, c+i] for i in range(CONNECT_N)]
            if np.count_nonzero(np.array(window) == player) == CONNECT_N - 1 and np.count_nonzero(np.array(window) == EMPTY) == 1:
                score += 5
            elif np.count_nonzero(np.array(window) == player) == CONNECT_N - 2 and np.count_nonzero(np.array(window) == EMPTY) == 2:
                score += 2

    # 中央列の評価（中央に近いほど良い）
    center_col = COLS // 2
    # 簡単な中央バイアスを追加 (空いていれば)
    if board[0, center_col] == EMPTY:
        score += 3

    return score


def ai_choose_column_heuristic(board):
    """
    AIがヒューリスティックに基づいて最適な列を選ぶ戦略
    """
    valid_cols = get_valid_locations(board)
    if not valid_cols:
        return -1  # 有効な列がない場合

    best_col = random.choice(valid_cols)  # デフォルトはランダム
    best_score = -10000  # 非常に低いスコアで初期化

    # 1. 勝利できる手を探す (AI自身)
    for col in valid_cols:
        temp_board = board.copy()  # 盤面を一時的にコピー
        drop_piece(temp_board, col, PLAYER_AI)
        if check_win(temp_board, PLAYER_AI):
            return col  # 勝利できるなら迷わずその列を選ぶ

    # 2. 相手の勝利をブロックする手を探す (人間)
    for col in valid_cols:
        temp_board = board.copy()
        drop_piece(temp_board, col, PLAYER_HUMAN)  # 相手がそこに置いたらどうなるか
        if check_win(temp_board, PLAYER_HUMAN):
            return col  # 相手の勝利をブロックできるならその列を選ぶ

    # 3. それ以外の評価
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
    """ゲーム盤がすべて埋まっているかチェックする"""
    return np.all(board != EMPTY)


def print_board(chan, board):
    """ゲーム盤を画像形式で表示する"""
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
            else:  # PLAYER_AI
                row_str += SYMBOL_AI + "|"
        chan.send((row_str + "\r\n").encode('utf-8'))
        # 各行の間に空行（または罫線）を入れる場合はここに追加
        # print("-" * (COLS * 2 + 1)) # 必要であれば


def get_player_symbol(player_id):
    """プレイヤーIDから表示シンボルを取得する"""
    return SYMBOL_HUMAN if player_id == PLAYER_HUMAN else SYMBOL_AI


def run_game_vs_ai(chan, menu_mode):
    """人間 対 AI のゲームのメインループ"""
    board = create_board()
    game_over = False
    turn = 0  # 0は先攻、1は後攻

    util.send_text_by_key(chan, "hamlet_game.title", menu_mode)
    util.send_text_by_key(chan, "hamlet_game.rules",
                          menu_mode, rows=ROWS, cols=COLS, connect_n=CONNECT_N)
    util.send_text_by_key(chan, "hamlet_game.player_info",
                          menu_mode, symbol_human=SYMBOL_HUMAN, symbol_ai=SYMBOL_AI)

    # 先手を選択するかどうか尋ねる
    while True:
        util.send_text_by_key(
            chan, "hamlet_game.prompt_first_move", menu_mode, add_newline=False)
        first_choice_input = ssh_input.process_input(chan)
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

        # プレイヤーの表示を画像形式に合わせる
        player_prompt_symbol = get_player_symbol(current_player)

        if current_player == PLAYER_HUMAN:
            col_choice_str = ""
            while True:
                util.send_text_by_key(chan, "hamlet_game.prompt_your_turn",
                                      menu_mode, symbol=player_prompt_symbol, add_newline=False)
                col_choice_str = ssh_input.process_input(chan)
                if col_choice_str is None:
                    return  # 切断
                if col_choice_str.strip().isdigit():
                    break
                else:
                    util.send_text_by_key(
                        chan, "common_messages.invalid_input", menu_mode)

            col_choice = int(col_choice_str) - 1

            if is_valid_location(board, col_choice):
                drop_piece(board, col_choice, current_player)
            else:
                util.send_text_by_key(
                    chan, "hamlet_game.invalid_column", menu_mode)
                continue  # ターンを消費しない
        else:  # AIのターン
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

        # 勝敗判定
        if check_win(board, current_player):
            print_board(chan, board)
            winner_name = get_player_name(current_player, menu_mode)
            winner_symbol = get_player_symbol(current_player)
            util.send_text_by_key(chan, "hamlet_game.win_message",
                                  menu_mode, winner=winner_name, symbol=winner_symbol)
            game_over = True
        elif is_board_full(board):
            print_board(chan, board)
            # あなたのルール: 「すべての石を打ち尽くした場合後手勝ち」
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
            turn += 1  # 次のプレイヤーへ
            # プレイヤーの切り替え
            current_player = PLAYER_AI if current_player == PLAYER_HUMAN else PLAYER_HUMAN


def get_player_name(player_id, menu_mode):
    """プレイヤーIDからプレイヤー名を取得する"""
    if player_id == PLAYER_HUMAN:
        return util.get_text_by_key("hamlet_game.player_name_human", menu_mode)
    else:
        return util.get_text_by_key("hamlet_game.player_name_ai", menu_mode)
