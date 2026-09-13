"""Physics tools for COMSOLPilot."""

from typing import Optional, Sequence, Union
from mcp.server.fastmcp import FastMCP

from .session import session_manager


PHYSICS_INTERFACES = {
    "AC/DC": {
        "electrostatic": "Electrostatics (es)",
        "electric_currents": "Electric Currents (ec)",
        "magnetic_fields": "Magnetic Fields (mf)",
        "electromagnetic_waves": "Electromagnetic Waves (emw)",
    },
    "Structural": {
        "solid_mechanics": "Solid Mechanics (solid)",
        "shell": "Shell (shell)",
        "beam": "Beam (beam)",
        "membrane": "Membrane (memb)",
    },
    "Heat Transfer": {
        "heat_transfer": "Heat Transfer in Solids (ht)",
        "htf": "Heat Transfer in Solids and Fluids (htf)",
        "radiation": "Radiation (rad)",
    },
    "Fluid Flow": {
        "laminar_flow": "Laminar Flow (spf)",
        "turbulent_flow": "Turbulent Flow (spf)",
        "creeping_flow": "Creeping Flow (brinkman)",
    },
    "Acoustics": {
        "pressure_acoustics": "Pressure Acoustics (acpr)",
        "thermoacoustics": "Thermoacoustics (ta)",
    },
    "Chemical": {
        "transport_diluted": "Transport of Diluted Species (tds)",
        "reaction_engineering": "Reaction Engineering (re)",
    },
    "Optics": {
        "ray_optics": "Geometrical Optics (gop)",
        "wave_optics": "Wave Optics (ewfd)",
    },
    "Multiphysics": {
        "thermal_stress": "Thermal Stress (ts)",
        "fluid_structure": "Fluid-Structure Interaction (fsi)",
        "electromechanical": "Electromechanical Forces",
        "joule_heating": "Joule Heating (jh)",
        "nonisothermal": "Non-Isothermal Flow (nitf)",
    },
}


PHYSICS_TYPE_MAP = {
    "electrostatics": ("es", "Electrostatics", "Electrostatics"),
    "es": ("es", "Electrostatics", "Electrostatics"),
    "electriccurrents": ("ec", "ElectricCurrents", "Electric Currents"),
    "ec": ("ec", "ElectricCurrents", "Electric Currents"),
    "solidmechanics": ("solid", "SolidMechanics", "Solid Mechanics"),
    "solid": ("solid", "SolidMechanics", "Solid Mechanics"),
    "heattransfer": ("ht", "HeatTransfer", "Heat Transfer in Solids"),
    "ht": ("ht", "HeatTransfer", "Heat Transfer in Solids"),
    "heattransferfluids": ("ht", "HeatTransferInSolidsAndFluids", "Heat Transfer in Solids and Fluids"),
    "htf": ("ht", "HeatTransferInSolidsAndFluids", "Heat Transfer in Solids and Fluids"),
    "conjugateheattransfer": ("ht", "HeatTransferInSolidsAndFluids", "Heat Transfer in Solids and Fluids"),
    "cht": ("ht", "HeatTransferInSolidsAndFluids", "Heat Transfer in Solids and Fluids"),
    "laminarflow": ("spf", "LaminarFlow", "Laminar Flow"),
    "spf": ("spf", "LaminarFlow", "Laminar Flow"),
    "transportofdilutedspecies": ("tds", "TransportOfDilutedSpecies", "Transport of Diluted Species"),
    "tds": ("tds", "TransportOfDilutedSpecies", "Transport of Diluted Species"),
    "magneticfields": ("mf", "MagneticFields", "Magnetic Fields"),
    "mf": ("mf", "MagneticFields", "Magnetic Fields"),
}


BOUNDARY_CONDITION_TYPES = {
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
}

DomainSelection = Optional[Union[str, Sequence[int]]]


def _first_component(jm):
    for comp in jm.component():
        return comp
    return None


def _first_geometry(comp):
    for geom in comp.geom():
        return geom
    return None


def _supported_physics_types() -> list[str]:
    return sorted({value for key in PHYSICS_TYPE_MAP for value in (key, PHYSICS_TYPE_MAP[key][0], PHYSICS_TYPE_MAP[key][1])})


def _available_physics(jm) -> list[dict]:
    available = []
    for comp in jm.component():
        for physics in comp.physics():
            available.append({
                "component": comp.tag(),
                "tag": physics.tag(),
                "label": physics.label(),
            })
    return available


def _find_physics(model, physics_name: str, preferred_tag: Optional[str] = None):
    jm = model.java
    # Resolve interface type aliases first: "htf" is the type
    # (HeatTransferInSolidsAndFluids) while the created node is tagged "ht".
    wanted_tags = set()
    key = str(physics_name).replace(" ", "").replace("_", "").lower()
    entry = PHYSICS_TYPE_MAP.get(key)
    if entry:
        wanted_tags.add(entry[0])
    for comp in jm.component():
        for physics in comp.physics():
            candidates = {physics.tag(), physics.label()}
            type_name = ""
            try:
                type_name = str(physics.getType())
            except Exception:
                try:
                    type_name = str(physics.type())
                except Exception:
                    type_name = ""
            if type_name:
                candidates.add(type_name)
            if physics_name in candidates or physics_name in physics.label():
                return comp, physics, None
            if physics.tag() in wanted_tags:
                return comp, physics, None
            if preferred_tag and physics.tag() == preferred_tag:
                return comp, physics, None
    return None, None, _available_physics(jm)


def _next_bc_tag(physics, prefix: str = "bc") -> str:
    """Generate a free boundary-condition tag such as 'bc1'.

    physics.feature() returns a Java PhysicsFeatureListClient, which supports
    neither len() nor reliable indexing, so enumerate tags instead.
    """
    existing = set()
    try:
        for tag in physics.feature().tags():
            existing.add(str(tag))
    except Exception:
        try:
            for feature in physics.feature():
                try:
                    existing.add(str(feature.tag()))
                except Exception:
                    pass
        except Exception:
            existing = set()
    index = 1
    while f"{prefix}{index}" in existing:
        index += 1
    return f"{prefix}{index}"


def _apply_domain_selection(selection, domain_selection: DomainSelection) -> None:
    if domain_selection is None:
        return
    if isinstance(domain_selection, str):
        selection.named(domain_selection)
    else:
        selection.set([int(domain) for domain in domain_selection])


def _add_physics_interface(
    model,
    physics_type: str,
    component_name: Optional[str] = None,
    domain_selection: DomainSelection = None,
) -> dict:
    """Create physics through the component Java API; model.create('physics', ...) is unreliable."""
    jm = model.java
    key = physics_type.replace(" ", "").replace("_", "").lower()
    if key not in PHYSICS_TYPE_MAP:
        return {
            "success": False,
            "error": f"Unsupported physics_type: {physics_type}",
            "supported_physics_types": _supported_physics_types(),
        }
    tag, interface, default_label = PHYSICS_TYPE_MAP[key]

    comp = jm.component(component_name) if component_name else _first_component(jm)
    if comp is None:
        return {"success": False, "error": "No component found. Create one first with model_create_component."}

    geom = _first_geometry(comp)
    if geom is None:
        return {"success": False, "error": f"No geometry found in component '{comp.tag()}'."}

    existing = {p.tag(): p for p in comp.physics()}
    if tag in existing:
        physics = existing[tag]
        created = False
    else:
        physics = comp.physics().create(tag, interface, geom.tag())
        physics.label(default_label)
        created = True

    if domain_selection:
        try:
            _apply_domain_selection(physics.selection(), domain_selection)
        except Exception:
            return {"success": False, "error": f"Domain selection not found or invalid: {domain_selection}"}

    return {
        "success": True,
        "physics": {
            "name": physics.label(),
            "type": interface,
            "tag": physics.tag(),
            "component": comp.tag(),
            "geometry": geom.tag(),
            "domain_selection": domain_selection,
            "created": created,
        },
    }


def register_physics_tools(mcp: FastMCP) -> None:
    """Register physics tools with the MCP server."""
    
    @mcp.tool()
    def physics_list(model_name: Optional[str] = None) -> dict:
        """
        List all physics interfaces defined in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of physics interface names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            physics = model.physics()
            multiphysics = model.multiphysics()
            
            return {
                "success": True,
                "physics": physics,
                "multiphysics": multiphysics,
                "physics_count": len(physics),
                "multiphysics_count": len(multiphysics),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list physics: {str(e)}"}
    
    @mcp.tool()
    def physics_get_available() -> dict:
        """
        Get a list of available physics interfaces organized by category.
        
        Returns:
            Dictionary of physics categories and their interfaces
        """
        return {
            "success": True,
            "interfaces": PHYSICS_INTERFACES,
            "note": "Interface identifiers (in parentheses) are used when adding physics.",
        }
    
    @mcp.tool()
    def physics_add(
        physics_type: str,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a physics interface to the model.
        
        Common physics types:
        - "Electrostatics" or "es": Electrostatic field analysis
        - "ElectricCurrents" or "ec": Electric current conduction
        - "SolidMechanics" or "solid": Structural stress analysis
        - "HeatTransfer" or "ht": Heat transfer in solids
        - "HeatTransferInSolidsAndFluids" or "htf": heat transfer in solids AND fluids
          (conjugate heat transfer; the kernel type "ConjugateHeatTransfer" does NOT exist)
        - "LaminarFlow" or "spf": Fluid dynamics
        
        Args:
            physics_type: Type identifier (e.g., "Electrostatics", "es")
            component_name: Component to add physics to (default: first component)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics interface info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _add_physics_interface(model, physics_type, component_name=component_name)
        except Exception as e:
            return {"success": False, "error": f"Failed to add physics: {str(e)}"}
    
    @mcp.tool()
    def physics_add_electrostatics(
        domain_selection: DomainSelection = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add Electrostatics physics interface for electric field analysis.
        
        Args:
            domain_selection: Selection name for domains (default: all domains)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _add_physics_interface(model, "Electrostatics", domain_selection=domain_selection)
        except Exception as e:
            return {"success": False, "error": f"Failed to add Electrostatics: {str(e)}"}
    
    @mcp.tool()
    def physics_add_solid_mechanics(
        domain_selection: DomainSelection = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add Solid Mechanics physics for structural analysis.
        
        Args:
            domain_selection: Selection name for domains (default: all domains)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _add_physics_interface(model, "SolidMechanics", domain_selection=domain_selection)
        except Exception as e:
            return {"success": False, "error": f"Failed to add Solid Mechanics: {str(e)}"}
    
    @mcp.tool()
    def physics_add_heat_transfer(
        domain_selection: DomainSelection = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add Heat Transfer physics for thermal analysis.
        
        Args:
            domain_selection: Selection name for domains (default: all domains)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _add_physics_interface(model, "HeatTransfer", domain_selection=domain_selection)
        except Exception as e:
            return {"success": False, "error": f"Failed to add Heat Transfer: {str(e)}"}
    
    @mcp.tool()
    def physics_add_laminar_flow(
        domain_selection: DomainSelection = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add Laminar Flow physics for fluid dynamics.
        
        Args:
            domain_selection: Selection name for domains (default: all domains)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _add_physics_interface(model, "LaminarFlow", domain_selection=domain_selection)
        except Exception as e:
            return {"success": False, "error": f"Failed to add Laminar Flow: {str(e)}"}
    
    @mcp.tool()
    def physics_configure_boundary(
        physics_name: str,
        boundary_condition: str,
        boundary_selection: Sequence[int],
        properties: Optional[dict] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Configure a boundary condition for a physics interface.
        
        Common boundary conditions for Electrostatics:
        - "Ground": Zero potential boundary
        - "ElectricPotential": Specified voltage
        - "SurfaceChargeDensity": Surface charge
        - "ZeroCharge": Zero normal displacement field
        
        Common for Solid Mechanics:
        - "Fixed": Fixed constraint
        - "Roller": Roller constraint
        - "Symmetry": Symmetry plane
        - "BoundaryLoad": Applied force/pressure
        
        Common for Heat Transfer:
        - "Temperature": Fixed temperature
        - "HeatFlux": Heat flux boundary
        - "ConvectiveHeatFlux": Convection cooling
        - "Symmetry": Symmetry (adiabatic)
        
        Args:
            physics_name: Name of the physics interface
            boundary_condition: Type of boundary condition
            boundary_selection: Boundary/edge numbers to apply condition to
            properties: Dictionary of property names and values
            model_name: Model name (default: current model)
        
        Returns:
            Created boundary condition info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            if boundary_condition not in BOUNDARY_CONDITION_TYPES:
                return {
                    "success": False,
                    "error": f"Unsupported boundary_condition: {boundary_condition}",
                    "supported_boundary_conditions": sorted(BOUNDARY_CONDITION_TYPES),
                }
            
            _, physics, available = _find_physics(model, physics_name)
            if physics is None:
                return {"success": False, "error": f"Physics interface not found: {physics_name}", "available_physics": available}
            
            tag = _next_bc_tag(physics)
            bc_node = physics.create(tag, boundary_condition)
            bc_node.selection().set([int(boundary) for boundary in boundary_selection])
            
            if properties:
                for prop_name, prop_value in properties.items():
                    try:
                        bc_node.set(prop_name, prop_value)
                    except Exception:
                        pass
            
            return {
                "success": True,
                "boundary_condition": {
                    "name": bc_node.label() if hasattr(bc_node, 'label') else boundary_condition,
                    "tag": tag,
                    "type": boundary_condition,
                    "physics": physics.tag(),
                    "selection": list(boundary_selection),
                    "properties": properties,
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to configure boundary: {str(e)}"}
    
    @mcp.tool()
    def physics_set_material(
        physics_name: str,
        material_name: str,
        domain_selection: DomainSelection = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Assign a material to physics domains.
        
        Args:
            physics_name: Name of the physics interface
            material_name: Name of the material to assign
            domain_selection: Domain numbers (default: all domains for this physics)
            model_name: Model name (default: current model)
        
        Returns:
            Assignment confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            materials = model.materials()
            if material_name not in materials:
                return {
                    "success": False,
                    "error": f"Material not found: {material_name}",
                    "available_materials": materials,
                }
            
            _, physics, available = _find_physics(model, physics_name)
            if physics is None:
                return {"success": False, "error": f"Physics interface not found: {physics_name}", "available_physics": available}
            
            return {
                "success": True,
                "message": f"Material '{material_name}' should be configured to cover the required domains.",
                "physics": {"tag": physics.tag(), "label": physics.label()},
                "domain_selection": domain_selection,
                "note": "Use COMSOL GUI or low-level API for detailed material assignment.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to set material: {str(e)}"}
    
    @mcp.tool()
    def multiphysics_add(
        coupling_type: str,
        physics_list: Sequence[str],
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a multiphysics coupling between physics interfaces.
        
        Common coupling types:
        - "ThermalStress": Couples Heat Transfer and Solid Mechanics
        - "FluidStructureInteraction": Couples Fluid Flow and Solid Mechanics
        - "ElectromechanicalForces": Couples Electrostatics and Solid Mechanics
        - "JouleHeating": Couples Electric Currents and Heat Transfer
        - "NonIsothermalFlow": Couples Laminar Flow and Heat Transfer in
          Solids and Fluids (aliases accepted: "nitf", "cht",
          "conjugateheattransfer")
        
        Args:
            coupling_type: Type of multiphysics coupling
            physics_list: Names of physics interfaces to couple
            model_name: Model name (default: current model)
        
        Returns:
            Created coupling info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            aliases = {
                "nitf": "NonIsothermalFlow",
                "nonisothermal": "NonIsothermalFlow",
                "nonisothermalflow": "NonIsothermalFlow",
                "conjugateheattransfer": "NonIsothermalFlow",
                "cht": "NonIsothermalFlow",
            }
            coupling_type = aliases.get(coupling_type.lower(), coupling_type)

            # Multiphysics couplings live under the component and need the
            # geometry tag; the old model.create("multiphysics", type) call
            # raised a JPype overload error, so NonIsothermalFlow could never
            # be created through this tool.
            jm = model.java
            comp = None
            for candidate in jm.component():
                comp = candidate
                break
            if comp is None:
                return {"success": False, "error": "Model has no component."}
            geometry_tag = None
            try:
                geometry_tag = next(iter(comp.geom())).tag()
            except Exception:
                geometry_tag = "geom1"

            tag = {"NonIsothermalFlow": "nitf"}.get(coupling_type, coupling_type[:4].lower())
            existing = {}
            try:
                existing = {str(item.tag()): item for item in comp.multiphysics()}
            except Exception:
                pass
            if tag in existing:
                coupling_node = existing[tag]
                created = False
            else:
                coupling_node = session_manager.retry_comsol_busy(
                    lambda: comp.multiphysics().create(tag, coupling_type, str(geometry_tag)))
                created = True

            # Point the coupling at the requested physics interfaces when the
            # coupling exposes selection properties for them.
            warnings = []
            for index, interface in enumerate(physics_list or [], start=1):
                for prop in (f"physics{index}", f"phys{index}"):
                    try:
                        coupling_node.set(prop, str(interface))
                        break
                    except Exception:
                        continue

            return {
                "success": True,
                "coupling": {
                    "name": coupling_node.name() if hasattr(coupling_node, "name") else tag,
                    "tag": tag,
                    "type": coupling_type,
                    "geometry": str(geometry_tag),
                    "created": created,
                    "physics": list(physics_list),
                },
                "property_warnings": warnings,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add multiphysics: {str(e)}"}
    
    @mcp.tool()
    @mcp.tool()
    def physics_set_domain_selection(
        physics_name: str,
        domains: Optional[Sequence[int]] = None,
        selection_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Set which domains a physics interface applies to.

        This is the missing half of "add a physics interface": Laminar Flow on
        a solid+fluid geometry must be restricted to the fluid domains, and Heat
        Transfer in Solids and Fluids needs both. Without an explicit selection
        an interface can cover every domain or none, which shows up as a solve
        that "completes" while the fluid variables are undefined/NaN.

        Args:
            physics_name: Physics interface tag or label (e.g. "spf")
            domains: Domain numbers to apply the interface to
            selection_name: Existing named selection to use instead of numbers
            model_name: Model name (default: current model)

        Returns:
            The selection now in effect, with its size
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {"success": False, "error": f"Model not found: {model_name or 'no current model'}"}
        if not domains and not selection_name:
            return {"success": False, "error": "Pass 'domains' or 'selection_name'."}

        try:
            comp, physics, available = _find_physics(model, physics_name)
            if physics is None:
                return {"success": False,
                        "error": f"Physics not found: {physics_name}",
                        "available_physics": available}
            selection = physics.selection()
            if selection_name:
                selection.named(str(selection_name))
                applied = {"selection": selection_name}
            else:
                selection.set([int(d) for d in domains])
                applied = {"domains": [int(d) for d in domains]}
            try:
                entities = [int(e) for e in selection.entities()]
            except Exception:
                entities = None
            return {
                "success": True,
                "physics": physics.tag(),
                "applied": applied,
                "domain_count": len(entities) if entities is not None else None,
                "domains": entities,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to set domain selection: {str(e)}"}


    def physics_list_features(
        physics_name: str,
        model_name: Optional[str] = None
    ) -> dict:
        """
        List all features (boundary conditions, domain settings) in a physics interface.
        
        Args:
            physics_name: Name of the physics interface
            model_name: Model name (default: current model)
        
        Returns:
            List of physics features
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            physics_interfaces = model.physics()
            if physics_name not in physics_interfaces:
                return {"success": False, "error": f"Physics interface not found: {physics_name}"}
            
            physics_node = model / "physics" / physics_name
            features = []
            
            for child in physics_node.children():
                feat_info = {"name": child.name()}
                try:
                    feat_info["type"] = child.type() if hasattr(child, 'type') else "unknown"
                except Exception:
                    pass
                features.append(feat_info)
            
            return {
                "success": True,
                "physics": physics_name,
                "features": features,
                "count": len(features),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list features: {str(e)}"}
    
    @mcp.tool()
    def physics_remove(
        physics_name: str,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Remove a physics interface from the model.
        
        Args:
            physics_name: Name of the physics interface to remove
            model_name: Model name (default: current model)
        
        Returns:
            Removal confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            physics_interfaces = model.physics()
            if physics_name not in physics_interfaces:
                return {"success": False, "error": f"Physics interface not found: {physics_name}"}
            
            physics_node = model / "physics" / physics_name
            model.remove(physics_node)
            
            return {
                "success": True,
                "removed": physics_name,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to remove physics: {str(e)}"}
    
    @mcp.tool()
    def geometry_get_boundaries(
        geometry_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Get all boundaries from a geometry with their properties.
        
        Use this to identify which boundary numbers correspond to which faces
        before setting boundary conditions.
        
        Args:
            geometry_name: Geometry sequence name (default: first geometry)
            model_name: Model name (default: current model)
        
        Returns:
            List of boundaries with their numbers and areas
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geometries = model.geometries()
            if not geometries:
                return {"success": False, "error": "No geometries found"}
            
            target_geom = geometry_name or geometries[0]
            jm = model.java
            
            # Get component
            comp = None
            for c in jm.component():
                if target_geom in [g.tag() for g in c.geom()]:
                    comp = c
                    break
            
            if comp is None:
                return {"success": False, "error": "Geometry not found in components"}
            
            geom = comp.geom(target_geom)
            geom.run()
            
            # GeomSequenceClient exposes entity counts directly; there is no geom.info().
            boundary_count = int(geom.getNBoundaries())
            domain_count = int(geom.getNDomains())
            entity_counts = list(geom.getNEntities())
            bounding_box = list(geom.getBoundingBox())
            boundaries = [{"boundary_number": i} for i in range(1, boundary_count + 1)]
            
            return {
                "success": True,
                "geometry": target_geom,
                "total_boundaries": boundary_count,
                "total_domains": domain_count,
                "entity_counts": {
                    "vertices": int(entity_counts[0]) if len(entity_counts) > 0 else None,
                    "edges": int(entity_counts[1]) if len(entity_counts) > 1 else None,
                    "boundaries": int(entity_counts[2]) if len(entity_counts) > 2 else boundary_count,
                    "domains": int(entity_counts[3]) if len(entity_counts) > 3 else domain_count,
                },
                "bounding_box": {
                    "xmin": bounding_box[0],
                    "xmax": bounding_box[1],
                    "ymin": bounding_box[2],
                    "ymax": bounding_box[3],
                    "zmin": bounding_box[4] if len(bounding_box) > 4 else None,
                    "zmax": bounding_box[5] if len(bounding_box) > 5 else None,
                },
                "boundaries": boundaries,
                "hint": "Use boundary numbers for simple cases, or coordinate Box selections for robust face targeting.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to get boundaries: {str(e)}"}
    
    @mcp.tool()
    def geometry_select_boundaries_by_box(
        xmin: float,
        xmax: float,
        ymin: float,
        ymax: float,
        zmin: float,
        zmax: float,
        selection_name: Optional[str] = None,
        geometry_name: Optional[str] = None,
        component_name: Optional[str] = None,
        condition: str = "inside",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create a boundary selection from a coordinate box.
        
        Use this instead of guessing boundary numbers. Coordinates are in meters.
        
        Args:
            xmin: Minimum x coordinate in meters
            xmax: Maximum x coordinate in meters
            ymin: Minimum y coordinate in meters
            ymax: Maximum y coordinate in meters
            zmin: Minimum z coordinate in meters
            zmax: Maximum z coordinate in meters
            selection_name: Selection tag to create (auto-generated if None)
            geometry_name: Geometry sequence tag (default: first geometry in component)
            component_name: Component tag (default: first component)
            condition: Box selection condition, usually 'inside' or 'intersects'
            model_name: Model name (default: current model)
        
        Returns:
            Selection tag and selected boundary numbers when COMSOL exposes them
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            jm = model.java
            comp = jm.component(component_name) if component_name else _first_component(jm)
            if comp is None:
                return {"success": False, "error": "No component found. Create one first with model_create_component."}
            
            geom = comp.geom(geometry_name) if geometry_name else _first_geometry(comp)
            if geom is None:
                return {"success": False, "error": f"No geometry found in component '{comp.tag()}'."}
            geom.run()
            
            tag = selection_name or f"bsel{comp.selection().size()+1}"
            existing = {sel.tag(): sel for sel in comp.selection()}
            if tag in existing:
                selection = existing[tag]
            else:
                selection = comp.selection().create(tag, "Box")
            
            # Entity dimension 2 means boundaries in 3D, edges in 2D.
            selection.geom(geom.tag(), 2)
            selection.set("entitydim", "2")
            selection.set("condition", condition)

            # COMSOL's Box "inside" test has an absolute tolerance (~1e-8 m on
            # COMSOL 6.2), so a box drawn exactly on a face matches nothing.
            # Writing the requested bounds verbatim therefore produced an empty
            # selection and a boundary condition on zero faces. Expand the box
            # outward in steps and keep the first non-empty match.
            span = max(abs(xmax - xmin), abs(ymax - ymin), abs(zmax - zmin)) or 1.0
            deltas: list[float] = []
            for margin in (0.0, 1e-8, 1e-6, 1e-4, 1e-3):
                delta = min(margin, 0.01 * span)
                if delta not in deltas:
                    deltas.append(delta)

            selected_boundaries = None
            used_margin = 0.0
            for delta in deltas:
                selection.set("xmin", str(xmin - delta))
                selection.set("xmax", str(xmax + delta))
                selection.set("ymin", str(ymin - delta))
                selection.set("ymax", str(ymax + delta))
                selection.set("zmin", str(zmin - delta))
                selection.set("zmax", str(zmax + delta))
                used_margin = delta
                for getter in (
                    lambda: list(selection.entities(2)),
                    lambda: list(selection.entities()),
                ):
                    try:
                        selected_boundaries = [int(item) for item in getter()]
                        break
                    except Exception:
                        selected_boundaries = None
                if selected_boundaries:
                    break
            
            return {
                "success": True,
                "selection": tag,
                "component": comp.tag(),
                "geometry": geom.tag(),
                "entity_dimension": 2,
                "box": {
                    "xmin": xmin,
                    "xmax": xmax,
                    "ymin": ymin,
                    "ymax": ymax,
                    "zmin": zmin,
                    "zmax": zmax,
                },
                "condition": condition,
                "boundary_numbers": selected_boundaries,
                "next_step": "Use physics_boundary_named_selection with this selection tag, or boundary_numbers if returned.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to select boundaries by box: {str(e)}"}
    
    @mcp.tool()
    def physics_boundary_named_selection(
        physics_name: str,
        boundary_condition_type: str,
        selection_name: str,
        properties: Optional[dict] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Apply a boundary condition to a named boundary selection.
        
        This avoids brittle boundary-number guessing when geometry selectors are
        available.
        
        Args:
            physics_name: Physics interface tag or label, for example 'ht'
            boundary_condition_type: COMSOL boundary condition type
            selection_name: Existing boundary selection tag
            properties: Boundary condition property dictionary
            model_name: Model name (default: current model)
        
        Returns:
            Boundary condition creation status
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            if boundary_condition_type not in BOUNDARY_CONDITION_TYPES:
                return {
                    "success": False,
                    "error": f"Unsupported boundary_condition_type: {boundary_condition_type}",
                    "supported_boundary_conditions": sorted(BOUNDARY_CONDITION_TYPES),
                }
            
            _, physics, available = _find_physics(model, physics_name)
            if physics is None:
                return {"success": False, "error": f"Physics '{physics_name}' not found.", "available_physics": available}
            
            properties = properties or {}
            tag = _next_bc_tag(physics)
            bc = physics.create(tag, boundary_condition_type)
            bc.selection().named(selection_name)
            
            for prop_name, prop_value in properties.items():
                try:
                    bc.set(prop_name, prop_value)
                except Exception:
                    pass
            
            bc.label(f"{boundary_condition_type} ({selection_name})")
            
            return {
                "success": True,
                "physics": physics.tag(),
                "boundary_condition": {
                    "type": boundary_condition_type,
                    "tag": tag,
                    "selection": selection_name,
                    "properties": properties,
                },
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to apply named boundary selection: {str(e)}"}
    
    @mcp.tool()
    def physics_interactive_setup_flow(
        physics_name: str = "Laminar Flow",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Interactive setup wizard for Laminar Flow boundary conditions.
        
        This tool helps identify and configure flow boundary conditions:
        1. Lists all available boundaries
        2. Prompts user to select inlet, outlet, and wall boundaries
        3. Configures appropriate boundary conditions
        
        Args:
            physics_name: Name of the Laminar Flow physics interface
            model_name: Model name (default: current model)
        
        Returns:
            Boundary information and setup instructions
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            # Get geometry boundaries
            boundaries_info = geometry_get_boundaries(None, model_name)
            if not boundaries_info.get("success"):
                return boundaries_info
            
            return {
                "success": True,
                "message": "Interactive Flow Setup - Please specify boundaries",
                "available_boundaries": boundaries_info["total_boundaries"],
                "boundaries": boundaries_info["boundaries"],
                "setup_instructions": {
                    "step1": "Identify which boundary numbers are INLETS (flow enters)",
                    "step2": "Identify which boundary numbers are OUTLETS (flow exits)",
                    "step3": "Use physics_configure_boundary to set conditions",
                },
                "boundary_condition_types": {
                    "InletBoundary": "Set inlet velocity (U0in parameter in COMSOL 6.x)",
                    "OutletBoundary": "Set outlet pressure (p0 parameter, default 0)",
                    "Wall": "No-slip wall (default for unspecified boundaries)",
                    "Symmetry": "Symmetry plane",
                },
                "example_usage": {
                    "inlet": "physics_configure_boundary(physics_name='Laminar Flow', boundary_condition='InletBoundary', boundary_selection=[1, 2], properties={'U0in': '1[mm/s]'})",
                    "outlet": "physics_configure_boundary(physics_name='Laminar Flow', boundary_condition='OutletBoundary', boundary_selection=[3])",
                },
                "next_step": "Please tell me which boundary numbers to use for inlet(s) and outlet(s)",
            }
        except Exception as e:
            return {"success": False, "error": f"Interactive setup failed: {str(e)}"}
    
    @mcp.tool()
    def physics_setup_flow_boundaries(
        physics_name: str,
        inlet_boundaries: Sequence[int],
        outlet_boundaries: Sequence[int],
        inlet_velocity: str = "1[mm/s]",
        outlet_pressure: str = "0",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Setup Laminar Flow boundary conditions with specified boundaries.
        
        This tool configures inlet velocity and outlet pressure boundary conditions
        for a fluid flow simulation.
        
        Args:
            physics_name: Name of the Laminar Flow physics interface
            inlet_boundaries: List of boundary numbers for inlets
            outlet_boundaries: List of boundary numbers for outlets
            inlet_velocity: Inlet velocity expression (default: "1[mm/s]")
            outlet_pressure: Outlet pressure expression (default: "0")
            model_name: Model name (default: current model)
        
        Returns:
            Configuration confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            _, physics, available = _find_physics(model, physics_name, preferred_tag="spf")
            if physics is None:
                return {"success": False, "error": f"Physics '{physics_name}' not found.", "available_physics": available}
            
            results = {"inlets": [], "outlets": []}
            
            # Add inlet boundary conditions
            for i, boundary in enumerate(inlet_boundaries):
                inlet_tag = f'inl{i+1}'
                inlet = physics.create(inlet_tag, 'InletBoundary')
                inlet.selection().set([int(boundary)])
                # COMSOL 6.x exposes normal inlet velocity as U0in, not U0.
                inlet.set('U0in', inlet_velocity)
                inlet.label(f'Inlet {i+1} (Boundary {boundary})')
                results["inlets"].append({
                    "tag": inlet_tag,
                    "boundary": boundary,
                    "velocity": inlet_velocity
                })
            
            # Add outlet boundary conditions
            for i, boundary in enumerate(outlet_boundaries):
                outlet_tag = f'out{i+1}'
                outlet = physics.create(outlet_tag, 'OutletBoundary')
                outlet.selection().set([int(boundary)])
                outlet.set('p0', outlet_pressure)
                outlet.label(f'Outlet {i+1} (Boundary {boundary})')
                results["outlets"].append({
                    "tag": outlet_tag,
                    "boundary": boundary,
                    "pressure": outlet_pressure
                })
            
            return {
                "success": True,
                "physics": physics_name,
                "configured_boundaries": results,
                "inlet_velocity": inlet_velocity,
                "outlet_pressure": outlet_pressure,
                "message": f"Configured {len(inlet_boundaries)} inlet(s) and {len(outlet_boundaries)} outlet(s)",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to setup boundaries: {str(e)}"}

    @mcp.tool()
    def physics_interactive_setup_heat(
        physics_name: str = "Heat Transfer in Solids",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Interactive setup wizard for Heat Transfer boundary conditions.
        
        This tool helps identify and configure thermal boundary conditions:
        1. Lists all available boundaries
        2. Shows typical boundary condition types for thermal analysis
        3. Provides setup instructions
        
        Args:
            physics_name: Name of the Heat Transfer physics interface
            model_name: Model name (default: current model)
        
        Returns:
            Boundary information and setup instructions
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            boundaries_info = geometry_get_boundaries(None, model_name)
            if not boundaries_info.get("success"):
                return boundaries_info
            
            return {
                "success": True,
                "message": "Interactive Heat Transfer Setup",
                "available_boundaries": boundaries_info["total_boundaries"],
                "boundaries": boundaries_info["boundaries"],
                "boundary_condition_types": {
                    "TemperatureBoundary": "Fixed temperature (heat sink/source)",
                    "HeatFluxBoundary": "Prescribed heat flux (heat source)",
                    "ConvectiveHeatFlux": "Convection cooling/heating",
                    "Symmetry": "Symmetry plane (adiabatic)",
                    "ThermalInsulation": "Thermal insulation (default)"
                },
                "typical_setup": {
                    "heat_source": "Use HeatFluxBoundary with q0 parameter (W/m^2)",
                    "heat_sink": "Use TemperatureBoundary with T0 parameter (K or degC)",
                    "convection": "Use ConvectiveHeatFlux with h and Text parameters"
                },
                "example_usage": {
                    "heat_source": "physics_setup_heat_boundaries(physics_name='Heat Transfer in Solids', heat_flux_boundaries=[1, 2], heat_flux_value='1e6[W/m^2]')",
                    "heat_sink": "physics_setup_heat_boundaries(physics_name='Heat Transfer in Solids', temperature_boundaries=[3], temperature_value='293.15[K]')"
                },
                "next_step": "Tell me which boundary numbers to use for heat source and heat sink",
            }
        except Exception as e:
            return {"success": False, "error": f"Interactive setup failed: {str(e)}"}

    @mcp.tool()
    def physics_setup_heat_boundaries(
        physics_name: str,
        heat_flux_boundaries: Optional[Sequence[int]] = None,
        temperature_boundaries: Optional[Sequence[int]] = None,
        convection_boundaries: Optional[Sequence[int]] = None,
        heat_flux_value: str = "1e6[W/m^2]",
        temperature_value: str = "293.15[K]",
        convection_coeff: str = "10[W/(m^2*K)]",
        ambient_temp: str = "293.15[K]",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Setup Heat Transfer boundary conditions with specified boundaries.
        
        This tool configures thermal boundary conditions for heat transfer simulation:
        - Heat flux boundaries (heat sources)
        - Temperature boundaries (heat sinks)
        - Convective cooling/heating boundaries
        
        Args:
            physics_name: Name of the Heat Transfer physics interface
            heat_flux_boundaries: List of boundary numbers for heat flux
            temperature_boundaries: List of boundary numbers for fixed temperature
            convection_boundaries: List of boundary numbers for convection
            heat_flux_value: Heat flux value (default: "1e6[W/m^2]")
            temperature_value: Temperature value (default: "293.15[K]" = 20°C)
            convection_coeff: Convection coefficient (default: "10[W/(m^2*K)]")
            ambient_temp: Ambient temperature for convection (default: "293.15[K]")
            model_name: Model name (default: current model)
        
        Returns:
            Configuration confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            _, physics, available = _find_physics(model, physics_name, preferred_tag="ht")
            if physics is None:
                return {"success": False, "error": f"Physics '{physics_name}' not found.", "available_physics": available}
            
            heat_flux_boundaries = heat_flux_boundaries or []
            temperature_boundaries = temperature_boundaries or []
            convection_boundaries = convection_boundaries or []
            
            results = {"heat_flux": [], "temperature": [], "convection": []}
            
            # Add heat flux boundaries (heat sources)
            for i, boundary in enumerate(heat_flux_boundaries):
                tag = f'hf{i+1}'
                bc = physics.create(tag, 'HeatFluxBoundary')
                bc.selection().set([int(boundary)])
                bc.set('q0', heat_flux_value)
                bc.label(f'Heat Flux {i+1} (Boundary {boundary})')
                results["heat_flux"].append({
                    "tag": tag,
                    "boundary": boundary,
                    "heat_flux": heat_flux_value
                })
            
            # Add temperature boundaries (heat sinks)
            for i, boundary in enumerate(temperature_boundaries):
                tag = f'temp{i+1}'
                bc = physics.create(tag, 'TemperatureBoundary')
                bc.selection().set([int(boundary)])
                bc.set('T0', temperature_value)
                bc.label(f'Temperature {i+1} (Boundary {boundary})')
                results["temperature"].append({
                    "tag": tag,
                    "boundary": boundary,
                    "temperature": temperature_value
                })
            
            # Add convection boundaries
            for i, boundary in enumerate(convection_boundaries):
                tag = f'conv{i+1}'
                bc = physics.create(tag, 'ConvectiveHeatFlux')
                bc.selection().set([int(boundary)])
                bc.set('h', convection_coeff)
                bc.set('Text', ambient_temp)
                bc.label(f'Convection {i+1} (Boundary {boundary})')
                results["convection"].append({
                    "tag": tag,
                    "boundary": boundary,
                    "h": convection_coeff,
                    "T_amb": ambient_temp
                })
            
            return {
                "success": True,
                "physics": physics_name,
                "configured_boundaries": results,
                "summary": {
                    "heat_flux_boundaries": len(heat_flux_boundaries),
                    "temperature_boundaries": len(temperature_boundaries),
                    "convection_boundaries": len(convection_boundaries)
                },
                "message": f"Configured {len(heat_flux_boundaries)} heat flux, {len(temperature_boundaries)} temperature, and {len(convection_boundaries)} convection boundaries",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to setup heat boundaries: {str(e)}"}

    @mcp.tool()
    def physics_boundary_selection(
        physics_name: str,
        boundary_condition_type: str,
        boundary_numbers: Sequence[int],
        properties: Optional[dict] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Generic boundary condition setup with boundary selection.
        
        Use this tool to configure any boundary condition by specifying:
        1. The physics interface name
        2. The boundary condition type
        3. The boundary numbers to apply the condition to
        4. Properties specific to the boundary condition
        
        Common boundary condition types by physics:
        
        Heat Transfer (ht):
        - TemperatureBoundary: Set T0 (temperature)
        - HeatFluxBoundary: Set q0 (heat flux)
        - ConvectiveHeatFlux: Set h (coefficient), Text (ambient temp)
        
        Laminar Flow (spf):
        - InletBoundary: Set U0in (normal inlet velocity)
        - OutletBoundary: Set p0 (pressure)
        - Wall: No-slip wall
        
        Solid Mechanics (solid):
        - Fixed: Fixed constraint
        - BoundaryLoad: Set Fx, Fy, Fz or FAx, FAy, FAz
        
        Args:
            physics_name: Name of the physics interface
            boundary_condition_type: Type of boundary condition
            boundary_numbers: List of boundary numbers
            properties: Dictionary of property names and values
            model_name: Model name (default: current model)
        
        Returns:
            Configuration confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            if boundary_condition_type not in BOUNDARY_CONDITION_TYPES:
                return {
                    "success": False,
                    "error": f"Unsupported boundary_condition_type: {boundary_condition_type}",
                    "supported_boundary_conditions": sorted(BOUNDARY_CONDITION_TYPES),
                }
            
            _, physics, available = _find_physics(model, physics_name)
            if physics is None:
                return {"success": False, "error": f"Physics '{physics_name}' not found.", "available_physics": available}
            
            properties = properties or {}
            
            # Create boundary condition
            import random
            tag = f'bc_{random.randint(1000, 9999)}'
            bc = physics.create(tag, boundary_condition_type)
            bc.selection().set([int(b) for b in boundary_numbers])
            
            # Report invalid COMSOL property keys; silently swallowing them makes
            # the GUI look configured while values remain at defaults.
            property_warnings = []
            for prop_name, prop_value in properties.items():
                try:
                    bc.set(prop_name, prop_value)
                except Exception as e:
                    property_warnings.append({
                        "property": prop_name,
                        "value": prop_value,
                        "error": str(e),
                    })
            
            bc.label(f'{boundary_condition_type} (Boundaries {list(boundary_numbers)})')
            
            return {
                "success": True,
                "physics": physics_name,
                "boundary_condition": {
                    "type": boundary_condition_type,
                    "tag": tag,
                    "boundaries": list(boundary_numbers),
                    "properties": properties,
                    "property_warnings": property_warnings
                },
                "message": f"Created {boundary_condition_type} on boundaries {list(boundary_numbers)}",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create boundary condition: {str(e)}"}


    @mcp.tool()
    def physics_set_property(
        physics_name: str,
        prop: str,
        value: Union[bool, int, float, str, list],
        feature_tag: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Set an arbitrary property on a physics interface or one of its features.

        This is the generic escape hatch when no structured tool covers a
        setting (e.g. a heat source Q0 on a domain feature).

        Args:
            physics_name: Physics interface name or tag (e.g. "ht")
            prop: Property name (e.g. "Q0", "T0", "Reluctivity")
            value: bool / int / float / str / list. Ints are wrapped in JInt
                automatically (JPype overload ambiguity); lists pass through.
            feature_tag: Feature tag to set on. Omit to set on the interface
                node itself.
            model_name: Model name (default: current model)

        Returns:
            Echo of the assignment
        """
        from jpype import JInt

        model = session_manager.get_model(model_name)
        if model is None:
            return {"success": False, "error": f"Model not found: {model_name or 'no current model'}"}

        try:
            comp, physics, _avail = _find_physics(model, physics_name)
            if physics is None:
                return {"success": False, "error": f"Physics not found: {physics_name}"}
            node = physics.feature(feature_tag) if feature_tag else physics
            if isinstance(value, bool):
                converted = value
            elif isinstance(value, int):
                converted = JInt(value)
            elif isinstance(value, list):
                converted = [
                    JInt(v) if isinstance(v, int) and not isinstance(v, bool) else v
                    for v in value
                ]
            else:
                converted = value
            node.set(prop, converted)
            return {
                "success": True,
                "physics": physics_name,
                "feature": feature_tag or "(interface)",
                "property": prop,
                "value": str(value),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to set {prop}: {str(e)}"}

    @mcp.tool()
    def variable_create(
        variables: dict,
        descriptions: Optional[dict] = None,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Create model variables (Definitions > Variables), e.g. derived
        quantities used by other expressions or evaluations.

        Args:
            variables: name -> expression mapping,
                e.g. {"T_chip_max": "maxop_T(T)", "R_th": "(T_chip_max - T_in)/P_heat"}
            descriptions: optional name -> description mapping
            component_name: Component to add variables to (default: first component)
            model_name: Model name (default: current model)

        Returns:
            Created variable-group tag and the variable names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {"success": False, "error": f"Model not found: {model_name or 'no current model'}"}

        try:
            jm = model.java
            comp = None
            for candidate in jm.component():
                tag = candidate.tag()
                if component_name and tag != component_name:
                    continue
                comp = candidate
                break
            if comp is None:
                return {"success": False, "error": f"Component not found: {component_name or 'no components'}"}

            existing = set()
            try:
                for t in comp.variable().tags():
                    existing.add(str(t))
            except Exception:
                pass
            index = 1
            while "var{}".format(index) in existing:
                index += 1
            group_tag = "var{}".format(index)

            group = comp.variable().create(group_tag)
            group.label("AI Variables")
            names = []
            for name, expr in variables.items():
                group.set(str(name), str(expr))
                if descriptions and str(name) in descriptions:
                    try:
                        group.description(str(name), str(descriptions[str(name)]))
                    except Exception:
                        pass
                names.append(str(name))

            return {
                "success": True,
                "group": group_tag,
                "component": comp.tag(),
                "variables": names,
                "count": len(names),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create variables: {str(e)}"}
