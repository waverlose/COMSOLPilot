"""Study and solving tools for COMSOLPilot."""

from typing import Optional
from mcp.server.fastmcp import FastMCP

from .session import session_manager
from ..async_handler.solver import async_solver


def register_study_tools(mcp: FastMCP) -> None:
    """Register study and solving tools with the MCP server."""
    
    @mcp.tool()
    def study_ensure(
        study_name: str = "std1",
        study_type: str = "Stationary",
        step_tag: Optional[str] = None,
        tlist: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Ensure a study exists with one analysis step.
        
        Use this before study_solve in automated workflows. Common study_type
        values are Stationary and TimeDependent.
        
        Args:
            study_name: Study tag to create or reuse (default: 'std1')
            study_type: Study step type, for example Stationary or TimeDependent
            step_tag: Optional study step tag (default based on study_type)
            model_name: Model name (default: current model)
        
        Returns:
            Study creation status and step info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        supported = {
            "Stationary": {"step": "stat", "comsol_type": "Stationary"},
            "TimeDependent": {"step": "time", "comsol_type": "Transient"},
            "FrequencyDomain": {"step": "freq", "comsol_type": "Frequency"},
            "Eigenfrequency": {"step": "eig", "comsol_type": "Eigenfrequency"},
        }
        if study_type not in supported:
            return {
                "success": False,
                "error": f"Unsupported study_type: {study_type}",
                "supported_study_types": list(supported.keys()),
            }
        
        try:
            jm = model.java
            existing = {study.tag(): study for study in jm.study()}
            created_study = False
            if study_name in existing:
                study = existing[study_name]
            else:
                study = jm.study().create(study_name)
                created_study = True
            
            tag = step_tag or supported[study_type]["step"]
            existing_steps = {step.tag(): step for step in study.feature()}
            created_step = False
            if tag in existing_steps:
                step = existing_steps[tag]
            else:
                step = study.feature().create(tag, supported[study_type]["comsol_type"])
                created_step = True

            if tlist:
                comsol_type = supported[study_type]["comsol_type"]
                if comsol_type != "Transient":
                    return {"success": False,
                            "error": "tlist is only valid for TimeDependent studies."}
                step.set("tlist", str(tlist))
            
            return {
                "success": True,
                "study": study.tag(),
                "study_type": study_type,
                "tlist": tlist,
                "step": step.tag(),
                "created_study": created_study,
                "created_step": created_step,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to ensure study: {str(e)}"}
    
    @mcp.tool()
    def study_list(model_name: Optional[str] = None) -> dict:
        """
        List all studies in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of study names with their types
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            study_info = []
            for study in model.java.study():
                info = {
                    "tag": study.tag(),
                    "label": study.label(),
                    "steps": [
                        {"tag": step.tag(), "label": step.label(), "type": step.getType()}
                        for step in study.feature()
                    ],
                }
                study_info.append(info)
            
            return {
                "success": True,
                "studies": study_info,
                "count": len(study_info),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list studies: {str(e)}"}
    
    @mcp.tool()
    def study_solve(
        study_name: Optional[str] = None,
        model_name: Optional[str] = None,
        wait: bool = True,
        timeout: Optional[float] = None
    ) -> dict:
        """
        Solve a study (synchronous by default).
        
        Args:
            study_name: Study to solve (None for all studies)
            model_name: Model name (default: current model)
            wait: If True, wait for completion; if False, return immediately
            timeout: Maximum wait time in seconds (only used if wait=True)
        
        Returns:
            Solution status, or error message
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        if async_solver.is_running:
            return {
                "success": False,
                "error": "Another solving operation is in progress. Use study_get_progress to check status."
            }
        
        try:
            if wait:
                if study_name:
                    # Use the Java tag directly; MPh's high-level solve path expects
                    # localized labels in some GUI languages.
                    model.java.study(study_name).run()
                else:
                    model.solve(study_name)
                return {
                    "success": True,
                    "study": study_name,
                    "message": "Solving completed.",
                }
            else:
                started = async_solver.start_solve(model, study_name)
                if started:
                    return {
                        "success": True,
                        "study": study_name,
                        "message": "Solving started in background. Use study_get_progress to monitor.",
                        "async": True,
                    }
                else:
                    return {
                        "success": False,
                        "error": "Failed to start async solver."
                    }
        except Exception as e:
            return {"success": False, "error": f"Failed to solve: {str(e)}"}
    
    @mcp.tool()
    def study_solve_async(
        study_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Start solving a study in the background (asynchronous).
        
        Use study_get_progress to monitor progress and study_cancel to stop.
        
        Args:
            study_name: Study to solve (None for all studies)
            model_name: Model name (default: current model)
        
        Returns:
            Confirmation that solving started, or error message
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        if async_solver.is_running:
            progress = async_solver.get_progress()
            return {
                "success": False,
                "error": "Another solving operation is already in progress.",
                "current_progress": progress,
            }
        
        try:
            started = async_solver.start_solve(model, study_name)
            if started:
                return {
                    "success": True,
                    "study": study_name,
                    "model": model.name(),
                    "message": "Solving started in background.",
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to start async solver."
                }
        except Exception as e:
            return {"success": False, "error": f"Failed to start solving: {str(e)}"}
    
    @mcp.tool()
    def study_get_progress() -> dict:
        """
        Get the progress of the current solving operation.
        
        Returns:
            Progress information including status, percentage, and elapsed time
        """
        progress = async_solver.get_progress()
        return {
            "success": True,
            "progress": progress,
        }
    
    @mcp.tool()
    def study_cancel() -> dict:
        """
        Cancel the current solving operation.
        
        Note: The solver may take a moment to respond to cancellation.
        
        Returns:
            Cancellation status
        """
        if async_solver.cancel():
            return {
                "success": True,
                "message": "Cancellation requested. Solver will stop at next checkpoint.",
            }
        return {
            "success": False,
            "message": "No solving operation in progress.",
        }
    
    @mcp.tool()
    def study_wait(timeout: Optional[float] = None) -> dict:
        """
        Wait for the current solving operation to complete.
        
        Args:
            timeout: Maximum time to wait in seconds (None for indefinite)
        
        Returns:
            Final progress status
        """
        completed = async_solver.wait(timeout=timeout)
        progress = async_solver.get_progress()
        
        return {
            "success": True,
            "completed": completed,
            "progress": progress,
        }
    
    @mcp.tool()
    def solutions_list(model_name: Optional[str] = None) -> dict:
        """
        List all solutions in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of solution configurations
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            solutions = model.solutions()
            return {
                "success": True,
                "solutions": solutions,
                "count": len(solutions),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list solutions: {str(e)}"}
    
    @mcp.tool()
    def datasets_list(model_name: Optional[str] = None) -> dict:
        """
        List all datasets in a model.
        
        Datasets represent solution data that can be evaluated or visualized.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of dataset names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            datasets = model.datasets()
            return {
                "success": True,
                "datasets": datasets,
                "count": len(datasets),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list datasets: {str(e)}"}
