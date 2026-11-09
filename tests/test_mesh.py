"""Regression tests for mesh settings without a COMSOL installation."""

from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP

from src.tools.mesh import register_mesh_tools, session_manager


def test_mesh_ensure_sets_native_global_size(monkeypatch):
    class Feature:
        def __init__(self, tag):
            self._tag = tag
            self.properties = {}

        def tag(self):
            return self._tag

        def set(self, name, value):
            self.properties[name] = value

    class Mesh:
        def __init__(self):
            self.features = {tag: Feature(tag) for tag in ("size", "ftet1")}
            self.ran = False

        def tag(self):
            return "mesh1"

        def feature(self, tag=None):
            return self.features[tag] if tag else self.features.values()

        def autoMeshSize(self, size):
            pass  # COMSOL 6.0 can leave the global Size node unchanged here.

        def run(self):
            self.ran = True

    mesh = Mesh()
    comp = SimpleNamespace(mesh=lambda: [mesh], tag=lambda: "comp1")
    model = SimpleNamespace(java=SimpleNamespace(component=lambda: [comp]))
    monkeypatch.setattr(session_manager, "get_model", lambda name: model)
    mcp = FastMCP("mesh-test")
    register_mesh_tools(mcp)

    result = mcp._tool_manager.get_tool("mesh_ensure").fn(mesh_size=7)

    assert result["success"] is True
    assert result["mesh_size"] == 7
    assert mesh.features["size"].properties["hauto"] == 7
    assert mesh.ran is True
