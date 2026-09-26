"""生产 / 采集自定义序列库：蓝图ID 生成、步骤校验与序列化。

序列只是「编排」（步骤 + 循环设置），运行断点仍由前端本地续传；本模块只保证入库的
结构与长度可信（防止超大 / 畸形负载），ID 语义（materialId / recipeId 是否存在、
当前是否可采集）由前端载入时按共享配置重解析。
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SequenceBlueprint

# 每账号最多保存的序列数（与前端提示一致）。
MAX_SEQUENCES_PER_USER = 5
# 单条序列的步数上限（与前端 game/core/sequence.ts:SEQ_STEP_LIMIT 对齐）。
MAX_STEPS = 50
MAX_NAME_LEN = 24
MAX_STEP_NAME_LEN = 48
MAX_ID_LEN = 48

# 蓝图ID：8 位易读字符（排除 0/O/1/I/L），与好友码同一字符集。
SHARE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SHARE_CODE_LENGTH = 8
_SHARE_CODE_ATTEMPTS = 20

LOOP_MODES = ("once", "count", "infinite")
BLOCK_REASONS = ("level", "region")


async def generate_share_code(db: AsyncSession) -> str:
    """生成唯一蓝图ID（查库重试 + DB 唯一索引兜底）。"""
    for _ in range(_SHARE_CODE_ATTEMPTS):
        code = "".join(secrets.choice(SHARE_CODE_ALPHABET) for _ in range(SHARE_CODE_LENGTH))
        exists = (
            await db.execute(
                select(SequenceBlueprint.id).where(SequenceBlueprint.share_code == code).limit(1)
            )
        ).scalar_one_or_none()
        if exists is None:
            return code
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="蓝图ID生成失败，请稍后再试"
    )


def _bad(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _text(value: Any, field: str, *, max_len: int, required: bool = True) -> str:
    if not isinstance(value, str):
        if not required and value is None:
            return ""
        raise _bad(f"步骤字段 {field} 非法")
    text = value.strip()
    if required and not text:
        raise _bad(f"步骤字段 {field} 不能为空")
    if len(text) > max_len:
        raise _bad(f"步骤字段 {field} 过长")
    return text


def _int(value: Any, field: str, *, lo: int, hi: int) -> int:
    if isinstance(value, bool):
        raise _bad(f"步骤字段 {field} 非法")
    if isinstance(value, (int, float)):
        number = int(value)
    elif isinstance(value, str):
        try:
            number = int(float(value))
        except ValueError:
            raise _bad(f"步骤字段 {field} 非法") from None
    else:
        raise _bad(f"步骤字段 {field} 非法")
    if number < lo or number > hi:
        raise _bad(f"步骤字段 {field} 超出范围")
    return number


def _sanitize_step(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _bad("序列步骤格式非法")
    kind = raw.get("kind")
    if kind not in ("gather", "produce"):
        raise _bad("序列步骤类型非法")
    step: dict[str, Any] = {
        "kind": kind,
        "id": _text(raw.get("id"), "id", max_len=MAX_ID_LEN),
        "name": _text(raw.get("name"), "name", max_len=MAX_STEP_NAME_LEN, required=False),
        "jobId": _text(raw.get("jobId"), "jobId", max_len=16),
        "target": _int(raw.get("target"), "target", lo=1, hi=100000),
    }
    if kind == "gather":
        step["materialId"] = _text(raw.get("materialId"), "materialId", max_len=MAX_ID_LEN)
        step["regionId"] = _int(raw.get("regionId", 0), "regionId", lo=0, hi=10000)
        blocked = raw.get("blocked")
        step["blocked"] = blocked if blocked in BLOCK_REASONS else None
        if raw.get("requiredLevel") is not None:
            step["requiredLevel"] = _int(raw.get("requiredLevel"), "requiredLevel", lo=0, hi=1000)
    else:
        step["recipeId"] = _text(raw.get("recipeId"), "recipeId", max_len=MAX_ID_LEN)
    return step


def sanitize_steps(raw: Any) -> list[dict[str, Any]]:
    """校验并归一化步骤列表（未知字段一律丢弃，防止畸形负载入库）。"""
    if not isinstance(raw, list) or not raw:
        raise _bad("序列至少需要一个步骤")
    if len(raw) > MAX_STEPS:
        raise _bad(f"序列最多 {MAX_STEPS} 步")
    return [_sanitize_step(step) for step in raw]


def normalize_loop_mode(value: Any) -> str:
    return value if value in LOOP_MODES else "once"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_sequence(
    seq: SequenceBlueprint, *, include_steps: bool = True, include_id: bool = True
) -> dict[str, Any]:
    steps = list(seq.steps or [])
    data: dict[str, Any] = {
        "name": seq.name,
        "shareCode": seq.share_code,
        "loopMode": seq.loop_mode,
        "loopTotal": seq.loop_total,
        "stepCount": len(steps),
        "createdAt": _iso(seq.created_at),
        "updatedAt": _iso(seq.updated_at),
    }
    if include_id:
        data["id"] = seq.id
    if include_steps:
        data["steps"] = steps
    return data
