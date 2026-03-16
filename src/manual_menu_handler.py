# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""手書きメニューハンドラ。

このモジュールは、主に「モード1」で使用される、手動で定義された
テキストベースのメニューを処理します。YAML設定ファイルを読み込んで、
入れ子になった一連のメニューを構築・ナビゲートし、最終的にBBS掲示板への
入室などの特定のアクションに繋げます。
"""

import yaml
import logging

from . import util


def _load_manual_menu_config(config_path: str):
    """手書きメニューのYAML設定ファイルを読み込み、パースします。"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        logging.error(f"メニュー設定ファイルが見つかりません。{config_path}")
        return None
    except yaml.YAMLError as e:
        logging.error(f"メニュー設定ファイルの読み込みエラー ({config_path}): {e}")
        return None
    except Exception as e:
        logging.error(f"メニュー設定ファイルの読み込み中に予期せぬエラー ({config_path}): {e}")
        return None


def _display_manual_menu(chan, menu_data, current_menu_mode):
    """指定されたメニューデータの `display_text` をクライアントに送信します。"""
    if "display_text" in menu_data:
        display_text_source = menu_data["display_text"]
        actual_display_text = ""

        if isinstance(display_text_source, dict):
            mode_key = f"mode_{current_menu_mode}"
            # 現在のモードのテキストを取得。なければmode_1にフォールバック。
            actual_display_text = display_text_source.get(mode_key)
            if actual_display_text is None:
                actual_display_text = display_text_source.get("mode_1", "")
                if not actual_display_text:
                    logging.warning(
                        f"Menu display text not found for mode '{current_menu_mode}' or '1'.")
                    actual_display_text = "Menu text not found."
        elif isinstance(display_text_source, str):
            actual_display_text = display_text_source
        else:
            logging.warning(
                f"Invalid format for display_text in menu data: {type(display_text_source)}")
            util.send_text_by_key(
                chan, "common_messages.error", current_menu_mode)
            return

        if actual_display_text is None:
            actual_display_text = ""

        processed_text = actual_display_text.replace(
            '\r\n', '\n').replace('\n', '\r\n')
        chan.send(processed_text.encode('utf-8'))
        if not processed_text.endswith('\r\n'):
            chan.send(b'\r\n')

    else:
        logging.warning("Menu data is missing 'display_text'.")
        util.send_text_by_key(chan, "common_messages.error", current_menu_mode)


def process_manual_menu(chan, login_id: str, menu_mode: str, menu_config_path: str, initial_menu_id: str, menu_type: str):
    """手書きメニューを処理するメイン関数です。

    Args:
        menu_type (str): "bbs" または "chat" など、最終的なアクションの種類。

    Returns:
        str: 選択された `board_id` や "exit_bbs_menu" などの結果文字列。
        dict: Chatの場合は選択されたルームの `action` 辞書。
        None: 切断された場合。
    """
    menu_config = _load_manual_menu_config(menu_config_path)
    if not menu_config:
        util.send_text_by_key(chan, "common_messages.error", menu_mode)
        return "back_to_top"  # 読めないときはトップに戻る(安全策)

    current_menu_id = initial_menu_id
    menu_stack = []

    while True:
        # 現在のメニューIDが設定ファイルに存在するかチェック
        if current_menu_id not in menu_config:
            logging.error(f"定義されていないメニューIDが指定されました{current_menu_id}")
            util.send_text_by_key(chan, "common_messages.error", menu_mode)
            if menu_stack:
                current_menu_id = menu_stack.pop()
                continue
            return "back_to_top"  # 読めないときはトップに戻る(安全策)

        # メニュー表示とプロンプト
        current_menu_data = menu_config[current_menu_id]
        _display_manual_menu(chan, current_menu_data, menu_mode)

        # YAMLで定義されたプロンプトキーを使用し、なければデフォルトのプロンプトを表示
        prompt_key = current_menu_data.get(
            "prompt_key", "common_messages.select_prompt")
        # 新着チェックを追加
        util.prompt_handler(chan, login_id, menu_mode)
        util.send_text_by_key(chan, prompt_key,
                              menu_mode, add_newline=False)
        user_input_raw = chan.process_input()

        if user_input_raw is None:
            return None  # 切断

        user_input = user_input_raw.strip().lower()

        # ユーザー入力に対応するアクションを取得 (空入力 "" もキーとして扱えます)
        actions = current_menu_data.get("actions", {})
        action_to_take = actions.get(user_input)

        if action_to_take:
            action_type = action_to_take.get("type")

            # --- アクションタイプに応じた処理の分岐 ---
            if action_type == "submenu":
                target_menu_id = action_to_take.get("target_menu_id")
                if target_menu_id:
                    menu_stack.append(current_menu_id)  # 今のメニューをスタック
                    current_menu_id = target_menu_id
                else:
                    logging.error(
                        f"submenuアクションにtarget_menu_idがありません:{action_to_take}")
                    util.send_text_by_key(
                        chan, "common_messages.error", menu_mode)

            elif action_type == "board":
                if menu_type == "bbs":
                    board_id = action_to_take.get("board_id")
                    if board_id:
                        return board_id
                    else:
                        logging.error(
                            f"boardアクションにboard_idがありません:{action_to_take}")
                        util.send_text_by_key(
                            chan, "common_messages.error", menu_mode)

            elif action_type == "room":
                if menu_type == "chat":
                    if action_to_take.get("room_id"):
                        return action_to_take  # room_id と room_name を含む辞書を返す
                    else:
                        logging.error(
                            f"roomアクションにroom_idがありません:{action_to_take}")
                        util.send_text_by_key(
                            chan, "common_messages.error", menu_mode)
                else:
                    logging.error(
                        f"不正なmenu_type({menu_type})でroomアクションが指定されました。")

            elif action_type == "back":
                if menu_stack:
                    current_menu_id = menu_stack.pop()
                else:
                    if menu_type == "bbs":
                        return "exit_bbs_menu"
                    elif menu_type == "chat":
                        return "exit_chat_menu"
                    else:
                        return "back_to_top"

            elif action_type == "exit_bbs_menu":
                return "exit_bbs_menu"
            elif action_type == "exit_chat_menu":
                return "exit_chat_menu"
            elif action_type == "exit_to_top":
                return "back_to_top"
            else:
                logging.warning(
                    f"未定義または未定義のアクションタイプ({action_type})が指定されました: {current_menu_id}")
                util.send_text_by_key(chan, "common_messages.error", menu_mode)
        else:
            util.send_text_by_key(
                chan, "common_messages.invalid_command", menu_mode)
