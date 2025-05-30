import logging
import yaml

import util
import ssh_input


def load_menu_config(config_path: str):
    """階層メニュー設定ファイルを読み込む"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        logging.error(f"メニュー設定ファイル読み込みエラー ({config_path}): {e}")
        return None


def display_menu(chan, items, menu_mode, title_key, prompt_key):
    """メニュー表示"""
    util.send_text_by_key(chan, title_key, menu_mode)
    # item['name'] が直接文字列であることを想定して修正
    for item in items:
        item_name = item.get('name', 'No name')  # name が直接文字列
        item_description = item.get('description', 'No description')
        # description が None の場合や空文字列の場合のフォールバック
        display_description = item_description if item_description else 'No description'
        chan.send(
            f"{item['number']}: {item_name} - {display_description} \r\n")
    util.send_text_by_key(chan, prompt_key, menu_mode, add_newline=False)


def navigate_menu(chan, items, menu_mode, title_key, prompt_key):
    """メニューナビゲート"""
    # items が存在しない場合のエラーハンドリング
    if not items:
        logging.error("メニュー項目が空です。")
        return "back"
    while True:
        display_menu(chan, items, menu_mode, title_key, prompt_key)
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


def handle_hierarchical_menu(chan, config_path: str, menu_mode: str):
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

    while True:
        # 今の階層の項目でメニュー表示・選択
        selected_item = navigate_menu(
            chan, current_level_items, menu_mode, "hierarchical_menu.title", "hierarchical_menu.prompt")

        if selected_item == "back":
            if not path_stack:  # スタックが空ならトップメニューに戻る
                return
            current_level_items = path_stack.pop()
            continue
        elif selected_item is None:
            return  # 切断

        # selected_item が辞書型であることを確認してからキーアクセス
        if isinstance(selected_item, dict):
            if "type" in selected_item:
                item_type = selected_item["type"]
                if item_type == "child":
                    if "items" in selected_item:  # 正しい child 構造
                        path_stack.append(current_level_items)
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
