import os
import re
import yaml  # PyYAMLが必要です (pip install PyYAML)
import argparse
import logging

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# get_text_by_key や send_text_by_key で使用されるキーを抽出する正規表現
# 例: get_text_by_key(chan, "some.key.name", ...)
#     send_text_by_key(chan, 'another.key', ...)
KEY_USAGE_REGEX = re.compile(
    r"(?:get_text_by_key|send_text_by_key)\s*\("  # 関数名と開き括弧
    r"[^,]+,\s*"                                 # 第1引数とカンマ
    r"(?:\"([^\"]+)\"|\'([^\']+)\')"             # キー文字列 (ダブルまたはシングルクォート)
    # 後続の引数はキャプチャしない
)


def get_defined_keys_from_yaml(data_dict, path_prefix_list=None):
    """
    YAMLデータからtextdataキーのセットを再帰的に抽出する。
    キーは 'feature.element' のような形式で、mode_X を含まない。
    """
    if path_prefix_list is None:
        path_prefix_list = []

    found_keys = set()

    if not isinstance(data_dict, dict):
        return found_keys

    for key, value in data_dict.items():
        current_path_list = path_prefix_list + [key]

        if isinstance(value, dict):
            # この辞書が 'mode_X' キーのみを子として持つか確認
            is_mode_specific_node = False
            if value:  # 空の辞書でないこと
                is_mode_specific_node = all(
                    k.startswith('mode_') for k in value.keys())

            if is_mode_specific_node:
                # このパスが get_text_by_key で使用されるキー
                found_keys.add(".".join(current_path_list))
            else:
                # mode_X で終わるノードでなければ、さらに深く探索
                found_keys.update(get_defined_keys_from_yaml(
                    value, current_path_list))
        # valueが辞書でない場合は、テキストキーの終端ではないと判断

    return found_keys


def find_specific_key_in_file(file_path, key_to_find):
    """指定されたPythonファイル内で特定のtextdataキーが使用されているか検索する"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 正規表現でキーの使用箇所を検索
            # KEY_USAGE_REGEX は get_text_by_key("key") または send_text_by_key('key') の形式にマッチ
            # マッチしたキーが key_to_find と一致するか確認
            matches = KEY_USAGE_REGEX.findall(content)
            for match in matches:
                used_key = match[0] if match[0] else match[1]
                if used_key == key_to_find:
                    return True  # キーが見つかった
    except Exception as e:
        logging.error(f"ファイル読み込みまたは解析エラー {file_path}: {e}")
    return False  # キーが見つからなかった


def find_used_keys_in_py_file(file_path):
    """指定されたPythonファイル内で使用されているtextdataキーを検索する"""
    used_keys = set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            matches = KEY_USAGE_REGEX.findall(content)
            for match in matches:
                # match はタプル (例: ('key.from.double', '') または ('', 'key.from.single'))
                key = match[0] if match[0] else match[1]
                if key:
                    used_keys.add(key)
    except Exception as e:
        logging.error(f"ファイル読み込みまたは解析エラー {file_path}: {e}")
    return used_keys


def find_files_using_key(directory, key_to_find):
    """指定されたディレクトリ内の全Pythonファイルで特定のtextdataキーを検索し、
       使用されているファイルのリストを返す"""
    found_in_files = []
    if key_to_find is None:  # key_to_find が None の場合は何もしない (またはエラーを出す)
        return found_in_files
    for root, _, files in os.walk(directory):
        for file_name in files:
            if file_name.endswith(".py"):
                file_path = os.path.join(root, file_name)
                if find_specific_key_in_file(file_path, key_to_find):
                    found_in_files.append(file_path)
    return found_in_files


def find_used_keys_in_directory(directory):
    """指定されたディレクトリ内の全Pythonファイルで使用されているtextdataキーを検索する"""
    all_used_keys = set()
    for root, _, files in os.walk(directory):
        for file_name in files:
            if file_name.endswith(".py"):
                file_path = os.path.join(root, file_name)
                all_used_keys.update(find_used_keys_in_py_file(file_path))
    return all_used_keys


def main():
    parser = argparse.ArgumentParser(
        description="textdata.yaml 内の未使用キーをPythonプロジェクトから検索します。")
    parser.add_argument("project_root", nargs='?', default='.',
                        help="プロジェクトのルートディレクトリパス (デフォルト: カレントディレクトリ)")
    parser.add_argument("--yaml_file", default="text/textdata.yaml",
                        help="プロジェクトルートからのtextdata.yamlファイルへの相対パス (デフォルト: text/textdata.yaml)")
    parser.add_argument("--find_key", type=str, default=None,
                        help="指定したキーがどのPythonファイルで使用されているかを検索します。")

    args = parser.parse_args()

    project_root = os.path.abspath(args.project_root)
    yaml_file_path = os.path.join(project_root, args.yaml_file)

    if not os.path.isdir(project_root):
        logging.error(f"プロジェクトルートディレクトリが見つかりません: {project_root}")
        return

    if args.find_key:
        key_to_search = args.find_key
        logging.info(f"キー '{key_to_search}' をPythonファイル内で検索中: {project_root}")
        files_using_key = find_files_using_key(project_root, key_to_search)

        if files_using_key:
            print(f"\nキー '{key_to_search}' は以下のファイルで使用されています:")
            for file_path in files_using_key:
                # プロジェクトルートからの相対パスで表示
                relative_path = os.path.relpath(file_path, project_root)
                print(f"  - {relative_path}")
        else:
            print(f"\nキー '{key_to_search}' はプロジェクト内のPythonファイルでは使用されていませんでした。")
        return  # キー検索モードの場合はここで終了

    if not os.path.isfile(yaml_file_path):
        logging.error(f"YAMLファイルが見つかりません: {yaml_file_path}")
        return

    try:
        with open(yaml_file_path, 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)
    except Exception as e:
        logging.error(f"YAMLファイル読み込みエラー {yaml_file_path}: {e}")
        return

    if not yaml_data:
        logging.warning(f"YAMLファイル {yaml_file_path} が空または無効です。")
        return

    logging.info(f"YAMLファイルをスキャン中: {yaml_file_path}")
    defined_keys = get_defined_keys_from_yaml(yaml_data)
    logging.info(f"{len(defined_keys)} 個のキーがYAMLに定義されています。")

    logging.info(f"Pythonファイルをスキャン中: {project_root}")
    used_keys_in_code = find_used_keys_in_directory(project_root)
    logging.info(f"{len(used_keys_in_code)} 個のユニークなキーがコード中で使用されています。")

    unused_keys = defined_keys - used_keys_in_code

    print("\n--- 解析結果 ---")
    if unused_keys:
        print(f"\n{len(unused_keys)} 個の未使用キーが {args.yaml_file} に見つかりました:")
        for key in sorted(list(unused_keys)):
            print(f"  - {key}")
    else:
        print(f"\n{args.yaml_file} に定義されている全てのキーはコード中で使用されているようです。")

    # コード中で使用されているがYAMLに定義されていないキー（おまけ）
    keys_used_not_defined = used_keys_in_code - defined_keys
    if keys_used_not_defined:
        print(
            f"\n{len(keys_used_not_defined)} 個のキーがコード中で使用されていますが、{args.yaml_file} に定義されていません (タイプミスや定義漏れの可能性):")
        for key in sorted(list(keys_used_not_defined)):
            print(f"  - {key}")


if __name__ == "__main__":
    main()
