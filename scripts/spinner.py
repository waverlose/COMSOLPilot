"""Run a command under a progress animation. Press a key to stop it.

    python scripts/spinner.py --message "<current operation>" \
        [--after "<running indicator>"] -- <command...>

The look is chosen by ``[ui] spinner`` in config.toml (or COMSOLPILOT_SPINNER):

    claude  rotating sparkle + a playful gerund + a blue shimmer   (default)
    plain   a simple turnstile and the current operation
    auto    claude style in Windows Terminal, plain elsewhere
    off     no animation at all, just the command's own output

The child's output goes to a temp file (never a pipe, which could block once
full); when it finishes, its last few lines are echoed.

``--after`` keeps the animation running once the command has succeeded - a
"service is running" light - and it stops only when a key is pressed. Without
it, a keypress stops the waiting early (the command keeps running in the
background, exit code 3).
"""

from __future__ import annotations

import ctypes
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FRAMES_PLAIN = "|/-\\"
FRAMES_SPARKLE = "·✢✳✶✻✽"
STYLES = ("auto", "claude", "plain", "off")

# A subset of the gerunds Claude Code cycles through, for the claude style.
VERBS = [
    "Cogitating", "Pondering", "Waddling", "Whirring", "Noodling", "Musing",
    "Zesting", "Wrangling", "Vibing", "Puzzling", "Whisking", "Zigzagging",
    "Fermenting", "Tinkering", "Orchestrating", "Simmering", "Percolating",
]

BASE_RGB = (110, 150, 205)      # Claude blue
PEAK_RGB = (196, 220, 255)      # shimmer highlight
DIM = "\x1b[2m"
RESET = "\x1b[0m"
ERASE_LINE = "\x1b[2K\r"
BLUE = "\x1b[38;2;%d;%d;%dm" % BASE_RGB

INTERRUPTED = 3
VERB_SECONDS = 2.6
LINE_WIDTH = 78


def _project_config():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from src import config as project_config

        return project_config
    except Exception:
        return None


def _style() -> str:
    override = str(os.environ.get("COMSOLPILOT_SPINNER", "")).strip().lower()
    if override in STYLES:
        return override
    if override == "ascii":
        return "plain"
    if override == "force":
        return "claude"
    project_config = _project_config()
    if project_config is not None:
        try:
            value = str(project_config.get("ui", "spinner") or "auto").strip().lower()
            if value in STYLES:
                return value
        except Exception:
            pass
    return "auto"


def _console_encoding() -> str:
    try:
        return "cp%d" % ctypes.windll.kernel32.GetConsoleOutputCP()
    except Exception:
        return "utf-8"


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


def _key_pending() -> bool:
    """True when a key is waiting. Never raises (no console, piped stdin, ...)."""
    try:
        import msvcrt

        return bool(msvcrt.kbhit())
    except Exception:
        return False


def _drain_keys() -> None:
    try:
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()
    except Exception:
        pass


def _shimmer(word: str, phase: float) -> str:
    """Colour each letter of *word* with a highlight sweeping left to right."""
    out = []
    count = max(1, len(word))
    for index, char in enumerate(word):
        wave = 0.5 + 0.5 * math.cos(2 * math.pi * (index / count - phase))
        red, green, blue = (round(base + (peak - base) * wave)
                            for base, peak in zip(BASE_RGB, PEAK_RGB))
        out.append("\x1b[38;2;%d;%d;%dm%s" % (red, green, blue, char))
    return "".join(out) + RESET


def _decode(raw: bytes) -> str:
    for encoding in (_console_encoding(), "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _spawn(command: list):
    log_path = Path(tempfile.gettempdir()) / ("comsolpilot_spin_%d.log" % int(time.time()))
    with log_path.open("wb") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL)
    return process, log_path


def _report(process, log_path) -> int:
    code = process.returncode
    try:
        text = _decode(log_path.read_bytes())
    except Exception:
        text = ""
    log_path.unlink(missing_ok=True)
    for line in [l.rstrip() for l in text.splitlines() if l.strip()][-6:]:
        print("    " + line)
    return code


def _draw(fancy: bool, left: str, elapsed: float, tail: str) -> None:
    """One frame; *left* is already styled, *tail* is dimmed."""
    if fancy:
        sys.stdout.write(ERASE_LINE + "    " + left
                         + DIM + "   %4.0fs   " % elapsed + tail + RESET)
    else:
        sys.stdout.write("\r" + ("    " + left + "   %4.0fs   %s "
                                 % (elapsed, tail)).ljust(LINE_WIDTH))
    sys.stdout.flush()


def _clear(fancy: bool) -> None:
    sys.stdout.write(ERASE_LINE if fancy else "\r" + " " * LINE_WIDTH + "\r")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print("usage: spinner.py --message TEXT [--after TEXT] -- command [args...]")
        return 2
    split = argv.index("--")
    options, command = argv[:split], argv[split + 1:]
    message = ""
    after = ""
    for index, item in enumerate(options):
        if index + 1 >= len(options):
            continue
        if item == "--message":
            message = options[index + 1]
        elif item == "--after":
            after = options[index + 1]
    if not command:
        print("spinner.py: no command given")
        return 2

    if not sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    style = _style()
    fancy = style == "claude" or (style == "auto" and bool(os.environ.get("WT_SESSION")))
    if fancy:
        fancy = sys.stdout.isatty() and _enable_vt()

    _drain_keys()
    process, log_path = _spawn(command)

    if style == "off":
        process.wait()
        return _report(process, log_path)

    frames = FRAMES_SPARKLE if fancy else FRAMES_PLAIN
    started = time.time()
    index = 0
    interrupted = False

    while process.poll() is None:
        if _key_pending():
            _drain_keys()
            interrupted = True
            break
        elapsed = time.time() - started
        frame = frames[index % len(frames)]
        if fancy:
            verb = VERBS[int(elapsed // VERB_SECONDS) % len(VERBS)]
            left = _shimmer(frame + " " + verb, (elapsed / 3.0) % 1.0)
        else:
            left = frame + "  " + message
        _draw(fancy, left, elapsed, "")
        index += 1
        time.sleep(0.1)

    _clear(fancy)

    if interrupted:
        print("    " + message + " 仍在后台继续。")
        return INTERRUPTED

    code = _report(process, log_path)

    # After a successful start, keep the light on: spin until a key is pressed.
    # Only where a key can actually arrive - a piped run has no console and
    # would spin forever.
    if after and code == 0 and sys.stdout.isatty():
        _drain_keys()
        index = 0
        started = time.time()
        while not _key_pending():
            frame = frames[index % len(frames)]
            left = (BLUE + frame + RESET + "  " + after) if fancy else (frame + "  " + after)
            _draw(fancy, left, time.time() - started, "按任意键返回菜单")
            index += 1
            time.sleep(0.1)
        _drain_keys()
        _clear(fancy)
        print()
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
