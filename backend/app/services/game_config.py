"""加载前后端共享的静态配置，并对外暴露为 `CONFIG`。

共享层位置通过向上查找 `shared/schema/loader.py` 确定，
因此本地开发（仓库根目录）与容器部署（/app/shared）都能正常工作。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _locate_repo_root() -> Path:
    env_dir = os.environ.get("EORZEA_SHARED_DIR")
    if env_dir:
        candidate = Path(env_dir).resolve()
        if (candidate / "schema" / "loader.py").exists():
            return candidate.parent
        raise RuntimeError(f"EORZEA_SHARED_DIR 指向的目录无效: {env_dir}")

    for parent in Path(__file__).resolve().parents:
        if (parent / "shared" / "schema" / "loader.py").exists():
            return parent

    raise RuntimeError(
        "未能定位共享层目录。请确保仓库内存在 shared/schema/loader.py，"
        "或设置环境变量 EORZEA_SHARED_DIR 指向该 shared 目录。"
    )


REPO_ROOT: Path = _locate_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.schema.loader import BaseItem, GameConfig, load_game_data  # noqa: E402

CONFIG: GameConfig = load_game_data()

__all__ = ["CONFIG", "GameConfig", "BaseItem", "REPO_ROOT"]
