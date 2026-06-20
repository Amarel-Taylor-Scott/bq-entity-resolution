"""Pipeline plan: immutable snapshot of planned SQL execution.

The plan phase generates all SQL without executing it. This enables:
1. Preview of all SQL before execution
2. Validation of stage contracts
3. Testing SQL generation independently from execution
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import TableRef

if TYPE_CHECKING:
    from bq_entity_resolution.pipeline.dag import StageDAG


@dataclass(frozen=True)
class StagePlan:
    """Plan for a single stage."""

    stage_name: str
    sql_expressions: tuple[SQLExpression, ...]
    inputs: dict[str, TableRef]
    outputs: dict[str, TableRef]
    dependencies: tuple[str, ...]

    @property
    def sql_count(self) -> int:
        return len(self.sql_expressions)

    def render_sql(self, dialect: str = "bigquery") -> list[str]:
        """Render all SQL expressions for this stage."""
        return [expr.render(dialect) for expr in self.sql_expressions]


@dataclass(frozen=True)
class PipelinePlan:
    """Immutable plan for a complete pipeline execution.

    Created by planning all stages in DAG order. Can be previewed,
    validated, and then executed by PipelineExecutor.
    """

    stages: tuple[StagePlan, ...]

    @property
    def stage_names(self) -> list[str]:
        return [s.stage_name for s in self.stages]

    @property
    def total_sql_count(self) -> int:
        return sum(s.sql_count for s in self.stages)

    def get_stage(self, name: str) -> StagePlan:
        """Get a stage plan by name."""
        for s in self.stages:
            if s.stage_name == name:
                return s
        raise KeyError(f"Stage not found: {name}")

    def all_sql(self, dialect: str = "bigquery") -> list[str]:
        """Render all SQL statements in execution order."""
        result = []
        for stage in self.stages:
            result.extend(stage.render_sql(dialect))
        return result

    def preview(self) -> str:
        """Human-readable summary of the plan."""
        lines = [
            f"Pipeline Plan: {len(self.stages)} stages, "
            f"{self.total_sql_count} SQL statements",
            "",
        ]
        for i, stage in enumerate(self.stages, 1):
            deps = (
                ", ".join(stage.dependencies)
                if stage.dependencies
                else "(none)"
            )
            inputs = (
                ", ".join(stage.inputs.keys())
                if stage.inputs
                else "(none)"
            )
            outputs = (
                ", ".join(stage.outputs.keys())
                if stage.outputs
                else "(none)"
            )
            lines.append(f"  {i}. {stage.stage_name}")
            lines.append(f"     deps: {deps}")
            lines.append(f"     inputs: {inputs}")
            lines.append(f"     outputs: {outputs}")
            lines.append(f"     sql: {stage.sql_count} statement(s)")
        return "\n".join(lines)


def create_plan(dag: StageDAG, **plan_kwargs: Any) -> PipelinePlan:
    """Generate a PipelinePlan from a StageDAG.

    plan_kwargs are passed to each stage's plan() method.
    Common kwargs:
      - watermark: dict[str, Any] | None
      - full_refresh: bool

    Blocking stages for tiers after the first automatically receive
    the all_matches_table as excluded_pairs_table for cross-tier
    pair exclusion.
    """
    stage_plans = []

    # Build the set of tiers that need cross-tier exclusion.
    # A blocking stage needs exclusion if its tier is NOT the first
    # (i.e., there are prior tiers whose matches should be excluded).
    # Extract tier names from blocking stage names (blocking_{tier_name}).
    tier_names_ordered: list[str] = []
    for stage in dag.stages:
        if stage.name.startswith("blocking_"):
            tier_name = stage.name[len("blocking_"):]
            if tier_name not in tier_names_ordered:
                tier_names_ordered.append(tier_name)

    tiers_with_exclusion: set[str] = set()
    for i, name in enumerate(tier_names_ordered):
        if i > 0:  # Not first tier — should exclude prior matches
            tiers_with_exclusion.add(name)

    for stage in dag.stages:
        stage_kwargs = dict(plan_kwargs)

        # Inject excluded_pairs_table for blocking stages after the first tier.
        if stage.name.startswith("blocking_"):
            tier_name = stage.name[len("blocking_"):]
            if tier_name in tiers_with_exclusion:
                # This blocking stage is for a tier after the first --
                # inject the all_matches_table for prior-tier exclusion.
                if "excluded_pairs_table" not in stage_kwargs:
                    from bq_entity_resolution.stages.blocking import BlockingStage

                    if isinstance(stage, BlockingStage):
                        from bq_entity_resolution.naming import all_matches_table

                        stage_kwargs["excluded_pairs_table"] = all_matches_table(
                            stage._config
                        )

        exprs = stage.plan(**stage_kwargs)

        stage_plans.append(StagePlan(
            stage_name=stage.name,
            sql_expressions=tuple(exprs),
            inputs=dict(stage.inputs),
            outputs=dict(stage.outputs),
            dependencies=tuple(dag.get_dependencies(stage.name)),
        ))

    return PipelinePlan(stages=tuple(stage_plans))
