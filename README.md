<div align="center">

# COMSOLPilot

**Drive COMSOL Multiphysics with AI — through MCP.**

One MCP server + one-click launcher. 121 tools in two tiers. From geometry to
results — watch every step live in COMSOL Desktop.

**The AI can start and configure COMSOL for you.** See the
[AI setup guide](docs/AI_SETUP_CN.md) (Chinese).

`Windows` `COMSOL 6.x` `MCP` `Python 3.10+` `JPype / MPh`

</div>

---

## What is this?

COMSOLPilot exposes COMSOL Multiphysics as an MCP server, so any MCP-capable
AI client (WorkBuddy, Claude Code, OpenCode, Codex, Cursor, ...) can build and
run simulations for you while you watch in COMSOL Desktop.

**GUI-sync mode:** the AI connects to the same COMSOL server as your Desktop.
Every geometry node, material, physics setting and result appears in your model
tree in real time. You can inspect the model or take over manually at any point.

---

## Features

Documentation search and verified troubleshooting notes are described in the
[reference and knowledge guide](docs/REFERENCE_KNOWLEDGE_CN.md) (Chinese).

| Feature | Description |
|---|---|
| 121 tools | Geometry (blocks, cylinders, boolean operations), materials, physics (es/ec/ht/spf/solid), mesh, studies, results, plots and parametric sweeps |
| Two-tier surface | `workflow_execute_spec` handles bulk setup directly; `tools_catalog`, `tools_describe` and `tools_call` provide access to the other 117 tools |
| GUI sync | The AI works on the same server as your Desktop, so you can watch its operations live |
| AI-driven setup | MCP connects immediately; COMSOL starts on the first modeling request. Configure the version, port and client through conversation |
| One-click launcher | One-time environment setup, followed by a GUI/headless menu; shared settings live in `config.toml` |
| Multi-client | Register a selected MCP client on demand; client configuration is written only when you request it |
| Reconnection | The connector detects a dead or restarted server and attempts to reconnect |

---

## Requirements

- Windows 10 1903+ (Windows Terminal recommended)
- COMSOL Multiphysics 6.x, with a license that can run the server
- Python 3.10+ for the initial environment setup
- An MCP-capable AI client

---

## Quick Start

**One-time environment setup** (creates `.venv` and installs dependencies):

```bat
git clone https://github.com/waverlose/COMSOLPilot.git
cd COMSOLPilot
start_comsol_server.bat
```

On its first run, `start_comsol_server.bat` creates `.venv` and installs the
dependencies. Equivalent manual command:

```bat
python -m venv .venv && .venv\Scripts\python -m pip install -r requirements-windows.txt
```

**Daily use: open your AI client and ask it to build a model. No bat is required.**

MCP becomes available immediately. Tool discovery, documentation search and spec
validation do not start COMSOL. The first modeling request starts an isolated
COMSOL worker; an existing server is reused. No connector reconnect is needed.
Status queries remain available during COMSOL initialization.

- `code=comsol_starting`: the original request has not executed. Query
  `comsol_status`, wait for `state=ready`, then retry the original request.
- `code=operation_in_progress`: the operation has been submitted. Do not replay
  it; use its `request_id` to retrieve the result from `last_operation.result`
  in the status response.
- Startup failure: inspect the error or `workspace/logs/worker.log`, then retry
  with `comsol_start_server`.

On Windows, the connector caches JPype's native bridge on an ASCII temporary
path when needed, so the project can stay in a directory with non-ASCII characters.
Check `runtime.native_bridge_ready` in `comsol_environment` for its status.

Startup is on demand by default. Set `[connector] autostart=true` to start COMSOL
in the background when MCP connects. See the [AI setup guide](docs/AI_SETUP_CN.md)
(Chinese) for details.

The bat launcher remains available for initial setup, manual management,
upgrades and troubleshooting.

---

## Connect an AI client

Choose a client and run the corresponding command:

```bash
# Print a configuration example to paste into your client.
python -m src.cli config --client workbuddy

# Register only the selected client.
python scripts/sync_mcp_port.py --ensure --only workbuddy
```

Supported clients:
`Agens` `workbuddy` `claude-code` `claude-desktop` `gemini` `cursor`
`windsurf` `opencode` `codex` `deepseek`

Configuration paths and format examples are in the
[client connection guide](docs/CONNECTORS_CN.md) (Chinese).

After registering, trust or enable `comsolpilot` in the client's connector page
once.

---

## Configuration

One file configures this installation: **`config.toml`** at the project root.
The launcher and MCP connector both read it, so you only need to change a shared
setting once.

```toml
[comsol]
port = 2036          # Server port
mode = "gui"         # gui (visible in Desktop) | headless
version = ""         # Pin a version, e.g. "6.2"; empty selects the latest installed
login_mode = "auto"  # auto | never | info | force
open_desktop = true

[connector]
autostart = false    # false: start on first modeling request; true: start on connect
entry_name = "comsolpilot"   # Client configuration entry name

[ui]
spinner = "claude"   # Startup/shutdown animation: claude | plain | auto | off
```

Priority: environment variable > `config.toml` > `workspace/settings.json`
(runtime state). The assistant can update preferences with
`comsol_set_preferences`, which preserves comments in `config.toml`.

Version and port settings apply when starting a new COMSOL worker session.
`comsol_start_server` reuses an already-ready worker; it does not switch that
worker's active version or port. Reconnect the MCP server to start a new worker
with changed settings.

---

## Tool surface: two tiers

The server advertises four tools by default: `workflow_execute_spec` for bulk
initial setup, plus three gateways for finding and calling individual tools.

**Start in bulk, then refine.** For a new model, call `workflow_execute_spec`
once with `solve=false` and `collect_outputs=false`. It validates the spec and
sets up parameters, geometry, materials, physics, mesh and study nodes inside
the server. A separate validation call is optional. For example, pass this
payload directly to `workflow_execute_spec`:

```json
{
  "spec": {
    "model": {"name": "HeatBlock", "dimension": 3},
    "parameters": {"L": "10[mm]"},
    "geometry": [
      {"type": "block", "tag": "blk1", "position": [0, 0, 0], "size": ["L", "L", "L"]}
    ],
    "materials": [
      {"tag": "mat1", "label": "Aluminum", "properties": {
        "thermalconductivity": "205[W/(m*K)]",
        "density": "2700[kg/m^3]",
        "heatcapacity": "900[J/(kg*K)]"
      }}
    ],
    "physics": [
      {"type": "ht", "boundary_conditions": [
        {"tag": "hot", "type": "Temperature", "where": {"face": "zmin"}, "properties": {"T0": "373.15[K]"}},
        {"tag": "cold", "type": "Temperature", "where": {"face": "zmax"}, "properties": {"T0": "293.15[K]"}}
      ]}
    ],
    "mesh": {"tag": "mesh1", "size": 7, "run": true},
    "study": {"tag": "std1", "type": "Stationary"}
  },
  "solve": false,
  "collect_outputs": false
}
```

The result includes model/component/geometry/mesh/study identifiers and geometry
and mesh counts. Numeric geometry lengths are meters; primitive dimensions can
also use COMSOL expressions referencing the supplied parameters. Materials and
physics are optional for geometry-only setup. Initialization creates a new model;
keep the returned model name and use individual tools for later changes:

```text
tools_call("param_set", {"model_name": "HeatBlock", "name": "L", "value": "12[mm]"})
tools_call("geometry_build", {"model_name": "HeatBlock", "geometry_name": "geom1"})
tools_call("mesh_ensure", {"model_name": "HeatBlock", "mesh_size": 6})
```

Do not rerun initialization to modify an existing model. On execution failure,
the partial model is retained and its name is returned for inspection or repair.
Set `solve=true` only when you also want the workflow to solve the new model.
For features outside the example, discover the relevant schema or small tool:

```text
tools_catalog()                                  # List tools by group
tools_catalog(query="thermal conduction")         # Search by keyword
tools_describe("geometry_add_block")              # Inspect the input schema
tools_call("geometry_add_block", {"size": [0.1, 0.1, 0.1]})
```

For the flat surface, set `COMSOLPILOT_TOOL_TIER=flat`. Pin selected tools to the
top level with `COMSOLPILOT_TOP_LEVEL_TOOLS=comsol_status,model_list`.
See the [tool tiers guide](docs/TOOL_TIERS_CN.md) (Chinese).

---

## Try it

Tell your AI:

> Build a 10x10x1 mm dielectric slab (eps_r = 4.5), 1 V on the bottom, ground
> on top, and compare the numerical capacitance with the parallel-plate formula.

The parallel-plate formula gives approximately 3.98438 pF. Compare the numerical
result with this value after checking the material and boundary selections.

---

## Project layout

```text
COMSOLPilot/
|-- src/                      MCP server, tools and telemetry
|   +-- server.py             FastMCP server: 121 tools in two tiers, 5 prompts
|   +-- mcp_targets.py        Multi-client configuration registry
|   +-- cli.py                doctor / onboard / config / demo commands
|   +-- tools/                Session, setup, gateway, geometry, physics, mesh,
|                             study, results and telemetry tools
|-- scripts/                  Server lifecycle, configuration and client sync
|-- docs/                     Guides (Chinese)
|-- tests/                    pytest suite
+-- workspace/                Runtime artifacts (git-ignored)
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Client says "Not connected" | Enable the MCP connector in your client. COMSOL `state=idle` is normal; the first modeling request starts it |
| COMSOL will not start, `Can't load library` | The connector caches JPype's native bridge on an ASCII path. Inspect `runtime.native_bridge_ready` and `workspace/logs/worker.log` |
| AI should start or reconfigure COMSOL | Ask it to call `comsol_environment`, `comsol_set_preferences`, then `comsol_start_server`. See the [AI setup guide](docs/AI_SETUP_CN.md). Changed version/port settings require a new worker session |
| "Server is in use by another client" | GUI-sync contention can be transient; the tools retry internally |
| Model prompts "save changes?" | The AI may have added tables, parameters or other model nodes. Review and save the changes |
| Port 2036 is busy | Change `port` in `config.toml`, or set `COMSOL_PORT`, before starting a new worker session |
| Git clone certificate revocation error | If a corporate proxy blocks CRL retrieval, use the per-command option `git -c http.schannelCheckRevoke=false clone ...` only in that trusted environment |
| Solve fails, "singular matrix" | Inspect `solve_error`. Check whether a boundary condition's `where` matched an entity; correct the selection or use a symbolic face |
| Result looks wrong | Check `solve_error`, units and boundary selections. Investigate fields that exceed imposed boundary values |
| Geometry feature has no dedicated tool (Sweep, Extrude, coil) | Use `model_execute_python` for the native COMSOL Java API |
| COMSOL is not found | Set `COMSOL_SERVER_EXE`, or inspect discovery results from `comsol_environment` |
| Models are piling up in memory | `model_clear_all` unloads every model in the session; use it only when all those models can be closed |
| New tools are missing in this chat | Refresh the client's MCP connection and open a new conversation to reload the tool list |

More guides (Chinese):
[AI startup and configuration](docs/AI_SETUP_CN.md) ·
[Two-tier tools](docs/TOOL_TIERS_CN.md) ·
[Client connections](docs/CONNECTORS_CN.md) ·
[Modeling constraints](docs/MODELING_CONSTRAINTS_CN.md) ·
[Manual search and knowledge base](docs/REFERENCE_KNOWLEDGE_CN.md)

---

## License

[MIT](LICENSE) — use it, fork it, ship it.

---

<div align="center">

*The road ahead is long — and walking it gets you there.*

</div>
