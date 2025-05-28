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
def broadcast_to_room(room_id: str, message_to_broadcast: str, exclude_login_id: str = None):
    """
    ルーム内のすべてのユーザーにメッセージをブロードキャスト。
    """
    with chat_rooms_lock:
        if room_id in active_chat_rooms:
            message_payload = f"{message_to_broadcast.replace('\n', '\r\n')}\r\n"
            for target_login_id, target_chan in active_chat_rooms[room_id]["users"].items():
                if target_login_id == exclude_login_id:
                    continue
                try:
                    # 1. Save cursor, 2. CR, 3. Insert Line, 4. Send Message, 5. Restore cursor
                    # Save, CR, Insert Line
                    # 他のユーザの入力業をクリアしてからメッセージ送信
                    target_chan.send(
                        b"\r\033[2K" + message_payload.encode('utf-8'))
                except Exception as e:
                    logging.error(
                        f"ルーム{room_id}のユーザー{target_login_id}へのメッセージブロードキャスト中にエラー：{e}")


def set_online_members_function_for_chat(func):

    global ONLINE_MEMBERS_FUNC
    ONLINE_MEMBERS_FUNC = func


def user_joins_room(room_id: str, login_id: str, chan, room_name: str):
    """ユーザーがルームに入室したときに呼び出される"""
    with chat_rooms_lock:
        if room_id not in active_chat_rooms:
            active_chat_rooms[room_id] = {"users": {}, "locked_by": None}
        active_chat_rooms[room_id]["users"][login_id] = chan

    join_notification = f"{login_id} が入室しました。"
    add_message_to_history(
        room_id, "System", join_notification, is_system_message=True)
    broadcast_to_room(
        # room_name_for_prompt 削除
        room_id, f"System: {join_notification}", exclude_login_id=login_id)


def user_leaves_room(room_id: str, login_id: str, room_name: str):
    """ユーザーがルームから退室したときに呼び出される"""
    chan_left = None
    user_was_in_room = False
    with chat_rooms_lock:
        if room_id in active_chat_rooms and login_id in active_chat_rooms[room_id]["users"]:
            chan_left = active_chat_rooms[room_id]["users"].pop(login_id, None)
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
                    room_id, f"System: {owner_left_unlock_message}")

    if chan_left:
        leave_notification = f"{login_id} が退室しました。"
        add_message_to_history(
            room_id, "System", leave_notification, is_system_message=True)
        broadcast_to_room(
            room_id, f"System: {leave_notification}")


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
            return
    user_joins_room(room_id, login_id, chan, room_name)

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
                        display_room_name = r_id
                        chan.send(
                            f"{display_room_name:<15} {lock_status}: {users_in_room}\r\n".encode('utf-8'))
                        util.send_text_by_key(
                            chan, "chat.room_status_footer", menu_mode)

            elif user_input.lower() == "!l":
                # 部屋をロック。途中入室は今のところ未実装。一瞬鍵を開けてから入室することにする。
                message_to_log_and_broadcast = None
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
                        room_id, f"System: {message_to_log_and_broadcast}")
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
                        room_id, f"System: {message_to_log_and_broadcast_unlock}")
            elif user_input.lower() in ("!exit", "!quit", "!bye", "退室"):
                # ユーザーがチャットルームから退出する
                util.send_text_by_key(
                    chan, "chat.leaving_room", menu_mode, room_name=room_name)
                break  # ループを抜けて finally で user_leaves_room が呼ばれる

            else:
                # 自分の画面にも「名前: メッセージ」形式で表示する
                my_message_display = f"{login_id}: {user_input}"
                # 他のユーザーへのブロードキャストと同様の表示制御を行う
                # 現在の入力行(ssh_inputが改行した後)をクリア
                chan.send(b"\r\033[2K" +
                          f"{my_message_display}\r\n".encode('utf-8'))
                # 他のユーザーにブロードキャスト
                message_to_send = f"{login_id}: {user_input}"
                add_message_to_history(room_id, login_id, user_input)
                broadcast_to_room(room_id, message_to_send,
                                  exclude_login_id=login_id)
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
        user_leaves_room(room_id, login_id, room_name)
        logging.info(f"User {login_id} finished chat in room {room_id}.")
