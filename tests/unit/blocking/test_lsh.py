"""Tests for LSH blocking utilities."""


from bq_entity_resolution.blocking.lsh import (
    estimate_collision_probability,
    lsh_blocking_condition,
    lsh_bucket_columns,
)


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestLshBucketColumns:
    def test_returns_correct_count(self):
        config = _NS(bucket_column_prefix="fp_lsh_bucket", num_hash_tables=4)
        cols = lsh_bucket_columns(config)
        assert len(cols) == 4

    def test_column_names(self):
        config = _NS(bucket_column_prefix="fp_lsh_bucket", num_hash_tables=3)
        cols = lsh_bucket_columns(config)
        assert cols == [
            "fp_lsh_bucket_0",
            "fp_lsh_bucket_1",
            "fp_lsh_bucket_2",
        ]

    def test_zero_tables(self):
        config = _NS(bucket_column_prefix="fp_lsh_bucket", num_hash_tables=0)
        cols = lsh_bucket_columns(config)
        assert cols == []


class TestLshBlockingCondition:
    def test_single_band(self):
        config = _NS(bucket_column_prefix="fp_lsh", num_hash_tables=2)
        cond = lsh_blocking_condition(config, "l", "r", min_matching_bands=1)
        assert "l.fp_lsh_0 = r.fp_lsh_0" in cond
        assert "l.fp_lsh_1 = r.fp_lsh_1" in cond
        assert ">= 1" in cond

    def test_multiple_bands(self):
        config = _NS(bucket_column_prefix="fp_lsh", num_hash_tables=3)
        cond = lsh_blocking_condition(config, "a", "b", min_matching_bands=2)
        assert ">= 2" in cond

    def test_empty_config(self):
        config = _NS(bucket_column_prefix="fp_lsh", num_hash_tables=0)
        cond = lsh_blocking_condition(config)
        assert cond == "FALSE"


class TestEstimateCollisionProbability:
    def test_identical_vectors(self):
        """Identical vectors (sim=1.0) have ~100% collision probability."""
        prob = estimate_collision_probability(1.0, num_tables=10, num_functions=5)
        assert prob > 0.99

    def test_orthogonal_vectors(self):
        """Orthogonal vectors (sim=0) have low collision probability."""
        prob = estimate_collision_probability(0.0, num_tables=10, num_functions=5)
        assert prob < 0.5  # Not zero due to random hyperplane hashing

    def test_opposite_vectors(self):
        """Opposite vectors (sim=-1.0) have ~0% collision probability."""
        prob = estimate_collision_probability(-1.0, num_tables=10, num_functions=5)
        assert prob < 0.01

    def test_moderate_similarity(self):
        """Moderate similarity should have moderate probability."""
        prob = estimate_collision_probability(0.7, num_tables=10, num_functions=5)
        assert 0.3 < prob < 1.0

    def test_more_tables_increases_probability(self):
        p_few = estimate_collision_probability(0.5, num_tables=2, num_functions=5)
        p_many = estimate_collision_probability(0.5, num_tables=20, num_functions=5)
        assert p_many > p_few

    def test_returns_valid_range(self):
        for sim in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            prob = estimate_collision_probability(sim, num_tables=5, num_functions=3)
            assert 0.0 <= prob <= 1.0
