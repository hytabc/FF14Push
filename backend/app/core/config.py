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

    # 启动时自动建表（本地开发用；生产应使用 alembic upgrade head）。
    # 默认 false：容器入口已执行 alembic，漏配时不该用 create_all 掩盖结构漂移。
    auto_create_tables: bool = False

    # 响应体压缩：对超过 gzip_min_size 的响应启用 gzip（前端 nginx 已启用，直连 API 时由此覆盖）。
    gzip_enabled: bool = True
    gzip_min_size: int = 1024

    # 响应体 brotli：客户端支持 br 时优先于 gzip；不支持时由 gzip 兜底（注册顺序见 main.py）。
    brotli_enabled: bool = True
    brotli_min_size: int = 1024
    brotli_quality: int = 4

    # 请求体 gzip 解压（客户端以 Content-Encoding: gzip 提交请求体时）。
    # 解压上限防 gzip bomb；与 nginx client_max_body_size（4m）同量级。
    request_decompress_enabled: bool = True
    request_max_decompressed_bytes: int = 8 * 1024 * 1024

    # 世界BOSS 客户端上报校验：伤害上限容差（越大越宽松，越不会误伤满练度玩家）。
    # 窗口一律由服务端时钟计算并钳制在 [min, max]（客户端 elapsedMs 仅供参考）。
    worldboss_report_tolerance: float = 1.15
    worldboss_report_min_ms: int = 300
    worldboss_report_max_ms: int = 20000
    # 上报限频（每账号每 60 秒次数）：额度模型之外的频率兜底。
    worldboss_report_per_minute: int = 120

    # 设备 Cookie 是否只在 HTTPS 下发送。前端走 HTTPS 时置 true（默认 false 以兼容本地 http）。
    cookie_secure: bool = False

    # 数据库连接池（仅 PostgreSQL 生效；SQLite 忽略）。默认按「小内存服务器」取值：
    # API 进程 5+5，worker 进程（DB_POOL_PROFILE=worker）2+0，总连接远低于 PG max_connections。
    db_pool_profile: str = "api"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle: int = 1800
    # 排队等待超时：小机器上宁可快速失败，也不要长时间堆积连接等待。
    db_pool_timeout: int = 15

    # 排行榜刷新是否在 API 进程内运行。多 worker / 小内存部署必须 false，
    # 改由 ranking-worker 独占执行（全量重算的峰值内存不应压在 API 进程上）。
    ranking_in_api: bool = False
    # 缓存榜刷新间隔（秒）。等级/战力/金币/关卡/游玩时间是缓存榜，10 分钟对玩家感知几乎无损。
    ranking_refresh_seconds: int = 600
    # 实时榜（钓鱼 / 生活 / 远征）进程内结果缓存秒数：避免同一份全表聚合被反复重算。
    ranking_live_cache_seconds: float = 10.0

    # 世界BOSS 全局时间兜底轮询是否留在 API 进程内。专用 worldboss-worker 已承担该职责，
    # 默认关闭以避免每个 API worker 每 30s 打一次库。
    worldboss_loop_in_api: bool = False

    # 数据保留：定时清理「终态 + 超期」的历史行，遏制表无限膨胀。
    # 注意：榜单真相（world_boss_contributions / _rewards、coop_records、coin_transfers）
    # 与反多开判定依据（user_devices）**永不清理**，不受这些配置影响。
    retention_enabled: bool = True
    retention_interval_seconds: int = 3600
    retention_sessions_days: int = 7
    retention_coop_days: int = 7
    retention_pvp_days: int = 30
    retention_audit_days: int = 30
    # 限流事件保留期必须 **大于所有限流窗口**（最长窗口为按天的注册限流 = 1 天），否则会放宽限制。
    retention_ratelimit_days: int = 2
    # 清理后是否顺带 VACUUM (ANALYZE) 高 churn 小表。
    retention_vacuum: bool = True

    @property
    def effective_pool_size(self) -> int:
        """按进程角色取连接池大小：worker 进程只需极少连接。"""
        return 2 if self.db_pool_profile == "worker" else self.db_pool_size

    @property
    def effective_max_overflow(self) -> int:
        return 0 if self.db_pool_profile == "worker" else self.db_max_overflow

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
