"""
Matching configuration models.

Defines comparisons, thresholds, hard negatives, soft signals,
training, active learning, and matching tier configuration.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from bq_entity_resolution.config.models.blocking import TierBlockingConfig
from bq_entity_resolution.sql.utils import validate_identifier

_SQL_INJECTION_PATTERN = re.compile(
    r";\s*|--\s|/\*|\bDROP\b|\bALTER\b|\bCREATE\b|\bTRUNCATE\b|\bGRANT\b|\bREVOKE\b",
    re.IGNORECASE,
)

__all__ = [
    "ComparisonLevelDef",
    "TermFrequencyConfig",
    "ComparisonDef",
    "ThresholdConfig",
    "HardNegativeDef",
    "HardPositiveDef",
    "SoftSignalDef",
    "ScoreBandDef",
    "ScoreBandingConfig",
    "TrainingConfig",
    "LabelFeedbackConfig",
    "ActiveLearningConfig",
    "MatchingTierConfig",
]


class ComparisonLevelDef(BaseModel):
    """One outcome level within a multi-level comparison.

    Levels are evaluated top-to-bottom; the first matching level wins.
    The last level should have method=None (else/fallthrough).
    m and u can be set manually or learned from training data / EM.
    log_weight is auto-computed from m/u via log2(m/u) if not set.
    """

    label: str  # "exact", "fuzzy_high", "else"
    method: str | None = None  # comparison function name (None = else/fallthrough)
    params: dict[str, Any] = Field(default_factory=dict)
    m: float | None = None  # P(level | match)
    u: float | None = None  # P(level | non-match)
    log_weight: float | None = None  # Explicit log-weight (auto-computed from m/u if None)
    sql_expr: str | None = None  # Raw SQL override for this level
    tf_adjusted: bool = False  # Apply term-frequency adjustment

    @field_validator("sql_expr")
    @classmethod
    def _validate_sql_expr_safe(cls, v: str | None) -> str | None:
        if v is not None and _SQL_INJECTION_PATTERN.search(v):
            raise ValueError(
                "sql_expr contains disallowed SQL pattern "
                "(semicolons, comments, or DDL keywords)"
            )
        return v

    @field_validator("m", "u")
    @classmethod
    def probability_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"Probability must be in [0, 1], got {v}")
        return v


class TermFrequencyConfig(BaseModel):
    """Term frequency adjustment for a comparison.

    Adjusts match evidence based on value rarity --- a match on "Smith"
    (common) provides less evidence than "Worthington" (rare).
    Follows the Splink approach of adjusting u-probability per-value.
    """

    enabled: bool = False
    tf_minimum_u_value: float = 0.001  # Floor prevents extreme weights from rare values
    tf_adjustment_column: str | None = None  # Override column (defaults to comp.left)

    @field_validator("tf_minimum_u_value")
    @classmethod
    def _valid_tf_floor(cls, v: float) -> float:
        if not (0.0 < v <= 1.0):
            raise ValueError("tf_minimum_u_value must be in (0.0, 1.0]")
        return v


class ComparisonDef(BaseModel):
    """A comparison between two columns using a registered method.

    Can be defined inline or reference a pool entry via ``ref``.
    When ``ref`` is set, the comparison inherits all fields from the pool
    entry.  Any additional fields set alongside ``ref`` act as overrides
    (e.g. ``ref: email_exact, weight: 1.5`` to override the pool weight
    for a specific tier).
    """

    ref: str | None = None  # Pool reference name
    left: str = ""
    right: str = ""
    method: str = ""  # exact, levenshtein, jaro_winkler, cosine_similarity, etc.
    params: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0
    weight_mode: Literal["manual", "auto", "profile"] = "manual"
    levels: list[ComparisonLevelDef] | None = None  # multi-level outcomes for F-S
    tf_adjustment: TermFrequencyConfig | None = None  # term frequency adjustment

    @field_validator("weight")
    @classmethod
    def _non_negative_weight(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Comparison weight must be >= 0")
        return v

    @field_validator("left", "right")
    @classmethod
    def _validate_column_name(cls, v: str) -> str:
        """Validate column names are safe SQL identifiers."""
        if v:
            validate_identifier(v, context="comparison column")
        return v

    @model_validator(mode="after")
    def _require_fields_when_inline(self) -> ComparisonDef:
        """Reject empty left/method when ref is not set (inline definition)."""
        if self.ref:
            return self  # Pool refs fill in fields later
        missing = []
        if not self.left:
            missing.append("left")
        if not self.method:
            missing.append("method")
        if missing:
            raise ValueError(
                f"Inline comparison requires {', '.join(missing)}. "
                "Set 'ref' to reference a comparison_pool entry instead."
            )
        return self


class ThresholdConfig(BaseModel):
    """How to aggregate comparison scores and apply the match threshold.

    Methods:
        sum:            Sum comparison weights where condition is true.
        weighted_sum:   Same as sum (alias for clarity).
        min_all:        All comparisons must pass (AND logic).
        fellegi_sunter: Log-likelihood ratio scoring with m/u probabilities.
    """

    method: Literal["sum", "weighted_sum", "min_all", "fellegi_sunter"] = "sum"
    min_score: float = 0.0
    match_threshold: float | None = None  # F-S: log-likelihood threshold for match
    log_prior_odds: float = 0.0  # F-S: prior log-odds of a match
    min_matching_comparisons: int = 0  # Minimum number of comparisons that must score > 0

    # TODO: Remove "weighted_sum" support in v0.4.0
    @field_validator("method")
    @classmethod
    def _deprecate_weighted_sum(cls, v: str) -> str:
        if v == "weighted_sum":
            import warnings
            warnings.warn(
                "threshold.method='weighted_sum' is deprecated and identical to 'sum'. "
                "Use 'sum' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return "sum"
        return v

    @field_validator("min_matching_comparisons")
    @classmethod
    def _non_negative_min_matches(cls, v: int) -> int:
        if v < 0:
            raise ValueError("min_matching_comparisons must be >= 0")
        return v


class HardNegativeDef(BaseModel):
    """A rule that disqualifies or penalizes candidate pairs.

    Severity classes control how aggressively the rule is applied:
      - hn1_critical: Always disqualify, no overrides possible.
      - hn2_structural: Disqualify by default (standard behavior).
      - hn3_identity: Disqualify only for matching entity types.
      - hn4_contextual: Can be overridden by N hard positives.
    """

    left: str
    right: str | None = None  # defaults to same as left
    method: str  # different, null_either, custom
    action: Literal["disqualify", "penalize"] = "disqualify"
    penalty: float = 0.0
    sql: str | None = None  # raw SQL condition override
    severity: Literal[
        "hn1_critical", "hn2_structural", "hn3_identity", "hn4_contextual"
    ] = "hn2_structural"
    entity_type_condition: str | None = None  # e.g. "personal", "business"
    category: str = "general"  # grouping label for reporting
    requires_overrides: int = 0  # For hn4: N strong positives needed to override
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sql")
    @classmethod
    def _validate_sql_safe(cls, v: str | None) -> str | None:
        if v is not None and _SQL_INJECTION_PATTERN.search(v):
            raise ValueError(
                "sql expression contains disallowed SQL pattern "
                "(semicolons, comments, or DDL keywords)"
            )
        return v

    @field_validator("requires_overrides")
    @classmethod
    def _non_negative_overrides(cls, v: int) -> int:
        if v < 0:
            raise ValueError("requires_overrides must be >= 0")
        return v

    @field_validator("left")
    @classmethod
    def _validate_column_name(cls, v: str) -> str:
        if v:
            validate_identifier(v, context="hard_negative column")
        return v

    @model_validator(mode="after")
    def _normalize_right(self) -> Self:
        if self.right is None:
            object.__setattr__(self, "right", self.left)
        return self


class HardPositiveDef(BaseModel):
    """A rule that boosts or auto-matches candidate pairs.

    Actions:
      - boost: Add a score bonus when condition is met.
      - auto_match: Bypass threshold — pair is an automatic match.
      - elevate_band: Elevate the pair to a higher score band.
    """

    left: str
    right: str | None = None
    method: str  # exact, exact_case_insensitive, custom
    action: Literal["boost", "auto_match", "elevate_band"] = "boost"
    boost: float = 5.0  # score boost when action=boost
    target_band: str = "HIGH"  # band to elevate to when action=elevate_band

    @field_validator("target_band")
    @classmethod
    def _validate_target_band(cls, v: str) -> str:
        if v:
            validate_identifier(v, context="target band name")
        return v

    @field_validator("boost")
    @classmethod
    def _non_negative_boost(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Hard positive boost must be >= 0")
        return v
    sql: str | None = None  # raw SQL condition override
    entity_type_condition: str | None = None
    category: str = "general"
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sql")
    @classmethod
    def _validate_sql_safe(cls, v: str | None) -> str | None:
        if v is not None and _SQL_INJECTION_PATTERN.search(v):
            raise ValueError(
                "sql expression contains disallowed SQL pattern "
                "(semicolons, comments, or DDL keywords)"
            )
        return v

    @field_validator("left")
    @classmethod
    def _validate_column_name(cls, v: str) -> str:
        if v:
            validate_identifier(v, context="hard_positive column")
        return v

    @model_validator(mode="after")
    def _normalize_right(self) -> Self:
        if self.right is None:
            object.__setattr__(self, "right", self.left)
        return self


class SoftSignalDef(BaseModel):
    """A signal that adjusts the match score (positive or negative)."""

    left: str
    right: str | None = None
    method: str  # exact, similar, both_null, custom
    bonus: float = 1.0
    sql: str | None = None
    entity_type_condition: str | None = None
    category: str = "general"
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sql")
    @classmethod
    def _validate_sql_safe(cls, v: str | None) -> str | None:
        if v is not None and _SQL_INJECTION_PATTERN.search(v):
            raise ValueError(
                "sql expression contains disallowed SQL pattern "
                "(semicolons, comments, or DDL keywords)"
            )
        return v

    @field_validator("left")
    @classmethod
    def _validate_column_name(cls, v: str) -> str:
        if v:
            validate_identifier(v, context="soft_signal column")
        return v

    @model_validator(mode="after")
    def _normalize_right(self) -> Self:
        if self.right is None:
            object.__setattr__(self, "right", self.left)
        return self


class ScoreBandDef(BaseModel):
    """A named score band with min/max boundaries."""

    name: str  # HIGH, MEDIUM, LOW, REJECT
    min_score: float
    max_score: float = 999999.0
    action: Literal["accept", "review", "reject"] = "accept"

    @field_validator("name")
    @classmethod
    def _validate_band_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("band name must be a non-empty string")
        validate_identifier(v, context="score band name")
        return v

    @model_validator(mode="after")
    def _min_le_max(self) -> ScoreBandDef:
        if self.min_score > self.max_score:
            raise ValueError(
                f"Band '{self.name}': min_score ({self.min_score}) "
                f"> max_score ({self.max_score})"
            )
        return self


class ScoreBandingConfig(BaseModel):
    """Score banding for tiered match classification.

    When enabled, adds a ``match_band`` column to scored output
    classifying each pair into bands (e.g. HIGH/MEDIUM/LOW/REJECT).
    """

    enabled: bool = False
    bands: list[ScoreBandDef] = Field(default_factory=list)


class TrainingConfig(BaseModel):
    """Parameter estimation configuration for Fellegi-Sunter m/u probabilities."""

    method: Literal["labeled", "em", "none"] = "none"
    labeled_pairs_table: str | None = None  # FQ BQ table of labeled pairs
    em_max_iterations: int = 10
    em_convergence_threshold: float = 0.001
    em_sample_size: int = 100_000
    em_initial_match_proportion: float = 0.1
    parameters_table: str | None = None  # FQ table to persist estimated params

    @field_validator("em_max_iterations", "em_sample_size")
    @classmethod
    def _positive_em_params(cls, v: int) -> int:
        if v < 1:
            raise ValueError("EM parameters must be >= 1")
        return v

    @field_validator("em_convergence_threshold")
    @classmethod
    def _positive_convergence(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("em_convergence_threshold must be > 0")
        return v

    @field_validator("em_initial_match_proportion")
    @classmethod
    def _valid_proportion(cls, v: float) -> float:
        if not (0.0 < v < 1.0):
            raise ValueError("em_initial_match_proportion must be in (0.0, 1.0)")
        return v

    @model_validator(mode="after")
    def _validate_labeled_requires_table(self) -> Self:
        if self.method == "labeled" and not self.labeled_pairs_table:
            raise ValueError(
                "TrainingConfig with method='labeled' requires labeled_pairs_table. "
                "Set labeled_pairs_table to a fully-qualified BigQuery table reference."
            )
        return self


class LabelFeedbackConfig(BaseModel):
    """Configuration for label ingestion and retrain feedback loop.

    Closes the active learning cycle: review queue -> human labels -> retrain m/u.
    """

    enabled: bool = False
    feedback_table: str | None = None  # FQ table to store ingested labels
    min_labels_for_retrain: int = 50  # Minimum labels before retraining
    auto_retrain: bool = False  # Automatically retrain when threshold met

    @field_validator("min_labels_for_retrain")
    @classmethod
    def _positive_min_labels(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_labels_for_retrain must be >= 1")
        return v


class ActiveLearningConfig(BaseModel):
    """Active learning review queue configuration."""

    enabled: bool = False
    review_queue_table: str | None = None
    queue_size: int = 200
    uncertainty_window: float = 0.15
    label_feedback: LabelFeedbackConfig = Field(default_factory=LabelFeedbackConfig)

    @field_validator("queue_size")
    @classmethod
    def _positive_queue_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("queue_size must be >= 1")
        return v

    @field_validator("uncertainty_window")
    @classmethod
    def _valid_uncertainty(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("uncertainty_window must be in [0.0, 1.0]")
        return v


class MatchingTierConfig(BaseModel):
    """A single matching tier in the pipeline."""

    name: str
    description: str = ""
    enabled: bool = True
    blocking: TierBlockingConfig
    comparisons: list[ComparisonDef]
    threshold: ThresholdConfig
    hard_negatives: list[HardNegativeDef] = Field(default_factory=list)
    hard_positives: list[HardPositiveDef] = Field(default_factory=list)
    soft_signals: list[SoftSignalDef] = Field(default_factory=list)
    score_banding: ScoreBandingConfig = Field(default_factory=ScoreBandingConfig)
    confidence: float | None = None  # fixed confidence score for this tier
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    active_learning: ActiveLearningConfig = Field(default_factory=ActiveLearningConfig)

    @field_validator("confidence")
    @classmethod
    def _valid_confidence_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be in [0.0, 1.0]")
        return v

    @field_validator("name")
    @classmethod
    def valid_tier_name(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Tier name must be alphanumeric/underscore/dash: {v}")
        return v
