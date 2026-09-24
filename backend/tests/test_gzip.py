"""响应体压缩：大响应在客户端支持 gzip 时应带 `Content-Encoding: gzip`（见 app/main.py）。"""

from __future__ import annotations

API = "/api/v1"


async def test_large_response_is_gzipped(client) -> None:
    """静态配置接口（大 JSON）远超 minimum_size，应被压缩。"""
    resp = await client.get(f"{API}/game/config", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") == "gzip"
    # 解压后仍是合法 JSON（httpx 会自动解压）
    assert "rarities" in resp.json()


async def test_small_response_not_compressed(client) -> None:
    """健康检查响应很小，低于 minimum_size，不应被压缩。"""
    resp = await client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") is None


async def test_no_gzip_without_accept_encoding(client) -> None:
    """客户端不支持 gzip 时不压缩。"""
    resp = await client.get(f"{API}/game/config", headers={"Accept-Encoding": "identity"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") is None
