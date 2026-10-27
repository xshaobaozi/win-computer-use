"""WebSocket 客户端 —— 同一份代码既连本机 mock，也连局域网里的 Windows。

这就是 docs/01 里说的"接口同构"：上层工具不需要知道对面是 localhost
还是一台远端机器，只改 URL。

用法::

    async with Remote("ws://192.168.1.20:8765/ws/control") as r:
        wins = await r.windows()
        shot = await r.capture(wins[0]["hwnd"])   # shot["image"] 是 JPEG bytes
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from websockets.asyncio.client import connect

from protocol.schema import (
    OP_CAPTURE,
    OP_CLICK,
    OP_TYPE,
    OP_UIA_QUERY,
    OP_WINDOWS,
    SPACE_PHYSICAL,
    TYPE_CLIPBOARD,
    Element,
    ErrorCode,
    Request,
    Response,
)

DEFAULT_URL = os.environ.get("WCU_SERVER", "ws://127.0.0.1:8765/ws/control")


class RemoteError(RuntimeError):
    """server 明确返回失败，或通信层超时。code 来自 protocol.ErrorCode。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def _with_token(url: str) -> str:
    token = os.environ.get("WCU_TOKEN")
    if not token or "token=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}token={token}"


class Remote:
    def __init__(self, url: str | None = None, timeout: float = 30.0, retries: int = 1):
        self.url = _with_token(url or DEFAULT_URL)
        self.timeout = timeout
        self.retries = retries
        self._ws = None

    # ------------------------------------------------------------ 生命周期
    async def __aenter__(self) -> "Remote":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._ws is None:
            self._ws = await connect(
                self.url, open_timeout=self.timeout, max_size=32 * 1024 * 1024
            )

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    # ------------------------------------------------------------ 主调用
    async def _request(self, op: str, **args: Any) -> tuple[Any, bytes | None]:
        """发请求、收响应，顺带把紧随其后的二进制帧捞出来（截图走这条路）。"""
        await self.connect()
        last: Exception | None = None

        for _ in range(self.retries + 1):
            req = Request(op=op, args=args)
            try:
                await self._ws.send(req.to_json())
                blob: bytes | None = None
                while True:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=self.timeout)
                    if isinstance(raw, (bytes, bytearray)):
                        blob = bytes(raw)
                        continue
                    resp = self._parse(raw)
                    if resp.id != req.id:
                        continue  # 乱序响应，继续等自己那条
                    if not resp.ok:
                        err = resp.error or {}
                        raise RemoteError(err.get("code", ErrorCode.INTERNAL), err.get("message", ""))
                    data = resp.data
                    # server 先发 JSON 再发二进制，按 image_len 决定要不要多收一帧
                    if isinstance(data, dict) and data.get("image_len") and blob is None:
                        nxt = await asyncio.wait_for(self._ws.recv(), timeout=self.timeout)
                        if isinstance(nxt, (bytes, bytearray)):
                            blob = bytes(nxt)
                    return data, blob
            except asyncio.TimeoutError as exc:
                last = exc
                continue

        raise RemoteError(
            ErrorCode.TIMEOUT, f"{op} 超时 {self.timeout}s，已重试 {self.retries} 次"
        ) from last

    async def call(self, op: str, **args: Any) -> Any:
        data, _ = await self._request(op, **args)
        return data

    @staticmethod
    def _parse(raw) -> Response:
        d = json.loads(raw)
        return Response(id=d.get("id") or "", ok=bool(d.get("ok")), data=d.get("data"), error=d.get("error"))

    # ------------------------------------------------------------ 语法糖
    async def windows(self) -> list[dict]:
        return await self.call(OP_WINDOWS)

    async def capture(self, hwnd: int, marks: bool = True, scale: float = 1.0) -> dict:
        """返回 {..., elements: [Element], image: bytes|None}。

        elements 已解析成 Element 对象；image 是 JPEG 原始字节。
        """
        data, blob = await self._request(OP_CAPTURE, hwnd=hwnd, marks=marks, scale=scale)
        data["elements"] = [Element.from_dict(e) for e in data.get("elements", [])]
        data["image"] = blob
        return data

    async def query(self, hwnd: int, name: str | None = None, role: str | None = None) -> list[Element]:
        data = await self.call(OP_UIA_QUERY, hwnd=hwnd, name=name, role=role)
        return [Element.from_dict(e) for e in data.get("elements", [])]

    async def click(self, x: int, y: int, hwnd: int | None = None,
                    space: str = SPACE_PHYSICAL, button: str = "left") -> dict:
        args: dict = {"x": x, "y": y, "space": space, "button": button}
        if hwnd is not None:
            args["hwnd"] = hwnd
        return await self.call(OP_CLICK, **args)

    async def type_text(self, text: str, method: str = TYPE_CLIPBOARD) -> dict:
        return await self.call(OP_TYPE, text=text, method=method)
