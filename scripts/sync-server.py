#!/usr/bin/env python3
"""双机同步服务 —— 在 Mac 上跑，公司电脑连过来推/拉仓库。

    python3 scripts/sync-server.py --token 你的口令
    python3 scripts/sync-server.py --host 0.0.0.0 --token 你的口令   # 供局域网访问

三个端点（全部需要 token）:

    GET  /health                    探活，返回当前仓库 HEAD
    GET  /bundle                    现场打包当前仓库，直接下载（Win 用来拉）
    POST /upload?name=xxx.bundle    上传 bundle 或 zip（Win 用来推）

设计上的克制:
- 只接受 .bundle / .zip，其他后缀一律 400，避免变成通用文件服务器
- 默认只绑 127.0.0.1；绑 0.0.0.0 必须显式指定并强制要求 token
- 上传落盘到 ~/wcu-inbox，不直接改工作副本 —— 合并交给 import-bundle.sh，
  这样"传输"和"合并"解耦，合并失败不会污染仓库

注意：这里不做双向自动合并。推和拉是两个独立动作，git 是唯一的仲裁者。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# 仓库根目录 = 本脚本所在目录的上一级，也可用环境变量 WCU_WORKDIR 覆盖。
WORKDIR = Path(os.environ.get("WCU_WORKDIR") or Path(__file__).resolve().parent.parent)
INBOX = Path.home() / "wcu-inbox"
MAX_BYTES = 200 * 1024 * 1024
ALLOWED_EXT = {".bundle", ".zip"}

# 分支策略：只同步这一个分支。
# 只打 master 而不是 --all —— 避免 Win 上的临时分支被顺带传过来，
# 造成"某个分支只在一台机器上存在"的半同步状态。
SYNC_BRANCH = "master"

TOKEN = ""
HOST = "127.0.0.1"
PORT = 8766


def git(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(WORKDIR), *args], capture_output=True, text=True, **kw
    )


def head_info() -> dict:
    log = git("log", "--oneline", "-1")
    branch = git("symbolic-ref", "--short", "HEAD")
    status = git("status", "--porcelain")
    cur = branch.stdout.strip() or "?"
    return {
        "head": log.stdout.strip(),
        "branch": cur,
        "dirty": bool(status.stdout.strip()),
        "sync_branch": SYNC_BRANCH,
        "on_sync_branch": cur == SYNC_BRANCH,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "wcu-sync/0.1"

    # ---------------------------------------------------------- 工具
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, qs: dict) -> bool:
        given = (qs.get("token") or [""])[0] or self.headers.get("X-Token", "")
        return bool(TOKEN) and given == TOKEN

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def _deny(self) -> None:
        self._json(401, {"ok": False, "error": "token 不对或缺失"})

    # ---------------------------------------------------------- GET
    def do_GET(self) -> None:
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path == "/health":
            if not self._authorized(qs):
                return self._deny()
            return self._json(200, {"ok": True, "repo": head_info(), "workdir": str(WORKDIR)})

        if u.path == "/bundle":
            if not self._authorized(qs):
                return self._deny()
            return self._serve_bundle()

        self._json(404, {"ok": False, "error": f"未知路径 {u.path}"})

    def _serve_bundle(self) -> None:
        info = head_info()
        if not info["on_sync_branch"]:
            return self._json(409, {
                "ok": False,
                "error": f"Mac 当前在 {info['branch']} 分支，只允许同步 {SYNC_BRANCH}",
            })

        fd, tmp = tempfile.mkstemp(suffix=".bundle")
        os.close(fd)
        try:
            # 带 HEAD：只打分支的话对方 clone 会检出空目录
            r = git("bundle", "create", tmp, "HEAD", SYNC_BRANCH)
            if r.returncode != 0:
                return self._json(500, {"ok": False, "error": f"打包失败: {r.stderr.strip()[:300]}"})

            size = os.path.getsize(tmp)
            name = f"wcu-mac-{time.strftime('%Y%m%d-%H%M%S')}.bundle"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("X-Filename", name)
            self.end_headers()
            with open(tmp, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            print(f"  → 已下发 {name} ({size / 1024:.0f} KB)")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ---------------------------------------------------------- POST
    def do_POST(self) -> None:
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path != "/upload":
            return self._json(404, {"ok": False, "error": f"未知路径 {u.path}"})
        if not self._authorized(qs):
            return self._deny()

        name = (qs.get("name") or [""])[0] or self.headers.get("X-Filename", "")
        name = os.path.basename(name)
        if not name:
            return self._json(400, {"ok": False, "error": "缺少文件名参数 name="})

        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_EXT:
            return self._json(400, {"ok": False, "error": f"只接受 {sorted(ALLOWED_EXT)}，收到 {ext}"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json(400, {"ok": False, "error": "Content-Length 非法"})
        if length <= 0:
            return self._json(400, {"ok": False, "error": "空文件"})
        if length > MAX_BYTES:
            return self._json(413, {"ok": False, "error": f"超过 {MAX_BYTES // 1024 // 1024}MB 上限"})

        INBOX.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.\-\u4e00-\u9fa5]", "_", name)
        dest = INBOX / safe
        stem, suffix = dest.stem, dest.suffix
        n = 1
        while dest.exists():
            dest = INBOX / f"{stem}-{n}{suffix}"
            n += 1

        remaining = length
        with open(dest, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)

        got = dest.stat().st_size
        if remaining > 0:
            dest.unlink(missing_ok=True)
            return self._json(400, {"ok": False, "error": "传输中断，文件不完整"})

        print(f"  ← 收到 {dest.name} ({got / 1024:.0f} KB)")
        self._json(200, {"ok": True, "saved": str(dest), "bytes": got})


def main() -> None:
    global TOKEN, HOST, PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--token", default=None, help="不填则自动生成")
    a = ap.parse_args()

    TOKEN = a.token or os.urandom(6).hex()
    HOST, PORT = a.host, a.port

    if not WORKDIR.exists():
        raise SystemExit(f"找不到仓库: {WORKDIR}")

    if HOST != "127.0.0.1":
        print("⚠ 正在监听局域网接口。任何拿到 token 的人都能推文件到这个 inbox。")
        print("  用完请立即 Ctrl-C，不要长期挂着。")
        print()

    print(f"同步服务已启动  http://{HOST}:{PORT}")
    print(f"  token : {TOKEN}")
    print(f"  inbox : {INBOX}")
    print(f"  当前   : {head_info()['head']}")
    print()
    print("公司电脑上用:")
    print(f"  .\\scripts\\sync.ps1 -Push -Server http://<本机IP>:{PORT} -Token {TOKEN}")
    print(f"  .\\scripts\\sync.ps1 -Pull -Server http://<本机IP>:{PORT} -Token {TOKEN}")
    print()

    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
