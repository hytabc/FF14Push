"""条件请求：`/game/state` 与 `/game/config` 的 ETag / 304。"""

from __future__ import annotations

from starlette.requests import Request

from app.core.http_cache import conditional_json

API = "/api/v1"


def _request(if_none_match: str | None = None) -> Request:
    headers = [(b"if-none-match", if_none_match.encode())] if if_none_match else []
    return Request(
        {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": headers}
    )


def test_conditional_json_etag_differs_by_payload() -> None:
    """内容不同 → ETag 必须不同（否则会错误返回 304 掩盖新数据）。"""
    a = conditional_json(_request(), {"a": 1})
    b = conditional_json(_request(), {"a": 2})
    assert a.headers["etag"] != b.headers["etag"]


def test_conditional_json_revalidation_returns_304() -> None:
    first = conditional_json(_request(), {"a": 1, "b": [1, 2, 3]})
    etag = first.headers["etag"]
    second = conditional_json(_request(etag), {"a": 1, "b": [1, 2, 3]})
    assert second.status_code == 304
    assert second.body == b""


def test_conditional_json_weak_and_list_if_none_match() -> None:
    etag = conditional_json(_request(), {"a": 1}).headers["etag"]
    assert conditional_json(_request(f"W/{etag}"), {"a": 1}).status_code == 304
    assert conditional_json(_request(f'"other", {etag}'), {"a": 1}).status_code == 304


async def test_config_has_etag_and_cache_control(client) -> None:
    resp = await client.get(f"{API}/game/config")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("etag")
    assert resp.headers.get("cache-control") == "public, max-age=3600"
    assert "rarities" in resp.json()


async def test_config_etag_revalidation_returns_304(client) -> None:
    first = await client.get(f"{API}/game/config")
    second = await client.get(
        f"{API}/game/config", headers={"If-None-Match": first.headers["etag"]}
    )
    assert second.status_code == 304, second.text
    assert second.content == b""


async def test_config_stale_etag_returns_full_body(client) -> None:
    """ETag 不匹配时必须回完整 200，而不是 304。"""
    resp = await client.get(f"{API}/game/config", headers={"If-None-Match": '"stale"'})
    assert resp.status_code == 200, resp.text
    assert "rarities" in resp.json()


async def test_config_response_is_built_once(client, monkeypatch) -> None:
    """静态配置的序列化 + 哈希应只做一次（后续请求直接复用）。"""
    from app.api.v1 import game as game_module
    from app.core import http_cache

    calls = {"n": 0}
    original = http_cache.json_body_and_etag

    def counting(payload):
        calls["n"] += 1
        return original(payload)

    # game.py 从 http_cache 直接导入了该函数，需同时打补丁到其命名空间。
    monkeypatch.setattr(game_module, "json_body_and_etag", counting)
    game_module._CONFIG_RESPONSE = None

    first = await client.get(f"{API}/game/config")
    second = await client.get(f"{API}/game/config")
    third = await client.get(f"{API}/game/config", headers={"If-None-Match": first.headers["etag"]})

    assert calls["n"] == 1, "配置响应只应构造一次"
    assert first.status_code == second.status_code == 200
    assert first.headers["etag"] == second.headers["etag"]
    assert third.status_code == 304


async def test_state_has_etag_and_vary(client, auth_client) -> None:
    resp = await auth_client.get(f"{API}/game/state")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("etag")
    assert resp.headers.get("cache-control") == "no-cache"
    assert "authorization" in resp.headers.get("vary", "").lower()


async def test_state_etag_revalidation_returns_304(client, auth_client) -> None:
    first = await auth_client.get(f"{API}/game/state")
    second = await auth_client.get(
        f"{API}/game/state", headers={"If-None-Match": first.headers["etag"]}
    )
    assert second.status_code == 304, second.text
    assert second.content == b""
