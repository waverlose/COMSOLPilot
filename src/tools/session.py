"""Session management tools for COMSOLPilot."""

from typing import Any, Optional
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from functools import lru_cache
import json
import locale
import platform
import mph
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


DEFAULT_COMSOL_PORT = 2036
DEFAULT_COMSOL_HOST = "localhost"


def project_root() -> Path:
    """Repository root (the folder holding src/, scripts/ and workspace/)."""
    return Path(__file__).resolve().parent.parent.parent


def workspace_dir() -> Path:
    path = project_root() / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_settings() -> dict:
    """Read workspace/settings.json (the user's persisted preferences).

    This is the same file the launcher menu and the scripts write, so a
    preference changed from a conversation survives into the next launch and
    keeps the .bat-free workflow coherent.
    """
    path = workspace_dir() / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(updates: dict) -> dict:
    """Merge *updates* into workspace/settings.json and return the new content."""
    settings = load_settings()
    settings.update({k: v for k, v in updates.items() if v is not None})
    path = workspace_dir() / "settings.json"
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return settings


def load_runtime() -> dict:
    """Read workspace/runtime.json (the server this project last started)."""
    try:
        data = json.loads((workspace_dir() / "runtime.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _project_config():
    """The project's config.toml reader (imported lazily to avoid cycles)."""
    from .. import config

    return config


def _setting_or_env(env_key: str, setting_key: str, default: Any = None) -> Any:
    """Environment variable -> config.toml -> workspace/settings.json -> default.

    config.toml is the user-facing configuration shared with the launcher
    script; settings.json only carries runtime state (a remembered version, the
    port COMSOL actually bound).
    """
    value = os.environ.get(env_key)
    if value not in (None, ""):
        return value
    config = _project_config()
    for section in ("comsol", "connector", "ui"):
        value = config.get(section, setting_key)
        if value not in (None, ""):
            return value
    value = load_settings().get(setting_key)
    return default if value in (None, "") else value


def _env_default_port() -> int:
    """Resolve the default COMSOL port."""
    try:
        return int(_setting_or_env("COMSOL_PORT", "port", DEFAULT_COMSOL_PORT))
    except (TypeError, ValueError):
        return DEFAULT_COMSOL_PORT


def _env_default_host() -> str:
    """Resolve the default COMSOL host."""
    return str(_setting_or_env("COMSOL_HOST", "host", DEFAULT_COMSOL_HOST))


def _env_default_mode() -> str:
    """Resolve the preferred session mode."""
    return str(_setting_or_env("COMSOL_MODE", "mode", "gui")).lower()


def _autostart_enabled() -> bool:
    """Whether connector start-up may launch COMSOL when none is listening.

    Defaults to **off**: opening an AI client should not spin up a COMSOL
    Server. COMSOL is started when the user actually asks for it - the assistant
    then runs ``comsol_start_server``, which starts the server process and asks
    for a connector reconnect (COMSOL's Java bridge can only attach during
    connector start-up, never mid-conversation). After that reconnect the
    connector attaches to the already-running server.

    Set ``COMSOL_AUTOSTART=on`` (env) or ``"autostart": true`` (settings.json)
    to have the connector start COMSOL at launch instead.
    """
    raw = os.environ.get("COMSOL_AUTOSTART")
    if raw in (None, ""):
        raw = _project_config().get("connector", "autostart")
    if raw in (None, ""):
        raw = load_settings().get("autostart")
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


LOGIN_MODES = ("auto", "never", "info", "force")



def _ensure_windows_architecture_fallback() -> None:
    """Fallback for hosted Windows processes where platform probing is incomplete."""
    if platform.system() != "Windows":
        return
    try:
        mph.discovery.detect_architecture()
    except OSError:
        @lru_cache(maxsize=1)
        def win64_architecture() -> str:
            return "win64"

        mph.discovery.detect_architecture = win64_architecture


def pinned_version() -> Optional[str]:
    """COMSOL version to pin the client to, if it can be determined.

    A workstation may carry several COMSOL versions; mph's discovery picks the
    newest, which then mismatches the server this project started (that is how
    "No user name and password could be obtained" appeared after 6.4 was
    installed next to 6.2). Priority:

    1. ``COMSOL_MCP_VERSION`` environment variable;
    2. ``comsol_version`` in ``workspace/settings.json`` (the launcher's choice);
    3. the COMSOL path recorded in ``workspace/runtime.json`` (the live server);
    4. None - let mph decide (single-installation machines).
    """
    env_version = os.environ.get("COMSOL_MCP_VERSION")
    if env_version:
        return env_version
    configured = _project_config().get("comsol", "version")
    if configured:
        return str(configured)
    root = Path(__file__).resolve().parent.parent.parent
    for name, keys in (("settings.json", ("comsol_version",)),
                       ("runtime.json", ("comsol_version", "server_exe", "desktop_exe")),
                       ("settings.json", ("comsol_path", "comsol_server_exe", "comsol_desktop_exe"))):
        try:
            state = json.loads((root / "workspace" / name).read_text(encoding="utf-8"))
        except Exception:
            continue
        for key in keys:
            match = re.search(r"(\d+\.\d+)", str(state.get(key) or ""))
            if match:
                return match.group(1)
    return None


def installed_versions() -> list:
    """COMSOL versions MPh can see on this machine, oldest first."""
    try:
        import mph.discovery as discovery
        names = [str(backend.get("name") or "") for backend in discovery.find_backends()]
    except Exception:
        return []
    def key(name: str):
        try:
            return [int(part) for part in name.split(".")]
        except Exception:
            return [0]
    return sorted([name for name in names if name], key=key)


def _backend_exe(version: Optional[str], kind: str) -> Optional[str]:
    """Path to a COMSOL executable ('server' or 'desktop') for *version*.

    MPh discovery is the single source of truth for where COMSOL lives; asking
    it here means the conversation-driven flow never hard-codes install folders
    the way the old launcher script had to.
    """
    _ensure_windows_architecture_fallback()
    try:
        import mph.discovery as discovery
        backend = discovery.backend(version)
    except Exception:
        return None
    entries = backend.get("server" if kind == "server" else "client") or []
    if not entries and kind == "desktop":
        server = (backend.get("server") or [None])[0]
        if server:
            sibling = Path(str(server)).with_name("comsol.exe")
            if sibling.is_file():
                return str(sibling)
        return None
    return str(entries[0]) if entries else None


def server_exe(version: Optional[str] = None) -> Optional[str]:
    """Full path to comsolmphserver.exe for *version* (newest when None)."""
    return _backend_exe(version, "server")


def desktop_exe(version: Optional[str] = None) -> Optional[str]:
    """Full path to comsol.exe (COMSOL Desktop) for *version* (newest when None)."""
    return _backend_exe(version, "desktop")


def launch_desktop(port: int, version: Optional[str] = None,
                   host: str = DEFAULT_COMSOL_HOST) -> dict:
    """Open COMSOL Desktop so the user can attach to the running server.

    The Desktop is started without an auto-connect argument (COMSOL has no
    supported switch for it); the returned hint tells the user the exact
    File > Connect to Server values, mirroring what the .bat printed.
    """
    executable = desktop_exe(version)
    if not executable:
        return {"success": False, "error": "Could not locate comsol.exe (COMSOL Desktop)."}
    try:
        if platform.system() == "Windows":
            subprocess.Popen([executable], close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        else:
            subprocess.Popen([executable], close_fds=True)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller
        return {"success": False, "error": f"Failed to launch COMSOL Desktop: {exc}"}
    return {
        "success": True,
        "desktop_exe": executable,
        "connect_hint": (
            f"In COMSOL Desktop: File > COMSOL Multiphysics Server > Connect to Server, "
            f"host {host}, port {port}."
        ),
    }


def port_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """True when something accepts TCP connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def port_bindable(port: int) -> bool:
    """True when the port can be bound right now.

    Listening and bindable are different questions: Windows can hand a port out
    as an ephemeral source port for a live outbound socket, so nothing appears
    to be listening while COMSOL's bind still fails and it silently relocates.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", port))
            return True
    except OSError:
        return False


def _first_free_port(start: int, window: int = 10) -> Optional[int]:
    for candidate in range(start, start + window + 1):
        if port_bindable(candidate) and not port_listening("localhost", candidate):
            return candidate
    return None


_ANNOUNCED_PORT = re.compile(r"(?:port|端口)[^0-9]{0,4}(\d{2,5})", re.IGNORECASE)


def _read_log_text(log_path: Path) -> str:
    """Read a COMSOL log file, which is written in the console code page (GBK)."""
    try:
        raw = Path(log_path).read_bytes()
    except Exception:
        return ""
    for encoding in ("utf-8", locale.getpreferredencoding(False), "mbcs", "latin-1"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", "replace")


def _announced_ports(log_path: Path) -> list:
    """Ports COMSOL announced in its own log, newest mention first."""
    text = _read_log_text(log_path)
    if not text:
        return []
    found = []
    for match in _ANNOUNCED_PORT.finditer(text):
        try:
            found.append(int(match.group(1)))
        except ValueError:
            continue
    return list(reversed(found))


class LocalServer:
    """A COMSOL server process started from the conversation.

    Mirrors the small part of ``mph.Server`` that the session needs (``port``,
    ``running``, ``stop``) but tolerates COMSOL relocating to a different port,
    which ``mph.Server`` treats as a fatal error even though the server is up.
    """

    def __init__(self, port: int, process=None, exe: Optional[str] = None,
                 log: Optional[str] = None, pid: Optional[int] = None):
        self.port = port
        self.process = process
        # A server launched through WMI has no Popen handle; its pid is all we
        # get back, so stop/status fall back to it.
        self.pid = pid if pid is not None else getattr(process, "pid", None)
        self.exe = exe
        self.log = log

    def running(self) -> bool:
        if self.process is not None:
            try:
                return self.process.poll() is None
            except Exception:
                return False
        return port_listening("localhost", self.port)

    def stop(self, timeout: int = 20) -> None:
        if self.process is not None:
            if not self.running():
                return
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=timeout)
                except Exception:
                    self.process.kill()
            except Exception:
                pass
            return
        if self.pid:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(self.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=timeout)
            except Exception:
                pass


def _spawn_via_wmi(arguments: list, log_path: Path) -> Optional[int]:
    """Start a process from *outside* this process's Windows Job object.

    The MCP stdio client puts the connector inside a Job created with
    ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` and without ``BREAKAWAY_OK``, so a
    plain child is killed the moment the connector exits - and
    ``CREATE_BREAKAWAY_FROM_JOB``, which such a job forbids, is refused with
    ERROR_ACCESS_DENIED. COMSOL must outlive the connector for "start it, then
    reconnect" to work, so it is launched through WMI: WmiPrvSE creates it,
    outside our job. Returns the new pid, or None when the launch failed.
    """
    if platform.system() != "Windows":
        return None
    inner = subprocess.list2cmdline([str(item) for item in arguments])
    command = f'cmd /c "{inner} > "{log_path}" 2>&1"'
    script = (
        "$ErrorActionPreference='Stop';"
        "$p = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{CommandLine=$env:COMSOLPILOT_LAUNCH};"
        "[Console]::Out.Write($p.ProcessId)"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            env=dict(os.environ, COMSOLPILOT_LAUNCH=command),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    except Exception:
        return None
    text = (done.stdout or b"").decode("utf-8", "replace").strip()
    for token in reversed(text.split()):
        if token.isdigit():
            return int(token)
    return None


def _launch_server_process(port: Optional[int] = None, version: Optional[str] = None,
                           cores: Optional[int] = None, timeout: float = 240.0) -> dict:
    """Start comsolmphserver.exe detached and report the port it actually bound.

    This is the Python equivalent of what start_comsol_server.ps1 did: pick a
    bindable port, launch the server with ``-multi on`` so COMSOL Desktop can
    attach, then believe COMSOL's own log over our guess if it relocates. Using
    the process itself (rather than ``mph.Server``) keeps the handle when the
    port moves, so stop/status keep working.
    """
    executable = server_exe(version)
    if not executable:
        return {"success": False,
                "error": "Could not locate comsolmphserver.exe (is COMSOL installed?)"}
    requested = port
    if port is not None and not port_bindable(port):
        free = _first_free_port(port + 1)
        if free is None:
            return {"success": False,
                    "error": f"Port {port} is not bindable and no free port was found nearby."}
        port = free

    log_dir = workspace_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"comsol_server_{port or 'auto'}_{time.strftime('%Y%m%d_%H%M%S')}.log"

    login = str(_setting_or_env("COMSOL_LOGIN_MODE", "login_mode", "auto")).lower()
    if login not in LOGIN_MODES:
        login = "auto"
    arguments = [executable, "-login", login, "-graphics", "-autosave", "off", "-multi", "on"]
    if cores:
        arguments += ["-np", str(cores)]
    if port is not None:
        arguments += ["-port", str(port)]

    creationflags = 0
    if platform.system() == "Windows":
        # The MCP client may run this connector inside a Windows Job object that
        # kills every descendant when the connector exits. Without breakaway the
        # COMSOL server we start here would be killed the moment the connector
        # restarts, so it could never outlive the conversation that started it.
        creationflags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000))
    handle = None
    process = None
    pid = None
    job_escaped = False
    try:
        handle = open(log_path, "wb")
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
        # On Windows the connector normally runs inside a Job object that the MCP
        # client created (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, and no
        # BREAKAWAY_OK). CREATE_BREAKAWAY_FROM_JOB is then *silently ignored* -
        # the spawn succeeds but the child stays in the job and dies with the
        # connector. Launching through WMI puts COMSOL outside the job, which is
        # what makes "start it now, reconnect in a moment" actually work. Set
        # COMSOLPILOT_LAUNCH_VIA_WMI=off to force the plain spawn (debugging).
        use_wmi = (platform.system() == "Windows"
                   and str(os.environ.get("COMSOLPILOT_LAUNCH_VIA_WMI", "on")).lower()
                   not in {"0", "false", "no", "off"})
        if use_wmi:
            handle.close()
            handle = None
            pid = _spawn_via_wmi(arguments, log_path)
            job_escaped = pid is not None
        if pid is None:
            try:
                process = subprocess.Popen(arguments, stdout=handle, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, creationflags=creationflags,
                                           close_fds=True)
                job_escaped = bool(creationflags & breakaway)
            except OSError:
                handle.close()
                handle = open(log_path, "ab")
                process = subprocess.Popen(arguments, stdout=handle, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL,
                                           creationflags=creationflags & ~breakaway,
                                           close_fds=True)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller
        if handle is not None:
            handle.close()
        return {"success": False, "error": f"Failed to start COMSOL server: {exc}"}

    # COMSOL relocates upward when the requested port is in use, so scan the
    # requested port and the next few, plus anything it announces in its log.
    if port is not None:
        candidates = [port] + list(range(port + 1, port + 11))
    else:
        candidates = list(range(2036, 2051))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            return {"success": False,
                    "error": f"COMSOL server exited during start-up (see {log_path}).",
                    "log": str(log_path)}
        for candidate in candidates + [p for p in _announced_ports(log_path)
                                       if p not in candidates]:
            if port_listening("localhost", candidate):
                return {"success": True, "port": candidate,
                        "pid": process.pid if process is not None else pid,
                        "exe": executable, "log": str(log_path), "process": process,
                        "job_escaped": job_escaped,
                        "relocated": requested is not None and candidate != requested}
        time.sleep(1.0)
    return {"success": False,
            "error": f"Timed out waiting for the COMSOL server to listen (see {log_path}).",
            "log": str(log_path)}


def server_process_running() -> bool:
    """Whether a COMSOL server process exists, started or still starting.

    Pre-warm uses this to decide if waiting is worthwhile: no process means
    nothing is coming, so blocking the connector start-up would only delay it.
    Returns True when the check itself fails, so the old, slower behaviour is
    kept rather than risking a missed attach.
    """
    try:
        if platform.system() == "Windows":
            done = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq comsolmphserver.exe", "/NH"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
            return b"comsolmphserver" in done.stdout.lower()
        done = subprocess.run(["pgrep", "-f", "comsolmphserver"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        return done.returncode == 0
    except Exception:
        return True


def start_server_process(port: Optional[int] = None, version: Optional[str] = None,
                         cores: Optional[int] = None) -> dict:
    """Start the COMSOL server *process* only - no JVM, no client.

    Safe to call from a tool: it spawns ``comsolmphserver.exe`` detached and
    waits for it to listen, but never touches COMSOL's Java bridge, so it cannot
    hit the start-up deadlock that guards :meth:`SessionManager.start`.
    """
    result = dict(_launch_server_process(port=port, version=version, cores=cores))
    result.pop("process", None)  # a Popen handle is not serialisable
    return result


def _decode_console(raw: bytes) -> str:
    """Decode subprocess output using the console code page (GBK on zh-CN)."""
    for encoding in ("utf-8", locale.getpreferredencoding(False), "mbcs"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def stop_server_processes() -> dict:
    """Stop every local COMSOL server process. Used by the AI-facing stop tool."""
    system = platform.system()
    if system == "Windows":
        command = ["taskkill", "/F", "/IM", "comsolmphserver.exe"]
    else:
        command = ["pkill", "-f", "comsolmphserver"]
    try:
        done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=30)
    except FileNotFoundError:
        return {"success": False, "error": f"{command[0]} not available on this system."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    output = _decode_console(done.stdout).strip()
    stopped = done.returncode == 0
    return {
        "success": True,
        "stopped": stopped,
        # taskkill exits 128 when no matching process exists - not a failure.
        "message": ("COMSOL server process(es) stopped." if stopped
                    else "No COMSOL server process was running."),
        "detail": output[-400:],
    }


def _version_from_runtime(port: int) -> Optional[str]:
    """Version of the server this project started, when it matches *port*."""
    root = Path(__file__).resolve().parent.parent.parent
    try:
        state = json.loads((root / "workspace" / "runtime.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    if str(state.get("port") or "") != str(port):
        return None
    recorded = str(state.get("comsol_version") or "").strip()
    if recorded:
        return recorded
    match = re.search(r"(\d+\.\d+)", str(state.get("server_exe") or ""))
    return match.group(1) if match else None


_PROBE = (
    "import sys\n"
    "try:\n"
    "    import mph\n"
    "    client = mph.Client(port=int(sys.argv[1]), host=sys.argv[2], version=sys.argv[3])\n"
    "    sys.stdout.write('OK ' + str(client.version))\n"
    "except Exception as exc:\n"
    "    sys.stdout.write('FAIL ' + str(exc)[:180])\n"
    "    sys.exit(1)\n"
)


def _probe_version(port: int, host: str) -> Optional[str]:
    """Try each installed version in a throwaway process; newest first."""
    for version in reversed(installed_versions()):
        try:
            done = subprocess.run(
                [sys.executable, "-c", _PROBE, str(port), host, version],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
        except Exception:
            continue
        if done.returncode == 0:
            return version
    return None


def _remember_version(version: str) -> None:
    """Persist a probed version so the next connection skips the probe."""
    if not version:
        return
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "workspace" / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        settings = {}
    if str(settings.get("comsol_version") or "") == version:
        return
    settings["comsol_version"] = version
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def resolve_connection_version(port: int, host: str, log=None) -> Optional[str]:
    """The COMSOL version to use for the *first* connection in this process."""
    recorded = _version_from_runtime(port)
    if recorded:
        return recorded
    pinned = pinned_version()
    if pinned:
        return pinned
    if log is not None:
        log("COMSOL version not configured; probing the server ...")
    probed = _probe_version(port, host)
    if probed:
        _remember_version(probed)
        if log is not None:
            log("Server speaks COMSOL {} (remembered in settings.json).".format(probed))
    return probed


class SessionManager:
    """Singleton manager for COMSOL client session."""
    
    _instance: Optional["SessionManager"] = None
    _client: Optional[mph.Client] = None
    _server: Optional[mph.Server] = None
    _models: dict[str, mph.Model] = {}
    _current_model: Optional[str] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Connect state. JPype's startJVM() deadlocks when it runs on the
            # MCP/anyio worker thread, so the connect sequence always owns a
            # dedicated threading.Thread and reports progress through these.
            cls._instance._connecting = False
            # 'kernel' or 'clientapi'; probed lazily, reset on session loss.
            cls._instance._api_kind = None
            cls._instance._connect_error: Optional[str] = None
            cls._instance._connect_done = threading.Event()
            cls._instance._connect_lock = threading.Lock()
            cls._instance._jvm_started = False
            # An mph Client whose server went away (or that was disconnected) is
            # kept here: MPh allows only one JVM per process, so the same client
            # object is re-attached instead of constructing a second one.
            cls._instance._retired_client = None
            cls._instance._retire_error = None
        return cls._instance
    
    @property
    def client(self) -> Optional[mph.Client]:
        return self._client
    
    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def _client_is_alive(self) -> bool:
        """True when the bound client can still talk to a live COMSOL server.

        A client whose server died (the launcher was stopped and re-run, or the
        server crashed) keeps its Java objects but every server call raises
        FlException("Not connected to a server"). Detect that zombie state so
        tools can self-heal instead of leaking raw Java exceptions into chat.
        """
        if self._client is None:
            return False
        try:
            self._client.names()
            return True
        except Exception:
            return False

    def clear_stale_session(self) -> None:
        """Drop a client whose server has died so a fresh connect can proceed."""
        try:
            self._retire_client()
            self._client = None
            self._api_kind = None
            self._models.clear()
            self._current_model = None
            if self._server is not None:
                try:
                    self._server.stop()
                except Exception:
                    pass
                self._server = None
        except Exception:
            self._client = None

    def _retire_client(self) -> None:
        """Park the current client for reuse: the JVM cannot be started twice."""
        client = self._client
        if client is None:
            return
        try:
            if getattr(client, "port", None):
                client.disconnect()
        except Exception:
            pass
        self._retired_client = client

    def _acquire_client(self, port: int, host: str, version: Optional[str]):
        """Return an mph Client bound to host:port, reusing the process JVM.

        MPh permits only one Client (one JVM) per Python process. When a session
        has already existed - after ``comsol_disconnect``, or after the server
        was restarted and the old client went stale - re-attach the existing
        client's connection instead of constructing a second one, which MPh
        would reject with "Only one client can be instantiated per Python
        session." The one exception is a stand-alone session, which cannot
        connect to a server at all.
        """
        retired = self._retired_client
        if retired is not None and not getattr(retired, "standalone", False):
            self._retired_client = None
            try:
                if getattr(retired, "port", None):
                    try:
                        retired.disconnect()
                    except Exception:
                        # The old server is already gone; the Java-side teardown
                        # fails but the JVM - and ModelUtil - remain usable.
                        pass
                # Force the bookkeeping back to "not connected" so Client.connect
                # will run even if the teardown above could not complete.
                retired.port = None
                retired.host = None
                retired.connect(port, host)
                return retired
            except Exception as exc:  # noqa: BLE001 - reported below
                self._retire_error = str(exc)
        try:
            import jpype
            jvm_up = bool(jpype.isJVMStarted())
        except Exception:
            jvm_up = False
        if jvm_up:
            detail = getattr(self, "_retire_error", None)
            raise RuntimeError(
                "This process already owns a COMSOL JVM, so a second client cannot "
                "be created, and reconnecting the existing one failed"
                + (f" ({detail})" if detail else "")
                + ". Restart the MCP connector to start a fresh COMSOL session.")
        return mph.Client(port=port, host=host, version=version)
    
    @property
    def current_model(self) -> Optional[str]:
        self.sync_models()
        return self._current_model
    
    @property
    def models(self) -> dict[str, mph.Model]:
        self.sync_models()
        return self._models.copy()

    def bind_client(self, client: mph.Client) -> None:
        """Bind a client and mirror already loaded GUI/server models."""
        self._client = client
        self.sync_models(reset_current=True)

    def sync_models(self, reset_current: bool = False) -> None:
        """Mirror models currently visible through the COMSOL client."""
        if self._client is None:
            return
        if reset_current:
            self._models.clear()
            self._current_model = None
        try:
            self._models = {model.name(): model for model in self._client.models()}
            if reset_current or self._current_model not in self._models:
                self._current_model = next(iter(self._models), None)
        except Exception:
            # Some MPh client modes expose names but not model objects until loaded.
            pass

    def retry_comsol_busy(self, operation, attempts: int = 6, delay: float = 0.4,
                          backoff: float = 1.6):
        """Retry COMSOL server-busy windows caused by GUI multi-client sync.

        Desktop interactions come in short bursts; a ~10 s exponential window
        clears almost all of them without surfacing an error to the AI.
        """
        last_error = None
        current = delay
        for _ in range(attempts):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if ("Server is in use by another client" not in str(exc)
                        and "被其他客户端使用" not in str(exc)):
                    raise
                time.sleep(current)
                current = min(current * backoff, 5.0)
        raise last_error

    def _server_is_listening(self, host: str, port: int, timeout: float = 1.0) -> bool:
        """Probe the fixed GUI-sync port before selecting a COMSOL mode."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _gui_server_missing_result(self, host: str, port: int) -> dict:
        return {
            "success": False,
            "mode": "gui",
            "host": host,
            "port": port,
            "error": (
                f"GUI mode requires a COMSOL server listening on {host}:{port}. "
                "Call comsol_start_server to start one from here, or start it "
                "manually and reconnect with comsol_connect."
            ),
        }

    def _mode_choice_required_result(self, host: str, port: int) -> dict:
        return {
            "success": False,
            "choice_required": True,
            "host": host,
            "port": port,
            # Force the AI/client to ask the user instead of silently choosing auto/headless.
            "message": "Please choose COMSOL mode before starting: gui or headless.",
            "choices": [
                {
                    "mode": "gui",
                    "label": "GUI visible mode",
                    "description": f"Connects to a user-started COMSOL Server on {host}:{port}.",
                },
                {
                    "mode": "headless",
                    "label": "Background mode",
                    "description": "Starts a standalone COMSOL JVM in the background.",
                },
            ],
        }
    
    def start(self, cores: Optional[int] = None, version: Optional[str] = None,
              port: Optional[int] = None, host: Optional[str] = None,
              standalone: bool = False, mode: Optional[str] = None,
              autostart_server: bool = False, open_desktop: bool = False) -> dict:
        """Start a COMSOL client session and refresh the process state.

        Thin wrapper around :meth:`_start_session` that also updates the
        JVM flag and records ``workspace/runtime.json``, so a session started
        from a tool call behaves exactly like one the launcher started - and a
        later ``comsol_connect`` correctly sees the JVM as live instead of
        telling the user to run a script.
        """
        result = self._start_session(
            cores=cores, version=version, port=port, host=host,
            standalone=standalone, mode=mode,
            autostart_server=autostart_server, open_desktop=open_desktop)
        self._mark_jvm_state()
        if result.get("success") and result.get("connected_to") in {"new_server", "standalone_jvm"}:
            self._record_runtime(result, version=version)
        return result

    def _start_session(self, cores: Optional[int] = None, version: Optional[str] = None,
                       port: Optional[int] = None, host: Optional[str] = None,
                       standalone: bool = False, mode: Optional[str] = None,
                       autostart_server: bool = False, open_desktop: bool = False) -> dict:
        """Start a COMSOL client session."""
        port = port if port is not None else _env_default_port()
        host = host or _env_default_host()
        selected_mode = (mode or os.environ.get("COMSOL_MODE") or ("headless" if standalone else "ask")).lower()
        if selected_mode == "ask":
            return self._mode_choice_required_result(host, port)
        if selected_mode not in {"auto", "gui", "headless"}:
            return {
                "success": False,
                "error": "Invalid mode. Use one of: ask, auto, gui, headless."
            }

        if self._client is not None and self._client_is_alive():
            return {
                "success": True,
                "version": self._client.version,
                "cores": getattr(self._client, "cores", None),
                "standalone": getattr(self._client, "standalone", None),
                "message": "Already connected to COMSOL. Use comsol_disconnect before switching modes."
            }
        if self._client is not None:
            # Zombie client from a dead server: drop it and start fresh.
            self.clear_stale_session()
        try:
            _ensure_windows_architecture_fallback()

            server_ready = selected_mode != "headless" and self._server_is_listening(host, port)

            if server_ready:
                finished, _client, error = self._run_jvm_task(self._connect_task(port, host))
                if self._client is None:
                    if not finished:
                        return {
                            "success": True,
                            "connecting": True,
                            "connected_to": "existing_server",
                            "mode": "gui" if selected_mode == "gui" else "auto",
                            "port": port,
                            "host": host,
                            "message": (
                                f"COMSOL connection to {host}:{port} is still starting. "
                                "Call comsol_status to check progress."
                            ),
                        }
                    return {
                        "success": False,
                        "error": error or f"Failed to connect to COMSOL on {host}:{port}.",
                        "port": port,
                        "host": host,
                    }
                return {
                    "success": True,
                    "connected_to": "existing_server",
                    "mode": "gui" if selected_mode == "gui" else "auto",
                    "version": self._client.version,
                    "port": port,
                    "host": host,
                    "standalone": getattr(self._client, "standalone", False),
                    "message": f"Connected to COMSOL server session on {host}:{port}."
                }

            if selected_mode == "gui":
                env_autostart = os.environ.get("COMSOL_AUTOSTART_SERVER", "").lower() in {"1", "true", "yes", "on"}
                if not autostart_server and not env_autostart:
                    return self._gui_server_missing_result(host, port)
                if host not in {DEFAULT_COMSOL_HOST, "127.0.0.1"}:
                    return self._gui_server_missing_result(host, port)
                # Explicit opt-in only: default GUI mode expects the user launcher to own startup.
                def _start_server_task():
                    launch = _launch_server_process(port=port, version=version, cores=cores)
                    if not launch.get("success"):
                        raise RuntimeError(launch.get("error") or "COMSOL server failed to start.")
                    server = LocalServer(launch["port"], launch.get("process"),
                                         exe=launch.get("exe"), log=launch.get("log"),
                                         pid=launch.get("pid"))
                    self._server = server
                    self.bind_client(self._acquire_client(server.port, host, version))
                    if open_desktop:
                        launch_desktop(server.port, version)
                    return server

                finished, _server, error = self._run_jvm_task(_start_server_task, wait=300.0)
                if self._client is None:
                    if not finished:
                        return {
                            "success": True,
                            "connecting": True,
                            "connected_to": "new_server",
                            "mode": "gui",
                            "port": port,
                            "host": host,
                            "message": (
                                "Starting a local COMSOL Server. "
                                "Call comsol_status to check progress."
                            ),
                        }
                    return {"success": False, "error": error or "Failed to start COMSOL Server."}
                relocated = self._server.port != port
                return {
                    "success": True,
                    "connected_to": "new_server",
                    "mode": "gui",
                    "version": self._client.version,
                    "port": self._server.port,
                    "host": host,
                    "relocated_from": port if relocated else None,
                    "log": getattr(self._server, "log", None),
                    "standalone": False,
                    "message": (
                        f"Started COMSOL Server on {host}:{self._server.port}. "
                        "Connect COMSOL Desktop to this server to watch AI operations."
                        + (f" COMSOL relocated from the requested port {port}." if relocated else "")
                    )
                }

            def _standalone_task():
                client = mph.start(cores=cores, version=version)
                self.bind_client(client)
                return client

            finished, _client, error = self._run_jvm_task(_standalone_task, wait=240.0)
            if self._client is None:
                if not finished:
                    return {
                        "success": True,
                        "connecting": True,
                        "mode": "headless",
                        "message": (
                            "Standalone COMSOL JVM is still starting. "
                            "Call comsol_status to check progress."
                        ),
                    }
                return {
                    "success": False,
                    "error": error or "Failed to start standalone COMSOL JVM.",
                }
            return {
                "success": True,
                "connected_to": "standalone_jvm",
                "mode": "headless",
                "version": self._client.version,
                "cores": self._client.cores,
                "standalone": self._client.standalone,
                "message": "Started standalone COMSOL JVM."
            }
        except Exception as e:
            if self._server is not None and self._client is None:
                try:
                    self._server.stop()
                except Exception:
                    pass
                self._server = None
            return {"success": False, "error": str(e)}
    
    def _run_jvm_task(self, task, wait: float = 45.0):
        """Run a JVM-touching callable, waiting up to ``wait`` seconds.

        JPype's ``startJVM`` and the WebBridge connect are only dependable on the
        process **main** thread. From a helper thread they can hang inside
        jpype's class initialisation (observed stuck in
        ``_jclassPost`` -> ``getDeclaredClasses`` while the MCP stdio server was
        serving requests). FastMCP runs synchronous tools on the event-loop
        thread, which is the main thread, so the task runs inline there. The
        helper thread is kept only for callers that really are off the main
        thread (a client that dispatches tools on its own worker thread), where
        inline execution is not possible anyway.

        Returns ``(finished, result, error)``.
        """
        box = {"result": None, "error": None, "finished": False}
        self._connect_error = None
        self._connect_done.clear()
        self._connecting = True

        if threading.current_thread() is threading.main_thread():
            try:
                box["result"] = task()
            except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
                box["error"] = str(exc)
                self._connect_error = str(exc)
            finally:
                box["finished"] = True
                self._connecting = False
                self._connect_done.set()
            return box["finished"], box["result"], box["error"]

        def _worker() -> None:
            try:
                box["result"] = task()
            except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
                box["error"] = str(exc)
                with self._connect_lock:
                    self._connect_error = str(exc)
            finally:
                box["finished"] = True
                with self._connect_lock:
                    self._connecting = False
                self._connect_done.set()

        threading.Thread(target=_worker, name="comsol-jvm", daemon=True).start()
        self._connect_done.wait(wait)
        return box["finished"], box["result"], box["error"]

    def _connect_task(self, port: int, host: str):
        """Connect and bind inside the JVM worker thread (bind touches the JVM)."""
        def _task():
            _ensure_windows_architecture_fallback()
            version = resolve_connection_version(port, host)
            try:
                client = self._acquire_client(port, host, version)
            except Exception as exc:
                # A version mismatch is the one failure the user cannot see
                # through: COMSOL only reports "版本检查失败 / version check
                # failed" and never says which side to change.
                text = str(exc)
                if "版本检查失败" in text or "version check" in text.lower():
                    match = re.search(r"(?:Server|服务器)\s*版本[:：]\s*([\d.]+)", text)
                    server_version = match.group(1) if match else None
                    if server_version:
                        _remember_version(server_version)
                    raise RuntimeError(
                        "COMSOL version mismatch: the client was {} but the server speaks {}."
                        "{}The server version has been recorded in workspace/settings.json -"
                        " restart the connector to pick it up, or start the server with"
                        " -Version {} so both sides match.".format(
                            version or "auto", server_version or "unknown",
                            " " if server_version else " ",
                            version or "6.4")) from exc
                raise
            self.bind_client(client)
            return client
        return _task

    @property
    def is_connecting(self) -> bool:
        return self._connecting

    def connect(self, port: int = DEFAULT_COMSOL_PORT, host: str = DEFAULT_COMSOL_HOST,
                wait: float = 45.0, threaded: bool = True) -> dict:
        """Connect to a running COMSOL server.

        ``threaded=True`` (default) runs the handshake on a background thread and
        waits up to ``wait`` seconds, so a tool call still returns a plain success
        result in the common case.

        ``threaded=False`` runs it on the calling thread and is used by
        :meth:`prewarm` during server startup. That is the only context in which
        the handshake is reliable: once the MCP event loop is serving requests,
        JPype's JVM/WebBridge connect can no longer complete.
        """
        if self._client is not None and self._client_is_alive():
            return {
                "success": False,
                "error": "COMSOL session already running. Disconnect first."
            }
        if self._client is not None:
            # Zombie client from a dead server: drop it and reconnect.
            self.clear_stale_session()
        if not self._server_is_listening(host, port):
            return self._gui_server_missing_result(host, port)

        if not threaded:
            try:
                self._connect_task(port, host)()
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller verbatim
                self._connect_error = str(exc)
            self._mark_jvm_state()
            return self._connect_result(port, host, wait)

        if self._connecting:
            self._connect_done.wait(wait)
        else:
            self._run_jvm_task(self._connect_task(port, host), wait)
        self._mark_jvm_state()
        return self._connect_result(port, host, wait)

    def _mark_jvm_state(self) -> None:
        """Remember whether a JVM now lives in this process."""
        try:
            import jpype
            self._jvm_started = bool(jpype.isJVMStarted())
        except Exception:
            pass

    def _record_runtime(self, result: dict, version: Optional[str] = None) -> None:
        """Record the server this session started in workspace/runtime.json.

        The launcher script used to own this file; writing it from the session
        keeps the "which port/version is live" answer consistent no matter
        whether COMSOL was started from a conversation or from the .bat.
        """
        try:
            live_version = result.get("version") or version
            port = result.get("port")
            server = self._server
            payload = {
                "port": int(port) if port else None,
                "host": result.get("host", DEFAULT_COMSOL_HOST),
                "mode": result.get("mode"),
                "pid": getattr(server, "pid", None),
                "log": getattr(server, "log", None),
                "comsol_version": live_version,
                "server_exe": getattr(server, "exe", None) or server_exe(live_version),
                "desktop_exe": desktop_exe(live_version),
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "started_by": "mcp",
            }
            (workspace_dir() / "runtime.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _connect_result(self, port: int, host: str, wait: float) -> dict:
        if self._client is not None:
            return {
                "success": True,
                "mode": "gui",
                "version": self._client.version,
                "port": port,
                "host": host,
            }
        if self._connecting:
            return {
                "success": True,
                "connecting": True,
                "port": port,
                "host": host,
                "message": (
                    f"COMSOL connection to {host}:{port} is still starting "
                    f"(waited {wait:.0f}s). Call comsol_status to check progress."
                ),
            }
        return {
            "success": False,
            "error": self._connect_error or f"Failed to connect to COMSOL on {host}:{port}.",
            "port": port,
            "host": host,
        }

    @property
    def jvm_started(self) -> bool:
        return self._jvm_started

    def prewarm(self, host: Optional[str] = None, port: Optional[int] = None,
                wait: Optional[float] = None) -> dict:
        """Establish the COMSOL session during startup, before the event loop runs.

        Attaches to a server that is already listening; when none is and
        autostart is enabled, starts one itself (this is what lets the connector
        launch alone bring COMSOL up, with no launcher script). Called from
        ``server.main()`` before ``mcp.run()`` so the first tool call is instant.
        Non-fatal: any failure is reported and the server still starts.
        """
        if self._client is not None:
            return {"success": True, "message": "Already connected."}

        host = host or _env_default_host()
        port = port if port is not None else _env_default_port()
        mode = _env_default_mode()

        prewarm_off = str(_setting_or_env("COMSOL_PREWARM", "prewarm", True)
                          ).strip().lower() in {"0", "false", "no", "off"}
        if prewarm_off:
            return {"success": False, "skipped": True, "message": "COMSOL_PREWARM is off."}

        if wait is None:
            try:
                wait = float(_setting_or_env("COMSOL_PREWARM_WAIT", "prewarm_wait", 20))
            except (TypeError, ValueError):
                wait = 20.0

        # 1. Wait a moment for a server that is already coming up, then attach.
        #    With no COMSOL process in sight nothing is coming, so waiting would
        #    only stall the connector for up to COMSOL_PREWARM_WAIT seconds.
        grace = max(0.0, wait) if server_process_running() else 0.0
        deadline = time.time() + grace
        while not self._server_is_listening(host, port) and time.time() < deadline:
            time.sleep(1.0)
        if self._server_is_listening(host, port):
            remaining = max(5.0, deadline - time.time())
            result = self.connect(port=port, host=host, wait=remaining, threaded=False)
            self._prewarm_banner(result)
            return result

        # 2. Nothing listening. Start one ourselves when allowed, so the MCP
        #    connector launch is the only start-up action the user needs.
        if not _autostart_enabled():
            return self._no_server_result(host, port)
        if host not in {DEFAULT_COMSOL_HOST, "127.0.0.1", "::1"}:
            return {"success": False, "skipped": True,
                    "message": f"Remote host {host}: not starting a local COMSOL server.",
                    "port": port, "host": host}

        if mode == "headless":
            launch = self.start(mode="headless", port=port, host=host)
        else:
            open_desktop = str(_setting_or_env("COMSOL_OPEN_DESKTOP", "open_desktop", "")
                               ).strip().lower() in {"1", "true", "yes", "on"}
            launch = self.start(mode="gui", port=port, host=host,
                                autostart_server=True, open_desktop=open_desktop)

        # The server boot is slow; give the connection the same start-up budget
        # the launcher used rather than the short prewarm window.
        boot_deadline = time.time() + max(wait, 180.0)
        while self._client is None and self._connecting and time.time() < boot_deadline:
            time.sleep(1.0)
        if self._client is not None:
            live_port = getattr(self._server, "port", None) or port
            result = {"success": True, "started_server": True,
                      "connected_to": launch.get("connected_to"),
                      "mode": launch.get("mode"), "version": self._client.version,
                      "port": live_port, "host": host,
                      "message": f"Started COMSOL {self._client.version} and connected on {host}:{live_port}."}
            self._prewarm_banner(result)
            return result
        if launch.get("success"):
            return launch
        return self._no_server_result(host, port, detail=launch.get("error"))

    def jvm_available(self) -> bool:
        """Whether this process already owns a COMSOL JVM.

        When it does not, a COMSOL session can only be opened from the connector
        start-up (``server.main`` -> :meth:`prewarm`), never from a tool call:
        JPype's ``startJVM`` and the WebBridge connect deadlock once the MCP
        event loop is serving requests (verified: a tool-driven start hangs
        inside jpype's class initialisation / ``ModelUtil.connect``).
        """
        if self._retired_client is not None:
            return True
        try:
            import jpype
            return bool(jpype.isJVMStarted())
        except Exception:
            return False

    def restart_required_result(self, port: Optional[int] = None,
                                host: Optional[str] = None,
                                mode: Optional[str] = None,
                                detail: Optional[str] = None) -> dict:
        """Tell the caller a connector restart is needed instead of deadlocking."""
        return {
            "success": False,
            "restart_required": True,
            "port": port,
            "host": host,
            "mode": mode,
            "error": (
                (f"{detail} " if detail else "")
                + "COMSOL is not attached: its Java bridge can only be connected "
                "while the MCP connector starts up, never from a tool call (doing "
                "it here deadlocks)."
            ),
            "hint": ("Start COMSOL with start_comsol_server.bat (or this tool), then "
                     "reconnect the connector once. After that, every connector start "
                     "attaches automatically - the COMSOL server keeps running."),
            "next_step": "start COMSOL, then reconnect the connector once",
        }

    def _no_server_result(self, host: str, port: int,
                          detail: Optional[str] = None) -> dict:
        return {
            "success": False,
            "error": (
                f"No COMSOL server listening on {host}:{port}"
                + (f" ({detail})" if detail else "")
                + ". Ask the assistant to run comsol_start_server, set "
                "COMSOL_AUTOSTART=on to let this connector start COMSOL itself, "
                "or start the server manually."
            ),
            "port": port,
            "host": host,
        }

    def _prewarm_banner(self, result: dict) -> None:
        """Write the presence banner once a pre-warmed session is live."""
        if not result.get("success"):
            return
        try:
            from ..tools.telemetry import ensure_banner
            ensure_banner()
        except Exception:
            pass
    
    def disconnect(self) -> dict:
        """Disconnect and clear the session."""
        if self._client is None:
            return {"success": True, "message": "No active session."}
        try:
            self._client.clear()
            self._models.clear()
            self._current_model = None
            self._retire_client()
            self._client = None
            if self._server is not None:
                self._server.stop()
                self._server = None
            return {"success": True, "message": "Session cleared and client reference released."}
        except Exception as e:
            self._models.clear()
            self._current_model = None
            self._retire_client()
            self._client = None
            if self._server is not None:
                try:
                    self._server.stop()
                except Exception:
                    pass
                self._server = None
            return {"success": True, "message": f"Session cleared (error during clear: {e})"}
    
    def api_kind(self) -> str:
        """Which COMSOL Java API the models expose: 'kernel' or 'clientapi'.

        COMSOL 6.4 replaced the kernel model API on the client side with the
        declarative client API (com.comsol.clientapi.impl). mph 1.4.0 does not
        adapt to it, and every tool here drives the kernel API, so such a
        session cannot run them. Probed once, cached until the session resets.
        """
        if self._api_kind:
            return self._api_kind
        try:
            # Probe with a throwaway model: java.model(tag) is unreliable under
            # the 6.4 client API ("unknown model" even for models it lists).
            probe = self._client.java.createUnique("model")
            try:
                # Both 6.2 and 6.4 hand out com.comsol.clientapi.impl.ModelClient
                # objects, but 6.2's implements the kernel interface
                # (com.comsol.model.Model) while 6.4's does not - the class name
                # alone cannot tell them apart.
                import jpype

                kernel_iface = jpype.JClass("com.comsol.model.Model")
                is_kernel = bool(kernel_iface.class_.isInstance(probe))
            except Exception:
                is_kernel = any(
                    str(i.getName()) == "com.comsol.model.Model"
                    for i in probe.getClass().getInterfaces())
            finally:
                try:
                    self._client.java.remove(probe.tag())
                except Exception:
                    pass
            self._api_kind = "kernel" if is_kernel else "clientapi"
        except Exception:
            self._api_kind = "unknown"
        return self._api_kind

    def get_status(self) -> dict:
        """Get current session status."""
        if self._client is not None and not self._client_is_alive():
            # The server behind this client is gone. Heal instead of throwing.
            self.clear_stale_session()
        if self._client is None:
            status = {
                "connected": False,
                "connecting": self._connecting,
                "message": "No active COMSOL session.",
                "start_hint": ("COMSOL is not running. Start it with "
                               "start_comsol_server.bat (or comsol_start_server), then "
                               "reconnect this connector once - after that every "
                               "connector start attaches automatically."),
            }
            if self._connecting:
                status["message"] = (
                    "COMSOL connection is still starting. Call comsol_status again in a moment."
                )
            elif self._connect_error:
                status["message"] = "COMSOL connection failed."
                status["last_connect_error"] = self._connect_error
            return status
        
        model_list = []
        for name in self._client.names():
            model_info = {"name": name}
            if name in self._models:
                model = self._models[name]
                model_info["file"] = model.file() if hasattr(model, 'file') else None
            model_list.append(model_info)
        
        status = {
            "connected": True,
            "version": self._client.version,
            "cores": self._client.cores,
            "standalone": self._client.standalone,
            "server_port": getattr(self._server, "port", None),
            "models": model_list,
            "current_model": self._current_model,
        }
        try:
            api_kind = self.api_kind()
            status["api_compatibility"] = api_kind
            if api_kind == "clientapi":
                status["warning"] = (
                    "COMSOL {} hands out the new declarative client API "
                    "(com.comsol.clientapi.impl), which none of the modelling "
                    "tools can drive - geometry, physics, mesh and solve calls "
                    "will all fail. Start the server with COMSOL 6.2 instead "
                    "(launcher menu [4]); a 6.4 adapter does not exist yet."
                ).format(status.get("version"))
        except Exception:
            pass
        try:
            from .telemetry import autosave_status

            status["autosave"] = autosave_status()
        except Exception:
            pass
        return status
    
    def add_model(self, model: mph.Model) -> str:
        """Add a model to tracking."""
        name = model.name()
        self._models[name] = model
        if self._current_model is None:
            self._current_model = name
        return name
    
    def get_model(self, name: Optional[str] = None) -> Optional[mph.Model]:
        """Get a model by name or current model, adopting server-side ones.

        A model can exist on the server without being tracked in this process:
        it may have been created by another MCP session, by another client, or by
        the user in the COMSOL Desktop. Those used to fail with "Model not found"
        even though comsol_status listed them, because only locally created
        models were tracked. Refresh from the server before giving up.
        """
        if name is None:
            name = self._current_model
        if name is None:
            return None
        model = self._models.get(name)
        if model is not None:
            return model
        self.sync_models()
        model = self._models.get(name)
        if model is not None:
            return model
        # Tolerate surrounding whitespace / a tag passed instead of a label.
        wanted = str(name).strip()
        for tracked_name, candidate in self._models.items():
            if str(tracked_name).strip() == wanted:
                return candidate
        return None

    def tracked_model_names(self) -> set[str]:
        """Names currently tracked, without contacting the server."""
        return set(self._models)
    
    def set_current_model(self, name: str) -> bool:
        """Set the current active model (adopting server-side ones first)."""
        if name not in self._models:
            self.get_model(name)
        if name in self._models:
            self._current_model = name
            return True
        return False
    
    def remove_model(self, name: str) -> bool:
        """Remove a model from tracking and client."""
        if name in self._models and self._client is not None:
            try:
                self._client.remove(self._models[name])
                del self._models[name]
                if self._current_model == name:
                    self._current_model = next(iter(self._models.keys()), None)
                return True
            except Exception:
                pass
        return False


session_manager = SessionManager()


def register_session_tools(mcp: FastMCP) -> None:
    """Register session management tools with the MCP server."""
    
    @mcp.tool()
    def comsol_start(cores: Optional[int] = None, version: Optional[str] = None,
                     port: Optional[int] = None, host: Optional[str] = None,
                     standalone: bool = False, mode: Optional[str] = None,
                     autostart_server: bool = False, open_desktop: bool = False) -> dict:
        """
        Start a local COMSOL client session.

        Args:
            cores: Number of processor cores to use (default: all available)
            version: COMSOL version to use, e.g., '6.0' (default: latest installed)
            port: COMSOL GUI/server port (default: saved preference, else 2036)
            host: COMSOL server host (default: localhost)
            standalone: Deprecated compatibility flag. Use mode='headless' for background operation.
            mode: 'ask', 'gui', 'headless', or 'auto'. Defaults to ask so the user must choose visible GUI or background mode.
            autostart_server: If true, comsol_start launches a local COMSOL Server for GUI mode (no external script needed).
            open_desktop: When a server is started in GUI mode, also open COMSOL Desktop so it can attach and watch.

        Returns:
            Session info including version and core count, or error message
        """
        if not session_manager.jvm_available():
            # Creating the JVM/connection here would deadlock; it belongs to the
            # connector start-up (prewarm). Ask for a restart instead.
            return session_manager.restart_required_result(
                port if port is not None else _env_default_port(),
                host or _env_default_host(), mode)
        return session_manager.start(
            cores=cores,
            version=version,
            port=port,
            host=host,
            standalone=standalone,
            mode=mode,
            autostart_server=autostart_server,
            open_desktop=open_desktop,
        )

    @mcp.tool()
    def comsol_connect(port: Optional[int] = None, host: Optional[str] = None) -> dict:
        """
        Connect to a running COMSOL Server (GUI-sync session).

        If no session was pre-warmed this can start the COMSOL JVM itself, so a
        server that came up after the connector started can still be attached to.

        Args:
            port: Port the COMSOL server listens on (default: COMSOL_PORT env var, else 2036)
            host: Server hostname or IP address (default: COMSOL_HOST env var, else 'localhost')

        Returns:
            Connection info or an actionable error message
        """
        resolved_port = port if port is not None else _env_default_port()
        resolved_host = host if host else _env_default_host()

        if session_manager._client is not None and session_manager._client_is_alive():
            status = session_manager.get_status()
            status["message"] = "Already connected to COMSOL."
            return status
        if session_manager._client is not None:
            # Zombie client bound to a dead server: drop it and reconnect now.
            session_manager.clear_stale_session()

        # Experimental escape hatch: attempt the in-loop connect anyway, to
        # measure whether it really deadlocks on this machine/version.
        if str(os.environ.get("COMSOLPILOT_FORCE_INLOOP_CONNECT", "")).lower() in {
                "1", "true", "yes", "on"}:
            return session_manager.connect(port=resolved_port, host=resolved_host)

        # Only the connector start-up may open a COMSOL session: a connect from a
        # tool call deadlocks COMSOL's Java bridge once the event loop is serving
        # (see jvm_available). Report that instead of hanging.
        return session_manager.restart_required_result(resolved_port, resolved_host)
    
    @mcp.tool()
    def comsol_disconnect() -> dict:
        """
        Disconnect from COMSOL and clear all models from memory.
        
        Returns:
            Success status and message
        """
        return session_manager.disconnect()
    
    @mcp.tool()
    def comsol_status() -> dict:
        """
        Get the current COMSOL session status.
        
        Returns:
            Session information including connection status, version, and loaded models
        """
        return session_manager.get_status()
