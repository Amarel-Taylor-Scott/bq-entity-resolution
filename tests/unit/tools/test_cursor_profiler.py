"""Tests for the CursorProfiler tool.

Verifies dataclass creation, recommendation generation,
and profiling with a mock backend.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from bq_entity_resolution.tools.cursor_profiler import (
    CursorProfiler,
    CursorProfileResult,
    HashCursorProfileResult,
)


class TestCursorProfileResult:
    """Tests for the CursorProfileResult dataclass."""

    def test_defaults(self):
        result = CursorProfileResult(column="policy_id")
        assert result.column == "policy_id"
        assert result.distinct_values == 0
        assert result.max_records_per_primary == 0
        assert result.avg_records_per_primary == 0.0
        assert result.std_dev_records == 0.0
        assert result.estimated_batches == 0
        assert result.uniformity_score == 0.0
        assert result.score == 0.0
        assert result.recommendation == ""
        assert result.details == {}

    def test_custom_values(self):
        result = CursorProfileResult(
            column="state",
            distinct_values=50,
            max_records_per_primary=1000000,
            avg_records_per_primary=500000.0,
            std_dev_records=100000.0,
            estimated_batches=10,
            uniformity_score=0.8,
            score=0.75,
            recommendation="Excellent cursor",
            details={"total_records": 5000000},
        )
        assert result.column == "state"
        assert result.distinct_values == 50
        assert result.score == 0.75
        assert result.details["total_records"] == 5000000


class TestHashCursorProfileResult:
    """Tests for the HashCursorProfileResult dataclass."""

    def test_defaults(self):
        result = HashCursorProfileResult()
        assert result.modulus == 1000
        assert result.estimated_batches == 0
        assert result.avg_records_per_bucket == 0.0
        assert result.max_records_per_bucket == 0
        assert result.score == 0.0
        assert result.recommendation == ""

    def test_custom_values(self):
        result = HashCursorProfileResult(
            modulus=500,
            estimated_batches=20,
            avg_records_per_bucket=10000.0,
            max_records_per_bucket=50000,
            score=0.8,
            recommendation="Good hash cursor",
        )
        assert result.modulus == 500
        assert result.estimated_batches == 20
        assert result.score == 0.8


class TestCursorProfilerRecommend:
    """Tests for CursorProfiler.recommend() output."""

    def test_recommend_with_good_natural_column(self):
        """Good natural column (score >= 0.5) generates natural recommendation."""
        profiler = CursorProfiler(backend=MagicMock())

        natural_results = [
            CursorProfileResult(
                column="policy_id",
                distinct_values=10000,
                uniformity_score=0.9,
                score=0.8,
                recommendation="Excellent cursor",
                estimated_batches=5,
            ),
        ]

        text = profiler.recommend(natural_results, batch_size=5_000_000)

        assert "Cursor Strategy Recommendation" in text
        assert "Natural Columns" in text
        assert "policy_id" in text
        assert "RECOMMENDATION" in text
        assert "natural column" in text.lower() or "policy_id" in text

    def test_recommend_with_hash_fallback(self):
        """When no good natural columns, recommends hash cursor."""
        profiler = CursorProfiler(backend=MagicMock())

        natural_results = [
            CursorProfileResult(
                column="status",
                distinct_values=5,
                score=0.2,
                recommendation="Poor cursor",
                estimated_batches=10,
                uniformity_score=0.3,
            ),
        ]

        hash_results = [
            HashCursorProfileResult(
                modulus=1000,
                score=0.8,
                recommendation="Good hash cursor",
                avg_records_per_bucket=5000.0,
                max_records_per_bucket=10000,
                estimated_batches=10,
            ),
        ]

        text = profiler.recommend(
            natural_results, hash_results, batch_size=5_000_000
        )

        assert "Hash Cursors" in text
        assert "RECOMMENDATION" in text
        assert "hash" in text.lower() or "FARM_FINGERPRINT" in text

    def test_recommend_empty_results(self):
        """Empty results generate fallback recommendation."""
        profiler = CursorProfiler(backend=MagicMock())
        text = profiler.recommend([], None, batch_size=5_000_000)

        assert "RECOMMENDATION" in text
        assert "batch_size" in text.lower() or "secondary cursor" in text.lower()

    def test_recommend_batch_size_in_header(self):
        """Batch size appears in the recommendation header."""
        profiler = CursorProfiler(backend=MagicMock())
        text = profiler.recommend([], batch_size=2_000_000)
        assert "2,000,000" in text

    def test_recommend_shows_top_3_natural(self):
        """Shows at most 3 natural column results."""
        profiler = CursorProfiler(backend=MagicMock())

        natural_results = [
            CursorProfileResult(
                column=f"col_{i}",
                score=0.9 - i * 0.1,
                recommendation=f"Col {i}",
                distinct_values=1000 - i * 100,
                uniformity_score=0.8,
                estimated_batches=5,
            )
            for i in range(5)
        ]

        text = profiler.recommend(natural_results, batch_size=5_000_000)

        # Should show col_0, col_1, col_2 but not col_3 or col_4
        assert "col_0" in text
        assert "col_1" in text
        assert "col_2" in text
        assert "col_3" not in text


class TestCursorProfilerProfile:
    """Tests for CursorProfiler.profile() with mock backend."""

    def test_profile_returns_results_sorted_by_score(self):
        """Results are sorted by score (best first)."""
        backend = MagicMock()
        # Return different stats for each column
        backend.execute_and_fetch.side_effect = [
            # First column: low cardinality
            [{
                "total_distinct": 5,
                "total_records": 1000000,
                "max_records_per_primary": 200000,
                "avg_records_per_primary": 100000.0,
                "std_dev_records": 50000.0,
                "avg_distinct_per_primary": 3.0,
            }],
            # Second column: high cardinality
            [{
                "total_distinct": 100000,
                "total_records": 1000000,
                "max_records_per_primary": 10,
                "avg_records_per_primary": 5.0,
                "std_dev_records": 1.0,
                "avg_distinct_per_primary": 50.0,
            }],
        ]

        profiler = CursorProfiler(backend)
        results = profiler.profile(
            table="proj.raw.customers",
            primary_cursor="updated_at",
            candidate_columns=["status", "policy_id"],
            batch_size=5_000_000,
        )

        assert len(results) == 2
        # Higher score should come first
        assert results[0].score >= results[1].score

    def test_profile_handles_query_error(self):
        """Profile gracefully handles query errors for individual columns."""
        backend = MagicMock()
        backend.execute_and_fetch.side_effect = RuntimeError("BQ error")

        profiler = CursorProfiler(backend)
        results = profiler.profile(
            table="proj.raw.customers",
            primary_cursor="updated_at",
            candidate_columns=["bad_col"],
        )

        assert len(results) == 1
        assert "Error" in results[0].recommendation

    def test_profile_empty_candidate_list(self):
        """Empty candidate list returns empty results."""
        backend = MagicMock()
        profiler = CursorProfiler(backend)
        results = profiler.profile(
            table="proj.raw.customers",
            primary_cursor="updated_at",
            candidate_columns=[],
        )
        assert results == []


class TestCursorProfilerHashProfile:
    """Tests for CursorProfiler.profile_hash_cursor() with mock backend."""

    def test_profile_hash_cursor_default_moduli(self):
        """Uses default modulus values [100, 500, 1000] when not specified."""
        backend = MagicMock()
        backend.execute_and_fetch.return_value = [{
            "avg_per_bucket": 5000.0,
            "max_per_bucket": 10000,
            "total_records": 1000000,
        }]

        profiler = CursorProfiler(backend)
        results = profiler.profile_hash_cursor(
            table="proj.raw.customers",
            hash_column="customer_id",
            primary_cursor="updated_at",
        )

        # Should have 3 results for default modulus values
        assert len(results) == 3

    def test_profile_hash_cursor_custom_moduli(self):
        """Custom modulus values are used."""
        backend = MagicMock()
        backend.execute_and_fetch.return_value = [{
            "avg_per_bucket": 5000.0,
            "max_per_bucket": 10000,
            "total_records": 1000000,
        }]

        profiler = CursorProfiler(backend)
        results = profiler.profile_hash_cursor(
            table="proj.raw.customers",
            hash_column="customer_id",
            primary_cursor="updated_at",
            modulus_values=[200, 2000],
        )

        assert len(results) == 2

    def test_profile_hash_cursor_empty_result(self):
        """Empty query result returns default HashCursorProfileResult."""
        backend = MagicMock()
        backend.execute_and_fetch.return_value = []

        profiler = CursorProfiler(backend)
        results = profiler.profile_hash_cursor(
            table="proj.raw.customers",
            hash_column="customer_id",
            primary_cursor="updated_at",
            modulus_values=[1000],
        )

        assert len(results) == 1
        assert results[0].modulus == 1000
        assert results[0].score == 0.0

    def test_profile_hash_cursor_sorted_by_score(self):
        """Results are sorted by score (best first)."""
        backend = MagicMock()
        backend.execute_and_fetch.side_effect = [
            # MOD 100: large buckets
            [{"avg_per_bucket": 50000.0, "max_per_bucket": 200000, "total_records": 5000000}],
            # MOD 1000: smaller buckets
            [{"avg_per_bucket": 5000.0, "max_per_bucket": 20000, "total_records": 5000000}],
        ]

        profiler = CursorProfiler(backend)
        results = profiler.profile_hash_cursor(
            table="proj.raw.customers",
            hash_column="customer_id",
            primary_cursor="updated_at",
            modulus_values=[100, 1000],
            batch_size=5_000_000,
        )

        assert len(results) == 2
        assert results[0].score >= results[1].score
