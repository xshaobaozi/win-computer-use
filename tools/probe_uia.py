"""UIA 可访问性探测：统计各窗口的控件树规模与可交互元素数量。

用途：判断某个应用（WPS / 浏览器 / 微信 / Electron 应用）能否被结构化感知。
用法：
    python probe_uia.py               # 列出所有顶层窗口并逐个统计
    python probe_uia.py "记事本"       # 只看窗口标题包含该关键字的窗口
"""
import sys
import json
import time

import uiautomation as auto

INTERACTIVE_TYPES = {
    "ButtonControl", "EditControl", "MenuItemControl", "HyperlinkControl",
    "CheckBoxControl", "ComboBoxControl", "ListItemControl", "TabItemControl",
    "RadioButtonControl", "SliderControl", "TreeItemControl", "SplitButtonControl",
    "DataItemControl", "DocumentControl", "SpinnerControl", "CalendarControl",
    "HeaderItemControl", "ImageControl", "TextControl",
}
STRONG_TYPES = INTERACTIVE_TYPES - {"TextControl", "ImageControl"}


def walk(ctrl, depth, max_depth, budget):
    """广度优先遍历，返回节点列表。budget 是节点上限，避免超大窗口卡死。"""
    nodes = []
    queue = [(ctrl, 0)]
    while queue and len(nodes) < budget:
        cur, d = queue.pop(0)
        try:
            rect = cur.BoundingRectangle
            box = [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
        except Exception:
            box = None
        try:
            item = {
                "type": cur.ControlTypeName,
                "name": (cur.Name or "")[:40],
                "aid": cur.AutomationId or "",
                "cls": cur.ClassName or "",
                "box": box,
                "depth": d,
                "offscreen": bool(cur.IsOffscreen),
                "enabled": bool(cur.IsEnabled),
            }
        except Exception:
            item = {"type": "?", "name": "", "aid": "", "cls": "", "box": None,
                    "depth": d, "offscreen": True, "enabled": False}
        nodes.append(item)
        if d >= max_depth:
            continue
        try:
            child = cur.GetFirstChildControl()
        except Exception:
            child = None
        while child is not None:
            queue.append((child, d + 1))
            try:
                child = child.GetNextSiblingControl()
            except Exception:
                break
    return nodes


def summarize(nodes):
    hist = {}
    named = 0
    strong = 0
    onscreen = 0
    for n in nodes:
        hist[n["type"]] = hist.get(n["type"], 0) + 1
        if n["name"] or n["aid"]:
            named += 1
        if n["type"] in STRONG_TYPES and (n["name"] or n["aid"]):
            strong += 1
        if not n["offscreen"]:
            onscreen += 1
    top = sorted(hist.items(), key=lambda x: -x[1])[:8]
    return {
        "total": len(nodes),
        "named": named,
        "interactive_named": strong,
        "onscreen": onscreen,
        "types": dict(top),
    }


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else None
    max_depth = int(sys.argv[2]) if len(sys.argv) > 2 else 9
    budget = int(sys.argv[3]) if len(sys.argv) > 3 else 4000

    root = auto.GetRootControl()
    results = []
    win = root.GetFirstChildControl()
    while win is not None:
        try:
            title = win.Name or ""
            cls = win.ClassName or ""
        except Exception:
            win = win.GetNextSiblingControl()
            continue
        if title and (keyword is None or keyword in title):
            t0 = time.time()
            try:
                nodes = walk(win, 0, max_depth, budget)
                s = summarize(nodes)
            except Exception as e:
                nodes, s = [], {"error": str(e)}
            s.update({
                "title": title[:60],
                "class": cls,
                "seconds": round(time.time() - t0, 2),
            })
            results.append(s)
            print(json.dumps(s, ensure_ascii=False))
        win = win.GetNextSiblingControl()

    print("\n=== 汇总 ===")
    print(f"{'窗口':<38} {'节点':>6} {'有名':>5} {'可交互':>6} {'可见':>5} {'耗时':>6}")
    for r in sorted(results, key=lambda x: -x.get("total", 0)):
        print(f"{r['title'][:36]:<38} {r.get('total', 0):>6} {r.get('named', 0):>5} "
              f"{r.get('interactive_named', 0):>6} {r.get('onscreen', 0):>5} {r.get('seconds', 0):>6}s")

    with open("probe_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n明细已写入 probe_result.json")


if __name__ == "__main__":
    main()
