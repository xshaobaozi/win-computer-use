#!/bin/bash
# 在 Mac 上导入 Windows 传过来的 bundle，安全地快进工作副本。
#
#   ./scripts/import-bundle.sh ~/Downloads/wcu-20261027-1530.bundle
#
# 行为:
#   1. 分支守卫：只允许在 master 上操作
#   2. 校验 bundle 完整性（缺前置提交会拒绝，不会导入半个东西）
#   3. fetch 到 refs/remotes/winsrc/master —— 不直接动 master
#   4. 只在能 fast-forward 时快进；不能 ff 时只提示，绝不覆盖本地改动
#   5. 打印本次新增了哪些提交

set -uo pipefail

WORKDIR="/Users/pengyijun/WorkBuddy/2026-10-27-10-25-34/win-computer-use"
REMOTE_NAME="winsrc"

# 分支策略：只同步这一个分支。bundle 只取这一个 ref，其他分支一律不导入，
# 避免两台机器之间出现"某个分支只在一台机器上存在"的半同步状态。
SYNC_BRANCH="master"

if [ $# -lt 1 ]; then
    echo "用法: $0 <bundle文件>"
    echo "例:   $0 ~/Downloads/wcu-20261027-1530.bundle"
    exit 1
fi

BUNDLE="$1"
[ -f "$BUNDLE" ] || { echo "✗ 文件不存在: $BUNDLE"; exit 1; }
BUNDLE="$(cd "$(dirname "$BUNDLE")" && pwd)/$(basename "$BUNDLE")"

[ -d "$WORKDIR/.git" ] || { echo "✗ 找不到工作副本: $WORKDIR"; exit 1; }

CURRENT="$(git -C "$WORKDIR" symbolic-ref --short HEAD 2>/dev/null || echo "")"
if [ "$CURRENT" != "$SYNC_BRANCH" ]; then
    echo "✗ 当前分支是 '${CURRENT:-未知}'，同步只允许在 $SYNC_BRANCH 上操作。"
    echo "  先切回: git -C \"$WORKDIR\" checkout $SYNC_BRANCH"
    exit 10
fi

echo "== 校验 bundle =="
if ! git -C "$WORKDIR" bundle verify "$BUNDLE" > /tmp/wcu_bundle_verify.log 2>&1; then
    echo "✗ 校验失败，可能文件损坏或缺少前置历史："
    sed 's/^/    /' /tmp/wcu_bundle_verify.log | tail -5
    exit 2
fi
echo "✓ 校验通过"

echo
echo "== 拉取到 $REMOTE_NAME/$SYNC_BRANCH =="
if ! git -C "$WORKDIR" fetch -q "$BUNDLE" "refs/heads/$SYNC_BRANCH:refs/remotes/$REMOTE_NAME/$SYNC_BRANCH"; then
    echo "✗ fetch 失败（bundle 里可能没有 $SYNC_BRANCH 分支）"
    exit 3
fi

BEFORE="$(git -C "$WORKDIR" rev-parse HEAD)"

echo
echo "== 当前分支: $SYNC_BRANCH =="
git -C "$WORKDIR" --no-pager log --oneline "$BEFORE..$REMOTE_NAME/$SYNC_BRANCH" 2>/dev/null | sed 's/^/    新增 /'

echo
if git -C "$WORKDIR" merge --ff-only -q "$REMOTE_NAME/$SYNC_BRANCH" 2>/dev/null; then
    AFTER="$(git -C "$WORKDIR" rev-parse --short HEAD)"
    echo "✓ 已快进到 $AFTER"
    echo
    echo "若这里不是你要的结果，回退到导入前:"
    echo "    git -C \"$WORKDIR\" reset --hard ${BEFORE:0:7}"
else
    echo "⚠ 无法快进（本地有未提交改动，或两边历史已分叉）"
    echo
    echo "  查看本地改动: git -C \"$WORKDIR\" status"
    echo "  分叉时手动处理: git -C \"$WORKDIR\" pull --rebase $REMOTE_NAME $SYNC_BRANCH"
    exit 4
fi
