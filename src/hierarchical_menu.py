# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""階層メニューエンジン。

このモジュールは、YAML設定ファイルで定義された、入れ子構造の
テキストベースメニューを作成・ナビゲートするための汎用エンジンを提供します。
"""

import logging
import yaml

from . import util, database


class MenuEngine:
    def __init__(self, chan, config_path, menu_mode, menu_type, enrich_boards=False):
        """MenuEngineのコンストラクタ。"""
        self.chan = chan
        self.config_path = config_path
        self.menu_mode = menu_mode
        self.menu_type = menu_type
        self.enrich_boards = enrich_boards
        self.config = None
        self.path_stack = []
        self.current_path_names = []

    def _load_config(self):
        """階層メニューのYAML設定ファイルを読み込みます。"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
            return True
        except Exception as e:
            logging.error(f"メニュー設定ファイル読み込みエラー ({self.config_path}): {e}")
            return False

    def _enrich_board_items(self, items):
        """掲示板アイテムに、DBから名前と説明を補完します。"""
        if not items:
            return []
        enriched_items = []
        for item in items:
            enriched_item = item.copy()
            if enriched_item.get('type') == 'board':
                shortcut_id = enriched_item.get('id')
                if shortcut_id:
                    board_info_db = database.get_board_by_shortcut_id(
                        shortcut_id)
                    if board_info_db:
                        enriched_item['name'] = board_info_db['name'] if 'name' in board_info_db.keys(
                        ) else shortcut_id
                        enriched_item['description'] = board_info_db['description'] if 'description' in board_info_db.keys(
                        ) else ''
                    else:
                        enriched_item['name'] = f"{shortcut_id} (unregistered)"
                        enriched_item['description'] = 'This board is not registered in the database.'
            elif "items" in enriched_item:
                enriched_item["items"] = self._enrich_board_items(
                    enriched_item["items"])
            enriched_items.append(enriched_item)
        return enriched_items

    def _display_menu(self, items):
        """現在の階層のメニュー項目をクライアントに表示します。"""
        for i, item in enumerate(items):
            item_name = item.get('name', 'No name')
            item_description = item.get('description', '')
            display_description = item_description if item_description else ''
            description_lines = display_description.splitlines()

            self.chan.send(
                f"[{i+1}] {item_name}\r\n".encode('utf-8'))

            if description_lines:
                indent_spaces = " " * 6
                for line in description_lines:
                    self.chan.send(
                        f"{indent_spaces}{line.strip()}\r\n".encode('utf-8'))

    def _navigate_menu(self, items):
        """メニューを表示し、ユーザーの選択を処理します。"""
        if not items:
            logging.error("メニュー項目が空です。")
            return "back"

        self._display_menu(items)

        # プロンプト表示
        menu_type_loc_key = f"common_menu_names.{self.menu_type.lower()}"
        menu_type_localized_name = util.get_text_by_key(
            menu_type_loc_key, self.menu_mode, default_value=self.menu_type)
        current_hierarchy_path_str = "/".join(self.current_path_names)
        if not self.current_path_names:
            prompt_hierarchy_display_str = menu_type_localized_name
        else:
            prompt_hierarchy_display_str = f"{menu_type_localized_name}/{current_hierarchy_path_str}"

        util.send_text_by_key(self.chan, "prompt.hierarchy", self.menu_mode, add_newline=False,
                              menu_name=self.menu_type.upper(), hierarchy=prompt_hierarchy_display_str)

        user_input = self.chan.process_input()
        if user_input is None:
            return None
        user_input = user_input.strip()
        if user_input == "":
            return "back"

        try:
            choice_index = int(user_input) - 1
            if 0 <= choice_index < len(items):
                return items[choice_index]
            else:
                self.chan.send("選択された項目は存在しません。\r\n".encode('utf-8'))
                return "continue"
        except ValueError:
            self.chan.send("入力された値は数値でありません。\r\n".encode('utf-8'))
            return "continue"

    def run(self):
        """階層メニューを処理するメインループ。"""
        if not self._load_config() or 'categories' not in self.config:
            util.send_text_by_key(
                self.chan, "common_messages.error", self.menu_mode)
            logging.warning(f"メニュー設定が無効か、カテゴリが定義されていません: {self.config_path}")
            return None

        current_level_items = self.config.get('categories', [])
        if self.enrich_boards:
            current_level_items = self._enrich_board_items(current_level_items)

        while True:
            selected_item = self._navigate_menu(current_level_items)

            if selected_item is None:
                return None  # 切断
            elif selected_item == "back":
                if not self.path_stack:
                    return None  # トップレベルで戻る -> 終了
                current_level_items = self.path_stack.pop()
                if self.current_path_names:
                    self.current_path_names.pop()
            elif selected_item == "continue":
                continue  # 無効な入力の場合
            elif isinstance(selected_item, dict):
                if selected_item.get("type") == "child" and "items" in selected_item:
                    self.path_stack.append(current_level_items)
                    self.current_path_names.append(
                        selected_item.get('name', 'Unknown'))
                    current_level_items = selected_item["items"]
                    if self.enrich_boards:
                        current_level_items = self._enrich_board_items(
                            current_level_items)
                else:
                    return selected_item  # 末端項目
            else:
                util.send_text_by_key(
                    self.chan, "common_messages.error", self.menu_mode)
                logging.warning(
                    f"階層メニュー: 予期せぬ項目型です。selected_item: {selected_item}")


def handle_hierarchical_menu(chan, config_path: str, menu_mode: str, menu_type: str, enrich_boards: bool = False):
    """階層メニューを処理するためのエントリーポイントとなるラッパー関数。"""
    menu = MenuEngine(chan, config_path, menu_mode,
                      menu_type, enrich_boards)
    return menu.run()
