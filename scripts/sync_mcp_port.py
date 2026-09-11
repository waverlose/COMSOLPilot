"""Sync the COMSOLPilot port in MCP client configs that already have an entry.

By default this NEVER creates anything: it only updates COMSOL_PORT inside
entries a developer has deliberately added. Creating a new entry is an
explicit, targeted action:

    python scripts/sync_mcp_port.py --ensure --only workbuddy
    python scripts/sync_mcp_port.py --ensure-all          # all detected clients

For a paste-ready example instead, use:
    python -m src.cli config --client <workbuddy|claude-code|codex|opencode|...>

Port resolution order: workspace/runtime.json (live server) ->
workspace/settings.json (user preference) -> COMSOL_PORT env -> 2036.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_targets import TARGET_KEYS, resolved_port, sync_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Point MCP clients at the COMSOL server port actually in use.")
    parser.add_argument("--dry-run", action="store_true",
                        help="report changes without writing")
    parser.add_argument("--ensure", action="store_true",
                        help="create missing entries, but only for --only clients")
    parser.add_argument("--ensure-all", action="store_true",
                        help="create missing entries in every detected client")
    parser.add_argument("--only", default="",
                        help="comma-separated client keys (default: all detected)")
    parser.add_argument("--port", type=int, default=None,
                        help="port to write (default: auto-resolve)")
    parser.add_argument("--quiet", action="store_true",
                        help="one-line summary only (for the launcher menu)")
    args = parser.parse_args(argv)

    if args.ensure and not args.only:
        parser.error("--ensure creates entries; name the targets with --only "
                     "(or use --ensure-all if you really mean every client).")

    port = args.port if args.port is not None else resolved_port()
    only = [part.strip() for part in args.only.split(",") if part.strip()]
    unknown = [key for key in only if key not in TARGET_KEYS]
    if unknown:
        parser.error(f"unknown client key(s): {', '.join(unknown)}; "
                     f"valid: {', '.join(TARGET_KEYS)}")

    print(f"COMSOLPilot port to configure: {port}")
    if args.ensure_all:
        print("Missing entries WILL be created in every detected client (--ensure-all).")
    elif args.ensure:
        print(f"Missing entries will be created only for: {', '.join(only)}")
    elif not args.quiet:
        print("Update-only mode: existing entries are synced, nothing is created.")
    if not args.quiet:
        print()

    results = sync_all(port, ensure=args.ensure, only=only or None,
                       ensure_keys=["*"] if args.ensure_all else None,
                       dry_run=args.dry_run)

    changed = []
    for item in results:
        action = item.get("action", "?")
        line = f"  {item.get('label', item.get('client', '?')):<16} {action}"
        if item.get("detail"):
            line += f"  ({item['detail']})"
        if item.get("reason"):
            line += f"  ({item['reason']})"
        if item.get("dry_run"):
            line += "  [dry-run]"
        if action in {"created", "updated"} and item.get("written", True):
            changed.append(item)
        if not args.quiet:
            print(line)

    if args.quiet:
        if changed:
            for item in changed:
                print(f"  [MCP] {item['label']}: COMSOL_PORT -> {port}")
            print("  [MCP] Re-trust / restart the connector(s) above.")
        else:
            registered = sum(1 for i in results if i.get("action") == "ok")
            print(f"  [MCP] port OK, {registered} client(s) registered "
                  f"(guide: docs/CONNECTORS_CN.md)")
        return 0

    print()
    if changed:
        for item in changed:
            print(f"  ! {item['label']}: {item['path']}")
        print()
        print("  Re-trust / restart the connector in the client(s) above")
        print("  so the new port takes effect.")
    else:
        print("Nothing to change. To register a new client, either paste an example:")
        print("  python -m src.cli config --client <name>")
        print("or run the registration command for the target client:")
        print("  python scripts/sync_mcp_port.py --ensure --only <name>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
