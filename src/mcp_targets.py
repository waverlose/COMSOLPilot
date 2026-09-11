"""Write and sync the COMSOLPilot connector entry across MCP client configs.

Supported clients (auto-detected; a client is touched only when its config
directory/file exists on this machine):

    workbuddy       ~/.workbuddy/mcp.json                        JSON mcpServers
    claude-code     ~/.claude.json                               JSON mcpServers
    claude-desktop  %APPDATA%/Claude/claude_desktop_config.json  JSON mcpServers
    gemini          ~/.gemini/settings.json                      JSON mcpServers
    cursor          ~/.cursor/mcp.json                           JSON mcpServers
    windsurf        ~/.codeium/windsurf/mcp_config.json          JSON mcpServers
    opencode        ~/.config/opencode/opencode.json             JSON, own schema
    codex           ~/.codex/config.toml                         TOML
    deepseek        %APPDATA%/DeepSeek/... (experimental)        JSON mcpServers

Rules:
- an existing COMSOLPilot entry is only touched when COMSOL_PORT differs;
- with ``ensure`` a missing entry is created;
- files are backed up to ``<name>.bak`` before the first write in a run;
- other keys in each config file are preserved as-is.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
from pathlib import Path
from typing import Any

ENTRY_NAME = "comsolpilot"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def project_root() -> Path:
    return _PROJECT_ROOT


def python_exe() -> str:
    """The interpreter the connector should run with (venv preferred)."""
    for candidate in (
        _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        _PROJECT_ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return "python"


def _env_block(port: int) -> dict[str, str]:
    """Environment for the connector process.

    Three hard lessons from new-user pitfalls, all auto-handled here:

    - several MCP clients ignore the ``cwd`` field entirely, so the process
      would start in a random directory and die with
      ``ModuleNotFoundError: No module named 'src'`` — PYTHONPATH is the
      decisive fix;
    - mph reads APPDATA (and friends) at *import* time, raising
      ``KeyError: 'APPDATA'`` before any code of ours runs — the four
      Windows variables must be passed through explicitly;
    - the stdio channel must be UTF-8, otherwise Chinese output garbles
      under the default GBK code page.
    """
    env = {
        "COMSOL_MODE": "gui",
        "COMSOL_HOST": "localhost",
        "COMSOL_PORT": str(port),
        "COMSOL_PREWARM": "on",
        "COMSOL_PREWARM_WAIT": "20",
        "PYTHONPATH": str(project_root()),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    for key in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROCESSOR_ARCHITECTURE"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


# ---------------------------------------------------------------------------
# Client registry
# ---------------------------------------------------------------------------

def _home() -> Path:
    return Path.home()


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", str(_home() / "AppData" / "Roaming")))


class Target:
    def __init__(self, key: str, label: str, kind: str,
                 candidates: list[Path], needs_parent: bool = True):
        self.key = key
        self.label = label
        self.kind = kind              # json_mcp_servers | opencode | codex_toml
        self.candidates = candidates  # first existing wins; first candidate is created when absent
        self.needs_parent = needs_parent

    def resolve(self) -> Path | None:
        """The config file to operate on, or None when not installed."""
        for path in self.candidates:
            if path.is_file():
                return path
        if not self.needs_parent:
            return self.candidates[0]
        # Client installed (its directory exists) but no config file yet.
        for path in self.candidates:
            if path.parent.is_dir():
                return path
        return None


def _targets() -> list[Target]:
    return [
        Target("workbuddy", "WorkBuddy", "json_mcp_servers",
               [_home() / ".workbuddy" / "mcp.json"]),
        Target("claude-code", "Claude Code", "json_mcp_servers",
               [_home() / ".claude.json"]),
        Target("claude-desktop", "Claude Desktop", "json_mcp_servers",
               [_appdata() / "Claude" / "claude_desktop_config.json"]),
        Target("gemini", "Gemini CLI", "json_mcp_servers",
               [_home() / ".gemini" / "settings.json"]),
        Target("cursor", "Cursor", "json_mcp_servers",
               [_home() / ".cursor" / "mcp.json"]),
        Target("windsurf", "Windsurf", "json_mcp_servers",
               [_home() / ".codeium" / "windsurf" / "mcp_config.json"]),
        Target("opencode", "OpenCode", "opencode",
               [_home() / ".config" / "opencode" / "opencode.json",
                _home() / ".opencode" / "opencode.json"]),
        Target("codex", "Codex", "codex_toml",
               [_home() / ".codex" / "config.toml"]),
        Target("deepseek", "DeepSeek", "json_mcp_servers",
               [_appdata() / "DeepSeek" / "mcp.json",
                _home() / ".deepseek" / "mcp.json"]),
    ]


TARGET_KEYS = [t.key for t in _targets()]


def detected_clients() -> list[str]:
    """Keys of clients whose config (or config directory) exists."""
    found = []
    for target in _targets():
        if target.resolve() is not None:
            found.append(target.key)
    return found


# ---------------------------------------------------------------------------
# Entry builders
# ---------------------------------------------------------------------------

def _is_comsol_entry(name: str, spec: Any) -> bool:
    haystack = [name]
    if isinstance(spec, dict):
        haystack.append(str(spec.get("command", "")))
        args = spec.get("args") or spec.get("command")
        if isinstance(args, list):
            haystack.extend(str(item) for item in args)
        haystack.append(str(spec.get("cwd", "")))
        env = spec.get("env") or spec.get("environment")
        if isinstance(env, dict):
            haystack.extend(str(k) for k in env)
    return any("comsol" in part.lower() for part in haystack)


def _entry_for_kind(kind: str, port: int) -> dict[str, Any]:
    py = python_exe()
    root = str(project_root())
    if kind == "opencode":
        env = _env_block(port)
        return {
            "type": "local",
            "command": [py, "-m", "src.server"],
            "environment": env,
            "enabled": True,
        }
    # json_mcp_servers and the TOML payload share this shape
    return {
        "command": py,
        "args": ["-m", "src.server"],
        "cwd": root,
        "env": _env_block(port),
    }


def _port_of_existing(spec: Any) -> str | None:
    if not isinstance(spec, dict):
        return None
    env = spec.get("env") or spec.get("environment")
    if isinstance(env, dict) and str(env.get("COMSOL_PORT", "")).strip():
        return str(env["COMSOL_PORT"]).strip()
    return None


# ---------------------------------------------------------------------------
# JSON backends
# ---------------------------------------------------------------------------

def _sync_json(target: Target, path: Path, port: int, ensure: bool,
               dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"client": target.key, "label": target.label,
                              "path": str(path)}
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    except Exception as exc:
        return {**result, "action": "skipped",
                "reason": f"cannot parse {path.name}: {exc}"}
    if not isinstance(config, dict):
        return {**result, "action": "skipped", "reason": "root is not an object"}

    if target.kind == "opencode":
        section = config.setdefault("mcp", {})
    else:
        section = config.setdefault("mcpServers", {})
    if not isinstance(section, dict):
        return {**result, "action": "skipped", "reason": "no mcpServers/mcp object"}

    existing_name = ENTRY_NAME if isinstance(section.get(ENTRY_NAME), dict) else None
    if existing_name is None:
        for name, spec in section.items():
            if _is_comsol_entry(str(name), spec):
                existing_name = str(name)
                break

    if existing_name is not None:
        spec = section[existing_name]
        current = _port_of_existing(spec)
        if current == str(port):
            return {**result, "action": "ok", "detail": f"COMSOL_PORT already {port}"}
        if not isinstance(spec, dict):
            return {**result, "action": "skipped", "reason": "existing entry is not an object"}
        new_spec = _entry_for_kind(target.kind, port)
        merged = dict(spec)
        for key, value in new_spec.items():
            if key == "env" and isinstance(spec.get("env"), dict):
                env = dict(spec["env"])
                env.update(value)
                merged["env"] = env
            elif key == "environment" and isinstance(spec.get("environment"), dict):
                env = dict(spec["environment"])
                env.update(value)
                merged["environment"] = env
            else:
                merged[key] = value
        section[existing_name] = merged
        result["action"] = "updated"
        result["detail"] = f"COMSOL_PORT {current or '(unset)'} -> {port}"
    elif ensure:
        section[ENTRY_NAME] = _entry_for_kind(target.kind, port)
        result["action"] = "created"
        result["detail"] = f"entry '{ENTRY_NAME}' added with COMSOL_PORT={port}"
    else:
        return {**result, "action": "skipped", "reason": "no existing entry (use --ensure)"}

    if dry_run:
        result["dry_run"] = True
        return result
    return {**result, **_write_json(path, config)}


def _write_json(path: Path, config: dict) -> dict[str, Any]:
    try:
        if path.is_file():
            backup = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return {"written": True}
    except Exception as exc:
        return {"written": False, "action": "failed", "reason": str(exc)}


# ---------------------------------------------------------------------------
# Codex TOML backend
# ---------------------------------------------------------------------------

_TOML_STR = re.compile(r"^([^'\"\\]|\\.)*$")


def _toml_literal(value: str) -> str:
    """TOML literal string ('...') — backslashes need no escaping."""
    return "'" + value.replace("'", "''") + "'"


def _toml_inline_array(values: list[str]) -> str:
    return "[ " + ", ".join(_toml_literal(v) for v in values) + " ]"


def _toml_inline_table(mapping: dict[str, str]) -> str:
    body = ", ".join(f"{k} = {_toml_literal(v)}" for k, v in mapping.items())
    return "{ " + body + " }"


def _codex_block(port: int) -> str:
    entry = _entry_for_kind("codex_toml", port)
    lines = [f"[mcp_servers.{ENTRY_NAME}]",
             f"command = {_toml_literal(entry['command'])}",
             f"args = {_toml_inline_array(entry['args'])}",
             f"cwd = {_toml_literal(entry['cwd'])}",
             f"env = {_toml_inline_table(entry['env'])}"]
    return "\n".join(lines)


_SECTION_HEADER = re.compile(r"^\[mcp_servers\.comsolpilot\]\s*$", re.MULTILINE)
_NEXT_HEADER = re.compile(r"^\[", re.MULTILINE)
_TOML_PORT = re.compile(r"COMSOL_PORT\s*=\s*[\"']?(\d+)")


def _sync_codex(target: Target, path: Path, port: int, ensure: bool,
                dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"client": target.key, "label": target.label,
                              "path": str(path)}
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    match = _SECTION_HEADER.search(text)
    if match:
        start = match.start()
        following = _NEXT_HEADER.search(text, match.end())
        end = following.start() if following else len(text)
        section = text[start:end]
        port_match = _TOML_PORT.search(section)
        current = port_match.group(1) if port_match else None
        if current == str(port):
            return {**result, "action": "ok", "detail": f"COMSOL_PORT already {port}"}
        new_text = text[:start] + _codex_block(port) + "\n\n" + text[end:]
        action, detail = "updated", f"COMSOL_PORT {current or '(unset)'} -> {port}"
    elif ensure:
        new_text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + _codex_block(port) + "\n"
        action, detail = "created", f"entry '{ENTRY_NAME}' added with COMSOL_PORT={port}"
    else:
        return {**result, "action": "skipped", "reason": "no existing entry (use --ensure)"}

    if dry_run:
        return {**result, "action": action, "detail": detail, "dry_run": True}
    try:
        if path.is_file():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        return {**result, "action": action, "detail": detail, "written": True}
    except Exception as exc:
        return {**result, "action": "failed", "reason": str(exc)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_client(key: str, port: int, *, ensure: bool = False,
                dry_run: bool = False) -> dict[str, Any]:
    for target in _targets():
        if target.key == key:
            path = target.resolve()
            if path is None:
                return {"client": key, "label": target.label,
                        "action": "skipped", "reason": "client not installed"}
            if target.kind == "codex_toml":
                return _sync_codex(target, path, port, ensure, dry_run)
            return _sync_json(target, path, port, ensure, dry_run)
    return {"client": key, "action": "skipped", "reason": "unknown client"}


def sync_all(port: int, *, ensure: bool = False, only: list[str] | None = None,
             ensure_keys: list[str] | None = None,
             dry_run: bool = False) -> list[dict[str, Any]]:
    """Sync every detected client's port.

    Entries are never created unless the client key is explicitly allowed:
    pass ``only`` together with ``ensure`` to create those exact clients, or
    ``ensure_keys`` to allowlist which clients may be auto-created. The default
    (developer-first) behaviour is update-only.
    """
    allowed = set(ensure_keys or [])
    if ensure and only:
        allowed.update(only)
    wildcard = "*" in allowed
    results = []
    for target in _targets():
        if only and target.key not in only:
            continue
        may_ensure = wildcard or target.key in allowed
        results.append(sync_client(target.key, port, ensure=may_ensure, dry_run=dry_run))
    return results


def resolved_port() -> int:
    """Best-known port: runtime.json (live server) -> settings.json -> 2036."""
    root = project_root()
    for name in ("runtime.json", "settings.json"):
        path = root / "workspace" / name
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig")).get("port")
            if isinstance(value, int) and 0 < value < 65536:
                return value
        except Exception:
            continue
    try:
        return int(os.environ.get("COMSOL_PORT", "2036"))
    except ValueError:
        return 2036


def port_bindable(port: int) -> bool:
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("0.0.0.0", port))
        listener.close()
        return True
    except OSError:
        return False
