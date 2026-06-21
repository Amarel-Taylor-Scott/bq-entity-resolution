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
    MATCH_CONFIDENCE,
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
    leaf_canonical_agg_table,
    leaf_candidates_table,
    leaf_metrics_table,
    leaf_pairs_table,
    leaf_repair_watermarks_table,
)
from bq_entity_resolution.sql.builders.leaf import (
    LeafBlockingPath,
    LeafScoreTerm,
    LeafSQLParams,
    build_leaf_candidates_sql,
    build_leaf_sql,
)
from bq_entity_resolution.sql.builders.leaf_entity import build_canonical_aggregate_sql
from bq_entity_resolution.sql.builders.leaf_metrics import (
    LeafMetricInput,
    build_leaf_metrics_sql,
)
from bq_entity_resolution.sql.builders.leaf_repair import (
    build_advance_repair_watermark_sql,
    build_repair_watermark_ddl,
    repair_watermark_floor,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.sql.utils import sql_escape, validate_table_ref
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

    def __init__(
        self,
        config: PipelineConfig,
        leaves: list[LeafDef] | None = None,
    ):
        self._config = config
        # ``leaves`` lets the DAG pass an explicit selection (e.g. a ``--repair``
        # or ``--leaf`` run that includes scheduled ``old×old`` leaves). When
        # omitted, fall back to the default every-run selection.
        self._leaves = leaves if leaves is not None else config.runnable_leaves()

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

    @staticmethod
    def _is_repair_leaf(leaf: LeafDef) -> bool:
        """A leaf whose cadence we record in the repair watermark.

        Any scheduled (``manual``/``cron``) leaf, and any ``touched_only`` leaf
        (which must advance its watermark each run so "touched since last repair"
        is well-defined).
        """
        return leaf.schedule != "every_run" or leaf.heuristics.touched_only

    @staticmethod
    def _combine_predicates(a: str | None, b: str | None) -> str | None:
        if a and b:
            return f"({a}) AND ({b})"
        return a or b

    def _touched_predicates(
        self, leaf: LeafDef, repair_table: str
    ) -> tuple[str | None, str | None, str | None]:
        """Compile ``touched_only`` into (extra_pair, left, right) predicates.

        Returns the predicates to AND onto, respectively, the join (self-join:
        "at least one endpoint changed since last repair") or the canonical
        side's partition CTE (cross-partition: restrict the old side). All-None
        when ``touched_only`` is off or no canonical side exists.
        """
        if not leaf.heuristics.touched_only:
            return None, None, None
        col = leaf.heuristics.touched_column
        floor = repair_watermark_floor(repair_table, leaf.name)
        if leaf.is_self_join:
            return f"l.{col} > {floor} OR r.{col} > {floor}", None, None
        if self._partition_source(leaf.right) == "canonical":
            return None, None, f"{col} > {floor}"
        if self._partition_source(leaf.left) == "canonical":
            return None, f"{col} > {floor}", None
        logger.warning(
            "Leaf '%s': touched_only set but neither side is canonical — ignoring",
            leaf.name,
        )
        return None, None, None

    def _tier_index(self, tier: Any) -> int:
        for i, t in enumerate(self._config.matching_tiers):
            if t.name == tier.name:
                return i
        return 0

    def _entity_level_columns(
        self, leaf: LeafDef, blocking_paths: list[LeafBlockingPath]
    ) -> list[str]:
        """Columns the consensus aggregate must carry for a leaf.

        Union of the leaf's blocking keys, the comparison columns of the tiers
        it uses, its short-circuit keys, and (if scoped) the touched column.
        """
        cols: set[str] = set()
        for path in blocking_paths:
            cols.update(path.keys)
        if leaf.matching_tiers is not None:
            wanted = set(leaf.matching_tiers)
            tiers = [t for t in self._config.enabled_tiers() if t.name in wanted]
        else:
            tiers = self._config.enabled_tiers()
        for tier in tiers:
            for comp in tier.comparisons:
                cols.add(comp.left)
                if comp.right:
                    cols.add(comp.right)
        cols.update(leaf.heuristics.exact_key_short_circuit)
        if leaf.heuristics.touched_only:
            cols.add(leaf.heuristics.touched_column)
        return sorted(cols)

    def _resolve_scoring_tier(self, leaf: LeafDef) -> Any | None:
        """Pick the tier whose scoring config a sum/F-S leaf reuses.

        Candidates are the leaf's named ``matching_tiers`` (else all enabled
        tiers). Prefer one whose ``threshold.method`` matches the leaf's
        ``scoring``; otherwise the first candidate.
        """
        tiers = self._config.enabled_tiers()
        if leaf.matching_tiers:
            wanted = set(leaf.matching_tiers)
            named = [t for t in tiers if t.name in wanted]
            tiers = named or tiers
        if not tiers:
            return None
        for t in tiers:
            if t.threshold.method == leaf.scoring:
                return t
        return tiers[0]

    def _plan_one_leaf(
        self, leaf: LeafDef, repair_table: str
    ) -> tuple[list[SQLExpression], str | None, str | None, str | None]:
        """Build one leaf's SQL.

        Returns (statements, leaf_pairs_table, left_source, right_source); the
        last three are None when the leaf is skipped. The source tables are the
        *resolved* ones the leaf actually compared (e.g. the consensus aggregate
        for an entity-level leaf), so per-leaf metrics are accurate.
        """
        blocking_paths = _collect_blocking_paths(self._config, leaf)
        if not blocking_paths:
            logger.warning("Leaf '%s' has no usable blocking paths — skipping", leaf.name)
            return [], None, None, None

        extra_pred, touched_left, touched_right = self._touched_predicates(
            leaf, repair_table
        )
        left_table = _partition_table(self._config, leaf.left)
        right_table = _partition_table(self._config, leaf.right)
        left_pred = self._combine_predicates(
            _partition_predicate(self._config, leaf.left), touched_left
        )
        right_pred = self._combine_predicates(
            _partition_predicate(self._config, leaf.right), touched_right
        )
        target = leaf_pairs_table(self._config, leaf.name)

        # Entity-level: collapse the canonical side(s) to one consensus row per
        # cluster, so the leaf compares against canonical *entities* not records.
        pre_exprs: list[SQLExpression] = []
        if leaf.heuristics.entity_level:
            left_canon = self._partition_source(leaf.left) == "canonical"
            right_canon = self._partition_source(leaf.right) == "canonical"
            if left_canon or right_canon:
                agg_table = leaf_canonical_agg_table(self._config, leaf.name)
                pre_exprs.append(
                    build_canonical_aggregate_sql(
                        target=agg_table,
                        source=canonical_index_table(self._config),
                        value_columns=self._entity_level_columns(leaf, blocking_paths),
                    )
                )
                if right_canon:
                    right_table = agg_table
                if left_canon:
                    left_table = agg_table
            else:
                logger.warning(
                    "Leaf '%s': entity_level set but neither side is canonical "
                    "— ignoring",
                    leaf.name,
                )

        if leaf.scoring == "greatest":
            score_terms = _collect_score_terms(self._config, leaf)
            if not score_terms:
                logger.warning(
                    "Leaf '%s' (greatest) has no usable comparisons — skipping",
                    leaf.name,
                )
                return [], None, None, None
            params = LeafSQLParams(
                target_table=target,
                leaf_name=leaf.name,
                left_table=left_table,
                right_table=right_table,
                blocking_paths=blocking_paths,
                score_terms=score_terms,
                threshold=_leaf_threshold(self._config, leaf),
                left_predicate=left_pred,
                right_predicate=right_pred,
                is_self_join=leaf.is_self_join,
                symmetric=leaf.heuristics.symmetric,
                exact_key_short_circuit=list(leaf.heuristics.exact_key_short_circuit),
                max_pairs=leaf.heuristics.max_pairs,
                extra_pair_predicate=extra_pred,
            )
            logger.info(
                "Leaf '%s' [%s × %s] greatest: %d blocking path(s), %d term(s), "
                "threshold=%s, touched_only=%s, entity_level=%s",
                leaf.name, leaf.left, leaf.right, len(blocking_paths),
                len(score_terms), params.threshold, leaf.heuristics.touched_only,
                leaf.heuristics.entity_level,
            )
            return [*pre_exprs, build_leaf_sql(params)], target, left_table, right_table

        # Production scoring (sum / fellegi_sunter): blocking → candidates →
        # reuse the matching tier's full scorer against the leaf's sources.
        from bq_entity_resolution.stages.matching import MatchingStage

        tier = self._resolve_scoring_tier(leaf)
        if tier is None:
            logger.warning(
                "Leaf '%s' (%s) has no tier to score with — skipping",
                leaf.name, leaf.scoring,
            )
            return [], None, None, None
        cand_table = leaf_candidates_table(self._config, leaf.name)
        cand_sql = build_leaf_candidates_sql(
            candidates_table=cand_table,
            left_table=left_table,
            right_table=right_table,
            blocking_paths=blocking_paths,
            left_predicate=left_pred,
            right_predicate=right_pred,
            is_self_join=leaf.is_self_join,
            symmetric=leaf.heuristics.symmetric,
            extra_pair_predicate=extra_pred,
            max_pairs=leaf.heuristics.max_pairs,
        )
        mstage = MatchingStage(
            tier,
            self._tier_index(tier),
            self._config,
            candidates_table_override=cand_table,
            matches_table_override=target,
            left_source_override=left_table,
            right_source_override=right_table,
        )
        scoring_exprs = mstage.plan_scoring(leaf.scoring)
        logger.info(
            "Leaf '%s' [%s × %s] %s via tier '%s': %d blocking path(s), "
            "touched_only=%s, entity_level=%s",
            leaf.name, leaf.left, leaf.right, leaf.scoring, tier.name,
            len(blocking_paths), leaf.heuristics.touched_only,
            leaf.heuristics.entity_level,
        )
        return [*pre_exprs, cand_sql, *scoring_exprs], target, left_table, right_table

    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate per-leaf candidate-pair SQL + the union into all_matches.

        Each leaf is scored by its ``scoring`` (``greatest`` inline, or the
        production ``sum``/``fellegi_sunter`` engine via a candidate table). When
        any selected leaf is a repair leaf (scheduled or ``touched_only``), a
        repair-watermark DDL is emitted first and a watermark-advance INSERT
        last, so ``touched_only`` self-restricts against the prior repair time.
        """
        if not self._leaves:
            return []

        exprs: list[SQLExpression] = []
        # (leaf_name, leaf_pairs_table, has_method_column)
        leaf_specs: list[tuple[str, str, bool]] = []
        metric_inputs: list[LeafMetricInput] = []
        emitted_repair_leaves: list[str] = []
        repair_table = leaf_repair_watermarks_table(self._config)

        if any(self._is_repair_leaf(leaf) for leaf in self._leaves):
            exprs.append(build_repair_watermark_ddl(repair_table))

        for leaf in self._leaves:
            leaf_exprs, target, left_src, right_src = self._plan_one_leaf(
                leaf, repair_table
            )
            if target is None:
                continue
            exprs.extend(leaf_exprs)
            # The greatest scorer's table carries a match_method column (e.g.
            # 'short_circuit'); the sum/F-S matches table does not.
            leaf_specs.append((leaf.name, target, leaf.scoring == "greatest"))
            if left_src and right_src:
                metric_inputs.append(
                    LeafMetricInput(
                        leaf_name=leaf.name,
                        pairs_table=target,
                        left_table=left_src,
                        right_table=right_src,
                        is_self_join=leaf.is_self_join,
                    )
                )
            if self._is_repair_leaf(leaf):
                emitted_repair_leaves.append(leaf.name)

        if leaf_specs:
            exprs.append(self._build_union_sql(leaf_specs))
        if emitted_repair_leaves:
            exprs.append(
                build_advance_repair_watermark_sql(repair_table, emitted_repair_leaves)
            )
        # Optional per-leaf effectiveness metrics (candidate pairs, reduction
        # ratio), gated on monitoring config so default runs are unchanged.
        if metric_inputs and self._config.monitoring.blocking_metrics.enabled:
            exprs.append(
                build_leaf_metrics_sql(leaf_metrics_table(self._config), metric_inputs)
            )
        return exprs

    def _build_union_sql(
        self, leaf_specs: list[tuple[str, str, bool]]
    ) -> SQLExpression:
        """UNION ALL every leaf's pairs into the all_matches table.

        Normalises across scorers: every leaf-pairs table (greatest *and*
        sum/F-S matches schema) carries ``left_entity_uid``, ``right_entity_uid``
        and ``match_total_score``; ``match_leaf`` is emitted as a per-branch
        literal so the union is independent of the scorer's extra columns.
        ``match_method`` is read from the greatest table (preserving
        ``short_circuit``) and synthesised as ``'compare'`` for sum/F-S leaves.
        ``match_confidence`` is carried from the sum/F-S matches schema (the
        greatest scorer has no calibrated confidence → untyped ``NULL``, whose
        type the UNION infers from the sum/F-S branches); this lets the
        clustering confidence floor and per-stratum gates act on leaf edges.
        ``match_tier_name`` carries the leaf name so leaf-aware tooling and
        clustering metrics keep working unchanged.
        """
        target = all_matches_table(self._config)
        selects = []
        for name, tbl, has_method in leaf_specs:
            leaf_lit = sql_escape(name)
            # has_method == greatest scorer: a match_method column but no
            # calibrated match_confidence; sum/F-S has confidence but no method.
            method_col = MATCH_METHOD if has_method else "'compare'"
            conf_col = "NULL" if has_method else MATCH_CONFIDENCE
            selects.append(
                f"SELECT {LEFT_ENTITY_UID}, {RIGHT_ENTITY_UID}, "
                f"{MATCH_TOTAL_SCORE}, '{leaf_lit}' AS {MATCH_LEAF}, "
                f"{method_col} AS {MATCH_METHOD}, "
                f"{conf_col} AS {MATCH_CONFIDENCE} "
                f"FROM `{tbl}`"
            )
        union = "\n  UNION ALL\n  ".join(selects)
        sql = (
            f"CREATE OR REPLACE TABLE `{target}` AS\n"
            f"SELECT\n"
            f"  {LEFT_ENTITY_UID},\n"
            f"  {RIGHT_ENTITY_UID},\n"
            f"  MAX({MATCH_TOTAL_SCORE}) AS {MATCH_TOTAL_SCORE},\n"
            f"  ANY_VALUE({MATCH_LEAF}) AS {MATCH_LEAF},\n"
            f"  ANY_VALUE({MATCH_LEAF}) AS match_tier_name,\n"
            f"  MAX({MATCH_METHOD}) AS {MATCH_METHOD},\n"
            f"  MAX({MATCH_CONFIDENCE}) AS {MATCH_CONFIDENCE}\n"
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
