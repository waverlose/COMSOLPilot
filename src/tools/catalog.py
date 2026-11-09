"""Tool catalogue, functional grouping and (in gateway mode) discovery.

With the two-tier surface the client only sees a handful of tools, so this
module becomes the index the assistant uses to find the rest:
``tools_catalog`` lists or searches every tool, ``gateway.tools_describe``
returns one tool's full input schema, and ``gateway.tools_call`` runs it.
"""

from __future__ import annotations

import inspect

from mcp.server.fastmcp import FastMCP


_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    # Exact names come first: they are more specific than the 'comsol_' prefix
    # below and would otherwise be swallowed by the session group.
    ("环境与配置", ("comsol_environment", "comsol_list_versions", "comsol_set_preferences",
                    "comsol_configure_client", "comsol_start_server", "comsol_stop_server",
                    "comsol_open_desktop")),
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


# Keep discovery bilingual without changing tool names or requiring a model.
_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "环境": ("environment", "version"),
    "连接": ("connect", "session"),
    "模型": ("model",),
    "参数": ("parameter",),
    "参数扫描": ("parametric", "sweep"),
    "几何": ("geometry",),
    "长方体": ("block",),
    "圆柱": ("cylinder",),
    "球体": ("sphere",),
    "材料": ("material",),
    "物理场": ("physics",),
    "静电": ("electrostatic",),
    "传热": ("heat", "thermal"),
    "热传导": ("heat", "thermal"),
    "热流": ("heat flux", "heat_flux", "heatflux"),
    "流体": ("flow", "fluid"),
    "层流": ("laminar",),
    "固体": ("solid",),
    "力学": ("mechanic",),
    "边界": ("boundary",),
    "边界条件": ("boundary",),
    "网格": ("mesh",),
    "求解": ("solve", "study"),
    "结果": ("result", "dataset", "solution"),
    "工作流": ("workflow",),
}


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


# Boilerplate that schema_hints prepends to tool.description; it must not become
# the catalogue summary, or every low-level tool would read the same.
_BOILERPLATE = ("Low-level/debug tool.", "Primary AI modeling entry point.")


def tool_text(tool) -> str:
    """A tool's own documentation, without the injected boilerplate.

    The wrapped function's docstring is the reliable source; ``tool.description``
    is only a fallback because schema_hints appends/prepends guidance to it.
    """
    fn = getattr(tool, "fn", None)
    doc = ""
    if fn is not None:
        try:
            doc = inspect.getdoc(fn) or ""
        except Exception:
            doc = ""
    text = doc.strip()
    if not text:
        text = (getattr(tool, "description", "") or "").strip()
    for prefix in _BOILERPLATE:
        if text.startswith(prefix):
            parts = text.split("\n\n", 1)
            text = parts[1].strip() if len(parts) > 1 else ""
            break
    return text


def summarize_tool(tool) -> str:
    """First meaningful line of a tool's documentation, for catalogue listings."""
    for line in tool_text(tool).splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


def _tool_source(mcp: FastMCP) -> dict:
    """Every known tool: the gateway registry when collapsed, else the manager."""
    try:
        from .gateway import known_tools

        return known_tools(mcp)
    except Exception:
        manager = getattr(mcp, "_tool_manager", None)
        return dict(getattr(manager, "_tools", {})) if manager is not None else {}


def _score(name: str, text: str, query: str, category: str) -> int:
    """How well a tool matches; 0 means no match.

    Matching covers the whole description, not just the summary line, so a query
    like 'heat flux' finds a tool whose docstring only mentions flux further in.
    """
    name_lower = name.casefold()
    haystack = f"{name}\n{text}".casefold()
    if category:
        category_lower = category.strip().casefold()
        if category_lower in {"其他", "other"} or any(
                category_lower == label.casefold() for label, _ in _CATEGORIES):
            label = next((label for label, prefixes in _CATEGORIES
                          if name.startswith(prefixes)), "其他")
            if category_lower == "other":
                category_lower = "其他"
            if label.casefold() != category_lower:
                return 0
        elif category_lower not in haystack:
            return 0
    if not query:
        return 1
    score = 0
    for token in query.casefold().split():
        alternatives = (token,) + _QUERY_ALIASES.get(token, ())
        if any(term in name_lower for term in alternatives):
            score += 3
        elif any(term in haystack for term in alternatives):
            score += 1
        else:
            return 0
    return score


def catalog(mcp: FastMCP, query: str = "", category: str = "",
            include_summaries: bool = False) -> dict:
    """List or search every tool. Shared by the tool and the CLI.

    The plain listing returns names only: with 120 tools the summaries alone
    cost several thousand characters, and a name plus tools_describe is enough
    to work with. A search always carries summaries, because that is where they
    earn their keep.
    """
    tools = _tool_source(mcp)
    summaries = {name: summarize_tool(tool) for name, tool in tools.items()}
    texts = {name: tool_text(tool) for name, tool in tools.items()}

    if query or category:
        scored = [(_score(name, texts[name], query, category), name) for name in tools]
        matched = [{"name": name, "summary": summaries[name]}
                   for score, name in sorted(scored, key=lambda item: (-item[0], item[1]))
                   if score > 0]
        return {
            "success": True,
            "tool_count": len(tools),
            "matched": len(matched),
            "query": query,
            "category": category,
            "results": matched,
            "hint": ("Call tools_describe(name) for the full input schema, then "
                     "tools_call(name, arguments)."),
        }

    groups = group_tool_names(sorted(tools))
    if include_summaries:
        for group in groups:
            group["summary"] = {name: summaries[name] for name in group["tools"]}
    return {
        "success": True,
        "tool_count": len(tools),
        "groups": groups,
        "hint": ("Search with tools_catalog(query='热流') or category='几何' (English keywords also work) "
                 "to get a one-line summary of each match; tools_describe(name) then "
                 "gives the exact parameters."),
    }


def register_catalog_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def tools_catalog(query: str = "", category: str = "",
                      include_summaries: bool = False) -> dict:
        """List every COMSOLPilot tool, grouped by area, or search for one by keyword.

        Start here when you are not sure which tool to use. Returns tool names
        with a one-line summary; follow up with tools_describe for the input
        schema and tools_call to run it.

        Args:
            query: Space-separated Chinese or English keywords, e.g. '热流', '圆柱' or 'thermal conduction'; all keywords must match
            category: Chinese group label such as '几何' or '物理场', or English name/description text such as 'geometry' or 'results'
            include_summaries: Attach a one-line summary to every tool in the plain listing (costly: ~10k characters)
        """
        return catalog(mcp, query=query, category=category,
                       include_summaries=include_summaries)
