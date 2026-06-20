"""Tests for signal flow through the matching stage.

Verifies that entity_type_condition, severity-aware behavior, global signals,
and score banding all produce correct SQL when wired through MatchingStage.
"""

from bq_entity_resolution.stages.matching import _ENTITY_TYPE_MAP, MatchingStage

# -- Namespace helper (same pattern as test_stages.py) -----------------------

class NS:
    """Simple namespace for minimal config-like objects."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_config(
    *,
    global_hard_negatives=None,
    global_hard_positives=None,
    global_soft_signals=None,
    entity_type_column="",
):
    """Build a minimal config with optional global signals."""
    project = NS(
        bq_project="proj",
        bq_dataset_bronze="proj.bronze",
        bq_dataset_silver="proj.silver",
        bq_dataset_gold="proj.gold",
        udf_dataset="",
        watermark_dataset="meta",
    )
    source = NS(
        name="src",
        table="proj.raw.table",
        unique_key="id",
        updated_at="ts",
    )
    feature_engineering = NS(
        entity_type_column=entity_type_column,
    )
    audit_trail = NS(enabled=False)
    output_config = NS(audit_trail=audit_trail)
    reconciliation = NS(output=output_config)

    config = NS(
        project=project,
        sources=[source],
        feature_engineering=feature_engineering,
        reconciliation=reconciliation,
    )

    # fq_table used by naming.py for table name resolution
    def fq_table(dataset_attr, suffix):
        ds = getattr(project, dataset_attr, "proj.default")
        return f"{ds}.{suffix}"

    config.fq_table = fq_table

    # Wire effective_* methods (mirrors PipelineConfig behavior)
    g_hns = global_hard_negatives or []
    g_hps = global_hard_positives or []
    g_sigs = global_soft_signals or []

    config.effective_hard_negatives = lambda tier: list(g_hns) + list(
        getattr(tier, "hard_negatives", [])
    )
    config.effective_hard_positives = lambda tier: list(g_hps) + list(
        getattr(tier, "hard_positives", [])
    )
    config.effective_soft_signals = lambda tier: list(g_sigs) + list(
        getattr(tier, "soft_signals", [])
    )

    return config


def _make_tier(
    *,
    hard_negatives=None,
    hard_positives=None,
    soft_signals=None,
    score_banding=None,
):
    """Build a minimal tier with one comparison."""
    comp = NS(
        name="email_exact",
        method="exact",
        left="email",
        right="email",
        weight=5.0,
        params=None,
        tf_enabled=False,
        tf_column="",
        tf_minimum_u=0.01,
        tf_adjustment=None,
        levels=[],
    )
    threshold = NS(
        method="score",
        min_score=3.0,
        match_threshold=None,
        log_prior_odds=0.0,
        min_matching_comparisons=0,
    )
    if score_banding is None:
        score_banding = NS(enabled=False, bands=[])
    return NS(
        name="exact",
        comparisons=[comp],
        threshold=threshold,
        hard_negatives=hard_negatives or [],
        hard_positives=hard_positives or [],
        soft_signals=soft_signals or [],
        score_banding=score_banding,
        confidence=None,
    )


# -- Entity Type Condition Tests --

class TestEntityTypeConditionWrapping:
    """entity_type_condition should wrap SQL with entity type guard."""

    def test_wraps_hard_negative_when_column_configured(self):
        hn = NS(
            left="gen_suffix", right="gen_suffix", method="different",
            action="disqualify", penalty=0.0, sql=None,
            severity="hn3_identity", entity_type_condition="personal",
            params={},
        )
        config = _make_config(entity_type_column="entity_type_class")
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert len(result) == 1
        cond = result[0].sql_condition
        assert "l.entity_type_class = 'PERSON'" in cond
        assert "r.entity_type_class = 'PERSON'" in cond
        assert "IS DISTINCT FROM" in cond

    def test_no_wrapping_when_column_not_configured(self):
        hn = NS(
            left="gen_suffix", right="gen_suffix", method="different",
            action="disqualify", penalty=0.0, sql=None,
            severity="hn3_identity", entity_type_condition="personal",
            params={},
        )
        config = _make_config(entity_type_column="")
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert len(result) == 1
        cond = result[0].sql_condition
        assert "entity_type_class" not in cond
        assert "IS DISTINCT FROM" in cond

    def test_wraps_hard_positive_with_business_condition(self):
        hp = NS(
            left="ein", right="ein", method="exact",
            action="auto_match", boost=5.0, target_band="HIGH",
            sql=None, entity_type_condition="business", params={},
        )
        config = _make_config(entity_type_column="et_col")
        tier = _make_tier(hard_positives=[hp])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_positives(tier)

        assert len(result) == 1
        cond = result[0].sql_condition
        assert "l.et_col = 'BUSINESS'" in cond
        assert "r.et_col = 'BUSINESS'" in cond

    def test_wraps_soft_signal_with_condition(self):
        ss = NS(
            left="email_domain_cat", right="email_domain_cat",
            method="exact", bonus=0.5, sql=None,
            entity_type_condition="personal", params={},
        )
        config = _make_config(entity_type_column="et")
        tier = _make_tier(soft_signals=[ss])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_soft_signals(tier)

        assert len(result) == 1
        cond = result[0].sql_condition
        assert "l.et = 'PERSON'" in cond
        assert "r.et = 'PERSON'" in cond

    def test_no_wrapping_when_no_condition_on_signal(self):
        hn = NS(
            left="state", right="state", method="different",
            action="disqualify", penalty=0.0, sql=None,
            severity="hn2_structural", entity_type_condition=None,
            params={},
        )
        config = _make_config(entity_type_column="entity_type_class")
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert len(result) == 1
        cond = result[0].sql_condition
        assert "entity_type_class" not in cond

    def test_custom_condition_value_uppercased(self):
        """Unknown values get uppercased as-is."""
        hp = NS(
            left="x", right="x", method="exact",
            action="boost", boost=1.0, target_band="HIGH",
            sql=None, entity_type_condition="government", params={},
        )
        config = _make_config(entity_type_column="et")
        tier = _make_tier(hard_positives=[hp])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_positives(tier)

        assert "GOVERNMENT" in result[0].sql_condition


class TestEntityTypeMap:
    """Verify the friendly name → SQL value mapping."""

    def test_personal_maps_to_person(self):
        assert _ENTITY_TYPE_MAP["personal"] == "PERSON"

    def test_business_maps_to_business(self):
        assert _ENTITY_TYPE_MAP["business"] == "BUSINESS"

    def test_org_maps_to_organization(self):
        assert _ENTITY_TYPE_MAP["org"] == "ORGANIZATION"


# -- Severity-Aware Behavior Tests --

class TestSeverityAwareBehavior:
    """hn4_contextual should be forced to penalize, never disqualify."""

    def test_hn4_contextual_forced_to_penalize(self):
        hn = NS(
            left="geo_qualifier", right="geo_qualifier", method="different",
            action="disqualify", penalty=-3.0, sql=None,
            severity="hn4_contextual", entity_type_condition=None,
            params={}, requires_overrides=2,
        )
        config = _make_config()
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert len(result) == 1
        assert result[0].action == "penalize"

    def test_hn4_contextual_already_penalize_unchanged(self):
        hn = NS(
            left="x", right="x", method="different",
            action="penalize", penalty=-1.0, sql=None,
            severity="hn4_contextual", entity_type_condition=None,
            params={},
        )
        config = _make_config()
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert result[0].action == "penalize"

    def test_hn1_critical_disqualify_preserved(self):
        hn = NS(
            left="ssn", right="ssn", method="different",
            action="disqualify", penalty=0.0, sql=None,
            severity="hn1_critical", entity_type_condition=None,
            params={},
        )
        config = _make_config()
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert result[0].action == "disqualify"

    def test_hn2_structural_disqualify_preserved(self):
        hn = NS(
            left="is_hoa", method="exact",
            action="disqualify", penalty=0.0,
            sql="(l.is_hoa = 1 OR r.is_hoa = 1)",
            severity="hn2_structural", entity_type_condition=None,
            params={},
        )
        config = _make_config()
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert result[0].action == "disqualify"

    def test_default_severity_is_hn2(self):
        """When severity is hn2_structural (default), disqualify is preserved."""
        hn = NS(
            left="x", right="x", method="different",
            action="disqualify", penalty=0.0, sql=None,
            severity="hn2_structural", entity_type_condition=None,
            params={},
        )
        config = _make_config()
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert result[0].action == "disqualify"


# -- Global Signal Flow Tests --

class TestGlobalSignalFlow:
    """Verify global signals merge with tier signals in SQL generation."""

    def test_global_hard_negatives_appear_in_sql(self):
        global_hn = NS(
            left="gen_suffix", right="gen_suffix", method="different",
            action="disqualify", penalty=0.0, sql=None,
            severity="hn2_structural", entity_type_condition=None,
            params={},
        )
        tier_hn = NS(
            left="state", right="state", method="different",
            action="penalize", penalty=-2.0, sql=None,
            severity="hn3_identity", entity_type_condition=None,
            params={},
        )
        config = _make_config(global_hard_negatives=[global_hn])
        tier = _make_tier(hard_negatives=[tier_hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        # Global + tier = 2 hard negatives
        assert len(result) == 2
        assert result[0].sql_condition == "l.gen_suffix IS DISTINCT FROM r.gen_suffix"
        assert result[1].sql_condition == "l.state IS DISTINCT FROM r.state"

    def test_global_hard_positives_appear_in_sql(self):
        global_hp = NS(
            left="ssn", right="ssn", method="exact",
            action="boost", boost=10.0, target_band="HIGH",
            sql=None, entity_type_condition=None, params={},
        )
        config = _make_config(global_hard_positives=[global_hp])
        tier = _make_tier()
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_positives(tier)

        assert len(result) == 1
        assert result[0].boost == 10.0
        assert "l.ssn = r.ssn" in result[0].sql_condition

    def test_global_soft_signals_appear_in_sql(self):
        global_ss = NS(
            left="state", right="state", method="exact",
            bonus=0.5, sql=None,
            entity_type_condition=None, params={},
        )
        config = _make_config(global_soft_signals=[global_ss])
        tier = _make_tier()
        stage = MatchingStage(tier, 0, config)
        result = stage._build_soft_signals(tier)

        assert len(result) == 1
        assert result[0].bonus == 0.5

    def test_global_and_tier_signals_merge_in_plan(self):
        """End-to-end: global + tier signals produce valid scored SQL."""
        global_hn = NS(
            left="gen_suffix", right="gen_suffix", method="different",
            action="disqualify", penalty=0.0, sql=None,
            severity="hn2_structural", entity_type_condition=None,
            params={},
        )
        global_hp = NS(
            left="ssn", right="ssn", method="exact",
            action="boost", boost=10.0, target_band="HIGH",
            sql=None, entity_type_condition=None, params={},
        )
        config = _make_config(
            global_hard_negatives=[global_hn],
            global_hard_positives=[global_hp],
        )
        tier = _make_tier()
        stage = MatchingStage(tier, 0, config)
        exprs = stage.plan()

        sql = exprs[0].render()
        # Global hard negative in WHERE clause
        assert "NOT (l.gen_suffix IS DISTINCT FROM r.gen_suffix)" in sql
        # Global hard positive boost in scoring
        assert "l.ssn = r.ssn" in sql
        assert "10.0" in sql


# -- Combined Entity Type + Severity Tests --

class TestCombinedEntityTypeAndSeverity:
    """Tests combining entity_type_condition with severity behavior."""

    def test_hn3_identity_with_entity_type_and_disqualify(self):
        """hn3_identity + entity_type_condition wraps SQL."""
        hn = NS(
            left="gen_suffix", right="gen_suffix", method="different",
            action="disqualify", penalty=0.0, sql=None,
            severity="hn3_identity", entity_type_condition="personal",
            params={},
        )
        config = _make_config(entity_type_column="et_class")
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert len(result) == 1
        # Still disqualify (hn3 doesn't force penalize)
        assert result[0].action == "disqualify"
        # Entity type guard applied
        assert "l.et_class = 'PERSON'" in result[0].sql_condition
        assert "r.et_class = 'PERSON'" in result[0].sql_condition

    def test_hn4_with_entity_type_forced_to_penalize(self):
        """hn4_contextual + entity_type_condition: wraps AND forces penalize."""
        hn = NS(
            left="geo_qualifier", right="geo_qualifier", method="different",
            action="disqualify", penalty=-3.0, sql=None,
            severity="hn4_contextual", entity_type_condition="business",
            params={}, requires_overrides=1,
        )
        config = _make_config(entity_type_column="et")
        tier = _make_tier(hard_negatives=[hn])
        stage = MatchingStage(tier, 0, config)
        result = stage._build_hard_negatives(tier)

        assert result[0].action == "penalize"
        assert "l.et = 'BUSINESS'" in result[0].sql_condition

    def test_end_to_end_entity_type_in_scored_sql(self):
        """Entity type guard appears in final scored SQL."""
        hp = NS(
            left="ein", right="ein", method="exact",
            action="boost", boost=10.0, target_band="HIGH",
            sql=None, entity_type_condition="business", params={},
        )
        config = _make_config(
            entity_type_column="et_class",
            global_hard_positives=[hp],
        )
        tier = _make_tier()
        stage = MatchingStage(tier, 0, config)
        exprs = stage.plan()

        sql = exprs[0].render()
        assert "et_class = 'BUSINESS'" in sql
        assert "l.ein = r.ein" in sql


# -- TF Fields Helper Tests --

class TestTfFieldsHelper:
    """Tests for the shared _tf_fields() extraction."""

    def test_no_tf_adjustment(self):
        comp = NS(
            tf_enabled=False, tf_column="", tf_minimum_u=0.01,
            tf_adjustment=None, left="name",
        )
        fields = MatchingStage._tf_fields(comp)
        assert fields["tf_enabled"] is False
        assert fields["tf_column"] == "name"

    def test_with_tf_adjustment_config(self):
        tf_adj = NS(enabled=True, tf_adjustment_column="last_name", tf_minimum_u_value=0.005)
        comp = NS(
            tf_enabled=False, tf_column="", tf_minimum_u=0.01,
            tf_adjustment=tf_adj, left="name",
        )
        fields = MatchingStage._tf_fields(comp)
        assert fields["tf_enabled"] is True
        assert fields["tf_column"] == "last_name"
        assert fields["tf_minimum_u"] == 0.005
