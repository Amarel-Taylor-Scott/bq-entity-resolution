"""Tests for pipeline checkpoint/resume functionality."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureEngineeringConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    ScaleConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)
from bq_entity_resolution.pipeline.context import PipelineContext
from bq_entity_resolution.watermark.checkpoint import CheckpointManager


def _minimal_config(checkpoint_enabled: bool = False) -> PipelineConfig:
    return PipelineConfig(
        project=ProjectConfig(name="test", bq_project="proj"),
        sources=[
            SourceConfig(
                name="src",
                table="proj.ds.tbl",
                unique_key="id",
                updated_at="updated_at",
                columns=[ColumnMapping(name="id"), ColumnMapping(name="name")],
            ),
        ],
        feature_engineering=FeatureEngineeringConfig(
            blocking_keys=[
                BlockingKeyDef(name="bk1", function="farm_fingerprint", inputs=["name"]),
            ],
        ),
        matching_tiers=[
            MatchingTierConfig(
                name="tier1",
                blocking=TierBlockingConfig(paths=[BlockingPathDef(keys=["bk1"])]),
                comparisons=[ComparisonDef(left="name", right="name", method="exact")],
                threshold=ThresholdConfig(min_score=1.0),
            ),
        ],
        scale=ScaleConfig(checkpoint_enabled=checkpoint_enabled),
    )


def _mock_context(config: PipelineConfig, completed: set | None = None) -> PipelineContext:
    ctx = PipelineContext(
        run_id="test_run",
        started_at=datetime.now(UTC),
        config=config,
    )
    if completed:
        ctx.completed_stages = completed
    return ctx


def test_checkpoint_manager_mark_stage_complete():
    """CheckpointManager.mark_stage_complete calls BQ client."""
    client = MagicMock()
    mgr = CheckpointManager(client, "proj.meta.checkpoints")
    mgr.mark_stage_complete("run_1", "staging")
    client.execute.assert_called_once()
    call_sql = client.execute.call_args[0][0]
    assert "INSERT INTO" in call_sql
    assert "staging" in call_sql
    assert "run_1" in call_sql


def test_checkpoint_manager_load_completed_stages():
    """CheckpointManager.load_completed_stages queries BQ for completed stages."""
    client = MagicMock()
    client.execute_and_fetch.return_value = [
        {"stage_name": "staging"},
        {"stage_name": "features"},
    ]
    mgr = CheckpointManager(client, "proj.meta.checkpoints")
    stages = mgr.load_completed_stages("run_1")
    assert stages == {"staging", "features"}


def test_checkpoint_manager_mark_run_complete():
    """CheckpointManager.mark_run_complete inserts __run_complete__ sentinel."""
    client = MagicMock()
    mgr = CheckpointManager(client, "proj.meta.checkpoints")
    mgr.mark_run_complete("run_1")
    call_sql = client.execute.call_args[0][0]
    assert "__run_complete__" in call_sql


def test_checkpoint_manager_find_resumable_run():
    """CheckpointManager.find_resumable_run returns most recent incomplete run."""
    client = MagicMock()
    client.execute_and_fetch.return_value = [{"run_id": "run_42"}]
    mgr = CheckpointManager(client, "proj.meta.checkpoints")
    result = mgr.find_resumable_run()
    assert result == "run_42"


def test_checkpoint_manager_find_resumable_run_none():
    """CheckpointManager.find_resumable_run returns None when no incomplete runs."""
    client = MagicMock()
    client.execute_and_fetch.return_value = []
    mgr = CheckpointManager(client, "proj.meta.checkpoints")
    result = mgr.find_resumable_run()
    assert result is None


def test_context_completed_stages_tracking():
    """completed_stages set on PipelineContext tracks stage completion."""
    config = _minimal_config()
    ctx = _mock_context(config)
    assert len(ctx.completed_stages) == 0
    ctx.completed_stages.add("staging")
    ctx.completed_stages.add("features")
    assert "staging" in ctx.completed_stages
    assert "features" in ctx.completed_stages
    assert "matching" not in ctx.completed_stages


def test_checkpoint_skips_completed_stages():
    """Pre-populated completed_stages can be checked for membership."""
    config = _minimal_config(checkpoint_enabled=True)
    ctx = _mock_context(
        config,
        completed={"init_watermarks", "staging", "features"},
    )
    assert "init_watermarks" in ctx.completed_stages
    assert "staging" in ctx.completed_stages
    assert "features" in ctx.completed_stages
    assert "tiers" not in ctx.completed_stages
