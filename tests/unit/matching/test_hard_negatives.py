"""Tests for hard negative rule expression builder."""

import pytest

from bq_entity_resolution.exceptions import SQLGenerationError
from bq_entity_resolution.matching.hard_negatives import build_hard_negative_expr


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestBuildHardNegativeExpr:
    def test_raw_sql_override(self):
        hn = _NS(
            sql="l.entity_uid != r.entity_uid",
            method="exact",
            left="col",
            right=None,
            action="disqualify",
            penalty=0.0,
        )
        result = build_hard_negative_expr(hn)
        assert result["sql_condition"] == "l.entity_uid != r.entity_uid"
        assert result["action"] == "disqualify"

    def test_method_based_expression(self):
        hn = _NS(
            sql=None,
            method="different",
            left="first_name",
            right="first_name",
            action="disqualify",
            penalty=0.0,
        )
        result = build_hard_negative_expr(hn)
        assert "first_name" in result["sql_condition"]
        assert result["action"] == "disqualify"

    def test_right_defaults_to_left(self):
        hn = _NS(
            sql=None,
            method="exact",
            left="email",
            right=None,
            action="penalize",
            penalty=-2.0,
        )
        result = build_hard_negative_expr(hn)
        assert "email" in result["sql_condition"]
        assert result["penalty"] == -2.0

    def test_unknown_method_raises(self):
        hn = _NS(
            sql=None,
            method="nonexistent_method",
            left="col",
            right=None,
            action="disqualify",
            penalty=0.0,
        )
        with pytest.raises(SQLGenerationError, match="Unknown hard negative method"):
            build_hard_negative_expr(hn)

    def test_penalize_action(self):
        hn = _NS(
            sql=None,
            method="null_either",
            left="phone",
            right="phone",
            action="penalize",
            penalty=-1.5,
        )
        result = build_hard_negative_expr(hn)
        assert result["action"] == "penalize"
        assert result["penalty"] == -1.5
