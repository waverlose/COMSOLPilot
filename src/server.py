"""COMSOLPilot - Main MCP server entry point."""

import logging
from mcp.server.fastmcp import FastMCP

from .tools.session import register_session_tools
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
from .tools.prompts import register_prompt_templates
from .tools.schema_hints import apply_schema_hints
from .tools.telemetry import install_observability, register_telemetry_tools
from .resources.model_resources import register_model_resources

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("COMSOLPilot")


def register_all_tools() -> None:
    """Register all MCP tools."""
    register_session_tools(mcp)
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
    register_telemetry_tools(mcp)
    register_prompt_templates(mcp)
    # FastMCP does not copy Args docstrings into property schemas.
    apply_schema_hints(mcp)
    # Wrap every tool last so the wrapper sees the final function objects. This
    # mirrors each call into COMSOL's own progress window and into a structured
    # JSONL log, and never changes the advertised schema.
    wrapped = install_observability(mcp)
    logger.info("Registered all tools (%d instrumented)", wrapped)


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
    # thread, BEFORE the MCP event loop starts serving. JPype's startJVM() and the
    # WebBridge connect deadlock once anyio is running, so a later comsol_connect
    # can never start a JVM -- it can only reuse the one established below.
    from .tools.session import session_manager
    try:
        prewarm = session_manager.prewarm()
        if prewarm.get("success"):
            logger.info("COMSOL session pre-warmed: %s", prewarm)
        elif prewarm.get("skipped"):
            logger.info("COMSOL pre-warm not attempted: %s", prewarm.get("message"))
        else:
            logger.warning(
                "COMSOL pre-warm failed: %s. The server still starts; run "
                "start_comsol_server.bat and reconnect the MCP connector.",
                prewarm.get("error"),
            )
    except Exception as exc:  # noqa: BLE001 - never block server startup
        logger.warning("COMSOL pre-warm raised %r; continuing without a session.", exc)

    mcp.run()


if __name__ == "__main__":
    main()
