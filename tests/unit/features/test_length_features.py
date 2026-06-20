"""Tests for length-aware feature functions: length_bucket and length_category."""

from __future__ import annotations

from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS

# ---------------------------------------------------------------------------
# Registry checks
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_length_bucket_registered(self):
        assert "length_bucket" in FEATURE_FUNCTIONS

    def test_length_category_registered(self):
        assert "length_category" in FEATURE_FUNCTIONS


# ---------------------------------------------------------------------------
# length_bucket
# ---------------------------------------------------------------------------

class TestLengthBucket:
    """Tests for the length_bucket feature function."""

    def test_generates_valid_sql(self):
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["customer_name"])
        assert "CHAR_LENGTH" in result
        assert "customer_name" in result

    def test_default_bucket_size_5(self):
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["name"])
        assert "/ 5" in result
        assert "* 5" in result

    def test_custom_bucket_size(self):
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["name"], bucket_size=10)
        assert "/ 10" in result
        assert "* 10" in result

    def test_uses_floor(self):
        """Should use FLOOR for consistent bucketing."""
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["col"])
        assert "FLOOR" in result

    def test_casts_to_int64(self):
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["col"])
        assert "AS INT64" in result

    def test_null_handling(self):
        """NULL inputs should return NULL."""
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["col"])
        assert "IS NOT NULL" in result or "IS NULL" in result
        assert "NULL" in result

    def test_case_when_structure(self):
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["col"])
        assert "CASE WHEN" in result
        assert "ELSE NULL END" in result

    def test_returns_string(self):
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["col"])
        assert isinstance(result, str)

    def test_accepts_kwargs(self):
        """Forward compatibility: extra kwargs are ignored."""
        fn = FEATURE_FUNCTIONS["length_bucket"]
        result = fn(["col"], bucket_size=5, unknown_param="ignored")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# length_category
# ---------------------------------------------------------------------------

class TestLengthCategory:
    """Tests for the length_category feature function."""

    def test_generates_valid_sql(self):
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["customer_name"])
        assert "CHAR_LENGTH" in result
        assert "customer_name" in result

    def test_short_category(self):
        """Short = 1-4 characters, labeled 'S'."""
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["name"])
        assert "'S'" in result

    def test_medium_category(self):
        """Medium = 5-12 characters, labeled 'M'."""
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["name"])
        assert "'M'" in result

    def test_long_category(self):
        """Long = 13+ characters, labeled 'L'."""
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["name"])
        assert "'L'" in result

    def test_boundary_4_chars(self):
        """<= 4 should map to S."""
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["col"])
        assert "<= 4" in result

    def test_boundary_12_chars(self):
        """<= 12 should map to M."""
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["col"])
        assert "<= 12" in result

    def test_null_handling(self):
        """NULL inputs should return NULL."""
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["col"])
        assert "NULL" in result
        assert "WHEN" in result

    def test_case_structure(self):
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["col"])
        assert "CASE" in result
        assert "END" in result

    def test_returns_string(self):
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["col"])
        assert isinstance(result, str)

    def test_null_first_check(self):
        """NULL check should come before length checks."""
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["col"])
        # NULL check should appear before the S/M/L checks
        null_pos = result.find("IS NULL")
        s_pos = result.find("'S'")
        assert null_pos < s_pos

    def test_accepts_kwargs(self):
        """Forward compatibility: extra kwargs are ignored."""
        fn = FEATURE_FUNCTIONS["length_category"]
        result = fn(["col"], unknown_param="ignored")
        assert isinstance(result, str)
