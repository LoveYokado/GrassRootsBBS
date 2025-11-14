# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""バックアップ・リストアユーティリティ。

このモジュールは、フルバックアップの作成 (データベース + 指定ディレクトリ)、
バックアップアーカイブからのデータ復元、全アプリケーションデータの消去、
古いバックアップファイルのクリーンアップといったデータ管理機能を提供します。
"""

import os
import datetime
import subprocess
import tarfile
import shutil
import logging
from . import util, database

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def create_backup():
    """データベース、添付ファイル、設定ファイルを一つのアーカイブにまとめてバックアップします。

    Returns:
        str or None: 作成されたバックアップファイル名。失敗した場合はNone。
    """
    # --- 設定ファイルからバックアップ設定を読み込む ---
    backup_config = util.app_config.get('backup', {})
    backup_dir_rel = backup_config.get('backup_directory', 'data/backups')
    temp_dir_prefix = backup_config.get('temp_directory_prefix', 'temp_')
    source_dirs = backup_config.get(
        'source_directories', ['data/attachments', 'setting'])
    db_dump_filename_format = backup_config.get(
        'db_dump_filename', 'dump_{db_name}.sql')
    archive_name_format = backup_config.get(
        'archive_name_format', 'grbbs_backup_{timestamp}.tar.gz')
    archive_root_dir_format = backup_config.get(
        'archive_root_dir_format', 'backup_{timestamp}')

    # バックアップディレクトリの絶対パスを決定
    backup_dir = os.path.join(PROJECT_ROOT, backup_dir_rel)
    os.makedirs(backup_dir, exist_ok=True)

    # 一時作業ディレクトリを作成（既存の場合はクリーンアップ）
    temp_backup_dir = os.path.join(backup_dir, f'{temp_dir_prefix}backup')
    if os.path.exists(temp_backup_dir):
        # 既存のものをクリーンアップ
        shutil.rmtree(temp_backup_dir)
    os.makedirs(temp_backup_dir)

    try:
        # --- 1. データベースのダンプ ---
        db_config = util.app_config.get('database', {})
        db_name = os.getenv('DB_NAME', db_config.get('name'))
        db_user = os.getenv('DB_USER', db_config.get('user'))
        db_password = os.getenv('DB_PASSWORD', db_config.get('password'))
        db_host = os.getenv('DB_HOST', db_config.get('host'))

        dump_filename = db_dump_filename_format.format(db_name=db_name)
        dump_filepath = os.path.join(temp_backup_dir, dump_filename)

        command = [
            'mysqldump',
            f'--host={db_host}',
            f'--user={db_user}',
            f'--password={db_password}',
            '--single-transaction',
            '--skip-ssl',
            '--routines',
            '--triggers',
            db_name
        ]
        with open(dump_filepath, 'w', encoding='utf-8') as f:
            process = subprocess.run(
                command, stdout=f, stderr=subprocess.PIPE, text=True)
            if process.returncode != 0:
                logging.error(f"mysqldump failed: {process.stderr}")
                return None

        # --- 2. 設定ファイルで指定されたディレクトリのコピー ---
        for src_rel_path in source_dirs:
            src_abs_path = os.path.join(PROJECT_ROOT, src_rel_path)
            if os.path.exists(src_abs_path):
                # `cp -a` の挙動を模倣し、ディレクトリ名を維持して一時ディレクトリ内にコピー
                dest_path = os.path.join(
                    temp_backup_dir, os.path.basename(src_rel_path))
                shutil.copytree(src_abs_path, dest_path)

        # --- 3. tar.gz形式でアーカイブ ---
        # タイムスタンプ付きのファイル名と、アーカイブ内のルートディレクトリ名を生成
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        archive_filename = archive_name_format.format(timestamp=timestamp)
        archive_filepath = os.path.join(backup_dir, archive_filename)
        archive_root_dir = archive_root_dir_format.format(timestamp=timestamp)

        with tarfile.open(archive_filepath, "w:gz") as tar:
            tar.add(temp_backup_dir, arcname=archive_root_dir)

        return archive_filename
    finally:
        # --- 4. 一時ディレクトリをクリーンアップ ---
        if os.path.exists(temp_backup_dir):
            shutil.rmtree(temp_backup_dir)


def restore_from_backup(filename):
    """指定されたバックアップファイルからデータをリストアします。

    この操作は現在のデータを上書きするため、非常に破壊的です。

    Args:
        filename (str): リストア対象のバックアップファイル名。

    Returns:
        bool: 成功した場合はTrue、失敗した場合はFalse。
    """
    # --- 設定ファイルからバックアップ設定を読み込む ---
    backup_config = util.app_config.get('backup', {})
    backup_dir_rel = backup_config.get('backup_directory', 'data/backups')
    temp_dir_prefix = backup_config.get('temp_directory_prefix', 'temp_')
    source_dirs = backup_config.get(
        'source_directories', ['data/attachments', 'setting'])
    db_dump_filename_format = backup_config.get(
        'db_dump_filename', 'dump_{db_name}.sql')

    backup_dir = os.path.join(PROJECT_ROOT, backup_dir_rel)
    archive_filepath = os.path.join(backup_dir, filename)

    if not os.path.exists(archive_filepath):
        logging.error(f"リストア失敗: バックアップファイルが見つかりません - {archive_filepath}")
        return False

    # 一時展開ディレクトリを作成
    temp_restore_dir = os.path.join(backup_dir, f'{temp_dir_prefix}restore')
    if os.path.exists(temp_restore_dir):
        shutil.rmtree(temp_restore_dir)
    os.makedirs(temp_restore_dir)

    try:
        # --- 1. バックアップファイルを一時ディレクトリに展開 ---
        with tarfile.open(archive_filepath, "r:gz") as tar:
            tar.extractall(path=temp_restore_dir)

        # 展開されたディレクトリ名を取得 (backup_YYYYMMDD_HHMMSS のような名前のはず)
        extracted_dirs = [d for d in os.listdir(
            temp_restore_dir) if os.path.isdir(os.path.join(temp_restore_dir, d))]
        if not extracted_dirs:
            logging.error("リストア失敗: バックアップアーカイブ内にディレクトリが見つかりません。")
            return False

        content_dir = os.path.join(temp_restore_dir, extracted_dirs[0])

        # --- 2. データベースのリストア ---
        db_config = util.app_config.get('database', {})
        db_name = os.getenv('DB_NAME', db_config.get('name'))
        db_user = os.getenv('DB_USER', db_config.get('user'))
        db_password = os.getenv('DB_PASSWORD', db_config.get('password'))
        db_host = os.getenv('DB_HOST', db_config.get('host'))

        dump_filename = db_dump_filename_format.format(db_name=db_name)
        dump_filepath = os.path.join(content_dir, dump_filename)

        if not os.path.exists(dump_filepath):
            logging.error(
                f"リストア失敗: データベースダンプファイルが見つかりません - {dump_filepath}")
            return False

        # mysqlコマンドでリストア
        command = ['mysql', f'--host={db_host}',
                   f'--user={db_user}', f'--password={db_password}', '--skip-ssl', db_name]
        with open(dump_filepath, 'r', encoding='utf-8') as f:
            process = subprocess.run(
                command, stdin=f, capture_output=True, text=True)
            if process.returncode != 0:
                logging.error(f"mysqlコマンドでのリストアに失敗しました: {process.stderr}")
                return False
        logging.info("データベースのリストアが完了しました。")

        # --- 3. 設定ファイルで指定されたディレクトリのリストア ---

        for src_rel_path in source_dirs:
            dest_abs_path = os.path.join(PROJECT_ROOT, src_rel_path)
            backup_src_path = os.path.join(
                content_dir, os.path.basename(src_rel_path))

            # ディレクトリが存在しない場合は作成
            os.makedirs(dest_abs_path, exist_ok=True)

            # 既存のディレクトリの中身をクリア
            if os.path.exists(dest_abs_path):
                for item in os.listdir(dest_abs_path):
                    item_path = os.path.join(dest_abs_path, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)

            # バックアップから新しい内容をコピー
            if os.path.exists(backup_src_path) and os.path.isdir(backup_src_path):
                shutil.copytree(backup_src_path, dest_abs_path,
                                dirs_exist_ok=True)
                logging.info(f"'{src_rel_path}' をリストアしました。")

        return True

    except Exception as e:
        logging.error(f"リストア処理中にエラーが発生しました: {e}", exc_info=True)
        return False
    finally:
        # --- 4. 一時ディレクトリをクリーンアップ ---
        if os.path.exists(temp_restore_dir):
            shutil.rmtree(temp_restore_dir)


def wipe_all_data():
    """全てのBBSデータを削除し、システムを初期状態に戻します。

    この操作は元に戻せません。

    - 添付ファイルや設定ファイルなど、指定されたディレクトリを削除します。
    - データベースの全テーブルを削除します。
    - データベースを再初期化し、シスオペアカウントを再作成します。

    Returns:
        bool: 成功した場合はTrue、失敗した場合はFalse。
    """
    try:
        # --- 1. 対象ディレクトリを削除 ---
        backup_config = util.app_config.get('backup', {})
        # wipe対象はバックアップ対象と同じディレクトリ群とする
        dirs_to_wipe = backup_config.get(
            'source_directories', ['data/attachments', 'setting'])

        # 1. 対象ディレクトリを削除
        for dir_rel_path in dirs_to_wipe:
            abs_path = os.path.join(PROJECT_ROOT, dir_rel_path)
            if os.path.exists(abs_path):
                shutil.rmtree(abs_path)

        # --- 2. データベースの全テーブルを削除 ---
        db_config = util.app_config.get('database', {})
        db_name = os.getenv('DB_NAME', db_config.get('name'))

        conn = None
        try:
            conn = database.get_connection()
            cursor = conn.cursor()

            # 外部キー制約を一時的に無効化
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")

            # 全テーブル名を取得
            cursor.execute("SHOW TABLES;")
            tables = [table[0] for table in cursor.fetchall()]

            # 全テーブルを削除
            if tables:
                logging.info(f"Dropping tables: {', '.join(tables)}")
                for table in tables:
                    cursor.execute(f"DROP TABLE IF EXISTS `{table}`;")
                logging.info("All database tables dropped.")

            # 外部キー制約を再度有効化
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            conn.commit()
        finally:
            if conn:
                conn.close()

        # --- 3. データベースの再初期化 ---
        logging.info("Re-initializing database...")
        sysop_id = os.getenv('GRASSROOTSBBS_SYSOP_ID')
        sysop_password = os.getenv('GRASSROOTSBBS_SYSOP_PASSWORD')
        sysop_email = os.getenv('GRASSROOTSBBS_SYSOP_EMAIL')

        util.initialize_database_and_sysop(
            sysop_id, sysop_password, sysop_email)
        logging.info("Database re-initialized successfully.")

        return True

    except Exception as e:
        logging.error(f"Data wipe process failed: {e}", exc_info=True)
        return False


def cleanup_old_backups():
    """古いバックアップファイルをクリーンアップします。"""
    server_prefs = database.read_server_pref()
    max_backups_setting = server_prefs.get('max_backups', 0)

    if max_backups_setting <= 0:
        logging.info("バックアップの自動クリーンアップは無効です (max_backups <= 0)。")
        return

    backup_config = util.app_config.get('backup', {})
    backup_dir_rel = backup_config.get('backup_directory', 'data/backups')
    backup_dir = os.path.join(PROJECT_ROOT, backup_dir_rel)

    if not os.path.isdir(backup_dir):
        return

    try:
        # バックアップディレクトリ内の .tar.gz ファイルを更新日時の降順（新しいものが先）でソート
        backups = [
            f for f in os.listdir(backup_dir)
            if f.endswith('.tar.gz') and os.path.isfile(os.path.join(backup_dir, f))  # noqa
        ]
        backups.sort(key=lambda f: os.path.getmtime(
            os.path.join(backup_dir, f)), reverse=True)

        # 保持する数を超えたものを削除 (max_backups_setting は保持する数)
        if len(backups) > max_backups_setting:
            files_to_delete = backups[max_backups_setting:]
            logging.info(
                f"{len(files_to_delete)}件の古いバックアップを削除します: {files_to_delete}")
            for filename in files_to_delete:
                try:
                    os.remove(os.path.join(backup_dir, filename))
                except OSError as e:
                    logging.error(f"古いバックアップファイル '{filename}' の削除に失敗しました: {e}")
    except Exception as e:
        logging.error(f"バックアップのクリーンアップ中にエラーが発生しました: {e}", exc_info=True)
