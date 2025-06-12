import logging
import yaml

import util
import ssh_input
import sqlite_tools


def load_menu_config(config_path: str):
    """階層メニュー設定ファイルを読み込む"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        logging.error(f"メニュー設定ファイル読み込みエラー ({config_path}): {e}")
        return None


def _enrich_board_items_with_db_data(items, dbname, menu_mode):
    """
    掲示板アイテムのリストにDBから名前と説明を拾う
    iemsはbbs.ymlを参照する
    """
    if not items:
        return []
    enriched_items = []
    for item in items:
        enriched_item = item.copy()
        if enriched_item.get('type') == 'board':
            shortcut_id = enriched_item.get('id')
            if shortcut_id:
                board_info_db = sqlite_tools.get_board_by_shortcut_id(
                    dbname, shortcut_id)
                if board_info_db:
                    enriched_item['name'] = board_info_db['name'] if 'name' in board_info_db.keys(
                    ) else shortcut_id
                    enriched_item['description'] = board_info_db['description'] if board_info_db.keys(
                    ) else ''
                else:  # DBにない場合
                    enriched_item['name'] = f"{shortcut_id} (unregistered)"
                    enriched_item['description'] = 'this board is not registered'
        elif "items" in enriched_item:
            enriched_item["items"] = _enrich_board_items_with_db_data(
                enriched_item["items"], dbname, menu_mode)
        enriched_items.append(enriched_item)
    return enriched_items


def display_menu(chan, items, menu_mode, title_key, prompt_key, menu_name_for_prompt: str, hierarchy_str_for_prompt: str):
    """メニュー表示"""
    # title_key は "hierarchy" などのベースキーを期待。menu_mode は util.send_text_by_key 内部で解決。
    # util.send_text_by_key(chan, title_key, menu_mode) # タイトルはプロンプトに含める形に変更

    # item['name'] が直接文字列であることを想定して修正
    for item in items:
        item_name = item.get('name', 'No name')  # name が直接文字列
        item_description = item.get('description', 'No description')
        # description が None の場合は空文字列として扱う
        display_description = item_description if item_description else ''
        description_lines = display_description.splitlines()
        first_line_desc = description_lines[0].strip(
        ) if description_lines else ""

        # 項目番号と名前を表示
        chan.send(
            f"{item['number']}: {item_name}\r\n".encode(
                'utf-8')

        )

        # 説明文をインデントして表示
        if description_lines:
            indent_spaces = " " * 6  # 6文字のインデント
            for line in description_lines:
                chan.send(f"{indent_spaces}{line.strip()}\r\n".encode('utf-8'))

    # プロンプト表示 (menu_name と hierarchy を渡す)
    util.send_text_by_key(chan, prompt_key, menu_mode, add_newline=False,
                          menu_name=menu_name_for_prompt, hierarchy=hierarchy_str_for_prompt)


def navigate_menu(chan, items, menu_mode, title_key, prompt_key, menu_name_for_prompt: str, hierarchy_str_for_prompt: str):
    """メニューナビゲート"""
    # items が存在しない場合のエラーハンドリング
    if not items:
        logging.error("メニュー項目が空です。")
        return "back"
    while True:
        display_menu(chan, items, menu_mode, title_key, prompt_key,
                     menu_name_for_prompt, hierarchy_str_for_prompt)
        user_input = ssh_input.process_input(chan)
        if user_input is None:
            return None  # 切断
        user_input = user_input.strip()
        if user_input == "":
            return "back"  # 戻る

        try:
            choice = int(user_input)
            for item in items:
                if item.get("number") == choice:
                    return item
            chan.send(
                "選択された項目は存在しません。 \r\n"
            )
        except ValueError:
            chan.send(
                f"入力された値は数値でありません。 \r\n"
            )


def handle_hierarchical_menu(chan, config_path: str, menu_mode: str, menu_type: str, dbname: str = None, enrich_boards: bool = False):
    """階層メニューを処理する"""
    config = load_menu_config(config_path)
    if not config or 'categories' not in config:
        util.send_text_by_key(
            chan, "common_messages.error", menu_mode
        )
        logging.warning("メニュー設定が無効か、カテゴリが定義されていません :{config_path}")
        return None

    initial_level_items = config.get('categories', [])
    if not initial_level_items:
        util.send_text_by_key(
            chan, "common_messages.error", menu_mode
        )
        logging.warning("階層構造のカテゴリがありません:{config_path}")
        return
    path_stack = []
    current_level_items = initial_level_items
    current_path_names = []  # パンくずリスト用の表示名スタック

    # 掲示板メニューの場合、DBから名前と説明を保管する
    if enrich_boards and dbname:
        current_level_items = _enrich_board_items_with_db_data(
            current_level_items, dbname, menu_mode)

    while True:
        # パンくずリスト文字列の生成
        current_hierarchy_path_str = "/".join(current_path_names)

        # 今の階層の項目でメニュー表示・選択
        # title_key は直接使わず、prompt_key で指定されるプロンプトにタイトル情報が含まれる想定
        # prompt_key は "hierarchy" のようなベースキーを渡す

        menu_type_loc_key = f"common_menu_names.{menu_type.lower()}"
        menu_type_localized_name = util.get_text_by_key(
            menu_type_loc_key, menu_mode, default_value=menu_type)

        if not current_path_names:  # トップレベル
            prompt_hierarchy_display_str = menu_type_localized_name
        else:  # サブカテゴリ
            prompt_hierarchy_display_str = f"{menu_type_localized_name}/{current_hierarchy_path_str}"

        selected_item = navigate_menu(
            chan, current_level_items, menu_mode,
            "hierarchy", "prompt.hierarchy",
            menu_type.upper(),
            prompt_hierarchy_display_str
        )
        if selected_item == "back":
            if not path_stack:  # スタックが空ならトップメニューに戻る
                return
            current_level_items = path_stack.pop()
            if current_path_names:  # 一つ前の階層に戻る
                current_path_names.pop()
            continue
        elif selected_item is None:
            return  # 切断

        # selected_item が辞書型であることを確認してからキーアクセス
        if isinstance(selected_item, dict):
            if "type" in selected_item:
                item_type = selected_item["type"]
                if item_type == "child":
                    if "items" in selected_item:  # 正しい child 構造
                       # スタックに積む前に、現在のレベルのアイテムも必要なら補完する
                        # ただし、current_level_items は既に補完済みのはず
                        current_path_names.append(
                            selected_item.get('name', 'Unknown'))
                        path_stack.append(current_level_items)  # 補完済みのものをスタックに
                        current_level_items = selected_item["items"]
                    else:  # child type だが items がない (YAML構造の問題の可能性)
                        util.send_text_by_key(
                            chan, "common_messages.error", menu_mode)
                        logging.warning(
                            f"階層メニュー: 'child' type の項目に 'items' がありません。selected_item: {selected_item}"
                        )
                else:  # "child" 以外の type は末端項目として扱う
                    return selected_item  # 呼び出し元がこの type を解釈する
            elif "items" in selected_item:  # type キーなし、items キーあり (暗黙的なカテゴリ)
                current_path_names.append(selected_item.get('name', 'Unknown'))
                path_stack.append(current_level_items)
                current_level_items = selected_item["items"]
            else:  # 辞書だが、type も items もない -> 末端項目として扱う
                return selected_item  # 呼び出し元がこの項目を解釈する
        else:  # "back", None, dict 以外の場合 (通常ここには来ないはず)
            # このelseブロックは、navigate_menuが予期せずdictでも"back"でもNoneでもない値を返した場合のフォールバック
            # 通常は発生しづらいが、念のためエラーログを残す
            if selected_item is not None and selected_item != "back":  # navigate_menuが空のitemsで"back"を返す場合を除く
                util.send_text_by_key(chan, "common_messages.error", menu_mode)
                logging.warning(
                    f"階層メニュー: 予期せぬ項目型です。selected_item の型: {type(selected_item)}, 内容: {selected_item}"
                )
        continue  # エラーケースやナビゲーション後、メニューを再表示するためにループを継続
