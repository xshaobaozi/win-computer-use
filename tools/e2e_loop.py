"""端到端闭环验证：结构化感知 → 精确定位 → 动作 → 读取反馈。

在 Chrome 测试页上模拟一次真实业务操作：
  1. 结构化快照，按语义找到输入框/按钮
  2. 填入客户名称
  3. 点击"提交订单"
  4. 重新快照，确认状态文字变化，拿到反馈
"""
import time

import win32clipboard
import win32con
import win32gui
import uiautomation as auto


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


def find_ctrl(root, name, ctype=None, max_depth=20, budget=30000):
    """在控件树中按语义名 + 类型查找。这就是"结构化感知"的核心检索。"""
    queue = [(root, 0)]
    n = 0
    while queue and n < budget:
        cur, d = queue.pop(0)
        n += 1
        try:
            if (cur.Name or "").strip() == name:
                if ctype is None or cur.ControlTypeName == ctype:
                    return cur
        except Exception:
            pass
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
    return None


def paste_text(text):
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    win32clipboard.CloseClipboard()
    auto.SendKeys("{Ctrl}v", waitTime=0.1)


def read_text_near(root, keyword):
    """扫描所有文本节点，返回包含关键字的文本（= 当前画面反馈）。"""
    queue = [(root, 0)]
    found = []
    n = 0
    while queue and n < 30000:
        cur, d = queue.pop(0)
        n += 1
        try:
            nm = (cur.Name or "").strip()
            if keyword in nm:
                found.append(nm)
        except Exception:
            pass
        if d >= 20:
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
    return found


def main():
    hwnd = find_hwnd("感知测试")
    if not hwnd:
        print("找不到测试页窗口")
        return
    win = auto.ControlFromHandle(hwnd)

    print("步骤 1  结构化感知")
    edit = find_ctrl(win, "客户名称", "EditControl")
    btn = find_ctrl(win, "提交订单", "ButtonControl")
    print(f"  输入框: {'找到' if edit else '未找到'}")
    print(f"  提交按钮: {'找到' if btn else '未找到'}")
    if not (edit and btn):
        return
    r = edit.BoundingRectangle
    br = btn.BoundingRectangle
    print(f"  输入框坐标 ({r.left},{r.top}) 按钮坐标 ({br.left},{br.top})")

    print("步骤 2  填写内容")
    ok = False
    try:
        edit.GetValuePattern().SetValue("杭州云图科技")
        ok = True
        print("  通过 ValuePattern 直接赋值成功")
    except Exception as e:
        print(f"  ValuePattern 不可用 ({type(e).__name__})，改用聚焦 + 粘贴")
    if not ok:
        edit.SetFocus()
        time.sleep(0.2)
        paste_text("杭州云图科技")
        time.sleep(0.3)
    time.sleep(0.3)

    print("步骤 3  点击提交")
    try:
        btn.GetInvokePattern().Invoke()
        print("  通过 InvokePattern 触发成功（未移动鼠标）")
    except Exception as e:
        print(f"  InvokePattern 不可用 ({type(e).__name__})，改用坐标点击")
        btn.Click(simulateMove=False)
    time.sleep(0.8)

    print("步骤 4  读取画面反馈")
    fb = read_text_near(win, "提交成功")
    if fb:
        print(f"  反馈文本: {fb[0]}")
    else:
        fb2 = read_text_near(win, "等待提交")
        print(f"  未检测到成功文本，当前状态: {fb2[0] if fb2 else '未知'}")

    print("步骤 5  验证输入框当前值")
    try:
        print(f"  客户名称 = {edit.GetValuePattern().Value!r}")
    except Exception:
        print("  无法读取当前值")


if __name__ == "__main__":
    main()
