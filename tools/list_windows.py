import win32gui, win32process, psutil, json


def proc_name(pid):
    try:
        return psutil.Process(pid).name()
    except Exception:
        return "?"


rows = []


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
    rect = win32gui.GetWindowRect(hwnd)
    rows.append({
        "hwnd": hwnd,
        "title": title[:70],
        "class": win32gui.GetClassName(hwnd),
        "pid": pid,
        "proc": proc_name(pid),
        "rect": list(rect),
    })


win32gui.EnumWindows(cb, None)
rows.sort(key=lambda r: r["proc"])
for r in rows:
    print(f'{r["proc"]:<22} | {r["class"]:<28} | {r["title"]}')
print(f"\n共 {len(rows)} 个可见窗口")
with open("windows.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
