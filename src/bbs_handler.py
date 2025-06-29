# bbs_handler.py (骨格)
import logging
import time
import sqlite_tools  # データベース操作用
import util  # 共通関数 (設定読み込み、テキスト表示など)
import ssh_input  # ユーザー入力処理
import socket
import textwrap
import datetime
import json

import hierarchical_menu

# クラスや関数は、以下の構成で定義していく
# - BoardManager: 掲示板のメタ情報管理、bbs.yaml との同期
# - ArticleManager: 記事のCRUD操作、表示
# - PermissionManager: 権限チェック、パーミッションリスト操作
# - CommandHandler: ユーザー入力に応じたコマンド処理
#     - command_loop: メインループ
#     - 各コマンドに対応する関数 (例: show_article_list, read_article, write_article, etc.)


class BoardManager:
    """掲示板のメタ情報を管理するクラス"""

    def __init__(self, dbname):
        self.dbname = dbname
        # self.load_boards_from_config() # SysOpメニューから実行する形に変更したため、初期化時は呼び出さない

    # This function is currently not called from anywhere.
    def load_boards_from_config(self):
        paths_config = util.app_config.get('paths', {})
        bbs_config_path = paths_config.get('bbs_sync_config')
        """bbs.yaml から掲示板情報を読み込み、DBと同期する"""
        bbs_config_data = util.load_yaml_file_for_shortcut(bbs_config_path)
        if not bbs_config_data or "categories" not in bbs_config_data:
            logging.error("bbs.yaml の読み込みに失敗したか、不正な形式です。")
            return False

        processed_shortcuts = set()
        boards_from_yml = []

        def _parse_items(items_list, current_category_id=None):
            for item_data in items_list:
                if item_data.get("type") == "board":
                    shortcut_id = item_data.get("id")
                    if not shortcut_id:
                        logging.warning(f"IDが未定義の掲示板項目がありました: {item_data}")
                        continue

                    # bbs.yaml の name は直接文字列
                    board_name_from_yml = item_data.get("name")
                    if board_name_from_yml is None:  # name がない場合はIDを使うなどフォールバック
                        board_name_from_yml = shortcut_id
                        logging.warning(
                            f"掲示板 {shortcut_id} の name が未定義です。IDを使用します。")

                    # bbs.yaml からは shortcut_id のみを取得。name, description はDBで管理。
                    # operators, default_permission はDBで直接管理 (sysop_menu.mkbd で初期設定)
                    # category_id, display_order も bbs.yaml で管理

                    processed_shortcuts.add(shortcut_id)
                elif item_data.get("type") == "child" and "items" in item_data:
                    _parse_items(item_data.get("items", []),
                                 item_data.get("id"))

        for category in bbs_config_data.get("categories", []):
            category_id = category.get("id")
            # カテゴリ自体の情報をDBに入れるかは別途検討
            _parse_items(category.get("items", []), category_id)

        # 現状の方針では、この関数は主に「bbs.yamlに定義されているがDBにない掲示板がないか」のチェックや、
        # 「DBには存在するがbbs.yamlのどこにも属していない掲示板がないか」のチェックになるかもしれません。
        logging.info(
            f"bbs.yamlから {len(processed_shortcuts)} 件の掲示板ショートカットIDを認識しました: {processed_shortcuts}")
        return True  # 仮

    def get_board_info(self, shortcut_id):
        """指定されたショートカットIDの掲示板情報をDBから取得する"""
        board_info = sqlite_tools.get_board_by_shortcut_id(
            self.dbname, shortcut_id)
        # sqlite3.Row を dict に変換
        return dict(board_info) if board_info else None


class ArticleManager:
    """記事のCRUD操作と表示を行うクラス"""

    def __init__(self, dbname):
        self.dbname = dbname

    def get_articles_by_board(self, board_id, include_deleted=False):
        """指定された掲示板の投稿一覧を取得する"""
        # board_idはboardsテーブルの主キー(id)
        # 投稿順（古いものが先）で取得
        return sqlite_tools.get_articles_by_board_id(self.dbname, board_id, order_by="created_at ASC, article_number ASC", include_deleted=include_deleted)

    def get_new_articles(self, board_id, last_login_timestamp):
        """指定された掲示板の、指定時刻以降の未削除記事を取得する。"""
        return sqlite_tools.get_new_articles_for_board(self.dbname, board_id, last_login_timestamp)

    def get_article_by_number(self, board_id, article_number, include_deleted=False):
        """指定された記事番号の記事を取得する"""
        # board_idはboardsテーブルの主キー(id)
        article_data = sqlite_tools.get_article_by_board_and_number(
            self.dbname, board_id, article_number, include_deleted=include_deleted)
        if article_data:
            return article_data
        return None

    def create_article(self, board_id_pk, user_id_pk, title, body, ip_address=None):
        """
        記事を新規作成する
        board_id_pkはboardsテーブルの主キー
        user_id_pkはusersテーブルの主キー
        戻り値は作成された記事のID、失敗したらNone
        """
        conn = None
        try:
            # 次の記事番号取得
            next_article_number = sqlite_tools.get_next_article_number(
                self.dbname, board_id_pk)
            if next_article_number is None:
                logging.error(
                    f"記事の作成に失敗しました(BoardID:{board_id_pk}, UserID:{user_id_pk}): 次の記事番号の取得に失敗")
                return None

            # 記事を挿入
            current_timestamp = int(time.time())
            article_id = sqlite_tools.insert_article(
                self.dbname, board_id_pk, next_article_number, user_id_pk, title, body, current_timestamp, ip_address
            )

            if article_id is not None:
                # 掲示板の最終投稿日時を更新
                sqlite_tools.update_board_last_posted_at(
                    self.dbname, board_id_pk, current_timestamp)
                logging.info(
                    f"記事を作成しました(BoardID:{board_id_pk}, ArticleNo:{next_article_number}, UserID:{user_id_pk}, ArticleDBID:{article_id})")
                return article_id
            else:
                return None

        except Exception as e:
            logging.error(
                f"記事の作成に失敗しました(BoardID:{board_id_pk}, UserID:{user_id_pk}): {e}")
            return None
        finally:
            if conn:
                conn.close()

    def update_article(self, article_id, title, body):
        """記事を更新する（主に看板用）"""
        # TODO: 実装
        pass

    def toggle_delete_article(self, article_id):
        """記事の削除フラグをトグルする(論理削除)"""
        return sqlite_tools.toggle_article_deleted_status(self.dbname, article_id)

    def search_articles(self, board_id, keyword, search_body=False):
        # TODO: 検索機能の実装時に include_deleted を考慮する
        """記事を検索する（タイトルまたは本文）"""
        # TODO: 実装
        pass


class PermissionManager:
    """権限管理を行うクラス"""

    def __init__(self, dbname):
        self.dbname = dbname

    def check_permission(self, board_id, user_id, action):
        """
        指定されたアクションの実行権限があるかチェックする
        将来的に詳細な権限管理に使用する予定。
        現状はcan_view_board,can_write_to_boardを使用
        """
        return True

    def can_view_board(self, board_info, user_id_pk, user_level):
        """指定された掲示板の閲覧権限があるかチェックする"""
        if user_level >= 5:
            return True

        board_id_pk = board_info["id"]
        default_perm = board_info['default_permission'] if 'default_permission' in board_info.keys(
        ) else 'unknown'
        user_specific_perm = sqlite_tools.get_user_permission_for_board(
            self.dbname, board_id_pk, str(user_id_pk))

        if user_specific_perm == "deny":  # 明示的な拒否はNG
            return False

        if default_perm == "open":
            return True  # denyじゃないならOK
        elif default_perm == "closed":
            return user_specific_perm == "allow"  # allowされてればOK
        elif default_perm == "readonly":
            return True  # deny#じゃないなら閲覧OK
        else:  # unknownなどなど
            logging.warning(
                f"掲示板ID {board_id_pk} のdefault_permissionが不明です: {default_perm}")
            return False  # 不明だとNG

    def can_write_to_board(self, board_info, user_id_pk, user_level):
        """指定された掲示板の書き込み権限があるかチェックする"""
        if user_level >= 5:
            return True

        board_id_pk = board_info["id"]
        default_perm = board_info['default_permission'] if 'default_permission' in board_info.keys(
        ) else 'unknown'
        user_specific_perm = sqlite_tools.get_user_permission_for_board(
            self.dbname, board_id_pk, str(user_id_pk))

        # シグオペかをチェック
        try:
            operator_ids_json = board_info['operators'] if 'operators' in board_info.keys(
            ) else '[]'
            operator_ids = json.loads(operator_ids_json)
            if user_id_pk in operator_ids:
                return True  # シグオペならOK
        except (json.JSONDecodeError, TypeError):
            pass  # エラー対策

        if default_perm == "deny":  # 明示的な拒否はNG
            return False

        if default_perm == "open":
            return True  # denyじゃないならOK
        elif default_perm == "closed" or default_perm == "readonly":  # closed, readonlyは同じロジック
            return user_specific_perm == "allow"  # allowされてればOK
        else:  # unknownなどなど
            logging.warning(
                f"掲示板ID {board_id_pk} のdefault_permissionが不明です: {default_perm}")
            return False  # 不明だとNG

    def get_permission_list(self, board_id):
        """指定された掲示板のパーミッションリストを取得する"""
        # TODO: 実装
        pass

    def update_permission_list(self, board_id, user_id, permission_type):
        """指定された掲示板のパーミッションリストを更新する"""
        # permission_type: "allow" (ホワイトリスト), "deny" (ブラックリスト)
        # TODO: 実装
        pass


class CommandHandler:
    """ユーザー入力に応じたコマンド処理を行うクラス"""

    def __init__(self, chan, dbname, login_id, menu_mode):
        self.chan = chan
        self.dbname = dbname
        self.login_id = login_id
        self.menu_mode = menu_mode
        self.board_manager = BoardManager(dbname)
        self.article_manager = ArticleManager(dbname)
        self.permission_manager = PermissionManager(dbname)
        self.current_board = None  # 現在の掲示板
        self.just_displayed_header_from_tail_h = False  # 読み戻り時の状態フラグ
        self.user_id_pk = sqlite_tools.get_user_id_from_user_name(
            dbname, login_id)
        self.userlevel = sqlite_tools.get_user_level_from_user_id(
            dbname, self.user_id_pk)
        # ユーザーの最終ログイン時刻を初期化時に取得
        user_data = sqlite_tools.get_user_auth_info(dbname, login_id)
        self.last_login_timestamp = 0

        if user_data:
            if 'lastlogin' in user_data.keys():  # キーの存在確認を .keys() に対して行う
                if user_data['lastlogin'] is not None:  # None でないことを確認
                    try:
                        # lastlogin は INTEGER 型のはずなので、そのまま代入
                        self.last_login_timestamp = int(user_data['lastlogin'])
                    except (ValueError, TypeError):
                        logging.warning(
                            f"CommandHandler.__init__: lastlogin field for user {login_id} is not a valid integer: {user_data['lastlogin']}. Defaulting to 0.")
                        self.last_login_timestamp = 0  # 変換失敗時は0
                # else: user_data['lastlogin'] が None の場合は self.last_login_timestamp はデフォルトの 0 のまま
            else:
                logging.warning(
                    f"CommandHandler.__init__: 'lastlogin' key NOT FOUND in user_data.keys() for {login_id}. Available keys: {user_data.keys() if user_data else 'user_data is None'}")
        else:
            logging.warning(
                f"CommandHandler.__init__: user_data is None for {login_id}.")

        self.user_read_progress_map = sqlite_tools.get_user_read_progress(
            self.dbname, self.user_id_pk)
        # logging.debug(f"既読記事番号の読み込み LoginID:{login_id}, {self.user_read_progress_map}")

    def _display_kanban(self):
        """看板を表示する"""
        if not self.current_board:
            return

        kanban_body = self.current_board.get('kanban_body', '')

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
            sqlite_tools.update_user_read_progress(
                self.dbname, self.user_id_pk, self.user_read_progress_map)
            logging.debug(
                f"既読記事番号の更新 BoardID:{board_id_pk}, ArticleNo:{article_number}, LoginID:{self.login_id}")

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
        while True:
            # メニュー表示
            util.send_text_by_key(
                self.chan, "prompt.bbs_wrdate", self.menu_mode, add_newline=False
            )
            choice = ssh_input.process_input(self.chan)
            if choice is None:
                return  # 切断
            choice = choice.lower().strip()

            if choice == 'w':
                self.write_article()
            elif choice == 'r':
                self.show_article_list(
                    last_login_timestamp=self.last_login_timestamp)
            elif choice == 'e' or choice == '':
                return "empty_exit"
            else:
                util.send_text_by_key(
                    self.chan, "common_messages.invalid_command", self.menu_mode)

    def show_article_list(self, display_initial_header=True, last_login_timestamp=0):
        """記事一覧を表示"""

        # 掲示板閲覧権限チェック(念の為)
        if not self.permission_manager.can_view_board(self.current_board, self.user_id_pk, self.userlevel):
            util.send_text_by_key(
                self.chan, "bbs.permission_denied_read_board", self.menu_mode)
            return

        board_id_pk = self.current_board['id']
        articles = []  # この行で articles を初期化
        current_index = 0
        article_id_width = 5  # 記事番号桁数

        # 常に削除済み記事も取得するが、表示方法は権限によって変える
        # show_deleted_articles 変数はここでは直接使わない

        def reload_articles_display(keep_index=True):
            nonlocal articles, current_index, article_id_width, display_initial_header, last_login_timestamp
            current_article_id_on_reload = None

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

                # 削除済みマーク
                # is_deleted は 0 or 1
                deleted_mark = "*" if article['is_deleted'] == 1 else ""
                user_name = sqlite_tools.get_user_name_from_user_id(
                    self.dbname, article['user_id'])
                user_name_short = textwrap.shorten(
                    user_name if user_name else "(Unknown)", width=7, placeholder="..")
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
                    can_see_deleted_title = False
                    if self.userlevel >= 5:  # シスオペ
                        can_see_deleted_title = True
                    else:
                        try:
                            if int(article['user_id']) == self.user_id_pk:  # 投稿者本人
                                can_see_deleted_title = True
                        except ValueError:
                            pass  # ID変換失敗時は見せない
                    if can_see_deleted_title:
                        title_short = textwrap.shorten(
                            title, width=36, placeholder="...")  # "* " を考慮して少し短く
                    else:
                        title_short = ""  # 一般ユーザーには表示しない
                else:
                    title_short = textwrap.shorten(
                        title, width=38, placeholder="...")
                # ユーザー名の後のスペースを調整
                spaces_before_title_field = "  " if deleted_mark else "   "
                # 左寄せ、指定幅
                article_no_str = f"{article['article_number']:0{article_id_width}d}"

                self.chan.send(
                    f"{article_no_str}  {r_date_str} {r_time_str} {user_name_short:<7}{spaces_before_title_field}{deleted_mark}{title_short}\r\n".encode('utf-8'))
            else:
                util.send_text_by_key(
                    self.chan, "bbs.no_article", self.menu_mode)

        reload_articles_display(keep_index=False)
        self.just_displayed_header_from_tail_h = False  # フラグをリセット

        while True:
            util.send_text_by_key(
                self.chan, "bbs.article_list_prompt", self.menu_mode, add_newline=False)
            key_input = None
            decoded_char_for_check = None  # 番号ジャンプ用数字判定
            try:
                data = self.chan.recv(1)  # 1バイトずつデータを受信
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
                search_term_raw = ssh_input.process_input(self.chan)

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
                search_term_raw = ssh_input.process_input(self.chan)

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
            elif key_input == '\x04' or key_input == "ENTER":
                if articles and 0 <= current_index < len(articles):
                    display_current_article_header()  # 1. 1行ヘッダを表示 (末尾に改行を含む)
                    self.chan.send(b'\r\n')          # 2. 1行ヘッダと本文の間に空行を追加
                    self.read_article(
                        articles[current_index]['article_number'],
                        show_header=False,
                        show_back_prompt=False
                    )  # 3. 本文を表示 (このメソッドの末尾で改行が1つ入る)
                    # 4. 記事一覧の全体ヘッダは再表示せず、現在のカーソル位置のヘッダ表示とループ末尾のプロンプト表示に任せる
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
                # DBのarticles.user_id (TEXT型)
                article_user_id_from_db = article_to_delete['user_id']

                # 権限チェック:シスオペ(LV5)または記事の投稿者
                is_owner = False
                try:
                    # articles.user_id は TEXT 型だが、数値のIDが格納されている想定なのでintに変換して比較
                    # self.user_id_pk は users.id (INTEGER)
                    is_owner = (int(article_user_id_from_db)
                                == self.user_id_pk)
                except ValueError:
                    logging.warning(
                        f"記事(ID:{article_id_pk})の投稿者ID({article_user_id_from_db})を数値に変換できませんでした。")
                if self.userlevel >= 5 or is_owner:
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
                            f"記事の削除/復旧が失敗しました。:(記事id {article_id_pk},記事番号 {article_number},投稿者ID {article_user_id_from_db}"
                        )
                        display_current_article_header()  # 失敗したら現在の行を再表示
                else:
                    # 権限なし
                    self.chan.send(b'\a')  # 権限なし
                    util.send_text_by_key(
                        self.chan, "bbs.permission_denied_delete", self.menu_mode)
                    display_current_article_header()  # 権限なしメッセージの後、現在の行を再表示
                self.just_displayed_header_from_tail_h = False

            elif key_input == "w":
                self.write_article()
                reload_articles_display(keep_index=False)  # 新規投稿後は先頭から再表示
                self.just_displayed_header_from_tail_h = False

            elif key_input == "s":  # シグ看板表示
                # 看板表示前に現在の記事ヘッダを消す必要はない（看板は別領域に表示される想定）
                self._display_kanban()
                display_current_article_header()  # 看板表示後はリストモードに戻る
                self.just_displayed_header_from_tail_h = False

            elif key_input == "e" or key_input == '\x1b':  # ESCでも終了
                return  # command_loop に戻る

            elif key_input == "?":
                self.chan.send(b'\r\n')
                util.send_text_by_key(
                    self.chan, "bbs.article_list_help", self.menu_mode)
                # ヘルプ表示後に現在の行を再表示
                self.just_displayed_header_from_tail_h = False
                display_current_article_header()  # ヘルプ表示後に現在の行を再表示

            elif key_input == "t":  # タイトル一覧 (連続スクロール)
                if not articles:
                    self.chan.send(b'\a')
                    continue
                start_idx = current_index if 0 <= current_index < len(
                    articles) else 0
                if start_idx == -1:
                    start_idx = 0  # 先頭マーカーなら0から

                self.chan.send(b'\r\n')
                util.send_text_by_key(
                    self.chan, "bbs.article_list_header", self.menu_mode)
                for i in range(start_idx, len(articles)):
                    article = articles[i]
                    # 左寄せ、指定幅
                    # sqlite3.Row object
                    article_no_str = f"{article['article_number']:0{article_id_width}d}"
                    title = article['title'] if article['title'] else "(No Title)"

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
                            title_short = textwrap.shorten(
                                title, width=36, placeholder="...")
                        else:
                            title_short = ""
                    else:
                        title_short = textwrap.shorten(
                            title, width=38, placeholder="...")
                    # title_short の後に評価
                    deleted_mark_list = "*" if article['is_deleted'] == 1 else ""
                    user_name = sqlite_tools.get_user_name_from_user_id(
                        self.dbname, article['user_id'])
                    spaces_before_title_field_list = "  " if deleted_mark_list else "   "
                    user_name_short = textwrap.shorten(
                        user_name if user_name else "(不明)", width=7, placeholder="..")
                    try:
                        created_at_ts = article['created_at']
                        r_date_str = datetime.datetime.fromtimestamp(
                            created_at_ts).strftime('%y/%m/%d')
                        r_time_str = datetime.datetime.fromtimestamp(
                            created_at_ts).strftime('%H:%M:%S')
                    except:
                        r_date_str = "----/--/--"
                        r_time_str = "--:--"
                    self.chan.send(
                        f"{article_no_str}  {r_date_str} {r_time_str} {user_name_short:<7}{spaces_before_title_field_list}{deleted_mark_list}{title_short}\r\n".encode('utf-8'))
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
            line = ssh_input.process_input(self.chan)
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
        confirm = ssh_input.process_input(self.chan)

        if confirm is None or confirm.strip().lower() != 'y':
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            return

        if sqlite_tools.update_board_kanban(self.dbname, board_id_pk, new_body):
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
            operator_names = [sqlite_tools.get_user_name_from_user_id(
                self.dbname, uid) or f"(ID:{uid})" for uid in current_operator_ids]
            util.send_text_by_key(
                self.chan, "bbs.current_operators_list", self.menu_mode, operators_list_str=", ".join(operator_names))
        else:
            util.send_text_by_key(
                self.chan, "bbs.no_operators_assigned", self.menu_mode)

        util.send_text_by_key(
            self.chan, "bbs.confirm_edit_operators_yn", self.menu_mode, add_newline=False)
        confirm_edit = ssh_input.process_input(self.chan)
        if confirm_edit is None or confirm_edit.strip().lower() != 'y':
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            return

        util.send_text_by_key(
            self.chan, "bbs.prompt_new_operators", self.menu_mode, add_newline=False)
        new_operators_input_str = ssh_input.process_input(self.chan)
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
            user_id = sqlite_tools.get_user_id_from_user_name(
                self.dbname, name)
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

        new_operator_names_display = [sqlite_tools.get_user_name_from_user_id(
            self.dbname, uid) or f"(ID:{uid})" for uid in new_operator_ids_unique]

        util.send_text_by_key(
            self.chan, "common_messages.confirm_yn", self.menu_mode, add_newline=False)  # 確認
        self.chan.send(
            f" (New_Operators: {', '.join(new_operator_names_display) if new_operator_names_display else 'なし'}): ".encode('utf-8'))

        final_confirm = ssh_input.process_input(self.chan)
        if final_confirm is None or final_confirm.strip().lower() != 'y':
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            return

        new_operators_json = json.dumps(new_operator_ids_unique)
        if sqlite_tools.update_board_operators(self.dbname, board_id_pk, new_operators_json):
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
        current_permissions_db = sqlite_tools.get_board_permissions(  # "allow"だけでなく"deny"も取得するように変更
            self.dbname, board_id_pk)

        registered_permissions = []
        if current_permissions_db:
            for perm_entry in current_permissions_db:
                user_name = sqlite_tools.get_user_name_from_user_id(
                    self.dbname, perm_entry['user_id'])
                access_level = perm_entry['access_level'] if 'access_level' in perm_entry.keys(
                ) else "unknown"
                if user_name and user_name != "(不明)":  # 比較文字列を修正
                    registered_permissions.append(
                        (user_name, access_level))
                elif user_name == "(不明)":  # ユーザー名が実際に "(不明)" の場合に警告
                    logging.warning(
                        f"掲示板 {board_id_pk} のパーミッションリストに不明なユーザID {perm_entry['user_id']} (access_level: {access_level}) が含まれています。")

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
        confirm_edit = ssh_input.process_input(self.chan)
        if confirm_edit is None or confirm_edit.strip().lower() != 'y':
            util.send_text_by_key(
                self.chan, "common_messages.cancel", self.menu_mode)
            return

        # ユーザリストを更新
        util.send_text_by_key(
            self.chan, "bbs.prompt_new_userlist", self.menu_mode, add_newline=False)
        new_userlist_input_str = ssh_input.process_input(self.chan)

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
                elif board_default_permission == "closed":
                    access_level_to_set = "allow"
                elif board_default_permission == "readonly":
                    access_level_to_set = "allow"
                else:
                    access_level_to_set = "allow"
                    logging.info(
                        f"掲示板タイプ {board_default_permission} に対応するアクセスレベルを決定できませんでした。ユーザ {user_name_input} のアクセスレベルは'allow'に設定されました。")

                target_user_id_pk_int = sqlite_tools.get_user_id_from_user_name(
                    self.dbname, user_name_input)
                if target_user_id_pk_int is None:
                    util.send_text_by_key(
                        self.chan, "bbs.user_not_found_in_list", self.menu_mode, username=user_name_input)
                    valid_input = False
                    break
                parsed_permissions_to_add.append(
                    (str(target_user_id_pk_int), access_level_to_set))

            if not valid_input:
                return

        # DB更新
        if not sqlite_tools.delete_board_permissions_by_board_id(self.dbname, board_id_pk):
            util.send_text_by_key(
                self.chan, "common_messages.db_update_error", self.menu_mode)
            logging.error(f"掲示板ID {board_id_pk} のユーザリストを削除できませんでした。")
            return

        if parsed_permissions_to_add:
            # 重複を除いてソート
            unique_sorted_permissions = sorted(
                list(set(parsed_permissions_to_add)), key=lambda x: x[0])
            for user_id_to_add_str, access_level_to_add in unique_sorted_permissions:
                if not sqlite_tools.add_board_permission(self.dbname, board_id_pk, user_id_to_add_str, access_level_to_add):
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
            # util.send_text_by_key でタイトル行は表示されるので、以下の個別のタイトル表示は不要
            # title = article['title'] if article['title'] else "(No Title)"
            # util.send_text_by_key(
            #     self.chan, "bbs.article_header", self.menu_mode,
            #     article_number=article['article_number'], title=title)
            user_name = sqlite_tools.get_user_name_from_user_id(
                self.dbname, article['user_id'])
            try:
                created_at_str = datetime.datetime.fromtimestamp(
                    article['created_at']).strftime("%Y/%m/%d %H:%M:%S")
            except:
                created_at_str = "----/--/-- --:--:--"

            self.chan.send(
                f"Sender: {user_name if user_name else 'Unknown'}\r\n".encode('utf-8'))
            self.chan.send(
                f"Date: {created_at_str}\r\n".encode('utf-8'))
            self.chan.send(b'\r\n')

        # 削除済み記事の本文表示に関する権限チェック
        if article['is_deleted']:
            can_read_deleted_body = False
            if self.userlevel >= 5:  # シスオペは読める
                can_read_deleted_body = True
            else:
                try:
                    # 記事の投稿者ID (DBからはTEXT型で取得される可能性がある)
                    # self.user_id_pk は users.id (INTEGER)
                    article_owner_id = int(article['user_id'])
                    if article_owner_id == self.user_id_pk:  # 投稿者本人は読める
                        can_read_deleted_body = True
                except ValueError:
                    logging.warning(
                        f"記事(ID:{article['id']})の投稿者ID({article['user_id']})を数値に変換できませんでした（本文閲覧チェック時）。")

            if not can_read_deleted_body:
                # 権限がない場合はメッセージを表示して本文表示をスキップ
                util.send_text_by_key(
                    self.chan, "bbs.article_deleted_body", self.menu_mode)
                # show_back_prompt が True の場合でも、この後のプロンプトループは実行されない
                return

        body_to_send = article['body'].replace(
            '\r\n', '\n').replace('\n', '\r\n')
        # textwrap を使って本文を折り返す
        wrapped_body_lines = textwrap.wrap(
            body_to_send, width=78, replace_whitespace=False, drop_whitespace=False)
        for line in wrapped_body_lines:
            self.chan.send(line.encode('utf-8') + b'\r\n')

        # 本文表示後、改行を1行だけ入れる
        self.chan.send(b'\r\n')

        # 記事本文表示後、既読として記録
        self._update_read_progress(board_id_pk, article_number)

        if show_back_prompt:
            while True:
                util.send_text_by_key(
                    self.chan, "bbs.back_to_list_prompt", self.menu_mode, add_newline=False)
                user_input = ssh_input.process_input(self.chan)
                if user_input is None:
                    return  # 切断
                command = user_input.strip().lower()
                if command == 'e' or command == '':
                    return
                else:
                    util.send_text_by_key(
                        self.chan, "common_messages.invalid_command", self.menu_mode)

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
            return

        util.send_text_by_key(self.chan, "bbs.post_header", self.menu_mode)

        limits_config = util.app_config.get('limits', {})
        title_max_len = limits_config.get('bbs_title_max_length', 100)

        util.send_text_by_key(self.chan, "bbs.post_subject", self.menu_mode,
                              max_len=title_max_len, add_newline=False)
        title = ssh_input.process_input(self.chan)
        if title is None:
            return  # 切断
        title = title.strip()

        if len(title) > title_max_len:
            title = title[:title_max_len]
            util.send_text_by_key(
                self.chan, "bbs.title_truncated", self.menu_mode, max_len=title_max_len)

        if not title:
            return  # タイトルがなければキャンセル

        body_max_len = limits_config.get('bbs_body_max_length', 8192)
        util.send_text_by_key(
            self.chan, "bbs.post_body", self.menu_mode, max_len=body_max_len)
        body_lines = []
        while True:
            line = ssh_input.process_input(self.chan)
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
            title = title+'(T/O)'  # タイトルをタイトルオンリーに

        util.send_text_by_key(self.chan, "bbs.confirm_post_yn",
                              self.menu_mode, add_newline=False)
        confirm = ssh_input.process_input(self.chan)
        if confirm is None or confirm.strip().lower() != 'y':
            util.send_text_by_key(self.chan, "bbs.post_cancel", self.menu_mode)
            return  # キャンセル

        if self.article_manager.create_article(board_id_pk, self.user_id_pk, title, body, ip_address=client_ip):
            util.send_text_by_key(
                self.chan, "bbs.post_success", self.menu_mode)
        else:
            util.send_text_by_key(self.chan, "bbs.post_failed", self.menu_mode)


def handle_bbs_menu(chan, dbname, login_id, menu_mode, shortcut_id):
    """掲示板メニューのエントリーポイント"""
    handler = CommandHandler(chan, dbname, login_id, menu_mode)
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
        selected_item = hierarchical_menu.handle_hierarchical_menu(
            chan, bbs_config_path, menu_mode, menu_type="BBS",  # menu_type を追加
            dbname=dbname, enrich_boards=True
        )
        logging.info(
            f"bbs_handler: hierarchical_menu.handle_hierarchical_menu returned: {selected_item}")

        if selected_item and selected_item.get("type") == "board":
            shortcut_id_selected = selected_item.get("id")
            # 再度 handle_bbs_menu を呼び出すか、直接 CommandHandler の処理を続ける
            # handle_bbs_menu からの戻り値をそのまま返す
            return handle_bbs_menu(chan, dbname, login_id,
                                   menu_mode, shortcut_id_selected)
        # else: 選択されなかったか、boardタイプではなかった場合。handle_hierarchical_menu内でメッセージ表示済みのはず。
        # hierarchical_menu から戻ってきた場合は、通常トップメニュー表示で問題ない想定
        return "back_to_top"
