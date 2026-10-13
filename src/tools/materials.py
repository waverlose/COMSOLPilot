"""Material tools for COMSOLPilot."""

from typing import Optional, Sequence, Union
from mcp.server.fastmcp import FastMCP

from .session import session_manager


DomainSelection = Optional[Union[str, Sequence[int]]]


def _first_component(jm):
    for comp in jm.component():
        return comp
    return None


def _apply_selection(material, domain_selection: DomainSelection) -> None:
    if domain_selection is None:
        return
    if isinstance(domain_selection, str):
        material.selection().named(domain_selection)
    else:
        material.selection().set([int(domain) for domain in domain_selection])


def register_material_tools(mcp: FastMCP) -> None:
    """Register material tools with the MCP server."""
    
    @mcp.tool()
    def material_list(model_name: Optional[str] = None) -> dict:
        """
        List materials in the model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            Materials with tags and labels where available
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            jm = model.java
            materials = []
            for comp in jm.component():
                for material in comp.material():
                    materials.append({
                        "component": comp.tag(),
                        "tag": material.tag(),
                        "label": material.label(),
                    })
            return {"success": True, "materials": materials, "count": len(materials)}
        except Exception as e:
            return {"success": False, "error": f"Failed to list materials: {str(e)}"}
    
    @mcp.tool()
    def material_create_basic(
        material_name: str = "mat1",
        label: Optional[str] = None,
        properties: Optional[dict] = None,
        component_name: Optional[str] = None,
        domain_selection: DomainSelection = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create or update a basic material in a component.
        
        The properties dictionary uses COMSOL material property keys and expression
        values, for example {'thermalconductivity': '130[W/(m*K)]'}.
        
        Args:
            material_name: Material tag to create or update, for example 'mat1'
            label: Human-readable material label, for example 'Silicon'
            properties: COMSOL material properties and values
            component_name: Component tag (default: first component)
            domain_selection: Domain numbers or named selection; null applies to all domains
            model_name: Model name (default: current model)
        
        Returns:
            Material creation/update status
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
            
            existing = {material.tag(): material for material in comp.material()}
            created = False
            if material_name in existing:
                material = existing[material_name]
            else:
                material = comp.material().create(material_name, "Common")
                created = True
            
            if label:
                material.label(label)
            
            if properties:
                group = material.propertyGroup("def")
                for key, value in properties.items():
                    # COMSOL accepts scalar strings or string arrays depending on property.
                    group.set(str(key), value)
            
            _apply_selection(material, domain_selection)
            
            return {
                "success": True,
                "material": {
                    "tag": material.tag(),
                    "label": material.label(),
                    "component": comp.tag(),
                    "created": created,
                    "properties": properties or {},
                    "domain_selection": domain_selection,
                },
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create material: {str(e)}"}
    
    @mcp.tool()
    def material_assign(
        material_name: str,
        domain_selection: DomainSelection = None,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Assign an existing material to domains.
        
        Args:
            material_name: Existing material tag, for example 'mat1'
            domain_selection: Domain numbers or named selection; null applies to all domains
            component_name: Component tag (default: first component)
            model_name: Model name (default: current model)
        
        Returns:
            Material assignment status
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
            
            existing = {material.tag(): material for material in comp.material()}
            if material_name not in existing:
                return {"success": False, "error": f"Material not found: {material_name}", "available_materials": list(existing)}
            
            material = existing[material_name]
            _apply_selection(material, domain_selection)
            
            return {
                "success": True,
                "material": material.tag(),
                "label": material.label(),
                "component": comp.tag(),
                "domain_selection": domain_selection,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to assign material: {str(e)}"}
