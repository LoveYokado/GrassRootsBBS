# /home/yuki/python/GrassRootsBBS/src/backup_util.py

import os
import datetime
import subprocess
import tarfile
import shutil
import logging
from . import util

# プロジェクトルートの絶対パスを取得
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def create_backup():
    """
    データベース、添付ファイル、設定ファイルをまとめてバックアップする。
    :return: 作成されたバックアップファイル名。失敗した場合はNone。
    """
    # バックアップディレクトリ
    backup_dir = os.path.join(PROJECT_ROOT, 'data', 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    # 一時作業ディレクトリ
    temp_backup_dir = os.path.join(backup_dir, 'temp_backup')
    if os.path.exists(temp_backup_dir):
        # 既存のものをクリーンアップ
        shutil.rmtree(temp_backup_dir)
    os.makedirs(temp_backup_dir)

    try:
        # 1. データベースのダンプ
        db_config = util.app_config.get('database', {})
        db_name = os.getenv('DB_NAME', db_config.get('name'))
        db_user = os.getenv('DB_USER', db_config.get('user'))
        db_password = os.getenv('DB_PASSWORD', db_config.get('password'))
        db_host = os.getenv('DB_HOST', db_config.get('host'))

        dump_filename = f"dump_{db_name}.sql"
        dump_filepath = os.path.join(temp_backup_dir, dump_filename)

        # mysqldumpコマンドの実行
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

        # 2. 添付ファイルと設定ファイルのコピー
        attachments_path = os.path.join(PROJECT_ROOT, 'data', 'attachments')
        settings_path = os.path.join(PROJECT_ROOT, 'setting')

        if os.path.exists(attachments_path):
            subprocess.run(['cp', '-a', attachments_path, temp_backup_dir])
        if os.path.exists(settings_path):
            subprocess.run(['cp', '-a', settings_path, temp_backup_dir])

        # 3. tar.gzにアーカイブ
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        archive_filename = f"grbbs_backup_{timestamp}.tar.gz"
        archive_filepath = os.path.join(backup_dir, archive_filename)

        with tarfile.open(archive_filepath, "w:gz") as tar:
            tar.add(temp_backup_dir, arcname=os.path.basename(
                f"backup_{timestamp}"))

        return archive_filename
    finally:
        # 一時ディレクトリをクリーンアップ
        if os.path.exists(temp_backup_dir):
            shutil.rmtree(temp_backup_dir)


def restore_from_backup(filename):
    """
    指定されたバックアップファイルからリストアを実行する。
    :param filename: リストアするバックアップファイル名 (e.g., 'grbbs_backup_20250101_120000.tar.gz')
    :return: 成功した場合はTrue、失敗した場合はFalse。
    """
    backup_dir = os.path.join(PROJECT_ROOT, 'data', 'backups')
    archive_filepath = os.path.join(backup_dir, filename)

    if not os.path.exists(archive_filepath):
        logging.error(f"リストア失敗: バックアップファイルが見つかりません - {archive_filepath}")
        return False

    # 一時展開ディレクトリ
    temp_restore_dir = os.path.join(backup_dir, 'temp_restore')
    if os.path.exists(temp_restore_dir):
        shutil.rmtree(temp_restore_dir)
    os.makedirs(temp_restore_dir)

    try:
        # 1. バックアップファイルを展開
        with tarfile.open(archive_filepath, "r:gz") as tar:
            tar.extractall(path=temp_restore_dir)

        # 展開されたディレクトリ名を取得 (backup_YYYYMMDD_HHMMSS のような名前のはず)
        extracted_dirs = [d for d in os.listdir(
            temp_restore_dir) if os.path.isdir(os.path.join(temp_restore_dir, d))]
        if not extracted_dirs:
            logging.error("リストア失敗: バックアップアーカイブ内にディレクトリが見つかりません。")
            return False

        content_dir = os.path.join(temp_restore_dir, extracted_dirs[0])

        # 2. データベースのリストア
        db_config = util.app_config.get('database', {})
        db_name = os.getenv('DB_NAME', db_config.get('name'))
        db_user = os.getenv('DB_USER', db_config.get('user'))
        db_password = os.getenv('DB_PASSWORD', db_config.get('password'))
        db_host = os.getenv('DB_HOST', db_config.get('host'))

        dump_filename = f"dump_{db_name}.sql"
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

        # 3. 添付ファイルと設定ファイルのリストア
        # まず既存のものを削除
        attachments_path = os.path.join(PROJECT_ROOT, 'data', 'attachments')
        settings_path = os.path.join(PROJECT_ROOT, 'setting')
        if os.path.exists(attachments_path):
            shutil.rmtree(attachments_path)
        if os.path.exists(settings_path):
            shutil.rmtree(settings_path)

        # バックアップからコピー
        backup_attachments_path = os.path.join(content_dir, 'attachments')
        backup_settings_path = os.path.join(content_dir, 'setting')
        if os.path.exists(backup_attachments_path):
            shutil.copytree(backup_attachments_path, attachments_path)
            logging.info("添付ファイルをリストアしました。")
        if os.path.exists(backup_settings_path):
            shutil.copytree(backup_settings_path, settings_path)
            logging.info("設定ファイルをリストアしました。")

        return True

    except Exception as e:
        logging.error(f"リストア処理中にエラーが発生しました: {e}", exc_info=True)
        return False
    finally:
        # 一時ディレクトリをクリーンアップ
        if os.path.exists(temp_restore_dir):
            shutil.rmtree(temp_restore_dir)


def wipe_all_data():
    """
    すべてのBBSデータを削除し、初期状態に戻す。
    - 添付ファイルの削除
    - データベーステーブルの全削除
    - データベースの再初期化（テーブル作成とシスオペ再登録）
    :return: 成功した場合はTrue、失敗した場合はFalse。
    """
    try:
        # 1. 添付ファイルの削除
        attachments_path = os.path.join(PROJECT_ROOT, 'data', 'attachments')
        if os.path.exists(attachments_path):
            logging.info("Deleting all attachments...")
            shutil.rmtree(attachments_path)
            os.makedirs(attachments_path)  # Recreate empty directory
            logging.info("All attachments deleted.")

        # 2. データベースの全テーブルを削除
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

        # 3. データベースの再初期化
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
    """
    古いバックアップファイルをクリーンアップする。
    設定ファイルに基づいて保持する数を決定する。
    """
    scheduler_config = util.app_config.get('scheduler', {})
    max_backups = scheduler_config.get('max_backups', 0)

    if max_backups <= 0:
        logging.info("バックアップの自動クリーンアップは無効です (max_backups <= 0)。")
        return

    backup_dir = os.path.join(PROJECT_ROOT, 'data', 'backups')
    if not os.path.isdir(backup_dir):
        return

    try:
        # バックアップファイル一覧を取得し、更新日時でソート
        backups = [
            f for f in os.listdir(backup_dir)
            if f.endswith('.tar.gz') and os.path.isfile(os.path.join(backup_dir, f))
        ]
        backups.sort(key=lambda f: os.path.getmtime(
            os.path.join(backup_dir, f)), reverse=True)

        # 保持する数を超えたものを削除
        if len(backups) > max_backups:
            files_to_delete = backups[max_backups:]
            logging.info(
                f"{len(files_to_delete)}件の古いバックアップを削除します: {files_to_delete}")
            for filename in files_to_delete:
                try:
                    os.remove(os.path.join(backup_dir, filename))
                except OSError as e:
                    logging.error(f"古いバックアップファイル '{filename}' の削除に失敗しました: {e}")
    except Exception as e:
        logging.error(f"バックアップのクリーンアップ中にエラーが発生しました: {e}", exc_info=True)
