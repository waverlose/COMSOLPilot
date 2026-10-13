"""Two-tier tool surface.

A flat MCP server advertises every tool to the client, and COMSOLPilot has
grown past a hundred of them — enough that the tool list alone is a large
fixed cost in every conversation, and hard for a model to scan.

This module folds the surface into two tiers:

* **Tier 1** — a handful of always-visible tools. ``tools_catalog`` (in
  :mod:`catalog`) lists and searches everything, ``tools_describe`` returns one
  tool's full input schema, and ``tools_call`` runs it.
* **Tier 2** — every modelling tool, unchanged, reachable by name through
  ``tools_call``. They keep their schemas, their docstrings and the
  observability wrapper, so behaviour is identical to the flat surface.

Set ``COMSOLPILOT_TOOL_TIER=flat`` to advertise everything directly again (the
old behaviour), or ``COMSOLPILOT_TOP_LEVEL_TOOLS=comsol_status,model_list`` to
pin specific tools next to the gateways.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

GATEWAY_TOOLS = ("tools_catalog", "tools_describe", "tools_call")

# name -> Tool for every tool that is reachable through tools_call. Filled by
# collapse_to_gateway(); empty while the surface is flat.
_REGISTRY: dict[str, Any] = {}


def tool_tier() -> str:
    return (os.environ.get("COMSOLPILOT_TOOL_TIER") or "gateway").strip().lower()


def gateway_enabled() -> bool:
    """Whether the tool surface is collapsed into two tiers."""
    return tool_tier() not in {"flat", "all", "off", "0", "false", "no"}


def top_level_extra() -> set[str]:
    """Tools the user asked to keep visible next to the gateways."""
    raw = os.environ.get("COMSOLPILOT_TOP_LEVEL_TOOLS") or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def known_tools(mcp: FastMCP) -> dict[str, Any]:
    """Every tool the gateway can reach: the registry, plus anything still top level."""
    tools: dict[str, Any] = {}
    manager = getattr(mcp, "_tool_manager", None)
    for name, tool in getattr(manager, "_tools", {}).items():
        tools[name] = tool
    tools.update(_REGISTRY)
    return tools


def collapse_to_gateway(mcp: FastMCP, keep: tuple[str, ...] = ()) -> dict:
    """Move every tool except the gateways behind ``tools_call``.

    Must run *after* ``install_observability`` so the registry holds the wrapped
    functions: calling them through the gateway then logs exactly as a direct
    call would have.
    """
    if not gateway_enabled():
        return {"enabled": False, "demoted": 0, "top_level": []}

    manager = getattr(mcp, "_tool_manager", None)
    tools = dict(getattr(manager, "_tools", {})) if manager is not None else {}
    keep_names = set(keep) | top_level_extra() | set(GATEWAY_TOOLS)

    demoted = {name: tool for name, tool in tools.items() if name not in keep_names}
    _REGISTRY.clear()
    _REGISTRY.update(demoted)
    for name in demoted:
        manager.remove_tool(name)

    return {"enabled": True, "demoted": len(demoted),
            "top_level": sorted(name for name in tools if name in keep_names)}


def _coerce_arguments(arguments: Any) -> tuple[Optional[dict], Optional[str]]:
    """Accept a mapping or a JSON object string; return (mapping, error)."""
    if arguments in (None, ""):
        return {}, None
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception as exc:  # noqa: BLE001
            return None, f"arguments must be a JSON object: {exc}"
    if not isinstance(arguments, dict):
        return None, "arguments must be an object mapping parameter names to values"
    return arguments, None


def call_tool(mcp: FastMCP, name: str, arguments: Any = None) -> Any:
    """Invoke a tier-2 tool by name. Shared by the tool and the CLI."""
    name = (name or "").strip()
    if name in GATEWAY_TOOLS:
        return {"success": False,
                "error": f"'{name}' is a top-level tool; call it directly."}

    tool = known_tools(mcp).get(name)
    if tool is None:
        suggestions = _suggest(mcp, name)
        return {"success": False, "error": f"Unknown tool: {name}",
                "did_you_mean": suggestions,
                "hint": "Call tools_catalog() to list tools or "
                        "tools_catalog(query=...) to search."}

    params, problem = _coerce_arguments(arguments)
    if problem:
        return {"success": False, "error": problem, "tool": name}

    schema = getattr(tool, "parameters", {}) or {}
    properties = set(schema.get("properties", {}))
    unknown = sorted(key for key in params if key not in properties)
    missing = sorted(key for key in schema.get("required", []) if key not in params)
    if unknown or missing:
        return {
            "success": False,
            "tool": name,
            "error": ("unknown parameter(s): " + ", ".join(unknown)) if unknown
                     else ("missing required parameter(s): " + ", ".join(missing)),
            "valid_parameters": sorted(properties),
            "hint": f"Call tools_describe('{name}') for the full input schema.",
        }

    try:
        return tool.fn(**params)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller, already logged inside
        return {"success": False, "tool": name,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": f"Call tools_describe('{name}') to check the parameters."}


def _suggest(mcp: FastMCP, name: str, limit: int = 5) -> list[str]:
    """Closest tool names by simple substring overlap, for a helpful typo answer."""
    if not name:
        return []
    needle = name.casefold()
    scored = []
    for candidate in known_tools(mcp):
        low = candidate.casefold()
        if low == needle:
            score = 100
        elif needle in low or low in needle:
            score = 50 + min(len(low), len(needle))
        else:
            score = len(set(needle) & set(low))
        if score > 2:
            scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _, candidate in scored[:limit]]


def register_gateway_tools(mcp: FastMCP) -> None:
    """Register the tier-1 discovery and dispatch tools."""

    @mcp.tool()
    def tools_describe(name: str) -> dict:
        """Show one tool's purpose and full input schema before calling it.

        Use this after tools_catalog to see exactly which parameters a tool
        accepts, then run it with tools_call.

        Args:
            name: Exact tool name from tools_catalog, e.g. 'physics_boundary_selection'
        """
        tool = known_tools(mcp).get((name or "").strip())
        if tool is None:
            return {"success": False, "error": f"Unknown tool: {name}",
                    "did_you_mean": _suggest(mcp, name or ""),
                    "hint": "Call tools_catalog() first."}
        schema = getattr(tool, "parameters", {}) or {}
        return {
            "success": True,
            "name": name,
            "summary": getattr(tool, "description", "") or "",
            "parameters": schema,
            "required": schema.get("required", []),
            "call_with": f"tools_call('{name}', {{...}})",
        }

    @mcp.tool()
    def tools_call(name: str, arguments: dict = None) -> dict:
        """Run any COMSOLPilot tool by name - the second tier of the tool surface.

        Only a few tools are visible directly; every other tool is reached
        through here. Find the name with tools_catalog, check its parameters
        with tools_describe, then pass them as `arguments`. For example, to
        build a model end to end:

            tools_call('workflow_capabilities')
            tools_call('workflow_validate_spec', {'spec': {...}})
            tools_call('workflow_execute_spec', {'spec': {...}, 'solve': true})

        Args:
            name: Exact tool name from tools_catalog, e.g. 'geometry_add_block'
            arguments: Object of the tool's parameters, e.g. {'size': [0.1, 0.1, 0.1]}
        """
        return call_tool(mcp, name, arguments)
