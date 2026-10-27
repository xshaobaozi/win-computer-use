"""Windows 执行层：键鼠注入。

按 docs/01 第四节的优先级实现：
  文本输入：ValuePattern 赋值 > 剪贴板粘贴 > 逐字符 SendInput
  鼠标点击：UIA InvokePattern > SendInput > PostMessage

当前只实现了 SendInput 与剪贴板两条，UIA Pattern 与 PostMessage 留 TODO。
**只能在 Windows 上 import。**
"""
from __future__ import annotations

import ctypes
import time

import win32api
import win32clipboard
import win32con
import win32gui

_u32 = ctypes.windll.user32


# ---------------------------------------------------------------- 鼠标
def click_at(x: int, y: int, button: str = "left") -> None:
    """SendInput 级别的真实点击：需要前台，会抢走鼠标。"""
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.08)
    down, up = (
        (win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP)
        if button == "right"
        else (win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP)
    )
    win32api.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(up, 0, 0, 0, 0)


def foreground(hwnd: int) -> bool:
    """点击前先激活目标窗口，否则坐标可能落在别的窗口上。"""
    try:
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        _u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(_u32.SetForegroundWindow(hwnd))
    except Exception:
        return False


# TODO: post_click(hwnd, x, y) —— 用 PostMessage 投 WM_LBUTTONDOWN/UP，
#       不抢鼠标、可后台，但对 UWP 无效。参考 tools/post_click.py。


# ---------------------------------------------------------------- 键盘
def _set_clipboard(text: str) -> None:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("剪贴板被占用，打不开")
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


def _key(vk: int, up: bool = False) -> None:
    flags = win32con.KEYEVENTF_KEYUP if up else 0
    win32api.keybd_event(vk, 0, flags, 0)


def paste(text: str, wait: float = 0.15) -> None:
    """写剪贴板 + Ctrl+V。中文长文本唯一可靠的方式。"""
    _set_clipboard(text)
    time.sleep(wait)
    _key(win32con.VK_CONTROL)
    _key(ord("V"))
    _key(ord("V"), up=True)
    _key(win32con.VK_CONTROL, up=True)
    time.sleep(wait)


def type_keys(text: str, per_char_delay: float = 0.012) -> None:
    """逐字符敲。中文会丢字 / 乱码，仅作兜底。"""
    for ch in text:
        win32api.keybd_event(0, ord(ch), win32con.KEYEVENTF_UNICODE, 0)
        win32api.keybd_event(0, ord(ch), win32con.KEYEVENTF_UNICODE | win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(per_char_delay)


def type_text(text: str, method: str = "clipboard") -> dict:
    if method == "clipboard":
        paste(text)
    elif method == "keystrokes":
        type_keys(text)
    elif method == "value":
        raise NotImplementedError("value 方式需要先定位到 Edit 控件并调 ValuePattern，见 TODO")
    else:
        raise ValueError(f"未知输入方式: {method}")
    return {"typed": len(text), "method": method}
