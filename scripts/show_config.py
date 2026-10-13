"""Print one config.toml value, for the launcher scripts.

    python scripts/show_config.py comsol port
    python scripts/show_config.py comsol version
    python scripts/show_config.py comsol login_mode

Keeps start_comsol_server.bat / .ps1 reading the same single config file the
MCP connector uses, instead of a second copy in workspace/settings.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: show_config.py <section> <key>", file=sys.stderr)
        return 2
    value = config.get(argv[0], argv[1], "")
    if isinstance(value, bool):
        value = "true" if value else "false"
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
