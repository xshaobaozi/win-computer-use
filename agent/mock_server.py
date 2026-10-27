"""假 server —— 在 Mac 上就能跑，用来开发 agent，不需要 Windows。

它实现了完整的 protocol 契约，但所有数据是编出来的：模拟一个 WPS 文档窗口，
点「保存」之后会出现「已保存」文本。这样 agent 的"动作后校验"逻辑可以
在没有真机的情况下先跑通。

有状态：saved / text 会随点击和输入变化，所以校验循环是有意义的，
不是每次都返回同样的假数据。

用法::

    python -m agent.mock_server              # 监听 127.0.0.1:8765
    python -m agent.mock_server --port 9000
"""
from __future__ import annotations

import argparse
import asyncio
import json

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

HWND = 1001

STATE = {"saved": False, "text": "", "prints": 0}


def _window() -> dict:
    return {
        "hwnd": HWND,
        "title": "季度报表.docx - WPS Office",
        "class": "OpusApp",
        "proc": "wps.exe",
        "rect": [100, 100, 1380, 900],
    }


def _elements() -> list[dict]:
    els = [
        {"index": 1, "role": "button", "name": "保存", "box": [790, 330, 46, 28],
         "source": "uia", "patterns": ["InvokePattern"]},
        {"index": 2, "role": "edit", "name": "正文", "box": [300, 200, 600, 400],
         "source": "uia", "patterns": ["ValuePattern"]},
        {"index": 3, "role": "button", "name": "打印", "box": [842, 330, 46, 28],
         "source": "uia", "patterns": ["InvokePattern"]},
    ]
    nxt = 4
    if STATE["text"]:
        els.append({"index": nxt, "role": "text", "name": f"正文内容:{STATE['text'][:20]}",
                    "box": [300, 200, 600, 24], "source": "uia", "patterns": []})
        nxt += 1
    if STATE["saved"]:
        els.append({"index": nxt, "role": "text", "name": "已保存", "box": [700, 300, 120, 20],
                    "source": "uia", "patterns": []})
        nxt += 1
    if STATE["prints"]:
        els.append({"index": nxt, "role": "text", "name": f"打印任务已提交 x{STATE['prints']}",
                    "box": [700, 320, 220, 20], "source": "uia", "patterns": []})
    return els


def _hit(el: dict, x: int, y: int) -> bool:
    ex, ey, ew, eh = el["box"]
    return ex <= x <= ex + ew and ey <= y <= ey + eh


def handle(req: Request) -> Response:
    try:
        if req.op == OP_WINDOWS:
            return Response.success(req.id, [_window()])

        if req.op == OP_CAPTURE:
            return Response.success(req.id, {
                "hwnd": req.args.get("hwnd", HWND),
                "w": 1280, "h": 800, "dpi": 144,
                "image": None,  # mock 不产图，真 server 返回二进制
                "elements": _elements(),
                "space": "physical",
            })

        if req.op == OP_UIA_QUERY:
            name = req.args.get("name")
            role = req.args.get("role")
            hits = [
                e for e in _elements()
                if (name is None or name in e["name"]) and (role is None or e["role"] == role)
            ]
            return Response.success(req.id, {"elements": hits})

        if req.op == OP_CLICK:
            x, y = int(req.args.get("x", 0)), int(req.args.get("y", 0))
            for el in _elements():
                if _hit(el, x, y):
                    if el["name"] == "保存":
                        STATE["saved"] = True
                    elif el["name"] == "打印":
                        STATE["prints"] += 1
                    return Response.success(req.id, {"clicked": True, "hit": el["name"]})
            return Response.success(req.id, {"clicked": True, "hit": None})

        if req.op == OP_TYPE:
            STATE["text"] = str(req.args.get("text", ""))
            return Response.success(req.id, {"typed": len(STATE["text"])})

        return Response.failure(req.id, ErrorCode.UNKNOWN_OP, f"未实现: {req.op}")

    except Exception as exc:  # noqa: BLE001
        return Response.failure(req.id, ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}")


async def _handler(ws) -> None:
    async for raw in ws:
        try:
            req = Request.from_json(raw)
        except Exception as exc:  # noqa: BLE001
            await ws.send(json.dumps({"id": None, "ok": False,
                                      "error": {"code": ErrorCode.BAD_REQUEST, "message": str(exc)}}))
            continue
        await ws.send(handle(req).to_json())


async def main(host: str, port: int) -> None:
    async with serve(_handler, host, port):
        print(f"mock server 已启动: ws://{host}:{port}/ws/control")
        print("这是个假 server，数据是编的。Ctrl-C 退出。")
        await asyncio.Future()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    try:
        asyncio.run(main(a.host, a.port))
    except KeyboardInterrupt:
        print("\n已退出")
