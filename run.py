#!/usr/bin/env python3
"""隔离模式（python -I）下的启动脚本：显式注入项目根目录后调用 CLI。

用法：
  python3 -I run.py coverage  samples
  python3 -I run.py allocate  samples --scenario extension
  python3 -I run.py closures  samples
  python3 -I run.py reconcile samples
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from carecycle.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
