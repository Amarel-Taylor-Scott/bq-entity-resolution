"""Stage base class and supporting types.

A Stage is an isolated unit of pipeline work that:
1. Declares what tables it reads (inputs) and writes (outputs)
2. Generates SQL via plan() without side effects
3. Can be tested independently
4. Carries quality gate definitions
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from bq_entity_resolution.sql.expression import SQLExpression


@dataclass(frozen=True)
class TableRef:
    """Reference to a table with optional schema expectations.

    Used to declare stage inputs and outputs so the DAG can be
    validated at compile time (Phase 4).
    """
    name: str  # Logical name (e.g., "featured", "candidates_tier1")
    fq_name: str = ""  # Fully-qualified name (e.g., "proj.ds.featured")
    description: str = ""


@dataclass
class StageResult:
    """Result of executing a stage."""
    stage_name: str
    sql_expressions: list[SQLExpression] = field(default_factory=list)
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Stage(ABC):
    """Abstract base class for pipeline stages.

    Each stage:
    - Has a unique name
    - Declares inputs (tables it reads) and outputs (tables it writes)
    - Implements plan() to generate SQL without side effects
    - Can be tested by examining the SQL output without executing it
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique stage identifier."""

    @property
    def inputs(self) -> dict[str, TableRef]:
        """Tables this stage reads from.

        Keys are logical names (e.g., "source"), values are TableRefs.
        Override in subclasses that read tables.
        """
        return {}

    @property
    def outputs(self) -> dict[str, TableRef]:
        """Tables this stage writes to.

        Keys are logical names (e.g., "featured"), values are TableRefs.
        Override in subclasses that write tables.
        """
        return {}

    @abstractmethod
    def plan(self, **kwargs: Any) -> list[SQLExpression]:
        """Generate SQL expressions for this stage.

        Must not have side effects. Returns a list of SQL expressions
        to execute in order.

        kwargs can include runtime context (watermarks, parameters, etc.)
        """

    def validate(self) -> list[str]:
        """Validate stage configuration. Returns list of error messages."""
        return []

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"
