"""Geometry tools for COMSOLPilot."""

from typing import Any, Optional, Sequence
from mcp.server.fastmcp import FastMCP

from .session import session_manager


def _get_geometry_node(model, geometry_name: Optional[str], component_name: str = "comp1"):
    """Helper to get geometry node via Java API.
    
    Returns:
        tuple: (geom_node, error_message) - geom_node is None if error
    """
    jm = model.java
    
    try:
        comp = jm.component(component_name)
        if comp is None:
            return None, f"Component '{component_name}' not found."
        
        geoms = list(comp.geom())
        if not geoms:
            return None, "No geometry sequences found. Create one first with geometry_create."

        if geometry_name:
            # COMSOL Desktop may localize labels such as "几何 1"; tools should still
            # accept either the stable Java tag ("geom1") or the GUI label.
            for candidate in geoms:
                if geometry_name in {candidate.tag(), candidate.label()}:
                    return candidate, None
            return None, f"Geometry '{geometry_name}' not found in component '{component_name}'."

        geom = geoms[0]
        
        return geom, None
    except Exception as e:
        return None, f"Failed to get geometry: {str(e)}"


def _next_feature_tag(geom, prefix: str) -> str:
    """Generate a free feature tag such as 'blk1' for the given geometry.

    geom.feature() returns a Java GeomFeatureListClient, which supports neither
    len() nor reliable indexing, so count via tag enumeration instead. Tags are
    also checked for uniqueness, which matters more than the number itself.
    """
    existing = set()
    try:
        for tag in geom.feature().tags():
            existing.add(str(tag))
    except Exception:
        try:
            for feature in geom.feature():
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


def _first_component(jm):
    """First component of the model, or None."""
    for comp in jm.component():
        return comp
    return None


def _find_geometry(comp, geometry_name=None):
    """Geometry sequence by tag, or the first one when no tag is given."""
    try:
        existing = {geom.tag(): geom for geom in comp.geom()}
    except Exception:
        return None
    if geometry_name:
        return existing.get(geometry_name)
    return next(iter(existing.values()), None)


def register_geometry_tools(mcp: FastMCP) -> None:
    """Register geometry tools with the MCP server."""
    
    @mcp.tool()
    def geometry_list(model_name: Optional[str] = None) -> dict:
        """
        List all geometry sequences in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of geometry sequence names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geometries = []
            for comp in model.java.component():
                for geom in comp.geom():
                    geometries.append({
                        "component": comp.tag(),
                        "tag": geom.tag(),
                        "label": geom.label(),
                    })
            return {
                "success": True,
                "geometries": geometries,
                "count": len(geometries),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list geometries: {str(e)}"}
    
    @mcp.tool()
    def geometry_create(
        geometry_name: Optional[str] = None,
        space_dimension: int = 3,
        component_name: str = "comp1",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create a new geometry sequence in the model's component.
        
        IMPORTANT: A component must exist first. Use model_create_component if needed.
        
        Args:
            geometry_name: Name for the geometry sequence (default: 'geom1')
            space_dimension: Space dimension - 2 for 2D, 3 for 3D (default: 3)
            component_name: Component name (default: 'comp1')
            model_name: Model name (default: current model)
        
        Returns:
            Created geometry info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            jm = model.java
            
            geom_name = geometry_name or "geom1"
            
            comp = jm.component(component_name)
            if comp is None:
                return {
                    "success": False,
                    "error": f"Component '{component_name}' not found. Create it first with model_create_component."
                }
            
            geom = comp.geom().create(geom_name, space_dimension)
            
            return {
                "success": True,
                "geometry": geom_name,
                "component": component_name,
                "space_dimension": space_dimension,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create geometry: {str(e)}"}
    
    @mcp.tool()
    def geometry_add_feature(
        feature_type: str,
        geometry_name: Optional[str] = None,
        feature_name: Optional[str] = None,
        component_name: str = "comp1",
        properties: Optional[dict[str, Any]] = None,
        selections: Optional[dict[str, Sequence[str]]] = None,
        build: bool = False,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Add a geometry feature to a geometry sequence.
        
        Common feature types:
        - Block: Rectangular block (3D)
        - Cylinder: Cylinder (3D)
        - Sphere: Sphere (3D)
        - Cone: Cone (3D)
        - WorkPlane: Working plane for 2D geometry
        - Rectangle: Rectangle (2D)
        - Circle: Circle (2D)
        - Polygon: Polygon from points
        - Import: Import CAD geometry
        - Union, Intersection, Difference: Boolean operations
        
        Args:
            feature_type: Type of geometry feature (Block, Cylinder, etc.)
            geometry_name: Geometry sequence name (default: first geometry)
            feature_name: Name for the feature (auto-generated if None)
            component_name: Component name (default: 'comp1')
            properties: Feature-specific COMSOL property dictionary
            selections: Selection inputs, for example {'input': ['blk1'], 'input2': ['cyl1']}
            build: Whether to run the geometry after creating the feature
            model_name: Model name (default: current model)
        
        Returns:
            Created feature info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}

            feat_name = feature_name or _next_feature_tag(geom, "feat")
            feature = geom.feature().create(feat_name, feature_type)
            warnings = []

            for prop_name, prop_value in (properties or {}).items():
                try:
                    feature.set(str(prop_name), prop_value)
                except Exception as exc:
                    warnings.append({"property": prop_name, "error": str(exc)})

            for selection_name, selection_values in (selections or {}).items():
                try:
                    feature.selection(str(selection_name)).set(list(selection_values))
                except Exception as exc:
                    warnings.append({"selection": selection_name, "error": str(exc)})

            if build:
                session_manager.retry_comsol_busy(lambda: geom.run())

            return {
                "success": True,
                "feature": {
                    "name": feature.tag(),
                    "type": feature_type,
                    "geometry": geom.tag(),
                    "properties": properties or {},
                    "selections": selections or {},
                    "built": build,
                },
                "warnings": warnings,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add geometry feature: {str(e)}"}
    
    @mcp.tool()
    def geometry_add_block(
        position: Sequence[float] = (0, 0, 0),
        size: Sequence[float] = (1, 1, 1),
        geometry_name: Optional[str] = None,
        component_name: str = "comp1",
        feature_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a block (rectangular cuboid) to the geometry.
        
        Args:
            position: Base position [x, y, z] in meters (default: origin)
            size: Dimensions [width, depth, height] in meters (default: 1m cube)
            geometry_name: Geometry sequence name (default: first geometry)
            component_name: Component name (default: 'comp1')
            feature_name: Feature name (auto-generated if None)
            model_name: Model name (default: current model)
        
        Returns:
            Created block info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}
            
            feat_name = feature_name or _next_feature_tag(geom, "blk")
            block = geom.feature().create(feat_name, "Block")
            
            block.set("pos", [str(p) for p in position])
            block.set("size", [str(s) for s in size])
            
            return {
                "success": True,
                "feature": {
                    "name": feat_name,
                    "type": "Block",
                    "position": list(position),
                    "size": list(size),
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add block: {str(e)}"}
    
    @mcp.tool()
    def geometry_add_cylinder(
        position: Sequence[float] = (0, 0, 0),
        radius: float = 0.5,
        height: float = 1.0,
        geometry_name: Optional[str] = None,
        component_name: str = "comp1",
        feature_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a cylinder to the geometry.
        
        Args:
            position: Center of base [x, y, z] in meters
            radius: Radius in meters (default: 0.5)
            height: Height in meters (default: 1.0)
            geometry_name: Geometry sequence name (default: first geometry)
            component_name: Component name (default: 'comp1')
            feature_name: Feature name (auto-generated if None)
            model_name: Model name (default: current model)
        
        Returns:
            Created cylinder info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}
            
            feat_name = feature_name or _next_feature_tag(geom, "cyl")
            cyl = geom.feature().create(feat_name, "Cylinder")
            
            cyl.set("pos", [str(p) for p in position])
            cyl.set("r", str(radius))
            cyl.set("h", str(height))
            
            return {
                "success": True,
                "feature": {
                    "name": feat_name,
                    "type": "Cylinder",
                    "position": list(position),
                    "radius": radius,
                    "height": height,
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add cylinder: {str(e)}"}
    
    @mcp.tool()
    def geometry_add_sphere(
        position: Sequence[float] = (0, 0, 0),
        radius: float = 0.5,
        geometry_name: Optional[str] = None,
        component_name: str = "comp1",
        feature_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a sphere to the geometry.
        
        Args:
            position: Center [x, y, z] in meters
            radius: Radius in meters (default: 0.5)
            geometry_name: Geometry sequence name (default: first geometry)
            component_name: Component name (default: 'comp1')
            feature_name: Feature name (auto-generated if None)
            model_name: Model name (default: current model)
        
        Returns:
            Created sphere info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}
            
            feat_name = feature_name or _next_feature_tag(geom, "sph")
            sphere = geom.feature().create(feat_name, "Sphere")
            
            sphere.set("pos", [str(p) for p in position])
            sphere.set("r", str(radius))
            
            return {
                "success": True,
                "feature": {
                    "name": feat_name,
                    "type": "Sphere",
                    "position": list(position),
                    "radius": radius,
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add sphere: {str(e)}"}
    
    @mcp.tool()
    def geometry_add_rectangle(
        position: Sequence[float] = (0, 0),
        size: Sequence[float] = (1, 1),
        geometry_name: Optional[str] = None,
        component_name: str = "comp1",
        feature_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a rectangle to a 2D geometry or work plane.
        
        Args:
            position: Base position [x, y] in meters
            size: Dimensions [width, height] in meters
            geometry_name: Geometry sequence name (default: first geometry)
            component_name: Component name (default: 'comp1')
            feature_name: Feature name (auto-generated if None)
            model_name: Model name (default: current model)
        
        Returns:
            Created rectangle info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}
            
            feat_name = feature_name or _next_feature_tag(geom, "r")
            rect = geom.feature().create(feat_name, "Rectangle")
            
            rect.set("pos", [str(p) for p in position])
            rect.set("size", [str(s) for s in size])
            
            return {
                "success": True,
                "feature": {
                    "name": feat_name,
                    "type": "Rectangle",
                    "position": list(position),
                    "size": list(size),
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add rectangle: {str(e)}"}
    
    @mcp.tool()
    def geometry_add_circle(
        position: Sequence[float] = (0, 0),
        radius: float = 0.5,
        geometry_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a circle to a 2D geometry or work plane.
        
        Args:
            position: Center [x, y] in meters
            radius: Radius in meters (default: 0.5)
            geometry_name: Geometry sequence name
            model_name: Model name (default: current model)
        
        Returns:
            Created circle info
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
                return {"success": False, "error": "No geometry sequences found."}
            
            target_geom = geometry_name or geometries[0]
            geom_node = model / "geometries" / target_geom
            circle_node = geom_node.create("Circle")
            
            if len(position) == 2:
                circle_node.property("pos", list(position))
            circle_node.property("r", radius)
            
            return {
                "success": True,
                "feature": {
                    "name": circle_node.name() if hasattr(circle_node, 'name') else "Circle",
                    "type": "Circle",
                    "geometry": target_geom,
                    "position": list(position),
                    "radius": radius,
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add circle: {str(e)}"}
    
    @mcp.tool()
    def geometry_boolean_union(
        input_objects: Sequence[str],
        geometry_name: Optional[str] = None,
        component_name: str = "comp1",
        feature_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create a boolean union of geometry objects.
        
        Args:
            input_objects: Names of objects to unite
            geometry_name: Geometry sequence name (default: first geometry)
            component_name: Component name (default: 'comp1')
            feature_name: Feature name (auto-generated if None)
            model_name: Model name (default: current model)
        
        Returns:
            Created union operation info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}
            
            feat_name = feature_name or _next_feature_tag(geom, "uni")
            union_node = geom.feature().create(feat_name, "Union")
            # Boolean features use geometry object tags, not boundary/domain numbers.
            union_node.selection("input").set(list(input_objects))
            
            return {
                "success": True,
                "feature": {
                    "name": feat_name,
                    "type": "Union",
                    "geometry": geometry_name or geom.tag(),
                    "input_objects": list(input_objects),
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create union: {str(e)}"}
    
    @mcp.tool()
    def geometry_boolean_difference(
        input_object: str,
        objects_to_subtract: Sequence[str],
        geometry_name: Optional[str] = None,
        component_name: str = "comp1",
        feature_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create a boolean difference (subtract objects from another).
        
        Args:
            input_object: Object to subtract from (e.g., 'blk1')
            objects_to_subtract: Objects to remove (e.g., ['cyl1'])
            geometry_name: Geometry sequence name (default: first geometry)
            component_name: Component name (default: 'comp1')
            feature_name: Feature name (auto-generated if None)
            model_name: Model name (default: current model)
        
        Returns:
            Created difference operation info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}
            
            feat_name = feature_name or _next_feature_tag(geom, "dif")
            diff = geom.feature().create(feat_name, "Difference")
            
            diff.selection("input").set([input_object])
            diff.selection("input2").set(list(objects_to_subtract))
            
            return {
                "success": True,
                "feature": {
                    "name": feat_name,
                    "type": "Difference",
                    "input_object": input_object,
                    "subtracted": list(objects_to_subtract),
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create difference: {str(e)}"}
    
    @mcp.tool()
    def geometry_import(
        file_path: str,
        geometry_name: Optional[str] = None,
        import_type: str = "CAD",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Import geometry from a CAD file.
        
        Supported formats: STEP, IGES, STL, NASTRAN, etc.
        
        Args:
            file_path: Path to the CAD file
            geometry_name: Geometry sequence name
            import_type: Import type (CAD, mesh, etc.)
            model_name: Model name (default: current model)
        
        Returns:
            Import operation info
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
                return {"success": False, "error": "No geometry sequences found."}
            
            target_geom = geometry_name or geometries[0]
            geom_node = model / "geometries" / target_geom
            import_node = geom_node.create("Import")
            
            model.import_(import_node, file_path)
            
            return {
                "success": True,
                "feature": {
                    "name": import_node.name() if hasattr(import_node, 'name') else "Import",
                    "type": "Import",
                    "geometry": target_geom,
                    "file": file_path,
                    "import_type": import_type,
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to import geometry: {str(e)}"}
    
    @mcp.tool()
    def geometry_build(
        geometry_name: Optional[str] = None,
        component_name: str = "comp1",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Build the geometry sequence to generate the actual geometry.
        
        This must be called after adding/modifying geometry features.
        
        Args:
            geometry_name: Geometry sequence name (default: build all)
            component_name: Component name (default: 'comp1')
            model_name: Model name (default: current model)
        
        Returns:
            Build status
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}
            
            geom.run()
            
            return {
                "success": True,
                "geometry": geometry_name or "first",
                "message": "Geometry built successfully.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to build geometry: {str(e)}"}
    
    @mcp.tool()
    def geometry_list_features(
        geometry_name: Optional[str] = None,
        component_name: str = "comp1",
        model_name: Optional[str] = None
    ) -> dict:
        """
        List all features in a geometry sequence.
        
        Args:
            geometry_name: Geometry sequence name (default: first geometry)
            model_name: Model name (default: current model)
        
        Returns:
            List of geometry features with their types
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geom_node, error = _get_geometry_node(model, geometry_name, component_name)
            if error:
                return {"success": False, "error": error}
            features = []
            
            for child in geom_node.feature():
                feat_info = {"tag": child.tag(), "label": child.label()}
                try:
                    feat_info["type"] = child.getType()
                except Exception:
                    pass
                features.append(feat_info)
            
            return {
                "success": True,
                "geometry": geom_node.tag(),
                "features": features,
                "count": len(features),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list features: {str(e)}"}

    @mcp.tool()
    def geometry_select_domains_by_box(
        xmin: float,
        xmax: float,
        ymin: float,
        ymax: float,
        zmin: float,
        zmax: float,
        selection_name: Optional[str] = None,
        geometry_name: Optional[str] = None,
        component_name: Optional[str] = "comp1",
        condition: str = "inside",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create a domain selection from a coordinate box.

        Use this to assign materials or domain physics without guessing domain numbers.
        Coordinates are in meters.
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            jm = model.java
            comp = jm.component(component_name) if component_name else next(iter(jm.component()), None)
            if comp is None:
                return {"success": False, "error": "No component found. Create one first with model_create_component."}

            geom, error = _get_geometry_node(model, geometry_name, comp.tag())
            if error:
                return {"success": False, "error": error}
            session_manager.retry_comsol_busy(lambda: geom.run())

            tag = selection_name or f"dsel{comp.selection().size()+1}"
            existing = {sel.tag(): sel for sel in comp.selection()}
            selection = existing.get(tag) or session_manager.retry_comsol_busy(
                lambda: comp.selection().create(tag, "Box")
            )

            # Entity dimension 3 means domains in 3D.
            selection.geom(geom.tag(), 3)
            selection.set("entitydim", "3")
            selection.set("xmin", str(xmin))
            selection.set("xmax", str(xmax))
            selection.set("ymin", str(ymin))
            selection.set("ymax", str(ymax))
            selection.set("zmin", str(zmin))
            selection.set("zmax", str(zmax))
            selection.set("condition", condition)

            selected_domains = None
            for getter in (
                lambda: list(selection.entities(3)),
                lambda: list(selection.entities()),
            ):
                try:
                    selected_domains = [int(item) for item in getter()]
                    break
                except Exception:
                    pass

            return {
                "success": True,
                "selection": tag,
                "component": comp.tag(),
                "geometry": geom.tag(),
                "entity_dimension": 3,
                "box": {
                    "xmin": xmin,
                    "xmax": xmax,
                    "ymin": ymin,
                    "ymax": ymax,
                    "zmin": zmin,
                    "zmax": zmax,
                },
                "condition": condition,
                "domain_numbers": selected_domains,
                "next_step": "Use this selection tag as domain_selection for material or physics tools.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to select domains by box: {str(e)}"}

    @mcp.tool()
    def geometry_info(
        geometry_name: Optional[str] = None,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Report the geometry bounding box, its centre and entity counts.

        Answers the practical question "where is my model?" - a geometry whose
        centre sits far from the origin looks lost in a corner of the COMSOL
        Desktop graphics window. Pair with geometry_center to move it back to
        the origin.

        Args:
            geometry_name: Geometry sequence tag (default: first one)
            component_name: Component tag (default: first component)
            model_name: Model name (default: current model)

        Returns:
            Per-axis min/max/size, the centre, entity counts, and which kernel
            accessor supplied the numbers ("source")
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {"success": False, "error": f"Model not found: {model_name or 'no current model'}"}

        try:
            jm = model.java
            comp = jm.component(component_name) if component_name else _first_component(jm)
            if comp is None:
                return {"success": False, "error": "Model has no component."}
            geom = _find_geometry(comp, geometry_name)
            if geom is None:
                return {"success": False, "error": "Model has no geometry sequence."}

            bbox = None
            source = None
            try:
                raw = [float(v) for v in geom.getBoundingBox()]
                if len(raw) == 6:
                    # COMSOL returns (xmin, xmax, ymin, ymax, zmin, zmax)
                    candidate = {"x": (raw[0], raw[1]), "y": (raw[2], raw[3]), "z": (raw[4], raw[5])}
                    if all(lo <= hi for lo, hi in candidate.values()):
                        bbox, source = candidate, "getBoundingBox"
                    else:
                        candidate = {"x": (raw[0], raw[3]), "y": (raw[1], raw[4]), "z": (raw[2], raw[5])}
                        if all(lo <= hi for lo, hi in candidate.values()):
                            bbox, source = candidate, "getBoundingBox(interleaved)"
            except Exception:
                pass
            if bbox is None:
                try:
                    bbox = {
                        "x": (float(geom.getXMin()), float(geom.getXMax())),
                        "y": (float(geom.getYMin()), float(geom.getYMax())),
                        "z": (float(geom.getZMin()), float(geom.getZMax())),
                    }
                    source = "getXMin/getXMax"
                except Exception:
                    pass
            if bbox is None:
                return {
                    "success": False,
                    "error": "Bounding box is not available from this kernel build.",
                    "hint": "Build the geometry first, or pass an explicit offset to geometry_center.",
                }

            info = {
                "bounding_box": {axis: {"min": lo, "max": hi, "size": hi - lo}
                                 for axis, (lo, hi) in bbox.items()},
                "center": {axis: (lo + hi) / 2.0 for axis, (lo, hi) in bbox.items()},
                "source": source,
            }
            for name, getter in (("domains", "getNDomains"), ("boundaries", "getNBoundaries"),
                                 ("edges", "getNEdges"), ("vertices", "getNVertices")):
                try:
                    info[name] = int(getattr(geom, getter)())
                except Exception:
                    pass

            center = info["center"]
            offset_norm = max(abs(center["x"]), abs(center["y"]), abs(center["z"]))
            size_ref = max(info["bounding_box"][a]["size"] for a in ("x", "y", "z")) or 1.0
            info["centered"] = offset_norm <= 1e-9 + 0.01 * size_ref
            info["offset_from_origin"] = offset_norm

            return {"success": True, "geometry": geom.tag(), "component": comp.tag(), "info": info}
        except Exception as e:
            return {"success": False, "error": f"Failed to read geometry info: {str(e)}"}

    @mcp.tool()
    def geometry_center(
        target_center: Optional[Sequence[float]] = None,
        offset: Optional[Sequence[float]] = None,
        geometry_name: Optional[str] = None,
        feature_tag: str = "mov1",
        run_build: bool = True,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Move the whole geometry so its bounding box centre lands where you want.

        Fixes the common "my model sits off in a corner" situation: measures the
        current bounding box centre and adds a Move feature with the required
        displacement (default target: the origin).

        Args:
            target_center: Point the geometry centre should move to
                (default [0, 0, 0])
            offset: Explicit displacement [dx, dy, dz]; overrides target_center
            geometry_name: Geometry sequence tag (default: first one)
            feature_tag: Tag for the Move feature (default: 'mov1')
            run_build: Rebuild the geometry right after moving (default True)
            component_name: Component tag (default: first component)
            model_name: Model name (default: current model)

        Returns:
            The displacement applied, the centre before and after, and the
            bounds of the moved geometry
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {"success": False, "error": f"Model not found: {model_name or 'no current model'}"}

        try:
            from jpype import JArray, JDouble

            jm = model.java
            comp = jm.component(component_name) if component_name else _first_component(jm)
            if comp is None:
                return {"success": False, "error": "Model has no component."}
            geom = _find_geometry(comp, geometry_name)
            if geom is None:
                return {"success": False, "error": "Model has no geometry sequence."}

            if offset is not None:
                if len(offset) != 3:
                    return {"success": False, "error": "offset must have 3 numbers [dx, dy, dz]."}
                displacement = [float(v) for v in offset]
                centre_before = None
            else:
                target = [float(v) for v in (target_center or [0.0, 0.0, 0.0])]
                if len(target) != 3:
                    return {"success": False, "error": "target_center must have 3 numbers [x, y, z]."}
                centre_before = _bbox_center(geom)
                if centre_before is None:
                    return {
                        "success": False,
                        "error": "Bounding box unavailable; pass an explicit offset instead.",
                    }
                displacement = [target[i] - centre_before[i] for i in range(3)]

            existing = {feature.tag(): feature for feature in geom.feature()}
            if feature_tag in existing:
                feature = existing[feature_tag]
                created = False
            else:
                feature = session_manager.retry_comsol_busy(
                    lambda: geom.create(feature_tag, "Move"))
                created = True
            feature.set("displ", JArray(JDouble)(displacement))
            try:
                feature.label("Centre geometry (COMSOLPilot)")
            except Exception:
                pass

            # A Move feature created through the API does not inherit the
            # previous feature's output here: it needs an explicit input
            # selection, otherwise the build fails with "必须提供输入对象".
            input_note = ""
            try:
                feature.selection("input").all()
                input_note = "selection('input').all()"
            except Exception as exc:
                input_note = f"input selection not set: {str(exc)[:80]}"

            built = False
            if run_build:
                try:
                    session_manager.retry_comsol_busy(lambda: geom.run())
                    built = True
                except Exception:
                    # Leave the geometry as it was: a half-applied Move would
                    # break the mesh and every later step.
                    try:
                        geom.feature().remove(feature_tag)
                    except Exception:
                        pass
                    raise

            centre_after = _bbox_center(geom) if built else None
            return {
                "success": True,
                "component": comp.tag(),
                "geometry": geom.tag(),
                "feature": feature_tag,
                "created": created,
                "displacement": displacement,
                "center_before": centre_before,
                "center_after": centre_after,
                "built": built,
                "input_selection": input_note,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to centre geometry: {str(e)}"}


def _bbox_center(geom):
    """Bounding box centre as [x, y, z], or None when the kernel cannot tell."""
    try:
        raw = [float(v) for v in geom.getBoundingBox()]
        if len(raw) == 6:
            candidate = [(raw[0], raw[1]), (raw[2], raw[3]), (raw[4], raw[5])]
            if not all(lo <= hi for lo, hi in candidate):
                candidate = [(raw[0], raw[3]), (raw[1], raw[4]), (raw[2], raw[5])]
            if all(lo <= hi for lo, hi in candidate):
                return [(lo + hi) / 2.0 for lo, hi in candidate]
    except Exception:
        pass
    try:
        return [
            (float(geom.getXMin()) + float(geom.getXMax())) / 2.0,
            (float(geom.getYMin()) + float(geom.getYMax())) / 2.0,
            (float(geom.getZMin()) + float(geom.getZMax())) / 2.0,
        ]
    except Exception:
        return None
