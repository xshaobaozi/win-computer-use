#!/bin/bash
# 导入 Windows 传来的 zip 快照。
#
#   ./scripts/import-zip.sh ~/wcu-inbox/snapshot.zip
#
# 和 bundle 的区别（务必理解）：
#   bundle —— 保留 git 历史，可以 fast-forward，冲突可控   ← 首选
#   zip    —— 只是一堆文件，没有历史；只能"照单覆盖"再补一个提交
#
# 所以 zip 的处理方式是：解压 → 覆盖到工作副本（排除 .git）
# → 只 add 导入清单里的文件 → 自动创建一个提交。这样虽然粒度粗，
# 但每次导入都有据可查、可以 revert 回来，不会出现"文件莫名变了却不知道是谁改的"。
# 注意只 add 导入的文件，不能用 git add -A（会把无关的未提交改动卷进来）。
#
# 如果 zip 里带 .git 目录，说明对方直接压了整个仓库——会提示改用 bundle。

set -uo pipefail

# 仓库根目录 = 本脚本所在目录的上一级。不再硬编码绝对路径。
HERE="$(cd "$(dirname "$0")" && pwd)"
WORKDIR="${WCU_WORKDIR:-$(cd "$HERE/.." && pwd)}"
SYNC_BRANCH="master"

if [ $# -lt 1 ]; then
    echo "用法: $0 <zip文件>"
    exit 1
fi

ZIP="$1"
[ -f "$ZIP" ] || { echo "✗ 文件不存在: $ZIP"; exit 1; }
[ -d "$WORKDIR/.git" ] || { echo "✗ 找不到工作副本: $WORKDIR"; exit 1; }

# 分支策略：只允许在 $SYNC_BRANCH 上同步。zip 本身不携带分支信息，
# 在别的分支上覆盖会造成难以理解的状态，直接拒绝。
CURRENT="$(git -C "$WORKDIR" symbolic-ref --short HEAD 2>/dev/null || echo "")"
if [ "$CURRENT" != "$SYNC_BRANCH" ]; then
    echo "✗ 当前分支是 '${CURRENT:-未知}'，同步只允许在 $SYNC_BRANCH 上操作。"
    echo "  先切回: git -C \"$WORKDIR\" checkout $SYNC_BRANCH"
    exit 10
fi

command -v unzip > /dev/null || { echo "✗ 系统没有 unzip"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== 解压 =="
if ! unzip -q "$ZIP" -d "$TMP"; then
    echo "✗ 解压失败，文件可能损坏"
    exit 2
fi

# 如果压缩的是整个文件夹，只有一个顶层目录时自动剥掉这一层
ROOT="$TMP"
count=$(ls -A "$TMP" | wc -l | tr -d ' ')
if [ "$count" -eq 1 ]; then
    only="$(ls -A "$TMP" | head -1)"
    [ -d "$TMP/$only" ] && ROOT="$TMP/$only"
fi
echo "   根目录: ${ROOT#$TMP}"

if [ -d "$ROOT/.git" ]; then
    echo ""
    echo "⚠ 这个 zip 里包含 .git 目录（整个仓库）。
    这种情况用 bundle 更合适：保留历史、能 fast-forward、不会丢分支。"
    echo "   在 Windows 上改用: .\\scripts\\export-bundle.ps1"
    echo ""
    echo "   已中止，未做任何修改。"
    exit 3
fi

echo
echo "== 预览将覆盖的文件 =="
tar -C "$ROOT" --exclude='.git' -cf - . 2>/dev/null | tar -tf - 2>/dev/null | sed 's/^/    /' | head -20
total=$(tar -C "$ROOT" --exclude='.git' -cf - . 2>/dev/null | tar -tf - 2>/dev/null | wc -l | tr -d ' ')
[ "$total" -gt 20 ] && echo "    … 共 $total 项"

echo
echo "== 覆盖到工作副本 =="
if ! tar -C "$ROOT" --exclude='.git' -cf - . 2>/dev/null | tar -C "$WORKDIR" -xf - 2>/dev/null; then
    echo "✗ 复制失败"
    exit 4
fi

# 收集本次导入的文件清单。只 add 这些路径，绝不用 `git add -A` ——
# 否则会把你工作区里其他未提交的改动一起卷进这个提交，非常难解释。
LIST="$TMP/.files"
( cd "$ROOT" && find . -type f -not -path './.git/*' -print | sed 's|^\./||' ) > "$LIST"
COUNT=$(wc -l < "$LIST" | tr -d ' ')

cd "$WORKDIR" || exit 1

if [ "$COUNT" -eq 0 ]; then
    echo "✓ zip 里没有文件"
    exit 0
fi

echo
echo "== 导入的文件 ($COUNT 个) =="
head -20 "$LIST" | sed 's/^/    /'
[ "$COUNT" -gt 20 ] && echo "    … 共 $COUNT 个"

CHANGED=$(git status --porcelain -- $(tr '\n' ' ' < "$LIST") 2>/dev/null | wc -l | tr -d ' ')
if [ "$CHANGED" -eq 0 ]; then
    echo ""
    echo "✓ 这些文件与当前工作副本完全一致，无需提交"
    exit 0
fi

echo
echo "== 变更明细 =="
tr '\n' '\0' < "$LIST" | xargs -0 git status --porcelain -- 2>/dev/null | sed 's/^/    /' | head -30

echo
tr '\n' '\0' < "$LIST" | xargs -0 git add --
STAMP="$(date '+%Y-%m-%d %H:%M')"
if git commit -q -m "sync: 导入 Windows zip 快照 ($STAMP)

来源: $(basename "$ZIP")
文件: $COUNT 个
注意: zip 不含 git 历史，本次为整包快照提交。
如需可追溯的逐次合并，请改用 bundle（scripts/export-bundle.ps1）。"; then
    echo "✓ 已提交 $(git rev-parse --short HEAD)（仅包含本次导入的 $COUNT 个文件）"
    echo
    echo "  不满意可回退: git reset --hard HEAD~1"
else
    echo "✗ 提交失败"
    exit 5
fi
