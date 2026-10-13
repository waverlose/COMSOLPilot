"""Set the COMSOL server port in config.toml.

    python scripts/set_port.py 2040

config.toml is the single configuration file the launcher script and the MCP
connector both read, so this is the same edit you could make by hand - it just
validates the port first. Prefer the assistant: `comsol_set_preferences(port=...)`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.mcp_targets import port_bindable, project_root  # noqa: E402
from src.tools.session import port_listening  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        # Menu item 5 calls it without arguments, so ask for the port.
        current = config.get("comsol", "port")
        try:
            argv = [input(f"    新端口 [1024-65535，当前 {current}]: ").strip()]
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not argv[0]:
            return 0
    try:
        port = int(argv[0])
    except ValueError:
        print(f"[!] '{argv[0]}' is not a number.")
        return 1
    if not (1024 <= port <= 65535):
        print("[!] Port must be between 1024 and 65535.")
        return 1

    # Re-affirming the port a live server already listens on is fine; anything
    # else must be free to bind.
    runtime_port = None
    try:
        runtime_port = int(json.loads(
            (project_root() / "workspace" / "runtime.json").read_text(
                encoding="utf-8-sig")).get("port") or 0)
    except Exception:
        runtime_port = None

    if port != runtime_port and not port_bindable(port):
        if port_listening("localhost", port):
            # Something is serving there already - almost certainly the COMSOL
            # server the launcher started. Re-affirming it is what the user
            # means; only a port held by anything else is an error.
            print(f"Note: a server is already listening on port {port}; keeping it.")
        else:
            print(f"[!] Port {port} cannot be bound (in use by another process).")
            print("    Pick another one, or stop the process holding it.")
            return 1

    previous = config.get("comsol", "port")
    config.update({"comsol": {"port": port}})
    print(f"Port saved: {port}" + (f"  (was {previous})" if previous and previous != port else ""))
    print(f"  -> {config.config_path()}")
    if runtime_port not in (None, port):
        print()
        print(f"NOTE: the running server is still on port {runtime_port}.")
        print("      Restart it (start_comsol_server.bat stop, then gui/headless) to move it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
