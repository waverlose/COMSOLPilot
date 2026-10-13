"""Choose the COMSOL version written to config.toml (launcher menu item 6).

    python scripts/set_version.py

Lists the installations MPh can find, lets you pick one (or "auto" = newest),
and saves it as [comsol] version. The assistant can do the same with
comsol_set_preferences(version=...).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.tools.session import installed_versions, server_exe  # noqa: E402


def main() -> int:
    current = str(config.get("comsol", "version") or "").strip()
    versions = installed_versions()
    print()
    if not versions:
        print("    没有检测到 COMSOL 安装。")
        print("    请确认已安装，或设置环境变量 COMSOL_SERVER_EXE 指定 comsolmphserver.exe。")
        return 1

    print("    已安装的 COMSOL：")
    for index, name in enumerate(versions, 1):
        marker = "   <- 当前" if name == current else ""
        print("      %d)  %-6s %s%s" % (index, name, server_exe(name) or "", marker))
    print("      0)  自动（本机最新）" + ("   <- 当前" if not current else ""))
    print()
    try:
        raw = input("    选择 [0-%d]: " % len(versions)).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if raw == "":
        return 0
    if raw == "0":
        chosen = ""
    elif raw.isdigit() and 1 <= int(raw) <= len(versions):
        chosen = versions[int(raw) - 1]
    else:
        print("    [!] 无效选择。")
        return 1

    config.update({"comsol": {"version": chosen}})
    print("    已保存：" + (chosen or "自动（最新）"))
    print("    下次启动服务端时生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
