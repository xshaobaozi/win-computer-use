"""双机通信契约 —— 跨平台、纯标准库。

这个文件是 Mac(agent) 与 Windows(server) 之间**唯一**的耦合点。
改它等于同时改两端，务必单独提交、单独 review。

消息格式（对应 docs/01 第五节）::

    请求  {"id": "r1", "op": "capture", "args": {...}}
    响应  {"id": "r1", "ok": true,  "data":  {...}}
          {"id": "r1", "ok": false, "error": {"code": "...", "message": "..."}}

设计约束：
1. 每个请求必须带 id，响应原样带回 —— 允许并发乱序。
2. 坐标必须显式声明 space，禁止依赖默认值（DPI 三套坐标空间是最大的坑）。
3. 元素 box 统一为 [x, y, w, h]，屏幕绝对坐标、物理像素。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "0.1"

# ---------------------------------------------------------------- 操作码
OP_WINDOWS = "windows.list"
OP_CAPTURE = "capture"
OP_UIA_QUERY = "uia.query"
OP_CLICK = "click"
OP_TYPE = "type"

ALL_OPS = (OP_WINDOWS, OP_CAPTURE, OP_UIA_QUERY, OP_CLICK, OP_TYPE)

# ---------------------------------------------------------------- 坐标空间
SPACE_PHYSICAL = "physical"   # 物理像素，推荐默认
SPACE_LOGICAL = "logical"     # 逻辑像素（受 DPI 缩放影响，慎用）
SPACE_IMAGE = "image"         # 截图图像坐标，服务端负责换算

# ---------------------------------------------------------------- 输入方式
TYPE_VALUE = "value"          # 首选：UIA ValuePattern 直接赋值
TYPE_CLIPBOARD = "clipboard"  # 次选：剪贴板 + Ctrl+V，中文最稳
TYPE_KEYS = "keystrokes"      # 兜底：逐字符 SendInput，中文易丢字


class ErrorCode:
    BAD_REQUEST = "bad_request"
    UNKNOWN_OP = "unknown_op"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    WINDOW_GONE = "window_gone"
    INTERNAL = "internal"


# ---------------------------------------------------------------- 消息
@dataclass
class Request:
    op: str
    args: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_json(self) -> str:
        return json.dumps(
            {"id": self.id, "op": self.op, "args": self.args}, ensure_ascii=False
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "Request":
        d = json.loads(raw)
        op = d.get("op")
        if op not in ALL_OPS:
            raise ValueError(f"unknown op: {op!r}")
        return cls(op=op, args=d.get("args") or {}, id=d.get("id") or uuid.uuid4().hex[:8])


@dataclass
class Response:
    id: str
    ok: bool
    data: Any = None
    error: dict | None = None

    @classmethod
    def success(cls, req_id: str, data: Any = None) -> "Response":
        return cls(id=req_id, ok=True, data=data)

    @classmethod
    def failure(cls, req_id: str, code: str, message: str) -> "Response":
        return cls(id=req_id, ok=False, error={"code": code, "message": message})

    def to_json(self) -> str:
        body: dict = {"id": self.id, "ok": self.ok}
        if self.ok:
            body["data"] = self.data
        else:
            body["error"] = self.error
        return json.dumps(body, ensure_ascii=False)


# ---------------------------------------------------------------- 元素
@dataclass
class Element:
    """一个可交互元素。

    source 标明它从哪一层来，对应 docs/01 的三级降级：
      uia  -> 第 1 级，最准最省
      ocr  -> 第 2 级，兜底文字
      vlm  -> 第 3 级，视觉模型
    """

    index: int
    role: str
    name: str
    box: list  # [x, y, w, h] 屏幕绝对坐标 / 物理像素
    source: str = "uia"
    patterns: list = field(default_factory=list)

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.box
        return x + w // 2, y + h // 2

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "role": self.role,
            "name": self.name,
            "box": list(self.box),
            "source": self.source,
            "patterns": list(self.patterns),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Element":
        return cls(
            index=d["index"],
            role=d.get("role", ""),
            name=d.get("name", ""),
            box=list(d["box"]),
            source=d.get("source", "uia"),
            patterns=list(d.get("patterns") or []),
        )


def find_elements(elements: list[Element], name: str, role: str | None = None) -> list[Element]:
    """按名称子串 + 可选角色筛选。空名不算命中。"""
    hits = []
    for el in elements:
        if not el.name:
            continue
        if name not in el.name:
            continue
        if role and el.role != role:
            continue
        hits.append(el)
    return hits


def signature(elements: list[Element]) -> str:
    """元素表的指纹，用于动作后判断界面到底变没变。

    只取 name + box，忽略 index 顺序抖动。
    """
    parts = sorted(f"{el.role}|{el.name}|{el.box}" for el in elements)
    return "|".join(parts)
