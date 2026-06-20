"""Tests for matching efficiency optimizations."""

from bq_entity_resolution.matching.comparisons import (
    COMPARISON_COSTS,
    COMPARISON_FUNCTIONS,
)

# ---------------------------------------------------------------------------
# Change 1: entity_uid INT64 (no STRING cast)
# ---------------------------------------------------------------------------


def test_staging_builder_no_string_cast():
    """Staging SQL builder produces FARM_FINGERPRINT without AS STRING."""
    from bq_entity_resolution.sql.builders.staging import StagingParams, build_staging_sql

    params = StagingParams(
        target_table="proj.ds.staged_src",
        source_table="proj.ds.raw_src",
        source_name="src",
        unique_key="id",
        updated_at="_source_updated_at",
        columns=["name"],
    )
    sql = build_staging_sql(params).render()
    assert "FARM_FINGERPRINT" in sql
    assert "AS STRING) AS entity_uid" not in sql
    assert "AS entity_uid" in sql


def test_blocking_builder_raises_on_empty_paths():
    """Blocking builder raises ValueError when no blocking paths are defined."""
    import pytest

    from bq_entity_resolution.sql.builders.blocking import (
        BlockingParams,
        build_blocking_sql,
    )

    params = BlockingParams(
        target_table="proj.ds.candidates",
        source_table="proj.ds.featured",
        blocking_paths=[],
        tier_name="tier1",
    )
    with pytest.raises(ValueError, match="No blocking paths defined for tier 'tier1'"):
        build_blocking_sql(params)


# ---------------------------------------------------------------------------
# Change 2: Comparison cost metadata + ordering
# ---------------------------------------------------------------------------


def test_comparison_costs_covers_all_functions():
    """COMPARISON_COSTS has an entry for every registered comparison function."""
    missing = set(COMPARISON_FUNCTIONS.keys()) - set(COMPARISON_COSTS.keys())
    assert not missing, f"Missing cost entries: {missing}"


def test_comparison_costs_order():
    """Cheap comparisons have lower cost than expensive ones."""
    assert COMPARISON_COSTS["exact"] < COMPARISON_COSTS["levenshtein"]
    assert COMPARISON_COSTS["levenshtein"] < COMPARISON_COSTS["jaro_winkler"]
    assert COMPARISON_COSTS["jaro_winkler"] < COMPARISON_COSTS["token_set_match"]
    assert COMPARISON_COSTS["token_set_match"] < COMPARISON_COSTS["cosine_similarity"]


# ---------------------------------------------------------------------------
# Change 4: Token set optimization
# ---------------------------------------------------------------------------


def test_token_set_match_no_union_distinct():
    """token_set_match uses inclusion-exclusion, not UNION DISTINCT."""
    result = COMPARISON_FUNCTIONS["token_set_match"]("name_a", "name_b")
    assert "UNION DISTINCT" not in result
    assert "ARRAY_LENGTH" in result
    assert "COUNTIF" in result


def test_token_set_score_no_union_distinct():
    """token_set_score uses inclusion-exclusion, not UNION DISTINCT."""
    result = COMPARISON_FUNCTIONS["token_set_score"]("name_a", "name_b")
    assert "UNION DISTINCT" not in result
    assert "ARRAY_LENGTH" in result
    assert "COUNTIF" in result


# ---------------------------------------------------------------------------
# Change 5: Registry cleanup
# ---------------------------------------------------------------------------


def test_last_word_uses_array_reverse():
    """last_word feature uses ARRAY_REVERSE instead of double SPLIT."""
    from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS

    result = FEATURE_FUNCTIONS["last_word"](["col"])
    assert "ARRAY_REVERSE" in result
    # Should NOT have double SPLIT pattern
    assert result.count("SPLIT") == 1


def test_farm_fingerprint_no_redundant_cast():
    """farm_fingerprint feature has no redundant CAST wrapper."""
    from bq_entity_resolution.features.registry import FEATURE_FUNCTIONS

    result = FEATURE_FUNCTIONS["farm_fingerprint"](["col"])
    assert "CAST" not in result
    assert "FARM_FINGERPRINT(col)" == result
