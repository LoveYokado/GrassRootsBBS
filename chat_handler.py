import logging
import collections
import time
import threading

import ssh_input
import util

# チャットルームごとのメッセージ履歴
# {room_id:collections.deque()}
chat_room_histories = {}
MAX_HISTORY_MESSAGES = 100

active_chat_rooms = {}
chat_rooms_lock = threading.Lock()


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
            for target_login_id, target_chan in active_chat_rooms[room_id].items():
                if target_login_id == exclude_login_id:
                    continue
                try:
                    # 1. Save cursor, 2. CR, 3. Insert Line, 4. Send Message, 5. Restore cursor
                    # Save, CR, Insert Line
                    target_chan.send(b"\r\033[2K")
                    target_chan.send(message_payload.encode(
                        'utf-8'))  # Send message
                except Exception as e:
                    logging.error(
                        f"ルーム{room_id}のユーザー{target_login_id}へのメッセージブロードキャスト中にエラー：{e}")


def user_joins_room(room_id: str, login_id: str, chan, room_name: str):
    """ユーザーがルームに入室したときに呼び出される"""
    with chat_rooms_lock:
        if room_id not in active_chat_rooms:
            active_chat_rooms[room_id] = {}
        active_chat_rooms[room_id][login_id] = chan
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
        if room_id in active_chat_rooms and login_id in active_chat_rooms[room_id]:
            chan_left = active_chat_rooms[room_id].pop(login_id)
            user_was_in_room = True
            if not active_chat_rooms[room_id]:
                del active_chat_rooms[room_id]
                if room_id in chat_room_histories:
                    del chat_room_histories[room_id]
                logging.info(f"チャットルーム {room_id} が空になったため削除しました。")

    if user_was_in_room:
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

            if user_input.lower() == "/help":
                util.send_text_by_key(chan, "chat.help", menu_mode)
            elif user_input.lower() == "/exit":
                logging.info(
                    f"ユーザー{login_id}がチャットルーム{room_id}から /exit で退室します。")
                break

            else:
                # 自分の画面にも「名前: メッセージ」形式で表示する
                my_message_display = f"{login_id}: {user_input}"
                # 他のユーザーへのブロードキャストと同様の表示制御を行う
                # 現在の入力行(ssh_inputが改行した後)をクリア
                chan.send(b"\r\033[2K")
                # 自分のメッセージを表示
                chan.send(f"{my_message_display}\r\n".encode(
                    'utf-8'))
                # 他のユーザーにブロードキャスト
                message_to_send = f"{login_id}: {user_input}"
                add_message_to_history(room_id, login_id, user_input)
                broadcast_to_room(room_id, message_to_send,
                                  exclude_login_id=login_id)

    except Exception as e:
        logging.error(f"チャットルーム {room_id} でエラーが発生しました(user: {login_id})：{e}")
        try:
            util.send_text_by_key(
                chan, "common_messages.unexpected_error", menu_mode)
        except Exception:
            logging.error(
                "Failed to send unexpected_error message to user in chat.")

    finally:
        user_leaves_room(room_id, login_id, room_name)
        logging.info(f"User {login_id} finished chat in room {room_id}.")
