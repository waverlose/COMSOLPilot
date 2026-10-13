"""COMSOLPilot - Main MCP server entry point."""

import logging
from mcp.server.fastmcp import FastMCP

from .tools.session import register_session_tools
from .tools.admin import register_admin_tools
from .tools.model import register_model_tools
from .tools.parameters import register_parameter_tools
from .tools.geometry import register_geometry_tools
from .tools.materials import register_material_tools
from .tools.physics import register_physics_tools
from .tools.mesh import register_mesh_tools
from .tools.study import register_study_tools
from .tools.surrogate import register_surrogate_tools
from .tools.results import register_results_tools
from .tools.workflow import register_workflow_tools
from .tools.recipes import register_recipe_tools
from .tools.prompts import register_prompt_templates
from .tools.schema_hints import apply_schema_hints
from .tools.telemetry import install_observability, register_telemetry_tools
from .tools.catalog import register_catalog_tools
from .tools.gateway import collapse_to_gateway, register_gateway_tools
from .tools.reference import register_reference_tools
from .tools.knowledge import register_knowledge_tools
from .resources.model_resources import register_model_resources

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("COMSOLPilot")


def register_all_tools() -> None:
    """Register all MCP tools."""
    register_session_tools(mcp)
    register_admin_tools(mcp)
    register_model_tools(mcp)
    register_parameter_tools(mcp)
    register_geometry_tools(mcp)
    register_material_tools(mcp)
    register_physics_tools(mcp)
    register_mesh_tools(mcp)
    register_study_tools(mcp)
    register_surrogate_tools(mcp)
    register_results_tools(mcp)
    register_workflow_tools(mcp)
    register_recipe_tools(mcp)
    register_telemetry_tools(mcp)
    register_catalog_tools(mcp)
    register_gateway_tools(mcp)
    register_reference_tools(mcp)
    register_knowledge_tools(mcp)
    register_prompt_templates(mcp)
    # FastMCP does not copy Args docstrings into property schemas.
    apply_schema_hints(mcp)
    # Wrap every tool last so the wrapper sees the final function objects. This
    # mirrors each call into COMSOL's own progress window and into a structured
    # JSONL log, and never changes the advertised schema.
    wrapped = install_observability(mcp)
    # Then collapse the surface: keep the discovery/dispatch gateways visible and
    # move the rest behind tools_call. Runs after the wrapping so calls through
    # the gateway are instrumented exactly like direct calls.
    collapsed = collapse_to_gateway(mcp)
    if collapsed.get("enabled"):
        logger.info("Registered %d tools: %d visible, %d behind tools_call (top level: %s)",
                    wrapped, wrapped - collapsed["demoted"], collapsed["demoted"],
                    ", ".join(collapsed["top_level"]))
    else:
        logger.info("Registered %d tools (flat surface)", wrapped)


def register_all_resources() -> None:
    """Register all MCP resources."""
    register_model_resources(mcp)
    logger.info("Registered all resources")


def main() -> None:
    """Run the MCP server."""
    logger.info("Starting COMSOLPilot MCP Server...")

    register_all_tools()
    register_all_resources()

    # The single COMSOL JVM handshake for this process happens here, on the main
    # thread, BEFORE the MCP event loop starts serving. Doing it here keeps the
    # first tool call instant; a JVM started later from a tool call also works
    # (see SessionManager._run_jvm_task), so this is an optimisation, not a
    # hard requirement. When COMSOL is not running yet and autostart is on,
    # prewarm starts the server itself, so the connector launch is the only
    # start-up action the user needs - no launcher script.
    from .tools.session import session_manager
    try:
        prewarm = session_manager.prewarm()
        if prewarm.get("success"):
            logger.info("COMSOL session pre-warmed: %s", prewarm)
        elif prewarm.get("skipped"):
            logger.info("COMSOL pre-warm not attempted: %s", prewarm.get("message"))
        else:
            logger.warning(
                "COMSOL pre-warm failed: %s. The server still starts; ask the "
                "assistant to run comsol_start_server, or set COMSOL_AUTOSTART=on.",
                prewarm.get("error"),
            )
    except Exception as exc:  # noqa: BLE001 - never block server startup
        logger.warning("COMSOL pre-warm raised %r; continuing without a session.", exc)

    mcp.run()


if __name__ == "__main__":
    main()
