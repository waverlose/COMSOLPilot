"""Tool discovery in Chinese and English, without a COMSOL connection."""

import pytest
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def discovery_server(monkeypatch):
    from src.tools import gateway

    monkeypatch.setattr(gateway, "_REGISTRY", {})
    monkeypatch.delenv("COMSOLPILOT_TOOL_TIER", raising=False)
    monkeypatch.delenv("COMSOLPILOT_TOP_LEVEL_TOOLS", raising=False)
    mcp = FastMCP("catalog-test")

    @mcp.tool()
    def geometry_add_block() -> dict:
        """Add a rectangular block to the geometry."""
        return {}

    @mcp.tool()
    def geometry_add_cylinder() -> dict:
        """Add a cylinder to the geometry."""
        return {}

    @mcp.tool()
    def physics_add_heat_transfer() -> dict:
        """Add heat transfer physics to the existing geometry."""
        return {}

    @mcp.tool()
    def physics_set_heat_boundary() -> dict:
        """Set a heat flux boundary condition for heat transfer."""
        return {}

    @mcp.tool()
    def custom_operation() -> dict:
        """自定义功能。"""
        return {}

    return mcp


@pytest.mark.parametrize("query, expected", [
    ("几何", ["geometry_add_block", "geometry_add_cylinder", "physics_add_heat_transfer"]),
    ("长方体", ["geometry_add_block"]),
    ("圆柱", ["geometry_add_cylinder"]),
    ("热传导 boundary", ["physics_set_heat_boundary"]),
    ("热流", ["physics_set_heat_boundary"]),
    ("heat boundary", ["physics_set_heat_boundary"]),
    ("自定义", ["custom_operation"]),
])
def test_keyword_search(discovery_server, query, expected):
    from src.tools.catalog import catalog

    result = catalog(discovery_server, query=query)
    assert [item["name"] for item in result["results"]] == expected


def test_chinese_category_filters_by_group(discovery_server):
    from src.tools.catalog import catalog

    result = catalog(discovery_server, category="几何")
    assert [item["name"] for item in result["results"]] == [
        "geometry_add_block", "geometry_add_cylinder"]


def test_chinese_category_combines_with_chinese_query(discovery_server):
    from src.tools.catalog import catalog

    result = catalog(discovery_server, category="物理场", query="热流")
    assert [item["name"] for item in result["results"]] == ["physics_set_heat_boundary"]


def test_search_uses_all_keywords(discovery_server):
    from src.tools.catalog import catalog

    assert catalog(discovery_server, query="圆柱 heat")["matched"] == 0


def test_chinese_search_works_after_gateway_collapse(discovery_server):
    from src.tools.catalog import catalog
    from src.tools.gateway import collapse_to_gateway

    collapse_to_gateway(discovery_server)
    result = catalog(discovery_server, query="圆柱")
    assert [item["name"] for item in result["results"]] == ["geometry_add_cylinder"]


@pytest.mark.parametrize("category", ["其他", "other"])
def test_other_category_matches_the_listing(discovery_server, category):
    from src.tools.catalog import catalog

    result = catalog(discovery_server, category=category)
    assert [item["name"] for item in result["results"]] == ["custom_operation"]


def test_session_category_excludes_environment_tools(discovery_server):
    from src.tools.catalog import catalog

    @discovery_server.tool()
    def comsol_start_server() -> dict:
        """Start the local server."""
        return {}

    @discovery_server.tool()
    def comsol_status() -> dict:
        """Return the session status."""
        return {}

    result = catalog(discovery_server, category="会话与模型")
    assert [item["name"] for item in result["results"]] == ["comsol_status"]
