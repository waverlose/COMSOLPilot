"""Cross-cutting observability for COMSOLPilot.

Two sinks, both best-effort so they can never break a tool call:

1. COMSOL's own message log
   ``ModelUtil.serverLog("...")`` appends to the COMSOL server log, which the
   COMSOL Desktop shows in its Messages window once connected as a client.
   Driving the server through GUI sync therefore lets the user watch exactly
   what the AI is doing, inside COMSOL, in real time.

   Do NOT use ``ModelUtil.showProgress(String)`` for this: it takes a *file*
   name and silently creates a "progress output file" with that name in the
   COMSOL working directory (observed on 6.2 — it littered ``bin\\win64`` with
   one file per message). ``showProgress(boolean)`` only toggles the progress
   bar. ``serverLog`` is the message-log entry point.

2. A structured JSONL call log
   ``workspace/logs/tool_calls.jsonl`` — one line per MCP tool call with the
   tool name, a trimmed argument summary, duration and status. This is the only
   thing that lets you answer "what did the AI actually run?" afterwards.
"""

from __future__ import annotations

import functools
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

try:  # stderr logging only; stdout is reserved for JSON-RPC
    from ..tools.session import session_manager
except Exception:  # pragma: no cover - import cycle safety
    session_manager = None  # type: ignore[assignment]


PREFIX = "COMSOLPilot"

# Chatty/read-only tools that would only add noise to the COMSOL window.
_QUIET_TOOLS = {
    "comsol_status",
    "comsol_disconnect",
    "study_get_progress",
    "study_wait",
    "model_list",
    "model_inspect",
    "geometry_list",
    "geometry_list_features",
    "physics_list",
    "physics_list_features",
    "physics_get_available",
    "mesh_list",
    "mesh_info",
    "results_plots_list",
    "results_exports_list",
    "solutions_list",
    "study_list",
    "workflow_capabilities",
    "workflow_validate_spec",
    "param_list",
    "param_get",
    "material_list",
    "datasets_list",
}

_LOG_LOCK = threading.Lock()
_model_util: Any = None
_model_util_probed = False

# --- COMSOLPilot signature table ----------------------------------------------
# One-shot, zero-lag: the current model gets a "comsolpilot" table holding
# the UTF-8 binary encoding of a short signature (one row per byte, one
# column per bit, most significant bit first). Written once when the session
# connects — no periodic writes, no heartbeat, no lag. The table API accepts
# double[][] only, hence the 0/1 grid. Best-effort everywhere: failures are
# remembered and retried on the next tool call, never breaking anything.

_MSG_TAG = "comsolpilot"
_MESSAGE = "道阻且长 微信 18298157587"
_message_written = False
_message_last_error: str | None = None

# --- COMSOLPilot digit screen -------------------------------------------------
# The user's idea: a table is effectively a low-resolution screen. 15 rows
# (the default visible height) x WIDTH columns, each cell one digit
# (9 = lit, 0 = dark), renders TEXT as a bitmap. Written ONCE — animation
# would mean constant table refreshes, which the user already rejected as
# laggy. Frozen at build time; no font/PIL dependency at runtime.

_SCREEN_TAG = "comsolpilot_screen"
_SCREEN_TEXT = "道阻且长"
_screen_written = False
_screen_last_error: str | None = None

SCREEN = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 9, 9, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0],
    [0, 9, 0, 0, 0, 0, 9, 0, 0, 9, 0, 0, 0, 0, 0, 9, 9, 9, 9, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 9, 9, 0, 0, 0],
    [0, 9, 0, 0, 9, 9, 9, 9, 9, 9, 9, 9, 9, 0, 0, 9, 9, 0, 9, 0, 9, 9, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 9, 9, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 9, 9, 0, 9, 0, 9, 9, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 9, 9, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 9, 9, 9, 9, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 9, 0, 0, 0, 0, 0, 0],
    [9, 9, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 9, 9, 0, 9, 0, 9, 9, 0, 0, 0, 9, 9, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9],
    [0, 9, 9, 0, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 9, 9, 0, 9, 0, 9, 9, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 9, 9, 0, 9, 9, 0, 0, 0, 9, 9],
    [0, 9, 9, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 9, 9, 0, 0, 9, 9, 9, 0, 0, 0, 9, 9, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 9, 0, 0, 0, 0, 0],
    [0, 9, 9, 0, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 9, 9, 0, 9, 9, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 9, 9, 0, 0, 0, 0],
    [0, 9, 9, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 9, 9, 9, 9, 0, 9, 9, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 9, 0, 0, 0, 0],
    [0, 9, 9, 0, 0, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 9, 9, 0, 0, 0, 9, 9, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 9, 9, 0, 0, 9, 9, 0, 0],
    [0, 9, 9, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 9, 9, 0, 0, 0, 9, 9, 0, 0, 0, 9, 9, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, 9, 9, 0, 0, 0, 0, 0, 0, 0, 9, 9, 9, 0, 0, 0, 0, 9, 9, 0],
    [9, 0, 0, 0, 9, 9, 9, 9, 9, 9, 9, 9, 9, 0, 0, 9, 9, 0, 0, 9, 9, 9, 9, 9, 9, 9, 9, 9, 0, 0, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 9, 9, 0, 0, 0, 0, 0, 0, 9, 0],
]


def ensure_screen() -> None:
    """Disabled: signature screen table injected into user models is unwanted.

    Referenced an undefined ``_status_lock`` (NameError on every tool call)
    and wrote a vendor watermark table into the active model. No-op now.
    """
    return


def _status_model() -> Any:
    """The current model object, or None when nothing is tracked."""
    try:
        if session_manager is None:
            return None
        return session_manager.get_model(None)
    except Exception:
        return None


def _message_table(model: Any):
    """Drop legacy tables (superseded by parameters)."""
    jm = model.java
    tables = jm.result().table()
    for legacy in ("comsolpilot", "comsolpilot_status", "ai_status"):
        try:
            tables.remove(legacy)
        except Exception:
            pass
    return None


def write_signature(model: Any) -> None:
    """Write the UTF-8 binary of _MESSAGE as model parameters B00..B30.

    Parameters display their values verbatim (no decimal formatting), so each
    byte reads as a clean 8-bit binary string in the Desktop parameter table.
    """
    global _message_last_error
    try:
        jm = model.java
        tables = jm.result().table()
        for legacy in ("comsolpilot", "comsolpilot_status", "ai_status"):
            try:
                tables.remove(legacy)
            except Exception:
                pass
        params = jm.param()
        for index, byte in enumerate(_MESSAGE.encode("utf-8")):
            params.set("B{:02d}".format(index), format(byte, "08b"))
        _message_last_error = None
    except Exception as exc:
        _message_last_error = str(exc)[:250]


def ensure_message() -> None:
    """Disabled: watermark/signature injection into user models is unwanted.

    The original implementation wrote a UTF-8 signature into model parameters
    B00..B30 and referenced an undefined ``_message_lock`` (NameError on every
    tool call). Writing vendor signatures into research models corrupts the
    deliverables, so this is now a no-op.
    """
    return


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _log_path() -> Path:
    directory = _project_root() / "workspace" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "tool_calls.jsonl"


def _load_model_util() -> Any:
    """Resolve COMSOL's ModelUtil once, after the JVM exists."""
    global _model_util, _model_util_probed
    if _model_util is not None or _model_util_probed:
        return _model_util
    _model_util_probed = True
    try:
        import jpype

        if not jpype.isJVMStarted():
            return None
        from com.comsol.model.util import ModelUtil  # type: ignore[import-not-found]

        _model_util = ModelUtil
    except Exception:
        _model_util = None
    return _model_util


def push_comsol_message(message: str) -> bool:
    """Append a line to the COMSOL message log. Never raises.

    ``serverLog`` is the only ModelUtil entry point that writes a message
    without side effects: ``showProgress(String)`` treats its argument as a
    file name and creates that file on disk.
    """
    util = _load_model_util()
    if util is None:
        return False
    try:
        util.serverLog(message)
        return True
    except Exception:
        return False


def summarize_arguments(arguments: Any, limit: int = 160) -> str:
    """Short, log-friendly rendering of tool arguments."""
    if not isinstance(arguments, dict) or not arguments:
        return ""
    parts: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            text = str(value)
        if len(text) > 60:
            text = text[:57] + "..."
        parts.append(f"{key}={text}")
    joined = " ".join(parts)
    return joined if len(joined) <= limit else joined[: limit - 3] + "..."


def record_tool_call(name: str, arguments: Any, status: str,
                     duration_ms: float, error: str | None = None) -> None:
    """Append one structured line to the JSONL call log. Never raises."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": name,
        "status": status,
        "duration_ms": round(duration_ms, 1),
        "arguments": summarize_arguments(arguments),
    }
    if error:
        entry["error"] = error[:400]
    try:
        with _LOG_LOCK:
            with open(_log_path(), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _describe(name: str, arguments: Any) -> str:
    summary = summarize_arguments(arguments, limit=110)
    return f"{PREFIX} > {name} {summary}".strip()


# Tools that can register a brand-new model. After such a call we compare the
# tracked model set and, when a new model appeared, hand the AI a user notice:
# the human has to open/import that model in COMSOL Desktop, otherwise the
# following geometry/physics steps are invisible in the GUI.
_MODEL_CREATING_TOOLS = {
    "model_create",
    "model_create_full",
    "model_create_component",
    "model_load",
    "model_clone",
    "workflow_execute_spec",
    "model_execute_python",
}


def _tracked_models() -> set[str]:
    try:
        return session_manager.tracked_model_names()
    except Exception:
        return set()


def _new_model_notice(before: set[str]) -> str | None:
    """Build the 'model is ready, import it in Desktop' notice, if any."""
    new = sorted(_tracked_models() - before)
    if not new:
        return None
    names = ", ".join(new)
    return (
        f"新模型已就绪：{names}。请现在到 COMSOL Desktop 中导入/打开该模型"
        f"（文件 > 打开，或从服务器打开）再继续后续操作，否则 GUI 里看不到"
        f"几何、物理场、求解的中间过程。"
        f" | RELAY THIS TO THE USER: model '{names}' has been created — ask them "
        f"to open it in COMSOL Desktop before you continue building."
    )


def install_observability(mcp: Any) -> int:
    """Wrap every registered tool with message + call-log instrumentation.

    Returns the number of tools wrapped. Wrapping ``tool.fn`` keeps the schema
    FastMCP already built from the original signature, so nothing about the
    advertised interface changes.
    """
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if not isinstance(tools, dict):
        return 0

    wrapped = 0
    for name, tool in list(tools.items()):
        original = getattr(tool, "fn", None)
        if original is None or getattr(original, "_cosmopilot_wrapped", False):
            continue

        @functools.wraps(original)
        def wrapper(*args, _original=original, _name=name, **kwargs):
            ensure_message()
            ensure_screen()
            if _name not in _QUIET_TOOLS:
                push_comsol_message(_describe(_name, kwargs or (args[0] if args else None)))
            before_models = (_tracked_models() if _name in _MODEL_CREATING_TOOLS else None)
            started = time.perf_counter()
            try:
                result = _original(*args, **kwargs)
            except Exception as exc:
                record_tool_call(_name, kwargs, "error",
                                 (time.perf_counter() - started) * 1000.0, str(exc))
                if _name not in _QUIET_TOOLS:
                    push_comsol_message(f"{PREFIX} < {_name} FAILED: {str(exc)[:120]}")
                raise
            elapsed = (time.perf_counter() - started) * 1000.0
            failed = isinstance(result, dict) and result.get("success") is False
            record_tool_call(_name, kwargs, "failed" if failed else "ok", elapsed,
                             result.get("error") if failed and isinstance(result, dict) else None)
            if before_models is not None and isinstance(result, dict) and not failed:
                notice = _new_model_notice(before_models)
                if notice:
                    result["user_notice"] = notice
                    push_comsol_message(f"{PREFIX}: {notice}")
            if _name not in _QUIET_TOOLS:
                marker = "FAILED" if failed else "done"
                push_comsol_message(f"{PREFIX} < {_name} {marker} ({elapsed:.0f} ms)")
            return result

        wrapper._cosmopilot_wrapped = True  # type: ignore[attr-defined]
        try:
            tool.fn = wrapper
            wrapped += 1
        except Exception:
            continue
    return wrapped


def register_telemetry_tools(mcp: Any) -> None:
    """Expose an explicit narration tool so the AI can label its own steps."""

    @mcp.tool()
    def comsol_say(message: str, model_name: str | None = None) -> dict:
        """
        Print a line into COMSOL's own message log.

        Use this to narrate what you are about to do, so a human watching COMSOL
        Desktop (or the server console) can follow along without reading the chat
        transcript.

        Args:
            message: Short line to display, e.g. 'Building the 0.1 m aluminium cube'
            model_name: Unused; accepted for signature symmetry

        Returns:
            Whether the message reached COMSOL
        """
        text = f"{PREFIX} {message}"
        delivered = push_comsol_message(text)
        return {
            "success": True,
            "delivered_to_comsol": delivered,
            "message": text,
            "note": (
                "Written to the COMSOL message log."
                if delivered
                else "COMSOL session not available; message not delivered."
            ),
        }
