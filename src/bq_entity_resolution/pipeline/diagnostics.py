"""Pipeline diagnostics: structured error reporting.

Provides actionable diagnosis when pipeline stages fail. Instead of
generic "0 rows returned", diagnostics explain WHY and provide
specific SQL queries to investigate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnosis:
    """Structured diagnosis for a pipeline failure."""

    message: str
    possible_causes: tuple[str, ...] = ()
    suggested_checks: tuple[str, ...] = ()

    def format(self) -> str:
        """Format as a human-readable multi-line string."""
        lines = [f"DIAGNOSIS: {self.message}"]
        if self.possible_causes:
            lines.append("Possible causes:")
            for cause in self.possible_causes:
                lines.append(f"  - {cause}")
        if self.suggested_checks:
            lines.append("Suggested checks:")
            for check in self.suggested_checks:
                lines.append(f"  - {check}")
        return "\n".join(lines)


def diagnose_empty_blocking(
    tier_name: str,
    blocking_keys: list[str],
    source_table: str,
    link_type: str | None = None,
) -> Diagnosis:
    """Diagnose why blocking produced zero candidates."""
    key_list = ", ".join(blocking_keys)
    null_checks = ", ".join(
        f"COUNTIF({k} IS NULL) AS {k}_nulls" for k in blocking_keys
    )

    causes = [
        f"Blocking key(s) [{key_list}] may have all NULL values",
        "Blocking keys may have very low cardinality (all unique values)",
        "Source table may be empty or have fewer than 2 records",
    ]

    checks = [
        f"SELECT COUNT(*), {null_checks} FROM `{source_table}`",
        (
            f"SELECT {key_list}, COUNT(*) AS cnt "
            f"FROM `{source_table}` "
            f"GROUP BY {key_list} ORDER BY cnt DESC LIMIT 10"
        ),
    ]

    if link_type == "link_only":
        causes.append(
            "link_type='link_only' requires records from different sources; "
            "check that source_name has at least 2 distinct values"
        )
        checks.append(
            f"SELECT DISTINCT source_name FROM `{source_table}`"
        )

    return Diagnosis(
        message=f"Empty blocking results for tier '{tier_name}'",
        possible_causes=tuple(causes),
        suggested_checks=tuple(checks),
    )


def diagnose_empty_matches(
    tier_name: str,
    candidates_table: str,
    threshold: float | None = None,
) -> Diagnosis:
    """Diagnose why matching produced zero matches."""
    causes = [
        "Threshold may be too high — no candidate pairs score above it",
        "Comparison functions may all return 0 (check NULL handling)",
        "Candidate pairs may genuinely have no matches",
    ]

    scores_table = candidates_table.replace("candidates", "scores")
    checks = [
        f"SELECT COUNT(*) AS candidate_count FROM `{candidates_table}`",
        (
            f"SELECT MIN(total_score), MAX(total_score), "
            f"AVG(total_score) FROM `{scores_table}`"
        ),
    ]

    if threshold is not None:
        checks.append(
            f"SELECT COUNT(*) FROM `{scores_table}` "
            f"WHERE total_score >= {threshold}"
        )

    return Diagnosis(
        message=f"Empty matching results for tier '{tier_name}'",
        possible_causes=tuple(causes),
        suggested_checks=tuple(checks),
    )


def diagnose_cluster_explosion(
    max_size: int,
    threshold: int,
    cluster_table: str,
) -> Diagnosis:
    """Diagnose cluster explosion (cluster too large)."""
    return Diagnosis(
        message=(
            f"Cluster explosion: max cluster size {max_size} "
            f"exceeds threshold {threshold}"
        ),
        possible_causes=(
            "Transitive closure links unrelated records through "
            "false positive matches",
            "Blocking keys are too broad, creating a mega-cluster",
            "Matching threshold is too low, admitting weak matches",
        ),
        suggested_checks=(
            (
                f"SELECT cluster_id, COUNT(*) AS size "
                f"FROM `{cluster_table}` GROUP BY cluster_id "
                f"ORDER BY size DESC LIMIT 5"
            ),
            "Review the largest cluster's match pairs to identify "
            "false positives",
            "Consider raising the matching threshold or adding hard "
            "negatives",
        ),
    )
