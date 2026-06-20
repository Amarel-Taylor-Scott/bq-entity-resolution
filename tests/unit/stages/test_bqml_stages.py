"""Tests for BQML classification pipeline stages."""

from bq_entity_resolution.stages.bqml_classification import (
    BQMLEvaluateStage,
    BQMLPredictStage,
    BQMLTrainingStage,
    FeatureMatrixExportStage,
)

# -- Minimal config fixture --

def _make_minimal_config():
    """Create a minimal PipelineConfig-like object for BQML stages."""
    class NS:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    project = NS(
        bq_project="test-proj",
        bq_dataset_bronze="test-proj.bronze",
        bq_dataset_silver="test-proj.silver",
        bq_dataset_gold="test-proj.gold",
        bq_location="US",
        name="customer_dedup",
    )

    source = NS(
        name="crm",
        table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        columns=[],
        passthrough_columns=[],
        joins=[],
        filter=None,
        partition_column=None,
        batch_size=None,
    )

    config = NS(
        project=project,
        sources=[source],
        name="customer_dedup",
    )

    def fq_table(dataset_attr, table_name):
        ds = getattr(project, dataset_attr, "test-proj.default")
        return f"{ds}.{table_name}"

    config.fq_table = fq_table

    return config


# -- FeatureMatrixExportStage --

class TestFeatureMatrixExportStage:
    def test_stage_name(self):
        config = _make_minimal_config()
        stage = FeatureMatrixExportStage(
            config, comparison_columns=["name_score"],
        )
        assert stage.name == "feature_matrix_export"

    def test_inputs_include_all_matches_and_featured(self):
        config = _make_minimal_config()
        stage = FeatureMatrixExportStage(
            config, comparison_columns=["score"],
        )
        inputs = stage.inputs
        assert "all_matches" in inputs
        assert "featured" in inputs

    def test_outputs_include_feature_matrix(self):
        config = _make_minimal_config()
        stage = FeatureMatrixExportStage(
            config, comparison_columns=["score"],
        )
        outputs = stage.outputs
        assert "feature_matrix" in outputs
        assert "feature_matrix" in outputs["feature_matrix"].fq_name

    def test_plan_generates_sql(self):
        config = _make_minimal_config()
        stage = FeatureMatrixExportStage(
            config,
            comparison_columns=["name_score", "email_score"],
        )
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "SELECT" in sql
        assert "name_score" in sql


# -- BQMLTrainingStage --

class TestBQMLTrainingStage:
    def test_stage_name(self):
        config = _make_minimal_config()
        stage = BQMLTrainingStage(config)
        assert stage.name == "bqml_training"

    def test_inputs_include_feature_matrix(self):
        config = _make_minimal_config()
        stage = BQMLTrainingStage(config)
        inputs = stage.inputs
        assert "feature_matrix" in inputs

    def test_outputs_include_model(self):
        config = _make_minimal_config()
        stage = BQMLTrainingStage(config)
        outputs = stage.outputs
        assert "model" in outputs
        assert "match_classifier" in outputs["model"].fq_name

    def test_plan_generates_create_model_sql(self):
        config = _make_minimal_config()
        stage = BQMLTrainingStage(config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "CREATE OR REPLACE MODEL" in sql
        assert "LOGISTIC_REG" in sql

    def test_custom_model_type(self):
        config = _make_minimal_config()
        stage = BQMLTrainingStage(config, model_type="BOOSTED_TREE_CLASSIFIER")
        exprs = stage.plan()
        sql = exprs[0].render()
        assert "BOOSTED_TREE_CLASSIFIER" in sql


# -- BQMLPredictStage --

class TestBQMLPredictStage:
    def test_stage_name(self):
        config = _make_minimal_config()
        stage = BQMLPredictStage(config)
        assert stage.name == "bqml_predict"

    def test_inputs_include_matches_featured_model(self):
        config = _make_minimal_config()
        stage = BQMLPredictStage(config)
        inputs = stage.inputs
        assert "all_matches" in inputs
        assert "featured" in inputs
        assert "model" in inputs

    def test_outputs_include_predictions(self):
        config = _make_minimal_config()
        stage = BQMLPredictStage(config)
        outputs = stage.outputs
        assert "predictions" in outputs
        assert "ml_predictions" in outputs["predictions"].fq_name

    def test_plan_generates_predict_sql(self):
        config = _make_minimal_config()
        stage = BQMLPredictStage(config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "ML.PREDICT" in sql


# -- BQMLEvaluateStage --

class TestBQMLEvaluateStage:
    def test_stage_name(self):
        config = _make_minimal_config()
        stage = BQMLEvaluateStage(config)
        assert stage.name == "bqml_evaluate"

    def test_inputs_include_model(self):
        config = _make_minimal_config()
        stage = BQMLEvaluateStage(config)
        inputs = stage.inputs
        assert "model" in inputs

    def test_outputs_include_evaluation(self):
        config = _make_minimal_config()
        stage = BQMLEvaluateStage(config)
        outputs = stage.outputs
        assert "evaluation" in outputs
        assert "model_evaluation" in outputs["evaluation"].fq_name

    def test_plan_generates_evaluate_sql(self):
        config = _make_minimal_config()
        stage = BQMLEvaluateStage(config)
        exprs = stage.plan()
        assert len(exprs) == 1
        sql = exprs[0].render()
        assert "ML.EVALUATE" in sql
