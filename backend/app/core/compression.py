"""响应 brotli 压缩与请求体 gzip 解压（纯 ASGI 中间件）。

响应侧：客户端支持 `br` 时用 brotli 压缩，体积低于阈值或类型不可压缩时原样透传，
仍由外层 `GZipMiddleware` 兜底。**因此注册顺序必须是「先 Brotli 再 GZip」**：
后注册的中间件在外层，Starlette 的 GZip 见到已存在的 `Content-Encoding` 会跳过。

请求侧：客户端以 `Content-Encoding: gzip` 压缩请求体时在此解压后交给下游。
解压设上限（防 gzip bomb），超限返回 413。
"""

from __future__ import annotations

import zlib

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:  # pragma: no cover - 依赖缺失时保持服务可启动，只是不压缩
    import brotli
except ImportError:  # pragma: no cover
    brotli = None  # type: ignore[assignment]

# 可压缩的响应类型（与 nginx gzip_types 口径接近）。
_COMPRESSIBLE_PREFIXES = ("text/",)
_COMPRESSIBLE_EXACT = frozenset(
    {
        "application/json",
        "application/javascript",
        "application/x-javascript",
        "application/xml",
        "application/xhtml+xml",
        "application/rss+xml",
        "application/atom+xml",
        "application/ld+json",
        "application/manifest+json",
        "image/svg+xml",
    }
)


def _is_compressible(content_type: str) -> bool:
    value = content_type.split(";", 1)[0].strip().lower()
    if not value:
        return False
    return (
        value.startswith(_COMPRESSIBLE_PREFIXES)
        or value in _COMPRESSIBLE_EXACT
        or value.endswith(("+json", "+xml"))
    )


async def _unattached_send(message: Message) -> None:  # pragma: no cover
    raise RuntimeError("send awaitable not set")


class BrotliMiddleware:
    """响应 brotli 压缩。"""

    def __init__(self, app: ASGIApp, minimum_size: int = 1024, quality: int = 4) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.quality = quality

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or brotli is None:
            await self.app(scope, receive, send)
            return
        if "br" not in Headers(scope=scope).get("Accept-Encoding", ""):
            await self.app(scope, receive, send)
            return
        await _BrotliResponder(self.app, self.minimum_size, self.quality)(scope, receive, send)


class _BrotliResponder:
    """缓冲响应体后一次性 brotli 压缩（接口响应均为完整 JSON，无需流式压缩）。"""

    def __init__(self, app: ASGIApp, minimum_size: int, quality: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.quality = quality
        self.send: Send = _unattached_send
        self.initial_message: Message = {}
        self.skip = False
        self.buffer = bytearray()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.send = send
        await self.app(scope, receive, self.send_with_brotli)

    async def send_with_brotli(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.initial_message = message
            headers = Headers(raw=message["headers"])
            status = int(message.get("status", 200))
            # 已编码 / 无正文状态码 / 不可压缩类型 → 原样透传（外层 GZip 仍可兜底）。
            self.skip = (
                "content-encoding" in headers
                or status in (204, 304)
                or status < 200
                or not _is_compressible(headers.get("content-type", ""))
            )
            if self.skip:
                await self.send(message)
            return

        if self.skip:
            await self.send(message)
            return

        self.buffer += message.get("body", b"")
        if message.get("more_body", False):
            return

        body = bytes(self.buffer)
        if len(body) < self.minimum_size:
            await self.send(self.initial_message)
            await self.send({"type": "http.response.body", "body": body})
            return

        compressed = brotli.compress(body, quality=self.quality)
        headers = MutableHeaders(raw=self.initial_message["headers"])
        headers["Content-Encoding"] = "br"
        headers["Content-Length"] = str(len(compressed))
        headers.add_vary_header("Accept-Encoding")
        await self.send(self.initial_message)
        await self.send({"type": "http.response.body", "body": compressed})


class RequestDecompressMiddleware:
    """请求体 gzip 解压（Content-Encoding: gzip）。"""

    def __init__(self, app: ASGIApp, max_decompressed_bytes: int) -> None:
        self.app = app
        self.max_decompressed_bytes = max_decompressed_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if "gzip" not in Headers(scope=scope).get("Content-Encoding", "").lower():
            await self.app(scope, receive, send)
            return

        raw = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            raw += message.get("body", b"")
            if not message.get("more_body", False):
                break

        try:
            body = _gunzip_limited(bytes(raw), self.max_decompressed_bytes)
        except _TooLarge:
            await _plain_error(send, 413, "请求体解压后过大")
            return
        except zlib.error:
            await _plain_error(send, 400, "请求体 gzip 解码失败")
            return

        # 下游按明文 JSON 处理：移除 content-encoding，修正 content-length。
        headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"content-encoding"]
        headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode()))
        scope = {**scope, "headers": headers}

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


class _TooLarge(Exception):
    pass


def _gunzip_limited(data: bytes, limit: int) -> bytes:
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)  # gzip 包装
    out = decompressor.decompress(data, limit + 1)
    if len(out) > limit or decompressor.unconsumed_tail:
        raise _TooLarge
    out += decompressor.flush()
    if len(out) > limit:
        raise _TooLarge
    return out


async def _plain_error(send: Send, status: int, detail: str) -> None:
    import json

    body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
