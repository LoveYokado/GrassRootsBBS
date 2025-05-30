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

                    # bbs.yml からは構造情報と、DBで管理しない情報を取得
                    # name, description は bbs.yml で管理するため、ここではDB同期対象外
                    # DBには shortcut_id と、DBで管理する情報 (operators, default_permission, category_id, display_order) を格納
                    boards_from_yml.append({
                        "shortcut_id": shortcut_id,
                        # "name": item_data.get("name", shortcut_id), # DBには保存しない
                        # "description": item_data.get("description", ""), # DBには保存しない
                        # JSON文字列で格納
                        "operators": json.dumps(item_data.get("operators", [])),
                        "default_permission": item_data.get("permission", "close"),
                        "category_id": current_category_id,
                        "display_order": item_data.get("number", 0)
                    })
                    processed_shortcuts.add(shortcut_id)
                elif item_data.get("type") == "child" and "items" in item_data:
                    # 子カテゴリのIDをそのまま使うか、別途 child 用の category_id を持つか検討
                    _parse_items(item_data.get("items", []),
                                 item_data.get("id"))

        for category in bbs_config_data.get("categories", []):
            category_id = category.get("id")
            # カテゴリ自体の情報をDBに入れるかは別途検討
            _parse_items(category.get("items", []), category_id)

        # DBとの同期処理 (sqlite_tools に sync_boards_with_config(dbname, boards_from_yml, processed_shortcuts) のような関数を実装する想定)
        # この関数内で、ymlに存在するものはINSERT/UPDATE、ymlに存在せずDBにあるものはDELETEまたはフラグ立てを行う
        # ここでは簡略化のため、成功したとしてTrueを返す
        logging.info(
            f"bbs.ymlから {len(boards_from_yml)} 件の掲示板情報を読み込みました。DB同期処理が必要です。")
        # return sqlite_tools.sync_boards_with_config(self.dbname, boards_from_yml, processed_shortcuts)
        return True  # 仮

    def get_board_info(self, shortcut_id):
        """指定されたショートカットIDの掲示板情報を bbs.yml と DB からマージして取得する"""
        # 1. DBから基本情報を取得
        board_info_db = sqlite_tools.get_board_by_shortcut_id(
            self.dbname, shortcut_id)
        if not board_info_db:
            return None

        # 2. bbs.yml から名前と説明を取得
        #    menu_mode はこのクラス内では直接持っていないため、固定値か、あるいは呼び出し元から渡す必要がある。
        #    ここでは仮に '1' を使うが、実際には適切な menu_mode を使うべき。
        #    もしくは、name, description は menu_mode に依存しない前提なら不要。
        bbs_config = util.load_yaml_file_for_shortcut("bbs.yml")
        board_info_yml, board_name_yml = util.find_item_in_yaml(
            bbs_config, shortcut_id, "1", "board")  # 仮のmenu_mode

        merged_info = dict(board_info_db)  # DB情報をベースにコピー
        # YMLにあればYMLの名前、なければID
        merged_info["name"] = board_name_yml if board_info_yml else shortcut_id
        merged_info["description"] = board_info_yml.get(
            "description", "") if board_info_yml else ""
        return merged_info


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

        # 現在の掲示板名を表示 (DBのnameカラムの形式に注意)
        # current_board['name'] は get_board_info で bbs.yml から取得した文字列が格納されている想定
        board_name_display = self.current_board.get('name', '不明な掲示板')
        # description も同様
        # board_description_display = self.current_board.get('description', '')

        # util.send_text_by_key(self.chan, "bbs.current_board_header", self.menu_mode, board_name=board_name_display)

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
