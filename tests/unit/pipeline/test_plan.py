"""Tests for the pipeline plan."""

import pytest

from bq_entity_resolution.pipeline.dag import StageDAG
from bq_entity_resolution.pipeline.plan import PipelinePlan, StagePlan, create_plan
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

# -- Dummy stage --

class DummyStage(Stage):
    def __init__(self, name, inputs=None, outputs=None, sql="SELECT 1"):
        self._name = name
        self._inputs = inputs or {}
        self._outputs = outputs or {}
        self._sql = sql

    @property
    def name(self):
        return self._name

    @property
    def inputs(self):
        return self._inputs

    @property
    def outputs(self):
        return self._outputs

    def plan(self, **kwargs):
        return [SQLExpression.from_raw(self._sql)]


# -- StagePlan tests --


class TestStagePlan:
    def test_sql_count(self):
        expr = SQLExpression.from_raw("SELECT 1")
        sp = StagePlan(
            stage_name="test",
            sql_expressions=(expr,),
            inputs={},
            outputs={},
            dependencies=(),
        )
        assert sp.sql_count == 1

    def test_render_sql(self):
        expr = SQLExpression.from_raw("CREATE TABLE t AS SELECT 1")
        sp = StagePlan(
            stage_name="test",
            sql_expressions=(expr,),
            inputs={},
            outputs={},
            dependencies=(),
        )
        rendered = sp.render_sql()
        assert len(rendered) == 1
        assert "CREATE TABLE" in rendered[0]

    def test_empty_plan(self):
        sp = StagePlan(
            stage_name="empty",
            sql_expressions=(),
            inputs={},
            outputs={},
            dependencies=(),
        )
        assert sp.sql_count == 0
        assert sp.render_sql() == []


# -- PipelinePlan tests --


class TestPipelinePlan:
    def _make_plan(self, n_stages=2):
        stages = []
        for i in range(n_stages):
            stages.append(StagePlan(
                stage_name=f"stage_{i}",
                sql_expressions=(SQLExpression.from_raw(f"SELECT {i}"),),
                inputs={},
                outputs={},
                dependencies=(),
            ))
        return PipelinePlan(stages=tuple(stages))

    def test_stage_names(self):
        plan = self._make_plan(3)
        assert plan.stage_names == ["stage_0", "stage_1", "stage_2"]

    def test_total_sql_count(self):
        plan = self._make_plan(3)
        assert plan.total_sql_count == 3

    def test_get_stage(self):
        plan = self._make_plan(2)
        sp = plan.get_stage("stage_0")
        assert sp.stage_name == "stage_0"

    def test_get_stage_not_found(self):
        plan = self._make_plan(1)
        with pytest.raises(KeyError, match="Stage not found"):
            plan.get_stage("nonexistent")

    def test_all_sql(self):
        plan = self._make_plan(2)
        all_sql = plan.all_sql()
        assert len(all_sql) == 2
        assert "SELECT 0" in all_sql[0]
        assert "SELECT 1" in all_sql[1]

    def test_preview(self):
        plan = self._make_plan(2)
        preview = plan.preview()
        assert "Pipeline Plan" in preview
        assert "stage_0" in preview
        assert "stage_1" in preview
        assert "2 stages" in preview

    def test_preview_shows_dependencies(self):
        sp = StagePlan(
            stage_name="child",
            sql_expressions=(SQLExpression.from_raw("SELECT 1"),),
            inputs={"in": TableRef(name="t", fq_name="p.d.t")},
            outputs={},
            dependencies=("parent",),
        )
        plan = PipelinePlan(stages=(sp,))
        preview = plan.preview()
        assert "parent" in preview


# -- create_plan tests --


class TestCreatePlan:
    def test_creates_plan_from_dag(self):
        a = DummyStage("a", sql="SELECT 'a'")
        b = DummyStage("b", sql="SELECT 'b'")
        dag = StageDAG.from_stages([a, b])
        plan = create_plan(dag)
        assert len(plan.stages) == 2
        assert plan.total_sql_count == 2

    def test_preserves_dag_order(self):
        a = DummyStage(
            "a",
            outputs={"out": TableRef(name="t", fq_name="p.d.t")},
        )
        b = DummyStage(
            "b",
            inputs={"in": TableRef(name="t", fq_name="p.d.t")},
        )
        dag = StageDAG.from_stages([b, a])
        plan = create_plan(dag)
        assert plan.stage_names == ["a", "b"]

    def test_plan_captures_inputs_outputs(self):
        out_ref = TableRef(name="t", fq_name="p.d.t", description="desc")
        a = DummyStage("a", outputs={"out": out_ref})
        dag = StageDAG.from_stages([a])
        plan = create_plan(dag)
        sp = plan.get_stage("a")
        assert "out" in sp.outputs
        assert sp.outputs["out"].fq_name == "p.d.t"
