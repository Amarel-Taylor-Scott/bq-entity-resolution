"""Tests for the label ingestion stage."""

from bq_entity_resolution.stages.label_ingestion import LabelIngestionStage


def _make_config_and_tier():
    """Build minimal config and tier for label ingestion tests."""
    class NS:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    project = NS(
        bq_project="test-proj",
        bq_dataset_bronze="bronze",
        bq_dataset_silver="silver",
        bq_dataset_gold="gold",
        bq_location="US",
        udf_dataset="udfs",
        watermark_dataset="meta",
    )

    config = NS(project=project)

    def fq_table(dataset_attr, suffix):
        ds = getattr(project, dataset_attr, "default")
        return f"{project.bq_project}.{ds}.{suffix}"

    config.fq_table = fq_table

    tier = NS(
        name="fuzzy",
        active_learning=NS(
            enabled=True,
            label_feedback=NS(enabled=True, auto_retrain=True),
        ),
    )

    return config, tier


class TestLabelIngestionStage:
    def test_stage_name(self):
        config, tier = _make_config_and_tier()
        stage = LabelIngestionStage(tier, config)
        assert stage.name == "label_ingestion_fuzzy"

    def test_inputs_reference_review_queue(self):
        config, tier = _make_config_and_tier()
        stage = LabelIngestionStage(tier, config)
        inputs = stage.inputs
        assert "review_queue" in inputs
        assert "al_review_queue_fuzzy" in inputs["review_queue"].fq_name

    def test_outputs_reference_labels_table(self):
        config, tier = _make_config_and_tier()
        stage = LabelIngestionStage(tier, config)
        outputs = stage.outputs
        assert "labels" in outputs
        assert "al_labels" in outputs["labels"].fq_name

    def test_plan_generates_sql(self):
        config, tier = _make_config_and_tier()
        stage = LabelIngestionStage(tier, config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "al_labels" in sql
        assert "al_review_queue_fuzzy" in sql
        assert "MERGE" in sql

    def test_plan_sql_contains_label_columns(self):
        config, tier = _make_config_and_tier()
        stage = LabelIngestionStage(tier, config)
        sql = stage.plan()[0].render()
        assert "human_label" in sql
        assert "left_entity_uid" in sql
        assert "right_entity_uid" in sql

    def test_different_tier_names(self):
        config, tier = _make_config_and_tier()
        tier.name = "exact_composite"
        stage = LabelIngestionStage(tier, config)
        assert stage.name == "label_ingestion_exact_composite"
        assert "exact_composite" in stage.inputs["review_queue"].fq_name
