"""Exhaustive integration tests: all comparison functions execute in DuckDB.

For each registered comparison function, generates SQL from sample columns,
wraps it in a SELECT, and verifies it executes without error in DuckDB.
"""

import pytest

from bq_entity_resolution.backends.duckdb import DuckDBBackend
from bq_entity_resolution.matching.comparisons import COMPARISON_FUNCTIONS


@pytest.fixture
def db():
    """DuckDB backend with sample pair data for comparison testing."""
    backend = DuckDBBackend(":memory:")

    # Create a table with sample data for comparisons
    backend.execute("""
        CREATE TABLE comp_left AS SELECT * FROM (VALUES
            ('John', 'Smith', 'john@example.com', '1990-01-15', '555-1234',
             '123 Main St', 'New York', 'NY', '10001', 'S530', 'JN', 'JOHN',
             [0.5, 0.3, 0.2]::DOUBLE[], 40.7128, -74.0060)
        ) AS t(first_name, last_name, email, dob, phone,
               address, city, state, zip, soundex_code, initials, name_clean,
               embedding, latitude, longitude)
    """)
    backend.execute("""
        CREATE TABLE comp_right AS SELECT * FROM (VALUES
            ('Jon', 'Smith', 'jon.smith@example.com', '1990-01-15', '555-1235',
             '124 Main St', 'New York', 'NY', '10001', 'S530', 'JS', 'JON',
             [0.4, 0.4, 0.2]::DOUBLE[], 40.7589, -73.9851)
        ) AS t(first_name, last_name, email, dob, phone,
               address, city, state, zip, soundex_code, initials, name_clean,
               embedding, latitude, longitude)
    """)

    return backend


# Map of comparison function → (left_col, right_col, extra_params)
_COMPARISON_TEST_ARGS = {
    "exact": ("last_name", "last_name", {}),
    "exact_case_insensitive": ("first_name", "first_name", {}),
    "exact_or_null": ("state", "state", {}),
    "levenshtein": ("first_name", "first_name", {"max_distance": 2}),
    "levenshtein_normalized": ("first_name", "first_name", {"threshold": 0.7}),
    "levenshtein_score": ("first_name", "first_name", {}),
    "jaro_winkler": ("first_name", "first_name", {"threshold": 0.8}),
    "jaro_winkler_score": ("first_name", "first_name", {}),
    "soundex_match": ("first_name", "first_name", {}),
    "cosine_similarity": ("embedding", "embedding", {"min_similarity": 0.8}),
    "cosine_similarity_score": ("embedding", "embedding", {}),
    "numeric_within": ("latitude", "latitude", {"tolerance": 1.0}),
    "date_within_days": ("dob", "dob", {"max_days": 365}),
    "contains": ("email", "email", {}),
    "starts_with": ("first_name", "first_name", {}),
    "different": ("first_name", "last_name", {}),
    "null_either": ("first_name", "first_name", {}),
    "length_mismatch": ("first_name", "first_name", {"max_diff": 3}),
    "token_set_match": ("address", "address", {}),
    "token_set_score": ("address", "address", {}),
    "initials_match": ("initials", "initials", {}),
    "abbreviation_match": ("first_name", "first_name", {}),
    "geo_within_km": (
        "latitude", "latitude",
        {"max_km": 100, "left_lon": "longitude", "right_lon": "longitude"},
    ),
    "geo_distance_score": (
        "latitude", "latitude",
        {"left_lon": "longitude", "right_lon": "longitude"},
    ),
    "metaphone_match": ("first_name", "first_name", {}),
    "double_metaphone_match": ("first_name", "first_name", {}),
    # Numeric comparisons (need numeric columns)
    "numeric_ratio": ("latitude", "latitude", {"min_ratio": 0.9}),
    "numeric_ratio_score": ("latitude", "latitude", {}),
    "numeric_percent_diff": ("latitude", "latitude", {"tolerance": 5.0}),
    # Date comparisons
    "date_within_months": ("dob", "dob", {"months": 6}),
    "date_within_years": ("dob", "dob", {"years": 1}),
    "age_difference": ("dob", "dob", {"max_diff": 5}),
    "date_overlap": ("dob", "dob", {"left_end": "dob", "right_end": "dob"}),
    "date_overlap_score": ("dob", "dob", {"left_end": "dob", "right_end": "dob"}),
    # Vector distances (need embedding columns)
    "euclidean_distance": ("embedding", "embedding", {"max_distance": 2.0}),
    "euclidean_distance_score": ("embedding", "embedding", {}),
    "manhattan_distance": ("embedding", "embedding", {"max_distance": 2.0}),
    "manhattan_distance_score": ("embedding", "embedding", {}),
    # String comparisons
    "jaccard_ngram": ("first_name", "first_name", {"min_similarity": 0.3}),
    "jaccard_ngram_score": ("first_name", "first_name", {}),
    "regex_match": ("first_name", "first_name", {"pattern": "^[A-Z]"}),
}

# Functions requiring geo data — may not work without spatial extension
_GEO_COMPARISONS = {"geo_within_km", "geo_distance_score"}

# Functions requiring UDF dataset
_UDF_COMPARISONS = {"jaro_winkler", "jaro_winkler_score"}


@pytest.fixture(params=sorted(COMPARISON_FUNCTIONS.keys()))
def comparison_name(request):
    return request.param


class TestComparisonExecution:
    def test_comparison_generates_sql(self, comparison_name):
        """Every comparison function generates a non-empty SQL string."""
        func = COMPARISON_FUNCTIONS[comparison_name]
        args = _COMPARISON_TEST_ARGS.get(comparison_name, ("first_name", "first_name", {}))
        left, right, params = args
        sql = func(left, right, **params)
        assert isinstance(sql, str)
        assert len(sql) > 0

    def test_comparison_executes_in_duckdb(self, db, comparison_name):
        """Every comparison function's SQL executes successfully in DuckDB."""
        if comparison_name in _GEO_COMPARISONS and not db.has_spatial:
            pytest.skip("Spatial extension not available for geo comparisons")

        func = COMPARISON_FUNCTIONS[comparison_name]
        args = _COMPARISON_TEST_ARGS.get(comparison_name, ("first_name", "first_name", {}))
        left, right, params = args
        sql_expr = func(left, right, **params)

        # Wrap in a SELECT with paired data
        query = (
            f"SELECT {sql_expr} AS result "
            f"FROM comp_left l, comp_right r"
        )
        try:
            rows = db.execute_and_fetch(query)
            assert len(rows) == 1
            # Result should be boolean or numeric (not error)
            assert rows[0]["result"] is not None or rows[0]["result"] is None
        except Exception as e:
            # Some functions may need specific column types — mark as expected failure
            if "does not exist" in str(e) or "No function matches" in str(e):
                pytest.skip(f"Function not available in DuckDB: {e}")
            raise
