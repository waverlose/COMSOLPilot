"""Results evaluation and export tools for COMSOLPilot."""

from typing import Optional, Union, Sequence
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from .session import session_manager


def _get_or_create_plot_group(result, tag: str, plot_group_type: str, label: Optional[str] = None):
    try:
        group = result(tag)
        created = False
    except Exception:
        group = session_manager.retry_comsol_busy(lambda: result.create(tag, plot_group_type))
        created = True
    if label:
        group.label(label)
    return group, created


def _get_or_create_plot_feature(group, tag: str, feature_type: str):
    try:
        feature = group.feature(tag)
        created = False
    except Exception:
        feature = session_manager.retry_comsol_busy(lambda: group.feature().create(tag, feature_type))
        created = True
    return feature, created


def _set_if_supported(node, key: str, value) -> Optional[str]:
    try:
        node.set(key, value)
        return None
    except Exception as exc:
        return str(exc)


def register_results_tools(mcp: FastMCP) -> None:
    """Register results tools with the MCP server."""
    
    @mcp.tool()
    def results_evaluate(
        expression: Union[str, Sequence[str]],
        unit: Optional[str] = None,
        dataset: Optional[str] = None,
        inner: Optional[Union[int, str, Sequence[int]]] = None,
        outer: Optional[Union[int, Sequence[int]]] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Evaluate an expression on a solution dataset.
        
        Args:
            expression: Expression(s) to evaluate, e.g., "es.normE" or ["x", "y", "es.normE"]
            unit: Desired unit for result, e.g., "V/m", "pF"
            dataset: Dataset name (default: uses default dataset)
            inner: For time-dependent solutions: index, 'first', 'last', or list of indices
            outer: For parametric sweeps: index or list of indices
            model_name: Model name (default: current model)
        
        Returns:
            Evaluated values as lists, or error message
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            result = model.evaluate(
                expression,
                unit=unit,
                dataset=dataset,
                inner=inner,
                outer=outer,
            )
            
            import numpy as np
            if isinstance(result, np.ndarray):
                if result.ndim == 0:
                    value = float(result)
                else:
                    value = result.tolist()
            elif isinstance(result, (list, tuple)):
                value = [v.tolist() if hasattr(v, 'tolist') else v for v in result]
            else:
                value = result
            
            return {
                "success": True,
                "expression": expression,
                "unit": unit,
                "dataset": dataset,
                "value": value,
                "shape": getattr(result, 'shape', None),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to evaluate: {str(e)}"}
    
    @mcp.tool()
    def results_global_evaluate(
        expression: Optional[str] = None,
        unit: Optional[str] = None,
        dataset: Optional[str] = None,
        expressions: Optional[Sequence[str]] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Evaluate a global expression (returns a single scalar value).
        
        Common global expressions include:
        - Integration: "intop1(T)" where intop1 is an integration operator
        - Maximum: "maxop1(T)" 
        - Derived values: "2*es.intWe/U^2" for capacitance
        
        Args:
            expression: Global expression to evaluate
            unit: Desired unit for result
            dataset: Dataset name
            model_name: Model name (default: current model)
        
        Returns:
            Single numerical value
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        wanted = list(expressions) if expressions else ([expression] if expression else [])
        if not wanted:
            return {"success": False, "error": "Pass 'expression' or 'expressions'."}

        # MPh creates one numerical node per evaluation. A syntax error used to
        # leave that node behind ("gev1") and the next solve died on the invalid
        # expression - a destructive side effect. Track nodes and roll back.
        def _numerical_tags():
            try:
                return {str(tag) for tag in model.java.result().numerical().tags()}
            except Exception:
                return set()

        import numpy as np

        results = []
        for item in wanted:
            before = _numerical_tags()
            try:
                result = model.evaluate(item, unit=unit, dataset=dataset)
                value = float(np.asarray(result).flatten()[0])
                results.append({"expression": item, "value": value, "unit": unit})
            except Exception as exc:
                leaked = sorted(_numerical_tags() - before)
                for tag in leaked:
                    try:
                        model.java.result().numerical().remove(tag)
                    except Exception:
                        pass
                results.append({"expression": item, "error": str(exc)[:400],
                                "rolled_back_nodes": leaked})

        failed = [item for item in results if "error" in item]
        response = {"success": not failed, "unit": unit, "results": results}
        if len(results) == 1 and not failed:
            response["expression"] = results[0]["expression"]
            response["value"] = results[0]["value"]
        if failed:
            response["error"] = (f"{len(failed)} expression(s) failed; "
                                 "no result nodes were left behind.")
        return response
    
    @mcp.tool()
    def results_inner_values(
        dataset: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Get inner solution indices and values (time steps in time-dependent study).
        
        Args:
            dataset: Dataset name (default: default dataset)
            model_name: Model name (default: current model)
        
        Returns:
            Arrays of indices and corresponding values (e.g., time values)
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            indices, values = model.inner(dataset)
            
            return {
                "success": True,
                "dataset": dataset,
                "indices": indices.tolist() if hasattr(indices, 'tolist') else list(indices),
                "values": values.tolist() if hasattr(values, 'tolist') else list(values),
                "count": len(values),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to get inner values: {str(e)}"}
    
    @mcp.tool()
    def results_outer_values(
        dataset: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Get outer solution indices and values (parameter values in parametric sweep).
        
        Args:
            dataset: Dataset name (default: default dataset)
            model_name: Model name (default: current model)
        
        Returns:
            Arrays of indices and corresponding parameter values
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            indices, values = model.outer(dataset)
            
            return {
                "success": True,
                "dataset": dataset,
                "indices": indices.tolist() if hasattr(indices, 'tolist') else list(indices),
                "values": values.tolist() if hasattr(values, 'tolist') else list(values),
                "count": len(values),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to get outer values: {str(e)}"}
    
    @mcp.tool()
    def results_export_data(
        node_name: Optional[str] = None,
        file_path: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Export data from an export node.
        
        Args:
            node_name: Export node name (default: run all exports)
            file_path: Output file path (overrides node setting)
            model_name: Model name (default: current model)
        
        Returns:
            Export confirmation with file path
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            model.export(node_name, file_path)
            
            return {
                "success": True,
                "node": node_name,
                "file": file_path,
                "message": f"Export completed: {node_name or 'all exports'}",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to export data: {str(e)}"}
    
    @mcp.tool()
    def results_export_image(
        node_name: Optional[str] = None,
        file_path: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Export a plot as an image.
        
        Args:
            node_name: Plot export node name
            file_path: Output image path (e.g., "results.png", "field.png")
            model_name: Model name (default: current model)
        
        Returns:
            Export confirmation with file path
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            model.export(node_name, file_path)
            
            return {
                "success": True,
                "node": node_name,
                "file": file_path,
                "message": f"Image exported to: {file_path}",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to export image: {str(e)}"}
    
    @mcp.tool()
    def results_label_tables(
        label: Optional[str] = None,
        only_default: bool = True,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Rename table nodes in the Tables pane of COMSOL Desktop.

        COMSOL auto-names evaluated tables with localized defaults like
        "Table 1" / "表格 1". With a label configured (launcher menu 5 or
        workspace/settings.json key "table_label", default "COMSOLPilot"),
        this renames those tables to "<label>", "<label> 2", ... so the
        Tables pane shows recognizable names instead of generic ones.

        Args:
            label: Custom label; omit to use the launcher-configured one
            only_default: Only rename tables still carrying default names
                ("Table N" / "表格 N"); false renames every table in order
            model_name: Model name (default: current model)

        Returns:
            List of renames applied
        """
        import re

        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        # Opt-in only: without an explicit label (or a configured one) this is
        # a no-op, so models are never stamped with COMSOLPilot names.
        final = (label or "").strip()
        if not final:
            try:
                settings_path = (
                    pathlib.Path(__file__).resolve().parent.parent.parent
                    / "workspace" / "settings.json")
                cfg = json.loads(settings_path.read_text(encoding="utf-8"))
                final = str(cfg.get("table_label") or "").strip()
            except Exception:
                final = ""
        if not final:
            return {
                "success": True,
                "label": None,
                "renamed": [],
                "count": 0,
                "note": "No label given, so nothing was renamed. Pass label=... "
                        "to opt in.",
            }

        try:
            table_list = model.java.result().table()
            pattern = re.compile(r"^(?:Table|表格)\s*\d+$", re.IGNORECASE)
            renames = []
            counter = 0
            used: set[str] = set()
            for tag in table_list.tags():
                table = model.java.result().table(str(tag))
                try:
                    current = str(table.label())
                except Exception:
                    current = str(tag)
                if only_default and not pattern.match(current):
                    continue
                counter += 1
                new = final if counter == 1 else f"{final} {counter}"
                while new in used:
                    counter += 1
                    new = f"{final} {counter}"
                used.add(new)
                table.label(new)
                renames.append({"tag": str(tag), "from": current, "to": new})

            return {
                "success": True,
                "label": final,
                "renamed": renames,
                "count": len(renames),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to rename tables: {str(e)}"}

    @mcp.tool()
    def results_annotate(
        text: str,
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Put readable text into COMSOL Desktop via an annotation plot node.

        Creates (or reuses) a 3D plot group labeled "COMSOLPilot" containing
        one Annotation feature with your text. The text renders in the
        Desktop graphics window when that plot is selected. Calling the tool
        again updates the same annotation instead of accumulating nodes.

        Args:
            text: Text to display; multi-line works (newline-separated)
            model_name: Model name (default: current model)

        Returns:
            Plot group tag, whether nodes were reused, and the stored text
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            jm = model.java
            res = jm.result()
            tags = [str(t) for t in res.tags()]
            group_tag = "pg_annot"
            if group_tag not in tags:
                res.create(group_tag, "PlotGroup3D")
                created_group = True
            else:
                created_group = False
            pg = jm.result(group_tag)
            try:
                pg.label("Annotations")
            except Exception:
                pass

            dataset_note = ""
            try:
                dtags = [str(t) for t in res.dataset().tags()]
                if dtags:
                    pg.set("data", dtags[0])
                else:
                    dataset_note = "no dataset available; annotation may not render until the model is solved"
            except Exception as exc:
                dataset_note = f"dataset binding skipped: {str(exc)[:80]}"

            try:
                ann = pg("ann1")
                reused = True
            except Exception:
                ann = pg.create("ann1", "Annotation")
                reused = False
            ann.set("text", str(text))

            return {
                "success": True,
                "plot_group": group_tag,
                "label": "Annotations",
                "created_group": created_group,
                "annotation_reused": reused,
                "text": str(text),
                "dataset_note": dataset_note,
                "hint": "Select the COMSOLPilot plot in Desktop to see the text in the graphics window.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to annotate: {str(e)}"}

    @mcp.tool()
    def results_exports_list(model_name: Optional[str] = None) -> dict:
        """
        List all export nodes defined in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of export node names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            exports = model.exports()
            return {
                "success": True,
                "exports": exports,
                "count": len(exports),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list exports: {str(e)}"}
    
    @mcp.tool()
    def results_plots_list(model_name: Optional[str] = None) -> dict:
        """
        List all plot nodes defined in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of plot node names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            plots = []
            for plot in model.java.result():
                plots.append({
                    "tag": plot.tag(),
                    "label": plot.label(),
                    "type": plot.getType(),
                })
            return {
                "success": True,
                "plots": plots,
                "count": len(plots),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list plots: {str(e)}"}

    @mcp.tool()
    def results_create_plot_3d(
        plot_group_tag: str,
        label: Optional[str] = None,
        feature_tag: str = "plot1",
        feature_type: str = "Surface",
        expression: Union[str, Sequence[str]] = "T",
        unit: Optional[str] = None,
        dataset: Optional[str] = None,
        description: Optional[str] = None,
        run: bool = True,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create or update a 3D result plot group.

        Common feature_type values:
        - Surface: 3D surface color plot for scalar fields, for example T or spf.U
        - Streamline: 3D streamline plot for vector fields, for example [u, v, w]
        - Slice: 3D slice plot for scalar fields

        Args:
            plot_group_tag: Stable COMSOL result plot group tag, for example pg_temp3d
            label: Human-readable plot group label shown in COMSOL
            feature_tag: Stable feature tag inside the plot group
            feature_type: COMSOL plot feature type, for example Surface, Streamline, or Slice
            expression: COMSOL expression. Use a string for scalar plots or 3 strings for vector streamlines
            unit: Optional expression unit, for example K or m/s
            dataset: Optional dataset tag, for example dset1
            description: Optional expression description shown in COMSOL
            run: Whether to run/update the plot group after creation
            model_name: Model name (default: current model)

        Returns:
            Plot group and feature creation status
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            result = model.java.result()
            group, group_created = _get_or_create_plot_group(result, plot_group_tag, "PlotGroup3D", label)
            warnings = []

            if dataset:
                error = _set_if_supported(group, "data", dataset)
                if error:
                    warnings.append({"property": "data", "value": dataset, "error": error})

            feature, feature_created = _get_or_create_plot_feature(group, feature_tag, feature_type)
            expr_value = list(expression) if isinstance(expression, (list, tuple)) else expression
            error = _set_if_supported(feature, "expr", expr_value)
            if error:
                warnings.append({"property": "expr", "value": expr_value, "error": error})

            if unit:
                error = _set_if_supported(feature, "unit", unit)
                if error:
                    warnings.append({"property": "unit", "value": unit, "error": error})

            if description:
                error = _set_if_supported(feature, "descr", description)
                if error:
                    warnings.append({"property": "descr", "value": description, "error": error})

            run_error = None
            if run:
                try:
                    session_manager.retry_comsol_busy(lambda: group.run())
                except Exception as exc:
                    run_error = str(exc)

            return {
                "success": True,
                "plot_group": {
                    "tag": group.tag(),
                    "label": group.label(),
                    "type": group.getType(),
                    "created": group_created,
                },
                "feature": {
                    "tag": feature.tag(),
                    "label": feature.label(),
                    "type": feature.getType(),
                    "created": feature_created,
                    "expression": expr_value,
                    "unit": unit,
                },
                "warnings": warnings,
                "run_error": run_error,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create 3D plot: {str(e)}"}

    @mcp.tool()
    def results_create_standard_3d_plots(
        temperature_expression: str = "T",
        velocity_expression: str = "spf.U",
        streamline_expression: Sequence[str] = ("u", "v", "w"),
        dataset: Optional[str] = None,
        run: bool = True,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create standard 3D result plots for thermal-fluid models.

        This creates:
        - 3D Temperature Surface
        - 3D Velocity Magnitude
        - 3D Flow Streamlines

        Args:
            temperature_expression: Temperature expression, usually T
            velocity_expression: Velocity magnitude expression, usually spf.U
            streamline_expression: Velocity vector components for streamlines, usually [u, v, w]
            dataset: Optional dataset tag, for example dset1
            run: Whether to run/update each plot group after creation
            model_name: Model name (default: current model)

        Returns:
            Created plot group summary
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            specs = [
                {
                    "plot_group_tag": "pg_temp3d",
                    "label": "3D Temperature Surface",
                    "feature_tag": "surf_temp",
                    "feature_type": "Surface",
                    "expression": temperature_expression,
                    "unit": "K",
                    "description": "Temperature",
                },
                {
                    "plot_group_tag": "pg_vel3d",
                    "label": "3D Velocity Magnitude",
                    "feature_tag": "surf_vel",
                    "feature_type": "Surface",
                    "expression": velocity_expression,
                    "unit": "m/s",
                    "description": "Velocity magnitude",
                },
                {
                    "plot_group_tag": "pg_stream3d",
                    "label": "3D Flow Streamlines",
                    "feature_tag": "str1",
                    "feature_type": "Streamline",
                    "expression": list(streamline_expression),
                    "unit": None,
                    "description": "Velocity field",
                },
            ]

            result = model.java.result()
            created_plots = []
            warnings = []
            for spec in specs:
                group, group_created = _get_or_create_plot_group(
                    result,
                    spec["plot_group_tag"],
                    "PlotGroup3D",
                    spec["label"],
                )
                if dataset:
                    error = _set_if_supported(group, "data", dataset)
                    if error:
                        warnings.append({"plot_group": group.tag(), "property": "data", "error": error})

                try:
                    feature, feature_created = _get_or_create_plot_feature(
                        group,
                        spec["feature_tag"],
                        spec["feature_type"],
                    )
                except Exception as exc:
                    if spec["feature_type"] != "Streamline":
                        raise
                    warnings.append({
                        "plot_group": group.tag(),
                        "feature_type": "Streamline",
                        "error": str(exc),
                        "fallback": "Surface",
                    })
                    feature, feature_created = _get_or_create_plot_feature(
                        group,
                        "surf_stream_fallback",
                        "Surface",
                    )
                    spec = {
                        **spec,
                        "feature_tag": "surf_stream_fallback",
                        "feature_type": "Surface",
                        "expression": velocity_expression,
                        "unit": "m/s",
                        "description": "Velocity magnitude fallback",
                    }

                expr_value = spec["expression"]
                error = _set_if_supported(feature, "expr", expr_value)
                if error:
                    warnings.append({"plot_group": group.tag(), "feature": feature.tag(), "property": "expr", "error": error})
                if spec["unit"]:
                    error = _set_if_supported(feature, "unit", spec["unit"])
                    if error:
                        warnings.append({"plot_group": group.tag(), "feature": feature.tag(), "property": "unit", "error": error})
                if spec["description"]:
                    error = _set_if_supported(feature, "descr", spec["description"])
                    if error:
                        warnings.append({"plot_group": group.tag(), "feature": feature.tag(), "property": "descr", "error": error})

                run_error = None
                if run:
                    try:
                        session_manager.retry_comsol_busy(lambda group=group: group.run())
                    except Exception as exc:
                        run_error = str(exc)

                created_plots.append({
                    "plot_group": group.tag(),
                    "label": group.label(),
                    "created": group_created,
                    "feature": feature.tag(),
                    "feature_type": feature.getType(),
                    "feature_created": feature_created,
                    "run_error": run_error,
                })

            return {
                "success": True,
                "plots": created_plots,
                "warnings": warnings,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create standard 3D plots: {str(e)}"}

    REPORT_LEVELS = ("brief", "intermediate", "complete", "model", "installation", "user", "test", "none")
    REPORT_FORMATS = ("html", "docx")

    @mcp.tool()
    def results_generate_report(
        report_tag: str = "rep1",
        file_path: Optional[str] = None,
        format: str = "html",
        level: str = "brief",
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Generate a simulation report from the solved model.

        Tries COMSOL's native Report node first. That node silently writes nothing
        in some headless/server sessions, so if no file appears the HTML report is
        generated locally instead -- a successful call always means a real file.

        Args:
            report_tag: Tag for the COMSOL report node, e.g. 'rep1'
            file_path: Destination file. Defaults to workspace/reports/<model>.<ext>
            format: 'html' or 'docx'
            level: 'brief', 'intermediate', 'complete', 'model', 'installation',
                'user', 'test' or 'none'
            model_name: Model name (default: current model)

        Returns:
            The exported report path and which generator produced it
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {"success": False, "error": f"Model not found: {model_name or 'no current model'}"}
        if format not in REPORT_FORMATS:
            return {"success": False, "error": f"format must be one of {list(REPORT_FORMATS)}."}
        if level not in REPORT_LEVELS:
            return {"success": False, "error": f"level must be one of {list(REPORT_LEVELS)}."}

        if not file_path:
            from pathlib import Path
            reports = Path(__file__).resolve().parents[2] / "workspace" / "reports"
            reports.mkdir(parents=True, exist_ok=True)
            safe_name = model_name or session_manager.current_model or "model"
            file_path = str(reports / f"{safe_name}.{format}")

        native_error = None
        try:
            jm = model.java
            if report_tag in list(jm.result().report().tags()):
                jm.result().report().remove(report_tag)
            report = jm.result().report().create(report_tag, "Report")
            report.set("level", level)
            report.set("format", format)
            report.set("filename", file_path)
            report.run()
        except Exception as exc:
            native_error = str(exc)

        from pathlib import Path
        target = Path(file_path)
        if target.exists() and target.stat().st_size > 0:
            return {
                "success": True,
                "generator": "comsol",
                "report_tag": report_tag,
                "file_path": file_path,
                "format": format,
                "level": level,
                "size_bytes": target.stat().st_size,
            }

        if format != "html":
            return {
                "success": False,
                "generator": "comsol",
                "file_path": file_path,
                "error": native_error or "COMSOL produced an empty report and no local fallback exists for this format.",
            }

        try:
            html = _render_html_report(model, model_name or session_manager.current_model or "model")
        except Exception as exc:
            return {"success": False,
                    "error": f"Native report failed ({native_error or 'empty output'}) and local render failed: {exc}"}

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        return {
            "success": True,
            "generator": "local",
            "reason": "COMSOL's Report node produced no file; rendered locally instead.",
            "file_path": str(target),
            "format": "html",
            "level": level,
            "size_bytes": target.stat().st_size,
        }

    def _render_html_report(model, name: str) -> str:
        """Render a self-contained HTML summary straight from the model tree."""
        import html as _html

        def row(label, value):
            return f"<tr><th>{_html.escape(str(label))}</th><td>{_html.escape(str(value))}</td></tr>"

        rows = [row("Model", name)]
        for label, getter in (("Components", "components"), ("Geometries", "geometries"),
                              ("Materials", "materials"), ("Physics", "physics"),
                              ("Multiphysics", "multiphysics"), ("Meshes", "meshes"),
                              ("Studies", "studies"), ("Datasets", "datasets"),
                              ("Plots", "plots"), ("Exports", "exports")):
            try:
                value = getattr(model, getter)()
                rows.append(row(label, ", ".join(str(v) for v in value) or "-"))
            except Exception:
                rows.append(row(label, "(unavailable)"))

        sections = []
        try:
            jm = model.java
            for physics_tag in jm.physics().tags():
                feature_rows = []
                for feature in jm.physics(physics_tag).feature():
                    try:
                        entities = list(feature.selection().entities())
                    except Exception:
                        entities = []
                    feature_rows.append(row(f"{feature.tag()} ({feature.getType()})", entities or "no selection"))
                if feature_rows:
                    sections.append(
                        f"<h2>Physics: {_html.escape(str(physics_tag))}</h2><table>{''.join(feature_rows)}</table>")
        except Exception:
            pass

        problems = []
        try:
            problems = list(model.problems())
        except Exception:
            pass
        problem_html = ("<h2>Problems</h2><ul>" + "".join(f"<li>{_html.escape(str(p))}</li>" for p in problems) + "</ul>"
                        if problems else "")

        return (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>COMSOLPilot report - {_html.escape(name)}</title>"
            "<style>body{font-family:system-ui,Segoe UI,sans-serif;margin:32px;line-height:1.6;color:#111}"
            "h1{font-size:20px}h2{font-size:15px;margin-top:24px}"
            "table{border-collapse:collapse;margin-top:8px}"
            "th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;font-size:13px}"
            "th{background:#f6f6f6;font-weight:500}"
            ".note{color:#666;font-size:12px;margin-top:24px}</style></head><body>"
            f"<h1>COMSOLPilot report - {_html.escape(name)}</h1>"
            f"<table>{''.join(rows)}</table>"
            f"{problem_html}{''.join(sections)}"
            "<p class=\"note\">Rendered locally from the model tree. Boundary condition "
            "selections are listed so an empty selection is visible at a glance.</p>"
            "</body></html>"
        )
