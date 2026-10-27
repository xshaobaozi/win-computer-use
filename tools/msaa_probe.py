"""尝试通过 MSAA / IAccessible 直接读取 CEF 容器内容。

UIA 走的是 UIA Provider 路径，MSAA 走的是 IAccessible 路径，
对老式 / 自研封装的窗口两者结果可能不同——所以值得单独试一次。
"""
import ctypes
from ctypes import POINTER, byref, c_void_p, c_long, c_wchar_p

import comtypes
import comtypes.client
from comtypes.automation import VARIANT

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import win32gui

OBJID_CLIENT = 0xFFFFFFFC
CHILDID_SELF = 0
ROLE_NAMES = {
    0x2A: "Document", 0x2C: "Pane", 0x2B: "Client", 0x9: "Window",
    0xF: "Text", 0x2B: "Client", 0x2E: "Grouping", 0x28: "Graphic",
    0x2B: "Client", 0x22: "Link", 0x2B: "Client",
}


def find_cef_hwnd(keyword="账号登录"):
    """连顶层窗口带所有子窗口一起找，CEF 容器通常是子窗口。"""
    hits = []
    tops = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            tops.append(hwnd)

    win32gui.EnumWindows(cb, None)

    def add(hwnd, depth):
        try:
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            return
        if "Cef" in cls or "Chrome_WidgetWin" in cls:
            r = win32gui.GetWindowRect(hwnd)
            hits.append(((r[2] - r[0]) * (r[3] - r[1]), hwnd, cls, title, depth))

    for top in tops:
        add(top, 0)
        try:
            win32gui.EnumChildWindows(top, lambda h, _: add(h, 1), None)
        except Exception:
            pass

    hits.sort(reverse=True)
    return hits


def main():
    print("=== 相关窗口 ===")
    for area, hwnd, cls, title, d in find_cef_hwnd():
        print(f"  hwnd={hwnd:<10} depth={d} {cls:<34} {title}")

    try:
        comtypes.client.GetModule("oleacc.dll")
        import comtypes.gen.Accessibility as Acc
    except Exception as e:
        print("生成 oleacc 类型库失败:", e)
        return

    oleacc = ctypes.oledll.oleacc
    iid = Acc.IAccessible._iid_

    for area, hwnd, cls, title, d in find_cef_hwnd():
        if "Cef" not in cls and "Chrome_WidgetWin" not in cls:
            continue
        print(f"\n=== 尝试 IAccessible: {cls} hwnd={hwnd} ===")
        ptr = POINTER(Acc.IAccessible)()
        try:
            oleacc.AccessibleObjectFromWindow(
                hwnd, OBJID_CLIENT, byref(iid), byref(ptr))
        except OSError as e:
            print("  拿不到 IAccessible:", e)
            continue

        if not ptr:
            print("  返回空指针")
            continue

        try:
            acc = ptr
            cnt = acc.accChildCount
            print(f"  accChildCount = {cnt}")
            name = acc.accName(CHILDID_SELF)
            print(f"  根节点名称 = {name!r}")
            if cnt:
                for i in range(1, min(cnt, 12) + 1):
                    try:
                        n = acc.accName(i)
                        role = acc.accRole(i)
                        val = acc.accValue(i)
                        loc = acc.accLocation(i)
                        print(f"    child {i}: name={n!r} role={role} value={val!r} loc={loc}")
                    except Exception as e:
                        print(f"    child {i}: 读取失败 {type(e).__name__}")
        except Exception as e:
            print("  遍历失败:", e)


if __name__ == "__main__":
    main()
