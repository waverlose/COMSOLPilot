"""Copy-ready workflow specs for common model families.

Modelling used to be slow because the assistant wrote a spec from the schema and
iterated on validation and solver errors. Each entry here is a starting point
that has actually been run against COMSOL - the `check` field records what the
result looked like - so the assistant can copy a known-good spec and change the
numbers instead of rediscovering the shape.

    workflow_recipes()                 list them (name + one-line + physics)
    workflow_recipes(name="...")       the full spec, ready for workflow_execute_spec

Nothing here is COMSOL-version specific beyond the project's own assumptions
(SI units, kernel API, COMSOL 6.x).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

ALUMINIUM = {
    "tag": "mat1",
    "label": "Aluminum",
    "domains": "all",
    "properties": {
        "thermalconductivity": "205[W/(m*K)]",
        "density": "2700[kg/m^3]",
        "heatcapacity": "900[J/(kg*K)]",
    },
}

RECIPES: dict = {
    "steady_heat_conduction": {
        "title": "三维稳态导热：铝块两端定温",
        "physics": "ht",
        "notes": [
            "最基础的模板：几何 + 材料 + 两个定温面 + 稳态求解。",
            '底面 {"face": "zmin"} 373.15 K，顶面 {"face": "zmax"} 293.15 K，其余面默认绝热。',
            "解析解：无内热源时温度沿 z 线性分布，两端即边界值。",
        ],
        "check": "Tmax = 373.15 K，Tmin = 293.15 K（与施加的边界值一致）",
        "spec": {
            "model": {"name": "HeatBlock", "dimension": 3},
            "geometry": [{"type": "block", "tag": "blk1",
                          "position": [0, 0, 0], "size": [0.1, 0.1, 0.1]}],
            "materials": [ALUMINIUM],
            "physics": [{"type": "ht", "boundary_conditions": [
                {"tag": "hot", "type": "Temperature", "where": {"face": "zmin"},
                 "properties": {"T0": "373.15[K]"}},
                {"tag": "cold", "type": "Temperature", "where": {"face": "zmax"},
                 "properties": {"T0": "293.15[K]"}},
            ]}],
            "mesh": {"tag": "mesh1", "size": 4, "run": True},
            "study": {"tag": "std1", "type": "Stationary"},
            "outputs": [
                {"name": "Tmax", "type": "max", "expression": "T", "unit": "K"},
                {"name": "Tmin", "type": "min", "expression": "T", "unit": "K"},
            ],
        },
    },

    "electrostatics_capacitance": {
        "title": "平行板电容：数值电容 vs 解析解",
        "physics": "es",
        "notes": [
            "10x10x1 mm 介质板，相对介电常数 4.5，顶面 1 V、底面接地。",
            "输出用静电能反推电容：C = 2*W/U^2，U 是施加的电压。",
            "解析解 C = eps0*eps_r*A/d = 8.854e-12 * 4.5 * 1e-4 / 1e-3。",
        ],
        "check": "C = 3.9844 pF（解析解 3.98438 pF；实跑 3.984385 pF，E_max = 1000 V/m = V/d）",
        "spec": {
            "model": {"name": "ParallelPlate", "dimension": 3},
            "geometry": [{"type": "block", "tag": "blk1", "position": [0, 0, 0],
                          "size": [0.01, 0.01, 0.001]}],
            "materials": [{"tag": "mat1", "label": "Dielectric", "domains": "all",
                           "properties": {"relpermittivity": "4.5"}}],
            "physics": [{"type": "es", "boundary_conditions": [
                {"tag": "terminal", "type": "ElectricPotential",
                 "where": {"face": "zmax"}, "properties": {"V0": "1[V]"}},
                {"tag": "ground", "type": "Ground", "where": {"face": "zmin"}},
            ]}],
            "mesh": {"tag": "mesh1", "size": 4, "run": True},
            "study": {"tag": "std1", "type": "Stationary"},
            "outputs": [
                {"name": "C", "type": "global",
                 "expression": "2*es.intWe/(1[V])^2", "unit": "pF"},
                {"name": "Emax", "type": "max", "expression": "es.normE", "unit": "V/m"},
            ],
        },
    },

    "convection_cooled_bar": {
        "title": "对流散热铝棒：一端定温，其余面自然对流",
        "physics": "ht",
        "notes": [
            "演示多面选择：用 faces 一次选多个面做同一个边界条件。",
            '热端 {"face": "zmin"} 373.15 K；其余五个面对流 h=15 W/(m^2*K)、环境 293.15 K。',
            "注意一个面只能给一个边界条件，所以热端要从对流列表里排除。",
        ],
        "check": "Tmax = 373.15 K（热端）；Tmin ≈ 362 K（高于环境 293.15 K，说明对流在起作用）",
        "spec": {
            "model": {"name": "CooledBar", "dimension": 3},
            "geometry": [{"type": "block", "tag": "blk1", "position": [0, 0, 0],
                          "size": [0.01, 0.01, 0.1]}],
            "materials": [ALUMINIUM],
            "physics": [{"type": "ht", "boundary_conditions": [
                {"tag": "hot", "type": "Temperature", "where": {"face": "zmin"},
                 "properties": {"T0": "373.15[K]"}},
                {"tag": "cool", "type": "ConvectiveHeatFlux",
                 "where": {"faces": ["zmax", "xmin", "xmax", "ymin", "ymax"]},
                 "properties": {"h": "15[W/(m^2*K)]", "Text": "293.15[K]"}},
            ]}],
            "mesh": {"tag": "mesh1", "size": 4, "run": True},
            "study": {"tag": "std1", "type": "Stationary"},
            "outputs": [
                {"name": "Tmax", "type": "max", "expression": "T", "unit": "K"},
                {"name": "Tmin", "type": "min", "expression": "T", "unit": "K"},
            ],
        },
    },

    "transient_heat": {
        "title": "瞬态加热：底面热流，顶面对流",
        "physics": "ht",
        "notes": [
            "演示 TimeDependent：热流 q0 = 20000 W/m^2 从底面进入，顶面自然对流。",
            "仅用于看升温趋势，不追求精确定量；要精确就加密网格并给更长的 tlist。",
            "tlist 用 COMSOL 的 range 语法（起点, 步长, 终点）。",
        ],
        "check": "求解成功；Tmax ≈ 476 K（从 293.15 K 升上来），Tmin ≈ 293.15 K",
        "spec": {
            "model": {"name": "TransientHeat", "dimension": 3},
            "geometry": [{"type": "block", "tag": "blk1", "position": [0, 0, 0],
                          "size": [0.05, 0.05, 0.005]}],
            "materials": [ALUMINIUM],
            "physics": [{"type": "ht", "boundary_conditions": [
                {"tag": "flux", "type": "HeatFlux", "where": {"face": "zmin"},
                 "properties": {"q0": "20000[W/m^2]"}},
                {"tag": "cool", "type": "ConvectiveHeatFlux", "where": {"face": "zmax"},
                 "properties": {"h": "15[W/(m^2*K)]", "Text": "293.15[K]"}},
            ]}],
            "mesh": {"tag": "mesh1", "size": 4, "run": True},
            "study": {"tag": "std1", "type": "TimeDependent",
                      "tlist": "range(0,10,120)"},
            "outputs": [
                {"name": "Tmax", "type": "max", "expression": "T", "unit": "K"},
                {"name": "Tmin", "type": "min", "expression": "T", "unit": "K"},
            ],
        },
    },
    "conjugate_heat_transfer": {
        "title": "共轭传热：水冷铝底板（固体导热 + 流道流动换热）",
        "physics": "htf + spf + nitf",
        "notes": [
            '几何必须用 union(keep_interior=true) 把固体域和流体域并起来。不要用 difference 去挖流道——挖出来的空腔会被 union 吞掉，网格里就没有流体域可选了。',
            '域编号由 COMSOL 决定，所以材料和 fluid_domains 都用 {"box": ...} 按坐标选域，不写死编号。',
            'htf 管传热（fluid_domains 标出哪个域走流体），spf 管流动（inlet/outlet），nitf 把两者耦合起来——缺了 nitf 流速不会影响温度。',
            '底面 373.15 K 加热，水从 x=0 以 0.05 m/s、293.15 K 流入，从 x=40 mm 流出。',
            '实测 212 秒解完（网格 size 4）。想快就把 mesh.size 调大（更粗），想准就调小。',
        ],
        "check": "Tmax = 373.15 K（热源面）；Tmin ≈ 292 K（进水 293.15 K，粗网格下入口有约 1 K 过冲）；沿 x 有温度梯度，说明水确实把热带走了",
        "spec": {
            "model": {"name": "ConjugateCooling", "dimension": 3},
            "geometry": [
                {"type": "block", "tag": "base", "position": [0, 0, 0],
                 "size": [0.04, 0.02, 0.004]},
                {"type": "block", "tag": "chan", "position": [0, 0, 0.004],
                 "size": [0.04, 0.02, 0.002]},
            ],
            "union": {"tag": "uni1", "inputs": ["base", "chan"], "keep_interior": True},
            "materials": [
                {"tag": "mat_solid", "label": "Aluminum", "domains": {"box": {"xmin": -1e-6, "xmax": 0.040001, "ymin": -1e-6, "ymax": 0.020001, "zmin": -1e-6, "zmax": 0.004001}},
                 "properties": {"thermalconductivity": "205[W/(m*K)]",
                                "density": "2700[kg/m^3]",
                                "heatcapacity": "900[J/(kg*K)]"}},
                {"tag": "mat_fluid", "label": "Water", "domains": {"box": {"xmin": -1e-6, "xmax": 0.040001, "ymin": -1e-6, "ymax": 0.020001, "zmin": 0.003999, "zmax": 0.006001}},
                 "properties": {"thermalconductivity": "0.6[W/(m*K)]",
                                "density": "1000[kg/m^3]",
                                "heatcapacity": "4180[J/(kg*K)]",
                                "dynamicviscosity": "1e-3[Pa*s]"}},
            ],
            "physics": [
                {"type": "htf", "fluid_domains": {"box": {"xmin": -1e-6, "xmax": 0.040001, "ymin": -1e-6, "ymax": 0.020001, "zmin": 0.003999, "zmax": 0.006001}},
                 "boundary_conditions": [
                     {"tag": "hot", "type": "Temperature", "where": {"face": "zmin"},
                      "properties": {"T0": "373.15[K]"}},
                     {"tag": "inlet_T", "type": "Temperature",
                      "where": {"box": {"xmin": -1e-6, "xmax": 1e-6, "ymin": -1e-6,
                                        "ymax": 0.020001, "zmin": 0.003999, "zmax": 0.006001}},
                      "properties": {"T0": "293.15[K]"}},
                 ]},
                {"type": "spf", "domains": {"box": {"xmin": -1e-6, "xmax": 0.040001, "ymin": -1e-6, "ymax": 0.020001, "zmin": 0.003999, "zmax": 0.006001}},
                 "boundary_conditions": [
                     {"tag": "in", "type": "InletBoundary",
                      "where": {"box": {"xmin": -1e-6, "xmax": 1e-6, "ymin": -1e-6,
                                        "ymax": 0.020001, "zmin": 0.003999, "zmax": 0.006001}},
                      "properties": {"U0in": "0.05[m/s]"}},
                     {"tag": "out", "type": "OutletBoundary",
                      "where": {"box": {"xmin": 0.039999, "xmax": 0.040001, "ymin": -1e-6,
                                        "ymax": 0.020001, "zmin": 0.003999, "zmax": 0.006001}},
                      "properties": {"p0": "0[Pa]"}},
                 ]},
            ],
            "multiphysics": [{"type": "nitf"}],
            "mesh": {"tag": "mesh1", "size": 4, "run": True},
            "study": {"tag": "std1", "type": "Stationary"},
            "outputs": [
                {"name": "Tmax", "type": "max", "expression": "T", "unit": "K"},
                {"name": "Tmin", "type": "min", "expression": "T", "unit": "K"},
                {"name": "Umax", "type": "max", "expression": "spf.U", "unit": "m/s"},
            ],
        },
    },

}


def list_recipes() -> dict:
    return {
        "success": True,
        "count": len(RECIPES),
        "recipes": [
            {"name": name, "title": entry["title"], "physics": entry["physics"],
             "check": entry["check"]}
            for name, entry in RECIPES.items()
        ],
        "hint": ("Call workflow_recipes(name='...') for the full spec, adapt its "
                 "numbers to the user's problem, then workflow_validate_spec -> "
                 "workflow_execute_spec."),
    }


def get_recipe(name: str) -> dict:
    entry = RECIPES.get((name or "").strip())
    if entry is None:
        return {"success": False, "error": f"unknown recipe: {name}",
                "available": sorted(RECIPES)}
    return {
        "success": True,
        "name": name,
        "title": entry["title"],
        "physics": entry["physics"],
        "notes": entry["notes"],
        "check": entry["check"],
        "spec": entry["spec"],
        "how_to_run": [
            "Change the geometry numbers, materials and boundary values to match the user's case.",
            "workflow_validate_spec(spec) - fix any errors it reports.",
            "workflow_execute_spec(spec, solve=True) - it builds and solves in one call.",
        ],
    }


def register_recipe_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def workflow_recipes(name: str = "") -> dict:
        """List verified, copy-ready workflow specs - or fetch one in full.

        Start modelling from one of these instead of writing a spec from
        scratch: each has been run against COMSOL, so it is known to build and
        solve, and its `check` says what the result should look like.

        Args:
            name: Recipe to return in full; omit to list them all (e.g. 'steady_heat_conduction')

        Returns:
            The recipe list, or one recipe's spec plus how to run and verify it.
        """
        if name:
            return get_recipe(name)
        return list_recipes()
