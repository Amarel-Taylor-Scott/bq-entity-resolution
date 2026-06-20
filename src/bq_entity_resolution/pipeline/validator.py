"""Pipeline validator: compile-time contract checking.

Validates that all stage inputs are satisfied by upstream outputs
before any SQL is executed. Catches configuration errors early.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bq_entity_resolution.pipeline.dag import StageDAG


@dataclass(frozen=True)
class ContractViolation:
    """A contract violation found during validation."""

    stage_name: str
    message: str
    severity: str = "error"  # "error" | "warning"


def validate_dag_contracts(
    dag: StageDAG,
    external_tables: set[str] | None = None,
) -> list[ContractViolation]:
    """Validate that all stage inputs are produced by upstream stages.

    Returns a list of violations. Empty list means the DAG is valid.
    Runs at plan time (before execution), catching broken connections.

    Args:
        dag: The pipeline DAG to validate.
        external_tables: FQ names of tables that exist outside the
            pipeline (e.g., raw source tables). These are not flagged
            as missing.
    """
    external_tables = external_tables or set()
    violations: list[ContractViolation] = []

    # Root stages (no dependencies) have external inputs by definition
    root_stages = {
        name
        for name in dag.stage_names
        if not dag.get_dependencies(name)
    }

    # Track tables produced by stages in topological order
    produced_tables: dict[str, str] = {}  # fq_name -> producer stage name

    for stage in dag.stages:
        # Check that all inputs are produced by upstream stages
        for input_key, input_ref in stage.inputs.items():
            if not input_ref.fq_name:
                continue

            # Skip external tables
            if input_ref.fq_name in external_tables:
                continue

            # Root stage inputs are always external
            if stage.name in root_stages:
                continue

            if input_ref.fq_name not in produced_tables:
                violations.append(ContractViolation(
                    stage_name=stage.name,
                    message=(
                        f"Input '{input_key}' references table "
                        f"'{input_ref.fq_name}' which is not produced "
                        f"by any upstream stage"
                    ),
                ))

        # Register this stage's outputs
        for output_ref in stage.outputs.values():
            if output_ref.fq_name:
                produced_tables[output_ref.fq_name] = stage.name

    # Check for stages with no outputs and no dependents (dead ends)
    for stage in dag.stages:
        if not stage.outputs:
            dependents = dag.get_dependents(stage.name)
            if not dependents:
                violations.append(ContractViolation(
                    stage_name=stage.name,
                    message=(
                        "Stage has no outputs and no dependents "
                        "(potential dead end)"
                    ),
                    severity="warning",
                ))

    return violations


def validate_stage_configs(dag: StageDAG) -> list[ContractViolation]:
    """Run each stage's validate() method.

    Catches stage-specific configuration errors (missing blocking
    keys, unknown feature functions, etc.).
    """
    violations: list[ContractViolation] = []

    for stage in dag.stages:
        errors = stage.validate()
        for error in errors:
            violations.append(ContractViolation(
                stage_name=stage.name,
                message=error,
            ))

    return violations
