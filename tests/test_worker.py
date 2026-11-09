"""Demand-start lifecycle tests using real isolated processes, without COMSOL."""

import os
import pickle
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


def test_native_results_are_serialized_before_crossing_the_process_pipe():
    from src.worker import _ipc_result

    class NativeString:
        def __str__(self):
            return "mesh1"

        def __reduce__(self):
            raise TypeError("Native Java objects cannot be pickled")

    result = {"mesh": NativeString(), "stats": {"elements": 12}, "built": True}
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(result)
    safe = _ipc_result(result)
    assert safe == {"mesh": "mesh1", "stats": {"elements": 12}, "built": True}
    assert pickle.loads(pickle.dumps(safe)) == safe


def test_direct_workflow_keeps_request_context_out_of_worker_ipc():
    import asyncio
    from types import SimpleNamespace
    from mcp.server.fastmcp import Context, FastMCP
    from src.worker import install_worker_dispatch

    class RequestContext:
        def __reduce__(self):
            raise TypeError("Request context cannot cross process boundaries")

    def call(name, arguments):
        assert name == "workflow_execute_spec"
        assert pickle.loads(pickle.dumps(arguments)) == {"spec": {}}
        return {"success": True}

    mcp = FastMCP("direct-context-test")

    @mcp.tool()
    def workflow_execute_spec(spec: dict, context: Context | None = None) -> dict:
        raise AssertionError("Native workflow executed in the MCP process")

    install_worker_dispatch(mcp, SimpleNamespace(handles=lambda name: True, call=call))
    tool = mcp._tool_manager.get_tool("workflow_execute_spec")
    assert asyncio.run(tool.run({"spec": {}}, context=RequestContext())) == {"success": True}


def simulated_worker(connection, options):
    """Exercise the same pipe protocol as the native worker."""
    connection.send({"type": "progress", "stage": "starting_comsol", "message": "Starting test COMSOL"})
    if options.get("version") == "slow":
        time.sleep(10)
    if options.get("version") == "fail":
        connection.send({"type": "failed", "error": "Test license unavailable"})
        connection.close()
        return
    connection.send({"type": "ready", "status": {"connected": True, "version": "test", "models": []}})
    count = 0
    while True:
        request = connection.recv()
        if request["kind"] == "shutdown":
            break
        name = request["name"]
        if name == "model_crash":
            os._exit(7)
        if name == "model_slow":
            time.sleep(0.3)
        count += 1
        result = ("# Worker model tree" if request["kind"] == "resource" else
                  {"success": True, "count": count, "worker_pid": os.getpid(), "options": options})
        connection.send({"type": "result", "id": request["id"], "result": result,
                         "status": {"connected": True, "version": "test", "models": [{"name": "test"}]}})
    connection.close()


@pytest.fixture
def worker():
    from src.worker import ComsolWorker

    instance = ComsolWorker(target=simulated_worker, call_timeout=2)
    yield instance
    instance.close()


def wait_for(worker, state, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = worker.status()
        if snapshot["state"] == state:
            return snapshot
        time.sleep(0.02)
    pytest.fail(f"Worker did not reach {state}: {worker.status()}")


def ready(worker):
    worker.start()
    return wait_for(worker, "ready")


def test_status_does_not_start_comsol(worker):
    assert worker.status()["state"] == "idle"
    assert worker.status()["connected"] is False
    assert worker.process is None


def test_first_model_request_only_starts_worker(worker):
    result = worker.call("model_create", {"name": "one"})
    assert result["code"] == "comsol_starting"
    assert result["executed"] is False
    assert result["retryable"] is True
    ready_state = wait_for(worker, "ready")
    assert ready_state["connected"] is True
    assert "last_operation" not in ready_state
    assert worker.call("model_create", {"name": "one"})["count"] == 1


def test_ready_worker_is_reused(worker):
    ready(worker)
    first = worker.call("model_create", {})
    second = worker.call("model_list", {})
    assert first["worker_pid"] == second["worker_pid"]
    assert second["count"] == 2


def test_concurrent_starts_share_one_process(worker):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: worker.start(), range(12)))
    process = worker.process
    wait_for(worker, "ready")
    assert worker.process is process


def test_boot_failure_is_reported_without_an_automatic_retry(worker):
    worker.start({"version": "fail"})
    failed = wait_for(worker, "failed")
    assert "license" in failed["error"]
    process = worker.process
    result = worker.call("model_create", {})
    assert result["success"] is False
    assert result["executed"] is False
    assert worker.process is process
    worker.start({"version": "ok"})
    wait_for(worker, "ready")
    assert worker.process is not process


def test_worker_crash_does_not_replay_the_operation(worker):
    ready(worker)
    result = worker.call("model_crash", {})
    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert result["retryable"] is False
    assert worker.status()["state"] == "failed"


def test_long_operation_can_be_queried_without_repeating_it(worker):
    ready(worker)
    worker.call_timeout = 0.02
    result = worker.call("model_slow", {})
    assert result["code"] == "operation_in_progress"
    assert result["retryable"] is False
    busy = worker.status()
    assert busy["state"] == "busy"
    assert busy["operation"]["id"] == result["request_id"]
    completed = wait_for(worker, "ready")
    assert completed["last_operation"]["result"]["count"] == 1
    assert completed["last_operation"]["id"] == result["request_id"]


def test_busy_worker_does_not_queue_an_extra_mutation(worker):
    ready(worker)
    worker.call_timeout = 0.02
    worker.call("model_slow", {})
    result = worker.call("model_create", {})
    assert result["code"] == "worker_busy"
    assert result["executed"] is False
    assert wait_for(worker, "ready")["last_operation"]["result"]["count"] == 1


def test_startup_timeout_stops_only_the_worker():
    from src.worker import ComsolWorker

    instance = ComsolWorker(target=simulated_worker, startup_timeout=0.1)
    try:
        instance.start({"version": "slow"})
        time.sleep(0.15)
        result = instance.status()
        assert result["state"] == "failed"
        assert "timed out" in result["error"]
        assert not instance.process.is_alive()
    finally:
        instance.close()


def test_idle_resource_does_not_start_worker(worker):
    assert "No active COMSOL" in worker.read_resource("tree", "one")
    assert worker.process is None


def test_model_resources_are_read_in_the_same_worker(worker):
    ready(worker)
    assert worker.read_resource("tree", "one") == "# Worker model tree"


def test_stop_during_boot_terminates_worker_before_stopping_comsol(worker, monkeypatch):
    from src.tools import admin

    worker.start({"version": "slow"})
    process = worker.process
    def stopped():
        assert not process.is_alive()
        return {"success": True, "stopped": True}
    monkeypatch.setattr(admin, "stop_server", stopped)
    assert worker.call("comsol_stop_server", {})["success"] is True
    assert worker.status()["state"] == "idle"


def test_disconnect_allows_a_fresh_session(worker):
    ready(worker)
    old_process = worker.process
    assert worker.call("comsol_disconnect", {})["success"] is True
    assert not old_process.is_alive()
    assert worker.status()["state"] == "idle"
    assert worker.call("model_create", {})["code"] == "comsol_starting"
    wait_for(worker, "ready")
    assert worker.process is not old_process


def front_server(worker):
    from mcp.server.fastmcp import FastMCP
    from src.tools.catalog import register_catalog_tools
    from src.tools.gateway import register_gateway_tools, collapse_to_gateway
    from src.worker import install_worker_dispatch

    mcp = FastMCP("worker-front-test")
    @mcp.tool()
    def model_create(name: str) -> dict:
        raise AssertionError("Native tool executed in MCP process")
    @mcp.tool()
    def model_slow() -> dict:
        raise AssertionError("Native tool executed in MCP process")
    @mcp.tool()
    def comsol_status() -> dict:
        raise AssertionError("Native status executed in MCP process")
    register_catalog_tools(mcp)
    register_gateway_tools(mcp)
    install_worker_dispatch(mcp, worker)
    collapse_to_gateway(mcp)
    return mcp


@pytest.fixture
def isolated_gateway(monkeypatch):
    from src.tools import gateway
    monkeypatch.setattr(gateway, "_REGISTRY", {})
    monkeypatch.delenv("COMSOLPILOT_TOOL_TIER", raising=False)
    monkeypatch.delenv("COMSOLPILOT_TOP_LEVEL_TOOLS", raising=False)


def test_gateway_validates_before_starting_worker(worker, isolated_gateway):
    from src.tools.gateway import call_tool
    mcp = front_server(worker)
    result = call_tool(mcp, "model_create", {"nmae": "wrong"})
    assert result["code"] == "invalid_arguments"
    assert worker.process is None


def test_gateway_runs_native_tool_in_worker(worker, isolated_gateway):
    import asyncio
    mcp = front_server(worker)
    tool = mcp._tool_manager.get_tool("tools_call")
    first = asyncio.run(tool.run({"name": "model_create", "arguments": {"name": "one"}}))
    assert first["executed"] is False
    wait_for(worker, "ready")
    result = asyncio.run(tool.run({"name": "model_create", "arguments": {"name": "one"}}))
    assert result["count"] == 1


def test_flat_tool_surface_uses_the_same_worker(worker, isolated_gateway, monkeypatch):
    import asyncio
    monkeypatch.setenv("COMSOLPILOT_TOOL_TIER", "flat")
    mcp = front_server(worker)
    ready(worker)
    result = asyncio.run(mcp._tool_manager.get_tool("model_create").run({"name": "one"}))
    assert result["worker_pid"] == worker.process.pid


def test_mcp_status_remains_responsive_during_native_work(worker, isolated_gateway):
    import asyncio
    mcp = front_server(worker)
    tool = mcp._tool_manager.get_tool("tools_call")
    ready(worker)
    async def run():
        operation = asyncio.create_task(tool.run({"name": "model_slow", "arguments": {}}))
        for _ in range(100):
            if worker.status()["state"] == "busy":
                break
            await asyncio.sleep(0.005)
        status = await tool.run({"name": "comsol_status", "arguments": {}})
        assert status["state"] == "busy"
        assert not operation.done()
        assert (await operation)["success"] is True
    asyncio.run(run())


def test_async_solve_status_does_not_probe_the_busy_server(monkeypatch):
    from types import SimpleNamespace
    from src.async_handler import solver
    from src.worker import _session_status
    def no_rpc():
        raise AssertionError("Busy COMSOL server was queried")
    manager = SimpleNamespace(client=object(), get_status=no_rpc)
    monkeypatch.setattr(solver, "async_solver", SimpleNamespace(
        is_running=True, get_progress=lambda: {"status": "running", "progress": 0.5}))
    result = _session_status(manager)
    assert result["connected"] is True and result["solving"] is True
    assert result["solver"]["progress"] == 0.5
