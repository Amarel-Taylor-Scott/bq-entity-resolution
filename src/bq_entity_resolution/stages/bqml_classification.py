"""BQML classification stage: supervised match prediction.

Trains a BQML model on labeled pair features, then optionally scores
candidate pairs using ML.PREDICT. Complements Fellegi-Sunter by
learning optimal feature weights from labeled data.

Usage in pipeline:
    1. Run standard pipeline to generate candidates + comparison scores
    2. Collect labels via active learning
    3. Add BQMLClassificationStage to train on labeled pairs
    4. Compare ML predictions vs rule-based scores

This stage is OPTIONAL — it enhances the pipeline but doesn't replace
the core blocking → matching → clustering flow.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.naming import (
    all_matches_table,
    featured_table,
)
from bq_entity_resolution.sql.builders.bqml import (
    BQMLEvaluateParams,
    BQMLModelParams,
    BQMLPredictParams,
    FeatureMatrixParams,
    build_create_model_sql,
    build_evaluate_sql,
    build_feature_matrix_sql,
    build_predict_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


class FeatureMatrixExportStage(Stage):
    """Export pair-level feature matrix for ML training.

    Generates a wide table with comparison scores + raw feature values
    for each candidate pair, suitable for BQML or external ML training.
    """

    def __init__(
        self,
        config: PipelineConfig,
        comparison_columns: list[str] | None = None,
        feature_columns: list[str] | None = None,
        labels_table: str | None = None,
        sample_size: int = 0,
    ):
        self._config = config
        self._comparison_columns = comparison_columns or []
        self._feature_columns = feature_columns or []
        self._labels_table = labels_table
        self._sample_size = sample_size

    @property
    def name(self) -> str:
        return "feature_matrix_export"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "all_matches": TableRef(
                name="all_matches",
                fq_name=all_matches_table(self._config),
            ),
            "featured": TableRef(
                name="featured",
                fq_name=featured_table(self._config),
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        output_tbl = self._output_table
        return {
            "feature_matrix": TableRef(
                name="feature_matrix",
                fq_name=output_tbl,
                description="Pair-level feature matrix for ML training",
            ),
        }

    @property
    def _output_table(self) -> str:
        project = self._config.project
        ds = getattr(project, "bq_dataset_silver", "er_silver")
        name = getattr(project, "name", "pipeline")
        return f"{ds}.{name}_feature_matrix"

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        logger.debug("Planning %s stage", self.__class__.__name__)
        params = FeatureMatrixParams(
            candidates_table=self.inputs["all_matches"].fq_name,
            featured_table=self.inputs["featured"].fq_name,
            labels_table=self._labels_table,
            feature_columns=self._feature_columns,
            comparison_columns=self._comparison_columns,
            output_table=self._output_table,
            sample_size=self._sample_size,
        )
        return [build_feature_matrix_sql(params)]


class BQMLTrainingStage(Stage):
    """Train a BQML model for match classification.

    Creates a logistic regression (default) or tree-based classifier
    that predicts is_match from pair-level features.
    """

    def __init__(
        self,
        config: PipelineConfig,
        model_type: str = "LOGISTIC_REG",
        feature_columns: list[str] | None = None,
        max_iterations: int = 20,
        auto_class_weights: bool = True,
    ):
        self._config = config
        self._model_type = model_type
        self._feature_columns = feature_columns or []
        self._max_iterations = max_iterations
        self._auto_class_weights = auto_class_weights

    @property
    def name(self) -> str:
        return "bqml_training"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "feature_matrix": TableRef(
                name="feature_matrix",
                fq_name=self._training_table,
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        return {
            "model": TableRef(
                name="model",
                fq_name=self._model_name,
                description="Trained BQML match classifier",
            ),
        }

    @property
    def _training_table(self) -> str:
        project = self._config.project
        ds = getattr(project, "bq_dataset_silver", "er_silver")
        name = getattr(project, "name", "pipeline")
        return f"{ds}.{name}_feature_matrix"

    @property
    def _model_name(self) -> str:
        project = self._config.project
        ds = getattr(project, "bq_dataset_silver", "er_silver")
        name = getattr(project, "name", "pipeline")
        return f"{ds}.{name}_match_classifier"

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        logger.debug("Planning %s stage", self.__class__.__name__)
        params = BQMLModelParams(
            training_table=self._training_table,
            model_name=self._model_name,
            model_type=self._model_type,  # type: ignore[arg-type]
            feature_columns=self._feature_columns,
            max_iterations=self._max_iterations,
            auto_class_weights=self._auto_class_weights,
        )
        return [build_create_model_sql(params)]


class BQMLPredictStage(Stage):
    """Score candidate pairs using trained BQML model."""

    def __init__(
        self,
        config: PipelineConfig,
        comparison_columns: list[str] | None = None,
        feature_columns: list[str] | None = None,
        threshold: float = 0.5,
    ):
        self._config = config
        self._comparison_columns = comparison_columns or []
        self._feature_columns = feature_columns or []
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "bqml_predict"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "all_matches": TableRef(
                name="all_matches",
                fq_name=all_matches_table(self._config),
            ),
            "featured": TableRef(
                name="featured",
                fq_name=featured_table(self._config),
            ),
            "model": TableRef(
                name="model",
                fq_name=self._model_name,
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        return {
            "predictions": TableRef(
                name="predictions",
                fq_name=self._output_table,
                description="ML-scored candidate pairs",
            ),
        }

    @property
    def _model_name(self) -> str:
        project = self._config.project
        ds = getattr(project, "bq_dataset_silver", "er_silver")
        name = getattr(project, "name", "pipeline")
        return f"{ds}.{name}_match_classifier"

    @property
    def _output_table(self) -> str:
        project = self._config.project
        ds = getattr(project, "bq_dataset_silver", "er_silver")
        name = getattr(project, "name", "pipeline")
        return f"{ds}.{name}_ml_predictions"

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        logger.debug("Planning %s stage", self.__class__.__name__)
        params = BQMLPredictParams(
            model_name=self._model_name,
            candidates_table=self.inputs["all_matches"].fq_name,
            featured_table=self.inputs["featured"].fq_name,
            output_table=self._output_table,
            feature_columns=self._feature_columns,
            comparison_columns=self._comparison_columns,
            threshold=self._threshold,
        )
        return [build_predict_sql(params)]


class BQMLEvaluateStage(Stage):
    """Evaluate BQML model quality (precision, recall, F1, AUC)."""

    def __init__(self, config: PipelineConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "bqml_evaluate"

    @property
    def inputs(self) -> dict[str, TableRef]:
        return {
            "model": TableRef(
                name="model",
                fq_name=self._model_name,
            ),
        }

    @property
    def outputs(self) -> dict[str, TableRef]:
        return {
            "evaluation": TableRef(
                name="evaluation",
                fq_name=self._output_table,
                description="Model evaluation metrics",
            ),
        }

    @property
    def _model_name(self) -> str:
        project = self._config.project
        ds = getattr(project, "bq_dataset_silver", "er_silver")
        name = getattr(project, "name", "pipeline")
        return f"{ds}.{name}_match_classifier"

    @property
    def _output_table(self) -> str:
        project = self._config.project
        ds = getattr(project, "bq_dataset_silver", "er_silver")
        name = getattr(project, "name", "pipeline")
        return f"{ds}.{name}_model_evaluation"

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        logger.debug("Planning %s stage", self.__class__.__name__)
        params = BQMLEvaluateParams(
            model_name=self._model_name,
            output_table=self._output_table,
        )
        return [build_evaluate_sql(params)]
