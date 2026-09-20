"""应用配置。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://eorzea:eorzea@localhost:5432/eorzea"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    cors_origins: str = "http://localhost:5173"

    report_tolerance: float = 1.10
    api_prefix: str = "/api/v1"

    # 兑换码：码与奖励金币均由环境变量配置；码为空即关闭该功能。
    redeem_code: str = ""
    redeem_gold: int = 0

    # 管理员账号：账号名与密码由环境变量配置；密码为空即不启用管理员。
    admin_username: str = "admin"
    admin_password: str = ""

    # 启动时自动建表（本地开发用；生产应使用 alembic upgrade head）
    auto_create_tables: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
