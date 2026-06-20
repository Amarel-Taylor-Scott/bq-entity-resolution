"""Pipeline package: DAG-based pipeline orchestration.

Core components:
- dag: Build a StageDAG from config
- plan: Create an immutable PipelinePlan from a DAG
- executor: Execute a plan against a Backend
- validator: Compile-time contract validation
- gates: Runtime data quality assertions
- diagnostics: Structured error reporting
"""

from bq_entity_resolution.pipeline.executor import (
    PipelineExecutor,
    PipelineResult,
    StageExecutionResult,
)
from bq_entity_resolution.pipeline.gates import (
    DataQualityGate,
    GateResult,
)
from bq_entity_resolution.pipeline.plan import (
    PipelinePlan,
    StagePlan,
)
from bq_entity_resolution.pipeline.validator import (
    ContractViolation,
)

__all__ = [
    "ContractViolation",
    "DataQualityGate",
    "GateResult",
    "PipelineExecutor",
    "PipelinePlan",
    "PipelineResult",
    "StageExecutionResult",
    "StagePlan",
]
