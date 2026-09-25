"""传输层压缩：响应 brotli 协商、请求体 gzip 解压（含 bomb / 坏数据）。

响应 gzip 的用例仍在 `test_gzip.py`；本文件覆盖阶段 2 新增的 brotli 与请求解压。
"""

from __future__ import annotations

import gzip

API = "/api/v1"


async def test_large_response_is_brotli_encoded(client) -> None:
    """声明支持 br 时，大 JSON 响应应带 `Content-Encoding: br`。"""
    resp = await client.get(f"{API}/game/config", headers={"Accept-Encoding": "br"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") == "br"
    # httpx 会自动解压，解压后仍是合法 JSON
    assert "rarities" in resp.json()


async def test_brotli_preferred_over_gzip(client) -> None:
    """同时支持 br 与 gzip 时优先 brotli。"""
    resp = await client.get(f"{API}/game/config", headers={"Accept-Encoding": "gzip, br"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") == "br"


async def test_gzip_fallback_without_brotli(client) -> None:
    """只支持 gzip 时回退 gzip（brotli 中间件跳过，外层 GZip 兜底）。"""
    resp = await client.get(f"{API}/game/config", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") == "gzip"


async def test_small_response_not_brotli(client) -> None:
    """小响应低于阈值，不压缩。"""
    resp = await client.get("/health", headers={"Accept-Encoding": "br"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") is None


async def test_request_body_gzip_accepted(client) -> None:
    """请求体以 gzip 压缩（Content-Encoding: gzip）时服务端应正常解压处理。"""
    import json

    payload = json.dumps(
        {"username": "gzuser", "password": "secret123", "nickname": "压缩战士"}
    ).encode()
    compressed = gzip.compress(payload)
    resp = await client.post(
        f"{API}/auth/register",
        content=compressed,
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["accessToken"]


async def test_request_body_gzip_bomb_rejected(client) -> None:
    """解压后超过上限（gzip bomb）应被拒绝为 413，且不交给下游处理。"""
    bomb = gzip.compress(b"\x00" * (9 * 1024 * 1024))
    resp = await client.post(
        f"{API}/auth/register",
        content=bomb,
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )
    assert resp.status_code == 413, resp.text


async def test_request_body_bad_gzip_rejected(client) -> None:
    """非法 gzip 请求体应返回 400。"""
    resp = await client.post(
        f"{API}/auth/register",
        content=b"not-a-gzip-stream",
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400, resp.text
