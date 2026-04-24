"""阿斯加德入口 - 支持 `python -m asgard` 运行。"""

from __future__ import annotations

from ._cli import main

if __name__ == "__main__":
    raise SystemExit(main())
