"""Leaf-resolution stage: run each enabled leaf and union the tagged pairs.

A *leaf* compares an ordered pair of partitions (``left × right``) with its own
blocking, scoring, threshold and heuristics, emits tagged candidate pairs, and
all runnable leaves union into the shared ``all_matches`` table that flows,
unchanged, into clustering (clustering is leaf-blind — it consumes a pair
graph). See ``docs/leaf-resolution-design.md`` §5 (executor flow).

The stage is wired into the DAG only when a config opts into leaf-based
resolution (``leaves:`` present). Configs without ``leaves`` keep the historical
blocking→matching→accumulation flow untouched, so the established suite stays
green; the synthesized presets are still available via
``config.effective_leaves()`` for preview/inspection.
"""

from __future__ import annotations

import logging
from typing import Any

from bq_entity_resolution.columns import (
    LEFT_ENTITY_UID,
    MATCH_LEAF,
    MATCH_METHOD,
    MATCH_TOTAL_SCORE,
    RIGHT_ENTITY_UID,
)
from bq_entity_resolution.config.models.leaves import LeafDef
from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.matching.comparisons import (
    COMPARISON_FUNCTIONS,
    _validated_call,
)
from bq_entity_resolution.naming import (
    all_matches_table,
    canonical_index_table,
    featured_table,
    leaf_pairs_table,
)
from bq_entity_resolution.sql.builders.leaf import (
    LeafBlockingPath,
    LeafScoreTerm,
    LeafSQLParams,
    build_leaf_sql,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import validate_table_ref
from bq_entity_resolution.stages.base import Stage, TableRef

logger = logging.getLogger(__name__)


def _partition_table(config: PipelineConfig, partition_name: str) -> str:
    """Bind a leaf partition reference to its physical table.

    ``batch`` → the featured (staging) table; ``canonical`` → the canonical
    index; ``table`` → the partition's explicit table ref. The default
    partitions are ``new`` (batch) and ``old`` (canonical); a config may name
    arbitrary partitions whose ``source`` selects the same dispatch.
    """
    for part in config.effective_partitions():
        if part.name != partition_name:
            continue
        if part.source == "batch":
            return featured_table(config)
        if part.source == "canonical":
            return canonical_index_table(config)
        if part.source == "table":
            return validate_table_ref(part.table or "")
    # No matching partition def → treat as the batch (back-compat default).
    return featured_table(config)


def _partition_predicate(config: PipelineConfig, partition_name: str) -> str | None:
    for part in config.effective_partitions():
        if part.name == partition_name:
            return part.predicate
    return None


def _collect_score_terms(
    config: PipelineConfig, leaf: LeafDef
) -> list[LeafScoreTerm]:
    """Build the leaf's scored comparison terms from the matching tiers.

    Reuses the comparison registry (``matching/comparisons/*``) exactly like the
    matching stage. ``leaf.matching_tiers`` selects a subset of tiers by name
    (``None`` = all enabled tiers); each comparison renders to a boolean SQL
    expression over ``l.``/``r.`` aliases.
    """
    if leaf.matching_tiers is not None:
        wanted = set(leaf.matching_tiers)
        tiers = [t for t in config.enabled_tiers() if t.name in wanted]
    else:
        tiers = config.enabled_tiers()

    terms: list[LeafScoreTerm] = []
    seen: set[str] = set()
    udf_dataset = config.project.udf_dataset
    for tier in tiers:
        for comp in tier.comparisons:
            func = COMPARISON_FUNCTIONS.get(comp.method)
            if func is None:
                continue
            name = f"{comp.left}_{comp.method}"
            if name in seen:
                continue
            params = dict(comp.params) if comp.params else {}
            if udf_dataset:
                params["udf_dataset"] = udf_dataset
            try:
                sql_expr = _validated_call(func, comp.left, comp.right or comp.left, **params)
            except Exception as exc:
                logger.warning(
                    "Leaf '%s': skipping comparison '%s' (method=%s): %s",
                    leaf.name, comp.left, comp.method, exc,
                )
                continue
            seen.add(name)
            terms.append(LeafScoreTerm(name=name, sql_expr=sql_expr, weight=comp.weight))
    return terms


def _collect_blocking_paths(
    config: PipelineConfig, leaf: LeafDef
) -> list[LeafBlockingPath]:
    """Build the leaf's blocking paths.

    Uses the leaf's own ``blocking`` override when set; otherwise the union of
    the (selected) tiers' blocking paths — the same multi-path keys the blocking
    builder would use, deduplicated.
    """
    paths: list[LeafBlockingPath] = []
    seen: set[tuple[str, ...]] = set()

    def _add(keys: list[str]) -> None:
        key_tuple = tuple(keys)
        if keys and key_tuple not in seen:
            seen.add(key_tuple)
            paths.append(LeafBlockingPath(keys=list(keys)))

    if leaf.blocking is not None:
        for path in leaf.blocking.paths:
            _add(list(path.keys))
        return paths

    if leaf.matching_tiers is not None:
        wanted = set(leaf.matching_tiers)
        tiers = [t for t in config.enabled_tiers() if t.name in wanted]
    else:
        tiers = config.enabled_tiers()
    for tier in tiers:
        for path in tier.blocking.paths:
            _add(list(path.keys))
    return paths


def _leaf_threshold(config: PipelineConfig, leaf: LeafDef) -> float:
    """Resolve the leaf's accept threshold.

    Honours ``heuristics.threshold_override`` first; otherwise derives a
    threshold from the selected tiers' ``min_score`` (max of them, so the leaf
    is at least as strict as its strictest tier).
    """
    if leaf.heuristics.threshold_override is not None:
        return leaf.heuristics.threshold_override
    if leaf.matching_tiers is not None:
        wanted = set(leaf.matching_tiers)
        tiers = [t for t in config.enabled_tiers() if t.name in wanted]
    else:
        tiers = config.enabled_tiers()
    scores = [t.threshold.min_score for t in tiers if t.threshold.min_score is not None]
    return max(scores) if scores else 0.0


class LeafResolutionStage(Stage):
    """Run each runnable leaf and union the tagged candidate pairs.

    Produces one ``leaf_pairs_<name>`` table per leaf, then unions them into the
    ``all_matches`` table (tagged by ``match_leaf``) that clustering consumes.
    """

    def __init__(self, config: PipelineConfig):
        self._config = config
        self._leaves = config.runnable_leaves()

    @property
    def name(self) -> str:
        return "leaf_resolution"

    @property
    def inputs(self) -> dict[str, TableRef]:
        refs = {
            "featured": TableRef(
                name="featured", fq_name=featured_table(self._config)
            ),
        }
        # Cross-partition / canonical leaves read the canonical index.
        if any(
            self._partition_source(leaf.left) == "canonical"
            or self._partition_source(leaf.right) == "canonical"
            for leaf in self._leaves
        ):
            refs["canonical_index"] = TableRef(
                name="canonical_index",
                fq_name=canonical_index_table(self._config),
            )
        return refs

    @property
    def outputs(self) -> dict[str, TableRef]:
        return {
            "all_matches": TableRef(
                name="all_matches",
                fq_name=all_matches_table(self._config),
                description="Accumulated leaf candidate pairs (tagged by leaf)",
            ),
        }

    def _partition_source(self, partition_name: str) -> str:
        for part in self._config.effective_partitions():
            if part.name == partition_name:
                return part.source
        return "batch"

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate per-leaf candidate-pair SQL + the union into all_matches."""
        if not self._leaves:
            return []

        exprs: list[SQLExpression] = []
        leaf_tables: list[str] = []

        for leaf in self._leaves:
            score_terms = _collect_score_terms(self._config, leaf)
            blocking_paths = _collect_blocking_paths(self._config, leaf)
            if not score_terms or not blocking_paths:
                logger.warning(
                    "Leaf '%s' has no usable %s — skipping",
                    leaf.name,
                    "comparisons" if not score_terms else "blocking paths",
                )
                continue

            target = leaf_pairs_table(self._config, leaf.name)
            params = LeafSQLParams(
                target_table=target,
                leaf_name=leaf.name,
                left_table=_partition_table(self._config, leaf.left),
                right_table=_partition_table(self._config, leaf.right),
                blocking_paths=blocking_paths,
                score_terms=score_terms,
                threshold=_leaf_threshold(self._config, leaf),
                left_predicate=_partition_predicate(self._config, leaf.left),
                right_predicate=_partition_predicate(self._config, leaf.right),
                is_self_join=leaf.is_self_join,
                symmetric=leaf.heuristics.symmetric,
                exact_key_short_circuit=list(leaf.heuristics.exact_key_short_circuit),
                max_pairs=leaf.heuristics.max_pairs,
            )
            exprs.append(build_leaf_sql(params))
            leaf_tables.append(target)
            logger.info(
                "Leaf '%s' [%s × %s]: %d blocking path(s), %d score term(s), "
                "threshold=%s, short_circuit=%s",
                leaf.name, leaf.left, leaf.right,
                len(blocking_paths), len(score_terms),
                params.threshold, params.exact_key_short_circuit,
            )

        if leaf_tables:
            exprs.append(self._build_union_sql(leaf_tables))
        return exprs

    def _build_union_sql(self, leaf_tables: list[str]) -> SQLExpression:
        """UNION ALL every leaf's pairs into the all_matches table.

        Tagged by ``match_leaf`` and shaped with the score/tier columns
        clustering expects (``match_tier_name`` carries the leaf name so
        leaf-aware tooling and clustering metrics keep working unchanged).
        """
        target = all_matches_table(self._config)
        selects = [
            (
                f"SELECT {LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}, "
                f"{MATCH_TOTAL_SCORE}, {MATCH_LEAF}, {MATCH_METHOD} "
                f"FROM `{tbl}`"
            )
            for tbl in leaf_tables
        ]
        union = "\n  UNION ALL\n  ".join(selects)
        sql = (
            f"CREATE OR REPLACE TABLE `{target}` AS\n"
            f"SELECT\n"
            f"  {LEFT_ENTITY_UID},\n"
            f"  {RIGHT_ENTITY_UID},\n"
            f"  MAX({MATCH_TOTAL_SCORE}) AS {MATCH_TOTAL_SCORE},\n"
            f"  ANY_VALUE({MATCH_LEAF}) AS {MATCH_LEAF},\n"
            f"  ANY_VALUE({MATCH_LEAF}) AS match_tier_name,\n"
            f"  MAX({MATCH_METHOD}) AS {MATCH_METHOD}\n"
            f"FROM (\n  {union}\n)\n"
            f"GROUP BY {LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}"
        )
        return SQLExpression.from_raw(sql)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for leaf in self._leaves:
            if not _collect_score_terms(self._config, leaf):
                errors.append(
                    f"Leaf '{leaf.name}' resolves to no usable comparisons"
                )
        return errors
