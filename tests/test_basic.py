"""Basic tests for COMSOL MCP Server."""

import pytest


@pytest.fixture(autouse=True)
def reset_session_manager():
    from src.tools.session import SessionManager

    sm = SessionManager()
    sm._client = None
    sm._server = None
    sm._models.clear()
    sm._current_model = None
    yield
    sm._client = None
    sm._server = None
    sm._models.clear()
    sm._current_model = None


class TestVersioning:
    """Tests for version naming utilities."""
    
    def test_generate_version_name(self):
        from src.utils.versioning import generate_version_name
        
        result = generate_version_name("model.mph")
        assert result.startswith("model_")
        assert result.endswith(".mph")
        assert len(result) > len("model.mph")
    
    def test_generate_version_name_no_extension(self):
        from src.utils.versioning import generate_version_name
        
        result = generate_version_name("model")
        assert result.startswith("model_")
        assert result.endswith(".mph")
    
    def test_generate_version_path(self):
        from pathlib import Path
        from src.utils.versioning import generate_version_path
        
        result = generate_version_path("/path/to/model.mph")
        path = Path(result)
        assert path.name.startswith("model_")
        assert path.suffix == ".mph"
    
    def test_parse_version_info_valid(self):
        from src.utils.versioning import parse_version_info
        
        result = parse_version_info("model_20260215_143022.mph")
        assert result is not None
        assert result["base_name"] == "model"
        assert result["timestamp"] == "20260215_143022"
    
    def test_parse_version_info_invalid(self):
        from src.utils.versioning import parse_version_info
        
        result = parse_version_info("model.mph")
        assert result is None
        
        result = parse_version_info("model_20260215.mph")
        assert result is None


class TestSessionManager:
    """Tests for session manager (without actual COMSOL)."""

    class FakeClient:
        version = "test-version"
        cores = 1
        standalone = False

        def __init__(self):
            self.cleared = False

        def models(self):
            return []

        def names(self):
            return []

        def clear(self):
            self.cleared = True

    class FakeServer:
        port = 2036

        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True
    
    def test_session_manager_singleton(self):
        from src.tools.session import SessionManager
        
        sm1 = SessionManager()
        sm2 = SessionManager()
        assert sm1 is sm2
    
    def test_session_manager_initial_state(self):
        from src.tools.session import SessionManager
        
        sm = SessionManager()
        assert sm.client is None
        assert not sm.is_connected
        assert sm.current_model is None
        assert sm.models == {}
    
    def test_get_status_disconnected(self):
        from src.tools.session import SessionManager
        
        sm = SessionManager()
        status = sm.get_status()
        assert status["connected"] is False

    def test_start_requires_user_mode_choice_by_default(self):
        from src.tools.session import SessionManager

        sm = SessionManager()

        result = sm.start()

        assert result["success"] is False
        assert result["choice_required"] is True
        assert [choice["mode"] for choice in result["choices"]] == ["gui", "headless"]
        assert sm.client is None

    def test_gui_mode_requires_user_started_server_by_default(self, monkeypatch):
        from src.tools.session import SessionManager

        sm = SessionManager()
        monkeypatch.setattr(sm, "_server_is_listening", lambda host, port, timeout=1.0: False)

        result = sm.start(mode="gui", port=2036)

        assert result["success"] is False
        assert result["mode"] == "gui"
        assert result["port"] == 2036
        assert "start_comsol_server.bat" in result["error"]
        assert sm.client is None

    def test_gui_mode_autostart_is_explicit_opt_in(self, monkeypatch):
        from src.tools import session as session_module
        from src.tools.session import SessionManager

        sm = SessionManager()
        server = self.FakeServer()
        client = self.FakeClient()
        monkeypatch.setattr(session_module, "_ensure_windows_architecture_fallback", lambda: None)
        monkeypatch.setattr(sm, "_server_is_listening", lambda host, port, timeout=1.0: False)
        monkeypatch.setattr(session_module.mph, "Server", lambda cores=None, version=None, port=2036, multi="on": server)
        monkeypatch.setattr(session_module.mph, "Client", lambda port=2036, host="localhost": client)

        result = sm.start(mode="gui", port=2036, autostart_server=True)

        assert result["success"] is True
        assert result["mode"] == "gui"
        assert result["port"] == 2036
        assert result["connected_to"] == "new_server"
        assert sm.client is client
        assert sm._server is server

    def test_auto_mode_falls_back_to_headless_when_fixed_port_is_closed(self, monkeypatch):
        from src.tools import session as session_module
        from src.tools.session import SessionManager

        sm = SessionManager()
        client = self.FakeClient()
        client.standalone = True

        monkeypatch.setattr(session_module, "_ensure_windows_architecture_fallback", lambda: None)
        monkeypatch.setattr(sm, "_server_is_listening", lambda host, port, timeout=1.0: False)
        monkeypatch.setattr(session_module.mph, "start", lambda cores=None, version=None: client)

        result = sm.start(mode="auto", port=2036)

        assert result["success"] is True
        assert result["connected_to"] == "standalone_jvm"
        assert result["mode"] == "headless"
        assert sm.client is client

    def test_disconnect_releases_client_reference(self):
        from src.tools.session import SessionManager

        sm = SessionManager()
        client = self.FakeClient()
        server = self.FakeServer()
        sm.bind_client(client)
        sm._server = server

        result = sm.disconnect()

        assert result["success"] is True
        assert client.cleared is True
        assert server.stopped is True
        assert sm.client is None
        assert sm._server is None


class TestToolSchemas:
    """Tests for MCP input schemas."""
    
    def test_tool_properties_have_descriptions_and_key_enums(self):
        from mcp.server.fastmcp import FastMCP
        from src.tools.geometry import register_geometry_tools
        from src.tools.materials import register_material_tools
        from src.tools.mesh import register_mesh_tools
        from src.tools.model import register_model_tools
        from src.tools.parameters import register_parameter_tools
        from src.tools.physics import register_physics_tools
        from src.tools.results import register_results_tools
        from src.tools.schema_hints import apply_schema_hints
        from src.tools.session import register_session_tools
        from src.tools.study import register_study_tools
        from src.tools.workflow import register_workflow_tools
        
        mcp = FastMCP("schema-test")
        register_session_tools(mcp)
        register_model_tools(mcp)
        register_parameter_tools(mcp)
        register_geometry_tools(mcp)
        register_material_tools(mcp)
        register_physics_tools(mcp)
        register_mesh_tools(mcp)
        register_study_tools(mcp)
        register_results_tools(mcp)
        register_workflow_tools(mcp)
        apply_schema_hints(mcp)
        
        missing = []
        for tool in mcp._tool_manager.list_tools():
            for name, prop in tool.parameters.get("properties", {}).items():
                if "description" not in prop:
                    missing.append((tool.name, name))
        
        assert missing == []
        physics_schema = mcp._tool_manager.get_tool("physics_add").parameters["properties"]["physics_type"]
        assert "HeatTransfer" in physics_schema["enum"]
        boundary_schema = mcp._tool_manager.get_tool("physics_boundary_selection").parameters["properties"]["boundary_condition_type"]
        assert "ConvectiveHeatFlux" in boundary_schema["enum"]
        mode_schema = mcp._tool_manager.get_tool("comsol_start").parameters["properties"]["mode"]
        assert mode_schema["enum"] == ["ask", "gui", "headless", "auto"]
        advanced_schema = mcp._tool_manager.get_tool("model_execute_python").parameters["properties"]
        assert "script" in advanced_schema
        assert advanced_schema["confirm"]["description"].startswith("Must be exactly EXECUTE_COMSOL_PYTHON")
        start_schema = mcp._tool_manager.get_tool("comsol_start").parameters["properties"]
        assert "start_comsol_server.bat" in start_schema["autostart_server"]["description"]
        feature_schema = mcp._tool_manager.get_tool("geometry_add_feature").parameters["properties"]
        assert {"properties", "selections", "build"}.issubset(feature_schema)
        assert "kwargs" not in feature_schema
