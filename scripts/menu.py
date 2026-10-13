"""Draw the COMSOLPilot launcher menu.

start_comsol_server.bat runs this and dispatches on the exit code, so the menu
can use the same colours, bold labels and column alignment as the rest of
COMSOLPilot - cmd's plain ``echo`` cannot do any of that.

Exit code: 0 quit | 1 headless | 2 gui | 3 stop | 4 restart
           5 port | 6 version | 255 redraw (bad choice / no input)
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import banner  # noqa: E402  (scripts/ is on sys.path)
from src import config  # noqa: E402

BOLD = "\x1b[1m"
CYAN = "\x1b[96m"
YELLOW = "\x1b[93m"
RESET = "\x1b[0m"

REDRAW = 255

# (key, label, description) - the label column is padded so the descriptions line up
ITEMS = [
    ("1", "headless 模式", "后台运行，不打开窗口"),
    ("2", "gui 模式", "服务端 + COMSOL Desktop"),
    ("3", "停止 comsol 服务器", ""),
    ("4", "重启 comsol 服务器", ""),
    ("5", "设置端口", ""),
    ("6", "设置 COMSOL 版本", ""),
    ("0", "退出", ""),
]

LABEL_COLUMN = 26


def _enable_vt() -> bool:
    """Turn on ANSI escape processing for this console."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _setup_output() -> bool:
    """Return True when colour is safe to emit."""
    try:
        console = sys.stdout.isatty()
    except Exception:
        console = False
    if not console:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        return False
    return _enable_vt()


def _cells(text: str) -> int:
    return sum(2 if ord(char) > 0x2E80 else 1 for char in text)


def _info_line() -> str:
    pairs = [
        ("端口:", str(config.get("comsol", "port"))),
        ("COMSOL:", str(config.get("comsol", "version") or "auto")),
    ]
    parts = []
    for label, value in pairs:
        parts.append("%s%s%s %s" % (BOLD, label, RESET, value))
    return "  " + "    ".join(parts)


def _item(key: str, label: str, description: str, bright: bool) -> str:
    number = "%s[%s]%s" % (BOLD if bright else "", key, RESET)
    pad = " " * max(1, LABEL_COLUMN - _cells(label))
    return ("  %s  %s%s%s" % (number, label, pad, description)).rstrip()


def draw(colour: bool) -> None:
    if colour:
        print(CYAN + banner.text() + RESET)
        print()
        print(_info_line())
        print()
    else:
        print(banner.text())
        print()
        print(_info_line().replace(BOLD, "").replace(RESET, ""))
        print()
    for key, label, description in ITEMS:
        line = _item(key, label, description, colour)
        if not colour:
            line = line.replace(BOLD, "").replace(RESET, "")
        print(line)
        if key == "6":
            print()
    print()


def main() -> int:
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass
    colour = _setup_output()
    draw(colour)

    try:
        answer = input("  " + (YELLOW if colour else "") + "选择: "
                       + (RESET if colour else "")).strip()
    except (EOFError, KeyboardInterrupt):
        # No input available (scripted launch, closed stdin): leave rather than
        # letting the launcher redraw the menu forever.
        print()
        return 0
    if answer in {key for key, _, _ in ITEMS}:
        return int(answer)
    return REDRAW


if __name__ == "__main__":
    raise SystemExit(main())
