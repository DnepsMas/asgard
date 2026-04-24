"""阿斯加德 - 校园网消息 AI 助手入口。"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src is on the path when run as `python -m src`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from iris._cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
