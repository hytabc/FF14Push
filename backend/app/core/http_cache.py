"""条件请求（ETag / 304）工具：为大响应省掉重复下载。

序列化口径与 Starlette `JSONResponse.render` 完全一致（`jsonable_encoder` 后
`ensure_ascii=False / allow_nan=False / separators=(",",":")`），因此接入本工具
不改变任何接口的 JSON 形态。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import Response


def _etag_for(body: bytes) -> str:
    return '"' + hashlib.sha1(body).hexdigest() + '"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = {c.strip() for c in if_none_match.split(",")}
    return "*" in candidates or etag in candidates or f"W/{etag}" in candidates


def json_body_and_etag(payload: Any) -> tuple[bytes, str]:
    """把 payload 序列化为 (body bytes, ETag)。

    序列化口径与 Starlette `JSONResponse.render` 完全一致。对**进程内不变的**响应
    （如 `/game/config`）可缓存本函数的返回值，避免每次请求重复编码 + 哈希。
    """
    body = json.dumps(
        jsonable_encoder(payload),
        ensure_ascii=False,
        allow_nan=False,
        indent=None,
        separators=(",", ":"),
    ).encode("utf-8")
    return body, _etag_for(body)


def respond(
    request: Request,
    body: bytes,
    etag: str,
    *,
    cache_control: str = "no-cache",
    vary: str | None = None,
) -> Response:
    """按 `If-None-Match` 返回 304 或带 `ETag` 的完整 JSON 响应。"""
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if vary:
        headers["Vary"] = vary
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


def conditional_json(
    request: Request,
    payload: Any,
    *,
    cache_control: str = "no-cache",
    vary: str | None = None,
) -> Response:
    """返回带 `ETag` 的 JSON 响应；`If-None-Match` 命中时返回 304（无 body）。

    - `Cache-Control: no-cache`：允许浏览器存储，但每次必须回源校验；
      内容未变时只回 304 头，省掉整个响应体。
    - `vary="Authorization"`：响应按用户个性化，避免同一浏览器切换账号后串用缓存。
    """
    body, etag = json_body_and_etag(payload)
    return respond(request, body, etag, cache_control=cache_control, vary=vary)
