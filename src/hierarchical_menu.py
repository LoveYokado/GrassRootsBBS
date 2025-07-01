import logging
import yaml

import util
import ssh_input
import sqlite_tools


class HierarchicalMenu:
    def __init__(self, chan, config_path, menu_mode, menu_type, dbname=None, enrich_boards=False):
        self.chan = chan
        self.config_path = config_path
        self.menu_mode = menu_mode
        self.menu_type = menu_type
        self.dbname = dbname
        self.enrich_boards = enrich_boards
        self.config = None
        self.path_stack = []
        self.current_path_names = []

    def _load_config(self):
        """階層メニュー設定ファイルを読み込む"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
            return True
        except Exception as e:
            logging.error(f"メニュー設定ファイル読み込みエラー ({self.config_path}): {e}")
            return False

    def _enrich_board_items(self, items):
        """掲示板アイテムのリストにDBから名前と説明を補完する"""
        if not items:
            return []
        enriched_items = []
        for item in items:
            enriched_item = item.copy()
            if enriched_item.get('type') == 'board':
                shortcut_id = enriched_item.get('id')
                if shortcut_id:
                    board_info_db = sqlite_tools.get_board_by_shortcut_id(
                        self.dbname, shortcut_id)
                    if board_info_db:
                        enriched_item['name'] = board_info_db.get(
                            'name', shortcut_id)
                        enriched_item['description'] = board_info_db.get(
                            'description', '')
                    else:
                        enriched_item['name'] = f"{shortcut_id} (unregistered)"
                        enriched_item['description'] = 'This board is not registered in the database.'
            elif "items" in enriched_item:
                enriched_item["items"] = self._enrich_board_items(
                    enriched_item["items"])
            enriched_items.append(enriched_item)
        return enriched_items

    def _display_menu(self, items):
        """現在のメニュー項目を表示する"""
        for item in items:
            item_name = item.get('name', 'No name')
            item_description = item.get('description', '')
            display_description = item_description if item_description else ''
            description_lines = display_description.splitlines()

            self.chan.send(
                f"{item['number']}: {item_name}\r\n".encode('utf-8'))

            if description_lines:
                indent_spaces = " " * 6
                for line in description_lines:
                    self.chan.send(
                        f"{indent_spaces}{line.strip()}\r\n".encode('utf-8'))

    def _navigate_menu(self, items):
        """メニューを表示し、ユーザーの選択を処理する"""
        if not items:
            logging.error("メニュー項目が空です。")
            return "back"

        self._display_menu(items)

        # プロンプト表示
        menu_type_loc_key = f"common_menu_names.{menu_type.lower()}"
        menu_type_localized_name = util.get_text_by_key(
            menu_type_loc_key, menu_mode, default_value=menu_type)
        current_hierarchy_path_str = "/".join(self.current_path_names)
        if not self.current_path_names:
            prompt_hierarchy_display_str = menu_type_localized_name
        else:
            prompt_hierarchy_display_str = f"{menu_type_localized_name}/{current_hierarchy_path_str}"

        util.send_text_by_key(self.chan, "prompt.hierarchy", self.menu_mode, add_newline=False,
                              menu_name=self.menu_type.upper(), hierarchy=prompt_hierarchy_display_str)

        user_input = ssh_input.process_input(self.chan)
        if user_input is None:
            return None
        user_input = user_input.strip()
        if user_input == "":
            return "back"

        try:
            choice = int(user_input)
            for item in items:
                if item.get("number") == choice:
                    return item
            self.chan.send("選択された項目は存在しません。\r\n".encode('utf-8'))
            return "continue"
        except ValueError:
            self.chan.send("入力された値は数値でありません。\r\n".encode('utf-8'))
            return "continue"

    def run(self):
        """階層メニューを処理するメインループ"""
        if not self._load_config() or 'categories' not in self.config:
            util.send_text_by_key(
                self.chan, "common_messages.error", self.menu_mode)
            logging.warning(f"メニュー設定が無効か、カテゴリが定義されていません: {self.config_path}")
            return None

        current_level_items = self.config.get('categories', [])
        if self.enrich_boards and self.dbname:
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
                    if self.enrich_boards and self.dbname:
                        current_level_items = self._enrich_board_items(
                            current_level_items)
                else:
                    return selected_item  # 末端項目
            else:
                util.send_text_by_key(
                    self.chan, "common_messages.error", self.menu_mode)
                logging.warning(
                    f"階層メニュー: 予期せぬ項目型です。selected_item: {selected_item}")


def handle_hierarchical_menu(chan, config_path: str, menu_mode: str, menu_type: str, dbname: str = None, enrich_boards: bool = False):
    """階層メニューを処理するためのラッパー関数"""
    menu = HierarchicalMenu(chan, config_path, menu_mode,
                            menu_type, dbname, enrich_boards)
    return menu.run()
