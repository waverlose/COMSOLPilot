"""Structured Java-API workflow tools for COMSOLPilot.

AI-facing rule:
1. AI translates user intent into a structured spec.
2. MCP validates the spec.
3. MCP executes a fixed Java API workflow.

This file is intentionally plain: capability registry, validator, executor, tools.
The main path avoids localized COMSOL labels and uses Java tags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from .session import session_manager


def _norm(value: str) -> str:
    return value.replace(" ", "").replace("_", "").replace("-", "").lower()


_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _leading_number(value: Any) -> float | None:
    """Pull the numeric part out of a COMSOL value string such as '373.15[K]'."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMBER_RE.match(value.strip())
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


@dataclass(frozen=True)
class PhysicsCapability:
    tag: str
    interface: str
    label: str
    aliases: tuple[str, ...]
    boundary_conditions: dict[str, dict[str, Any]]


GEOMETRY_CAPABILITIES: dict[str, dict[str, Any]] = {
    "block": {"comsol_type": "Block", "required": ["tag", "position", "size"]},
    "cylinder": {"comsol_type": "Cylinder", "required": ["tag", "position", "radius", "height"]},
    "sphere": {"comsol_type": "Sphere", "required": ["tag", "position", "radius"]},
}

PHYSICS_CAPABILITIES: dict[str, PhysicsCapability] = {
    "ht": PhysicsCapability(
        tag="ht",
        interface="HeatTransfer",
        label="Heat Transfer in Solids",
        aliases=("HeatTransfer", "Heat Transfer", "Heat Transfer in Solids", "ht"),
        boundary_conditions={
            "TemperatureBoundary": {"feature": "TemperatureBoundary", "property_examples": {"T0": "293.15[K]"}},
            "Temperature": {"feature": "TemperatureBoundary", "property_examples": {"T0": "293.15[K]"}},
            "HeatFluxBoundary": {"feature": "HeatFluxBoundary", "property_examples": {"q0": "1e6[W/m^2]"}},
            "HeatFlux": {"feature": "HeatFluxBoundary", "property_examples": {"q0": "1e6[W/m^2]"}},
            "ConvectiveHeatFlux": {
                "feature": "HeatFluxBoundary",
                "default_properties": {"HeatFluxType": "ConvectiveHeatFlux"},
                "property_examples": {"h": "10[W/(m^2*K)]", "Text": "293.15[K]"},
            },
            "ThermalInsulation": {"feature": "ThermalInsulation", "property_examples": {}},
            "Symmetry": {"feature": "Symmetry", "property_examples": {}},
        },
    ),
    "solid": PhysicsCapability(
        tag="solid",
        interface="SolidMechanics",
        label="Solid Mechanics",
        aliases=("SolidMechanics", "Solid Mechanics", "solid"),
        boundary_conditions={
            "Fixed": {"feature": "Fixed", "property_examples": {}},
            "Roller": {"feature": "Roller", "property_examples": {}},
            "Symmetry": {"feature": "Symmetry", "property_examples": {}},
            "BoundaryLoad": {"feature": "BoundaryLoad", "property_examples": {"FperArea": ["0", "0", "-1e6[Pa]"]}},
        },
    ),
    "es": PhysicsCapability(
        tag="es",
        interface="Electrostatics",
        label="Electrostatics",
        aliases=("Electrostatics", "es"),
        boundary_conditions={
            "Ground": {"feature": "Ground", "property_examples": {}},
            "ElectricPotential": {"feature": "ElectricPotential", "property_examples": {"V0": "5[V]"}},
            "SurfaceChargeDensity": {"feature": "SurfaceChargeDensity", "property_examples": {"rhoqs": "1e-6[C/m^2]"}},
            "ZeroCharge": {"feature": "ZeroCharge", "property_examples": {}},
        },
    ),
    "ec": PhysicsCapability(
        tag="ec",
        interface="ElectricCurrents",
        label="Electric Currents",
        aliases=("ElectricCurrents", "Electric Currents", "ec"),
        boundary_conditions={
            "Ground": {"feature": "Ground", "property_examples": {}},
            "ElectricPotential": {"feature": "ElectricPotential", "property_examples": {"V0": "5[V]"}},
            "ElectricInsulation": {"feature": "ElectricInsulation", "property_examples": {}},
        },
    ),
    "spf": PhysicsCapability(
        tag="spf",
        interface="LaminarFlow",
        label="Laminar Flow",
        aliases=("LaminarFlow", "Laminar Flow", "spf"),
        boundary_conditions={
            "InletBoundary": {"feature": "InletBoundary", "property_examples": {"U0in": "0.01[m/s]"}},
            "OutletBoundary": {"feature": "OutletBoundary", "property_examples": {"p0": "0[Pa]"}},
            "Wall": {"feature": "Wall", "property_examples": {}},
            "Symmetry": {"feature": "Symmetry", "property_examples": {}},
        },
    ),
}

PHYSICS_ALIAS_TO_TAG = {
    _norm(alias): capability.tag
    for capability in PHYSICS_CAPABILITIES.values()
    for alias in capability.aliases
}

STUDY_CAPABILITIES = {
    "Stationary": {"default_step": "stat"},
    "TimeDependent": {"default_step": "time"},
    "FrequencyDomain": {"default_step": "freq"},
    "Eigenfrequency": {"default_step": "eig"},
}

OUTPUT_CAPABILITIES = {"summary", "field", "max", "min", "global", "point"}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _capabilities_payload() -> dict[str, Any]:
    return {
        "spec_schema": {
            "model": "Object: name, dimension=2|3, component='comp1', geometry='geom1'",
            "geometry": "Array of features: block/cylinder/sphere. All coordinates and sizes are SI meters.",
            "union": "Optional boolean or object {tag, inputs}.",
            "materials": "Array of {tag, label, properties, domains}. properties use COMSOL keys.",
            "physics": "Array of {type, boundary_conditions}. type may be alias or tag.",
            "boundary_conditions": "Array of {tag, type, where, properties}. where is box, selection, or boundaries.",
            "where.box": "Object with xmin/xmax/ymin/ymax/zmin/zmax in meters and optional condition.",
            "mesh": "Object: tag='mesh1', size=1..9, run=true.",
            "study": "Object: tag='std1', type='Stationary', step_tag optional.",
            "outputs": "Array of {name, type, expression, unit, raw=false}.",
        },
        "geometry": GEOMETRY_CAPABILITIES,
        "physics": {
            tag: {
                "interface": cap.interface,
                "label": cap.label,
                "aliases": list(cap.aliases),
                "boundary_conditions": cap.boundary_conditions,
            }
            for tag, cap in PHYSICS_CAPABILITIES.items()
        },
        "studies": STUDY_CAPABILITIES,
        "outputs": sorted(OUTPUT_CAPABILITIES),
    }


class SpecValidator:
    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate(self) -> dict[str, Any]:
        if not isinstance(self.spec, dict):
            return {"valid": False, "errors": ["spec must be an object."], "warnings": []}
        self._model()
        self._geometry()
        self._union()
        self._materials()
        self._physics()
        self._study()
        self._outputs()
        return {"valid": not self.errors, "errors": self.errors, "warnings": self.warnings}

    def _model(self) -> None:
        model = self.spec.get("model", {})
        if not isinstance(model, dict):
            self.errors.append("model must be an object.")
            return
        if model.get("dimension", 3) not in (2, 3):
            self.errors.append("model.dimension must be 2 or 3.")

    def _geometry(self) -> None:
        geometry = self.spec.get("geometry", [])
        if not isinstance(geometry, list) or not geometry:
            self.errors.append("geometry must be a non-empty array.")
            return
        tags: set[str] = set()
        for index, feature in enumerate(geometry):
            path = f"geometry[{index}]"
            if not isinstance(feature, dict):
                self.errors.append(f"{path} must be an object.")
                continue
            tag = feature.get("tag")
            if not isinstance(tag, str):
                self.errors.append(f"{path}.tag is required.")
            elif tag in tags:
                self.errors.append(f"{path}.tag duplicates an earlier geometry tag.")
            else:
                tags.add(tag)
            feature_type = feature.get("type")
            if feature_type not in GEOMETRY_CAPABILITIES:
                self.errors.append(f"{path}.type must be one of {sorted(GEOMETRY_CAPABILITIES)}.")
                continue
            for key in GEOMETRY_CAPABILITIES[feature_type]["required"]:
                if key not in feature:
                    self.errors.append(f"{path}.{key} is required.")
            if feature_type == "block":
                self._vector(feature, "position", 3, path)
                self._vector(feature, "size", 3, path)
            elif feature_type == "cylinder":
                self._vector(feature, "position", 3, path)
                self._number(feature, "radius", path)
                self._number(feature, "height", path)
            elif feature_type == "sphere":
                self._vector(feature, "position", 3, path)
                self._number(feature, "radius", path)

    def _union(self) -> None:
        union = self.spec.get("union")
        if union is None or isinstance(union, bool):
            return
        if not isinstance(union, dict):
            self.errors.append("union must be a boolean or object.")
            return
        inputs = union.get("inputs")
        if inputs is not None and (not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs)):
            self.errors.append("union.inputs must be an array of geometry tags.")

    def _materials(self) -> None:
        materials = self.spec.get("materials", [])
        if not isinstance(materials, list):
            self.errors.append("materials must be an array.")
            return
        if not materials:
            self.warnings.append("No materials specified.")
        for index, material in enumerate(materials):
            path = f"materials[{index}]"
            if not isinstance(material, dict):
                self.errors.append(f"{path} must be an object.")
                continue
            if not isinstance(material.get("tag"), str):
                self.errors.append(f"{path}.tag is required.")
            if not isinstance(material.get("properties", {}), dict):
                self.errors.append(f"{path}.properties must be an object.")

    def _physics(self) -> None:
        physics_list = self.spec.get("physics", [])
        if not isinstance(physics_list, list):
            self.errors.append("physics must be an array.")
            return
        if not physics_list:
            self.warnings.append("No physics interfaces specified.")
        for index, physics in enumerate(physics_list):
            path = f"physics[{index}]"
            if not isinstance(physics, dict):
                self.errors.append(f"{path} must be an object.")
                continue
            physics_tag = self._physics_tag(physics.get("type"))
            if physics_tag is None:
                self.errors.append(f"{path}.type must be one of {sorted(PHYSICS_ALIAS_TO_TAG)} aliases.")
                continue
            capability = PHYSICS_CAPABILITIES[physics_tag]
            for bc_index, bc in enumerate(_as_list(physics.get("boundary_conditions"))):
                self._boundary_condition(bc, capability, f"{path}.boundary_conditions[{bc_index}]")

    def _study(self) -> None:
        study = self.spec.get("study", {"type": "Stationary"})
        if not isinstance(study, dict):
            self.errors.append("study must be an object.")
            return
        if study.get("type", "Stationary") not in STUDY_CAPABILITIES:
            self.errors.append(f"study.type must be one of {sorted(STUDY_CAPABILITIES)}.")

    def _outputs(self) -> None:
        outputs = self.spec.get("outputs", [])
        if not isinstance(outputs, list):
            self.errors.append("outputs must be an array.")
            return
        for index, output in enumerate(outputs):
            path = f"outputs[{index}]"
            if not isinstance(output, dict):
                self.errors.append(f"{path} must be an object.")
                continue
            if output.get("type") not in OUTPUT_CAPABILITIES:
                self.errors.append(f"{path}.type must be one of {sorted(OUTPUT_CAPABILITIES)}.")
            if not isinstance(output.get("expression"), str):
                self.errors.append(f"{path}.expression is required.")

    def _boundary_condition(self, bc: Any, capability: PhysicsCapability, path: str) -> None:
        if not isinstance(bc, dict):
            self.errors.append(f"{path} must be an object.")
            return
        if bc.get("type") not in capability.boundary_conditions:
            self.errors.append(f"{path}.type is not supported for physics {capability.tag}.")
        where = bc.get("where")
        if not isinstance(where, dict):
            self.errors.append(f"{path}.where must be an object.")
            return
        if "box" in where:
            box = where["box"]
            if not isinstance(box, dict):
                self.errors.append(f"{path}.where.box must be an object.")
                return
            for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"):
                if not isinstance(box.get(key), (int, float)):
                    self.errors.append(f"{path}.where.box.{key} must be a number in meters.")
        elif "selection" in where:
            if not isinstance(where["selection"], str):
                self.errors.append(f"{path}.where.selection must be a string tag.")
        elif "boundaries" in where:
            if not isinstance(where["boundaries"], list) or not all(isinstance(item, int) for item in where["boundaries"]):
                self.errors.append(f"{path}.where.boundaries must be an array of integers.")
        else:
            self.errors.append(f"{path}.where must contain box, selection, or boundaries.")
        if not isinstance(bc.get("properties", {}), dict):
            self.errors.append(f"{path}.properties must be an object.")

    def _physics_tag(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        return PHYSICS_ALIAS_TO_TAG.get(_norm(value))

    def _vector(self, item: dict, key: str, length: int, path: str) -> None:
        value = item.get(key)
        if not isinstance(value, list) or len(value) != length or not all(isinstance(v, (int, float)) for v in value):
            self.errors.append(f"{path}.{key} must be an array of {length} numbers in meters.")

    def _number(self, item: dict, key: str, path: str) -> None:
        if not isinstance(item.get(key), (int, float)):
            self.errors.append(f"{path}.{key} must be a number in meters.")


class JavaWorkflowExecutor:
    # Ordered stage names, used for progress reporting. Keep in sync with run().
    STAGES: tuple[str, ...] = (
        "model", "geometry", "materials", "physics",
        "mesh", "study", "solve", "outputs",
    )

    def __init__(self, spec: dict[str, Any], solve: bool, collect_outputs: bool,
                 progress: Any = None):
        self.spec = spec
        self.solve = solve
        self.collect_outputs = collect_outputs
        self.progress = progress
        self.log: list[dict[str, Any]] = []
        self.model = None
        self.model_name: str | None = None
        self.component = None
        self.geometry = None

    def _report(self, stage: str) -> None:
        """Push a progress notification; never let it break the workflow.

        The MCP client may not support notifications/progress, and the callback
        may also run outside a request context. Both are expected, not errors.
        """
        if self.progress is None:
            return
        try:
            index = self.STAGES.index(stage) + 1
        except ValueError:
            index = len(self.STAGES)
        try:
            self.progress(index, len(self.STAGES), f"COMSOLPilot: {stage}")
        except Exception:
            pass

    def run(self) -> dict[str, Any]:
        if not session_manager.is_connected:
            return {"success": False, "stage": "session", "error": "No active COMSOL session. Start with comsol_start first."}
        try:
            self._create_model()
            self._report("model")
            self._bootstrap()
            self._geometry_features()
            self._report("geometry")
            self._materials()
            self._report("materials")
            self._physics()
            self._report("physics")
            self._mesh()
            self._report("mesh")
            study_tag = self._study()
            self._report("study")
            solved, solve_error = self._solve(study_tag)
            self._report("solve")
            outputs = self._outputs(solved)
            self._report("outputs")
            return {
                "success": solve_error is None,
                "model": self.model_name,
                "log": self.log,
                "solved": solved,
                "solve_error": solve_error,
                "outputs": outputs,
            }
        except Exception as exc:
            return {"success": False, "stage": "execute", "error": str(exc), "log": self.log}

    def _create_model(self) -> None:
        client = session_manager.client
        if client is None:
            raise RuntimeError("Client not available.")
        name = self.spec.get("model", {}).get("name")
        self.model = session_manager.retry_comsol_busy(lambda: client.create(name))
        self.model_name = session_manager.add_model(self.model)
        session_manager.set_current_model(self.model_name)
        self.log.append({"step": "model_create", "model": self.model_name})

    def _bootstrap(self) -> None:
        model_spec = self.spec.get("model", {})
        component_tag = model_spec.get("component", "comp1")
        geometry_tag = model_spec.get("geometry", "geom1")
        dimension = int(model_spec.get("dimension", 3))
        jm = self.model.java
        components = {comp.tag(): comp for comp in jm.component()}
        self.component = components.get(component_tag) or session_manager.retry_comsol_busy(
            lambda: jm.component().create(component_tag, True)
        )
        geometries = {geom.tag(): geom for geom in self.component.geom()}
        self.geometry = geometries.get(geometry_tag) or session_manager.retry_comsol_busy(
            lambda: self.component.geom().create(geometry_tag, dimension)
        )
        self.log.append({"step": "bootstrap", "component": self.component.tag(), "geometry": self.geometry.tag()})

    def _geometry_features(self) -> None:
        for feature in self.spec.get("geometry", []):
            feature_type = feature["type"]
            existing = {node.tag(): node for node in self.geometry.feature()}
            node = existing.get(feature["tag"]) or session_manager.retry_comsol_busy(
                lambda: self.geometry.feature().create(feature["tag"], GEOMETRY_CAPABILITIES[feature_type]["comsol_type"])
            )
            if feature_type == "block":
                node.set("pos", [str(v) for v in feature["position"]])
                node.set("size", [str(v) for v in feature["size"]])
            elif feature_type == "cylinder":
                node.set("pos", [str(v) for v in feature["position"]])
                node.set("r", str(feature["radius"]))
                node.set("h", str(feature["height"]))
            elif feature_type == "sphere":
                node.set("pos", [str(v) for v in feature["position"]])
                node.set("r", str(feature["radius"]))
            self.log.append({"step": "geometry_add", "tag": feature["tag"], "type": feature_type})
        self._union_if_requested()
        self.geometry.run()
        self.log.append({"step": "geometry_build", "geometry": self.geometry.tag()})

    def _union_if_requested(self) -> None:
        union = self.spec.get("union")
        if not union:
            return
        if isinstance(union, dict):
            tag = union.get("tag", "uni1")
            inputs = union.get("inputs") or [feature["tag"] for feature in self.spec.get("geometry", [])]
        else:
            tag = "uni1"
            inputs = [feature["tag"] for feature in self.spec.get("geometry", [])]
        existing = {node.tag(): node for node in self.geometry.feature()}
        node = existing.get(tag) or session_manager.retry_comsol_busy(
            lambda: self.geometry.feature().create(tag, "Union")
        )
        node.selection("input").set(inputs)
        self.log.append({"step": "geometry_union", "tag": tag, "inputs": inputs})

    def _materials(self) -> None:
        for material_spec in self.spec.get("materials", []):
            existing = {mat.tag(): mat for mat in self.component.material()}
            material = existing.get(material_spec["tag"]) or session_manager.retry_comsol_busy(
                lambda: self.component.material().create(material_spec["tag"], "Common")
            )
            if material_spec.get("label"):
                material.label(material_spec["label"])
            group = material.propertyGroup("def")
            for key, value in material_spec.get("properties", {}).items():
                group.set(str(key), value)
            domains = material_spec.get("domains")
            if isinstance(domains, list):
                material.selection().set([int(domain) for domain in domains])
            elif isinstance(domains, str) and domains != "all":
                material.selection().named(domains)
            self.log.append({"step": "material", "tag": material.tag(), "label": material.label()})

    def _physics(self) -> None:
        for physics_spec in self.spec.get("physics", []):
            physics_tag = PHYSICS_ALIAS_TO_TAG[_norm(physics_spec["type"])]
            capability = PHYSICS_CAPABILITIES[physics_tag]
            existing = {physics.tag(): physics for physics in self.component.physics()}
            physics = existing.get(capability.tag) or session_manager.retry_comsol_busy(
                lambda: self.component.physics().create(capability.tag, capability.interface, self.geometry.tag())
            )
            physics.label(capability.label)
            self.log.append({"step": "physics", "tag": physics.tag(), "type": capability.interface})
            for index, bc_spec in enumerate(_as_list(physics_spec.get("boundary_conditions"))):
                self._boundary_condition(physics, capability, bc_spec, index)

    def _boundary_condition(self, physics, capability: PhysicsCapability, bc_spec: dict[str, Any], index: int) -> None:
        bc_capability = capability.boundary_conditions[bc_spec["type"]]
        feature_type = bc_capability["feature"]
        bc_tag = bc_spec.get("tag") or f"{physics.tag()}bc{index + 1}"
        existing = {feature.tag(): feature for feature in physics.feature()}
        bc = existing.get(bc_tag) or session_manager.retry_comsol_busy(
            lambda: physics.create(bc_tag, feature_type)
        )
        self._apply_where(bc, physics.tag(), bc_spec.get("where", {}), index)
        properties = {
            **bc_capability.get("default_properties", {}),
            **bc_spec.get("properties", {}),
        }
        for key, value in properties.items():
            bc.set(str(key), value)
        self.log.append({
            "step": "boundary_condition",
            "physics": physics.tag(),
            "tag": bc_tag,
            "type": feature_type,
            "requested_type": bc_spec["type"],
        })

    def _apply_where(self, bc, physics_tag: str, where: dict[str, Any], index: int) -> None:
        if "box" in where:
            selection_tag = where.get("selection_name") or f"{physics_tag}_bsel_{index + 1}"
            selection_tag = self._box_selection(selection_tag, where["box"])
            bc.selection().named(selection_tag)
        elif "selection" in where:
            bc.selection().named(where["selection"])
        elif "boundaries" in where:
            bc.selection().set([int(boundary) for boundary in where["boundaries"]])

    # COMSOL's Box "inside" test carries an absolute tolerance (measured ~1e-8 m
    # on COMSOL 6.2): a box drawn exactly on a face matches nothing at all. The
    # original code wrote the requested bounds verbatim, so a box such as
    # z in [-1e-9, 1e-9] produced an empty selection -> the boundary condition
    # covered zero faces -> the stationary system went singular, surfacing either
    # as "not converged" or, worse, as a successful solve with wrong numbers.
    # Expand the box outward in steps and keep the first non-empty match.
    BOX_MARGINS: tuple[float, ...] = (0.0, 1e-8, 1e-6, 1e-4, 1e-3)

    def _box_selection(self, tag: str, box: dict[str, Any]) -> str:
        existing = {sel.tag(): sel for sel in self.component.selection()}
        selection = existing.get(tag) or session_manager.retry_comsol_busy(
            lambda: self.component.selection().create(tag, "Box")
        )
        selection.geom(self.geometry.tag(), 2)
        selection.set("entitydim", "2")
        selection.set("condition", box.get("condition", "inside"))

        span = max(
            abs(float(box["xmax"]) - float(box["xmin"])),
            abs(float(box["ymax"]) - float(box["ymin"])),
            abs(float(box["zmax"]) - float(box["zmin"])),
        ) or 1.0
        # Never grow the box by more than 1% of its own span, so a micro-scale
        # model does not silently swallow neighbouring faces.
        deltas: list[float] = []
        for margin in self.BOX_MARGINS:
            delta = min(margin, 0.01 * span)
            if delta not in deltas:
                deltas.append(delta)

        selected: list[int] = []
        used_delta = 0.0
        for delta in deltas:
            for key, sign in (("xmin", -1.0), ("xmax", 1.0),
                              ("ymin", -1.0), ("ymax", 1.0),
                              ("zmin", -1.0), ("zmax", 1.0)):
                selection.set(key, str(float(box[key]) + sign * delta))
            selected = [int(item) for item in selection.entities()]
            used_delta = delta
            if selected:
                break

        if not selected:
            bounds = {k: box[k] for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax") if k in box}
            raise ValueError(
                f"Box selection '{tag}' matched no boundaries (box={bounds}). "
                "No face fell inside this box even after expanding it. Check the "
                "coordinates, or pick boundaries explicitly with "
                "{\"where\": {\"boundaries\": [...]}}."
            )

        self.log.append({
            "step": "selection_box",
            "tag": tag,
            "entitydim": 2,
            "boundaries": selected,
            "box_margin": used_delta,
        })
        return selection.tag()

    def _mesh(self) -> None:
        mesh_spec = self.spec.get("mesh", {})
        tag = mesh_spec.get("tag", "mesh1")
        existing = {mesh.tag(): mesh for mesh in self.component.mesh()}
        mesh = existing.get(tag) or session_manager.retry_comsol_busy(
            lambda: self.component.mesh().create(tag)
        )
        if mesh_spec.get("size") is not None:
            try:
                mesh.autoMeshSize(int(mesh_spec["size"]))
            except Exception:
                self.log.append({"step": "mesh_size_warning", "tag": mesh.tag(), "requested_size": mesh_spec["size"]})
        if mesh_spec.get("run", True):
            mesh.run()
        self.log.append({"step": "mesh", "tag": mesh.tag(), "ran": mesh_spec.get("run", True)})

    def _study(self) -> str:
        study_spec = self.spec.get("study", {"type": "Stationary"})
        tag = study_spec.get("tag", "std1")
        study_type = study_spec.get("type", "Stationary")
        step_tag = study_spec.get("step_tag") or STUDY_CAPABILITIES[study_type]["default_step"]
        jm = self.model.java
        existing = {study.tag(): study for study in jm.study()}
        study = existing.get(tag) or session_manager.retry_comsol_busy(
            lambda: jm.study().create(tag)
        )
        existing_steps = {step.tag(): step for step in study.feature()}
        if step_tag not in existing_steps:
            session_manager.retry_comsol_busy(lambda: study.feature().create(step_tag, study_type))
        self.log.append({"step": "study", "tag": tag, "type": study_type, "study_step": step_tag})
        return tag

    # Scalar field used to sanity-check a solved model, keyed by physics
    # interface. Only fields with a single unambiguous scalar variable are
    # listed; anything else is simply not verified (no false alarms).
    VERIFY_EXPRESSIONS: dict[str, str] = {
        "HeatTransfer": "T",
        "Electrostatics": "V",
    }

    def _solve(self, study_tag: str) -> tuple[bool, str | None]:
        if not self.solve:
            return False, None
        self._preflight()
        try:
            self.model.java.study(study_tag).run()
            self.log.append({"step": "solve", "study": study_tag, "success": True})
        except Exception as exc:
            self.log.append({"step": "solve", "study": study_tag, "success": False, "error": str(exc)})
            return False, str(exc)

        # A stationary solve can return without raising while being badly
        # under-converged: on a coarse mesh the temperature overshot the applied
        # boundary values (377.59 K against a 373.15 K boundary, i.e. a result
        # that violates the maximum principle). Verify the field against the
        # boundary data and refine the mesh once if it disagrees.
        problem = self._verify_solution()
        if problem is None:
            return True, None

        if self._refine_mesh():
            self.log.append({"step": "solve_retry", "reason": problem})
            try:
                self.model.java.study(study_tag).run()
            except Exception as exc:
                self.log.append({"step": "solve", "study": study_tag, "success": False, "error": str(exc)})
                return False, str(exc)
            problem = self._verify_solution()
            if problem is None:
                self.log.append({"step": "solve", "study": study_tag, "success": True, "verified": True})
                return True, None

        self.log.append({"step": "solve_unverified", "reason": problem})
        return True, problem

    def _preflight(self) -> None:
        """Refuse to solve a model whose boundary conditions select no entities.

        An empty selection silently leaves COMSOL's default insulation in place.
        For a stationary problem that makes the system singular, and the failure
        mode is nasty: either a non-convergence error, or a solve that reports
        success while returning numbers that violate the applied boundary values.
        Checking here turns a silent wrong answer into an immediate, actionable
        error.
        """
        for physics_spec in _as_list(self.spec.get("physics")):
            if not isinstance(physics_spec, dict):
                continue
            tag = PHYSICS_ALIAS_TO_TAG.get(_norm(str(physics_spec.get("type", ""))))
            capability = PHYSICS_CAPABILITIES.get(tag) if tag else None
            if capability is None:
                continue
            physics = {item.tag(): item for item in self.component.physics()}.get(capability.tag)
            if physics is None:
                continue
            features = {item.tag(): item for item in physics.feature()}
            for index, bc_spec in enumerate(_as_list(physics_spec.get("boundary_conditions"))):
                if not isinstance(bc_spec, dict):
                    continue
                bc_tag = bc_spec.get("tag") or f"{capability.tag}bc{index + 1}"
                feature = features.get(bc_tag)
                if feature is None:
                    continue
                try:
                    entities = list(feature.selection().entities())
                except Exception:
                    continue
                if not entities:
                    raise ValueError(
                        f"Boundary condition '{bc_tag}' selects no entities, so the "
                        "default insulation would stay in place and the stationary "
                        "system would be singular. Fix its 'where' clause (check the "
                        "coordinates, or use {\"boundaries\": [...]})."
                    )
        self.log.append({"step": "preflight", "checked": True})

    def _verify_solution(self) -> str | None:
        """Check the solved field against the boundary values that were imposed.

        Returns None when the solution is consistent, or when the model cannot be
        checked automatically. Otherwise returns a human-readable violation.
        """
        import numpy as np

        for physics_spec in _as_list(self.spec.get("physics")):
            if not isinstance(physics_spec, dict):
                continue
            tag = PHYSICS_ALIAS_TO_TAG.get(_norm(str(physics_spec.get("type", ""))))
            capability = PHYSICS_CAPABILITIES.get(tag) if tag else None
            if capability is None:
                continue
            expression = self.VERIFY_EXPRESSIONS.get(capability.interface)
            if expression is None:
                continue

            imposed: list[float] = []
            for bc in _as_list(physics_spec.get("boundary_conditions")):
                if not isinstance(bc, dict):
                    continue
                for value in (bc.get("properties") or {}).values():
                    number = _leading_number(value)
                    if number is not None:
                        imposed.append(number)
            if len(imposed) < 2:
                continue

            try:
                array = np.asarray(self.model.evaluate(expression), dtype=float).reshape(-1)
            except Exception:
                continue
            array = array[np.isfinite(array)]
            if array.size == 0:
                continue

            low, high = min(imposed), max(imposed)
            tolerance = 1e-3 * abs(high - low) + 1e-6
            if array.max() > high + tolerance or array.min() < low - tolerance:
                return (
                    f"solved {expression} spans [{array.min():.4f}, {array.max():.4f}] "
                    f"but the imposed boundary values are [{low:.4f}, {high:.4f}]. "
                    "The solution violates its own boundary data, so the numbers "
                    "must not be used."
                )
        return None

    def _refine_mesh(self) -> bool:
        """One-step mesh refinement used by the solve retry above."""
        mesh_spec = self.spec.setdefault("mesh", {})
        try:
            current = int(mesh_spec.get("size") or 5)
        except (TypeError, ValueError):
            current = 5
        if current <= 1:
            return False
        mesh_spec["size"] = max(1, current - 2)
        mesh_spec["run"] = True
        try:
            self._mesh()
        except Exception:
            return False
        return True

    def _outputs(self, solved: bool) -> list[dict[str, Any]]:
        if not self.collect_outputs or (self.solve and not solved):
            return []
        import numpy as np

        outputs: list[dict[str, Any]] = []
        for output in self.spec.get("outputs", []):
            expression = output["expression"]
            unit = output.get("unit")
            try:
                value = self.model.evaluate(expression, unit=unit, dataset=output.get("dataset"))
                array = np.asarray(value, dtype=float).reshape(-1)
                result = {
                    "success": True,
                    "name": output.get("name"),
                    "type": output["type"],
                    "expression": expression,
                    "unit": unit,
                }
                if output["type"] in {"summary", "field"} and not output.get("raw", False):
                    result["summary"] = {
                        "count": int(array.size),
                        "min": float(np.nanmin(array)),
                        "max": float(np.nanmax(array)),
                        "mean": float(np.nanmean(array)),
                        "sample": array[: int(output.get("sample_size", 10))].tolist(),
                    }
                elif output["type"] in {"max", "min"}:
                    index = int(np.nanargmax(array) if output["type"] == "max" else np.nanargmin(array))
                    result["value"] = float(array[index])
                    result["index"] = index
                    result["position"] = self._position_for_index(index, output.get("dataset"))
                else:
                    result["value"] = array.tolist() if hasattr(value, "tolist") else value
                outputs.append(result)
            except Exception as exc:
                outputs.append({
                    "success": False,
                    "name": output.get("name"),
                    "type": output["type"],
                    "expression": expression,
                    "error": str(exc),
                })
        self.log.append({"step": "outputs", "count": len(outputs)})
        return outputs

    def _position_for_index(self, index: int, dataset: str | None) -> list[float] | None:
        import numpy as np

        try:
            coords = self.model.evaluate(["x", "y", "z"], dataset=dataset)
            arrays = [np.asarray(coord, dtype=float).reshape(-1) for coord in coords]
            if all(array.size > index for array in arrays):
                return [float(array[index]) for array in arrays]
        except Exception:
            return None
        return None


def register_workflow_tools(mcp: FastMCP) -> None:
    """Register structured workflow tools with the MCP server."""

    @mcp.tool()
    def workflow_capabilities() -> dict:
        """
        Return the supported structured workflow schema and capability registry.

        Returns:
            Supported geometry types, physics interfaces, boundary conditions,
            studies, outputs, and the expected spec shape.
        """
        return {"success": True, "capabilities": _capabilities_payload()}

    @mcp.tool()
    def workflow_validate_spec(spec: dict) -> dict:
        """
        Validate a structured simulation spec before touching COMSOL.

        Args:
            spec: Structured simulation specification object

        Returns:
            Validation errors, warnings, and supported schema summary
        """
        result = SpecValidator(spec).validate()
        return {"success": True, **result, "capabilities": _capabilities_payload()}

    @mcp.tool()
    def workflow_execute_spec(
        spec: dict,
        solve: bool = True,
        collect_outputs: bool = True,
        ctx: Context | None = None,
    ) -> dict:
        """
        Execute a structured simulation spec with a fixed Java API workflow.

        Args:
            spec: Structured simulation specification object
            solve: Whether to solve after building the model
            collect_outputs: Whether to evaluate requested outputs after solving

        Returns:
            Execution log, solve status, outputs, or structured error
        """
        validation = SpecValidator(spec).validate()
        if not validation["valid"]:
            return {"success": False, "stage": "validate", **validation, "capabilities": _capabilities_payload()}

        # Push notifications/progress as stages complete. Clients that do not
        # support it simply ignore the notifications; the callback swallows any
        # error so progress reporting can never fail a workflow run.
        progress = None
        if ctx is not None:
            def progress(index: int, total: int, message: str) -> None:
                try:
                    ctx.report_progress(progress=index, total=total, message=message)
                except Exception:
                    pass

        result = JavaWorkflowExecutor(spec, solve=solve, collect_outputs=collect_outputs,
                                      progress=progress).run()
        result["warnings"] = validation["warnings"]
        return result
