"""Custom exception hierarchy for the entity resolution pipeline."""


class EntityResolutionError(Exception):
    """Base exception for all pipeline errors."""


class ConfigurationError(EntityResolutionError):
    """Invalid or missing configuration."""


class SQLGenerationError(EntityResolutionError):
    """Failed to generate SQL from template."""


class SQLExecutionError(EntityResolutionError):
    """BigQuery SQL execution failed."""

    def __init__(self, message: str, sql: str = "", job_id: str = ""):
        super().__init__(message)
        self.sql = sql
        self.job_id = job_id


class WatermarkError(EntityResolutionError):
    """Watermark read/write/advance failure."""


class BlockingError(EntityResolutionError):
    """Blocking candidate generation failure."""


class MatchingError(EntityResolutionError):
    """Matching tier execution failure."""


class ReconciliationError(EntityResolutionError):
    """Cross-tier reconciliation failure."""


class EmbeddingError(EntityResolutionError):
    """Embedding computation or LSH failure."""


class ParameterEstimationError(EntityResolutionError):
    """Parameter estimation (training/EM) failure."""


class PipelineAbortError(EntityResolutionError):
    """Pipeline aborted (manual or safety limit)."""


class PipelineCostExceededError(PipelineAbortError):
    """Pipeline aborted because cumulative bytes_billed exceeded threshold."""


class LockFencingError(EntityResolutionError):
    """Fencing token mismatch — lock was stolen by another holder."""
