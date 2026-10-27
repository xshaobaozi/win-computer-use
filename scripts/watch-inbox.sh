#!/bin/bash
# 监视 ~/wcu-inbox，出现 .bundle 或 .zip 就自动导入工作副本。
#
#   ./scripts/watch-inbox.sh
#
# 传输通道随你：微信 / 网盘 / U 盘 / scripts/sync-server.py，只要最终把文件
# 放进 ~/wcu-inbox 就会自动处理。处理过的移到 ~/wcu-inbox/done/。
#
#   .bundle → import-bundle.sh  保留历史，fast-forward
#   .zip    → import-zip.sh     快照覆盖，自动补一个提交
#
# 分支策略：只处理 master。导入脚本自己会检查，这里只负责分发。

INBOX="$HOME/wcu-inbox"
DONE="$INBOX/done"
HERE="$(cd "$(dirname "$0")" && pwd)"
IMPORT_BUNDLE="$HERE/import-bundle.sh"
IMPORT_ZIP="$HERE/import-zip.sh"

[ -x "$IMPORT_BUNDLE" ] || { echo "✗ 找不到 $IMPORT_BUNDLE"; exit 1; }
[ -x "$IMPORT_ZIP" ] || { echo "✗ 找不到 $IMPORT_ZIP"; exit 1; }
mkdir -p "$DONE"

echo "监视中: $INBOX"
echo "支持 .bundle 和 .zip，Ctrl-C 退出。已处理的移到 $DONE"
echo ""

handle() {
    f="$1"
    base="$(basename "$f")"
    echo "===== 发现 $base ($(date '+%H:%M:%S')) ====="

    case "$f" in
        *.bundle) "$IMPORT_BUNDLE" "$f"; rc=$? ;;
        *.zip)    "$IMPORT_ZIP" "$f";    rc=$? ;;
        *)        echo "✗ 不认识的文件类型"; rc=1 ;;
    esac

    if [ $rc -eq 0 ]; then
        mv "$f" "$DONE/$base"
        echo "→ 已归档到 done/"
    else
        mv "$f" "$DONE/$base.failed"
        echo "→ 未完成（返回码 $rc），文件留在 done/ 里加了 .failed 后缀"
    fi
    echo ""
}

while true; do
    found=0
    for f in "$INBOX"/*.bundle "$INBOX"/*.zip; do
        [ -e "$f" ] || continue
        found=1
        sleep 1  # 等传输落盘完成，避免读到半个文件
        handle "$f"
    done

    [ "$found" -eq 0 ] && sleep 4
done
