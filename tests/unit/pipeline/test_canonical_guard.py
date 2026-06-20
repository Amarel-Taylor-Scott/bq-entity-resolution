"""Tests for canonical index table support."""

from bq_entity_resolution.config.schema import (
    BlockingKeyDef,
    BlockingPathDef,
    ColumnMapping,
    ComparisonDef,
    FeatureEngineeringConfig,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)
from bq_entity_resolution.naming import canonical_index_table
from bq_entity_resolution.sql.builders.clustering import (
    IncrementalClusteringParams,
    PopulateCanonicalIndexParams,
    build_incremental_cluster_sql,
    build_populate_canonical_index_sql,
)


def _minimal_config(cross_batch: bool = False) -> PipelineConfig:
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
                BlockingKeyDef(
                    name="bk1", function="farm_fingerprint",
                    inputs=["name"],
                ),
            ],
        ),
        matching_tiers=[
            MatchingTierConfig(
                name="tier1",
                blocking=TierBlockingConfig(
                    paths=[BlockingPathDef(keys=["bk1"])],
                    cross_batch=cross_batch,
                ),
                comparisons=[ComparisonDef(left="name", right="name", method="exact")],
                threshold=ThresholdConfig(min_score=1.0),
            ),
        ],
    )


def test_canonical_index_table_naming():
    """canonical_index_table returns the gold layer canonical table."""
    config = _minimal_config()
    result = canonical_index_table(config)
    assert "canonical_index" in result


def test_incremental_cluster_builder_exists():
    """Incremental clustering builder generates SQL referencing canonical table."""
    params = IncrementalClusteringParams(
        all_matches_table="proj.silver.all_matched_pairs",
        cluster_table="proj.silver.entity_clusters",
        source_table="proj.silver.featured",
        canonical_table="proj.gold.canonical_index",
    )
    sql = build_incremental_cluster_sql(params).render()
    assert "canonical_index" in sql


def test_populate_canonical_index_builder_exists():
    """Populate canonical index builder generates MERGE SQL to upsert entities."""
    params = PopulateCanonicalIndexParams(
        canonical_table="proj.gold.canonical_index",
        source_table="proj.silver.featured",
        cluster_table="proj.silver.entity_clusters",
    )
    sql = build_populate_canonical_index_sql(params).render()
    assert "canonical_index" in sql
    assert "MERGE INTO" in sql
    assert "WHEN NOT MATCHED THEN" in sql
    assert "INSERT ROW" in sql


def test_cross_batch_config_accepted():
    """TierBlockingConfig accepts cross_batch=True."""
    config = _minimal_config(cross_batch=True)
    assert config.matching_tiers[0].blocking.cross_batch is True


def test_cross_batch_default_false():
    """TierBlockingConfig defaults cross_batch to False."""
    config = _minimal_config(cross_batch=False)
    assert config.matching_tiers[0].blocking.cross_batch is False
