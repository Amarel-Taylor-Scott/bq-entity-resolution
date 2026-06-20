"""Tests for pipeline diagnostics."""

from bq_entity_resolution.pipeline.diagnostics import (
    Diagnosis,
    diagnose_cluster_explosion,
    diagnose_empty_blocking,
    diagnose_empty_matches,
)


class TestDiagnosis:
    def test_format_basic(self):
        d = Diagnosis(message="Something broke")
        text = d.format()
        assert "DIAGNOSIS: Something broke" in text

    def test_format_with_causes(self):
        d = Diagnosis(
            message="Error",
            possible_causes=("Cause A", "Cause B"),
        )
        text = d.format()
        assert "Possible causes:" in text
        assert "Cause A" in text
        assert "Cause B" in text

    def test_format_with_checks(self):
        d = Diagnosis(
            message="Error",
            suggested_checks=("SELECT COUNT(*) FROM t",),
        )
        text = d.format()
        assert "Suggested checks:" in text
        assert "SELECT COUNT" in text

    def test_immutable(self):
        d = Diagnosis(message="test")
        assert d.message == "test"


class TestDiagnoseEmptyBlocking:
    def test_basic(self):
        d = diagnose_empty_blocking(
            tier_name="exact",
            blocking_keys=["soundex_name"],
            source_table="proj.ds.featured",
        )
        assert "exact" in d.message
        assert "soundex_name" in d.possible_causes[0]
        assert "featured" in d.suggested_checks[0]

    def test_link_only(self):
        d = diagnose_empty_blocking(
            tier_name="fuzzy",
            blocking_keys=["bk"],
            source_table="proj.ds.featured",
            link_type="link_only",
        )
        assert any("link_only" in c for c in d.possible_causes)
        assert any("source_name" in c for c in d.suggested_checks)

    def test_multiple_keys(self):
        d = diagnose_empty_blocking(
            tier_name="multi",
            blocking_keys=["k1", "k2"],
            source_table="proj.ds.featured",
        )
        assert "k1" in d.possible_causes[0]
        assert "k2" in d.possible_causes[0]


class TestDiagnoseEmptyMatches:
    def test_basic(self):
        d = diagnose_empty_matches(
            tier_name="fuzzy",
            candidates_table="proj.ds.candidates_fuzzy",
        )
        assert "fuzzy" in d.message
        assert "candidate_count" in d.suggested_checks[0]

    def test_with_threshold(self):
        d = diagnose_empty_matches(
            tier_name="fuzzy",
            candidates_table="proj.ds.candidates_fuzzy",
            threshold=0.85,
        )
        assert len(d.suggested_checks) >= 3
        assert "0.85" in d.suggested_checks[-1]


class TestDiagnoseClusterExplosion:
    def test_basic(self):
        d = diagnose_cluster_explosion(
            max_size=5000,
            threshold=100,
            cluster_table="proj.ds.clusters",
        )
        assert "5000" in d.message
        assert "100" in d.message
        assert len(d.possible_causes) >= 3
        assert "clusters" in d.suggested_checks[0]
