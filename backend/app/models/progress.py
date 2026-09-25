"""地区进度、图鉴、新手指引、酒馆。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType, TimestampMixin


class RegionProgress(Base, TimestampMixin):
    __tablename__ = "region_progress"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "difficulty", "region_id", name="uq_progress_user_region_difficulty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    region_id: Mapped[int] = mapped_column(sa.Integer)
    # 地区战斗难度等级：每个难度独立记录解锁/通关（周目制）。0 = 基础难度。
    difficulty: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    unlocked: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    cleared: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    cleared_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    best_clear_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)


class CodexEquipment(Base, TimestampMixin):
    """装备图鉴：按底材记录，品阶为子进度。"""

    __tablename__ = "codex_equipment"
    __table_args__ = (sa.UniqueConstraint("user_id", "base_id", name="uq_codex_equip"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    base_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    unlocked_rarities: Mapped[list] = mapped_column(JsonType, default=list)
    total_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    first_unlock_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class CodexMonster(Base, TimestampMixin):
    __tablename__ = "codex_monsters"
    __table_args__ = (sa.UniqueConstraint("user_id", "monster_id", name="uq_codex_monster"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    monster_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    kill_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    first_defeat_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class CodexTerm(Base, TimestampMixin):
    """词条图鉴：普通/稀有/太古分别记录为独立子项。"""

    __tablename__ = "codex_terms"
    __table_args__ = (sa.UniqueConstraint("user_id", "term_id", "quality", name="uq_codex_term"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    term_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    quality: Mapped[str] = mapped_column(sa.String(16))
    first_seen_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class CodexMaterial(Base, TimestampMixin):
    """材料图鉴：采集材料与半成品，首次获得即永久解锁（出售/消耗不撤销）。"""

    __tablename__ = "codex_materials"
    __table_args__ = (sa.UniqueConstraint("user_id", "item_id", name="uq_codex_material"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    total_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    first_unlock_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class TutorialProgress(Base):
    __tablename__ = "tutorial_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    current_step: Mapped[int] = mapped_column(sa.Integer, default=1)
    completed: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    skipped: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    rewarded: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class TavernState(Base):
    __tablename__ = "tavern"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    candidate: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    # 十连抽结果：一次抽出的 10 个候选（购买其中 1 个后清空）
    multi_candidates: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    refreshed_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    free_refresh_used_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    # 太古属性保底：距上次出太古已生成的候选数；满 talents.ancientPityCount 则下一个必出
    ancient_pity: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")


class AutoSellSetting(Base):
    __tablename__ = "auto_sell_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    rarities: Mapped[list] = mapped_column(JsonType, default=lambda: ["common", "uncommon"])
    # 自动卖鱼：按鱼的档位（normal / king / emperor / legend）多选。
    fish_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    fish_kinds: Mapped[list] = mapped_column(JsonType, default=lambda: ["normal"], server_default=sa.text("'[]'"))
