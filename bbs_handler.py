# bbs_handler.py (骨格)
import sqlite3
import logging
import time
import sqlite_tools  # データベース操作用
import util  # 共通関数 (設定読み込み、テキスト表示など)
import ssh_input  # ユーザー入力処理

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

    def get_articles_by_board(self, board_id):
        """指定された掲示板の投稿一覧を取得する"""
        # TODO: 実装
        pass

    def get_article_by_number(self, board_id, article_number):
        """指定された記事番号の記事を取得する"""
        # TODO: 実装
        pass

    def create_article(self, board_id_pk, user_id_pk, title, body):
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
                self.dbname, board_id_pk, next_article_number, user_id_pk, title, body, current_timestamp
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
        """記事の削除フラグをトグルする"""
        # TODO: 実装
        pass

    def search_articles(self, board_id, keyword, search_body=False):
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
        self.user_id_pk = sqlite_tools.get_user_id_from_user_name(
            dbname, login_id)

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
            util.send_text_by_key(self.chan, "bbs.rw_prompt",
                                  self.menu_mode, add_newline=False)
            user_input = ssh_input.process_input(self.chan)

            if user_input is None:
                return  # 切断

            command = user_input.strip().lower()

            if command == '':
                break  # 掲示板終了
            elif command == 'w':
                self.write_article()  # 記事書き込み
            elif command == 'r':
                pass  # 記事読み込み

            else:
                continue  # コマンド不明

    def show_article_list(self):
        """記事一覧を表示"""
        # TODO: 実装
        pass

    def read_article(self, article_number):
        """記事を読む"""
        # TODO: 実装
        pass

    def write_article(self):
        """記事を新規作成"""
        if not self.current_board:
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        board_id_pk = self.current_board['id']  # sqlite3のオブジェクトを取得
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
            title = title+'(T/O)'  # タイトルをタイトルオンリーに更新

        util.send_text_by_key(self.chan, "bbs.confirm_post_yn",
                              self.menu_mode, add_newline=False)
        confirm = ssh_input.process_input(self.chan)
        if confirm is None or confirm.strip().lower() != 'y':
            util.send_text_by_key(self.chan, "bbs.post_cancel", self.menu_mode)
            return  # キャンセル

        if self.article_manager.create_article(board_id_pk, self.user_id_pk, title, body):
            util.send_text_by_key(
                self.chan, "bbs.post_success", self.menu_mode)
        else:
            util.send_text_by_key(self.chan, "bbs.post_failed", self.menu_mode)

    # ... 他のコマンドに対応するメソッドを定義

# 外部から呼び出す関数 (例: server.py から)


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
