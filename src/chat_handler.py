# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
チャットハンドラ
 
このモジュールは、リアルタイムチャットルームのサーバーサイドロジックを管理します。
ユーザーの入退室、メッセージのブロードキャスト、履歴管理、チャットルーム内の 
特別なコマンド（ロック、状況確認など）を処理します。
グローバルな辞書を使用して、アクティブなルームとユーザーの状態を保持します。
"""

import logging
import collections
import threading
import time
import os
import json
from . import terminal_handler
from . import util, bbsmenu

# --- Global State Management / グローバル状態管理 ---

# {room_id: collections.deque()}
# 各チャットルームのメッセージ履歴を保持します。
chat_room_histories = {}
MAX_HISTORY_MESSAGES = 100

# {room_id: {"users": {login_id: {"chan": chan, "menu_mode": "2", "user_id": 1}}, "locked_by": "owner_login_id" or None}}
# 現在アクティブなチャットルームと、それに参加しているユーザーの情報を保持します。
active_chat_rooms = {}

# {room_id: 1678886400.0}
# Push通知のクールダウンタイムスタンプを管理します。ルームが空になっても維持されます。
chat_room_notification_timestamps = {}

# グローバルな状態変数を保護するためのロックオブジェクト。
chat_rooms_lock = threading.Lock()

# --- ログ関連の設定 ---
CHAT_LOG_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'logs', 'chat'))


# server.py から get_online_members_list をセットするためのグローバル変数
ONLINE_MEMBERS_FUNC = None


def get_room_history(room_id: str) -> collections.deque:
    """
    指定されたルームIDのメッセージ履歴を取得または新規作成します。
    スレッドセーフな操作のためにロックを使用します。 
    """
    with chat_rooms_lock:
        if room_id not in chat_room_histories:
            chat_room_histories[room_id] = collections.deque(
                maxlen=MAX_HISTORY_MESSAGES)
        return chat_room_histories[room_id]


def add_message_to_history(room_id: str, display_name: str, message: str, is_system_message=False):
    """指定されたルームの履歴にメッセージを追加します。"""
    history = get_room_history(room_id)
    if is_system_message:
        formatted_message = f"System: {message}"
    else:
        formatted_message = f"{display_name}: {message}"
    history.append(formatted_message)

    # --- ログファイルへの書き込み処理 ---
    try:
        paths_config = util.app_config.get('paths', {})
        chatroom_config_path = paths_config.get('chatroom_yaml')
        chatroom_config = util.load_yaml_file_for_shortcut(
            chatroom_config_path)

        if chatroom_config:
            target_item, _ = util.find_item_in_yaml(
                chatroom_config, room_id, '2', "room")

            if target_item and target_item.get('log') is True:
                log_file_path = os.path.join(CHAT_LOG_DIR, f"{room_id}.txt")
                timestamp = time.strftime(
                    '%Y-%m-%d %H:%M:%S', time.localtime())
                log_entry = f"[{timestamp}] {formatted_message}\n"
                with open(log_file_path, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
    except Exception as e:
        logging.error(f"チャットログの書き込み中にエラー (Room: {room_id}): {e}")


def broadcast_to_room(room_id: str, display_name: str,
                      message_body: str, is_system_message: bool,
                      exclude_login_id: str = None,
                      message_key_for_system: str = None,
                      format_args_for_system: dict = None):
    """ルーム内のすべてのユーザーにメッセージをブロードキャストします。 
    各ユーザーの `menu_mode` に応じたフォーマットで送信します。
    """
    with chat_rooms_lock:
        if room_id in active_chat_rooms:
            for target_login_id, user_data in active_chat_rooms[room_id]["users"].items():
                if target_login_id == exclude_login_id:
                    continue

                target_chan = user_data["chan"]
                target_menu_mode = user_data["menu_mode"]

                if is_system_message:
                    specific_message_content = ""
                    if message_key_for_system:  # キーが指定されていれば優先
                        text_to_format = util.get_text_by_key(
                            message_key_for_system, target_menu_mode)
                        if text_to_format:
                            try:
                                current_format_args = format_args_for_system if format_args_for_system is not None else {}
                                specific_message_content = text_to_format.format(
                                    **current_format_args)
                            except KeyError as e:
                                logging.error(
                                    f"Formatting error for key '{message_key_for_system}' (mode: {target_menu_mode}): {e}")
                                specific_message_content = f"(Error formatting message for key {message_key_for_system})"
                        else:
                            logging.warning(
                                f"Text key '{message_key_for_system}' for mode '{target_menu_mode}' not found.")
                            specific_message_content = f"(Message for key {message_key_for_system} not found)"
                    elif message_body:  # キーがなく、従来の message_body があればそれを使う
                        specific_message_content = message_body
                    else:  # キーも従来の body もない
                        logging.error(
                            "System message broadcast without key or body.")
                        specific_message_content = "(System message content error)"

                    # システムメッセージの共通ラッパーを取得して適用
                    wrapper_format_string = util.get_text_by_key(
                        "chat.broadcast_chatsystem_message_format", target_menu_mode
                    )
                    if wrapper_format_string:
                        try:
                            formatted_message = wrapper_format_string.format(
                                message=specific_message_content)
                        except KeyError as e:  # ラッパーのフォーマットエラー
                            logging.error(
                                f"Formatting error for wrapper 'chat.broadcast_chatsystem_message_format' (mode: {target_menu_mode}): {e}")
                            # フォールバック
                            formatted_message = f"System: {specific_message_content}"
                    else:  # ラッパーがない場合は、内容をそのまま使用（先頭に "System: " などは付かない）
                        logging.warning(
                            f"Wrapper 'chat.broadcast_chatsystem_message_format' for mode '{target_menu_mode}' not found. Using content directly.")
                        formatted_message = specific_message_content

                else:
                    # ユーザーメッセージのフォーマットキーを textdata.yaml から取得
                    base_format_string = util.get_text_by_key(
                        "chat.broadcast_user_message_format", target_menu_mode
                    )
                    if base_format_string:
                        try:
                            formatted_message = base_format_string.format(
                                sender=display_name, message=message_body)
                        except KeyError as e:
                            logging.error(
                                f"Formatting error for key 'chat.broadcast_user_message_format' (mode: {target_menu_mode}): {e}. Raw: '{base_format_string}'")
                            formatted_message = f"{display_name}: {message_body}"
                    else:
                        logging.warning(
                            f"Text key 'chat.broadcast_user_message_format' for mode '{target_menu_mode}' not found. Using default.")
                        formatted_message = f"{display_name}: {message_body}"
                message_payload = formatted_message.replace(
                    '\n', '\r\n') + '\r\n'
                try:
                    # 現在の行をクリアし、メッセージを表示後、プロンプトを再表示する
                    # これにより、メッセージが上書きされるのを防ぐ
                    target_chan.send(b"\r\033[2K" +  # 行頭に移動して行全体をクリア
                                     message_payload.encode('utf-8') +
                                     b"> ")
                    # 他のユーザーからのメッセージ受信後にも電報チェック
                    # util.telegram_recieve は未読がなければ何も表示しない
                    util.telegram_recieve(
                        target_chan, target_login_id, target_menu_mode)
                except Exception as e:
                    logging.error(
                        f"ルーム{room_id}のユーザー{target_login_id}へのメッセージブロードキャスト中にエラー：{e}")


def set_online_members_function_for_chat(func):
    """外部モジュールからオンラインメンバーリスト取得用の関数をセットします。"""
    global ONLINE_MEMBERS_FUNC
    ONLINE_MEMBERS_FUNC = func


def user_joins_room(room_id: str, login_id: str, display_name: str, chan, room_name: str, menu_mode: str, user_id: int):
    """ユーザーがルームに入室した際の処理を行います。 
    アクティブユーザーリストに追加し、入室通知をブロードキャストし、必要に応じてPush通知を送信します。
    """
    with chat_rooms_lock:

        # --- Push通知送信処理 (ユーザー参加前) ---
        try:
            paths_config = util.app_config.get('paths', {})
            chatroom_config_path = paths_config.get('chatroom_yaml')
            chatroom_config = util.load_yaml_file_for_shortcut(
                chatroom_config_path)

            if chatroom_config:
                target_item, _ = util.find_item_in_yaml(
                    chatroom_config, room_id, menu_mode, "room")

                if target_item and target_item.get('push') is True:
                    push_config = util.app_config.get('push', {})
                    cooldown_seconds = push_config.get(
                        'NOTIFICATION_COOLDOWN_SECONDS', 60)
                    current_time = time.time()

                    last_notification_time = chat_room_notification_timestamps.get(
                        room_id, 0)

                    if (current_time - last_notification_time) > cooldown_seconds:
                        from . import database
                        # 入室した本人を除外して購読リストを取得
                        subscriptions = database.get_all_subscriptions(
                            exclude_user_id=user_id)

                        if subscriptions:
                            notification_payload = json.dumps({
                                "title": "GR-BBS Chat",
                                "body": f"{display_name}さんが「{room_name}」に入室しました。",
                                "data": {"url": f"/?shortcut=c:{room_id}"}
                            })
                            logging.info(
                                f"Sending {len(subscriptions)} push notifications for user joining room {room_id}.")
                            for sub in subscriptions:
                                util.send_push_notification(
                                    sub['subscription_info'], notification_payload)

                            # タイムスタンプを更新
                            chat_room_notification_timestamps[room_id] = current_time
                    else:
                        logging.info(
                            f"Push notification for room {room_id} skipped due to cooldown.")
        except Exception as e:
            logging.error(f"Push通知の送信中にエラーが発生しました: {e}", exc_info=True)

        # --- ユーザーをルームに追加 ---
        if room_id not in active_chat_rooms:
            active_chat_rooms[room_id] = {"users": {}, "locked_by": None}
        active_chat_rooms[room_id]["users"][login_id] = {
            "chan": chan, "menu_mode": menu_mode, "user_id": user_id}

    join_notification = f"{display_name} が入室しました。"
    logging.info(
        f"ChatEvent[{room_id}]: User {login_id}({display_name}) joined.")

    # 履歴とログファイルに記録
    add_message_to_history(room_id, "System", join_notification, True)

    # システムメッセージとしてブロードキャスト (画面表示用)
    broadcast_to_room(room_id, "System", join_notification,
                      is_system_message=True, exclude_login_id=login_id)


def user_leaves_room(room_id: str, login_id: str, display_name: str, room_name: str):
    """ユーザーがルームから退室した際の処理を行います。 
    アクティブユーザーリストから削除し、退室通知をブロードキャストします。
    オーナーが退室した場合はルームをアンロックします。
    """
    chan_left = None
    with chat_rooms_lock:
        if room_id in active_chat_rooms and login_id in active_chat_rooms[room_id]["users"]:
            user_data_left = active_chat_rooms[room_id]["users"].pop(
                login_id, None)
            chan_left = user_data_left["chan"] if user_data_left else None
            if not active_chat_rooms[room_id]["users"]:
                del active_chat_rooms[room_id]
                if room_id in chat_room_histories:
                    del chat_room_histories[room_id]
                logging.info(f"チャットルーム {room_id} が空になったため削除しました。")
            elif active_chat_rooms[room_id]["locked_by"] == login_id:
                # オーナーが抜けたらロック解除
                # 履歴には残さず、サーバーログには手動で記録することも可能
                logging.info(
                    f"ChatEvent[{room_id}]: Room '{room_name}' unlocked due to owner {login_id} leaving.")
                # ロッククリア
                active_chat_rooms[room_id]["locked_by"] = None
                broadcast_to_room(
                    room_id, "System",
                    message_body="",  # ダミー
                    is_system_message=True,
                    message_key_for_system="chat.owner_left_unlock_broadcast",
                    format_args_for_system={"room_name": room_name, "owner": login_id})

    leave_notification = f"{display_name} が退室しました。"
    add_message_to_history(room_id, "System", leave_notification, True)

    if chan_left:
        leave_notification = f"{display_name} が退室しました。"
        # 履歴には残さず、サーバーログには手動で記録することも可能
        logging.info(
            f"ChatEvent[{room_id}]: User {login_id}({display_name}) left.")
        broadcast_to_room(room_id, "System",
                          leave_notification, is_system_message=True)


def handle_chat_room(chan, login_id: str, display_name: str, menu_mode: str, user_id: int, room_id: str, room_name: str):
    """チャットルームのメインループ。ユーザーからの入力を受け付け、コマンド処理やメッセージ送信を行います。"""
    # モバイル用の操作ボタンを表示
    chan.send(b'\x1b[?2026h')

    util.send_text_by_key(chan, "chat.welcome", menu_mode, room_name=room_name)
    util.send_text_by_key(chan, "chat.help", menu_mode)

    # ルームロック確認
    with chat_rooms_lock:
        room_data = active_chat_rooms.get(room_id)
        if room_data and room_data.get("locked_by") and room_data.get("locked_by") != login_id:
            util.send_text_by_key(chan, "chat.room_locked", menu_mode,
                                  room_name=room_name, owner=room_data.get("locked_by"))
            return "back_one_level"  # 入室せずに終了
    user_joins_room(room_id, login_id, display_name, chan,
                    room_name, menu_mode, user_id)

    # --- このルームがロック可能かどうかの設定を取得 ---
    paths_config = util.app_config.get('paths', {})
    chatroom_config_path = paths_config.get('chatroom_yaml')
    chatroom_config = util.load_yaml_file_for_shortcut(chatroom_config_path)
    current_room_config, _ = util.find_item_in_yaml(
        chatroom_config, room_id, menu_mode, "room") if chatroom_config else (None, None)
    is_lockable = current_room_config.get(
        'lock', False) if current_room_config else False

    try:
        while True:
            user_input = chan.process_input()

            if user_input is None:
                logging.info(f"ユーザー{login_id}はチャットルーム{room_id}で切断されました。")
                break

            user_input = user_input.strip()

            if not user_input:
                continue

            if user_input.lower() == "!?":
                # ヘルプ
                util.send_text_by_key(chan, "chat.help", menu_mode)
            elif user_input.lower() == "!":
                # 電報をチャット内から送信
                if ONLINE_MEMBERS_FUNC:
                    online_members_dict = ONLINE_MEMBERS_FUNC()
                    # SIDのリストではなく、ユーザー名のリストを渡すように修正
                    online_user_logins = [
                        member_data.get('username') for member_data in online_members_dict.values() if member_data.get('username')
                    ]
                    is_mobile = (isinstance(chan, terminal_handler.WebTerminalHandler.WebChannel) and
                                 getattr(chan.handler, 'is_mobile', False)
                                 )
                    util.telegram_send(
                        chan, display_name, online_user_logins, menu_mode, chan.handler.app, is_mobile=is_mobile)
                else:
                    util.send_text_by_key(
                        chan, "common_messages.error", menu_mode)

            elif user_input.lower() == "!w":
                # WHOをチャット内から参照
                if ONLINE_MEMBERS_FUNC:
                    online_members_dict = ONLINE_MEMBERS_FUNC()
                    bbsmenu.who_menu(chan, online_members_dict, menu_mode)
                else:
                    util.send_text_by_key(
                        chan, "common_messages.error", menu_mode)

            elif user_input.lower() == "!r":
                # チャットルーム状況表示
                if not active_chat_rooms:  # この状態でチャットルームなしはありえないけど一応
                    util.send_text_by_key(
                        chan, "chat.no_active_rooms", menu_mode)
                else:
                    util.send_text_by_key(
                        chan, "chat.room_status_header", menu_mode)
                    for r_id, data in active_chat_rooms.items():
                        users_in_room = ", ".join(
                            data["users"].keys()) if data["users"] else "no user"
                        lock_status = f"Locked by {data.get('locked_by')}" if data.get(
                            "locked_by") else "Unlocked"
                        # 後々chatroom.yamlからroom_idに対応するnameを取得して表示する予定。
                        display_room_name_for_status = r_id  # TODO: chatroom.yaml から正式名を取得
                        util.send_text_by_key(chan, "chat.room_status", menu_mode,
                                              room_name=display_room_name_for_status,
                                              lock_status=lock_status, users=users_in_room)
                    util.send_text_by_key(
                        chan, "chat.room_status_footer", menu_mode)

            # --- ルームロック機能 ---
            elif user_input.lower() == "!l":
                # 部屋をロック。
                if not is_lockable:
                    util.send_text_by_key(
                        chan, "chat.lock_not_allowed", menu_mode)
                    continue

                lock_successful = False

                if login_id.upper() == 'GUEST':
                    util.send_text_by_key(
                        chan, "common_messages.permission_denied", menu_mode)
                    continue

                with chat_rooms_lock:
                    if room_id in active_chat_rooms:
                        room_info = active_chat_rooms[room_id]
                        if room_info.get("locked_by"):
                            util.send_text_by_key(
                                chan, "chat.room_already_locked", menu_mode, owner=room_info.get("locked_by"), room_name=room_name)
                        else:
                            room_info["locked_by"] = login_id
                            # 履歴には残さず、サーバーログには手動で記録することも可能
                            logging.info(
                                f"ChatEvent[{room_id}]: Room '{room_name}' locked by {login_id}.")
                            lock_successful = True
                    else:
                        util.send_text_by_key(
                            chan, "chat.room_not_found_error", menu_mode, room_id=room_id)

                if lock_successful:
                    broadcast_to_room(
                        room_id, "System",
                        message_body="",  # ダミー
                        is_system_message=True,
                        message_key_for_system="chat.room_locked_broadcast",
                        format_args_for_system={"room_name": room_name, "owner": login_id})

            # --- ルームアンロック機能 ---
            elif user_input.lower() == "!u":
                # 部屋をアンロック。
                if not is_lockable:
                    util.send_text_by_key(
                        chan, "chat.lock_not_allowed", menu_mode)
                    continue

                unlock_successful = False

                if login_id.upper() == 'GUEST':
                    util.send_text_by_key(
                        chan, "common_messages.permission_denied", menu_mode)
                    continue

                with chat_rooms_lock:
                    if room_id in active_chat_rooms:
                        room_info = active_chat_rooms[room_id]
                        current_owner = room_info.get("locked_by")

                        if not current_owner:
                            util.send_text_by_key(
                                chan, "chat.room_not_locked", menu_mode, room_name=room_name)
                        elif current_owner == login_id:
                            room_info["locked_by"] = None
                            # 履歴には残さず、サーバーログには手動で記録することも可能
                            logging.info(
                                f"ChatEvent[{room_id}]: Room '{room_name}' unlocked by {login_id}.")
                            unlock_successful = True
                        elif current_owner != login_id:
                            util.send_text_by_key(
                                chan, "chat.room_unlock_not_owner", menu_mode, owner=current_owner, room_name=room_name)
                    else:
                        util.send_text_by_key(
                            chan, "chat.room_not_found_error", menu_mode, room_id=room_id)

                if unlock_successful:
                    broadcast_to_room(
                        room_id, "System",
                        message_body="",  # ダミー
                        is_system_message=True,
                        message_key_for_system="chat.room_unlocked_broadcast",
                        format_args_for_system={"room_name": room_name, "owner": login_id})

            # --- 退出コマンド ---
            elif user_input.lower() in ("^"):
                # ユーザーがチャットルームから退出する
                util.send_text_by_key(
                    chan, "chat.leaving_room", menu_mode, room_name=room_name)
                return "back_one_level"  # ループを抜けて finally で user_leaves_room が呼ばれる

            # --- 通常メッセージ送信 ---
            else:
                # 自分の画面に表示するメッセージ (menu_mode 対応)
                base_my_message_format = util.get_text_by_key(
                    "chat.my_message_format", menu_mode
                )
                if base_my_message_format:
                    try:
                        my_message_display = base_my_message_format.format(
                            sender=display_name, message=user_input)
                    except KeyError as e:
                        logging.error(
                            f"Formatting error for key 'chat.my_message_format' (mode: {menu_mode}): {e}. Raw: '{base_my_message_format}'")
                        # Fallback
                        my_message_display = f"{display_name}: {user_input}"
                else:
                    logging.warning(
                        f"Text key 'chat.my_message_format' for mode '{menu_mode}' not found. Using default.")
                    # Fallback
                    my_message_display = f"{display_name}: {user_input}"
                # 自分のメッセージ表示
                chan.send(b"\r\033[2K" +
                          f"{my_message_display}\r\n".encode('utf-8'))

                # 履歴に追加 (現状のフォーマットを維持)
                add_message_to_history(room_id, display_name, user_input)

                # 他のユーザーにブロードキャスト
                broadcast_to_room(room_id, display_name, user_input, is_system_message=False,
                                  exclude_login_id=login_id)

            # 各コマンド処理またはメッセージ送信後、新着電報をチェック
            # この呼び出しは、他のユーザーからのメッセージ受信時にも行われるようになったため、
            # ここでの呼び出しが重複になる可能性を考慮する。
            # ただし、telegram_recieve は未読がなければ何もしないので、実害は少ない。
            if not user_input.lower().startswith("!"):  # 通常メッセージ送信時のみここでチェック（コマンド時はbroadcast内でチェックされる）
                util.telegram_recieve(chan, login_id, menu_mode)

    except ConnectionResetError:
        logging.info(f"ユーザ {login_id} との接続がリセットされました(room_id): {room_id}")
    except BrokenPipeError:
        logging.info(f"ユーザ {login_id} とのパイプが壊れました(room_id): {room_id}")
    except Exception as e:
        logging.error(f"チャットルーム {room_id} でエラーが発生しました(user: {login_id})：{e}")
        try:
            if chan and chan.active:  # chanが有効か確認
                util.send_text_by_key(chan, "common_messages.error", menu_mode)
        except Exception as e_send:
            logging.error(
                f"User {login_id} finished chat in room{room_id}: {e_send}")

    finally:
        # モバイル用の操作ボタンを非表示
        chan.send(b'\x1b[?2026l')

        user_leaves_room(room_id, login_id, display_name, room_name)
        logging.info(f"User {login_id} finished chat in room {room_id}.")
        # finallyブロックでは明示的な戻り値を返さない（例外発生時などはNoneが返る）


def handle_chat_menu(chan, login_id, display_name, menu_mode, user_id, online_members_func):
    """チャットの階層メニューを表示し、選択されたルームへの入室を処理するエントリーポイントです。"""
    paths_config = util.app_config.get('paths', {})
    chatroom_config_path = paths_config.get('chatroom_yaml')
    if not chatroom_config_path:
        logging.error("chatroom.yaml のパスが設定されていません。")
        util.send_text_by_key(chan, "common_messages.error", menu_mode)
        return "back_to_top"

    # モバイル用の操作ボタンを表示
    chan.send(b'\x1b[?2028h')
    try:
        from . import hierarchical_menu
        selected_item = hierarchical_menu.handle_hierarchical_menu(
            chan, chatroom_config_path, menu_mode, menu_type="CHAT"
        )
    finally:
        # メニューを抜けたら必ずボタンを非表示にする
        chan.send(b'\x1b[?2028l')

    if selected_item and selected_item.get("type") == "room":
        room_id = selected_item.get("id")
        room_name = selected_item.get("name", room_id)
        set_online_members_function_for_chat(online_members_func)
        return handle_chat_room(chan, login_id, display_name, menu_mode, user_id, room_id, room_name)

    return "back_to_top"
