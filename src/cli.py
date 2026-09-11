"""COMSOLPilot command line interface.

One entry point for the things a user actually needs to do outside the AI
client, so nobody has to read the source to get started:

    python -m src.cli onboard     # first run: checks, config, next steps
    python -m src.cli doctor      # environment / COMSOL / port / registration
    python -m src.cli config      # paste-ready MCP client configuration
    python -m src.cli tools       # the full tool catalogue, grouped
    python -m src.cli prompts     # reusable prompt templates
    python -m src.cli demo --run  # build and solve a tiny model end to end

Everything here is read-only or explicitly opt-in; none of it starts the MCP
server or talks to COMSOL unless a command says so.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# mph reads %APPDATA% at import time; a shell without it (Git Bash, some CI
# runners) would otherwise fail before we can print anything useful.
if platform.system() == "Windows" and not os.environ.get("APPDATA"):
    os.environ["APPDATA"] = os.path.expanduser("~\\AppData\\Roaming")

DEFAULT_PORT = 2036
DEFAULT_HOST = "localhost"

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def head(text: str) -> None:
    print()
    print(_c(text, "1"))
    print(_c("-" * max(len(text), 40), "90"))


def ok(text: str) -> None:
    print(f"  {_c('OK  ', '32')} {text}")


def warn(text: str) -> None:
    print(f"  {_c('WARN', '33')} {text}")


def bad(text: str) -> None:
    print(f"  {_c('FAIL', '31')} {text}")


def info(text: str) -> None:
    print(f"  {_c('    ', '90')} {text}")


def _port_env() -> int:
    try:
        return int(os.environ.get("COMSOL_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def _host_env() -> str:
    return os.environ.get("COMSOL_HOST") or DEFAULT_HOST


def _mode_env() -> str:
    return os.environ.get("COMSOL_MODE") or "gui"


def _port_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _port_bindable(port: int) -> bool:
    """Listening and bindable are different: Windows can hand a port out as an
    ephemeral source port, which makes COMSOL's bind fail while nothing listens."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", port))
            return True
    except OSError:
        return False


def _venv_python() -> Path | None:
    candidate = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return candidate
    candidate = PROJECT_ROOT / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def cmd_doctor(_args: argparse.Namespace) -> int:
    head("1. Runtime")
    ok(f"OS        {platform.system()} {platform.release()} ({platform.machine()})")
    ok(f"Python    {sys.version.split()[0]}  ({sys.executable})")
    ok(f"Project   {PROJECT_ROOT}")

    head("2. Python packages")
    failures = 0
    for package in ("mph", "jpype", "mcp", "pydantic"):
        try:
            module = __import__(package)
            ok(f"{package:<10} {getattr(module, '__version__', 'installed')}")
        except Exception as exc:  # noqa: BLE001
            bad(f"{package:<10} missing ({exc})")
            failures += 1
    if failures:
        info("Fix with: pip install -r requirements-windows.txt")

    head("3. COMSOL installation")
    comsol_ok = False
    try:
        import mph
        backends = mph.discovery.find_backends()
        if backends:
            comsol_ok = True
            for backend in backends:
                ok(f"{backend.get('name')}  {backend.get('root')}")
        else:
            bad("No COMSOL installation found")
    except Exception as exc:  # noqa: BLE001
        bad(f"Discovery failed: {exc}")
    if not comsol_ok:
        info("Set COMSOL_SERVER_EXE or pass -ServerExe to start_comsol_server.bat")

    head("4. Session / port")
    host, port, mode = _host_env(), _port_env(), _mode_env()
    info(f"COMSOL_MODE={mode}  COMSOL_HOST={host}  COMSOL_PORT={port}")
    if _port_listening(host, port):
        ok(f"A COMSOL server is listening on {host}:{port}")
    elif _port_bindable(port):
        warn(f"Nothing listening on {host}:{port} yet")
        info("Start it with: start_comsol_server.bat")
    else:
        warn(f"Port {port} cannot be bound (held by another process, often an ephemeral socket)")
        info("start_comsol_server.bat will pick the next free port and tell you which one")
    if mode == "gui":
        info("GUI mode needs the server running BEFORE the MCP connector starts")

    head("5. MCP surface")
    try:
        from src.server import mcp, register_all_tools
        register_all_tools()
        count = len(mcp._tool_manager._tools)
        try:
            prompt_count = len(mcp._prompt_manager._prompts)
        except Exception:
            prompt_count = 0
        ok(f"{count} tools, {prompt_count} prompt templates registered")
    except Exception as exc:  # noqa: BLE001
        bad(f"Registration failed: {exc}")
        failures += 1

    head("Result")
    if failures:
        bad(f"{failures} problem(s) found -- see above")
        return 1
    ok("Environment check passed")
    return 0


def _mcp_payload(port: int) -> dict:
    python = _venv_python()
    command = str(python) if python else sys.executable
    return {
        "command": command,
        "args": ["-m", "src.server"],
        "cwd": str(PROJECT_ROOT),
        "env": {
            "COMSOL_MODE": "gui",
            "COMSOL_HOST": _host_env(),
            "COMSOL_PORT": str(port),
            "COMSOL_PREWARM": "on",
            "COMSOL_PREWARM_WAIT": "20",
        },
    }


_CLIENT_NOTES = {
    "workbuddy": ("~/.workbuddy/mcp.json", "json"),
    "claude": ("%APPDATA%\\Claude\\claude_desktop_config.json", "json"),
    "gemini": ("%USERPROFILE%\\.gemini\\settings.json", "json"),
    "opencode": ("<project>\\.mcp.json", "json"),
    "codex": ("%USERPROFILE%\\.codex\\config.toml", "toml"),
}


def cmd_config(args: argparse.Namespace) -> int:
    port = args.port or _port_env()
    payload = _mcp_payload(port)
    client = (args.client or "workbuddy").lower()
    path, flavour = _CLIENT_NOTES.get(client, _CLIENT_NOTES["workbuddy"])

    head(f"MCP configuration for {client}")
    info(f"Config file: {path}")
    print()
    if flavour == "toml":
        print(f"[mcp_servers.comsolpilot]\ncommand = {json.dumps(payload['command'])}")
        print(f"args = {json.dumps(payload['args'])}")
        print(f"cwd = {json.dumps(payload['cwd'])}")
        print("env = " + json.dumps(payload["env"]))
    else:
        print(json.dumps({"mcpServers": {"comsolpilot": payload}}, indent=2, ensure_ascii=False))

    head("Next steps")
    info("1. Copy the block above into the config file")
    info("2. Trust / enable the server in the client's connector page")
    info("3. Start COMSOL first:  start_comsol_server.bat")
    info("4. Then reconnect the connector so it pre-warms the session")
    return 0


_TOOL_GROUPS = (
    ("Session", ("comsol_",)),
    ("Model", ("model_",)),
    ("Geometry", ("geometry_",)),
    ("Material", ("material_",)),
    ("Physics", ("physics_", "multiphysics_")),
    ("Mesh", ("mesh_",)),
    ("Study / solve", ("study_", "solutions_", "datasets_")),
    ("Results", ("results_",)),
    ("Parameters", ("param_",)),
    ("Workflow (one-call modelling)", ("workflow_",)),
)


def cmd_tools(args: argparse.Namespace) -> int:
    from src.server import mcp, register_all_tools
    register_all_tools()
    names = sorted(mcp._tool_manager._tools.keys())

    if not args.group:
        head(f"{len(names)} tools")
        for name in names:
            print("  " + name)
        return 0

    head(f"{len(names)} tools, grouped")
    claimed: set[str] = set()
    for label, prefixes in _TOOL_GROUPS:
        members = [n for n in names if n.startswith(prefixes) and n not in claimed]
        claimed.update(members)
        if members:
            print(f"\n  {_c(label, '1')}  ({len(members)})")
            for name in members:
                print("    " + name)
    leftover = [n for n in names if n not in claimed]
    if leftover:
        print(f"\n  {_c('Other', '1')}  ({len(leftover)})")
        for name in leftover:
            print("    " + name)
    return 0


def cmd_prompts(_args: argparse.Namespace) -> int:
    from src.server import mcp, register_all_tools
    register_all_tools()
    try:
        prompts = mcp._prompt_manager._prompts
    except Exception:
        prompts = {}
    head(f"{len(prompts)} prompt templates")
    for name, prompt in sorted(prompts.items()):
        doc = (getattr(prompt, "fn", None) or getattr(prompt, "description", None))
        text = ""
        if callable(doc):
            text = (doc.__doc__ or "").strip().splitlines()[0] if doc.__doc__ else ""
        elif isinstance(doc, str):
            text = doc.strip().splitlines()[0]
        print(f"  {_c(name, '1'):<34} {_c(text, '90')}")
    info("Clients expose these as slash commands or template pickers.")
    return 0


DEMO_SPEC = {
    "model": {"name": "OnboardingDemo", "dimension": 3},
    "geometry": [{"type": "block", "tag": "blk1", "position": [0, 0, 0], "size": [0.1, 0.1, 0.1]}],
    "materials": [{
        "tag": "mat1", "label": "Aluminum", "domains": "all",
        "properties": {"thermalconductivity": "205[W/(m*K)]",
                       "density": "2700[kg/m^3]",
                       "heatcapacity": "900[J/(kg*K)]"},
    }],
    "physics": [{"type": "ht", "boundary_conditions": [
        {"tag": "hot", "type": "Temperature",
         "where": {"box": {"xmin": -1e-6, "xmax": 0.100001,
                           "ymin": -1e-6, "ymax": 0.100001,
                           "zmin": -1e-6, "zmax": 1e-6}},
         "properties": {"T0": "373.15[K]"}},
        {"tag": "cold", "type": "Temperature",
         "where": {"box": {"xmin": -1e-6, "xmax": 0.100001,
                           "ymin": -1e-6, "ymax": 0.100001,
                           "zmin": 0.099999, "zmax": 0.100001}},
         "properties": {"T0": "293.15[K]"}},
    ]}],
    "mesh": {"tag": "mesh1", "size": 4, "run": True},
    "study": {"tag": "std1", "type": "Stationary"},
    "outputs": [
        {"name": "Tmax", "type": "max", "expression": "T", "unit": "K"},
        {"name": "Tmin", "type": "min", "expression": "T", "unit": "K"},
    ],
}


def cmd_demo(args: argparse.Namespace) -> int:
    head("Onboarding demo: steady-state conduction through a 0.1 m aluminium cube")
    info("Hot face 373.15 K, cold face 293.15 K, everything else insulated.")
    info("Expected: Tmax = 373.15 K, Tmin = 293.15 K.")

    if not args.run:
        print()
        print(json.dumps(DEMO_SPEC, indent=2, ensure_ascii=False))
        head("To run it")
        info("python -m src.cli demo --run")
        info("Requires a COMSOL server: start_comsol_server.bat")
        return 0

    host, port = _host_env(), (args.port or _port_env())
    if not _port_listening(host, port):
        bad(f"No COMSOL server on {host}:{port}")
        info("Run start_comsol_server.bat, then retry")
        return 1

    from src.tools.session import session_manager
    from src.tools.workflow import JavaWorkflowExecutor

    head("Connecting")
    result = session_manager.connect(port=port, host=host, threaded=False)
    if session_manager.client is None:
        bad(f"Connect failed: {result.get('error')}")
        return 1
    ok(f"Connected to COMSOL {session_manager.client.version} on {host}:{port}")

    head("Building and solving")
    outcome = JavaWorkflowExecutor(DEMO_SPEC, solve=True, collect_outputs=True).run()
    for step in outcome.get("log", []):
        info(str(step))

    head("Result")
    if not outcome.get("success"):
        bad(str(outcome.get("solve_error") or outcome.get("error")))
        return 1
    for output in outcome.get("outputs", []):
        ok(f"{output.get('name')} = {output.get('value')} {output.get('unit')}")
    ok("Demo completed")
    return 0


def cmd_onboard(args: argparse.Namespace) -> int:
    code = cmd_doctor(args)
    port = args.port or _port_env()

    head("6. Register the connector in your MCP client(s)")
    info("Nothing is written automatically - you decide which client gets an entry.")
    try:
        from src.mcp_targets import detected_clients, sync_client
        for key in detected_clients():
            item = sync_client(key, port, ensure=False, dry_run=True)
            label = item.get("label", key)
            if item.get("action") == "ok":
                ok(f"{label:<16} already registered (port synced to {port})")
            else:
                warn(f"{label:<16} not registered yet")
    except Exception as exc:  # noqa: BLE001
        bad(f"Client detection failed: {exc}")

    info("Register a client - pick ONE of:")
    info("  a) paste-ready example:  python -m src.cli config --client <name>")
    info("  b) let the tool create:  python scripts/sync_mcp_port.py --ensure --only <name>")
    info("Client names: workbuddy, claude-code, claude-desktop, gemini, cursor,")
    info("               windsurf, opencode, codex, deepseek")

    cmd_config(argparse.Namespace(port=args.port, client=args.client))
    head("You are set up when these are true")
    info("start_comsol_server.bat says the server started")
    info("The connector page shows comsolpilot as trusted/enabled")
    info("Asking the AI 'check COMSOLPilot status' returns connected: true")
    head("Then try")
    info("python -m src.cli demo --run          # see a real solve end to end")
    info("Or just tell the AI: build a steady-state heat conduction model")
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="COMSOLPilot companion CLI: get running, then get productive.",
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="check the environment, COMSOL and the port")
    onboard = sub.add_parser("onboard", help="doctor + config + next steps (start here)")
    onboard.add_argument("--client", default="workbuddy",
                         choices=sorted(_CLIENT_NOTES), help="target MCP client for config printing")
    onboard.add_argument("--port", type=int, default=0, help="override the COMSOL port")
    sub.add_parser("prompts", help="list reusable prompt templates")

    config = sub.add_parser("config", help="print a paste-ready MCP client config")
    config.add_argument("--client", default="workbuddy",
                        choices=sorted(_CLIENT_NOTES), help="target MCP client")
    config.add_argument("--port", type=int, default=0, help="override the COMSOL port")

    tools = sub.add_parser("tools", help="list the tool catalogue")
    tools.add_argument("--group", action="store_true", help="group by area")

    demo = sub.add_parser("demo", help="show (or run) a minimal end-to-end model")
    demo.add_argument("--run", action="store_true", help="actually build and solve it")
    demo.add_argument("--port", type=int, default=0, help="override the COMSOL port")

    return parser


def main(argv: list[str] | None = None) -> int:
    global _USE_COLOR
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "no_color", False):
        _USE_COLOR = False

    handlers = {
        "doctor": cmd_doctor,
        "onboard": cmd_onboard,
        "config": cmd_config,
        "tools": cmd_tools,
        "prompts": cmd_prompts,
        "demo": cmd_demo,
    }
    if not args.command:
        parser.print_help()
        return 0
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
