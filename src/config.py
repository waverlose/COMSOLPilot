"""Project configuration, read from ``config.toml`` at the repository root.

One file configures this installation: the launcher script and the MCP
connector both read it, so changing a port or a COMSOL version is done once
instead of in every client's config. Missing keys fall back to the built-in
defaults below; ``workspace/settings.json`` is only runtime state written by
the tools (a remembered COMSOL version, the port COMSOL actually bound).

Priority, highest first: environment variable -> config.toml ->
workspace/settings.json -> DEFAULT.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULTS: dict[str, dict[str, object]] = {
    "comsol": {
        "port": 2036,
        "host": "localhost",
        "mode": "gui",
        "version": "",
        "login_mode": "auto",
        "open_desktop": True,
    },
    "connector": {
        "autostart": False,
        "prewarm": True,
        "prewarm_wait": 20,
        "entry_name": "comsolpilot",
    },
    "ui": {
        "table_label": "",
        "spinner": "claude",
    },
}


def config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.toml"


def settings_path() -> Path:
    return Path(__file__).resolve().parent.parent / "workspace" / "settings.json"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import tomllib  # Python 3.11+
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except ModuleNotFoundError:
        pass
    except Exception:
        return {}
    try:
        import tomli  # type: ignore
        with path.open("rb") as handle:
            return tomli.load(handle)
    except Exception:
        pass
    return _parse_simple(path)


def _parse_simple(path: Path) -> dict:
    """Minimal TOML subset reader, for Python 3.10 without tomli installed."""
    data: dict = {}
    section = data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = data.setdefault(line[1:-1].strip(), {})
        elif "=" in line:
            key, value = line.split("=", 1)
            section[key.strip()] = _coerce(value.strip())
    return data


def _coerce(text: str):
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def load() -> dict:
    """config.toml merged over the built-in defaults."""
    merged = {section: dict(values) for section, values in DEFAULTS.items()}
    for section, values in (_load_toml(config_path()) or {}).items():
        if isinstance(values, dict):
            merged.setdefault(section, {}).update(values)
    return merged


def get(section: str, key: str, default=None):
    return load().get(section, {}).get(key, default)


def runtime_settings() -> dict:
    """workspace/settings.json, read lazily (runtime state, not user config)."""
    import json

    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Writing (comment-preserving)
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_\-]+)(\s*)=")


def _format(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _section_bounds(lines: list, section: str) -> tuple:
    """(header index, end index) for [section]; (-1, -1) when it is absent."""
    header = None
    for index, line in enumerate(lines):
        if line.strip() == f"[{section}]":
            header = index
            break
    if header is None:
        return -1, -1
    for index in range(header + 1, len(lines)):
        if lines[index].lstrip().startswith("["):
            return header, index
    return header, len(lines)


def update(updates: dict) -> list:
    """Write settings into config.toml, preserving comments and layout.

    Only the lines whose value changed are rewritten, so the explanatory
    comments survive an assistant-driven change. Returns the keys touched.
    """
    path = config_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    touched: list = []

    for section, values in updates.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            header, end = _section_bounds(lines, section)
            if header < 0:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(f"[{section}]")
                lines.append(f"{key} = {_format(value)}")
                touched.append(f"{section}.{key}")
                continue
            replaced = False
            for index in range(header + 1, end):
                match = _KEY_RE.match(lines[index])
                if match and match.group(2) == key:
                    # Keep any trailing "# comment" on the line.
                    comment = ""
                    hash_at = lines[index].find("#")
                    if hash_at >= 0:
                        comment = "  " + lines[index][hash_at:].strip()
                    lines[index] = f"{key} = {_format(value)}{comment}"
                    replaced = True
                    break
            if not replaced:
                insert_at = end
                while insert_at > header + 1 and not lines[insert_at - 1].strip():
                    insert_at -= 1
                lines.insert(insert_at, f"{key} = {_format(value)}")
            touched.append(f"{section}.{key}")

    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return touched
