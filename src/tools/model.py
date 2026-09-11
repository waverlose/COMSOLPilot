"""Model management tools for COMSOLPilot."""

from typing import Any, Optional
import contextlib
import io
from pathlib import Path
from mcp.server.fastmcp import FastMCP
import mph

from .session import session_manager
from ..utils.versioning import (
    generate_version_path, 
    generate_latest_path,
    parse_version_info,
    list_model_versions,
    get_model_directory,
    MODELS_BASE_DIR
)


def register_model_tools(mcp: FastMCP) -> None:
    """Register model management tools with the MCP server."""

    def _json_safe(value: Any):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (list, tuple)):
            return [_json_safe(item) for item in value]
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        return repr(value)
    
    @mcp.tool()
    def model_load(file_path: str, set_current: bool = True) -> dict:
        """
        Load a COMSOL model from a .mph file.
        
        Args:
            file_path: Absolute or relative path to the .mph model file
            set_current: Whether to set this as the current active model (default: True)
        
        Returns:
            Model info including name, file path, and version, or error message
        """
        if not session_manager.is_connected:
            return {"success": False, "error": "No active COMSOL session. Start with comsol_start first."}
        
        client = session_manager.client
        if client is None:
            return {"success": False, "error": "Client not available."}
        
        try:
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}
            if not path.suffix.lower() == ".mph":
                return {"success": False, "error": f"File must be a .mph file: {file_path}"}
            
            model = client.load(str(path.absolute()))
            name = session_manager.add_model(model)
            
            if set_current:
                session_manager.set_current_model(name)
            
            version_info = parse_version_info(name)
            
            return {
                "success": True,
                "model": {
                    "name": name,
                    "file": str(path.absolute()),
                    "comsol_version": model.version(),
                    "is_versioned": version_info is not None,
                    "version_info": version_info,
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to load model: {str(e)}"}
    
    @mcp.tool()
    def model_create(name: Optional[str] = None, set_current: bool = True) -> dict:
        """
        Create a new empty COMSOL model.
        
        Args:
            name: Optional name for the model (auto-generated if not provided)
            set_current: Whether to set this as the current active model (default: True)
        
        Returns:
            Model info including name, or error message
        """
        if not session_manager.is_connected:
            return {"success": False, "error": "No active COMSOL session. Start with comsol_start first."}
        
        client = session_manager.client
        if client is None:
            return {"success": False, "error": "Client not available."}
        
        try:
            model = session_manager.retry_comsol_busy(lambda: client.create(name))
            model_name = session_manager.add_model(model)
            
            if set_current:
                session_manager.set_current_model(model_name)
            
            return {
                "success": True,
                "model": {
                    "name": model_name,
                    "is_new": True,
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create model: {str(e)}"}
    
    @mcp.tool()
    def model_create_component(
        component_name: str = "comp1",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create a component in the model (required before adding geometry/physics).
        
        Components are containers for geometry, physics, materials, and mesh.
        Must be created before adding geometry or physics.
        
        Args:
            component_name: Name for the component (default: 'comp1')
            model_name: Model name (default: current model)
        
        Returns:
            Created component info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            jm = model.java
            components = {comp.tag(): comp for comp in jm.component()}
            comp = components.get(component_name) or session_manager.retry_comsol_busy(
                lambda: jm.component().create(component_name, True)
            )
            
            return {
                "success": True,
                "component": component_name,
                "model": model.name(),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create component: {str(e)}"}
    
    @mcp.tool()
    def model_create_full(
        model_name: Optional[str] = None,
        space_dimension: int = 3,
        component_name: str = "comp1",
        geometry_name: str = "geom1",
        set_current: bool = True
    ) -> dict:
        """
        Create a new model with component and geometry initialized.
        
        This bootstraps the common sequence:
        model_create -> model_create_component -> geometry_create.
        
        Args:
            model_name: Optional model name (auto-generated if not provided)
            space_dimension: Geometry space dimension, 2 or 3 (default: 3)
            component_name: Component tag to create (default: 'comp1')
            geometry_name: Geometry sequence tag to create (default: 'geom1')
            set_current: Whether to set this as the current active model (default: True)
        
        Returns:
            Created model, component, and geometry info, or error message
        """
        if space_dimension not in (2, 3):
            return {"success": False, "error": "space_dimension must be 2 or 3."}
        if not session_manager.is_connected:
            return {"success": False, "error": "No active COMSOL session. Start with comsol_start first."}
        
        client = session_manager.client
        if client is None:
            return {"success": False, "error": "Client not available."}
        
        try:
            model = session_manager.retry_comsol_busy(lambda: client.create(model_name))
            created_model_name = session_manager.add_model(model)
            
            if set_current:
                session_manager.set_current_model(created_model_name)
            
            jm = model.java
            components = {comp.tag(): comp for comp in jm.component()}
            comp = components.get(component_name) or session_manager.retry_comsol_busy(
                lambda: jm.component().create(component_name, True)
            )
            geometries = {geom.tag(): geom for geom in comp.geom()}
            geom = geometries.get(geometry_name) or session_manager.retry_comsol_busy(
                lambda: comp.geom().create(geometry_name, space_dimension)
            )
            
            return {
                "success": True,
                "model": {
                    "name": created_model_name,
                    "is_new": True,
                    "is_current": created_model_name == session_manager.current_model,
                },
                "component": comp.tag(),
                "geometry": geom.tag(),
                "space_dimension": space_dimension,
                "next_steps": [
                    "Add geometry features.",
                    "Run geometry_build before geometry_get_boundaries.",
                    "Use returned physics tags such as 'ht' in later physics tools.",
                ],
            }
        except Exception as e:
            result = {"success": False, "error": f"Failed to create full model: {str(e)}"}
            if "Server is in use by another client" in str(e):
                result["recoverable"] = True
                result["recommended_next_steps"] = [
                    "Retry after the GUI finishes updating.",
                    "Or use the safer sequence: model_create -> model_create_component -> geometry_create.",
                ]
            return result
    
    @mcp.tool()
    def model_list_components(
        model_name: Optional[str] = None
    ) -> dict:
        """
        List all components in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of component names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            jm = model.java
            components = []
            
            for comp in jm.component():
                # Java component collections are iterable; get(int) is not valid here.
                components.append({
                    "name": comp.tag(),
                    "label": comp.label() if hasattr(comp, 'label') else comp.tag()
                })
            
            return {
                "success": True,
                "components": components,
                "count": len(components),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list components: {str(e)}"}
    
    @mcp.tool()
    def model_state(model_name: Optional[str] = None) -> dict:
        """
        Summarize model readiness for automated workflows.
        
        This tool is intended as the first diagnostic checkpoint before choosing
        the next modeling step.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            Model state, missing requirements, and recommended next steps
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            jm = model.java
            components = []
            for comp in jm.component():
                components.append({
                    "tag": comp.tag(),
                    "label": comp.label(),
                    "geometries": [geom.tag() for geom in comp.geom()],
                    "physics": [{"tag": phys.tag(), "label": phys.label()} for phys in comp.physics()],
                    "materials": [{"tag": mat.tag(), "label": mat.label()} for mat in comp.material()],
                    "meshes": [mesh.tag() for mesh in comp.mesh()],
                })
            
            studies = []
            for study in jm.study():
                steps = []
                for step in study.feature():
                    step_info = {"tag": step.tag()}
                    try:
                        step_info["type"] = step.getType()
                    except Exception:
                        pass
                    steps.append(step_info)
                studies.append({
                    "tag": study.tag(),
                    "label": study.label(),
                    "steps": steps,
                })
            
            missing = []
            next_steps = []
            if not components:
                missing.append("component")
                next_steps.append("model_create_component or model_create_full")
            if components and not any(item["geometries"] for item in components):
                missing.append("geometry")
                next_steps.append("geometry_create")
            if components and any(item["geometries"] for item in components) and not any(item["physics"] for item in components):
                missing.append("physics")
                next_steps.append("physics_add_*")
            if components and not any(item["materials"] for item in components):
                missing.append("material")
                next_steps.append("material_create_basic")
            if components and not any(item["meshes"] for item in components):
                missing.append("mesh")
                next_steps.append("mesh_ensure")
            if not studies:
                missing.append("study")
                next_steps.append("study_ensure")
            
            ready_for_solve = not missing
            
            return {
                "success": True,
                "model": model.name(),
                "current_model": session_manager.current_model,
                "components": components,
                "studies": studies,
                "datasets": model.datasets(),
                "solutions": model.solutions(),
                "plots": model.plots(),
                "exports": model.exports(),
                "missing": missing,
                "ready_for_solve": ready_for_solve,
                "recommended_next_steps": next_steps,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to get model state: {str(e)}"}
    
    @mcp.tool()
    def model_validate_ready_for_solve(model_name: Optional[str] = None) -> dict:
        """
        Validate whether a model has the minimum structure needed before solving.
        
        This is a pre-solve gate for AI workflows. It checks generic COMSOL
        prerequisites, not physics-specific correctness.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            Validation result with blockers, warnings, and suggested fixes
        """
        state = model_state(model_name)
        if not state.get("success"):
            return state
        
        blockers = []
        warnings = []
        fixes = []
        
        for missing in state.get("missing", []):
            blockers.append(f"Missing {missing}.")
        
        if "component" in state.get("missing", []):
            fixes.append("Call model_create_component or model_create_full.")
        if "geometry" in state.get("missing", []):
            fixes.append("Call geometry_create, add geometry features, then geometry_build.")
        if "physics" in state.get("missing", []):
            fixes.append("Call the relevant physics_add_* tool.")
        if "material" in state.get("missing", []):
            fixes.append("Call material_create_basic or material_assign.")
        if "mesh" in state.get("missing", []):
            fixes.append("Call mesh_ensure.")
        if "study" in state.get("missing", []):
            fixes.append("Call study_ensure.")
        
        if state.get("components"):
            for comp in state["components"]:
                if comp["geometries"] and not comp["materials"]:
                    warnings.append(f"Component {comp['tag']} has geometry but no material.")
                if comp["physics"] and not comp["meshes"]:
                    warnings.append(f"Component {comp['tag']} has physics but no mesh.")
        
        return {
            "success": True,
            "ready": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
            "suggested_fixes": fixes,
            "state": state,
        }
    
    @mcp.tool()
    def model_save(
        model_name: Optional[str] = None,
        file_path: Optional[str] = None,
        format: Optional[str] = None
    ) -> dict:
        """
        Save a COMSOL model to file.
        
        Args:
            model_name: Name of the model to save (default: current model)
            file_path: Path to save to (default: original file path)
            format: Save format - 'Comsol', 'Java', 'Matlab', or 'VBA' (default: Comsol/.mph)
        
        Returns:
            Save confirmation with file path, or error message
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            model.save(path=file_path, format=format)
            saved_path = file_path or model.file()
            
            return {
                "success": True,
                "model": model.name(),
                "saved_to": str(saved_path),
                "format": format or "Comsol",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to save model: {str(e)}"}
    
    @mcp.tool()
    def model_save_version(
        model_name: Optional[str] = None,
        description: Optional[str] = None
    ) -> dict:
        """
        Save a model with a timestamp version suffix.
        
        Creates a new file with structured path: 
        ./workspace/models/{model_name}/{model_name}_{timestamp}.mph
        
        Also saves a 'latest' copy: 
        ./workspace/models/{model_name}/{model_name}_latest.mph
        
        Useful for version control and design iterations.
        
        Args:
            model_name: Name of the model to save (default: current model)
            description: Optional description for this version (stored in metadata)
        
        Returns:
            Save confirmation with versioned file path, or error message
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            # Get model name for directory structure
            name = model.name()
            
            # Generate versioned path using new structure
            versioned_path = generate_version_path(name)
            
            # Save versioned copy
            model.save(path=versioned_path)
            
            # Also save as 'latest'
            latest_path = generate_latest_path(name)
            model.save(path=latest_path)
            
            return {
                "success": True,
                "model": name,
                "version_path": versioned_path,
                "latest_path": latest_path,
                "description": description,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to save version: {str(e)}"}
    
    @mcp.tool()
    def model_list() -> dict:
        """
        List all models currently loaded in the COMSOL session.
        
        Returns:
            List of models with their names, file paths, and status
        """
        if not session_manager.is_connected:
            return {"success": False, "error": "No active COMSOL session."}
        
        models = session_manager.models
        current = session_manager.current_model
        
        model_list = []
        for name, model in models.items():
            info = {
                "name": name,
                "is_current": name == current,
            }
            try:
                info["file"] = model.file()
                info["comsol_version"] = model.version()
            except Exception:
                pass
            model_list.append(info)
        
        return {
            "success": True,
            "models": model_list,
            "count": len(model_list),
            "current_model": current,
        }
    
    @mcp.tool()
    def model_set_current(model_name: str) -> dict:
        """
        Set the current active model for subsequent operations.
        
        Args:
            model_name: Name of the model to set as current
        
        Returns:
            Confirmation or error message
        """
        if session_manager.set_current_model(model_name):
            return {
                "success": True,
                "current_model": model_name,
            }
        return {
            "success": False,
            "error": f"Model not found: {model_name}"
        }
    
    @mcp.tool()
    def model_clone(
        model_name: Optional[str] = None,
        new_name: Optional[str] = None,
        set_current: bool = False
    ) -> dict:
        """
        Clone a model to create a copy for comparison or modification.
        
        Args:
            model_name: Name of the model to clone (default: current model)
            new_name: Name for the cloned model (auto-generated if not provided)
            set_current: Whether to set the clone as current model (default: False)
        
        Returns:
            Info about the cloned model, or error message
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            client = session_manager.client
            if client is None:
                return {"success": False, "error": "Client not available."}
            
            java_model = model.java.createCopy()
            if new_name:
                java_model.label(new_name)
            
            cloned_model = mph.Model(java_model)
            clone_name = session_manager.add_model(cloned_model)
            
            if set_current:
                session_manager.set_current_model(clone_name)
            
            return {
                "success": True,
                "original": model.name(),
                "clone": clone_name,
                "is_current": clone_name == session_manager.current_model,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to clone model: {str(e)}"}

    @mcp.tool()
    def model_execute_python(
        script: str,
        model_name: Optional[str] = None,
        confirm: str = ""
    ) -> dict:
        """
        Execute an advanced Python script against the active COMSOL model.

        Use this escape hatch for COMSOL Java API features that are not covered
        by the structured workflow or dedicated tools, such as ParametricCurve,
        Sweep, Extrude, Fillet, advanced selections, and custom result nodes.

        The script runs locally inside the MCP server process. It receives these
        variables:
        - model: active mph.Model
        - jm: model.java
        - session_manager: current session manager
        - mph: MPh module
        - Path: pathlib.Path

        To return structured data, assign a JSON-like value to result.

        Args:
            script: Python code to execute against the active model
            model_name: Model name (default: current model)
            confirm: Must be exactly EXECUTE_COMSOL_PYTHON

        Returns:
            Captured stdout and optional result value, or an error message
        """
        if confirm != "EXECUTE_COMSOL_PYTHON":
            return {
                "success": False,
                "error": "Refusing to execute script. Pass confirm='EXECUTE_COMSOL_PYTHON'.",
            }

        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        namespace: dict[str, Any] = {
            "model": model,
            "jm": model.java,
            "session_manager": session_manager,
            "mph": mph,
            "Path": Path,
            "result": None,
        }
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                exec(script, namespace, namespace)

            session_manager.sync_models()
            return {
                "success": True,
                "stdout": stdout.getvalue(),
                "result": _json_safe(namespace.get("result")),
                "model": model.name(),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": stdout.getvalue(),
            }
    
    @mcp.tool()
    def model_remove(model_name: str) -> dict:
        """
        Remove a model from memory.
        
        Args:
            model_name: Name of the model to remove
        
        Returns:
            Confirmation or error message
        """
        if model_name == session_manager.current_model:
            new_current = None
            for name in session_manager.models.keys():
                if name != model_name:
                    new_current = name
                    break
        
        if session_manager.remove_model(model_name):
            return {
                "success": True,
                "removed": model_name,
                "current_model": session_manager.current_model,
            }
        return {
            "success": False,
            "error": f"Failed to remove model: {model_name}"
        }
    
    @mcp.tool()
    def model_inspect(model_name: Optional[str] = None) -> dict:
        """
        Get detailed information about a model's structure and contents.
        
        Args:
            model_name: Name of the model to inspect (default: current model)
        
        Returns:
            Detailed model structure including parameters, physics, studies, etc.
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            info = {
                "name": model.name(),
                "file": model.file(),
                "comsol_version": model.version(),
                "parameters": dict(model.parameters()) if model.parameters() else {},
                "functions": model.functions(),
                "components": model.components(),
                "geometries": model.geometries(),
                "selections": model.selections(),
                "physics": model.physics(),
                "multiphysics": model.multiphysics(),
                "materials": model.materials(),
                "meshes": model.meshes(),
                "studies": model.studies(),
                "solutions": model.solutions(),
                "datasets": model.datasets(),
                "plots": model.plots(),
                "exports": model.exports(),
                "modules": model.modules(),
            }
            
            problems = model.problems()
            if problems:
                info["problems"] = problems
            
            return {"success": True, "model": info}
        except Exception as e:
            return {"success": False, "error": f"Failed to inspect model: {str(e)}"}

    @mcp.tool()
    def model_clear_all() -> dict:
        """
        Remove every model from the COMSOL session and free JVM memory.

        Use between unrelated modelling sessions; a long-lived COMSOL server
        accumulates models and the JVM heap grows with them.

        Returns:
            How many models were cleared
        """
        if not session_manager.is_connected:
            return {"success": False, "error": "No active COMSOL session."}
        try:
            names = list(session_manager.models.keys())
            session_manager.client.clear()
            session_manager._models.clear()
            session_manager._current_model = None
            return {"success": True, "cleared": names, "count": len(names)}
        except Exception as e:
            return {"success": False, "error": f"Failed to clear models: {str(e)}"}
