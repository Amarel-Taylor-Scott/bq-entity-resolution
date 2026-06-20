"""Tests for standard blocking helpers."""

from bq_entity_resolution.blocking.standard import (
    estimate_selectivity,
    validate_blocking_path,
)


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestValidateBlockingPath:
    def test_empty_keys_warning(self):
        path = _NS(keys=[], lsh_keys=[], candidate_limit=100)
        warnings = validate_blocking_path(path)
        assert any("no keys" in w for w in warnings)

    def test_high_candidate_limit_warning(self):
        path = _NS(keys=["bk_soundex"], lsh_keys=[], candidate_limit=50000)
        warnings = validate_blocking_path(path)
        assert any("very high" in w for w in warnings)

    def test_zero_candidate_limit_warning(self):
        path = _NS(keys=["bk_zip"], lsh_keys=[], candidate_limit=0)
        warnings = validate_blocking_path(path)
        assert any("0 or negative" in w for w in warnings)

    def test_valid_path_has_warnings_for_limit(self):
        """Valid keys + reasonable limit still warns about limit 0."""
        path = _NS(keys=["bk_name"], lsh_keys=[], candidate_limit=-1)
        warnings = validate_blocking_path(path)
        assert any("0 or negative" in w for w in warnings)


class TestEstimateSelectivity:
    def test_high_cardinality(self):
        bk = _NS(name="bk_email")
        selectivity = estimate_selectivity(bk, 100000)
        assert selectivity == 1.0 / 100000

    def test_low_cardinality(self):
        bk = _NS(name="bk_state")
        selectivity = estimate_selectivity(bk, 50)
        assert selectivity == 1.0 / 50

    def test_zero_cardinality(self):
        bk = _NS(name="bk_empty")
        selectivity = estimate_selectivity(bk, 0)
        assert selectivity == 1.0

    def test_negative_cardinality(self):
        bk = _NS(name="bk_err")
        selectivity = estimate_selectivity(bk, -5)
        assert selectivity == 1.0
