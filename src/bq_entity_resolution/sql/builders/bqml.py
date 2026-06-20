"""SQL builder for BQML supervised classification.

Generates SQL for:
1. Feature matrix export (pair-level features for training)
2. CREATE MODEL (logistic regression or boosted tree classifier)
3. ML.PREDICT (score candidate pairs using trained model)
4. ML.EVALUATE (model diagnostics: precision, recall, F1, AUC)

BQML Classification Pipeline
=============================
This enables supervised entity resolution: instead of (or in addition to)
hand-tuned weights and Fellegi-Sunter probabilistic scoring, train a BQML
model on labeled match/non-match pairs to learn optimal feature weights.

The pipeline:
  1. Export a feature matrix from candidate pairs + comparison scores
  2. Train a logistic regression (or boosted tree) on labeled pairs
  3. Score new candidate pairs using ML.PREDICT
  4. Evaluate model quality using ML.EVALUATE

This complements the existing Fellegi-Sunter pipeline — users can:
  - Start with rule-based/probabilistic matching
  - Collect labeled data via active learning
  - Train a BQML model for higher accuracy
  - Compare model predictions vs Fellegi-Sunter scores
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from bq_entity_resolution.columns import (
    ENTITY_UID,
    LEFT_ENTITY_UID,
    MATCH_CONFIDENCE,
    RIGHT_ENTITY_UID,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref


@dataclass(frozen=True)
class FeatureMatrixParams:
    """Parameters for feature matrix export."""
    candidates_table: str
    featured_table: str
    labels_table: str | None = None
    feature_columns: list[str] = field(default_factory=list)
    comparison_columns: list[str] = field(default_factory=list)
    output_table: str = ""
    sample_size: int = 0  # 0 = all

    def __post_init__(self) -> None:
        validate_table_ref(self.candidates_table)
        validate_table_ref(self.featured_table)
        if self.labels_table is not None:
            validate_table_ref(self.labels_table)
        if self.output_table:
            validate_table_ref(self.output_table)
        for col in self.feature_columns:
            validate_identifier(col, "feature matrix feature column")
        for col in self.comparison_columns:
            validate_identifier(col, "feature matrix comparison column")


@dataclass(frozen=True)
class BQMLModelParams:
    """Parameters for BQML model creation."""
    training_table: str
    model_name: str
    model_type: Literal[
        "LOGISTIC_REG", "BOOSTED_TREE_CLASSIFIER",
        "RANDOM_FOREST_CLASSIFIER", "DNN_CLASSIFIER",
    ] = "LOGISTIC_REG"
    label_column: str = "is_match"
    feature_columns: list[str] = field(default_factory=list)
    max_iterations: int = 20
    learn_rate: float | None = None
    l1_reg: float | None = None
    l2_reg: float | None = None
    auto_class_weights: bool = True

    def __post_init__(self) -> None:
        validate_table_ref(self.training_table)
        validate_table_ref(self.model_name)
        validate_identifier(self.label_column, "BQML label column")
        for col in self.feature_columns:
            validate_identifier(col, "BQML feature column")


@dataclass(frozen=True)
class BQMLPredictParams:
    """Parameters for ML.PREDICT scoring."""
    model_name: str
    candidates_table: str
    featured_table: str
    output_table: str
    feature_columns: list[str] = field(default_factory=list)
    comparison_columns: list[str] = field(default_factory=list)
    threshold: float = 0.5

    def __post_init__(self) -> None:
        validate_table_ref(self.model_name)
        validate_table_ref(self.candidates_table)
        validate_table_ref(self.featured_table)
        if self.output_table:
            validate_table_ref(self.output_table)
        for col in self.feature_columns:
            validate_identifier(col, "predict feature column")
        for col in self.comparison_columns:
            validate_identifier(col, "predict comparison column")


@dataclass(frozen=True)
class BQMLEvaluateParams:
    """Parameters for ML.EVALUATE diagnostics."""
    model_name: str
    evaluation_table: str | None = None
    output_table: str = ""

    def __post_init__(self) -> None:
        validate_table_ref(self.model_name)
        if self.evaluation_table is not None:
            validate_table_ref(self.evaluation_table)
        if self.output_table:
            validate_table_ref(self.output_table)


def build_feature_matrix_sql(params: FeatureMatrixParams) -> SQLExpression:
    """Build SQL to export pair-level feature matrix for ML training.

    Generates a wide table with:
    - left_entity_uid, right_entity_uid (pair identity)
    - Comparison score columns (from candidates/matches table)
    - Raw feature values from both sides (left_*, right_*)
    - is_match label (from labels table, if available)

    This table can be used directly as BQML training data or exported
    for external ML frameworks (scikit-learn, XGBoost, etc.).
    """
    if not params.comparison_columns and not params.feature_columns:
        raise ValueError(
            "Feature matrix requires at least one comparison_column or feature_column"
        )

    lines: list[str] = []

    if params.output_table:
        lines.append(f"CREATE OR REPLACE TABLE `{params.output_table}` AS")

    lines.append("SELECT")
    lines.append(f"  c.{LEFT_ENTITY_UID},")
    lines.append(f"  c.{RIGHT_ENTITY_UID},")

    # Comparison scores from candidates table
    for col in params.comparison_columns:
        lines.append(f"  c.{col},")

    # Feature values from both sides
    for col in params.feature_columns:
        lines.append(f"  lf.{col} AS left_{col},")
        lines.append(f"  rf.{col} AS right_{col},")

    # Label column (if labels table provided)
    if params.labels_table:
        lines.append(
            "  CASE WHEN lab.human_label = 'match' THEN 1 ELSE 0 END AS is_match"
        )
    else:
        lines.append(
            f"  CASE WHEN c.{MATCH_CONFIDENCE} >= 0.5 THEN 1 ELSE 0 END AS is_match"
        )

    lines.append(f"FROM `{params.candidates_table}` c")

    # Join featured table for left and right feature values
    if params.feature_columns:
        lines.append(
            f"LEFT JOIN `{params.featured_table}` lf "
            f"ON c.{LEFT_ENTITY_UID} = lf.{ENTITY_UID}"
        )
        lines.append(
            f"LEFT JOIN `{params.featured_table}` rf "
            f"ON c.{RIGHT_ENTITY_UID} = rf.{ENTITY_UID}"
        )

    # Join labels table if provided
    if params.labels_table:
        lines.append(
            f"LEFT JOIN `{params.labels_table}` lab "
            f"ON c.{LEFT_ENTITY_UID} = lab.{LEFT_ENTITY_UID} "
            f"AND c.{RIGHT_ENTITY_UID} = lab.{RIGHT_ENTITY_UID}"
        )

    # Sample if requested
    if params.sample_size > 0:
        lines.append(f"ORDER BY FARM_FINGERPRINT(CONCAT("
                     f"CAST(c.{LEFT_ENTITY_UID} AS STRING), "
                     f"CAST(c.{RIGHT_ENTITY_UID} AS STRING)))")
        lines.append(f"LIMIT {params.sample_size}")

    return SQLExpression.from_raw("\n".join(lines))


def build_create_model_sql(params: BQMLModelParams) -> SQLExpression:
    """Build BQML CREATE MODEL SQL for match classification.

    Creates a logistic regression (default) or boosted tree classifier
    that predicts is_match from pair-level features.

    PERF: Logistic regression trains in seconds on <1M pairs.
    Boosted trees take longer but handle non-linear interactions.
    """
    lines: list[str] = []

    lines.append(f"CREATE OR REPLACE MODEL `{params.model_name}`")
    lines.append("OPTIONS (")
    lines.append(f"  model_type = '{params.model_type}',")
    lines.append(f"  input_label_cols = ['{params.label_column}'],")
    lines.append(f"  max_iterations = {params.max_iterations},")

    if params.auto_class_weights:
        lines.append("  auto_class_weights = TRUE,")

    if params.learn_rate is not None:
        lines.append(f"  learn_rate = {params.learn_rate},")

    if params.l1_reg is not None:
        lines.append(f"  l1_reg = {params.l1_reg},")

    if params.l2_reg is not None:
        lines.append(f"  l2_reg = {params.l2_reg},")

    # Remove trailing comma from last option
    lines[-1] = lines[-1].rstrip(",")
    lines.append(") AS")

    # Training query
    lines.append("SELECT")
    if params.feature_columns:
        for col in params.feature_columns:
            lines.append(f"  {col},")
    else:
        lines.append("  * EXCEPT (left_entity_uid, right_entity_uid),")

    # Remove trailing comma
    lines[-1] = lines[-1].rstrip(",")
    lines.append(f"FROM `{params.training_table}`")
    lines.append(f"WHERE {params.label_column} IS NOT NULL")

    return SQLExpression.from_raw("\n".join(lines))


def build_predict_sql(params: BQMLPredictParams) -> SQLExpression:
    """Build ML.PREDICT SQL to score candidate pairs.

    Generates predictions (match probability) for each candidate pair
    using the trained BQML model.
    """
    lines: list[str] = []

    if params.output_table:
        lines.append(f"CREATE OR REPLACE TABLE `{params.output_table}` AS")

    lines.append("SELECT")
    lines.append(f"  base.{LEFT_ENTITY_UID},")
    lines.append(f"  base.{RIGHT_ENTITY_UID},")
    lines.append("  pred.predicted_is_match,")
    lines.append("  pred.predicted_is_match_probs,")
    lines.append(f"  base.{MATCH_CONFIDENCE} AS rule_based_confidence")

    lines.append("FROM ML.PREDICT(")
    lines.append(f"  MODEL `{params.model_name}`,")
    lines.append("  (")
    lines.append("    SELECT")
    lines.append(f"      c.{LEFT_ENTITY_UID},")
    lines.append(f"      c.{RIGHT_ENTITY_UID},")
    lines.append(f"      c.{MATCH_CONFIDENCE},")

    # Comparison scores
    for col in params.comparison_columns:
        lines.append(f"      c.{col},")

    # Feature values from both sides
    for col in params.feature_columns:
        lines.append(f"      lf.{col} AS left_{col},")
        lines.append(f"      rf.{col} AS right_{col},")

    # Remove trailing comma
    lines[-1] = lines[-1].rstrip(",")

    lines.append(f"    FROM `{params.candidates_table}` c")

    if params.feature_columns:
        lines.append(
            f"    LEFT JOIN `{params.featured_table}` lf "
            f"ON c.{LEFT_ENTITY_UID} = lf.{ENTITY_UID}"
        )
        lines.append(
            f"    LEFT JOIN `{params.featured_table}` rf "
            f"ON c.{RIGHT_ENTITY_UID} = rf.{ENTITY_UID}"
        )

    lines.append("  )")
    lines.append(") pred")
    lines.append(f"JOIN `{params.candidates_table}` base")
    lines.append(f"  ON pred.{LEFT_ENTITY_UID} = base.{LEFT_ENTITY_UID}")
    lines.append(f"  AND pred.{RIGHT_ENTITY_UID} = base.{RIGHT_ENTITY_UID}")

    return SQLExpression.from_raw("\n".join(lines))


def build_evaluate_sql(params: BQMLEvaluateParams) -> SQLExpression:
    """Build ML.EVALUATE SQL for model diagnostics.

    Returns: precision, recall, accuracy, f1_score, log_loss, roc_auc.
    """
    lines: list[str] = []

    if params.output_table:
        lines.append(f"CREATE OR REPLACE TABLE `{params.output_table}` AS")

    if params.evaluation_table:
        lines.append("SELECT *")
        lines.append("FROM ML.EVALUATE(")
        lines.append(f"  MODEL `{params.model_name}`,")
        lines.append(f"  (SELECT * FROM `{params.evaluation_table}`))")
    else:
        lines.append("SELECT *")
        lines.append(f"FROM ML.EVALUATE(MODEL `{params.model_name}`)")

    return SQLExpression.from_raw("\n".join(lines))


def build_feature_importance_sql(model_name: str) -> SQLExpression:
    """Build ML.FEATURE_IMPORTANCE SQL to rank features by predictive power.

    Returns feature name + importance_weight for each feature used by the model.
    Only works with tree-based models (BOOSTED_TREE_CLASSIFIER,
    RANDOM_FOREST_CLASSIFIER). For logistic regression, use ML.WEIGHTS instead.
    """
    validate_table_ref(model_name)
    return SQLExpression.from_raw(
        f"SELECT *\nFROM ML.FEATURE_IMPORTANCE(MODEL `{model_name}`)"
    )


def build_model_weights_sql(model_name: str) -> SQLExpression:
    """Build ML.WEIGHTS SQL for logistic regression coefficients.

    Returns feature name + weight for each feature. Useful for understanding
    which comparison scores have the most impact on match prediction.
    """
    validate_table_ref(model_name)
    return SQLExpression.from_raw(
        f"SELECT *\nFROM ML.WEIGHTS(MODEL `{model_name}`)"
    )
