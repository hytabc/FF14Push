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

    # 反滥用（防多开 / 防刷）：按客户端 IP 的滑动窗口限值，<= 0 关闭该项。
    # 注册：同一 IP 每小时 / 每天最多创建多少账号（多开的主要入口）。
    register_per_ip_per_hour: int = 5
    register_per_ip_per_day: int = 20
    # 登录：同一 IP 每 5 分钟最多尝试多少次（防撞库）。
    login_per_ip_per_5min: int = 30
    # 兑换：同一 IP 每小时最多尝试多少次；同一 IP 对同一兑换码最多几个账号可兑换。
    redeem_per_ip_per_hour: int = 10
    redeem_accounts_per_ip: int = 5

    # 启动时自动建表（本地开发用；生产应使用 alembic upgrade head）
    auto_create_tables: bool = True

    # 响应体压缩：对超过 gzip_min_size 的响应启用 gzip（前端 nginx 已启用，直连 API 时由此覆盖）。
    gzip_enabled: bool = True
    gzip_min_size: int = 1024

    # 设备 Cookie 是否只在 HTTPS 下发送。前端走 HTTPS 时置 true（默认 false 以兼容本地 http）。
    cookie_secure: bool = False

    # 数据库连接池（仅 PostgreSQL 生效；SQLite 忽略）：并发挂机依赖足够的连接数。
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800
    db_pool_timeout: int = 30

    # 排行榜刷新是否在 API 进程内运行。多 worker 部署应置 false，改由 ranking-worker 独占执行。
    ranking_in_api: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
