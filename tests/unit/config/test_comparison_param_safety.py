"""Comparison params are screened for SQL injection (they reach generated SQL)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bq_entity_resolution.config.models.matching import ComparisonDef


def _cmp(params):
    return ComparisonDef(left="a", right="b", method="exact", params=params)


class TestLegitParamsPass:
    @pytest.mark.parametrize("params", [
        {"threshold": 0.75},
        {"n": 2, "metric": "jaccard"},
        {"udf_dataset": "er_udfs"},
        {"weights": [0.1, 0.2, 0.3]},
        {},
    ])
    def test_safe(self, params):
        assert _cmp(params).params == params


class TestInjectionRejected:
    @pytest.mark.parametrize("params", [
        {"x": "'; DROP TABLE users; --"},
        {"y": "a UNION SELECT secret FROM vault"},
        {"z": ["ok", "b/*comment*/"]},          # nested in a list
        {"nested": {"k": "1; DELETE FROM t"}},   # nested in a dict
    ])
    def test_unsafe(self, params):
        with pytest.raises(ValidationError):
            _cmp(params)
