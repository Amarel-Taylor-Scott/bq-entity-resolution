"""Tests for the Stage base class and supporting types."""

from bq_entity_resolution.sql.expression import SQLExpression
from bq_entity_resolution.stages.base import Stage, StageResult, TableRef


def test_table_ref_creation():
    """TableRef is a frozen dataclass."""
    ref = TableRef(name="featured", fq_name="proj.ds.featured")
    assert ref.name == "featured"
    assert ref.fq_name == "proj.ds.featured"


def test_table_ref_defaults():
    """TableRef has sensible defaults."""
    ref = TableRef(name="test")
    assert ref.fq_name == ""
    assert ref.description == ""


def test_stage_result_defaults():
    """StageResult has sensible defaults."""
    result = StageResult(stage_name="test")
    assert result.success is True
    assert result.error is None
    assert result.sql_expressions == []


def test_stage_result_with_error():
    """StageResult can record errors."""
    result = StageResult(stage_name="test", success=False, error="boom")
    assert result.success is False
    assert result.error == "boom"


class DummyStage(Stage):
    """Minimal concrete stage for testing."""

    @property
    def name(self) -> str:
        return "dummy"

    def plan(self, **kwargs) -> list[SQLExpression]:
        return [SQLExpression.from_raw("SELECT 1")]


def test_concrete_stage_name():
    """Concrete stage has a name."""
    stage = DummyStage()
    assert stage.name == "dummy"


def test_concrete_stage_plan():
    """Concrete stage generates SQL."""
    stage = DummyStage()
    exprs = stage.plan()
    assert len(exprs) == 1
    assert "SELECT 1" in exprs[0].render()


def test_stage_default_inputs_outputs():
    """Default inputs and outputs are empty."""
    stage = DummyStage()
    assert stage.inputs == {}
    assert stage.outputs == {}


def test_stage_validate_returns_empty():
    """Default validate returns no errors."""
    stage = DummyStage()
    assert stage.validate() == []


def test_stage_repr():
    """Stage has a useful repr."""
    stage = DummyStage()
    assert "DummyStage" in repr(stage)
    assert "dummy" in repr(stage)
