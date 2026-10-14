"""Tests for the conversation-driven setup / configuration tools.

These exercise the pure logic (preference validation, client config planning,
environment reporting) without starting COMSOL, so they run anywhere.
"""

import pytest


@pytest.fixture()
def isolated_workspace(tmp_path, monkeypatch):
    """Point config.toml and workspace/settings.json at a temporary directory."""
    from src import config as config_module
    from src.tools import session as session_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(session_module, "workspace_dir", lambda: workspace)
    monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "settings_path",
                        lambda: workspace / "settings.json")
    return workspace


class TestPreferences:
    def test_rejects_bad_port(self, isolated_workspace):
        from src.tools.admin import set_preferences

        result = set_preferences(port=80)
        assert result["success"] is False
        assert any("1024" in problem for problem in result["errors"])

    def test_rejects_bad_mode_and_login_mode(self, isolated_workspace):
        from src.tools.admin import set_preferences

        assert set_preferences(mode="sideways")["success"] is False
        assert set_preferences(login_mode="sometimes")["success"] is False

    def test_persists_valid_preferences(self, isolated_workspace):
        from src import config as config_module
        from src.tools.admin import set_preferences

        result = set_preferences(port=2041, mode="headless", login_mode="never",
                                 autostart=False)
        assert result["success"] is True
        assert result["updated"]["port"] == 2041

        saved = config_module.load()
        assert saved["comsol"]["port"] == 2041
        assert saved["comsol"]["mode"] == "headless"
        assert saved["comsol"]["login_mode"] == "never"
        assert saved["connector"]["autostart"] is False

    def test_keeps_other_settings(self, isolated_workspace):
        from src import config as config_module
        from src.tools.admin import set_preferences

        set_preferences(port=2042, table_label="Pilot")
        set_preferences(mode="gui")

        saved = config_module.load()
        assert saved["comsol"]["port"] == 2042
        assert saved["ui"]["table_label"] == "Pilot"
        assert saved["comsol"]["mode"] == "gui"


class TestConfigWriter:
    def test_update_preserves_comments_and_untouched_keys(self, isolated_workspace):
        from src import config as config_module

        path = config_module.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# keep this header\n[comsol]\nport = 2036  # the port\n"
                        'version = "6.2"\n', encoding="utf-8")

        config_module.update({"comsol": {"port": 2100}})
        text = path.read_text(encoding="utf-8")

        assert "# keep this header" in text
        assert "# the port" in text
        assert "port = 2100" in text
        assert config_module.load()["comsol"]["version"] == "6.2"

    def test_update_creates_a_missing_section(self, isolated_workspace):
        from src import config as config_module

        config_module.update({"connector": {"autostart": True}})
        assert config_module.load()["connector"]["autostart"] is True


class TestClientConfig:
    def test_unknown_client_is_rejected(self):
        from src.tools.admin import configure_clients

        result = configure_clients(clients=["not-a-client"])
        assert result["success"] is False
        assert "valid_keys" in result

    def test_dry_run_plans_without_writing(self):
        from src.tools.admin import configure_clients

        result = configure_clients(clients=["claude-code"], ensure=True, dry_run=True)
        assert result["success"] is True
        assert result["dry_run"] is True
        # Nothing should ever be written on a dry run.
        assert all(item.get("written") is not True for item in result["results"])


class TestEnvironment:
    def test_environment_report_shape(self, isolated_workspace):
        from src.tools.admin import environment_report

        report = environment_report()
        assert report["success"] is True
        for key in ("runtime", "packages", "comsol", "server", "settings", "clients"):
            assert key in report
        assert "mph" in report["packages"]

    def test_list_versions_shape(self):
        from src.tools.admin import _installed_versions

        versions = _installed_versions()
        assert isinstance(versions, list)
        for item in versions:
            assert {"name", "server", "desktop"} == set(item)


class TestAutoStartDefault:
    def test_autostart_is_off_by_default(self, isolated_workspace, monkeypatch):
        """Opening an AI client must not launch COMSOL on its own."""
        from src.tools.session import _autostart_enabled

        monkeypatch.delenv("COMSOL_AUTOSTART", raising=False)
        assert _autostart_enabled() is False

    def test_autostart_can_be_turned_on(self, isolated_workspace, monkeypatch):
        from src import config as config_module
        from src.tools.session import _autostart_enabled

        monkeypatch.delenv("COMSOL_AUTOSTART", raising=False)
        config_module.update({"connector": {"autostart": True}})
        assert _autostart_enabled() is True

        monkeypatch.setenv("COMSOL_AUTOSTART", "on")
        assert _autostart_enabled() is True


class TestCatalogGrouping:
    def test_admin_tools_are_grouped_separately(self):
        from src.tools.catalog import group_tool_names

        names = ["comsol_start", "comsol_start_server", "comsol_environment",
                 "comsol_stop_server", "model_list"]
        groups = {group["id"]: group["tools"] for group in group_tool_names(names)}
        assert "comsol_start_server" in groups["环境与配置"]
        assert "comsol_environment" in groups["环境与配置"]
        # The session tool must not be swallowed by the admin group.
        assert "comsol_start" in groups["会话与模型"]


class TestRegistration:
    def test_admin_tools_registered_with_descriptions(self):
        from mcp.server.fastmcp import FastMCP
        from src.tools.admin import register_admin_tools
        from src.tools.schema_hints import apply_schema_hints

        mcp = FastMCP("admin-test")
        register_admin_tools(mcp)
        apply_schema_hints(mcp)

        names = {tool.name for tool in mcp._tool_manager.list_tools()}
        assert {"comsol_environment", "comsol_list_versions", "comsol_set_preferences",
                "comsol_configure_client", "comsol_start_server", "comsol_stop_server",
                "comsol_open_desktop"}.issubset(names)

        missing = []
        for tool in mcp._tool_manager.list_tools():
            for prop_name, prop in tool.parameters.get("properties", {}).items():
                if "description" not in prop:
                    missing.append((tool.name, prop_name))
        assert missing == []


class TestStartRefusesExistingServer:
    """A server already on the port is not "started" - and must never look like it.

    This is the hot-swap bug: with the old server still listening,
    _launch_server_process's wait loop found the port open and reported success
    for the *old* process, so a version change appeared to apply while nothing
    but the runtime record changed.
    """

    def test_start_refuses_when_the_port_is_already_listening(
            self, isolated_workspace, monkeypatch):
        from src.tools import session as session_module

        monkeypatch.setattr(session_module, "port_listening", lambda *a, **k: True)
        monkeypatch.setattr(session_module, "server_exe",
                            lambda version=None: "C:/fake/comsolmphserver.exe")

        result = session_module._launch_server_process(port=2036, version="6.2")

        assert result["success"] is False
        assert result["already_listening"] is True
        assert result["port"] == 2036
        assert "stop" in result["error"].lower()

    def test_the_refusal_names_the_version_that_is_running(
            self, isolated_workspace, monkeypatch):
        from src.tools import session as session_module

        (isolated_workspace / "runtime.json").write_text(
            '{"port": 2036, "comsol_version": "6.0"}', encoding="utf-8")
        monkeypatch.setattr(session_module, "port_listening", lambda *a, **k: True)
        monkeypatch.setattr(session_module, "server_exe",
                            lambda version=None: "C:/fake/comsolmphserver.exe")

        result = session_module._launch_server_process(port=2036)

        assert result["running_version"] == "6.0"

    def test_start_proceeds_when_the_port_is_free(self, isolated_workspace, monkeypatch):
        from src.tools import session as session_module

        # Nothing listens, discovery finds nothing bindable to launch against -
        # the point is only that the pre-check does not fire.
        monkeypatch.setattr(session_module, "port_listening", lambda *a, **k: False)
        monkeypatch.setattr(session_module, "server_exe",
                            lambda version=None: "C:/fake/comsolmphserver.exe")
        monkeypatch.setattr(session_module, "port_bindable", lambda port: False)
        monkeypatch.setattr(session_module, "_first_free_port", lambda start: None)

        result = session_module._launch_server_process(port=2036)

        assert result["success"] is False
        assert "already_listening" not in result
