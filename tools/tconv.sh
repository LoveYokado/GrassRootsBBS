#!/bin/bash
find . -type f -print0 | while IFS= read -r -d $'¥0' file; do
  echo "Converting: $file"
  iconv -f SHIFT-JIS -t UTF-8 "$file" -o "$file.temp" && mv "$file.temp" "$file"
done
