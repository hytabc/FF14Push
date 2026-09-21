"""账号与英雄。"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(sa.String(128))
    nickname: Mapped[str] = mapped_column(sa.String(64))
    gold: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    # 封号：登录与所有已认证请求都会被拒绝，且不参与排行榜。
    # 注意：对外只返回机器码，不返回任何封禁文案（见 `core/security.BANNED_DETAIL`）。
    banned: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    banned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    hero: Mapped["Hero | None"] = relationship(back_populates="user", uselist=False)
    items: Mapped[list["Item"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Hero(Base, TimestampMixin):
    __tablename__ = "heroes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(64))
    level: Mapped[int] = mapped_column(sa.Integer, default=1)
    exp: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    talent: Mapped[str] = mapped_column(sa.String(16), default="common")
    attr_bias: Mapped[str] = mapped_column(sa.String(16), default="balanced")
    strength: Mapped[int] = mapped_column(sa.Integer, default=0)
    agility: Mapped[int] = mapped_column(sa.Integer, default=0)
    intellect: Mapped[int] = mapped_column(sa.Integer, default=0)
    # 太古属性：值为 "str"|"dex"|"int"，表示该条三维为太古（最高值 ×1.25）；None 表示无
    ancient_attr: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    current_region_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True, default=1)
    region_kill_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    is_initial: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="hero")
    skill_stats: Mapped[list["HeroSkillStat"]] = relationship(
        back_populates="hero", cascade="all, delete-orphan"
    )


class HeroSkillStat(Base):
    __tablename__ = "hero_skill_stats"
    __table_args__ = (sa.UniqueConstraint("hero_id", "skill_id", name="uq_hero_skill"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hero_id: Mapped[int] = mapped_column(sa.ForeignKey("heroes.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(sa.String(16))
    skill_id: Mapped[str] = mapped_column(sa.String(32))
    cast_count: Mapped[int] = mapped_column(sa.BigInteger, default=0)

    hero: Mapped[Hero] = relationship(back_populates="skill_stats")
