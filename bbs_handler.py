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

# クラスや関数は、以下の構成で定義していく
# - BoardManager: 掲示板のメタ情報管理、bbs.yml との同期
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

    def load_boards_from_config(self):
        """bbs.yml から掲示板情報を読み込み、DBと同期する"""
        bbs_config_data = util.load_yaml_file_for_shortcut("bbs.yml")
        if not bbs_config_data or "categories" not in bbs_config_data:
            logging.error("bbs.yml の読み込みに失敗したか、不正な形式です。")
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

                    # bbs.yml の name は直接文字列
                    board_name_from_yml = item_data.get("name")
                    if board_name_from_yml is None:  # name がない場合はIDを使うなどフォールバック
                        board_name_from_yml = shortcut_id
                        logging.warning(
                            f"掲示板 {shortcut_id} の name が未定義です。IDを使用します。")

                    # bbs.yml からは shortcut_id のみを取得。name, description はDBで管理。
                    # operators, default_permission はDBで直接管理 (sysop_menu.mkbd で初期設定)
                    # category_id, display_order も bbs.yml で管理

                    processed_shortcuts.add(shortcut_id)
                elif item_data.get("type") == "child" and "items" in item_data:
                    _parse_items(item_data.get("items", []),
                                 item_data.get("id"))

        for category in bbs_config_data.get("categories", []):
            category_id = category.get("id")
            # カテゴリ自体の情報をDBに入れるかは別途検討
            _parse_items(category.get("items", []), category_id)

        # 現状の方針では、この関数は主に「bbs.ymlに定義されているがDBにない掲示板がないか」のチェックや、
        # 「DBには存在するがbbs.ymlのどこにも属していない掲示板がないか」のチェックになるかもしれません。
        logging.info(
            f"bbs.ymlから {len(processed_shortcuts)} 件の掲示板ショートカットIDを認識しました: {processed_shortcuts}")
        return True  # 仮

    def get_board_info(self, shortcut_id):
        """指定されたショートカットIDの掲示板情報をDBから取得する"""
        board_info = sqlite_tools.get_board_by_shortcut_id(
            self.dbname, shortcut_id)
        return board_info  # sqlite3.Row オブジェクトか None をそのまま返す


class ArticleManager:
    """記事のCRUD操作と表示を行うクラス"""

    def __init__(self, dbname):
        self.dbname = dbname

    def get_articles_by_board(self, board_id, include_deleted=False):
        """指定された掲示板の投稿一覧を取得する"""
        # board_idはboardsテーブルの主キー(id)
        # 投稿順（古いものが先）で取得
        return sqlite_tools.get_articles_by_board_id(self.dbname, board_id, order_by="created_at ASC, article_number ASC", include_deleted=include_deleted)

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
        """指定されたアクションの実行権限があるかチェックする"""
        # action: "read", "write", "delete", "edit_kanban", "edit_permission"
        # TODO: 実装
        pass

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

    def _display_kanban(self):
        """看板を表示する"""
        if not self.current_board:
            return

        kanban_title = self.current_board['kanban_title'] if 'kanban_title' in self.current_board.keys(
        ) else ''
        kanban_body = self.current_board['kanban_body'] if 'kanban_body' in self.current_board.keys(
        ) else ''

        if not kanban_title and not kanban_body:
            return  # 看板がなければ表示しない

        if kanban_title:
            processed_title = kanban_title.replace(
                '\r\n', '\n').replace('\n', '\r\n')
            self.chan.send(processed_title.encode('utf-8'))
            if not processed_title.endswith('\r\n'):
                self.chan.send(b'\r\n')

        if kanban_body:
            processed_body = kanban_body.replace(
                '\r\n', '\n').replace('\n', '\r\n')
            self.chan.send(processed_body.encode('utf-8'))
            if not processed_body.endswith('\r\n'):
                self.chan.send(b'\r\n')
        if kanban_title or kanban_body:
            self.chan.send(b'\r\n')

    def command_loop(self):
        """コマンド処理のメインループ (mail_handler.py を参考に実装)"""
        if not self.current_board:
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        board_name_display = self.current_board['name'] if 'name' in self.current_board.keys(
        ) else 'unknown board'
        # 説明表示が必要ならコメント外す
        util.send_text_by_key(
            self.chan, "bbs.current_board_header",
            self.menu_mode, board_name=board_name_display
        )

        self._display_kanban()  # 板看板を表示
        while True:
            # メニュー表示
            util.send_text_by_key(
                self.chan, "bbs.main_prompt", self.menu_mode, add_newline=False
            )
            choice = ssh_input.process_input(self.chan)
            if choice is None:
                return  # 切断
            choice = choice.lower().strip()

            if choice == 'w':
                self.write_article()
                return  # command_loop を抜けて handle_bbs_menu に戻る
            elif choice == 'r':
                self.show_article_list()
                return  # command_loop を抜けて handle_bbs_menu に戻る
            elif choice == 'e' or choice == '':
                return
            else:
                util.send_text_by_key(
                    self.chan, "common_messages.invalid_command", self.menu_mode)

    def show_article_list(self):
        """記事一覧を表示"""
        if not self.current_board:
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        board_id_pk = self.current_board['id']
        articles = []  # この行で articles を初期化
        current_index = 0
        article_id_width = 5  # 記事番号桁数

        # 常に削除済み記事も取得するが、表示方法は権限によって変える
        # show_deleted_articles 変数はここでは直接使わない

        def reload_articles_display(keep_index=True):
            nonlocal articles, current_index, article_id_width
            current_article_id_on_reload = None
            if articles and 0 <= current_index < len(articles) and keep_index:
                current_article_id_on_reload = articles[current_index]['id']

            fetched_articles = self.article_manager.get_articles_by_board(
                board_id_pk, include_deleted=True)  # 常に削除済み記事も取得
            articles = fetched_articles if fetched_articles else []

            new_idx = 0
            if articles and keep_index:
                if keep_index and current_article_id_on_reload is not None:
                    found = False
                    for i, art in enumerate(articles):
                        if art['id'] == current_article_id_on_reload:
                            new_idx = i
                            found = True
                            break
                    if not found:
                        new_idx = 0
            article_id_width = max(
                5, len(str(len(articles)))) if articles else 5
            current_index = new_idx

            # 画面クリアしてヘッダ再表示
            util.send_text_by_key(
                self.chan, "bbs.article_list_header", self.menu_mode)
            if not articles:
                util.send_text_by_key(
                    self.chan, "bbs.no_article", self.menu_mode)
                current_index = 0  # 記事がなかったらインデックスは0
            else:
                display_current_article_header()

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
                        created_at_ts).strftime("%H:%M")
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
                # 左寄せ、指定幅
                article_no_str = f"{article['article_number']:0{article_id_width}d}"

                self.chan.send(
                    f"{article_no_str}  {r_date_str} {r_time_str}    {user_name_short:<7}   {deleted_mark}{title_short}\r\n".encode('utf-8'))
            else:
                util.send_text_by_key(
                    self.chan, "bbs.no_article", self.menu_mode)

        reload_articles_display(keep_index=False)
        self.just_displayed_header_from_tail_h = False  # フラグをリセット

        while True:
            util.send_text_by_key(
                self.chan, "bbs.article_list_prompt", self.menu_mode, add_newline=False)
            key_input = None
            try:
                data = self.chan.recv(1)  # 1バイトずつデータを受信
                if not data:
                    logging.info(
                        f"掲示板記事一覧中にクライアントが切断されました。 (ユーザー: {self.login_id})")
                    return  # 切断

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

            # 旧方向へ進む[ctrl+e][k][上カーソル]
            if key_input == '\x05' or key_input == "k" or key_input == "KEY_UP":
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
                self.chan.send(b'\r\n')
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
                    deleted_mark_list = "*" if article['is_deleted'] == 1 else ""

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
                    user_name = sqlite_tools.get_user_name_from_user_id(
                        self.dbname, article['user_id'])
                    user_name_short = textwrap.shorten(
                        user_name if user_name else "(不明)", width=7, placeholder="..")
                    try:
                        created_at_ts = article['created_at']
                        r_date_str = datetime.datetime.fromtimestamp(
                            created_at_ts).strftime('%y/%m/%d')
                        r_time_str = datetime.datetime.fromtimestamp(
                            created_at_ts).strftime('%H:%M')
                    except:
                        r_date_str = "----/--/--"
                        r_time_str = "--:--"
                    self.chan.send(
                        f"{article_no_str}  {r_date_str} {r_time_str}    {user_name_short:<7}   {deleted_mark_list}{title_short}\r\n".encode('utf-8'))
                self.chan.send(b'\r\n')  # タイトル一覧の最後に空行
                current_index = len(articles)  # 末尾マーカーへ
                display_current_article_header()
                self.just_displayed_header_from_tail_h = False

            elif key_input == "c":  # シグオペ変更
                self.edit_board_operators()
                display_current_article_header()
                self.just_displayed_header_from_tail_h = False

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
            current_operator_ids = json.loads(self.current_board['operators'])
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logging.warning(
                f"掲示板ID {board_id_pk} のオペレーターリストの読み込み/デコードに失敗: {e} (operators: {self.current_board.get('operators')})")
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
                    article['created_at']).strftime("%Y-/%m-/%d %H:%M:%S")
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
        # TODO:将来的にはPermissionManagerで書き込み権限チェック
        # if not self.permission_manager.check_permission(board_id_pk, self.user_id_pk, "write"):
        #    util.send_text_by_key(self.chan, "bbs.permission_denied_write", self.menu_mode)
        #    return

        util.send_text_by_key(self.chan, "bbs.post_header", self.menu_mode)
        util.send_text_by_key(self.chan, "bbs.post_subject",
                              self.menu_mode, add_newline=False)
        title = ssh_input.process_input(self.chan)
        if title is None:
            return  # 切断
        title = title.strip()

        if not title:
            return  # タイトルがなければキャンセル

        util.send_text_by_key(self.chan, "bbs.post_body", self.menu_mode)
        body_lines = []
        while True:
            line = ssh_input.process_input(self.chan)
            if line is None:
                return  # 切断
            if line == '^':
                break
            body_lines.append(line)
        body = '\r\n'.join(body_lines)

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
            # TODO: ここでパーミッションチェックを行う
            # if not handler.permission_manager.check_permission(handler.current_board['id'], login_id, "read"):
            #     util.send_text_by_key(chan, "bbs.permission_denied_read", menu_mode)
            #     return
            handler.command_loop()
        else:
            # TODO: textdata.yaml に追加
            util.send_text_by_key(chan, "bbs.board_not_found", menu_mode)
    else:
        # 指定がなければ、カテゴリ選択 or 掲示板一覧表示からの遷移
        # hierarchical_menu を使って掲示板を選択させる
        bbs_config_path = "setting/bbs.yml"
        selected_item = hierarchical_menu.handle_hierarchical_menu(
            chan, bbs_config_path, menu_mode
        )
        if selected_item and selected_item.get("type") == "board":
            shortcut_id_selected = selected_item.get("id")
            # 再度 handle_bbs_menu を呼び出すか、直接 CommandHandler の処理を続ける
            handle_bbs_menu(chan, dbname, login_id,
                            menu_mode, shortcut_id_selected)
        # else: 選択されなかったか、boardタイプではなかった場合。handle_hierarchical_menu内でメッセージ表示済みのはず。
