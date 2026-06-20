"""Dataclass models for comparison/scoring SQL builders.

These frozen dataclasses define the parameters for sum-based and
Fellegi-Sunter probabilistic scoring SQL generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref


@dataclass(frozen=True)
class ComparisonLevel:
    """A single comparison level (for Fellegi-Sunter)."""
    label: str
    sql_expr: str | None  # None = ELSE clause
    log_weight: float = 0.0
    m: float = 0.9
    u: float = 0.1
    tf_adjusted: bool = False


@dataclass(frozen=True)
class ComparisonDef:
    """A comparison definition."""
    name: str
    sql_expr: str = ""  # For sum-based scoring
    weight: float = 1.0
    levels: list[ComparisonLevel] = field(default_factory=list)  # For F-S
    tf_enabled: bool = False
    tf_column: str = ""
    tf_minimum_u: float = 0.01


@dataclass(frozen=True)
class HardNegative:
    """A hard negative rule."""
    sql_condition: str
    action: str  # disqualify or penalize
    penalty: float = 0.0


@dataclass(frozen=True)
class SoftSignal:
    """A soft signal bonus."""
    sql_condition: str
    bonus: float = 0.0


@dataclass(frozen=True)
class HardPositive:
    """A hard positive rule that boosts or auto-matches pairs."""
    sql_condition: str
    action: str = "boost"  # boost, auto_match, elevate_band
    boost: float = 5.0
    target_band: str = "HIGH"

    def __post_init__(self) -> None:
        validate_identifier(self.target_band, "hard positive target band")


@dataclass(frozen=True)
class ScoreBand:
    """A named score band for match classification."""
    name: str
    min_score: float
    max_score: float = 999999.0
    action: str = "accept"  # accept, review, reject

    def __post_init__(self) -> None:
        validate_identifier(self.name, "score band name")


@dataclass(frozen=True)
class Threshold:
    """Scoring threshold configuration."""
    method: str = "score"
    min_score: float = 0.0
    match_threshold: float | None = None
    min_matching_comparisons: int = 0


@dataclass(frozen=True)
class SumScoringParams:
    """Parameters for sum-based scoring."""
    tier_name: str
    tier_index: int
    matches_table: str
    candidates_table: str
    source_table: str
    comparisons: list[ComparisonDef]
    hard_negatives: list[HardNegative] = field(default_factory=list)
    hard_positives: list[HardPositive] = field(default_factory=list)
    soft_signals: list[SoftSignal] = field(default_factory=list)
    threshold: Threshold = field(default_factory=Threshold)
    confidence: float | None = None
    max_possible_score: float = 1.0
    tf_table: str | None = None
    audit_trail_enabled: bool = False
    score_bands: list[ScoreBand] = field(default_factory=list)
    confidence_method: str = "ratio"  # "ratio" or "sigmoid"

    def __post_init__(self) -> None:
        validate_table_ref(self.matches_table)
        validate_table_ref(self.candidates_table)
        validate_table_ref(self.source_table)
        if self.tf_table is not None:
            validate_table_ref(self.tf_table)
        if self.confidence_method not in ("ratio", "sigmoid"):
            raise ValueError(
                f"confidence_method must be 'ratio' or 'sigmoid', "
                f"got '{self.confidence_method}'"
            )


@dataclass(frozen=True)
class FellegiSunterParams:
    """Parameters for Fellegi-Sunter probabilistic scoring."""
    tier_name: str
    tier_index: int
    matches_table: str
    candidates_table: str
    source_table: str
    comparisons: list[ComparisonDef]
    log_prior_odds: float = 0.0
    hard_negatives: list[HardNegative] = field(default_factory=list)
    hard_positives: list[HardPositive] = field(default_factory=list)
    soft_signals: list[SoftSignal] = field(default_factory=list)
    threshold: Threshold = field(default_factory=Threshold)
    tf_table: str | None = None
    audit_trail_enabled: bool = False
    score_bands: list[ScoreBand] = field(default_factory=list)

    def __post_init__(self) -> None:
        validate_table_ref(self.matches_table)
        validate_table_ref(self.candidates_table)
        validate_table_ref(self.source_table)
        if self.tf_table is not None:
            validate_table_ref(self.tf_table)


__all__ = [
    "ComparisonLevel",
    "ComparisonDef",
    "HardNegative",
    "SoftSignal",
    "HardPositive",
    "ScoreBand",
    "Threshold",
    "SumScoringParams",
    "FellegiSunterParams",
]
