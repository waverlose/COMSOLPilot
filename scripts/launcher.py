# -*- coding: utf-8 -*-
"""COMSOLPilot console launcher (interactive menu with live start counter).

Called by start_comsol_server.bat when no direct command is given.
The heavy lifting happens in scripts/*.ps1 and scripts/*.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PY = ROOT / ".venv" / "Scripts" / "python.exe"

os.system("")  # enable ANSI escape processing on Windows 10+

CYAN, YELLOW, GREEN, RED, GREY, RESET, BOLD = (
    "\033[96m", "\033[93m", "\033[92m", "\033[91m", "\033[90m", "\033[0m", "\033[1m")

BANNER = '                                                                                                              \n                                                  ▗▗▄▄▖▖                  ██    ▗▗▄▄▖▖                        \n                                                  ▝▝▜▜▌▌                  ▀▀    ▝▝▜▜▌▌                ▐▐▌▌    \n  ▟▟████▖▖  ▟▟██▙▙  ▐▐██▙▙██▖▖▗▗▟▟████▖▖  ▟▟██▙▙    ▐▐▌▌    ▐▐▙▙██▙▙    ████      ▐▐▌▌      ▟▟██▙▙  ▐▐██████  \n▐▐▛▛    ▘▘▐▐▛▛  ▜▜▌▌▐▐▌▌██▐▐▌▌▐▐▙▙▄▄▖▖▘▘▐▐▛▛  ▜▜▌▌  ▐▐▌▌    ▐▐▛▛  ▜▜▌▌    ██      ▐▐▌▌    ▐▐▛▛  ▜▜▌▌  ▐▐▌▌    \n▐▐▌▌      ▐▐▌▌  ▐▐▌▌▐▐▌▌██▐▐▌▌  ▀▀▀▀██▖▖▐▐▌▌  ▐▐▌▌  ▐▐▌▌    ▐▐▌▌  ▐▐▌▌    ██      ▐▐▌▌    ▐▐▌▌  ▐▐▌▌  ▐▐▌▌    \n▝▝██▄▄▄▄▌▌▝▝██▄▄██▘▘▐▐▌▌██▐▐▌▌▐▐▄▄▄▄▟▟▌▌▝▝██▄▄██▘▘  ▐▐▙▙▄▄  ▐▐██▄▄██▘▘▗▗▄▄██▄▄▖▖  ▐▐▙▙▄▄  ▝▝██▄▄██▘▘  ▐▐▙▙▄▄  \n  ▝▝▀▀▀▀    ▝▝▀▀▘▘  ▝▝▘▘▀▀▝▝▘▘  ▀▀▀▀▀▀    ▝▝▀▀▘▘      ▀▀▀▀  ▐▐▌▌▀▀▘▘  ▝▝▀▀▀▀▀▀▘▘    ▀▀▀▀    ▝▝▀▀▘▘      ▀▀▀▀  \n                                                            ▐▐▌▌                                              \n                                                                                                              '

BANNER_LINES = BANNER.splitlines()
BANNER_WIDTH = max(len(line) for line in BANNER_LINES)

DIGITS = {
    '0': [' ▗▄▖ ', ' █▀█ ', '▐▌ ▐▌', '▐▌█▐▌', '▐▌ ▐▌', ' █▄█ ', ' ▝▀▘ '],
    '1': [' ▗▄  ', ' ▛█  ', '  █  ', '  █  ', '  █  ', '▗▄█▄▖', '▝▀▀▀▘'],
    '2': [' ▄▄▖ ', '▐▀▀█▖', '   ▐▌', '  ▗▛ ', ' ▗▛  ', '▗█▄▄▖', '▝▀▀▀▘'],
    '3': [' ▄▄▖ ', '▐▀▀█▖', '   ▟▌', ' ▐██ ', '   ▜▌', '▐▄▄█▘', ' ▀▀▘ '],
    '4': ['  ▗▄ ', '  ▟█ ', ' ▐▘█ ', '▗▛ █ ', '▐███▌', '   █ ', '   ▀ '],
    '5': ['▗▄▄▄ ', '▐▛▀▀ ', '▐▙▄▖ ', '▐▀▀█▖', '   ▐▌', '▐▄▄█▘', ' ▀▀▘ '],
    '6': [' ▗▄▖ ', ' █▀▜ ', '▐▌▄▖ ', '▐█▀█▖', '▐▌ ▐▌', '▝█▄█▘', ' ▝▀▘ '],
    '7': ['▗▄▄▄▖', '▝▀▀█▌', '  ▗█ ', '  ▐▌ ', '  █  ', ' ▐▌  ', ' ▀   '],
    '8': [' ▗▄▖ ', '▗█▀█▖', '▐▙ ▟▌', ' ███ ', '▐▛ ▜▌', '▝█▄█▘', ' ▝▀▘ '],
    '9': [' ▗▄▖ ', '▗█▀█▖', '▐▌ ▐▌', '▝█▄█▌', ' ▝▀▐▌', ' ▙▄█ ', ' ▝▀▘ '],
    ':': ['     ', '  ▄  ', '  █  ', '     ', '  █  ', '  ▀  ', '     '],
}

TIMER_HEIGHT = 7

_banner_drawn = 0


def draw_banner_frame(blank_from: int, blank_to: int, color: str) -> None:
    """Draw one banner frame; columns in [blank_from, blank_to) are blanked."""
    global _banner_drawn
    frame = []
    for line in BANNER_LINES:
        padded = line.ljust(BANNER_WIDTH)
        rendered = (padded[:blank_from] + " " * max(0, blank_to - blank_from)
                    + padded[blank_to:])
        frame.append("\x1b[2K" + color + rendered + RESET)
    if _banner_drawn:
        sys.stdout.write("\x1b[" + str(len(BANNER_LINES)) + "A")
    sys.stdout.write("\n".join(frame) + "\n")
    sys.stdout.flush()
    _banner_drawn = len(BANNER_LINES)


def animate_banner() -> None:
    """Dissolve the banner left-to-right, then regenerate left-to-right."""
    global _banner_drawn
    draw_banner_frame(0, 0, CYAN)
    time.sleep(0.4)
    for x in range(BANNER_WIDTH + 1):        # dissolve: blank [0, x)
        draw_banner_frame(x, x, GREY)
        time.sleep(0.012)
    for x in range(BANNER_WIDTH + 1):        # regenerate: blank [x, width)
        draw_banner_frame(x, BANNER_WIDTH, CYAN)
        time.sleep(0.012)
    _banner_drawn = len(BANNER_LINES)


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def resolved_port() -> str:
    for name in ("runtime.json", "settings.json"):
        path = ROOT / "workspace" / name
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig")).get("port")
            if isinstance(value, int) and 0 < value < 65536:
                return str(value)
        except Exception:
            continue
    return os.environ.get("COMSOL_PORT", "2036")


def run(cmd):
    print()
    subprocess.run(cmd, cwd=str(ROOT))
    print()


def sync_quiet() -> None:
    run([str(PY), str(SCRIPTS / "sync_mcp_port.py"), "--quiet"])


def pause() -> None:
    try:
        input(GREY + "\nPress Enter to return to the menu..." + RESET)
    except EOFError:
        pass


def compose_timer(seconds: int) -> list:
    text = "{:02d}:{:02d}".format(seconds // 60, seconds % 60)
    glyphs = [DIGITS[ch] for ch in text]
    return [" ".join(g[row] for g in glyphs) for row in range(TIMER_HEIGHT)]


_timer_lines_drawn = 0


def draw_timer(seconds: int, color: str) -> None:
    """Redraw the big elapsed-time digits in place."""
    global _timer_lines_drawn
    art = compose_timer(seconds)
    if _timer_lines_drawn:
        sys.stdout.write("\x1b[" + str(_timer_lines_drawn) + "A")
    for line in art:
        sys.stdout.write("\x1b[2K" + color + line + RESET + "\n")
    sys.stdout.flush()
    _timer_lines_drawn = len(art)


def erase_timer() -> None:
    global _timer_lines_drawn
    if _timer_lines_drawn:
        sys.stdout.write("\x1b[" + str(_timer_lines_drawn) + "A\x1b[J")
        sys.stdout.flush()
        _timer_lines_drawn = 0


def action_start(open_desktop: bool) -> None:
    port = resolved_port()
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
           str(SCRIPTS / "start_comsol_server.ps1"), "-Port", port]
    if open_desktop:
        cmd.append("-OpenDesktop")
    print()
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    collected = []

    def reader() -> None:
        for raw in iter(proc.stdout.readline, b""):
            collected.append(raw)

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    started = time.monotonic()
    last_shown = -1
    while proc.poll() is None:
        elapsed = int(time.monotonic() - started)
        if elapsed != last_shown:
            color = GREEN if elapsed < 30 else YELLOW if elapsed < 60 else RED
            draw_timer(elapsed, color)
            last_shown = elapsed
        time.sleep(0.15)

    proc.wait()
    try:
        reader_thread.join(timeout=5)
    except Exception:
        pass
    elapsed = int(time.monotonic() - started)
    erase_timer()

    for raw in collected:
        print(raw.decode("utf-8", "replace").rstrip())
    if proc.returncode == 0:
        print(GREEN + "\nServer is up. Startup took {} s.".format(elapsed) + RESET)
    else:
        print(RED + "\nStartup failed after {} s (exit code {}).".format(
            elapsed, proc.returncode) + RESET)
        print(GREY + "Logs: workspace/logs" + RESET)
    sync_quiet()
    pause()


def action_setport() -> None:
    current = resolved_port()
    try:
        raw = input(YELLOW + "New port (1024-65535, Enter keeps {}): ".format(current) + RESET).strip()
    except EOFError:
        return
    if not raw:
        raw = current
    run([str(PY), str(SCRIPTS / "set_port.py"), raw])
    run([str(PY), str(SCRIPTS / "sync_mcp_port.py"), "--quiet", "--port", raw])
    print(YELLOW + "\nNote: restart the server to move it to port {}."
                   " Stop with: start_comsol_server.bat stop".format(raw) + RESET)
    pause()


def table_label() -> str:
    """The label AI-created tables get (workspace/settings.json table_label)."""
    try:
        cfg = json.loads((ROOT / "workspace" / "settings.json").read_text(encoding="utf-8"))
        return str(cfg.get("table_label") or "").strip()
    except Exception:
        return ""


MENU = BOLD + "  [1]" + RESET + "  GUI mode        server + COMSOL Desktop (watch the solve)\n" \
     + BOLD + "  [2]" + RESET + "  Headless mode   server only\n" \
     + BOLD + "  [3]" + RESET + "  Port setup\n" \
     + BOLD + "  [5]" + RESET + "  Table label     opt-in renaming of tables (current: {label})\n" \
     + BOLD + "  [6]" + RESET + "  Diagnose        check server, credentials and connection\n" \
     + BOLD + "  [0]" + RESET + "  Exit\n"


def action_tablelabel() -> None:
    print()
    current = table_label()
    print("  Current label for AI-created tables: "
          + BOLD + (current or "(disabled - tables keep their COMSOL names)") + RESET)
    try:
        value = input(YELLOW + "  New label (Enter = disable renaming): " + RESET).strip()
    except (EOFError, KeyboardInterrupt):
        return
    label = value
    settings = ROOT / "workspace" / "settings.json"
    try:
        cfg = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    except Exception:
        cfg = {}
    cfg["table_label"] = label
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(GREEN + f"  Table label set to: {label}" + RESET)
    print(GREY + "  Takes effect the next time the AI creates/renames tables." + RESET)
    pause()


def action_diagnose() -> None:
    """Run the connection self-check (server, credentials, mph connect)."""
    print()
    script = SCRIPTS / "check_comsol_login.py"
    if not script.is_file():
        print(RED + "  check_comsol_login.py not found." + RESET)
        pause()
        return
    run([str(PY), str(script)])
    pause()


def draw_screen(animate: bool = False) -> None:
    clear()
    if animate:
        animate_banner()
    else:
        print(CYAN + BANNER + RESET)
    print("  " + BOLD + "Port:" + RESET + " " + resolved_port()
          + "   " + BOLD + "Table label:" + RESET + " " + table_label())
    print()
    print(MENU.format(label=table_label()))


def main() -> int:
    first_draw = True
    while True:
        draw_screen(animate=first_draw)
        first_draw = False
        try:
            choice = input(YELLOW + "  Select: " + RESET).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "1":
            action_start(open_desktop=True)
        elif choice == "2":
            action_start(open_desktop=False)
        elif choice == "3":
            action_setport()
        elif choice == "5":
            action_tablelabel()
        elif choice == "6":
            action_diagnose()
        elif choice in ("0", "q", "Q"):
            return 0
        else:
            print(RED + "  Invalid selection." + RESET)


if __name__ == "__main__":
    sys.exit(main())
