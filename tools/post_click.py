"""不经过物理光标的点击：直接向目标窗口投递鼠标消息。

适用场景：
  - 当前进程没有输入桌面权限（GetCursorPos 报拒绝访问）
  - 不想抢走用户的鼠标
  - 需要在后台操作某个窗口

原理：把屏幕坐标转成客户区坐标，PostMessage 发 WM_LBUTTONDOWN / WM_LBUTTONUP。
CEF / Qt / Win32 窗口通常都会处理这些消息。
"""
import ctypes
import sys
import time

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

import win32api
import win32con
import win32gui

import vision_snapshot as vs


def deepest_window_at(x, y, top):
    """从顶层窗口往下找，定位该坐标处最深一层的子窗口。"""
    hwnd = top
    for _ in range(12):
        pt = win32gui.ScreenToClient(hwnd, (x, y))
        child = win32gui.ChildWindowFromPointEx(
            hwnd, pt, win32con.CWP_SKIPINVISIBLE | win32con.CWP_SKIPDISABLED
        )
        if not child or child == hwnd:
            break
        hwnd = child
    return hwnd


def post_click(top_hwnd, sx, sy):
    target = deepest_window_at(sx, sy, top_hwnd)
    cx, cy = win32gui.ScreenToClient(target, (sx, sy))
    lparam = win32api.MAKELONG(cx & 0xFFFF, cy & 0xFFFF)
    print(f"  顶层句柄 {top_hwnd} → 目标句柄 {target} ({win32gui.GetClassName(target)})")
    print(f"  屏幕({sx},{sy}) → 客户区({cx},{cy})")
    win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.05)
    win32gui.PostMessage(target, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.06)
    win32gui.PostMessage(target, win32con.WM_LBUTTONUP, 0, lparam)
    return target


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "账号登录"
    target_text = sys.argv[2] if len(sys.argv) > 2 else "更多"

    hwnd = vs.find_hwnd(kw)
    if not hwnd:
        print("找不到窗口")
        return

    img, origin = vs.capture(hwnd)
    elems = vs.ocr_elements(img, origin)
    cands = [e for e in elems if target_text in e["text"]]
    if not cands:
        print(f'没找到 "{target_text}"')
        return
    best = max(cands, key=lambda e: e["conf"])
    x, y, w, h = best["box"]
    sx, sy = x + w // 2, y + h // 2
    print(f'目标: "{best["text"]}" 中心 ({sx},{sy})')

    post_click(hwnd, sx, sy)
    time.sleep(1.2)

    img2, origin2 = vs.capture(hwnd)
    elems2 = vs.ocr_elements(img2, origin2)
    before = {e["text"] for e in elems}
    after = {e["text"] for e in elems2}
    print(f"\n点击前 {len(before)} 项 → 点击后 {len(after)} 项")
    added = after - before
    removed = before - after
    if added:
        print("新增: " + " / ".join(sorted(added)[:8]))
    if removed:
        print("消失: " + " / ".join(sorted(removed)[:8]))
    if not added and not removed:
        print("文本无变化")

    img2.save("after_click.png")
    print("点击后截图已保存 after_click.png")


if __name__ == "__main__":
    main()
