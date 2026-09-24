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
    # 累计在线时长（毫秒）：由战斗 / 采集 / 生产 / 钓鱼 / 副本的服务端上报窗口累加，离线不计入。
    play_ms: Mapped[int] = mapped_column(sa.BigInteger, default=0, server_default="0")
    # 好友码：唯一、可分享的加好友凭证（注册 / 迁移时生成，8 位易读字符）。
    friend_code: Mapped[str | None] = mapped_column(sa.String(12), unique=True, index=True, nullable=True)
    # 最近活跃时间：好友在线状态依据（前端心跳刷新）。在线 = now - last_seen_at < 阈值。
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    # 反多开：注册 IP 与最近请求 IP。与 `user_devices` 一起判定「同一人」的多个账号（见 services/devices.py）。
    reg_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    # 地区战斗难度等级（0 = 当前各地区数值）。battle_difficulty 为当前选择，battle_difficulty_max 为已解锁上限。
    # 见 services/difficulty.py 与 shared/data/combat.json:difficulty。
    battle_difficulty: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    battle_difficulty_max: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    # 种田：已解锁的田地数量（初始 2，最多 10）。见 services/farm.py 与 shared/data/farm.json。
    farm_unlocked: Mapped[int] = mapped_column(sa.Integer, default=2, server_default="2")
    # 佩戴中的称号（titles.json 的 title id）；None = 不佩戴。最多一个，展示在排行榜 / 玩家资料。
    active_title_id: Mapped[str | None] = mapped_column(sa.String(48), nullable=True)

    active_hero_id: Mapped[int | None] = mapped_column(sa.ForeignKey("heroes.id", ondelete="SET NULL", use_alter=True, name="fk_users_active_hero"), nullable=True)
    hero: Mapped["Hero | None"] = relationship(foreign_keys=[active_hero_id], post_update=True)
    heroes: Mapped[list["Hero"]] = relationship(back_populates="user", foreign_keys="Hero.user_id")
    items: Mapped[list["Item"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Hero(Base, TimestampMixin):
    __tablename__ = "heroes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
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
    # 彩蛋英雄 id（见 shared/data/egg-heroes.json）；None 表示普通英雄
    egg_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    # 彩蛋技能「拔豆芽」剩余的奖励翻倍怪物数（服务端权威结算）
    double_reward_charges: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    current_region_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True, default=1)
    region_kill_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    is_initial: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="heroes", foreign_keys=[user_id])
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


class UserDevice(Base, TimestampMixin):
    """账号 ↔ 设备指纹（浏览器指纹）关联。反多开依据：同一设备最多注册 N 个账号，
    关联账号之间的转账 / 交易板额度另有限制（见 services/devices.py）。"""

    __tablename__ = "user_devices"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "device_id", name="uq_user_device"),
        sa.Index("ix_user_devices_device", "device_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[str] = mapped_column(sa.String(64))
    # 该账号在此设备上首次 / 最近出现的 IP（用于 IP 维度的关联判定）
    first_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
