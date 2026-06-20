"""Tests for soft signal expression builder."""

import pytest

from bq_entity_resolution.exceptions import SQLGenerationError
from bq_entity_resolution.matching.soft_signals import build_soft_signal_expr


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestBuildSoftSignalExpr:
    def test_raw_sql_override(self):
        ss = _NS(
            sql="l.city = r.city",
            method="exact",
            left="city",
            right=None,
            bonus=0.5,
        )
        result = build_soft_signal_expr(ss)
        assert result["sql_condition"] == "l.city = r.city"
        assert result["bonus"] == 0.5

    def test_method_based_expression(self):
        ss = _NS(
            sql=None,
            method="exact",
            left="email_domain",
            right="email_domain",
            bonus=0.3,
        )
        result = build_soft_signal_expr(ss)
        assert "email_domain" in result["sql_condition"]
        assert result["bonus"] == 0.3

    def test_right_defaults_to_left(self):
        ss = _NS(
            sql=None,
            method="exact",
            left="phone_area_code",
            right=None,
            bonus=0.2,
        )
        result = build_soft_signal_expr(ss)
        assert "phone_area_code" in result["sql_condition"]

    def test_unknown_method_raises(self):
        ss = _NS(
            sql=None,
            method="no_such_method",
            left="col",
            right=None,
            bonus=0.1,
        )
        with pytest.raises(SQLGenerationError, match="Unknown soft signal method"):
            build_soft_signal_expr(ss)

    def test_negative_bonus(self):
        ss = _NS(
            sql=None,
            method="different",
            left="state",
            right="state",
            bonus=-0.5,
        )
        result = build_soft_signal_expr(ss)
        assert result["bonus"] == -0.5
