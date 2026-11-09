"""Keep COMSOL's JVM on a separate process main thread; start it on demand."""
from __future__ import annotations

import asyncio
import functools
import inspect
import json
import multiprocessing
import os
import threading
import time
from pathlib import Path

_LOCAL_TOOLS = {
    "tools_catalog", "tools_describe", "tools_call", "comsol_environment",
    "comsol_list_versions", "comsol_set_preferences", "comsol_configure_client",
    "comsol_open_desktop", "workflow_capabilities", "workflow_validate_spec",
    "workflow_recipes", "physics_get_available",
}
_START_TOOLS = {"comsol_start", "comsol_start_server", "comsol_connect"}


def _ipc_result(value):
    """Use FastMCP's JSON fallback before native Java values cross the pipe."""
    from pydantic_core import to_json
    return json.loads(to_json(value, fallback=str))


def _session_status(manager):
    from .async_handler.solver import async_solver
    if async_solver.is_running:
        # A server RPC during an asynchronous solve can block progress/cancel.
        return {"connected": manager.client is not None, "solving": True,
                "solver": async_solver.get_progress()}
    return {**manager.get_status(), "solving": False}


def worker_main(connection, options):
    """No event loop here: all native initialization runs on this main thread."""
    log_path = Path(__file__).resolve().parent.parent / "workspace" / "logs" / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        # Native libraries must never write into the parent's MCP stdio stream.
        import sys
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        sys.stdout = sys.stderr = log
        if os.name == "nt":
            import ctypes
            import msvcrt
            handle = ctypes.c_void_p(msvcrt.get_osfhandle(log.fileno()))
            ctypes.windll.kernel32.SetStdHandle(-11, handle)
            ctypes.windll.kernel32.SetStdHandle(-12, handle)
        try:
            connection.send({"type": "progress", "stage": "loading_runtime",
                             "message": "正在准备 COMSOL 运行环境…"})
            from .server import mcp, register_all_tools
            from .resources.model_resources import register_model_resources
            from .tools.gateway import call_tool
            from .tools import session

            register_all_tools()
            resources = register_model_resources(mcp)
            manager = session.session_manager
            host = options.get("host") or session._env_default_host()
            port = options.get("port") or session._env_default_port()
            mode = options.get("mode") or ("headless" if options.get("standalone") else session._env_default_mode())
            connection.send({"type": "progress", "stage": "starting_comsol",
                             "message": "正在启动或连接 COMSOL，完成后即可建模…"})
            if options.get("connect_only"):
                result = manager.connect(host=host, port=port, threaded=False)
            else:
                desktop = options.get("open_desktop")
                if desktop is None:
                    desktop = str(session._setting_or_env("COMSOL_OPEN_DESKTOP", "open_desktop", True)).lower() in {"true", "1", "yes", "on"}
                result = manager.start(host=host, port=port, mode=mode,
                                       version=options.get("version") or session.pinned_version(),
                                       cores=options.get("cores"), autostart_server=True,
                                       open_desktop=desktop)
            if not result.get("success") or manager.client is None:
                connection.send({"type": "failed", "error": result.get("error") or "COMSOL did not establish a session."})
                return
            connection.send({"type": "ready", "status": _session_status(manager)})
            while True:
                request = connection.recv()
                if request["kind"] == "shutdown":
                    break
                from .async_handler.solver import async_solver
                control = request["name"] in {"study_get_progress", "study_cancel", "study_wait"}
                if not control and not async_solver.is_running and not manager._client_is_alive():
                    connection.send({"type": "failed", "error": "COMSOL session was lost. Call comsol_start_server to reconnect; the requested operation was not executed.", "executed": False})
                    break
                try:
                    if async_solver.is_running and not control:
                        connection.send({"type": "result", "id": request["id"],
                                         "result": {"success": False, "code": "worker_busy", "executed": False,
                                                    "retryable": True, "hint": "A solve is running. Use study_get_progress or study_cancel before modifying the model."},
                                         "status": _session_status(manager)})
                        continue
                    if request["kind"] == "resource":
                        value = resources[request["name"]](**request["arguments"])
                    else:
                        value = call_tool(mcp, request["name"], request["arguments"])
                    connection.send({"type": "result", "id": request["id"],
                                     "result": _ipc_result(value), "status": _session_status(manager)})
                except Exception as exc:
                    connection.send({"type": "result", "id": request["id"],
                                     "result": {"success": False, "error": str(exc)}})
        except (EOFError, BrokenPipeError):
            pass
        except Exception as exc:
            try:
                connection.send({"type": "failed", "error": f"{type(exc).__name__}: {exc}"})
            except (EOFError, OSError):
                pass
        finally:
            # Do not clear models or shut down a shared COMSOL server on MCP exit.
            connection.close()


class ComsolWorker:
    def __init__(self, target=worker_main, startup_timeout=300, call_timeout=20):
        self.target = target
        self.startup_timeout = startup_timeout
        self.call_timeout = call_timeout
        self.process = None
        self._connection = None
        self._lock = threading.RLock()
        self._state = "idle"
        self._stage = "idle"
        self._message = "COMSOL 将在首次建模时自动启动，无需运行 bat。"
        self._native_status = {}
        self._error = None
        self._pending = None
        self._last_operation = None
        self._started = 0
        self._sequence = 0

    @staticmethod
    def handles(name):
        return name not in _LOCAL_TOOLS and not name.startswith(("reference_", "knowledge_"))

    def _fail(self, message, executed=None):
        self._state = "failed"
        self._error = message
        self._message = "COMSOL 启动或连接失败，请查看错误后重试。"
        if self._pending is not None:
            pending = self._pending
            result = {"success": False, "code": "worker_disconnected", "error": message,
                      "retryable": executed is False, "outcome_unknown": executed is not False,
                      "hint": "Call comsol_start_server to reconnect. Inspect existing models before repeating an operation whose outcome is unknown."}
            if executed is False:
                result["executed"] = False
            pending["result"] = result
            self._last_operation = {"id": pending["id"], "tool": pending["name"], "result": result}
            self._pending = None
            pending["event"].set()

    def status(self):
        with self._lock:
            if self._state == "starting" and time.monotonic() - self._started > self.startup_timeout:
                self.process.terminate()
                self.process.join(timeout=1)
                self._fail("COMSOL startup timed out. See workspace/logs/worker.log, then call comsol_start_server to retry.")
            if self._state not in {"idle", "failed"} and self.process is not None and not self.process.is_alive():
                self._fail("COMSOL worker exited unexpectedly. Call comsol_start_server to reconnect.")
            result = {**self._native_status, "success": self._state != "failed",
                      "state": self._state, "stage": self._stage,
                      "connected": self._state in {"ready", "busy"},
                      "connecting": self._state == "starting", "message": self._message,
                      "worker_pid": self.process.pid if self.process and self._state != "idle" else None}
            if self._state == "starting":
                result["elapsed_seconds"] = round(time.monotonic() - self._started, 1)
            if self._error:
                result["error"] = self._error
            if self._pending:
                result["operation"] = {"id": self._pending["id"], "tool": self._pending["name"]}
            if self._last_operation is not None:
                result["last_operation"] = self._last_operation
            return result

    def _listen(self, connection, process):
        try:
            while True:
                message = connection.recv()
                with self._lock:
                    if process is not self.process or self._state == "idle":
                        return
                    kind = message["type"]
                    if kind == "progress":
                        self._stage = message["stage"]
                        self._message = message["message"]
                    elif kind == "ready":
                        self._native_status = message["status"]
                        self._state = self._stage = "ready"
                        self._message = "COMSOL 已就绪，可以执行建模请求。"
                    elif kind == "failed":
                        self._fail(message["error"], message.get("executed"))
                        return
                    elif kind == "result" and self._pending and message["id"] == self._pending["id"]:
                        pending = self._pending
                        pending["result"] = message["result"]
                        self._native_status.update(message.get("status", {}))
                        self._last_operation = {"id": pending["id"], "tool": pending["name"], "result": message["result"]}
                        self._pending = None
                        self._state = self._stage = "ready"
                        pending["event"].set()
        except (EOFError, OSError):
            with self._lock:
                if process is self.process and self._state not in {"idle", "failed"}:
                    self._fail("COMSOL worker connection closed. The last operation will not be replayed automatically.")

    def start(self, options=None):
        with self._lock:
            if self._state in {"starting", "ready", "busy"}:
                return self.status()
            self.close()
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            self._state = self._stage = "starting"
            self._message = "正在启动 COMSOL 工作进程…"
            self._started = time.monotonic()
            self._error = None
            self._native_status = {}
            self._connection = parent
            self.process = context.Process(target=self.target, args=(child, options or {}), daemon=True)
            try:
                self.process.start()
            except Exception as exc:
                child.close()
                parent.close()
                self._fail(f"Cannot start COMSOL worker: {exc}")
                return self.status()
            child.close()
            threading.Thread(target=self._listen, args=(parent, self.process), daemon=True).start()
            return self.status()

    def _request(self, kind, name, arguments):
        with self._lock:
            if self._state == "busy":
                return {"success": False, "code": "worker_busy", "executed": False,
                        "retryable": True, "hint": "Call comsol_status to wait for the current operation before retrying."}
            if self._state != "ready":
                return {"success": False, "code": "worker_not_ready", "executed": False, "status": self.status()}
            self._sequence += 1
            pending = {"id": self._sequence, "name": name, "event": threading.Event()}
            self._pending = pending
            self._state = "busy"
            try:
                self._connection.send({"id": pending["id"], "kind": kind,
                                       "name": name, "arguments": arguments})
            except (OSError, EOFError) as exc:
                self._fail(str(exc))
        pending["event"].wait(self.call_timeout)
        with self._lock:
            if pending["event"].is_set():
                return pending["result"]
            return {"success": True, "code": "operation_in_progress", "request_id": pending["id"],
                    "retryable": False, "hint": "Do not repeat this operation. Poll comsol_status; last_operation contains its result when complete."}

    def call(self, name, arguments):
        if name == "comsol_status":
            return self.status()
        if name in _START_TOOLS:
            options = {key: value for key, value in arguments.items() if value is not None}
            if name == "comsol_connect":
                options["connect_only"] = True
            return self.start(options)
        if name == "comsol_stop_server":
            self.close()
            from .tools.admin import stop_server
            result = stop_server()
            result["note"] = "The next modeling request starts COMSOL automatically; no bat or connector reconnect is needed."
            return result
        if name == "comsol_disconnect":
            state = self.status()["state"]
            result = self._request("tool", name, arguments) if state == "ready" else {"success": True}
            if state == "busy":
                return {"success": False, "code": "worker_busy", "executed": False,
                        "hint": "Wait for the current operation or use comsol_stop_server to stop it."}
            self.close()
            return result
        state = self.status()["state"]
        if state == "idle":
            self.start()
            return {"success": False, "code": "comsol_starting", "executed": False,
                    "retryable": True, "retry_after_seconds": 2, "status": self.status(),
                    "hint": "COMSOL is starting automatically. Poll comsol_status until state=ready, then retry this request. It has not been executed or queued."}
        if state == "starting":
            return {"success": False, "code": "comsol_starting", "executed": False,
                    "retryable": True, "retry_after_seconds": 2, "status": self.status(),
                    "hint": "Poll comsol_status until state=ready, then retry this unexecuted request."}
        if state == "failed":
            return {"success": False, "code": "worker_failed", "executed": False,
                    "error": self.status().get("error"),
                    "hint": "Inspect the error or workspace/logs/worker.log, then call comsol_start_server to retry without reconnecting MCP."}
        return self._request("tool", name, arguments)

    def read_resource(self, kind, name):
        if self.status()["state"] != "ready":
            return "# COMSOL Session Status\n\nNo active COMSOL resource available. " + self.status()["message"]
        result = self._request("resource", kind, {"name": name})
        return result if isinstance(result, str) else str(result)

    def close(self):
        with self._lock:
            process, connection = self.process, self._connection
            self._state = self._stage = "idle"
            self._message = "COMSOL 将在首次建模时自动启动，无需运行 bat。"
            self._error = None
            self._native_status = {}
            if self._pending:
                self._fail("COMSOL worker was stopped; an in-flight operation may have completed.")
                self._state = "idle"
            if process is not None and process.pid is not None and process.is_alive():
                # No clear()/disconnect(): preserve server-side models on MCP exit.
                process.terminate()
                process.join(timeout=2)
            if connection is not None:
                connection.close()
            self._connection = None


def install_worker_dispatch(mcp, worker):
    """Preserve schemas; keep blocking IPC off the MCP event loop."""
    mcp._comsol_worker = worker
    for name, tool in list(mcp._tool_manager._tools.items()):
        if worker.handles(name):
            original = tool.fn
            @functools.wraps(original)
            async def proxy(_name=name, **kwargs):
                return await asyncio.to_thread(worker.call, _name, kwargs)
            tool.fn = proxy
            tool.is_async = True
        elif name == "tools_call":
            # Native tool calls are logged in the worker. A normal cold start
            # must not be recorded as a modeling failure by the outer gateway.
            original = inspect.unwrap(tool.fn)
            @functools.wraps(original)
            async def dispatch(_original=original, **kwargs):
                return await asyncio.to_thread(_original, **kwargs)
            tool.fn = dispatch
            tool.is_async = True
