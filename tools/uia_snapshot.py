"""把 Windows 控件树序列化成 LLM 可读的紧凑结构快照。

核心思路与 browser-use 的 DOM 序列化一致：
  原始控件树（几千节点） → 过滤（可见 + 有语义 + 可交互） → 编号 → 紧凑文本

用法:
    python uia_snapshot.py "记事本"          # 文本快照
    python uia_snapshot.py "记事本" --json   # 结构化 JSON（给程序用）
    python uia_snapshot.py "记事本" --all    # 不过滤，看完整树
"""
import sys
import json

import win32gui
import uiautomation as auto


def find_hwnd(keyword):
    """用 Win32 枚举顶层窗口找句柄。

    比 UIA 的 GetRootControl 子级遍历可靠：Chrome / Electron 这类窗口
    经常不会出现在 UIA root 的 children 里，但 Win32 一定枚举得到。
    """
    hits = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if keyword in title:
            rect = win32gui.GetWindowRect(hwnd)
            area = (rect[2] - rect[0]) * (rect[3] - rect[1])
            hits.append((area, hwnd, title))

    win32gui.EnumWindows(cb, None)
    if not hits:
        return None
    hits.sort(key=lambda x: -x[0])
    return hits[0][1]

ACTIONABLE = {
    "ButtonControl", "EditControl", "MenuItemControl", "HyperlinkControl",
    "CheckBoxControl", "ComboBoxControl", "ListItemControl", "TabItemControl",
    "RadioButtonControl", "SliderControl", "TreeItemControl", "SplitButtonControl",
    "DataItemControl", "SpinnerControl", "HeaderItemControl", "CalendarControl",
}
CONTAINER = {"DocumentControl", "WindowControl", "PaneControl", "GroupControl"}


def collect(root, max_depth=20, budget=20000):
    out, queue = [], [(root, 0)]
    while queue and len(out) < budget:
        cur, d = queue.pop(0)
        try:
            ctype = cur.ControlTypeName
            name = (cur.Name or "").strip()
            aid = cur.AutomationId or ""
            cls = cur.ClassName or ""
            r = cur.BoundingRectangle
            box = (r.left, r.top, r.right - r.left, r.bottom - r.top)
            off = bool(cur.IsOffscreen)
            en = bool(cur.IsEnabled)
            val = ""
            if ctype in ("EditControl", "DocumentControl"):
                try:
                    vp = cur.GetValuePattern()
                    val = (vp.Value or "")[:60]
                except Exception:
                    pass
        except Exception:
            ctype, name, aid, cls, box, off, en, val = "?", "", "", "", (0, 0, 0, 0), True, False, ""

        out.append({
            "type": ctype, "name": name, "aid": aid, "cls": cls,
            "x": box[0], "y": box[1], "w": box[2], "h": box[3],
            "offscreen": off, "enabled": en, "value": val, "depth": d,
            "path": [],  # 留空，需要时再补
        })
        if d >= max_depth:
            continue
        try:
            c = cur.GetFirstChildControl()
        except Exception:
            break
        while c is not None:
            queue.append((c, d + 1))
            try:
                c = c.GetNextSiblingControl()
            except Exception:
                break
    return out


def is_actionable(n, keep_all):
    if keep_all:
        return True
    if n["offscreen"] or not n["enabled"]:
        return False
    if n["w"] <= 0 or n["h"] <= 0:
        return False
    has_id = bool(n["name"] or n["aid"])
    if n["type"] in ACTIONABLE:
        return has_id
    if n["type"] in CONTAINER:
        return bool(n["name"]) and n["w"] > 60 and n["h"] > 40
    # 纯文本节点也保留，它是"当前画面反馈"的主要来源
    if n["type"] == "TextControl":
        return bool(n["name"])
    return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    kw = sys.argv[1]
    as_json = "--json" in sys.argv
    keep_all = "--all" in sys.argv

    hwnd = find_hwnd(kw)
    if hwnd is None:
        print(f"未找到窗口: {kw}")
        return
    target = auto.ControlFromHandle(hwnd)
    if target is None:
        print(f"无法附加 UIA: {kw}")
        return

    raw = collect(target)
    kept = [n for n in raw if is_actionable(n, keep_all)]

    if as_json:
        print(json.dumps({
            "window": target.Name,
            "raw_nodes": len(raw),
            "kept_nodes": len(kept),
            "elements": kept,
        }, ensure_ascii=False, indent=2))
        return

    print(f"窗口: {target.Name}")
    print(f"原始节点 {len(raw)} → 过滤后 {len(kept)} 个有语义元素\n")
    for i, n in enumerate(kept, 1):
        label = n["name"] or n["aid"]
        if len(label) > 30:
            label = label[:30] + "…"
        extra = f' = "{n["value"]}"' if n["value"] else ""
        print(f'#{i:<3} {n["type"].replace("Control",""):<10} "{label}" @({n["x"]},{n["y"]},{n["w"]}x{n["h"]}){extra}')


if __name__ == "__main__":
    main()
