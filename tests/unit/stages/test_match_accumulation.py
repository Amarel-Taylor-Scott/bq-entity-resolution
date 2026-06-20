"""Tests for MatchAccumulationStage.

Validates that the stage produces correct SQL for:
- First tier (CREATE OR REPLACE from tier matches)
- Subsequent tiers (INSERT INTO with dedup)
"""


from bq_entity_resolution.stages.match_accumulation import MatchAccumulationStage

# -- Minimal config fixture --

class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_config_and_tier(tier_name="exact"):
    project = _NS(
        bq_project="test-proj",
        bq_dataset_bronze="test-proj.bronze",
        bq_dataset_silver="test-proj.silver",
        bq_dataset_gold="test-proj.gold",
        bq_location="US",
        udf_dataset="test-proj.udfs",
        watermark_dataset="meta",
    )

    tier = _NS(name=tier_name)

    config = _NS(project=project)
    config.fq_table = lambda attr, name: f"{getattr(project, attr)}.{name}"

    return config, tier


class TestMatchAccumulationStage:
    def test_name_includes_tier(self):
        config, tier = _make_config_and_tier("fuzzy")
        stage = MatchAccumulationStage(tier=tier, tier_index=0, config=config)
        assert stage.name == "accumulate_fuzzy"

    def test_inputs_reference_tier_matches(self):
        config, tier = _make_config_and_tier("exact")
        stage = MatchAccumulationStage(tier=tier, tier_index=0, config=config)
        inputs = stage.inputs
        assert "matches" in inputs
        assert "matches_exact" in inputs["matches"].fq_name

    def test_outputs_reference_all_matches(self):
        config, tier = _make_config_and_tier("exact")
        stage = MatchAccumulationStage(tier=tier, tier_index=0, config=config)
        outputs = stage.outputs
        assert "all_matches" in outputs
        assert "all_matched_pairs" in outputs["all_matches"].fq_name

    def test_first_tier_creates_table(self):
        """First tier (index=0) produces CREATE OR REPLACE TABLE."""
        config, tier = _make_config_and_tier("exact")
        stage = MatchAccumulationStage(tier=tier, tier_index=0, config=config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "CREATE OR REPLACE TABLE" in sql
        assert "all_matched_pairs" in sql
        assert "matches_exact" in sql

    def test_subsequent_tier_inserts(self):
        """Subsequent tiers (index>0) produce INSERT INTO with dedup."""
        config, tier = _make_config_and_tier("fuzzy")
        stage = MatchAccumulationStage(tier=tier, tier_index=1, config=config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "INSERT INTO" in sql
        assert "all_matched_pairs" in sql
        assert "matches_fuzzy" in sql
        # Should have LEFT JOIN for dedup
        assert "LEFT JOIN" in sql
        assert "IS NULL" in sql

    def test_third_tier_also_inserts(self):
        """Third tier (index=2) also inserts."""
        config, tier = _make_config_and_tier("phonetic")
        stage = MatchAccumulationStage(tier=tier, tier_index=2, config=config)
        exprs = stage.plan()
        sql = exprs[0].render()
        assert "INSERT INTO" in sql
        assert "CREATE OR REPLACE" not in sql
