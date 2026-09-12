"""JSON Schema hints for MCP tool inputs.

FastMCP keeps function docstrings as the tool description, but it does not copy
Arg docstrings into each property schema. Patch the generated schema so clients
see units, formats, examples, and constrained choices in inputSchema.
"""

from __future__ import annotations

import inspect
import re
from typing import Any


from .physics import PHYSICS_TYPE_MAP
from .workflow import STUDY_CAPABILITIES

# Derived from PHYSICS_TYPE_MAP so the advertised enum can never drift from
# what physics_add actually accepts (single source of truth).
PHYSICS_TYPE_ENUM = sorted({
    alias
    for key, (_, interface, _label) in PHYSICS_TYPE_MAP.items()
    for alias in (key, interface)
})

BOUNDARY_CONDITION_ENUM = [
    "Ground",
    "ElectricPotential",
    "SurfaceChargeDensity",
    "ZeroCharge",
    "Fixed",
    "Roller",
    "Symmetry",
    "BoundaryLoad",
    "Temperature",
    "TemperatureBoundary",
    "HeatFlux",
    "HeatFluxBoundary",
    "ConvectiveHeatFlux",
    "ThermalInsulation",
    "InletBoundary",
    "OutletBoundary",
    "Wall",
]

COUPLING_TYPE_ENUM = [
    "ThermalStress",
    "FluidStructureInteraction",
    "ElectromechanicalForces",
    "JouleHeating",
    "NonIsothermalFlow",
    "nitf",
    "cht",
    "conjugateheattransfer",
]

STUDY_TYPE_ENUM = sorted(STUDY_CAPABILITIES)

PARAMETER_HINTS = {
    "host": "COMSOL server hostname. For local GUI sync, use 'localhost'.",
    "port": "Fixed COMSOL GUI/server port. Default is 2036.",
    "standalone": "Deprecated compatibility flag. Use mode='headless' for background operation.",
    "mode": "COMSOL session mode: 'ask' requires the user to choose, 'gui' requires port 2036, 'headless' starts a background JVM, and 'auto' probes first.",
    "autostart_server": "Advanced opt-in. If true, comsol_start may launch a local COMSOL Server for GUI mode. Default is false; prefer start_comsol_server.bat.",
    "model_name": "Loaded model name. Omit or pass null to use the current active model.",
    "component_name": "COMSOL component tag, for example 'comp1'. Create it before geometry or physics tools.",
    "geometry_name": "COMSOL geometry sequence tag, for example 'geom1'. Create it with geometry_create before adding features.",
    "feature_name": "Optional COMSOL feature tag. Omit or pass null to auto-generate a tag.",
    "space_dimension": "Geometry space dimension. Use 2 for planar geometry or 3 for 3D geometry.",
    "position": "Coordinate array in meters. Use SI values such as 1e-3 for 1 mm; COMSOL will not infer millimeters.",
    "size": "Dimension array in meters. Use SI values such as 10e-3 for 10 mm; COMSOL will not infer millimeters.",
    "radius": "Radius in meters. Use SI values such as 5e-4 for 0.5 mm.",
    "height": "Height in meters. Use SI values such as 1e-3 for 1 mm.",
    "physics_name": "Physics interface tag or label. Prefer returned tags such as 'ht', 'spf', 'solid', or 'es'.",
    "physics_type": "Supported physics identifier. Prefer tags 'ht', 'spf', 'solid', 'es', or 'ec'.",
    "domain_selection": "Domain selection. Use null for all domains, a named COMSOL selection tag, or domain number list where supported.",
    "boundary_selection": "Boundary numbers from geometry_get_boundaries after geometry_build; do not guess face numbers.",
    "boundary_numbers": "Boundary numbers from geometry_get_boundaries after geometry_build; do not guess face numbers.",
    "boundary_condition": "COMSOL boundary condition type. Match the physics interface, for example HeatFluxBoundary for Heat Transfer.",
    "boundary_condition_type": "COMSOL boundary condition type. Match the physics interface, for example TemperatureBoundary or ConvectiveHeatFlux.",
    "properties": "COMSOL property dictionary. Use feature, material, or boundary-condition keys matching the target tool.",
    "selections": "COMSOL feature selection inputs, for example {'input': ['blk1'], 'input2': ['cyl1']}.",
    "build": "Whether to run the geometry after creating the feature.",
    "script": "Python code to execute inside the local MCP server process against the active COMSOL model.",
    "confirm": "Explicit confirmation token required by tools that execute local code.",
    "spec": "Structured simulation specification. The AI should translate user intent into model, geometry, materials, physics, mesh, study, and outputs before execution.",
    "solve": "Whether workflow_execute_spec should run the solver after creating the model.",
    "collect_outputs": "Whether workflow_execute_spec should evaluate requested outputs after solving.",
    "material_name": "Existing COMSOL material tag or label in the model. Check model_inspect/materials first; do not assume 'Si' exists.",
    "label": "Human-readable label shown in COMSOL. The tag/name remains the stable identifier.",
    "mesh_name": "COMSOL mesh sequence tag, for example 'mesh1'.",
    "mesh_size": "Physics-controlled mesh size 1-9 if supported; lower is finer.",
    "run": "Whether to run/generate after ensuring the object exists.",
    "study_name": "COMSOL study tag, for example 'std1'.",
    "study_type": "COMSOL study step type.",
    "step_tag": "Optional COMSOL study feature tag, for example 'stat' for Stationary.",
    "selection_name": "COMSOL named selection tag. Prefer stable tags such as 'bottom_bnd' or 'heat_source_top'.",
    "condition": "Box selection condition. Use 'inside' for fully contained entities or 'intersects' for touching entities.",
    "xmin": "Minimum x coordinate in meters.",
    "xmax": "Maximum x coordinate in meters.",
    "ymin": "Minimum y coordinate in meters.",
    "ymax": "Maximum y coordinate in meters.",
    "zmin": "Minimum z coordinate in meters.",
    "zmax": "Maximum z coordinate in meters.",
    "heat_flux_value": "COMSOL heat flux expression, typically with units, for example '1e6[W/m^2]'.",
    "temperature_value": "COMSOL temperature expression, typically with units, for example '293.15[K]'.",
    "convection_coeff": "Convection coefficient expression, for example '10[W/(m^2*K)]'.",
    "ambient_temp": "Ambient temperature expression, for example '293.15[K]'.",
    "inlet_velocity": "Laminar Flow inlet velocity expression, for example '1[mm/s]' or '0.01[m/s]'.",
    "outlet_pressure": "Outlet pressure expression, for example '0[Pa]'.",
    "expression": "COMSOL expression or list of expressions to evaluate, for example 'T' or ['x', 'y', 'T'].",
    "unit": "Optional output unit string, for example 'K', 'V/m', or 'pF'.",
    "dataset": "Dataset tag/name. Omit or pass null to use COMSOL's default solution dataset.",
    "inner": "Time-dependent inner solution index, 'first', 'last', or list of indices.",
    "outer": "Parametric sweep outer solution index or list of indices.",
    "file_path": "Filesystem path. Use an absolute path when the server working directory is uncertain.",
    "format": "COMSOL save format.",
}

PRIMARY_WORKFLOW_DESCRIPTION = (
    "Primary AI modeling entry point. For user requests like 'build/simulate/solve a COMSOL model', "
    "call workflow_capabilities first, translate the request into a structured spec, validate it with "
    "workflow_validate_spec, then execute it with workflow_execute_spec. Do not start with low-level "
    "model_create/geometry_add/physics_add tools unless debugging a workflow failure."
)

LOW_LEVEL_TOOL_PREFIXES = (
    "model_execute_python",
    "model_create",
    "geometry_",
    "material_",
    "physics_",
    "mesh_",
    "study_",
    "results_",
)

FUNCTION_PARAM_HINTS = {
    ("physics_add", "domain_selection"): "Not accepted by this generic wrapper. Use physics_add_heat_transfer or another dedicated physics_add_* tool if a domain selection is needed.",
    ("physics_set_material", "domain_selection"): "Domain numbers or a named selection for material assignment scope. Omit or pass null for all domains.",
    ("material_create_basic", "material_name"): "Material tag to create or update, for example 'mat1'. Use label for display name such as 'Silicon'.",
    ("material_create_basic", "properties"): "COMSOL material property dictionary, for example {'thermalconductivity': '130[W/(m*K)]', 'density': '2329[kg/m^3]', 'heatcapacity': '700[J/(kg*K)]'}.",
    ("geometry_add_feature", "properties"): "Feature-specific COMSOL property dictionary passed to feature.set(key, value). Prefer dedicated geometry_add_* tools for common shapes.",
    ("geometry_add_feature", "selections"): "Feature selection inputs passed to feature.selection(name).set(values), for example {'input': ['blk1'], 'input2': ['cyl1']}.",
    ("model_execute_python", "script"): "Advanced COMSOL automation script. Use this for Java API operations such as ParametricCurve, Sweep, Extrude, Fillet, and custom result nodes.",
    ("model_execute_python", "confirm"): "Must be exactly EXECUTE_COMSOL_PYTHON. This tool runs trusted local code inside the MCP server process.",
}


def _arg_descriptions(fn: Any) -> dict[str, str]:
    doc = inspect.getdoc(fn) or ""
    lines = doc.splitlines()
    descriptions: dict[str, str] = {}
    in_args = False
    current_name: str | None = None

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped == "Args:":
            in_args = True
            current_name = None
            continue
        if in_args and re.match(r"^[A-Z][A-Za-z ]+:$", stripped):
            break
        if not in_args or not stripped:
            continue

        match = re.match(r"^\*{0,2}([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", stripped)
        if match:
            current_name = match.group(1)
            descriptions[current_name] = match.group(2).strip()
        elif current_name and line.startswith((" ", "\t")):
            descriptions[current_name] += " " + stripped

    return descriptions


def _set_enum(property_schema: dict[str, Any], values: list[Any]) -> None:
    # Mutating inputSchema is intentional: FastMCP reads this object in list_tools.
    property_schema["enum"] = values


def _apply_property_hint(tool_name: str, prop_name: str, prop_schema: dict[str, Any], doc_hints: dict[str, str]) -> None:
    description = FUNCTION_PARAM_HINTS.get((tool_name, prop_name)) or PARAMETER_HINTS.get(prop_name) or doc_hints.get(prop_name)
    if description:
        prop_schema["description"] = description

    if prop_name == "physics_type":
        _set_enum(prop_schema, PHYSICS_TYPE_ENUM)
    elif prop_name in {"boundary_condition", "boundary_condition_type"}:
        _set_enum(prop_schema, BOUNDARY_CONDITION_ENUM)
    elif prop_name == "coupling_type":
        _set_enum(prop_schema, COUPLING_TYPE_ENUM)
    elif prop_name == "study_type":
        _set_enum(prop_schema, STUDY_TYPE_ENUM)
    elif prop_name == "condition":
        _set_enum(prop_schema, ["inside", "intersects", "somevertex", "allvertices"])
    elif prop_name == "space_dimension":
        _set_enum(prop_schema, [2, 3])
    elif prop_name == "format":
        _set_enum(prop_schema, ["Comsol", "Java", "Matlab", "VBA"])
    elif prop_name == "import_type":
        _set_enum(prop_schema, ["CAD", "mesh"])
    elif prop_name == "mode":
        _set_enum(prop_schema, ["ask", "gui", "headless", "auto"])


def apply_schema_hints(mcp: Any) -> None:
    """Fill generated FastMCP tool input schemas with parameter descriptions."""
    for tool in mcp._tool_manager.list_tools():
        properties = tool.parameters.get("properties", {})
        doc_hints = _arg_descriptions(tool.fn)

        for prop_name, prop_schema in properties.items():
            _apply_property_hint(tool.name, prop_name, prop_schema, doc_hints)

        # Keep the schema self-explanatory for multi-step COMSOL workflows.
        if tool.name.startswith("geometry_add_"):
            tool.parameters.setdefault(
                "description",
                "Requires model_create, model_create_component, and geometry_create before use. Call geometry_build before boundary lookup.",
            )
        
        if tool.name.startswith("workflow_"):
            tool.description = f"{PRIMARY_WORKFLOW_DESCRIPTION}\n\n{tool.description or ''}".strip()
        elif tool.name.startswith(LOW_LEVEL_TOOL_PREFIXES):
            tool.description = (
                "Low-level/debug tool. For normal AI-driven modeling, prefer workflow_capabilities -> "
                "workflow_validate_spec -> workflow_execute_spec so MCP can use stable Java tags and a fixed workflow. "
                f"\n\n{tool.description or ''}"
            ).strip()
