"""Tests for the two-tier tool surface (gateway)."""

import pytest
from mcp.server.fastmcp import FastMCP


@pytest.fixture(autouse=True)
def clean_gateway(monkeypatch):
    """Reset the global registry and tier setting around each test."""
    from src.tools import gateway

    monkeypatch.delenv("COMSOLPILOT_TOOL_TIER", raising=False)
    monkeypatch.delenv("COMSOLPILOT_TOP_LEVEL_TOOLS", raising=False)
    gateway._REGISTRY.clear()
    yield
    gateway._REGISTRY.clear()


def _server() -> FastMCP:
    from src.tools.catalog import register_catalog_tools
    from src.tools.gateway import register_gateway_tools

    mcp = FastMCP("gateway-test")

    @mcp.tool()
    def widget_add(size: int = 1, label: str = "w") -> dict:
        """Add a widget.

        Args:
            size: Widget size
            label: Widget label
        """
        return {"success": True, "size": size, "label": label}

    @mcp.tool()
    def widget_remove(name: str) -> dict:
        """Remove a widget.

        Args:
            name: Widget name
        """
        return {"success": True, "removed": name}

    register_catalog_tools(mcp)
    register_gateway_tools(mcp)
    return mcp


def _top_level(mcp) -> set:
    return {tool.name for tool in mcp._tool_manager.list_tools()}


class TestCollapse:
    def test_collapses_to_gateways(self):
        from src.tools.gateway import collapse_to_gateway

        mcp = _server()
        assert {"widget_add", "widget_remove"} <= _top_level(mcp)

        result = collapse_to_gateway(mcp)

        assert result["enabled"] is True
        assert result["demoted"] == 2
        assert _top_level(mcp) == {"tools_catalog", "tools_describe", "tools_call"}

    def test_flat_mode_keeps_everything(self, monkeypatch):
        from src.tools.gateway import collapse_to_gateway

        monkeypatch.setenv("COMSOLPILOT_TOOL_TIER", "flat")
        mcp = _server()
        result = collapse_to_gateway(mcp)

        assert result["enabled"] is False
        assert {"widget_add", "widget_remove"} <= _top_level(mcp)

    def test_top_level_pin_keeps_a_tool_visible(self, monkeypatch):
        from src.tools.gateway import collapse_to_gateway

        monkeypatch.setenv("COMSOLPILOT_TOP_LEVEL_TOOLS", "widget_add")
        mcp = _server()
        collapse_to_gateway(mcp)

        assert "widget_add" in _top_level(mcp)
        assert "widget_remove" not in _top_level(mcp)


class TestDispatch:
    def test_call_runs_the_tool(self):
        from src.tools.gateway import call_tool, collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)

        assert call_tool(mcp, "widget_add", {"size": 3, "label": "big"}) == {
            "success": True, "size": 3, "label": "big"}

    def test_call_defaults_apply_when_arguments_omitted(self):
        from src.tools.gateway import call_tool, collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)

        assert call_tool(mcp, "widget_add")["size"] == 1

    def test_call_accepts_json_string_arguments(self):
        from src.tools.gateway import call_tool, collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)

        assert call_tool(mcp, "widget_add", '{"size": 9}')["size"] == 9

    def test_unknown_tool_suggests_a_name(self):
        from src.tools.gateway import call_tool, collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)

        result = call_tool(mcp, "widget_ad")
        assert result["success"] is False
        assert "widget_add" in result["did_you_mean"]

    def test_unknown_parameter_is_reported(self):
        from src.tools.gateway import call_tool, collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)

        result = call_tool(mcp, "widget_add", {"size": 1, "colour": "red"})
        assert result["success"] is False
        assert "colour" in result["error"]
        assert "size" in result["valid_parameters"]

    def test_missing_required_parameter_is_reported(self):
        from src.tools.gateway import call_tool, collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)

        result = call_tool(mcp, "widget_remove", {})
        assert result["success"] is False
        assert "name" in result["error"]

    def test_gateway_tools_are_not_callable_through_the_gateway(self):
        from src.tools.gateway import call_tool, collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)

        assert call_tool(mcp, "tools_call", {})["success"] is False


class TestDescribeAndCatalog:
    def test_describe_returns_schema(self):
        from src.tools.gateway import collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)
        describe = mcp._tool_manager.get_tool("tools_describe").fn

        result = describe("widget_add")
        assert result["success"] is True
        assert "size" in result["parameters"]["properties"]

    def test_catalog_lists_demoted_tools(self):
        from src.tools.gateway import collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)
        catalog = mcp._tool_manager.get_tool("tools_catalog").fn

        names = set()
        for group in catalog()["groups"]:
            names.update(group["tools"])
        assert {"widget_add", "widget_remove"} <= names

    def test_catalog_search_filters(self):
        from src.tools.gateway import collapse_to_gateway

        mcp = _server()
        collapse_to_gateway(mcp)
        catalog = mcp._tool_manager.get_tool("tools_catalog").fn

        result = catalog(query="remove")
        assert [item["name"] for item in result["results"]] == ["widget_remove"]
