"""Tests for centralized column naming constants."""

from bq_entity_resolution import columns


class TestCoreColumns:
    def test_entity_uid(self):
        assert columns.ENTITY_UID == "entity_uid"

    def test_cluster_id(self):
        assert columns.CLUSTER_ID == "cluster_id"

    def test_left_right_entity_uid(self):
        assert columns.LEFT_ENTITY_UID == "left_entity_uid"
        assert columns.RIGHT_ENTITY_UID == "right_entity_uid"

    def test_source_metadata(self):
        assert columns.SOURCE_NAME == "source_name"
        assert columns.SOURCE_UPDATED_AT == "source_updated_at"

    def test_pipeline_metadata(self):
        assert columns.PIPELINE_LOADED_AT == "pipeline_loaded_at"
        assert columns.PIPELINE_RUN_ID == "pipeline_run_id"

    def test_match_scoring(self):
        assert columns.MATCH_TOTAL_SCORE == "match_total_score"
        assert columns.MATCH_CONFIDENCE == "match_confidence"
        assert columns.MATCH_TIER_NAME == "match_tier_name"


class TestPrefixes:
    def test_prefix_constants(self):
        assert columns.PREFIX_SOURCE == "source_"
        assert columns.PREFIX_PIPELINE == "pipeline_"
        assert columns.PREFIX_FINGERPRINT == "fp_"
        assert columns.PREFIX_MATCH == "match_"
        assert columns.PREFIX_BLOCKING_KEY == "bk_"
        assert columns.PREFIX_TERM_FREQUENCY == "term_frequency_"


class TestDynamicColumnNames:
    def test_match_score_column(self):
        assert columns.match_score_column("email_exact") == "match_score_email_exact"

    def test_match_log_weight_column(self):
        assert columns.match_log_weight_column("name_jw") == "match_log_weight_name_jw"

    def test_fp_lsh_bucket_column(self):
        assert columns.fp_lsh_bucket_column(0) == "fp_lsh_bucket_0"
        assert columns.fp_lsh_bucket_column(3) == "fp_lsh_bucket_3"

    def test_blocking_key_column(self):
        assert columns.blocking_key_column("first_soundex") == "bk_first_soundex"

    def test_fingerprint_column(self):
        assert columns.fingerprint_column("policy_number") == "fp_policy_number"
