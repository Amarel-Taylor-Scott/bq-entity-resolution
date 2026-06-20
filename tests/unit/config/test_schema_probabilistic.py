"""Tests for probabilistic matching config models."""

import pytest
from pydantic import ValidationError

from bq_entity_resolution.config.schema import (
    ActiveLearningConfig,
    ComparisonDef,
    ComparisonLevelDef,
    ThresholdConfig,
    TrainingConfig,
)


def test_comparison_level_valid():
    """Valid comparison level creation."""
    lvl = ComparisonLevelDef(label="exact", method="exact", m=0.95, u=0.05)
    assert lvl.label == "exact"
    assert lvl.m == 0.95
    assert lvl.u == 0.05


def test_comparison_level_else():
    """Else level has no method."""
    lvl = ComparisonLevelDef(label="else", m=0.1, u=0.9)
    assert lvl.method is None


def test_comparison_level_no_mu():
    """Levels can omit m/u (filled by training)."""
    lvl = ComparisonLevelDef(label="exact", method="exact")
    assert lvl.m is None
    assert lvl.u is None


def test_comparison_level_invalid_probability():
    """m/u must be in [0, 1]."""
    with pytest.raises(ValidationError):
        ComparisonLevelDef(label="bad", m=1.5, u=0.5)

    with pytest.raises(ValidationError):
        ComparisonLevelDef(label="bad", m=0.5, u=-0.1)


def test_comparison_def_with_levels():
    """ComparisonDef can have levels."""
    comp = ComparisonDef(
        left="name",
        right="name",
        method="exact",
        levels=[
            ComparisonLevelDef(label="exact", method="exact", m=0.9, u=0.1),
            ComparisonLevelDef(label="else", m=0.1, u=0.9),
        ],
    )
    assert len(comp.levels) == 2


def test_comparison_def_without_levels():
    """ComparisonDef without levels (backwards compatible)."""
    comp = ComparisonDef(left="name", right="name", method="exact", weight=3.0)
    assert comp.levels is None
    assert comp.weight == 3.0


def test_threshold_config_with_match_threshold():
    """ThresholdConfig has match_threshold for F-S."""
    tc = ThresholdConfig(method="fellegi_sunter", match_threshold=6.0)
    assert tc.match_threshold == 6.0


def test_threshold_config_sum_default():
    """Default threshold is sum (backwards compatible)."""
    tc = ThresholdConfig()
    assert tc.method == "sum"
    assert tc.match_threshold is None


def test_training_config_none():
    """Default training is none."""
    tc = TrainingConfig()
    assert tc.method == "none"


def test_training_config_labeled():
    """Labeled training config."""
    tc = TrainingConfig(
        method="labeled",
        labeled_pairs_table="proj.ds.labels",
    )
    assert tc.method == "labeled"
    assert tc.labeled_pairs_table == "proj.ds.labels"


def test_training_config_em():
    """EM training config."""
    tc = TrainingConfig(
        method="em",
        em_max_iterations=15,
        em_sample_size=50000,
        em_initial_match_proportion=0.05,
    )
    assert tc.em_max_iterations == 15


def test_active_learning_config_defaults():
    """Active learning defaults to disabled."""
    al = ActiveLearningConfig()
    assert not al.enabled
    assert al.queue_size == 200


def test_active_learning_config_enabled():
    """Active learning can be enabled."""
    al = ActiveLearningConfig(
        enabled=True,
        queue_size=500,
        uncertainty_window=0.2,
        review_queue_table="proj.ds.queue",
    )
    assert al.enabled
    assert al.queue_size == 500
