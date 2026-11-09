"""Bulk initialization validates once and leaves a model ready for small edits."""

from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from src.tools import workflow


def _spec():
    return {
        "model": {"name": "Cube", "dimension": 3},
        "parameters": {"L": "10[mm]"},
        "geometry": [{"type": "block", "tag": "blk1", "position": [0, 0, 0],
                      "size": ["L", "L", "L"]}],
        "mesh": {"size": 7},
    }


def test_parameterized_primitive_is_valid():
    assert workflow.SpecValidator(_spec()).validate()["valid"]


@pytest.mark.parametrize("value", [None, True, "", [], {}])
def test_invalid_parameter_is_rejected_before_execution(monkeypatch, value):
    spec = _spec()
    spec["parameters"]["L"] = value
    mcp = FastMCP("initialization-test")
    workflow.register_workflow_tools(mcp)
    monkeypatch.setattr(workflow.JavaWorkflowExecutor, "run",
                        lambda self: pytest.fail("Invalid spec reached execution"))

    result = mcp._tool_manager.get_tool("workflow_execute_spec").fn(
        spec, solve=False, collect_outputs=False)

    assert result["success"] is False
    assert result["stage"] == "validate"
    assert any("parameters.L" in error for error in result["errors"])


def test_array_displacement_still_requires_numeric_values():
    spec = _spec()
    spec["geometry"].append({"type": "array", "tag": "arr1", "input": ["blk1"],
                             "displacement": ["L", 0, 0]})
    assert not workflow.SpecValidator(spec).validate()["valid"]


def test_bulk_setup_sets_parameters_before_geometry_and_does_not_solve(monkeypatch):
    parameters = {}
    manager = SimpleNamespace(is_connected=True, retry_comsol_busy=lambda fn: fn())
    monkeypatch.setattr(workflow, "session_manager", manager)
    executor = workflow.JavaWorkflowExecutor(_spec(), solve=False, collect_outputs=False)

    def create():
        param = SimpleNamespace(set=lambda name, value: parameters.update({name: value}))
        executor.model = SimpleNamespace(java=SimpleNamespace(param=lambda: param))
        executor.model_name = "Cube"

    def bootstrap():
        assert parameters == {"L": "10[mm]"}
        executor.component = SimpleNamespace(tag=lambda: "comp1")
        executor.geometry = SimpleNamespace(tag=lambda: "geom1")

    monkeypatch.setattr(executor, "_create_model", create)
    monkeypatch.setattr(executor, "_bootstrap", bootstrap)
    for method in ("_geometry_features", "_materials", "_physics", "_multiphysics", "_mesh"):
        monkeypatch.setattr(executor, method, lambda: None)
    monkeypatch.setattr(executor, "_study", lambda: "std1")
    monkeypatch.setattr(executor, "_preflight", lambda: pytest.fail("Solver path was entered"))

    result = executor.run()

    assert result["success"] is True
    assert result["solved"] is False
    assert result["outputs"] == []
    assert {key: result[key] for key in ("model", "component", "geometry", "mesh", "study")} == {
        "model": "Cube", "component": "comp1", "geometry": "geom1",
        "mesh": "mesh1", "study": "std1"}


def test_failed_setup_returns_partial_model_for_small_tool_repair(monkeypatch):
    monkeypatch.setattr(workflow, "session_manager", SimpleNamespace(is_connected=True))
    executor = workflow.JavaWorkflowExecutor(_spec(), solve=False, collect_outputs=False)
    monkeypatch.setattr(executor, "_create_model", lambda: setattr(executor, "model_name", "Cube"))
    def fail_parameters():
        raise ValueError("bad expression")
    monkeypatch.setattr(executor, "_parameters", fail_parameters)

    result = executor.run()

    assert result["success"] is False
    assert result["model"] == "Cube"
    assert result["error"] == "bad expression"


@pytest.mark.parametrize("dimension,feature_type", [(2, "FreeTri"), (3, "FreeTet")])
@pytest.mark.parametrize("run", [False, True])
def test_bulk_mesh_has_real_elements_and_explicit_native_size(monkeypatch, dimension, feature_type, run):
    import jpype

    class JavaInt(int):
        pass

    monkeypatch.setattr(jpype, "JInt", JavaInt)
    monkeypatch.setattr(workflow, "session_manager",
                        SimpleNamespace(retry_comsol_busy=lambda fn: fn()))
    sizes = {}

    def set_size(name, value):
        assert isinstance(value, JavaInt)
        sizes[name] = value

    features = {"size": SimpleNamespace(tag=lambda: "size", set=set_size)}
    created = []
    ran = []

    def create(tag, kind):
        features[tag] = SimpleNamespace(tag=lambda: tag)
        created.append(kind)

    mesh = SimpleNamespace(
        tag=lambda: "mesh1", feature=lambda tag=None: features[tag] if tag else features.values(),
        create=create, run=lambda: ran.append(True),
        stat=lambda: SimpleNamespace(getNumElem=lambda: 100))
    spec = _spec()
    spec["model"]["dimension"] = dimension
    spec["mesh"]["run"] = run
    executor = workflow.JavaWorkflowExecutor(spec, solve=False, collect_outputs=False)
    executor.component = SimpleNamespace(mesh=lambda: [mesh])

    executor._mesh()

    assert created == [feature_type]
    assert sizes["hauto"] == 7
    assert bool(ran) == run
    assert executor.log[-1]["ran"] == run
    assert executor.log[-1].get("elements") == (100 if run else None)
