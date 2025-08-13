# bbs_handler.py (骨格)
import logging
import socket
import textwrap
import datetime
import json

from . import util, hierarchical_menu, bbs_manager, database

# CommandHandler: ユーザー入力に応じたコマンド処理


class CommandHandler:
    """ユーザー入力に応じたコマンド処理を行うクラス"""

    def __init__(self, chan, login_id, display_name, menu_mode, ip_address):
        self.chan = chan
        self.login_id = login_id
        self.display_name = display_name
        self.menu_mode = menu_mode
        self.ip_address = ip_address
        self.board_manager = bbs_manager.BoardManager()
        self.article_manager = bbs_manager.ArticleManager()
        self.permission_manager = bbs_manager.PermissionManager()
        self.current_board = None  # 現在の掲示板
        self.just_displayed_header_from_tail_h = False  # 読み戻り時の状態フラグ

        # ユーザー情報をDBから一括で取得
        user_data = database.get_user_auth_info(login_id)
        if not user_data:
            # ユーザーが見つからない場合は、処理を続行できないためエラーログを出して初期化を中断
            logging.error(
                f"CommandHandler初期化失敗: ユーザー '{login_id}' が見つかりません。")
            # 属性をNoneやデフォルト値で初期化してクラッシュを防ぐ
            self.user_id_pk = None
            self.userlevel = 0
            self.last_login_timestamp = 0
            self.user_read_progress_map = {}
            # この後、呼び出し元でNoneチェックなどが必要になるかもしれないが、まずはここまで
            return

        self.user_id_pk = user_data.get('id')
        self.userlevel = user_data.get('level', 0)
        self.last_login_timestamp = 0
        if user_data.get('lastlogin') is not None:
            try:
                self.last_login_timestamp = int(user_data['lastlogin'])
            except (ValueError, TypeError):
                logging.warning(
                    f"CommandHandler.__init__: lastlogin field for user {login_id} is not a valid integer: {user_data['lastlogin']}. Defaulting to 0.")

        # 既読情報は専用の関数で取得（JSONパースのため）
        self.user_read_progress_map = database.get_user_read_progress(
            self.user_id_pk)

    def _display_kanban(self):
        """看板を表示する"""
        if not self.current_board:
            return

        kanban_body = self.current_board['kanban_body'] if 'kanban_body' in self.current_board.keys(
        ) else ''

        if not kanban_body:
            return  # 看板がなければ表示しない

        if kanban_body:
            processed_body = kanban_body.replace(
                '\r\n', '\n').replace('\n', '\r\n')
            self.chan.send(processed_body.encode('utf-8'))
            if not processed_body.endswith('\r\n'):
                self.chan.send(b'\r\n')
        if kanban_body:
            self.chan.send(b'\r\n')

    def _update_read_progress(self, board_id_pk, article_number):
        """
        ユーザの閲覧進捗更新
        指定された掲示板で指定された記事番号まで読んだことを記録
        """
        # board_id_pk は int なので、辞書のキーとして使うために文字列に変換
        current_read_article_number = self.user_read_progress_map.get(
            str(board_id_pk), 0)
        if article_number > current_read_article_number:
            self.user_read_progress_map[str(board_id_pk)] = article_number
            # dbnameは不要になった
            database.update_user_read_progress(
                self.user_id_pk, self.user_read_progress_map)

    def display_board_entry_sequence(self):
        """掲示板に入った際の初期表示(ヘッダと看板)"""
        if not self.current_board:
            logging.error("現在のボードが設定されていません。")
            return
        board_name_display = self.current_board['name'] if 'name' in self.current_board else 'unknown board'
        util.send_text_by_key(
            self.chan, "bbs.current_board_header", self.menu_mode, board_name=board_name_display
        )
        self._display_kanban()

    def command_loop(self):
        """コマンド処理のメインループ (mail_handler.py を参考に実装)"""
        if not self.current_board:
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        # 掲示板閲覧権限チェック
        if not self.permission_manager.can_view_board(self.current_board, self.user_id_pk, self.userlevel):
            util.send_text_by_key(
                self.chan, "bbs.permission_denied_read_board", self.menu_mode)
            return

        board_name_display = self.current_board['name'] if 'name' in self.current_board else 'unknown board'
        # 説明表示が必要ならコメント外す
        util.send_text_by_key(
            self.chan, "bbs.current_board_header",
            self.menu_mode, board_name=board_name_display
        )

        self._display_kanban()  # 板看板を表示
        # モバイル用の操作ボタンを表示
        self.chan.send(b'\x1b[?2030h')
        try:
            while True:
                # メニュー表示
                util.send_text_by_key(
                    self.chan, "prompt.bbs_wrdate", self.menu_mode, add_newline=False
                )
                try:
                    self.chan.settimeout(25.0)
                    choice = self.chan.process_input()
                except socket.timeout:
                    continue  # タイムアウトしたらループを継続
                finally:
                    self.chan.settimeout(None)
                if choice is None:
                    return  # 切断
                choice = choice.lower().strip()

                if choice == 'w':
                    self.chan.send(b'\x1b[?2030l')  # Write/Readボタンを非表示
                    self.write_article()
                    # 戻ってきたら再度表示
                    self.chan.send(b'\x1b[?2030h')
                elif choice == 'r':
                    self.chan.send(b'\x1b[?2030l')  # Write/Readボタンを非表示
                    self.show_article_list(
                        last_login_timestamp=self.last_login_timestamp)
                    # 戻ってきたら再度表示
                    self.chan.send(b'\x1b[?2030h')
                elif choice == 'e' or choice == '':
                    return "empty_exit"
                else:
                    util.send_text_by_key(
                        self.chan, "common_messages.invalid_command", self.menu_mode)
        finally:
            # メニューを抜けたら必ずボタンを非表示にする
            self.chan.send(b'\x1b[?2030l')

    def show_article_list(self, display_initial_header=True, last_login_timestamp=0):
        """記事一覧を表示"""

        # モバイル用の操作ボタンを表示するエスケープシーケンスを送信
        self.chan.send(b'\x1b[?2024h')  # パネル表示

        # 掲示板閲覧権限チェック(念の為)
        if not self.permission_manager.can_view_board(self.current_board, self.user_id_pk, self.userlevel):
            util.send_text_by_key(
                self.chan, "bbs.permission_denied_read_board", self.menu_mode)
            return

        board_id_pk = self.current_board['id']
        articles = []  # この行で articles を初期化
        board_type = self.current_board.get('board_type', 'simple')
        current_index = 0
        article_id_width = 5  # 記事番号桁数

        # 常に削除済み記事も取得するが、表示方法は権限によって変える
        # show_deleted_articles 変数はここでは直接使わない

        def reload_articles_display(keep_index=True):
            nonlocal articles, current_index, article_id_width, display_initial_header, last_login_timestamp
            current_article_id_on_reload = None

            if board_type == 'thread':
                fetched_articles = self.article_manager.get_threads(
                    board_id_pk, include_deleted=True)
            else:  # simple
                fetched_articles = self.article_manager.get_articles_by_board(
                    board_id_pk, include_deleted=True)  # 常に削除済み記事も取得
            articles = fetched_articles if fetched_articles else []

            # last_login_timestamp 以降の記事にジャンプする
            initial_jump_index = 0
            found_new_articles = False
            if articles and last_login_timestamp > 0:
                for i, art in enumerate(articles):
                    if art['created_at'] > last_login_timestamp:
                        initial_jump_index = i
                        found_new_articles = True
                        break

            # リスト表示前の未読既読処理
            total_articles = len(articles)
            last_read_article_number = self.user_read_progress_map.get(
                str(board_id_pk), 0)
            unread_articles_count = 0
            for article in articles:
                if article['article_number'] > last_read_article_number:
                    unread_articles_count += 1

            new_idx = 0
            if articles:  # 記事が1件以上ある場合のみインデックスを考慮
                if keep_index and current_article_id_on_reload is not None:  # 前回の記事IDを維持する場合
                    # 既存のインデックス維持
                    found = False
                    for i, art in enumerate(articles):
                        if art['id'] == current_article_id_on_reload:
                            new_idx = i
                            found = True
                            break
                    if not found:
                        new_idx = 0  # 該当記事がなければ先頭へ
                else:  # keep_index が False の場合
                    if found_new_articles:
                        new_idx = initial_jump_index  # 未読記事がある場合はその先頭へ
                    else:
                        # 未読記事がない場合は末尾へ (記事が1件以上ある場合)
                        new_idx = len(articles) - 1
            article_id_width = max(
                5, len(str(len(articles)))) if articles else 5
            current_index = new_idx

            # 画面クリアしてヘッダ再表示
            if display_initial_header:  # display_initial_header が True の場合のみヘッダを表示
                util.send_text_by_key(
                    self.chan, "bbs.article_list_count", self.menu_mode,
                    total_count=total_articles, unread_count=unread_articles_count
                )
                if board_type == 'thread':
                    util.send_text_by_key(
                        self.chan, "bbs.thread_list_header", self.menu_mode)
                else:
                    util.send_text_by_key(
                        self.chan, "bbs.article_list_header", self.menu_mode)
            if not articles:
                util.send_text_by_key(
                    self.chan, "bbs.no_article", self.menu_mode)
                current_index = 0  # 記事がなかったらインデックスは0
            else:
                display_current_article_header()

            display_initial_header = True

        def display_current_article_header():
            nonlocal articles, current_index, article_id_width
            if current_index == -1:  # 先頭マーカ
                marker_num_str = "0" * article_id_width
                self.chan.send(f"{marker_num_str} v\r\n".encode('utf-8'))
            elif current_index == len(articles):  # 末尾マーカ
                if not articles:  # 記事がない場合
                    util.send_text_by_key(
                        self.chan, "bbs.no_article", self.menu_mode)
                else:
                    marker_num_display = len(articles) + 1
                    marker_num_str = f"{marker_num_display:0{article_id_width}d}"
                    self.chan.send(f"{marker_num_str} ^\r\n".encode('utf-8'))
            elif articles and 0 <= current_index < len(articles):
                article = articles[current_index]
                title = article['title'] if article['title'] else "(No Title)"
                reply_count = article['reply_count'] if board_type == 'thread' and 'reply_count' in article.keys(
                ) else 0

                deleted_mark = "*" if article['is_deleted'] == 1 else ""

                user_id_from_article = article['user_id']
                display_sender_name = ""
                try:
                    # user_idが数値に変換できるか試す (登録ユーザー)
                    user_id_int = int(user_id_from_article)
                    # dbnameは不要になった
                    user_name = database.get_user_name_from_user_id(
                        user_id_int)
                    display_sender_name = user_name if user_name else "(Unknown)"
                except (ValueError, TypeError):
                    # 数値に変換できない場合 (GUEST(hash)など)、そのまま表示名として使用
                    display_sender_name = str(user_id_from_article)

                # 投稿者名短縮
                user_name_short = util.shorten_text_by_slicing(
                    display_sender_name if display_sender_name else "(Unknown)", width=14)
                try:
                    created_at_ts = article['created_at']
                    r_date_str = datetime.datetime.fromtimestamp(
                        created_at_ts).strftime("%y/%m/%d")
                    r_time_str = datetime.datetime.fromtimestamp(
                        created_at_ts).strftime("%H:%M:%S")
                except:
                    r_date_str = "--/--/--"
                    r_time_str = "--:--"

                # タイトル表示の調整
                if article['is_deleted'] == 1:
                    # 権限チェックを PermissionManager に移譲
                    if self.permission_manager.can_view_deleted_article_content(article, self.user_id_pk, self.userlevel):
                        title_short = util.shorten_text_by_slicing(
                            title, width=28)  # "* " を考慮して少し短く
                    else:
                        title_short = ""  # 権限がない場合は表示しない
                else:
                    to_marker = "(T/O)" if article['body'] == '(T/O)' else ""
                    if board_type == 'thread':
                        # 返信数と(T/O)マークを表示するスペースを確保
                        title_part = util.shorten_text_by_slicing(
                            title, width=24 - len(to_marker))
                        title_short = f"{title_part}{to_marker}"
                    else:  # simple
                        title_part = util.shorten_text_by_slicing(
                            title, width=32 - len(to_marker))
                        title_short = f"{title_part}{to_marker}"
                # ユーザー名の後のスペースを調整
                spaces_before_title_field = "  " if deleted_mark else "   "
                # 左寄せ、指定幅
                article_no_str = f"{article['article_number']:0{article_id_width}d}"

                reply_count_str = f"({reply_count})" if board_type == 'thread' else ""
                self.chan.send(
                    f"{article_no_str}  {r_date_str} {r_time_str} {user_name_short:<14}{spaces_before_title_field}{deleted_mark}{title_short}{reply_count_str}\r\n".encode('utf-8'))
            else:
                util.send_text_by_key(
                    self.chan, "bbs.no_article", self.menu_mode)

        reload_articles_display(keep_index=False)
        self.just_displayed_header_from_tail_h = False  # フラグをリセット

        while True:
            util.prompt_handler(self.chan, self.login_id, self.menu_mode)
            key_input = None
            decoded_char_for_check = None  # 番号ジャンプ用数字判定
            try:
                # Gunicornのタイムアウト(デフォルト30秒)より短いタイムアウトを設定
                self.chan.settimeout(25.0)
                data = self.chan.recv(1)  # 1バイトずつデータを受信
                self.chan.settimeout(None)  # 他の処理に影響しないようにタイムアウトをリセット

                if not data:
                    logging.info(
                        f"掲示板記事一覧中にクライアントが切断されました。 (ユーザー: {self.login_id})")
                    return  # 切断

                # ASCIIデコード判定
                try:
                    decoded_char_for_check = data.decode('ascii')
                except UnicodeDecodeError:
                    decoded_char_for_check = None  # 失敗したとき

                if data == b'\x1b':  # esc - 矢印の可能性
                    self.chan.settimeout(0.05)  # 短いタイムアウトを設定
                    try:
                        next_byte1 = self.chan.recv(1)
                        if next_byte1 == b'[':
                            next_byte2 = self.chan.recv(1)
                            if next_byte2 == b'A':
                                key_input = "KEY_UP"
                            elif next_byte2 == b'B':
                                key_input = "KEY_DOWN"
                            elif next_byte2 == b'C':  # KEY_RIGHT
                                key_input = "KEY_RIGHT"
                            elif next_byte2 == b'D':  # KEY_LEFT
                                key_input = "KEY_LEFT"
                            else:
                                key_input = '\x1b'  # 不明なのはesc扱い
                        else:
                            key_input = '\x1b'  # escのあとに[以外が来た場合
                    except socket.timeout:
                        key_input = '\x1b'  # タイムアウトもesc扱い
                    finally:
                        self.chan.settimeout(None)  # タイムアウトを解除
                elif data == b'\x05':  # CTRL+E
                    key_input = '\x05'
                elif data == b'\x12':  # CTRL+R
                    key_input = '\x12'
                elif data == b'\x18':  # CTRL+X
                    key_input = '\x18'
                elif data == b'\x06':  # CTRL+F
                    key_input = '\x06'
                elif data == b'\x04':  # CTRL+D
                    key_input = '\x04'
                elif data == b'\t':
                    key_input = "\t"  # タブキー
                elif data in (b'\r', b'\n'):
                    key_input = "ENTER"  # エンターキー
                elif data == b' ':
                    key_input = "SPACE"  # スペースキー
                else:
                    try:
                        key_input = data.decode('ascii').strip().lower()
                    except UnicodeDecodeError:
                        self.chan.send(b'\a')  # デコードできないときはビープ音
                        continue  # 次のループへ
            except socket.timeout:
                # ユーザーからの入力がなくてもタイムアウトでループが継続する
                # これによりワーカースレッドのハングを防ぐ
                continue
            except Exception as e:
                logging.info(
                    f"掲示板記事一覧中にクライアントが切断されました。 (ユーザー: {self.login_id})")
                return  # 切断

            if key_input is None:  # キーが取得できなかった場合 (通常は発生しないはず)
                continue

            # 数字キーによる記事ジャンプ処理
            if decoded_char_for_check and decoded_char_for_check.isdigit():
                num_input_buffer = decoded_char_for_check
                self.chan.send(data)  # 最初の数字をエコー

                max_digits = 5  # 記事番号の最大桁数（記事数に応じて調整しても良い）

                while True:  # Enterが押されるか、不正な入力があるまでループ
                    char_data = self.chan.recv(1)
                    if not char_data:
                        return  # 切断

                    try:
                        char = char_data.decode('ascii')
                        if char in ('\r', '\n'):
                            self.chan.send(b'\r\n')  # Enterをエコー
                            break
                        elif char.isdigit():
                            if len(num_input_buffer) < max_digits:
                                num_input_buffer += char
                                self.chan.send(char_data)  # 入力された数字をエコー
                            else:
                                self.chan.send(b'\a')  # 桁数オーバーでビープ
                        else:  # 数字でもEnterでもバックスペースでもない
                            self.chan.send(b'\a')  # ビープ音
                            num_input_buffer = ""  # 入力を無効化してループを抜ける
                            break
                    except UnicodeDecodeError:  # ASCIIデコード失敗
                        self.chan.send(b'\a')  # ビープ音
                        num_input_buffer = ""  # 入力を無効化してループを抜ける
                        break

                if num_input_buffer:  # 何か有効な数字が入力されていれば
                    try:
                        target_article_number = int(num_input_buffer)
                        target_article_index = -1
                        for i, art_item in enumerate(articles):
                            if art_item['article_number'] == target_article_number:
                                target_article_index = i
                                break
                        if target_article_index != -1:
                            current_index = target_article_index
                            # self.read_article(target_article_number, show_header=True, show_back_prompt=True) # 本文読み込みはしない
                            # reload_articles_display(keep_index=True) # リスト全体の再読み込みも不要
                            # ジャンプ先表示前にリストヘッダを再表示
                            util.send_text_by_key(
                                self.chan, "bbs.article_list_header", self.menu_mode)
                            display_current_article_header()  # 該当記事のヘッダを表示
                        else:
                            util.send_text_by_key(
                                self.chan, "bbs.article_not_found", self.menu_mode)
                            display_current_article_header()
                    except ValueError:  # int変換失敗 (通常は起こらないはず)
                        util.send_text_by_key(
                            self.chan, "common_messages.invalid_input", self.menu_mode)
                        display_current_article_header()
                self.just_displayed_header_from_tail_h = False
                continue  # 数字ジャンプ処理後はループの先頭へ
            elif decoded_char_for_check == '"':  # タイトル検索
                self.chan.send(b'"\r\n')  # 入力された " をエコーして改行
                util.send_text_by_key(
                    self.chan, "bbs.search_title_prompt", self.menu_mode, add_newline=False)
                search_term_raw = self.chan.process_input()

                if search_term_raw is None:
                    return  # 切断
                search_term = search_term_raw.strip().lower()

                if not search_term:
                    # 検索文字列が空なら元のリストヘッダを再表示して継続
                    util.send_text_by_key(
                        self.chan, "bbs.article_list_header", self.menu_mode)
                    display_current_article_header()
                    self.just_displayed_header_from_tail_h = False
                    continue

                # DBから全記事を再取得してフィルタリング
                all_articles_from_db_for_search = self.article_manager.get_articles_by_board(
                    board_id_pk, include_deleted=True)  # 常に削除済みも取得

                filtered_articles_list = []
                if all_articles_from_db_for_search:  # DBに記事があればフィルタリング
                    for article_item in all_articles_from_db_for_search:
                        # 検索対象のタイトル文字列を準備
                        title_to_check = (
                            article_item['title'] if article_item['title'] else "").lower()
                        # 削除済みタイトルの可視性チェック
                        if article_item['is_deleted'] == 1:
                            can_see_deleted_title_search = False
                            if self.userlevel >= 5:  # シスオペ
                                can_see_deleted_title_search = True
                            else:
                                try:
                                    # 投稿者本人
                                    if int(article_item['user_id']) == self.user_id_pk:
                                        can_see_deleted_title_search = True
                                except ValueError:
                                    pass  # ID変換失敗時は見せない
                            if not can_see_deleted_title_search:
                                title_to_check = ""  # 見えないタイトルは検索対象外

                        if search_term in title_to_check:
                            filtered_articles_list.append(article_item)

                articles = filtered_articles_list  # 表示用リストを検索結果で上書き
                current_index = 0  # 検索結果の先頭に

                if articles:
                    # フィルタリングされた記事リスト内の最大の記事番号の桁数を計算
                    max_num_val = 0
                    for art_item_for_width in articles:
                        if art_item_for_width['article_number'] > max_num_val:
                            max_num_val = art_item_for_width['article_number']
                    article_id_width = max(5, len(str(max_num_val)))
                else:
                    article_id_width = 5  # 記事がない場合はデフォルト

                util.send_text_by_key(
                    self.chan, "bbs.search_results_header", self.menu_mode, search_term=search_term_raw)
                util.send_text_by_key(  # 検索結果表示の前に、共通のリストヘッダを表示
                    self.chan, "bbs.article_list_header", self.menu_mode)

                if not articles:
                    util.send_text_by_key(
                        self.chan, "bbs.search_no_results", self.menu_mode)
                else:
                    display_current_article_header()  # 検索結果の先頭記事ヘッダを表示
                self.just_displayed_header_from_tail_h = False
                continue
            elif decoded_char_for_check == "'":  # 全文検索
                self.chan.send(b"'\r\n")  # 入力された ' をエコーして改行
                util.send_text_by_key(
                    self.chan, "bbs.search_title_prompt", self.menu_mode, add_newline=False)  # タイトル検索と同じプロンプト
                search_term_raw = self.chan.process_input()

                if search_term_raw is None:
                    return  # 切断
                search_term = search_term_raw.strip().lower()

                if not search_term:
                    util.send_text_by_key(
                        self.chan, "bbs.article_list_header", self.menu_mode)
                    display_current_article_header()
                    self.just_displayed_header_from_tail_h = False
                    continue

                all_articles_from_db_for_search = self.article_manager.get_articles_by_board(
                    board_id_pk, include_deleted=True)

                filtered_articles_list = []
                if all_articles_from_db_for_search:
                    for article_item in all_articles_from_db_for_search:
                        title_to_check = (
                            article_item['title'] if article_item['title'] else "").lower()
                        # sqlite3.Rowからは辞書形式でアクセス
                        body_from_row = article_item['body']
                        body_to_check = (
                            body_from_row if body_from_row else "").lower()

                        if article_item['is_deleted'] == 1:
                            can_see_deleted_content = False
                            if self.userlevel >= 5:  # シスオペ
                                can_see_deleted_content = True
                            else:
                                try:
                                    # 投稿者本人
                                    if int(article_item['user_id']) == self.user_id_pk:
                                        can_see_deleted_content = True
                                except ValueError:
                                    pass
                            if not can_see_deleted_content:
                                title_to_check = ""
                                body_to_check = ""  # 見えない記事はタイトルも本文も検索対象外

                        if search_term in title_to_check or search_term in body_to_check:
                            filtered_articles_list.append(article_item)

                articles = filtered_articles_list
                current_index = 0
                if articles:
                    max_num_val = max(art['article_number']
                                      for art in articles) if articles else 0
                    article_id_width = max(5, len(str(max_num_val)))
                else:
                    article_id_width = 5

                util.send_text_by_key(
                    self.chan, "bbs.search_results_header", self.menu_mode, search_term=search_term_raw)
                util.send_text_by_key(
                    self.chan, "bbs.article_list_header", self.menu_mode)
                if not articles:
                    util.send_text_by_key(
                        self.chan, "bbs.search_no_results", self.menu_mode)
                else:
                    display_current_article_header()
                self.just_displayed_header_from_tail_h = False
                continue
            # 旧方向へ進む[ctrl+e][k][上カーソル]
            elif key_input == '\x05' or key_input == "k" or key_input == "KEY_UP":
                if not articles:
                    self.chan.send(b'\a')
                    continue
                if current_index > -1:
                    current_index -= 1
                    display_current_article_header()
                else:
                    self.chan.send(b'\a')
                self.just_displayed_header_from_tail_h = False

            elif key_input == "j" or key_input == "SPACE" or key_input == "KEY_DOWN":
                if not articles:
                    self.chan.send(b'\a')
                    continue
                if current_index < len(articles):
                    current_index += 1
                    display_current_article_header()
                else:
                    self.chan.send(b'\a')
                self.just_displayed_header_from_tail_h = False

            # 現在位置を読む[ctrl+d][enter]
            elif key_input == '\x04' or key_input == "ENTER" or key_input == 'p':
                if articles and 0 <= current_index < len(articles):
                    self.read_article(
                        articles[current_index]['article_number'],
                        show_header=True,
                        show_back_prompt=True
                    )
                    # read_articleから戻ってきたら、リストを再描画
                    # (返信が投稿された可能性を考慮)
                    reload_articles_display(keep_index=True)
                elif not articles or current_index == -1 or current_index == len(articles):
                    self.chan.send(b'\a')  # マーカー位置では読めない
                self.just_displayed_header_from_tail_h = False

            elif key_input == "h" or key_input == "KEY_LEFT":  # 読み戻り
                if not articles:
                    self.chan.send(b'\a')
                    self.just_displayed_header_from_tail_h = False
                    continue

                if current_index == len(articles):  # 末尾マーカーにいる場合
                    if not articles:  # 記事がなければ何もしない
                        self.chan.send(b'\a')
                        self.just_displayed_header_from_tail_h = False
                        continue
                    current_index = len(articles) - 1  # 最終記事へ
                    display_current_article_header()    # 最終記事のヘッダ表示
                    self.just_displayed_header_from_tail_h = True
                elif self.just_displayed_header_from_tail_h:  # 末尾からhでヘッダ表示した直後
                    # この時点で current_index は最終記事を指している
                    self.read_article(
                        articles[current_index]['article_number'],
                        show_header=False,
                        show_back_prompt=False
                    )
                    current_index -= 1  # 一つ前の記事へ
                    display_current_article_header()  # 一つ前の記事のヘッダ表示
                    self.just_displayed_header_from_tail_h = False
                else:  # 通常の読み戻り (記事ヘッダが表示されている状態から h)
                    if 0 <= current_index < len(articles):  # 有効な記事位置
                        self.read_article(
                            articles[current_index]['article_number'],
                            show_header=False,
                            show_back_prompt=False
                        )
                        current_index -= 1  # 一つ前の記事へ (最初の記事を読んだ後は-1になる)
                        display_current_article_header()  # 一つ前の記事のヘッダ or 先頭マーカー表示
                    elif current_index == -1:  # 先頭マーカー
                        self.chan.send(b'\a')
                    # else current_index が範囲外のケースは通常発生しない
                    self.just_displayed_header_from_tail_h = False

            # 読み進み[ctrl+f][l][右カーソル][タブ]
            elif key_input == '\x06' or key_input == "l" or key_input == "KEY_RIGHT" or key_input == "\t":
                if not articles:
                    self.chan.send(b'\a')
                    self.just_displayed_header_from_tail_h = False
                    continue

                if current_index == -1:  # 先頭マーカーの場合
                    if not articles:  # 記事がない
                        self.chan.send(b'\a')
                        display_current_article_header()  # マーカー再表示
                        self.just_displayed_header_from_tail_h = False
                        continue
                    current_index = 0  # 最初の記事へ
                    display_current_article_header()
                    self.chan.send(b'\r\n')  # ヘッダと本文の間に空行を挿入

                    display_current_article_header()
                    self.chan.send(b'\r\n')  # ヘッダと本文の間に空行を挿入

                    self.read_article(
                        articles[current_index]['article_number'],
                        show_header=False,  # 本文表示時にはヘッダを表示しない
                        show_back_prompt=False
                    )

                    current_index += 1
                    display_current_article_header()  # 次の記事ヘッダ or 末尾マーカー
                elif 0 <= current_index < len(articles):  # 有効な記事位置
                    self.chan.send(b'\r\n')  # ヘッダと本文の間に空行
                    self.read_article(
                        articles[current_index]['article_number'],
                        show_header=False,
                        show_back_prompt=False
                    )
                    current_index += 1
                    display_current_article_header()  # 次の記事ヘッダ or 末尾マーカー
                elif current_index == len(articles):  # 末尾マーカーの場合
                    self.chan.send(b'\a')
                else:  # 予期せぬ状態
                    self.chan.send(b'\a')
                    display_current_article_header()  # とりあえず現在の状態を表示
                self.just_displayed_header_from_tail_h = False

            # 削除[*]
            elif key_input == "*":
                # ゲストは削除/復元機能を使えないようにしないとね
                if self.login_id.upper() == 'GUEST':
                    self.chan.send(b'\a')  # ビープ音
                    display_current_article_header()
                    self.just_displayed_header_from_tail_h = False
                    continue

                if not articles or current_index == -1 or current_index == len(articles):
                    self.chan.send(b'\a')  # マーカ位置では無効
                    self.just_displayed_header_from_tail_h = False
                    continue

                article_to_delete = articles[current_index]
                article_id_pk = article_to_delete['id']
                article_number = article_to_delete['article_number']

                if self.permission_manager.can_delete_article(article_to_delete, self.user_id_pk, self.userlevel):
                    if self.article_manager.toggle_delete_article(article_id_pk):
                        # トグル前の状態
                        was_deleted = article_to_delete['is_deleted'] == 1
                        # 削除状態が切り替わった
                        if was_deleted:  # 復旧された
                            util.send_text_by_key(
                                self.chan, "bbs.article_restored_success", self.menu_mode, article_number=article_number)
                        else:  # 削除された
                            util.send_text_by_key(
                                self.chan, "bbs.article_deleted_success", self.menu_mode, article_number=article_number)
                        reload_articles_display(
                            keep_index=True)  # カーソル位置を維持して再表示
                    else:
                        # 削除/復旧に失敗した場合
                        util.send_text_by_key(
                            self.chan, "common_messages.error", self.menu_mode)
                        logging.warning(
                            f"記事の削除/復旧が失敗しました。:(記事id {article_id_pk},記事番号 {article_number},投稿者ID {article_to_delete.get('user_id')})")
                        display_current_article_header()  # 失敗したら現在の行を再表示
                else:
                    # 権限なし
                    self.chan.send(b'\a')  # 権限なし
                    util.send_text_by_key(
                        self.chan, "bbs.permission_denied_delete", self.menu_mode)
                    display_current_article_header()  # 権限なしメッセージの後、現在の行を再表示
                self.just_displayed_header_from_tail_h = False

            elif key_input == "u":  # Update/Refresh
                reload_articles_display(keep_index=True)
                self.just_displayed_header_from_tail_h = False

            elif key_input == "w":
                result = self.write_article()
                if result == 'posted':
                    # 投稿成功時は、記事一覧を抜けて掲示板トップに戻る
                    self.chan.send(b'\x1b[?2024l')  # モバイルボタンを非表示
                    return
                else:
                    # キャンセルまたはエラーの場合は、記事一覧を再表示
                    reload_articles_display(keep_index=True)  # カーソル位置を維持して再表示
                    self.just_displayed_header_from_tail_h = False

            elif key_input == "s":  # シグ看板表示
                # 看板表示前に現在の記事ヘッダを消す必要はない（看板は別領域に表示される想定）
                self._display_kanban()
                display_current_article_header()  # 看板表示後はリストモードに戻る
                self.just_displayed_header_from_tail_h = False

            elif key_input == "e" or key_input == '\x1b':  # ESCでも終了
                # モバイル用の操作ボタンを非表示にするエスケープシーケンスを送信
                self.chan.send(b'\x1b[?2024l')
                return  # command_loop に戻る

            elif key_input == "?":
                self.chan.send(b'\r\n')
                util.send_text_by_key(
                    self.chan, "bbs.article_list_help", self.menu_mode)
                # ヘルプ表示後に現在の行を再表示
                self.just_displayed_header_from_tail_h = False
                display_current_article_header()  # ヘルプ表示後に現在の行を再表示

            elif key_input == "@":
                # 現在の掲示板のショートカットIDを取得
                target_shortcut_id = self.current_board['shortcut_id'] if 'shortcut_id' in self.current_board.keys(
                ) else None
                if not target_shortcut_id:
                    logging.warning(
                        f"探索リストのトグル操作中にショートカットIDが取得できませんでした。board: {self.current_board}")
                    util.send_text_by_key(
                        self.chan, "common_messages.error", self.menu_mode)
                    display_current_article_header()
                    self.just_displayed_header_from_tail_h = False
                    continue

                # ユーザーの現在の探索リストを取得
                current_list_str = database.get_user_exploration_list(
                    self.user_id_pk)
                current_list = [item.strip()
                                for item in current_list_str.split(',') if item.strip()]

                # トグル処理
                if target_shortcut_id in current_list:
                    current_list.remove(target_shortcut_id)
                    message_key = "bbs.toggle_exploration_list_removed"
                else:
                    current_list.append(target_shortcut_id)
                    message_key = "bbs.toggle_exploration_list_added"

                new_list_str = ",".join(current_list)
                if database.set_user_exploration_list(self.user_id_pk, new_list_str):
                    util.send_text_by_key(
                        self.chan, message_key, self.menu_mode, shortcut_id=target_shortcut_id)
                else:
                    util.send_text_by_key(
                        self.chan, "common_messages.db_update_error", self.menu_mode)

                display_current_article_header()
                self.just_displayed_header_from_tail_h = False

            elif key_input == "t":  # タイトル一覧 (連続スクロール)
                if not articles:
                    self.chan.send(b'\a')
                    continue
                start_idx = current_index if 0 <= current_index < len(
                    articles) else 0
                if start_idx == -1:
                    start_idx = 0  # 先頭マーカーなら0から

                self.chan.send(b'\r\n')
                if board_type == 'thread':
                    util.send_text_by_key(
                        self.chan, "bbs.thread_list_header", self.menu_mode)
                else:
                    util.send_text_by_key(
                        self.chan, "bbs.article_list_header", self.menu_mode)
                for i in range(start_idx, len(articles)):
                    article = articles[i]
                    # 左寄せ、指定幅
                    # sqlite3.Row object
                    article_no_str = f"{article['article_number']:0{article_id_width}d}"
                    title = article['title'] if article['title'] else "(No Title)"

                    reply_count = article['reply_count'] if board_type == 'thread' and 'reply_count' in article.keys(
                    ) else 0
                    # タイトル表示の調整 (記事一覧表示と同様のロジック)
                    if article['is_deleted'] == 1:
                        can_see_deleted_title_list = False
                        if self.userlevel >= 5:  # シスオペ
                            can_see_deleted_title_list = True
                        else:
                            try:
                                if int(article['user_id']) == self.user_id_pk:  # 投稿者本人
                                    can_see_deleted_title_list = True
                            except ValueError:
                                pass
                        if can_see_deleted_title_list:
                            title_short = util.shorten_text_by_slicing(
                                title, width=28)
                        else:
                            title_short = ""
                    else:
                        to_marker_list = "(T/O)" if article['body'] == '(T/O)' else ""
                        if board_type == 'thread':
                            title_part = util.shorten_text_by_slicing(
                                title, width=24 - len(to_marker_list))
                            title_short = f"{title_part}{to_marker_list}"
                        else:  # simple
                            title_part = util.shorten_text_by_slicing(
                                title, width=32 - len(to_marker_list))
                            title_short = f"{title_part}{to_marker_list}"

                    deleted_mark_list = "*" if article['is_deleted'] == 1 else ""
                    user_id_from_article = article['user_id']
                    display_sender_name = ""
                    try:
                        user_id_int = int(user_id_from_article)
                        # dbnameは不要になった
                        user_name = database.get_user_name_from_user_id(
                            user_id_int)
                        display_sender_name = user_name if user_name else "(Unknown)"
                    except (ValueError, TypeError):
                        display_sender_name = str(user_id_from_article)

                    spaces_before_title_field_list = "  " if deleted_mark_list else "   "
                    user_name_short = util.shorten_text_by_slicing(
                        display_sender_name if display_sender_name else "(Unknown)", width=14)
                    try:
                        created_at_ts = article['created_at']
                        r_date_str = datetime.datetime.fromtimestamp(
                            created_at_ts).strftime('%y/%m/%d')
                        r_time_str = datetime.datetime.fromtimestamp(
                            created_at_ts).strftime('%H:%M:%S')
                    except:
                        r_date_str = "----/--/--"
                        r_time_str = "--:--"
                    reply_count_str = f"({reply_count})" if board_type == 'thread' else ""
                    self.chan.send(
                        f"{article_no_str}  {r_date_str} {r_time_str} {user_name_short:<14}{spaces_before_title_field_list}{deleted_mark_list}{title_short}{reply_count_str}\r\n".encode('utf-8'))
                self.chan.send(b'\r\n')  # タイトル一覧の最後に空行
                current_index = len(articles)  # 末尾マーカーへ
                display_current_article_header()
                self.just_displayed_header_from_tail_h = False

            elif key_input == "c":  # シグオペ変更
                self.edit_board_operators()
                display_current_article_header()
                self.just_displayed_header_from_tail_h = False

            elif key_input == "g":  # シグ看板編集
                self.edit_kanban()
                self.just_displayed_header_from_tail_h = False
                continue

            elif key_input == "u":
                self.edit_board_userlist()
                display_current_article_header()
                self.just_displayed_header_from_tail_h = False
                continue

            elif key_input == "r":  # 連続読み
                if not articles:
                    self.chan.send(b'\a')
                    continue
                start_idx = current_index if 0 <= current_index < len(
                    articles) else 0
                if start_idx == -1:
                    start_idx = 0

                self.chan.send(b'\r\n')
                for i in range(start_idx, len(articles)):
                    current_index = i  # 内部的にカーソルを動かす
                    display_current_article_header()  # まずヘッダ表示
                    # 本文表示 (戻るプロンプトなし)
                    self.read_article(
                        articles[i]['article_number'], show_back_prompt=False)
                    self.chan.send(b'\r\n')  # 記事間に空行
                # 連続読み終了後、末尾マーカーへ移動
                current_index = len(articles)  # 末尾マーカーへ
                display_current_article_header()
                self.just_displayed_header_from_tail_h = False

            else:
                self.chan.send(b'\a')
                self.just_displayed_header_from_tail_h = False

    def edit_kanban(self):
        """看板編集"""
        if not self.current_board:  # 念の為
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        board_id_pk = self.current_board['id']

        # 権限チェック
        can_edit = False
        if self.userlevel >= 5:
            can_edit = True
        else:
            try:
                operator_ids_json = self.current_board['operators'] if 'operators' in self.current_board else '[]'
                operator_ids = json.loads(operator_ids_json)
                if self.user_id_pk in operator_ids:
                    can_edit = True
            except json.JSONDecodeError:
                logging.error(
                    f"掲示板ID {board_id_pk} のオペレーターリストのデコード失敗: {operator_ids_json}")
            except TypeError:
                logging.error(
                    f"掲示板ID {board_id_pk} のオペレーターリストが不正な型: {operator_ids_json}")

        if not can_edit:
            util.send_text_by_key(
                self.chan, "bbs.permission_denied_edit_kanban", self.menu_mode)
            return

        util.send_text_by_key(
            self.chan, "bbs.edit_kanban_header", self.menu_mode)
        current_body = self.current_board['kanban_body'] if 'kanban_body' in self.current_board else ''

        # 看板本体
        self.chan.send(b'\r\n')
        util.send_text_by_key(
            self.chan, "bbs.current_kanban_body_prompt", self.menu_mode)
        if current_body:
            processed_current_body = current_body.replace(
                '\r\n', '\n').replace('\n', '\r\n')
            self.chan.send(processed_current_body.encode('utf-8'))
            if not processed_current_body.endswith('\r\n'):
                self.chan.send(b'\r\n')
        util.send_text_by_key(
            self.chan, "bbs.new_kanban_body_prompt", self.menu_mode)
        body_lines = []
        while True:
            line = self.chan.process_input()
            if line is None:
                return  # 切断
            if line == '^':
                break
            body_lines.append(line)
        new_body = '\r\n'.join(body_lines)
        if not new_body.strip() and not body_lines:  # 何も入力されず^だけの場合
            new_body = current_body

        # 確認と保存
        self.chan.send(b'New Body:\r\n')
        # 本文が空でも改行は入れる
        self.chan.send(new_body.encode('utf-8') +
                       (b'\r\n' if new_body else b''))
        util.send_text_by_key(
            self.chan, "bbs.confirm_save_kanban_yn", self.menu_mode, add_newline=False)
        confirm = self.chan.process_input()

        if confirm is None or confirm.strip().lower() != 'y':
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            return

        if database.update_board_kanban(board_id_pk, new_body):
            util.send_text_by_key(
                self.chan, "bbs.kanban_save_success", self.menu_mode)
            updated_board_info = self.board_manager.get_board_info(
                self.current_board['shortcut_id'])
            if updated_board_info:
                self.current_board = updated_board_info
            else:
                logging.error(
                    f"看板更新後、掲示板情報 {self.current_board['shortcut_id']} の再取得に失敗。")
            self.chan.send(b'\r\n')
            self._display_kanban()  # 更新された看板を即時表示
            util.send_text_by_key(  # 記事一覧ヘッダを再表示
                self.chan, "bbs.article_list_header", self.menu_mode)
        else:
            logging.error(
                f"edit_kanban: sqlite_tools.update_board_kanban returned False. Kanban save failed.")
            util.send_text_by_key(
                self.chan, "bbs.kanban_save_failed", self.menu_mode)

    def edit_board_operators(self):
        """現在の掲示板のオペレータの編集"""
        if not self.current_board:  # 念の為
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        board_id_pk = self.current_board['id']

        current_operator_ids = []
        try:
            # self.current_board['operators'] はJSON文字列であることを期待
            current_operator_ids_json = self.current_board[
                'operators'] if 'operators' in self.current_board else '[]'
            current_operator_ids = json.loads(current_operator_ids_json)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logging.warning(
                f"掲示板ID {board_id_pk} のオペレーターリストの読み込み/デコードに失敗: {e} (operators: {self.current_board['operators'] if 'operators' in self.current_board else 'N/A'})")
            # フォールバックとして空リスト扱い

        # 権限チェック:lv5(Sysop)
        can_edit = self.userlevel >= 5
        if not can_edit:
            util.send_text_by_key(
                self.chan, "bbs.permission_denied_edit_operators", self.menu_mode)
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            return

        # 編集画面表示
        util.send_text_by_key(
            self.chan, "bbs.edit_operators_header", self.menu_mode)

        if current_operator_ids:
            operator_names = [database.get_user_name_from_user_id(
                uid) or f"(ID:{uid})" for uid in current_operator_ids]
            util.send_text_by_key(
                self.chan, "bbs.current_operators_list", self.menu_mode, operators_list_str=", ".join(operator_names))
        else:
            util.send_text_by_key(
                self.chan, "bbs.no_operators_assigned", self.menu_mode)

        util.send_text_by_key(
            self.chan, "bbs.confirm_edit_operators_yn", self.menu_mode, add_newline=False)
        confirm_edit = self.chan.process_input()
        if confirm_edit is None or confirm_edit.strip().lower() != 'y':
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            return

        util.send_text_by_key(
            self.chan, "bbs.prompt_new_operators", self.menu_mode, add_newline=False)
        new_operators_input_str = self.chan.process_input()
        if new_operators_input_str is None:
            return  # 切断
        if not new_operators_input_str.strip():  # からはキャンセル
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            return

        new_operator_names = [
            name.strip() for name in new_operators_input_str.split(',')if name.strip()]
        new_operator_ids = []
        valid_input = True
        for name in new_operator_names:
            user_id = database.get_user_id_from_user_name(name)
            if user_id is None:
                util.send_text_by_key(
                    self.chan, "bbs.operator_user_not_found", self.menu_mode, username=name)
                valid_input = False
                break
            new_operator_ids.append(user_id)

        if not valid_input:
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            return  # ユーザが見つからず処理中断

        # 重複削除
        new_operator_ids_unique = sorted(
            list(set(new_operator_ids)), key=new_operator_ids.index)

        new_operator_names_display = [database.get_user_name_from_user_id(
            uid) or f"(ID:{uid})" for uid in new_operator_ids_unique]

        util.send_text_by_key(
            self.chan, "common_messages.confirm_yn", self.menu_mode, add_newline=False)  # 確認
        self.chan.send(
            f" (New_Operators: {', '.join(new_operator_names_display) if new_operator_names_display else 'なし'}): ".encode('utf-8'))

        final_confirm = self.chan.process_input()
        if final_confirm is None or final_confirm.strip().lower() != 'y':
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            return

        new_operators_json = json.dumps(new_operator_ids_unique)
        if database.update_board_operators(board_id_pk, new_operators_json):
            util.send_text_by_key(
                self.chan, "bbs.operators_updated_success", self.menu_mode)
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            # 即時反映
            updated_board_info = self.board_manager.get_board_info(
                self.current_board['shortcut_id'])
            if updated_board_info:
                self.current_board = updated_board_info
            else:
                logging.error(
                    f"オペレータ更新後掲示板情報 {self.current_board['shortcut_id']} を取得できません")
        else:
            util.send_text_by_key(
                self.chan, "common_messages.db_update_error", self.menu_mode
            )

    def edit_board_userlist(self):
        """
        現在の掲示板のユーザーパーミッションリスト（ユーザー名とallow/deny）を編集する。
        ユーザーはユーザー名のみを入力し、ボードタイプによってallow/denyが自動設定される。
        """
        if not self.current_board:
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        board_id_pk = self.current_board['id']
        board_default_permission = self.current_board[
            'default_permission'] if 'default_permission' in self.current_board.keys() else 'unknown'
        # 権限チェック
        can_edit = False
        if self.userlevel >= 5:
            can_edit = True
        else:
            try:
                operator_ids_json = self.current_board['operators'] if 'operators' in self.current_board else '[]'
                operator_ids = json.loads(operator_ids_json)
                if self.user_id_pk in operator_ids:
                    can_edit = True
            except (json.JSONDecodeError, TypeError) as e:
                logging.error(f"掲示板ID {board_id_pk} のオペレーターリストのデコードに失敗: {e}")

        if not can_edit:  # 権限がない場合
            util.send_text_by_key(
                self.chan, "bbs.permission_denied_edit_userlist", self.menu_mode)
            return

        # ボードのパーミッションに応じたヘッダを取得
        header_info_key = f"bbs.edit_userlist_header_info_{board_default_permission.lower()}"
        if not util.get_text_by_key(header_info_key, self.menu_mode):  # 対応するものがない場合
            header_info_key = "bbs.edit_userlist_header_info_unknown"

        util.send_text_by_key(
            self.chan, "bbs.edit_userlist_header", self.menu_mode)
        util.send_text_by_key(
            self.chan, header_info_key, self.menu_mode, board_permission_type=board_default_permission)

        # 現在のユーザリストを表示
        current_permissions_db = database.get_board_permissions(board_id_pk)

        registered_permissions = []
        if current_permissions_db:
            # ユーザーIDのリストを作成し、一度のクエリでユーザー名を取得
            user_ids_in_list = [perm['user_id']
                                for perm in current_permissions_db]
            id_to_name_map = database.get_user_names_from_user_ids(
                user_ids_in_list)

            for perm_entry in current_permissions_db:
                user_id_str = perm_entry.get('user_id')
                user_id_int = int(user_id_str) if user_id_str else -1
                user_name = id_to_name_map.get(user_id_int)
                access_level = perm_entry.get('access_level', "unknown")

                if user_name:
                    registered_permissions.append(
                        (user_name, access_level))
                else:
                    logging.warning(
                        f"掲示板 {board_id_pk} のパーミッションリストに不明なユーザID {user_id_str} (access_level: {access_level}) が含まれています。")

        if registered_permissions:
            util.send_text_by_key(
                self.chan, "bbs.current_userlist_header", self.menu_mode,
            )
            for name, level in sorted(list(set(registered_permissions))):
                self.chan.send(f" - {name}: {level}\r\n".encode('utf-8'))
            self.chan.send(b'\r\n')
        else:
            util.send_text_by_key(
                self.chan, "bbs.no_users_in_list", self.menu_mode)

        util.send_text_by_key(
            self.chan, "bbs.confirm_edit_userlist_yn", self.menu_mode)
        confirm_edit = self.chan.process_input()
        if confirm_edit is None or confirm_edit.strip().lower() != 'y':
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            return

        # ユーザリストを更新
        util.send_text_by_key(
            self.chan, "bbs.prompt_new_userlist", self.menu_mode, add_newline=False)
        new_userlist_input_str = self.chan.process_input()

        if new_userlist_input_str is None:
            return  # 切断

        parsed_permissions_to_add = []  # user_id_str,access_level_strのタプル
        if not new_userlist_input_str.strip():  # 空入力はクリア
            pass
        else:

            # usere1,user2のような形式を期待
            input_user_names = [
                name.strip() for name in new_userlist_input_str.split(',')if name.strip()]

            valid_input = True
            for user_name_input in input_user_names:
                # ユーザネーム画からならスキップ",,"って感じの入力の対策
                if not user_name_input:
                    continue

                # board_default_permissionによってアクセスレベルを決定
                access_level_to_set = ""
                if board_default_permission == "open":
                    access_level_to_set = "deny"
                elif board_default_permission == "close":
                    access_level_to_set = "allow"
                elif board_default_permission == "readonly":
                    access_level_to_set = "allow"
                else:
                    access_level_to_set = "allow"
                    logging.info(
                        f"掲示板タイプ {board_default_permission} に対応するアクセスレベルを決定できませんでした。ユーザ {user_name_input} のアクセスレベルは'allow'に設定されました。")
                user_name_upper = user_name_input.upper()
                target_user_id_pk_int = database.get_user_id_from_user_name(
                    user_name_upper)
                if target_user_id_pk_int is None:
                    util.send_text_by_key(
                        self.chan, "bbs.user_not_found_in_list", self.menu_mode, username=user_name_upper)
                    valid_input = False
                    break
                parsed_permissions_to_add.append(
                    (str(target_user_id_pk_int), access_level_to_set))

            if not valid_input:
                return

        # DB更新
        if not database.delete_board_permissions_by_board_id(board_id_pk):
            util.send_text_by_key(
                self.chan, "common_messages.db_update_error", self.menu_mode)
            logging.error(f"掲示板ID {board_id_pk} のユーザリストを削除できませんでした。")
            return

        if parsed_permissions_to_add:
            # 重複を除いてソート
            unique_sorted_permissions = sorted(
                list(set(parsed_permissions_to_add)), key=lambda x: x[0])
            for user_id_to_add_str, access_level_to_add in unique_sorted_permissions:
                if not database.add_board_permission(board_id_pk, user_id_to_add_str, access_level_to_add):
                    util.send_text_by_key(
                        self.chan, "common_messages.db_update_error", self.menu_mode)
                    logging.error(
                        f"掲示板ID {board_id_pk} のパーミッションリストにユーザID {user_id_to_add_str} (level {access_level_to_add})を追加できませんでした。")
                    return

        util.send_text_by_key(
            self.chan, "bbs.userlist_updated_success", self.menu_mode)

    def read_article(self, article_number, show_header=True, show_back_prompt=True):
        """記事を読む"""
        if not self.current_board:
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        board_id_pk = self.current_board['id']

        article = self.article_manager.get_article_by_number(
            board_id_pk, article_number, include_deleted=True)  # 読むときは削除済みでも取得する

        if not article:
            util.send_text_by_key(
                self.chan, "bbs.article_not_found", self.menu_mode)
            return

        if show_header:
            # 削除済み記事の場合、ヘッダにマークをつける
            deleted_mark = "*" if article['is_deleted'] == 1 else ""
            display_title = article['title'] if article['title'] else "(No Title)"

            if article['is_deleted'] == 1:
                can_see_deleted_title_header = False
                if self.userlevel >= 5:  # シスオペ
                    can_see_deleted_title_header = True
                else:
                    try:
                        if int(article['user_id']) == self.user_id_pk:  # 投稿者本人
                            can_see_deleted_title_header = True
                    except ValueError:
                        pass
                if not can_see_deleted_title_header:
                    display_title = ""  # 一般ユーザーには表示しない

            util.send_text_by_key(
                self.chan, "bbs.article_header", self.menu_mode,
                article_number=article['article_number'],
                title=f"{deleted_mark}{display_title}",  # 削除マークと調整済みタイトル
            )
            self.chan.send(b'\r\n')

        # 削除済み記事の本文表示に関する権限チェック
        if not self.permission_manager.can_view_deleted_article_content(article, self.user_id_pk, self.userlevel):
            # 権限がない場合はメッセージを表示して本文表示をスキップ
            util.send_text_by_key(
                self.chan, "bbs.article_deleted_body", self.menu_mode)
            # show_back_prompt が True の場合でも、この後のプロンプトループは実行されない
            return

        # (T/O) の場合は本文を表示しない
        if article['body'] != '(T/O)':
            body_to_send = article['body'].replace(
                '\r\n', '\n').replace('\n', '\r\n')
            # textwrap を使って本文を折り返す
            wrapped_body_lines = textwrap.wrap(
                body_to_send, width=78, replace_whitespace=False, drop_whitespace=False)
            for line in wrapped_body_lines:
                self.chan.send(line.encode('utf-8') + b'\r\n')

        # --- 添付ファイルダウンロード確認処理 ---
        if article and article.get('attachment_filename') and article.get('attachment_originalname'):
            file_size_bytes = article.get('attachment_size')
            formatted_size = util.format_file_size(
                file_size_bytes) if file_size_bytes is not None else "不明"

            util.send_text_by_key(
                self.chan,
                "bbs.attachment_info_with_size",
                self.menu_mode,
                original_filename=article['attachment_originalname'],
                formatted_size=formatted_size
            )
            util.send_text_by_key(
                self.chan, "bbs.attachment_download_prompt", self.menu_mode, add_newline=False)

            confirm = None
            try:
                self.chan.settimeout(25.0)
                confirm = self.chan.process_input()
            except socket.timeout:
                # タイムアウトしたらNを入力したことにする
                self.chan.send(b'N\r\n')
                confirm = 'n'
            finally:
                self.chan.settimeout(None)

            if confirm and confirm.strip().lower() == 'y':
                webapp_config = util.app_config.get('webapp', {})
                origin = webapp_config.get('ORIGIN', '')
                download_url = f"{origin}/attachments/{article['attachment_filename']}"

                download_sequence = f"\x1b_GRBBS_DOWNLOAD;{download_url}\x1b\\"
                self.chan.send(download_sequence.encode('utf-8'))
                util.send_text_by_key(
                    self.chan, "bbs.attachment_download_starting", self.menu_mode)

        # 本文表示後、改行を1行だけ入れる
        self.chan.send(b'\r\n')

        # --- スレッド形式の場合、返信を表示 ---
        board_type = self.current_board.get('board_type', 'simple')
        is_parent_article = article['parent_article_id'] is None

        if board_type == 'thread' and is_parent_article:
            replies = self.article_manager.get_replies(article['id'])
            if replies:
                util.send_text_by_key(
                    self.chan, "bbs.read_replies_header", self.menu_mode,
                    parent_article_number=article['article_number']
                )
                for i, reply in enumerate(replies):
                    # 返信の表示
                    reply_sender_name = ""
                    try:
                        user_id_int = int(reply['user_id'])
                        user_name = database.get_user_name_from_user_id(
                            user_id_int)
                        reply_sender_name = user_name if user_name else "(Unknown)"
                    except (ValueError, TypeError):
                        reply_sender_name = str(reply['user_id'])

                    try:
                        created_at_str = datetime.datetime.fromtimestamp(
                            reply['created_at']).strftime("%Y/%m/%d %H:%M:%S")
                    except:
                        created_at_str = "----/--/-- --:--:--"

                    # 返信本文の折り返し
                    reply_body_wrapped = textwrap.wrap(
                        reply['body'].replace('\r\n', '\n'),
                        width=78, replace_whitespace=False, drop_whitespace=False
                    )

                    # 返信ヘッダ
                    self.chan.send(
                        f"{i+1}: {reply_sender_name} ({created_at_str})\r\n".encode('utf-8'))
                    # 返信本文
                    for line in reply_body_wrapped:
                        self.chan.send(f"  {line}\r\n".encode('utf-8'))
                    self.chan.send(b'\r\n')  # 返信ごとの空行

        # --- スレッド形式で、かつ親記事を読んでいる場合、返信を促す ---
        if board_type == 'thread' and is_parent_article and show_back_prompt:
            util.send_text_by_key(
                self.chan, "bbs.reply_prompt", self.menu_mode, add_newline=False)
            reply_choice = self.chan.process_input()
            if reply_choice and reply_choice.strip().lower() == 'r':
                self._reply_to_article(article)
                # 返信後は記事一覧に戻るため、ここで処理を終了
                # 注意: 現状では返信内容は即時反映されません。一度掲示板を抜けて入り直すと表示されます。
                #      この動作は今後のステップで改善される可能性があります。
                return

        # 記事本文表示後、既読として記録
        self._update_read_progress(board_id_pk, article_number)

    def _reply_to_article(self, parent_article):
        """記事に返信する"""
        if not self.permission_manager.can_write_to_board(self.current_board, self.user_id_pk, self.userlevel):
            util.send_text_by_key(
                self.chan, "bbs.permission_denied_write_article", self.menu_mode)
            return

        # --- リプライ上限チェック ---
        max_replies = self.current_board.get('max_replies', 0)
        if max_replies > 0:
            # 親記事のIDは parent_article['id']
            current_reply_count = self.article_manager.get_reply_count(
                parent_article['id'])
            if current_reply_count >= max_replies:
                util.send_text_by_key(
                    self.chan, "bbs.reply_limit_reached", self.menu_mode)
                return
        util.send_text_by_key(
            self.chan, "bbs.reply_header", self.menu_mode,
            parent_id=parent_article['article_number']
        )

        limits_config = util.app_config.get('limits', {})
        body_max_len = limits_config.get('bbs_body_max_length', 8192)
        util.send_text_by_key(
            self.chan, "bbs.post_body", self.menu_mode, max_len=body_max_len)

        body_lines = []
        while True:
            line = self.chan.process_input()
            if line is None:
                return  # 切断
            if line == '^':
                break
            body_lines.append(line)
        body = '\r\n'.join(body_lines)

        if len(body) > body_max_len:
            body = body[:body_max_len]
            util.send_text_by_key(
                self.chan, "bbs.body_truncated", self.menu_mode, max_len=body_max_len)

        if not body.strip():
            util.send_text_by_key(self.chan, "bbs.post_cancel", self.menu_mode)
            return

        util.send_text_by_key(self.chan, "bbs.confirm_post_yn",
                              self.menu_mode, add_newline=False)
        confirm = self.chan.process_input()
        if confirm is None or confirm.strip().lower() != 'y':
            util.send_text_by_key(self.chan, "bbs.post_cancel", self.menu_mode)
            return

        # 投稿者識別子を決定
        user_identifier = util.get_display_name(
            self.login_id, self.ip_address) if self.login_id.upper() == 'GUEST' else self.user_id_pk

        # 返信をDBに保存
        # 返信はタイトルなし(None)、親記事IDを指定してcreate_articleを呼び出す
        if self.article_manager.create_article(self.current_board['id'], user_identifier, None, body, ip_address=self.ip_address, parent_article_id=parent_article['id']):
            util.send_text_by_key(
                self.chan, "bbs.post_success", self.menu_mode)
        else:
            util.send_text_by_key(self.chan, "bbs.post_failed", self.menu_mode)

    def write_article(self):
        """記事を新規作成"""
        if not self.current_board:
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        board_id_pk = self.current_board['id']  # sqlite3のオブジェクトを取得
        client_ip = None
        try:
            client_ip = self.chan.getpeername(
            )[0] if self.chan.getpeername() else None
        except Exception:  # getpeername が失敗するケースも考慮
            client_ip = None

        if not self.permission_manager.can_write_to_board(self.current_board, self.user_id_pk, self.userlevel):
            util.send_text_by_key(
                self.chan, "bbs.permission_denied_write_article", self.menu_mode)
            return 'failed'

        # --- スレッド/記事数 上限チェック ---
        # 'max_threads' はスレッド形式ではスレッド数、シンプル形式では記事数の上限として扱う
        max_threads = self.current_board.get('max_threads', 0)
        if max_threads > 0:
            # get_thread_countは親記事(parent_article_id IS NULL)の数を数える。
            # シンプル形式では全記事が親記事扱いなので、これで記事総数をチェックできる。
            current_thread_count = self.article_manager.get_thread_count(
                board_id_pk)
            if current_thread_count >= max_threads:
                util.send_text_by_key(
                    self.chan, "bbs.thread_limit_reached", self.menu_mode)
                return 'failed'

        # ファイル添付が許可されているかチェック
        allow_attachments = self.current_board.get('allow_attachments', 0) == 1

        try:
            util.send_text_by_key(self.chan, "bbs.post_header", self.menu_mode)

            limits_config = util.app_config.get('limits', {})
            title_max_len = limits_config.get('bbs_title_max_length', 100)

            util.send_text_by_key(self.chan, "bbs.post_subject", self.menu_mode,
                                  max_len=title_max_len, add_newline=False)
            title = self.chan.process_input()
            if title is None:
                return 'cancelled'  # 切断
            title = title.strip()

            if len(title) > title_max_len:
                title = title[:title_max_len]
                util.send_text_by_key(
                    self.chan, "bbs.title_truncated", self.menu_mode, max_len=title_max_len)

            board_type = self.current_board.get('board_type', 'simple')
            if not title and board_type == 'thread':
                # スレッド形式の場合、新規投稿（スレッド作成）にはタイトルが必須
                util.send_text_by_key(
                    self.chan, "bbs.title_required", self.menu_mode)
                return 'failed'

            body_max_len = limits_config.get('bbs_body_max_length', 8192)
            util.send_text_by_key(
                self.chan, "bbs.post_body", self.menu_mode, max_len=body_max_len)
            body_lines = []
            while True:
                line = self.chan.process_input()
                if line is None:
                    return 'cancelled'  # 切断
                if line == '^':
                    break
                body_lines.append(line)
            body = '\r\n'.join(body_lines)

            if len(body) > body_max_len:
                body = body[:body_max_len]
                util.send_text_by_key(
                    self.chan, "bbs.body_truncated", self.menu_mode, max_len=body_max_len)

            if not body.strip() and not title.strip():
                util.send_text_by_key(
                    self.chan, "bbs.post_cancel", self.menu_mode)
                return 'cancelled'
            elif not body.strip():
                body = '(T/O)'

            util.send_text_by_key(self.chan, "bbs.confirm_post_yn",
                                  self.menu_mode, add_newline=False)
            confirm = self.chan.process_input()
            if confirm is None or confirm.strip().lower() != 'y':
                util.send_text_by_key(
                    self.chan, "bbs.post_cancel", self.menu_mode)
                return 'cancelled'

            # 投稿者識別子を決定
            user_identifier = None
            if self.login_id.upper() == 'GUEST':
                # ゲストの場合、IPからハッシュ付きの表示名を生成
                # util.get_display_name は 'GUEST(hash)' を返す
                user_identifier = util.get_display_name(
                    self.login_id, client_ip)
            else:
                # 登録ユーザーの場合、ユーザーID(数値)を使用
                user_identifier = self.user_id_pk

            # --- ファイル添付処理 ---
            attachment_filename = None
            attachment_originalname = None
            attachment_size = None

            if allow_attachments:
                util.send_text_by_key(
                    self.chan, "bbs.confirm_upload_attachment_yn", self.menu_mode, add_newline=False)
                upload_choice = self.chan.process_input()
                if upload_choice and upload_choice.strip().lower() == 'y':
                    util.send_text_by_key(
                        self.chan, "bbs.prompt_select_file", self.menu_mode)

                    # webapp.py のアップロードハンドラに現在の掲示板情報を渡す
                    if hasattr(self.chan, 'handler'):
                        self.chan.handler.current_board_for_upload = self.current_board

                    # ファイルアップロードUI表示 & 即時ダイアログ表示命令
                    self.chan.send(b'\x1b[?2033h')
                    try:
                        self.chan.settimeout(60.0)
                        self.chan.process_input()  # クライアントからの信号を待つ
                    except socket.timeout:
                        if hasattr(self.chan, 'handler'):
                            self.chan.handler.pending_attachment = {
                                'error': 'ファイル選択がタイムアウトしました。'}
                    finally:
                        self.chan.settimeout(None)

                    attachment_info = self.chan.handler.pending_attachment if hasattr(
                        self.chan, 'handler') else None

                    if attachment_info and 'error' in attachment_info:
                        error_message = attachment_info.get(
                            'error', '不明なアップロードエラーです。')
                        self.chan.send(
                            f"\r\n** エラー: {error_message} **\r\n".encode('utf-8'))
                        util.send_text_by_key(
                            self.chan, "bbs.post_cancel", self.menu_mode)
                        return 'cancelled'

                    if attachment_info:
                        attachment_filename = attachment_info.get(
                            'unique_filename')
                        attachment_originalname = attachment_info.get(
                            'original_filename')
                        attachment_size = attachment_info.get('size')

            # --- 記事をDBに保存 ---
            if self.article_manager.create_article(
                board_id_pk, user_identifier, title, body,
                ip_address=client_ip,
                attachment_filename=attachment_filename,
                attachment_originalname=attachment_originalname,
                attachment_size=attachment_size
            ):
                util.send_text_by_key(
                    self.chan, "bbs.post_success", self.menu_mode)
                return 'posted'
            else:
                util.send_text_by_key(
                    self.chan, "bbs.post_failed", self.menu_mode)
                return 'failed'

        finally:
            # 保留中の添付ファイルをクリア
            if hasattr(self.chan, 'handler'):
                self.chan.handler.pending_attachment = None
            if allow_attachments:
                # ファイルアップロードUI非表示命令
                self.chan.send(b'\x1b[?2032l')


def handle_bbs_menu(chan, login_id, display_name, menu_mode, shortcut_id, ip_address):
    """掲示板メニューのエントリーポイント"""
    handler = CommandHandler(
        chan, login_id, display_name, menu_mode, ip_address)
    if shortcut_id:
        # ショートカットIDが指定されていれば、その掲示板に直接移動
        board_data_from_db = handler.board_manager.get_board_info(shortcut_id)
        if board_data_from_db:
            handler.current_board = board_data_from_db
            if not handler.permission_manager.can_view_board(handler.current_board, handler.user_id_pk, handler.userlevel):
                util.send_text_by_key(
                    chan, "bbs.permission_denied_read_board", menu_mode)
                return
            loop_result = handler.command_loop()  # "empty_exit" or None
            if loop_result == "empty_exit":
                # 1階層戻ることを呼び出し元に伝える
                return "back_one_level"
            else:  # None (切断) の場合
                return None
        else:
            # TODO: textdata.yaml に追加
            util.send_text_by_key(
                chan, "bbs.board_not_found", menu_mode, shortcut_id=shortcut_id)
    else:
        # 指定がなければ、カテゴリ選択 or 掲示板一覧表示からの遷移
        # hierarchical_menu を使って掲示板を選択させる
        paths_config = util.app_config.get('paths', {})
        # server.py の bbs コマンド処理と合わせ、mode3用のyamlを参照する
        bbs_config_path = paths_config.get('bbs_mode3_yaml')
        logging.info(
            f"bbs_handler: Calling hierarchical_menu.handle_hierarchical_menu with path: {bbs_config_path}")
        # モバイル用の操作ボタンを表示
        chan.send(b'\x1b[?2028h')
        try:
            selected_item = hierarchical_menu.handle_hierarchical_menu(
                chan, bbs_config_path, menu_mode, menu_type="BBS", enrich_boards=True
            )
            logging.info(
                f"bbs_handler: hierarchical_menu.handle_hierarchical_menu returned: {selected_item}")
        finally:
            # メニューを抜けたら必ずボタンを非表示にする
            chan.send(b'\x1b[?2028l')

        if selected_item and selected_item.get("type") == "board":
            shortcut_id_selected = selected_item.get("id")
            # 再度 handle_bbs_menu を呼び出すか、直接 CommandHandler の処理を続ける
            # ショートカット時と同様に、IPアドレスも渡す
            return handle_bbs_menu(chan, login_id, display_name, menu_mode, shortcut_id_selected, ip_address)
        # else: 選択されなかったか、boardタイプではなかった場合。handle_hierarchical_menu内でメッセージ表示済みのはず。
        # hierarchical_menu から戻ってきた場合は、通常トップメニュー表示で問題ない想定
        return "back_to_top"
