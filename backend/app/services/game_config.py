"""加载前后端共享的静态配置，并对外暴露为 `CONFIG`。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.schema.loader import BaseItem, GameConfig, load_game_data  # noqa: E402

CONFIG: GameConfig = load_game_data()

__all__ = ["CONFIG", "GameConfig", "BaseItem", "REPO_ROOT"]
