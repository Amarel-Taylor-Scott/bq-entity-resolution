"""Tests for the pipeline DAG."""

import pytest

from bq_entity_resolution.pipeline.dag import StageDAG, StageNode, build_pipeline_dag
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

# -- Dummy stages for testing --


class DummyStage(Stage):
    """Configurable dummy stage for DAG testing."""

    def __init__(
        self,
        name: str,
        inputs: dict[str, TableRef] | None = None,
        outputs: dict[str, TableRef] | None = None,
    ):
        self._name = name
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
        return [SQLExpression.from_raw(f"SELECT 1 -- {self._name}")]


# -- Tests --


class TestStageDAG:
    def test_single_stage(self):
        """DAG with one stage works."""
        s = DummyStage("only")
        dag = StageDAG.from_stages([s])
        assert dag.stage_names == ["only"]
        assert len(dag) == 1

    def test_linear_chain_auto_resolved(self):
        """DAG auto-resolves A -> B -> C from TableRef matching."""
        a = DummyStage(
            "a",
            outputs={"out": TableRef(name="t1", fq_name="proj.ds.t1")},
        )
        b = DummyStage(
            "b",
            inputs={"in": TableRef(name="t1", fq_name="proj.ds.t1")},
            outputs={"out": TableRef(name="t2", fq_name="proj.ds.t2")},
        )
        c = DummyStage(
            "c",
            inputs={"in": TableRef(name="t2", fq_name="proj.ds.t2")},
        )
        dag = StageDAG.from_stages([c, a, b])  # shuffled order
        assert dag.stage_names == ["a", "b", "c"]

    def test_parallel_stages(self):
        """Independent stages appear in alphabetical order (deterministic)."""
        a = DummyStage("alpha")
        b = DummyStage("beta")
        c = DummyStage("gamma")
        dag = StageDAG.from_stages([c, a, b])
        # All roots, sorted alphabetically
        assert dag.stage_names == ["alpha", "beta", "gamma"]

    def test_diamond_dependency(self):
        """DAG handles diamond: A -> B, A -> C, B -> D, C -> D."""
        a = DummyStage(
            "a",
            outputs={"out": TableRef(name="t1", fq_name="p.d.t1")},
        )
        b = DummyStage(
            "b",
            inputs={"in": TableRef(name="t1", fq_name="p.d.t1")},
            outputs={"out": TableRef(name="t2", fq_name="p.d.t2")},
        )
        c = DummyStage(
            "c",
            inputs={"in": TableRef(name="t1", fq_name="p.d.t1")},
            outputs={"out": TableRef(name="t3", fq_name="p.d.t3")},
        )
        d = DummyStage(
            "d",
            inputs={
                "in1": TableRef(name="t2", fq_name="p.d.t2"),
                "in2": TableRef(name="t3", fq_name="p.d.t3"),
            },
        )
        dag = StageDAG.from_stages([d, c, b, a])
        assert dag.stage_names[0] == "a"
        assert dag.stage_names[-1] == "d"
        # b and c are between a and d (order doesn't matter)
        assert set(dag.stage_names[1:3]) == {"b", "c"}

    def test_explicit_edges(self):
        """Explicit edges override auto-resolved dependencies."""
        a = DummyStage("a")
        b = DummyStage("b")
        c = DummyStage("c")
        dag = StageDAG.from_stages(
            [a, b, c],
            explicit_edges={"b": ["a"], "c": ["b"]},
        )
        assert dag.stage_names == ["a", "b", "c"]

    def test_cycle_detection(self):
        """Cycles raise ValueError."""
        a = DummyStage(
            "a",
            inputs={"in": TableRef(name="t2", fq_name="p.d.t2")},
            outputs={"out": TableRef(name="t1", fq_name="p.d.t1")},
        )
        b = DummyStage(
            "b",
            inputs={"in": TableRef(name="t1", fq_name="p.d.t1")},
            outputs={"out": TableRef(name="t2", fq_name="p.d.t2")},
        )
        with pytest.raises(ValueError, match="Cycle detected"):
            StageDAG.from_stages([a, b])

    def test_duplicate_name_raises(self):
        """Duplicate stage names raise ValueError."""
        a = DummyStage("same")
        b = DummyStage("same")
        with pytest.raises(ValueError, match="Duplicate stage name"):
            StageDAG([
                StageNode(stage=a),
                StageNode(stage=b),
            ])

    def test_get_stage(self):
        """get_stage returns the correct stage."""
        s = DummyStage("target")
        dag = StageDAG.from_stages([s])
        assert dag.get_stage("target").name == "target"

    def test_get_dependencies(self):
        """get_dependencies returns correct deps."""
        a = DummyStage(
            "a",
            outputs={"out": TableRef(name="t", fq_name="p.d.t")},
        )
        b = DummyStage(
            "b",
            inputs={"in": TableRef(name="t", fq_name="p.d.t")},
        )
        dag = StageDAG.from_stages([a, b])
        assert dag.get_dependencies("a") == []
        assert dag.get_dependencies("b") == ["a"]

    def test_get_dependents(self):
        """get_dependents returns stages that depend on the given stage."""
        a = DummyStage(
            "a",
            outputs={"out": TableRef(name="t", fq_name="p.d.t")},
        )
        b = DummyStage(
            "b",
            inputs={"in": TableRef(name="t", fq_name="p.d.t")},
        )
        dag = StageDAG.from_stages([a, b])
        assert dag.get_dependents("a") == ["b"]
        assert dag.get_dependents("b") == []

    def test_repr(self):
        """repr shows stage names."""
        s = DummyStage("test")
        dag = StageDAG.from_stages([s])
        assert "test" in repr(dag)
        assert "StageDAG" in repr(dag)

    def test_stages_property_returns_in_order(self):
        """stages property returns Stage objects in topological order."""
        a = DummyStage("a")
        b = DummyStage("b")
        dag = StageDAG.from_stages([a, b], explicit_edges={"b": ["a"]})
        stages = dag.stages
        assert [s.name for s in stages] == ["a", "b"]


class TestBuildPipelineDAG:
    """Test build_pipeline_dag with a minimal config."""

    def _make_config(self):
        """Minimal config for DAG building tests."""
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
        ck1 = NS(
            name="bk_name",
            expression="UPPER(first_name)",
        )

        features_config = NS(
            groups=[feat_group],
            blocking_keys=[bk1],
            composite_keys=[ck1],
        )

        blocking_path = NS(
            keys=["bk_soundex"],
            lsh_keys=[],
            candidate_limit=0,
        )
        blocking_config = NS(
            paths=[blocking_path],
            cross_batch=False,
        )

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
        canonical_selection = NS(
            method="completeness",
            source_priority=[],
        )
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
            link_type=None,
        )

        def fq_table(dataset_attr, table_name):
            ds = getattr(project, dataset_attr, "test-proj.default")
            return f"{ds}.{table_name}"

        config.fq_table = fq_table
        config.enabled_tiers = lambda: [tier]

        return config

    def test_builds_dag(self):
        """build_pipeline_dag creates a valid DAG."""
        config = self._make_config()
        dag = build_pipeline_dag(config)
        assert len(dag) >= 6  # staging, features, tf, blocking, matching, clustering, gold

    def test_staging_before_features(self):
        """Staging must come before feature engineering."""
        config = self._make_config()
        dag = build_pipeline_dag(config)
        names = dag.stage_names
        assert names.index("staging_crm") < names.index("feature_engineering")

    def test_features_before_blocking(self):
        """Features must come before blocking."""
        config = self._make_config()
        dag = build_pipeline_dag(config)
        names = dag.stage_names
        assert names.index("feature_engineering") < names.index("blocking_exact")

    def test_blocking_before_matching(self):
        """Blocking must come before matching within a tier."""
        config = self._make_config()
        dag = build_pipeline_dag(config)
        names = dag.stage_names
        assert names.index("blocking_exact") < names.index("matching_exact")

    def test_matching_before_clustering(self):
        """Matching must come before clustering."""
        config = self._make_config()
        dag = build_pipeline_dag(config)
        names = dag.stage_names
        assert names.index("matching_exact") < names.index("clustering")

    def test_clustering_before_gold(self):
        """Clustering must come before gold output."""
        config = self._make_config()
        dag = build_pipeline_dag(config)
        names = dag.stage_names
        assert names.index("clustering") < names.index("gold_output")

    def test_no_cluster_quality_when_disabled(self):
        """Cluster quality stage only included when monitoring enabled."""
        config = self._make_config()
        dag = build_pipeline_dag(config)
        assert "cluster_quality" not in dag.stage_names

    def test_cluster_quality_when_enabled(self):
        """Cluster quality stage included when monitoring enabled."""
        config = self._make_config()
        config.monitoring.cluster_quality.enabled = True
        dag = build_pipeline_dag(config)
        assert "cluster_quality" in dag.stage_names
