"""List the COMSOL installations MPh can find on this machine.

Prints a single JSON line so callers (the launcher, the MCP tools) do not have
to import MPh themselves - importing MPh needs APPDATA/USERPROFILE, which some
tool shells drop or mangle.

    {"success": true, "versions": [
        {"name": "6.2", "server": "...comsolmphserver.exe", "desktop": "...comsol.exe"},
        {"name": "6.4", "server": "...comsolmphserver.exe", "desktop": "...comsol.exe"}]}

The list is sorted oldest -> newest. "active" repeats the version this project
is currently pinned to (settings.json comsol_version, else the running server).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys


def _ensure_windows_env() -> None:
    """MPh reads APPDATA at import time; repair the environment first."""
    home = pathlib.Path.home()
    defaults = {
        "USERPROFILE": home,
        "APPDATA": home / "AppData" / "Roaming",
        "LOCALAPPDATA": home / "AppData" / "Local",
    }
    for key, value in defaults.items():
        current = os.environ.get(key)
        if not current or "//" in current or "/" in current:
            os.environ[key] = str(value)
    os.environ.setdefault("USERNAME", os.environ.get("USERNAME") or home.name)


def _sort_key(name: str):
    try:
        return [int(part) for part in str(name).split(".")]
    except Exception:
        return [0]


def _active_version() -> str:
    """Version this project will use: explicit setting, else the live server."""
    root = pathlib.Path(__file__).resolve().parent.parent
    for filename, keys in (("settings.json", ("comsol_version",)),
                           ("runtime.json", ("server_exe", "desktop_exe"))):
        try:
            data = json.loads((root / "workspace" / filename).read_text(encoding="utf-8"))
        except Exception:
            continue
        for key in keys:
            value = str(data.get(key) or "").strip()
            if not value:
                continue
            if key == "comsol_version":
                return value
            import re
            match = re.search(r"(\d+\.\d+)", value)
            if match:
                return match.group(1)
    return ""


def main() -> int:
    _ensure_windows_env()
    try:
        import mph.discovery as discovery
    except Exception as exc:
        print(json.dumps({"success": False, "error": "mph unavailable: {}".format(exc)}))
        return 1

    versions = []
    try:
        backends = discovery.find_backends()
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        return 1

    for backend in backends:
        servers = backend.get("server") or []
        clients = backend.get("client") or []
        server = str(servers[0]) if servers else ""
        desktop = str(clients[0]) if clients else ""
        if not desktop and server:
            # Older MPh releases do not fill in 'client'; the Desktop always sits
            # next to the server executable in a COMSOL install.
            sibling = pathlib.Path(server).with_name("comsol.exe")
            if sibling.is_file():
                desktop = str(sibling)
        versions.append({
            "name": str(backend.get("name") or ""),
            "server": server,
            "desktop": desktop,
        })

    versions.sort(key=lambda item: _sort_key(item["name"]))
    print(json.dumps({"success": True, "active": _active_version(),
                      "versions": versions}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
