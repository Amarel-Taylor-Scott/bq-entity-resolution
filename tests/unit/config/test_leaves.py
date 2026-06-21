"""Tests for leaf-based resolution config models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bq_entity_resolution.config.models.leaves import (
    LeafDef,
    LeafHeuristics,
    PartitionDef,
    default_leaves,
    default_partitions,
)


class TestPartitionDef:
    def test_defaults_to_batch_source(self) -> None:
        p = PartitionDef(name="new")
        assert p.source == "batch"
        assert p.predicate is None

    def test_table_source_requires_table(self) -> None:
        with pytest.raises(ValidationError, match="requires 'table'"):
            PartitionDef(name="crm", source="table")
        PartitionDef(name="crm", source="table", table="proj.ds.crm")  # ok

    def test_predicate_rejects_sql_injection(self) -> None:
        for bad in ["x=1; DROP TABLE t", "1=1 -- ", "a/*c*/", "DELETE FROM t"]:
            with pytest.raises(ValidationError):
                PartitionDef(name="p", predicate=bad)
        PartitionDef(name="p", predicate="updated_at >= 5 AND source = 'crm'")  # ok

    def test_name_must_be_valid_identifier(self) -> None:
        with pytest.raises(ValidationError):
            PartitionDef(name="bad name!")


class TestLeafHeuristics:
    def test_threshold_bounds(self) -> None:
        LeafHeuristics(threshold_override=0.0)
        LeafHeuristics(threshold_override=1.0)
        for bad in (-0.1, 1.1):
            with pytest.raises(ValidationError):
                LeafHeuristics(threshold_override=bad)

    def test_short_circuit_keys_validated(self) -> None:
        LeafHeuristics(exact_key_short_circuit=["email_norm", "phone_e164"])
        with pytest.raises(ValidationError):
            LeafHeuristics(exact_key_short_circuit=["bad key"])

    def test_max_pairs_positive(self) -> None:
        with pytest.raises(ValidationError):
            LeafHeuristics(max_pairs=0)


class TestLeafDef:
    def test_self_join_detection(self) -> None:
        assert LeafDef(name="nxn", left="new", right="new").is_self_join is True
        assert LeafDef(name="nxo", left="new", right="old").is_self_join is False

    def test_cron_schedule_requires_expr(self) -> None:
        with pytest.raises(ValidationError, match="requires 'cron'"):
            LeafDef(name="oxo", left="old", right="old", schedule="cron")
        LeafDef(name="oxo", left="old", right="old", schedule="cron", cron="0 3 * * 0")  # ok

    def test_generic_nxm_leaf(self) -> None:
        leaf = LeafDef(name="crm_x_erp", left="crm", right="erp",
                       heuristics=LeafHeuristics(exact_key_short_circuit=["national_id"]))
        assert not leaf.is_self_join
        assert leaf.enabled and leaf.schedule == "every_run"


class TestPresetSynthesis:
    def test_default_partitions(self) -> None:
        names = [p.name for p in default_partitions()]
        assert names == ["new", "old"]

    def test_default_leaves_cross_batch(self) -> None:
        leaves = default_leaves(cross_batch=True)
        assert [leaf.name for leaf in leaves] == ["new_x_new", "new_x_old"]
        assert leaves[0].is_self_join and not leaves[1].is_self_join

    def test_default_leaves_no_cross_batch(self) -> None:
        leaves = default_leaves(cross_batch=False)
        assert [leaf.name for leaf in leaves] == ["new_x_new"]
