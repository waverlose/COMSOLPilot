"""Update this COMSOLPilot checkout from its git remote.

Reached from menu item 7 ("升级") in start_comsol_server.bat, or directly:

    start_comsol_server.bat upgrade

The MCP client launches the server as ``python -m src.server`` from this
directory, so the installed code *is* this working tree - a fast-forward is the
whole upgrade, and there is no install step. The only exception is a changed
dependency file, which this script reinstalls.

It is deliberately one-way: it never rewrites history, never discards local
work, and stops with an explanation when it cannot fast-forward. A checkout with
local changes still upgrades, as long as those changes touch files the incoming
commits leave alone - which is the normal case, since menu items 5 and 6 write
to config.toml and nothing else does.

Exit code: 0 up to date or updated | 2 nothing was changed.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPO_URL = "https://github.com/waverlose/COMSOLPilot"
DEPENDENCIES = "requirements-windows.txt"
GIT_TIMEOUT = 180
MAX_COMMITS_SHOWN = 10

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[91m"
GREEN = "\x1b[92m"
YELLOW = "\x1b[93m"
RESET = "\x1b[0m"

COLOUR = False


def _setup_output() -> bool:
    """Enable ANSI on a real console; fall back to plain text when piped."""
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
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _paint(text: str, *codes: str) -> str:
    if not COLOUR or not codes:
        return text
    return "".join(codes) + text + RESET


def say(text: str = "") -> None:
    print(text)


def _git(*args: str) -> tuple[bool, str]:
    """Run git in the checkout. Returns (ok, output-or-error)."""
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError:
        return False, "找不到 git：它没安装，或者不在 PATH 里。"
    except subprocess.TimeoutExpired:
        return False, "git %s 超时（%d 秒），多半是网络或代理的问题。" % (
            args[0], GIT_TIMEOUT)
    if done.returncode != 0:
        message = (done.stderr or done.stdout or "").strip()
        return False, message or "git %s 失败。" % args[0]
    return True, done.stdout.strip()


def _modified_files() -> set:
    """Paths with local changes, tracked or untracked.

    Deliberately not parsed from ``git status --porcelain``: its fixed-width
    prefix does not survive the trailing whitespace strip in _git, so the first
    line loses a character.
    """
    paths = set()
    for args in (("diff", "--name-only", "HEAD"),
                 ("ls-files", "--others", "--exclude-standard")):
        ok, out = _git(*args)
        if ok:
            paths.update(line.strip() for line in out.splitlines() if line.strip())
    return paths


def _upstream() -> str:
    """The branch this checkout tracks, e.g. 'origin/main'."""
    ok, out = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if ok and out and "/" in out:
        return out
    for candidate in ("origin/main", "origin/master"):
        ok, _ = _git("rev-parse", "--verify", "--quiet", candidate)
        if ok:
            return candidate
    return ""


def _describe(rev: str) -> str:
    ok, out = _git("log", "-1", "--format=%h  %ad  %s", "--date=short", rev)
    return out if ok else rev


def _not_a_checkout() -> int:
    say(_paint("这个目录不是 git 检出，没法自动升级。", BOLD, YELLOW))
    say()
    say("  安装目录：%s" % ROOT)
    say("  多半是解压压缩包安装的。想升级，请重新下载最新版：")
    say("    %s" % REPO_URL)
    say()
    say("  换成 git clone 安装，以后就能在这里一键升级：")
    say("    git clone %s" % REPO_URL)
    return 2


def main() -> int:
    global COLOUR
    COLOUR = _setup_output()

    say()
    if not (ROOT / ".git").exists():
        return _not_a_checkout()

    branch = _upstream()
    if not branch:
        say(_paint("这个检出没有绑定远端分支，无法判断要升级到什么。", BOLD, YELLOW))
        say()
        say("  在 %s 里执行一次即可：git branch --set-upstream-to=origin/main" % ROOT)
        return 2

    remote = branch.split("/", 1)[0]
    say(_paint("  正在检查更新 %s ..." % branch, DIM))

    ok, out = _git("fetch", remote, "--quiet")
    if not ok:
        say()
        say(_paint("拉取失败，没能连上远端。", BOLD, RED))
        say()
        for line in out.splitlines()[:6]:
            say("    %s" % line)
        say()
        say("  检查网络；如果走代理，确认 git 的代理配置可用（git config --global http.proxy）。")
        return 2

    ok, behind = _git("rev-list", "--count", "HEAD..%s" % branch)
    ok2, ahead = _git("rev-list", "--count", "%s..HEAD" % branch)
    if not (ok and ok2):
        say(_paint("无法比较本地与远端，git 没有给出可用的提交计数。", BOLD, RED))
        return 2
    behind, ahead = int(behind), int(ahead)

    say()
    if behind == 0:
        say(_paint("  已是最新版本。", BOLD, GREEN))
        say("  %s" % _describe("HEAD"))
        if ahead:
            say()
            say("  本地另有 %d 个提交尚未推送。" % ahead)
        return 0

    if ahead:
        say(_paint("  本地和远端都各自有新提交，无法快进。", BOLD, YELLOW))
        say()
        say("  本地领先 %d 个、落后 %d 个。自动升级只做快进，不会替你合并或改写历史。" % (ahead, behind))
        say("  想继续，请先在 %s 里手动处理（git pull --rebase，或 git log 看清楚再说）。" % ROOT)
        return 2

    # Local edits only stand in the way when the incoming commits also touch
    # those files; otherwise git fast-forwards over them without a murmur.
    ok, changed_out = _git("diff", "--name-only", "HEAD..%s" % branch)
    changed = {line.strip() for line in changed_out.splitlines() if line.strip()}
    blocked = sorted(_modified_files() & changed)
    if blocked:
        say(_paint("  本地改过的文件，这次升级也要改，先处理一下。", BOLD, YELLOW))
        say()
        for name in blocked[:10]:
            say("    %s" % name)
        if len(blocked) > 10:
            say("    ... 还有 %d 个" % (len(blocked) - 10))
        say()
        say("  不想留就 git checkout -- <文件>，想留就先 git stash 或 git commit。")
        return 2

    ok, log_out = _git("log", "--oneline", "--no-decorate", "HEAD..%s" % branch)
    commits = [line for line in log_out.splitlines() if line.strip()]
    say("  发现 %d 个新提交：" % len(commits))
    say()
    for line in commits[:MAX_COMMITS_SHOWN]:
        say("    %s" % line)
    if len(commits) > MAX_COMMITS_SHOWN:
        say("    ... 还有 %d 个" % (len(commits) - MAX_COMMITS_SHOWN))
    say()

    old = _describe("HEAD")
    ok, old_sha = _git("rev-parse", "HEAD")
    ok, out = _git("merge", "--ff-only", branch)
    if not ok:
        say(_paint("  快进失败，工作区没有改动。", BOLD, RED))
        say()
        for line in out.splitlines()[:8]:
            say("    %s" % line)
        return 2

    say(_paint("  已升级到最新版本。", BOLD, GREEN))
    say("    升级前  %s" % old)
    say("    现在    %s" % _describe("HEAD"))

    ok, files = _git("diff", "--name-only", "%s..HEAD" % (old_sha or "HEAD@{1}"))
    touched = {line.strip() for line in files.splitlines() if line.strip()}
    if DEPENDENCIES in touched or "pyproject.toml" in touched:
        say()
        say("  依赖文件有变动，正在重新安装依赖（这一步可能要几分钟）...")
        try:
            done = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-cache-dir",
                 "-r", str(ROOT / DEPENDENCIES), "-q"],
                timeout=GIT_TIMEOUT * 4,
            )
        except Exception as error:                     # noqa: BLE001 - report anything
            say(_paint("  依赖安装没跑成：%s" % error, RED))
            say("  手动补一次：.venv\\Scripts\\python.exe -m pip install -r %s" % DEPENDENCIES)
        else:
            if done.returncode == 0:
                say(_paint("  依赖已更新。", GREEN))
            else:
                say(_paint("  依赖安装失败（退出码 %d）。" % done.returncode, RED))
                say("  手动补一次：.venv\\Scripts\\python.exe -m pip install -r %s" % DEPENDENCIES)

    say()
    say("  重启你的 AI 客户端，新代码才会生效（服务端进程仍是升级前启动的那个）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
