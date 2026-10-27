"""视觉通道：截图 + OCR，把"UIA 读不到的界面"变成带坐标的元素表。

这是最后一道防线。适用于 WPS 登录窗、微信、游戏、远程桌面这类
自绘 / CEF / Canvas 界面——操作系统拿不到控件信息，只能靠像素。

用法:
    python vision_snapshot.py "账号登录"              # 列出识别到的文字元素
    python vision_snapshot.py "账号登录" --json       # JSON 输出
    python vision_snapshot.py "账号登录" --click "临时登录"   # 识别并点击
"""
import ctypes
import json
import sys
import time

# 必须在任何窗口操作之前：按显示器 DPI 感知，否则坐标会被系统虚拟化缩放
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

import numpy as np
import win32api
import win32con
import win32gui
import win32ui
from PIL import Image

from rapidocr_onnxruntime import RapidOCR

_OCR = None


def get_ocr():
    global _OCR
    if _OCR is None:
        _OCR = RapidOCR()
    return _OCR


def find_hwnd(keyword):
    hits = []

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


def capture(hwnd):
    """PrintWindow 抓取指定窗口（不需要它在前台）。返回 (PIL图, 窗口左上角)。"""
    left, top, right, bot = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bot - top
    if w <= 0 or h <= 0:
        raise RuntimeError("窗口尺寸异常")

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)
    # 2 = PW_RENDERFULLCONTENT，能抓到 CEF / Qt 这类 GPU 合成窗口
    ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)

    info = bmp.GetInfo()
    bits = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)

    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    win32gui.DeleteObject(bmp.GetHandle())
    return img, (left, top)


def ocr_elements(img, origin):
    """OCR → [{id, text, conf, box:[x,y,w,h]}]，坐标已转成屏幕绝对坐标。"""
    arr = np.array(img)
    result, _ = get_ocr()(arr)
    out = []
    if not result:
        return out
    for i, item in enumerate(result, 1):
        box, text, conf = item[0], item[1], item[2]
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x, y = int(min(xs)), int(min(ys))
        w, h = int(max(xs) - x), int(max(ys) - y)
        out.append({
            "id": i,
            "text": text,
            "conf": round(float(conf), 3),
            "box": [x + origin[0], y + origin[1], w, h],  # 屏幕绝对坐标
        })
    return out


def click_at(x, y):
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.08)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    kw = sys.argv[1]
    hwnd = find_hwnd(kw)
    if hwnd is None:
        print(f"未找到窗口: {kw}")
        return

    img, origin = capture(hwnd)
    print(f"窗口: {win32gui.GetWindowText(hwnd)}  截图 {img.width}x{img.height}  原点 {origin}")

    elems = ocr_elements(img, origin)

    if "--json" in sys.argv:
        print(json.dumps(elems, ensure_ascii=False, indent=2))
    else:
        print(f"识别到 {len(elems)} 个文本元素\n")
        for e in elems:
            t = e["text"] if len(e["text"]) <= 24 else e["text"][:24] + "…"
            x, y, w, h = e["box"]
            print(f'#{e["id"]:<3} "{t}"  @({x},{y},{w}x{h})  conf={e["conf"]}')

    if "--click" in sys.argv:
        target = sys.argv[sys.argv.index("--click") + 1]
        cands = [e for e in elems if target in e["text"]]
        if not cands:
            print(f'\n未找到包含 "{target}" 的元素')
            return
        best = max(cands, key=lambda e: e["conf"])
        x, y, w, h = best["box"]
        cx, cy = x + w // 2, y + h // 2
        print(f'\n点击 "{best["text"]}" 中心点 ({cx},{cy})')
        click_at(cx, cy)
        time.sleep(1.0)

        # 点击后重新识别，验证界面确实变了 —— 这就是反馈闭环
        img2, origin2 = capture(hwnd)
        elems2 = ocr_elements(img2, origin2)
        before = {e["text"] for e in elems}
        after = {e["text"] for e in elems2}
        print(f"点击后文本数 {len(elems)} → {len(elems2)}")
        added = after - before
        if added:
            print("新增文本: " + " / ".join(list(added)[:6]))
        else:
            print("文本无变化（界面可能只做了视觉切换）")


if __name__ == "__main__":
    main()
