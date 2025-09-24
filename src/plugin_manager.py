# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""
プラグインマネージャ

このモジュールは、プラグインの発見、読み込み、実行を担当します。
専用の 'plugins' ディレクトリをスキャンし、各プラグインの 'plugin.toml'
ファイルからメタデータを読み込み、依存関係をチェックし、ホストアプリケーションと
安全に対話するためのサンドボックス化されたAPIを提供します。
"""

import os
import importlib
import importlib.util
from gevent import Timeout
import logging
import toml

from .grbbs_api import GrbbsApi
from . import database, util

# --- Constants and Global State / 定数とグローバル状態 ---
_current_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_current_dir)
PLUGINS_DIR = os.path.join(PROJECT_ROOT, 'plugins')

# ロードされたプラグインを格納する辞書
# { 'plugin_dir_name': {'module': module, 'name': 'Plugin Name', ...} }
_loaded_plugins = {}


def load_plugins():
    """
    Scans the 'plugins' directory, reads metadata, checks dependencies and
    database settings, and loads all valid and enabled plugins.
    'plugins' ディレクトリをスキャンし、メタデータ、依存関係、DB設定をチェックして、
    有効なすべてのプラグインをロードします。
    """
    global _loaded_plugins
    _loaded_plugins = {}
    logging.info("プラグインの読み込みを開始します...")

    if not os.path.isdir(PLUGINS_DIR):
        logging.warning(f"プラグインディレクトリが見つかりません: {PLUGINS_DIR}")
        return

    # 1. DBから現在のプラグイン設定を取得
    plugin_settings = database.get_all_plugin_settings()

    for item in os.listdir(PLUGINS_DIR):
        plugin_dir = os.path.join(PLUGINS_DIR, item)
        metadata_path = os.path.join(plugin_dir, 'plugin.toml')

        if os.path.isdir(plugin_dir) and os.path.exists(metadata_path):
            plugin_id = item
            try:
                # 2. DB設定を確認。なければデフォルトで有効化し、DBに登録。
                is_enabled = plugin_settings.get(plugin_id, True)
                if plugin_id not in plugin_settings:
                    database.upsert_plugin_setting(plugin_id, True)

                if not is_enabled:
                    logging.info(
                        f"Plugin '{plugin_id}' is disabled, skipping.")
                    continue

                # 3. プラグインのメタデータを読み込み
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = toml.load(f)

                # 4. 依存関係をチェック
                requirements = metadata.get('requirements', [])
                is_loadable = True
                for req in requirements:
                    if importlib.util.find_spec(req) is None:
                        logging.warning(
                            f"プラグイン '{metadata.get('name', plugin_id)}' の依存ライブラリ '{req}' が見つかりません。このプラグインは無効化されます。")
                        is_loadable = False
                        break

                if not is_loadable:
                    continue

                # 5. 依存関係が満たされていれば、モジュールをインポート
                module_name = metadata.get('entry_point')
                if not module_name:
                    logging.warning(
                        f"プラグイン '{plugin_id}' の 'plugin.toml' に 'entry_point' がありません。")
                    continue

                plugin_module = importlib.import_module(module_name)

                if hasattr(plugin_module, 'run') and callable(plugin_module.run):
                    _loaded_plugins[plugin_id] = {
                        'module': plugin_module,
                        'name': metadata.get('name', plugin_id),
                        'description': metadata.get('description', ''),
                    }
                    logging.info(
                        f"プラグイン '{metadata.get('name', plugin_id)}' ({plugin_id}) を正常にロードしました。")
                else:
                    logging.warning(
                        f"プラグイン '{plugin_id}' のモジュール '{module_name}' に実行可能な 'run' 関数がありません。")

            except (ImportError, toml.TomlDecodeError) as e:
                logging.error(f"プラグイン '{plugin_id}' の読み込みに失敗しました: {e}")
            except Exception as e:
                logging.error(
                    f"プラグイン '{plugin_id}' の読み込み中に予期せぬエラーが発生しました: {e}", exc_info=True)

    logging.info(f"{len(_loaded_plugins)}個のプラグインをロードしました。")


def get_loaded_plugins():
    """ロード済みのプラグインのリストをメニュー表示用に整形して返します。"""
    plugins_list = []
    for plugin_id, plugin_data in _loaded_plugins.items():
        plugins_list.append({
            'id': plugin_id,
            'name': plugin_data['name'],
            'description': plugin_data['description']
        })
    # 名前順でソートして返す
    return sorted(plugins_list, key=lambda p: p['name'])


def run_plugin(plugin_id, context):
    """
    指定されたIDのプラグインを実行します。
    プラグインには、機能が制限された安全なAPIを持つコンテキストが提供されます。
    実行は config.toml で定義されたタイムアウトの対象となります。
    """
    # config.tomlからタイムアウト値を取得
    plugins_config = util.app_config.get('plugins', {})
    timeout_seconds = plugins_config.get('execution_timeout', 60)

    plugin_data = _loaded_plugins.get(plugin_id)
    if not plugin_data:
        logging.error(f"実行しようとしたプラグイン '{plugin_id}' が見つかりません。")
        return False

    logging.info(
        f"プラグイン '{plugin_data['name']}' を実行します (タイムアウト: {timeout_seconds}秒)...")

    # プラグインに安全なAPIを提供するためにコンテキストを再構築
    api = GrbbsApi(context.chan)
    safe_context = {
        'api': api,
        'login_id': context.login_id,
        'display_name': context.display_name,
        'user_id': context.user_id,
        'user_level': context.user_level,
    }

    try:
        with Timeout(timeout_seconds):
            plugin_data['module'].run(safe_context)
        logging.info(f"プラグイン '{plugin_data['name']}' の実行が完了しました。")
        return True
    except Timeout:
        logging.error(f"プラグイン '{plugin_data['name']}' がタイムアウトしました。実行を強制終了します。")
        api.send(
            f"\r\nエラー: プログラムが時間内に応答しませんでした。({timeout_seconds}秒)\r\n".encode('utf-8'))
        return False


def get_all_available_plugins():
    """
    'plugins' ディレクトリをスキャンし、利用可能な全てのプラグインの情報を返します。
    DBから取得した有効/無効の状態も含まれます。
    この関数は管理画面で使用されます。
    """
    available_plugins = []
    if not os.path.isdir(PLUGINS_DIR):
        return []

    plugin_settings = database.get_all_plugin_settings()

    for item in os.listdir(PLUGINS_DIR):
        plugin_dir = os.path.join(PLUGINS_DIR, item)
        metadata_path = os.path.join(plugin_dir, 'plugin.toml')

        if os.path.isdir(plugin_dir) and os.path.exists(metadata_path):
            plugin_id = item
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = toml.load(f)

                is_enabled = plugin_settings.get(plugin_id, True)

                available_plugins.append({
                    'id': plugin_id,
                    'name': metadata.get('name', plugin_id),
                    'description': metadata.get('description', ''),
                    'is_enabled': is_enabled,
                })
            except Exception as e:
                logging.error(f"プラグイン '{plugin_id}' のメタデータ読み込みに失敗: {e}")
                continue

    return sorted(available_plugins, key=lambda p: p['name'])
