"""Surrogate model training tools for COMSOLPilot.

COMSOL 6.2 added the Surrogate Model Training study step: a DOE-based
parametric sweep (Latin hypercube sampling) generates training data, and a
surrogate model is then fitted and exposed as a function under Global
Definitions. Evaluating that function approximates the full FE model at a
tiny fraction of the cost.

License notes:
- ``dnn`` (Deep Neural Network) ships with base COMSOL Multiphysics;
- ``gp`` (Gaussian Process) and ``pce`` (Polynomial Chaos Expansion) require
  the Uncertainty Quantification Module.
"""

from typing import Optional, Sequence, Union
from mcp.server.fastmcp import FastMCP

from .session import session_manager


# Feature type string as documented in the COMSOL 6.2 Programming Reference:
#   model.study(stdname).create(fname, "SurrogateModelTraining");
_SURROGATE_FEATURE = "SurrogateModelTraining"

_SURROGATE_MODELS = ("none", "dnn", "gp", "pce")
_SURROGATE_MODEL_REQUIREMENTS = {
    "none": "DOE data generation only, no model is trained",
    "dnn": "included with base COMSOL Multiphysics",
    "gp": "requires the Uncertainty Quantification Module",
    "pce": "requires the Uncertainty Quantification Module",
}
_DISTRIBUTIONS = ("uniform", "normal", "lognormal", "gamma", "beta", "weibull", "gumbel")
_COMPUTE_ACTIONS = ("recompute", "append")
_LOG_LEVELS = ("minimal", "normal", "detailed")


def register_surrogate_tools(mcp: FastMCP) -> None:
    """Register surrogate-model training tools."""

    @mcp.tool()
    def surrogate_train(
        study_name: str = "sup1",
        feature_tag: str = "smt1",
        surrogate_model: str = "dnn",
        sample_points: int = 50,
        distributions: Optional[dict] = None,
        automatic_training: bool = True,
        activation: Optional[Sequence[str]] = None,
        function_names: Optional[Sequence[str]] = None,
        compute_action: str = "recompute",
        training_log_level: str = "normal",
        model_name: Optional[str] = None,
    ) -> dict:
        """
        Configure a Surrogate Model Training study step (COMSOL 6.2+).

        The step performs a DOE-based parametric sweep (Latin hypercube
        sampling) over the study-input parameters of the model, collects the
        quantities of interest, and optionally trains a surrogate model that
        then appears as a function under Global Definitions. Evaluating that
        function replaces the full finite element model.

        Requirements before calling:
        - the input parameters must be global parameters actually used by the
          model (the DOE samples them);
        - the quantities of interest must be observable, e.g. through probes
          so that every sample writes a row of data.

        License note: "dnn" ships with base COMSOL Multiphysics; "gp" and
        "pce" require the Uncertainty Quantification Module.

        Args:
            study_name: Study tag to create or reuse (default: 'sup1')
            feature_tag: Tag of the SurrogateModelTraining step (default: 'smt1')
            surrogate_model: "dnn" (default), "gp", "pce", or "none" for
                data generation only
            sample_points: Number of DOE samples (nsolvenonadp, default 50;
                training quality grows with this and so does runtime)
            distributions: Optional map of input parameter name to sampling
                distribution, e.g. {"L_chip": "uniform", "h_conv": "normal"}
            automatic_training: Train right after the DOE completes (default
                true). Set false to generate data first and train later.
            activation: Optional per-layer activation sequence for the DNN,
                e.g. ["tanh", "relu"]; allowed values are none, relu, elu,
                sigmoid, tanh, softplus, leakyrelu, gelu
            function_names: Optional names for the generated surrogate
                functions, one per quantity of interest
            compute_action: "recompute" to build the surrogate from scratch,
                "append" to improve an existing one with additional data
            training_log_level: "minimal", "normal" (default) or "detailed"
            model_name: Model name (default: current model)

        Returns:
            Tags of the created study/step, the settings actually applied and
            any property that COMSOL rejected.
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}",
            }

        surrogate_model = (surrogate_model or "dnn").lower()
        if surrogate_model not in _SURROGATE_MODELS:
            return {
                "success": False,
                "error": f"Unsupported surrogate_model: {surrogate_model}",
                "supported": list(_SURROGATE_MODELS),
                "license_notes": _SURROGATE_MODEL_REQUIREMENTS,
            }
        if compute_action not in _COMPUTE_ACTIONS:
            return {
                "success": False,
                "error": f"Unsupported compute_action: {compute_action}",
                "supported": list(_COMPUTE_ACTIONS),
            }
        if training_log_level not in _LOG_LEVELS:
            return {
                "success": False,
                "error": f"Unsupported training_log_level: {training_log_level}",
                "supported": list(_LOG_LEVELS),
            }

        warnings = []
        try:
            from jpype import JArray, JInt, JString

            jm = model.java
            studies = {study.tag(): study for study in jm.study()}
            created_study = False
            if study_name in studies:
                study = studies[study_name]
            else:
                study = jm.study().create(study_name)
                created_study = True

            features = {feature.tag(): feature for feature in study.feature()}
            created_feature = False
            if feature_tag in features:
                step = features[feature_tag]
            else:
                step = study.create(feature_tag, _SURROGATE_FEATURE)
                created_feature = True

            # Only set what this kernel actually exposes: 6.2 has no
            # 'automatictraining' (that appeared in 6.4); training is driven by
            # 'surrogatemodel' + 'computeaction' here.
            try:
                supported = {str(name) for name in step.properties()}
            except Exception:
                supported = set()

            applied = {}

            def apply(name, value):
                if supported and name not in supported:
                    warnings.append({"property": name,
                                     "skipped": "not supported by this kernel"})
                    return
                try:
                    step.set(name, value)
                    applied[name] = str(value)
                except Exception as exc:
                    warnings.append({"property": name, "error": str(exc)[:120]})

            apply("surrogatemodel", surrogate_model)
            apply("nsolvenonadp", JInt(int(sample_points)))
            apply("computeaction", compute_action)
            # 6.2 rejects the documented token 'normal' for convinfo, so only
            # send it when the caller deliberately asks for another level.
            if training_log_level != "normal":
                apply("convinfo", training_log_level)
            if not automatic_training:
                warnings.append({"property": "automatictraining",
                                 "note": "6.2 trains as part of the step; "
                                         "re-run with computeaction=append to improve"})

            if activation:
                bad = [a for a in activation if a not in (
                    "none", "relu", "elu", "sigmoid", "tanh",
                    "softplus", "leakyrelu", "gelu")]
                if bad:
                    warnings.append({"property": "activation", "rejected": bad})
                else:
                    step.set("activation", JArray(JString)([str(a) for a in activation]))
                    applied["activation"] = [str(a) for a in activation]

            if distributions:
                flat = []
                for name, dist in distributions.items():
                    dist = str(dist).lower()
                    if dist not in _DISTRIBUTIONS:
                        warnings.append({"property": "distributionselection",
                                         "rejected": f"{name}={dist}",
                                         "allowed": list(_DISTRIBUTIONS)})
                        continue
                    flat.extend([str(name), dist])
                if flat:
                    step.set("distributionselection", JArray(JString)(flat))
                    applied["distributionselection"] = {
                        flat[i]: flat[i + 1] for i in range(0, len(flat), 2)}

            if function_names:
                flat = []
                for index, fname in enumerate(function_names, start=1):
                    flat.extend([str(index), str(fname)])
                if flat:
                    step.set("funcname", JArray(JString)(flat))
                    applied["funcname"] = list(function_names)

            return {
                "success": True,
                "study": study_name,
                "step": feature_tag,
                "created_study": created_study,
                "created_step": created_feature,
                "settings": applied,
                "property_warnings": warnings,
                "license_note": _SURROGATE_MODEL_REQUIREMENTS[surrogate_model],
                "next_steps": [
                    "Send the required input parameters and probe definitions first",
                    "Run the study (prefer study_solve_async: DOE runs many solves)",
                    "Trained surrogate functions then appear under Global Definitions",
                    "Evaluate them with results_evaluate or model_execute_python",
                ],
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to configure surrogate training: {str(e)}",
                "property_warnings": warnings,
            }

    @mcp.tool()
    def surrogate_list(model_name: Optional[str] = None) -> dict:
        """
        List surrogate-model training studies and trained surrogate functions.

        Reports every study step of type SurrogateModelTraining and the
        functions currently defined under Global Definitions, so trained
        surrogates can be identified before evaluating them.

        Args:
            model_name: Model name (default: current model)

        Returns:
            Studies with their surrogate steps and the global function tags
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}",
            }

        try:
            jm = model.java
            studies = []
            for study in jm.study():
                steps = []
                try:
                    for feature in study.feature():
                        try:
                            ftype = str(feature.type())
                        except Exception:
                            ftype = ""
                        if _SURROGATE_FEATURE.lower() in ftype.lower():
                            info = {"tag": feature.tag()}
                            try:
                                info["label"] = feature.label()
                            except Exception:
                                pass
                            steps.append(info)
                except Exception:
                    pass
                if steps:
                    studies.append({"study": study.tag(), "surrogate_steps": steps})

            functions = []
            try:
                for func in jm.func():
                    functions.append({
                        "tag": func.tag(),
                        "label": str(func.label()) if hasattr(func, "label") else "",
                    })
            except Exception:
                pass

            return {
                "success": True,
                "surrogate_studies": studies,
                "global_functions": functions,
                "count": len(studies),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list surrogates: {str(e)}"}
