"""MCP Prompt templates for COMSOLPilot.

Prompts are the third MCP server primitive: reusable, parameterised instruction
templates that clients surface to the user (slash commands, pickers, ...). They
differ from tools in that they produce text for the model rather than performing
an action.

Each template here encodes the conventions that this project actually verified
against COMSOL 6.2, so a user who starts from a prompt does not rediscover them:

* boundary condition types are aliases resolved server-side ("Temperature" ->
  TemperatureBoundary) -- never guess the raw COMSOL feature id
* a coordinate box that sits exactly on a face can select nothing; prefer an
  explicit boundary list when the face ids are already known
* solve, then confirm the field actually respects the imposed boundary values
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

_SPEC_HEADER = """Build a COMSOL model with COMSOLPilot. Work in this order and stop
if a step reports `success: false`:

1. `comsol_status` -- confirm a session exists (the connector pre-warms it at startup).
2. `workflow_validate_spec` -- validate the spec before touching COMSOL.
3. `workflow_execute_spec` -- execute it.

Conventions that this COMSOL version actually requires:
- Boundary condition `type` is the friendly alias (`Temperature`, `HeatFlux`,
  `ConvectiveHeatFlux`, `Fixed`, `Roller`, `Ground`, `ElectricPotential`). The
  server maps it to the real feature id.
- All geometry coordinates are SI metres.
- A `where.box` must contain the face with room to spare. If it selects nothing
  the server raises a clear error rather than building a singular model; fall
  back to `"where": {"boundaries": [id, ...]}` when you know the face ids.
- After solving, check the reported outputs against the boundary values you
  imposed. A field that overshoots its own boundary data is not trustworthy and
  the server will flag it in `solve_error`.
"""


def register_prompt_templates(mcp: FastMCP) -> None:
    """Register reusable modelling prompt templates."""

    @mcp.prompt()
    def steady_heat_conduction(
        length_m: float = 0.1,
        conductivity: str = "205[W/(m*K)]",
        hot_k: float = 373.15,
        cold_k: float = 293.15,
    ) -> str:
        """Steady-state heat conduction through a solid block.

        Args:
            length_m: Block edge length in metres
            conductivity: Thermal conductivity with units, e.g. '205[W/(m*K)]'
            hot_k: Temperature of the hot face in kelvin
            cold_k: Temperature of the cold face in kelvin
        """
        return f"""{_SPEC_HEADER}
Task: steady-state heat conduction through an aluminium block.

```json
{{
  "model": {{"name": "SteadyConduction", "dimension": 3, "component": "comp1", "geometry": "geom1"}},
  "geometry": [
    {{"type": "block", "tag": "blk1", "position": [0, 0, 0], "size": [{length_m}, {length_m}, {length_m}]}}
  ],
  "materials": [
    {{"tag": "mat1", "label": "Aluminum", "domains": "all",
      "properties": {{"thermalconductivity": "{conductivity}",
                     "density": "2700[kg/m^3]",
                     "heatcapacity": "900[J/(kg*K)]"}}}}
  ],
  "physics": [
    {{"type": "ht", "boundary_conditions": [
      {{"tag": "temp_bottom", "type": "Temperature",
       "where": {{"box": {{"xmin": -1e-6, "xmax": {length_m + 1e-6},
                          "ymin": -1e-6, "ymax": {length_m + 1e-6},
                          "zmin": -1e-6, "zmax": 1e-6}}}},
       "properties": {{"T0": "{hot_k}[K]"}}}},
      {{"tag": "temp_top", "type": "Temperature",
       "where": {{"box": {{"xmin": -1e-6, "xmax": {length_m + 1e-6},
                          "ymin": -1e-6, "ymax": {length_m + 1e-6},
                          "zmin": {length_m - 1e-6}, "zmax": {length_m + 1e-6}}}}},
       "properties": {{"T0": "{cold_k}[K]"}}}}
    ]}}
  ],
  "mesh": {{"tag": "mesh1", "size": 4, "run": true}},
  "study": {{"tag": "std1", "type": "Stationary"}},
  "outputs": [
    {{"name": "Tmax", "type": "max", "expression": "T", "unit": "K"}},
    {{"name": "Tmin", "type": "min", "expression": "T", "unit": "K"}}
  ]
}}
```

Sanity checks for this model: `Tmax` must equal {hot_k} K and `Tmin` must equal
{cold_k} K. The heat flux is conductivity * (hot - cold) / {length_m}. If the
extremes do not match the boundary values, the model is wrong -- say so instead
of presenting the numbers.
"""

    @mcp.prompt()
    def structural_statics(
        length_m: float = 0.1,
        youngs_modulus: str = "200e9[Pa]",
        poissons_ratio: str = "0.33",
    ) -> str:
        """Static structural analysis of a clamped block under a body load.

        Args:
            length_m: Block edge length in metres
            youngs_modulus: Young's modulus with units
            poissons_ratio: Poisson's ratio
        """
        return f"""{_SPEC_HEADER}
Task: linear-static structural analysis of a {length_m} m steel block, clamped on
the bottom face, loaded on the top face.

Use `"type": "solid"` with `Fixed` on the bottom face and `BoundaryLoad` with a
pressure on the top face. Build a mesh of at least size 3 for a meaningful stress
result -- coarse meshes on Solid Mechanics give badly under-resolved peaks at the
clamped edge, and the peak stress is exactly what you are reporting.

Material properties to use:
- `youngsmodulus`: {youngs_modulus}
- `poissonsratio`: {poissons_ratio}
- `density`: "7850[kg/m^3]"

Report the maximum von Mises stress and say which face it sits on. Note that the
clamped-edge peak is a stress singularity in the mathematical model: state that
the value is mesh dependent instead of quoting it as a material result.
"""

    @mcp.prompt()
    def parametric_sweep(
        parameter: str = "k",
        values: str = "10, 50, 100, 200",
    ) -> str:
        """Set up and run a parametric sweep over a material or geometry parameter.

        Args:
            parameter: Name of the parameter to sweep, e.g. 'k'
            values: Comma separated list of values
        """
        return f"""{_SPEC_HEADER}
Task: sweep the parameter `{parameter}` over these values: {values}.

Approach:
1. Build and solve the base model first with a single value, and confirm the
   solution respects its boundary conditions.
2. Only then add the sweep. Use `param_sweep_setup` plus a Stationary study with
   a parametric step, or express the sweep directly in the study spec.
3. Solve with `study_solve_async` and poll `study_get_progress` -- a sweep over
   four values is long enough that a blocking call risks a client-side timeout.

Report results as a table of `{parameter}` against the quantity of interest. Do
not extrapolate beyond the swept range.
"""

    @mcp.prompt()
    def debug_nonconvergence() -> str:
        """Diagnose a stationary or time-dependent solve that will not converge."""
        return f"""{_SPEC_HEADER}
Task: the model will not converge. Work through these checks in order and report
which one was the cause.

1. Boundary conditions with empty selections. A condition that selects no
   entities leaves COMSOL's default insulation in place, which makes a stationary
   heat or current problem singular. `workflow_execute_spec` now blocks this with
   a `preflight` step -- if it fired, fix the `where` clause.
2. A field that overshoots its own boundary values. The server compares the
   solved field against the imposed values and reports a violation in
   `solve_error`. Coarse meshes are the usual cause; drop the mesh `size` by one
   or two and re-solve.
3. Missing material data. Wrap every material property in a list, e.g.
   `['205[W/(m*K)]']`. An unwrapped value can be read as zero and produce a
   singular matrix.
4. A genuinely ill-posed model: no heat source and no fixed values, or two
   conflicting conditions on the same entity. Say so rather than adding a
   numerical patch.

Report the root cause and the fix. Do not report a result you could not verify.
"""

    @mcp.prompt()
    def model_from_description(description: str) -> str:
        """Turn a natural-language simulation description into a validated spec.

        Args:
            description: What the user wants to simulate, in their own words
        """
        return f"""{_SPEC_HEADER}
The user described the simulation like this:

> {description}

First restate the physical setup as geometry, materials, physics, boundary
conditions and study type -- and list every assumption you had to make. Ask the
user to confirm anything you are guessing (dimensions, which faces are clamped or
held, material, whether the problem is steady or transient).

Then call `workflow_capabilities` to confirm the physics interface and boundary
condition aliases available, build the spec, validate it, and execute it. Report
the outputs together with the assumptions they rest on.
"""
