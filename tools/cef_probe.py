"""探测 WPS 的 CEF 容器是否暴露了 DevTools 调试端口。

CEF 内核支持 --remote-debugging-port，只要开启，就能通过 CDP 直接拿到
DOM / AX 树，完全绕过 UIA 和 OCR。先看有没有开。
"""
import json
import re
import subprocess
import sys
import urllib.request


def listening_ports():
    """解析 netstat，返回 {pid: [port, ...]}"""
    try:
        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="ignore")
    except Exception as e:
        print("netstat 失败", e)
        return {}
    table = {}
    for line in out.splitlines():
        m = re.match(r"\s*TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING\s+(\d+)", line)
        if m:
            addr, port, pid = m.group(1), int(m.group(2)), int(m.group(3))
            table.setdefault(pid, []).append((addr, port))
    return table


def wps_pids():
    pids = set()
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq wps.exe", "/FO", "CSV", "/NH"],
            text=True, errors="ignore")
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.add(int(parts[1]))
    except Exception:
        pass
    return pids


def try_cdp(port):
    """问一下这个端口是不是 Chrome DevTools 协议。"""
    for path in ("/json/version", "/json"):
        url = f"http://127.0.0.1:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=1.2) as r:
                body = r.read(4000).decode("utf-8", "ignore")
            if "Browser" in body or "webSocketDebuggerUrl" in body or body.strip().startswith("["):
                return True, body[:300]
        except Exception:
            continue
    return False, ""


def main():
    table = listening_ports()
    pids = wps_pids()
    print(f"WPS 进程: {sorted(pids) if pids else '未运行'}\n")

    seen = set()
    hits = []
    for pid, addrs in sorted(table.items()):
        for addr, port in addrs:
            if port in seen:
                continue
            seen.add(port)
            is_wps = pid in pids
            ok, body = try_cdp(port)
            if ok:
                hits.append((pid, port, is_wps))
                print(f"[CDP 命中] pid={pid} port={port} wps={is_wps}")
                print(f"   {body[:200]}")
            elif is_wps:
                print(f"[WPS 端口] pid={pid} port={port}  (非 CDP)")

    if not hits:
        print("\n未发现可用的 DevTools 调试端口")

    print("\n=== WPS 进程全部监听端口 ===")
    for pid in sorted(pids):
        for addr, port in table.get(pid, []):
            print(f"  pid={pid}  {addr}:{port}")

    with open("cef_probe.json", "w", encoding="utf-8") as f:
        json.dump({"hits": hits, "wps_ports": {str(k): v for k, v in table.items() if k in pids}},
                  f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
