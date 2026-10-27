"""Windows 感知层：窗口枚举、UIA 树、截图。

实现直接沿用 tools/ 里已验证过的探针代码（uia_snapshot.py / vision_snapshot.py /
list_windows.py），只是重组成可被 WebSocket server 调用的函数。
原探针脚本保持不动，继续当命令行工具用。

**只能在 Windows 上 import。**
"""
from __future__ import annotations

import ctypes

# 必须在任何窗口 / UIA 操作之前完成，否则坐标会被系统按 DPI 虚拟化缩放。
# 2 = PROCESS_PER_MONITOR_DPI_AWARE
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

import io

import psutil
import uiautomation as auto
import win32gui
import win32process
import win32ui
from PIL import Image

# 可交互控件类型（见 tools/uia_snapshot.py）
ACTIONABLE = {
    "ButtonControl", "EditControl", "MenuItemControl", "HyperlinkControl",
    "CheckBoxControl", "ComboBoxControl", "ListItemControl", "TabItemControl",
    "RadioButtonControl", "SliderControl", "TreeItemControl", "SplitButtonControl",
    "DataItemControl", "SpinnerControl", "HeaderItemControl", "CalendarControl",
}
CONTAINER = {"DocumentControl", "WindowControl", "PaneControl", "GroupControl"}

_ROLE = {
    "ButtonControl": "button", "EditControl": "edit", "MenuItemControl": "menuitem",
    "HyperlinkControl": "link", "CheckBoxControl": "checkbox", "ComboBoxControl": "combobox",
    "ListItemControl": "listitem", "TabItemControl": "tab", "RadioButtonControl": "radio",
    "TreeItemControl": "treeitem", "DocumentControl": "document", "TextControl": "text",
    "WindowControl": "window", "PaneControl": "pane", "GroupControl": "group",
}


# ---------------------------------------------------------------- 窗口
def _proc_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return "?"


def list_windows() -> list[dict]:
    rows: list[dict] = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title.strip():
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = 0
        rows.append({
            "hwnd": hwnd,
            "title": title[:120],
            "class": win32gui.GetClassName(hwnd),
            "pid": pid,
            "proc": _proc_name(pid),
            "rect": list(win32gui.GetWindowRect(hwnd)),
        })

    win32gui.EnumWindows(cb, None)
    rows.sort(key=lambda r: r["proc"])
    return rows


def find_window(keyword: str) -> int | None:
    """按标题子串找窗口，多个命中取面积最大的那个。"""
    hits: list[tuple[int, int]] = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if keyword in t:
                r = win32gui.GetWindowRect(hwnd)
                hits.append(((r[2] - r[0]) * (r[3] - r[1]), hwnd))

    win32gui.EnumWindows(cb, None)
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    return win32gui.GetWindowRect(hwnd)


# ---------------------------------------------------------------- 截图
def capture(hwnd: int) -> tuple[Image.Image, tuple[int, int]]:
    """PrintWindow 抓指定窗口（不需要它在前台）。返回 (图, 窗口左上角)。"""
    left, top, right, bot = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bot - top
    if w <= 0 or h <= 0:
        raise RuntimeError(f"窗口尺寸异常: {w}x{h}")

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)
    # 2 = PW_RENDERFULLCONTENT，能抓 CEF / Qt 这类 GPU 合成窗口
    ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)

    info = bmp.GetInfo()
    bits = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)

    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    win32gui.DeleteObject(bmp.GetHandle())
    return img.copy(), (left, top)


def is_blank(img: Image.Image, threshold: int = 6) -> bool:
    """判断截图是不是纯色（CEF 未渲染完时常全白，见 docs/01 坑清单）。"""
    gray = img.convert("L").resize((32, 32))
    px = list(gray.getdata())
    return max(px) - min(px) < threshold


def to_jpeg(img: Image.Image, scale: float = 1.0, quality: int = 75) -> bytes:
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


# ---------------------------------------------------------------- UIA
def _collect(root, max_depth: int = 20, budget: int = 20000) -> list[dict]:
    out: list[dict] = []
    queue: list[tuple[object, int]] = [(root, 0)]
    while queue and len(out) < budget:
        cur, d = queue.pop(0)
        try:
            ctype = cur.ControlTypeName
            name = (cur.Name or "").strip()
            aid = cur.AutomationId or ""
            r = cur.BoundingRectangle
            off = bool(cur.IsOffscreen)
            en = bool(cur.IsEnabled)
        except Exception:
            ctype, name, aid, off, en = "?", "", "", True, False
            r = None

        if r is not None:
            out.append({
                "type": ctype, "name": name, "aid": aid,
                "x": r.left, "y": r.top,
                "w": r.right - r.left, "h": r.bottom - r.top,
                "offscreen": off, "enabled": en, "depth": d,
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


def _is_actionable(n: dict) -> bool:
    if n["offscreen"] or not n["enabled"]:
        return False
    if n["w"] <= 0 or n["h"] <= 0:
        return False
    has_id = bool(n["name"] or n["aid"])
    if n["type"] in ACTIONABLE:
        return has_id
    if n["type"] in CONTAINER:
        return bool(n["name"]) and n["w"] > 60 and n["h"] > 40
    if n["type"] == "TextControl":
        return bool(n["name"])
    return False


def uia_elements(hwnd: int, name: str | None = None, role: str | None = None) -> list[dict]:
    """UIA 树 → 契约里的 Element 列表。坐标已是屏幕绝对坐标 / 物理像素。"""
    target = auto.ControlFromHandle(hwnd)
    if target is None:
        raise RuntimeError(f"无法附加 UIA: hwnd={hwnd}")
    kept = [n for n in _collect(target) if _is_actionable(n)]
    out: list[dict] = []
    for i, n in enumerate(kept, 1):
        label = n["name"] or n["aid"]
        if name and name not in label:
            continue
        r = _ROLE.get(n["type"], n["type"].replace("Control", "").lower())
        if role and r != role:
            continue
        out.append({
            "index": i,
            "role": r,
            "name": label[:120],
            "box": [n["x"], n["y"], n["w"], n["h"]],
            "source": "uia",
            "patterns": [],
        })
    return out
