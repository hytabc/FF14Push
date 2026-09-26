# -*- coding: utf-8 -*-
"""死者宫殿数值标定：输出「零成长 / 部分成长 / 满成长」的到达层数分布与速通秒数。

用法（仓库根目录）：`python scripts/palace-balance.py [samples]`

依赖 `backend` 包，请用后端虚拟环境运行：
    cd backend && .venv/bin/python ../scripts/palace-balance.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.services import palace_sim  # noqa: E402


def main() -> None:
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    all_nodes = palace_sim.full_growth_nodes()

    scenarios = {
        "零成长": [],
        "半成长": all_nodes[: len(all_nodes) // 2],
        "满成长": all_nodes,
    }

    for name, unlocked in scenarios.items():
        reaches = [palace_sim.simulate_reach(unlocked, seed) for seed in range(samples)]
        avg = sum(reaches) / len(reaches)
        hist = {f: reaches.count(f) for f in sorted(set(reaches))}
        print(f"[{name}] 平均到达 {avg:.2f} 层  分布 {hist}")

    print()
    for floor in (1, 2, 3, 5, 8, 10):
        zero = palace_sim.kill_seconds([], floor, "battle", seed=0)
        full = palace_sim.kill_seconds(all_nodes, floor, "battle", seed=0)
        print(f"第 {floor:>2} 层小怪：零成长 {zero:>10.2f}s  满成长 {full:>10.2f}s")


if __name__ == "__main__":
    main()
