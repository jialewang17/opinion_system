"""
项目根目录启动脚本
用法示例：
  python cli.py trs-merge --topic 控烟 --date 2025-08-24
  python cli.py clean --topic 控烟 --date 2025-08-24
"""
import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def main() -> None:
    _ensure_src_on_path()
    from src.cli import cli as cli_group
    cli_group()


if __name__ == "__main__":
    main()


