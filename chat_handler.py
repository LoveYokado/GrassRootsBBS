import logging
import collections
import threading

import ssh_input
import util
import bbsmenu

# チャットルームごとのメッセージ履歴
# {room_id:collections.deque()}
chat_room_histories = {}
MAX_HISTORY_MESSAGES = 100

active_chat_rooms = {}
# {room_id: {"users": {login_id: chan}, "locked_by": "owner_login_id" or None}}

chat_rooms_lock = threading.Lock()

ONLINE_MEMBERS_FUNC = None
# server.py から get_online_members_list をセットするためのグローバル変数


def get_room_history(room_id: str) -> collections.deque:
    """指定されたルームIDのメッセージ履歴を取得・作成"""
    with chat_rooms_lock:
        if room_id not in chat_room_histories:
            chat_room_histories[room_id] = collections.deque(
                maxlen=MAX_HISTORY_MESSAGES)
        return chat_room_histories[room_id]


def add_message_to_history(room_id: str, sender: str, message: str, is_system_message=False):
    """指定された部屋の履歴にメッセージを追加"""
    history = get_room_history(room_id)
    if is_system_message:
        formatted_message = f"System: {message}"
    else:
        formatted_message = f"{sender}: {message}"
    history.append(formatted_message)
    logging.info(f"ChatHistory[{room_id}]: {formatted_message}")


# room_name_for_prompt は実際には使われません
def broadcast_to_room(room_id: str, dbname: str, sender_name: str, message_body: str, is_system_message: bool, exclude_login_id: str = None):
    """
    ルーム内のすべてのユーザーにメッセージをブロードキャスト。
    各ユーザーの menu_mode に応じたフォーマットで送信する。
    """
    with chat_rooms_lock:
        if room_id in active_chat_rooms:
            for target_login_id, user_data in active_chat_rooms[room_id]["users"].items():
                if target_login_id == exclude_login_id:
                    continue

                target_chan = user_data["chan"]
                target_menu_mode = user_data["menu_mode"]

                if is_system_message:
                    # システムメッセージのフォーマットキーを textdata.yaml から取得
                    base_format_string = util.get_text_by_key(
                        "chat.broadcast_system_message_format", target_menu_mode
                    )
                    if base_format_string:
                        try:
                            formatted_message = base_format_string.format(
                                message=message_body)
                        except KeyError as e:
                            logging.error(
                                f"Formatting error for key 'chat.broadcast_system_message_format' (mode: {target_menu_mode}): {e}. Raw: '{base_format_string}'")
                            # Fallback
                            formatted_message = f"System: {message_body}"
                    else:
                        logging.warning(
                            f"Text key 'chat.broadcast_system_message_format' for mode '{target_menu_mode}' not found. Using default.")
                        # Fallback
                        formatted_message = f"System: {message_body}"
                else:
                    # ユーザーメッセージのフォーマットキーを textdata.yaml から取得
                    base_format_string = util.get_text_by_key(
                        "chat.broadcast_user_message_format", target_menu_mode
                    )
                    if base_format_string:
                        try:
                            formatted_message = base_format_string.format(
                                sender=sender_name, message=message_body)
                        except KeyError as e:
                            logging.error(
                                f"Formatting error for key 'chat.broadcast_user_message_format' (mode: {target_menu_mode}): {e}. Raw: '{base_format_string}'")
                            # Fallback
                            formatted_message = f"{sender_name}: {message_body}"
                    else:
                        logging.warning(
                            f"Text key 'chat.broadcast_user_message_format' for mode '{target_menu_mode}' not found. Using default.")
                        # Fallback
                        formatted_message = f"{sender_name}: {message_body}"
                message_payload = f"{formatted_message.replace('\n', '\r\n')}\r\n"
                try:
                    target_chan.send(
                        b"\033[s" +       # カーソル位置保存
                        b"\r\n" +         # 改行して新しい行へ
                        b"\r" +           # 念のためカーソルを行頭へ
                        message_payload.encode('utf-8') +  # メッセージ表示
                        b"\033[u"         # カーソル位置復元
                    )
                    # 他のユーザーからのメッセージ受信後にも電報チェック
                    # bbsmenu.telegram_recieve は未読がなければ何も表示しない
                    bbsmenu.telegram_recieve(
                        target_chan, dbname, target_login_id, target_menu_mode)
                except Exception as e:
                    logging.error(
                        f"ルーム{room_id}のユーザー{target_login_id}へのメッセージブロードキャスト中にエラー：{e}")


def set_online_members_function_for_chat(func):
    global ONLINE_MEMBERS_FUNC
    ONLINE_MEMBERS_FUNC = func


def user_joins_room(room_id: str, dbname: str, login_id: str, chan, room_name: str, menu_mode: str):
    """ユーザーがルームに入室したときに呼び出される"""
    with chat_rooms_lock:
        if room_id not in active_chat_rooms:
            active_chat_rooms[room_id] = {"users": {}, "locked_by": None}
        # チャンネルと一緒に menu_mode も保存
        active_chat_rooms[room_id]["users"][login_id] = {
            "chan": chan, "menu_mode": menu_mode}

    join_notification = f"{login_id} が入室しました。"
    add_message_to_history(
        room_id, "System", join_notification, is_system_message=True)
    # システムメッセージとしてブロードキャスト
    broadcast_to_room(room_id, dbname, "System", join_notification,
                      is_system_message=True, exclude_login_id=login_id)


def user_leaves_room(room_id: str, dbname: str, login_id: str, room_name: str):
    """ユーザーがルームから退室したときに呼び出される"""
    chan_left = None
    user_was_in_room = False
    with chat_rooms_lock:
        if room_id in active_chat_rooms and login_id in active_chat_rooms[room_id]["users"]:
            user_data_left = active_chat_rooms[room_id]["users"].pop(
                login_id, None)
            chan_left = user_data_left["chan"] if user_data_left else None
            user_was_in_room = True
            if not active_chat_rooms[room_id]["users"]:
                del active_chat_rooms[room_id]
                if room_id in chat_room_histories:
                    del chat_room_histories[room_id]
                logging.info(f"チャットルーム {room_id} が空になったため削除しました。")
            elif active_chat_rooms[room_id]["locked_by"] == login_id:
                # オーナーが抜けたらロック解除
                owner_left_unlock_message = f"{login_id} が退出したため、ルーム'{room_name}'のロックは解除されました。"
                # ロッククリア
                active_chat_rooms[room_id]["locked_by"] = None
                add_message_to_history(
                    room_id, "System", owner_left_unlock_message, is_system_message=True)
                broadcast_to_room(
                    room_id, dbname, "System", owner_left_unlock_message, is_system_message=True)

    if chan_left:
        leave_notification = f"{login_id} が退室しました。"
        add_message_to_history(
            room_id, "System", leave_notification, is_system_message=True)
        broadcast_to_room(room_id, dbname, "System",
                          leave_notification, is_system_message=True)


def handle_chat_room(chan, dbname: str, login_id: str, menu_mode: str, room_id: str, room_name: str):
    """
    チャットルーム本体
    """
    util.send_text_by_key(chan, "chat.welcome", menu_mode, room_name=room_name)
    util.send_text_by_key(chan, "chat.help", menu_mode)

    # ルームロック確認
    with chat_rooms_lock:
        room_data = active_chat_rooms.get(room_id)
        if room_data and room_data.get("locked_by") and room_data.get("locked_by") != login_id:
            util.send_text_by_key(chan, "chat.room_locked", menu_mode,
                                  room_name=room_name, owner=room_data.get("locked_by"))
            return  # 入室せずに終了
    user_joins_room(room_id, dbname, login_id, chan, room_name, menu_mode)

    try:
        while True:
            user_input = ssh_input.process_input(chan)

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
                    online_list = ONLINE_MEMBERS_FUNC()
                    bbsmenu.telegram_send(
                        chan, dbname, login_id, online_list, menu_mode)
                else:
                    util.send_text_by_key(
                        chan, "common_messages.error", menu_mode)
            elif user_input.lower() == "!w":
                # WHOをチャット内から参照
                if ONLINE_MEMBERS_FUNC:
                    online_list = ONLINE_MEMBERS_FUNC()
                    bbsmenu.who_menu(chan, dbname, online_list, menu_mode)
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
                        # 後々chatroom.ymlからroom_idに対応するnameを取得して表示する予定。
                        display_room_name_for_status = r_id  # TODO: chatroom.yml から正式名を取得
                        util.send_text_by_key(chan, "chat.room_status", menu_mode,
                                              room_name=display_room_name_for_status,
                                              lock_status=lock_status, users=users_in_room)
                    util.send_text_by_key(
                        chan, "chat.room_status_footer", menu_mode)

            elif user_input.lower() == "!l":
                # 部屋をロック。途中入室は今のところ未実装。一瞬鍵を開けてから入室することにする。
                message_for_log_and_broadcast_body = None
                lock_successful = False

                with chat_rooms_lock:
                    if room_id in active_chat_rooms:
                        room_info = active_chat_rooms[room_id]
                        if room_info.get("locked_by"):
                            util.send_text_by_key(
                                chan, "chat.room_already_locked", menu_mode, owner=room_info.get("locked_by"), room_name=room_name)
                        else:
                            room_info["locked_by"] = login_id
                            message_to_log_and_broadcast = f"ルーム'{room_name}'は {login_id} によりロックされました。"
                            lock_successful = True
                    else:
                        util.send_text_by_key(
                            chan, "chat.room_not_found_error", menu_mode, room_id=room_id)

                if lock_successful and message_to_log_and_broadcast:
                    add_message_to_history(
                        room_id, "System", message_to_log_and_broadcast, is_system_message=True)
                    broadcast_to_room(
                        room_id, dbname, "System", message_to_log_and_broadcast, is_system_message=True)
            elif user_input.lower() == "!u":
                # 部屋をアンロック。
                message_to_log_and_broadcast_unlock = None
                unlock_successful = False

                with chat_rooms_lock:
                    if room_id in active_chat_rooms:
                        room_info = active_chat_rooms[room_id]
                        current_owner = room_info.get("locked_by")

                        if not current_owner:
                            util.send_text_by_key(
                                chan, "chat.room_not_locked", menu_mode, room_name=room_name)
                        elif current_owner == login_id:  # Owner unlocks
                            room_info["locked_by"] = None
                            message_to_log_and_broadcast_unlock = f"ルーム'{room_name}'は {login_id} によりアンロックされました。"
                            unlock_successful = True
                        elif current_owner != login_id:  # Someone else tries to unlock a room locked by 'current_owner'
                            util.send_text_by_key(
                                chan, "chat.room_unlock_not_owner", menu_mode, owner=current_owner, room_name=room_name)
                    else:
                        util.send_text_by_key(
                            chan, "chat.room_not_found_error", menu_mode, room_id=room_id)  # More specific error

                if unlock_successful and message_to_log_and_broadcast_unlock:
                    add_message_to_history(
                        room_id, "System", message_to_log_and_broadcast_unlock, is_system_message=True)
                    broadcast_to_room(
                        room_id, dbname, "System", message_to_log_and_broadcast_unlock, is_system_message=True)
            elif user_input.lower() in ("!exit", "!quit", "!bye", "退室"):
                # ユーザーがチャットルームから退出する
                util.send_text_by_key(
                    chan, "chat.leaving_room", menu_mode, room_name=room_name)
                break  # ループを抜けて finally で user_leaves_room が呼ばれる
            else:
                # 自分の画面に表示するメッセージ (menu_mode 対応)
                base_my_message_format = util.get_text_by_key(
                    "chat.my_message_format", menu_mode
                )
                if base_my_message_format:
                    try:
                        my_message_display = base_my_message_format.format(
                            sender=login_id, message=user_input)
                    except KeyError as e:
                        logging.error(
                            f"Formatting error for key 'chat.my_message_format' (mode: {menu_mode}): {e}. Raw: '{base_my_message_format}'")
                        # Fallback
                        my_message_display = f"{login_id}: {user_input}"
                else:
                    logging.warning(
                        f"Text key 'chat.my_message_format' for mode '{menu_mode}' not found. Using default.")
                    # Fallback
                    my_message_display = f"{login_id}: {user_input}"
                # 自分のメッセージ表示
                chan.send(b"\r\033[2K" +
                          f"{my_message_display}\r\n".encode('utf-8'))

                # 履歴に追加 (現状のフォーマットを維持)
                add_message_to_history(room_id, login_id, user_input)

                # 他のユーザーにブロードキャスト
                broadcast_to_room(room_id, dbname, login_id, user_input, is_system_message=False,
                                  exclude_login_id=login_id)

            # 各コマンド処理またはメッセージ送信後、新着電報をチェック
            # この呼び出しは、他のユーザーからのメッセージ受信時にも行われるようになったため、
            # ここでの呼び出しが重複になる可能性を考慮する。
            # ただし、telegram_recieve は未読がなければ何もしないので、実害は少ない。
            if not user_input.lower().startswith("!"):  # 通常メッセージ送信時のみここでチェック（コマンド時はbroadcast内でチェックされる）
                bbsmenu.telegram_recieve(chan, dbname, login_id, menu_mode)

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
        user_leaves_room(room_id, dbname, login_id, room_name)
        logging.info(f"User {login_id} finished chat in room {room_id}.")
