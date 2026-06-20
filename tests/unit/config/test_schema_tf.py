"""Tests for term frequency adjustment config models."""


from bq_entity_resolution.config.schema import (
    ComparisonDef,
    TermFrequencyConfig,
)


def test_tf_config_defaults():
    """Default TF config is disabled."""
    tf = TermFrequencyConfig()
    assert not tf.enabled
    assert tf.tf_minimum_u_value == 0.001
    assert tf.tf_adjustment_column is None


def test_tf_config_enabled():
    """TF config can be enabled with custom values."""
    tf = TermFrequencyConfig(
        enabled=True,
        tf_minimum_u_value=0.005,
        tf_adjustment_column="name_clean",
    )
    assert tf.enabled
    assert tf.tf_minimum_u_value == 0.005
    assert tf.tf_adjustment_column == "name_clean"


def test_comparison_def_with_tf():
    """ComparisonDef accepts tf_adjustment."""
    comp = ComparisonDef(
        left="first_name_clean",
        right="first_name_clean",
        method="exact",
        weight=3.0,
        tf_adjustment=TermFrequencyConfig(enabled=True),
    )
    assert comp.tf_adjustment is not None
    assert comp.tf_adjustment.enabled


def test_comparison_def_without_tf():
    """ComparisonDef without TF is backwards compatible."""
    comp = ComparisonDef(
        left="name",
        right="name",
        method="exact",
        weight=3.0,
    )
    assert comp.tf_adjustment is None
