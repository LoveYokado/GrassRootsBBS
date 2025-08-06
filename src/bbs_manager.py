import logging
import time
import json

from . import util, database


class BoardManager:
    """掲示板のメタ情報を管理するクラス"""

    def __init__(self):
        # dbname は不要になったため削除
        pass

    def load_boards_from_config(self):
        # This function is currently not called from anywhere.
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
        # database.py は直接辞書を返すため、dict()変換は不要
        return database.get_board_by_shortcut_id(shortcut_id)


class ArticleManager:
    """記事のCRUD操作と表示を行うクラス"""

    def __init__(self):
        # dbname は不要になったため削除
        pass

    def get_articles_by_board(self, board_id, include_deleted=False):
        """指定された掲示板の投稿一覧を取得する"""
        # board_idはboardsテーブルの主キー(id)
        # 投稿順（古いものが先）で取得
        return database.get_articles_by_board_id(board_id, order_by="created_at ASC, article_number ASC", include_deleted=include_deleted)

    def get_new_articles(self, board_id, last_login_timestamp):
        """指定された掲示板の、指定時刻以降の未削除記事を取得する。"""
        return database.get_new_articles_for_board(board_id, last_login_timestamp)

    def get_article_by_number(self, board_id, article_number, include_deleted=False):
        """指定された記事番号の記事を取得する"""
        # board_idはboardsテーブルの主キー(id)
        # self.dbname は不要になったため、直接 database モジュールを呼び出す
        return database.get_article_by_board_and_number(
            board_id, article_number, include_deleted=include_deleted)

    def create_article(self, board_id_pk, user_identifier, title, body, ip_address=None, parent_article_id=None, attachment_filename=None, attachment_originalname=None, attachment_size=None):
        """
        記事を新規作成する
        board_id_pkはboardsテーブルの主キー
        user_identifierはusersテーブルの主キー(int)またはゲストの表示名(str)
        戻り値は作成された記事のID、失敗したらNone
        """
        conn = None
        cursor = None
        try:
            conn = database.get_connection()
            cursor = conn.cursor()

            # 返信の場合は記事番号を採番せず、スレッド作成の場合のみ採番する
            if parent_article_id is not None:
                next_article_number = None  # 返信には記事番号を割り当てない
            else:
                # 次の記事番号取得 (トランザクション内で実行)
                query_next_num = "SELECT COALESCE(MAX(article_number), 0) + 1 FROM articles WHERE board_id = %s"
                cursor.execute(query_next_num, (board_id_pk,))
                result = cursor.fetchone()
                next_article_number = result[0] if result and result[0] is not None else 1

                if next_article_number is None:
                    raise Exception("次の記事番号の取得に失敗")

            # 記事を挿入 (トランザクション内で実行)
            current_timestamp = int(time.time())
            query_insert = """
                INSERT INTO articles (board_id, article_number, user_id, parent_article_id, title, body, created_at, ip_address, attachment_filename, attachment_originalname, attachment_size)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            params_insert = (board_id_pk, next_article_number, str(user_identifier),
                             parent_article_id, title, body, current_timestamp, ip_address,
                             attachment_filename, attachment_originalname, attachment_size)
            cursor.execute(query_insert, params_insert)
            article_id = cursor.lastrowid
            if article_id is None:
                raise Exception("記事の挿入に失敗")

            # 掲示板の最終投稿日時を更新 (トランザクション内で実行)
            query_update_board = "UPDATE boards SET last_posted_at = %s WHERE id = %s"
            cursor.execute(query_update_board,
                           (current_timestamp, board_id_pk))
            if cursor.rowcount == 0:
                raise Exception(f"掲示板(ID: {board_id_pk})の最終投稿日時更新に失敗（対象行なし）")

            # 全ての処理が成功したらコミット
            conn.commit()
            logging.info(
                f"記事を作成しました(BoardID:{board_id_pk}, ArticleNo:{next_article_number}, User:{user_identifier}, ArticleDBID:{article_id})")
            return article_id

        except Exception as e:
            logging.error(
                f"記事の作成に失敗しました(BoardID:{board_id_pk}, User:{user_identifier}): {e}", exc_info=True)
            if conn:
                conn.rollback()  # エラー発生時はロールバック
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_threads(self, board_id, include_deleted=False):
        """指定された掲示板のスレッド一覧(親記事と返信数)を取得"""
        return database.get_thread_root_articles_with_reply_count(board_id, include_deleted)

    def get_replies(self, parent_article_id, include_deleted=False):
        """指定された親記事の返信をすべて取得"""
        return database.get_replies_for_article(parent_article_id, include_deleted)

    def update_article(self, article_id, title, body):
        """記事を更新する（主に看板用）"""
        # TODO: 実装
        pass

    def toggle_delete_article(self, article_id):
        """記事の削除フラグをトグルする(論理削除)"""
        return database.toggle_article_deleted_status(article_id)

    def search_articles(self, board_id, keyword, search_body=False):
        # TODO: 検索機能の実装時に include_deleted を考慮する
        """記事を検索する（タイトルまたは本文）"""
        # TODO: 実装
        pass


class PermissionManager:
    """権限管理を行うクラス"""

    def __init__(self):
        # dbname は不要になったため削除
        pass

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

        user_specific_perm = database.get_user_permission_for_board(
            board_id_pk, str(user_id_pk))

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

        user_specific_perm = database.get_user_permission_for_board(
            board_id_pk, str(user_id_pk))

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

    def can_delete_article(self, article_data, user_id_pk, user_level):
        """指定された記事の削除/復元権限があるかチェックする"""
        if not article_data:
            return False

        # シスオペ (レベル5以上) は常に権限あり
        if user_level >= 5:
            return True

        # 記事の投稿者本人かチェック
        try:
            # article_data['user_id'] は TEXT 型の可能性があるため int に変換
            # user_id_pk は users.id (INTEGER)
            article_owner_id = int(article_data['user_id'])
            if article_owner_id == user_id_pk:
                return True
        except (ValueError, TypeError, KeyError):
            # GUEST(hash) のような文字列や、キーが存在しない場合は本人ではない
            pass

        return False

    def can_view_deleted_article_content(self, article_data, user_id_pk, user_level):
        """削除された記事の内容（タイトルや本文）を閲覧する権限があるかチェックする"""
        if not article_data or article_data.get('is_deleted') != 1:
            # 削除されていない記事、またはデータがない場合は権限チェックの対象外
            return True

        # シスオペ (レベル5以上) は常に権限あり
        if user_level >= 5:
            return True

        # 記事の投稿者本人かチェック
        try:
            article_owner_id = int(article_data['user_id'])
            return article_owner_id == user_id_pk
        except (ValueError, TypeError, KeyError):
            # GUEST(hash) やIDがない場合は本人ではない
            return False

    def get_permission_list(self, board_id):
        """指定された掲示板のパーミッションリストを取得する"""
        # TODO: 実装
        pass

    def update_permission_list(self, board_id, user_id, permission_type):
        """指定された掲示板のパーミッションリストを更新する"""
        # permission_type: "allow" (ホワイトリスト), "deny" (ブラックリスト)
        # TODO: 実装
        pass
