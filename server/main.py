"""Windows 被控端 server —— WebSocket 入口。

    python -m server.main                    # 只听 127.0.0.1，安全
    python -m server.main --host 0.0.0.0     # 供局域网内 Mac 连接（会告警）
    python -m server.main --token abc123     # 额外要求 ?token=abc123

协议见 protocol/schema.py。截图走二进制帧，JSON 里只放元数据，不做 base64。

**只能在 Windows 上运行。**
"""
from __future__ import annotations

import argparse
import asyncio
import json
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import serve

from protocol.schema import (
    OP_CAPTURE,
    OP_CLICK,
    OP_TYPE,
    OP_UIA_QUERY,
    OP_WINDOWS,
    ErrorCode,
    Request,
    Response,
)

try:
    from server import action, perception

    PLATFORM_OK = True
    PLATFORM_ERR: Exception | None = None
except ImportError as exc:  # 在 Mac / Linux 上就是这个分支
    PLATFORM_OK = False
    PLATFORM_ERR = exc

TOKEN: str | None = None


def dispatch(req: Request) -> tuple[Response, bytes | None]:
    """返回 (JSON 响应, 可选的二进制载荷)。"""
    p = req.args

    if req.op == OP_WINDOWS:
        return Response.success(req.id, perception.list_windows()), None

    if req.op == OP_CAPTURE:
        hwnd = int(p.get("hwnd") or 0) or perception.find_window(p.get("keyword", ""))
        if not hwnd:
            return Response.failure(req.id, ErrorCode.NOT_FOUND, "没找到目标窗口"), None
        img, origin = perception.capture(hwnd)
        meta = {
            "hwnd": hwnd,
            "w": img.width,
            "h": img.height,
            "origin": list(origin),
            "dpi": int(96 * (img.width / max(1, img.width))),  # 占位，真实 DPI 由 GetDpiForWindow 取
            "blank": perception.is_blank(img),
            "space": "physical",
            "elements": perception.uia_elements(hwnd),
        }
        blob = perception.to_jpeg(img, scale=float(p.get("scale") or 1.0))
        meta["image_len"] = len(blob)
        meta["image_mime"] = "image/jpeg"
        return Response.success(req.id, meta), blob

    if req.op == OP_UIA_QUERY:
        hwnd = int(p.get("hwnd") or 0) or perception.find_window(p.get("keyword", ""))
        if not hwnd:
            return Response.failure(req.id, ErrorCode.NOT_FOUND, "没找到目标窗口"), None
        els = perception.uia_elements(hwnd, name=p.get("name"), role=p.get("role"))
        return Response.success(req.id, {"elements": els}), None

    if req.op == OP_CLICK:
        hwnd = int(p.get("hwnd") or 0)
        if hwnd:
            action.foreground(hwnd)
        action.click_at(int(p.get("x", 0)), int(p.get("y", 0)), p.get("button", "left"))
        return Response.success(req.id, {"clicked": True}), None

    if req.op == OP_TYPE:
        return Response.success(req.id, action.type_text(p.get("text", ""), p.get("method", "clipboard"))), None

    return Response.failure(req.id, ErrorCode.UNKNOWN_OP, f"未实现: {req.op}"), None


def _authorized(ws) -> bool:
    if not TOKEN:
        return True
    qs = parse_qs(urlparse(ws.request.path).query)
    return qs.get("token", [""])[0] == TOKEN


async def _handler(ws) -> None:
    if not _authorized(ws):
        await ws.close(code=4401, reason="bad token")
        return

    async for raw in ws:
        try:
            req = Request.from_json(raw)
        except Exception as exc:  # noqa: BLE001
            await ws.send(Response.failure(None, ErrorCode.BAD_REQUEST, str(exc)).to_json())
            continue

        try:
            resp, blob = dispatch(req)
        except Exception as exc:  # noqa: BLE001
            resp, blob = Response.failure(req.id, ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}"), None

        await ws.send(resp.to_json())
        if blob:
            await ws.send(blob)


async def main(host: str, port: int) -> None:
    if not PLATFORM_OK:
        print("✗ 这个端只能在 Windows 上跑。")
        print(f"  导入失败: {PLATFORM_ERR}")
        print("  在 Mac 上请用: python -m agent.mock_server")
        raise SystemExit(1)

    async with serve(_handler, host, port, max_size=32 * 1024 * 1024):
        print(f"server 已启动: ws://{host}:{port}/ws/control")
        if TOKEN:
            print(f"  已启用 token 校验: ?token={TOKEN}")
        else:
            print("  未启用认证 —— 仅限本机或完全可信的内网使用")
        await asyncio.Future()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default=None)
    a = ap.parse_args()
    TOKEN = a.token

    if a.host == "0.0.0.0" and not a.token:
        print("⚠ 绑定 0.0.0.0 且未设 token：同网段任何设备都能控制这台机器。")
        print("  建议加 --token，或改用 SSH 端口转发。")
        print()
    try:
        asyncio.run(main(a.host, a.port))
    except KeyboardInterrupt:
        print("\n已退出")
