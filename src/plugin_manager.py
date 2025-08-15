# -*- coding: utf-8 -*-

import os
import importlib
import importlib.util
from gevent import Timeout
import logging
import toml

from .grbbs_api import GrbbsApi
# このファイルの絶対パスから、プロジェクトのルートディレクトリを特定します。
_current_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_current_dir)
PLUGINS_DIR = os.path.join(PROJECT_ROOT, 'plugins')

# ロードされたプラグインを格納する辞書
# { 'plugin_dir_name': {'module': module, 'name': 'Plugin Name', 'description': '...'} }
_loaded_plugins = {}


def load_plugins():
    """
    'plugins' ディレクトリをスキャンし、有効なプラグインをロードする。
    """
    global _loaded_plugins
    _loaded_plugins = {}
    logging.info("プラグインの読み込みを開始します...")

    if not os.path.isdir(PLUGINS_DIR):
        logging.warning(f"プラグインディレクトリが見つかりません: {PLUGINS_DIR}")
        return

    for item in os.listdir(PLUGINS_DIR):
        plugin_dir = os.path.join(PLUGINS_DIR, item)
        metadata_path = os.path.join(plugin_dir, 'plugin.toml')

        if os.path.isdir(plugin_dir) and os.path.exists(metadata_path):
            plugin_id = item
            try:
                # 1. メタデータを先に読み込む
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = toml.load(f)

                # 2. 依存関係をチェック
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

                # 3. 依存関係が満たされていれば、モジュールをインポート
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
    """
    ロード済みのプラグインのリストを返す。
    メニュー表示用に整形された辞書のリスト。
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


def run_plugin(plugin_id, context):
    """
    指定されたIDのプラグインを実行する。
    """
    # プラグインの実行時間にタイムアウトを設定 (例: 60秒)
    TIMEOUT_SECONDS = 60

    plugin_data = _loaded_plugins.get(plugin_id)
    if not plugin_data:
        logging.error(f"実行しようとしたプラグイン '{plugin_id}' が見つかりません。")
        return False

    logging.info(
        f"プラグイン '{plugin_data['name']}' を実行します (タイムアウト: {TIMEOUT_SECONDS}秒)...")

    # プラグインに渡すコンテキストを再構築し、安全なAPIのみを公開する
    api = GrbbsApi(context['chan'])
    safe_context = {
        'api': api,
        'login_id': context.get('login_id'),
        'display_name': context.get('display_name'),
        'user_id': context.get('user_id'),
        'user_level': context.get('userlevel'),
    }

    try:
        with Timeout(TIMEOUT_SECONDS):
            plugin_data['module'].run(safe_context)
        logging.info(f"プラグイン '{plugin_data['name']}' の実行が完了しました。")
        return True
    except Timeout:
        logging.error(f"プラグイン '{plugin_data['name']}' がタイムアウトしました。実行を強制終了します。")
        api.send(
            f"\r\nエラー: プログラムが時間内に応答しませんでした。({TIMEOUT_SECONDS}秒)\r\n".encode('utf-8'))
        return False
