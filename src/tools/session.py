"""Session management tools for COMSOLPilot."""

from typing import Optional
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from functools import lru_cache
import json
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


def _env_default_port() -> int:
    """Resolve the default COMSOL port: COMSOL_PORT env var, else 2036.

    Keeps zero-argument calls such as comsol_connect() working out of the box,
    while still honouring run_mcp.bat / client config overrides.
    """
    raw = os.environ.get("COMSOL_PORT")
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return DEFAULT_COMSOL_PORT


def _env_default_host() -> str:
    """Resolve the default COMSOL host: COMSOL_HOST env var, else localhost."""
    return os.environ.get("COMSOL_HOST") or DEFAULT_COMSOL_HOST



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
            cls._instance._connect_error: Optional[str] = None
            cls._instance._connect_done = threading.Event()
            cls._instance._connect_lock = threading.Lock()
            cls._instance._jvm_started = False
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
            self._client = None
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
                "Run start_comsol_server.bat, then reconnect with comsol_connect."
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
              autostart_server: bool = False) -> dict:
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
                    server = mph.Server(cores=cores, version=version, port=port, multi="on")
                    self._server = server
                    self.bind_client(mph.Client(port=server.port, host=host))
                    return server

                finished, _server, error = self._run_jvm_task(_start_server_task, wait=240.0)
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
                return {
                    "success": True,
                    "connected_to": "new_server",
                    "mode": "gui",
                    "version": self._client.version,
                    "port": self._server.port,
                    "host": host,
                    "standalone": False,
                    "message": (
                        f"Started COMSOL Server on {host}:{self._server.port}. "
                        "Connect COMSOL Desktop to this server to watch AI operations."
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
        """Run a JVM-touching callable on its own thread, waiting up to ``wait`` seconds.

        JPype holds the GIL while it starts the COMSOL JVM, which deadlocks when
        the call originates from the MCP / anyio worker thread. Every JVM entry
        point (connect, start server, standalone JVM) therefore goes through this
        helper and never touches JVM state from the caller's own thread.

        Returns ``(finished, result, error)``.
        """
        box = {"result": None, "error": None, "finished": False}
        self._connect_error = None
        self._connect_done.clear()
        self._connecting = True

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
                client = mph.Client(port=port, host=host, version=version)
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

        JPype's JVM handshake deadlocks once the MCP event loop is serving, so this
        must be called from ``server.main()`` *before* ``mcp.run()``. Non-fatal: any
        failure is reported and the server still starts.
        """
        if self._client is not None:
            return {"success": True, "message": "Already connected."}

        host = host or _env_default_host()
        port = port if port is not None else _env_default_port()

        if (os.environ.get("COMSOL_MODE") or "gui").lower() == "headless":
            return {"success": False, "skipped": True,
                    "message": "headless mode: no startup connect attempted."}

        if os.environ.get("COMSOL_PREWARM", "on").lower() in {"0", "false", "no", "off"}:
            return {"success": False, "skipped": True, "message": "COMSOL_PREWARM is off."}

        if wait is None:
            try:
                wait = float(os.environ.get("COMSOL_PREWARM_WAIT", "20"))
            except ValueError:
                wait = 20.0

        deadline = time.time() + max(0.0, wait)
        while True:
            if self._server_is_listening(host, port):
                remaining = max(5.0, deadline - time.time())
                result = self.connect(port=port, host=host, wait=remaining, threaded=False)
                if result.get("success"):
                    try:
                        # 连接成功后在消息日志打一条存在横幅（不写模型）
                        from ..tools.telemetry import ensure_banner

                        ensure_banner()
                    except Exception:
                        pass
                return result
            if time.time() >= deadline:
                return {
                    "success": False,
                    "error": (
                        f"No COMSOL server listening on {host}:{port}. "
                        "Run start_comsol_server.bat, then reconnect this MCP connector."
                    ),
                    "port": port,
                    "host": host,
                }
            time.sleep(1.0)
    
    def disconnect(self) -> dict:
        """Disconnect and clear the session."""
        if self._client is None:
            return {"success": True, "message": "No active session."}
        try:
            self._client.clear()
            self._models.clear()
            self._current_model = None
            self._client = None
            if self._server is not None:
                self._server.stop()
                self._server = None
            return {"success": True, "message": "Session cleared and client reference released."}
        except Exception as e:
            self._models.clear()
            self._current_model = None
            self._client = None
            if self._server is not None:
                try:
                    self._server.stop()
                except Exception:
                    pass
                self._server = None
            return {"success": True, "message": f"Session cleared (error during clear: {e})"}
    
    def get_status(self) -> dict:
        """Get current session status."""
        if self._client is not None and not self._client_is_alive():
            # The server behind this client is gone. Heal instead of throwing.
            self.clear_stale_session()
        if self._client is None:
            status = {
                "connected": False,
                "connecting": self._connecting,
                "message": "No active COMSOL session."
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
        """Get a model by name or current model."""
        if name is None:
            name = self._current_model
        return self._models.get(name)

    def tracked_model_names(self) -> set[str]:
        """Names currently tracked, without contacting the server."""
        return set(self._models)
    
    def set_current_model(self, name: str) -> bool:
        """Set the current active model."""
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
                     port: Optional[int] = DEFAULT_COMSOL_PORT, host: str = DEFAULT_COMSOL_HOST,
                     standalone: bool = False, mode: Optional[str] = None,
                     autostart_server: bool = False) -> dict:
        """
        Start a local COMSOL client session.
        
        Args:
            cores: Number of processor cores to use (default: all available)
            version: COMSOL version to use, e.g., '6.0' (default: latest installed)
            port: Fixed COMSOL GUI/server port (default: 2036)
            host: COMSOL server host (default: localhost)
            standalone: Deprecated compatibility flag. Use mode='headless' for background operation.
            mode: 'ask', 'gui', 'headless', or 'auto'. Defaults to ask so the user must choose visible GUI or background mode.
            autostart_server: Advanced opt-in. If true, comsol_start may launch a local COMSOL Server for GUI mode.
        
        Returns:
            Session info including version and core count, or error message
        """
        return session_manager.start(
            cores=cores,
            version=version,
            port=port,
            host=host,
            standalone=standalone,
            mode=mode,
            autostart_server=autostart_server,
        )
    
    @mcp.tool()
    def comsol_connect(port: Optional[int] = None, host: Optional[str] = None) -> dict:
        """
        Connect to a running COMSOL Server (GUI-sync session).

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

        if not session_manager.jvm_started:
            # No JVM exists in this process. Starting one from inside a tool call
            # deadlocks the MCP event loop (JPype startJVM + anyio), so refuse with
            # a clear next step instead of hanging the whole connector forever.
            return {
                "success": False,
                "error": (
                    "COMSOL was not reachable when this MCP server started, so no "
                    f"session was pre-warmed for {resolved_host}:{resolved_port}. "
                    "Run start_comsol_server.bat first, then reconnect this MCP "
                    "connector (or restart the AI client)."
                ),
                "port": resolved_port,
                "host": resolved_host,
                "hint": "Reconnect the MCP connector after the COMSOL server is up.",
            }

        return session_manager.connect(port=resolved_port, host=resolved_host)
    
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
