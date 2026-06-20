"""Cursor profiler: analyze source columns to recommend cursor strategies.

Helps users choose the best secondary cursor column for composite
watermarks by analyzing cardinality, distribution uniformity, and
estimated batch boundaries.

Usage:
    from bq_entity_resolution.tools.cursor_profiler import CursorProfiler

    profiler = CursorProfiler(backend)
    results = profiler.profile(
        table="my-project.raw.customers",
        primary_cursor="updated_at",
        candidate_columns=["policy_id", "state", "region"],
        batch_size=5_000_000,
    )
    for r in results:
        print(f"{r.column}: {r.score:.2f} — {r.recommendation}")

CLI:
    bq-er profile-cursors --config config.yml --batch-size 5000000
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CursorProfileResult:
    """Profiling result for a single candidate cursor column."""

    column: str
    distinct_values: int = 0
    max_records_per_primary: int = 0
    avg_records_per_primary: float = 0.0
    std_dev_records: float = 0.0
    estimated_batches: int = 0
    uniformity_score: float = 0.0  # 0-1, higher = more uniform distribution
    score: float = 0.0  # Overall recommendation score (0-1)
    recommendation: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HashCursorProfileResult:
    """Profiling result for a hash-based virtual cursor."""

    modulus: int = 1000
    estimated_batches: int = 0
    avg_records_per_bucket: float = 0.0
    max_records_per_bucket: int = 0
    score: float = 0.0
    recommendation: str = ""


class CursorProfiler:
    """Analyze source table columns to recommend cursor strategies.

    Helps users choose the best secondary cursor column by analyzing:
    - Cardinality per primary cursor value (e.g., records per date)
    - Distribution uniformity (std dev of partition sizes)
    - Natural ordering properties
    - Estimated batch boundaries for a given batch_size
    """

    def __init__(self, backend: Any):
        """Initialize with a backend that supports execute_and_fetch."""
        self.backend = backend

    def profile(
        self,
        table: str,
        primary_cursor: str,
        candidate_columns: list[str],
        batch_size: int = 5_000_000,
    ) -> list[CursorProfileResult]:
        """Profile candidate columns for use as secondary cursors.

        Args:
            table: Fully-qualified source table.
            primary_cursor: Primary cursor column (usually a timestamp).
            candidate_columns: Columns to evaluate as secondary cursors.
            batch_size: Target batch size for estimation.

        Returns:
            List of CursorProfileResult sorted by score (best first).
        """
        from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref

        validate_table_ref(table)
        validate_identifier(primary_cursor, context="primary cursor column")
        for col in candidate_columns:
            validate_identifier(col, context="candidate cursor column")

        results: list[CursorProfileResult] = []

        for col in candidate_columns:
            try:
                result = self._profile_column(
                    table, primary_cursor, col, batch_size
                )
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "Failed to profile column '%s': %s", col, exc
                )
                results.append(CursorProfileResult(
                    column=col,
                    recommendation=f"Error: {exc}",
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def profile_hash_cursor(
        self,
        table: str,
        hash_column: str,
        primary_cursor: str,
        modulus_values: list[int] | None = None,
        batch_size: int = 5_000_000,
    ) -> list[HashCursorProfileResult]:
        """Profile hash-based virtual cursor with different modulus values.

        Args:
            table: Fully-qualified source table.
            hash_column: Column to hash (e.g., unique_key).
            primary_cursor: Primary cursor column.
            modulus_values: List of MOD values to test (default: [100, 500, 1000]).
            batch_size: Target batch size.

        Returns:
            List of HashCursorProfileResult sorted by score.
        """
        from bq_entity_resolution.sql.utils import validate_identifier, validate_table_ref

        validate_table_ref(table)
        validate_identifier(hash_column, context="hash cursor column")
        validate_identifier(primary_cursor, context="primary cursor column")

        if modulus_values is None:
            modulus_values = [100, 500, 1000]

        results: list[HashCursorProfileResult] = []

        for mod in modulus_values:
            try:
                result = self._profile_hash(
                    table, hash_column, primary_cursor, mod, batch_size
                )
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "Failed to profile hash cursor (MOD %d): %s", mod, exc
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def recommend(
        self,
        natural_results: list[CursorProfileResult],
        hash_results: list[HashCursorProfileResult] | None = None,
        batch_size: int = 5_000_000,
    ) -> str:
        """Generate a recommendation summary.

        Args:
            natural_results: Results from profile().
            hash_results: Optional results from profile_hash_cursor().
            batch_size: Target batch size.

        Returns:
            Human-readable recommendation string.
        """
        lines: list[str] = []
        lines.append(f"Cursor Strategy Recommendation (batch_size={batch_size:,})")
        lines.append("=" * 60)
        lines.append("")

        if natural_results:
            lines.append("Natural Columns (preferred — no compute cost):")
            for r in natural_results[:3]:
                stars = "*" * max(1, int(r.score * 5))
                lines.append(
                    f"  {r.column}: {stars} (score={r.score:.2f})"
                )
                lines.append(f"    {r.recommendation}")
                lines.append(
                    f"    distinct={r.distinct_values:,}, "
                    f"uniformity={r.uniformity_score:.2f}, "
                    f"est_batches={r.estimated_batches}"
                )
            lines.append("")

        if hash_results:
            lines.append("Hash Cursors (fallback — adds FARM_FINGERPRINT cost):")
            for hr in hash_results[:3]:
                lines.append(
                    f"  MOD {hr.modulus}: score={hr.score:.2f}"
                )
                lines.append(f"    {hr.recommendation}")
                lines.append(
                    f"    avg/bucket={hr.avg_records_per_bucket:,.0f}, "
                    f"max/bucket={hr.max_records_per_bucket:,}, "
                    f"est_batches={hr.estimated_batches}"
                )
            lines.append("")

        # Final recommendation
        best_natural = natural_results[0] if natural_results else None
        best_hash = hash_results[0] if hash_results else None

        if best_natural and best_natural.score >= 0.5:
            lines.append(
                f"RECOMMENDATION: Use natural column '{best_natural.column}' "
                f"as secondary cursor."
            )
        elif best_hash:
            lines.append(
                f"RECOMMENDATION: Use hash cursor with "
                f"FARM_FINGERPRINT MOD {best_hash.modulus}."
            )
        else:
            lines.append(
                "RECOMMENDATION: Consider increasing batch_size or "
                "adding a secondary cursor column to your source."
            )

        return "\n".join(lines)

    def _profile_column(
        self,
        table: str,
        primary_cursor: str,
        column: str,
        batch_size: int,
    ) -> CursorProfileResult:
        """Profile a single column as secondary cursor candidate."""
        sql = f"""
        WITH per_primary AS (
            SELECT
                {primary_cursor},
                COUNT(*) AS record_count,
                COUNT(DISTINCT {column}) AS distinct_values
            FROM `{table}`
            GROUP BY {primary_cursor}
        ),
        overall AS (
            SELECT
                COUNT(DISTINCT {column}) AS total_distinct,
                COUNT(*) AS total_records
            FROM `{table}`
        )
        SELECT
            o.total_distinct,
            o.total_records,
            MAX(p.record_count) AS max_records_per_primary,
            AVG(p.record_count) AS avg_records_per_primary,
            STDDEV(p.record_count) AS std_dev_records,
            AVG(p.distinct_values) AS avg_distinct_per_primary
        FROM per_primary p
        CROSS JOIN overall o
        """

        rows = self.backend.execute_and_fetch(sql)
        if not rows:
            return CursorProfileResult(
                column=column,
                recommendation="No data found",
            )

        row = rows[0]
        total_distinct = int(row.get("total_distinct", 0))
        total_records = int(row.get("total_records", 0))
        max_per_primary = int(row.get("max_records_per_primary", 0))
        avg_per_primary = float(row.get("avg_records_per_primary", 0))
        std_dev = float(row.get("std_dev_records", 0))
        avg_distinct = float(row.get("avg_distinct_per_primary", 0))

        # Uniformity: lower std_dev relative to mean = more uniform
        uniformity = 1.0 - min(1.0, std_dev / max(avg_per_primary, 1))

        # Estimate batches needed
        estimated_batches = max(1, total_records // batch_size)

        # Score: higher distinct values + higher uniformity = better
        cardinality_score = min(1.0, total_distinct / max(1, estimated_batches * 2))
        score = (cardinality_score * 0.6 + uniformity * 0.4)

        # Generate recommendation
        if score >= 0.7:
            rec = (
                f"Excellent cursor — high cardinality"
                f" ({total_distinct:,}) and uniform distribution"
            )
        elif score >= 0.5:
            rec = f"Good cursor — adequate cardinality ({total_distinct:,})"
        elif score >= 0.3:
            rec = (
                f"Marginal cursor — low cardinality"
                f" ({total_distinct:,}), consider hash fallback"
            )
        else:
            rec = (
                f"Poor cursor — very low cardinality"
                f" ({total_distinct:,}), use hash cursor instead"
            )

        return CursorProfileResult(
            column=column,
            distinct_values=total_distinct,
            max_records_per_primary=max_per_primary,
            avg_records_per_primary=avg_per_primary,
            std_dev_records=std_dev,
            estimated_batches=estimated_batches,
            uniformity_score=uniformity,
            score=score,
            recommendation=rec,
            details={
                "total_records": total_records,
                "avg_distinct_per_primary": avg_distinct,
            },
        )

    def _profile_hash(
        self,
        table: str,
        hash_column: str,
        primary_cursor: str,
        modulus: int,
        batch_size: int,
    ) -> HashCursorProfileResult:
        """Profile a hash-based virtual cursor."""
        sql = f"""
        WITH bucketed AS (
            SELECT
                {primary_cursor},
                MOD(FARM_FINGERPRINT(CAST({hash_column} AS STRING)), {modulus}) AS bucket,
                COUNT(*) AS cnt
            FROM `{table}`
            GROUP BY {primary_cursor}, bucket
        )
        SELECT
            AVG(cnt) AS avg_per_bucket,
            MAX(cnt) AS max_per_bucket,
            SUM(cnt) AS total_records
        FROM bucketed
        """

        rows = self.backend.execute_and_fetch(sql)
        if not rows:
            return HashCursorProfileResult(modulus=modulus)

        row = rows[0]
        avg_per_bucket = float(row.get("avg_per_bucket", 0))
        max_per_bucket = int(row.get("max_per_bucket", 0))
        total_records = int(row.get("total_records", 0))

        estimated_batches = max(1, total_records // batch_size)

        # Score based on max_per_bucket being close to batch_size
        bucket_efficiency = min(1.0, batch_size / max(max_per_bucket, 1))
        score = bucket_efficiency * 0.8

        if score >= 0.7:
            rec = f"Good hash cursor — max bucket ({max_per_bucket:,}) fits within batch_size"
        elif score >= 0.4:
            rec = "Acceptable hash cursor — some buckets exceed batch_size"
        else:
            rec = f"Poor fit — increase modulus to reduce max bucket size ({max_per_bucket:,})"

        return HashCursorProfileResult(
            modulus=modulus,
            estimated_batches=estimated_batches,
            avg_records_per_bucket=avg_per_bucket,
            max_records_per_bucket=max_per_bucket,
            score=score,
            recommendation=rec,
        )
