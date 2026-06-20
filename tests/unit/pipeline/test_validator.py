"""Tests for the pipeline validator."""


from bq_entity_resolution.pipeline.dag import StageDAG
from bq_entity_resolution.pipeline.validator import (
    ContractViolation,
    validate_dag_contracts,
    validate_stage_configs,
)
from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, TableRef

# -- Dummy stages --


class DummyStage(Stage):
    def __init__(self, name, inputs=None, outputs=None, errors=None):
        self._name = name
        self._inputs = inputs or {}
        self._outputs = outputs or {}
        self._errors = errors or []

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
        return [SQLExpression.from_raw("SELECT 1")]

    def validate(self):
        return self._errors


# -- validate_dag_contracts tests --


class TestValidateDagContracts:
    def test_valid_linear_chain(self):
        """A -> B -> C with matching TableRefs is valid."""
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
            inputs={"in": TableRef(name="t2", fq_name="p.d.t2")},
        )
        dag = StageDAG.from_stages([a, b, c])
        violations = validate_dag_contracts(dag)
        errors = [v for v in violations if v.severity == "error"]
        assert errors == []

    def test_missing_upstream_table(self):
        """Input not produced by any upstream stage is flagged."""
        a = DummyStage("a")
        b = DummyStage(
            "b",
            inputs={"in": TableRef(name="t", fq_name="p.d.missing")},
        )
        dag = StageDAG.from_stages([a, b], explicit_edges={"b": ["a"]})
        violations = validate_dag_contracts(dag)
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) == 1
        assert "missing" in errors[0].message

    def test_root_stage_external_inputs_ok(self):
        """Root stage inputs are treated as external (no violation)."""
        root = DummyStage(
            "root",
            inputs={
                "source": TableRef(
                    name="raw", fq_name="proj.raw.customers"
                )
            },
            outputs={
                "out": TableRef(name="staged", fq_name="p.d.staged")
            },
        )
        dag = StageDAG.from_stages([root])
        violations = validate_dag_contracts(dag)
        errors = [v for v in violations if v.severity == "error"]
        assert errors == []

    def test_external_tables_not_flagged(self):
        """Explicitly listed external tables are not flagged."""
        a = DummyStage("a")
        b = DummyStage(
            "b",
            inputs={"in": TableRef(name="ext", fq_name="p.d.external")},
        )
        dag = StageDAG.from_stages([a, b], explicit_edges={"b": ["a"]})
        violations = validate_dag_contracts(
            dag, external_tables={"p.d.external"}
        )
        errors = [v for v in violations if v.severity == "error"]
        assert errors == []

    def test_dead_end_warning(self):
        """Stage with no outputs and no dependents gets a warning."""
        leaf = DummyStage("leaf")
        dag = StageDAG.from_stages([leaf])
        violations = validate_dag_contracts(dag)
        warnings = [v for v in violations if v.severity == "warning"]
        assert any("dead end" in w.message for w in warnings)

    def test_stage_with_outputs_no_warning(self):
        """Stage with outputs does not get dead-end warning."""
        s = DummyStage(
            "producer",
            outputs={"out": TableRef(name="t", fq_name="p.d.t")},
        )
        dag = StageDAG.from_stages([s])
        violations = validate_dag_contracts(dag)
        warnings = [v for v in violations if v.severity == "warning"]
        assert not any("dead end" in w.message for w in warnings)

    def test_empty_fq_name_ignored(self):
        """Inputs with empty fq_name are not checked."""
        s = DummyStage(
            "s",
            inputs={"in": TableRef(name="empty")},
        )
        dag = StageDAG.from_stages([s])
        violations = validate_dag_contracts(dag)
        errors = [v for v in violations if v.severity == "error"]
        assert errors == []


class TestContractViolation:
    def test_creation(self):
        v = ContractViolation(
            stage_name="test", message="broken", severity="error"
        )
        assert v.stage_name == "test"
        assert v.message == "broken"
        assert v.severity == "error"

    def test_default_severity(self):
        v = ContractViolation(stage_name="test", message="broken")
        assert v.severity == "error"


# -- validate_stage_configs tests --


class TestValidateStageConfigs:
    def test_no_errors(self):
        """Stages with no validation errors produce empty list."""
        s = DummyStage("clean")
        dag = StageDAG.from_stages([s])
        violations = validate_stage_configs(dag)
        assert violations == []

    def test_stage_errors_propagated(self):
        """Stage validate() errors are captured as violations."""
        s = DummyStage("broken", errors=["missing field", "bad config"])
        dag = StageDAG.from_stages([s])
        violations = validate_stage_configs(dag)
        assert len(violations) == 2
        assert violations[0].stage_name == "broken"
        assert "missing field" in violations[0].message
