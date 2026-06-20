"""Tests for the BQML classification SQL builder."""

import pytest

from bq_entity_resolution.sql.builders.bqml import (
    BQMLEvaluateParams,
    BQMLModelParams,
    BQMLPredictParams,
    FeatureMatrixParams,
    build_create_model_sql,
    build_evaluate_sql,
    build_feature_importance_sql,
    build_feature_matrix_sql,
    build_model_weights_sql,
    build_predict_sql,
)

# -- Feature matrix export --

class TestBuildFeatureMatrixSql:
    def test_basic_with_comparison_columns(self):
        params = FeatureMatrixParams(
            candidates_table="proj.ds.all_matches",
            featured_table="proj.ds.featured",
            comparison_columns=["name_score", "email_score"],
        )
        expr = build_feature_matrix_sql(params)
        sql = expr.render()

        assert "SELECT" in sql
        assert "left_entity_uid" in sql
        assert "right_entity_uid" in sql
        assert "c.name_score" in sql
        assert "c.email_score" in sql
        assert "is_match" in sql

    def test_basic_with_feature_columns(self):
        params = FeatureMatrixParams(
            candidates_table="proj.ds.all_matches",
            featured_table="proj.ds.featured",
            feature_columns=["first_name_clean", "email_domain"],
        )
        expr = build_feature_matrix_sql(params)
        sql = expr.render()

        assert "lf.first_name_clean AS left_first_name_clean" in sql
        assert "rf.first_name_clean AS right_first_name_clean" in sql
        assert "LEFT JOIN" in sql

    def test_with_output_table(self):
        params = FeatureMatrixParams(
            candidates_table="proj.ds.all_matches",
            featured_table="proj.ds.featured",
            comparison_columns=["score"],
            output_table="proj.ds.feature_matrix",
        )
        expr = build_feature_matrix_sql(params)
        sql = expr.render()

        assert "CREATE OR REPLACE TABLE" in sql
        assert "proj.ds.feature_matrix" in sql

    def test_with_labels_table(self):
        params = FeatureMatrixParams(
            candidates_table="proj.ds.all_matches",
            featured_table="proj.ds.featured",
            comparison_columns=["score"],
            labels_table="proj.ds.labels",
        )
        expr = build_feature_matrix_sql(params)
        sql = expr.render()

        assert "lab.human_label" in sql
        assert "proj.ds.labels" in sql
        assert "LEFT JOIN" in sql

    def test_without_labels_uses_match_confidence(self):
        params = FeatureMatrixParams(
            candidates_table="proj.ds.all_matches",
            featured_table="proj.ds.featured",
            comparison_columns=["score"],
        )
        expr = build_feature_matrix_sql(params)
        sql = expr.render()

        assert "match_confidence" in sql
        assert ">= 0.5" in sql

    def test_with_sample_size(self):
        params = FeatureMatrixParams(
            candidates_table="proj.ds.all_matches",
            featured_table="proj.ds.featured",
            comparison_columns=["score"],
            sample_size=10000,
        )
        expr = build_feature_matrix_sql(params)
        sql = expr.render()

        assert "LIMIT 10000" in sql
        assert "FARM_FINGERPRINT" in sql

    def test_empty_columns_raises_error(self):
        params = FeatureMatrixParams(
            candidates_table="proj.ds.all_matches",
            featured_table="proj.ds.featured",
        )
        with pytest.raises(ValueError, match="at least one"):
            build_feature_matrix_sql(params)


# -- Create model --

class TestBuildCreateModelSql:
    def test_logistic_regression_default(self):
        params = BQMLModelParams(
            training_table="proj.ds.feature_matrix",
            model_name="proj.ds.match_classifier",
        )
        expr = build_create_model_sql(params)
        sql = expr.render()

        assert "CREATE OR REPLACE MODEL" in sql
        assert "proj.ds.match_classifier" in sql
        assert "LOGISTIC_REG" in sql
        assert "is_match" in sql
        assert "max_iterations = 20" in sql
        assert "auto_class_weights = TRUE" in sql

    def test_boosted_tree_model(self):
        params = BQMLModelParams(
            training_table="proj.ds.feature_matrix",
            model_name="proj.ds.model",
            model_type="BOOSTED_TREE_CLASSIFIER",
        )
        expr = build_create_model_sql(params)
        sql = expr.render()

        assert "BOOSTED_TREE_CLASSIFIER" in sql

    def test_custom_iterations(self):
        params = BQMLModelParams(
            training_table="p.d.training",
            model_name="p.d.model",
            max_iterations=50,
        )
        expr = build_create_model_sql(params)
        sql = expr.render()

        assert "max_iterations = 50" in sql

    def test_explicit_feature_columns(self):
        params = BQMLModelParams(
            training_table="p.d.training",
            model_name="p.d.model",
            feature_columns=["name_score", "email_score"],
        )
        expr = build_create_model_sql(params)
        sql = expr.render()

        assert "name_score" in sql
        assert "email_score" in sql

    def test_default_selects_all_except_uids(self):
        params = BQMLModelParams(
            training_table="p.d.training",
            model_name="p.d.model",
        )
        expr = build_create_model_sql(params)
        sql = expr.render()

        assert "* EXCEPT" in sql
        assert "left_entity_uid" in sql

    def test_learn_rate(self):
        params = BQMLModelParams(
            training_table="p.d.training",
            model_name="p.d.model",
            learn_rate=0.01,
        )
        expr = build_create_model_sql(params)
        sql = expr.render()

        assert "learn_rate = 0.01" in sql

    def test_regularization(self):
        params = BQMLModelParams(
            training_table="p.d.training",
            model_name="p.d.model",
            l1_reg=0.001,
            l2_reg=0.01,
        )
        expr = build_create_model_sql(params)
        sql = expr.render()

        assert "l1_reg = 0.001" in sql
        assert "l2_reg = 0.01" in sql

    def test_where_label_not_null(self):
        params = BQMLModelParams(
            training_table="p.d.training",
            model_name="p.d.model",
        )
        expr = build_create_model_sql(params)
        sql = expr.render()

        assert "WHERE is_match IS NOT NULL" in sql


# -- Predict --

class TestBuildPredictSql:
    def test_basic_predict(self):
        params = BQMLPredictParams(
            model_name="proj.ds.model",
            candidates_table="proj.ds.all_matches",
            featured_table="proj.ds.featured",
            output_table="proj.ds.predictions",
        )
        expr = build_predict_sql(params)
        sql = expr.render()

        assert "ML.PREDICT" in sql
        assert "proj.ds.model" in sql
        assert "predicted_is_match" in sql
        assert "rule_based_confidence" in sql
        assert "CREATE OR REPLACE TABLE" in sql

    def test_with_comparison_columns(self):
        params = BQMLPredictParams(
            model_name="p.d.model",
            candidates_table="p.d.candidates",
            featured_table="p.d.featured",
            output_table="p.d.output",
            comparison_columns=["name_score", "email_score"],
        )
        expr = build_predict_sql(params)
        sql = expr.render()

        assert "c.name_score" in sql
        assert "c.email_score" in sql

    def test_with_feature_columns(self):
        params = BQMLPredictParams(
            model_name="p.d.model",
            candidates_table="p.d.candidates",
            featured_table="p.d.featured",
            output_table="p.d.output",
            feature_columns=["first_name_clean"],
        )
        expr = build_predict_sql(params)
        sql = expr.render()

        assert "lf.first_name_clean AS left_first_name_clean" in sql
        assert "rf.first_name_clean AS right_first_name_clean" in sql
        assert "LEFT JOIN" in sql

    def test_without_output_table(self):
        params = BQMLPredictParams(
            model_name="p.d.model",
            candidates_table="p.d.candidates",
            featured_table="p.d.featured",
            output_table="",
        )
        expr = build_predict_sql(params)
        sql = expr.render()

        assert "CREATE OR REPLACE TABLE" not in sql
        assert "ML.PREDICT" in sql


# -- Evaluate --

class TestBuildEvaluateSql:
    def test_basic_evaluate(self):
        params = BQMLEvaluateParams(
            model_name="proj.ds.model",
        )
        expr = build_evaluate_sql(params)
        sql = expr.render()

        assert "ML.EVALUATE" in sql
        assert "proj.ds.model" in sql

    def test_with_evaluation_table(self):
        params = BQMLEvaluateParams(
            model_name="proj.ds.model",
            evaluation_table="proj.ds.eval_data",
        )
        expr = build_evaluate_sql(params)
        sql = expr.render()

        assert "proj.ds.eval_data" in sql

    def test_with_output_table(self):
        params = BQMLEvaluateParams(
            model_name="proj.ds.model",
            output_table="proj.ds.eval_results",
        )
        expr = build_evaluate_sql(params)
        sql = expr.render()

        assert "CREATE OR REPLACE TABLE" in sql
        assert "proj.ds.eval_results" in sql


# -- Feature importance + model weights --

def test_feature_importance_sql():
    sql = build_feature_importance_sql("proj.ds.model").render()
    assert "ML.FEATURE_IMPORTANCE" in sql
    assert "proj.ds.model" in sql


def test_model_weights_sql():
    sql = build_model_weights_sql("proj.ds.model").render()
    assert "ML.WEIGHTS" in sql
    assert "proj.ds.model" in sql
