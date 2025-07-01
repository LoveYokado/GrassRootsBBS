import logging
import time
import json
import util
import sqlite_tools


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

        board_id_pk = board_info.get("id")
        read_level = board_info.get('read_level', 1)  # デフォルトはレベル1

        user_specific_perm = sqlite_tools.get_user_permission_for_board(
            self.dbname, board_id_pk, str(user_id_pk))

        # 優先順位: 1. deny, 2. allow, 3. level check
        if user_specific_perm == "deny":
            return False
        if user_specific_perm == "allow":
            return True

        return user_level >= read_level

    def can_write_to_board(self, board_info, user_id_pk, user_level):
        """指定された掲示板の書き込み権限があるかチェックする"""
        if user_level >= 5:
            return True

        board_id_pk = board_info.get("id")
        write_level = board_info.get('write_level', 1)  # デフォルトはレベル1

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

        # 優先順位: 1. deny, 2. allow, 3. level check
        if user_specific_perm == "deny":
            return False
        if user_specific_perm == "allow":
            return True

        return user_level >= write_level

    def get_permission_list(self, board_id):
        """指定された掲示板のパーミッションリストを取得する"""
        # TODO: 実装
        pass

    def update_permission_list(self, board_id, user_id, permission_type):
        """指定された掲示板のパーミッションリストを更新する"""
        # permission_type: "allow" (ホワイトリスト), "deny" (ブラックリスト)
        # TODO: 実装
        pass
