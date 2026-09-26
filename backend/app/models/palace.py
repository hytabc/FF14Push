"""死者宫殿：与账号战力完全隔离的 roguelike 深层迷宫。

- `PalaceProfile`：每账号一行，账号级进度——成长点余额、代币（烈火纹章 / 玻璃南瓜）、
  通关第 10 层次数、已解锁成长节点列表。
- `PalaceRun`：每账号至多一份进行中的运行（run）快照——副本英雄、装备、BUFF、路径图、
  当前节点、待领奖励等。副本内的一切数据都存这里，不落 `items` 表、不动账号面板。

时间统一用 epoch 浮点（与 world_boss / ishgard 一致，避免方言差异）。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType

# run 状态
STATUS_CHOOSING_HERO = "choosing_hero"
STATUS_CHOOSING_WEAPON = "choosing_weapon"
STATUS_RUNNING = "running"
ENDED = "ended"
STATUS_ENDED = ENDED


class PalaceProfile(Base):
    __tablename__ = "palace_profiles"
    __table_args__ = (sa.UniqueConstraint("user_id", name="uq_palace_profile_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    growth_points: Mapped[int] = mapped_column(default=0)
    total_growth_earned: Mapped[int] = mapped_column(default=0)
    flame_crest: Mapped[int] = mapped_column(default=0)
    glass_pumpkin: Mapped[int] = mapped_column(default=0)
    floor10_clears: Mapped[int] = mapped_column(default=0)
    # 已解锁的成长节点 id 列表。
    unlocked: Mapped[list] = mapped_column(JsonType, default=list)
    created_at: Mapped[float] = mapped_column(sa.Float, default=0)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)


class PalaceRun(Base):
    __tablename__ = "palace_runs"
    __table_args__ = (sa.UniqueConstraint("user_id", name="uq_palace_run_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(sa.String(24), default=STATUS_CHOOSING_HERO)
    # 结束原因：completed（通关第 10 层）/ death（阵亡且无复活）/ abandoned / superseded
    ended_reason: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    floor: Mapped[int] = mapped_column(default=1)
    step: Mapped[int] = mapped_column(default=1)
    # 副本英雄快照：level / exp / talent / strength / agility / intellect / jobId / attrs。
    hero: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    hero_candidates: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    weapon_candidates: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    # 当前层路径图（rows / edges / seed）。
    map: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    current_node: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    # 副本装备列表（item_factory 生成的装备字典）与穿戴映射 slot→itemIndex。
    items: Mapped[list] = mapped_column(JsonType, default=list)
    equipped: Mapped[dict] = mapped_column(JsonType, default=dict)
    # 副本持久 BUFF（[{id,name,stat,value,desc}]）。
    buffs: Mapped[list] = mapped_column(JsonType, default=list)
    run_gold: Mapped[int] = mapped_column(default=0)
    # 待领奖励三选一（[{kind, equip?, buff?}]）与待结算节点上下文。
    pending_reward: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    pending_node: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    revive_left: Mapped[int] = mapped_column(default=0)
    # 当前战斗节点的校验快照与开始时间（服务端时钟）。
    snapshot: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    node_started_at: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    created_at: Mapped[float] = mapped_column(sa.Float, default=0)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)
