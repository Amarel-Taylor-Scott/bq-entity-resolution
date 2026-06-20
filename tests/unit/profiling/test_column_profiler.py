"""Tests for the column profiler module."""

from __future__ import annotations

import math

import pytest

from bq_entity_resolution.profiling.column_profiler import ColumnProfile, ColumnProfiler

# ---------------------------------------------------------------------------
# ColumnProfile property tests
# ---------------------------------------------------------------------------


class TestColumnProfile:
    """Tests for ColumnProfile computed properties."""

    def test_suggested_u_high_cardinality(self):
        """SSN-like column: u ≈ 1/1_000_000."""
        p = ColumnProfile("ssn", cardinality=1_000_000, total_rows=2_000_000)
        assert p.suggested_u == pytest.approx(1e-6, rel=0.01)

    def test_suggested_u_low_cardinality(self):
        """State column: u ≈ 1/50 = 0.02."""
        p = ColumnProfile("state", cardinality=50, total_rows=1_000_000)
        assert p.suggested_u == pytest.approx(0.02, rel=0.01)

    def test_suggested_u_zero_cardinality(self):
        """All-null column returns 1.0 (no discriminative power)."""
        p = ColumnProfile("empty", cardinality=0, total_rows=100)
        assert p.suggested_u == 1.0

    def test_suggested_m_no_nulls(self):
        """Fully populated column: m ≈ 1.0."""
        p = ColumnProfile("name", total_rows=1000, null_rate=0.0)
        assert p.suggested_m == pytest.approx(0.999, rel=0.01)

    def test_suggested_m_high_null_rate(self):
        """50% null column: m ≈ 0.5."""
        p = ColumnProfile("phone", total_rows=1000, null_rate=0.5)
        assert p.suggested_m == pytest.approx(0.5, rel=0.01)

    def test_suggested_weight_ssn_like(self):
        """High-cardinality, low-null column should have high weight."""
        p = ColumnProfile("ssn", cardinality=1_000_000, total_rows=2_000_000, null_rate=0.01)
        # weight = log2(0.99 / 0.000001) ≈ 19.9 bits
        assert p.suggested_weight > 15

    def test_suggested_weight_state_like(self):
        """Low-cardinality column should have low weight."""
        p = ColumnProfile("state", cardinality=50, total_rows=1_000_000, null_rate=0.0)
        # weight = log2(0.999 / 0.02) ≈ 5.6 bits
        assert 4 < p.suggested_weight < 7

    def test_discriminative_power_high(self):
        p = ColumnProfile("ssn", cardinality=1_000_000, total_rows=2_000_000, null_rate=0.01)
        assert p.discriminative_power == "HIGH"

    def test_discriminative_power_medium(self):
        # Cardinality 500 → u=0.002, m≈0.95 → weight=log2(475)≈8.9 bits
        p = ColumnProfile("city", cardinality=500, total_rows=1_000_000, null_rate=0.05)
        assert p.discriminative_power == "MEDIUM"

    def test_discriminative_power_low(self):
        p = ColumnProfile("gender", cardinality=3, total_rows=1_000_000, null_rate=0.0)
        assert p.discriminative_power == "LOW"

    def test_weight_is_information_content(self):
        """Weight equals log2(m/u) — the information content formula."""
        p = ColumnProfile("col", cardinality=1000, total_rows=10000, null_rate=0.1)
        expected = round(math.log2(p.suggested_m / p.suggested_u), 2)
        assert p.suggested_weight == expected


# ---------------------------------------------------------------------------
# ColumnProfiler SQL generation tests
# ---------------------------------------------------------------------------


class TestColumnProfiler:
    """Tests for ColumnProfiler SQL generation and parsing."""

    def setup_method(self):
        self.profiler = ColumnProfiler()

    def test_generate_profile_sql_single_column(self):
        sql = self.profiler.generate_profile_sql("proj.ds.table", ["first_name"])
        assert "COUNT(DISTINCT first_name)" in sql
        assert "COUNTIF(first_name IS NULL)" in sql
        assert "`proj.ds.table`" in sql
        assert "UNION ALL" not in sql  # Single column, no UNION

    def test_generate_profile_sql_multiple_columns(self):
        sql = self.profiler.generate_profile_sql(
            "proj.ds.table", ["first_name", "last_name", "email"]
        )
        assert sql.count("UNION ALL") == 2  # 3 columns = 2 UNION ALLs
        assert "'first_name' AS column_name" in sql
        assert "'last_name' AS column_name" in sql
        assert "'email' AS column_name" in sql

    def test_generate_top_values_sql(self):
        sql = self.profiler.generate_top_values_sql("proj.ds.table", "city", top_k=5)
        assert "GROUP BY city" in sql
        assert "LIMIT 5" in sql
        assert "ORDER BY freq DESC" in sql

    def test_parse_profile_results(self):
        rows = [
            {
                "column_name": "email",
                "cardinality": 500_000,
                "total_rows": 1_000_000,
                "null_count": 100_000,
                "avg_frequency": 2.0,
                "max_frequency": 50,
            },
            {
                "column_name": "state",
                "cardinality": 50,
                "total_rows": 1_000_000,
                "null_count": 5_000,
                "avg_frequency": 20_000.0,
                "max_frequency": 200_000,
            },
        ]
        profiles = self.profiler.parse_profile_results(rows)
        assert len(profiles) == 2
        assert profiles[0].column_name == "email"
        assert profiles[0].cardinality == 500_000
        assert profiles[0].null_rate == pytest.approx(0.1)
        assert profiles[1].column_name == "state"
        assert profiles[1].null_rate == pytest.approx(0.005)

    def test_parse_profile_results_handles_none(self):
        """Gracefully handles None values from BQ."""
        rows = [
            {
                "column_name": "sparse_col",
                "cardinality": None,
                "total_rows": None,
                "null_count": None,
                "avg_frequency": None,
                "max_frequency": None,
            }
        ]
        profiles = self.profiler.parse_profile_results(rows)
        assert profiles[0].cardinality == 0
        assert profiles[0].total_rows == 0
        assert profiles[0].null_rate == 0.0

    def test_suggest_weights(self):
        profiles = [
            ColumnProfile("ssn", cardinality=1_000_000, total_rows=2_000_000, null_rate=0.01),
            ColumnProfile("state", cardinality=50, total_rows=1_000_000, null_rate=0.0),
        ]
        weights = self.profiler.suggest_weights(profiles)
        assert "ssn" in weights
        assert "state" in weights
        assert weights["ssn"] > weights["state"]  # SSN more discriminative

    def test_suggest_comparisons_high_cardinality(self):
        profiles = [
            ColumnProfile("email", cardinality=500_000, total_rows=1_000_000, null_rate=0.1),
        ]
        suggestions = self.profiler.suggest_comparisons(profiles)
        assert len(suggestions) == 1
        assert suggestions[0]["method"] == "exact"  # High cardinality → exact
        assert suggestions[0]["discriminative_power"] in ("HIGH", "MEDIUM")

    def test_suggest_comparisons_medium_cardinality(self):
        profiles = [
            ColumnProfile("last_name", cardinality=5_000, total_rows=1_000_000, null_rate=0.02),
        ]
        suggestions = self.profiler.suggest_comparisons(profiles)
        assert suggestions[0]["method"] == "jaro_winkler"  # Medium → fuzzy

    def test_suggest_comparisons_low_cardinality(self):
        profiles = [
            ColumnProfile("state", cardinality=50, total_rows=1_000_000, null_rate=0.0),
        ]
        suggestions = self.profiler.suggest_comparisons(profiles)
        assert suggestions[0]["method"] == "exact"
        assert suggestions[0]["discriminative_power"] == "MEDIUM"

    def test_suggest_comparisons_warns_high_null_rate(self):
        profiles = [
            ColumnProfile("phone", cardinality=100_000, total_rows=1_000_000, null_rate=0.5),
        ]
        suggestions = self.profiler.suggest_comparisons(profiles)
        assert "warning" in suggestions[0]
        assert "null" in suggestions[0]["warning"].lower()

    def test_suggest_comparisons_skips_zero_cardinality(self):
        profiles = [
            ColumnProfile("empty", cardinality=0, total_rows=1_000_000, null_rate=1.0),
        ]
        suggestions = self.profiler.suggest_comparisons(profiles)
        assert len(suggestions) == 0

    def test_format_report(self):
        profiles = [
            ColumnProfile(
                "email", cardinality=500_000, total_rows=1_000_000,
                null_count=100_000, null_rate=0.1, avg_frequency=2.0, max_frequency=50,
            ),
        ]
        report = self.profiler.format_report(profiles)
        assert "email:" in report
        assert "500,000" in report
        assert "10.0%" in report
        assert "bits" in report
        assert "HIGH" in report or "MEDIUM" in report


# ---------------------------------------------------------------------------
# Weight ordering: verify that profiler-suggested weights maintain
# the intuitive ordering SSN > email > name > state > gender
# ---------------------------------------------------------------------------


class TestWeightOrdering:
    """Verify that information-content weights produce intuitive orderings."""

    @pytest.fixture()
    def typical_profiles(self) -> list[ColumnProfile]:
        rows = 15_000_000
        return [
            ColumnProfile("ssn", cardinality=10_000_000, total_rows=rows, null_rate=0.02),
            ColumnProfile("email", cardinality=5_000_000, total_rows=rows, null_rate=0.1),
            ColumnProfile("full_name", cardinality=1_000_000, total_rows=rows, null_rate=0.01),
            ColumnProfile("date_of_birth", cardinality=30_000, total_rows=rows, null_rate=0.05),
            ColumnProfile("city", cardinality=5_000, total_rows=rows, null_rate=0.03),
            ColumnProfile("state", cardinality=50, total_rows=rows, null_rate=0.01),
            ColumnProfile("gender", cardinality=3, total_rows=rows, null_rate=0.0),
        ]

    def test_ssn_most_discriminative(self, typical_profiles):
        weights = ColumnProfiler().suggest_weights(typical_profiles)
        assert weights["ssn"] > weights["email"]
        assert weights["ssn"] > weights["full_name"]

    def test_email_more_than_name(self, typical_profiles):
        weights = ColumnProfiler().suggest_weights(typical_profiles)
        assert weights["email"] > weights["full_name"]

    def test_name_more_than_city(self, typical_profiles):
        weights = ColumnProfiler().suggest_weights(typical_profiles)
        assert weights["full_name"] > weights["city"]

    def test_city_more_than_state(self, typical_profiles):
        weights = ColumnProfiler().suggest_weights(typical_profiles)
        assert weights["city"] > weights["state"]

    def test_state_more_than_gender(self, typical_profiles):
        weights = ColumnProfiler().suggest_weights(typical_profiles)
        assert weights["state"] > weights["gender"]
