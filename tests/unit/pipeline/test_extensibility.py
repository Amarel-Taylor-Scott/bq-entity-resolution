"""Tests for pipeline extensibility APIs.

Validates that users can:
1. Register custom feature/comparison functions at runtime
2. Replace built-in stages via stage_overrides
3. Exclude stages from the DAG
4. Build pipelines from custom stage lists via Pipeline.from_stages()
5. Access all extensibility APIs from the top-level package
"""

from __future__ import annotations

import pytest

from bq_entity_resolution.pipeline.dag import StageDAG, build_pipeline_dag
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

# -- Dummy stages for testing --


class CustomStage(Stage):
    """Custom stage for extensibility testing."""

    def __init__(self, stage_name: str, inputs=None, outputs=None):
        self._name = stage_name
        self._inputs = inputs or {}
        self._outputs = outputs or {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def inputs(self) -> dict[str, TableRef]:
        return self._inputs

    @property
    def outputs(self) -> dict[str, TableRef]:
        return self._outputs

    def plan(self, **kwargs) -> list[SQLExpression]:
        return [SQLExpression.from_raw(f"SELECT 1 -- custom:{self._name}")]


# -- Helper to build a minimal config namespace --


def _make_config():
    class NS:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    project = NS(
        bq_project="test-proj",
        bq_dataset_bronze="test-proj.bronze",
        bq_dataset_silver="test-proj.silver",
        bq_dataset_gold="test-proj.gold",
        bq_location="US",
        udf_dataset="test-proj.udfs",
        watermark_dataset="meta",
    )

    col1 = NS(name="first_name")
    source = NS(
        name="crm",
        table="test-proj.raw.customers",
        unique_key="customer_id",
        updated_at="updated_at",
        columns=[col1],
        passthrough_columns=[],
        joins=[],
        filter=None,
        partition_column=None,
        batch_size=None,
    )

    feat1 = NS(
        name="name_clean",
        function="name_clean",
        inputs=["first_name"],
        params=None,
    )
    feat_group = NS(features=[feat1])
    bk1 = NS(
        name="bk_soundex",
        function="soundex",
        inputs=["last_name"],
        params=None,
    )
    ck1 = NS(name="bk_name", expression="UPPER(first_name)")
    features_config = NS(
        groups=[feat_group],
        blocking_keys=[bk1],
        composite_keys=[ck1],
    )

    blocking_path = NS(keys=["bk_soundex"], lsh_keys=[], candidate_limit=0)
    blocking_config = NS(paths=[blocking_path], cross_batch=False)

    comp1 = NS(
        name="name_exact",
        method="exact",
        left="first_name",
        right="first_name",
        weight=2.0,
        params=None,
        tf_enabled=False,
        tf_column="",
        tf_minimum_u=0.01,
        levels=[],
    )
    threshold = NS(
        method="score",
        min_score=1.0,
        match_threshold=None,
        log_prior_odds=0.0,
        min_matching_comparisons=0,
    )
    al = NS(enabled=False, queue_size=100, uncertainty_window=0.3)
    tier = NS(
        name="exact",
        blocking=blocking_config,
        comparisons=[comp1],
        threshold=threshold,
        hard_negatives=[],
        soft_signals=[],
        active_learning=al,
        confidence=None,
    )

    incremental = NS(
        grace_period_hours=6,
        cursor_columns=["updated_at"],
    )
    canonical_selection = NS(method="completeness", source_priority=[])
    clustering = NS(max_iterations=20)
    reconciliation = NS(
        canonical_selection=canonical_selection,
        clustering=clustering,
    )
    output = NS(
        include_match_metadata=True,
        entity_id_prefix="ent",
        partition_column=None,
        cluster_columns=[],
    )
    monitoring = NS(
        audit_trail_enabled=False,
        blocking_metrics=NS(enabled=False),
        cluster_quality=NS(
            enabled=False,
            alert_max_cluster_size=100,
            abort_on_explosion=False,
        ),
        persist_sql_log=False,
    )
    scale = NS(checkpoint_enabled=False, max_bytes_billed=None)
    embeddings = NS(enabled=False)
    execution = NS(skip_stages=[])

    config = NS(
        project=project,
        sources=[source],
        features=features_config,
        incremental=incremental,
        reconciliation=reconciliation,
        output=output,
        monitoring=monitoring,
        scale=scale,
        embeddings=embeddings,
        execution=execution,
        link_type=None,
    )

    def fq_table(dataset_attr, table_name):
        ds = getattr(project, dataset_attr, "test-proj.default")
        return f"{ds}.{table_name}"

    config.fq_table = fq_table
    config.enabled_tiers = lambda: [tier]
    return config


# -- Tests: stage_overrides --


class TestStageOverrides:
    def test_override_replaces_stage(self):
        """stage_overrides replaces a built-in stage by name."""
        config = _make_config()
        custom = CustomStage("clustering")
        dag = build_pipeline_dag(config, stage_overrides={"clustering": custom})
        stage = dag.get_stage("clustering")
        assert isinstance(stage, CustomStage)

    def test_override_preserves_other_stages(self):
        """stage_overrides only affects the targeted stage."""
        config = _make_config()
        custom = CustomStage("clustering")
        dag = build_pipeline_dag(config, stage_overrides={"clustering": custom})
        assert "staging_crm" in dag.stage_names
        assert "feature_engineering" in dag.stage_names
        assert "gold_output" in dag.stage_names

    def test_override_nonexistent_stage_is_ignored(self):
        """Overriding a nonexistent stage has no effect."""
        config = _make_config()
        custom = CustomStage("nonexistent")
        dag = build_pipeline_dag(
            config, stage_overrides={"nonexistent": custom}
        )
        assert "nonexistent" not in dag.stage_names


# -- Tests: exclude_stages --


class TestExcludeStages:
    def test_exclude_removes_stage(self):
        """exclude_stages removes a stage from the DAG."""
        config = _make_config()
        config.monitoring.cluster_quality.enabled = True
        dag = build_pipeline_dag(config, exclude_stages={"cluster_quality"})
        assert "cluster_quality" not in dag.stage_names

    def test_exclude_preserves_other_stages(self):
        """Excluding one stage doesn't affect others."""
        config = _make_config()
        config.monitoring.cluster_quality.enabled = True
        dag = build_pipeline_dag(config, exclude_stages={"cluster_quality"})
        assert "clustering" in dag.stage_names
        assert "gold_output" in dag.stage_names


# -- Tests: Pipeline.from_stages --


class TestPipelineFromStages:
    def test_from_stages_with_stage_list(self):
        """Pipeline.from_stages builds from a list of stages."""
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        config = _make_config()
        a = CustomStage(
            "step_a",
            outputs={"out": TableRef(name="t1", fq_name="p.d.t1")},
        )
        b = CustomStage(
            "step_b",
            inputs={"in": TableRef(name="t1", fq_name="p.d.t1")},
        )
        pipeline = Pipeline.from_stages(config, stages=[a, b])
        assert pipeline.stage_names == ["step_a", "step_b"]

    def test_from_stages_with_explicit_edges(self):
        """Pipeline.from_stages respects explicit edges."""
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        config = _make_config()
        a = CustomStage("alpha")
        b = CustomStage("beta")
        pipeline = Pipeline.from_stages(
            config,
            stages=[a, b],
            explicit_edges={"beta": ["alpha"]},
        )
        assert pipeline.stage_names == ["alpha", "beta"]

    def test_from_stages_with_prebuilt_dag(self):
        """Pipeline.from_stages accepts a pre-built StageDAG."""
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        config = _make_config()
        a = CustomStage("only")
        dag = StageDAG.from_stages([a])
        pipeline = Pipeline.from_stages(config, dag=dag)
        assert pipeline.stage_names == ["only"]

    def test_from_stages_requires_stages_or_dag(self):
        """Pipeline.from_stages raises if neither stages nor dag."""
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        config = _make_config()
        with pytest.raises(ValueError, match="Provide either"):
            Pipeline.from_stages(config)

    def test_from_stages_dag_takes_precedence(self):
        """When both stages and dag provided, dag wins."""
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        config = _make_config()
        a = CustomStage("from_list")
        b = CustomStage("from_dag")
        dag = StageDAG.from_stages([b])
        pipeline = Pipeline.from_stages(config, stages=[a], dag=dag)
        assert pipeline.stage_names == ["from_dag"]


# -- Tests: Pipeline constructor extensibility --


class TestPipelineExtensibility:
    def test_pipeline_accepts_stage_overrides(self):
        """Pipeline constructor forwards stage_overrides to DAG builder."""
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        config = _make_config()
        custom = CustomStage("clustering")
        pipeline = Pipeline(config, stage_overrides={"clustering": custom})
        stage = pipeline.dag.get_stage("clustering")
        assert isinstance(stage, CustomStage)

    def test_pipeline_accepts_exclude_stages(self):
        """Pipeline constructor forwards exclude_stages to DAG builder."""
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        config = _make_config()
        config.monitoring.cluster_quality.enabled = True
        pipeline = Pipeline(config, exclude_stages={"cluster_quality"})
        assert "cluster_quality" not in pipeline.stage_names

    def test_pipeline_accepts_dag_builder(self):
        """Pipeline constructor uses a custom dag_builder function."""
        from bq_entity_resolution.pipeline.pipeline import Pipeline

        config = _make_config()
        custom = CustomStage("custom_only")

        def my_builder(cfg):
            return StageDAG.from_stages([custom])

        pipeline = Pipeline(config, dag_builder=my_builder)
        assert pipeline.stage_names == ["custom_only"]


# -- Tests: runtime registry extensions --


class TestRuntimeRegistration:
    def test_register_custom_feature(self):
        """External code can register custom feature functions."""
        from bq_entity_resolution.features.registry import (
            FEATURE_FUNCTIONS,
            register,
        )

        @register("test_custom_feat_001")
        def test_custom_feat_001(inputs, **_):
            return f"CUSTOM({inputs[0]})"

        assert "test_custom_feat_001" in FEATURE_FUNCTIONS
        assert FEATURE_FUNCTIONS["test_custom_feat_001"](["col"]) == "CUSTOM(col)"

    def test_register_custom_comparison(self):
        """External code can register custom comparison functions."""
        from bq_entity_resolution.matching.comparisons import (
            COMPARISON_FUNCTIONS,
            register,
        )

        @register("test_custom_comp_001")
        def test_custom_comp_001(left, right, **_):
            return f"(l.{left} = r.{right})"

        assert "test_custom_comp_001" in COMPARISON_FUNCTIONS
        result = COMPARISON_FUNCTIONS["test_custom_comp_001"]("a", "b")
        assert result == "(l.a = r.b)"

    def test_register_via_top_level_imports(self):
        """Custom functions can be registered via top-level package imports."""
        from bq_entity_resolution import register_comparison, register_feature

        @register_feature("test_toplevel_feat_001")
        def tl_feat(inputs, **_):
            return f"TL({inputs[0]})"

        @register_comparison("test_toplevel_comp_001")
        def tl_comp(left, right, **_):
            return f"(l.{left} <> r.{right})"

        from bq_entity_resolution import COMPARISON_FUNCTIONS, FEATURE_FUNCTIONS

        assert "test_toplevel_feat_001" in FEATURE_FUNCTIONS
        assert "test_toplevel_comp_001" in COMPARISON_FUNCTIONS


# -- Tests: public API exports --


class TestPublicAPIExports:
    """Ensure all extensibility APIs are importable from the top-level package."""

    def test_stage_base_classes(self):
        from bq_entity_resolution import Stage, StageResult, TableRef

        assert Stage is not None
        assert TableRef is not None
        assert StageResult is not None

    def test_dag_classes(self):
        from bq_entity_resolution import StageDAG, build_pipeline_dag

        assert StageDAG is not None
        assert callable(build_pipeline_dag)

    def test_plan_classes(self):
        from bq_entity_resolution import PipelinePlan, StagePlan

        assert PipelinePlan is not None
        assert StagePlan is not None

    def test_executor_classes(self):
        from bq_entity_resolution import (
            PipelineExecutor,
            PipelineResult,
            ProgressCallback,
        )

        assert PipelineExecutor is not None
        assert PipelineResult is not None
        assert ProgressCallback is not None

    def test_gate_classes(self):
        from bq_entity_resolution import (
            ClusterSizeGate,
            DataQualityGate,
            GateResult,
            OutputNotEmptyGate,
        )

        assert DataQualityGate is not None
        assert GateResult is not None
        assert OutputNotEmptyGate is not None
        assert ClusterSizeGate is not None

    def test_backend_protocol(self):
        from bq_entity_resolution import Backend, QueryResult

        assert Backend is not None
        assert QueryResult is not None

    def test_sql_expression(self):
        from bq_entity_resolution import SQLExpression

        assert SQLExpression is not None

    def test_comparison_costs(self):
        from bq_entity_resolution import COMPARISON_COSTS

        assert isinstance(COMPARISON_COSTS, dict)
        assert "exact" in COMPARISON_COSTS

    def test_contract_violation(self):
        from bq_entity_resolution import ContractViolation

        assert ContractViolation is not None


# -- Tests: custom Stage subclassing --


class TestCustomStageSubclassing:
    """Verify the Stage ABC contract is simple enough for external use."""

    def test_minimal_stage_implementation(self):
        """A minimal Stage subclass needs only name and plan."""

        class MinimalStage(Stage):
            @property
            def name(self):
                return "minimal"

            def plan(self, **kwargs):
                return [SQLExpression.from_raw("SELECT 1")]

        s = MinimalStage()
        assert s.name == "minimal"
        assert s.inputs == {}
        assert s.outputs == {}
        assert len(s.plan()) == 1

    def test_full_stage_implementation(self):
        """A fully-implemented Stage with inputs/outputs/validate."""

        class FullStage(Stage):
            @property
            def name(self):
                return "full"

            @property
            def inputs(self):
                return {"src": TableRef(name="source", fq_name="p.d.src")}

            @property
            def outputs(self):
                return {"dest": TableRef(name="result", fq_name="p.d.dest")}

            def plan(self, **kwargs):
                return [
                    SQLExpression.from_raw(
                        f"CREATE TABLE {self.outputs['dest'].fq_name} AS "
                        f"SELECT * FROM {self.inputs['src'].fq_name}"
                    )
                ]

            def validate(self):
                return []

        s = FullStage()
        assert s.inputs["src"].fq_name == "p.d.src"
        assert s.outputs["dest"].fq_name == "p.d.dest"
        sql = s.plan()[0].render()
        assert "p.d.dest" in sql
        assert "p.d.src" in sql

    def test_custom_stage_in_dag(self):
        """Custom stages integrate with StageDAG."""
        a = CustomStage(
            "producer",
            outputs={"out": TableRef(name="t", fq_name="p.d.t")},
        )
        b = CustomStage(
            "consumer",
            inputs={"in": TableRef(name="t", fq_name="p.d.t")},
        )
        dag = StageDAG.from_stages([b, a])
        assert dag.stage_names == ["producer", "consumer"]
        assert dag.get_dependencies("consumer") == ["producer"]
