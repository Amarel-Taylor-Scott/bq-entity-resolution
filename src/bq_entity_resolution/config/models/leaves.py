"""Leaf-based resolution configuration models.

A *leaf* is a first-class, independently-configured comparison over an ordered
pair of *partitions* of the entity space (``left × right``). It owns its own
blocking, matching tiers, thresholds and heuristics, and emits tagged candidate
pairs that union into the shared clustering step.

``new×new`` / ``new×old`` / ``old×old`` are presets of the generic ``N×M`` model
(see ``docs/leaf-resolution-design.md``). When a config omits ``leaves``, the
loader synthesizes the historical behaviour (intra-batch + cross-batch) so
existing configs are unchanged.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from bq_entity_resolution.config.models.blocking import TierBlockingConfig
from bq_entity_resolution.sql.utils import validate_identifier

__all__ = [
    "PartitionDef",
    "LeafHeuristics",
    "LeafDef",
    "default_partitions",
    "default_leaves",
]

# Reuse the project's SQL-safety guard for raw predicate / key fragments.
_SQL_INJECTION_PATTERN = re.compile(
    r";\s*|--\s|/\*|\bDROP\b|\bALTER\b|\bCREATE\b|\bTRUNCATE\b|\bGRANT\b|\bREVOKE\b|"
    r"\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bMERGE\b",
    re.IGNORECASE,
)


def _reject_sql_injection(value: str, *, context: str) -> str:
    if _SQL_INJECTION_PATTERN.search(value):
        raise ValueError(f"Unsafe SQL in {context}: {value!r}")
    return value


class PartitionDef(BaseModel):
    """A named, SQL-expressible subset of the record/entity space.

    ``source`` selects the physical table the executor binds to:
      - ``batch``     → the current watermark batch (the "new" records)
      - ``canonical`` → the canonical index / gold store (the "old" entities)
      - ``table``     → an explicit table reference (``table`` required)

    An optional ``predicate`` (a raw SQL boolean expression) further narrows the
    partition, e.g. ``"updated_at >= @last_repair_at"`` or ``"source = 'crm'"``.
    """

    name: str
    source: Literal["batch", "canonical", "table"] = "batch"
    table: str | None = None
    predicate: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return validate_identifier(v, context="partition name")

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, v: str | None) -> str | None:
        return None if v is None else _reject_sql_injection(v, context="partition predicate")

    @model_validator(mode="after")
    def _table_required_for_table_source(self) -> PartitionDef:
        if self.source == "table" and not self.table:
            raise ValueError(f"partition {self.name!r}: source='table' requires 'table'")
        return self


class LeafHeuristics(BaseModel):
    """Per-leaf tuning knobs (compiled into the leaf SQL)."""

    # Canonical key columns that auto-accept on exact equality (cheap, high-recall).
    # Used mainly by new×old (e.g. ["email_norm", "phone_e164"]).
    exact_key_short_circuit: list[str] = Field(default_factory=list)
    # Override the leaf's accept threshold (else inherit the matching tier's).
    threshold_override: float | None = Field(default=None, ge=0.0, le=1.0)
    # Self-join (left == right) emits each unordered pair once.
    symmetric: bool = True
    # new×old: compare a new record against each canonical *entity* (one
    # consensus row per cluster — most-frequent value per field) instead of
    # against every historical *record*. Yields cleaner consensus scoring and
    # removes redundant pairs against multiple members of the same entity.
    # Trade-off: blocking is via the consensus value, so a new record matching
    # only a minority member's blocking key won't block — opt in per leaf.
    entity_level: bool = False
    # old×old repair: only re-examine entities changed since the last repair run.
    touched_only: bool = False
    # Timestamp column used to decide whether an entity is "touched" (loaded /
    # updated) since the last repair. Must exist on the canonical/old partition
    # (the canonical index mirrors `featured`, so `pipeline_loaded_at` is the
    # default). Only consulted when ``touched_only`` is True.
    touched_column: str = "pipeline_loaded_at"
    # Safety cap on candidate pairs produced by this leaf (None = unlimited).
    max_pairs: int | None = Field(default=None, ge=1)

    @field_validator("exact_key_short_circuit")
    @classmethod
    def _validate_keys(cls, v: list[str]) -> list[str]:
        for key in v:
            validate_identifier(key, context="short-circuit key")
        return v

    @field_validator("touched_column")
    @classmethod
    def _validate_touched_column(cls, v: str) -> str:
        return validate_identifier(v, context="touched_only column")


class LeafDef(BaseModel):
    """A comparison leaf: ``left × right`` partitions with its own blocking,
    matching and heuristics.

    ``matching_tiers`` names a subset of the pipeline's tiers to run inside this
    leaf (``None`` = all enabled tiers). ``blocking`` overrides the tier blocking
    for this leaf (``None`` = use each tier's own blocking).

    ``schedule`` controls when a leaf runs: ``every_run`` (default), ``manual``
    (only via ``--leaf``/``--repair``), or ``cron`` (when the cron window is due).
    ``old×old`` repair is typically ``schedule="cron"`` so it never changes the
    default per-run cost.
    """

    name: str
    left: str
    right: str
    blocking: TierBlockingConfig | None = None
    matching_tiers: list[str] | None = None
    # Scorer for this leaf's candidate pairs:
    #   - "greatest"        → lightweight GREATEST(weighted booleans) scorer built
    #     into the leaf SQL (fast pre-screen; the historical leaf behaviour).
    #   - "sum"/"fellegi_sunter" → reuse the *production* scoring engine (soft
    #     signals, hard negatives, score banding, auto-match, TF) against the
    #     leaf's candidate table, so the leaf threshold is on the same scale as
    #     the matching tier's ``min_score``. A leaf using these resolves to a
    #     single tier (its named ``matching_tiers`` entry, else the first enabled
    #     tier of the resolved method).
    scoring: Literal["greatest", "sum", "fellegi_sunter"] = "greatest"
    heuristics: LeafHeuristics = Field(default_factory=LeafHeuristics)
    enabled: bool = True
    schedule: Literal["every_run", "manual", "cron"] = "every_run"
    cron: str | None = None

    @field_validator("name", "left", "right")
    @classmethod
    def _validate_idents(cls, v: str) -> str:
        return validate_identifier(v, context="leaf partition reference")

    @property
    def is_self_join(self) -> bool:
        """True when comparing a partition to itself (dedup / intra-partition)."""
        return self.left == self.right

    @model_validator(mode="after")
    def _cron_requires_expr(self) -> LeafDef:
        if self.schedule == "cron" and not self.cron:
            raise ValueError(f"leaf {self.name!r}: schedule='cron' requires 'cron'")
        return self


# ── preset synthesis (back-compat: configs without `leaves`) ────────────────

def default_partitions() -> list[PartitionDef]:
    """The two partitions every incremental pipeline already has."""
    return [
        PartitionDef(name="new", source="batch"),
        PartitionDef(name="old", source="canonical"),
    ]


def default_leaves(*, cross_batch: bool) -> list[LeafDef]:
    """Reproduce the historical behaviour as explicit leaves.

    Always intra-batch (``new×new``). Add ``new×old`` only when the existing
    blocking enabled cross-batch comparison — preserving pre-leaf semantics so
    the established test suite stays green. ``old×old`` is opt-in (not synthesized).
    """
    leaves = [LeafDef(name="new_x_new", left="new", right="new")]
    if cross_batch:
        leaves.append(
            LeafDef(
                name="new_x_old", left="new", right="old",
                heuristics=LeafHeuristics(exact_key_short_circuit=[]),
            )
        )
    return leaves
