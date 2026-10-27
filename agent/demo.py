"""端到端闭环演示：感知 → 定位 → 执行 → 校验。

这就是 docs/01 第九节说的"真正需要你自己投入的部分"——动作后的状态校验。
先对着 mock 跑通，再把 --url 换成真 Windows server，代码一行不用改。

用法::

    # 终端 1
    python -m agent.mock_server
    # 终端 2
    python -m agent.demo
    python -m agent.demo --url ws://192.168.1.20:8765/ws/control --keyword WPS
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

from agent.transport import Remote, RemoteError
from protocol.schema import find_elements, signature


def step(n: int, title: str, detail: str = "") -> None:
    print(f"\n[{n}] {title}")
    if detail:
        print(f"    {detail}")


async def run(url: str, keyword: str) -> int:
    t0 = time.perf_counter()
    async with Remote(url) as r:
        step(1, "枚举窗口")
        wins = await r.windows()
        if not wins:
            print("    ✗ 没有可见窗口")
            return 1
        for w in wins:
            print(f"    hwnd={w['hwnd']}  {w['proc']:<12} {w['title']}")
        target = next((w for w in wins if keyword in w["title"]), wins[0])
        hwnd = target["hwnd"]
        print(f"    → 选中 hwnd={hwnd}  {target['title']}")

        step(2, "感知（第 1 级 UIA）")
        shot = await r.capture(hwnd)
        els = shot["elements"]
        print(f"    {shot['w']}x{shot['h']} dpi={shot.get('dpi')}  元素 {len(els)} 个")
        for el in els:
            print(f"    #{el.index:<2} {el.role:<8} {el.name[:20]:<22} @{el.box}  {el.source}")
        before = signature(els)

        step(3, "定位目标：保存")
        cands = find_elements(els, "保存")
        if not cands:
            print("    ✗ UIA 里找不到「保存」，真实场景这里应降级到 OCR")
            return 2
        btn = cands[0]
        cx, cy = btn.center
        print(f"    命中 #{btn.index} {btn.name}  中心点 ({cx},{cy})")

        step(4, "执行点击")
        res = await r.click(cx, cy, hwnd=hwnd)
        print(f"    server 回执: {res}")

        step(5, "校验：界面真的变了吗")
        shot2 = await r.capture(hwnd)
        els2 = shot2["elements"]
        after = signature(els2)
        if after == before:
            print("    ✗ 元素表与点击前完全一致 —— 这一步算失败，需要重试或换通道")
            return 3
        added = {e.name for e in els2} - {e.name for e in els}
        removed = {e.name for e in els} - {e.name for e in els2}
        print(f"    元素 {len(els)} → {len(els2)}")
        if added:
            print(f"    新增: {' / '.join(sorted(added))}")
        if removed:
            print(f"    消失: {' / '.join(sorted(removed))}")
        if any("已保存" in e.name for e in els2):
            print("    ✓ 出现「已保存」，闭环成立")
        else:
            print("    ⚠ 元素变了但没看到「已保存」，界面可能只做了视觉切换")

    print(f"\n总耗时 {time.perf_counter() - t0:.2f}s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="ws://host:port/ws/control，默认读 WCU_SERVER")
    ap.add_argument("--keyword", default="WPS", help="窗口标题关键字")
    a = ap.parse_args()
    try:
        return asyncio.run(run(a.url, a.keyword))
    except RemoteError as exc:
        print(f"\n✗ server 返回错误: {exc}")
        return 4
    except OSError as exc:
        print(f"\n✗ 连不上 server: {exc}")
        print("  先启动 python -m agent.mock_server，或确认 Windows 端已监听")
        return 5


if __name__ == "__main__":
    sys.exit(main())
