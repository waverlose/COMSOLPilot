"""Tool catalogue and functional grouping for COMSOLPilot."""

from mcp.server.fastmcp import FastMCP


_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("会话与模型", ("comsol_", "model_")),
    ("参数", ("parameter_",)),
    ("几何", ("geometry_",)),
    ("材料", ("material_",)),
    ("物理场", ("physics_", "multiphysics_")),
    ("网格", ("mesh_",)),
    ("研究与求解", ("study_", "solver_")),
    ("结果", ("results_", "result_")),
    ("工作流", ("workflow_",)),
    ("代理模型", ("surrogate_",)),
    ("监控", ("telemetry_",)),
]


def group_tool_names(names: list[str]) -> list[dict]:
    """Group tool names deterministically while preserving alphabetical order."""
    remaining = set(names)
    groups = []
    for label, prefixes in _CATEGORIES:
        matched = sorted(name for name in remaining if name.startswith(prefixes))
        if matched:
            groups.append({"id": label, "label": label, "tools": matched, "count": len(matched)})
            remaining.difference_update(matched)
    other = sorted(remaining)
    if other:
        groups.append({"id": "other", "label": "其他", "tools": other, "count": len(other)})
    return groups


def register_catalog_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def tools_catalog() -> dict:
        """List all registered MCP tools grouped by modeling function."""
        names = sorted(mcp._tool_manager._tools.keys())
        groups = group_tool_names(names)
        return {"success": True, "groups": groups, "tool_count": len(names)}
