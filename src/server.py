"""COMSOLPilot - Main MCP server entry point."""

import logging
import os
import sys
from pathlib import Path

# Some MCP clients omit Windows environment variables; mph reads them at import.
if sys.platform == "win32":
    for key, folder in (("APPDATA", "Roaming"), ("LOCALAPPDATA", "Local")):
        os.environ.setdefault(key, str(Path.home() / "AppData" / folder))

from .runtime import prepare_native_bridge
prepare_native_bridge()

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


def register_all_tools(worker=None) -> None:
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
    if worker is not None:
        from .worker import install_worker_dispatch
        install_worker_dispatch(mcp, worker)
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


def register_all_resources(worker=None) -> None:
    """Register all MCP resources."""
    register_model_resources(mcp, worker=worker)
    logger.info("Registered all resources")


def main() -> None:
    """Serve MCP immediately; initialize COMSOL in an isolated worker on demand."""
    from .worker import ComsolWorker
    from .tools.session import _autostart_enabled

    worker = ComsolWorker()
    register_all_tools(worker=worker)
    register_all_resources(worker=worker)
    if _autostart_enabled():
        worker.start()  # Existing opt-in: eager startup is now non-blocking too.
    try:
        mcp.run()
    finally:
        worker.close()


if __name__ == "__main__":
    main()
