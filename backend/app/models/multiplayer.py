"""Durable multiplayer state. JSON values are replaced atomically, never mutated in place."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, JsonType

class HeroRegistration(Base):
    __tablename__ = 'hero_registrations'
    __table_args__ = (sa.UniqueConstraint('hero_id', 'kind', name='uq_registration_hero_kind'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'), index=True)
    hero_id: Mapped[int] = mapped_column(sa.ForeignKey('heroes.id', ondelete='CASCADE'))
    kind: Mapped[str] = mapped_column(sa.String(12))
    active: Mapped[bool] = mapped_column(default=True)
    snapshot: Mapped[dict] = mapped_column(JsonType)

class CoopRoom(Base):
    __tablename__ = 'coop_rooms'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(12), unique=True)
    owner_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'))
    dungeon_id: Mapped[str] = mapped_column(sa.String(32))
    mode: Mapped[str] = mapped_column(sa.String(12))
    status: Mapped[str] = mapped_column(sa.String(16), default='lobby', index=True)
    public: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[float] = mapped_column(sa.Float)

class CoopMember(Base):
    __tablename__ = 'coop_members'
    __table_args__ = (sa.UniqueConstraint('room_id', 'user_id', name='uq_room_member'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(sa.ForeignKey('coop_rooms.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'), index=True)
    ready: Mapped[bool] = mapped_column(default=False)
    heartbeat_at: Mapped[float] = mapped_column(sa.Float)

class CoopSeat(Base):
    __tablename__ = 'coop_seats'
    __table_args__ = (sa.UniqueConstraint('room_id', 'slot', name='uq_room_seat'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(sa.ForeignKey('coop_rooms.id', ondelete='CASCADE'), index=True)
    slot: Mapped[int] = mapped_column()
    controller_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'))
    hero_id: Mapped[int] = mapped_column()
    registration_id: Mapped[int | None] = mapped_column(nullable=True)
    snapshot: Mapped[dict] = mapped_column(JsonType)

class CoopBattle(Base):
    __tablename__ = 'coop_battles'
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(sa.ForeignKey('coop_rooms.id'), unique=True)
    status: Mapped[str] = mapped_column(sa.String(16), default='running', index=True)
    state: Mapped[dict] = mapped_column(JsonType)
    config: Mapped[dict] = mapped_column(JsonType)
    sequence: Mapped[int] = mapped_column(default=0)
    command_cursor: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[float] = mapped_column(sa.Float)
    lease_until: Mapped[float] = mapped_column(sa.Float, default=0)
    lease_owner: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

class CoopCommand(Base):
    __tablename__ = 'coop_commands'
    __table_args__ = (sa.UniqueConstraint('battle_id', 'user_id', 'key', name='uq_coop_command'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    battle_id: Mapped[int] = mapped_column(sa.ForeignKey('coop_battles.id'), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'))
    key: Mapped[str] = mapped_column(sa.String(64))
    payload: Mapped[dict] = mapped_column(JsonType)

class CoopReward(Base):
    __tablename__ = 'coop_rewards'
    __table_args__ = (sa.UniqueConstraint('battle_id', 'user_id', name='uq_coop_reward'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    battle_id: Mapped[int] = mapped_column(sa.ForeignKey('coop_battles.id'))
    user_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'))
    receipt: Mapped[dict] = mapped_column(JsonType)

class CoopProgress(Base):
    __tablename__ = 'coop_progress'
    __table_args__ = (sa.UniqueConstraint('user_id', 'dungeon_id', name='uq_coop_progress'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'))
    dungeon_id: Mapped[str] = mapped_column(sa.String(32))
    clears: Mapped[int] = mapped_column(default=0)
    records: Mapped[dict] = mapped_column(JsonType, default=dict)

class PvpBattle(Base):
    __tablename__ = 'pvp_battles'
    __table_args__ = (sa.UniqueConstraint('attacker_id', 'key', name='uq_pvp_request'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attacker_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'), index=True)
    defender_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'), index=True)
    key: Mapped[str] = mapped_column(sa.String(64))
    report: Mapped[dict] = mapped_column(JsonType)
    created_at: Mapped[float] = mapped_column(sa.Float)

class CoopTicket(Base):
    __tablename__ = 'coop_tickets'
    token: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey('users.id'))
    room_id: Mapped[int] = mapped_column(sa.ForeignKey('coop_rooms.id'))
    expires_at: Mapped[float] = mapped_column(sa.Float)
