"""High-level Pipeline API: the recommended entry point.

Combines DAG construction, validation, planning, and execution
into a single fluent interface. This replaces the old orchestrator
as the primary way to build and run entity resolution pipelines.

Usage:
    from bq_entity_resolution.pipeline.pipeline import Pipeline

    # Build from config
    pipeline = Pipeline(config)

    # Validate before running
    violations = pipeline.validate()
    if violations:
        for v in violations:
            print(f"  {v.stage_name}: {v.message}")

    # Generate execution plan
    plan = pipeline.plan(full_refresh=True)
    print(plan.preview())

    # Execute against a backend
    result = pipeline.execute(plan, backend=my_backend)

    # Or use quick_config for minimal setup
    from bq_entity_resolution.config.presets import quick_config
    config = quick_config(
        bq_project="my-project",
        source_table="my-project.raw.customers",
        columns=["first_name", "last_name", "email"],
    )
    pipeline = Pipeline(config)
    result = pipeline.run(backend=my_backend, full_refresh=True)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bq_entity_resolution.backends.protocol import Backend
from bq_entity_resolution.config.schema import PipelineConfig
from bq_entity_resolution.exceptions import LockFencingError, WatermarkError
from bq_entity_resolution.monitoring.metrics import MetricsCollector
from bq_entity_resolution.pipeline.dag import StageDAG, build_pipeline_dag
from bq_entity_resolution.pipeline.executor import (
    CheckpointManagerProtocol,
    PipelineExecutor,
    PipelineResult,
    ProgressCallback,
)
from bq_entity_resolution.pipeline.gates import DataQualityGate, default_gates
from bq_entity_resolution.pipeline.health import HealthProbe
from bq_entity_resolution.pipeline.plan import PipelinePlan, create_plan
from bq_entity_resolution.pipeline.shutdown import GracefulShutdown
from bq_entity_resolution.pipeline.validator import (
    ContractViolation,
    validate_dag_contracts,
    validate_stage_configs,
)
from bq_entity_resolution.stages.base import Stage

logger = logging.getLogger(__name__)

DagBuilder = Callable[[PipelineConfig], StageDAG]


@dataclass(frozen=True)
class CostEstimate:
    """Pre-execution cost estimate from BigQuery dry-run API."""

    total_bytes_processed: int = 0
    per_stage: dict[str, int] = field(default_factory=dict)

    @property
    def total_gb(self) -> float:
        return self.total_bytes_processed / (1024 ** 3)

    @property
    def estimated_cost_usd(self) -> float:
        """Estimated on-demand cost at $6.25 per TiB processed."""
        return self.total_bytes_processed / (1024 ** 4) * 6.25


class Pipeline:
    """High-level API for entity resolution pipelines.

    This is the recommended entry point. It provides:
    1. Compile-time validation (before any SQL runs)
    2. Plan preview (see all SQL before executing)
    3. Backend-agnostic execution (BigQuery or DuckDB)
    4. Quality gates (runtime assertions after each stage)
    5. Checkpoint/resume for crash recovery
    6. Progress callbacks for UI integration

    Extensibility:
    - **stage_overrides**: Replace built-in stages by name with custom
      implementations. E.g., ``{"clustering": MyClusteringStage(config)}``.
    - **exclude_stages**: Remove built-in stages by name.
      E.g., ``{"cluster_quality"}``.
    - **dag_builder**: Replace the entire DAG construction function.
      Receives a PipelineConfig and must return a StageDAG.
    - **Pipeline.from_stages()**: Build a pipeline from a custom list
      of Stage objects or a pre-built StageDAG.
    """

    def __init__(
        self,
        config: PipelineConfig,
        quality_gates: list[DataQualityGate] | None = None,
        dag_builder: DagBuilder | None = None,
        stage_overrides: dict[str, Stage] | None = None,
        exclude_stages: set[str] | None = None,
    ):
        self._config = config
        if dag_builder:
            self._dag = dag_builder(config)
        else:
            # Merge YAML-level skip_stages with Python API exclude_stages
            effective_excludes = set(exclude_stages or set())
            if config.execution.skip_stages:
                effective_excludes |= set(config.execution.skip_stages)
            self._dag = build_pipeline_dag(
                config,
                stage_overrides=stage_overrides,
                exclude_stages=effective_excludes or None,
            )
        self._gates = (
            quality_gates
            if quality_gates is not None
            else default_gates(config)
        )

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def dag(self) -> StageDAG:
        """The pipeline's stage DAG."""
        return self._dag

    @property
    def stage_names(self) -> list[str]:
        """Stage names in execution order."""
        return self._dag.stage_names

    @classmethod
    def from_stages(
        cls,
        config: PipelineConfig,
        stages: list[Stage] | None = None,
        dag: StageDAG | None = None,
        explicit_edges: dict[str, list[str]] | None = None,
        quality_gates: list[DataQualityGate] | None = None,
    ) -> Pipeline:
        """Create a Pipeline from custom stages or a pre-built DAG.

        Use this when you need full control over the stage graph —
        injecting custom stages, reordering, or replacing the entire
        pipeline structure.

        Provide EITHER ``stages`` (will be assembled into a DAG) or
        ``dag`` (used as-is). If both are given, ``dag`` takes precedence.

        Args:
            config: Pipeline configuration.
            stages: List of Stage objects to assemble into a DAG.
            dag: Pre-built StageDAG (takes precedence over ``stages``).
            explicit_edges: Extra dependency edges when using ``stages``.
                Maps stage name to list of dependency stage names.
            quality_gates: Optional custom quality gates.

        Example::

            from bq_entity_resolution import (
                Pipeline, Stage, StageDAG, build_pipeline_dag,
            )

            # Option A: Modify the default DAG
            default_dag = build_pipeline_dag(config)
            stages = list(default_dag.stages)
            stages.append(MyCustomEnrichmentStage(config))
            pipeline = Pipeline.from_stages(
                config,
                stages=stages,
                explicit_edges={"my_enrichment": ["feature_engineering"]},
            )

            # Option B: Provide a fully custom DAG
            dag = StageDAG.from_stages(my_stages, my_edges)
            pipeline = Pipeline.from_stages(config, dag=dag)
        """
        inst = object.__new__(cls)
        inst._config = config
        if dag is not None:
            inst._dag = dag
        elif stages is not None:
            inst._dag = StageDAG.from_stages(stages, explicit_edges)
        else:
            raise ValueError("Provide either 'stages' or 'dag'")
        inst._gates = (
            quality_gates
            if quality_gates is not None
            else default_gates(config)
        )
        return inst

    def validate(self) -> list[ContractViolation]:
        """Run compile-time validation.

        Checks:
        1. All stage inputs are produced by upstream stages
        2. Stage-specific config validation (missing keys, etc.)

        Returns a list of violations. Empty = valid.
        """
        violations = validate_dag_contracts(
            self._dag,
            external_tables=self._external_tables(),
        )
        violations.extend(validate_stage_configs(self._dag))
        return violations

    def plan(self, **kwargs: Any) -> PipelinePlan:
        """Generate an immutable execution plan.

        The plan contains all SQL to execute, in order, without
        actually running anything. Use plan.preview() to inspect.

        Common kwargs:
            full_refresh: bool — ignore watermarks, reprocess everything
            watermark: dict — per-source watermark values
        """
        return create_plan(self._dag, **kwargs)

    def estimate_cost(
        self,
        backend: Backend,
        **plan_kwargs: Any,
    ) -> CostEstimate:
        """Estimate execution cost via BigQuery dry-run API.

        Generates the full plan and runs each SQL statement in dry-run
        mode to estimate total bytes processed. No data is read or written.

        Returns a CostEstimate with total bytes, per-stage breakdown,
        and approximate USD cost. Returns zero estimates for backends
        that don't support dry-run (e.g. DuckDB).

        Example::

            estimate = pipeline.estimate_cost(backend=my_backend, full_refresh=True)
            print(f"Estimated cost: ${estimate.estimated_cost_usd:.2f}")
            print(f"Total bytes: {estimate.total_gb:.1f} GB")
            if estimate.estimated_cost_usd < 10.0:
                pipeline.run(backend=my_backend, full_refresh=True)
        """
        plan = self.plan(**plan_kwargs)
        total = 0
        per_stage: dict[str, int] = {}
        for stage_plan in plan.stages:
            stage_bytes = 0
            for expr in stage_plan.sql_expressions:
                stage_bytes += backend.estimate_bytes(
                    expr.render(), label=stage_plan.stage_name
                )
            per_stage[stage_plan.stage_name] = stage_bytes
            total += stage_bytes
        return CostEstimate(total_bytes_processed=total, per_stage=per_stage)

    def execute(
        self,
        plan: PipelinePlan,
        backend: Backend,
        run_id: str | None = None,
        skip_stages: set[str] | None = None,
        checkpoint_manager: CheckpointManagerProtocol | None = None,
        resume: bool = False,
        on_progress: ProgressCallback | None = None,
        max_cost_bytes: int | None = None,
        health_probe: HealthProbe | None = None,
        fencing_kwargs: dict[str, Any] | None = None,
    ) -> PipelineResult:
        """Execute a pre-generated plan against a backend.

        Args:
            plan: The immutable plan from self.plan().
            backend: Execution backend (BigQuery or DuckDB).
            run_id: Optional run identifier.
            skip_stages: Stage names to skip (checkpoint/resume).
            checkpoint_manager: Optional checkpoint manager for crash recovery.
            resume: If True, auto-detect resumable run from checkpoint.
            on_progress: Optional callback for progress reporting.
            max_cost_bytes: Pipeline-level cost ceiling (total bytes billed).
            health_probe: Optional health probe for K8s liveness updates.
            fencing_kwargs: Optional fencing params for checkpoint writes.
        """
        # Job tracking config
        jt = getattr(self._config.monitoring, "job_tracking", None)
        jt_enabled = bool(jt and getattr(jt, "enabled", False))
        jt_table: str | None = None
        if jt_enabled:
            from bq_entity_resolution.naming import job_tracking_table
            jt_table = job_tracking_table(self._config)

        # Cost budget guards from job tracking config
        cost_alert = getattr(jt, "cost_alert_threshold_bytes", None) if jt else None
        cost_abort = getattr(jt, "cost_abort_threshold_bytes", None) if jt else None

        executor = PipelineExecutor(
            backend=backend,
            quality_gates=self._gates,
            checkpoint_manager=checkpoint_manager,
            on_progress=on_progress,
            max_cost_bytes=max_cost_bytes,
            health_probe=health_probe,
            fencing_kwargs=fencing_kwargs,
            job_tracking_table=jt_table,
            job_tracking_enabled=jt_enabled,
            cost_alert_threshold_bytes=cost_alert,
            cost_abort_threshold_bytes=cost_abort,
        )
        return executor.execute(
            plan,
            run_id=run_id,
            skip_stages=skip_stages,
            resume=resume,
        )

    def run(
        self,
        backend: Backend,
        full_refresh: bool = False,
        drain: bool = False,
        dry_run: bool = False,
        run_id: str | None = None,
        skip_stages: set[str] | None = None,
        checkpoint_manager: CheckpointManagerProtocol | None = None,
        resume: bool = False,
        on_progress: ProgressCallback | None = None,
        watermark_manager: Any | None = None,
        **plan_kwargs: Any,
    ) -> PipelineResult | CostEstimate:
        """Convenience: validate, plan, and execute in one call.

        Args:
            backend: Execution backend.
            full_refresh: Ignore watermarks.
            drain: If True, auto-loop through batches until all
                unprocessed records are consumed. Each iteration
                advances the watermark and processes the next batch.
            dry_run: If True, estimate cost via BigQuery dry-run API
                without executing. Returns a CostEstimate instead
                of PipelineResult.
            run_id: Optional run identifier.
            skip_stages: Stages to skip.
            checkpoint_manager: Optional checkpoint persistence.
            resume: Auto-resume from last incomplete run.
            on_progress: Optional progress callback.
            watermark_manager: Optional WatermarkManager instance for
                reading/advancing watermarks. When not provided,
                watermark kwargs are passed through to plan().
            **plan_kwargs: Additional kwargs for plan generation.
        """
        # --- Production infrastructure setup (early, so probes reflect failures) ---
        from bq_entity_resolution.config.models.infrastructure import DeploymentConfig
        deploy = getattr(self._config, "deployment", None) or DeploymentConfig()

        # Health probe (created early so validation failures are visible to K8s)
        health_probe: HealthProbe | None = None
        if deploy.health_probe.enabled:
            health_probe = HealthProbe(
                path=deploy.health_probe.path,
                enabled=True,
            )
            health_probe.mark_healthy(stage="init", run_id=run_id or "")

        # Validate first
        violations = self.validate()
        errors = [v for v in violations if v.severity == "error"]
        if errors:
            if health_probe:
                health_probe.mark_unhealthy()
            error_msgs = "; ".join(
                f"{v.stage_name}: {v.message}" for v in errors
            )
            raise ValueError(
                f"Pipeline validation failed: {error_msgs}"
            )

        warnings = [v for v in violations if v.severity == "warning"]
        for w in warnings:
            logger.warning(
                "Validation warning for '%s': %s",
                w.stage_name,
                w.message,
            )

        # Dry-run: estimate cost without executing
        if dry_run:
            return self.estimate_cost(
                backend=backend,
                full_refresh=full_refresh,
                **plan_kwargs,
            )

        # Graceful shutdown handler
        shutdown = GracefulShutdown(enabled=deploy.graceful_shutdown.enabled)
        if deploy.graceful_shutdown.enabled and hasattr(backend, "bq_client"):
            shutdown.register_client(backend.bq_client)
        if health_probe:
            shutdown.register_health_probe(health_probe)

        # Distributed lock
        pipeline_lock = None
        lock_table: str | None = None
        pipeline_name = getattr(getattr(self._config, "project", None), "name", "default")
        if deploy.distributed_lock.enabled and hasattr(backend, "bq_client"):
            from bq_entity_resolution.pipeline.lock import PipelineLock
            project = self._config.project
            lock_table = (
                f"{project.bq_project}."
                f"{project.watermark_dataset}."
                f"{deploy.distributed_lock.lock_table}"
            )
            pipeline_lock = PipelineLock(
                bq_client=backend.bq_client,
                lock_table=lock_table,
                ttl_minutes=deploy.distributed_lock.ttl_minutes,
                retry_seconds=deploy.distributed_lock.retry_seconds,
                max_wait_seconds=deploy.distributed_lock.max_wait_seconds,
            )
            shutdown.register_lock(pipeline_lock, pipeline_name)

        # Cost ceiling from config (opt-in, None by default)
        execution = getattr(self._config, "execution", None)
        max_cost_bytes = getattr(execution, "max_cost_bytes", None) if execution else None

        # Install shutdown handlers
        shutdown.install()

        pipeline_ran = False
        try:
            # Acquire distributed lock if configured
            if pipeline_lock:
                pipeline_lock.acquire(pipeline_name)

            result = self._run_loop(
                backend=backend,
                full_refresh=full_refresh,
                drain=drain,
                run_id=run_id,
                skip_stages=skip_stages,
                checkpoint_manager=checkpoint_manager,
                resume=resume,
                on_progress=on_progress,
                watermark_manager=watermark_manager,
                health_probe=health_probe,
                max_cost_bytes=max_cost_bytes,
                pipeline_lock=pipeline_lock,
                lock_table=lock_table,
                pipeline_name=pipeline_name,
                **plan_kwargs,
            )
            pipeline_ran = True
        finally:
            # Release lock
            if pipeline_lock:
                try:
                    pipeline_lock.release(pipeline_name)
                except Exception:
                    logger.error(
                        "Failed to release pipeline lock for '%s'. "
                        "Lock will expire after TTL, but concurrent runs "
                        "may be blocked until then.",
                        pipeline_name, exc_info=True,
                    )

            # Uninstall shutdown handlers
            shutdown.uninstall()

            # Health probe: mark success if pipeline ran, else signal unhealthy
            if health_probe:
                if pipeline_ran:
                    health_probe.mark_healthy(stage="complete", run_id=run_id or "")
                else:
                    health_probe.mark_unhealthy()

        return result

    def _run_loop(
        self,
        backend: Backend,
        full_refresh: bool,
        drain: bool,
        run_id: str | None,
        skip_stages: set[str] | None,
        checkpoint_manager: CheckpointManagerProtocol | None,
        resume: bool,
        on_progress: ProgressCallback | None,
        watermark_manager: Any | None,
        health_probe: HealthProbe | None,
        max_cost_bytes: int | None,
        pipeline_lock: Any | None,
        lock_table: str | None = None,
        pipeline_name: str | None = None,
        **plan_kwargs: Any,
    ) -> PipelineResult:
        """Core execution loop, separated from infrastructure setup."""
        # Build fencing kwargs for checkpoint writes
        fencing_kwargs: dict[str, Any] = {}
        if (
            pipeline_lock
            and pipeline_lock.fencing_token is not None
            and lock_table
            and pipeline_name
        ):
            fencing_kwargs = {
                "fencing_token": pipeline_lock.fencing_token,
                "lock_table": lock_table,
                "pipeline_name": pipeline_name,
            }

        # Check drain mode from config if not explicitly passed
        inc = self._config.incremental
        if not drain and inc and inc.drain_mode:
            drain = True
        max_iterations = inc.drain_max_iterations if inc else 100

        # Read initial watermarks if manager is provided (per-source)
        watermark = plan_kwargs.pop("watermark", None)
        watermarks: dict[str, dict[str, Any]] = {}
        if watermark_manager and not full_refresh and not watermark:
            for source in self._config.sources:
                wm = watermark_manager.read(source.name)
                if wm:
                    watermarks[source.name] = wm
            # Use first source's watermark for backward compatibility
            if watermarks:
                watermark = next(iter(watermarks.values()))

        iteration = 0
        result: PipelineResult | None = None
        consecutive_empty = 0

        while True:
            # Plan
            plan = self.plan(
                full_refresh=full_refresh,
                watermark=watermark,
                **plan_kwargs,
            )
            logger.info(
                "Pipeline plan (iteration %d): %d stages, %d SQL statements",
                iteration,
                len(plan.stages),
                plan.total_sql_count,
            )

            # Execute
            result = self.execute(
                plan,
                backend=backend,
                run_id=f"{run_id}_iter{iteration}" if run_id and drain else run_id,
                skip_stages=skip_stages,
                checkpoint_manager=checkpoint_manager,
                resume=resume if iteration == 0 else False,
                on_progress=on_progress,
                max_cost_bytes=max_cost_bytes,
                health_probe=health_probe,
                fencing_kwargs=fencing_kwargs or None,
            )

            # Record metrics if monitoring is configured
            try:
                monitoring = self._config.monitoring
                metrics_cfg = monitoring.metrics if monitoring else None
                if metrics_cfg and metrics_cfg.enabled:
                    collector = MetricsCollector(self._config)
                    collector.set_backend(backend)
                    collector.record_run(result)
            except Exception:
                logger.warning("Failed to record metrics", exc_info=True)

            # Refresh distributed lock heartbeat after each iteration.
            # Failure to refresh means the lock may expire and another pod
            # could acquire it — abort to prevent concurrent execution.
            if pipeline_lock:
                try:
                    pipeline_lock.refresh(self._config.project.name)
                except Exception:
                    logger.error(
                        "Failed to refresh pipeline lock — aborting to prevent "
                        "concurrent execution. Lock may have expired.",
                        exc_info=True,
                    )
                    raise RuntimeError(
                        "Pipeline lock refresh failed. Aborting to prevent "
                        "concurrent runs. Check BigQuery connectivity and "
                        "lock table permissions."
                    )

            # Advance watermark after successful execution (all sources)
            batch_had_rows = False
            if watermark_manager and not full_refresh and result.success:
                cursor_cols = inc.cursor_columns if inc else ["updated_at"]
                for source in self._config.sources:
                    try:
                        from bq_entity_resolution.naming import staged_table
                        staged = staged_table(self._config, source.name)
                        new_wm = watermark_manager.compute_new_watermark_from_staged(
                            staged_table=staged,
                            cursor_columns=cursor_cols,
                            column_mapping={"updated_at": "source_updated_at"},
                        )
                        if new_wm:
                            batch_had_rows = True
                            # Wire fencing token for lock-protected writes
                            wm_kwargs: dict[str, Any] = {
                                "run_id": run_id or "",
                            }
                            if (
                                pipeline_lock
                                and pipeline_lock.fencing_token is not None
                                and lock_table
                                and pipeline_name
                            ):
                                wm_kwargs["fencing_token"] = pipeline_lock.fencing_token
                                wm_kwargs["lock_table"] = lock_table
                                wm_kwargs["pipeline_name"] = pipeline_name
                            watermark_manager.write(
                                source.name,
                                new_wm,
                                **wm_kwargs,
                            )
                            watermarks[source.name] = new_wm
                            logger.info(
                                "Watermark advanced for '%s': %s",
                                source.name, new_wm,
                            )
                    except (WatermarkError, LockFencingError):
                        raise  # Watermark/fencing failures are critical — propagate
                    except Exception:
                        if drain:
                            # In drain mode, non-transient errors must propagate
                            # to prevent infinite loops re-processing same batch
                            logger.error(
                                "Failed to advance watermark for '%s' in drain "
                                "mode — aborting to prevent infinite loop",
                                source.name, exc_info=True,
                            )
                            raise
                        logger.error(
                            "Failed to advance watermark for '%s'. "
                            "Next run will reprocess this batch.",
                            source.name, exc_info=True,
                        )
                # Update watermark for plan generation
                if watermarks:
                    watermark = next(iter(watermarks.values()))

            # Track consecutive empty batches in drain mode
            if drain:
                if not batch_had_rows:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        logger.info(
                            "Two consecutive empty batches in drain mode — stopping"
                        )
                        break
                else:
                    consecutive_empty = 0

            # Drain mode: continue if there might be more records
            if not drain:
                break

            iteration += 1
            if iteration >= max_iterations:
                logger.warning(
                    "Drain mode: reached max iterations (%d), stopping",
                    max_iterations,
                )
                break

            # Check if there are more records to process (any source)
            if watermark_manager and watermarks:
                cursor_cols = inc.cursor_columns if inc else ["updated_at"]
                has_any_more = False
                for source in self._config.sources:
                    src_wm = watermarks.get(source.name)
                    if not src_wm:
                        continue
                    try:
                        has_more = watermark_manager.has_unprocessed_records(
                            source_table=source.table,
                            cursor_columns=cursor_cols,
                            current_watermark=src_wm,
                            cursor_mode=inc.cursor_mode if inc else "ordered",
                            grace_period_hours=inc.grace_period_hours if inc else 0,
                        )
                        if has_more:
                            has_any_more = True
                            break
                    except Exception:
                        # In drain mode, treat check failure as "has more"
                        # to avoid silently missing records
                        logger.warning(
                            "Failed to check unprocessed records for '%s'; "
                            "assuming more records exist",
                            source.name, exc_info=True,
                        )
                        has_any_more = True
                        break
                if not has_any_more:
                    logger.info(
                        "Drain mode: no more unprocessed records after "
                        "%d iterations", iteration
                    )
                    break
            else:
                # No watermark manager — can't determine if more records exist
                logger.info(
                    "Drain mode: no watermark manager, running single iteration"
                )
                break

        if result is None:
            raise RuntimeError(
                "Pipeline.run() completed without producing a result. "
                "This indicates a bug in the execution loop."
            )
        return result

    @classmethod
    def from_table(
        cls,
        table: str,
        backend: Backend,
        bq_project: str | None = None,
        unique_key: str = "id",
        updated_at: str = "updated_at",
        column_roles: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Pipeline:
        """Create a Pipeline directly from a BigQuery table reference.

        The ultimate minimal setup: auto-discovers columns, detects roles,
        generates features, blocking keys, comparisons, and tiers.

        Args:
            table: Fully-qualified BigQuery table (project.dataset.table).
            backend: Backend for schema introspection.
            bq_project: GCP project (auto-detected from table if not set).
            unique_key: Primary key column.
            updated_at: Timestamp column.
            column_roles: Explicit role overrides {column_name: role}.
            **kwargs: Additional Pipeline constructor kwargs.

        Example:
            from bq_entity_resolution import Pipeline
            from bq_entity_resolution.backends.bigquery import BigQueryBackend

            backend = BigQueryBackend(project="my-project")
            pipeline = Pipeline.from_table(
                "my-project.raw.customers",
                backend=backend,
            )
            result = pipeline.run(backend=backend)
        """
        from bq_entity_resolution.config.presets import quick_config
        from bq_entity_resolution.config.schema import SourceConfig

        # Discover columns from live table
        source = SourceConfig.from_table(
            table=table,
            backend=backend,
            unique_key=unique_key,
            updated_at=updated_at,
        )

        # Build role map from discovered columns
        role_map: dict[str, str] = {}
        if column_roles:
            role_map.update(column_roles)
        for col in source.columns:
            if col.name not in role_map and col.role:
                role_map[col.name] = col.role

        # Derive project from table
        if not bq_project:
            parts = table.split(".")
            bq_project = parts[0] if len(parts) >= 3 else "default-project"

        config = quick_config(
            bq_project=bq_project,
            source_table=table,
            unique_key=unique_key,
            updated_at=updated_at,
            column_roles=role_map if role_map else None,
            columns=[c.name for c in source.columns] if not role_map else None,
        )

        return cls(config, **kwargs)

    def _external_tables(self) -> set[str]:
        """Collect external table names from config sources."""
        return {source.table for source in self._config.sources}
