"""Tests for symbolic face selection in a workflow spec.

`where.face` / `faces` / `normal` / `outer` let a spec name a boundary by the
geometry's axis extremes instead of hand-writing a bounding box - the change
that removes the most common "the boundary condition landed on nothing" error.
"""

import pytest

from src.tools.workflow import FACE_KEYS, JavaWorkflowExecutor, SpecValidator


def _spec(where):
    return {
        "model": {"name": "t", "dimension": 3},
        "geometry": [{"type": "block", "tag": "blk1",
                      "position": [0, 0, 0], "size": [0.1, 0.1, 0.1]}],
        "physics": [{"type": "ht", "boundary_conditions": [
            {"tag": "hot", "type": "Temperature", "where": where,
             "properties": {"T0": "373.15[K]"}},
        ]}],
        "mesh": {"tag": "mesh1", "size": 4, "run": True},
        "study": {"tag": "std1", "type": "Stationary"},
    }


class TestValidatorAcceptsSymbolicFaces:
    def test_single_face(self):
        result = SpecValidator(_spec({"face": "zmin"})).validate()
        assert result["errors"] == [], result["errors"]

    def test_faces_normal_and_outer(self):
        for where in ({"faces": ["zmin", "zmax"]}, {"normal": "+z"}, {"outer": True}):
            result = SpecValidator(_spec(where)).validate()
            assert result["errors"] == [], (where, result["errors"])

    def test_box_and_boundaries_still_accepted(self):
        box = {"xmin": 0, "xmax": 0.1, "ymin": 0, "ymax": 0.1, "zmin": -1e-6, "zmax": 1e-6}
        assert SpecValidator(_spec({"box": box})).validate()["errors"] == []
        assert SpecValidator(_spec({"boundaries": [1, 2]})).validate()["errors"] == []


class TestValidatorRejectsMistakes:
    def test_unknown_face_name(self):
        result = SpecValidator(_spec({"face": "bottom"})).validate()
        assert any("must be one of" in error for error in result["errors"]), result["errors"]

    def test_bad_normal(self):
        result = SpecValidator(_spec({"normal": "up"})).validate()
        assert any("normal" in error for error in result["errors"]), result["errors"]

    def test_empty_where_names_the_options(self):
        result = SpecValidator(_spec({})).validate()
        assert any("must name a location" in error for error in result["errors"]), result["errors"]


class TestFaceKeyResolution:
    def _executor(self):
        # _face_keys touches no COMSOL state, so skip __init__.
        return JavaWorkflowExecutor.__new__(JavaWorkflowExecutor)

    def test_single_face(self):
        assert self._executor()._face_keys({"face": "zmin"}) == ["zmin"]

    def test_normal_maps_to_face(self):
        executor = self._executor()
        assert executor._face_keys({"normal": "+z"}) == ["zmax"]
        assert executor._face_keys({"normal": "-x"}) == ["xmin"]
        assert executor._face_keys({"normal": " +Z "}) == ["zmax"]

    def test_faces_deduplicate_preserving_order(self):
        assert self._executor()._face_keys({"faces": ["zmax", "zmin", "zmax"]}) == ["zmax", "zmin"]

    def test_outer_is_every_extreme(self):
        assert self._executor()._face_keys({"outer": True}) == list(FACE_KEYS)

    def test_unknown_face_raises(self):
        with pytest.raises(ValueError):
            self._executor()._face_keys({"face": "middle"})

    def test_no_selector_returns_empty(self):
        assert self._executor()._face_keys({}) == []
