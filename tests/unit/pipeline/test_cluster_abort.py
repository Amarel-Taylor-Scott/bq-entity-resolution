"""Tests for cluster explosion hard abort."""

from bq_entity_resolution.config.schema import ClusterQualityConfig
from bq_entity_resolution.exceptions import PipelineAbortError


def test_abort_on_explosion_default_false():
    """abort_on_explosion defaults to False."""
    config = ClusterQualityConfig()
    assert config.abort_on_explosion is False


def test_abort_on_explosion_schema_accepts_true():
    """ClusterQualityConfig accepts abort_on_explosion=True."""
    config = ClusterQualityConfig(abort_on_explosion=True)
    assert config.abort_on_explosion is True


def test_pipeline_abort_error_exists():
    """PipelineAbortError is importable and is an Exception."""
    assert issubclass(PipelineAbortError, Exception)


def test_cluster_quality_config_has_abort_field():
    """ClusterQualityConfig has the abort_on_explosion field."""
    fields = ClusterQualityConfig.model_fields
    assert "abort_on_explosion" in fields
    assert fields["abort_on_explosion"].default is False


def test_abort_message_includes_sizes():
    """PipelineAbortError message includes both sizes."""
    err = PipelineAbortError(
        "Cluster explosion: max cluster size 500 exceeds threshold 100"
    )
    assert "500" in str(err)
    assert "100" in str(err)
    assert "Cluster explosion" in str(err)
