# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""プラグインマネージャーモジュール。

このモジュールは、プラグインの発見、読み込み、実行を担当します。
`plugins`ディレクトリをスキャンし、各プラグインの`plugin.toml`メタデータに基づいて
動的にモジュールをロードします。また、プラグインを安全な環境で実行するための
タイムアウト処理やAPIの提供も行います。
"""

import os
import importlib
import importlib.util
from gevent import Timeout
import logging
import sys
import toml

from .grbbs_api import GrbbsApi
from . import database, util

# --- 定数とグローバル状態 ---
_current_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_current_dir)
PLUGINS_DIR = os.path.join(PROJECT_ROOT, 'plugins')

# ロード済みのプラグイン情報を格納するグローバル辞書。
# 形式: { 'plugin_dir_name': {'module': module, 'name': 'Plugin Name', ...} }
_loaded_plugins = {}


def load_plugins():
    """'plugins' ディレクトリをスキャンし、有効な全てのプラグインをロードします。"""
    global _loaded_plugins
    _loaded_plugins = {}
    logging.info("プラグインの読み込みを開始します...")

    if not os.path.isdir(PLUGINS_DIR):
        logging.warning(f"プラグインディレクトリが見つかりません: {PLUGINS_DIR}")
        return

    # データベースから現在のプラグイン設定を一括で取得
    plugin_settings = database.get_all_plugin_settings()

    for item in os.listdir(PLUGINS_DIR):
        plugin_dir = os.path.join(PLUGINS_DIR, item)
        metadata_path = os.path.join(plugin_dir, 'plugin.toml')

        if os.path.isdir(plugin_dir) and os.path.exists(metadata_path):
            plugin_id = item
            try:
                is_enabled = plugin_settings.get(plugin_id, True)

                if not is_enabled:
                    logging.info(
                        f"Plugin '{plugin_id}' is disabled, skipping.")
                    continue

                # プラグインのメタデータ(plugin.toml)を読み込み
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = toml.load(f)

                # 依存ライブラリがインストールされているかチェック
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

                # エントリーポイントとして指定されたモジュールを動的にインポート
                module_name = metadata.get('entry_point')
                if not module_name:
                    logging.warning(
                        f"プラグイン '{plugin_id}' の 'plugin.toml' に 'entry_point' がありません。")
                    continue

                if module_name in sys.modules:
                    plugin_module = importlib.reload(sys.modules[module_name])
                else:
                    plugin_module = importlib.import_module(module_name)

                if hasattr(plugin_module, 'run') and callable(plugin_module.run):
                    _loaded_plugins[plugin_id] = {
                        'module': plugin_module,
                        'name': metadata.get('name', plugin_id),
                        'description': metadata.get('description', ''),
                        'timeout': metadata.get('timeout'),
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
    """ロード済みのプラグインのリストをメニュー表示用に整形して返します。

    Returns:
        list[dict]: プラグイン情報の辞書のリスト。
                    各辞書は 'id', 'name', 'description' を含みます。
    """
    plugins_list = []
    for plugin_id, plugin_data in _loaded_plugins.items():
        plugins_list.append({
            'id': plugin_id,
            'name': plugin_data['name'],
            'description': plugin_data['description']
        })
    # 名前順でソートして返す
    return sorted(plugins_list, key=lambda p: p['name'])


def run_plugin(app, plugin_id, context):
    """指定されたIDのプラグインを実行します。

    プラグインに`GrbbsApi`を提供し、タイムアウトを設定した上で、
    サンドボックス化された環境で`run`関数を呼び出します。

    Args:
        app (Flask): Flaskアプリケーションインスタンス。
        plugin_id (str): 実行するプラグインのID（ディレクトリ名）。
        context (CommandContext): コマンド実行コンテキスト。
    """
    plugin_data = _loaded_plugins.get(plugin_id)
    if not plugin_data:
        logging.error(f"実行しようとしたプラグイン '{plugin_id}' が見つかりません。")
        return False

    # プラグインに渡すコンテキストを再構築し、安全なAPIのみを公開
    api = GrbbsApi(app, context.chan, plugin_id, context.online_members_func)
    safe_context = {
        'api': api,
        'login_id': context.login_id,
        'display_name': context.display_name,
        'user_id': context.user_id,
        'user_level': context.user_level,
        # プラグインが自身のIDを知るためにコンテキストに追加
        'plugin_id': plugin_id,
    }

    # --- タイムアウト設定の解決 ---
    plugin_timeout_setting = plugin_data.get('timeout')
    timeout_seconds = None  # デフォルトはタイムアウトなし

    if plugin_timeout_setting == "none":
        timeout_seconds = None  # タイムアウトを無効化
    elif isinstance(plugin_timeout_setting, int):
        timeout_seconds = plugin_timeout_setting  # プラグイン指定の秒数
    else:
        # 未設定の場合はDBからグローバル設定を読み込む
        server_prefs = database.read_server_pref()
        # DBに設定がなければデフォルトで60秒
        timeout_seconds = server_prefs.get('plugin_execution_timeout', 60)

    logging.info(
        f"プラグイン '{plugin_data['name']}' を実行します (タイムアウト: {timeout_seconds if timeout_seconds is not None else 'なし'})...")

    try:
        if timeout_seconds is None:
            # タイムアウトなしで実行
            plugin_data['module'].run(safe_context)
        else:
            # 指定された秒数でタイムアウトを設定して実行
            with Timeout(timeout_seconds):
                plugin_data['module'].run(safe_context)
        logging.info(f"プラグイン '{plugin_data['name']}' の実行が完了しました。")
        return True
    except Timeout:
        logging.error(
            f"プラグイン '{plugin_data['name']}' がタイムアウト({timeout_seconds}秒)しました。実行を強制終了します。")
        api.send(
            f"\r\nエラー: プログラムが時間内に応答しませんでした。({timeout_seconds}秒)\r\n".encode('utf-8'))
        return False


def get_all_available_plugins():
    """利用可能な全てのプラグインの情報を、DBの有効/無効状態と合わせて返します。

    Returns:
        list[dict]: 利用可能な全プラグイン情報のリスト。
                    各辞書は 'id', 'name', 'description', 'is_enabled' を含みます。
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
