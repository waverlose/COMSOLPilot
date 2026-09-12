"""Mesh tools for COMSOLPilot."""

from typing import Optional
from mcp.server.fastmcp import FastMCP

from .session import session_manager


def register_mesh_tools(mcp: FastMCP) -> None:
    """Register mesh tools with the MCP server."""
    
    @mcp.tool()
    def mesh_list(model_name: Optional[str] = None) -> dict:
        """
        List all mesh sequences in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of mesh sequence names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            meshes = model.meshes()
            return {
                "success": True,
                "meshes": meshes,
                "count": len(meshes),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list meshes: {str(e)}"}
    
    @mcp.tool()
    def mesh_ensure(
        mesh_name: str = "mesh1",
        component_name: Optional[str] = None,
        mesh_size: Optional[int] = None,
        run: bool = True,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Ensure a mesh sequence exists and optionally run it.
        
        This is the safe default for AI workflows: if no mesh sequence exists,
        it creates one before meshing.
        
        Args:
            mesh_name: Mesh sequence tag to create or run (default: 'mesh1')
            component_name: Component tag (default: first component)
            mesh_size: Physics-controlled mesh size 1-9 if supported; lower is finer
            run: Whether to generate the mesh after ensuring it exists
            model_name: Model name (default: current model)
        
        Returns:
            Mesh creation/run status
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            jm = model.java
            comp = jm.component(component_name) if component_name else None
            if comp is None:
                for candidate in jm.component():
                    comp = candidate
                    break
            if comp is None:
                return {"success": False, "error": "No component found. Create one first with model_create_component."}
            
            existing = {mesh.tag(): mesh for mesh in comp.mesh()}
            created = False
            if mesh_name in existing:
                mesh = existing[mesh_name]
            else:
                mesh = comp.mesh().create(mesh_name)
                created = True
            
            if mesh_size is not None:
                if mesh_size < 1 or mesh_size > 9:
                    return {"success": False, "error": "mesh_size must be between 1 and 9."}
                try:
                    mesh.autoMeshSize(int(mesh_size))
                except Exception:
                    pass
            
            if run:
                mesh.run()
            
            return {
                "success": True,
                "mesh": mesh.tag(),
                "component": comp.tag(),
                "created": created,
                "ran": run,
                "mesh_size": mesh_size,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to ensure mesh: {str(e)}"}
    
    @mcp.tool()
    def mesh_create(
        mesh_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Run a mesh sequence to generate the mesh.
        
        This executes the meshing operations defined in the mesh sequence.
        
        Args:
            mesh_name: Mesh sequence name (default: run all mesh sequences)
            model_name: Model name (default: current model)
        
        Returns:
            Mesh generation status
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            model.mesh(mesh_name)
            return {
                "success": True,
                "mesh": mesh_name,
                "message": f"Mesh created: {mesh_name or 'all meshes'}",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create mesh: {str(e)}"}
    
    @mcp.tool()
    def mesh_info(
        mesh_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Get information about a mesh.
        
        Args:
            mesh_name: Mesh sequence name (default: first mesh)
            model_name: Model name (default: current model)
        
        Returns:
            Mesh statistics including element counts
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            meshes = model.meshes()
            if not meshes:
                return {"success": False, "error": "No meshes defined in model."}
            
            target = mesh_name or meshes[0]
            if target not in meshes:
                return {"success": False, "error": f"Mesh not found: {target}"}
            
            mesh_node = model / "meshes" / target
            
            info = {
                "name": target,
            }
            
            try:
                java_mesh = mesh_node.java
                if hasattr(java_mesh, 'getVertex'):
                    info["num_vertices"] = java_mesh.getVertex().size()
                if hasattr(java_mesh, 'getElement'):
                    info["num_elements"] = java_mesh.getElement().size()
            except Exception:
                pass
            
            try:
                children = [child.name() for child in mesh_node.children()]
                info["features"] = children
            except Exception:
                pass
            
            return {
                "success": True,
                "mesh": info,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to get mesh info: {str(e)}"}

    PRESET_HAUTO = {
        "extremelyfine": 1, "extrafine": 2, "finer": 3, "fine": 4, "normal": 5,
        "coarse": 6, "coarser": 7, "extracoarse": 8, "extremelycoarse": 9,
    }

    def _resolve_mesh(jm, mesh_name: Optional[str], component_name: Optional[str]):
        """Resolve a mesh node by tag, creating it if needed.

        Meshes live under components, so resolving through the model would miss
        them on a localised install. Returns (component, mesh, created).
        """
        comp = jm.component(component_name) if component_name else None
        if comp is None:
            for candidate in jm.component():
                comp = candidate
                break
        if comp is None:
            return None, None, False
        existing = {mesh.tag(): mesh for mesh in comp.mesh()}
        if mesh_name and mesh_name in existing:
            return comp, existing[mesh_name], False
        if not mesh_name and existing:
            return comp, next(iter(existing.values())), False
        tag = mesh_name or "mesh1"
        return comp, comp.mesh().create(tag), True

    @mcp.tool()
    def mesh_configure_global_size(
        mesh_name: Optional[str] = None,
        preset: Optional[str] = None,
        custom_hmax: Optional[str] = None,
        custom_hmin: Optional[str] = None,
        custom_hgrad: Optional[str] = None,
        custom_hcurve: Optional[str] = None,
        custom_hnarrow: Optional[str] = None,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Configure global element sizing for a mesh sequence.

        Args:
            mesh_name: Mesh sequence tag (default: first mesh, created if none exists)
            preset: Physics-controlled preset: extremelyfine, extrafine, finer, fine,
                normal, coarse, coarser, extracoarse, extremelycoarse
            custom_hmax: Maximum element size, e.g. '0.01'
            custom_hmin: Minimum element size
            custom_hgrad: Maximum element growth rate
            custom_hcurve: Curvature factor (resolution of curved boundaries)
            custom_hnarrow: Resolution of narrow regions
            component_name: Component tag (default: first component)
            model_name: Model name (default: current model)

        Returns:
            The applied sizing settings
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {"success": False, "error": f"Model not found: {model_name or 'no current model'}"}

        try:
            jm = model.java
            comp, mesh, created = _resolve_mesh(jm, mesh_name, component_name)
            if mesh is None:
                return {"success": False, "error": "No component found. Create one first with model_create_component."}

            features = {item.tag(): item for item in mesh.feature()}
            size = features.get("size")
            if size is None:
                return {"success": False, "error": "This mesh has no global 'size' feature to configure."}

            updates: dict = {}
            if preset:
                value = PRESET_HAUTO.get(preset.lower().replace(" ", "").replace("_", ""))
                if value is None:
                    return {"success": False,
                            "error": f"Invalid preset: {preset}. Valid: {sorted(PRESET_HAUTO)}"}
                import jpype
                size.set("custom", "off")
                size.set("hauto", jpype.JInt(value))
                updates["preset"] = preset

            custom = {"hmax": custom_hmax, "hmin": custom_hmin, "hgrad": custom_hgrad,
                      "hcurve": custom_hcurve, "hnarrow": custom_hnarrow}
            if any(value is not None for value in custom.values()):
                size.set("custom", "on")
                for key, value in custom.items():
                    if value is not None:
                        size.set(key, str(value))
                        updates[key] = value

            return {
                "success": True,
                "component": comp.tag(),
                "mesh": mesh.tag(),
                "created": created,
                "updates": updates,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to configure global size: {str(e)}"}

    @mcp.tool()
    def mesh_add_local_size(
        size_tag: str,
        entities: list,
        entity_dimension: int = 2,
        mesh_name: Optional[str] = None,
        custom_hmax: Optional[str] = None,
        custom_hmin: Optional[str] = None,
        custom_hgrad: Optional[str] = None,
        custom_hcurve: Optional[str] = None,
        custom_hnarrow: Optional[str] = None,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a local Size node to refine the mesh on specific entities.

        The node is created under the mesh sequence (never at root level), which
        is what COMSOL requires for local refinement to take effect.

        Args:
            size_tag: Tag for the local size node, e.g. 'size1'
            entities: Entity ids to refine, e.g. [3] for one boundary
            entity_dimension: 3 domains, 2 boundaries, 1 edges, 0 points (default: 2)
            mesh_name: Mesh sequence tag (default: first mesh, created if none exists)
            custom_hmax: Maximum element size on those entities, e.g. '0.001'
            custom_hmin: Minimum element size
            custom_hgrad: Maximum element growth rate
            custom_hcurve: Curvature factor
            custom_hnarrow: Resolution of narrow regions
            component_name: Component tag (default: first component)
            model_name: Model name (default: current model)

        Returns:
            The created local size node
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {"success": False, "error": f"Model not found: {model_name or 'no current model'}"}
        if not entities:
            return {"success": False,
                    "error": "entities must list the entity ids to refine; an empty list would create a no-op node."}

        try:
            jm = model.java
            comp, mesh, created = _resolve_mesh(jm, mesh_name, component_name)
            if mesh is None:
                return {"success": False, "error": "No component found. Create one first with model_create_component."}

            if size_tag in {item.tag() for item in mesh.feature()}:
                mesh.feature().remove(size_tag)

            import jpype
            node = mesh.feature().create(size_tag, "Size")
            # A mesh Size selection must be told which geometry sequence it refers
            # to as well as the entity dimension; passing the dimension alone makes
            # COMSOL read it as a geometry tag ("Unsupported geometry: 2").
            geom_tags = list(comp.geom().tags()) if hasattr(comp, "geom") else []
            geom_tag = geom_tags[0] if geom_tags else "geom1"
            node.selection().geom(geom_tag, int(entity_dimension))
            node.selection().set([jpype.JInt(int(item)) for item in entities])

            updates: dict = {
                "tag": size_tag,
                "entity_dimension": entity_dimension,
                "entities": [int(item) for item in entities],
            }
            node.set("custom", "on")
            for key, value in (("hmax", custom_hmax), ("hmin", custom_hmin),
                               ("hgrad", custom_hgrad), ("hcurve", custom_hcurve),
                               ("hnarrow", custom_hnarrow)):
                if value is not None:
                    node.set(key, str(value))
                    updates[key] = value

            return {
                "success": True,
                "component": comp.tag(),
                "mesh": mesh.tag(),
                "created": created,
                "local_size": updates,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add local size: {str(e)}"}

    @mcp.tool()
    def mesh_configure_boundary_layers(
        num_layers: int = 3,
        stretching_factor: float = 1.2,
        thickness_adjustment_factor: float = 4.0,
        boundaries: Optional[Sequence[int]] = None,
        mesh_name: Optional[str] = None,
        feature_tag: str = "bl1",
        run_mesh: bool = False,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Add or update a Boundary Layers feature on the mesh sequence.

        Boundary layers resolve near-wall gradients - essential for flow and
        convective heat transfer (microchannels, forced convection, film
        cooling). The layer property node is created under the mesh sequence;
        call the mesh run / study solve afterwards, or set run_mesh=true.

        Args:
            num_layers: Number of boundary layers (default 3)
            stretching_factor: Layer stretching factor (default 1.2)
            thickness_adjustment_factor: Thickness adjustment factor (default 4)
            boundaries: Optional boundary numbers for the layers; omit to let
                COMSOL place them on the default (fluid-adjacent) boundaries
            mesh_name: Mesh sequence tag (default: first mesh, created if none)
            feature_tag: Feature tag (default: 'bl1')
            run_mesh: Rebuild the mesh immediately after configuration
            component_name: Component tag (default: first component)
            model_name: Model name (default: current model)

        Returns:
            Applied boundary-layer settings and any property COMSOL rejected
        """
        from jpype import JInt

        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        warnings = []
        applied: dict = {}
        try:
            jm = model.java
            comp, mesh, created = _resolve_mesh(jm, mesh_name, component_name)
            try:
                feature = mesh.feature(feature_tag)
            except Exception:
                feature = session_manager.retry_comsol_busy(
                    lambda: mesh.create(feature_tag, "BndLayer"))
            try:
                prop = feature(feature_tag + "p")
            except Exception:
                prop = session_manager.retry_comsol_busy(
                    lambda: feature.create(feature_tag + "p", "BndLayerProp"))

            for name, value in (
                ("numLayers", num_layers),
                ("stretchingFactor", stretching_factor),
                ("thicknessAdjustmentFactor", thickness_adjustment_factor),
            ):
                try:
                    converted = JInt(value) if isinstance(value, int) and not isinstance(value, bool) else value
                    prop.set(name, converted)
                    applied[name] = value
                except Exception as exc:
                    warnings.append({"property": name, "value": value,
                                     "error": str(exc)[:120]})

            if boundaries:
                try:
                    prop.selection().set([int(b) for b in boundaries])
                    applied["boundaries"] = [int(b) for b in boundaries]
                except Exception as exc:
                    warnings.append({"property": "selection",
                                     "error": str(exc)[:120]})

            if run_mesh:
                session_manager.retry_comsol_busy(lambda: mesh.run())
                applied["mesh_run"] = True

            return {
                "success": True,
                "component": comp.tag(),
                "mesh": mesh.tag(),
                "feature": feature_tag,
                "applied": applied,
                "property_warnings": warnings,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to configure boundary layers: {str(e)}",
                "property_warnings": warnings,
            }

    @mcp.tool()
    def mesh_quality_report(
        mesh_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Report mesh statistics: element/vertex counts and quality metrics.

        Aggregates whatever the kernel exposes for the mesh sequence
        (mesh.stat() label/value pairs plus element and vertex counts), so the
        AI can judge whether the mesh is fit for the study before solving.

        Args:
            mesh_name: Mesh sequence tag (default: first mesh)
            model_name: Model name (default: current model)

        Returns:
            Statistics dictionary (label -> value when parseable)
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        stats: dict = {}
        try:
            jm = model.java
            _comp, mesh, _created = _resolve_mesh(jm, mesh_name, None)

            try:
                raw = mesh.stat()
                pairs = list(raw)
                if len(pairs) % 2 == 0:
                    for i in range(0, len(pairs), 2):
                        label = str(pairs[i])
                        value = pairs[i + 1]
                        try:
                            stats[label] = float(str(value))
                        except (TypeError, ValueError):
                            stats[label] = str(value)
                else:
                    stats["raw"] = [str(item) for item in pairs]
            except Exception as exc:
                stats["stat_error"] = str(exc)[:160]

            try:
                if hasattr(mesh, "getVertex"):
                    stats["number_of_vertices"] = int(mesh.getVertex().size())
            except Exception:
                pass
            try:
                if hasattr(mesh, "getElement"):
                    stats["number_of_elements"] = int(mesh.getElement().size())
            except Exception:
                pass

            features = []
            try:
                features = [str(child.name()) for child in mesh.feature()]
            except Exception:
                pass

            return {
                "success": True,
                "mesh": mesh.tag(),
                "stats": stats,
                "features": features,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to report mesh quality: {str(e)}"}
