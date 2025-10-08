# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""テキストアドベンチャープラグインのメインロジック。

このプラグインは、ホストアプリケーションの変更を一切行わず、
提供された `GrbbsApi` の汎用データストレージ機能 (`save_data`, `get_data`) のみを使用して
ゲームデータの永続化を実現しています。
"""

import uuid
import json


def _deserialize_data(raw_data, default_value=None):
    """api.get_data()から返されたデータを安全にデシリアライズするヘルパー関数。"""
    if raw_data is None:
        return default_value if default_value is not None else [] if isinstance(default_value, list) else {}
    if isinstance(raw_data, (list, dict)):
        return raw_data
    if isinstance(raw_data, str):
        try:
            return json.loads(raw_data)
        except json.JSONDecodeError:
            return default_value if default_value is not None else [] if isinstance(default_value, list) else {}
    return raw_data


def _play_game(api, game_id):
    """指定されたゲームをプレイする関数。"""
    game = _deserialize_data(api.get_data(f"game:{game_id}"), default_value={})
    if not game:
        api.send("\r\nゲームが見つかりませんでした。\r\n")
        return

    current_scene_id = game.get('start_scene_id')
    if not current_scene_id:
        api.send("\r\nこのゲームには開始シーンが設定されていません。\r\n")
        return

    while current_scene_id:
        scene = _deserialize_data(api.get_data(
            f"scene:{game_id}:{current_scene_id}"), default_value={})
        if not scene:
            api.send("\r\nシーンデータが見つかりません。ゲームを終了します。\r\n")
            break

        api.send(b'\x1b[2J\x1b[H')  # 画面クリア
        api.send("\r\n" + scene['text'].replace('\n', '\r\n') + "\r\n\r\n")

        choices = _deserialize_data(api.get_data(
            f"choices:{game_id}:{current_scene_id}"), default_value=[])

        if not choices:
            api.send("--- 終わり ---\r\n")
            api.send("何かキーを押すとメニューに戻ります...")
            api.get_input()
            break

        for i, choice in enumerate(choices):
            api.send(f"[{i + 1}] {choice['text']}\r\n")

        api.send("\r\nどうしますか？: ")
        user_input = api.get_input()

        if user_input is None:  # 接続が切れた場合
            break

        try:
            choice_index = int(user_input) - 1
            if 0 <= choice_index < len(choices):
                current_scene_id = choices[choice_index]['next_scene_id']
            else:
                api.send("無効な選択です。もう一度選んでください。\r\n")
        except ValueError:
            api.send("数字で選択してください。\r\n")


def _handle_play_menu(api, context):
    """プレイするゲームを選択するメニューを表示します。"""
    while True:
        api.send(b'\x1b[2J\x1b[H')
        api.send("--- テキストアドベンチャー: ゲームを選択 ---\r\n\r\n")

        game_index = _deserialize_data(
            api.get_data("game_index"), default_value=[])

        if not game_index:
            api.send("プレイできるゲームがありません。\r\n")
            api.send("何かキーを押すと戻ります...")
            api.get_input()
            return

        games_details = []
        for index_item in game_index:
            game_detail = _deserialize_data(api.get_data(
                f"game:{index_item['id']}"), default_value={})
            if game_detail:
                games_details.append(game_detail)

        for i, game in enumerate(games_details):
            api.send(f"[{i + 1}] {game['title']}\r\n")
            author_name = game.get(
                'author_login_id', game.get('author_id', '不明'))
            open_marker = " (OPEN)" if game.get('open_edit', False) else ""
            api.send(
                f"    作成者: {author_name}{open_marker} | {game.get('description', '')}\r\n\r\n")

        api.send("プレイするゲームの番号を入力してください ([D]削除 [E]戻る): ")
        choice = api.get_input()

        if choice is None or choice.lower() == 'e':
            break
        elif choice.lower() == 'd':
            _handle_delete_game(api, context, games_details)
            # 削除後はメニューを再表示するためにループを継続
            continue

        try:
            game_choice_index = int(choice) - 1
            if 0 <= game_choice_index < len(games_details):
                _play_game(api, games_details[game_choice_index]['id'])
            else:
                api.send("無効な番号です。\r\n")
        except ValueError:
            api.send("数字で入力してください。\r\n")


def _create_game(api, context):
    """新しいゲームを作成する関数。"""
    api.send(b'\x1b[2J\x1b[H')
    api.send("--- 新しいゲームの作成 ---\r\n")
    api.send("ゲームのタイトルを入力してください: ")
    title = api.get_input()
    if not title:
        api.send("タイトルは必須です。作成を中止しました。\r\n")
        return

    api.send("ゲームの説明を入力してください: ")
    description = api.get_input()

    api.send("このゲームを誰でも編集可能にしますか？ (y/n): ")
    open_edit_choice = api.get_input()
    is_open_edit = open_edit_choice and open_edit_choice.lower() == 'y'

    game_id = str(uuid.uuid4())
    new_game_data = {
        "id": game_id,
        "title": title,
        "description": description,
        "author_id": context['user_id'],
        "author_login_id": context['login_id'],
        "open_edit": is_open_edit,
        "start_scene_id": None,
        "scene_ids": []  # このゲームに属するシーンIDのリスト
    }
    api.save_data(f"game:{game_id}", new_game_data)

    game_index = _deserialize_data(
        api.get_data("game_index"), default_value=[])
    game_index.append({"id": game_id, "title": title})
    api.save_data("game_index", game_index)

    api.send(f"\r\nゲーム '{title}' を作成しました！\r\n")
    api.send("次に、最初のシーンを作成します。\r\n")
    scene_id = _create_scene(api, game_id)

    if scene_id:
        # ゲームデータに開始シーンIDを設定
        new_game_data['start_scene_id'] = scene_id
        # ゲームデータにシーンIDのリストを追加
        if 'scene_ids' not in new_game_data:
            new_game_data['scene_ids'] = []
        new_game_data['scene_ids'].append(scene_id)
        api.save_data(f"game:{game_id}", new_game_data)
        api.send("このシーンがゲームの開始シーンとして設定されました。\r\n")
        # 最初のシーンの選択肢作成フローへ
        api.send("続けて、このシーンからの選択肢を作成しますか？ (y/n): ")
        if api.get_input().lower() == 'y':
            _create_choice(api, scene_id, game_id)


def _create_scene(api, game_id):
    """新しいシーンを作成する関数。"""
    api.send("\r\n--- 新しいシーンの作成 ---\r\n")
    api.send("シーンID (例: '玄関', '地下室への階段') を入力してください: ")
    scene_id = api.get_input()
    if not scene_id or not scene_id.strip():
        api.send("シーンIDは必須です。作成を中止しました。\r\n")
        return None
    scene_id = scene_id.strip()

    # シーンIDがこのゲーム内で既に使用されていないかチェック
    game_data_check = _deserialize_data(
        api.get_data(f"game:{game_id}"), default_value={})
    existing_scene_ids = game_data_check.get('scene_ids', [])

    if scene_id in existing_scene_ids:
        api.send(f"シーンID '{scene_id}' は既に使用されています。作成を中止しました。\r\n")
        return None

    api.send("シーンのテキストを入力してください ('.'だけの行で終了):\r\n")

    lines = []
    while True:
        line = api.get_input()
        if line == '.':
            break
        lines.append(line)
    scene_text = "\n".join(lines)

    if not scene_text:
        api.send("シーンテキストは必須です。作成を中止しました。\r\n")
        return None

    new_scene_data = {
        "id": scene_id,
        "game_id": game_id,
        "text": scene_text
    }
    api.save_data(f"scene:{game_id}:{scene_id}", new_scene_data)

    # ゲームデータにこのシーンIDを追加
    game_data = _deserialize_data(
        api.get_data(f"game:{game_id}"), default_value={})
    if game_data and 'scene_ids' in game_data:
        if scene_id not in game_data['scene_ids']:
            game_data['scene_ids'].append(scene_id)
            api.save_data(f"game:{game_id}", game_data)

    api.send(f"\r\nシーン '{scene_id}' を作成しました。\r\n")
    return scene_id


def _create_choice(api, from_scene_id, game_id):
    """新しい選択肢を作成する関数。"""
    while True:
        api.send(f"\r\n--- シーン {from_scene_id} の選択肢作成 ---\r\n")
        api.send("選択肢のテキストを入力してください (空入力で終了): ")
        choice_text = api.get_input()
        if not choice_text:
            break

        api.send("この選択肢を選んだ時の移動先シーンIDを入力してください: ")
        next_scene_id_str = api.get_input()
        if not next_scene_id_str:
            api.send("移動先シーンIDは必須です。作成を中止しました。\r\n")
            continue

        next_scene_id = next_scene_id_str.strip()

        # 飛び先シーンがこのゲーム内に存在するかチェック
        scene_exists = api.get_data(
            f"scene:{game_id}:{next_scene_id}") is not None

        if not scene_exists:
            api.send(
                f"シーンID '{next_scene_id}' は存在しません。新しいシーンとして作成しますか？ (y/n): ")
            confirm_create = api.get_input()
            if confirm_create and confirm_create.lower() == 'y':
                if game_id:
                    # 指定されたIDで新しい空のシーンを作成
                    new_scene_data = {"id": next_scene_id,
                                      "game_id": game_id, "text": "(未編集のシーン)"}
                    api.save_data(
                        f"scene:{game_id}:{next_scene_id}", new_scene_data)
                    api.send(
                        f"空のシーン '{next_scene_id}' を作成しました。後で編集してください。\r\n")  # noqa
                    # ゲームデータにこのシーンIDを追加
                    game_data = _deserialize_data(api.get_data(
                        f"game:{game_id}"), default_value={})
                    if game_data and 'scene_ids' in game_data:
                        if next_scene_id not in game_data['scene_ids']:
                            game_data['scene_ids'].append(next_scene_id)
                            api.save_data(f"game:{game_id}", game_data)
                else:
                    api.send("ゲームIDが取得できず、新しいシーンを作成できませんでした。\r\n")
                    continue
            else:
                api.send("選択肢の作成を中止しました。\r\n")
                continue

        choice_id = str(uuid.uuid4())
        new_choice = {
            "id": choice_id,
            "text": choice_text,
            "next_scene_id": next_scene_id
        }

        choices = _deserialize_data(api.get_data(
            f"choices:{game_id}:{from_scene_id}"), default_value=[])

        choices.append(new_choice)
        api.save_data(f"choices:{game_id}:{from_scene_id}", choices)
        api.send("選択肢を作成しました。\r\n")


def _edit_scenes_menu(api, game_data):
    """ゲームに属するシーンを編集するためのメニュー。"""
    game_id = game_data['id']
    while True:
        api.send(b'\x1b[2J\x1b[H')
        api.send(f"--- 「{game_data['title']}」のシーン編集 ---\r\n\r\n")

        # ゲームデータを再読み込みして最新のシーンリストを取得
        current_game_data = _deserialize_data(
            api.get_data(f"game:{game_id}"), default_value={})
        scene_ids = current_game_data.get('scene_ids', [])

        if not scene_ids:
            api.send("このゲームにはシーンがありません。\r\n")
        else:
            for i, scene_id in enumerate(scene_ids):
                start_marker = " (開始)" if scene_id == current_game_data.get(
                    'start_scene_id') else ""
                api.send(f"[{i + 1}] {scene_id}{start_marker}\r\n")

        api.send("\r\n[A] 新規シーン作成  [E] 戻る\r\n")
        api.send("編集するシーンの番号を入力してください: ")
        choice = api.get_input()

        if choice is None or choice.lower() == 'e':
            break
        elif choice.lower() == 'a':
            new_scene_id = _create_scene(api, game_id)
            if new_scene_id and not current_game_data.get('start_scene_id'):
                # 開始シーンがなければ、最初のシーンを開始シーンに設定
                current_game_data['start_scene_id'] = new_scene_id
                api.save_data(f"game:{game_id}", current_game_data)
                api.send("このシーンがゲームの開始シーンとして設定されました。\r\n")
            continue  # メニューを再表示

        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(scene_ids):
                selected_scene_id = scene_ids[choice_idx]
                _edit_single_scene_menu(api, selected_scene_id, game_id)
            else:
                api.send("無効な番号です。\r\n")
        except ValueError:
            api.send("数字で入力してください。\r\n")


def _edit_single_scene_menu(api, scene_id, game_id):
    """単一のシーンを編集するためのサブメニュー。"""
    while True:
        scene_data = _deserialize_data(api.get_data(
            f"scene:{game_id}:{scene_id}"), default_value={})
        if not scene_data:
            api.send("シーンが見つかりませんでした。\r\n")
            return

        api.send(b'\x1b[2J\x1b[H')
        # api.send(f"DEBUG: scene_id={scene_id}, game_id={game_id}\r\n")
        api.send(f"--- シーン「{scene_id}」の編集 ---\r\n")
        api.send(
            f"テキスト:\r\n---\r\n{scene_data.get('text', '')}\r\n---\r\n\r\n")
        api.send("[1] シーンのテキストを編集\r\n")
        api.send("[2] このシーンの選択肢を編集\r\n")
        api.send("[3] このシーンをゲームの開始シーンに設定\r\n")
        api.send("[D] このシーンを削除\r\n")
        api.send("[E] 戻る\r\n")
        api.send("選択してください: ")
        choice = api.get_input()

        if choice is None or choice.lower() == 'e':
            break
        elif choice == '1':
            _edit_scene_text(api, scene_id, game_id)
        elif choice == '2':
            _edit_scene_choices_menu(api, scene_id, game_id)
        elif choice == '3':
            game_data = _deserialize_data(
                api.get_data(f"game:{game_id}"), default_value={})
            if game_data:
                game_data['start_scene_id'] = scene_id
                api.save_data(f"game:{game_id}", game_data)
                api.send("このシーンを開始シーンとして設定しました。\r\n")
            else:
                api.send("ゲームデータの更新に失敗しました。\r\n")
        elif choice.lower() == 'd':
            if _delete_scene(api, scene_id, game_id):
                api.send("シーンを削除しました。前のメニューに戻ります。\r\n")
                api.get_input()
                return  # 削除後はこのメニューを抜ける
        else:
            api.send("無効な選択です。\r\n")


def _edit_scene_text(api, scene_id, game_id):
    """シーンのテキストを編集する。"""
    scene_data = _deserialize_data(api.get_data(
        f"scene:{game_id}:{scene_id}"), default_value={})
    if not scene_data:
        api.send("シーンデータが見つかりません。\r\n")
        return

    api.send("\r\n新しいシーンのテキストを入力してください ('.'だけの行で終了):\r\n")
    lines = []
    while True:
        line = api.get_input()
        if line == '.':
            break
        lines.append(line)
    new_text = "\n".join(lines)

    if not new_text.strip():
        api.send("テキストは空にできません。編集を中止しました。\r\n")
        return

    scene_data['text'] = new_text
    api.save_data(f"scene:{game_id}:{scene_id}", scene_data)
    api.send("シーンのテキストを更新しました。\r\n")


def _edit_scene_choices_menu(api, scene_id, game_id):
    """シーンの選択肢を編集するためのメニュー。"""
    while True:
        choices = _deserialize_data(api.get_data(
            f"choices:{game_id}:{scene_id}"), default_value=[])

        api.send(b'\x1b[2J\x1b[H')
        api.send(f"--- シーン「{scene_id}」の選択肢編集 ---\r\n\r\n")

        if not choices:
            api.send("このシーンには選択肢がありません。\r\n")
        else:
            for i, choice in enumerate(choices):
                api.send(
                    f"[{i + 1}] 「{choice['text']}」 -> (移動先: {choice['next_scene_id']})\r\n")

        api.send("\r\n[A] 新規選択肢作成  [D] 選択肢を削除  [E] 戻る\r\n")
        api.send("編集する選択肢の番号を入力してください: ")
        user_input = api.get_input()

        if user_input is None or user_input.lower() == 'e':
            break
        elif user_input.lower() == 'a':
            _create_choice(api, scene_id, game_id)
        elif user_input.lower() == 'd':
            if not choices:
                api.send("削除する選択肢がありません。\r\n")
                continue
            api.send("削除する選択肢の番号を入力してください: ")
            del_choice_str = api.get_input()
            try:
                del_idx = int(del_choice_str) - 1
                if 0 <= del_idx < len(choices):
                    choices.pop(del_idx)
                    api.save_data(f"choices:{game_id}:{scene_id}", choices)
                    api.send("選択肢を削除しました。\r\n")
                else:
                    api.send("無効な番号です。\r\n")
            except ValueError:
                api.send("数字で入力してください。\r\n")
        else:
            try:
                edit_idx = int(user_input) - 1
                if 0 <= edit_idx < len(choices):
                    _edit_single_choice(
                        api, choices, edit_idx, scene_id, game_id)
                else:
                    api.send("無効な番号です。\r\n")
            except ValueError:
                api.send("数字で入力してください。\r\n")


def _edit_single_choice(api, choices, index, scene_id, game_id):
    """単一の選択肢を編集する。"""
    choice_to_edit = choices[index]

    api.send(f"\r\n新しい選択肢のテキストを入力してください (現在: {choice_to_edit['text']}): ")
    new_text = api.get_input()
    if new_text:
        choice_to_edit['text'] = new_text

    api.send(
        f"新しい移動先シーンIDを入力してください (現在: {choice_to_edit['next_scene_id']}): ")
    new_next_scene_id = api.get_input()
    if new_next_scene_id:
        choice_to_edit['next_scene_id'] = new_next_scene_id.strip()

    api.save_data(f"choices:{game_id}:{scene_id}", choices)
    api.send("選択肢を更新しました。\r\n")


def _delete_scene(api, scene_id, game_id):
    """シーンと関連データを削除する。"""
    api.send(f"\r\n本当にシーン「{scene_id}」を削除しますか？この操作は元に戻せません。(y/n): ")
    confirm = api.get_input()
    if not confirm or confirm.lower() != 'y':
        api.send("削除を中止しました。\r\n")
        return False

    # 1. シーンデータを削除
    api.delete_data(f"scene:{game_id}:{scene_id}")
    # 2. このシーンの選択肢データを削除
    api.delete_data(f"choices:{game_id}:{scene_id}")
    # 3. ゲームデータからこのシーンIDを削除
    game_data = _deserialize_data(
        api.get_data(f"game:{game_id}"), default_value={})
    if game_data and 'scene_ids' in game_data:
        if scene_id in game_data['scene_ids']:
            game_data['scene_ids'].remove(scene_id)
        # 開始シーンだったらNoneにする
        if game_data.get('start_scene_id') == scene_id:
            game_data['start_scene_id'] = None
        api.save_data(f"game:{game_id}", game_data)

    # TODO: 他のシーンからこの削除されたシーンへの選択肢が残ってしまう。
    # これをクリーンアップするのは大変なので、現状は仕様とする。
    return True


def _handle_edit_menu(api, context):
    """ゲーム編集メニュー。オープン編集モードまたは作成者のみが編集可能です。"""
    while True:
        api.send(b'\x1b[2J\x1b[H')
        api.send("--- テキストアドベンチャー: ゲームを編集 ---\r\n\r\n")

        game_index = _deserialize_data(
            api.get_data("game_index"), default_value=[])

        if not game_index:
            api.send("編集できるゲームがありません。\r\n")
            api.send("何かキーを押すと戻ります...")
            api.get_input()
            return

        games_details = []
        for index_item in game_index:
            game_detail = _deserialize_data(api.get_data(
                f"game:{index_item['id']}"), default_value={})
            if game_detail:
                games_details.append(game_detail)

        for i, game in enumerate(games_details):
            api.send(f"[{i + 1}] {game['title']}\r\n")
            author_name = game.get(
                'author_login_id', game.get('author_id', '不明'))
            open_marker = " (OPEN)" if game.get('open_edit', False) else ""
            api.send(f"    作成者: {author_name}{open_marker}\r\n\r\n")

        api.send("編集するゲームの番号を入力してください ([E]戻る): ")
        choice_str = api.get_input()

        if choice_str is None or choice_str.lower() == 'e':
            break

        try:
            choice_idx = int(choice_str) - 1
            if not (0 <= choice_idx < len(games_details)):
                api.send("無効な番号です。\r\n")
                continue

            game_to_edit = games_details[choice_idx]

            # --- 編集権限チェック ---
            is_author = game_to_edit.get('author_id') == context['user_id']
            is_open_edit = game_to_edit.get('open_edit', False)

            if not is_author and not is_open_edit:
                api.send("\r\nあなたはこのゲームの編集権限がありません。\r\n")
                api.send("何かキーを押すと戻ります...")
                api.get_input()
                continue

            # --- 編集サブメニュー ---
            while True:
                api.send(b'\x1b[2J\x1b[H')
                api.send(f"--- 「{game_to_edit['title']}」の編集 ---\r\n")
                api.send("[1] ゲームの基本情報を編集\r\n")
                api.send("[2] シーンと選択肢を編集\r\n")
                api.send("[E] 編集を終了\r\n")
                api.send("選択してください: ")
                edit_choice = api.get_input()

                if edit_choice is None or edit_choice.lower() == 'e':
                    break
                elif edit_choice == '1':
                    _edit_game_details(api, game_to_edit)
                    # 更新された可能性があるので再読み込み
                    game_to_edit = _deserialize_data(api.get_data(
                        f"game:{game_to_edit['id']}"), default_value={})
                elif edit_choice == '2':
                    _edit_scenes_menu(api, game_to_edit)
                else:
                    api.send("無効な選択です。\r\n")
            # 編集サブメニューを抜けたら、ゲーム選択メニューに戻る

        except (ValueError, IndexError):
            api.send("無効な入力です。\r\n")


def _edit_game_details(api, game_data):
    """ゲームのタイトルと説明を編集します。"""
    original_game_id = game_data['id']  # IDを保持

    api.send(f"\r\n新しいタイトルを入力してください (現在: {game_data['title']}): ")
    new_title = api.get_input() or game_data['title']

    api.send(f"新しい説明を入力してください (現在: {game_data.get('description', '')}): ")
    new_description = api.get_input() or game_data.get('description', '')

    game_data['title'] = new_title
    game_data['description'] = new_description
    api.save_data(f"game:{original_game_id}", game_data)

    # game_indexも更新
    game_index = _deserialize_data(
        api.get_data("game_index"), default_value=[])
    for item in game_index:
        if item['id'] == original_game_id:
            item['title'] = new_title
    api.save_data("game_index", game_index)
    api.send("ゲーム情報を更新しました。\r\n")


def _handle_delete_game(api, context, games_details):
    """ゲーム削除の対話処理。"""
    api.send("\r\n削除するゲームの番号を入力してください: ")
    choice_str = api.get_input()
    if not choice_str:
        return

    try:
        choice_index = int(choice_str) - 1
        if not (0 <= choice_index < len(games_details)):
            api.send("無効な番号です。\r\n")
            return

        game_to_delete = games_details[choice_index]

        # --- 所有者チェック ---
        if game_to_delete.get('author_id') != context['user_id']:
            api.send("\r\nあなたはこのゲームの作成者ではないため、削除できません。\r\n")
            api.send("何かキーを押すと戻ります...")
            api.get_input()
            return

        api.send(f"\r\n本当にゲーム「{game_to_delete['title']}」を削除しますか？ (y/n): ")
        confirm = api.get_input()
        if confirm and confirm.lower() == 'y':
            if _delete_game_data(api, game_to_delete['id']):
                api.send("ゲームを削除しました。\r\n")
            else:  # noqa
                api.send("ゲームの削除中にエラーが発生しました。\r\n")
        else:
            api.send("削除を中止しました。\r\n")

    except ValueError:
        api.send("数字で入力してください。\r\n")

    api.send("何かキーを押すと戻ります...")
    api.get_input()


def _delete_game_data(api, game_id):
    """指定されたゲームIDに関連する全てのデータを削除します。"""
    try:
        game_data = _deserialize_data(api.get_data(
            f"game:{game_id}"), default_value={})
        scene_ids = game_data.get('scene_ids', [])
        for scene_id in scene_ids:
            api.delete_data(f"choices:{game_id}:{scene_id}")
            api.delete_data(f"scene:{game_id}:{scene_id}")
        api.delete_data(f"game:{game_id}")
        game_index = _deserialize_data(
            api.get_data("game_index"), default_value=[])
        updated_index = [
            item for item in game_index if item.get('id') != game_id]
        api.save_data("game_index", updated_index)
        return True
    except Exception as e:
        api.send(f"削除エラー: {e}\r\n")
        return False


def run(context):
    """プラグインのエントリーポイント。"""
    api = context['api']

    while True:
        api.send(b'\x1b[2J\x1b[H')  # 画面クリア
        api.send("\r\n--- テキストアドベンチャー ---\r\n\r\n")
        api.send("[1] ゲームをプレイする\r\n")
        api.send("[2] 新しいゲームを作成する\r\n")
        api.send("[3] ゲームを編集する\r\n")
        api.send("[E] 終了\r\n\r\n")
        api.send("選択してください: ")

        choice = api.get_input()

        if choice is None or choice.lower() == 'e':
            break
        elif choice == '1':
            _handle_play_menu(api, context)  # プレイメニューにコンテキストを渡す
        elif choice == '2':
            _create_game(api, context)
        elif choice == '3':
            _handle_edit_menu(api, context)
        else:
            api.send("無効な選択です。\r\n")
