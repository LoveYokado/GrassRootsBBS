# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""BBS ビジネスロジックマネージャ。

このモジュールは、電子掲示板システム (BBS) のビジネスロジックを
カプセル化するマネージャクラスを含んでいます。これらのクラスは、
リクエストハンドラ (例: bbs_handler.py) とデータベースアクセス層
(database.py) の中間層として機能し、掲示板、記事、権限に関連する操作を処理します。
"""

import logging
import time
import json

from . import util, database


class BoardManager:
    """掲示板のメタ情報（設定、看板など）を管理するクラスです。"""

    def __init__(self):
        # データベース接続はグローバルな database モジュールを介して行われるため、
        # このクラスのインスタンス変数として保持する必要はありません。
        pass

    def load_boards_from_config(self):
        paths_config = util.app_config.get('paths', {})
        bbs_config_path = paths_config.get('bbs_sync_config')
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
                    board_name_from_yml = item_data.get("name")
                    if board_name_from_yml is None:
                        board_name_from_yml = shortcut_id
                        logging.warning(
                            f"掲示板 {shortcut_id} の name が未定義です。IDを使用します。")

                    processed_shortcuts.add(shortcut_id)
                elif item_data.get("type") == "child" and "items" in item_data:
                    _parse_items(item_data.get("items", []),
                                 item_data.get("id"))

        for category in bbs_config_data.get("categories", []):
            category_id = category.get("id")
            _parse_items(category.get("items", []), category_id)

        logging.info(
            f"bbs.yamlから {len(processed_shortcuts)} 件の掲示板ショートカットIDを認識しました: {processed_shortcuts}")
        return True

    def get_board_info(self, shortcut_id):
        """指定されたショートカットIDを持つ掲示板の情報をDBから取得します。"""
        return database.get_board_by_shortcut_id(shortcut_id)


class ArticleManager:
    """記事の作成、読み込み、更新、削除 (CRUD) 操作を管理するクラスです。"""

    def __init__(self):
        pass

    def get_articles_by_board(self, board_id, include_deleted=False):
        """指定された掲示板の投稿一覧を取得します。"""
        return database.get_articles_by_board_id(board_id, order_by="created_at ASC, article_number ASC", include_deleted=include_deleted)

    def get_new_articles(self, board_id, last_login_timestamp):
        """指定された掲示板の、指定時刻以降の未削除記事を取得します。"""
        return database.get_new_articles_for_board(board_id, last_login_timestamp)

    def get_article_by_number(self, board_id, article_number, include_deleted=False):
        """指定された記事番号の記事を取得します。"""
        return database.get_article_by_board_and_number(
            board_id, article_number, include_deleted=include_deleted)

    def create_article(self, board_id_pk, user_identifier, title, body, ip_address=None, parent_article_id=None, attachment_filename=None, attachment_originalname=None, attachment_size=None):
        """記事を新規作成します。

        Args:
            board_id_pk (int): 掲示板の主キー (boards.id)。
            user_identifier (int or str): ユーザーの主キー (users.id) またはゲストの表示名。

        Returns:
            int or None: 成功した場合は作成された記事のID、失敗した場合はNone。
        """
        conn = None
        cursor = None
        try:
            conn = database.get_connection()
            cursor = conn.cursor()

            # --- 1. 記事番号の採番 (新規スレッド/記事の場合のみ) ---
            if parent_article_id is not None:
                next_article_number = None  # 返信には記事番号を割り当てない
            else:
                query_next_num = "SELECT COALESCE(MAX(article_number), 0) + 1 FROM articles WHERE board_id = %s"
                cursor.execute(query_next_num, (board_id_pk,))
                result = cursor.fetchone()
                next_article_number = result[0] if result and result[0] is not None else 1

                if next_article_number is None:
                    raise Exception("次の記事番号の取得に失敗")

            # --- 2. 記事の挿入 ---
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

            # --- 3. 掲示板の最終投稿日時を更新 ---
            query_update_board = "UPDATE boards SET last_posted_at = %s WHERE id = %s"
            cursor.execute(query_update_board,
                           (current_timestamp, board_id_pk))
            if cursor.rowcount == 0:
                raise Exception(f"掲示板(ID: {board_id_pk})の最終投稿日時更新に失敗（対象行なし）")

            # --- 4. コミット ---
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
        """指定された掲示板のスレッド一覧（親記事と返信数）を取得します。"""
        return database.get_thread_root_articles_with_reply_count(board_id, include_deleted)

    def get_replies(self, parent_article_id, include_deleted=False):
        """指定された親記事の返信をすべて取得します。"""
        return database.get_replies_for_article(parent_article_id, include_deleted)

    def toggle_delete_article(self, article_id):
        """記事の削除フラグをトグルします（論理削除）。"""
        return database.toggle_article_deleted_status(article_id)

    def get_thread_count(self, board_id_pk):
        """指定された掲示板の現在のスレッド数を取得します（削除済みは除く）。"""
        query = "SELECT COUNT(*) AS count FROM articles WHERE board_id = %s AND parent_article_id IS NULL AND is_deleted = 0"
        result = database.execute_query(query, (board_id_pk,), fetch='one')
        return result['count'] if result else 0

    def get_reply_count(self, parent_article_id_pk):
        """指定された親記事の現在の返信数を取得します（削除済みは除く）。"""
        query = "SELECT COUNT(*) AS count FROM articles WHERE parent_article_id = %s AND is_deleted = 0"
        result = database.execute_query(
            query, (parent_article_id_pk,), fetch='one')
        return result['count'] if result else 0


class PermissionManager:
    """掲示板や記事へのアクセス権限を管理・検証するクラスです。"""

    def __init__(self):
        pass

    def _check_generic_permission(self, board_info, user_id_pk, user_level, level_key):
        """汎用的な権限チェックロジック。"""
        if user_level >= 5:
            return True  # SysOpは常に許可

        board_id_pk = board_info.get("id")

        # 1. ユーザー固有のパーミッションを先にチェック
        user_specific_perm = database.get_user_permission_for_board(
            board_id_pk, str(user_id_pk))

        if user_specific_perm == "deny":
            return False
        if user_specific_perm == "allow":
            return True

        # 2. 掲示板のデフォルト設定に基づいて判断
        default_permission = board_info.get('default_permission', 'open')
        if default_permission == 'close':
            return False  # closeの場合、リストにallowで載っていないユーザーは全員拒否

        # open または readonly の場合、レベルチェックを行う
        required_level = board_info.get(level_key, 1)  # デフォルトはレベル1
        return user_level >= required_level

    def can_view_board(self, board_info, user_id_pk, user_level):
        """指定された掲示板の閲覧権限があるかチェックします。"""
        return self._check_generic_permission(board_info, user_id_pk, user_level, 'read_level')

    def can_write_to_board(self, board_info, user_id_pk, user_level):
        """指定された掲示板の書き込み権限があるかチェックします。"""
        # 1. SysOpは常に許可
        if user_level >= 5:
            return True

        # 2. 掲示板のシグオペは常に許可
        try:
            operator_ids_json = board_info.get('operators', '[]')
            operator_ids = json.loads(operator_ids_json)
            if user_id_pk in operator_ids:
                return True
        except (json.JSONDecodeError, TypeError):
            pass  # JSONデコードエラーは無視

        # 3. ユーザー固有の `allow` 設定があれば許可
        user_specific_perm = database.get_user_permission_for_board(
            board_info.get("id"), str(user_id_pk))
        if user_specific_perm == "allow":
            return True

        # 4. 掲示板のデフォルト設定が 'close' または 'readonly' の場合、
        #    上記で許可されていないユーザーは書き込み不可
        default_permission = board_info.get('default_permission', 'open')
        if default_permission in ['close', 'readonly']:
            return False

        # 5. 掲示板が 'open' の場合、ユーザーレベルと要求レベルを比較
        required_level = board_info.get('write_level', 1)
        return user_level >= required_level

    def can_delete_article(self, article_data, user_id_pk, user_level):
        """指定された記事の削除/復元権限があるかチェックします。"""
        if not article_data:
            return False

        # シスオペ (レベル5以上) は常に権限あり
        if user_level >= 5:
            return True

        try:
            article_owner_id = int(article_data['user_id'])
            if article_owner_id == user_id_pk:
                return True
        except (ValueError, TypeError, KeyError):
            # GUEST(hash) のような文字列や、キーが存在しない場合は本人ではない
            pass

        return False

    def can_view_deleted_article_content(self, article_data, user_id_pk, user_level):
        """削除された記事の内容（タイトルや本文）を閲覧する権限があるかチェックします。"""
        if not article_data or article_data.get('is_deleted') != 1:
            return True

        if user_level >= 5:
            return True

        try:
            article_owner_id = int(article_data['user_id'])
            return article_owner_id == user_id_pk
        except (ValueError, TypeError, KeyError):
            return False
