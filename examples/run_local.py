#!/usr/bin/env python3
"""Run entity resolution datasets locally using DuckDB.

Usage:
    python examples/run_local.py                    # Run all datasets
    python examples/run_local.py fuzzy_persons      # Run one dataset
    python examples/run_local.py --list              # List available datasets
"""

from __future__ import annotations

import csv
import logging
import os
import sys
import time
from pathlib import Path

# Add project to path if needed
project_root = Path(__file__).resolve().parent.parent
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))

from bq_entity_resolution import Pipeline, load_config
from bq_entity_resolution.backends.duckdb import DuckDBBackend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_local")

DATASETS_DIR = Path(__file__).parent / "datasets"
CONFIGS_DIR = Path(__file__).parent / "configs"


def discover_datasets() -> list[str]:
    """Find all available datasets (YAML configs in configs/)."""
    datasets = []
    for yml in sorted(CONFIGS_DIR.glob("*.yml")):
        datasets.append(yml.stem)
    return datasets


def load_csv_data(csv_path: Path) -> list[dict]:
    """Load CSV into list of dicts, handling empty strings as NULL."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                cleaned[k] = v if v != "" else None
            rows.append(cleaned)
        return rows


def setup_source_table(
    backend: DuckDBBackend, table_name: str, data: list[dict],
) -> int:
    """Create and populate a source table in DuckDB."""
    if not data:
        logger.warning("No data for table %s", table_name)
        return 0

    columns = list(data[0].keys())

    # Infer types: if a column ends with _at or is named updated_at/created_at,
    # make it TIMESTAMP; otherwise VARCHAR
    col_defs = []
    for col in columns:
        if col in ("updated_at", "created_at", "modified_date", "last_updated"):
            col_defs.append(f'"{col}" TIMESTAMP')
        elif col.endswith("_at") or col.endswith("_date"):
            col_defs.append(f'"{col}" TIMESTAMP')
        else:
            col_defs.append(f'"{col}" VARCHAR')

    ddl = f"CREATE OR REPLACE TABLE {table_name} ({', '.join(col_defs)})"
    backend.execute(ddl)

    # Insert rows
    for row in data:
        values = []
        for col in columns:
            v = row.get(col)
            if v is None:
                values.append("NULL")
            elif col in ("updated_at", "created_at", "modified_date", "last_updated") \
                    or col.endswith("_at") or col.endswith("_date"):
                values.append(f"TIMESTAMP '{v}'")
            else:
                escaped = str(v).replace("'", "''")
                values.append(f"'{escaped}'")
        insert = f"INSERT INTO {table_name} VALUES ({', '.join(values)})"
        backend.execute(insert)

    return len(data)


def run_dataset(name: str, verbose: bool = True) -> dict:
    """Run a single dataset end-to-end and return results."""
    config_path = CONFIGS_DIR / f"{name}.yml"
    if not config_path.exists():
        logger.error("Config not found: %s", config_path)
        return {"name": name, "success": False, "error": "Config not found"}

    logger.info("=" * 70)
    logger.info("DATASET: %s", name)
    logger.info("=" * 70)

    # Load config
    os.environ.setdefault("BQ_PROJECT", "local-test")
    config = load_config(str(config_path), validate=False)

    # Create DuckDB backend
    with DuckDBBackend(":memory:") as backend:
        # Load source data into DuckDB tables
        for source in config.sources:
            # Table name is the last part of the fully-qualified name
            table_local = source.table.split(".")[-1]
            csv_path = DATASETS_DIR / f"{table_local}.csv"

            if not csv_path.exists():
                # Try dataset name as fallback
                csv_path = DATASETS_DIR / f"{name}.csv"

            if not csv_path.exists():
                logger.error("CSV not found: %s", csv_path)
                return {
                    "name": name, "success": False,
                    "error": f"CSV not found for source '{source.name}'",
                }

            data = load_csv_data(csv_path)
            n = setup_source_table(backend, table_local, data)
            logger.info("Loaded %d rows into '%s' from %s", n, table_local, csv_path.name)

        # Build and run pipeline
        pipeline = Pipeline(config)

        # Validate
        violations = pipeline.validate()
        errors = [v for v in violations if v.severity == "error"]
        if errors:
            for e in errors:
                logger.error("Validation error [%s]: %s", e.stage_name, e.message)
            return {"name": name, "success": False, "error": "Validation failed"}

        warnings = [v for v in violations if v.severity == "warning"]
        for w in warnings:
            logger.warning("Validation warning [%s]: %s", w.stage_name, w.message)

        # Run
        start = time.monotonic()

        def on_progress(stage_name, idx, total, status):
            logger.info("  [%d/%d] %s: %s", idx + 1, total, stage_name, status)

        try:
            result = pipeline.run(
                backend=backend,
                full_refresh=True,
                on_progress=on_progress,
            )
            elapsed = time.monotonic() - start
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error("Pipeline failed after %.1fs: %s", elapsed, e)
            return {"name": name, "success": False, "error": str(e), "time": elapsed}

        # Report results
        logger.info("-" * 40)
        logger.info("Result: %s in %.1fs", "SUCCESS" if result.success else "FAILED", elapsed)
        logger.info("Completed stages: %d", len(result.completed_stages))

        if result.error:
            logger.error("Error: %s", result.error)

        # Query output tables for summary
        summary = {"name": name, "success": result.success, "time": elapsed}

        try:
            # Count matched pairs
            matches = backend.execute_and_fetch(
                "SELECT COUNT(*) as cnt FROM all_matched_pairs"
            )
            match_count = matches[0]["cnt"] if matches else 0
            summary["match_pairs"] = match_count
            logger.info("Match pairs found: %d", match_count)
        except Exception:
            pass

        try:
            # Count clusters
            clusters = backend.execute_and_fetch(
                "SELECT COUNT(DISTINCT cluster_id) as cnt FROM entity_clusters"
            )
            cluster_count = clusters[0]["cnt"] if clusters else 0
            summary["clusters"] = cluster_count
            logger.info("Clusters formed: %d", cluster_count)
        except Exception:
            pass

        try:
            # Count resolved entities
            resolved = backend.execute_and_fetch(
                "SELECT COUNT(*) as cnt FROM resolved_entities"
            )
            resolved_count = resolved[0]["cnt"] if resolved else 0
            summary["resolved_entities"] = resolved_count
            logger.info("Resolved entities: %d", resolved_count)
        except Exception:
            pass

        try:
            # Show sample matches
            if verbose:
                sample = backend.execute_and_fetch("""
                    SELECT left_entity_uid, right_entity_uid,
                           match_score, tier_name
                    FROM all_matched_pairs
                    ORDER BY match_score DESC
                    LIMIT 10
                """)
                if sample:
                    logger.info("Top matches:")
                    for m in sample:
                        logger.info(
                            "  %s <-> %s  score=%.2f  tier=%s",
                            m["left_entity_uid"], m["right_entity_uid"],
                            m["match_score"], m["tier_name"],
                        )
        except Exception:
            pass

        logger.info("")
        return summary


def main():
    args = sys.argv[1:]

    if "--list" in args:
        datasets = discover_datasets()
        print(f"Available datasets ({len(datasets)}):")
        for d in datasets:
            print(f"  - {d}")
        return

    if args and args[0] != "--verbose":
        # Run specific dataset(s)
        names = [a for a in args if not a.startswith("--")]
        verbose = "--verbose" in args
    else:
        # Run all
        names = discover_datasets()
        verbose = "--verbose" in args or not args

    if not names:
        print("No datasets found. Create YAML configs in examples/configs/")
        return

    results = []
    for name in names:
        r = run_dataset(name, verbose=verbose)
        results.append(r)

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Dataset':<30} {'Status':<10} {'Time':>6} {'Pairs':>7} {'Clusters':>9}")
    print("-" * 70)
    for r in results:
        status = "PASS" if r.get("success") else "FAIL"
        time_s = f"{r.get('time', 0):.1f}s" if "time" in r else "N/A"
        pairs = str(r.get("match_pairs", "N/A"))
        clusters = str(r.get("clusters", "N/A"))
        print(f"{r['name']:<30} {status:<10} {time_s:>6} {pairs:>7} {clusters:>9}")

    print("-" * 70)
    total = len(results)
    passed = sum(1 for r in results if r.get("success"))
    print(f"Total: {passed}/{total} passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
