#!/bin/bash
# 监视 ~/wcu-inbox，出现 .bundle 就自动导入工作副本。
#
#   ./scripts/watch-inbox.sh
#
# 传输通道随你：微信 / 网盘 / U 盘 / 临时 HTTP，只要最终把文件放进
# ~/wcu-inbox 就会自动处理。处理过的文件移到 ~/wcu-inbox/done/。

INBOX="$HOME/wcu-inbox"
DONE="$INBOX/done"
IMPORT="$(cd "$(dirname "$0")" && pwd)/import-bundle.sh"

[ -x "$IMPORT" ] || { echo "✗ 找不到 $IMPORT"; exit 1; }
mkdir -p "$DONE"

echo "监视中: $INBOX"
echo "把 .bundle 丢进这个目录即可，Ctrl-C 退出。"
echo "已处理的文件会移到 $DONE"
echo ""

while true; do
    found=0
    for f in "$INBOX"/*.bundle; do
        [ -e "$f" ] || continue
        found=1
        sleep 1  # 等传输落盘完成，避免读到半个文件

        base="$(basename "$f")"
        echo "===== 发现 $base ($(date '+%H:%M:%S')) ====="

        if "$IMPORT" "$f"; then
            mv "$f" "$DONE/$base"
            echo "→ 已归档到 done/"
        else
            mv "$f" "$DONE/$base.failed"
            echo "→ 导入未完成，文件留在 done/ 里加了 .failed 后缀"
        fi
        echo ""
    done

    [ "$found" -eq 0 ] && sleep 4
done
