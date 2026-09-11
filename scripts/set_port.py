"""Validate and persist the user's preferred COMSOL server port.

Writes workspace/settings.json ({"port": N}) which the launcher and
sync_mcp_port.py both read. Run from the launcher menu:

    python scripts/set_port.py 2040
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_targets import port_bindable, project_root  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print("Usage: set_port.py <port>")
        return 2
    try:
        port = int(argv[0])
    except ValueError:
        print(f"[!] '{argv[0]}' is not a number.")
        return 1
    if not (1024 <= port <= 65535):
        print("[!] Port must be between 1024 and 65535.")
        return 1

    # A port the live server already listens on is fine (re-affirming it);
    # anything else must be free to bind.
    runtime_port = None
    runtime_path = project_root() / "workspace" / "runtime.json"
    try:
        runtime_port = int(json.loads(
            runtime_path.read_text(encoding="utf-8-sig")).get("port") or 0)
    except Exception:
        runtime_port = None

    if port != runtime_port and not port_bindable(port):
        print(f"[!] Port {port} cannot be bound (in use by another process).")
        print("    Pick another one, or stop the process holding it.")
        return 1

    settings_path = project_root() / "workspace" / "settings.json"
    settings: dict = {}
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except Exception:
        settings = {}
    previous = settings.get("port")
    settings["port"] = port
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    print(f"Port saved: {port}" + (f"  (was {previous})" if previous and previous != port else ""))
    print(f"  -> {settings_path}")
    if runtime_port not in (None, port):
        print()
        print(f"NOTE: the running server is still on port {runtime_port}.")
        print("      Restart the server (menu option 4, then 1 or 2) to move it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
