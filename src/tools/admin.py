"""Conversation-driven setup: inspect, prefer, start and register.

Everything the start-up scripts used to require the user to run by hand -
finding COMSOL, choosing a version and port, starting the server, opening the
Desktop, and pointing the MCP clients at the right port - is exposed here as
MCP tools. The assistant can therefore bring COMSOL up and configure the
clients from inside the conversation, with no ``.bat`` and no manual sync:

    comsol_environment       what is installed / listening / configured
    comsol_list_versions     pick which COMSOL to run
    comsol_set_preferences   persist port / version / mode / login mode
    comsol_configure_client  register this connector in MCP clients
    comsol_start_server      launch COMSOL (server + optional Desktop)
    comsol_stop_server       shut the COMSOL server down
    comsol_open_desktop      open COMSOL Desktop to watch a running server

Every mutating tool reports exactly what it changed; nothing here writes to a
client config file unless it is asked to.
"""

from __future__ import annotations

import platform
import socket
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .session import (
    DEFAULT_COMSOL_HOST,
    LOGIN_MODES,
    launch_desktop,
    load_runtime,
    load_settings,
    save_settings,
    session_manager,
    start_server_process,
    stop_server_processes,
)

_VALID_MODES = ("gui", "headless", "auto")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _venv_python() -> str | None:
    for candidate in (_project_root() / ".venv" / "Scripts" / "python.exe",
                      _project_root() / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return None


def _is_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_bindable(port: int) -> bool:
    """Listening and bindable differ: Windows can hold a port as an ephemeral
    source port, which makes COMSOL's bind fail while nothing listens."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", port))
            return True
    except OSError:
        return False


def _installed_versions() -> list[dict]:
    """[(name, server exe, desktop exe)] from MPh discovery, oldest first."""
    try:
        import mph.discovery as discovery
        backends = discovery.find_backends()
    except Exception:
        return []
    versions = []
    for backend in backends:
        name = str(backend.get("name") or "")
        servers = backend.get("server") or []
        server = str(servers[0]) if servers else ""
        desktop = ""
        clients = backend.get("client") or []
        if clients:
            desktop = str(clients[0])
        elif server:
            sibling = Path(server).with_name("comsol.exe")
            if sibling.is_file():
                desktop = str(sibling)
        versions.append({"name": name, "server": server, "desktop": desktop})

    def key(item: dict):
        try:
            return [int(part) for part in item["name"].split(".")]
        except Exception:
            return [0]

    return sorted([v for v in versions if v["name"]], key=key)


def _active_version() -> str:
    """Which COMSOL this project would use: saved preference, else live server."""
    settings_version = str(load_settings().get("comsol_version") or "").strip()
    if settings_version:
        return settings_version
    runtime = load_runtime()
    for key in ("comsol_version", "server_exe", "desktop_exe"):
        value = str(runtime.get(key) or "")
        match = __import__("re").search(r"(\d+\.\d+)", value)
        if match:
            return match.group(1)
    return ""


def environment_report() -> dict:
    """Assemble the environment picture the assistant needs before acting."""
    runtime_python = sys.executable
    packages = {}
    for name in ("mph", "jpype", "mcp", "pydantic", "pypdf"):
        try:
            module = __import__(name)
            packages[name] = getattr(module, "__version__", "installed")
        except Exception:
            packages[name] = "missing"

    versions = _installed_versions()
    settings = load_settings()
    host = str(settings.get("host") or DEFAULT_COMSOL_HOST)
    try:
        port = int(settings.get("port") or 2036)
    except (TypeError, ValueError):
        port = 2036

    clients: dict = {"detected": [], "registered": []}
    try:
        from ..mcp_targets import detected_clients, sync_client
        clients["detected"] = detected_clients()
        for key in clients["detected"]:
            item = sync_client(key, port, ensure=False, dry_run=True)
            if item.get("action") == "ok":
                clients["registered"].append(item.get("label", key))
    except Exception as exc:  # noqa: BLE001
        clients["error"] = str(exc)[:200]

    return {
        "success": True,
        "runtime": {
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python": sys.version.split()[0],
            "executable": runtime_python,
            "venv_python": _venv_python(),
            "project": str(_project_root()),
            "venv_on_non_ascii_path": _non_ascii(str(_project_root())),
        },
        "packages": packages,
        "comsol": {"installed": [v["name"] for v in versions],
                   "active": _active_version() or "auto (newest)"},
        "server": {
            "host": host,
            "port": port,
            "listening": _is_listening(host, port),
            "bindable": _is_bindable(port),
            "runtime": load_runtime(),
        },
        "settings": settings,
        "clients": clients,
        "note": (
            "JPype cannot load its native bridge from a non-ASCII path: keep the "
            "project (and its .venv) on an ASCII-only path or COMSOL will not start."
            if _non_ascii(str(_project_root())) else
            "Environment looks startable; comsol_start_server will use the "
            "active COMSOL version and the saved port."
        ),
    }


def _non_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def set_preferences(port=None, version=None, mode=None, login_mode=None,
                    table_label=None, autostart=None, open_desktop=None) -> dict:
    """Validate and persist preferences into workspace/settings.json."""
    updates: dict = {}
    problems: list[str] = []

    if port is not None:
        try:
            numeric = int(port)
        except (TypeError, ValueError):
            problems.append(f"port '{port}' is not a number")
        else:
            if not (1024 <= numeric <= 65535):
                problems.append("port must be between 1024 and 65535")
            else:
                updates["port"] = numeric

    if version is not None:
        text = str(version).strip()
        known = {item["name"] for item in _installed_versions()}
        if text and text not in known and known:
            problems.append(f"COMSOL {text} is not installed (found: {', '.join(sorted(known))})")
        else:
            updates["comsol_version"] = text

    if mode is not None:
        text = str(mode).strip().lower()
        if text not in _VALID_MODES:
            problems.append(f"mode must be one of {', '.join(_VALID_MODES)}")
        else:
            updates["mode"] = text

    if login_mode is not None:
        text = str(login_mode).strip().lower()
        if text not in LOGIN_MODES:
            problems.append(f"login_mode must be one of {', '.join(LOGIN_MODES)}")
        else:
            updates["login_mode"] = text

    if table_label is not None:
        updates["table_label"] = str(table_label)
    if autostart is not None:
        updates["autostart"] = bool(autostart)
    if open_desktop is not None:
        updates["open_desktop"] = bool(open_desktop)

    if problems:
        return {"success": False, "errors": problems}

    from .. import config as project_config

    # Everything the user can set lives in config.toml; the keys are named after
    # their TOML counterparts so the file stays readable next to the code.
    sections: dict = {}
    if "port" in updates:
        sections.setdefault("comsol", {})["port"] = updates["port"]
    if "comsol_version" in updates:
        sections.setdefault("comsol", {})["version"] = updates["comsol_version"]
    if "mode" in updates:
        sections.setdefault("comsol", {})["mode"] = updates["mode"]
    if "login_mode" in updates:
        sections.setdefault("comsol", {})["login_mode"] = updates["login_mode"]
    if "open_desktop" in updates:
        sections.setdefault("comsol", {})["open_desktop"] = updates["open_desktop"]
    if "autostart" in updates:
        sections.setdefault("connector", {})["autostart"] = updates["autostart"]
    if "table_label" in updates:
        sections.setdefault("ui", {})["table_label"] = updates["table_label"]

    written = project_config.update(sections)
    return {
        "success": True,
        "updated": updates,
        "written": written,
        "config": project_config.load(),
        "path": str(project_config.config_path()),
        "note": ("Saved to config.toml; applies to the next COMSOL server start / "
                 "connector launch."),
    }


def configure_clients(clients=None, ensure: bool = False, port=None,
                      dry_run: bool = True) -> dict:
    """Register or refresh this connector's entry in MCP client configs."""
    from ..mcp_targets import TARGET_KEYS, detected_clients, sync_all

    resolved_port = port if port is not None else int(load_settings().get("port") or 2036)
    requested = [item.strip() for item in clients] if clients else []
    unknown = [key for key in requested if key not in TARGET_KEYS]
    if unknown:
        return {"success": False,
                "error": f"unknown client key(s): {', '.join(unknown)}",
                "valid_keys": TARGET_KEYS}

    targets = requested or detected_clients()
    results = []
    for key in targets:
        results.append(sync_all(resolved_port, ensure=ensure, only=[key],
                                dry_run=dry_run)[0])
    changed = [item for item in results
               if item.get("action") in {"created", "updated"}]
    return {
        "success": True,
        "port": resolved_port,
        "dry_run": dry_run,
        "ensure": ensure,
        "results": results,
        "changed": [item.get("label", item.get("client")) for item in changed],
        "detected_clients": detected_clients(),
        "hint": ("Re-run with dry_run=false to write the changes; the client must "
                 "be restarted or its connector re-trusted for a new entry to load."
                 if dry_run else
                 "Restart / re-trust the affected connectors so they pick up the change."),
    }


def start_server(mode="gui", port=None, version=None, cores=None,
                 open_desktop=None, login_mode=None) -> dict:
    """Start COMSOL from the conversation and connect this session to it."""
    selected = (mode or load_settings().get("mode") or "gui")
    selected = str(selected).strip().lower()
    if selected == "ask":
        # The shared 'mode' schema also offers 'ask'; a direct start cannot ask,
        # so treat it as 'auto' (attach if a server is up, otherwise start one).
        selected = "auto"
    if selected not in _VALID_MODES:
        return {"success": False, "error": f"mode must be one of {', '.join(_VALID_MODES)}"}

    if login_mode is not None:
        pref = set_preferences(login_mode=login_mode)
        if not pref.get("success"):
            return pref

    resolved_port = port if port is not None else load_settings().get("port")
    if resolved_port is not None:
        resolved_port = int(resolved_port)

    settings = load_settings()
    if open_desktop is None:
        open_desktop = bool(settings.get("open_desktop", selected == "gui"))

    status = session_manager.get_status()
    if status.get("connected"):
        return {"success": True, "already_connected": True, "status": status,
                "message": "A COMSOL session is already connected."}

    if not session_manager.jvm_available():
        # Opening the session from a tool call deadlocks COMSOL's Java bridge, but
        # the server *process* is safe to start - and doing so makes the
        # connector's next start-up instant.
        listener = None
        if selected != "headless":
            listener = start_server_process(port=resolved_port, version=version, cores=cores)
        live_port = (listener.get("port") if listener and listener.get("success")
                     else resolved_port)
        detail = (f"A COMSOL server is now listening on {DEFAULT_COMSOL_HOST}:{live_port}."
                  if listener and listener.get("success") else "")
        if listener and listener.get("success") and str(live_port) != str(resolved_port):
            # COMSOL took a different port than asked. Persist it, otherwise the
            # connector that reconnects next would look on the old one and report
            # "no server listening" even though COMSOL is up.
            save_settings({"port": int(live_port)})
            detail += (f" It bound port {live_port} instead of {resolved_port}; that has "
                       "been saved as the new default.")
        result = session_manager.restart_required_result(
            live_port, DEFAULT_COMSOL_HOST, selected, detail=detail)
        result["server"] = listener
        if open_desktop and selected != "headless":
            result["desktop"] = launch_desktop(live_port, version)
        return result

    # A JVM already exists, but re-attaching to a (possibly restarted) server is
    # still a WebBridge connect, which must not run inside the event loop.
    return session_manager.restart_required_result(
        resolved_port, DEFAULT_COMSOL_HOST, selected)


def stop_server() -> dict:
    """Shut down the local COMSOL server and release this session.

    The processes are killed first: a server started with ``-multi on`` ignores
    the client's polite shutdown request, and waiting for it would stall the
    call. Once the process is gone, releasing the session is instant.
    """
    stopped = stop_server_processes()
    disconnect = session_manager.disconnect()
    return {"success": True, "stopped": stopped, "disconnect": disconnect,
            "message": "COMSOL server stopped.",
            "note": ("To use COMSOL again, start it with comsol_start_server and "
                     "reconnect the connector once so it attaches.")}


def open_desktop(port=None, version=None) -> dict:
    """Open COMSOL Desktop to attach to a running server."""
    runtime = load_runtime()
    resolved_port = port if port is not None else runtime.get("port") or load_settings().get("port")
    resolved_version = version or runtime.get("comsol_version") or load_settings().get("comsol_version")
    result = launch_desktop(int(resolved_port) if resolved_port else 2036, resolved_version)
    if result.get("success") and not resolved_port:
        result["warning"] = "No server port is recorded; connect Desktop manually once COMSOL is up."
    return result


def register_admin_tools(mcp: FastMCP) -> None:
    """Register the setup / configuration tools."""

    @mcp.tool()
    def comsol_environment() -> dict:
        """Report the COMSOLPilot environment: Python, packages, COMSOL installs, server state and MCP clients.

        Call this first when something is not working, or before changing a
        setting, so you know which COMSOL version, port and clients are in play.
        """
        return environment_report()

    @mcp.tool()
    def comsol_list_versions() -> dict:
        """List the COMSOL versions installed on this machine and which one is active.

        Returns the server and Desktop executable path for each version so a
        version can be chosen without hard-coding install folders.
        """
        versions = _installed_versions()
        return {
            "success": True,
            "active": _active_version() or "auto (newest)",
            "versions": versions,
            "hint": "Call comsol_set_preferences(version=...) to pin one.",
        }

    @mcp.tool()
    def comsol_set_preferences(port: int = None, version: str = None, mode: str = None,
                               login_mode: str = None, table_label: str = None,
                               autostart: bool = None, open_desktop: bool = None) -> dict:
        """Persist COMSOLPilot preferences (port, version, mode, login mode, table label).

        These are written to workspace/settings.json and take effect on the next
        COMSOL server start or connector launch, replacing the launcher menu.

        Args:
            port: Server port, 1024-65535 (default: keep current)
            version: COMSOL version to pin, e.g. '6.2'; empty string means auto/newest
            mode: Session mode: 'gui' (watched in Desktop), 'headless' or 'auto'
            login_mode: Server authentication: 'auto', 'never', 'info' or 'force'
            table_label: Opt-in renaming label for AI-created COMSOL tables
            autostart: Whether the connector may start COMSOL itself when none is running
            open_desktop: Whether GUI start-up also opens COMSOL Desktop
        """
        return set_preferences(port=port, version=version, mode=mode,
                               login_mode=login_mode, table_label=table_label,
                               autostart=autostart, open_desktop=open_desktop)

    @mcp.tool()
    def comsol_configure_client(clients: list = None, ensure: bool = False,
                                port: int = None, dry_run: bool = True) -> dict:
        """Register or refresh the comsolpilot entry in MCP client configuration files.

        Defaults to a dry run that only reports what would change; set
        dry_run=False to write. A missing entry is created only when ensure is
        true, so an existing client is never silently modified.

        Args:
            clients: Client keys to touch, e.g. ['claude-code']; none means all detected
            ensure: Create the entry where it does not exist yet
            port: Port to write into COMSOL_PORT (default: saved preference)
            dry_run: Report changes without writing (default true)
        """
        return configure_clients(clients=clients, ensure=ensure, port=port, dry_run=dry_run)

    @mcp.tool()
    def comsol_start_server(mode: str = "gui", port: int = None, version: str = None,
                            cores: int = None, open_desktop: bool = None,
                            login_mode: str = None) -> dict:
        """Start the COMSOL server and connect this session to it - no launcher script needed.

        Args:
            mode: 'gui' starts a server COMSOL Desktop can attach to, 'headless'
                runs an unattached background JVM, 'auto' attaches if a server is up
            port: Server port (default: saved preference, else 2036)
            version: COMSOL version to run (default: saved preference, else newest)
            cores: Processor cores for COMSOL to use (default: all available)
            open_desktop: Also open COMSOL Desktop (default: the saved preference)
            login_mode: Server authentication mode to save and apply
        """
        return start_server(mode=mode, port=port, version=version, cores=cores,
                            open_desktop=open_desktop, login_mode=login_mode)

    @mcp.tool()
    def comsol_stop_server() -> dict:
        """Stop the local COMSOL server and release the current session."""
        return stop_server()

    @mcp.tool()
    def comsol_open_desktop(port: int = None, version: str = None) -> dict:
        """Open COMSOL Desktop so it can attach to the running server and show the session live.

        Args:
            port: Server port to connect to (default: the running server's port)
            version: COMSOL version whose Desktop to open (default: the running server's)
        """
        return open_desktop(port=port, version=version)
