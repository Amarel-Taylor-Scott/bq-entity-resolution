"""Tests for data quality gates."""


from bq_entity_resolution.pipeline.gates import (
    ClusterSizeGate,
    DataQualityScoreGate,
    GateResult,
    OutputNotEmptyGate,
    default_gates,
)
from bq_entity_resolution.stages.base import TableRef

# -- Mock backend --


class MockBackend:
    def __init__(self, row_counts=None, fetch_results=None):
        self._row_counts = row_counts or {}
        self._fetch_results = fetch_results or []

    @property
    def dialect(self):
        return "bigquery"

    def row_count(self, ref):
        if ref in self._row_counts:
            return self._row_counts[ref]
        raise RuntimeError(f"Table not found: {ref}")

    def execute_and_fetch(self, sql, label=""):
        return self._fetch_results


# -- GateResult tests --


class TestGateResult:
    def test_passing(self):
        r = GateResult(passed=True, message="OK")
        assert r.passed

    def test_failing(self):
        r = GateResult(passed=False, message="bad", severity="error")
        assert not r.passed
        assert r.severity == "error"


# -- OutputNotEmptyGate tests --


class TestOutputNotEmptyGate:
    def test_applies_to_matching_prefix(self):
        gate = OutputNotEmptyGate("blocking_")
        assert gate.applies_to("blocking_exact")
        assert not gate.applies_to("matching_exact")

    def test_passes_when_rows_exist(self):
        backend = MockBackend(row_counts={"p.d.candidates": 100})
        gate = OutputNotEmptyGate("blocking_", output_key="candidates")
        outputs = {
            "candidates": TableRef(
                name="candidates", fq_name="p.d.candidates"
            )
        }
        result = gate.check("blocking_exact", backend, outputs)
        assert result.passed

    def test_fails_when_empty(self):
        backend = MockBackend(row_counts={"p.d.candidates": 0})
        gate = OutputNotEmptyGate(
            "blocking_", severity="error", output_key="candidates"
        )
        outputs = {
            "candidates": TableRef(
                name="candidates", fq_name="p.d.candidates"
            )
        }
        result = gate.check("blocking_exact", backend, outputs)
        assert not result.passed
        assert result.severity == "error"
        assert "empty" in result.message

    def test_fails_when_table_not_found(self):
        backend = MockBackend()  # No tables registered
        gate = OutputNotEmptyGate("blocking_")
        outputs = {
            "candidates": TableRef(
                name="candidates", fq_name="p.d.missing"
            )
        }
        result = gate.check("blocking_exact", backend, outputs)
        assert not result.passed
        assert "does not exist" in result.message

    def test_skips_non_matching_output_key(self):
        backend = MockBackend(row_counts={"p.d.other": 0})
        gate = OutputNotEmptyGate("blocking_", output_key="candidates")
        outputs = {
            "other": TableRef(name="other", fq_name="p.d.other")
        }
        result = gate.check("blocking_exact", backend, outputs)
        assert result.passed  # Skipped, not checked


# -- ClusterSizeGate tests --


class TestClusterSizeGate:
    def test_applies_to_clustering(self):
        gate = ClusterSizeGate(max_cluster_size=100)
        assert gate.applies_to("clustering")
        assert not gate.applies_to("blocking_exact")

    def test_passes_within_limits(self):
        backend = MockBackend(
            fetch_results=[{"max_size": 50}]
        )
        gate = ClusterSizeGate(max_cluster_size=100)
        outputs = {
            "clusters": TableRef(
                name="clusters", fq_name="p.d.clusters"
            )
        }
        result = gate.check("clustering", backend, outputs)
        assert result.passed

    def test_fails_on_explosion(self):
        backend = MockBackend(
            fetch_results=[{"max_size": 500}]
        )
        gate = ClusterSizeGate(
            max_cluster_size=100, abort_on_explosion=True
        )
        outputs = {
            "clusters": TableRef(
                name="clusters", fq_name="p.d.clusters"
            )
        }
        result = gate.check("clustering", backend, outputs)
        assert not result.passed
        assert result.severity == "error"
        assert "500" in result.message

    def test_warning_when_not_abort(self):
        backend = MockBackend(
            fetch_results=[{"max_size": 200}]
        )
        gate = ClusterSizeGate(
            max_cluster_size=100, abort_on_explosion=False
        )
        outputs = {
            "clusters": TableRef(
                name="clusters", fq_name="p.d.clusters"
            )
        }
        result = gate.check("clustering", backend, outputs)
        assert not result.passed
        assert result.severity == "warning"

    def test_no_cluster_table(self):
        backend = MockBackend()
        gate = ClusterSizeGate(max_cluster_size=100)
        result = gate.check("clustering", backend, {})
        assert result.passed


# -- default_gates tests --


class TestDefaultGates:
    def test_creates_gates_without_config(self):
        gates = default_gates()
        assert len(gates) >= 2

    def test_includes_cluster_gate_when_enabled(self):
        class NS:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        config = NS(
            monitoring=NS(
                cluster_quality=NS(
                    enabled=True,
                    alert_max_cluster_size=50,
                    abort_on_explosion=True,
                )
            )
        )
        gates = default_gates(config)
        cluster_gates = [
            g for g in gates if isinstance(g, ClusterSizeGate)
        ]
        assert len(cluster_gates) == 1


class TestDataQualityScoreGate:
    """Tests for DataQualityScoreGate."""

    def test_applies_to_blocking_stages(self):
        gate = DataQualityScoreGate(min_score=50)
        assert gate.applies_to("blocking_tier0") is True
        assert gate.applies_to("blocking_exact") is True
        assert gate.applies_to("matching_tier0") is False
        assert gate.applies_to("clustering") is False

    def test_check_passes(self):
        gate = DataQualityScoreGate(min_score=50)
        result = gate.check("blocking_tier0", None, {})
        assert result.passed is True

    def test_included_in_default_gates_when_enabled(self):
        class NS:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        config = NS(
            monitoring=NS(
                cluster_quality=NS(enabled=False),
                min_data_quality_score=50,
            )
        )
        gates = default_gates(config)
        dq_gates = [g for g in gates if isinstance(g, DataQualityScoreGate)]
        assert len(dq_gates) == 1

    def test_excluded_from_default_gates_when_zero(self):
        class NS:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        config = NS(
            monitoring=NS(
                cluster_quality=NS(enabled=False),
                min_data_quality_score=0,
            )
        )
        gates = default_gates(config)
        dq_gates = [g for g in gates if isinstance(g, DataQualityScoreGate)]
        assert len(dq_gates) == 0
