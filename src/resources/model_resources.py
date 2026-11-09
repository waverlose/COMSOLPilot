"""MCP Resources for COMSOL model information."""

from typing import Optional
from mcp.server.fastmcp import FastMCP

from ..tools.session import session_manager


def register_model_resources(mcp: FastMCP, worker=None) -> dict:
    """Register model resources with the MCP server."""
    
    @mcp.resource("comsol://session/info")
    def get_session_info() -> str:
        """
        Get current COMSOL session information as a resource.
        
        Returns formatted session status including connection state and loaded models.
        """
        status = worker.status() if worker is not None else session_manager.get_status()
        
        if not status.get("connected"):
            return "# COMSOL Session Status\n\n" + status.get("message", "No active COMSOL session.") + "\n\nThe first modeling request starts COMSOL automatically."
        
        lines = [
            "# COMSOL Session Status",
            "",
            f"**Version:** {status.get('version', 'unknown')}",
            f"**Cores:** {status.get('cores', 'unknown')}",
            f"**Mode:** {'Standalone' if status.get('standalone') else 'Client-Server'}",
            "",
            "## Loaded Models",
            "",
        ]
        
        models = status.get("models", [])
        current = status.get("current_model")
        
        if not models:
            lines.append("No models loaded.")
        else:
            for model in models:
                name = model.get("name", "unnamed")
                marker = " (current)" if name == current else ""
                lines.append(f"- **{name}**{marker}")
                if model.get("file"):
                    lines.append(f"  - File: {model['file']}")
        
        return "\n".join(lines)
    
    @mcp.resource("comsol://model/{name}/tree")
    def get_model_tree(name: str) -> str:
        """
        Get the model tree structure as a resource.
        
        Args:
            name: Model name
        
        Returns formatted model tree showing all features.
        """
        if worker is not None:
            return worker.read_resource("tree", name)
        model = session_manager.get_model(name)
        if model is None:
            return f"# Model Not Found\n\nModel '{name}' not found in current session."
        
        try:
            lines = [
                f"# Model Tree: {model.name()}",
                "",
                f"**File:** {model.file() or 'Not saved'}",
                f"**COMSOL Version:** {model.version()}",
                "",
            ]
            
            sections = [
                ("Parameters", "parameters"),
                ("Functions", "functions"),
                ("Components", "components"),
                ("Geometries", "geometries"),
                ("Selections", "selections"),
                ("Physics", "physics"),
                ("Multiphysics", "multiphysics"),
                ("Materials", "materials"),
                ("Meshes", "meshes"),
                ("Studies", "studies"),
                ("Solutions", "solutions"),
                ("Datasets", "datasets"),
                ("Plots", "plots"),
                ("Exports", "exports"),
            ]
            
            for title, attr in sections:
                items = getattr(model, attr)()
                if items:
                    lines.append(f"## {title}")
                    for item in items:
                        lines.append(f"- {item}")
                    lines.append("")
            
            problems = model.problems()
            if problems:
                lines.append("## Problems")
                for problem in problems:
                    lines.append(f"- **{problem.get('node', 'unknown')}**: {problem.get('message', '')}")
                lines.append("")
            
            return "\n".join(lines)
        except Exception as e:
            return f"# Error\n\nFailed to get model tree: {str(e)}"
    
    @mcp.resource("comsol://model/{name}/parameters")
    def get_model_parameters(name: str) -> str:
        """
        Get model parameters as a resource.
        
        Args:
            name: Model name
        
        Returns formatted parameter list with values and descriptions.
        """
        if worker is not None:
            return worker.read_resource("parameters", name)
        model = session_manager.get_model(name)
        if model is None:
            return f"# Model Not Found\n\nModel '{name}' not found in current session."
        
        try:
            params = model.parameters()
            descriptions = model.descriptions()
            
            lines = [
                f"# Parameters: {model.name()}",
                "",
                "| Name | Value | Description |",
                "|------|-------|-------------|",
            ]
            
            for param_name, value in params.items():
                desc = descriptions.get(param_name, "")
                lines.append(f"| {param_name} | `{value}` | {desc} |")
            
            return "\n".join(lines)
        except Exception as e:
            return f"# Error\n\nFailed to get parameters: {str(e)}"
    
    @mcp.resource("comsol://model/{name}/physics")
    def get_model_physics(name: str) -> str:
        """
        Get model physics interfaces as a resource.
        
        Args:
            name: Model name
        
        Returns formatted physics interface list.
        """
        if worker is not None:
            return worker.read_resource("physics", name)
        model = session_manager.get_model(name)
        if model is None:
            return f"# Model Not Found\n\nModel '{name}' not found in current session."
        
        try:
            physics_list = model.physics()
            multiphysics_list = model.multiphysics()
            
            lines = [
                f"# Physics: {model.name()}",
                "",
            ]
            
            if physics_list:
                lines.append("## Physics Interfaces")
                for p in physics_list:
                    lines.append(f"- {p}")
                lines.append("")
            
            if multiphysics_list:
                lines.append("## Multiphysics Couplings")
                for m in multiphysics_list:
                    lines.append(f"- {m}")
                lines.append("")
            
            if not physics_list and not multiphysics_list:
                lines.append("No physics interfaces defined.")
            
            return "\n".join(lines)
        except Exception as e:
            return f"# Error\n\nFailed to get physics: {str(e)}"

    return {"tree": get_model_tree, "parameters": get_model_parameters,
            "physics": get_model_physics}
