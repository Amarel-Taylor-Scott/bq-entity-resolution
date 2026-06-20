"""Tests for signal framework configuration models."""
from __future__ import annotations

from bq_entity_resolution.config.schema import (
    BlockingPathDef,
    ColumnMapping,
    ConfidenceShapingConfig,
    HardNegativeDef,
    HardPositiveDef,
    MatchingTierConfig,
    PipelineConfig,
    ProjectConfig,
    ScoreBandDef,
    ScoreBandingConfig,
    SoftSignalDef,
    SourceConfig,
    ThresholdConfig,
    TierBlockingConfig,
)


class TestHardPositiveDef:
    """Tests for HardPositiveDef configuration model."""
    def test_boost_action(self):
        hp = HardPositiveDef(
            left="email_clean", right="email_clean",
            method="exact", action="boost", boost=10.0,
        )
        assert hp.action == "boost" and hp.boost == 10.0 and hp.left == "email_clean"
    def test_auto_match_action(self):
        hp = HardPositiveDef(
            left="ssn_clean", right="ssn_clean",
            method="exact", action="auto_match",
        )
        assert hp.action == "auto_match"
    def test_elevate_band_action(self):
        hp = HardPositiveDef(
            left="email_clean", right="email_clean",
            method="exact", action="elevate_band",
            target_band="HIGH",
        )
        assert hp.action == "elevate_band" and hp.target_band == "HIGH"
    def test_default_values(self):
        hp = HardPositiveDef(left="col", method="exact")
        assert hp.right == "col" and hp.action == "boost" and hp.boost == 5.0
        assert hp.target_band == "HIGH" and hp.sql is None
        assert hp.entity_type_condition is None
        assert hp.category == "general" and hp.params == {}
    def test_with_sql_override(self):
        hp = HardPositiveDef(
            left="col", method="custom",
            sql="l.ssn = r.ssn AND l.ssn IS NOT NULL",
        )
        assert hp.sql == "l.ssn = r.ssn AND l.ssn IS NOT NULL"
    def test_with_entity_type_condition(self):
        hp = HardPositiveDef(
            left="email", method="exact",
            entity_type_condition="personal",
        )
        assert hp.entity_type_condition == "personal"
    def test_with_params(self):
        hp = HardPositiveDef(
            left="col", method="exact",
            params={"normalize": True},
        )
        assert hp.params == {"normalize": True}

class TestHardNegativeDef:
    """Tests for HardNegativeDef configuration model."""
    def test_hn1_critical(self):
        hn = HardNegativeDef(left="entity_uid", method="different", severity="hn1_critical")
        assert hn.severity == "hn1_critical" and hn.action == "disqualify"
    def test_hn2_structural(self):
        hn = HardNegativeDef(
            left="gen_suffix", right="gen_suffix",
            method="different", severity="hn2_structural",
        )
        assert hn.severity == "hn2_structural"
    def test_hn3_identity(self):
        hn = HardNegativeDef(
            left="entity_type", right="entity_type",
            method="different", severity="hn3_identity",
            entity_type_condition="personal",
        )
        assert hn.severity == "hn3_identity" and hn.entity_type_condition == "personal"
    def test_hn4_contextual(self):
        hn = HardNegativeDef(
            left="geo_qualifier", right="geo_qualifier",
            method="different", severity="hn4_contextual",
            requires_overrides=2,
        )
        assert hn.severity == "hn4_contextual" and hn.requires_overrides == 2
    def test_with_entity_type_condition(self):
        hn = HardNegativeDef(
            left="suffix", method="different",
            entity_type_condition="business",
        )
        assert hn.entity_type_condition == "business"
    def test_with_params_dict(self):
        hn = HardNegativeDef(
            left="col", method="custom",
            params={"max_diff": 3},
        )
        assert hn.params == {"max_diff": 3}
    def test_backward_compatibility_default_severity(self):
        hn = HardNegativeDef(left="gen_suffix", method="different", action="disqualify")
        assert hn.severity == "hn2_structural" and hn.action == "disqualify"
    def test_penalize_action_with_penalty(self):
        hn = HardNegativeDef(left="col", method="different", action="penalize", penalty=-3.0)
        assert hn.action == "penalize" and hn.penalty == -3.0
    def test_default_values(self):
        hn = HardNegativeDef(left="col", method="different")
        assert hn.right == "col" and hn.action == "disqualify" and hn.penalty == 0.0
        assert hn.severity == "hn2_structural" and hn.requires_overrides == 0 and hn.params == {}
    def test_with_sql_override(self):
        assert HardNegativeDef(left="col", method="custom", sql="l.t != r.t").sql == "l.t != r.t"
    def test_category_field(self):
        hn = HardNegativeDef(
            left="col", method="different",
            category="generational",
        )
        assert hn.category == "generational"

class TestSoftSignalDef:
    """Tests for SoftSignalDef configuration model."""
    def test_creation(self):
        ss = SoftSignalDef(left="zip5", right="zip5", method="exact", bonus=1.5)
        assert ss.left == "zip5" and ss.bonus == 1.5
    def test_with_entity_type_condition(self):
        ss = SoftSignalDef(
            left="col", method="exact",
            entity_type_condition="personal",
        )
        assert ss.entity_type_condition == "personal"
    def test_with_params(self):
        ss = SoftSignalDef(
            left="col", method="similar",
            params={"threshold": 0.8},
        )
        assert ss.params == {"threshold": 0.8}
    def test_defaults(self):
        ss = SoftSignalDef(left="col", method="exact")
        assert ss.right == "col" and ss.bonus == 1.0 and ss.sql is None and ss.category == "general"
    def test_with_sql_override(self):
        ss = SoftSignalDef(left="col", method="custom", sql="l.zip5 = r.zip5", bonus=0.5)
        assert ss.sql is not None and ss.bonus == 0.5

class TestScoreBandDef:
    """Tests for ScoreBandDef configuration model."""
    def test_creation(self):
        band = ScoreBandDef(name="HIGH", min_score=8.0, max_score=100.0)
        assert band.name == "HIGH" and band.action == "accept"
    def test_with_review_action(self):
        band = ScoreBandDef(
            name="MEDIUM", min_score=5.0,
            max_score=8.0, action="review",
        )
        assert band.action == "review"
    def test_with_reject_action(self):
        band = ScoreBandDef(
            name="LOW", min_score=0.0,
            max_score=3.0, action="reject",
        )
        assert band.action == "reject"
    def test_default_max_score(self):
        assert ScoreBandDef(name="TOP", min_score=10.0).max_score == 999999.0

class TestScoreBandingConfig:
    """Tests for ScoreBandingConfig."""
    def test_with_bands(self):
        config = ScoreBandingConfig(
            enabled=True,
            bands=[
                ScoreBandDef(name="HIGH", min_score=8.0),
                ScoreBandDef(
                    name="LOW", min_score=0.0,
                    max_score=5.0, action="reject",
                ),
            ],
        )
        assert config.enabled is True and len(config.bands) == 2
    def test_disabled_by_default(self):
        assert ScoreBandingConfig().enabled is False and ScoreBandingConfig().bands == []

class TestConfidenceShapingConfig:
    """Tests for ConfidenceShapingConfig."""
    def test_defaults(self):
        c = ConfidenceShapingConfig()
        assert not c.group_size_penalty
        assert c.group_size_threshold == 10 and not c.hub_node_detection
    def test_all_options_enabled(self):
        c = ConfidenceShapingConfig(
            group_size_penalty=True,
            group_size_threshold=5,
            group_size_penalty_rate=0.05,
            hub_node_detection=True,
            hub_degree_threshold=15,
        )
        assert c.group_size_penalty and c.group_size_threshold == 5 and c.hub_node_detection
    def test_only_group_size_penalty(self):
        c = ConfidenceShapingConfig(group_size_penalty=True, group_size_threshold=8)
        assert c.group_size_penalty and not c.hub_node_detection
    def test_only_hub_node_detection(self):
        c = ConfidenceShapingConfig(hub_node_detection=True, hub_degree_threshold=25)
        assert not c.group_size_penalty and c.hub_node_detection and c.hub_degree_threshold == 25

class TestMatchingTierWithSignals:
    """Tests for MatchingTierConfig with signals."""
    def _make_tier(self, **kwargs):
        defaults = dict(
            name="exact",
            blocking=TierBlockingConfig(
                paths=[BlockingPathDef(keys=["bk_email"])],
            ),
            comparisons=[],
            threshold=ThresholdConfig(min_score=5.0),
        )
        defaults.update(kwargs)
        return MatchingTierConfig(**defaults)
    def test_tier_with_hard_positives(self):
        tier = self._make_tier(hard_positives=[
            HardPositiveDef(
                left="ssn", method="exact",
                action="auto_match",
            ),
            HardPositiveDef(
                left="email", method="exact",
                action="boost", boost=3.0,
            ),
        ])
        assert len(tier.hard_positives) == 2 and tier.hard_positives[0].action == "auto_match"
    def test_tier_with_score_banding(self):
        tier = self._make_tier(score_banding=ScoreBandingConfig(
            enabled=True,
            bands=[
                ScoreBandDef(name="HIGH", min_score=8.0),
                ScoreBandDef(
                    name="LOW", min_score=0.0,
                    max_score=8.0,
                ),
            ],
        ))
        assert tier.score_banding.enabled is True and len(tier.score_banding.bands) == 2
    def test_tier_score_banding_disabled_by_default(self):
        assert not self._make_tier().score_banding.enabled
    def test_tier_hard_positives_empty_by_default(self):
        assert self._make_tier().hard_positives == []

class TestEffectiveHardPositives:
    """Tests for PipelineConfig.effective_hard_positives()."""
    def _make_config(self, global_hps=None, tier_hps=None):
        tier = MatchingTierConfig(
            name="exact",
            blocking=TierBlockingConfig(
                paths=[BlockingPathDef(keys=["bk_email"])],
            ),
            comparisons=[],
            threshold=ThresholdConfig(),
            hard_positives=tier_hps or [],
        )
        return PipelineConfig(
            project=ProjectConfig(
                name="test", bq_project="proj",
            ),
            sources=[SourceConfig(
                name="src", table="t",
                unique_key="id", updated_at="ts",
                columns=[ColumnMapping(name="c")],
            )],
            feature_engineering={
                "blocking_keys": [{
                    "name": "bk_email",
                    "function": "farm_fingerprint",
                    "inputs": ["c"],
                }],
            },
            matching_tiers=[tier],
            global_hard_positives=global_hps or [],
        )
    def test_combines_global_and_tier(self):
        config = self._make_config(
            global_hps=[HardPositiveDef(
                left="ssn", method="exact",
                action="auto_match",
            )],
            tier_hps=[HardPositiveDef(
                left="email", method="exact",
                action="boost", boost=3.0,
            )],
        )
        effective = config.effective_hard_positives(config.matching_tiers[0])
        assert len(effective) == 2 and effective[0].left == "ssn" and effective[1].left == "email"
    def test_global_only(self):
        config = self._make_config(global_hps=[HardPositiveDef(left="ssn", method="exact")])
        assert len(config.effective_hard_positives(config.matching_tiers[0])) == 1
    def test_tier_only(self):
        config = self._make_config(tier_hps=[HardPositiveDef(left="email", method="exact")])
        assert len(config.effective_hard_positives(config.matching_tiers[0])) == 1
    def test_empty(self):
        config = self._make_config()
        assert config.effective_hard_positives(config.matching_tiers[0]) == []

class TestBlockingPathDefBucketSizeLimit:
    """Tests for BlockingPathDef with bucket_size_limit."""
    def test_default_bucket_size_limit(self):
        assert BlockingPathDef(keys=["bk_email"]).bucket_size_limit == 10_000
    def test_custom_bucket_size_limit(self):
        assert BlockingPathDef(keys=["bk_email"], bucket_size_limit=1000).bucket_size_limit == 1000
    def test_default_candidate_limit(self):
        assert BlockingPathDef(keys=["bk_email"]).candidate_limit == 200
    def test_custom_candidate_limit(self):
        assert BlockingPathDef(keys=["bk_name"], candidate_limit=500).candidate_limit == 500
    def test_with_multiple_keys(self):
        path = BlockingPathDef(
            keys=["bk_zip", "bk_last_name"],
            bucket_size_limit=500, candidate_limit=100,
        )
        assert path.keys == ["bk_zip", "bk_last_name"] and path.bucket_size_limit == 500
    def test_lsh_min_bands_default(self):
        assert BlockingPathDef(keys=["lsh_bucket_0"]).lsh_min_bands == 1
