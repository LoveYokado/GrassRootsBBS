# bbs_handler.py (骨格)

import logging
import textwrap
import sqlite_tools  # データベース操作用
import util  # 共通関数 (設定読み込み、テキスト表示など)
import json  # operators の処理や、もしDBのnameがJSONのままなら必要
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

    def create_article(self, board_id, user_id, title, body):
        """記事を新規作成する"""
        # TODO: 実装
        pass

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

    def command_loop(self):
        """コマンド処理のメインループ (mail_handler.py を参考に実装)"""
        if not self.current_board:
            util.send_text_by_key(
                self.chan, "bbs.no_board_selected", self.menu_mode)
            return

        # 現在の掲示板名を表示 (get_board_info で bbs.yml から name がマージされている想定)
        board_name_display = self.current_board.get('name', '不明な掲示板')
        # 必要であれば description も表示
        util.send_text_by_key(self.chan, "bbs.current_board_header",
                              self.menu_mode, board_name=board_name_display)

        self.show_article_list()  # 初期表示として記事一覧
    # 各コマンドに対応するメソッド

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
        # TODO: 実装
        pass

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
