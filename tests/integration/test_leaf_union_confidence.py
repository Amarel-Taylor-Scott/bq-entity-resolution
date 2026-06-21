"""The leaf union carries match_confidence (real for sum/F-S, NULL for greatest)."""

from __future__ import annotations

import pytest

from bq_entity_resolution.config.presets import quick_config
from bq_entity_resolution.config.schema import LeafDef
from bq_entity_resolution.stages.leaf_resolution import LeafResolutionStage


@pytest.fixture
def cfg():
    c = quick_config(
        bq_project="p", source_table="p.raw.c", unique_key="id",
        updated_at="updated_at",
        column_roles={"first_name": "first_name", "last_name": "last_name",
                      "email": "email"},
        project_name="pr",
    )
    c.leaves = [
        LeafDef(name="nxn", left="new", right="new"),                 # greatest
        LeafDef(name="nxo", left="new", right="old", scoring="sum"),  # sum
    ]
    return c


def _union_sql(cfg) -> str:
    stage = LeafResolutionStage(cfg, leaves=cfg.select_leaves())
    return next(e.render() for e in stage.plan() if "all_matched_pairs" in e.render())


def test_union_shape(cfg):
    u = _union_sql(cfg)
    assert "NULL AS match_confidence" in u          # greatest leaf: no confidence
    assert "match_confidence AS match_confidence" in u  # sum leaf: carried
    assert "MAX(match_confidence) AS match_confidence" in u  # aggregated out


def test_union_executes_on_duckdb(cfg):
    from bq_entity_resolution.backends.duckdb import DuckDBBackend
    from bq_entity_resolution.backends.duckdb.sql_adapter import adapt_sql

    db = DuckDBBackend(":memory:")
    # greatest leaf table: no match_confidence column.
    db.execute(
        "CREATE TABLE leaf_pairs_nxn (left_entity_uid BIGINT, right_entity_uid "
        "BIGINT, match_total_score DOUBLE, match_method VARCHAR)"
    )
    db.connection.execute("INSERT INTO leaf_pairs_nxn VALUES (1,2,0.9,'compare')")
    # sum leaf table: has match_confidence.
    db.execute(
        "CREATE TABLE leaf_pairs_nxo (left_entity_uid BIGINT, right_entity_uid "
        "BIGINT, match_total_score DOUBLE, match_confidence DOUBLE)"
    )
    db.connection.execute("INSERT INTO leaf_pairs_nxo VALUES (3,4,0.8,0.75)")

    db.execute(adapt_sql(_union_sql(cfg)))
    rows = db.execute_and_fetch(
        "SELECT left_entity_uid, match_confidence FROM all_matched_pairs "
        "ORDER BY left_entity_uid"
    )
    conf = {int(r["left_entity_uid"]): r["match_confidence"] for r in rows}
    assert conf[1] is None              # greatest pair → NULL confidence
    assert float(conf[3]) == 0.75       # sum pair → carried confidence
