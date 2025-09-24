#!/bin/bash
#
# Shift-JISからUTF-8への一括文字コード変換スクリプト
#
# カレントディレクトリ以下の全ファイルを対象に、文字コードを
# Shift-JISからUTF-8へ変換します。
# 注意: この操作は元に戻せません。実行前に必ずバックアップを取得してください。

find . -type f -print0 | while IFS= read -r -d $'¥0' file; do
  echo "Converting: $file"
  iconv -f SHIFT-JIS -t UTF-8 "$file" -o "$file.temp" && mv "$file.temp" "$file"
done
