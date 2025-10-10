# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""テキストアドベンチャープラグイン。

このプラグインは、ユーザーがテキストベースのアドベンチャーゲームを作成し、
プレイできるようにするものです。ゲームデータはすべて、`GrbbsApi`を介してキーバリューストアに保存され、ホストアプリケーションの変更を必要としません。
"""

import uuid
import json


def _deserialize_data(raw_data, default_value=None):
    """`api.get_data()`から返されたデータを安全にデシリアライズするヘルパー関数。

    Args:
        raw_data: APIから取得したデータ。
        default_value: デシリアライズに失敗した場合に返すデフォルト値。

    Returns:
        list | dict: デシリアライズされたデータ。
    """
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
    """指定されたゲームIDのゲームプレイを開始します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        game_id (str): プレイするゲームのID。
    """
    game = _deserialize_data(api.get_data(f"game:{game_id}"), default_value={})
    if not game:
        api.send("\r\nゲームが見つかりませんでした。\r\n")
        return

    current_scene_id = game.get('start_scene_id')
    if not current_scene_id:
        api.send("\r\nこのゲームには開始シーンが設定されていません。\r\n")
        return

    # ゲームに設定された画像加工のデフォルト値を取得
    game_image_settings = game.get('image_settings', {})
    resize_setting = tuple(game_image_settings.get(
        'resize')) if game_image_settings.get('resize') else None
    enlarge_to_setting = tuple(game_image_settings.get(
        'enlarge_to')) if game_image_settings.get('enlarge_to') else None
    reduce_colors_setting = game_image_settings.get('reduce_colors')

    # 画像表示用の共通関数
    def show_scene_image(scene_data):
        image_filename = scene_data.get('image_filename')
        if image_filename:
            api.show_image_popup(
                image_path=image_filename, title=f"Scene: {scene_data.get('id')}",
                resize=resize_setting, enlarge_to=enlarge_to_setting, reduce_colors=reduce_colors_setting
            )

    while current_scene_id:
        scene = _deserialize_data(api.get_data(
            f"scene:{game_id}:{current_scene_id}"), default_value={})
        if not scene:
            api.send("\r\nシーンデータが見つかりません。ゲームを終了します。\r\n")
            break

        api.send(b'\x1b[2J\x1b[H')  # 画面クリア
        api.send("\r\n" + scene['text'].replace('\n', '\r\n') + "\r\n\r\n")

        # シーンに入った時に、設定されていれば画像を一度だけ表示
        show_scene_image(scene)

        choices = _deserialize_data(api.get_data(
            f"choices:{game_id}:{current_scene_id}"), default_value=[])

        if not choices:
            api.send("--- 終わり ---\r\n")
            api.send("何かキーを押すとメニューに戻ります...")
            api.get_input()
            break

        for i, choice in enumerate(choices):
            api.send(f"[{i + 1}] {choice['text']}\r\n")

        # 画像が設定されている場合、選択肢の最後に「画像を表示」を追加
        if scene.get('image_filename'):
            api.send("[P] 画像を表示\r\n")

        api.send("\r\nどうしますか？: ")
        user_input = api.get_input()

        if user_input is None:  # 接続が切れた場合
            break

        # 'i'が入力されたら画像を再表示
        if user_input.lower() == 'p' and scene.get('image_filename'):
            show_scene_image(scene)
            continue

        try:
            choice_index = int(user_input) - 1
            if 0 <= choice_index < len(choices):
                current_scene_id = choices[choice_index]['next_scene_id']
            else:
                api.send("無効な選択です。もう一度選んでください。\r\n")
        except ValueError:
            api.send("数字で選択してください。\r\n")


def _handle_play_menu(api, context):
    """プレイするゲームを選択するためのメニューを表示・処理します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        context (dict): 実行コンテキスト。
    """
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
            # 自分が作成者でなく、かつ非公開のゲームは表示しない
            is_author = game.get('author_id') == context['user_id']
            is_public = game.get('is_public', False)
            if not is_author and not is_public:
                continue

            author_name = game.get(
                'author_login_id', game.get('author_id', '不明'))
            status_markers = []
            if not is_public:
                status_markers.append("非公開")
            if game.get('open_edit', False):
                status_markers.append("OPEN")
            status_str = f" ({', '.join(status_markers)})" if status_markers else ""

            api.send(f"[{i + 1}] {game['title']}{status_str}\r\n")
            api.send(
                f"    作成者: {author_name} | {game.get('description', '')}\r\n\r\n")

        api.send("プレイするゲームの番号を入力してください ([E]戻る): ")
        choice = api.get_input()

        if choice is None or choice.lower() == 'e':
            break

        try:
            game_choice_index = int(choice) - 1
            if 0 <= game_choice_index < len(games_details):
                _play_game(api, games_details[game_choice_index]['id'])
            else:
                api.send("無効な番号です。\r\n")
        except ValueError:
            api.send("数字で入力してください。\r\n")


def _create_game(api, context):
    """新しいゲームを作成するための対話フローを処理します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        context (dict): 実行コンテキスト。
    """
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

    # --- 公開設定 ---
    api.send("このゲームを他のユーザーに公開しますか？ (y/n): ")
    public_choice = api.get_input()
    is_public = public_choice and public_choice.lower() == 'y'

    # --- ゲーム全体で共通の画像設定 ---
    api.send("\r\n--- 画像のデフォルト設定 ---\r\n")
    api.send("縮小解像度 (例: 320,200 / 不要なら空): ")
    resize_input = api.get_input() or ""
    resize_parts = [p.strip() for p in resize_input.split(',')]
    resize_setting = [int(p) for p in resize_parts] if len(
        resize_parts) == 2 and all(p.isdigit() for p in resize_parts) else None

    api.send("拡大解像度 (例: 640,400 / 不要なら空): ")
    enlarge_input = api.get_input() or ""
    enlarge_parts = [p.strip() for p in enlarge_input.split(',')]
    enlarge_setting = [int(p) for p in enlarge_parts] if len(
        enlarge_parts) == 2 and all(p.isdigit() for p in enlarge_parts) else None

    api.send("減色数 (例: 16 / 不要なら空): ")
    colors_input = api.get_input()
    colors_setting = int(
        colors_input) if colors_input and colors_input.isdigit() else None

    game_id = str(uuid.uuid4())
    new_game_data = {
        "id": game_id,
        "title": title,
        "description": description,
        "author_id": context['user_id'],
        "author_login_id": context['login_id'],
        "open_edit": is_open_edit,
        "is_public": is_public,
        "image_settings": {
            "resize": resize_setting,
            "enlarge_to": enlarge_setting,
            "reduce_colors": colors_setting,
        },
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
    """新しいシーンを作成するための対話フローを処理します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        game_id (str): このシーンが属するゲームのID。

    Returns:
        str | None: 作成されたシーンのID。失敗した場合はNone。
    """
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

    # このシーンに紐づける画像があればアップロード
    image_filename = _handle_scene_image_upload(api, game_id, scene_id)

    new_scene_data = {
        "id": scene_id,
        "game_id": game_id,
        "text": scene_text,
        "image_filename": image_filename,
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
    """指定されたシーンに新しい選択肢を作成するための対話フローを処理します。

    存在しないシーンIDが指定された場合、その場で新しい空のシーンを作成することもできます。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        from_scene_id (str): 選択肢の分岐元となるシーンのID。
        game_id (str): この選択肢が属するゲームのID。
    """
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


def _handle_scene_image_upload(api, game_id, scene_id):
    """シーンに紐づく画像をアップロードし、ファイル名を返すヘルパー関数。

    アップロードされたファイルは、`upload_file` APIの `preferred_filename` を利用して
    「ゲーム名_シーン名.拡張子」という形式で保存されます。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        game_id (str): ゲームのID。
        scene_id (str): シーンのID。

    Returns:
        str | None: 保存された一意なファイル名。失敗した場合はNone。
    """
    api.send("\r\nこのシーンに画像を設定しますか？ (y/n): ")
    if api.get_input().lower() != 'y':
        return None

    # ゲーム名とシーン名をファイル名に含める（無害化）
    game_data = _deserialize_data(
        api.get_data(f"game:{game_id}"), default_value={})
    game_title_safe = "".join(
        c for c in game_data.get('title', 'game') if c.isalnum())
    scene_id_safe = "".join(c for c in scene_id if c.isalnum())
    preferred_filename = f"{game_title_safe}_{scene_id_safe}"

    uploaded_file = api.upload_file(
        prompt="画像ファイルを選択してください:",
        allowed_extensions=['png', 'jpg', 'jpeg', 'gif', 'bmp'],
        max_size_mb=5,
        preferred_filename=preferred_filename
    )

    if not uploaded_file:
        api.send("画像のアップロードがキャンセルされました。\r\n")
        return None

    api.send(
        f"'{uploaded_file['original_filename']}' をアップロードしました。プレビューを表示します。\r\n")
    api.send(f"(デバッグ情報: ファイルパス -> {uploaded_file['filepath']})\r\n")
    api.show_image_popup(uploaded_file['filepath'], title="プレビュー")
    return uploaded_file['unique_filename']


def _edit_scenes_menu(api, game_data):
    """ゲームに属する全てのシーンを一覧表示し、編集対象を選択するメニュー。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        game_data (dict): 編集対象のゲームデータ。
    """
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
    """単一のシーン（テキスト、選択肢、画像など）を編集するためのサブメニュー。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        scene_id (str): 編集対象のシーンID。
        game_id (str): 編集対象のゲームID。
    """
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
        api.send("[3] 画像を変更/追加する\r\n")
        api.send("[4] このシーンをゲームの開始シーンに設定\r\n")
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
            # 既存の画像を削除
            if scene_data.get('image_filename'):  # noqa
                if api.delete_static_file(scene_data['image_filename']):
                    api.send("既存の画像を削除しました。\r\n")

            # 新しい画像をアップロード
            new_image_filename = _handle_scene_image_upload(
                api, game_id, scene_id)
            scene_data['image_filename'] = new_image_filename
            api.save_data(f"scene:{game_id}:{scene_id}", scene_data)
        elif choice == '4':
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
    """シーンの本文テキストを編集します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        scene_id (str): 編集対象のシーンID。
        game_id (str): 編集対象のゲームID。
    """
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
    """シーンに紐づく選択肢を編集するためのメニュー。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        scene_id (str): 編集対象のシーンID。
        game_id (str): 編集対象のゲームID。
    """
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
    """単一の選択肢（テキストと移動先）を編集します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        choices (list): 編集対象を含む選択肢のリスト。
        index (int): `choices`リスト内の編集対象のインデックス。
        scene_id (str): この選択肢が属するシーンのID。
        game_id (str): この選択肢が属するゲームのID。
    """
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
    """シーンとそれに関連するデータ（選択肢など）を削除します。

    注意: このシーンに遷移してくる他のシーンの選択肢は削除されません。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        scene_id (str): 削除対象のシーンID。
        game_id (str): 削除対象のゲームID。
    """
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
    """ゲーム編集のトップメニュー。編集対象のゲームを選択します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        context (dict): 実行コンテキスト。
    """
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

        api.send("編集するゲームの番号を入力してください ([D]削除 [E]戻る): ")
        choice_str = api.get_input()

        if choice_str is None or choice_str.lower() == 'e':
            break
        elif choice_str.lower() == 'd':
            # 削除対象のゲームを選択させる
            # games_detailsには自分のゲームしか含まれていないので権限チェックは不要
            _handle_delete_game(api, context, games_details)
            # 削除後はメニューを再表示するためにループを継続
            continue

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
                api.send("[1] ゲームのタイトルと説明を編集\r\n")
                api.send("[2] ゲームの画像設定を編集\r\n")
                api.send("[3] シーンと選択肢を編集\r\n")
                api.send("[E] 編集を終了\r\n")
                api.send("選択してください: ")
                edit_choice = api.get_input()

                if edit_choice is None or edit_choice.lower() == 'e':
                    break
                elif edit_choice == '1':
                    _edit_game_details(api, game_to_edit)
                elif edit_choice == '2':
                    _edit_game_image_settings(api, game_to_edit)
                    # 更新された可能性があるので再読み込み
                    game_to_edit = _deserialize_data(api.get_data(
                        f"game:{game_to_edit['id']}"), default_value={})
                elif edit_choice == '3':
                    _edit_scenes_menu(api, game_to_edit)
                else:
                    api.send("無効な選択です。\r\n")
        except ValueError:
            api.send("数字で入力してください。\r\n")


def _edit_game_image_settings(api, game_data):
    """ゲーム全体で共通のデフォルト画像設定を編集します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        game_data (dict): 編集対象のゲームデータ。
    """
    game_id = game_data['id']
    current_settings = game_data.get('image_settings', {})

    api.send("\r\n--- 画像のデフォルト設定編集 ---\r\n")
    api.send(f"現在の縮小解像度: {current_settings.get('resize')}\r\n")
    api.send("新しい縮小解像度 (例: 320,200 / 変更しないなら空): ")
    resize_input = api.get_input()
    if resize_input and ',' in resize_input:
        resize_parts = [p.strip() for p in resize_input.split(',')]
        if len(resize_parts) == 2 and all(p.isdigit() for p in resize_parts):
            current_settings['resize'] = [int(p) for p in resize_parts]

    api.send(f"現在の拡大解像度: {current_settings.get('enlarge_to')}\r\n")
    api.send("新しい拡大解像度 (例: 640,400 / 変更しないなら空): ")
    enlarge_input = api.get_input()
    if enlarge_input and ',' in enlarge_input:
        enlarge_parts = [p.strip() for p in enlarge_input.split(',')]
        if len(enlarge_parts) == 2 and all(p.isdigit() for p in enlarge_parts):
            current_settings['enlarge_to'] = [int(p) for p in enlarge_parts]

    api.send(f"現在の減色数: {current_settings.get('reduce_colors')}\r\n")
    api.send("新しい減色数 (例: 16 / 変更しないなら空): ")
    colors_input = api.get_input()
    if colors_input and colors_input.isdigit():
        current_settings['reduce_colors'] = int(colors_input)

    game_data['image_settings'] = current_settings
    api.save_data(f"game:{game_id}", game_data)
    api.send("画像設定を更新しました。\r\n")


def _edit_game_details(api, game_data):
    """ゲームの基本情報（タイトル、説明、公開設定など）を編集します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        game_data (dict): 編集対象のゲームデータ。
    """
    original_game_id = game_data['id']  # IDを保持

    api.send(f"\r\n新しいタイトルを入力してください (現在: {game_data['title']}): ")
    new_title = api.get_input() or game_data['title']

    api.send(f"新しい説明を入力してください (現在: {game_data.get('description', '')}): ")
    new_description = api.get_input() or game_data.get('description', '')

    game_data['title'] = new_title
    game_data['description'] = new_description
    api.save_data(f"game:{original_game_id}", game_data)

    # 公開設定の編集
    current_public_status = "公開" if game_data.get(
        'is_public', False) else "非公開"
    api.send(f"ゲームを公開しますか？ (現在: {current_public_status}) (y/n/空欄=変更しない): ")
    public_choice = api.get_input()
    if public_choice.lower() == 'y':
        game_data['is_public'] = True
    elif public_choice.lower() == 'n':
        game_data['is_public'] = False

    # 誰でも編集可能かどうかの設定
    current_open_status = "はい" if game_data.get('open_edit', False) else "いいえ"
    api.send(f"誰でも編集可能にしますか？ (現在: {current_open_status}) (y/n/空欄=変更しない): ")
    open_edit_choice = api.get_input()
    if open_edit_choice.lower() == 'y':
        game_data['open_edit'] = True
    elif open_edit_choice.lower() == 'n':
        game_data['open_edit'] = False

    # game_indexも更新
    game_index = _deserialize_data(
        api.get_data("game_index"), default_value=[])
    for item in game_index:
        if item['id'] == original_game_id:
            item['title'] = new_title
    api.save_data("game_index", game_index)
    api.send("ゲーム情報を更新しました。\r\n")


def _handle_delete_game(api, context, games_details):
    """ゲーム削除の対話処理。

    ユーザーに削除対象のゲーム番号を尋ね、確認の上で削除を実行します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        context (dict): 実行コンテキスト。
        games_details (list): 削除候補となるゲームのリスト。
    """
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
    """指定されたゲームIDに関連する全てのデータ（ゲーム本体、シーン、選択肢、画像ファイル）を削除します。

    Args:
        api (GrbbsApi): プラグインAPIのインスタンス。
        game_id (str): 削除対象のゲームID。
    Returns:
        bool: 削除に成功した場合はTrue。
    """
    try:
        game_data = _deserialize_data(api.get_data(
            f"game:{game_id}"), default_value={})
        scene_ids = game_data.get('scene_ids', [])
        for scene_id in scene_ids:
            # シーンに紐づく画像ファイルも削除
            scene_data = _deserialize_data(api.get_data(
                f"scene:{game_id}:{scene_id}"), default_value={})
            if scene_data.get('image_filename'):
                api.delete_static_file(scene_data['image_filename'])
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
    """プラグインのエントリーポイント。

    Args:
        context (dict): 実行コンテキスト。
    """
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
